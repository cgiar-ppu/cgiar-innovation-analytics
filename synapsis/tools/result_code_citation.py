"""
PRMS result-code citations: every result the agent names links to its PUBLIC source.

History
-------
* July-7 Step 2: the agent cited results as ``[R<code>]`` tokens and this module
  rewrote them into links to the public CGIAR Results Dashboard
  (``…/results-dashboard/?result_code=<code>``).
* 2026-09-25, Marc Schut: *"the system ALWAYS includes the URLs that direct back
  to the source of the information (for example:
  https://reporting.cgiar.org/reports/result-details/1003?phase=6)… It does
  mention the ResultID, but not the URL."* In Jules's real 18-Sep export some
  codes were bare text and the rest linked to the dashboard HOME page (the
  dashboard ignores ``?result_code=``; verified in a browser on 2026-09-26).

What was verified (2026-09-26, anonymous headless Chromium, no cookies)
-----------------------------------------------------------------------
``https://reporting.cgiar.org/reports/result-details/<result_code>?phase=<version_id>``
is a PUBLIC page: the PRMS SPA calls the anonymous endpoint
``api.reporting.cgiar.org/api/platform-report/result/<code>?phase=<version_id>``
(HTTP 200 without a session) and shows the generated one-result PDF report
("CGIAR PDF Generator") in an iframe. ``<X>`` is the persistent **result code**
(NOT ``result.id``) and ``<P>`` is ``result.version_id`` (the reporting phase:
1 = Reporting 2022, 3 = 2023, 4 = 2024, 6 = 2025, 8 = 2026; IPSR 2/5/7/9).
Innovation Packages and complementary innovations (IPSR module phases) use the
sibling route ``/reports/ipsr-details/<code>?phase=<version_id>``; the
``result-details`` report answers "type not supported" for them. Evidence:
``analysis/ia-finalize-20260926/lanes/G-REPORT.md``.

The logged-in PRMS application pages (``reporting.cgiar.org/result/…``,
``prms.cgiar.org``) remain SESSION-GATED and are never emitted.

How a code becomes a URL (deterministic)
----------------------------------------
The mapping is a lookup in the configured PRMS snapshot (``result`` ⋈
``version``), cached per snapshot file (path + mtime + size). A result code has
one row per reporting phase; the link points at the **latest published phase**:
the best row by (public report works, active, quality-assured [W1/W2 status 2
or W3/bilateral status 6], phase closed, phase year, version id, row id).

THE LINK RULE (Marc Schut, 2026-10-08: result codes and URLs "should ALWAYS
trace back to the automated PDFs that the PRMS produces, e.g. 11180 -->
https://reporting.cgiar.org/reports/ipsr-details/11180?phase=7")
-----------------------------------------------------------------------------
A result code is only ever linked to its PRMS-generated PDF report page
(``reporting.cgiar.org/reports/{result|ipsr}-details/<code>?phase=<n>``).
The generic CGIAR Results Dashboard is NEVER used as a link for a result: it
ignores ``?result_code=`` and opens its home page (verified 2026-09-26).

1. Code in the snapshot with a working public report → that report, for the
   best phase above (a working phase always beats a broken one).
2. Code whose ONLY phases have a report PRMS currently fails to generate
   (IPSR 2023/2024, ``PRMS_BROKEN_IPSR_REPORT_PHASES``; re-tested 2026-10-08,
   still ``FUNCTION prdb.reportIPSRPathwaysByCode does not exist``) → NOT
   linked; the code is shown with the honest note
   ``PRMS report currently unavailable: PRMS-side error`` (first mention in a
   message). Linking the error page would send readers to "Something went
   wrong"; the dashboard would send them to a page without the result.
3. Code NOT in the snapshot → never guessed; an explicit citation token shows
   ``not found in the PRMS snapshot``.
4. Snapshot unavailable → codes stay plain text (nothing to resolve the phase
   with); never a dashboard link.

Model-written URLs are normalised by the linkifier: a Results Dashboard link
for a result (``?result_code=N``, or a dashboard link whose text is a code) and
a hand-written PRMS report URL with a wrong/missing phase or the wrong
``result``/``ipsr`` route are rewritten to the resolved report (or rule 2/3).
A plain "CGIAR Results Dashboard" portal link that does not name a result is
left alone. Session-gated PRMS application URLs are never emitted.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public link targets (the ONLY allowed destinations)
# ---------------------------------------------------------------------------

#: The public CGIAR Results Dashboard landing page (Power BI portal). It is a
#: portfolio-level view and is NEVER emitted as the link for a result (it
#: ignores ``?result_code=``). Kept to RECOGNISE such links in model output and
#: in chats saved before 2026-09-26, which are rewritten to the PRMS report.
PUBLIC_RESULTS_DASHBOARD: str = "https://www.cgiar.org/food-security-impact/results-dashboard"

#: Dashboard links in text: ``…/results-dashboard[/…][?…]`` on cgiar.org.
_DASHBOARD_URL_RE = re.compile(
    r"^https?://(?:www\.)?cgiar\.org/food-security-impact/results-dashboard(?:[/?#][^\s]*)?$",
    re.IGNORECASE,
)
#: A hand-written PRMS report page, any phase (or none) and either route.
_REPORT_URL_RE = re.compile(
    r"^https?://(?:www\.)?reporting\.cgiar\.org/reports/(?:result|ipsr)-details/(\d{1,9})/?(?:[?#][^\s]*)?$",
    re.IGNORECASE,
)

#: Public per-result report (verified anonymous 2026-09-26). ``code`` is the
#: result code, ``phase`` the ``result.version_id`` of the phase shown.
PUBLIC_RESULT_REPORT_TEMPLATE: str = (
    "https://reporting.cgiar.org/reports/result-details/{code}?phase={phase}"
)

#: Same, for IPSR-module phases (Innovation Packages, complementary innovations).
PUBLIC_IPSR_REPORT_TEMPLATE: str = (
    "https://reporting.cgiar.org/reports/ipsr-details/{code}?phase={phase}"
)

#: Version ``app_module_id`` of the IPSR module (versions 2/5/7/9).
_IPSR_APP_MODULE_ID = 2

#: KNOWN PRMS-SIDE BUG (verified 2026-09-26 and re-tested 2026-10-08,
#: anonymous API + headless browser): the public IPSR report for the IPSR 2023
#: (version 2) and IPSR 2024 (version 5) phases fails for every code tried with
#: ``QueryFailedError: FUNCTION prdb.reportIPSRPathwaysByCode does not exist``
#: and the page shows "Something went wrong". We never link those phases: a
#: code that also exists in a later IPSR phase (7 = IPSR 2025, 9 = IPSR 2026,
#: even as a row still being edited) is linked there — that report renders the
#: same result code publicly; a code that exists ONLY in 2/5 is shown unlinked
#: with ``REPORT_UNAVAILABLE_NOTE`` (never the generic dashboard).
#: Once PRMS fixes the report function, set ``IA_PRMS_BROKEN_REPORT_PHASES=``
#: (empty) in the environment — no code change — or remove the phases here.
PRMS_BROKEN_IPSR_REPORT_PHASES: frozenset[int] = frozenset({2, 5})

#: Environment override for :data:`PRMS_BROKEN_IPSR_REPORT_PHASES`: unset →
#: the default above; empty or ``none`` → no broken phases; ``"2,5"`` → those.
BROKEN_PHASES_ENV = "IA_PRMS_BROKEN_REPORT_PHASES"


def broken_report_phases() -> frozenset[int]:
    """The IPSR phases whose public PRMS report is currently known to fail."""
    raw = os.environ.get(BROKEN_PHASES_ENV)
    if raw is None:
        return PRMS_BROKEN_IPSR_REPORT_PHASES
    raw = raw.strip().lower()
    if raw in ("", "none", "-"):
        return frozenset()
    try:
        return frozenset(int(x) for x in re.split(r"[\s,;]+", raw) if x)
    except ValueError:
        logger.warning("%s=%r is not a list of phase ids; using the default", BROKEN_PHASES_ENV, raw)
        return PRMS_BROKEN_IPSR_REPORT_PHASES

#: Result types that only exist in IPSR phases (fallback if the version table
#: lacks ``app_module_id``): 10 Innovation Package, 11 Complementary innovation.
_IPSR_RESULT_TYPES = (10, 11)

# ---------------------------------------------------------------------------
# Session-gated patterns that must NEVER be emitted
# ---------------------------------------------------------------------------

_PRMS_REPORTING_HOST = "reporting.cgiar.org"
_PUBLIC_REPORT_PATH_RE = re.compile(r"^/reports/(?:result|ipsr)-details/\d{1,9}/?$")
_GATED_HOSTS = ("prms.cgiar.org",)
_GATED_PATH_RE = re.compile(r"/result-details?/", re.IGNORECASE)

#: Accepted result-code shapes. PRMS result codes are numeric (e.g. ``28583``);
#: they are also commonly written with an ``R`` prefix (e.g. ``R28583``).
_RESULT_CODE_RE = re.compile(r"^R?-?(\d{1,9})$", re.IGNORECASE)


def is_public_prms_report_url(url: str) -> bool:
    """True for the anonymous one-result report pages on ``reporting.cgiar.org``."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if (parsed.hostname or "").lower() != _PRMS_REPORTING_HOST:
        return False
    if not _PUBLIC_REPORT_PATH_RE.match(parsed.path or ""):
        return False
    phase = parse_qs(parsed.query).get("phase", [""])[0]
    return phase.isdigit()


def is_session_gated_url(url: str) -> bool:
    """Return True if *url* points at a session-gated PRMS surface.

    Everything on ``reporting.cgiar.org`` is gated EXCEPT the public report
    pages (``/reports/result-details/<code>?phase=<n>`` and
    ``/reports/ipsr-details/<code>?phase=<n>``); ``prms.cgiar.org`` is gated;
    a ``/result-detail(s)/`` path on any other host is treated as gated too.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return True
    host = (parsed.hostname or "").lower()
    if not host:
        # Not an absolute URL: fall back to substring checks.
        low = url.lower()
        if _PRMS_REPORTING_HOST in low or any(h in low for h in _GATED_HOSTS):
            return True
        return bool(_GATED_PATH_RE.search(url))
    if host == _PRMS_REPORTING_HOST or host.endswith("." + _PRMS_REPORTING_HOST):
        return not is_public_prms_report_url(url)
    if any(host == h or host.endswith("." + h) for h in _GATED_HOSTS):
        return True
    return bool(_GATED_PATH_RE.search(parsed.path or ""))


def assert_no_session_gated_url(url: str) -> None:
    """Raise ValueError if *url* is session-gated. Belt-and-braces safety guard."""
    if is_session_gated_url(url):
        raise ValueError(
            f"Refusing to emit a session-gated PRMS citation URL: {url!r}. "
            "Citations must resolve to the public PRMS result report or the "
            "public Results Dashboard only."
        )


def normalize_result_code(result_code: str | int | None) -> Optional[str]:
    """Return the bare numeric result code (no ``R`` prefix), or None if invalid."""
    if result_code is None:
        return None
    m = _RESULT_CODE_RE.match(str(result_code).strip())
    if not m:
        return None
    return str(int(m.group(1)))  # drop leading zeros: "R017" -> "17"


# ---------------------------------------------------------------------------
# Snapshot-backed index: result code -> public report link
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultLink:
    """The public link chosen for one result code."""

    code: str
    phase: int              # result.version_id of the phase linked
    module: str             # "result" | "ipsr"
    phase_name: str = ""
    quality_assured: bool = True
    #: True when PRMS has no working public report for this code (it exists
    #: only in broken IPSR phases): the code is shown with
    #: ``REPORT_UNAVAILABLE_NOTE`` and is NOT linked.
    report_unavailable: bool = False
    #: Every (phase, module) with an active row whose public report works: a
    #: hand-written link to one of these (e.g. the 2024 edition) is kept.
    working_reports: frozenset = frozenset()

    def accepts(self, url: str) -> bool:
        """True if *url* is a working PRMS report page of THIS code (any of its phases)."""
        if not is_public_prms_report_url(url):
            return False
        parsed = urlparse(url.strip())
        m = _REPORT_URL_RE.match(url.strip())
        if not m or normalize_result_code(m.group(1)) != self.code:
            return False
        module = "ipsr" if "/ipsr-details/" in parsed.path else "result"
        phase = int(parse_qs(parsed.query).get("phase", ["0"])[0])
        return (phase, module) in self.working_reports

    @property
    def report_url(self) -> str:
        """The PRMS report page for the chosen phase (even if PRMS fails it today)."""
        template = PUBLIC_IPSR_REPORT_TEMPLATE if self.module == "ipsr" else PUBLIC_RESULT_REPORT_TEMPLATE
        return template.format(code=self.code, phase=self.phase)

    @property
    def url(self) -> Optional[str]:
        """The link to emit: the PRMS PDF report page, or None when PRMS cannot render it."""
        return None if self.report_unavailable else self.report_url


#: Test/ops override for the snapshot path (``None`` → the app's PRMS DB path).
_DB_PATH_OVERRIDE: Optional[str] = None


def use_citation_db_path(path: Optional[str]) -> None:
    """Point the resolver at a specific snapshot file (``None`` = app default)."""
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = path
    _load_index.cache_clear()


def _db_path() -> Optional[str]:
    if _DB_PATH_OVERRIDE is not None:
        return _DB_PATH_OVERRIDE or None
    try:
        from synapsis.tools.prms_query import PRMS_DB_PATH  # lazy: avoid import cycles
        return PRMS_DB_PATH
    except Exception:  # pragma: no cover - defensive
        return os.environ.get("PRMS_DB_PATH")


def _file_key(path: Optional[str]) -> Optional[tuple]:
    if not path:
        return None
    try:
        real = os.path.realpath(path)
        st = os.stat(real)
    except OSError:
        return None
    return (real, st.st_mtime_ns, st.st_size)


_INDEX_SQL_WITH_MODULE = """
SELECT r.result_code, r.version_id, r.result_type_id, r.source, r.status_id,
       r.is_active, r.id, v.status, v.phase_year, v.phase_name, v.app_module_id
FROM result r LEFT JOIN version v ON v.id = r.version_id
WHERE r.result_code IS NOT NULL AND r.version_id IS NOT NULL
"""

_INDEX_SQL_NO_MODULE = """
SELECT r.result_code, r.version_id, r.result_type_id, r.source, r.status_id,
       r.is_active, r.id, v.status, v.phase_year, v.phase_name, NULL
FROM result r LEFT JOIN version v ON v.id = r.version_id
WHERE r.result_code IS NOT NULL AND r.version_id IS NOT NULL
"""


def _is_qa(source, status_id) -> bool:
    return (source == "Result" and status_id == 2) or (source == "API" and status_id == 6)


@lru_cache(maxsize=2)
def _load_index(file_key: tuple, broken_phases: frozenset = PRMS_BROKEN_IPSR_REPORT_PHASES) -> dict[str, ResultLink]:
    """Build {result_code: ResultLink} from the snapshot identified by *file_key*."""
    real = file_key[0]
    best: dict[str, tuple] = {}
    working: dict[str, set] = {}
    with closing(sqlite3.connect(f"file:{real}?mode=ro", uri=True, timeout=5)) as conn:
        try:
            rows = conn.execute(_INDEX_SQL_WITH_MODULE).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(_INDEX_SQL_NO_MODULE).fetchall()
    for (code, version_id, type_id, source, status_id, is_active, row_id,
         v_status, phase_year, phase_name, app_module_id) in rows:
        try:
            code_s = str(int(code))
            version = int(version_id)
        except (TypeError, ValueError):
            continue
        qa = _is_qa(source, status_id)
        closed = v_status in (0, "0", None)
        if app_module_id is not None:
            module = "ipsr" if int(app_module_id) == _IPSR_APP_MODULE_ID else "result"
        else:
            module = "ipsr" if type_id in _IPSR_RESULT_TYPES else "result"
        report_works = not (module == "ipsr" and version in broken_phases)
        rank = (
            1 if report_works else 0,  # a working public page beats everything else
            1 if is_active in (1, "1", True) else 0,
            1 if qa else 0,
            1 if closed else 0,
            int(phase_year or 0),
            version,
            int(row_id or 0),
        )
        if report_works and is_active in (1, "1", True):
            working.setdefault(code_s, set()).add((version, module))
        payload = (rank, version, module, phase_name or "", qa, not report_works)
        cur = best.get(code_s)
        if cur is None or rank > cur[0]:
            best[code_s] = payload
    return {
        code: ResultLink(
            code=code, phase=p[1], module=p[2], phase_name=p[3],
            quality_assured=p[4], report_unavailable=p[5],
            working_reports=frozenset(working.get(code, ())),
        )
        for code, p in best.items()
    }


def citation_index() -> Optional[dict[str, ResultLink]]:
    """The cached code→link index for the active snapshot, or None if unavailable."""
    key = _file_key(_db_path())
    if key is None:
        return None
    try:
        return _load_index(key, broken_report_phases())
    except sqlite3.Error as exc:
        logger.warning("result-code citation index unavailable: %s", exc)
        return None


def get_result_link(result_code: str | int | None) -> Optional[ResultLink]:
    """The :class:`ResultLink` for *result_code*, or None (unknown/malformed/no snapshot)."""
    code = normalize_result_code(result_code)
    if code is None:
        return None
    index = citation_index()
    if not index:
        return None
    return index.get(code)


#: Status values returned by :func:`result_code_status`.
LINKED, UNAVAILABLE, UNKNOWN, NO_SNAPSHOT = "linked", "report_unavailable", "unknown", "no_snapshot"


def result_code_status(result_code: str | int | None) -> tuple[str, Optional[str]]:
    """``(status, url)`` for a result code under THE LINK RULE (module docstring).

    * ``("linked", url)``: the PRMS PDF report page for the code.
    * ``("report_unavailable", None)``: the code is in the snapshot but PRMS
      cannot currently generate any of its reports (broken IPSR phases only).
    * ``("unknown", None)``: malformed, or not in the snapshot (never guessed).
    * ``("no_snapshot", None)``: no snapshot to resolve against.

    A returned URL is guaranteed to be a public PRMS report page — never the
    generic Results Dashboard, never a session-gated PRMS application page.
    """
    code = normalize_result_code(result_code)
    if code is None:
        return UNKNOWN, None
    index = citation_index()
    if index is None:
        return NO_SNAPSHOT, None
    link = index.get(code)
    if link is None:
        return UNKNOWN, None
    if link.report_unavailable:
        return UNAVAILABLE, None
    url = link.url
    # Guards: a future template edit can never silently introduce a gated or
    # non-report link.
    assert_no_session_gated_url(url)
    if not is_public_prms_report_url(url):  # pragma: no cover - defensive
        raise ValueError(f"Refusing to emit a non-report citation URL: {url!r}")
    return LINKED, url


def resolve_result_code_url(result_code: str | int | None) -> Optional[str]:
    """Resolve a PRMS result code to its PRMS-generated PDF report page, or None.

    * Known code → ``reporting.cgiar.org/reports/result-details/<code>?phase=<version_id>``
      (``ipsr-details`` for IPSR-module results) for its best working phase.
    * Code whose only phases have a broken PRMS report (IPSR 2023/2024) → None;
      callers show :data:`REPORT_UNAVAILABLE_NOTE` (see :func:`result_code_status`).
    * Malformed code, code NOT in the snapshot, or no snapshot → None.

    Never returns the generic Results Dashboard or a session-gated URL.
    """
    return result_code_status(result_code)[1]


def result_code_in_url(url: str) -> Optional[str]:
    """The result code a URL is meant to open, if it is a per-result link.

    Recognises a Results Dashboard link with ``?result_code=N`` (any path under
    ``/results-dashboard``) and a PRMS report page ``/reports/{result|ipsr}-details/N``
    with any or no phase. Returns the bare code, or None.
    """
    u = (url or "").strip().strip("<>")
    m = _REPORT_URL_RE.match(u)
    if m:
        return normalize_result_code(m.group(1))
    if _DASHBOARD_URL_RE.match(u):
        try:
            q = parse_qs(urlparse(u).query)
        except ValueError:
            return None
        for key in ("result_code", "resultCode", "code", "result"):
            vals = q.get(key)
            if vals:
                return normalize_result_code(vals[0])
    return None


def is_results_dashboard_url(url: str) -> bool:
    """True for any link into the generic CGIAR Results Dashboard."""
    return bool(_DASHBOARD_URL_RE.match((url or "").strip().strip("<>")))


# ---------------------------------------------------------------------------
# Post-processing: every result code in a message becomes a public link
# ---------------------------------------------------------------------------

#: Visible note appended to an explicit citation token whose code is not in the
#: snapshot (a typo or an invented code) — the reader must not trust it blindly.
UNKNOWN_CODE_NOTE = "not found in the PRMS snapshot"

#: Note attached to a hand-written link into the logged-in PRMS application.
GATED_LINK_NOTE = "PRMS login required; not a public source"

#: Note shown (first mention per message) for a code whose PRMS report PRMS
#: cannot currently generate (rule 2 of THE LINK RULE). Honest, short, and it
#: never sends the reader to an error page or to the generic dashboard.
REPORT_UNAVAILABLE_NOTE = "PRMS report currently unavailable: PRMS-side error"

# Placeholder for a note while a message is rewritten (private-use characters:
# never in real text, never matched by the code regexes).
_NOTE_OPEN, _NOTE_CLOSE = "\ue000", "\ue001"
_NOTE_MARK_RE = re.compile(_NOTE_OPEN + r"(\d{1,9})([nc])" + _NOTE_CLOSE)

# "R16106 (PRMS report currently unavailable…" / "name (R16106, PRMS report…":
# codes already annotated in a text (keeps the linkifier idempotent).
_NOTED_CODE_RE = re.compile(
    r"R-?(\d{1,7})\)?\]?\s*[(,]\s*" + re.escape(REPORT_UNAVAILABLE_NOTE)
)


@dataclass
class LinkifyReport:
    """What :func:`linkify_result_codes_report` did to one message."""

    text: str
    linked: list[str] = field(default_factory=list)   # codes turned into links
    unknown: list[str] = field(default_factory=list)  # codes not in the snapshot
    index_available: bool = True
    #: codes in the snapshot whose PRMS report PRMS cannot generate right now
    unavailable: list[str] = field(default_factory=list)
    #: model-written URLs rewritten (dashboard → report, wrong phase → right one)
    rewritten_urls: int = 0


# Regions that must never be rewritten (checked in this order, leftmost wins).
_PROTECTED_RE = re.compile(
    r"(?P<fence>^[ \t]*(?P<fch>`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*(?P=fch)[ \t]*$|\Z))"
    r"|(?P<chart><chart>.*?</chart>)"
    r"|(?P<code>(?P<bt>`{1,3})[^`\n][^\n]*?(?P=bt))"
    r"|(?P<mdlink>!?\[(?P<ltext>(?:[^\[\]]|\[[^\[\]]*\])*)\]\((?P<href>[^()\s]*(?:\([^()\s]*\)[^()\s]*)*)(?P<ltitle>\s+\"[^\"]*\")?\))"
    r"|(?P<autolink><https?://[^>\s]+>)"
    r"|(?P<html></?[A-Za-z][^>\n]*>)"
    r"|(?P<url>\bhttps?://[^\s)\]>]+)",
    re.DOTALL | re.MULTILINE,
)

# [R1003] / [R17, R28] / [R-1003] / [#1003 is NOT accepted]; bracketed numbers
# WITHOUT an R (e.g. "[2024]", "[1]") are years/footnotes, never codes.
_BRACKET_GROUP_RE = re.compile(
    r"\[\s*(R-?\d{1,7}(?:\s*[,;]\s*(?:and\s+)?R-?\d{1,7})*)\s*\](?!\()"
)
_R_TOKEN_RE = re.compile(r"R-?(\d{1,7})")

# Bare R-codes in prose/tables: "R1003", "R-1003". At least 2 digits and not
# glued to words, paths, versions or hyphenated names ("R1-nj", "R2.5", "IR64").
# A slash right before the code is allowed only in prose separators (QA-4 D7):
# after ")" or whitespace ("[R26008](…)/R28583", "a / R17", ") /R17"), at the
# start of a chunk (i.e. straight after a protected link), or after another
# bare R-code ("R26008/R28583"). Path segments ("/data/R1003") stay unlinked.
_SLASH_AFTER_CODE = "|".join(
    rf"(?<=(?<![\w/#=.\-\[]){p}\d{{{n}}}/)" for n in range(2, 8) for p in ("R", "R-")
)
_BARE_R_RE = re.compile(
    r"(?:(?<![\w/#=.\-\[])|(?<=[)\s]/)|(?<=\A/)|" + _SLASH_AFTER_CODE + r")"
    r"R-?(\d{2,7})(?![\w\-]|\.\d)"
)

# "result code 1003", "Result codes: 1003, 1004 and 1005", "result_code=1003".
_PHRASE_RE = re.compile(
    r"(?P<lead>\bresult[ _\-]?codes?\b\s*(?:[:#=]\s*|\s+)(?:is\s+|are\s+|of\s+)?)"
    r"(?P<list>#?\d{1,7}(?:\s*(?:,|;|/|&|\band\b|\bor\b)\s*#?\d{1,7})*)"
    r"(?![\w.]\d|\w)",
    re.IGNORECASE,
)
_NUM_RE = re.compile(r"#?(\d{1,7})")

# Markdown table header cells that hold result codes.
_CODE_HEADER_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?:prms\s+)?(?:result[ _\-]?code|result\s*#|code|r[ _\-]?code)s?\s*(?:\*\*)?\s*$",
    re.IGNORECASE,
)
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_CELL_CODE_RE = re.compile(r"^(\s*)#?(?:R-?)?(\d{1,7})(\s*)$")


def _apply_unprotected(text: str, fn: Callable[[str], str]) -> str:
    """Apply *fn* to the unprotected parts of *text* only."""
    return "".join(chunk if prot else fn(chunk) for prot, chunk, _ in _split_protected(text))


def _split_protected(text: str) -> list[tuple[bool, str, Optional[re.Match]]]:
    """Split *text* into (is_protected, chunk, match) segments."""
    out: list[tuple[bool, str, Optional[re.Match]]] = []
    pos = 0
    for m in _PROTECTED_RE.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()], None))
        out.append((True, m.group(0), m))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:], None))
    return out


class _Linker:
    def __init__(self, status: Callable[[str], tuple[str, Optional[str]]], index_available: bool,
                 text: str = "", get_link: Callable[[str], Optional[ResultLink]] = lambda c: None):
        self._status = status
        self._get_link = get_link
        self.report_linked: list[str] = []
        self.report_unknown: list[str] = []
        self.report_unavailable: list[str] = []
        self.rewritten_urls = 0
        self.index_available = index_available
        # Codes already carrying the "unavailable" note (idempotence).
        self._noted: set[str] = {str(int(m.group(1))) for m in _NOTED_CODE_RE.finditer(text or "")}

    def url(self, code: str) -> Optional[str]:
        """The PRMS report URL for *code*, or None (unknown/unavailable/no snapshot)."""
        norm = normalize_result_code(code)
        if norm is None:
            return None
        status, url = self._status(norm)
        if status == LINKED and url:
            if norm not in self.report_linked:
                self.report_linked.append(norm)
            return url
        if status == UNAVAILABLE:
            if norm not in self.report_unavailable:
                self.report_unavailable.append(norm)
        elif status == UNKNOWN and self.index_available:
            if norm not in self.report_unknown:
                self.report_unknown.append(norm)
        return None

    def unavailable(self, code: str) -> bool:
        return (normalize_result_code(code) or "") in self.report_unavailable

    def note(self, code: str, after_name: bool = False) -> str:
        """A placeholder for the "unavailable" note; :meth:`place_notes` keeps
        the note on the FIRST mention of each code in reading order."""
        norm = normalize_result_code(code) or code
        return f"{_NOTE_OPEN}{norm}{'n' if after_name else 'c'}{_NOTE_CLOSE}"

    def place_notes(self, text: str) -> str:
        seen: set[str] = set(self._noted)

        def _rep(m: re.Match) -> str:
            code, mode = m.group(1), m.group(2)
            first = code not in seen
            seen.add(code)
            if mode == "n":
                return f" (R{code}, {REPORT_UNAVAILABLE_NOTE})" if first else f" (R{code})"
            return f" ({REPORT_UNAVAILABLE_NOTE})" if first else ""
        return _NOTE_MARK_RE.sub(_rep, text)

    # -- rewriters for unprotected text ------------------------------------

    def bracket_groups(self, text: str) -> str:
        def _rep(m: re.Match) -> str:
            parts = []
            for tok in _R_TOKEN_RE.finditer(m.group(1)):
                code = str(int(tok.group(1)))
                url = self.url(code)
                if url:
                    parts.append(f"[R{code}]({url})")
                elif self.unavailable(code):
                    parts.append(f"R{code}{self.note(code)}")
                elif self.index_available:
                    parts.append(f"R{code} ({UNKNOWN_CODE_NOTE})")
                else:
                    parts.append(f"R{code}")
            return ", ".join(parts)
        return _BRACKET_GROUP_RE.sub(_rep, text)

    def bare_codes(self, text: str) -> str:
        def _rep(m: re.Match) -> str:
            if m.string.startswith(_NOTE_OPEN, m.end()):
                return m.group(0)  # already handled by an earlier stage
            code = str(int(m.group(1)))
            url = self.url(code)
            if url:
                return f"[R{code}]({url})"
            if self.unavailable(code):
                return m.group(0) + self.note(code)
            return m.group(0)
        return _BARE_R_RE.sub(_rep, text)

    def phrases(self, text: str) -> str:
        def _rep(m: re.Match) -> str:
            def _num(n: re.Match) -> str:
                url = self.url(n.group(1))
                if url:
                    return f"[{n.group(0)}]({url})"
                if self.unavailable(n.group(1)):
                    return n.group(0) + self.note(n.group(1))
                return n.group(0)
            return m.group("lead") + _NUM_RE.sub(_num, m.group("list"))
        return _PHRASE_RE.sub(_rep, text)

    def unprotected(self, text: str) -> str:
        # Each stage only sees text that is still unprotected, so links made by
        # an earlier stage (their URLs contain digits) are never re-processed.
        text = self.bracket_groups(text)
        text = _apply_unprotected(text, self.phrases)
        return _apply_unprotected(text, self.bare_codes)

    # -- protected segments that still carry a code --------------------------

    def _accepted(self, code: str, url: str) -> bool:
        """A hand-written report URL that already opens a working report of *code*."""
        link = self._get_link(code)
        return link is not None and link.accepts(url)

    def _code_from_link_text(self, ltext: str) -> Optional[str]:
        """A link whose visible text IS a result code: "R1003", "[R1003]", "1003"."""
        m = re.fullmatch(r"\s*\\?\[?\s*(?:R-?|#)?(\d{2,7})\s*\\?\]?\s*", ltext or "")
        return str(int(m.group(1))) if m else None

    def _bare_url(self, raw: str, autolink: bool) -> Optional[str]:
        """Rewrite a bare/auto-linked URL that is meant to open one result."""
        code = result_code_in_url(raw)
        if code is None:
            return None
        if self._accepted(code, raw):
            return None
        url = self.url(code)
        if url:
            if url == raw:
                return None
            self.rewritten_urls += 1
            return f"<{url}>" if autolink else url
        if self.unavailable(code):
            self.rewritten_urls += 1
            return f"R{code}{self.note(code)}"
        if is_results_dashboard_url(raw):
            # The dashboard cannot open a result: say what the link was meant to show.
            self.rewritten_urls += 1
            return f"R{code} ({UNKNOWN_CODE_NOTE})" if self.index_available else f"R{code}"
        return None  # a hand-written report URL for a code we cannot check: leave it

    def protected(self, chunk: str, m: re.Match) -> str:
        if m.group("url") is not None or m.group("autolink") is not None:
            raw = chunk.strip("<>")
            tail = ""
            if m.group("url") is not None:
                stripped = raw.rstrip(".,;:!?'\"")
                raw, tail = stripped, raw[len(stripped):]
            replaced = self._bare_url(raw, autolink=m.group("autolink") is not None)
            if replaced is not None:
                return replaced + tail
            raw = raw + tail
            if is_session_gated_url(raw):
                # A hand-written PRMS application URL: needs a PRMS login, so it
                # must not look like a public source. Keep it visible, unlinked.
                return f"`{raw}` ({GATED_LINK_NOTE})"
            return chunk
        if m.group("mdlink") is None:
            return chunk
        href = m.group("href") or ""
        ltext = m.group("ltext") or ""
        title = m.group("ltitle") or ""
        bang = "!" if chunk.startswith("!") else ""
        if bang:
            return chunk
        # [Innovation name](R1003) — a code used as the link target.
        code_m = re.fullmatch(r"R-?(\d{1,7})", href.strip())
        if code_m:
            code = str(int(code_m.group(1)))
            url = self.url(code)
            if url:
                return f"[{ltext}]({url}{title})"
            if self.unavailable(code):
                return ltext + self.note(code, after_name=True)
            if self.index_available:
                return f"{ltext} (R{code} {UNKNOWN_CODE_NOTE})"
            return ltext
        # A link meant to open ONE result: a Results Dashboard link (with
        # ?result_code=N, or whose text is the code) or a hand-written PRMS
        # report URL (any phase/route) → the resolved PRMS report.
        h = href.strip()
        is_dash = is_results_dashboard_url(h)
        code = result_code_in_url(h)
        if code is None and is_dash:
            code = self._code_from_link_text(ltext)
        if code is not None and self._accepted(code, h):
            self.url(code)  # count it as linked
            return chunk
        if code is not None:
            url = self.url(code)
            text_has_code = re.search(rf"(?<!\d){code}(?!\d)", ltext) is not None
            if url:
                if url != h:
                    self.rewritten_urls += 1
                return f"[{ltext}]({url}{title})"
            if self.unavailable(code):
                self.rewritten_urls += 1
                return ltext + self.note(code, after_name=not text_has_code)
            if is_dash:
                self.rewritten_urls += 1
                if not self.index_available:
                    return ltext if text_has_code else f"{ltext} (R{code})"
                return (f"{ltext} ({UNKNOWN_CODE_NOTE})" if text_has_code
                        else f"{ltext} (R{code} {UNKNOWN_CODE_NOTE})")
            # hand-written report URL for a code not in the snapshot: keep it
            # unless it is not a public report page (e.g. no phase).
        if href.startswith(("http://", "https://")) and is_session_gated_url(href):
            return f"{ltext} ({GATED_LINK_NOTE})"
        return chunk

    def table_line_cells(self, line: str, code_cols: set[int]) -> str:
        if not code_cols:
            return line
        stripped = line.strip()
        lead_pipe = stripped.startswith("|")
        cells = _split_cells(line)
        changed = False
        for idx in code_cols:
            if idx < len(cells):
                cm = _CELL_CODE_RE.match(cells[idx])
                if cm:
                    url = self.url(cm.group(2))
                    code = str(int(cm.group(2)))
                    if url:
                        cells[idx] = f"{cm.group(1)}[R{code}]({url}){cm.group(3)}"
                        changed = True
                    elif self.unavailable(code):
                        cells[idx] = f"{cm.group(1)}R{code}{self.note(code)}{cm.group(3)}"
                        changed = True
        if not changed:
            return line
        indent = line[: len(line) - len(line.lstrip())]
        body = "|".join(cells)
        if lead_pipe:
            body = "|" + body
        if stripped.endswith("|"):
            body = body + "|"
        return indent + body


def _split_cells(line: str) -> list[str]:
    """Split a markdown table row into raw cells (keeps spacing, honours ``\\|``)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return re.split(r"(?<!\\)\|", s)


def _rewrite_tables(text: str, linker: _Linker) -> str:
    """Link bare numeric cells in markdown-table columns headed "Result code"."""
    if "|" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    code_cols: set[int] = set()
    in_table = False
    in_fence: Optional[str] = None
    for i, line in enumerate(lines):
        fence = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = marker
            elif in_fence == marker:
                in_fence = None
            in_table = False
            out.append(line)
            continue
        if in_fence is not None:
            out.append(line)
            continue
        is_row = "|" in line and line.strip() != ""
        if not in_table:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if is_row and _TABLE_SEP_RE.match(nxt):
                headers = _split_cells(line)
                code_cols = {j for j, h in enumerate(headers) if _CODE_HEADER_RE.match(h)}
                in_table = True
            out.append(line)
            continue
        if not is_row:
            in_table = False
            code_cols = set()
            out.append(line)
            continue
        if _TABLE_SEP_RE.match(line):
            out.append(line)
            continue
        out.append(linker.table_line_cells(line, code_cols))
    return "\n".join(out)


def linkify_result_codes_report(text: Optional[str]) -> LinkifyReport:
    """Rewrite every result-code mention in *text* into a public markdown link.

    Handled forms (all idempotent; already-linked codes are never re-linked):

    * citation tokens ``[R1003]`` / ``[R17, R28]`` → ``[R1003](<url>)``;
    * bare ``R1003`` in prose, lists, tables and parentheses → ``[R1003](<url>)``;
    * phrases ``result code 1003`` / ``result codes: 1003, 1004 and 1005`` → the
      numbers become links (the wording is kept);
    * bare numeric cells in a markdown-table column headed "Result code"/"Code";
    * ``[Innovation name](R1003)`` (code as link target) → real URL, so prose can
      link a name without printing the code (funder persona);
    * Results Dashboard links for a result (``…/results-dashboard/?result_code=N``
      or a dashboard link whose text is the code) and hand-written PRMS report
      URLs with a wrong/missing phase or route → the resolved PRMS report (a
      hand-written link to another WORKING phase of the same code is kept);
    * codes whose PRMS report PRMS cannot generate (IPSR 2023/2024 only) →
      ``R16106 (PRMS report currently unavailable: PRMS-side error)`` on the
      first mention, never a link to an error page or to the dashboard.

    Never touched: fenced/inline code, ``<chart>`` JSON, HTML tags, URLs and the
    text/target of existing links. Unknown codes are left as written and
    reported; an explicit citation token with an unknown code is visibly
    flagged (``R99999 (not found in the PRMS snapshot)``). Bracketed numbers
    without an ``R`` (``[2024]``) are never treated as codes.
    """
    if not text:
        return LinkifyReport(text=text or "", index_available=citation_index() is not None)

    index_available = citation_index() is not None
    linker = _Linker(result_code_status, index_available, text, get_result_link)
    text = _rewrite_tables(text, linker)
    pieces = []
    for is_protected, chunk, m in _split_protected(text):
        pieces.append(linker.protected(chunk, m) if is_protected else linker.unprotected(chunk))
    out = linker.place_notes("".join(pieces))
    if linker.report_unknown:
        logger.info("citation: %d result code(s) not in the PRMS snapshot: %s",
                    len(linker.report_unknown), ", ".join(linker.report_unknown[:20]))
    return LinkifyReport(
        text=out,
        linked=linker.report_linked,
        unknown=linker.report_unknown,
        index_available=index_available,
        unavailable=linker.report_unavailable,
        rewritten_urls=linker.rewritten_urls,
    )


def linkify_result_codes(text: Optional[str]) -> str:
    """Backward-compatible wrapper: return only the rewritten text."""
    return linkify_result_codes_report(text).text
