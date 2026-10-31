"""Automatic rigid fitting preserves a real native covalent root; manual edits do not clamp."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.design_geometry import fitting_geometry
from backend.core.lattice import make_overhang_extrude
from backend.core.overhang_root_constraints import (
    overhang_root_bond,
    root_preserving_rolls,
    rotate_overhang_about,
)
from tests.conftest import valid_overhang_sites
from tests.test_overhang_geometry import _make_stapled_6hb


@pytest.fixture(params=[False, True], ids=["3prime", "5prime"])
def rooted(request):
    source = _make_stapled_6hb(42)
    site = next(
        s for s in valid_overhang_sites(source) if s["is_five_prime"] == request.param
    )
    out = make_overhang_extrude(source, **site, length_bp=12)
    oid = next(
        o.id for o in out.overhangs if o.id not in {o.id for o in source.overhangs}
    )
    return out, oid


def test_repeated_automatic_rotations_preserve_covalent_root_and_host(rooted):
    source, oid = rooted
    baseline = overhang_root_bond(source, oid)
    before = fitting_geometry(source)
    unchanged = source.model_dump_json()
    result = source
    for angles in ([70, -35, 120], [-25, 115, 30]):
        rotation = Rotation.from_euler("xyz", angles, degrees=True).as_matrix()
        result = rotate_overhang_about(result, oid, rotation, baseline.fixed)
        measured = overhang_root_bond(result, oid)
        assert measured.length_nm == pytest.approx(baseline.length_nm, abs=1e-9)
        np.testing.assert_allclose(measured.fixed, baseline.fixed, atol=1e-10)
    after = fitting_geometry(result)
    assert [n for n in before if n.get("overhang_id") != oid] == [
        n for n in after if n.get("overhang_id") != oid
    ]
    assert source.model_dump_json() == unchanged
    # Persisted native poses, not display-only corrections.
    restored = type(result).model_validate_json(result.model_dump_json())
    assert fitting_geometry(restored) == after


def test_manual_cluster_translation_can_stretch_root(rooted):
    source, oid = rooted
    baseline = overhang_root_bond(source, oid)
    materialized = rotate_overhang_about(source, oid, np.eye(3), baseline.fixed)
    from backend.core.duplex_cluster import duplex_cluster_for

    cluster = duplex_cluster_for(materialized, oid)
    moved = materialized.copy_with(
        cluster_transforms=[
            c.model_copy(
                update={
                    "translation": (np.asarray(c.translation) + [10, 0, 0]).tolist()
                }
            )
            if c.id == cluster.id
            else c
            for c in materialized.cluster_transforms
        ]
    )
    assert overhang_root_bond(moved, oid).length_nm > baseline.length_nm + 5


def test_roll_constraint_preserves_viewer_and_export_root_bonds(rooted):
    source, oid = rooted
    fast = overhang_root_bond(source, oid)
    exported = overhang_root_bond(source, oid, fast_bridges=False)
    axis = np.array([0.3, 0.7, 0.4])
    axis /= np.linalg.norm(axis)
    rolls = root_preserving_rolls(np.eye(3), axis, fast.fixed, exported, [0.0])
    assert len(rolls)
    for roll in rolls:
        out = rotate_overhang_about(
            source, oid, Rotation.from_rotvec(axis * roll).as_matrix(), fast.fixed
        )
        for mode, expected in ((True, fast), (False, exported)):
            assert overhang_root_bond(
                out, oid, fast_bridges=mode
            ).length_nm == pytest.approx(expected.length_nm, abs=1e-9)


def test_attachment_preserves_root_after_collective_solve_and_final_fit(rooted):
    from backend.api.nanoparticle_attachment import attach_nanoparticle
    from backend.core.models import Nanoparticle
    from backend.core.nanoparticle import build_thiol_conjugation
    from backend.core.sequences import assign_scaffold_sequence, assign_staple_sequences

    source, oid = rooted
    source, _, _ = assign_scaffold_sequence(source)
    sequence = "ACGTGACTCAGT"
    source = assign_staple_sequences(
        source.copy_with(
            overhangs=[
                o.model_copy(update={"sequence": sequence}) if o.id == oid else o
                for o in source.overhangs
            ]
        )
    )
    particle = Nanoparticle(diameter_nm=10)
    owner, helices, strands = build_thiol_conjugation(
        particle,
        scheme="direct_thiol",
        sequence="ACTGAGTCACGT",
        count=1,
    )
    source = source.copy_with(
        nanoparticles=[particle],
        nanoparticle_conjugations=[owner],
        helices=[*source.helices, *helices],
        strands=[*source.strands, *strands],
    )
    baseline = {
        fast: overhang_root_bond(source, oid, fast_bridges=fast)
        for fast in (True, False)
    }
    out, report = attach_nanoparticle(source, particle.id, oid)
    assert report["residual_nm"] < 0.02
    for fast, before in baseline.items():
        assert overhang_root_bond(
            out, oid, fast_bridges=fast
        ).length_nm == pytest.approx(before.length_nm, abs=1e-8)


def test_fit_accepts_collision_without_changing_root_radius():
    from scipy.spatial import cKDTree
    from types import SimpleNamespace
    from backend.core.nanoparticle_attachment_fit import fit_swing

    version = SimpleNamespace(strand_id="handle", overhang_id="oh")
    points = [
        {
            "strand_id": "handle",
            "backbone_position": [3.0, 0.0, 0.0],
            "base_position": [3.0, 0.1, 0.0],
        }
    ]
    target, rotation, _ = fit_swing(
        np.zeros(3),
        np.array([3.0, 0.0, 0.0]),
        np.array([3.0, 0.0, 0.0]),
        2.0,
        np.eye(3),
        points,
        version,
        [SimpleNamespace(diameter_nm=200.0)],
        [np.zeros(3)],
        obstacle_tree=cKDTree([[0.0, 0.0, 0.0]]),
    )
    assert np.linalg.norm(target) == pytest.approx(3.0)
    assert np.linalg.norm(target - [3.0, 0.0, 0.0]) == pytest.approx(2.0)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
