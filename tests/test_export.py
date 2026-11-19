import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "export_public.sh"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True,
                          capture_output=True, text=True).stdout.strip()


def run_export(repo, target):
    return subprocess.run([str(SCRIPT), str(target)], cwd=repo, env=ENV, capture_output=True, text=True, check=False)


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    for name, text in {
        "README.md": "hello", "CLAUDE.md": "internal", "docs/superpowers/plan.md": "internal",
        "docs/my guide.md": "spaces ok", "src/a.py": "x = 1",
    }.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    (repo / ".private-strings").write_text("\nphotos.private.example\n")
    git(repo, "init", "-q", "-b", "main")
    (repo / ".git/info/exclude").write_text(".private-strings\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


def test_export_leaves_out_internal_files_and_commits_once(tmp_repo, tmp_path):
    out = run_export(tmp_repo, tmp_path / "pub")
    assert out.returncode == 0, out.stderr
    pub = tmp_path / "pub"
    assert not (pub / "CLAUDE.md").exists() and not (pub / "docs/superpowers").exists()
    assert not (pub / ".private-strings").exists() and (pub / "docs/my guide.md").exists()
    assert git(pub, "rev-list", "--count", "HEAD") == "1"
    assert git(pub, "log", "-1", "--format=%s") == "v0.1.0"


def test_export_refuses_a_tree_with_a_private_string(tmp_repo, tmp_path):
    (tmp_repo / "README.md").write_text("see photos.private.example")
    git(tmp_repo, "commit", "-qam", "leak")
    out = run_export(tmp_repo, tmp_path / "pub")
    assert out.returncode == 1 and "photos.private.example" in out.stdout and not (tmp_path / "pub").exists()


def test_export_refuses_non_empty_target_and_missing_strings(tmp_repo, tmp_path):
    (tmp_path / "full").mkdir()
    (tmp_path / "full/x").write_text("x")
    assert run_export(tmp_repo, tmp_path / "full").returncode == 1
    (tmp_repo / ".private-strings").write_text("\n\n")
    assert run_export(tmp_repo, tmp_path / "pub").returncode == 1
    (tmp_repo / ".private-strings").unlink()
    assert run_export(tmp_repo, tmp_path / "pub").returncode == 1
    assert (tmp_path / "full/x").exists() and not (tmp_path / "pub").exists()


def test_crlf_strings_file_still_matches(tmp_repo, tmp_path):
    (tmp_repo / ".private-strings").write_bytes(b"photos.private.example\r\n")
    (tmp_repo / "README.md").write_text("see photos.private.example")
    git(tmp_repo, "commit", "-qam", "leak")
    assert run_export(tmp_repo, tmp_path / "pub").returncode == 1
    (tmp_repo / ".private-strings").write_bytes(b"\r\n\r\n")
    assert run_export(tmp_repo, tmp_path / "pub2").returncode == 1


def test_symlinks_stay_links_and_dash_names_work(tmp_repo, tmp_path):
    (tmp_path / "outside.txt").write_text("outside")
    (tmp_repo / "ln").symlink_to(tmp_path / "outside.txt")
    (tmp_repo / "dirln").symlink_to(tmp_path)
    (tmp_repo / "dangling").symlink_to("nowhere")
    (tmp_repo / "-dash.txt").write_text("d")
    git(tmp_repo, "add", "-A")
    git(tmp_repo, "commit", "-qm", "more")
    out = run_export(tmp_repo, tmp_path / "pub")
    assert out.returncode == 0, out.stderr
    assert all((tmp_path / "pub" / n).is_symlink() for n in ("ln", "dirln", "dangling"))
    assert (tmp_path / "pub/-dash.txt").exists()


def test_private_string_in_a_file_name_is_refused_and_cleaned_up(tmp_repo, tmp_path):
    (tmp_repo / "photos.private.example").mkdir()
    (tmp_repo / "photos.private.example/a.txt").write_text("x")
    git(tmp_repo, "add", "-A")
    git(tmp_repo, "commit", "-qm", "name")
    out = run_export(tmp_repo, tmp_path / "pub")
    assert out.returncode == 1 and "photos.private.example" in out.stdout and not (tmp_path / "pub").exists()


def test_private_strings_match_regardless_of_case(tmp_repo, tmp_path):
    (tmp_repo / "README.md").write_text("see PHOTOS.Private.Example")
    (tmp_repo / "Photos.PRIVATE.example.txt").write_text("x")
    git(tmp_repo, "add", "-A")
    git(tmp_repo, "commit", "-qm", "case")
    out = run_export(tmp_repo, tmp_path / "pub")
    assert out.returncode == 1 and "PHOTOS.Private.Example" in out.stdout and "Photos.PRIVATE.example.txt" in out.stdout
