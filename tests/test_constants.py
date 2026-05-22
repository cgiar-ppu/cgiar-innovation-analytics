"""
Tests for synapsis/constants.py

Covers the is_aup_error() utility function: known AUP patterns, case
insensitivity, and non-matching (normal) error messages.
"""

import pytest
from synapsis.constants import is_aup_error, AUP_ERROR_PATTERNS


# ---------------------------------------------------------------------------
# is_aup_error tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "This request violates our usage policy",
    "Unable to respond to this request due to safety policy",
    "Content policy restriction applied",
    "This appears to violate our guidelines",
    "See /aup for more information",
    "AUP violation detected",
])
def test_is_aup_error_matches(message: str):
    """Known AUP-related error messages are correctly detected."""
    assert is_aup_error(message) is True, (
        f"Expected is_aup_error to return True for: {message!r}"
    )


@pytest.mark.parametrize("message,pattern", [
    ("USAGE POLICY violation", "usage policy"),
    ("Unable To Respond To This Request", "unable to respond to this request"),
    ("CONTENT POLICY Enforced", "content policy"),
    ("VIOLATE terms", "violate"),
    ("SAFETY POLICY breach", "safety policy"),
])
def test_is_aup_error_case_insensitive(message: str, pattern: str):
    """is_aup_error is case-insensitive — uppercase messages are still detected."""
    assert is_aup_error(message) is True, (
        f"Expected case-insensitive match for {message!r} with pattern {pattern!r}"
    )


@pytest.mark.parametrize("message", [
    "Connection timeout after 30 seconds",
    "File not found: data.csv",
    "KeyError: 'session_id'",
    "IndexError: list index out of range",
    "Network error: DNS lookup failed",
    "",
    "Everything looks good",
])
def test_is_aup_error_no_match(message: str):
    """Normal (non-AUP) error messages are not flagged as AUP violations."""
    assert is_aup_error(message) is False, (
        f"Expected is_aup_error to return False for: {message!r}"
    )


def test_aup_patterns_are_nonempty():
    """Sanity check: the AUP_ERROR_PATTERNS list must contain at least one entry."""
    assert len(AUP_ERROR_PATTERNS) > 0
