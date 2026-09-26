"""
HTTP hardening for the IA app (review 2026-09-23 L1-07 / L1-08 / L4-11 / L4-12).

* ``cors_settings()`` — CORS restricted to the environment's own origin(s)
  instead of ``*`` + credentials. ``CORS_ORIGINS`` (comma-separated) overrides;
  otherwise the deployment's public origin (``IA_SSO_ORIGIN``, set on every
  hosted env) is used; with neither, no cross-origin browser access is granted
  (the SPA is same-origin and needs none).
* ``SecurityHeadersMiddleware`` — pure ASGI (safe for streaming and never
  touches WebSockets) adding HSTS, ``nosniff``, ``Referrer-Policy``,
  ``X-Frame-Options: DENY`` + ``frame-ancestors 'none'``, a ``Permissions-Policy``
  that still allows the microphone for the voice guide, and a
  Content-Security-Policy in **Report-Only** mode by default (``IA_CSP_MODE`` =
  ``report-only`` | ``enforce`` | ``off``). The policy is tuned for the built SPA:
  same-origin scripts, recharts' inline styles, Google Fonts, data/blob images,
  the same-origin chat WebSocket, blob/srcdoc iframes for interactive answers,
  and voice (the SDP exchange goes through our API; WebRTC media is not
  governed by ``connect-src``). SSO (Cognito/Entra) is a top-level redirect,
  which CSP does not restrict.
  A response that already sets its own CSP (e.g. inline images from
  ``/api/files``) keeps it.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def cors_origins(environ: dict | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    raw = (env.get("CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    sso_origin = (env.get("IA_SSO_ORIGIN") or "").strip().rstrip("/")
    return [sso_origin] if sso_origin else []


def cors_settings(environ: dict | None = None) -> dict:
    """Keyword arguments for Starlette's CORSMiddleware."""
    origins = cors_origins(environ)
    wildcard = "*" in origins
    return {
        "allow_origins": origins,
        # Never combine a wildcard with credentials (Starlette would reflect any
        # Origin). The API authenticates with a Bearer header anyway.
        "allow_credentials": bool(origins) and not wildcard,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type"],
        "max_age": 600,
    }


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

def _ws_origin(origin: str) -> str:
    parts = urlsplit(origin)
    if not parts.netloc:
        return ""
    return ("wss://" if parts.scheme == "https" else "ws://") + parts.netloc


def content_security_policy(environ: dict | None = None) -> str:
    env = os.environ if environ is None else environ
    override = (env.get("IA_CSP_POLICY") or "").strip()
    if override:
        return override
    connect = ["'self'"]
    for origin in cors_origins(env):
        if origin != "*":
            ws = _ws_origin(origin)
            if ws:
                connect.append(ws)
    directives = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        "media-src 'self' blob: mediastream:",
        "connect-src " + " ".join(dict.fromkeys(connect)),
        "frame-src 'self' blob: data:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
    return "; ".join(directives)


def static_security_headers(environ: dict | None = None) -> list[tuple[str, str]]:
    env = os.environ if environ is None else environ
    headers = [
        ("strict-transport-security", "max-age=31536000; includeSubDomains"),
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("x-frame-options", "DENY"),
        ("permissions-policy", "microphone=(self), camera=(), geolocation=(), payment=(), usb=()"),
    ]
    mode = (env.get("IA_CSP_MODE") or "report-only").strip().lower()
    policy = content_security_policy(env)
    if mode == "enforce":
        headers.append(("content-security-policy", policy))
    elif mode != "off":
        headers.append(("content-security-policy-report-only", policy))
        # frame-ancestors is ignored in Report-Only; enforce just that part.
        headers.append(("content-security-policy", "frame-ancestors 'none'"))
    return headers


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware adding the security headers to HTTP responses."""

    def __init__(self, app: ASGIApp, environ: dict | None = None) -> None:
        self.app = app
        self.headers = static_security_headers(environ)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers:
                    if name not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
