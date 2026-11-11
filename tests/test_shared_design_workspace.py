"""Repository setup only: these checks never create molecular documents."""

import subprocess

import pytest

from scripts.setup_shared_design_workspace import setup


def test_setup_creates_independent_repository_and_keeps_jobs_untracked(tmp_path):
    destination = setup(tmp_path)
    result = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--show-toplevel"],
        check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == str(destination)
    ignored = subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "md_jobs/job/job.json", "runs/a.dcd", ".env"],
        check=True, capture_output=True, text=True,
    )
    assert len(ignored.stdout.splitlines()) == 3
    assert subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "parts/example.nadoc", "assemblies/example.nass"],
        capture_output=True,
    ).returncode == 1
    assert sorted(path.name for path in destination.iterdir()) == [".git", ".gitignore", "AGENTS.md", "README.md"]
    assert subprocess.run(
        ["git", "-C", str(destination), "remote"], check=True, capture_output=True, text=True,
    ).stdout == ""


def test_setup_refuses_existing_folder_without_modifying_it(tmp_path):
    destination = tmp_path / "Shared Designs"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("existing user data")
    with pytest.raises(FileExistsError):
        setup(tmp_path)
    assert marker.read_text() == "existing user data"
    assert list(destination.iterdir()) == [marker]
