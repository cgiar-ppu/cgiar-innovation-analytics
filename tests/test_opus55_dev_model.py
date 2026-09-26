"""Opus 5.5 availability: curated, backed by a CLI new enough to serve it, exposed on DEV only."""
import re
from pathlib import Path

from synapsis.constants import SELECTABLE_MODELS

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = (ROOT / ".github/workflows/deploy.yml").read_text()


def test_opus55_is_curated_with_plain_id_and_label():
    entry = next(m for m in SELECTABLE_MODELS if m["id"] == "claude-opus-5-5")
    assert entry["label"] == "Opus 5.5"
    # Native 1M model: the id must not carry the legacy [1m] suffix.
    assert "[" not in entry["id"]


def _version(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.split("."))


def test_sdk_bundles_cli_that_serves_opus55():
    """The API rejects Opus 5.5 below Claude Code 2.1.280 ("version 2.1.280 or newer is required")."""
    import claude_agent_sdk
    from claude_agent_sdk._cli_version import __cli_version__

    assert _version(__cli_version__) >= (2, 1, 280), __cli_version__
    for req in ("requirements.txt", "requirements-macos.txt"):
        pin = re.search(r"claude-agent-sdk==([\d.]+)", (ROOT / req).read_text()).group(1)
        assert _version(pin) >= (0, 2, 159), (req, pin)
    assert _version(claude_agent_sdk.__version__) >= (0, 2, 159)


def test_deploy_exposes_opus55_on_dev_only():
    m = re.search(
        r"SYNAPSIS_AVAILABLE_MODELS=\\\"\$\{\{ env\.STAGE == 'dev' && '([^']+)' \|\| '([^']+)' \}\}\\\"",
        DEPLOY,
    )
    assert m, "SYNAPSIS_AVAILABLE_MODELS must be stage-conditional"
    dev, other = m.group(1).split(","), m.group(2).split(",")
    assert "claude-opus-5-5" in dev
    assert "claude-opus-5-5" not in other
    # Staging/prod list is unchanged from the 14-Sep release.
    assert other == ["claude-sonnet-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-4-6", "claude-opus-4-8[1m]"]
    assert "SYNAPSIS_MODEL=claude-sonnet-5" in DEPLOY  # default unchanged


def test_dev_exposes_opus55_to_admins_but_not_researchers():
    """Role policy on top of the DEV list: admins keep Opus 5.5, researchers
    (and invited testers) get only the default Sonnet 5 unless
    IA_RESEARCHER_MODELS says otherwise."""
    from unittest.mock import patch
    from synapsis.runtime_policy import allowed_models_for_role

    m = re.search(
        r"SYNAPSIS_AVAILABLE_MODELS=\\\"\$\{\{ env\.STAGE == 'dev' && '([^']+)' \|\| '([^']+)' \}\}\\\"",
        DEPLOY,
    )
    dev = m.group(1).split(",")
    with (
        patch("synapsis.config.MODEL", "claude-sonnet-5"),
        patch("synapsis.config.AVAILABLE_MODELS", dev),
        patch("synapsis.config.ADMIN_MODELS", dev),
        patch("synapsis.config.RESEARCHER_MODELS", ["claude-sonnet-5"]),
    ):
        assert "claude-opus-5-5" in allowed_models_for_role("admin")
        assert allowed_models_for_role("researcher") == ["claude-sonnet-5"]
        assert allowed_models_for_role("user") == ["claude-sonnet-5"]
        assert allowed_models_for_role(None) == ["claude-sonnet-5"]
