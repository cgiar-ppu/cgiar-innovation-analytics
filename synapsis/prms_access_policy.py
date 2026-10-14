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
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Callable

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

#: SQL functions that are never callable from agent SQL (extension loading).
DENIED_FUNCTIONS: frozenset[str] = frozenset({"load_extension"})


class PRMSAccessDenied(sqlite3.DatabaseError):
    """A statement referenced a denied table (raised instead of SQLite's
    generic "not authorized")."""

    def __init__(self, tables: list[str]):
        self.tables = tables
        names = ", ".join(tables) if tables else "a restricted object"
        super().__init__(f"{names}: {DENIAL_MESSAGE}")


@dataclass
class AccessLog:
    """What the authorizer refused or blanked while compiling one statement."""

    denied: list[str] = field(default_factory=list)
    nulled: list[str] = field(default_factory=list)

    def _add(self, bucket: list[str], item: str) -> None:
        if item not in bucket:
            bucket.append(item)


def make_authorizer(log: AccessLog) -> Callable[..., int]:
    """Build a ``Connection.set_authorizer`` callback that records into *log*."""

    def _authorize(action: int, arg1, arg2, _db_name, _source) -> int:
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").lower()
            if table in DENIED_TABLES:
                log._add(log.denied, table)
                return sqlite3.SQLITE_DENY
            column = (arg2 or "").lower()
            if (table, column) in NULLED_COLUMNS:
                log._add(log.nulled, f"{table}.{column}")
                return sqlite3.SQLITE_IGNORE
            return sqlite3.SQLITE_OK
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            log._add(log.denied, "ATTACH/DETACH")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in DENIED_FUNCTIONS:
            log._add(log.denied, f"{arg2}()")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return _authorize


def install(conn: sqlite3.Connection) -> AccessLog:
    """Install the policy on *conn* and return the log it fills."""
    log = AccessLog()
    conn.set_authorizer(make_authorizer(log))
    return log


def translate_error(exc: BaseException, log: AccessLog) -> BaseException:
    """Turn SQLite's bare "not authorized" into a ``PRMSAccessDenied``."""
    if log.denied and isinstance(exc, sqlite3.DatabaseError):
        return PRMSAccessDenied(list(log.denied))
    return exc


def nulled_note(log: AccessLog) -> str | None:
    """A line for the tool output when columns were blanked, else None."""
    if not log.nulled:
        return None
    cols = ", ".join(log.nulled)
    return (
        f"NOTE: {cols} returned empty (NULL) on purpose: "
        f"{DENIAL_MESSAGE} Do not report these values as missing in PRMS."
    )
