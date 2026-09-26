"""
Selected persona — the specialist agent the user picked for the conversation.

Feedback F3 (Marc Schut, 2026-08): *"can I use a specific agent if I want/need?
now I cannot find this option"*. The specialists existed (nine builtin
subagents, plus two model variants each) and the orchestrator routed to them on
its own judgement, but the user had no way to ask for one.

Design — why this is a message preamble, not an SDK option
----------------------------------------------------------
The SDK is handed the WHOLE agent roster once, when the session's
``ClaudeSDKClient`` is built (``agent_options.build_agent_options`` passes
``agents=all_agents``). Rebuilding the client to pin one agent would mean
tearing down the subprocess and resuming the Claude session on every change of
the picker — the same expensive dance ``handle_switch_model`` performs — and it
would still not stop the orchestrator delegating elsewhere, because the SDK has
no "only this subagent" switch.

Meanwhile the system prompt is a SHARED file (``/tmp/cgiar-ia-system-prompt.txt``)
read by every SDK subprocess, so writing a per-user persona into it would let
concurrent sessions clobber each other — the exact hazard documented in
``synapsis/scope.py``.

So the persona is injected **per message**, server-side, as a delimited
preamble prepended to the copy of the text handed to the SDK, reusing the seam
``<workflow_context>`` and the active data scope already established. The
persisted user message is never modified, and the picker shows the active
selection at all times, so nothing is routed invisibly.

Honest limits of this seam
--------------------------
This is a routing INSTRUCTION to the orchestrator, not a hard binding: the
orchestrator is the process that receives the turn and it decides whether to
call the ``Task`` tool with ``subagent_type=<id>``. The preamble therefore also
tells it to say plainly when the requested specialist is the wrong tool for the
question rather than pretending. What is guaranteed mechanically:

* an empty selection produces a byte-identical message to the pre-F3 one;
* an unknown/ill-formed id is rejected before the agent is touched;
* only ids that really exist in ``SUBAGENTS`` can ever reach the model.

Why only the nine base agents are selectable
--------------------------------------------
``SUBAGENTS`` holds 27 entries: nine specialists plus ``_opus_powerful`` /
``_sonnet_efficient`` variants of each. The variants are a legacy routing
detail (per platform policy every subagent now runs Sonnet 4.6 regardless), so
surfacing 27 near-duplicate names in a picker would be noise, not choice. The
variants remain valid ids for the orchestrator's own routing; they are simply
not offered in the UI. Custom agents created via ``/api/agents`` are likewise
not selectable yet — see the result notes.

Audience personas (2026-09-26: Marc's persona skills, WB W2, Nikki "Language")
----------------------------------------------------------------------------
The same picker also offers AUDIENCE personas — "Funder / investor" and
"Scientist / researcher" — condensed from the two skill files Marc Schut wrote
(shared 7 Sep 2026: "hope your feedback above can be taken into account"). They
do not route to a specialist; they change WHO the answer is written for
(vocabulary, which figures lead, level of detail, suggested visuals). Each is a
data file in ``references/personas/<id>.md`` (front matter: id, name,
description; body: the instruction block), so the wording can be edited without
touching code. Picking one prepends an ``[AUDIENCE PERSONA …]`` block to the
message the SDK sees, through exactly the same seam as a specialist; choosing
nothing still leaves the message byte-identical to the pre-picker one.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from synapsis.agents import SUBAGENTS, AGENT_REGISTRY

logger = logging.getLogger(__name__)

#: Suffixes that mark a model-variant of a base agent (not separately offered).
_VARIANT_SUFFIXES = ("_opus_powerful", "_sonnet_efficient")

#: Defensive cap — an agent id is a short snake_case token, never a payload.
MAX_PERSONA_ID_LEN = 64


class PersonaValidationError(ValueError):
    """Raised when a client sends an unknown or ill-formed persona id."""


# ---------------------------------------------------------------------------
# Audience personas (data files under references/personas/)
# ---------------------------------------------------------------------------

#: Where the audience persona instruction files live (copied into the image
#: with the rest of ``references/``).
AUDIENCE_PERSONAS_DIR = Path(__file__).resolve().parent.parent / "references" / "personas"

#: Stable picker order for the known audience personas; any extra file sorts
#: after these by id.
_AUDIENCE_ORDER = ("funder_investor", "scientist_researcher")

#: Picker metadata shared by every audience persona.
AUDIENCE_TYPE = "Audience"
_AUDIENCE_COLORS = {
    "funder_investor": "hsl(35, 80%, 50%)",
    "scientist_researcher": "hsl(200, 70%, 45%)",
}
_AUDIENCE_TAGS = {
    "funder_investor": ["audience", "plain language", "funders", "investors"],
    "scientist_researcher": ["audience", "evidence", "reproducibility", "researchers"],
}

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n(?P<body>.*)\Z", re.DOTALL)
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _parse_persona_file(path: Path) -> dict[str, str] | None:
    text = path.read_text(encoding="utf-8")
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        logger.warning("persona file %s has no front matter; skipped", path.name)
        return None
    meta: dict[str, str] = {}
    for line in m.group("meta").splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    persona_id = meta.get("id") or path.stem
    if not _ID_RE.match(persona_id) or persona_id in SUBAGENTS:
        logger.warning("persona file %s has an invalid/colliding id %r; skipped", path.name, persona_id)
        return None
    body = m.group("body").strip()
    if not body or not meta.get("name"):
        logger.warning("persona file %s is missing a name or body; skipped", path.name)
        return None
    return {
        "id": persona_id,
        "name": meta["name"],
        "description": meta.get("description", ""),
        "instructions": body,
    }


@lru_cache(maxsize=1)
def _audience_personas() -> dict[str, dict[str, str]]:
    """{id: {id, name, description, instructions}} in stable picker order."""
    found: dict[str, dict[str, str]] = {}
    if AUDIENCE_PERSONAS_DIR.is_dir():
        for path in sorted(AUDIENCE_PERSONAS_DIR.glob("*.md")):
            try:
                parsed = _parse_persona_file(path)
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning("persona file %s unreadable: %s", path.name, exc)
                continue
            if parsed:
                found[parsed["id"]] = parsed
    order = [i for i in _AUDIENCE_ORDER if i in found] + sorted(
        i for i in found if i not in _AUDIENCE_ORDER
    )
    return {i: found[i] for i in order}


def audience_persona_ids() -> list[str]:
    """Ids of the audience personas (Funder / investor, Scientist / researcher)."""
    return list(_audience_personas())


def is_audience_persona(persona: str | None) -> bool:
    return bool(persona) and persona in _audience_personas()


def audience_persona_instructions(persona: str) -> str:
    """The instruction block for an audience persona ("" if unknown)."""
    entry = _audience_personas().get(persona)
    return entry["instructions"] if entry else ""


def specialist_persona_ids() -> list[str]:
    """The specialist agent ids the picker may offer (base builtins, stable order)."""
    return [
        agent_id
        for agent_id in SUBAGENTS
        if not agent_id.endswith(_VARIANT_SUFFIXES)
    ]


def selectable_persona_ids() -> list[str]:
    """Every id the picker may offer: audience personas first, then specialists."""
    return audience_persona_ids() + specialist_persona_ids()


def selectable_personas() -> list[dict[str, Any]]:
    """Full picker payload: id, display name, description, tags, colour.

    Names/colours/tags come from ``AGENT_REGISTRY`` (the same metadata the
    Agents page renders) and the description from the ``AgentDefinition``
    itself, so the picker cannot drift from what the agent actually is.
    """
    out: list[dict[str, Any]] = []
    for persona_id, entry in _audience_personas().items():
        out.append(
            {
                "id": persona_id,
                "name": entry["name"],
                "description": entry["description"],
                "type": AUDIENCE_TYPE,
                "color": _AUDIENCE_COLORS.get(persona_id, "hsl(35, 60%, 50%)"),
                "tags": list(_AUDIENCE_TAGS.get(persona_id, ["audience"])),
            }
        )
    for agent_id in specialist_persona_ids():
        meta = AGENT_REGISTRY.get(agent_id, {})
        agent_def = SUBAGENTS[agent_id]
        out.append(
            {
                "id": agent_id,
                "name": meta.get("name", agent_id.replace("_", " ").title()),
                "description": agent_def.description,
                "type": meta.get("type", "builtin"),
                "color": meta.get("color", ""),
                "tags": list(meta.get("tags", [])),
            }
        )
    return out


def normalize_persona(raw: Any) -> str:
    """Validate a raw client persona value.

    Accepts ``None``, ``""`` (both meaning "no preference — orchestrator
    decides, exactly as before this feature existed") or a known agent id.

    Returns:
        The normalized agent id, or ``""`` for no selection.

    Raises:
        PersonaValidationError: if the value is not a string, is too long, or
            is not one of the ids the picker may offer.
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise PersonaValidationError("agent must be a string")
    agent_id = raw.strip()
    if not agent_id:
        return ""
    if len(agent_id) > MAX_PERSONA_ID_LEN:
        raise PersonaValidationError("agent id is too long")
    if agent_id not in selectable_persona_ids():
        raise PersonaValidationError(f"unknown agent '{agent_id}'")
    return agent_id


def persona_is_empty(persona: str | None) -> bool:
    """True when no specialist is selected (⇒ behaviour identical to before)."""
    return not persona


def persona_display_name(persona: str) -> str:
    """Human-readable name for an agent id ("PRMS Data Analyst")."""
    if is_audience_persona(persona):
        return _audience_personas()[persona]["name"]
    meta = AGENT_REGISTRY.get(persona, {})
    return meta.get("name", persona.replace("_", " ").title())


def describe_persona(persona: str | None) -> str:
    """One-liner for logs / API echoes."""
    if persona_is_empty(persona):
        return "no specialist selected (orchestrator routes)"
    return f"{persona_display_name(persona)} ({persona})"


def render_persona_preamble(persona: str | None) -> str:
    """Render the block prepended to the message sent to the SDK.

    Returns ``""`` when nothing is selected, so an unpicked conversation is
    byte-for-byte what it was before this feature existed.
    """
    if persona_is_empty(persona):
        return ""

    assert persona is not None  # narrowed by persona_is_empty
    if is_audience_persona(persona):
        return render_audience_preamble(persona)
    name = persona_display_name(persona)
    description = getattr(SUBAGENTS.get(persona), "description", "") or ""

    return (
        "[SELECTED SPECIALIST — chosen by the user in the agent picker, not "
        "typed in the message]\n"
        f"For this turn, delegate the work to the `{persona}` specialist "
        f"({name}) using the Task tool with subagent_type=\"{persona}\".\n"
        f"That specialist's remit: {description}\n"
        "Rules for this turn:\n"
        "1. Route to that specialist rather than answering directly or "
        "delegating to a different one, unless rule 3 applies.\n"
        "2. Name the specialist you used in your answer, so the user can see "
        "their choice was honoured.\n"
        "3. If the question falls outside that specialist's remit, or it "
        "cannot be answered with that specialist's tools, SAY SO PLAINLY, "
        "explain which specialist fits, and let the user decide — never "
        "silently reroute and never pretend a different agent's work came "
        "from the one they picked.\n"
        "4. All standing rules still apply — the PRMS counting method, the "
        "result-code citations and the snapshot statement are required "
        "whichever specialist runs.\n"
        "[END SELECTED SPECIALIST]"
    )


def render_audience_preamble(persona: str) -> str:
    """The delimited block for an AUDIENCE persona (no specialist routing)."""
    name = persona_display_name(persona)
    return (
        f"[AUDIENCE PERSONA — {name} — chosen by the user in the picker, not "
        "typed in the message]\n"
        f"{audience_persona_instructions(persona)}\n"
        "Standing rules are unchanged by this persona: the PRMS counting method "
        "and definitions, the snapshot statement, the result-code citations with "
        "their public links, the Sources list, and the separation of what comes "
        "from the data versus interpretation.\n"
        "[END AUDIENCE PERSONA]"
    )


def apply_persona_to_message(message: str, persona: str | None) -> str:
    """Prepend the persona preamble to *message* (no-op when unselected)."""
    preamble = render_persona_preamble(persona)
    if not preamble:
        return message
    return f"{preamble}\n\n{message}"
