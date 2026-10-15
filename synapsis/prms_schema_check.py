"""
prms_schema_check.py — is every PRMS table the agent relies on really in the snapshot?

Why this exists (Marc Schut, 13 Oct 2026)
-----------------------------------------
From the 2026-09-13 snapshot on, the nightly MySQL→SQLite conversion silently
dropped every PRMS table whose DDL had a column ``COMMENT`` — among them
``results_innovations_use`` (the 0-9 Innovation Use level) and
``result_actors`` (the use numbers: how many farmers, women, youth …). The
publish gate only counted tables, so nothing flagged it. The agent's own
references still documented both tables, so when it hit ``no such table`` it
concluded the data "lives in a CLARISA API layer" and told a user that PRMS has
no use levels — a confident, wrong story.

This module compares a short list of tables the agent's references depend on
with the snapshot actually loaded. The result is surfaced

* to administrators on ``/api/health`` (``prms_data``) and to signed-in users on
  ``/api/prms/snapshot`` (``schema_check``);
* in the agent's system prompt (a DATA HEALTH warning when anything is missing);
* in ``prms_query`` when a query fails with ``no such table`` on an expected
  table (a plain "missing from the loaded snapshot — data-pipeline issue"
  message instead of "the table might be named differently").

Stdlib only, read-only, never raises, cached per real file like
:mod:`synapsis.prms_snapshot`.

Companion: :mod:`synapsis.prms_access_policy` lists the tables/columns the
agent may NOT read (credentials, personal contact data). None of them is an
expected table here; a refused query is not a missing table.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any, Optional

from synapsis.prms_snapshot import resolve_db_path

logger = logging.getLogger("synapsis.prms_schema_check")

#: Tables the agent's references (cookbook, data guide, schema reference,
#: dashboard) rely on. A snapshot without one of these is DEGRADED: answers
#: that need it must say the data is missing from the loaded snapshot.
#: table -> what it carries (shown to the agent and in the health output).
EXPECTED_TABLES: dict[str, str] = {
    "result": "every result (central fact table)",
    "version": "reporting phases",
    "result_type": "result types",
    "result_status": "result statuses",
    "result_level": "result levels",
    "results_by_inititiative": "result <-> program/initiative links",
    "clarisa_initiatives": "programs / initiatives",
    "results_center": "result <-> CGIAR center links",
    "clarisa_center": "CGIAR centers",
    "results_by_institution": "partners and other institutions",
    "clarisa_institutions": "institutions",
    "result_country": "result countries",
    "result_region": "result regions",
    "clarisa_countries": "countries",
    "clarisa_regions": "regions",
    "evidence": "evidence links",
    "linked_result": "links between results",
    "gender_tag_level": "impact-area tag levels",
    "results_innovations_dev": "Innovation Development details (readiness level 0-9)",
    "clarisa_innovation_readiness_level": "innovation readiness levels 0-9",
    "results_innovations_use": "Innovation Use details: the 0-9 innovation use level, new users added, use narrative",
    "clarisa_innovation_use_levels": "innovation use levels 0-9",
    "results_innovations_use_measures": "legacy Innovation Use quantities (2022-style) and units",
    "result_ip_measure": "other quantitative measures of Innovation Use (hectares, kg …) as in the PRMS PDF",
    "result_actors": "use numbers by actor type (how many; women, men, youth) — current and 2030 target",
    "actor_type": "actor types (farmers, researchers, extension agents …)",
    "result_innov_section": "Current vs Future (2030 target) section of use data",
    "results_by_institution_type": "organisations using an innovation, by institution type",
    "result_innovation_package": "Innovation Packages (IPSR)",
    "result_by_innovation_package": "IPSR package components",
    "results_knowledge_product": "knowledge products",
    "results_policy_changes": "policy changes",
    "results_capacity_developments": "capacity sharing",
}

_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, tuple, dict[str, Any]]] = {}

DATA_PIPELINE_NOTE = (
    "This PRMS table is expected but missing from the loaded snapshot — a "
    "data-pipeline (snapshot load) issue on our side, not a sign that PRMS lacks "
    "the data. Tell the user plainly that this data is not available in the "
    "current snapshot and that it has been flagged; do not guess where else the "
    "data might live (e.g. 'a CLARISA API layer') and do not substitute another "
    "table as if it held the same data."
)


def _file_key(realpath: str) -> Optional[tuple]:
    try:
        st = os.stat(realpath)
    except OSError:
        return None
    return (realpath, st.st_size, int(st.st_mtime))


def check_schema(db_path: Optional[str] = None, *, refresh: bool = False) -> dict[str, Any]:
    """Compare :data:`EXPECTED_TABLES` with the tables in the snapshot.

    Returns ``{"status": "ok" | "degraded" | "unavailable", "expected": n,
    "missing": [{"table", "carries"}, ...], "present_table_count": n}``.
    Never raises.
    """
    path = db_path or resolve_db_path()
    realpath = os.path.realpath(path)
    key = _file_key(realpath)
    if key is None:
        return {"status": "unavailable", "expected": len(EXPECTED_TABLES), "missing": [],
                "present_table_count": None}

    now = time.time()
    cached = _cache.get(realpath)
    if cached and not refresh:
        ts, cached_key, result = cached
        if cached_key == key and (now - ts) < _CACHE_TTL_SECONDS:
            return result

    try:
        conn = sqlite3.connect(f"file:{realpath}?mode=ro", uri=True)
        try:
            names = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("prms_schema_check: could not read %s: %s", realpath, exc)
        result = {"status": "unavailable", "expected": len(EXPECTED_TABLES), "missing": [],
                  "present_table_count": None}
        _cache[realpath] = (now, key, result)
        return result

    missing = [
        {"table": t, "carries": why}
        for t, why in EXPECTED_TABLES.items()
        if t not in names
    ]
    result = {
        "status": "degraded" if missing else "ok",
        "expected": len(EXPECTED_TABLES),
        "missing": missing,
        "present_table_count": len([n for n in names if not n.startswith("sqlite_")]),
    }
    if missing:
        logger.warning(
            "PRMS snapshot %s is missing %d expected table(s): %s",
            realpath, len(missing), ", ".join(m["table"] for m in missing),
        )
    _cache[realpath] = (now, key, result)
    return result


def missing_expected_tables(db_path: Optional[str] = None) -> list[str]:
    """Names of expected tables absent from the snapshot (empty when healthy/unknown)."""
    return [m["table"] for m in check_schema(db_path)["missing"]]


def is_expected_table(name: str) -> bool:
    return name in EXPECTED_TABLES


def missing_table_message(table: str) -> str:
    """Tool-output text for ``no such table: <table>`` on an expected table."""
    carries = EXPECTED_TABLES.get(table, "")
    what = f" (it carries: {carries})" if carries else ""
    return f"Table `{table}`{what}: {DATA_PIPELINE_NOTE}"


def prompt_warning(db_path: Optional[str] = None) -> str:
    """System-prompt block naming missing expected tables ('' when healthy)."""
    missing = check_schema(db_path)["missing"]
    if not missing:
        return ""
    lines = [
        "## ⚠️ DATA HEALTH WARNING — expected PRMS tables are missing from the loaded snapshot",
        "",
        "The snapshot you query was loaded incompletely. These tables are documented in your",
        "references and exist in PRMS, but are NOT in this snapshot:",
        "",
    ]
    lines += [f"- `{m['table']}` — {m['carries']}" for m in missing]
    lines += [
        "",
        "When a question needs one of them: say plainly that this data is missing from the",
        "current snapshot because of a data-loading problem on our side (already flagged), give",
        "what you CAN answer from other tables, and stop there. Do NOT conclude that PRMS does",
        "not collect the data, do NOT guess where else it might live (e.g. 'a CLARISA API",
        "layer', 'PowerBI'), and do NOT present another table (e.g. IPSR",
        "`result_by_innovation_package.current_innovation_use_level`) as the same data.",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "DATA_PIPELINE_NOTE",
    "EXPECTED_TABLES",
    "check_schema",
    "is_expected_table",
    "missing_expected_tables",
    "missing_table_message",
    "prompt_warning",
]
