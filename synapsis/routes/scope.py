"""
Active-data-scope filter options — the values the chat filter bar offers.

- GET /api/scope/options — reporting years + programmes/accelerators the user
  can scope the agent to.

Programmes are read from the PRMS `clarisa_initiatives` table (the same table
the dashboard's initiative charts join against), so the list cannot drift from
the data the agent queries. Two portfolio eras are exposed, per
`references/prms_data_guide.md` §3:

  - "Initiatives (2022–2024)": INIT-xx, SGP-xx, PLAT-xx  (portfolio_id = 2)
  - "Programs & Accelerators (2025+)": SP01…SP13         (portfolio_id = 3)

If the PRMS database is unavailable the endpoint still returns the years and a
small static fallback list of the 2025+ Science Programs, so the filter bar
never comes up empty (and says which source it used).

Auth-gated like the session/history endpoints.
"""

import os
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, Depends

from synapsis.auth.middleware import get_current_user
from synapsis.config import logger
from synapsis.scope import VALID_YEARS

router = APIRouter(prefix="/api", tags=["scope"])

# Same resolution order as prms_dashboard.py / prms_query.py.
_PRMS_DB_PATH = os.getenv(
    "PRMS_DB_PATH",
    "/Users/smithai/workspace/coding/PRMSDB/fresh_13June2026/prdb_fresh.sqlite",
)

_ERA_LABELS = {
    2: "Initiatives (2022–2024)",
    3: "Programs & Accelerators (2025+)",
}

# Only real portfolio entities — excludes internal placeholder rows in
# clarisa_initiatives (MP-01/02, OFF-01, OPLAT-01/02) which have no short_name
# and never carry results.
_CODE_PREFIXES = ("INIT-", "SGP-", "PLAT-", "SP")

_SQL_PROGRAMS = """
SELECT official_code, short_name, name, portfolio_id
FROM clarisa_initiatives
WHERE active = 1
ORDER BY portfolio_id DESC, official_code
"""

#: Fallback used only when the PRMS DB is unreachable (2025+ Science Programs).
_FALLBACK_PROGRAMS: list[dict[str, Any]] = [
    {"code": code, "label": f"{code} — {label}", "era": _ERA_LABELS[3]}
    for code, label in [
        ("SP01", "Breeding for Tomorrow"),
        ("SP02", "Sustainable Farming"),
        ("SP03", "Sustainable Animal and Aquatic Foods"),
        ("SP04", "Multifunctional Landscapes"),
        ("SP05", "Better Diets and Nutrition"),
        ("SP06", "Climate Action"),
        ("SP07", "Policy Innovations"),
        ("SP08", "Food Frontiers and Security"),
        ("SP09", "Scaling for Impact"),
        ("SP10", "Gender Equality and Inclusion"),
        ("SP11", "Capacity Sharing"),
        ("SP12", "Digital Transformation"),
        ("SP13", "Genebank"),
    ]
]

# Small in-memory cache — the PRMS snapshot is static.
_cache: dict[str, Any] | None = None
_cache_ts: float = 0.0
_CACHE_TTL = 900.0  # 15 minutes


def _load_programs() -> tuple[list[dict[str, Any]], str]:
    """Return (programs, source). Falls back to the static list on any failure."""
    if not os.path.isfile(_PRMS_DB_PATH):
        logger.warning("Scope options: PRMS DB not found at %s — using fallback list", _PRMS_DB_PATH)
        return list(_FALLBACK_PROGRAMS), "fallback"

    try:
        conn = sqlite3.connect(f"file:{_PRMS_DB_PATH}?mode=ro", uri=True)
        try:
            rows = conn.execute(_SQL_PROGRAMS).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("Scope options: PRMS query failed (%s) — using fallback list", exc)
        return list(_FALLBACK_PROGRAMS), "fallback"

    programs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for official_code, short_name, name, portfolio_id in rows:
        code = (official_code or "").strip()
        if not code or not code.startswith(_CODE_PREFIXES):
            continue
        if code in seen:  # clarisa_initiatives carries a few duplicate codes
            continue
        seen.add(code)
        # `\xa0` (non-breaking space) shows up in several SP short names.
        label_part = (short_name or name or "").replace("\xa0", " ").strip()
        programs.append(
            {
                "code": code,
                "label": f"{code} — {label_part}" if label_part else code,
                "era": _ERA_LABELS.get(portfolio_id, "Other"),
            }
        )

    if not programs:
        return list(_FALLBACK_PROGRAMS), "fallback"
    return programs, "prms"


@router.get("/scope/options")
async def scope_options(user: dict = Depends(get_current_user)):
    """Return the year and programme/accelerator values the filter bar offers.

    Response::

        {
          "years": [2022, 2023, 2024, 2025],
          "programs": [{"code": "SP09", "label": "SP09 — Scaling for Impact",
                        "era": "Programs & Accelerators (2025+)"}, ...],
          "source": "prms" | "fallback"
        }
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    programs, source = _load_programs()
    _cache = {
        "years": list(VALID_YEARS),
        "programs": programs,
        "source": source,
    }
    _cache_ts = now
    return _cache
