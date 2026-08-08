"""Tests for the primitive-library catalog service + routes.

Covers the pure metadata derivation, the directory scan (including malformed-file
skip + asset-flag detection), and the HTTP surface (list shape, asset serving,
path-traversal rejection).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly as _asm
from backend.api.main import app
from backend.core import primitive_catalog as pc


# ── Pure derivation ────────────────────────────────────────────────────────────


def test_derive_metadata_from_helices():
    design = {
        "helices": [{}] * 6,
        "lattice_type": "HONEYCOMB",
        "camera_poses": [{}, {}],
    }
    meta = pc.derive_metadata(design, "6hb_primitive")
    assert meta["id"] == "6hb_primitive"
    assert meta["helix_count"] == 6
    assert meta["short_name"] == "6HB"
    assert meta["name"] == "6-Helix Bundle"
    assert meta["description"] == "Honeycomb 6-helix beam"
    assert meta["lattice"] == "HONEYCOMB"
    assert meta["pose_count"] == 2


def test_derive_metadata_square_and_explicit_name():
    design = {"helices": [{}] * 4, "lattice_type": "SQUARE", "name": "My Block"}
    meta = pc.derive_metadata(design, "blk")
    assert meta["short_name"] == "4HB"
    assert meta["name"] == "My Block"  # explicit name wins over size-derived
    assert meta["description"] == "Square 4-helix beam"
    assert meta["pose_count"] == 0


def test_derive_metadata_ignores_stem_named_design():
    # Designs auto-saved with name == filename stem should NOT show the stem.
    design = {"helices": [{}] * 6, "name": "6hb_primitive"}
    meta = pc.derive_metadata(design, "6hb_primitive")
    assert meta["name"] == "6-Helix Bundle"


def test_is_safe_id_rejects_traversal():
    assert pc.is_safe_id("6hb_primitive")
    assert not pc.is_safe_id("../secret")
    assert not pc.is_safe_id("a/b")
    assert not pc.is_safe_id("foo.nadoc")


# ── Placement-spec derivation ────────────────────────────────────────────────────


def _bundle_create_design(cells, length_bp=42, plane="XY"):
    return {
        "lattice_type": "HONEYCOMB",
        "helices": [{"grid_pos": c, "length_bp": length_bp} for c in cells],
        "feature_log": [
            {
                "op_kind": "bundle-create",
                "params": {
                    "cells": cells,
                    "length_bp": length_bp,
                    "plane": plane,
                    "strand_filter": "both",
                    "ligate_adjacent": True,
                    "lattice_type": "HONEYCOMB",
                },
            }
        ],
    }


def test_placement_spec_from_bundle_create_op():
    cells = [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]]
    spec = pc.derive_placement_spec(_bundle_create_design(cells, length_bp=42))
    assert spec["cells"] == cells
    assert spec["anchor_cell"] == [0, 1]  # min row then min col
    assert spec["length_bp"] == 42
    assert spec["plane"] == "XY"
    assert spec["strand_filter"] == "both"
    assert spec["ligate_adjacent"] is True
    assert spec["lattice"] == "HONEYCOMB"


def test_placement_spec_anchor_is_min_row_then_col():
    spec = pc.derive_placement_spec(_bundle_create_design([[2, 5], [1, 9], [1, 4]]))
    assert spec["anchor_cell"] == [1, 4]


def test_placement_spec_falls_back_to_helices_without_log():
    design = {
        "lattice_type": "SQUARE",
        "helices": [
            {"grid_pos": [0, 0], "length_bp": 32},
            {"grid_pos": [0, 1], "length_bp": 32},
        ],
        "feature_log": [],
    }
    spec = pc.derive_placement_spec(design)
    assert spec["cells"] == [[0, 0], [0, 1]]
    assert spec["anchor_cell"] == [0, 0]
    assert spec["length_bp"] == 32
    assert spec["lattice"] == "SQUARE"
    assert spec["plane"] == "XY"


def test_placement_spec_none_when_no_footprint():
    assert pc.derive_placement_spec({"helices": [], "feature_log": []}) is None


def test_list_primitives_includes_placement(tmp_path):
    cells = [[0, 1], [1, 1]]
    (tmp_path / "two.nadoc").write_text(
        json.dumps(_bundle_create_design(cells)), encoding="utf-8"
    )
    out = pc.list_primitives(tmp_path)
    assert out[0]["placement"]["cells"] == cells
    assert out[0]["placement"]["anchor_cell"] == [0, 1]


# ── Directory scan ──────────────────────────────────────────────────────────────


def _write_design(path, helices, lattice="HONEYCOMB", poses=()):
    path.write_text(
        json.dumps(
            {
                "helices": [{} for _ in range(helices)],
                "lattice_type": lattice,
                "camera_poses": list(poses),
            }
        ),
        encoding="utf-8",
    )


def test_list_primitives_scans_sorts_and_flags_assets(tmp_path):
    _write_design(tmp_path / "18hb_primitive.nadoc", 18)
    _write_design(tmp_path / "6hb_primitive.nadoc", 6)
    (tmp_path / "6hb_primitive.gif").write_bytes(b"GIF89a")  # has preview
    (tmp_path / "broken.nadoc").write_text("{not json", encoding="utf-8")

    out = pc.list_primitives(tmp_path)
    ids = [m["id"] for m in out]
    assert ids == [
        "6hb_primitive",
        "18hb_primitive",
    ]  # sorted by helix count, broken skipped
    assert out[0]["has_preview"] is True
    assert out[0]["has_poster"] is False
    assert out[1]["has_preview"] is False


def test_list_primitives_missing_dir_is_empty(tmp_path):
    assert pc.list_primitives(tmp_path / "nope") == []


# ── HTTP surface ────────────────────────────────────────────────────────────────


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(_asm, "_WORKSPACE_DIR", tmp_path)
    prim = tmp_path / "Primitives"
    prim.mkdir()
    _write_design(prim / "6hb_primitive.nadoc", 6, poses=[{}, {}])
    (prim / "6hb_primitive.gif").write_bytes(b"GIF89a\x00")
    (prim / "6hb_primitive.poster.png").write_bytes(b"\x89PNG\r\n")
    return prim


def test_get_primitives_list(workspace):
    client = TestClient(app)
    r = client.get("/api/primitives")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    e = body[0]
    assert e["id"] == "6hb_primitive"
    assert e["preview_url"] == "/api/primitives/6hb_primitive/preview.gif"
    assert e["poster_url"] == "/api/primitives/6hb_primitive/poster.png"


def test_serve_preview_and_poster(workspace):
    client = TestClient(app)
    assert client.get("/api/primitives/6hb_primitive/preview.gif").status_code == 200
    assert client.get("/api/primitives/6hb_primitive/poster.png").status_code == 200


def test_missing_asset_404(workspace):
    client = TestClient(app)
    assert (
        client.get("/api/primitives/6hb_primitive_missing/preview.gif").status_code
        == 404
    )
