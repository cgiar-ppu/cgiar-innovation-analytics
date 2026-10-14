"""
Runtime policy — role-aware models, cost ceilings and chat limits.

One place that answers "what may the current caller do?" for the chat
runtime, the REST query endpoint, ``/api/config`` and the agent-options
builder:

- which models a role may pick (non-admins: the cheaper default only; admins:
  the full stage list) — enforced in ``switch_model``, ``retry_with_model``,
  resume and new clients, and reported by ``/api/config``;
- the per-question spend ceiling (SDK ``max_budget_usd``);
- the soft daily spend cap per user (admins exempt);
- the MVP test budget (SYN-2306): one deployment-wide USD budget over a test
  window, a per-chat-session cap, threshold log lines at 50/75/90 %, and a
  graceful stop at the cap or at the end of the window.

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


class MvpBudgetExhausted(PolicyError):
    """Global test budget used up (or the test window is closed)."""

    code = "test_budget"


class MvpPeriodClosed(MvpBudgetExhausted):
    code = "test_ended"


class SessionBudgetExceeded(PolicyError):
    code = "session_limit"


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


# ---------------------------------------------------------------------------
# MVP test budget (SYN-2306)
# ---------------------------------------------------------------------------
#
# Who is stopped:
#   * global test budget / window: every NON-admin caller. Admin spend still
#     COUNTS toward the budget, but admins are not stopped, so the team can
#     still diagnose, demo and export after the cap (documented choice; set
#     IA_TEST_BUDGET_USD=0 to switch the global cap off entirely).
#   * per-session cap: non-admins only (like the daily cap).
# All checks fail OPEN on a database error (logged): these are cost guards,
# not security boundaries, and a broken read must not take the tool down
# during a demo.

THRESHOLD_LOG_TAG = "IA_TEST_BUDGET_THRESHOLD"
EXHAUSTED_LOG_TAG = "IA_TEST_BUDGET_EXHAUSTED"


def session_budget_usd(role: Optional[str] = None) -> Optional[float]:
    """Per-chat-session cap for the role (None = exempt / disabled)."""
    r = role if role is not None else current_role()
    if r == "admin":
        return None
    value = _config.SESSION_BUDGET_USD
    return value if value and value > 0 else None


def test_budget_usd() -> Optional[float]:
    value = _config.TEST_BUDGET_USD
    return value if value and value > 0 else None


def _environment() -> str:
    try:
        from synapsis.routes.usage import _environment_label
        return _environment_label()
    except Exception:
        return _config.ENVIRONMENT_LABEL or "local"


async def test_budget_status(now: Optional[float] = None, *, check_alerts: bool = True) -> dict:
    """The ``test_budget`` block of ``/api/admin/usage``.

    ``{enabled, budget_usd, spent_usd, remaining_usd, pct, state, window,
    thresholds, alerts, session_budget_usd, voice, basis}`` where ``state`` is
    ``not_started`` | ``open`` | ``exhausted`` | ``ended`` | ``disabled``.
    With ``check_alerts`` the call also logs (once) any newly crossed
    threshold, so a monitor polling the endpoint and the log agree.
    """
    import time as _time
    from synapsis.database.budget import crossed_alerts, iso, spent_between, test_window

    now = now if now is not None else _time.time()
    budget = test_budget_usd()
    window = await test_window(now)
    spent = await spent_between(window["start"], window["end"])
    total = spent["total_usd"]
    if budget is None:
        state = "disabled"
    elif now < window["start"]:
        state = "not_started"
    elif now >= window["end"]:
        state = "ended"
    elif total >= budget:
        state = "exhausted"
    else:
        state = "open"
    pct = round(100.0 * total / budget, 2) if budget else None
    if check_alerts and budget is not None:
        await _log_crossed_thresholds(window, total, budget)
    return {
        "enabled": budget is not None,
        "budget_usd": budget,
        "spent_usd": round(total, 4),
        "remaining_usd": round(max(0.0, budget - total), 4) if budget is not None else None,
        "pct": pct,
        "state": state,
        "window": {
            "start": iso(window["start"]),
            "end": iso(window["end"]),
            "start_source": window["start_source"],
            "end_source": window["end_source"],
            "days_left": round(max(0.0, (window["end"] - now) / 86400.0), 1),
        },
        "thresholds": [round(t * 100) for t in _config.BUDGET_ALERT_THRESHOLDS],
        "alerts": await crossed_alerts(window["start"]) if budget is not None else [],
        "session_budget_usd": session_budget_usd("researcher"),
        "questions": spent["questions"],
        "voice": {
            "minutes": round(spent["voice_minutes"], 1),
            "usd": round(spent["voice_usd"], 4),
            "usd_per_minute": _config.VOICE_USD_PER_MINUTE,
        },
        "basis": (
            "Model cost as reported by the Claude Agent SDK per question (list "
            "prices) since the window start, plus voice minutes x usd_per_minute. "
            "Admin usage counts toward the budget; only non-admins are stopped."
        ),
    }


async def _log_crossed_thresholds(window: dict, spent: float, budget: float) -> None:
    """Emit ONE distinctive log line per crossed threshold per window."""
    from synapsis.database.budget import claim_alert, iso

    win = f"{iso(window['start'])[:10]}..{iso(window['end'])[:10]}"
    env = _environment()
    for fraction in [*_config.BUDGET_ALERT_THRESHOLDS, 1.0]:
        if spent < fraction * budget:
            break
        payload = {"fraction": fraction, "pct": round(fraction * 100), "spent_usd": round(spent, 2),
                   "budget_usd": budget}
        try:
            first = await claim_alert(window["start"], fraction, payload)
        except Exception:
            _config.logger.warning("Could not record budget alert %.2f", fraction, exc_info=True)
            continue
        if not first:
            continue
        tag = EXHAUSTED_LOG_TAG if fraction >= 1.0 else THRESHOLD_LOG_TAG
        _config.logger.warning(
            "%s pct=%d spent=%.2f budget=%.2f window=%s env=%s",
            tag, round(fraction * 100), spent, budget, win, env,
        )


async def check_test_budget_thresholds() -> None:
    """Called after each recorded question: log newly crossed thresholds.

    Never raises (the answer has already been delivered).
    """
    if test_budget_usd() is None:
        return
    try:
        await test_budget_status(check_alerts=True)
    except Exception:
        _config.logger.warning("Test budget threshold check failed", exc_info=True)


async def enforce_test_budget(role: Optional[str] = None) -> None:
    """Refuse a new question for non-admins when the test budget is used up
    or the test window is closed (graceful stop with a clear message)."""
    from synapsis.constants import (
        TEST_BUDGET_EXHAUSTED_ERROR,
        TEST_PERIOD_ENDED_ERROR,
        TEST_PERIOD_NOT_STARTED_ERROR,
    )

    if test_budget_usd() is None:
        return
    r = role if role is not None else current_role()
    try:
        status = await test_budget_status(check_alerts=True)
    except Exception:
        _config.logger.warning("Test budget check failed; allowing the turn", exc_info=True)
        return
    if is_admin(r):
        return
    contact = support_contact()
    state = status["state"]
    if state == "exhausted":
        raise MvpBudgetExhausted(TEST_BUDGET_EXHAUSTED_ERROR.format(contact=contact))
    if state == "ended":
        # The window end is exclusive (a bare IA_TEST_END date means the END of
        # that day), so the last open day is one second earlier.
        from datetime import datetime, timedelta
        raw_end = status["window"]["end"] or ""
        try:
            end = (datetime.fromisoformat(raw_end) - timedelta(seconds=1)).date().isoformat()
        except ValueError:
            end = raw_end[:10]
        raise MvpPeriodClosed(TEST_PERIOD_ENDED_ERROR.format(end=end, contact=contact))
    if state == "not_started":
        start = (status["window"]["start"] or "")[:10]
        raise MvpPeriodClosed(TEST_PERIOD_NOT_STARTED_ERROR.format(start=start, contact=contact))


async def enforce_session_budget(session_id: Optional[str], role: Optional[str] = None) -> None:
    """Refuse another question in a chat that already spent its cap
    (non-admins). A new chat (no id yet) always passes."""
    from synapsis.constants import SESSION_LIMIT_ERROR

    r = role if role is not None else current_role()
    cap = session_budget_usd(r)
    if cap is None or not session_id:
        return
    try:
        from synapsis.database.budget import spent_in_session
        spent = await spent_in_session(session_id)
    except Exception:
        _config.logger.warning("Session budget check failed for %s; allowing the turn", session_id, exc_info=True)
        return
    if spent >= cap:
        _config.logger.info("Session budget reached for %s: spent $%.4f >= $%.2f", session_id, spent, cap)
        raise SessionBudgetExceeded(SESSION_LIMIT_ERROR.format(limit=cap))


async def enforce_spend_limits(session_id: Optional[str] = None, user_id: Optional[str] = None,
                               role: Optional[str] = None) -> None:
    """All pre-question cost guards, cheapest refusal first: global test
    budget/window, then this chat's cap, then the caller's daily cap."""
    await enforce_test_budget(role)
    await enforce_session_budget(session_id, role)
    await enforce_daily_budget(user_id, role)


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
