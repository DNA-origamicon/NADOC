"""Desktop-derived primitives survive the VR scene and native scene validation."""

from pathlib import Path
import subprocess

import numpy as np
import pytest

from backend.core.vr_scene_contract import parse_scene_contract, compare_scenes
from tools.vr_workflows.representation_tour import export_design
from tests.conftest import make_minimal_design


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
    for rep in ("hull-prism", "surface"):
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
