"""
PRMS result-code citation resolver (July-7 Step 2).

Every innovation-related statement or table row the agent makes should carry its
PRMS result code as a clickable reference. Marc does this manually today; this
makes it the default via a system-prompt rule (see synapsis/system_prompt.py)
plus this resolver, which turns a bare result code into a PUBLIC URL.

HARD CONSTRAINT (the whole reason this module exists)
-----------------------------------------------------
PRMS *detail-page* URLs (``reporting.cgiar.org/...``) are SESSION-GATED — they
require an active PRMS login and, for some result types (e.g. Window-3
bilaterals), evidence is intentionally withheld at center request. Citation
links must therefore NEVER point at a session-gated PRMS detail page. They
resolve ONLY to:

  1. the public CGIAR Results Dashboard (a public, Power BI portal), or
  2. an automated public PDF/result extract.

This mirrors the Zero-Draft Reports tool's own prior pivot (its
``citationService.js`` links PRMS result *PDFs*, not raw detail pages) and
SNAP-2026's result-code-as-hyperlink approach.

If a resolver ever cannot produce a public URL it returns ``None`` (degrade
gracefully) rather than emitting a gated link. ``assert_no_session_gated_url``
is the belt-and-braces guard used both here and in the test suite.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Public link targets (the ONLY allowed destinations)
# ---------------------------------------------------------------------------

#: The public CGIAR Results Dashboard landing page (Power BI portal).
PUBLIC_RESULTS_DASHBOARD: str = "https://www.cgiar.org/food-security-impact/results-dashboard"

#: Public result-detail deep link on the Results Dashboard host. This is the
#: PUBLIC dashboard surface (``*.cgiar.org``), NOT the session-gated PRMS
#: reporting host (``reporting.cgiar.org``). The dashboard exposes per-result
#: views by result code without requiring a PRMS login.
_PUBLIC_RESULT_DETAIL_TEMPLATE: str = (
    "https://www.cgiar.org/food-security-impact/results-dashboard/?result_code={code}"
)

# ---------------------------------------------------------------------------
# Session-gated patterns that must NEVER be emitted
# ---------------------------------------------------------------------------

#: Any URL matching these patterns requires an active PRMS session and is
#: forbidden as a citation target. ``reporting.cgiar.org`` is the PRMS reporting
#: host; ``/result-detail(s)/`` deep links there are the gated detail pages.
_SESSION_GATED_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"reporting\.cgiar\.org", re.IGNORECASE),
    re.compile(r"prms\.cgiar\.org", re.IGNORECASE),
    re.compile(r"/result-details?/", re.IGNORECASE),
)

#: Accepted result-code shapes. PRMS result codes are numeric (e.g. ``28583``);
#: they are also commonly written with an ``R`` prefix (e.g. ``R28583``).
_RESULT_CODE_RE = re.compile(r"^R?(\d{1,9})$", re.IGNORECASE)


def is_session_gated_url(url: str) -> bool:
    """Return True if *url* points at a session-gated PRMS surface."""
    return any(p.search(url) for p in _SESSION_GATED_PATTERNS)


def assert_no_session_gated_url(url: str) -> None:
    """Raise ValueError if *url* is session-gated. Belt-and-braces safety guard."""
    if is_session_gated_url(url):
        raise ValueError(
            f"Refusing to emit a session-gated PRMS citation URL: {url!r}. "
            "Citations must resolve to the public Results Dashboard or a public "
            "PDF extract only."
        )


def normalize_result_code(result_code: str | int) -> Optional[str]:
    """Return the bare numeric result code (no ``R`` prefix), or None if invalid."""
    if result_code is None:
        return None
    m = _RESULT_CODE_RE.match(str(result_code).strip())
    return m.group(1) if m else None


def resolve_result_code_url(result_code: str | int) -> Optional[str]:
    """Resolve a PRMS result code to a PUBLIC citation URL.

    Returns a public CGIAR Results Dashboard deep link for the result code, or
    ``None`` if the code is malformed (degrade gracefully — never guess, never
    emit a gated link). The returned URL is guaranteed non-session-gated.

    Args:
        result_code: A PRMS result code, e.g. ``28583`` or ``"R28583"``.

    Returns:
        A public URL string, or ``None``.
    """
    code = normalize_result_code(result_code)
    if code is None:
        return None
    url = _PUBLIC_RESULT_DETAIL_TEMPLATE.format(code=code)
    # Guard: this should be impossible given the template, but assert anyway so
    # a future template edit can never silently introduce a gated link.
    assert_no_session_gated_url(url)
    return url


# ---------------------------------------------------------------------------
# Post-processing: rewrite bare / [Rxxxx] result-code references into links
# ---------------------------------------------------------------------------

# Matches an already-bracketed but unlinked citation like ``[R28583]`` or
# ``[28583]`` that is NOT already a markdown link (no following ``(``).
_CITATION_TOKEN_RE = re.compile(r"\[R?(\d{3,9})\](?!\()", re.IGNORECASE)


def linkify_result_codes(text: str) -> str:
    """Rewrite bracketed result-code tokens in *text* into markdown links.

    ``[R28583]`` / ``[28583]`` → ``[R28583](<public url>)``. Codes that cannot
    be resolved are left untouched. Never produces a session-gated URL.

    This is a light post-processor applied to agent output; the primary
    mechanism is the system-prompt rule instructing the agent to cite codes.
    """
    if not text:
        return text or ""

    def _replace(match: re.Match) -> str:
        code = match.group(1)
        url = resolve_result_code_url(code)
        if url is None:
            return match.group(0)  # leave malformed tokens as-is
        return f"[R{code}]({url})"

    return _CITATION_TOKEN_RE.sub(_replace, text)
