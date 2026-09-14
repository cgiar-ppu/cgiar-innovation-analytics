"""Cached, non-blocking probe of the voice provider credential and model.

``configured`` only proves the key is a non-empty string; on 2026-09-14 a dead
key produced a clickable voice button that could only 503. ``provider_ok``
asks the provider whether the configured key can see the configured model.

- Never raises; a failed probe (HTTP error, timeout, network) is cached too,
  so a broken provider cannot turn every status call into a 5 s stall.
- One in-flight probe at a time; concurrent status calls share the result.
- Logs a structured warning on failure with the HTTP status, never the key.
"""
import asyncio
import os
import time

import httpx
from synapsis.config import logger
from .config import model

CACHE_SECONDS = 600
TIMEOUT_SECONDS = 5
_cache: dict = {'ok': None, 'checked': 0.0, 'status': None}
_lock: asyncio.Lock | None = None
_transport = None  # tests may inject an httpx.MockTransport


def configured() -> bool:
    return bool(os.getenv('OPENAI_API_KEY'))


def invalidate():
    """Force the next status call to re-probe (e.g. after the provider rejected a create)."""
    _cache.update(ok=None, checked=0.0, status=None)


def snapshot() -> dict:
    return {'provider_ok': _cache['ok'], 'provider_status': _cache['status'], 'checked_at': _cache['checked'] or None}


async def _probe() -> tuple[bool, int | None]:
    key = os.getenv('OPENAI_API_KEY', '')
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=_transport) as client:
        response = await client.get('https://api.openai.com/v1/models/' + model(), headers={'Authorization': 'Bearer ' + key})
    return response.is_success, response.status_code


async def provider_ok() -> bool | None:
    """True/False from a probe at most CACHE_SECONDS old; None when no key is configured."""
    global _lock
    if not configured():
        return None
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if _cache['ok'] is not None and time.time() - _cache['checked'] < CACHE_SECONDS:
            return _cache['ok']
        status = None
        try:
            ok, status = await _probe()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            ok = False
            logger.warning('voice_provider_probe_failed model=%s error=%s', model(), type(exc).__name__)
        if ok:
            logger.info('voice_provider_probe_ok model=%s provider_status=%s', model(), status)
        elif status is not None:
            logger.warning('voice_provider_probe_failed model=%s provider_status=%s', model(), status)
        _cache.update(ok=ok, checked=time.time(), status=status)
        return ok
