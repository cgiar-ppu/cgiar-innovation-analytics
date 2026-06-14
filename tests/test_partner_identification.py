"""
Tests for the partner identification tool.

Tests cover:
- Parameter validation (at least one criterion required)
- PRMS partner queries by country, region, initiative, topic
- Innovation readiness filtering
- Partner type filtering
- Relevance scoring
- Response structure and attribution labels
- Edge cases (no results, sparse data)
"""

import asyncio
import pytest
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.tools.partner_identification import (
    partner_identification,
    _build_partner_query,
    _build_web_search_query,
    _compute_relevance_scores,
    PRMS_DB_PATH,
    INSTITUTION_TYPE_CATEGORIES,
    PARTNERSHIP_ROLES,
)

# The @tool decorator wraps the async function into an SdkMcpTool object.
# To call it directly in tests, we use the .handler attribute.
_handler = partner_identification.handler


# ---------------------------------------------------------------------------
# Helper to run async tool function synchronously
# ---------------------------------------------------------------------------

def run_partner_search(**kwargs) -> dict:
    """Execute partner_identification synchronously and return the result dict."""
    return asyncio.run(_handler(kwargs))


def get_text(result: dict) -> str:
    """Extract the text content from an MCP tool response."""
    return result["content"][0]["text"]


def is_error(result: dict) -> bool:
    """Check if the result is an error response."""
    return result.get("is_error", False)


# ---------------------------------------------------------------------------
# Unit tests: Parameter validation
# ---------------------------------------------------------------------------

class TestParameterValidation:

    def test_no_parameters_returns_error(self):
        """At least one search criterion is required."""
        result = run_partner_search()
        assert is_error(result)
        assert "At least one search criterion" in get_text(result)

    def test_invalid_irl_min_too_high(self):
        """IRL must be between 0 and 9."""
        result = run_partner_search(innovation_readiness_min=10)
        assert is_error(result)
        assert "between 0 and 9" in get_text(result)

    def test_invalid_irl_min_negative(self):
        """IRL must be between 0 and 9."""
        result = run_partner_search(innovation_readiness_min=-1)
        assert is_error(result)
        assert "between 0 and 9" in get_text(result)


# ---------------------------------------------------------------------------
# Unit tests: Query building
# ---------------------------------------------------------------------------

class TestQueryBuilding:

    def test_country_filter_builds_join(self):
        """Country filter should add result_country JOIN."""
        sql, params = _build_partner_query(country="Kenya")
        assert "result_country" in sql
        assert "clarisa_countries" in sql
        assert any("Kenya" in str(p) for p in params)

    def test_region_filter_builds_join(self):
        """Region filter should add result_region JOIN."""
        sql, params = _build_partner_query(region="Eastern Africa")
        assert "result_region" in sql
        assert "clarisa_regions" in sql

    def test_initiative_filter_builds_join(self):
        """Initiative filter should add results_by_inititiative JOIN."""
        sql, params = _build_partner_query(initiative="Accelerated Breeding")
        assert "results_by_inititiative" in sql
        assert "clarisa_initiatives" in sql

    def test_result_type_innovation(self):
        """Result type 'innovation' should map to type_id 7."""
        sql, params = _build_partner_query(result_type="innovation")
        assert "result_type_id = ?" in sql
        assert 7 in params

    def test_irl_filter_builds_join(self):
        """IRL filter should add results_innovations_dev JOIN."""
        sql, params = _build_partner_query(innovation_readiness_min=7)
        assert "results_innovations_dev" in sql
        assert "clarisa_innovation_readiness_level" in sql
        assert 7 in params

    def test_topic_filter_uses_like(self):
        """Topic filter should search result titles with LIKE."""
        sql, params = _build_partner_query(topic="soil health")
        assert "r.title LIKE ?" in sql
        assert "%soil health%" in params

    def test_partner_type_filter(self):
        """Partner type filter should constrain institution_type_code."""
        sql, params = _build_partner_query(
            country="India", partner_types=["NGO"]
        )
        assert "institution_type_code IN" in sql

    def test_combined_filters(self):
        """Multiple filters should be combined with AND."""
        sql, params = _build_partner_query(
            country="Kenya", initiative="Breeding", result_type="innovation"
        )
        assert "result_country" in sql
        assert "results_by_inititiative" in sql
        assert "result_type_id" in sql


# ---------------------------------------------------------------------------
# Unit tests: Web search query building
# ---------------------------------------------------------------------------

class TestWebSearchQuery:

    def test_basic_query(self):
        """Should include topic and agricultural research."""
        query = _build_web_search_query(topic="soil health", country="Kenya")
        assert "soil health" in query
        assert "Kenya" in query
        assert "agricultural research" in query

    def test_region_fallback(self):
        """Should use region when country is not specified."""
        query = _build_web_search_query(topic="climate", region="South Asia")
        assert "South Asia" in query

    def test_partner_type_terms(self):
        """Should include appropriate search terms for partner types."""
        query = _build_web_search_query(
            topic="breeding", partner_types=["NGO", "Private Sector"]
        )
        assert "NGO" in query


# ---------------------------------------------------------------------------
# Unit tests: Relevance scoring
# ---------------------------------------------------------------------------

class TestRelevanceScoring:

    def test_scores_are_computed(self):
        """All partners should get a relevance score."""
        partners = [
            {"partnership_results": 100, "partnership_roles": "Partner,Actor",
             "country_coverage": ["Kenya", "Tanzania"], "scaling_ready_pct": 50,
             "initiative_history": ["Init A (20 results)", "Init B (10 results)"]},
            {"partnership_results": 10, "partnership_roles": "Partner",
             "country_coverage": ["Uganda"], "scaling_ready_pct": 0,
             "initiative_history": ["Init A (5 results)"]},
        ]
        scored = _compute_relevance_scores(partners, True, True, True)
        assert all("relevance_score" in p for p in scored)
        # Higher result count should score higher
        assert scored[0]["relevance_score"] > scored[1]["relevance_score"]

    def test_scores_bounded_0_100(self):
        """Scores should not exceed 100."""
        partners = [
            {"partnership_results": 1000, "partnership_roles": "Partner,Actor,Core Innovation Package Partner",
             "country_coverage": ["Kenya", "Tanzania", "Uganda", "Ethiopia", "Zambia"],
             "scaling_ready_pct": 100,
             "initiative_history": ["A (1)", "B (1)", "C (1)", "D (1)", "E (1)"]},
        ]
        scored = _compute_relevance_scores(partners, True, True, True)
        assert scored[0]["relevance_score"] <= 100

    def test_sorted_by_score(self):
        """Partners should be sorted by relevance score descending."""
        partners = [
            {"partnership_results": 5, "partnership_roles": "Partner",
             "country_coverage": [], "initiative_history": []},
            {"partnership_results": 50, "partnership_roles": "Partner,Actor",
             "country_coverage": ["Kenya"], "initiative_history": ["A (10)"]},
        ]
        scored = _compute_relevance_scores(partners, False, False, False)
        assert scored[0]["partnership_results"] == 50  # Higher should be first


# ---------------------------------------------------------------------------
# Integration tests: Real PRMS database queries
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.isfile(PRMS_DB_PATH),
    reason="PRMS database not available"
)
class TestPRMSIntegration:

    def test_search_by_country(self):
        """Should find partners with results in Kenya."""
        result = run_partner_search(country="Kenya")
        assert not is_error(result)
        text = get_text(result)
        assert "PRMS-Validated Partners" in text
        assert "[PRMS-VALIDATED]" in text
        # KALRO should appear (they have 356 results in Kenya)
        assert "KALRO" in text

    def test_search_by_initiative(self):
        """Should find partners for Accelerated Breeding."""
        result = run_partner_search(initiative="Breed")
        assert not is_error(result)
        text = get_text(result)
        assert "PRMS-Validated Partners" in text
        # NARO should appear (top partner for breeding)
        assert "NARO" in text

    def test_search_by_innovation_irl7(self):
        """Should find partners linked to IRL 7+ innovations."""
        result = run_partner_search(
            innovation_readiness_min=7,
            result_type="innovation",
        )
        assert not is_error(result)
        text = get_text(result)
        assert "PRMS-Validated Partners" in text
        assert "Relevance Score" in text

    def test_search_by_topic(self):
        """Should find partners by topic keyword."""
        result = run_partner_search(topic="climate")
        assert not is_error(result)
        text = get_text(result)
        # Should have some results (climate is a common topic)
        assert "Partner Identification Results" in text

    def test_search_by_region(self):
        """Should find partners active in South Asia."""
        result = run_partner_search(region="Southern Asia")
        assert not is_error(result)
        text = get_text(result)
        assert "PRMS-Validated Partners" in text
        # ICAR (Indian Council) should appear
        assert "ICAR" in text

    def test_combined_country_and_type(self):
        """Should filter by country AND partner type."""
        result = run_partner_search(
            country="Kenya",
            partner_types=["NGO"],
        )
        assert not is_error(result)
        text = get_text(result)
        assert "Partner Identification Results" in text

    def test_web_suggestions_included_by_default(self):
        """Should include web search instructions by default."""
        result = run_partner_search(country="Kenya")
        assert not is_error(result)
        text = get_text(result)
        assert "Web Search Enrichment" in text
        assert "WEB-SOURCED" in text

    def test_web_suggestions_can_be_disabled(self):
        """Should exclude web search when include_web_suggestions=False."""
        result = run_partner_search(
            country="Kenya",
            include_web_suggestions=False,
        )
        assert not is_error(result)
        text = get_text(result)
        assert "Web Search Enrichment" not in text

    def test_no_results_graceful(self):
        """Should handle gracefully when no partners match."""
        result = run_partner_search(topic="zzz_nonexistent_topic_xyz")
        assert not is_error(result)
        text = get_text(result)
        assert "No partners found" in text or "PRMS partners found: 0" in text

    def test_response_has_metadata(self):
        """Response should include execution metadata."""
        result = run_partner_search(country="Kenya")
        assert not is_error(result)
        text = get_text(result)
        assert "PRMS Database (snapshot 2026-03-18)" in text
        assert "Query executed in:" in text
