"""Repository setup only: these checks never create molecular documents."""

import subprocess

import pytest

from scripts.setup_shared_design_workspace import ROOT, setup


def test_shared_folder_uses_parent_repository_and_keeps_jobs_untracked(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    destination = setup(tmp_path / "workspace")
    result = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--show-toplevel"],
        check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == str(tmp_path)
    ignored = subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "md_jobs/job/job.json", "runs/a.dcd", ".env"],
        check=True, capture_output=True, text=True,
    )
    assert len(ignored.stdout.splitlines()) == 3
    assert subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "parts/example.nadoc", "assemblies/example.nass"],
        capture_output=True,
    ).returncode == 1
    assert sorted(path.name for path in destination.iterdir()) == [".gitignore", "AGENTS.md", "README.md"]
    assert not (destination / ".git").exists()
    assert subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", "workspace/private.nadoc"],
        capture_output=True,
    ).returncode == 0
    subprocess.run(["git", "-C", str(tmp_path), "add", "workspace/Shared Designs"], check=True)
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "--stage"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "workspace/Shared Designs/README.md" in tracked
    assert "160000" not in tracked  # ordinary files, never a nested Git link


def test_checked_in_shared_folder_matches_setup_template():
    for name in ("README.md", "AGENTS.md", ".gitignore"):
        assert (ROOT / "workspace/Shared Designs" / name).read_bytes() == (
            ROOT / "scripts/shared_design_workspace" / name
        ).read_bytes()


def test_setup_refuses_existing_folder_without_modifying_it(tmp_path):
    destination = tmp_path / "Shared Designs"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("existing user data")
    with pytest.raises(FileExistsError):
        setup(tmp_path)
    assert marker.read_text() == "existing user data"
    assert list(destination.iterdir()) == [marker]
