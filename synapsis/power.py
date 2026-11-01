"""Env-power busy + activity signal (AWS cost sprint, Nov 2026).

The env-power controller may stop this server's EC2 instance after 60 min with
no real use. It must never stop it while work is in flight -- including
workflow pipelines that run detached from the WebSocket -- and neither an open
but idle tab nor internet scanners may count as use. (This app serves its SPA
for any path, so scanners get 200s and the load-balancer counts are useless as
a usage signal.)

Every ``ENV_POWER_PUBLISH_SECONDS`` (60 s) the app writes ONE raw JSON line to
stdout, which the container's awslogs driver ships to ``/cgiar-ia/<stage>``:

    {"env_power": 1, "env": "cgiar-ia-dev", "busy": 0, "activity": 3, "ts": 1793500000}

The controller reads it (CloudWatch Logs filter ``{ $.env_power = 1 }``, or a
metric filter). No AWS credentials or SDK needed in the app.

- ``busy``: PEAK in the interval (10-s samples) of running chat turns +
  running workflow pipelines + live voice sessions. A finished chat whose
  socket stays open is not busy.
- ``activity``: user actions in the interval: ``/api/*`` responses < 400
  (excluding health checks, the SSO session refresh and the voice-status
  re-check, which background tabs used to send) plus chat WebSocket frames
  received, plus a deploy's hold keep-alive (``X-Env-Power-Hold`` header).

Off: ``ENV_POWER_SIGNAL=off``. Never raises into the app.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import suppress
from typing import Any, Awaitable, Callable

logger = logging.getLogger("synapsis.power")

PUBLISH_SECONDS = float(os.getenv("ENV_POWER_PUBLISH_SECONDS", "60"))
SAMPLE_SECONDS = float(os.getenv("ENV_POWER_SAMPLE_SECONDS", "10"))
HOLD_HEADER = b"x-env-power-hold"
# Background/automatic calls that must never count as use: exact paths and path prefixes.
EXCLUDED_PATHS = ("/api/health", "/api/voice/status")
EXCLUDED_PREFIXES = ("/api/auth/",)

_activity = 0


def enabled() -> bool:
    if os.getenv("ENV_POWER_SIGNAL", "on").strip().lower() in ("off", "false", "0", "no"):
        return False
    return bool(env_name())


def env_name() -> str:
    explicit = os.getenv("ENV_POWER_ENV", "").strip()
    if explicit:
        return explicit
    stage = os.getenv("IA_ENVIRONMENT", "").strip()
    return f"cgiar-ia-{stage}" if stage else ""


# --- busy -----------------------------------------------------------------
def chat_busy() -> int:
    from synapsis.chat_run_manager import chat_run_manager

    return sum(1 for h in list(chat_run_manager._handles.values()) if getattr(h, "status", "") == "running")


def pipelines_busy() -> int:
    from synapsis.workflow_run_manager import run_manager

    return sum(1 for h in list(run_manager._active_runs.values()) if getattr(h, "status", "") == "running")


async def voice_busy() -> int:
    from synapsis.database import get_db

    now = time.time()
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT COUNT(*) FROM voice_sessions WHERE status IN ('creating','active') AND expires>? AND heartbeat>?",
            (now, now))).fetchone()
    return int(row[0]) if row else 0


async def busy_units() -> int:
    total = 0
    for fn in (chat_busy, pipelines_busy):
        with suppress(Exception):
            total += fn()
    with suppress(Exception):
        total += await voice_busy()
    return total


# --- activity -------------------------------------------------------------
def record_activity(n: int = 1) -> None:
    global _activity
    _activity += n


def take_activity() -> int:
    global _activity
    n, _activity = _activity, 0
    return n


def counts_http(method: str, path: str, headers: list | None = None) -> bool:
    if method in ("OPTIONS", "HEAD"):
        return False
    if any(k == HOLD_HEADER for k, _ in (headers or [])):
        return True
    if not path.startswith("/api/"):
        return False
    if path in EXCLUDED_PATHS or path.startswith(EXCLUDED_PREFIXES):
        return False
    return True


class ActivityMiddleware:
    """Counts user actions. Pure ASGI; never alters requests or responses."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        kind = scope.get("type")
        if kind == "http" and counts_http(scope.get("method", ""), scope.get("path", ""), scope.get("headers")):
            async def send_counting(message: dict) -> None:
                if message.get("type") == "http.response.start" and int(message.get("status", 500)) < 400:
                    record_activity()
                await send(message)
            await self.app(scope, receive, send_counting)
            return
        if kind == "websocket" and scope.get("path", "").startswith("/ws/"):
            async def receive_counting() -> dict:
                message = await receive()
                if message.get("type") == "websocket.receive":
                    record_activity()
                return message
            await self.app(scope, receive_counting, send)
            return
        await self.app(scope, receive, send)


# --- publisher ------------------------------------------------------------
def signal_line(busy: int, activity: int, env: str | None = None) -> str:
    return json.dumps({"env_power": 1, "env": env or env_name(), "busy": int(busy),
                       "activity": int(activity), "ts": int(time.time())}, separators=(",", ":"))


def _stdout(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def run_publisher(
    emit: Callable[[str], None] = _stdout,
    sample: Callable[[], Awaitable[int]] = busy_units,
    publish_seconds: float | None = None,
    sample_seconds: float | None = None,
    max_publishes: int | None = None,
) -> None:
    publish_s = PUBLISH_SECONDS if publish_seconds is None else publish_seconds
    sample_s = SAMPLE_SECONDS if sample_seconds is None else sample_seconds
    published = 0
    while max_publishes is None or published < max_publishes:
        peak, deadline = 0, time.monotonic() + publish_s
        while True:
            with suppress(Exception):
                peak = max(peak, await sample())
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(sample_s, remaining))
        with suppress(Exception):
            emit(signal_line(peak, take_activity()))
        published += 1


_task: asyncio.Task | None = None


def start() -> None:
    global _task
    if not enabled():
        logger.info("ENV_POWER signal: off")
        return
    logger.info("ENV_POWER signal: env=%s every %.0fs (stdout JSON line)", env_name(), PUBLISH_SECONDS)
    _task = asyncio.get_event_loop().create_task(run_publisher(), name="env-power-signal")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await _task
    _task = None
