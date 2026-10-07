"""Desktop-derived primitives survive the VR scene and native scene validation."""

from pathlib import Path
import subprocess

import numpy as np
import pytest

from backend.core.vr_scene_contract import parse_scene_contract, compare_scenes
from tools.vr_workflows.representation_tour import export_design
from tests.conftest import make_minimal_design


@pytest.mark.parametrize("representation,detail", [("surface", "coarse"), ("surface-detail", "chimerax")])
def test_surface_keeps_desktop_strand_ownership_and_motion(representation, detail):
    from backend.api.routes_display_geometry import _build_design_surface_mesh
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes
    from backend.core.vr_representation_geometry import build, records

    design = make_minimal_design(helix_length_bp=12)
    data = build(design, _geometry_for_design(design), deformed_helix_axes(design), {representation})
    desktop = _build_design_surface_mesh(design, .20, .06, 1.30, 15, detail)
    mesh = data[representation]
    expected = np.asarray(desktop.vertex_strand_ids)[desktop.faces].reshape(-1)
    actual = np.asarray([data["source"][i]["strand_id"] for i in mesh["owners"]])
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_allclose(mesh["vertices"], desktop.vertices[desktop.faces].reshape(-1, 3))
    # Ensure this fixture exposes the original nearest-backbone recoloring bug.
    old_owners = data["tree"].query(mesh["vertices"])[1]
    old_strands = np.asarray([data["source"][i]["strand_id"] for i in old_owners])
    assert np.count_nonzero(old_strands != expected) > 0

    shifted = [{**n, "backbone_position": (np.asarray(n["backbone_position"]) +
                ([5, 0, 0] if n["strand_id"] == expected[0] else [0, 0, 0])).tolist()}
               for n in data["source"]]
    before = [r for r in records(data, data["source"]) if r[0] == representation]
    after = [r for r in records(data, shifted) if r[0] == representation]
    for i, (original, moved) in enumerate(zip(before, after)):
        np.testing.assert_array_equal(moved[4], mesh["owners"][i*3:i*3+3])
        # The record origin is the midpoint of corners two and three.
        dx = 2.5 * np.count_nonzero(expected[i*3+1:i*3+3] == expected[0])
        np.testing.assert_allclose(moved[3][:3] - original[3][:3], [dx, 0, 0], atol=1e-6)


@pytest.mark.parametrize("representation", ["surface", "surface-detail"])
def test_surface_face_palette_uses_majority_strand(monkeypatch, representation):
    from backend.core import vr_representation_geometry as vr

    source = [{"strand_id": "a"}, {"strand_id": "b"}, {"strand_id": "b"}]
    data = {"source": source, "hull": [], "surface": {"vertices": []}, "mrdna": {}, "oxdna": []}
    monkeypatch.setattr(vr, "records", lambda *_: iter([
        (representation, "B", "face", np.zeros(12), [0, 1, 2], None, None),
    ]))
    emitted = []
    vr.append_records(
        data, source, np.eye(3), lambda *_: None,
        lambda *args, **kwargs: emitted.append(args), [],
        lambda n: [n["strand_id"]], lambda n: n["strand_id"],
        lambda i: [float(i)] * 12,
    )
    # Both b corners use b's palette even though the first corner belongs to a.
    assert emitted[0][14:26] == (2.0,) * 12


def test_desktop_meshes_previews_and_vdw_round_trip(tmp_path):
    source = tmp_path / "design.nadoc"
    source.write_text(make_minimal_design(helix_length_bp=14).to_json())
    target = tmp_path / "scene.nadocvr"
    export_design(source, target, use_cache=False)
    text = target.read_text()
    scene = parse_scene_contract(text)
    expected = {
        "full",
        "cylinders",
        "ballstick",
        "stick",
        "hull-prism",
        "surface",
        "surface-detail",
        "mrdna-coarse",
        "mrdna-fine",
        "oxdna",
    }
    assert set(scene) == expected
    for rep in expected:
        assert scene[rep]
    # One 14-bp duplex: fine uses one site/bp, coarse groups five bp,
    # and oxDNA displays one backbone and one ellipsoid per nucleotide.
    count = lambda rep, kind: sum(p.record_type == kind for p in scene[rep].values())
    assert count("mrdna-fine", "P") == 14
    assert count("mrdna-coarse", "P") == 3
    assert count("oxdna", "P") == count("oxdna", "B") == 28
    for rep in ("hull-prism", "surface", "surface-detail"):
        faces = [p for p in scene[rep].values() if p.record_type == "B"]
        assert faces
        for face in faces:
            assert dict(face.annotations)["N"]
            axes = np.asarray(face.values[:12]).reshape(4, 3)
            assert np.linalg.norm(np.cross(axes[1], axes[2])) > 0
    atoms = [p for p in scene["ballstick"].values() if p.record_type == "P"]
    assert atoms and all(dict(p.annotations)["V"][0] > p.values[3] for p in atoms)
    ox = list(scene["oxdna"].values())
    assert {p.record_type for p in ox} >= {"P", "C", "B"}
    tapered = [p for p in ox if "backbone-connector" in p.identity]
    assert tapered and all(
        dict(p.annotations)["U"][0] == pytest.approx(5 * p.values[6], rel=1e-5)
        for p in tapered
    )
    assert compare_scenes(text, text).ok
    binary = Path("native/vr_viewer/build/nadoc-vr-viewer")
    if binary.exists():
        subprocess.run(
            [str(binary), "--validate", str(target)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_annotation_changes_are_detected_and_invalid_targets_rejected():
    base = (
        "NADOCVR 15 ballstick strand\nR ballstick\nP atom 0 0 0 .1 "
        + " ".join(["1"] * 12)
        + "\n"
    )
    first = base + "V atom .17\n"
    assert not compare_scenes(first, base + "V atom .18\n").ok
    for annotation in (
        "V atom -1",
        "V missing .17",
        "N atom " + " ".join(["1"] * 9),
        "V atom nan",
    ):
        with pytest.raises(ValueError):
            parse_scene_contract(base + annotation + "\n")
