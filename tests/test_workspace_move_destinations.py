"""Filesystem-only move fixtures; no molecular documents are constructed."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.workspace_move_destinations import list_move_destinations


def test_excludes_internal_outside_self_descendants_and_collisions(tmp_path):
    root = tmp_path / "workspace"
    for folder in ("Source/child", "Valid/empty", "Valid/.git", "Collision/Source", "md_jobs", ".hidden"):
        (root / folder).mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "outside-link").symlink_to(outside, target_is_directory=True)
    (root / "internal-link").symlink_to(root / "md_jobs", target_is_directory=True)
    (root / "hidden-link").symlink_to(root / "Valid/.git", target_is_directory=True)
    assert list_move_destinations(root, ["Source"]) == ["Collision/Source", "Valid", "Valid/empty"]


def test_checks_real_collisions_and_refreshes_disk_state(tmp_path):
    for folder in ("From", "To", "Blocked"):
        (tmp_path / folder).mkdir()
    (tmp_path / "From/item.txt").write_text("metadata fixture")
    (tmp_path / "Blocked/item.txt").symlink_to(tmp_path / "missing")
    assert list_move_destinations(tmp_path, ["From/item.txt"]) == ["", "To"]
    (tmp_path / "To").rmdir()
    (tmp_path / "New").mkdir()
    assert list_move_destinations(tmp_path, ["From/item.txt"]) == ["", "New"]


def test_bulk_root_destination_and_conflicting_selections(tmp_path):
    for folder in ("A", "B", "To"):
        (tmp_path / folder).mkdir()
    (tmp_path / "A/one.txt").touch()
    (tmp_path / "B/two.txt").touch()
    assert list_move_destinations(tmp_path, ["A/one.txt", "B/two.txt"]) == ["", "A", "B", "To"]
    (tmp_path / "B/one.txt").touch()
    assert list_move_destinations(tmp_path, ["A/one.txt", "B/one.txt"]) == []
    assert list_move_destinations(tmp_path, ["A", "A/one.txt"]) == []


def test_excludes_unwritable_destinations(tmp_path, monkeypatch):
    (tmp_path / "source.txt").touch()
    (tmp_path / "ReadOnly").mkdir()
    (tmp_path / "Writable").mkdir()
    original = os.access
    monkeypatch.setattr(os, "access", lambda path, mode: path.name != "ReadOnly" and original(path, mode))
    assert list_move_destinations(tmp_path, ["source.txt"]) == ["Writable"]


def test_rejects_missing_and_outside_sources(tmp_path):
    with pytest.raises(FileNotFoundError):
        list_move_destinations(tmp_path, ["missing"])
    with pytest.raises(ValueError):
        list_move_destinations(tmp_path, [".."])
    with pytest.raises(ValueError):
        list_move_destinations(tmp_path, [])


def test_endpoint_accepts_multiple_paths_and_reports_invalid_sources(tmp_path, monkeypatch):
    from backend.api import assembly
    from backend.api.routes_assembly_workspace import router

    (tmp_path / "A").mkdir()
    (tmp_path / "A/one.txt").touch()
    (tmp_path / "A/two.txt").touch()
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/library/move-destinations", params=[("path", "A/one.txt"), ("path", "A/two.txt")])
        assert response.status_code == 200
        assert response.json() == [""]
        assert client.get("/library/move-destinations", params={"path": "missing"}).status_code == 400
