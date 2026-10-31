"""Root-preserving Relax, joint motion, idempotency and atomic refusal.

Feasible inline-root inputs exercise successful motion. Frozen 2x2 crossover
fixtures retain their Viewer/Export incompatibility and must refuse unchanged.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.direct_relax import relax_direct_binding
from tests.direct_root_fixtures import connected_root_pair, assert_preserved_roots
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Direction,
    Domain,
    Helix,
    OverhangSpec,
    Strand,
    StrandType,
    SubDomain,
    Vec3,
)

client = TestClient(app)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"
_CLOSE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_closebond.nadoc"


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _hinge_angle_deg(design: Design) -> float:
    """Signed x-axis hinge angle of the second (driven) cluster."""
    q = design.cluster_transforms[1].rotation
    return float(np.degrees(2.0 * np.arctan2(q[0], q[3])))


# ── Solver: minimal-motion + idempotency (the reported "overshoot" bug) ───────


def _driver_overhang_rotation(design: Design, driver_oh_id: str) -> np.ndarray:
    return np.asarray(
        next(o for o in design.overhangs if o.id == driver_oh_id).rotation, dtype=float
    )


def test_relax_is_idempotent():
    """A settled nonexempt connection preserves both builder outputs exactly."""
    design = connected_root_pair()
    b = design.overhang_bindings[0]

    out1, _i1 = relax_direct_binding(design, b.driver_oh_id, b.driven_oh_id)
    out2, info2 = relax_direct_binding(out1, b.driver_oh_id, b.driven_oh_id)
    assert info2["final_chord_nm"] == pytest.approx(info2["target_nm"], abs=0.05)
    assert all(abs(t) < 1.0 for t in info2["thetas_deg"])  # arc-min doesn't re-rotate
    # Duplex placement (driver overhang rotation) and driven cluster are unchanged.
    r1 = _driver_overhang_rotation(out1, b.driver_oh_id)
    r2 = _driver_overhang_rotation(out2, b.driver_oh_id)
    assert float(np.linalg.norm(r2 - r1)) < 1e-2
    assert abs(_hinge_angle_deg(out2) - _hinge_angle_deg(out1)) < 1.0
    assert_preserved_roots(out1)
    assert_preserved_roots(out2)
    from backend.core.atomistic import build_atomistic_model
    assert build_atomistic_model(out2) == build_atomistic_model(out1)


def test_relax_opens_an_over_compressed_bond_to_original_length():
    """Manual compression returns to both original covalent lengths, not a CG target."""
    from backend.core.overhang_root_constraints import overhang_root_bond

    design = connected_root_pair(displacement=(0, 0, 0))
    root = overhang_root_bond(design, "oh_b")
    delta = .8 * (root.moving - root.fixed)
    design = design.copy_with(cluster_transforms=[c.model_copy(update={
        "translation": (np.asarray(c.translation) + delta).tolist()})
        if c.id == "cB" else c for c in design.cluster_transforms])
    assert overhang_root_bond(design, "oh_b").length_nm == pytest.approx(.2 * root.length_nm, abs=1e-10)
    b = design.overhang_bindings[0]

    out, info = relax_direct_binding(design, b.driver_oh_id, b.driven_oh_id)
    assert info["final_chord_nm"] == pytest.approx(info["target_nm"], abs=0.15)
    assert_preserved_roots(out)


def test_relax_closes_a_stretched_bond_via_cluster_motion_only():
    """Only the declared joint moves the parent; the duplex fit preserves both roots."""
    from backend.core.models import ClusterJoint, _local_to_world_joint
    from backend.core.linker_relax import _composed_transform

    design = connected_root_pair(displacement=(0, 0, 0))
    b = design.overhang_bindings[0]
    parent = next(c for c in design.cluster_transforms if c.id == "cB")
    joint = ClusterJoint(id="fixture-hinge", cluster_id=parent.id,
        local_axis_origin=[-5., 0., 0.], local_axis_direction=[0., 1., 0.],
        min_angle_deg=-180., max_angle_deg=180.)
    origin, axis = _local_to_world_joint(joint.local_axis_origin, joint.local_axis_direction, parent)
    q, t = _composed_transform(parent, np.asarray(origin), np.asarray(axis), np.pi / 2)
    design = design.copy_with(cluster_joints=[joint], cluster_transforms=[c.model_copy(update={
        "rotation": q, "translation": t}) if c.id == parent.id else c for c in design.cluster_transforms])

    out, info = relax_direct_binding(design, b.driver_oh_id, b.driven_oh_id)
    assert info["final_chord_nm"] == pytest.approx(info["target_nm"], abs=0.2)
    assert any(
        abs(t) > 1.0 for t in info["thetas_deg"]
    )  # the joint carried the closure
    assert info["moved_cluster_ids"] == [parent.id]
    assert_preserved_roots(out)
    assert out.strands == design.strands
    assert out.helices == design.helices
    moved_parent = next(c for c in design.cluster_transforms if c.id == parent.id)
    origin, axis = _local_to_world_joint(joint.local_axis_origin, joint.local_axis_direction, moved_parent)
    q, t = _composed_transform(moved_parent, np.asarray(origin), np.asarray(axis),
                              np.deg2rad(info["thetas_deg"][0]))
    actual = next(c for c in out.cluster_transforms if c.id == parent.id)
    np.testing.assert_allclose(actual.rotation, q, atol=1e-10)
    np.testing.assert_allclose(actual.translation, t, atol=1e-10)


# ── Route: relax a bound duplex (Proposal-B path) ─────────────────────────────


def test_relax_bound_duplex_route_closes_and_is_idempotent():
    """The duplex HTTP route preserves both roots and a repeated Relax stays put."""
    design = connected_root_pair()
    dx = design.duplexes[0].model_copy(update={"bound": True})
    design = design.model_copy(update={"duplexes": [dx]})
    design_state.set_design(design)

    r = client.post(f"/api/design/duplexes/{dx.id}/relax")
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    assert info["final_chord_nm"] == pytest.approx(info["target_nm"], abs=0.6)
    assert_preserved_roots(design_state.get_or_404())
    poses = design_state.get_or_404().cluster_transforms
    assert client.post(f"/api/design/duplexes/{dx.id}/relax").status_code == 200
    assert design_state.get_or_404().cluster_transforms == poses


@pytest.mark.parametrize("path", [_FIXTURE, _CLOSE_FIXTURE], ids=["stretched", "compressed"])
def test_frozen_2x2_linker_conflict_refuses_without_history_or_pose_change(path):
    """Keep the original assets: neither builder's covalent length may be sacrificed."""
    from fastapi import HTTPException
    if not path.exists():
        pytest.skip(f"{path.name} fixture missing")
    design = Design.model_validate_json(path.read_text())
    binding = design.overhang_bindings[0]
    before = design.model_dump_json()
    with pytest.raises(HTTPException, match="native viewer and export root linkers"):
        relax_direct_binding(design, binding.driver_oh_id, binding.driven_oh_id)
    assert design.model_dump_json() == before
    dx = design.duplexes[0].model_copy(update={"bound": True})
    design_state.load_design(design.copy_with(duplexes=[dx]))
    current, revision = design_state.get_design_with_revision()
    depth = design_state.undo_depth()
    response = client.post(f"/api/design/duplexes/{dx.id}/relax")
    assert response.status_code == 422
    assert "native viewer and export root linkers" in response.json()["detail"]
    assert design_state.get_design_with_revision() == (current, revision)
    assert design_state.undo_depth() == depth


# ── Route guards ──────────────────────────────────────────────────────────────


def _helix(hid, length, *, x=0.0):
    return Helix(
        id=hid,
        axis_start=Vec3(x=x, y=0.0, z=0.0),
        axis_end=Vec3(x=x, y=0.0, z=length * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length,
        grid_pos=(0, 0),
    )


def _simple_design() -> Design:
    st_drv = Strand(
        id="st_drv",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="h_drv",
                start_bp=0,
                end_bp=23,
                direction=Direction.FORWARD,
                overhang_id="OHd",
            )
        ],
    )
    st_drvn = Strand(
        id="st_drvn",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="h_drvn",
                start_bp=0,
                end_bp=9,
                direction=Direction.FORWARD,
                overhang_id="OHn",
            )
        ],
    )
    ohd = OverhangSpec(
        id="OHd",
        helix_id="h_drv",
        strand_id="st_drv",
        sequence="A" * 24,
        sub_domains=[SubDomain(id="sdd", start_bp_offset=0, length_bp=24)],
    )
    ohn = OverhangSpec(
        id="OHn",
        helix_id="h_drvn",
        strand_id="st_drvn",
        sequence="T" * 10,
        sub_domains=[SubDomain(id="sdn", start_bp_offset=0, length_bp=10)],
    )
    return Design(
        helices=[_helix("h_drv", 24), _helix("h_drvn", 10, x=8.0)],
        strands=[st_drv, st_drvn],
        overhangs=[ohd, ohn],
        cluster_transforms=[
            ClusterRigidTransform(id="c1", name="C1", helix_ids=["h_drv"]),
            ClusterRigidTransform(id="c2", name="C2", helix_ids=["h_drvn"]),
        ],
    )


def test_relax_unbound_duplex_is_422():
    design_state.set_design(_simple_design())
    r = client.post(
        "/api/design/duplexes",
        json={
            "left": {"overhang_id": "OHd", "start_bp": 0, "end_bp": 9},
            "right": {"overhang_id": "OHn", "start_bp": 9, "end_bp": 0},
            "driver": "left",
            "bound": False,
        },
    )
    assert r.status_code == 201, r.text
    dxid = r.json()["duplex_id"]
    r2 = client.post(f"/api/design/duplexes/{dxid}/relax")
    assert r2.status_code == 422, r2.text
    assert "not bound" in r2.json()["detail"].lower()


def test_relax_unknown_duplex_is_404():
    design_state.set_design(_simple_design())
    r = client.post("/api/design/duplexes/does-not-exist/relax")
    assert r.status_code == 404, r.text
