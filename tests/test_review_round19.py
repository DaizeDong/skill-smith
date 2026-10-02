"""Native regression for operation-owned submodule checkout line endings."""
import subprocess

import pytest

from test_review_round16 import fixtures, module


@pytest.mark.native
def test_submodule_checkout_preserves_pinned_bytes_with_global_autocrlf(monkeypatch, tmp_path):
    scaffold = module("scaffold_skill")
    inputs = fixtures.review19_checkout_layout(tmp_path, scaffold.KITS, scaffold.KIT_FILES)
    for key, value in inputs["environment"].items():
        monkeypatch.setenv(key, value)

    scaffold.emit_guards(str(inputs["root"]), False, inputs["name"])

    assert inputs["global_config"].read_bytes() == inputs["global_bytes"]
    assert scaffold.checked_git(inputs["root"], "config", "--global", "--get",
                                "core.autocrlf") == "true"
    for kit, mirror in inputs["mirrors"].items():
        checkout = inputs["root"] / kit
        for relative, payload in mirror["payloads"].items():
            blob = subprocess.run(
                ["git", "-C", str(checkout), "cat-file", "blob",
                 mirror["revision"] + ":" + relative],
                capture_output=True, timeout=120, env=scaffold.git_environment())
            assert blob.returncode == 0, blob.stderr
            assert blob.stdout == payload
            assert checkout.joinpath(relative).read_bytes() == blob.stdout
        scaffold.verify_kit_payload(checkout, mirror["revision"], kit)

    changed = inputs["root"] / "guards" / inputs["changed_member"]
    changed.write_bytes(inputs["changed_payload"])
    with pytest.raises(SystemExit, match="modified pinned payload"):
        scaffold.verify_kit_payload(inputs["root"] / "guards",
                                    inputs["mirrors"]["guards"]["revision"], "guards")
    assert inputs["global_config"].read_bytes() == inputs["global_bytes"]
