"""
Synapsis configuration — environment variables, paths, and logging setup.

All configurable values are centralized here so other modules can import them
without duplicating env-var reads or path logic.
"""

import os
import sys
import logging
from pathlib import Path

from synapsis.constants import DEFAULT_MODEL, DEFAULT_FALLBACK_MODEL, SELECTABLE_MODELS


def _get_int_env(name: str, default: int) -> int:
    """Return the integer value of an environment variable, falling back to
    *default* when the variable is unset or contains a non-integer value."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger("synapsis_agent").warning(
            "Invalid integer value for %s=%r — using default %d", name, raw, default
        )
        return default

# ---------------------------------------------------------------------------
# Prevent "nested session" error when launched from within Claude Code
# ---------------------------------------------------------------------------
os.environ.pop("CLAUDECODE", None)

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

SYNAPSIS_PLATFORM: str = os.getenv(
    "SYNAPSIS_PLATFORM",
    "macos" if sys.platform == "darwin" else "linux",
)
IS_MACOS: bool = SYNAPSIS_PLATFORM == "macos"

# ---------------------------------------------------------------------------
# Safety hooks (disabled on macOS by default, enabled in Docker)
# ---------------------------------------------------------------------------

SAFETY_HOOKS_ENABLED: bool = (
    os.getenv("SYNAPSIS_SAFETY_HOOKS", "false" if IS_MACOS else "true").lower() == "true"
)

# ---------------------------------------------------------------------------
# Workspace & model settings
# ---------------------------------------------------------------------------

WORKSPACE: Path = Path(
    os.getenv(
        "SYNAPSIS_WORKSPACE",
        str(Path.home() / "workspace") if IS_MACOS else "/workspace",
    )
)
WORKSPACE.mkdir(parents=True, exist_ok=True)

# Project root — the directory containing app.py, synapsis/, .claude/, etc.
# Used for skill discovery (SKILL.md files live under .claude/skills/).
PROJECT_DIR: Path = Path(__file__).resolve().parent.parent

MAX_SESSIONS: int = _get_int_env("SYNAPSIS_MAX_SESSIONS", 10)

MODEL: str = os.getenv("SYNAPSIS_MODEL", DEFAULT_MODEL)
FALLBACK_MODEL: str = os.getenv("SYNAPSIS_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)
# Agent turns per question. 60 is the IA cost-policy default (was 200); the
# IA_MAX_TURNS name wins over the legacy SYNAPSIS_MAX_TURNS so a deploy that
# still passes SYNAPSIS_MAX_TURNS=200 can be tightened without editing it.
MAX_TURNS: int = _get_int_env("IA_MAX_TURNS", _get_int_env("SYNAPSIS_MAX_TURNS", 60))


def _get_float_env(name: str, default: float) -> float:
    """Return a non-negative float env var, falling back to *default*."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logging.getLogger("synapsis_agent").warning(
            "Invalid number for %s=%r — using default %s", name, raw, default
        )
        return default
    if value < 0:
        return default
    return value

# ---------------------------------------------------------------------------
# Available models — env-var-overridable allow-list for the model selector
# ---------------------------------------------------------------------------
#
# ``SYNAPSIS_AVAILABLE_MODELS`` is a comma-separated list of model IDs that a
# given deployment is allowed to expose in the chat model-selector pill. This
# lets dev/prod restrict the offered models (e.g. lock prod to Sonnet only)
# without code changes. The default exposes every curated model.
#
# AVAILABLE_MODELS  — the raw list of allowed IDs (order preserved).
# SELECTABLE_MODELS_FILTERED — the curated SELECTABLE_MODELS entries (id+label)
#   intersected with AVAILABLE_MODELS, preserving the curated order. This is
#   what the frontend renders via GET /api/config.

_DEFAULT_AVAILABLE_MODELS: str = ",".join(m["id"] for m in SELECTABLE_MODELS)

AVAILABLE_MODELS: list[str] = [
    m.strip()
    for m in os.getenv("SYNAPSIS_AVAILABLE_MODELS", _DEFAULT_AVAILABLE_MODELS).split(",")
    if m.strip()
]

SELECTABLE_MODELS_FILTERED: list[dict[str, str]] = [
    m for m in SELECTABLE_MODELS if m["id"] in AVAILABLE_MODELS
]

# Guard against a misconfigured allow-list that filters everything out — fall
# back to the full curated list so the UI is never left with zero models.
if not SELECTABLE_MODELS_FILTERED:
    logging.getLogger("synapsis_agent").warning(
        "SYNAPSIS_AVAILABLE_MODELS=%r matched none of the curated models; "
        "falling back to the full SELECTABLE_MODELS list.",
        os.getenv("SYNAPSIS_AVAILABLE_MODELS"),
    )
    SELECTABLE_MODELS_FILTERED = list(SELECTABLE_MODELS)
    AVAILABLE_MODELS = [m["id"] for m in SELECTABLE_MODELS]

# ---------------------------------------------------------------------------
# Role-aware model policy + cost ceilings (IA finalisation 2026-09-26)
# ---------------------------------------------------------------------------
#
# AVAILABLE_MODELS above is what the *deployment* allows. On top of that each
# role gets its own subset, so invited testers and CGIAR researchers can only
# pick the cheaper default model while admins keep the full stage list:
#
#   IA_RESEARCHER_MODELS  comma list, default "claude-sonnet-5"
#   IA_ADMIN_MODELS       comma list, default = every AVAILABLE_MODELS entry
#
# Both are intersected with AVAILABLE_MODELS (a role can never get a model the
# deployment does not expose). Every non-admin role (researcher, user,
# invited, ...) uses the researcher list. See synapsis/runtime_policy.py.


def _parse_model_list(raw: str | None, default: list[str]) -> list[str]:
    if raw is None or not raw.strip():
        return list(default)
    return [m.strip() for m in raw.split(",") if m.strip()]


RESEARCHER_MODELS: list[str] = [
    m for m in _parse_model_list(os.getenv("IA_RESEARCHER_MODELS"), [MODEL])
    if m in AVAILABLE_MODELS
] or [m for m in [MODEL] if m in AVAILABLE_MODELS] or AVAILABLE_MODELS[:1]

ADMIN_MODELS: list[str] = [
    m for m in _parse_model_list(os.getenv("IA_ADMIN_MODELS"), AVAILABLE_MODELS)
    if m in AVAILABLE_MODELS
] or list(AVAILABLE_MODELS)

# Per-question (per agent turn) spend ceiling, passed to the SDK as
# ``max_budget_usd``. 0 disables the ceiling for that role.
MAX_BUDGET_USD_RESEARCHER: float = _get_float_env("IA_MAX_BUDGET_USD_RESEARCHER", 1.00)
MAX_BUDGET_USD_ADMIN: float = _get_float_env("IA_MAX_BUDGET_USD_ADMIN", 5.00)

# The SDK/CLI counts the budget per live CLI process (cumulative over the
# questions it served), so a chat's process is recycled (resumed fresh on the
# next question, conversation kept) once it has spent more than this fraction
# of the per-question ceiling. Guarantees every question at least
# (1 - fraction) x ceiling of headroom and never more than the ceiling.
BUDGET_RECYCLE_FRACTION: float = min(
    max(_get_float_env("IA_BUDGET_RECYCLE_FRACTION", 0.5), 0.0), 1.0
)

# Soft daily cap per user (UTC day). Admins are exempt. 0 disables it.
DAILY_USER_BUDGET_USD: float = _get_float_env("IA_DAILY_USER_BUDGET_USD", 5.00)

# Who users are told to contact when they hit the daily cap (free text; empty
# = generic wording). Deliberately not hard-coded: set per deployment.
SUPPORT_CONTACT: str = os.getenv("IA_SUPPORT_CONTACT", "").strip()

# Stall watchdog: a streaming answer that produces no event for this many
# seconds is stopped with a friendly message (was an unused constant).
STALL_TIMEOUT_SECONDS: int = _get_int_env("IA_STALL_TIMEOUT_SECONDS", 300)

# New-chat rate limits: per user (sliding window) plus a deployment-wide
# safety net against reconnect storms.
NEW_CHATS_PER_USER: int = _get_int_env("IA_NEW_CHATS_PER_USER", 5)
NEW_CHATS_GLOBAL: int = _get_int_env("IA_NEW_CHATS_GLOBAL", 30)
NEW_CHATS_WINDOW_SECONDS: int = _get_int_env("IA_NEW_CHATS_WINDOW_SECONDS", 60)

# Label reported by the admin usage endpoint (each env has its own DB).
ENVIRONMENT_LABEL: str = os.getenv("IA_ENVIRONMENT", "").strip()

# ---------------------------------------------------------------------------
# Application version
# ---------------------------------------------------------------------------

APP_VERSION: str = "2.0.0"

# Optional Cognito SSO; all values are explicit per deployment, off by default.
SSO_ENABLED = os.getenv("IA_SSO_ENABLED", "false").lower() == "true"
PASSWORD_LOGIN_ENABLED = os.getenv("IA_PASSWORD_LOGIN_ENABLED", "true").lower() == "true"
INVITED_LOGIN_ENABLED = os.getenv("IA_INVITED_LOGIN_ENABLED", "false").lower() == "true"
SSO_ADMIN_SUBJECTS = tuple(s.strip() for s in os.getenv("IA_SSO_ADMIN_SUBJECTS", "").split(",") if s.strip())
SSO_ISSUER = os.getenv("IA_SSO_ISSUER", "").rstrip("/")
SSO_CLIENT_ID = os.getenv("IA_SSO_CLIENT_ID", "")
SSO_DOMAIN = os.getenv("IA_SSO_DOMAIN", "").rstrip("/")
SSO_ORIGIN = os.getenv("IA_SSO_ORIGIN", "").rstrip("/")
SSO_ALLOWED_DOMAINS = tuple(d.strip().lower() for d in os.getenv(
    "IA_SSO_ALLOWED_DOMAINS", "cgiar.org").split(",") if d.strip())

# ---------------------------------------------------------------------------
# Server settings
# ---------------------------------------------------------------------------

HOST: str = os.getenv("SYNAPSIS_HOST", "0.0.0.0")
PORT: int = _get_int_env("SYNAPSIS_PORT", 7777)
LOG_LEVEL: str = os.getenv("SYNAPSIS_LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Text-to-Speech settings
# ---------------------------------------------------------------------------

TTS_MODEL: str = os.getenv("SYNAPSIS_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE: str = os.getenv("SYNAPSIS_TTS_VOICE", "coral")
TTS_INSTRUCTIONS: str = os.getenv(
    "SYNAPSIS_TTS_INSTRUCTIONS",
    "Speak in a warm, conversational, and clear tone.",
)
TTS_SPEED: float = float(os.getenv("SYNAPSIS_TTS_SPEED", "1.0"))

# ---------------------------------------------------------------------------
# Database & audit paths
# ---------------------------------------------------------------------------

SYNAPSIS_DIR: Path = WORKSPACE / ".synapsis"
DB_PATH: Path = SYNAPSIS_DIR / "chat.db"
AUDIT_LOG: Path = SYNAPSIS_DIR / "audit.log"
SYNAPSIS_DB_TIMEOUT: int = int(os.getenv("SYNAPSIS_DB_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Authentication (Step 3 — app-level password login; identity abstraction that
# swaps cleanly to Cognito/Entra ID JWT `sub` later; see docs/AZURE-SSO-SETUP.md)
# ---------------------------------------------------------------------------

# JWT signing. The secret MUST be overridden in every deployed environment via
# IA_JWT_SECRET (wired as an SSM SecureString in deploy.yml). The default is for
# local dev only.
JWT_SECRET: str = os.getenv("IA_JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRY_HOURS: int = _get_int_env("IA_JWT_EXPIRY_HOURS", 24)

# Allow-list of issued-password users (email + bcrypt hash + role). Editing this
# JSON file adds/removes users with no code change. Path is env-overridable so
# the deployed container can mount it read-only from a secret store.
USERS_FILE: Path = Path(os.getenv("IA_USERS_FILE", str(PROJECT_DIR / "config" / "allowed_users.json")))

# Dev bypass: when true, auth is skipped and a dummy admin identity is returned.
# Defaults ON for local macOS runs (frictionless dev) and OFF everywhere else.
# The deployed dev URL sets IA_AUTH_DISABLED=false so login is actually enforced.
AUTH_DISABLED: bool = os.getenv(
    "IA_AUTH_DISABLED", "true" if IS_MACOS else "false"
).lower() in ("true", "1", "yes")

# Sentinel identity assigned to legacy (pre-auth) chat sessions during the
# idempotent user_id migration, and returned by the dev bypass.
LEGACY_USER_ID: str = "legacy@innovation-analytics"

# Interim self-signup (no email confirmation). Defaults OFF everywhere so the
# prod-lineage config stays closed unless a deployment explicitly opts in.
# deploy.yml sets IA_SELF_SIGNUP=true only for the dev stage's docker run.
SELF_SIGNUP_ENABLED: bool = os.getenv(
    "IA_SELF_SIGNUP", "false"
).lower() in ("true", "1", "yes")


def _parse_signup_allowed_domains(raw: str | None) -> list[str]:
    """Parse IA_SIGNUP_ALLOWED_DOMAINS into a normalized allow-list.

    Semantics (deliberately fail-CLOSED — see SIGNUP_ALLOWED_DOMAINS below):

    - unset, empty, or whitespace-only  -> the default ``["cgiar.org"]``.
      An accidentally-blank env var must never silently open signup to the
      whole internet, so blank falls back to the restrictive default.
    - ``"*"`` anywhere in the list      -> ``[]`` = restriction DISABLED
      (explicit, deliberate opt-out; the only way to allow any domain).
    - otherwise                         -> the comma-separated domains,
      lower-cased and stripped (a leading ``@`` is tolerated).

    Matching (see synapsis.auth.routes._signup_domain_allowed) is an EXACT,
    case-insensitive comparison of the part after ``@``. Subdomains do NOT
    match: ``x@mail.cgiar.org`` is rejected under the default. That is the
    simplest reading of the stated requirement ("a CG email" = ``@cgiar.org``);
    any additional domain (e.g. ``mail.cgiar.org``, centre domains like
    ``cimmyt.org``) must be listed explicitly.
    """
    if raw is None or not raw.strip():
        return ["cgiar.org"]
    parts = [p.strip().lstrip("@").lower() for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return ["cgiar.org"]
    if "*" in parts:
        return []
    return parts


# Self-signup email-domain allow-list. Jose's commitment to Marc Schut
# (2026-07-22): signup "is not allowed ... without a CG email". The interim
# self-signup endpoint previously accepted ANY address, so this makes the code
# match the stated policy. Empty list = no restriction (only reachable by
# setting IA_SIGNUP_ALLOWED_DOMAINS="*").
SIGNUP_ALLOWED_DOMAINS: list[str] = _parse_signup_allowed_domains(
    os.getenv("IA_SIGNUP_ALLOWED_DOMAINS")
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger: logging.Logger = logging.getLogger("synapsis_agent")

# ---------------------------------------------------------------------------
# Auth detection
# ---------------------------------------------------------------------------

_claude_config = Path.home() / ".claude"
_has_claude_config: bool = (
    _claude_config.exists() and any(_claude_config.iterdir())
)
_has_api_key: bool = bool(os.getenv("ANTHROPIC_API_KEY"))

AUTH_METHOD: str = (
    "subscription" if _has_claude_config
    else ("api_key" if _has_api_key else "none")
)

if _has_claude_config:
    logger.info("Auth: Using Claude Code subscription (mounted ~/.claude)")
elif _has_api_key:
    logger.info("Auth: Using ANTHROPIC_API_KEY environment variable")
else:
    logger.error("No authentication found. Mount ~/.claude or set ANTHROPIC_API_KEY.")
