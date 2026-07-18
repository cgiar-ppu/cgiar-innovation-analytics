"""Tests for the PRMS result-code citation resolver (July-7 Step 2).

The load-bearing test is the NEGATIVE one: no citation URL the resolver can
produce may ever point at a session-gated PRMS detail page. This is the exact
mistake the feature's hard constraint exists to prevent.
"""

import pytest

from synapsis.tools.result_code_citation import (
    resolve_result_code_url,
    normalize_result_code,
    linkify_result_codes,
    is_session_gated_url,
    assert_no_session_gated_url,
    PUBLIC_RESULTS_DASHBOARD,
)


# ---------------------------------------------------------------------------
# Happy path — public URLs
# ---------------------------------------------------------------------------

def test_resolve_numeric_code():
    url = resolve_result_code_url(28583)
    assert url is not None
    assert url.startswith("https://www.cgiar.org/food-security-impact/results-dashboard")
    assert "28583" in url


def test_resolve_r_prefixed_code():
    assert resolve_result_code_url("R28583") == resolve_result_code_url("28583")


def test_normalize_strips_prefix():
    assert normalize_result_code("R123") == "123"
    assert normalize_result_code(" 456 ") == "456"
    assert normalize_result_code("not-a-code") is None


def test_public_dashboard_constant_is_public():
    assert PUBLIC_RESULTS_DASHBOARD.startswith("https://www.cgiar.org")
    assert not is_session_gated_url(PUBLIC_RESULTS_DASHBOARD)


# ---------------------------------------------------------------------------
# NEGATIVE TEST (the whole point) — never emit a session-gated URL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "gated_url",
    [
        "https://reporting.cgiar.org/result-details/28583?phase=1",
        "https://reporting.cgiar.org/",
        "https://prms.cgiar.org/result/28583",
        "https://www.cgiar.org/food-security-impact/results-dashboard/result-details/28583",
    ],
)
def test_session_gated_patterns_detected(gated_url):
    assert is_session_gated_url(gated_url) is True
    with pytest.raises(ValueError):
        assert_no_session_gated_url(gated_url)


def test_resolver_never_emits_session_gated_url():
    # Exhaustively confirm: for a spread of codes, the resolved URL is never gated.
    for code in [1, 42, 28583, 999999, "R100000"]:
        url = resolve_result_code_url(code)
        assert url is not None
        assert not is_session_gated_url(url), f"resolver produced a gated URL for {code}: {url}"


def test_malformed_code_degrades_to_none():
    # Never guess, never emit a gated link — return None instead.
    assert resolve_result_code_url("") is None
    assert resolve_result_code_url("abc") is None
    assert resolve_result_code_url(None) is None


# ---------------------------------------------------------------------------
# Post-processing — linkify bracketed tokens
# ---------------------------------------------------------------------------

def test_linkify_bracketed_tokens():
    text = "This innovation [R28583] reached IRL 9, and [12345] is also relevant."
    out = linkify_result_codes(text)
    assert "[R28583](https://www.cgiar.org" in out
    assert "[R12345](https://www.cgiar.org" in out
    assert not is_session_gated_url(out)


def test_linkify_leaves_existing_markdown_links_untouched():
    text = "Already linked [R28583](https://www.cgiar.org/x) stays as-is."
    out = linkify_result_codes(text)
    # The token is already followed by "(" so it must not be double-linked.
    assert out.count("https://www.cgiar.org/x") == 1


def test_linkify_empty_and_none():
    assert linkify_result_codes("") == ""
    assert linkify_result_codes(None) == ""
