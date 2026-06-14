"""
Partner identification MCP tool -- finds relevant CGIAR partners.

Combines PRMS partner data with web search to identify organizations
relevant to a given topic, geography, or innovation area.

Approach:
1. Query PRMS for known partners linked to relevant results
   (initiatives, countries, regions, innovation types, result types)
2. Enrich with web search for potential new partners not yet in PRMS
3. Return structured results with clear source attribution:
   - [PRMS-VALIDATED] for partners with documented PRMS history
   - [WEB-SOURCED] for suggested partners found via search

The tool handles sparse data gracefully -- if PRMS has no partners for a
topic, it still provides web-sourced suggestions with appropriate caveats.
"""

import json
import logging
import os
import re
import sqlite3
import time
from typing import Any

from claude_agent_sdk import tool

from synapsis.utils.responses import error_response, success_response

logger = logging.getLogger("synapsis.tools.partner_identification")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRMS_DB_PATH: str = os.getenv(
    "PRMS_DB_PATH",
    "/Users/smithai/workspace/coding/PRMSDB/prdb.sqlite",
)

# Maximum results per source
MAX_PRMS_PARTNERS: int = 30
MAX_WEB_PARTNERS: int = 10

# Institution type categories for user-friendly labeling
INSTITUTION_TYPE_CATEGORIES: dict[str, list[int]] = {
    "CGIAR Center": [54],
    "Research/University": [50, 51, 52, 53, 55, 56, 57, 58, 59, 60, 61, 62, 63],
    "NGO": [37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49],
    "Government": [67, 68, 69],
    "Private Sector": [75, 76],
    "Financial Institution": [70, 71, 72, 73, 74],
    "Foundation": [77],
    "International Organization": [64, 65, 66],
    "Other": [78, 18, 19, 20, 21, 23],
}

# Reverse lookup: type_code -> category
_TYPE_CODE_TO_CATEGORY: dict[int, str] = {}
for category, codes in INSTITUTION_TYPE_CATEGORIES.items():
    for code in codes:
        _TYPE_CODE_TO_CATEGORY[code] = category

# Institution roles that indicate partnership
PARTNERSHIP_ROLES: list[int] = [2, 5, 6, 7]  # Partner, IP Partners, Core IP Partners, Expected
PARTNERSHIP_ROLE_NAMES: dict[int, str] = {
    1: "Actor",
    2: "Partner",
    3: "Capdev trainees",
    4: "Policy owner",
    5: "Innovation Package Partner",
    6: "Core Innovation Package Partner",
    7: "Expected partner",
    8: "KP Additional Contributor",
}


# ---------------------------------------------------------------------------
# PRMS query helpers
# ---------------------------------------------------------------------------

def _get_connection() -> sqlite3.Connection:
    """Get read-only PRMS database connection."""
    if not os.path.isfile(PRMS_DB_PATH):
        raise FileNotFoundError(f"PRMS database not found: {PRMS_DB_PATH}")
    return sqlite3.connect(f"file:{PRMS_DB_PATH}?mode=ro", uri=True)


def _query_rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    """Execute SQL and return list of dicts."""
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _query_scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    """Execute SQL and return single value."""
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# PRMS partner search functions
# ---------------------------------------------------------------------------

def _build_partner_query(
    topic: str | None = None,
    country: str | None = None,
    region: str | None = None,
    initiative: str | None = None,
    result_type: str | None = None,
    innovation_readiness_min: int | None = None,
    partner_types: list[str] | None = None,
) -> tuple[str, tuple]:
    """Build SQL query to find partners based on search criteria.

    Returns (sql, params) tuple for parameterized query.
    The query finds institutions linked to results matching the criteria,
    aggregated with partnership metrics.
    """
    # Base query: find institutions linked to active results via partnership roles
    select_clause = """
    SELECT
        ci.id AS institution_id,
        ci.name AS institution_name,
        ci.acronym,
        ci.website_link,
        ci.headquarter_country_iso2 AS hq_country,
        ci.institution_type_code,
        COUNT(DISTINCT rbi.result_id) AS result_count,
        GROUP_CONCAT(DISTINCT ir.name) AS roles,
        GROUP_CONCAT(DISTINCT rbi.institution_roles_id) AS role_ids
    """

    from_clause = """
    FROM results_by_institution rbi
    JOIN clarisa_institutions ci ON rbi.institutions_id = ci.id
    JOIN institution_role ir ON rbi.institution_roles_id = ir.id
    JOIN result r ON rbi.result_id = r.id
    """

    join_clauses: list[str] = []
    where_conditions: list[str] = [
        "rbi.is_active = 1",
        "r.is_active = 1",
        f"rbi.institution_roles_id IN ({','.join(str(r) for r in PARTNERSHIP_ROLES)})",
    ]
    params_list: list[Any] = []

    # Country filter
    if country:
        join_clauses.append(
            "JOIN result_country rc ON r.id = rc.result_id AND rc.is_active = 1 "
            "JOIN clarisa_countries cc ON rc.country_id = cc.id"
        )
        where_conditions.append("(cc.name LIKE ? OR cc.iso_alpha_2 LIKE ? OR cc.iso_alpha_3 LIKE ?)")
        country_pattern = f"%{country}%"
        params_list.extend([country_pattern, country.upper(), country.upper()])

    # Region filter
    if region:
        join_clauses.append(
            "JOIN result_region rr ON r.id = rr.result_id AND rr.is_active = 1 "
            "JOIN clarisa_regions cr ON rr.region_id = cr.um49Code"
        )
        where_conditions.append("cr.name LIKE ?")
        params_list.append(f"%{region}%")

    # Initiative filter
    if initiative:
        join_clauses.append(
            "JOIN results_by_inititiative rbi_init ON r.id = rbi_init.result_id AND rbi_init.is_active = 1 "
            "JOIN clarisa_initiatives cinit ON rbi_init.inititiative_id = cinit.id"
        )
        where_conditions.append(
            "(cinit.name LIKE ? OR cinit.short_name LIKE ? OR cinit.official_code LIKE ?)"
        )
        init_pattern = f"%{initiative}%"
        params_list.extend([init_pattern, init_pattern, init_pattern])

    # Result type filter (by name or ID)
    if result_type:
        # Map common names to type IDs
        type_map = {
            "innovation": 7,
            "innovation development": 7,
            "innovation use": 2,
            "knowledge product": 6,
            "policy change": 1,
            "capacity": 5,
            "capacity sharing": 5,
            "innovation package": 10,
        }
        type_id = type_map.get(result_type.lower().strip())
        if type_id:
            where_conditions.append("r.result_type_id = ?")
            params_list.append(type_id)
        else:
            # Try matching by result type name
            join_clauses.append("JOIN result_type rt ON r.result_type_id = rt.id")
            where_conditions.append("rt.name LIKE ?")
            params_list.append(f"%{result_type}%")

    # Innovation readiness level filter
    if innovation_readiness_min is not None:
        join_clauses.append(
            "JOIN results_innovations_dev rid ON r.id = rid.results_id AND rid.is_active = 1 "
            "JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id"
        )
        where_conditions.append("cirl.level >= ?")
        params_list.append(innovation_readiness_min)

    # Partner type filter
    if partner_types:
        type_codes: list[int] = []
        for pt in partner_types:
            pt_lower = pt.lower().strip()
            for category, codes in INSTITUTION_TYPE_CATEGORIES.items():
                if pt_lower in category.lower():
                    type_codes.extend(codes)
        if type_codes:
            placeholders = ",".join("?" * len(type_codes))
            where_conditions.append(f"ci.institution_type_code IN ({placeholders})")
            params_list.extend(type_codes)

    # Topic search (free text matching against result titles)
    if topic:
        where_conditions.append("r.title LIKE ?")
        params_list.append(f"%{topic}%")

    # Assemble query
    joins = "\n    ".join(join_clauses)
    wheres = "\n        AND ".join(where_conditions)

    sql = f"""
    {select_clause}
    {from_clause}
    {joins}
    WHERE {wheres}
    GROUP BY ci.id, ci.name, ci.acronym, ci.website_link, ci.headquarter_country_iso2, ci.institution_type_code
    ORDER BY result_count DESC
    LIMIT {MAX_PRMS_PARTNERS}
    """

    return sql, tuple(params_list)


def _get_partner_initiative_history(
    conn: sqlite3.Connection, institution_id: int
) -> list[dict]:
    """Get the initiatives a partner has worked on (top 5 by result count)."""
    sql = """
    SELECT cinit.short_name AS initiative, COUNT(DISTINCT rbi_inst.result_id) AS result_count
    FROM results_by_institution rbi_inst
    JOIN result r ON rbi_inst.result_id = r.id
    JOIN results_by_inititiative rbi_init ON r.id = rbi_init.result_id AND rbi_init.is_active = 1
    JOIN clarisa_initiatives cinit ON rbi_init.inititiative_id = cinit.id
    WHERE rbi_inst.institutions_id = ? AND rbi_inst.is_active = 1 AND r.is_active = 1
    GROUP BY cinit.short_name
    ORDER BY result_count DESC
    LIMIT 5
    """
    return _query_rows(conn, sql, (institution_id,))


def _get_partner_country_coverage(
    conn: sqlite3.Connection, institution_id: int
) -> list[str]:
    """Get the countries where a partner has active results (top 8)."""
    sql = """
    SELECT cc.name AS country
    FROM results_by_institution rbi_inst
    JOIN result r ON rbi_inst.result_id = r.id
    JOIN result_country rc ON r.id = rc.result_id AND rc.is_active = 1
    JOIN clarisa_countries cc ON rc.country_id = cc.id
    WHERE rbi_inst.institutions_id = ? AND rbi_inst.is_active = 1 AND r.is_active = 1
    GROUP BY cc.name
    ORDER BY COUNT(DISTINCT rbi_inst.result_id) DESC
    LIMIT 8
    """
    rows = _query_rows(conn, sql, (institution_id,))
    return [r["country"] for r in rows]


def _get_partner_innovation_levels(
    conn: sqlite3.Connection, institution_id: int
) -> dict[str, int]:
    """Get IRL distribution for innovations this partner is linked to."""
    sql = """
    SELECT cirl.level, COUNT(DISTINCT r.id) AS count
    FROM results_by_institution rbi_inst
    JOIN result r ON rbi_inst.result_id = r.id
    JOIN results_innovations_dev rid ON r.id = rid.results_id AND rid.is_active = 1
    JOIN clarisa_innovation_readiness_level cirl ON rid.innovation_readiness_level_id = cirl.id
    WHERE rbi_inst.institutions_id = ?
      AND rbi_inst.is_active = 1 AND r.is_active = 1
      AND r.result_type_id = 7
    GROUP BY cirl.level
    ORDER BY cirl.level
    """
    rows = _query_rows(conn, sql, (institution_id,))
    return {f"IRL_{r['level']}": r["count"] for r in rows}


def _enrich_partners(conn: sqlite3.Connection, partners: list[dict]) -> list[dict]:
    """Enrich partner results with initiative history, geography, and IRL data."""
    enriched = []
    for p in partners:
        inst_id = p["institution_id"]
        type_code = p.get("institution_type_code")

        # Basic info
        partner_data = {
            "source": "PRMS-VALIDATED",
            "institution_name": p["institution_name"],
            "acronym": p.get("acronym") or "",
            "website": p.get("website_link") or "",
            "hq_country": p.get("hq_country") or "",
            "institution_category": _TYPE_CODE_TO_CATEGORY.get(type_code, "Other") if type_code else "Other",
            "partnership_results": p["result_count"],
            "partnership_roles": p.get("roles", ""),
        }

        # Add initiative history (top 5)
        initiatives = _get_partner_initiative_history(conn, inst_id)
        if initiatives:
            partner_data["initiative_history"] = [
                f"{i['initiative']} ({i['result_count']} results)" for i in initiatives
            ]

        # Add country coverage
        countries = _get_partner_country_coverage(conn, inst_id)
        if countries:
            partner_data["country_coverage"] = countries

        # Add IRL distribution (only if they have innovation links)
        irl_data = _get_partner_innovation_levels(conn, inst_id)
        if irl_data:
            partner_data["innovation_readiness_levels"] = irl_data
            # Compute a scaling-readiness score (% of innovations at IRL 7+)
            total_innovations = sum(irl_data.values())
            scaling_ready = sum(v for k, v in irl_data.items() if int(k.split("_")[1]) >= 7)
            partner_data["scaling_ready_pct"] = round(
                (scaling_ready / total_innovations * 100) if total_innovations > 0 else 0, 1
            )

        enriched.append(partner_data)

    return enriched


def _compute_relevance_scores(
    partners: list[dict],
    has_country_filter: bool,
    has_initiative_filter: bool,
    has_innovation_filter: bool,
) -> list[dict]:
    """Compute a relevance score (0-100) for each partner based on search criteria match.

    Scoring factors:
    - Result count (partnership depth): 0-40 points
    - Role diversity (multiple roles = stronger relationship): 0-15 points
    - Country match (if country filter was used): 0-15 points
    - Innovation readiness (if innovation filter used): 0-15 points
    - Initiative match (if initiative filter used): 0-15 points
    """
    if not partners:
        return partners

    # Normalize result counts (max gets 40 points)
    max_results = max(p["partnership_results"] for p in partners)

    for p in partners:
        score = 0.0

        # Result count score (0-40)
        if max_results > 0:
            score += (p["partnership_results"] / max_results) * 40

        # Role diversity score (0-15)
        roles = p.get("partnership_roles", "")
        role_count = len(roles.split(",")) if roles else 0
        score += min(role_count * 5, 15)

        # Country coverage score (0-15) - more countries = broader reach
        countries = p.get("country_coverage", [])
        if has_country_filter and countries:
            score += min(len(countries) * 3, 15)
        elif countries:
            score += min(len(countries) * 2, 10)

        # Innovation readiness score (0-15)
        if has_innovation_filter:
            scaling_pct = p.get("scaling_ready_pct", 0)
            score += (scaling_pct / 100) * 15

        # Initiative match bonus (0-15)
        if has_initiative_filter:
            init_history = p.get("initiative_history", [])
            score += min(len(init_history) * 5, 15)

        p["relevance_score"] = round(min(score, 100), 1)

    # Sort by relevance score descending
    partners.sort(key=lambda x: x["relevance_score"], reverse=True)
    return partners


# ---------------------------------------------------------------------------
# Web search enrichment
# ---------------------------------------------------------------------------

def _build_web_search_query(
    topic: str | None = None,
    country: str | None = None,
    region: str | None = None,
    partner_types: list[str] | None = None,
) -> str:
    """Build a web search query string for finding potential partners.

    Constructs a targeted search query to find organizations relevant to
    the specified topic, geography, and type.
    """
    parts: list[str] = []

    # Core topic
    if topic:
        parts.append(topic)

    # Geography
    if country:
        parts.append(country)
    elif region:
        parts.append(region)

    # Domain context
    parts.append("agricultural research")

    # Organization types
    if partner_types:
        type_terms = []
        for pt in partner_types:
            pt_lower = pt.lower()
            if "ngo" in pt_lower:
                type_terms.append("NGO")
            elif "private" in pt_lower:
                type_terms.append("company")
            elif "government" in pt_lower:
                type_terms.append("government ministry agency")
            elif "research" in pt_lower or "university" in pt_lower:
                type_terms.append("university research institute")
            elif "foundation" in pt_lower or "funder" in pt_lower:
                type_terms.append("foundation donor funder")
        if type_terms:
            parts.append(" OR ".join(type_terms))
    else:
        parts.append("partner organization")

    return " ".join(parts)


def _format_web_search_instructions(
    search_query: str,
    topic: str | None,
    country: str | None,
    region: str | None,
) -> str:
    """Format instructions for the agent to execute a web search.

    Since the partner_identification tool runs in the MCP server and doesn't
    have direct web search access, we return instructions for the agent to
    perform the search and interpret results.
    """
    geography = country or region or "global"

    return f"""
## Web Search Enrichment Instructions

To find additional partners beyond the PRMS database, perform a web search:

**Suggested search query:** "{search_query}"

**What to look for:**
- Research institutions working on {topic or 'agricultural research'} in {geography}
- NGOs with field presence in {geography} focused on {topic or 'agriculture'}
- Government agencies (ministries of agriculture, environment, science) in {geography}
- Private sector companies in agritech, seed systems, or related industries
- Foundations and donors active in {geography} agriculture

**How to present web-sourced partners:**
For each organization found, provide:
1. Organization name and type
2. Why they're relevant (specific programs, mandate overlap)
3. Geographic presence
4. Mark clearly as **[WEB-SOURCED]** — these are suggestions, not confirmed PRMS partners
5. Assign a confidence level: HIGH (well-known, clear relevance), MEDIUM (likely relevant), LOW (speculative)

**Important:** Web-sourced partners are suggestions for further investigation. They have NOT been validated against the PRMS system and do not have documented CGIAR partnership history.
"""


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------

def _format_prms_results(partners: list[dict], query_context: str) -> str:
    """Format PRMS partner results as structured text for the agent."""
    lines: list[str] = []

    lines.append("# Partner Identification Results")
    lines.append("")
    lines.append(f"**Search context:** {query_context}")
    lines.append(f"**PRMS partners found:** {len(partners)}")
    lines.append("")

    if not partners:
        lines.append("No partners found in PRMS matching these criteria.")
        lines.append("Consider broadening your search (remove geography or type filters) ")
        lines.append("or use web search to identify potential new partners.")
        return "\n".join(lines)

    lines.append("## PRMS-Validated Partners")
    lines.append("")
    lines.append("Partners with documented CGIAR partnership history in the specified area:")
    lines.append("")

    for i, p in enumerate(partners, 1):
        score = p.get("relevance_score", 0)
        lines.append(f"### {i}. {p['institution_name']}")
        if p["acronym"]:
            lines.append(f"   **Acronym:** {p['acronym']}")
        lines.append(f"   **Category:** {p['institution_category']}")
        lines.append(f"   **Relevance Score:** {score}/100")
        lines.append(f"   **Partnership Results:** {p['partnership_results']}")
        lines.append(f"   **Roles:** {p['partnership_roles']}")
        if p.get("hq_country"):
            lines.append(f"   **HQ Country:** {p['hq_country']}")
        if p.get("website"):
            lines.append(f"   **Website:** {p['website']}")

        # Initiative history
        if p.get("initiative_history"):
            lines.append(f"   **Initiative History:** {'; '.join(p['initiative_history'])}")

        # Country coverage
        if p.get("country_coverage"):
            lines.append(f"   **Country Coverage:** {', '.join(p['country_coverage'])}")

        # Innovation readiness
        if p.get("innovation_readiness_levels"):
            irl_str = ", ".join(
                f"{k}: {v}" for k, v in sorted(p["innovation_readiness_levels"].items())
            )
            lines.append(f"   **Innovation Levels:** {irl_str}")
            if p.get("scaling_ready_pct") is not None:
                lines.append(f"   **Scaling Ready (IRL 7+):** {p['scaling_ready_pct']}%")

        lines.append(f"   **Source:** [PRMS-VALIDATED]")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------

@tool(
    "partner_identification",
    "Identify relevant partners for CGIAR initiatives, innovations, or scaling efforts. "
    "Searches the PRMS database for known partners with documented partnership history, "
    "and provides web search guidance for discovering potential new partners. "
    "Results include relevance scoring, partnership depth, initiative history, "
    "geographic coverage, and innovation readiness levels. "
    "Supports filtering by topic/keyword, country, region, initiative, result type, "
    "innovation readiness level, and partner type. "
    "All results clearly labeled [PRMS-VALIDATED] or [WEB-SOURCED].",
    {
        "topic": str,
        "country": str,
        "region": str,
        "initiative": str,
        "result_type": str,
        "innovation_readiness_min": int,
        "partner_types": list,
        "include_web_suggestions": bool,
    },
)
async def partner_identification(args: dict[str, Any]) -> dict[str, Any]:
    """Identify relevant partners based on search criteria.

    Args (via tool schema):
        topic:                    Free-text keyword search (e.g. "soil health", "climate adaptation")
        country:                  Country name or ISO code (e.g. "Kenya", "KE")
        region:                   Region name (e.g. "Eastern Africa", "Southern Asia")
        initiative:               Initiative name or code (e.g. "Accelerated Breeding", "INIT-01")
        result_type:              Result type filter (e.g. "innovation", "policy change", "knowledge product")
        innovation_readiness_min: Minimum IRL level (0-9) for innovation-linked partners
        partner_types:            List of partner type categories to filter by
                                  (e.g. ["NGO", "Research/University", "Government", "Private Sector"])
        include_web_suggestions:  Whether to include web search instructions for finding
                                  additional partners (default: True)

    Returns:
        Structured partner identification results with:
        - PRMS-validated partners with partnership metrics and history
        - Relevance scores for ranking
        - Web search instructions for discovering new partners
        - Source attribution labels
    """
    # Extract parameters (all optional)
    topic = args.get("topic")
    country = args.get("country")
    region = args.get("region")
    initiative = args.get("initiative")
    result_type = args.get("result_type")
    innovation_readiness_min = args.get("innovation_readiness_min")
    partner_types = args.get("partner_types")
    include_web = args.get("include_web_suggestions", True)

    # Validate that at least one search criterion is provided
    if not any([topic, country, region, initiative, result_type, innovation_readiness_min]):
        return error_response(
            "At least one search criterion is required. Provide one or more of: "
            "topic, country, region, initiative, result_type, or innovation_readiness_min. "
            "Example: {\"topic\": \"soil health\", \"country\": \"Kenya\"}"
        )

    # Validate innovation_readiness_min range
    if innovation_readiness_min is not None:
        if not (0 <= innovation_readiness_min <= 9):
            return error_response(
                "innovation_readiness_min must be between 0 and 9 (IRL scale)."
            )

    # Build query context description
    context_parts: list[str] = []
    if topic:
        context_parts.append(f"topic='{topic}'")
    if country:
        context_parts.append(f"country='{country}'")
    if region:
        context_parts.append(f"region='{region}'")
    if initiative:
        context_parts.append(f"initiative='{initiative}'")
    if result_type:
        context_parts.append(f"result_type='{result_type}'")
    if innovation_readiness_min is not None:
        context_parts.append(f"IRL>={innovation_readiness_min}")
    if partner_types:
        context_parts.append(f"types={partner_types}")
    query_context = ", ".join(context_parts)

    # Execute PRMS query
    start_time = time.monotonic()
    try:
        conn = _get_connection()

        # Build and execute the partner search query
        sql, params = _build_partner_query(
            topic=topic,
            country=country,
            region=region,
            initiative=initiative,
            result_type=result_type,
            innovation_readiness_min=innovation_readiness_min,
            partner_types=partner_types,
        )

        logger.info(f"Partner search SQL: {sql}")
        logger.info(f"Parameters: {params}")

        raw_partners = _query_rows(conn, sql, params)

        # Enrich with detailed partnership data
        partners = _enrich_partners(conn, raw_partners)

        # Compute relevance scores
        partners = _compute_relevance_scores(
            partners,
            has_country_filter=bool(country),
            has_initiative_filter=bool(initiative),
            has_innovation_filter=bool(innovation_readiness_min),
        )

        conn.close()

    except FileNotFoundError as exc:
        return error_response(str(exc))
    except sqlite3.Error as exc:
        return error_response(f"Database error during partner search: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error in partner_identification")
        return error_response(f"Unexpected error: {exc}")

    elapsed = time.monotonic() - start_time

    # Format PRMS results
    result_text = _format_prms_results(partners, query_context)

    # Add web search instructions if requested
    if include_web:
        search_query = _build_web_search_query(
            topic=topic, country=country, region=region, partner_types=partner_types
        )
        web_instructions = _format_web_search_instructions(
            search_query=search_query,
            topic=topic,
            country=country,
            region=region,
        )
        result_text += "\n" + web_instructions

    # Metadata footer
    result_text += f"""
---
**Query executed in:** {elapsed:.2f}s
**Source:** PRMS Database (snapshot 2026-03-18)
**Partners from PRMS:** {len(partners)}
**Attribution:** All PRMS results are [PRMS-VALIDATED]. Web search suggestions are [WEB-SOURCED].
"""

    return success_response(result_text)
