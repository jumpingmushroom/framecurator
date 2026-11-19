import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_version.py"


def run(tmp_path, py="0.1.0", manifest="0.1.0", *args):
    (tmp_path / "custom_components" / "framecurator").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{py}"\n')
    (tmp_path / "custom_components" / "framecurator" / "manifest.json").write_text(
        json.dumps({"version": manifest}))
    cmd = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(cmd, check=False, cwd=tmp_path, capture_output=True, text=True)


def test_matching_versions_pass(tmp_path):
    assert run(tmp_path, "0.2.0", "0.2.0", "v0.2.0").returncode == 0


def test_no_tag_matching_passes(tmp_path):
    assert run(tmp_path).returncode == 0


def test_tag_mismatch_fails_with_both_versions(tmp_path):
    r = run(tmp_path, "0.2.0", "0.2.0", "v0.3.0")
    assert r.returncode == 1
    assert "0.2.0" in r.stderr and "0.3.0" in r.stderr


def test_manifest_mismatch_fails(tmp_path):
    r = run(tmp_path, "0.2.0", "0.1.0")
    assert r.returncode == 1
    assert "0.1.0" in r.stderr and "0.2.0" in r.stderr
