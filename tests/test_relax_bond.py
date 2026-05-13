"""Tests for the generic relax-bond endpoint (POST /design/relax-bond).

Covers:
  * Crossover record path — anchor lookup + cluster resolution.
  * Forced ligation record path.
  * Half-edge addressing (side_a + side_b) for arbitrary bonds.
  * 0-DOF rigid translate (no joints between clusters): side_to_move
    chosen by the user.
  * 1-DOF joint rotate (one joint connects the clusters).
  * Same-cluster refusal (422).
  * Type-specific default chord targets (crossover → 0.67, ligation → 0).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    ClusterJoint, ClusterRigidTransform,
    Crossover, Direction, Domain, ForcedLigation,
    HalfCrossover, Helix, Strand, StrandType, Vec3,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _seed_two_helices_separate_clusters(
    *, with_joint: bool = False, with_crossover: bool = True,
) -> object:
    """Two parallel helices, each in its own cluster, optionally joined.
    Returns the seeded Design.
    """
    base = _demo_design()
    L = 12
    h_a = Helix(
        id="bond_h_a",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
        phase_offset=0.0, length_bp=L, grid_pos=(0, 0),
    )
    h_b = Helix(
        id="bond_h_b",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=L * BDNA_RISE_PER_BP),
        phase_offset=0.0, length_bp=L, grid_pos=(0, 1),
    )
    strand_a = Strand(
        id="bond_strand_a",
        domains=[Domain(
            helix_id="bond_h_a", start_bp=0, end_bp=L - 1,
            direction=Direction.FORWARD,
        )],
        strand_type=StrandType.STAPLE,
    )
    strand_b = Strand(
        id="bond_strand_b",
        domains=[Domain(
            helix_id="bond_h_b", start_bp=0, end_bp=L - 1,
            direction=Direction.REVERSE,
        )],
        strand_type=StrandType.STAPLE,
    )
    cluster_a = ClusterRigidTransform(
        id="bond_cluster_a", name="A",
        helix_ids=["bond_h_a"],
        translation=[0.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
        pivot=[0.0, 0.0, 0.0],
    )
    cluster_b = ClusterRigidTransform(
        id="bond_cluster_b", name="B",
        helix_ids=["bond_h_b"],
        translation=[0.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
        pivot=[0.0, 0.0, 0.0],
    )
    joints = []
    if with_joint:
        joints.append(ClusterJoint(
            id="bond_joint",
            cluster_id="bond_cluster_a",
            name="Hinge",
            local_axis_origin=[1.25, 0.0, L * BDNA_RISE_PER_BP / 2],
            local_axis_direction=[0.0, 1.0, 0.0],
            min_angle_deg=-90.0,
            max_angle_deg=+90.0,
        ))
    crossovers = list(base.crossovers)
    if with_crossover:
        crossovers.append(Crossover(
            id="bond_xover_01",
            half_a=HalfCrossover(helix_id="bond_h_a", index=6, strand=Direction.FORWARD),
            half_b=HalfCrossover(helix_id="bond_h_b", index=6, strand=Direction.REVERSE),
        ))
    return base.model_copy(update={
        "helices": [*base.helices, h_a, h_b],
        "strands": [*base.strands, strand_a, strand_b],
        "cluster_transforms": [cluster_a, cluster_b],
        "cluster_joints": joints,
        "crossovers": crossovers,
    })


# ── 0-DOF: rigid translate ──────────────────────────────────────────────────

def test_relax_bond_crossover_0_dof_translates_chosen_side():
    """No joints between clusters → side_to_move picks which cluster
    translates. The chord is pulled to the type-default target_nm."""
    seeded = _seed_two_helices_separate_clusters(with_joint=False)
    design_state.set_design(seeded)
    pre = design_state.get_or_404()
    ct_b_pre = next(c for c in pre.cluster_transforms if c.id == "bond_cluster_b").translation

    r = client.post("/api/design/relax-bond", json={
        "bond_type": "crossover",
        "bond_id": "bond_xover_01",
        "side_to_move": "b",
    })
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    assert info["mode"] == "translate"
    assert info["moved_cluster"] == "bond_cluster_b"

    post = design_state.get_or_404()
    ct_b_post = next(c for c in post.cluster_transforms if c.id == "bond_cluster_b").translation
    ct_a_post = next(c for c in post.cluster_transforms if c.id == "bond_cluster_a").translation
    # Side A unchanged.
    assert ct_a_post == [0.0, 0.0, 0.0]
    # Side B moved.
    assert ct_b_post != ct_b_pre


def test_relax_bond_0_dof_requires_side_to_move():
    """0-DOF case without side_to_move → 422 (the optimizer can't pick)."""
    seeded = _seed_two_helices_separate_clusters(with_joint=False)
    design_state.set_design(seeded)
    r = client.post("/api/design/relax-bond", json={
        "bond_type": "crossover",
        "bond_id": "bond_xover_01",
    })
    assert r.status_code == 422, r.text
    assert "side_to_move" in r.json()["detail"].lower()


# ── 1-DOF: joint rotate ────────────────────────────────────────────────────

def test_relax_bond_1_dof_rotates_joint_cluster():
    """One joint between the two clusters → side_to_move ignored, joint
    optimisation rotates the joint's owning cluster to close the chord."""
    seeded = _seed_two_helices_separate_clusters(with_joint=True)
    design_state.set_design(seeded)
    r = client.post("/api/design/relax-bond", json={
        "bond_type": "crossover",
        "bond_id": "bond_xover_01",
    })
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    assert info["mode"] == "1dof"
    assert info["joint_id"] == "bond_joint"
    assert info["moved_cluster"] == "bond_cluster_a"


# ── Forced ligation path ───────────────────────────────────────────────────

def test_relax_bond_ligation_record_path():
    """Forced ligation: bond_id resolves to a ForcedLigation. Default
    chord target is 0 (endpoints should coincide)."""
    seeded = _seed_two_helices_separate_clusters(
        with_joint=False, with_crossover=False,
    )
    fl = ForcedLigation(
        id="bond_fl_01",
        three_prime_helix_id="bond_h_a",
        three_prime_bp=8,
        three_prime_direction=Direction.FORWARD,
        five_prime_helix_id="bond_h_b",
        five_prime_bp=8,
        five_prime_direction=Direction.REVERSE,
    )
    seeded = seeded.model_copy(update={"forced_ligations": [fl]})
    design_state.set_design(seeded)
    r = client.post("/api/design/relax-bond", json={
        "bond_type": "ligation",
        "bond_id": "bond_fl_01",
        "side_to_move": "b",
    })
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    assert info["mode"] == "translate"
    # Chord after = target = 0 for ligation.
    assert info["chord_nm_after"] == 0.0


# ── Half-edge addressing ───────────────────────────────────────────────────

def test_relax_bond_half_edge_addressing():
    """When bond_id isn't provided, side_a + side_b half-edge endpoints
    resolve to the two nuc positions directly. Useful for strand-arc
    bonds that don't have a record id."""
    seeded = _seed_two_helices_separate_clusters(with_joint=False)
    design_state.set_design(seeded)
    r = client.post("/api/design/relax-bond", json={
        "bond_type": "strand_arc",
        "side_a": {"helix_id": "bond_h_a", "bp_index": 5,
                   "direction": "FORWARD"},
        "side_b": {"helix_id": "bond_h_b", "bp_index": 5,
                   "direction": "REVERSE"},
        "side_to_move": "a",
    })
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    assert info["mode"] == "translate"
    assert info["moved_cluster"] == "bond_cluster_a"


# ── Same-cluster refusal ───────────────────────────────────────────────────

def test_relax_bond_same_cluster_refused():
    """When both endpoints are owned by the same cluster, no relaxation
    is possible — 422 with an explanatory message."""
    base = _seed_two_helices_separate_clusters(with_joint=False)
    # Merge the two clusters → single cluster covering both helices.
    merged = base.model_copy(update={
        "cluster_transforms": [
            ClusterRigidTransform(
                id="bond_cluster_a", name="A+B",
                helix_ids=["bond_h_a", "bond_h_b"],
                translation=[0.0, 0.0, 0.0],
                rotation=[0.0, 0.0, 0.0, 1.0],
                pivot=[0.0, 0.0, 0.0],
            ),
        ],
    })
    design_state.set_design(merged)
    r = client.post("/api/design/relax-bond", json={
        "bond_type": "crossover",
        "bond_id": "bond_xover_01",
        "side_to_move": "b",
    })
    assert r.status_code == 422, r.text
    detail = r.json()["detail"].lower()
    assert "share a cluster" in detail or "single" in detail


# ── Target override ────────────────────────────────────────────────────────

def test_relax_bond_target_nm_override():
    """target_nm in the request body overrides the type-default."""
    seeded = _seed_two_helices_separate_clusters(with_joint=False)
    design_state.set_design(seeded)
    r = client.post("/api/design/relax-bond", json={
        "bond_type": "crossover",
        "bond_id": "bond_xover_01",
        "side_to_move": "b",
        "target_nm": 1.5,
    })
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    assert info["chord_nm_after"] == 1.5
