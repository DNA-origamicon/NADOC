"""Headless regression from the saved 2hb_1xT_CPD design (no workspace dependency)."""

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.core.atomistic import VDW_RADIUS, build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.cpd_design import (
    relax_existing_cpd,
    convert_extra_pair,
    _pose_with_jacobian,
)
from backend.core.models import Design

FIXTURE = Path(__file__).parent / "fixtures/cpd_2hb_1xt.nadoc"


def measured_clashes(model, keys):
    # Independent measurement of emitted coordinates, not the optimizer residual.
    graph = {}
    for a, b in model.bonds:
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    pairs, severe = 0, 0
    for a in model.atoms:
        if atom_base_key(a) not in keys:
            continue
        first = graph.get(a.serial, set())
        excluded = first | {c for b in first for c in graph.get(b, set())}
        for b in model.atoms:
            if atom_base_key(b) in keys or b.serial in excluded:
                continue
            distance = np.linalg.norm(np.array([a.x - b.x, a.y - b.y, a.z - b.z]))
            radii = VDW_RADIUS.get(a.element, 0.16) + VDW_RADIUS.get(b.element, 0.16)
            pairs += distance < 0.85 * radii - 1e-6
            severe += distance < 0.5 * radii
    return int(pairs), int(severe)


@pytest.mark.slow
@pytest.mark.atomistic
def test_saved_2hb_relaxation_removes_severe_clashes_and_preserves_ring_and_neighbors():
    design = Design.from_json(FIXTURE.read_text())
    original_json = design.model_dump_json()
    lesion = design.photoproduct_junctions[0]
    keys = {lesion.base_key_1, lesion.base_key_2}
    before = build_atomistic_model(design)
    relaxed, report = relax_existing_cpd(design, lesion.id)
    after = build_atomistic_model(relaxed)
    assert design.model_dump_json() == original_json
    assert measured_clashes(before, keys) == (
        report["clashes_before"]["count"],
        report["clashes_before"]["severe_count"],
    )
    assert measured_clashes(after, keys) == (report["clashes_after"]["count"], 0)
    assert report["clashes_after"]["count"] < report["clashes_before"]["count"] / 2
    assert report["objective_after"] < report["objective_before"]
    pair_before, pair_after = [], []
    ring_names = {"N1", "C2", "N3", "C4", "C5", "C6", "C7", "O2", "O4"}
    for a, b in zip(before.atoms, after.atoms, strict=True):
        if atom_base_key(a) in keys:
            if a.name in ring_names:
                pair_before.append([a.x, a.y, a.z])
                pair_after.append([b.x, b.y, b.z])
        else:
            np.testing.assert_allclose([a.x, a.y, a.z], [b.x, b.y, b.z], atol=1e-10)
    a, b = np.array(pair_before), np.array(pair_after)
    np.testing.assert_allclose(
        np.linalg.norm(a[:, None] - a, axis=2),
        np.linalg.norm(b[:, None] - b, axis=2),
        atol=1e-10,
    )
    # Signed volume pins handedness in addition to the distances.
    assert np.sign(np.linalg.det(a[1:4] - a[0])) == np.sign(
        np.linalg.det(b[1:4] - b[0])
    )
    # Torsions may change long-range sugar/phosphate distances, but no internal
    # covalent bond or valence angle may stretch, including glycosidic attachment.
    old_atoms = {a.serial: a for a in before.atoms}
    new_atoms = {a.serial: a for a in after.atoms}
    graph = {}
    for i, j in before.bonds:
        if (
            atom_base_key(old_atoms[i]) not in keys
            or atom_base_key(old_atoms[j]) not in keys
        ):
            continue
        graph.setdefault(i, set()).add(j)
        graph.setdefault(j, set()).add(i)

        def xyz(atoms, k):
            a = atoms[k]
            return np.array([a.x, a.y, a.z])

        np.testing.assert_allclose(
            np.linalg.norm(xyz(old_atoms, i) - xyz(old_atoms, j)),
            np.linalg.norm(xyz(new_atoms, i) - xyz(new_atoms, j)),
            atol=1e-10,
        )
    for j, adjacent in graph.items():
        for i in adjacent:
            for k in adjacent:
                # Neighbor-to-neighbor distances plus fixed covalent lengths pin
                # the bond angles, without unstable inverse trig near 180 degrees.
                np.testing.assert_allclose(
                    np.linalg.norm(xyz(old_atoms, i) - xyz(old_atoms, k)),
                    np.linalg.norm(xyz(new_atoms, i) - xyz(new_atoms, k)),
                    atol=1e-10,
                )
    assert report["clashes_after"]["count"] == 0
    assert report["rms_error_after_nm"] < 0.20  # previous relaxed copy was 0.366 nm
    restored = Design.from_json(relaxed.to_json())
    assert restored.photoproduct_junctions[0].bond_relaxation == report


@pytest.mark.slow
@pytest.mark.atomistic
def test_relax_api_is_one_revision_checked_undo_step():
    design = Design.from_json(FIXTURE.read_text())
    state.set_design(design)
    state.clear_history()
    client = TestClient(app)
    revision = state.revision()
    url = f"/api/design/photoproducts/{design.photoproduct_junctions[0].id}/relax"
    response = client.post(url, json={"expected_revision": revision})
    assert response.status_code == 200, response.text
    assert response.json()["bond_relaxation"]["clashes_after"]["severe_count"] == 0
    assert state.undo_depth() == 1
    assert client.post(url, json={"expected_revision": revision}).status_code == 409
    state.undo()
    assert state.get_or_404().nucleotide_transforms == design.nucleotide_transforms
    assert state.get_or_404().photoproduct_junctions == design.photoproduct_junctions


@pytest.mark.slow
@pytest.mark.atomistic
def test_headless_cli_writes_reopenable_copy_and_report(tmp_path):
    output, report = tmp_path / "relaxed.nadoc", tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/relax_cpd_design.py",
            str(FIXTURE),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        env={**os.environ, "PYTHONPATH": "."},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(report.read_text())["products"][0]["clashes_after"]["severe_count"]
        == 0
    )
    assert (
        Design.from_json(output.read_text())
        .photoproduct_junctions[0]
        .bond_relaxation["clashes_after"]["severe_count"]
        == 0
    )


@pytest.mark.slow
@pytest.mark.atomistic
def test_fresh_conversion_matches_saved_relaxation_and_is_stable_on_repeat():
    saved = Design.from_json(FIXTURE.read_text())
    lesion = saved.photoproduct_junctions[0]
    keys = [lesion.base_key_1, lesion.base_key_2]
    # Fixture contains only the two CPD endpoint transforms.
    bare = saved.copy_with(photoproduct_junctions=[], nucleotide_transforms=[])
    fresh, new_lesion = convert_extra_pair(bare, keys)
    old_relaxed, report = relax_existing_cpd(saved, lesion.id)
    again, _ = relax_existing_cpd(fresh, new_lesion.id)
    expected = np.array([[a.x, a.y, a.z] for a in build_atomistic_model(fresh).atoms])
    for other in (old_relaxed, again):
        np.testing.assert_allclose(
            [[a.x, a.y, a.z] for a in build_atomistic_model(other).atoms],
            expected,
            atol=1e-7,
        )
        # Full-view projections must match too, not just the exact atom positions.
        for a, b in zip(
            sorted(fresh.nucleotide_transforms, key=lambda t: t.target_key()),
            sorted(other.nucleotide_transforms, key=lambda t: t.target_key()),
            strict=True,
        ):
            np.testing.assert_allclose(a.translation, b.translation, atol=1e-7)
            np.testing.assert_allclose(a.rotation, b.rotation, atol=1e-7)
    assert new_lesion.bond_relaxation["clashes_after"]["count"] == 0
    assert report["rms_error_after_nm"] < 0.20


def test_nested_torsion_jacobian_matches_independent_finite_differences():
    coordinates = np.random.default_rng(73).normal(size=(8, 3))
    center = coordinates.mean(axis=0)
    torsions = [(0, 1, [1, 2, 3, 4, 5, 6, 7]), (3, 4, [4, 5, 6, 7]), (5, 6, [6, 7])]
    for rotation in ([0.0, 0.0, 0.0], [0.2, -0.5, 0.8]):
        x = np.array([*rotation, 0.1, 0.2, 0.3, 0.8, -1.2, 0.4])
        _, derivative = _pose_with_jacobian(coordinates, center, torsions, x)
        for k in range(len(x)):
            step = np.zeros(len(x))
            step[k] = 1e-6
            estimate = (
                _pose_with_jacobian(coordinates, center, torsions, x + step)[0]
                - _pose_with_jacobian(coordinates, center, torsions, x - step)[0]
            ) / 2e-6
            np.testing.assert_allclose(derivative[:, :, k], estimate, atol=1e-8)
