"""QA-4 D13: the daily-cap message names a contact on DEV."""

from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "deploy.yml"


def test_deploy_passes_a_support_contact_to_the_container():
    text = DEPLOY.read_text()
    assert "-e IA_SUPPORT_CONTACT=\\\"${{ vars.IA_SUPPORT_CONTACT || 'J.Berenguer@cgiar.org' }}\\\"" in text


def test_daily_cap_message_names_the_contact(monkeypatch):
    from synapsis import config, runtime_policy
    from synapsis.constants import DAILY_LIMIT_ERROR

    monkeypatch.setattr(config, "SUPPORT_CONTACT", "J.Berenguer@cgiar.org")
    msg = DAILY_LIMIT_ERROR.format(limit=5.0, contact=runtime_policy.support_contact())
    assert "please contact J.Berenguer@cgiar.org." in msg
    monkeypatch.setattr(config, "SUPPORT_CONTACT", "")
    assert runtime_policy.support_contact() == "the Innovation Analytics team"
