"""Direct input→output unit tests for the pure workspace service
(`backend/core/workspace.py`), extracted from assembly.py's
`_safe_workspace_path` / `_dedup_filename` / `_patch_references`
(carve-up Refactor #10, service push, B=0).

No TestClient — these pin the path/file/remap rules directly.
"""

import json

import pytest

from backend.core.models import (
    Assembly,
    Design,
    PartInstance,
    PartSourceFile,
    PartSourceInline,
)
from backend.core.workspace import (
    dedup_filename,
    patch_assembly_instances,
    patch_nass_files,
    remap_source_path,
    safe_workspace_path,
)


# ── safe_workspace_path ─────────────────────────────────────────────────────


def test_safe_workspace_path_resolves_inside(tmp_path):
    p = safe_workspace_path("parts/2hb.nadoc", tmp_path)
    assert p == (tmp_path / "parts" / "2hb.nadoc").resolve()


def test_safe_workspace_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        safe_workspace_path("../escape.nadoc", tmp_path)


def test_safe_workspace_path_rejects_absolute_escape(tmp_path):
    with pytest.raises(ValueError):
        safe_workspace_path("/etc/passwd", tmp_path)


def test_safe_workspace_path_creates_workspace(tmp_path):
    ws = tmp_path / "newws"
    assert not ws.exists()
    safe_workspace_path("x.nadoc", ws)
    assert ws.is_dir()


# ── dedup_filename ──────────────────────────────────────────────────────────


def test_dedup_filename_no_collision(tmp_path):
    assert dedup_filename("part", ".nadoc", tmp_path) == "part.nadoc"


def test_dedup_filename_single_collision(tmp_path):
    (tmp_path / "part.nadoc").write_text("x")
    assert dedup_filename("part", ".nadoc", tmp_path) == "part_2.nadoc"


def test_dedup_filename_multiple_collisions(tmp_path):
    (tmp_path / "part.nadoc").write_text("x")
    (tmp_path / "part_2.nadoc").write_text("x")
    (tmp_path / "part_3.nadoc").write_text("x")
    assert dedup_filename("part", ".nadoc", tmp_path) == "part_4.nadoc"


# ── remap_source_path ───────────────────────────────────────────────────────


def test_remap_file_exact_match():
    assert (
        remap_source_path("parts/a.nadoc", "parts/a.nadoc", "parts/b.nadoc")
        == "parts/b.nadoc"
    )


def test_remap_file_no_match_returns_none():
    assert (
        remap_source_path("parts/other.nadoc", "parts/a.nadoc", "parts/b.nadoc") is None
    )


def test_remap_folder_prefix():
    assert remap_source_path("old/a.nadoc", "old/", "new/") == "new/a.nadoc"


def test_remap_folder_non_prefix_returns_none():
    assert remap_source_path("keep/a.nadoc", "old/", "new/") is None


# ── patch_nass_files ────────────────────────────────────────────────────────


def _write_nass(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_patch_nass_files_v1_instances_shape(tmp_path):
    nass = tmp_path / "asm.nass"
    _write_nass(
        nass, {"instances": [{"source": {"type": "file", "path": "old/a.nadoc"}}]}
    )
    patched = patch_nass_files(tmp_path, "old/a.nadoc", "new/a.nadoc")
    assert patched == ["asm.nass"]
    data = json.loads(nass.read_text())
    assert data["instances"][0]["source"]["path"] == "new/a.nadoc"


def test_patch_nass_files_v2_sources_shape(tmp_path):
    nass = tmp_path / "asm.nass"
    _write_nass(nass, {"sources": {"k1": {"type": "file", "path": "old/a.nadoc"}}})
    patched = patch_nass_files(tmp_path, "old/a.nadoc", "new/a.nadoc")
    assert patched == ["asm.nass"]
    data = json.loads(nass.read_text())
    assert data["sources"]["k1"]["path"] == "new/a.nadoc"


def test_patch_nass_files_folder_rename(tmp_path):
    nass = tmp_path / "asm.nass"
    _write_nass(nass, {"sources": {"k": {"type": "file", "path": "old/a.nadoc"}}})
    patched = patch_nass_files(tmp_path, "old/", "renamed/")
    assert patched == ["asm.nass"]
    assert json.loads(nass.read_text())["sources"]["k"]["path"] == "renamed/a.nadoc"


def test_patch_nass_files_untouched_file_not_reported(tmp_path):
    nass = tmp_path / "asm.nass"
    _write_nass(nass, {"sources": {"k": {"type": "file", "path": "keep/a.nadoc"}}})
    assert patch_nass_files(tmp_path, "old/a.nadoc", "new/a.nadoc") == []


def test_patch_nass_files_ignores_inline_sources(tmp_path):
    nass = tmp_path / "asm.nass"
    _write_nass(nass, {"sources": {"k": {"type": "inline", "design": {}}}})
    assert patch_nass_files(tmp_path, "old/a.nadoc", "new/a.nadoc") == []


# ── patch_assembly_instances ────────────────────────────────────────────────


def test_patch_assembly_instances_remaps_file_source():
    inst = PartInstance(id="i1", name="P", source=PartSourceFile(path="old/a.nadoc"))
    asm = Assembly(instances=[inst])
    out = patch_assembly_instances(asm, "old/a.nadoc", "new/a.nadoc")
    assert out is not None
    assert out.instances[0].source.path == "new/a.nadoc"


def test_patch_assembly_instances_no_change_returns_none():
    inst = PartInstance(id="i1", name="P", source=PartSourceFile(path="keep/a.nadoc"))
    asm = Assembly(instances=[inst])
    assert patch_assembly_instances(asm, "old/a.nadoc", "new/a.nadoc") is None


def test_patch_assembly_instances_ignores_inline():
    inst = PartInstance(id="i1", name="P", source=PartSourceInline(design=Design()))
    asm = Assembly(instances=[inst])
    assert patch_assembly_instances(asm, "old/a.nadoc", "new/a.nadoc") is None
