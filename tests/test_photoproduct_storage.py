"""Fail-closed storage-root tests for large photoproduct workflows."""

from pathlib import Path

import pytest

from backend.core import photoproduct_storage


def test_known_archive_path_requires_actual_mount(tmp_path: Path, monkeypatch) -> None:
    mount = tmp_path / "Archive"
    root = mount / "NADOC_archive"
    root.mkdir(parents=True)
    monkeypatch.setattr(photoproduct_storage, "ARCHIVE_MOUNT", mount)

    with pytest.raises(ValueError, match="Archive drive is not mounted"):
        photoproduct_storage.validate_photoproduct_storage_root(root)


def test_portable_nonarchive_storage_root_remains_supported(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        photoproduct_storage, "ARCHIVE_MOUNT", tmp_path / "different-mount"
    )
    root = tmp_path / "durable-root"
    root.mkdir()
    status = photoproduct_storage.validate_photoproduct_storage_root(root)
    assert status == {
        "storage_root": str(root.resolve()),
        "archive_mount_required": False,
        "archive_mount": None,
        "archive_mounted": None,
    }
