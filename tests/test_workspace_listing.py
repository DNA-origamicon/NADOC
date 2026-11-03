"""Metadata-only fixtures: empty filenames, never authored molecular documents."""

import os

from backend.core.workspace_listing import list_workspace_entries


def test_validation_keeps_documents_and_ancestors_but_not_result_folders(tmp_path):
    for name in (
        "validation/campaign/deep/part.nadoc",
        "validation/campaign/assembly.nass",
        "validation/campaign/results/run/trajectory.dat",
        "validation/other/results/log.txt",
        "user/validation/empty/.keep",
        "ordinary/empty/.keep",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    entries = {entry["path"]: entry for entry in list_workspace_entries(tmp_path)}
    assert set(entries) == {
        "validation", "validation/campaign", "validation/campaign/deep",
        "validation/campaign/deep/part.nadoc", "validation/campaign/assembly.nass",
        "user", "user/validation", "user/validation/empty", "ordinary", "ordinary/empty",
    }
    assert entries["validation/campaign/deep/part.nadoc"]["type"] == "part"
    assert entries["validation/campaign/assembly.nass"]["type"] == "assembly"
    # Refresh still discovers newly added documents and removes vanished ones.
    (tmp_path / "validation/other/new.nadoc").touch()
    (tmp_path / "validation/campaign/deep/part.nadoc").unlink()
    paths = {entry["path"] for entry in list_workspace_entries(tmp_path)}
    assert "validation/other/new.nadoc" in paths
    assert "validation/campaign/deep" not in paths


def test_internal_roots_are_not_scanned_and_directory_links_not_followed(tmp_path, monkeypatch):
    (tmp_path / "md_jobs/nested").mkdir(parents=True)
    (tmp_path / "md_jobs/nested/hidden.nadoc").touch()
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "part.nadoc").touch()
    (tmp_path / ".hidden.nadoc").touch()
    original = os.scandir

    def checked_scan(path):
        assert "md_jobs" not in os.fspath(path)
        assert os.fspath(path) != os.fspath(tmp_path / "link")
        return original(path)

    monkeypatch.setattr(os, "scandir", checked_scan)
    entries = list_workspace_entries(tmp_path)
    assert {entry["path"] for entry in entries} == {"part.nadoc", "link"}
    assert all(entry["size_bytes"] == 0 for entry in entries)
