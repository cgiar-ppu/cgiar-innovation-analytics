"""L2-04 / L2-05 / L2-14 / L2-15 + data notes: prompt-text guards.

The agent's numbers depend on the prompts. These assertions keep the superseded
"calibrated" totals, row-count recipes and developer-machine paths out, and keep
the counting rules, the data-source statement and the W3/bilateral QA caveat in.
"""

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.agents.definitions import PRMS_COUNTING_RULES, SUBAGENTS  # noqa: E402
from synapsis.system_prompt import build_system_prompt  # noqa: E402

REFERENCES = Path(__file__).resolve().parent.parent / "references"


@pytest.fixture(scope="module")
def prompt() -> str:
    return build_system_prompt()


class TestOrchestratorPrompt:

    @pytest.mark.parametrize("stale", ["2,755", "2755", "2,804", "5,615", "197 tables", "100-row"])
    def test_superseded_figures_are_gone(self, prompt, stale):
        assert stale not in prompt

    def test_no_developer_machine_paths(self, prompt):
        assert "/Users/smithai" not in prompt

    def test_reference_map_lists_only_shipped_files(self, prompt):
        section = prompt.split("## REFERENCE FILE MAP", 1)[1].split("## MANDATORY", 1)[0]
        for path in re.findall(r"`([^`]+\.md)`", section):
            assert Path(path).is_file(), path

    def test_counting_rules_are_present(self, prompt):
        assert "Counting rules" in prompt
        assert "COUNT(DISTINCT result_code)" in prompt
        assert "((source='Result' AND status_id=2) OR (source='API' AND status_id=6))" in prompt

    def test_cross_type_total_recipe_has_the_quality_gate(self, prompt):
        recipe = prompt.split("Cross-type total counts", 1)[1][:900]
        assert "status_id = 2" in recipe and "status_id = 6" in recipe
        assert "is_discontinued" not in recipe

    def test_per_year_recipe_is_alive_in_year_not_a_growth_trend(self, prompt):
        assert "matches the official dashboard totals (2022=62" not in prompt
        assert "not a growth" in prompt or "not growth" in prompt

    def test_data_source_is_named_with_snapshot_dates(self, prompt):
        from synapsis.prms_snapshot import get_snapshot_info

        assert "CGIAR PRMS Reporting" in prompt
        info = get_snapshot_info()
        if info.available and info.data_as_of:
            assert info.data_as_of in prompt.split("### Data source", 1)[1][:800]

    def test_bilateral_qa_caveat_is_present(self, prompt):
        assert "not QA'd in PRMS" in prompt
        assert "Center level" in prompt
        assert "fully quality-assured" not in prompt


class TestSubAgentPrompts:

    def test_prms_data_analyst_carries_the_counting_rules(self):
        text = SUBAGENTS["prms_data_analyst"].prompt
        assert PRMS_COUNTING_RULES in text
        assert "COUNT(DISTINCT result_code)" in text
        assert "status_id = 6" in text
        assert "open reporting phases" in text.lower() or "Exclude open reporting phases" in text

    @pytest.mark.parametrize("name", ["innovation_strategy_advisor", "research_synthesizer",
                                      "prms_data_analyst_sonnet_efficient",
                                      "prms_data_analyst_opus_powerful"])
    def test_every_prms_capable_agent_gets_the_rules(self, name):
        assert "PRMS COUNTING RULES" in SUBAGENTS[name].prompt

    def test_prms_data_analyst_templates_never_count_rows(self):
        text = SUBAGENTS["prms_data_analyst"].prompt
        body = text.split("PRMS COUNTING RULES", 1)[0]
        assert "COUNT(*)" not in body
        assert "is_discontinued IS NULL" not in body
        for stale in ("197-table", "32,005", "100-row", "INIT-01 to INIT-35"):
            assert stale not in text
        assert "197-table" not in SUBAGENTS["prms_data_analyst"].description

    def test_rules_state_method_snapshot_source_and_caveats(self):
        for needle in ("snapshot", "CGIAR PRMS Reporting", "not QA'd in PRMS", "not growth"):
            assert needle in PRMS_COUNTING_RULES


class TestReferences:

    def test_schema_reference_has_no_calibrated_2755_block(self):
        text = (REFERENCES / "prms_schema_reference.md").read_text()
        assert "2,755" not in text
        assert "calibrated against PRMS Results Dashboard" not in text

    def test_data_guide_carries_source_and_bilateral_notes(self):
        text = (REFERENCES / "prms_data_guide.md").read_text()
        assert "CGIAR PRMS Reporting" in text
        assert "not QA'd in PRMS" in text
        assert "Center level" in text
