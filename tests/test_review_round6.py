"""Separate public initializer template constraints from configured resource values."""
from pathlib import Path
import re

import pytest

from test_review_round4 import consumer, config_env, invoke
from make_fixtures import config_resource_cases, config_resource_companion, config_template_path_control, config_template_url_control


@pytest.mark.parametrize("case", config_resource_cases(), ids=lambda case: case[0])
def test_configured_resource_values_preserve_generic_schema_boundary(consumer, config_env, tmp_path, case):
    selected, resource = config_resource_companion(tmp_path / "resource config", consumer["consumer"], case)
    before = (selected / "registry.json").read_bytes()
    result = invoke(consumer, "verify_config.py", config_env, "--config-dir", str(selected))
    output = result.stdout + result.stderr
    assert (selected / "registry.json").read_bytes() == before
    assert "Traceback" not in output
    if case[2]:
        assert result.returncode != 0 and case[2] in output, output
        assert "TEMPLATE CONFORMS" not in output
    else:
        assert result.returncode == 0, output
        assert "TEMPLATE CONFORMS" in output
        assert "Configured and functional readiness require" in output
        if isinstance(resource, str):
            assert resource not in output, "doctor must not echo configured resource values"
        initialized = invoke(consumer, "init_config.py", config_env, "--out", str(selected))
        assert initialized.returncode == 0, initialized.stdout + initialized.stderr
        assert (selected / "registry.json").read_bytes() == before


def template_snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def template_path_leaks(snapshot):
    return [name for name, raw in snapshot.items()
            if re.search(r"(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]|/(?:home|Users|root)/", raw.decode("utf-8"))]


def test_shipped_initializer_templates_remain_deterministic_and_path_free(consumer, config_env, tmp_path):
    snapshots = []
    for label in ("template A", "template B"):
        root = tmp_path / label
        result = invoke(consumer, "init_config.py", config_env, "--out", str(root))
        assert result.returncode == 0, result.stdout + result.stderr
        snapshots.append(template_snapshot(root))
    assert snapshots[0] and snapshots[0] == snapshots[1]
    assert not template_path_leaks(snapshots[0]), "shipped initializer output cannot bake in author paths"
    assert str(tmp_path).encode() not in b"".join(snapshots[0].values())
    polluted = config_template_path_control(tmp_path / "negative template control")
    assert "registry.json" in template_path_leaks(template_snapshot(polluted))
    public_url = config_template_url_control(tmp_path / "public URL control")
    assert not template_path_leaks(template_snapshot(public_url))
    assert list(Path(config_env["HOME"]).iterdir()) == []
