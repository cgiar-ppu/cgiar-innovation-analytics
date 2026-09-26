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
the best row by (active, quality-assured [W1/W2 status 2 or W3/bilateral
status 6], phase closed, phase year, version id, row id). A code that is not in
the snapshot is never guessed at; when the snapshot itself is unavailable the
resolver falls back to the public Results Dashboard link (never a gated one).
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

#: The public CGIAR Results Dashboard landing page (Power BI portal). Used only
#: as a last-resort fallback when no PRMS snapshot is configured.
PUBLIC_RESULTS_DASHBOARD: str = "https://www.cgiar.org/food-security-impact/results-dashboard"

#: Legacy dashboard "deep link". The dashboard ignores the parameter (it lands
#: on the home page), so it is only a fallback; old links of this shape found
#: in a message are upgraded to the per-result report when the code is known.
_LEGACY_DASHBOARD_TEMPLATE: str = (
    "https://www.cgiar.org/food-security-impact/results-dashboard/?result_code={code}"
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

    @property
    def url(self) -> str:
        template = PUBLIC_IPSR_REPORT_TEMPLATE if self.module == "ipsr" else PUBLIC_RESULT_REPORT_TEMPLATE
        return template.format(code=self.code, phase=self.phase)


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
def _load_index(file_key: tuple) -> dict[str, ResultLink]:
    """Build {result_code: ResultLink} from the snapshot identified by *file_key*."""
    real = file_key[0]
    best: dict[str, tuple] = {}
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
        rank = (
            1 if is_active in (1, "1", True) else 0,
            1 if qa else 0,
            1 if closed else 0,
            int(phase_year or 0),
            version,
            int(row_id or 0),
        )
        if app_module_id is not None:
            module = "ipsr" if int(app_module_id) == _IPSR_APP_MODULE_ID else "result"
        else:
            module = "ipsr" if type_id in _IPSR_RESULT_TYPES else "result"
        payload = (rank, version, module, phase_name or "", qa)
        cur = best.get(code_s)
        if cur is None or rank > cur[0]:
            best[code_s] = payload
    return {
        code: ResultLink(code=code, phase=p[1], module=p[2], phase_name=p[3], quality_assured=p[4])
        for code, p in best.items()
    }


def citation_index() -> Optional[dict[str, ResultLink]]:
    """The cached code→link index for the active snapshot, or None if unavailable."""
    key = _file_key(_db_path())
    if key is None:
        return None
    try:
        return _load_index(key)
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


def resolve_result_code_url(result_code: str | int | None) -> Optional[str]:
    """Resolve a PRMS result code to its PUBLIC source URL.

    * Known code → the public PRMS result report for its latest published phase
      (``reporting.cgiar.org/reports/result-details/<code>?phase=<version_id>``,
      or ``ipsr-details`` for IPSR-module results).
    * Snapshot unavailable → the public Results Dashboard (graceful fallback).
    * Malformed code, or a code that is NOT in the snapshot → ``None`` (never
      guess a link for a code that does not exist).

    The returned URL is guaranteed non-session-gated.
    """
    code = normalize_result_code(result_code)
    if code is None:
        return None
    index = citation_index()
    if index is None:
        url = _LEGACY_DASHBOARD_TEMPLATE.format(code=code)
    else:
        link = index.get(code)
        if link is None:
            return None
        url = link.url
    # Guard: a future template edit can never silently introduce a gated link.
    assert_no_session_gated_url(url)
    return url


# ---------------------------------------------------------------------------
# Post-processing: every result code in a message becomes a public link
# ---------------------------------------------------------------------------

#: Visible note appended to an explicit citation token whose code is not in the
#: snapshot (a typo or an invented code) — the reader must not trust it blindly.
UNKNOWN_CODE_NOTE = "not found in the PRMS snapshot"

#: Note attached to a hand-written link into the logged-in PRMS application.
GATED_LINK_NOTE = "PRMS login required; not a public source"


@dataclass
class LinkifyReport:
    """What :func:`linkify_result_codes_report` did to one message."""

    text: str
    linked: list[str] = field(default_factory=list)   # codes turned into links
    unknown: list[str] = field(default_factory=list)  # codes not in the snapshot
    index_available: bool = True


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
_BARE_R_RE = re.compile(r"(?<![\w/#=.\-\[])R-?(\d{2,7})(?![\w\-]|\.\d)")

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
    def __init__(self, resolve: Callable[[str], Optional[str]], index_available: bool):
        self._resolve = resolve
        self.report_linked: list[str] = []
        self.report_unknown: list[str] = []
        self.index_available = index_available

    def url(self, code: str) -> Optional[str]:
        norm = normalize_result_code(code)
        if norm is None:
            return None
        url = self._resolve(norm)
        if url is None:
            if norm not in self.report_unknown:
                self.report_unknown.append(norm)
            return None
        if norm not in self.report_linked:
            self.report_linked.append(norm)
        return url

    # -- rewriters for unprotected text ------------------------------------

    def bracket_groups(self, text: str) -> str:
        def _rep(m: re.Match) -> str:
            parts = []
            for tok in _R_TOKEN_RE.finditer(m.group(1)):
                code = str(int(tok.group(1)))
                url = self.url(code)
                if url:
                    parts.append(f"[R{code}]({url})")
                elif self.index_available:
                    parts.append(f"R{code} ({UNKNOWN_CODE_NOTE})")
                else:
                    parts.append(f"R{code}")
            return ", ".join(parts)
        return _BRACKET_GROUP_RE.sub(_rep, text)

    def bare_codes(self, text: str) -> str:
        def _rep(m: re.Match) -> str:
            code = str(int(m.group(1)))
            url = self.url(code)
            return f"[R{code}]({url})" if url else m.group(0)
        return _BARE_R_RE.sub(_rep, text)

    def phrases(self, text: str) -> str:
        def _rep(m: re.Match) -> str:
            def _num(n: re.Match) -> str:
                url = self.url(n.group(1))
                return f"[{n.group(0)}]({url})" if url else n.group(0)
            return m.group("lead") + _NUM_RE.sub(_num, m.group("list"))
        return _PHRASE_RE.sub(_rep, text)

    def unprotected(self, text: str) -> str:
        # Each stage only sees text that is still unprotected, so links made by
        # an earlier stage (their URLs contain digits) are never re-processed.
        text = self.bracket_groups(text)
        text = _apply_unprotected(text, self.phrases)
        return _apply_unprotected(text, self.bare_codes)

    # -- protected segments that still carry a code --------------------------

    def protected(self, chunk: str, m: re.Match) -> str:
        if m.group("url") is not None or m.group("autolink") is not None:
            raw = chunk.strip("<>")
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
        # [Innovation name](R1003) — a code used as the link target.
        code_m = re.fullmatch(r"R-?(\d{1,7})", href.strip())
        if code_m and not bang:
            code = str(int(code_m.group(1)))
            url = self.url(code)
            if url:
                return f"[{ltext}]({url}{title})"
            if self.index_available:
                return f"{ltext} (R{code} {UNKNOWN_CODE_NOTE})"
            return ltext
        # Legacy dashboard deep link → upgrade to the per-result report.
        legacy = re.match(
            r"^https?://(?:www\.)?cgiar\.org/food-security-impact/results-dashboard/?\?result_code=(\d{1,7})$",
            href.strip(),
        )
        if legacy and self.index_available:
            url = self.url(legacy.group(1))
            if url:
                return f"{bang}[{ltext}]({url}{title})"
        if not bang and href.startswith(("http://", "https://")) and is_session_gated_url(href):
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
                    if url:
                        code = str(int(cm.group(2)))
                        cells[idx] = f"{cm.group(1)}[R{code}]({url}){cm.group(3)}"
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
    * legacy dashboard links ``…/results-dashboard/?result_code=N`` → upgraded.

    Never touched: fenced/inline code, ``<chart>`` JSON, HTML tags, URLs and the
    text/target of existing links. Unknown codes are left as written and
    reported; an explicit citation token with an unknown code is visibly
    flagged (``R99999 (not found in the PRMS snapshot)``). Bracketed numbers
    without an ``R`` (``[2024]``) are never treated as codes.
    """
    if not text:
        return LinkifyReport(text=text or "", index_available=citation_index() is not None)

    index_available = citation_index() is not None
    linker = _Linker(resolve_result_code_url, index_available)
    text = _rewrite_tables(text, linker)
    pieces = []
    for is_protected, chunk, m in _split_protected(text):
        pieces.append(linker.protected(chunk, m) if is_protected else linker.unprotected(chunk))
    out = "".join(pieces)
    if linker.report_unknown:
        logger.info("citation: %d result code(s) not in the PRMS snapshot: %s",
                    len(linker.report_unknown), ", ".join(linker.report_unknown[:20]))
    return LinkifyReport(
        text=out,
        linked=linker.report_linked,
        unknown=linker.report_unknown,
        index_available=index_available,
    )


def linkify_result_codes(text: Optional[str]) -> str:
    """Backward-compatible wrapper: return only the rewritten text."""
    return linkify_result_codes_report(text).text
