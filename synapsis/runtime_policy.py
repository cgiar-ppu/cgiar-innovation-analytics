"""
Runtime policy — role-aware models, cost ceilings and chat limits.

One place that answers "what may the current caller do?" for the chat
runtime, the REST query endpoint, ``/api/config`` and the agent-options
builder:

- which models a role may pick (non-admins: the cheaper default only; admins:
  the full stage list) — enforced in ``switch_model``, ``retry_with_model``,
  resume and new clients, and reported by ``/api/config``;
- the per-question spend ceiling (SDK ``max_budget_usd``);
- the soft daily spend cap per user (admins exempt).

The caller's identity comes from the per-connection context
(``synapsis.auth.context``) that ``ws_chat`` / ``/api/query`` set from the
verified JWT. In dev-bypass mode (``IA_AUTH_DISABLED``) everyone is treated as
admin, matching the dummy admin identity the bypass hands out.

Values live in ``synapsis.config`` and are read at call time (module
attribute access) so tests and operators can change them without re-imports.
"""

from __future__ import annotations

from typing import Optional

import synapsis.config as _config
from synapsis.constants import SELECTABLE_MODELS


class PolicyError(Exception):
    """A request the runtime policy refuses. ``code`` goes to the client."""

    code = "policy"

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.user_message = message
        if code:
            self.code = code


class SessionLimitError(PolicyError, RuntimeError):
    """New-chat rate limit or concurrent-session capacity reached.

    Subclasses RuntimeError for backward compatibility with callers that
    caught the old bare RuntimeError.
    """

    code = "rate_limited"


class ModelNotAllowedError(PolicyError):
    code = "model_not_allowed"


class DailyBudgetExceeded(PolicyError):
    code = "daily_limit"


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

def current_role() -> str:
    """Role of the current caller ("admin" in dev-bypass mode)."""
    if _config.AUTH_DISABLED:
        return "admin"
    from synapsis.auth.context import get_current_role
    return get_current_role() or "user"


def current_user_id() -> str:
    from synapsis.auth.context import get_current_user_id
    return get_current_user_id()


def is_admin(role: Optional[str] = None) -> bool:
    return (role if role is not None else current_role()) == "admin"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def allowed_models_for_role(role: Optional[str]) -> list[str]:
    """Model ids a role may use, in curated order.

    ``role=None`` means an anonymous caller (public ``/api/config``): only the
    deployment default model is reported.
    """
    if role is None:
        return [_config.MODEL] if _config.MODEL in _config.AVAILABLE_MODELS else _config.AVAILABLE_MODELS[:1]
    ids = _config.ADMIN_MODELS if role == "admin" else _config.RESEARCHER_MODELS
    return [m for m in _config.AVAILABLE_MODELS if m in ids]


def selectable_models_for_role(role: Optional[str]) -> list[dict[str, str]]:
    """Curated ``{id, label}`` entries for the role (shape of /api/config)."""
    allowed = set(allowed_models_for_role(role))
    entries = [m for m in SELECTABLE_MODELS if m["id"] in allowed]
    return entries or [m for m in _config.SELECTABLE_MODELS_FILTERED if m["id"] == _config.MODEL]


def is_model_allowed(model: Optional[str], role: Optional[str] = None) -> bool:
    if not model:
        return False
    r = role if role is not None else current_role()
    return model in allowed_models_for_role(r)


def default_model_for_role(role: Optional[str] = None) -> str:
    r = role if role is not None else current_role()
    allowed = allowed_models_for_role(r)
    if _config.MODEL in allowed:
        return _config.MODEL
    return allowed[0] if allowed else _config.MODEL


def resolve_model(requested: Optional[str], role: Optional[str] = None) -> Optional[str]:
    """Model a (re)created client should run for this role.

    Returns ``requested`` when allowed, otherwise ``None`` (= server default)
    when the default is allowed, otherwise the role's first allowed model.
    Used on resume so a chat created on Opus before the policy existed quietly
    continues on the role's default instead of bypassing the policy.
    """
    r = role if role is not None else current_role()
    if requested and is_model_allowed(requested, r):
        return requested
    default = default_model_for_role(r)
    return None if default == _config.MODEL else default


def fallback_model_for_role(role: Optional[str] = None) -> str:
    """The AUP/overload fallback model for this role, or "" when none.

    Non-admins only get a fallback if it is in their allowed list (by default
    it is not: Sonnet-only), so a refusal is reported instead of silently
    escalating to a more expensive model.
    """
    r = role if role is not None else current_role()
    fb = _config.FALLBACK_MODEL
    return fb if fb and is_model_allowed(fb, r) else ""


def sdk_fallback_model(model: Optional[str], role: Optional[str] = None) -> Optional[str]:
    """``ClaudeAgentOptions.fallback_model`` value (None disables it).

    The CLI rejects a fallback equal to the main model, so that case is
    disabled too.
    """
    fb = fallback_model_for_role(role)
    main = model or _config.MODEL
    return fb if fb and fb != main else None


# ---------------------------------------------------------------------------
# Cost ceilings
# ---------------------------------------------------------------------------

def turn_budget_usd(role: Optional[str] = None) -> Optional[float]:
    """Per-question spend ceiling for the role (None = no ceiling)."""
    r = role if role is not None else current_role()
    value = _config.MAX_BUDGET_USD_ADMIN if r == "admin" else _config.MAX_BUDGET_USD_RESEARCHER
    return value if value and value > 0 else None


def daily_budget_usd(role: Optional[str] = None) -> Optional[float]:
    """Daily soft cap for the role (None = exempt / disabled)."""
    r = role if role is not None else current_role()
    if r == "admin":
        return None
    value = _config.DAILY_USER_BUDGET_USD
    return value if value and value > 0 else None


def support_contact() -> str:
    return _config.SUPPORT_CONTACT or "the Innovation Analytics team"


async def enforce_daily_budget(user_id: Optional[str] = None, role: Optional[str] = None) -> None:
    """Raise :class:`DailyBudgetExceeded` if the caller spent today's cap.

    Fail-open: if spend cannot be read (DB error), the turn is allowed and the
    problem is logged — this is a soft cap, not a security boundary.
    """
    from synapsis.constants import DAILY_LIMIT_ERROR

    r = role if role is not None else current_role()
    cap = daily_budget_usd(r)
    if cap is None:
        return
    uid = user_id or current_user_id()
    try:
        from synapsis.database.usage import spent_today_usd
        spent = await spent_today_usd(uid)
    except Exception:
        _config.logger.warning("Daily budget check failed for %s; allowing the turn", uid, exc_info=True)
        return
    if spent >= cap:
        _config.logger.info("Daily budget reached for %s: spent $%.4f >= $%.2f", uid, spent, cap)
        raise DailyBudgetExceeded(DAILY_LIMIT_ERROR.format(limit=cap, contact=support_contact()))


def policy_summary(role: Optional[str]) -> dict:
    """The ``model_policy`` block of ``/api/config`` (see D-REPORT contract)."""
    return {
        "role": role or "anonymous",
        "default_model": default_model_for_role(role) if role else _config.MODEL,
        "allowed_models": allowed_models_for_role(role),
        "max_budget_usd_per_turn": turn_budget_usd(role) if role else None,
        "daily_budget_usd": daily_budget_usd(role) if role else None,
        "max_turns": _config.MAX_TURNS,
        "show_cost": role == "admin",
    }
