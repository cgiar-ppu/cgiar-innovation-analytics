"""
End-user agent sandbox — PreToolUse hooks (review 2026-09-23 P0-2, L1-03, L3-02).

The IA agent answers questions for CGIAR staff and invited externals. It must
not be able to read secrets, other users' material or the server's databases,
and it must not reach internal network endpoints. Tool *availability* is cut
down in ``synapsis/agent_options.py`` (no Bash / Write / Edit / NotebookEdit,
IA-only MCP tools). These hooks are the second layer, applied to every tool
call of the orchestrator AND its sub-agents:

1. **Tool gate** — any tool that is not on the IA allow-list is denied, even if
   a future CLI version adds a new built-in.
2. **Path confinement** for ``Read`` / ``Glob`` / ``Grep`` — allowed only inside
   * the app's ``references/`` directory,
   * the caller's own upload and output areas (``synapsis.user_files``),
   * the CLI's own per-session folder (large tool results are spilled there and
     read back by the model).
   Everything else is denied, and hidden paths, ``/proc``, ``/sys``, ``/dev``,
   ``/etc``, ``/opt``, database files and env files are denied even inside an
   allowed root.
3. **WebFetch SSRF guard** — ``https`` only, default port, no credentials in the
   URL, no IP literals, no ``localhost`` / ``*.internal`` / metadata names, and
   every DNS answer must be a public (global) address.

The caller is bound when the options are built (``build_sandbox_hooks(owner)``),
from the connection's verified identity — never from model or user input.

Every hook fails CLOSED: an unexpected exception denies the call.

Residual risks (documented in the lane report): DNS rebinding between this
check and the CLI's own fetch (mitigate at infra: IMDSv2 + hop limit 1), and
the ``ANTHROPIC_API_KEY`` the CLI itself needs stays in its environment (the
agent can no longer read it: no shell, ``/proc`` denied, ``@file`` mentions off).
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import urlsplit

from claude_agent_sdk import HookContext, HookMatcher

from synapsis.config import logger

HookFn = Callable[[dict[str, Any], "str | None", HookContext], Awaitable[dict[str, Any]]]

#: Absolute prefixes the agent may never read, whatever the allow-list says.
DENIED_PREFIXES: tuple[str, ...] = ("/proc", "/sys", "/dev", "/etc", "/opt", "/root", "/var/run", "/run")

#: File suffixes that are never readable (databases, secrets).
DENIED_SUFFIXES: tuple[str, ...] = (
    ".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".db-journal",
    ".pem", ".key", ".p12", ".pfx",
)

#: Host names (or suffixes) that are never fetched.
DENIED_HOSTS: tuple[str, ...] = (
    "localhost", "metadata", "metadata.google.internal", "instance-data",
    "instance-data.ec2.internal",
)
DENIED_HOST_SUFFIXES: tuple[str, ...] = (
    ".localhost", ".local", ".internal", ".localdomain", ".home.arpa", ".lan", ".intranet",
)

DNS_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


ALLOW: dict[str, Any] = {}


def _fail_closed(name: str, fn: HookFn) -> HookFn:
    async def wrapper(input_data, tool_use_id, context):
        try:
            if input_data.get("hook_event_name", "PreToolUse") != "PreToolUse":
                return ALLOW
            return await fn(input_data, tool_use_id, context)
        except Exception as exc:  # noqa: BLE001 — fail closed on ANY error
            logger.warning("sandbox hook %s failed closed: %s", name, type(exc).__name__)
            return deny("Blocked by the Innovation Analytics sandbox (internal check failed).")

    wrapper.__name__ = f"sandbox_{name}"
    return wrapper


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _real(p: str | os.PathLike, base: str | os.PathLike | None = None) -> Path:
    path = Path(os.path.expanduser(str(p)))
    if not path.is_absolute():
        path = Path(base or os.getcwd()) / path
    return Path(os.path.realpath(path))


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def allowed_roots(owner_id: str | None) -> list[Path]:
    """The directories the caller's agent may read (besides its session folder)."""
    from synapsis import config
    from synapsis.user_files import owner_area

    return [
        _real(config.PROJECT_DIR / "references"),
        _real(owner_area("uploads", owner_id)),
        _real(owner_area("outputs", owner_id)),
    ]


def session_root(input_data: dict[str, Any] | None) -> Path | None:
    """The CLI's own per-session folder (``<projects>/<slug>/<session_id>/``).

    Oversized tool results are written there and read back with ``Read``, so
    the model must be able to read it — and nothing else under ``~/.claude``.
    """
    transcript = (input_data or {}).get("transcript_path")
    sid = str((input_data or {}).get("session_id") or "")
    if not transcript or not sid or "/" in sid or sid in (".", ".."):
        return None
    return _real(Path(transcript).parent / sid)


def path_denial(path: Path) -> str | None:
    """Reason a resolved path is never readable, or None."""
    s = str(path)
    for prefix in DENIED_PREFIXES:
        if s == prefix or s.startswith(prefix + "/"):
            return f"{prefix} is not readable"
    name = path.name.lower()
    if name.startswith(".env") or name.endswith(DENIED_SUFFIXES):
        return "database, key and environment files are not readable"
    return None


def check_read_path(raw: str | None, owner_id: str | None, input_data: dict[str, Any]) -> str | None:
    """Return a denial reason for reading *raw*, or None when allowed."""
    if not raw:
        return "a path is required"
    cwd = input_data.get("cwd")
    path = _real(raw, cwd)
    reason = path_denial(path)
    if reason:
        return reason
    sroot = session_root(input_data)
    if sroot is not None and _inside(path, sroot):
        return None
    for root in allowed_roots(owner_id):
        if _inside(path, root):
            if any(p.startswith(".") for p in path.relative_to(root).parts):
                return "hidden files are not readable"
            return None
    return (
        "outside the allowed areas — you may only read the app's references/ "
        "folder and this user's own uploaded or generated files"
    )


_GLOB_CHARS = set("*?[{")


def _static_prefix(pattern: str) -> str:
    parts = []
    for part in Path(pattern).parts:
        if any(c in part for c in _GLOB_CHARS):
            break
        parts.append(part)
    return str(Path(*parts)) if parts else "/"


def check_search(tool: str, tool_input: dict[str, Any], owner_id: str | None, input_data: dict[str, Any]) -> str | None:
    """Glob / Grep: the search root must be inside an allowed area."""
    pattern = str(tool_input.get("pattern") or "")
    extra_glob = str(tool_input.get("glob") or "")
    for p in (pattern if tool == "Glob" else "", extra_glob):
        if p and (".." in Path(p).parts):
            return "'..' is not allowed in search patterns"
        if p and tool == "Grep" and p.startswith(("/", "~")):
            return "absolute glob filters are not allowed"
    base = tool_input.get("path")
    if tool == "Glob" and pattern.startswith(("/", "~")):
        base = _static_prefix(os.path.expanduser(pattern))
    if not base:
        return (
            "give an explicit 'path' inside references/ or this user's own "
            "upload/output folder (searching the whole workspace is not allowed)"
        )
    return check_read_path(str(base), owner_id, input_data)


# ---------------------------------------------------------------------------
# WebFetch SSRF guard
# ---------------------------------------------------------------------------

def _ip_is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast and not ip.is_reserved


def static_url_denial(url: str) -> tuple[str | None, str | None]:
    """Checks that need no DNS. Returns (reason, hostname)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "not a valid URL", None
    if parts.scheme.lower() != "https":
        return "only https:// URLs may be fetched", None
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "URLs with credentials are not allowed", None
    try:
        port = parts.port
    except ValueError:
        return "invalid port", None
    if port not in (None, 443):
        return "only the default https port is allowed", None
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return "the URL has no host", None
    try:
        ipaddress.ip_address(host)
        return "IP-address URLs are not allowed; use a public host name", None
    except ValueError:
        pass
    if host in DENIED_HOSTS or host.endswith(DENIED_HOST_SUFFIXES) or "." not in host:
        return "internal host names are not allowed", None
    if not all(c.isalnum() or c in "-." for c in host):
        return "invalid host name", None
    return None, host


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout=DNS_TIMEOUT_SECONDS
    )
    return sorted({info[4][0] for info in infos})


async def check_fetch_url(url: str | None, resolver: Callable[[str], Awaitable[Iterable[str]]] | None = None) -> str | None:
    """Return a denial reason for fetching *url*, or None when allowed."""
    if not url:
        return "a URL is required"
    reason, host = static_url_denial(url)
    if reason:
        return reason
    try:
        addrs = list(await (resolver or _resolve)(host))
    except Exception:  # noqa: BLE001 — unresolvable = not fetched
        return "the host name could not be resolved"
    if not addrs:
        return "the host name could not be resolved"
    for addr in addrs:
        try:
            if not _ip_is_public(addr):
                return "the host resolves to a private or internal address"
        except ValueError:
            return "the host resolved to an invalid address"
    return None


# ---------------------------------------------------------------------------
# Hook factory
# ---------------------------------------------------------------------------

def build_sandbox_hooks(owner_id: str | None, allowed_tools: Iterable[str]) -> list[HookMatcher]:
    """PreToolUse matchers for one agent client, bound to its owner."""
    allowed = frozenset(allowed_tools)

    async def tool_gate(input_data, tool_use_id, context):
        name = str(input_data.get("tool_name") or "")
        if name not in allowed:
            logger.warning("sandbox: blocked tool %s", name[:80])
            return deny(f"The tool '{name}' is not available in Innovation Analytics.")
        return ALLOW

    async def path_guard(input_data, tool_use_id, context):
        name = str(input_data.get("tool_name") or "")
        tool_input = input_data.get("tool_input") or {}
        if name == "Read":
            reason = check_read_path(tool_input.get("file_path"), owner_id, input_data)
        elif name in ("Glob", "Grep"):
            reason = check_search(name, tool_input, owner_id, input_data)
        else:
            return ALLOW
        if reason:
            logger.info("sandbox: denied %s (%s)", name, reason)
            return deny(f"{name} blocked: {reason}.")
        return ALLOW

    async def fetch_guard(input_data, tool_use_id, context):
        tool_input = input_data.get("tool_input") or {}
        reason = await check_fetch_url(tool_input.get("url"))
        if reason:
            logger.info("sandbox: denied WebFetch (%s)", reason)
            return deny(f"WebFetch blocked: {reason}.")
        return ALLOW

    return [
        HookMatcher(hooks=[_fail_closed("tool_gate", tool_gate)]),
        HookMatcher(matcher="Read|Glob|Grep", hooks=[_fail_closed("path_guard", path_guard)]),
        HookMatcher(matcher="WebFetch", hooks=[_fail_closed("fetch_guard", fetch_guard)]),
    ]
