"""
Scenario analysis MCP tool -- 'what if' portfolio modeling.

Models hypothetical portfolio changes against current PRMS baseline data.
Returns structured comparisons with sensitivity analysis.

Scenario types:
- reallocation:     Shift result-producing capacity between initiatives
- irl_advancement:  Model innovation pipeline advancement (IRL level shifts)
- output_scaling:   Scale initiative output by a factor
- portfolio_focus:  Model portfolio-wide emphasis shifts

All outputs are clearly labeled [SCENARIO-MODELED] to distinguish from
[PRMS-VALIDATED] data directly from the PRMS database.
"""

import json
import logging
import math
import os
import sqlite3
from typing import Any

from claude_agent_sdk import tool

from synapsis.utils.responses import error_response, success_response

logger = logging.getLogger("synapsis.tools.scenario_analysis")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRMS_DB_PATH: str = os.getenv(
    "PRMS_DB_PATH",
    "/Users/smithai/workspace/coding/PRMSDB/prdb.sqlite",
)

VALID_SCENARIO_TYPES: list[str] = [
    "reallocation",
    "irl_advancement",
    "output_scaling",
    "portfolio_focus",
]

# ---------------------------------------------------------------------------
# Modeling constants
# ---------------------------------------------------------------------------

DIMINISHING_RETURNS_FACTOR: float = 0.8   # Reallocation efficiency
SCALING_EXPONENT: float = 0.7             # sqrt-ish diminishing returns for scale-ups
IRL_VALLEY_OF_DEATH_FACTOR: float = 0.7   # IRL 6->7 transition is harder
SENSITIVITY_BAND: float = 0.20            # +/-20% for optimistic/pessimistic

# IRL ID mapping in PRMS: IRL 0 = ID 11, IRL 1 = ID 12, ..., IRL 9 = ID 20
# IRL 0-2  (early)         = IDs 11-13
# IRL 3-6  (developing)    = IDs 14-17
# IRL 7-9  (scaling-ready) = IDs 18-20

# ---------------------------------------------------------------------------
# PRMS query helpers
# ---------------------------------------------------------------------------


def _get_connection() -> sqlite3.Connection:
    """Get read-only PRMS database connection."""
    if not os.path.isfile(PRMS_DB_PATH):
        raise FileNotFoundError(f"PRMS database not found: {PRMS_DB_PATH}")
    return sqlite3.connect(f"file:{PRMS_DB_PATH}?mode=ro", uri=True)


def _query_rows(conn: sqlite3.Connection, sql: str) -> list[dict]:
    """Execute SQL and return list of dicts."""
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _query_scalar(conn: sqlite3.Connection, sql: str) -> Any:
    """Execute SQL and return single value."""
    cur = conn.cursor()
    cur.execute(sql)
    row = cur.fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Baseline data functions
# ---------------------------------------------------------------------------


def _get_initiative_baselines(conn: sqlite3.Connection) -> list[dict]:
    """Get per-initiative result counts, broken down by type.

    Returns list of dicts with keys:
        short_name, innovations, innovation_uses, knowledge_products,
        policy_changes, total_results
    """
    sql = """
        SELECT i.short_name,
               SUM(CASE WHEN r.result_type_id = 7 THEN 1 ELSE 0 END) AS innovations,
               SUM(CASE WHEN r.result_type_id = 2 THEN 1 ELSE 0 END) AS innovation_uses,
               SUM(CASE WHEN r.result_type_id = 6 THEN 1 ELSE 0 END) AS knowledge_products,
               SUM(CASE WHEN r.result_type_id = 1 THEN 1 ELSE 0 END) AS policy_changes,
               COUNT(*) AS total_results
        FROM results_by_inititiative rbi
        JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
        JOIN result r ON r.id = rbi.result_id
        WHERE r.is_active = 1 AND rbi.initiative_role_id = 1
        GROUP BY i.short_name
        ORDER BY total_results DESC;
    """
    return _query_rows(conn, sql)


def _get_irl_distribution(conn: sqlite3.Connection) -> list[dict]:
    """Get IRL distribution per initiative.

    Returns list of dicts with keys:
        short_name, irl_7plus, irl_4to6, irl_1to3, irl_0, total
    """
    sql = """
        SELECT i.short_name,
               SUM(CASE WHEN rid.innovation_readiness_level_id >= 18 THEN 1 ELSE 0 END) AS irl_7plus,
               SUM(CASE WHEN rid.innovation_readiness_level_id BETWEEN 15 AND 17
                        THEN 1 ELSE 0 END) AS irl_4to6,
               SUM(CASE WHEN rid.innovation_readiness_level_id BETWEEN 12 AND 14
                        THEN 1 ELSE 0 END) AS irl_1to3,
               SUM(CASE WHEN rid.innovation_readiness_level_id = 11 THEN 1 ELSE 0 END) AS irl_0,
               COUNT(*) AS total
        FROM results_by_inititiative rbi
        JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
        JOIN result r ON r.id = rbi.result_id
        JOIN results_innovations_dev rid ON rid.results_id = r.id AND rid.is_active = 1
        WHERE r.is_active = 1 AND rbi.initiative_role_id = 1
        GROUP BY i.short_name
        ORDER BY total DESC;
    """
    return _query_rows(conn, sql)


def _get_geographic_reach(conn: sqlite3.Connection) -> list[dict]:
    """Get country reach per initiative.

    Returns list of dicts with keys: short_name, countries
    """
    sql = """
        SELECT i.short_name, COUNT(DISTINCT rc.country_id) AS countries
        FROM results_by_inititiative rbi
        JOIN clarisa_initiatives i ON rbi.inititiative_id = i.id
        JOIN result r ON r.id = rbi.result_id
        JOIN result_country rc ON rc.result_id = r.id AND rc.is_active = 1
        WHERE r.is_active = 1 AND rbi.initiative_role_id = 1
        GROUP BY i.short_name
        ORDER BY countries DESC;
    """
    return _query_rows(conn, sql)


def _get_portfolio_totals(conn: sqlite3.Connection) -> dict:
    """Get portfolio-wide summary metrics.

    Returns dict with keys:
        total_results, total_innovations, irl_7plus, total_countries,
        total_initiatives
    """
    total_results = _query_scalar(conn, """
        SELECT COUNT(*) FROM result WHERE is_active = 1;
    """)
    total_innovations = _query_scalar(conn, """
        SELECT COUNT(*)
        FROM result r
        JOIN results_innovations_dev rid ON rid.results_id = r.id AND rid.is_active = 1
        WHERE r.is_active = 1 AND r.result_type_id = 7;
    """)
    irl_7plus = _query_scalar(conn, """
        SELECT COUNT(*)
        FROM result r
        JOIN results_innovations_dev rid ON rid.results_id = r.id AND rid.is_active = 1
        WHERE r.is_active = 1 AND rid.innovation_readiness_level_id >= 18;
    """)
    total_countries = _query_scalar(conn, """
        SELECT COUNT(DISTINCT rc.country_id)
        FROM result_country rc
        JOIN result r ON rc.result_id = r.id
        WHERE rc.is_active = 1 AND r.is_active = 1;
    """)
    total_initiatives = _query_scalar(conn, """
        SELECT COUNT(*) FROM clarisa_initiatives WHERE active = 1;
    """)

    return {
        "total_results": total_results,
        "total_innovations": total_innovations,
        "irl_7plus": irl_7plus,
        "total_countries": total_countries,
        "total_initiatives": total_initiatives,
    }


# ---------------------------------------------------------------------------
# Fuzzy initiative matching
# ---------------------------------------------------------------------------


def _fuzzy_match_initiative(
    query: str, available: list[str]
) -> str | None:
    """Find the closest matching initiative name.

    Uses case-insensitive substring matching. Returns the best match or None.
    """
    query_lower = query.strip().lower()
    if not query_lower:
        return None

    # Exact match (case-insensitive)
    for name in available:
        if name.strip().lower() == query_lower:
            return name

    # Substring match -- prefer shortest name that contains the query
    substring_matches = [
        name for name in available if query_lower in name.strip().lower()
    ]
    if substring_matches:
        # Return the shortest match (most specific)
        return min(substring_matches, key=len)

    # Reverse substring -- query contains the initiative name
    reverse_matches = [
        name for name in available if name.strip().lower() in query_lower
    ]
    if reverse_matches:
        return max(reverse_matches, key=len)

    return None


def _resolve_initiative_names(
    names: list[str], available: list[str]
) -> tuple[list[str], list[str]]:
    """Resolve a list of user-provided names to actual initiative names.

    Returns (resolved_names, unresolved_names).
    """
    resolved = []
    unresolved = []
    for name in names:
        match = _fuzzy_match_initiative(name, available)
        if match:
            resolved.append(match)
        else:
            unresolved.append(name)
    return resolved, unresolved


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------


def _apply_sensitivity(
    projected_values: dict[str, int | float], band: float = SENSITIVITY_BAND
) -> dict[str, dict[str, int | float]]:
    """Add optimistic/pessimistic bounds to projected values."""
    return {
        "pessimistic": {k: round(v * (1 - band)) for k, v in projected_values.items()},
        "expected": {k: round(v) if isinstance(v, float) else v for k, v in projected_values.items()},
        "optimistic": {k: round(v * (1 + band)) for k, v in projected_values.items()},
    }


def _confidence_level(change_pct: float) -> str:
    """Determine confidence level based on the magnitude of change."""
    abs_change = abs(change_pct)
    if abs_change <= 10:
        return "High"
    elif abs_change <= 30:
        return "Medium"
    else:
        return "Low"


# ---------------------------------------------------------------------------
# Scenario modeling functions
# ---------------------------------------------------------------------------


def _model_reallocation(
    baselines: list[dict],
    geo_reach: list[dict],
    params: dict,
) -> dict:
    """Model resource reallocation between initiatives.

    Shifts result-producing capacity from one set of initiatives to another,
    applying a diminishing returns factor to transferred capacity.

    Returns dict with: affected_initiatives, portfolio_impact, methodology
    """
    from_inits = params.get("from_initiatives", [])
    to_inits = params.get("to_initiatives", [])
    shift_pct = params.get("shift_percentage", 10)

    # Clamp shift_pct to reasonable range
    shift_pct = max(1, min(shift_pct, 100))

    available_names = [b["short_name"] for b in baselines]

    # Resolve names
    from_resolved, from_unresolved = _resolve_initiative_names(from_inits, available_names)
    to_resolved, to_unresolved = _resolve_initiative_names(to_inits, available_names)

    if from_unresolved or to_unresolved:
        all_unresolved = from_unresolved + to_unresolved
        return {
            "error": (
                f"Could not match initiative(s): {', '.join(all_unresolved)}. "
                f"Available initiatives: {', '.join(sorted(available_names))}"
            )
        }

    if not from_resolved:
        return {"error": "No 'from_initiatives' specified for reallocation."}
    if not to_resolved:
        return {"error": "No 'to_initiatives' specified for reallocation."}

    # Build lookup
    baseline_lookup = {b["short_name"]: dict(b) for b in baselines}
    geo_lookup = {g["short_name"]: g["countries"] for g in geo_reach}

    # 1. Calculate total results in "from" initiatives
    from_total = sum(baseline_lookup[n]["total_results"] for n in from_resolved)

    # 2. Calculate shifted amount
    shifted_amount = round(from_total * shift_pct / 100)

    # 3. Apply diminishing returns to transferred capacity
    effective_transfer = round(shifted_amount * DIMINISHING_RETURNS_FACTOR)

    # 4. Calculate "to" initiative weights (proportional to current output)
    to_total = sum(baseline_lookup[n]["total_results"] for n in to_resolved)
    if to_total == 0:
        to_total = 1  # avoid division by zero

    # 5. Build per-initiative projections
    affected = []

    # "From" initiatives lose proportionally
    for name in from_resolved:
        bl = baseline_lookup[name]
        init_total = bl["total_results"]
        reduction = round(init_total * shift_pct / 100)
        projected_total = init_total - reduction

        affected.append({
            "short_name": name,
            "role": "source",
            "baseline_results": init_total,
            "projected_results": projected_total,
            "change": -reduction,
            "change_pct": round(-shift_pct, 1),
            "countries": geo_lookup.get(name, 0),
        })

    # "To" initiatives gain proportionally (with diminishing returns)
    for name in to_resolved:
        bl = baseline_lookup[name]
        init_total = bl["total_results"]
        weight = init_total / to_total
        gain = round(effective_transfer * weight)
        projected_total = init_total + gain
        change_pct = round(gain / max(init_total, 1) * 100, 1)

        affected.append({
            "short_name": name,
            "role": "recipient",
            "baseline_results": init_total,
            "projected_results": projected_total,
            "change": gain,
            "change_pct": change_pct,
            "countries": geo_lookup.get(name, 0),
        })

    # 6. Portfolio-level impact
    portfolio_baseline_total = sum(b["total_results"] for b in baselines)
    lost = shifted_amount
    gained = effective_transfer
    net_change = gained - lost
    portfolio_projected = portfolio_baseline_total + net_change

    portfolio_impact = {
        "baseline_total_results": portfolio_baseline_total,
        "projected_total_results": portfolio_projected,
        "net_change": net_change,
        "net_change_pct": round(net_change / max(portfolio_baseline_total, 1) * 100, 1),
        "capacity_lost_in_transfer": lost - gained,
        "transfer_efficiency": DIMINISHING_RETURNS_FACTOR,
    }

    methodology = (
        f"Shifted {shift_pct}% of result-producing capacity ({shifted_amount:,} results) "
        f"from {', '.join(from_resolved)} to {', '.join(to_resolved)}. "
        f"Applied {DIMINISHING_RETURNS_FACTOR}x diminishing returns factor, yielding "
        f"{effective_transfer:,} effective results transferred. "
        f"Net portfolio change: {net_change:+,} results."
    )

    return {
        "affected_initiatives": affected,
        "portfolio_impact": portfolio_impact,
        "methodology": methodology,
        "shifted_amount": shifted_amount,
        "effective_transfer": effective_transfer,
    }


def _model_irl_advancement(
    irl_data: list[dict],
    params: dict,
) -> dict:
    """Model innovation pipeline advancement.

    Moves a percentage of innovations from a target IRL band to the next band.
    Applies valley-of-death factor for IRL 6->7 transitions.

    Returns dict with: affected_initiatives, portfolio_impact, methodology
    """
    advancement_rate = params.get("advancement_rate", 20) / 100
    target_band = params.get("target_irl_band", "3-6")
    target_inits = params.get("target_initiatives", ["all"])

    available_names = [row["short_name"] for row in irl_data]

    # Resolve target initiatives
    if target_inits == ["all"] or "all" in [str(t).lower() for t in target_inits]:
        selected_names = available_names
    else:
        selected_names, unresolved = _resolve_initiative_names(target_inits, available_names)
        if unresolved:
            return {
                "error": (
                    f"Could not match initiative(s): {', '.join(unresolved)}. "
                    f"Available: {', '.join(sorted(available_names))}"
                )
            }

    irl_lookup = {row["short_name"]: dict(row) for row in irl_data}

    # Determine which field to advance from based on target_band
    band_map = {
        "0-2": ("irl_0", "irl_1to3"),       # irl_0 includes 0; advance to 1-3
        "1-3": ("irl_1to3", "irl_4to6"),
        "3-6": ("irl_4to6", "irl_7plus"),
        "4-6": ("irl_4to6", "irl_7plus"),
        "0":   ("irl_0", "irl_1to3"),
    }

    if target_band not in band_map:
        return {
            "error": (
                f"Invalid target_irl_band: '{target_band}'. "
                f"Valid options: {', '.join(sorted(band_map.keys()))}"
            )
        }

    source_field, dest_field = band_map[target_band]

    # Apply valley-of-death factor if advancing into IRL 7+ (from 4-6 band)
    effective_rate = advancement_rate
    crossing_valley = dest_field == "irl_7plus"
    if crossing_valley:
        effective_rate = advancement_rate * IRL_VALLEY_OF_DEATH_FACTOR

    affected = []
    total_advanced = 0
    total_baseline_7plus = 0
    total_projected_7plus = 0

    for name in selected_names:
        if name not in irl_lookup:
            continue
        row = irl_lookup[name]

        source_count = row.get(source_field, 0)
        advancing = round(source_count * effective_rate)
        total_advanced += advancing

        # Build projected IRL distribution
        baseline = {
            "irl_0": row.get("irl_0", 0),
            "irl_1to3": row.get("irl_1to3", 0),
            "irl_4to6": row.get("irl_4to6", 0),
            "irl_7plus": row.get("irl_7plus", 0),
            "total": row.get("total", 0),
        }
        projected = dict(baseline)
        projected[source_field] = baseline[source_field] - advancing
        projected[dest_field] = baseline[dest_field] + advancing

        total_baseline_7plus += baseline["irl_7plus"]
        total_projected_7plus += projected["irl_7plus"]

        if advancing > 0:
            affected.append({
                "short_name": name,
                "baseline_irl": baseline,
                "projected_irl": projected,
                "innovations_advanced": advancing,
                "source_band": target_band,
            })

    # Portfolio-level impact
    total_innovations = sum(row.get("total", 0) for row in irl_data)
    baseline_scaling_pct = round(total_baseline_7plus / max(total_innovations, 1) * 100, 1)
    projected_scaling_pct = round(total_projected_7plus / max(total_innovations, 1) * 100, 1)

    portfolio_impact = {
        "total_innovations": total_innovations,
        "baseline_irl_7plus": total_baseline_7plus,
        "projected_irl_7plus": total_projected_7plus,
        "change_irl_7plus": total_projected_7plus - total_baseline_7plus,
        "baseline_scaling_ready_pct": baseline_scaling_pct,
        "projected_scaling_ready_pct": projected_scaling_pct,
    }

    valley_note = ""
    if crossing_valley:
        valley_note = (
            f" Applied valley-of-death factor ({IRL_VALLEY_OF_DEATH_FACTOR}x) "
            f"for IRL 6->7 transition, reducing effective advancement rate "
            f"from {advancement_rate * 100:.0f}% to {effective_rate * 100:.0f}%."
        )

    scope = "all initiatives" if len(selected_names) == len(available_names) else ", ".join(selected_names)
    methodology = (
        f"Advanced {advancement_rate * 100:.0f}% of innovations in IRL band {target_band} "
        f"to the next band across {scope}. "
        f"{total_advanced:,} innovations advanced.{valley_note}"
    )

    return {
        "affected_initiatives": affected,
        "portfolio_impact": portfolio_impact,
        "methodology": methodology,
        "total_advanced": total_advanced,
    }


def _model_output_scaling(
    baselines: list[dict],
    params: dict,
) -> dict:
    """Model scaling initiative output.

    Applies a scale factor with diminishing returns (factor^SCALING_EXPONENT)
    to all result types for a given initiative.

    Returns dict with: initiative_detail, portfolio_impact, methodology
    """
    initiative_name = params.get("initiative", "")
    scale_factor = params.get("scale_factor", 1.5)

    # Clamp scale factor to reasonable range
    scale_factor = max(0.1, min(scale_factor, 10.0))

    available_names = [b["short_name"] for b in baselines]
    matched = _fuzzy_match_initiative(initiative_name, available_names)

    if not matched:
        return {
            "error": (
                f"Could not match initiative '{initiative_name}'. "
                f"Available: {', '.join(sorted(available_names))}"
            )
        }

    baseline_lookup = {b["short_name"]: dict(b) for b in baselines}
    bl = baseline_lookup[matched]

    # Apply diminishing returns: effective_factor = scale_factor ^ SCALING_EXPONENT
    effective_factor = math.pow(scale_factor, SCALING_EXPONENT)

    result_types = ["innovations", "innovation_uses", "knowledge_products", "policy_changes"]

    baseline_detail = {
        "short_name": matched,
        "innovations": bl["innovations"],
        "innovation_uses": bl["innovation_uses"],
        "knowledge_products": bl["knowledge_products"],
        "policy_changes": bl["policy_changes"],
        "total_results": bl["total_results"],
    }

    projected_detail = {"short_name": matched}
    projected_total = 0
    for rt in result_types:
        projected_val = round(bl[rt] * effective_factor)
        projected_detail[rt] = projected_val
        projected_total += projected_val

    # For remaining result types not explicitly tracked, scale the remainder
    tracked_baseline = sum(bl[rt] for rt in result_types)
    other_baseline = bl["total_results"] - tracked_baseline
    other_projected = round(other_baseline * effective_factor)
    projected_total += other_projected
    projected_detail["other_results"] = other_projected
    projected_detail["total_results"] = projected_total

    baseline_detail["other_results"] = other_baseline

    # Portfolio-level impact
    portfolio_baseline_total = sum(b["total_results"] for b in baselines)
    portfolio_projected = portfolio_baseline_total - bl["total_results"] + projected_total
    net_change = projected_total - bl["total_results"]

    portfolio_impact = {
        "baseline_total_results": portfolio_baseline_total,
        "projected_total_results": portfolio_projected,
        "initiative_baseline": bl["total_results"],
        "initiative_projected": projected_total,
        "initiative_change": net_change,
        "initiative_change_pct": round(net_change / max(bl["total_results"], 1) * 100, 1),
        "portfolio_change_pct": round(net_change / max(portfolio_baseline_total, 1) * 100, 1),
    }

    methodology = (
        f"Applied {scale_factor}x scaling factor to {matched} with diminishing returns "
        f"(exponent {SCALING_EXPONENT}), yielding effective factor of {effective_factor:.2f}x. "
        f"Baseline: {bl['total_results']:,} results -> Projected: {projected_total:,} results "
        f"(+{net_change:,})."
    )

    return {
        "initiative_detail": {
            "baseline": baseline_detail,
            "projected": projected_detail,
        },
        "portfolio_impact": portfolio_impact,
        "methodology": methodology,
    }


def _model_portfolio_focus(
    baselines: list[dict],
    irl_data: list[dict],
    geo_reach: list[dict],
    params: dict,
) -> dict:
    """Model portfolio-wide focus shifts.

    For 'scaling_ready': calculates what proportion of innovations need to
    advance to IRL 7+ to reach a target percentage.
    For 'geographic_expansion': calculates what additional country reach
    is needed to reach a target count.

    Returns dict with: focus_details, portfolio_impact, methodology
    """
    focus_area = params.get("focus_area", "scaling_ready")
    target_value = params.get("target_value", 50)

    if focus_area == "scaling_ready":
        return _model_scaling_ready_focus(irl_data, target_value)
    elif focus_area == "geographic_expansion":
        return _model_geographic_expansion(baselines, geo_reach, target_value)
    else:
        return {
            "error": (
                f"Unknown focus_area: '{focus_area}'. "
                "Valid options: 'scaling_ready', 'geographic_expansion'."
            )
        }


def _model_scaling_ready_focus(
    irl_data: list[dict],
    target_pct: float,
) -> dict:
    """Model what it takes to reach target % of innovations at IRL 7+."""
    total_innovations = sum(row.get("total", 0) for row in irl_data)
    current_7plus = sum(row.get("irl_7plus", 0) for row in irl_data)
    current_pct = round(current_7plus / max(total_innovations, 1) * 100, 1)

    target_count = round(total_innovations * target_pct / 100)
    needed = max(0, target_count - current_7plus)

    # Which initiatives have the most room to grow?
    # Calculate needed advancement per initiative, proportional to their IRL 4-6 pool
    total_irl_4to6 = sum(row.get("irl_4to6", 0) for row in irl_data)

    initiative_needs = []
    for row in irl_data:
        pool = row.get("irl_4to6", 0)
        if pool == 0:
            continue
        weight = pool / max(total_irl_4to6, 1)
        init_needed = round(needed * weight)
        # Apply valley of death factor -- need more to account for losses
        init_needed_raw = round(init_needed / IRL_VALLEY_OF_DEATH_FACTOR) if init_needed > 0 else 0
        advancement_pct = round(init_needed_raw / max(pool, 1) * 100, 1)

        initiative_needs.append({
            "short_name": row["short_name"],
            "current_irl_7plus": row.get("irl_7plus", 0),
            "current_irl_4to6": pool,
            "innovations_to_advance": init_needed,
            "raw_needed_pre_valley": init_needed_raw,
            "advancement_rate_needed_pct": advancement_pct,
            "feasibility": "High" if advancement_pct <= 30 else ("Medium" if advancement_pct <= 60 else "Low"),
        })

    # Sort by innovations_to_advance descending
    initiative_needs.sort(key=lambda x: x["innovations_to_advance"], reverse=True)

    portfolio_impact = {
        "total_innovations": total_innovations,
        "current_irl_7plus": current_7plus,
        "current_scaling_ready_pct": current_pct,
        "target_scaling_ready_pct": target_pct,
        "target_irl_7plus_count": target_count,
        "additional_innovations_needed": needed,
        "gap": needed,
    }

    methodology = (
        f"Target: {target_pct}% of innovations at IRL 7+ ({target_count:,} of {total_innovations:,}). "
        f"Current: {current_pct}% ({current_7plus:,}). "
        f"Gap: {needed:,} innovations need to advance from IRL 4-6 to 7+. "
        f"Valley-of-death factor ({IRL_VALLEY_OF_DEATH_FACTOR}x) applied to account for "
        f"transition losses."
    )

    return {
        "focus_area": "scaling_ready",
        "initiative_needs": initiative_needs[:20],  # Top 20
        "portfolio_impact": portfolio_impact,
        "methodology": methodology,
    }


def _model_geographic_expansion(
    baselines: list[dict],
    geo_reach: list[dict],
    target_countries: int,
) -> dict:
    """Model what it takes to reach a target country count."""
    geo_lookup = {g["short_name"]: g["countries"] for g in geo_reach}
    baseline_lookup = {b["short_name"]: dict(b) for b in baselines}

    # Current max country reach across portfolio
    current_max = max((g["countries"] for g in geo_reach), default=0)
    current_avg = round(sum(g["countries"] for g in geo_reach) / max(len(geo_reach), 1), 1)

    # Initiatives with room to grow (below target)
    expansion_candidates = []
    for row in geo_reach:
        name = row["short_name"]
        current = row["countries"]
        gap = max(0, target_countries - current)
        if gap > 0:
            bl = baseline_lookup.get(name, {})
            expansion_candidates.append({
                "short_name": name,
                "current_countries": current,
                "target_countries": target_countries,
                "gap": gap,
                "current_results": bl.get("total_results", 0),
                "results_per_country": round(bl.get("total_results", 0) / max(current, 1), 1),
            })

    expansion_candidates.sort(key=lambda x: x["gap"], reverse=True)

    # How many initiatives already meet the target?
    meeting_target = sum(1 for g in geo_reach if g["countries"] >= target_countries)

    portfolio_impact = {
        "total_initiatives_with_geo_data": len(geo_reach),
        "initiatives_meeting_target": meeting_target,
        "initiatives_below_target": len(geo_reach) - meeting_target,
        "current_avg_countries": current_avg,
        "current_max_countries": current_max,
        "target_countries": target_countries,
    }

    methodology = (
        f"Target: each initiative reaching {target_countries} countries. "
        f"Currently {meeting_target} of {len(geo_reach)} initiatives meet this target. "
        f"Average country reach: {current_avg}. "
        f"Max: {current_max} countries."
    )

    return {
        "focus_area": "geographic_expansion",
        "expansion_candidates": expansion_candidates[:20],
        "portfolio_impact": portfolio_impact,
        "methodology": methodology,
    }


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------


def _build_comparison_chart(
    title: str,
    baseline_data: list[dict],
    projected_data: list[dict],
    x_key: str,
    metric_key: str,
) -> dict:
    """Build a multiBar chart spec comparing baseline vs projected.

    Uses the same ChartData format as create_chart.py so the frontend can
    render it inline.
    """
    data = []
    for b, p in zip(baseline_data, projected_data):
        data.append({
            x_key: b[x_key],
            "Baseline": b[metric_key],
            "Projected": p[metric_key],
        })
    return {
        "chartType": "multiBar",
        "title": title,
        "description": "[SCENARIO-MODELED] Baseline vs. projected comparison",
        "xAxisKey": x_key,
        "data": data[:20],  # limit to 20 bars for readability
        "series": [
            {"key": "Baseline", "label": "Current (PRMS)", "color": "#427730"},
            {"key": "Projected", "label": "Scenario", "color": "#E37222"},
        ],
    }


def _build_reallocation_chart(affected: list[dict]) -> dict:
    """Build chart for reallocation scenario."""
    data = []
    for item in affected[:20]:
        data.append({
            "Initiative": item["short_name"],
            "Baseline": item["baseline_results"],
            "Projected": item["projected_results"],
        })
    return {
        "chartType": "multiBar",
        "title": "Resource Reallocation: Baseline vs. Projected Results",
        "description": "[SCENARIO-MODELED] Baseline vs. projected comparison",
        "xAxisKey": "Initiative",
        "data": data,
        "series": [
            {"key": "Baseline", "label": "Current (PRMS)", "color": "#427730"},
            {"key": "Projected", "label": "Scenario", "color": "#E37222"},
        ],
    }


def _build_irl_chart(affected: list[dict]) -> dict:
    """Build chart for IRL advancement scenario."""
    data = []
    for item in affected[:20]:
        data.append({
            "Initiative": item["short_name"],
            "Baseline IRL 7+": item["baseline_irl"]["irl_7plus"],
            "Projected IRL 7+": item["projected_irl"]["irl_7plus"],
        })
    return {
        "chartType": "multiBar",
        "title": "IRL Advancement: Scaling-Ready Innovations (IRL 7+)",
        "description": "[SCENARIO-MODELED] Baseline vs. projected IRL 7+ counts",
        "xAxisKey": "Initiative",
        "data": data,
        "series": [
            {"key": "Baseline IRL 7+", "label": "Current IRL 7+ (PRMS)", "color": "#427730"},
            {"key": "Projected IRL 7+", "label": "Projected IRL 7+", "color": "#E37222"},
        ],
    }


def _build_scaling_chart(detail: dict) -> dict:
    """Build chart for output scaling scenario."""
    baseline = detail["baseline"]
    projected = detail["projected"]
    result_types = ["innovations", "innovation_uses", "knowledge_products", "policy_changes"]

    data = []
    for rt in result_types:
        label = rt.replace("_", " ").title()
        data.append({
            "Result Type": label,
            "Baseline": baseline.get(rt, 0),
            "Projected": projected.get(rt, 0),
        })

    return {
        "chartType": "multiBar",
        "title": f"Output Scaling: {baseline['short_name']}",
        "description": "[SCENARIO-MODELED] Baseline vs. projected by result type",
        "xAxisKey": "Result Type",
        "data": data,
        "series": [
            {"key": "Baseline", "label": "Current (PRMS)", "color": "#427730"},
            {"key": "Projected", "label": "Projected", "color": "#E37222"},
        ],
    }


def _build_focus_chart(result: dict) -> dict | None:
    """Build chart for portfolio focus scenario."""
    focus_area = result.get("focus_area", "")

    if focus_area == "scaling_ready":
        needs = result.get("initiative_needs", [])
        if not needs:
            return None
        data = []
        for item in needs[:15]:
            data.append({
                "Initiative": item["short_name"],
                "Current IRL 7+": item["current_irl_7plus"],
                "Need to Advance": item["innovations_to_advance"],
            })
        return {
            "chartType": "multiBar",
            "title": "Scaling-Ready Focus: Current vs. Needed Advancements",
            "description": "[SCENARIO-MODELED] Innovations at IRL 7+ and advancement needed",
            "xAxisKey": "Initiative",
            "data": data,
            "series": [
                {"key": "Current IRL 7+", "label": "Current IRL 7+", "color": "#427730"},
                {"key": "Need to Advance", "label": "Need to Advance", "color": "#E37222"},
            ],
        }
    elif focus_area == "geographic_expansion":
        candidates = result.get("expansion_candidates", [])
        if not candidates:
            return None
        data = []
        for item in candidates[:15]:
            data.append({
                "Initiative": item["short_name"],
                "Current Countries": item["current_countries"],
                "Target": item["target_countries"],
            })
        return {
            "chartType": "multiBar",
            "title": "Geographic Expansion: Current vs. Target Country Reach",
            "description": "[SCENARIO-MODELED] Current country coverage and expansion target",
            "xAxisKey": "Initiative",
            "data": data,
            "series": [
                {"key": "Current Countries", "label": "Current Countries", "color": "#427730"},
                {"key": "Target", "label": "Target", "color": "#E37222"},
            ],
        }

    return None


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------


def _format_reallocation_response(
    description: str,
    result: dict,
    portfolio_totals: dict,
    sensitivity: dict,
    chart_spec: dict | None,
) -> str:
    """Format a reallocation scenario response as structured markdown."""
    lines = []

    lines.append("## Scenario Analysis: Resource Reallocation")
    lines.append("")
    lines.append(
        "> **[SCENARIO-MODELED]** These projections are modeled estimates based on PRMS baseline data "
        "and analytical assumptions. They are NOT PRMS-validated predictions."
    )
    lines.append("")

    # Baseline
    lines.append("### Baseline (Current Portfolio) [PRMS-VALIDATED]")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    pt = portfolio_totals
    lines.append(f"| Total Results | {pt['total_results']:,} |")
    lines.append(f"| Total Innovations | {pt['total_innovations']:,} |")
    lines.append(f"| Scaling-Ready (IRL 7+) | {pt['irl_7plus']:,} |")
    lines.append(f"| Countries Reached | {pt['total_countries']:,} |")
    lines.append(f"| Active Initiatives | {pt['total_initiatives']:,} |")
    lines.append("")

    # Scenario description
    lines.append(f"### Scenario: {description}")
    lines.append("")
    lines.append(result["methodology"])
    lines.append("")

    # Projected outcomes
    pi = result["portfolio_impact"]
    lines.append("### Projected Outcomes [SCENARIO-MODELED]")
    lines.append("")

    lines.append("**Per-Initiative Impact:**")
    lines.append("")
    lines.append("| Initiative | Role | Baseline Results | Projected Results | Change | Change % |")
    lines.append("|-----------|------|-----------------|-------------------|--------|----------|")
    for item in result["affected_initiatives"]:
        change_str = f"{item['change']:+,}"
        lines.append(
            f"| {item['short_name']} | {item['role'].title()} | "
            f"{item['baseline_results']:,} | {item['projected_results']:,} | "
            f"{change_str} | {item['change_pct']:+.1f}% |"
        )
    lines.append("")

    lines.append("**Portfolio-Level Impact:**")
    lines.append("")
    lines.append("| Metric | Baseline | Projected | Change | Confidence |")
    lines.append("|--------|----------|-----------|--------|------------|")

    conf = _confidence_level(pi["net_change_pct"])
    lines.append(
        f"| Total Results | {pi['baseline_total_results']:,} | "
        f"{pi['projected_total_results']:,} | {pi['net_change']:+,} ({pi['net_change_pct']:+.1f}%) | {conf} |"
    )
    lines.append(
        f"| Transfer Efficiency | - | - | "
        f"{pi['transfer_efficiency'] * 100:.0f}% of shifted capacity retained | - |"
    )
    lines.append("")

    # Sensitivity analysis
    lines.append("### Sensitivity Analysis")
    lines.append("| Metric | Pessimistic (-20%) | Expected | Optimistic (+20%) |")
    lines.append("|--------|--------------------|----------|-------------------|")
    for metric in sensitivity["expected"]:
        pess = sensitivity["pessimistic"][metric]
        exp = sensitivity["expected"][metric]
        opt = sensitivity["optimistic"][metric]
        label = metric.replace("_", " ").title()
        lines.append(f"| {label} | {pess:,} | {exp:,} | {opt:,} |")
    lines.append("")

    # Assumptions
    lines.append("### Key Assumptions")
    lines.append(
        "1. Result counts used as proxy for resource allocation "
        "(budget data covers only 5.6% of results) [DATA-LIMITATION]"
    )
    lines.append(f"2. Diminishing returns factor: {DIMINISHING_RETURNS_FACTOR}x for reallocated capacity")
    lines.append(f"3. Sensitivity band: +/-{SENSITIVITY_BAND * 100:.0f}% for optimistic/pessimistic bounds")
    lines.append("4. Recipients absorb transferred capacity proportional to their current output")
    lines.append("")

    lines.append("### Methodology")
    lines.append(result["methodology"])
    lines.append("")

    if chart_spec:
        chart_json = json.dumps(chart_spec, indent=2, ensure_ascii=False)
        lines.append(f"<chart>\n{chart_json}\n</chart>")

    return "\n".join(lines)


def _format_irl_response(
    description: str,
    result: dict,
    portfolio_totals: dict,
    sensitivity: dict,
    chart_spec: dict | None,
) -> str:
    """Format an IRL advancement scenario response."""
    lines = []

    lines.append("## Scenario Analysis: IRL Pipeline Advancement")
    lines.append("")
    lines.append(
        "> **[SCENARIO-MODELED]** These projections are modeled estimates based on PRMS baseline data "
        "and analytical assumptions. They are NOT PRMS-validated predictions."
    )
    lines.append("")

    # Baseline
    lines.append("### Baseline (Current Portfolio) [PRMS-VALIDATED]")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    pt = portfolio_totals
    lines.append(f"| Total Results | {pt['total_results']:,} |")
    lines.append(f"| Total Innovations | {pt['total_innovations']:,} |")
    lines.append(f"| Scaling-Ready (IRL 7+) | {pt['irl_7plus']:,} |")
    lines.append(f"| Countries Reached | {pt['total_countries']:,} |")
    lines.append("")

    # Scenario
    lines.append(f"### Scenario: {description}")
    lines.append("")
    lines.append(result["methodology"])
    lines.append("")

    # Projected outcomes
    pi = result["portfolio_impact"]
    lines.append("### Projected Outcomes [SCENARIO-MODELED]")
    lines.append("")
    lines.append("| Metric | Baseline | Projected | Change | Confidence |")
    lines.append("|--------|----------|-----------|--------|------------|")

    change_7 = pi["change_irl_7plus"]
    change_pct = round(change_7 / max(pi["baseline_irl_7plus"], 1) * 100, 1)
    conf = _confidence_level(change_pct)
    lines.append(
        f"| IRL 7+ (Scaling-Ready) | {pi['baseline_irl_7plus']:,} | "
        f"{pi['projected_irl_7plus']:,} | {change_7:+,} ({change_pct:+.1f}%) | {conf} |"
    )
    lines.append(
        f"| Scaling-Ready % | {pi['baseline_scaling_ready_pct']}% | "
        f"{pi['projected_scaling_ready_pct']}% | "
        f"{pi['projected_scaling_ready_pct'] - pi['baseline_scaling_ready_pct']:+.1f}pp | {conf} |"
    )
    lines.append(f"| Innovations Advanced | - | - | {result['total_advanced']:,} | - |")
    lines.append("")

    # Per-initiative detail (top 10)
    if result["affected_initiatives"]:
        lines.append("**Top Initiatives Affected:**")
        lines.append("")
        lines.append("| Initiative | Baseline IRL 7+ | Projected IRL 7+ | Advanced |")
        lines.append("|-----------|----------------|-----------------|----------|")
        for item in result["affected_initiatives"][:10]:
            lines.append(
                f"| {item['short_name']} | {item['baseline_irl']['irl_7plus']:,} | "
                f"{item['projected_irl']['irl_7plus']:,} | +{item['innovations_advanced']:,} |"
            )
        lines.append("")

    # Sensitivity
    lines.append("### Sensitivity Analysis")
    lines.append("| Metric | Pessimistic (-20%) | Expected | Optimistic (+20%) |")
    lines.append("|--------|--------------------|----------|-------------------|")
    for metric in sensitivity["expected"]:
        pess = sensitivity["pessimistic"][metric]
        exp = sensitivity["expected"][metric]
        opt = sensitivity["optimistic"][metric]
        label = metric.replace("_", " ").title()
        lines.append(f"| {label} | {pess:,} | {exp:,} | {opt:,} |")
    lines.append("")

    # Assumptions
    lines.append("### Key Assumptions")
    lines.append(
        "1. Result counts used as proxy for resource allocation "
        "(budget data covers only 5.6% of results) [DATA-LIMITATION]"
    )
    lines.append(f"2. IRL 6->7 'valley of death' factor: {IRL_VALLEY_OF_DEATH_FACTOR}x advancement rate")
    lines.append(f"3. Sensitivity band: +/-{SENSITIVITY_BAND * 100:.0f}% for optimistic/pessimistic bounds")
    lines.append("4. Advancement distributed proportionally across target initiatives")
    lines.append("")

    lines.append("### Methodology")
    lines.append(result["methodology"])
    lines.append("")

    if chart_spec:
        chart_json = json.dumps(chart_spec, indent=2, ensure_ascii=False)
        lines.append(f"<chart>\n{chart_json}\n</chart>")

    return "\n".join(lines)


def _format_scaling_response(
    description: str,
    result: dict,
    portfolio_totals: dict,
    sensitivity: dict,
    chart_spec: dict | None,
) -> str:
    """Format an output scaling scenario response."""
    lines = []

    lines.append("## Scenario Analysis: Output Scaling")
    lines.append("")
    lines.append(
        "> **[SCENARIO-MODELED]** These projections are modeled estimates based on PRMS baseline data "
        "and analytical assumptions. They are NOT PRMS-validated predictions."
    )
    lines.append("")

    # Baseline
    lines.append("### Baseline (Current Portfolio) [PRMS-VALIDATED]")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    pt = portfolio_totals
    lines.append(f"| Total Results | {pt['total_results']:,} |")
    lines.append(f"| Total Innovations | {pt['total_innovations']:,} |")
    lines.append(f"| Scaling-Ready (IRL 7+) | {pt['irl_7plus']:,} |")
    lines.append(f"| Countries Reached | {pt['total_countries']:,} |")
    lines.append("")

    # Scenario
    lines.append(f"### Scenario: {description}")
    lines.append("")
    lines.append(result["methodology"])
    lines.append("")

    # Projected outcomes
    pi = result["portfolio_impact"]
    detail = result["initiative_detail"]
    bl = detail["baseline"]
    pr = detail["projected"]

    lines.append("### Projected Outcomes [SCENARIO-MODELED]")
    lines.append("")
    lines.append(f"**{bl['short_name']} Detail:**")
    lines.append("")
    lines.append("| Result Type | Baseline | Projected | Change | Confidence |")
    lines.append("|-------------|----------|-----------|--------|------------|")

    for rt in ["innovations", "innovation_uses", "knowledge_products", "policy_changes"]:
        b_val = bl[rt]
        p_val = pr[rt]
        change = p_val - b_val
        change_pct = round(change / max(b_val, 1) * 100, 1)
        conf = _confidence_level(change_pct)
        label = rt.replace("_", " ").title()
        lines.append(
            f"| {label} | {b_val:,} | {p_val:,} | {change:+,} ({change_pct:+.1f}%) | {conf} |"
        )

    total_change = pi["initiative_change"]
    total_change_pct = pi["initiative_change_pct"]
    conf = _confidence_level(total_change_pct)
    lines.append(
        f"| **Total** | **{pi['initiative_baseline']:,}** | **{pi['initiative_projected']:,}** | "
        f"**{total_change:+,} ({total_change_pct:+.1f}%)** | **{conf}** |"
    )
    lines.append("")

    lines.append("**Portfolio-Level Impact:**")
    lines.append("")
    lines.append("| Metric | Baseline | Projected | Change |")
    lines.append("|--------|----------|-----------|--------|")
    lines.append(
        f"| Portfolio Total Results | {pi['baseline_total_results']:,} | "
        f"{pi['projected_total_results']:,} | {total_change:+,} ({pi['portfolio_change_pct']:+.1f}%) |"
    )
    lines.append("")

    # Sensitivity
    lines.append("### Sensitivity Analysis")
    lines.append("| Metric | Pessimistic (-20%) | Expected | Optimistic (+20%) |")
    lines.append("|--------|--------------------|----------|-------------------|")
    for metric in sensitivity["expected"]:
        pess = sensitivity["pessimistic"][metric]
        exp = sensitivity["expected"][metric]
        opt = sensitivity["optimistic"][metric]
        label = metric.replace("_", " ").title()
        lines.append(f"| {label} | {pess:,} | {exp:,} | {opt:,} |")
    lines.append("")

    # Assumptions
    lines.append("### Key Assumptions")
    lines.append(
        "1. Result counts used as proxy for resource allocation "
        "(budget data covers only 5.6% of results) [DATA-LIMITATION]"
    )
    lines.append(
        f"2. Diminishing returns: scale_factor^{SCALING_EXPONENT} "
        f"(e.g., 2.0x investment -> {math.pow(2.0, SCALING_EXPONENT):.2f}x output)"
    )
    lines.append(f"3. Sensitivity band: +/-{SENSITIVITY_BAND * 100:.0f}% for optimistic/pessimistic bounds")
    lines.append("4. All result types scale proportionally")
    lines.append("")

    lines.append("### Methodology")
    lines.append(result["methodology"])
    lines.append("")

    if chart_spec:
        chart_json = json.dumps(chart_spec, indent=2, ensure_ascii=False)
        lines.append(f"<chart>\n{chart_json}\n</chart>")

    return "\n".join(lines)


def _format_focus_response(
    description: str,
    result: dict,
    portfolio_totals: dict,
    sensitivity: dict,
    chart_spec: dict | None,
) -> str:
    """Format a portfolio focus scenario response."""
    lines = []

    focus_area = result.get("focus_area", "unknown")
    title_map = {
        "scaling_ready": "Scaling-Ready Focus",
        "geographic_expansion": "Geographic Expansion Focus",
    }
    lines.append(f"## Scenario Analysis: {title_map.get(focus_area, 'Portfolio Focus')}")
    lines.append("")
    lines.append(
        "> **[SCENARIO-MODELED]** These projections are modeled estimates based on PRMS baseline data "
        "and analytical assumptions. They are NOT PRMS-validated predictions."
    )
    lines.append("")

    # Baseline
    lines.append("### Baseline (Current Portfolio) [PRMS-VALIDATED]")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    pt = portfolio_totals
    lines.append(f"| Total Results | {pt['total_results']:,} |")
    lines.append(f"| Total Innovations | {pt['total_innovations']:,} |")
    lines.append(f"| Scaling-Ready (IRL 7+) | {pt['irl_7plus']:,} |")
    lines.append(f"| Countries Reached | {pt['total_countries']:,} |")
    lines.append("")

    # Scenario
    lines.append(f"### Scenario: {description}")
    lines.append("")
    lines.append(result["methodology"])
    lines.append("")

    # Projected outcomes
    pi = result["portfolio_impact"]
    lines.append("### Projected Outcomes [SCENARIO-MODELED]")
    lines.append("")

    if focus_area == "scaling_ready":
        lines.append("| Metric | Current | Target | Gap |")
        lines.append("|--------|---------|--------|-----|")
        lines.append(
            f"| IRL 7+ Count | {pi['current_irl_7plus']:,} | {pi['target_irl_7plus_count']:,} | "
            f"{pi['gap']:,} |"
        )
        lines.append(
            f"| Scaling-Ready % | {pi['current_scaling_ready_pct']}% | "
            f"{pi['target_scaling_ready_pct']}% | "
            f"{pi['target_scaling_ready_pct'] - pi['current_scaling_ready_pct']:+.1f}pp |"
        )
        lines.append("")

        needs = result.get("initiative_needs", [])
        if needs:
            lines.append("**Per-Initiative Advancement Needed:**")
            lines.append("")
            lines.append(
                "| Initiative | Current IRL 7+ | IRL 4-6 Pool | Need to Advance | "
                "Rate Needed | Feasibility |"
            )
            lines.append("|-----------|---------------|-------------|-----------------|------------|-------------|")
            for item in needs[:15]:
                lines.append(
                    f"| {item['short_name']} | {item['current_irl_7plus']:,} | "
                    f"{item['current_irl_4to6']:,} | {item['innovations_to_advance']:,} | "
                    f"{item['advancement_rate_needed_pct']:.0f}% | {item['feasibility']} |"
                )
            lines.append("")

    elif focus_area == "geographic_expansion":
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Target Countries per Initiative | {pi['target_countries']:,} |")
        lines.append(f"| Initiatives Meeting Target | {pi['initiatives_meeting_target']:,} |")
        lines.append(f"| Initiatives Below Target | {pi['initiatives_below_target']:,} |")
        lines.append(f"| Current Average Countries | {pi['current_avg_countries']} |")
        lines.append(f"| Current Maximum Countries | {pi['current_max_countries']:,} |")
        lines.append("")

        candidates = result.get("expansion_candidates", [])
        if candidates:
            lines.append("**Top Expansion Candidates:**")
            lines.append("")
            lines.append(
                "| Initiative | Current Countries | Target | Gap | Results/Country |"
            )
            lines.append("|-----------|------------------|--------|-----|-----------------|")
            for item in candidates[:15]:
                lines.append(
                    f"| {item['short_name']} | {item['current_countries']:,} | "
                    f"{item['target_countries']:,} | {item['gap']:,} | "
                    f"{item['results_per_country']} |"
                )
            lines.append("")

    # Sensitivity
    lines.append("### Sensitivity Analysis")
    lines.append("| Metric | Pessimistic (-20%) | Expected | Optimistic (+20%) |")
    lines.append("|--------|--------------------|----------|-------------------|")
    for metric in sensitivity["expected"]:
        pess = sensitivity["pessimistic"][metric]
        exp = sensitivity["expected"][metric]
        opt = sensitivity["optimistic"][metric]
        label = metric.replace("_", " ").title()
        lines.append(f"| {label} | {pess:,} | {exp:,} | {opt:,} |")
    lines.append("")

    # Assumptions
    lines.append("### Key Assumptions")
    lines.append(
        "1. Result counts used as proxy for resource allocation "
        "(budget data covers only 5.6% of results) [DATA-LIMITATION]"
    )
    if focus_area == "scaling_ready":
        lines.append(
            f"2. IRL 6->7 'valley of death' factor: {IRL_VALLEY_OF_DEATH_FACTOR}x advancement rate"
        )
        lines.append("3. Advancement distributed proportionally to each initiative's IRL 4-6 pool size")
    elif focus_area == "geographic_expansion":
        lines.append("2. Country reach is compared against a uniform target across all initiatives")
        lines.append("3. Results-per-country ratio indicates current efficiency of geographic spread")
    lines.append(f"{3 if focus_area == 'scaling_ready' else 3}. "
                 f"Sensitivity band: +/-{SENSITIVITY_BAND * 100:.0f}% for optimistic/pessimistic bounds")
    lines.append("")

    lines.append("### Methodology")
    lines.append(result["methodology"])
    lines.append("")

    if chart_spec:
        chart_json = json.dumps(chart_spec, indent=2, ensure_ascii=False)
        lines.append(f"<chart>\n{chart_json}\n</chart>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------


@tool(
    "scenario_analysis",
    "Run 'what if' portfolio scenario analysis on CGIAR research data. "
    "Models hypothetical changes (resource reallocation, innovation pipeline "
    "advancement, output scaling, portfolio focus shifts) against current PRMS "
    "baseline data. Returns structured comparison with sensitivity analysis. "
    "Results are clearly labeled [SCENARIO-MODELED] distinct from [PRMS-VALIDATED] data.",
    {
        "scenario_type": str,
        "description": str,
        "parameters": dict,
        "include_chart": bool,
    },
)
async def scenario_analysis(args: dict) -> dict:
    """Run a 'what if' portfolio scenario analysis.

    Args (via tool schema):
        scenario_type (required): One of 'reallocation', 'irl_advancement',
                                  'output_scaling', 'portfolio_focus'.
        description (required): Human-readable scenario description.
        parameters (required): Type-specific parameters dict.
        include_chart (optional): Generate comparison chart spec (default True).

    Returns:
        MCP-formatted response with scenario analysis results.
    """
    scenario_type = args.get("scenario_type", "").strip()
    description = args.get("description", "").strip()
    parameters = args.get("parameters", {})
    include_chart = args.get("include_chart", True)

    # --- Validation ---

    if not scenario_type:
        return error_response(
            "Missing required parameter 'scenario_type'. "
            f"Must be one of: {', '.join(VALID_SCENARIO_TYPES)}"
        )

    if scenario_type not in VALID_SCENARIO_TYPES:
        return error_response(
            f"Invalid scenario_type '{scenario_type}'. "
            f"Must be one of: {', '.join(VALID_SCENARIO_TYPES)}"
        )

    if not description:
        return error_response(
            "Missing required parameter 'description'. "
            "Provide a human-readable description of the scenario."
        )

    if not isinstance(parameters, dict) or not parameters:
        return error_response(
            "Missing or invalid 'parameters'. "
            "Provide a dict with type-specific parameters for the scenario."
        )

    # --- Connect to PRMS database ---

    try:
        conn = _get_connection()
    except FileNotFoundError as exc:
        return error_response(
            f"PRMS database not found: {exc}. "
            "Set PRMS_DB_PATH environment variable to the correct path."
        )
    except Exception as exc:
        return error_response(f"Failed to connect to PRMS database: {exc}")

    try:
        # --- Pull baseline data ---

        try:
            portfolio_totals = _get_portfolio_totals(conn)
        except Exception as exc:
            logger.warning("Failed to get portfolio totals: %s", exc)
            portfolio_totals = {
                "total_results": 0,
                "total_innovations": 0,
                "irl_7plus": 0,
                "total_countries": 0,
                "total_initiatives": 0,
            }

        # --- Route to scenario-specific modeling ---

        if scenario_type == "reallocation":
            try:
                baselines = _get_initiative_baselines(conn)
                geo_reach = _get_geographic_reach(conn)
            except Exception as exc:
                return error_response(f"Failed to query baseline data: {exc}")

            result = _model_reallocation(baselines, geo_reach, parameters)

            if "error" in result:
                return error_response(result["error"])

            # Sensitivity on portfolio-level projected values
            pi = result["portfolio_impact"]
            sensitivity = _apply_sensitivity({
                "projected_total_results": pi["projected_total_results"],
                "net_change": pi["net_change"],
            })

            # Chart
            chart_spec = None
            if include_chart and result["affected_initiatives"]:
                chart_spec = _build_reallocation_chart(result["affected_initiatives"])

            response_text = _format_reallocation_response(
                description, result, portfolio_totals, sensitivity, chart_spec,
            )

        elif scenario_type == "irl_advancement":
            try:
                irl_data = _get_irl_distribution(conn)
            except Exception as exc:
                return error_response(f"Failed to query IRL data: {exc}")

            result = _model_irl_advancement(irl_data, parameters)

            if "error" in result:
                return error_response(result["error"])

            pi = result["portfolio_impact"]
            sensitivity = _apply_sensitivity({
                "projected_irl_7plus": pi["projected_irl_7plus"],
                "innovations_advanced": result["total_advanced"],
            })

            chart_spec = None
            if include_chart and result["affected_initiatives"]:
                chart_spec = _build_irl_chart(result["affected_initiatives"])

            response_text = _format_irl_response(
                description, result, portfolio_totals, sensitivity, chart_spec,
            )

        elif scenario_type == "output_scaling":
            try:
                baselines = _get_initiative_baselines(conn)
            except Exception as exc:
                return error_response(f"Failed to query baseline data: {exc}")

            result = _model_output_scaling(baselines, parameters)

            if "error" in result:
                return error_response(result["error"])

            pi = result["portfolio_impact"]
            sensitivity = _apply_sensitivity({
                "initiative_projected_results": pi["initiative_projected"],
                "portfolio_projected_results": pi["projected_total_results"],
            })

            chart_spec = None
            if include_chart:
                chart_spec = _build_scaling_chart(result["initiative_detail"])

            response_text = _format_scaling_response(
                description, result, portfolio_totals, sensitivity, chart_spec,
            )

        elif scenario_type == "portfolio_focus":
            try:
                baselines = _get_initiative_baselines(conn)
                irl_data = _get_irl_distribution(conn)
                geo_reach = _get_geographic_reach(conn)
            except Exception as exc:
                return error_response(f"Failed to query baseline data: {exc}")

            result = _model_portfolio_focus(baselines, irl_data, geo_reach, parameters)

            if "error" in result:
                return error_response(result["error"])

            pi = result["portfolio_impact"]

            # Build sensitivity values based on focus area
            if result.get("focus_area") == "scaling_ready":
                sensitivity = _apply_sensitivity({
                    "additional_innovations_needed": pi.get("additional_innovations_needed", 0),
                    "target_irl_7plus_count": pi.get("target_irl_7plus_count", 0),
                })
            else:
                sensitivity = _apply_sensitivity({
                    "initiatives_below_target": pi.get("initiatives_below_target", 0),
                    "target_countries": pi.get("target_countries", 0),
                })

            chart_spec = None
            if include_chart:
                chart_spec = _build_focus_chart(result)

            response_text = _format_focus_response(
                description, result, portfolio_totals, sensitivity, chart_spec,
            )

        else:
            return error_response(f"Unhandled scenario_type: {scenario_type}")

        return success_response(response_text)

    except Exception as exc:
        logger.exception("Unexpected error in scenario_analysis")
        return error_response(f"Unexpected error during scenario analysis: {exc}")
    finally:
        conn.close()
