"""Which parts of the PRMS snapshot the assistant may read.

The PRMS snapshot is a full copy of the reporting database. Besides the
analytic data (results, innovations, partners, geographies, CLARISA lookups)
it carries operational tables of the PRMS web application: login accounts,
integration settings, report-embedding tokens and directory data. None of
that is needed to answer a portfolio question, so the free-SQL entry points
(``prms_query`` and ``prms_search``'s ``filter_sql``) open their connection
with a SQLite authorizer built from the lists below.

Why an authorizer and not a regex on the SQL text: SQLite calls the authorizer
while it compiles the statement, once for every table/column it will actually
read — through aliases, sub-queries, CTEs, views, ``SELECT *`` and quoted or
oddly-cased names alike. A text filter cannot see those reliably.

Two levels:

* ``DENIED_TABLES`` → ``SQLITE_DENY``: the whole statement fails with a clear
  message. Used for tables with no analytic content at all. SQLite also asks
  about a table that is touched without reading a column (``COUNT(*)``,
  ``EXISTS``, ``rowid``), so even "how many rows" is refused.
* ``NULLED_COLUMNS`` → ``SQLITE_IGNORE``: the column reads as NULL everywhere
  in the statement (select list, ``WHERE``, ``JOIN``, ``ORDER BY``), so the
  rest of the table — e.g. the names of intellectual-property experts linked
  to a result — stays usable and ``SELECT *`` still works. Because the value is
  NULL in the ``WHERE`` clause too, it cannot be probed with ``LIKE``
  conditions either. The tool adds a note so the model knows the empty values
  are deliberate and does not report them as missing data.

Schema browsing (``sqlite_master``, ``pragma_table_info``) stays allowed: table
and column names are not sensitive; their values are.

Free-text fields that may contain contact details typed by reporters (for
example ``result.lead_contact_person``) are analytic content and are not
restricted here.

Role-aware layer (external partners, Oct 2026)
----------------------------------------------
Accounts with the ``external`` role (partners such as funders or development
banks testing the platform) must not see internal budget and financial
figures. For every role outside ``FULL_ACCESS_ROLES`` the authorizer adds:

* ``FINANCIAL_DENIED_TABLES`` → refused as a whole (the per-result budget
  tables hold nothing but amounts);
* ``FINANCIAL_NULLED_COLUMNS`` → read as NULL (project budgets, allocations,
  allocation percentages, sources of funding; the rest of those tables —
  project names, programme mappings, countries — stays usable).

The check is fail-closed: an unknown or missing role ("user", the default of
a context that never authenticated) gets the external restrictions, so only
the two verified full-access roles see the financial columns. The refusal text
is a separate, polite message so the model declines ("not available in this
external view") instead of reporting missing data.

Scope toggles (environment, read at call time):

* ``IA_EXTERNAL_BLOCK_POLICY_AMOUNTS`` (default ``true``) also blanks
  ``results_policy_changes.amount`` / ``status_amount`` for external roles
  (investment amounts reported on policy-change results).
* ``IA_EXTERNAL_W12_ONLY`` (default ``false``) is the strict "public dashboard
  only" reading (W1/W2 quality-assessed results, no W3/bilateral, no open
  phases). It is applied in the system prompt only; row-level filtering is
  not something a column authorizer can do.

Also for restricted roles (Oct 2026 verification round):

* internal project narratives and funder identifiers are in
  ``FINANCIAL_NULLED_COLUMNS`` (reporters typed project budgets into them);
* ``INTERNAL_DENIED_TABLES`` / ``INTERNAL_TABLE_PREFIXES`` /
  ``INTERNAL_NULLED_COLUMNS``: PRMS workflow data that is not on the public
  Results Dashboard (account names, QA/review and submission comments, field
  revision history, AI drafts, notifications, deletion/backup copies);
* :func:`redact_amounts`: currency amounts inside any text value returned to
  the model are replaced by ``AMOUNT_PLACEHOLDER``. A column authorizer
  cannot see inside free text, so this is the second layer. It is a
  best-effort pattern (symbols and codes such as $, USD, EUR, GBP with
  million/bn/k), not a guarantee against SQL that rewrites the text first;
  the narratives that are not public at all are NULLed by the authorizer.

Defence in depth for every role: ``DENIED_VTABLES`` (raw page / storage
statistics virtual tables), ``DENIED_PRAGMAS`` (``pragma_database_list``
reveals the server path) and ``DENIED_FUNCTIONS``.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Optional

#: Shown to the model (and so possibly to the user) when a statement is refused.
DENIAL_MESSAGE = (
    "This table/column holds credentials or personal contact data and is not "
    "available to the assistant."
)

#: Tables refused as a whole (lower-case name -> rationale).
DENIED_TABLES: dict[str, str] = {
    "global_parameters": "application settings, including integration credentials",
    "token_report_bi": "report-embedding access tokens",
    "otp_challenges": "one-time-password challenges (login)",
    "webhook_endpoint": "webhook URLs and signing secrets",
    "ad_users": "directory accounts: login names, e-mail addresses, HR identifiers",
}

#: Columns that read as NULL ((table, column) lower-case -> rationale).
NULLED_COLUMNS: dict[tuple[str, str], str] = {
    ("users", "password"): "login credential",
    ("users", "email"): "personal contact data (account e-mail)",
    ("intellectual_property_experts", "email"): "personal contact data",
    ("result_ip_expert", "email"): "personal contact data",
    ("result_ip_expert_workshop_organized", "email"): "personal contact data",
}

#: SQL functions that are never callable from agent SQL: extension loading,
#: file access (CLI helpers, if ever compiled in) and the FTS3 tokenizer hook
#: (it takes and returns raw pointers). None of them is used by any feature.
DENIED_FUNCTIONS: frozenset[str] = frozenset(
    {"load_extension", "readfile", "writefile", "fts3_tokenizer", "edit"}
)

#: Eponymous virtual tables that expose raw storage: ``sqlite_dbpage`` returns
#: the raw bytes of every page (it would bypass the column authorizer if the
#: build has it) and ``dbstat`` page-level statistics. Refused for every role.
DENIED_VTABLES: frozenset[str] = frozenset({"sqlite_dbpage", "dbstat"})

#: Pragmas refused for every role, also as table-valued functions
#: (``SELECT * FROM pragma_database_list`` shows the server-side file path).
#: Schema browsing (``pragma_table_info`` etc.) stays allowed.
DENIED_PRAGMAS: frozenset[str] = frozenset({"database_list"})


# ---------------------------------------------------------------------------
# Role-aware layer: budget / financial data for external roles
# ---------------------------------------------------------------------------

#: The role given to external partner accounts.
EXTERNAL_ROLE = "external"

#: Roles that read the full analytic snapshot. Every other role — including an
#: unknown or missing one — gets the financial restrictions (fail-closed).
FULL_ACCESS_ROLES: frozenset[str] = frozenset({"admin", "researcher"})

#: Shown to the model when a statement touches financial data for an external
#: role. Worded so the model declines politely instead of reporting a gap.
FINANCIAL_DENIAL_MESSAGE = (
    "Budget and financial figures (budgets, funding amounts, allocations, cash "
    "and in-kind contributions, sources of funding) are not available in this "
    "external view of Innovation Analytics."
)

#: Tables refused as a whole for external roles (lower-case name -> rationale).
FINANCIAL_DENIED_TABLES: dict[str, str] = {
    "result_initiative_budget": "per-result budget by initiative (current/next year, in-kind/cash)",
    "result_institutions_budget": "per-result partner budget (in-kind/in-cash)",
    "non_pooled_projetct_budget": "per-result bilateral project budget (in-kind/in-cash)",
}

#: Columns that read as NULL for external roles.
FINANCIAL_NULLED_COLUMNS: dict[tuple[str, str], str] = {
    ("clarisa_projects", "total_budget"): "project budget",
    ("clarisa_projects", "remaining"): "remaining project budget",
    ("clarisa_projects", "annual"): "annual project budget",
    ("clarisa_projects", "source_of_funding"): "source of funding",
    ("clarisa_project_mappings", "allocation"): "project-to-programme allocation",
    ("clarisa_project_countries", "allocation_percentage"): "project allocation by country",
    ("results_toc_result", "program_invested_financial_resources"): "programme financial-investment flag",
    # Internal CLARISA project-registry narratives: not on the public Results
    # Dashboard, and reporters typed project budgets into them ("over five
    # years with a budget of ..."). Verification round, Oct 2026.
    ("clarisa_projects", "summary"): "internal project narrative (may quote project budgets)",
    ("clarisa_projects", "description"): "internal project narrative (may quote project budgets)",
    ("clarisa_projects", "project_results"): "internal project progress narrative (may quote amounts)",
    ("clarisa_projects", "interim_director_review"): "internal review status",
    ("clarisa_projects", "modification_justification"): "internal justification",
    ("clarisa_projects", "funder_code"): "funder of a bilateral grant",
    ("clarisa_project_mappings", "comments"): "internal mapping comments",
    ("clarisa_project_mappings", "complementarity"): "internal mapping assessment",
    ("clarisa_project_mappings", "efficiencies"): "internal mapping assessment",
    ("non_pooled_project", "funder_institution_id"): "funder of a non-pooled grant",
    ("non_pooled_project", "center_grant_id"): "internal grant / contract number",
}

#: Policy-change investment amounts (toggle ``IA_EXTERNAL_BLOCK_POLICY_AMOUNTS``).
POLICY_AMOUNT_COLUMNS: dict[tuple[str, str], str] = {
    ("results_policy_changes", "amount"): "investment amount of a policy change",
    ("results_policy_changes", "status_amount"): "status of that investment amount",
}


# ---------------------------------------------------------------------------
# Role-aware layer: internal PRMS workflow data (not on the public dashboard)
# ---------------------------------------------------------------------------

#: Shown to the model when a statement touches internal workflow data for an
#: external role.
INTERNAL_DENIAL_MESSAGE = (
    "Internal PRMS workflow data (account names, QA / review and submission "
    "comments, revision history, AI drafts, notifications) is not part of the "
    "public Results Dashboard and is not available in this external view of "
    "Innovation Analytics."
)

#: What the model should do when internal workflow data was refused or blanked.
INTERNAL_GUIDANCE = (
    "Tell the user briefly that this internal detail isn't available in this "
    "external view (do not call it missing from PRMS), then answer the rest of "
    "the question from the published result data."
)

#: Tables refused as a whole for external roles (lower-case name -> rationale).
INTERNAL_DENIED_TABLES: dict[str, str] = {
    "result_qaed_log": "QA log (who quality-assessed what)",
    "result_field_revision": "field revision history (old/new values, user, reason)",
    "result_field_ai_state": "AI drafts and user feedback on them",
    "bilateral_quality_assessments": "AI QA verdicts on bilateral results",
    "notifications": "application notifications",
    "result_deletion_audit": "deletion audit",
    "user_notification_settings": "user notification settings",
}

#: Table-name prefixes refused for external roles (dated copies, companions).
INTERNAL_TABLE_PREFIXES: tuple[str, ...] = (
    "share_result_request",          # share_result_request, share_result_request_seen
    "result_reactivation_backup_",   # result_reactivation_backup_<yyyymmdd>
)

#: Columns that read as NULL for external roles.
INTERNAL_NULLED_COLUMNS: dict[tuple[str, str], str] = {
    ("users", "first_name"): "PRMS account name",
    ("users", "last_name"): "PRMS account name",
    ("result_review_history", "comment"): "QA / review comment",
    ("submission", "comment"): "submission comment",
    ("result", "reviewed_by"): "reviewer account",
}


def is_internal_table(table: str) -> bool:
    """True when *table* (lower-case) is internal workflow data."""
    return table in INTERNAL_DENIED_TABLES or table.startswith(INTERNAL_TABLE_PREFIXES)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def external_blocks_policy_amounts() -> bool:
    """``IA_EXTERNAL_BLOCK_POLICY_AMOUNTS`` (default true)."""
    return _env_flag("IA_EXTERNAL_BLOCK_POLICY_AMOUNTS", True)


def external_w12_only() -> bool:
    """``IA_EXTERNAL_W12_ONLY`` (default false): strict public-dashboard scope."""
    return _env_flag("IA_EXTERNAL_W12_ONLY", False)


def is_restricted(role: Optional[str]) -> bool:
    """True when *role* must not see financial data.

    ``None`` means "no role given" and keeps the base (credential / contact)
    policy only — used by callers that are not acting for a user. Any other
    value outside ``FULL_ACCESS_ROLES`` is restricted (fail-closed).
    """
    return role is not None and str(role).strip().lower() not in FULL_ACCESS_ROLES


def caller_role() -> str:
    """Verified role of the current request / chat connection.

    Read from the authenticated context (``synapsis.auth.context``) the same
    way the upload and document tools read the caller's user id; dev-bypass
    mode counts as admin. Must be called in the caller's context (the event
    loop or a ``to_thread`` worker), never inside a bare ``threading.Thread``.
    """
    from synapsis.runtime_policy import current_role

    return current_role()


def financial_nulled_columns() -> dict[tuple[str, str], str]:
    """The financial columns blanked for external roles (toggles applied)."""
    cols = dict(FINANCIAL_NULLED_COLUMNS)
    if external_blocks_policy_amounts():
        cols.update(POLICY_AMOUNT_COLUMNS)
    return cols


def blocked_financial_objects() -> list[str]:
    """Human-readable list of what external roles cannot read (for docs/tests)."""
    return sorted(FINANCIAL_DENIED_TABLES) + sorted(
        f"{t}.{c}" for t, c in financial_nulled_columns()
    )


def blocked_internal_objects() -> list[str]:
    """Internal workflow tables / prefixes / columns external roles cannot read."""
    return (sorted(INTERNAL_DENIED_TABLES)
            + sorted(f"{p}*" for p in INTERNAL_TABLE_PREFIXES)
            + sorted(f"{t}.{c}" for t, c in INTERNAL_NULLED_COLUMNS))


class PRMSAccessDenied(sqlite3.DatabaseError):
    """A statement referenced a denied table (raised instead of SQLite's
    generic "not authorized").

    ``financial`` is True when every refused object is a financial table
    refused for an external role (the message then says so). ``external_view``
    is True when every refused object is refused only because of the external
    view (financial or internal workflow data); ``guidance`` is the matching
    instruction for the model.
    """

    def __init__(self, tables: list[str], financial: bool = False, external_view: bool = False):
        self.tables = tables
        self.financial = financial
        self.external_view = financial or external_view
        names = ", ".join(tables) if tables else "a restricted object"
        if financial:
            message, self.guidance = FINANCIAL_DENIAL_MESSAGE, FINANCIAL_GUIDANCE
        elif self.external_view:
            message, self.guidance = INTERNAL_DENIAL_MESSAGE, INTERNAL_GUIDANCE
        else:
            message, self.guidance = DENIAL_MESSAGE, ""
        super().__init__(f"{names}: {message}")


@dataclass
class AccessLog:
    """What the authorizer refused or blanked while compiling one statement."""

    denied: list[str] = field(default_factory=list)
    nulled: list[str] = field(default_factory=list)
    #: Subsets of ``denied`` / ``nulled`` that are financial objects refused
    #: for an external role.
    financial_denied: list[str] = field(default_factory=list)
    financial_nulled: list[str] = field(default_factory=list)
    #: Subsets refused / blanked as internal workflow data for an external role.
    internal_denied: list[str] = field(default_factory=list)
    internal_nulled: list[str] = field(default_factory=list)
    #: Currency amounts replaced inside text values (external roles).
    redacted_amounts: int = 0

    def _add(self, bucket: list[str], item: str) -> None:
        if item not in bucket:
            bucket.append(item)


def make_authorizer(log: AccessLog, role: Optional[str] = None) -> Callable[..., int]:
    """Build a ``Connection.set_authorizer`` callback that records into *log*.

    *role* ``None`` applies the base policy (credentials / contact data) only;
    a role outside ``FULL_ACCESS_ROLES`` also gets the financial restrictions.
    """
    restricted = is_restricted(role)
    fin_tables = FINANCIAL_DENIED_TABLES if restricted else {}
    fin_columns = financial_nulled_columns() if restricted else {}
    int_columns = INTERNAL_NULLED_COLUMNS if restricted else {}

    def _authorize(action: int, arg1, arg2, _db_name, _source) -> int:
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").lower()
            if table in DENIED_TABLES or table in DENIED_VTABLES:
                log._add(log.denied, table)
                return sqlite3.SQLITE_DENY
            if table in fin_tables:
                log._add(log.denied, table)
                log._add(log.financial_denied, table)
                return sqlite3.SQLITE_DENY
            if restricted and is_internal_table(table):
                log._add(log.denied, table)
                log._add(log.internal_denied, table)
                return sqlite3.SQLITE_DENY
            column = (arg2 or "").lower()
            if (table, column) in NULLED_COLUMNS:
                log._add(log.nulled, f"{table}.{column}")
                return sqlite3.SQLITE_IGNORE
            if (table, column) in fin_columns:
                log._add(log.nulled, f"{table}.{column}")
                log._add(log.financial_nulled, f"{table}.{column}")
                return sqlite3.SQLITE_IGNORE
            if (table, column) in int_columns:
                log._add(log.nulled, f"{table}.{column}")
                log._add(log.internal_nulled, f"{table}.{column}")
                return sqlite3.SQLITE_IGNORE
            return sqlite3.SQLITE_OK
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            log._add(log.denied, "ATTACH/DETACH")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() in DENIED_PRAGMAS:
            log._add(log.denied, f"pragma_{(arg1 or '').lower()}")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in DENIED_FUNCTIONS:
            log._add(log.denied, f"{arg2}()")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return _authorize


def install(conn: sqlite3.Connection, role: Optional[str] = None) -> AccessLog:
    """Install the policy for *role* on *conn* and return the log it fills."""
    log = AccessLog()
    conn.set_authorizer(make_authorizer(log, role))
    return log


def translate_error(exc: BaseException, log: AccessLog) -> BaseException:
    """Turn SQLite's bare "not authorized" into a ``PRMSAccessDenied``."""
    if log.denied and isinstance(exc, sqlite3.DatabaseError):
        denied = set(log.denied)
        financial = bool(log.financial_denied) and denied <= set(log.financial_denied)
        external_view = denied <= set(log.financial_denied) | set(log.internal_denied)
        return PRMSAccessDenied(list(log.denied), financial=financial,
                                external_view=external_view)
    return exc


#: What the model should do when financial data was refused or blanked.
FINANCIAL_GUIDANCE = (
    "Tell the user politely that this financial detail isn't available in this "
    "external view (it is not missing from PRMS — do not call it missing, "
    "incomplete or unreported, and do not estimate it or look it up elsewhere), "
    "then answer the rest of the question from the non-financial PRMS data."
)


# ---------------------------------------------------------------------------
# Currency amounts inside free text (restricted roles)
# ---------------------------------------------------------------------------

#: A number: 1,200,000 / 1 200 000 / 1.2 / 450 / 3,5.
_NUM = r"(?:\d{1,3}(?:[,\u00a0\u202f ]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
#: A number that starts a token (not the tail of a longer number or word).
_NUM_START = rf"(?<![\w.,]){_NUM}"
#: Other currency codes / names seen in PRMS text (case-sensitive, so gene
#: names such as "rs123" or words such as "Europe" never match).
_OTHER_CODES = r"(?-i:INR|KES|KSh|KSH|Ksh|ETB|NGN|UGX|TZS|RWF|XOF|BDT|PKR|NPR|CHF|AUD|CAD|ZAR|Rs\.)"
#: Currency before the number. Longer forms first; letter codes not glued to
#: a preceding letter (so "EUROPE" or "BUSD" never match).
_CUR_PRE = (r"(?:(?<![A-Za-z])(?:U\.?S\.?\s?\$|US-\$|\$\s?US(?![A-Za-z])|USD|EUR(?![a-z])|GBP|"
            r"Euros?(?!\s?(?:19|20)\d\d(?![\d.,]))|\(euro\)|dollars?|" + _OTHER_CODES + r")|\$|€|£)")
#: Currency after the number (not followed by another number, where it is
#: the prefix of that number instead: "in 2023 USD 5 million").
_CUR_POST = (r"(?:US\s?\$|\$\s?US|USD|EUR|GBP|€|£|\$|(?:US\s|U\.S\.\s)?dollars?|euros?|pounds?\s+sterling|"
             + _OTHER_CODES + r")(?![A-Za-z])(?!\s?\d)")
#: Optional range: "$1-2 million", "USD 3–5 m".
_RANGE = rf"(?:\s?(?:-|\u2013|to)\s?(?:\$|US\$|USD|EUR|€|GBP|£)?\s?{_NUM})?"
#: Optional scale word: million / m / mn / bn / billion / k / thousand / B.
_SCALE = r"(?:\s{0,2}(?:million|billion|trillion|thousand|mln|mio|mn|bn|crores?|lakhs?|m|b|k)\b)?"

#: A currency amount in free text. Case-insensitive except the codes above.
AMOUNT_RE = re.compile(
    rf"{_CUR_PRE}\s?{_NUM}{_RANGE}{_SCALE}"
    rf"|{_NUM_START}{_RANGE}{_SCALE}[\s-]{{0,2}}{_CUR_POST}",
    re.IGNORECASE,
)

#: What a redacted amount reads as.
AMOUNT_PLACEHOLDER = "[amount withheld in external view]"


def redact_amounts(value):
    """Replace currency amounts inside a text value; other values unchanged."""
    if isinstance(value, str) and value:
        return AMOUNT_RE.sub(AMOUNT_PLACEHOLDER, value)
    return value


def count_amounts(text: str) -> int:
    """Number of currency amounts in *text*."""
    return len(AMOUNT_RE.findall(text)) if isinstance(text, str) and text else 0


def redact_rows(rows: list[dict], log: Optional["AccessLog"] = None) -> list[dict]:
    """Redact currency amounts in every text cell of *rows* (new list).

    Records the number of replacements in ``log.redacted_amounts``.
    """
    out = []
    hits = 0
    for row in rows:
        new = {}
        for key, val in row.items():
            if isinstance(val, str) and val:
                red, n = AMOUNT_RE.subn(AMOUNT_PLACEHOLDER, val)
                hits += n
                new[key] = red
            else:
                new[key] = val
        out.append(new)
    if log is not None:
        log.redacted_amounts += hits
    return out


def redact_for_role(rows: list[dict], role: Optional[str], log: Optional["AccessLog"] = None) -> list[dict]:
    """``redact_rows`` for restricted roles; *rows* unchanged otherwise."""
    return redact_rows(rows, log) if is_restricted(role) else rows


#: Tool-output note when amounts were replaced.
AMOUNT_NOTE = (
    "NOTE: {n} currency amount(s) inside text values were replaced with "
    f"\"{AMOUNT_PLACEHOLDER}\" on purpose: {FINANCIAL_DENIAL_MESSAGE} "
    "Quote the text with the placeholder as it is; do not guess the amount."
)


def nulled_note(log: AccessLog) -> str | None:
    """A line for the tool output when columns were blanked, else None."""
    if not log.nulled and not log.redacted_amounts:
        return None
    lines = []
    contact = [c for c in log.nulled
               if c not in log.financial_nulled and c not in log.internal_nulled]
    if contact:
        lines.append(
            f"NOTE: {', '.join(contact)} returned empty (NULL) on purpose: "
            f"{DENIAL_MESSAGE} Do not report these values as missing in PRMS."
        )
    if log.financial_nulled:
        lines.append(
            f"NOTE: {', '.join(log.financial_nulled)} returned empty (NULL) on purpose: "
            f"{FINANCIAL_DENIAL_MESSAGE} {FINANCIAL_GUIDANCE}"
        )
    if log.internal_nulled:
        lines.append(
            f"NOTE: {', '.join(log.internal_nulled)} returned empty (NULL) on purpose: "
            f"{INTERNAL_DENIAL_MESSAGE} {INTERNAL_GUIDANCE}"
        )
    if log.redacted_amounts:
        lines.append(AMOUNT_NOTE.format(n=log.redacted_amounts))
    return "\n".join(lines)
