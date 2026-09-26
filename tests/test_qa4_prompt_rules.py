"""QA round 4 (2026-09-27) prompt-text guards: D4, D5, D16 and the theme-question UX rule."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.system_prompt import build_system_prompt  # noqa: E402


@pytest.fixture(scope="module")
def prompt() -> str:
    return build_system_prompt()


def test_download_paths_carry_no_scheme(prompt):
    """D4: `sandbox:/…` links render dead."""
    assert "never add a `sandbox:`, `file://` or any other scheme" in prompt


def test_titles_are_quoted_verbatim(prompt):
    """D5: titles were paraphrased (one with an invented qualifier) under a verbatim claim."""
    assert "**Quote PRMS titles verbatim.**" in prompt
    rule = prompt.split("**Quote PRMS titles verbatim.**", 1)[1].split("\n", 1)[0]
    for phrase in ('end with "…"', "never paraphrase", "add qualifiers", '"as stored in PRMS"'):
        assert phrase in rule


def test_prms_query_keeps_titles_long_enough_to_quote():
    """D5: the table view cut titles at 80 characters (73 % of PRMS titles are longer)."""
    from synapsis.tools.prms_query import TITLE_CELL_LIMIT, _format_results_text

    title = (
        "Evidence on the cost-effectiveness and benefits distribution of investments in "
        "infrastructure at value chain nodes for the reduction of zoonotic transmission, "
        "improvement of food safety, and identification of appropriate financing"
    )
    assert len(title) < TITLE_CELL_LIMIT
    rows = [{"result_code": 3426, "title": title, "description": "d" * 300}]
    out = _format_results_text(rows, ["result_code", "title", "description"], None, "SELECT 1", ["result"])
    assert title in out                     # full title, verbatim
    assert "d" * 77 + "..." in out          # other long text still cut at 80
    assert "d" * 78 not in out
    long_title = "T" * 400
    out = _format_results_text([{"short_title": long_title}], ["short_title"], None, "SELECT 1", ["result"])
    assert "T" * (TITLE_CELL_LIMIT - 3) + "..." in out and "T" * (TITLE_CELL_LIMIT - 2) not in out


def test_specialists_also_quote_titles_verbatim():
    from synapsis.agents.definitions import PRMS_COUNTING_RULES

    assert "Quote PRMS titles verbatim" in PRMS_COUNTING_RULES
