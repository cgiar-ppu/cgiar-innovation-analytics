"""
Active data scope — user-set filters that CONSTRAIN THE AGENT, not just a chart.

Marc Schut's July-7 ask #6 ("year + program/accelerator filters") is explicitly
about the agent: the filters must narrow what the agent queries and answers,
and the answer must SAY which slice it is talking about. A dashboard-only
filter would not close it.

Design
------
The system prompt is global: ``synapsis.agent_options._write_system_prompt_file``
writes ONE shared file (``/tmp/cgiar-ia-system-prompt.txt``) passed to every SDK
subprocess via ``--system-prompt-file``. Injecting a per-user scope there would
let concurrent sessions clobber each other's scope — a correctness AND a
confidentiality hazard. So the scope is injected **per message**, server-side,
as a delimited preamble prepended to the user's text at the chat entry point
(``synapsis.handlers.chat_handlers.handle_user_message``). That reuses the seam
the existing ``<workflow_context>`` prepend already established.

The user's own message is persisted to the DB unmodified; only the copy handed
to the SDK carries the preamble. The frontend shows the active scope on its own,
so nothing is hidden from the user.

Counting discipline
-------------------
The preamble instructs the agent to keep obeying ``references/prms_data_guide.md``
(the dedup CTE, the type-7 default, the stated-method/snapshot rule) and to state
the active scope in every answer, so a scoped number can never be mistaken for a
portfolio total.
"""

from __future__ import annotations

from typing import Any

# Reporting years PRMS actually covers in this snapshot (matches the
# `_VALID_YEARS` set the PRMS dashboard route validates against).
VALID_YEARS: tuple[int, ...] = (2022, 2023, 2024, 2025)

#: Defensive caps — a scope is a UI filter, not a bulk query channel.
MAX_YEARS = len(VALID_YEARS)
MAX_PROGRAMS = 30
MAX_PROGRAM_LABEL_LEN = 120


class ScopeValidationError(ValueError):
    """Raised when a client sends a structurally invalid scope object."""


def normalize_scope(raw: Any) -> dict[str, list]:
    """Validate and normalize a raw client scope object.

    Accepts ``None``, ``{}``, or ``{"years": [...], "programs": [...]}``.
    Returns a dict with the two keys always present (possibly empty lists).
    Unknown keys are ignored rather than rejected, so an older/newer frontend
    never breaks the chat path.

    Raises:
        ScopeValidationError: if the payload is not an object, if the values are
            not lists, if a year is not one of :data:`VALID_YEARS`, if a program
            entry is not a non-empty string, or if the caps are exceeded.
    """
    if raw is None:
        return {"years": [], "programs": []}
    if not isinstance(raw, dict):
        raise ScopeValidationError("scope must be an object")

    years_raw = raw.get("years") or []
    programs_raw = raw.get("programs") or []

    if not isinstance(years_raw, list) or not isinstance(programs_raw, list):
        raise ScopeValidationError("scope.years and scope.programs must be lists")
    if len(years_raw) > MAX_YEARS:
        raise ScopeValidationError(f"scope.years accepts at most {MAX_YEARS} entries")
    if len(programs_raw) > MAX_PROGRAMS:
        raise ScopeValidationError(
            f"scope.programs accepts at most {MAX_PROGRAMS} entries"
        )

    years: list[int] = []
    for y in years_raw:
        if isinstance(y, bool) or not isinstance(y, (int, str)):
            raise ScopeValidationError(f"invalid year: {y!r}")
        try:
            y_int = int(y)
        except (TypeError, ValueError):
            raise ScopeValidationError(f"invalid year: {y!r}") from None
        if y_int not in VALID_YEARS:
            raise ScopeValidationError(
                f"year {y_int} is outside the PRMS snapshot "
                f"({VALID_YEARS[0]}–{VALID_YEARS[-1]})"
            )
        if y_int not in years:
            years.append(y_int)

    programs: list[str] = []
    for p in programs_raw:
        if not isinstance(p, str):
            raise ScopeValidationError(f"invalid program: {p!r}")
        label = p.strip()
        if not label:
            raise ScopeValidationError("program entries must be non-empty strings")
        if len(label) > MAX_PROGRAM_LABEL_LEN:
            raise ScopeValidationError("program entry is too long")
        if label not in programs:
            programs.append(label)

    return {"years": sorted(years), "programs": programs}


def scope_is_empty(scope: dict[str, list] | None) -> bool:
    """True when the scope selects nothing (⇒ behaviour identical to no scope)."""
    if not scope:
        return True
    return not scope.get("years") and not scope.get("programs")


def describe_scope(scope: dict[str, list] | None) -> str:
    """Human-readable one-liner for the active scope ("years = 2024; programs = X")."""
    if scope_is_empty(scope):
        return "no filters (full portfolio)"
    parts: list[str] = []
    years = scope.get("years") or []
    programs = scope.get("programs") or []
    if years:
        parts.append("years = " + ", ".join(str(y) for y in years))
    if programs:
        parts.append("programs/accelerators = " + ", ".join(programs))
    return "; ".join(parts)


def render_scope_preamble(scope: dict[str, list] | None) -> str:
    """Render the scope block prepended to the message sent to the SDK.

    Returns ``""`` for an empty/absent scope, so an unfiltered conversation is
    byte-for-byte what it was before this feature existed.
    """
    if scope_is_empty(scope):
        return ""

    return (
        "[ACTIVE DATA SCOPE — set by the user via the filter bar, not typed in "
        "the message]\n"
        f"Constrain all PRMS queries and every answer to: {describe_scope(scope)}.\n"
        "Rules for this turn:\n"
        "1. Apply the scope in the SQL/tool call itself (e.g. reported_year_id "
        "for years, the initiative/programme join for programmes) — never "
        "compute a portfolio-wide number and then describe it as scoped.\n"
        "2. STATE the active scope explicitly in your answer, alongside the "
        "counting method and snapshot statement required by the PRMS data "
        "guide, so a scoped figure can never be mistaken for a portfolio total.\n"
        "3. If the question conflicts with the scope (e.g. it asks about a year "
        "or programme outside it), say so plainly and let the user decide — do "
        "not silently ignore either the scope or the question.\n"
        "4. If a requested breakdown is impossible within the scope, say that "
        "rather than widening the scope on your own.\n"
        "[END ACTIVE DATA SCOPE]"
    )


def apply_scope_to_message(message: str, scope: dict[str, list] | None) -> str:
    """Prepend the scope preamble to *message* (no-op for an empty scope)."""
    preamble = render_scope_preamble(scope)
    if not preamble:
        return message
    return f"{preamble}\n\n{message}"
