"""The hosted release smoke must fail a promotion whose voice key the provider rejects."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/release-smoke.py'


def load():
    spec = importlib.util.spec_from_file_location('release_smoke', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # __name__ != '__main__': main() is not run
    return module


def test_voice_gate_requires_a_provider_accepted_key_when_enabled():
    smoke = load()
    assert smoke.check_voice_status({'enabled': True, 'configured': True, 'provider_ok': True}).startswith('voice enabled=True')
    with pytest.raises(AssertionError, match='provider probe failed'):
        smoke.check_voice_status({'enabled': True, 'configured': True, 'provider_ok': False})
    with pytest.raises(AssertionError, match='provider probe failed'):
        smoke.check_voice_status({'enabled': True, 'configured': True})  # an old build without the probe cannot pass either
    with pytest.raises(AssertionError, match='not configured'):
        smoke.check_voice_status({'enabled': True, 'configured': False, 'provider_ok': None})
    # Disabled voice is not gated on the provider (the key must still exist).
    smoke.check_voice_status({'enabled': False, 'configured': True, 'provider_ok': None})


def test_smoke_script_still_runs_as_main_and_calls_the_gate():
    text = SCRIPT.read_text()
    assert "if __name__=='__main__':asyncio.run(main())" in text
    assert 'voice=check_voice_status(r.json())' in text
