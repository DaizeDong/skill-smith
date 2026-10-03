"""Declared registry schema enforced by actual emitted config doctors."""
from pathlib import Path

import pytest

from test_review_round4 import consumer, config_env, invoke
from make_fixtures import config_schema_cases, config_schema_companion


@pytest.mark.parametrize("case", config_schema_cases(), ids=lambda case: case["name"])
def test_emitted_doctor_validates_registry_schema(consumer, config_env, tmp_path, case):
    selected = config_schema_companion(tmp_path / "selected config", case)
    result = invoke(consumer, "verify_config.py", config_env, "--config-dir", str(selected))
    output = result.stdout + result.stderr
    assert str(selected) in output
    assert case["marker"] not in output
    assert (selected / "registry.json").read_bytes() == case["raw"], "doctor must not rewrite input"
    if case["valid"]:
        assert result.returncode == 0, output
        assert "TEMPLATE CONFORMS" in output
        assert "Configured and functional readiness require" in output
    else:
        assert result.returncode != 0, output
        assert case["field"] in output
        assert "[FAIL]" in output
        assert "TEMPLATE CONFORMS" not in output
        assert "Traceback" not in output


def test_fresh_initializer_output_still_passes_generic_schema(consumer, config_env, tmp_path):
    selected = tmp_path / "fresh config"
    initialized = invoke(consumer, "init_config.py", config_env, "--out", str(selected))
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    verified = invoke(consumer, "verify_config.py", config_env, "--config-dir", str(selected))
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "TEMPLATE CONFORMS" in verified.stdout
    assert "Configured and functional readiness require" in verified.stdout
    assert list(Path(config_env["HOME"]).iterdir()) == []
