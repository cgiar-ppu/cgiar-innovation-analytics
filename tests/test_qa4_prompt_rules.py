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
