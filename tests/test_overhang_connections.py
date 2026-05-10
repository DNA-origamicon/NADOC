"""
Tests for the metadata-only OverhangConnection feature.

Endpoints under test:
  POST   /design/overhang-connections
  DELETE /design/overhang-connections/{conn_id}

These records are pure annotations — no strand topology is mutated. The API
is tested against a synthetic design seeded with two minimal OverhangSpecs.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.atomistic import _SUGAR, _atom_frame, build_atomistic_model
from backend.core.deformation import deformed_nucleotide_arrays, effective_helix_for_geometry, _normalize_helix_for_grid
from backend.core.geometry import nucleotide_positions
from backend.core.lattice import assign_overhang_connection_names
from backend.core.models import (
    Design, Direction, Domain, Helix, OverhangConnection, OverhangSpec,
    Strand, StrandType, Vec3,
)


client = TestClient(app)


def _seed_with_two_overhangs() -> Design:
    """Demo design plus four synthetic OverhangSpec entries (no real geometry).

    Four overhangs (two 5p, two 3p) so tests can build multiple connections
    without bumping into the per-end uniqueness rule.
    """
    base = _demo_design()
    overhangs = [
        OverhangSpec(id="ovhg_inline_a_5p", helix_id="demo_helix", strand_id="staple_0", label="OH1"),
        OverhangSpec(id="ovhg_inline_a_3p", helix_id="demo_helix", strand_id="staple_0", label="OH2"),
        OverhangSpec(id="ovhg_inline_b_5p", helix_id="demo_helix", strand_id="staple_0", label="OH3"),
        OverhangSpec(id="ovhg_inline_b_3p", helix_id="demo_helix", strand_id="staple_0", label="OH4"),
    ]
    return base.model_copy(update={"overhangs": overhangs})


def _seed_with_two_5p_overhangs() -> Design:
    """Demo design with two 5p overhangs (same-end pair — rule constraints apply)."""
    base = _demo_design()
    overhangs = [
        OverhangSpec(id="ovhg_inline_a_5p", helix_id="demo_helix", strand_id="staple_0", label="OH1"),
        OverhangSpec(id="ovhg_inline_b_5p", helix_id="demo_helix", strand_id="staple_0", label="OH2"),
    ]
    return base.model_copy(update={"overhangs": overhangs})


def _seed_with_real_oh_domains() -> Design:
    """Two extruded overhang helices, each with a staple strand whose only
    domain has overhang_id set. Mirrors what an actual user design looks like
    after Tools → Extrude Overhang. Used to validate that ds linker complement
    domains are placed on the real OH helices.
    """
    base = _demo_design()
    oh_helix_a = Helix(
        id="oh_helix_a",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=8,
        grid_pos=(0, 0),
    )
    oh_helix_b = Helix(
        id="oh_helix_b",
        axis_start=Vec3(x=5.0, y=0.0, z=0.0),
        axis_end=Vec3(x=5.0, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=8,
        grid_pos=(0, 3),
    )
    oh_strand_a = Strand(
        id="oh_strand_a",
        domains=[Domain(
            helix_id="oh_helix_a", start_bp=0, end_bp=7,
            direction=Direction.FORWARD, overhang_id="oh_a_5p",
        )],
        strand_type=StrandType.STAPLE,
    )
    oh_strand_b = Strand(
        id="oh_strand_b",
        domains=[Domain(
            helix_id="oh_helix_b", start_bp=0, end_bp=7,
            direction=Direction.REVERSE, overhang_id="oh_b_5p",
        )],
        strand_type=StrandType.STAPLE,
    )
    overhangs = [
        OverhangSpec(id="oh_a_5p", helix_id="oh_helix_a", strand_id="oh_strand_a", label="OHA"),
        OverhangSpec(id="oh_b_5p", helix_id="oh_helix_b", strand_id="oh_strand_b", label="OHB"),
    ]
    return base.model_copy(update={
        "helices": [*base.helices, oh_helix_a, oh_helix_b],
        "strands": [*base.strands, oh_strand_a, oh_strand_b],
        "overhangs": overhangs,
    })


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_seed_with_two_overhangs())
    yield
    design_state.set_design(_demo_design())


# ── POST ──────────────────────────────────────────────────────────────────────


def _post_conn(**overrides) -> dict:
    # Default: 5p+free_end (comp-first) and 3p+free_end (bridge-first) — a valid
    # ss polarity combo (mixed sides). Tests that vary `linker_type=ds` get a
    # mixed-polarity request which the new rule rejects; those tests pass an
    # explicit `overhang_b_attach` to land on a matching-polarity ds combo.
    body = {
        "overhang_a_id": "ovhg_inline_a_5p",
        "overhang_a_attach": "free_end",
        "overhang_b_id": "ovhg_inline_a_3p",
        "overhang_b_attach": "free_end",
        "linker_type": "ss",
        "length_value": 12,
        "length_unit": "bp",
    }
    body.update(overrides)
    r = client.post("/api/design/overhang-connections", json=body)
    return r


# Helper for tests that need a SECOND connection — uses OH3+OH4.
def _post_conn_2(**overrides) -> dict:
    body = {
        "overhang_a_id": "ovhg_inline_b_5p",
        "overhang_a_attach": "free_end",
        "overhang_b_id": "ovhg_inline_b_3p",
        "overhang_b_attach": "root",
        "linker_type": "ds",
        "length_value": 8,
        "length_unit": "bp",
    }
    body.update(overrides)
    r = client.post("/api/design/overhang-connections", json=body)
    return r


def test_post_creates_connection_with_l1_name():
    r = _post_conn()
    assert r.status_code == 201, r.text
    conns = r.json()["design"]["overhang_connections"]
    assert len(conns) == 1
    assert conns[0]["name"] == "L1"
    assert conns[0]["overhang_a_attach"] == "free_end"
    assert conns[0]["overhang_b_attach"] == "free_end"
    assert conns[0]["linker_type"] == "ss"
    assert conns[0]["length_value"] == 12
    assert conns[0]["length_unit"] == "bp"


def test_second_post_yields_l2():
    _post_conn()
    r = _post_conn_2(length_value=4.08, length_unit="nm")
    assert r.status_code == 201
    conns = r.json()["design"]["overhang_connections"]
    names = sorted(c["name"] for c in conns)
    assert names == ["L1", "L2"]


def test_delete_removes_by_id_and_preserves_others():
    _post_conn()
    r = _post_conn_2(length_value=20)
    conns = r.json()["design"]["overhang_connections"]
    l1_id = next(c["id"] for c in conns if c["name"] == "L1")

    r = client.delete(f"/api/design/overhang-connections/{l1_id}")
    assert r.status_code == 200
    remaining = r.json()["design"]["overhang_connections"]
    assert len(remaining) == 1
    assert remaining[0]["name"] == "L2"


def test_post_after_delete_reuses_lowest_unused_name():
    """After deleting L1, a fresh POST should fill the L1 slot, not L3."""
    _post_conn()       # L1 — uses OH1 + OH2
    _post_conn_2()     # L2 — uses OH3 + OH4
    r = client.get("/api/design").json()
    l1_id = next(c["id"] for c in r["design"]["overhang_connections"] if c["name"] == "L1")
    client.delete(f"/api/design/overhang-connections/{l1_id}")
    # OH1 + OH2 are now free; reposting fills the L1 slot.
    r = _post_conn()
    names = sorted(c["name"] for c in r.json()["design"]["overhang_connections"])
    assert names == ["L1", "L2"]


def test_same_overhang_on_both_sides_is_400():
    r = _post_conn(overhang_b_id="ovhg_inline_a_5p")
    assert r.status_code == 400


def test_unknown_overhang_id_is_404():
    r = _post_conn(overhang_a_id="ovhg_does_not_exist")
    assert r.status_code == 404


def test_zero_length_is_400():
    r = _post_conn(length_value=0)
    assert r.status_code == 400


def test_invalid_attach_value_is_422():
    r = _post_conn(overhang_a_attach="middle")  # not a Literal value
    assert r.status_code == 422


def test_delete_unknown_id_is_404():
    r = client.delete("/api/design/overhang-connections/does-not-exist")
    assert r.status_code == 404


def test_reconcile_preserves_overhangs_referenced_by_linker():
    """Regression: `_reconcile_inline_overhangs` used to strip an inline
    overhang tag whenever the staple's terminal domain no longer extended
    beyond the scaffold boundary — even when an active OverhangConnection
    referenced that overhang. Result: linkers silently lost their anchor
    metadata on every save→load round-trip (the polymer-hinge file bug).

    With the protected-id guard in place, overhangs referenced by any
    overhang_connection MUST survive reconciliation regardless of current
    scaffold coverage.
    """
    from backend.core.lattice import reconcile_all_inline_overhangs
    from backend.core.models import (
        Design, Strand, Domain, Helix, OverhangSpec, OverhangConnection,
        Direction, StrandType, LatticeType, DesignMetadata, Vec3,
    )
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=42 * BDNA_RISE_PER_BP),
        length_bp=42,
    )
    # Scaffold covers bp 10–30. The two staples' 3' ends sit FLUSH with the
    # scaffold boundary (no extension beyond), but each carries an inline
    # overhang tag referenced by linker L1. Without the protected-id guard
    # the reconciler strips both tags + their OverhangSpecs.
    scaf = Strand(id="scaf", strand_type=StrandType.SCAFFOLD,
        domains=[Domain(helix_id="h0", start_bp=10, end_bp=30, direction=Direction.FORWARD)])
    stap_a = Strand(id="stap_a", strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="h0", start_bp=30, end_bp=10, direction=Direction.REVERSE,
                        overhang_id="ovhg_inline_stap_a_3p")])
    stap_b = Strand(id="stap_b", strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="h0", start_bp=10, end_bp=30, direction=Direction.FORWARD,
                        overhang_id="ovhg_inline_stap_b_3p")])
    ov_a = OverhangSpec(id="ovhg_inline_stap_a_3p", helix_id="h0", strand_id="stap_a", label="OH1")
    ov_b = OverhangSpec(id="ovhg_inline_stap_b_3p", helix_id="h0", strand_id="stap_b", label="OH2")
    linker = OverhangConnection(id="L1", name="L1",
        overhang_a_id="ovhg_inline_stap_a_3p", overhang_a_attach="free_end",
        overhang_b_id="ovhg_inline_stap_b_3p", overhang_b_attach="free_end",
        linker_type="ds", length_value=10.0, length_unit="bp")
    d = Design(id="d", helices=[helix], strands=[scaf, stap_a, stap_b],
        overhangs=[ov_a, ov_b], overhang_connections=[linker],
        lattice_type=LatticeType.HONEYCOMB, metadata=DesignMetadata(name="t"))

    d2 = reconcile_all_inline_overhangs(d)

    survived = {o.id for o in d2.overhangs}
    assert "ovhg_inline_stap_a_3p" in survived
    assert "ovhg_inline_stap_b_3p" in survived
    # Domain tags also preserved — required for downstream
    # _overhang_helix_id lookup → cluster ownership → DOF topology → relax.
    assert d2.strands[1].domains[0].overhang_id == "ovhg_inline_stap_a_3p"
    assert d2.strands[2].domains[0].overhang_id == "ovhg_inline_stap_b_3p"
    # Linker still resolves to non-dangling endpoints.
    assert len(d2.overhang_connections) == 1


def test_migrate_split_staple_domains_merges_stale_splits():
    """Regression: an earlier ``_reconcile_inline_overhangs`` bug saved staples
    as two adjacent same-helix / same-direction domains where the Domain
    invariant ("a contiguous run of nucleotides") demands one — e.g.
    ``stap_19_92`` in *Ultimate Polymer Hinge*. ``migrate_split_staple_domains``
    runs at load time and merges those.

    Three pairs cover the matrix:
      - ``stap_stale_none``: ``(None, None)`` — the most common stale split.
      - ``stap_stale_inline``: stale ``ovhg_inline_`` tag whose combined range
         lies fully within scaffold coverage; tag and OverhangSpec must be
         dropped.
      - ``stap_legit_overhang``: the overhang half extends beyond scaffold;
         the split is real and must survive untouched.
    """
    from backend.core.lattice import migrate_split_staple_domains
    from backend.core.models import (
        Design, Strand, Domain, Helix, OverhangSpec,
        Direction, StrandType, LatticeType, DesignMetadata, Vec3,
    )

    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=100 * BDNA_RISE_PER_BP),
        length_bp=100,
    )
    # Scaffold covers bp 10–90.
    scaf = Strand(id="scaf", strand_type=StrandType.SCAFFOLD,
        domains=[Domain(helix_id="h0", start_bp=10, end_bp=90, direction=Direction.FORWARD)])

    # Stale split, both halves untagged. Combined 20-39 fully inside scaffold.
    stap_stale_none = Strand(id="stap_stale_none", strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=39, end_bp=30, direction=Direction.REVERSE),
            Domain(helix_id="h0", start_bp=29, end_bp=20, direction=Direction.REVERSE),
        ])

    # Stale split with stale ovhg_inline_ tag on the 5p half. Combined 50-69
    # is fully inside scaffold, so the tag is bogus and must go.
    stap_stale_inline = Strand(id="stap_stale_inline", strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=50, end_bp=59, direction=Direction.FORWARD,
                   overhang_id="ovhg_inline_stap_stale_inline_5p"),
            Domain(helix_id="h0", start_bp=60, end_bp=69, direction=Direction.FORWARD),
        ])
    stale_spec = OverhangSpec(
        id="ovhg_inline_stap_stale_inline_5p", helix_id="h0",
        strand_id="stap_stale_inline", label="OHstale")

    # Legitimate inline overhang: 5p half (bp 5-9) sits outside scaffold (lo=10),
    # so the split is real. Must NOT be merged.
    stap_legit = Strand(id="stap_legit_overhang", strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=5, end_bp=9, direction=Direction.FORWARD,
                   overhang_id="ovhg_inline_stap_legit_overhang_5p"),
            Domain(helix_id="h0", start_bp=10, end_bp=25, direction=Direction.FORWARD),
        ])
    legit_spec = OverhangSpec(
        id="ovhg_inline_stap_legit_overhang_5p", helix_id="h0",
        strand_id="stap_legit_overhang", label="OHkeep", sequence="GATTA")

    d = Design(id="d", helices=[helix],
        strands=[scaf, stap_stale_none, stap_stale_inline, stap_legit],
        overhangs=[stale_spec, legit_spec],
        lattice_type=LatticeType.HONEYCOMB, metadata=DesignMetadata(name="t"))

    out = migrate_split_staple_domains(d)
    by_id = {s.id: s for s in out.strands}

    # Untagged stale split → single domain spanning 39→20.
    none_doms = by_id["stap_stale_none"].domains
    assert len(none_doms) == 1
    assert (none_doms[0].start_bp, none_doms[0].end_bp) == (39, 20)
    assert none_doms[0].overhang_id is None

    # Inline-tagged stale split → single domain 50→69; tag + spec removed.
    inline_doms = by_id["stap_stale_inline"].domains
    assert len(inline_doms) == 1
    assert (inline_doms[0].start_bp, inline_doms[0].end_bp) == (50, 69)
    assert inline_doms[0].overhang_id is None
    assert all(o.id != "ovhg_inline_stap_stale_inline_5p" for o in out.overhangs)

    # Legitimate split untouched — both domains and OverhangSpec preserved.
    legit_doms = by_id["stap_legit_overhang"].domains
    assert len(legit_doms) == 2
    assert legit_doms[0].overhang_id == "ovhg_inline_stap_legit_overhang_5p"
    assert any(o.id == "ovhg_inline_stap_legit_overhang_5p" and o.sequence == "GATTA"
               for o in out.overhangs)

    # Idempotent on a clean design.
    out2 = migrate_split_staple_domains(out)
    assert [s.model_dump() for s in out2.strands] == [s.model_dump() for s in out.strands]
    assert [o.model_dump() for o in out2.overhangs] == [o.model_dump() for o in out.overhangs]


def test_migrate_split_staple_domains_respects_protected_overhangs():
    """A linker-anchored overhang must survive the migration even if its
    domain split would otherwise look stale (combined range fully inside
    scaffold coverage). Mirrors the protected-id guard in reconcile."""
    from backend.core.lattice import migrate_split_staple_domains
    from backend.core.models import (
        Design, Strand, Domain, Helix, OverhangSpec, OverhangConnection,
        Direction, StrandType, LatticeType, DesignMetadata, Vec3,
    )

    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=100 * BDNA_RISE_PER_BP),
        length_bp=100,
    )
    scaf = Strand(id="scaf", strand_type=StrandType.SCAFFOLD,
        domains=[Domain(helix_id="h0", start_bp=10, end_bp=90, direction=Direction.FORWARD)])

    stap_a = Strand(id="stap_a", strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=20, end_bp=29, direction=Direction.FORWARD,
                   overhang_id="ovhg_inline_stap_a_5p"),
            Domain(helix_id="h0", start_bp=30, end_bp=40, direction=Direction.FORWARD),
        ])
    stap_b = Strand(id="stap_b", strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="h0", start_bp=80, end_bp=70, direction=Direction.REVERSE,
                        overhang_id="ovhg_inline_stap_b_3p")])
    ov_a = OverhangSpec(id="ovhg_inline_stap_a_5p", helix_id="h0", strand_id="stap_a", label="OH1")
    ov_b = OverhangSpec(id="ovhg_inline_stap_b_3p", helix_id="h0", strand_id="stap_b", label="OH2")
    linker = OverhangConnection(id="L1", name="L1",
        overhang_a_id="ovhg_inline_stap_a_5p", overhang_a_attach="free_end",
        overhang_b_id="ovhg_inline_stap_b_3p", overhang_b_attach="free_end",
        linker_type="ds", length_value=10.0, length_unit="bp")

    d = Design(id="d", helices=[helix], strands=[scaf, stap_a, stap_b],
        overhangs=[ov_a, ov_b], overhang_connections=[linker],
        lattice_type=LatticeType.HONEYCOMB, metadata=DesignMetadata(name="t"))

    out = migrate_split_staple_domains(d)
    a = next(s for s in out.strands if s.id == "stap_a")
    assert len(a.domains) == 2
    assert a.domains[0].overhang_id == "ovhg_inline_stap_a_5p"
    assert any(o.id == "ovhg_inline_stap_a_5p" for o in out.overhangs)


# ── Persistence ───────────────────────────────────────────────────────────────


def _seed_with_two_clusters_and_one_joint() -> Design:
    """Two real overhang helices, each in its own helix-level cluster, with
    a single revolute joint on cluster A. The 1-DOF case for relax-linker."""
    from backend.core.models import ClusterJoint, ClusterRigidTransform
    base = _seed_with_real_oh_domains()
    cluster_a = ClusterRigidTransform(
        id="cluster_a", name="A",
        helix_ids=["oh_helix_a"],
        translation=[0.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
        pivot=[0.0, 0.0, 0.0],
    )
    cluster_b = ClusterRigidTransform(
        id="cluster_b", name="B",
        helix_ids=["oh_helix_b"],
        translation=[0.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
        pivot=[0.0, 0.0, 0.0],
    )
    # Joint axis runs along +Y, anchored at cluster A's overhang base. Rotating
    # cluster A around it sweeps oh_helix_a's tip along a circle in the X–Z
    # plane, so the chord between anchors A and B can be tuned.
    joint = ClusterJoint(
        id="joint_a",
        cluster_id="cluster_a",
        name="Hinge",
        local_axis_origin=[2.5, 0.0, 0.0],
        local_axis_direction=[0.0, 1.0, 0.0],
    )
    return base.model_copy(update={
        "cluster_transforms": [cluster_a, cluster_b],
        "cluster_joints": [joint],
    })


def test_relax_dof_topology_classifies_correctly():
    """0/1/2 DOF + shared cluster + ssDNA cases each return the expected status."""
    from backend.core.linker_relax import dof_topology
    from backend.core.models import ClusterJoint, ClusterRigidTransform

    base = _seed_with_real_oh_domains()
    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ds", length_value=8, length_unit="bp",
    )

    # No clusters → no_cluster
    topo = dof_topology(base, conn)
    assert topo["status"] == "no_cluster"
    assert topo["n_dof"] == 0

    # Two clusters but no joints → no_joints
    seeded = _seed_with_two_clusters_and_one_joint()
    no_joints = seeded.model_copy(update={"cluster_joints": []})
    topo = dof_topology(no_joints, conn)
    assert topo["status"] == "no_joints"
    assert topo["n_dof"] == 0

    # Both overhangs on the same cluster → shared_cluster
    same_cluster = base.model_copy(update={
        "cluster_transforms": [
            ClusterRigidTransform(
                id="cluster_shared", name="Shared",
                helix_ids=["oh_helix_a", "oh_helix_b"],
                translation=[0.0, 0.0, 0.0],
                rotation=[0.0, 0.0, 0.0, 1.0],
                pivot=[0.0, 0.0, 0.0],
            ),
        ],
    })
    topo = dof_topology(same_cluster, conn)
    assert topo["status"] == "shared_cluster"

    # 1 DOF — exactly one joint
    topo = dof_topology(seeded, conn)
    assert topo["status"] == "ok"
    assert topo["n_dof"] == 1

    # 2 DOF — joint on each cluster
    multi = seeded.model_copy(update={
        "cluster_joints": [
            *seeded.cluster_joints,
            ClusterJoint(id="joint_b", cluster_id="cluster_b", local_axis_origin=[5.0, 0.0, 0.0], local_axis_direction=[0.0, 1.0, 0.0]),
        ],
    })
    topo = dof_topology(multi, conn)
    assert topo["status"] == "multi_dof"
    assert topo["n_dof"] == 2


def test_relax_endpoint_rejects_ssdna():
    """ssDNA relax is deferred to a future physics-based pass; the endpoint
    should refuse it with 400 rather than running the dsDNA optimizer."""
    seeded = _seed_with_two_clusters_and_one_joint()
    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ss", length_value=8, length_unit="bp",
    )
    design_state.set_design(seeded.model_copy(update={"overhang_connections": [conn]}))
    r = client.post(f"/api/design/overhang-connections/{conn.id}/relax")
    assert r.status_code == 400
    assert "dsDNA" in r.json()["detail"]


def test_relax_endpoint_rejects_zero_dof():
    """Without joints on either cluster the endpoint refuses (no axis to rotate)."""
    seeded = _seed_with_two_clusters_and_one_joint()
    no_joints = seeded.model_copy(update={"cluster_joints": []})
    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ds", length_value=8, length_unit="bp",
    )
    design_state.set_design(no_joints.model_copy(update={"overhang_connections": [conn]}))
    r = client.post(f"/api/design/overhang-connections/{conn.id}/relax")
    assert r.status_code == 400


def test_relax_endpoint_one_dof_brings_arc_chords_toward_target():
    """1-DOF case: the optimizer minimizes the sum of the two connector-arc
    chord residuals around _ARC_TARGET_NM (0.67 nm — the standard backbone-
    to-backbone distance). Doesn't require a perfect match (the joint axis
    may not be able to reach the target for arbitrary geometry), only that
    the post-residual is no worse than the pre-residual."""
    from backend.core.lattice import generate_linker_topology
    from backend.core.linker_relax import (
        _anchor_pos_and_normal, _arc_chord_lengths, _ARC_TARGET_NM, _linker_bp,
    )
    from backend.api.crud import _geometry_for_design

    seeded = _seed_with_two_clusters_and_one_joint()
    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ds", length_value=8, length_unit="bp",
    )
    seeded_with_conn = generate_linker_topology(
        seeded.model_copy(update={"overhang_connections": [conn]}),
        conn,
    )
    design_state.set_design(seeded_with_conn)

    # Pre-relax sum-of-squares arc residual.
    nucs = _geometry_for_design(seeded_with_conn)
    pa0, na0 = _anchor_pos_and_normal(nucs, conn, conn.overhang_a_id, True)
    pb0, _   = _anchor_pos_and_normal(nucs, conn, conn.overhang_b_id, False)
    base_count = _linker_bp(conn)
    from backend.core.linker_relax import _comp_first
    cfa = _comp_first(conn.overhang_a_id, conn.overhang_a_attach)
    cfb = _comp_first(conn.overhang_b_id, conn.overhang_b_attach)
    arc_a0, arc_b0 = _arc_chord_lengths(pa0, na0, pb0, base_count, cfa, cfb)
    pre_residual = (arc_a0 - _ARC_TARGET_NM) ** 2 + (arc_b0 - _ARC_TARGET_NM) ** 2

    r = client.post(f"/api/design/overhang-connections/{conn.id}/relax")
    assert r.status_code == 200, r.text
    body = r.json()
    info = body["relax_info"]
    assert info["joint_ids"] == ["joint_a"]
    assert len(info["thetas_rad"]) == 1
    assert info["target_arc_nm"] == pytest.approx(_ARC_TARGET_NM)
    post_residual = ((info["final_arc_a_nm"] - _ARC_TARGET_NM) ** 2
                     + (info["final_arc_b_nm"] - _ARC_TARGET_NM) ** 2)
    assert post_residual <= pre_residual + 1e-9, (
        f"Expected sum-of-squares arc residual to not increase: "
        f"pre={pre_residual:.4f}, post={post_residual:.4f}"
    )

    # Cluster A's transform should have changed (rotation no longer identity).
    updated = next(c for c in body["design"]["cluster_transforms"] if c["id"] == "cluster_a")
    assert updated["rotation"] != [0.0, 0.0, 0.0, 1.0]
    # Feature log gets a ClusterOpLogEntry tagged source='relax' so the panel
    # can render it as "(relax) move/rotate <cluster>".
    relax_entries = [e for e in body["design"]["feature_log"]
                     if e.get("feature_type") == "cluster_op"
                     and e.get("cluster_id") == "cluster_a"
                     and e.get("source") == "relax"]
    assert relax_entries, "expected a (relax)-tagged ClusterOpLogEntry"


def test_relax_respects_joint_angle_bounds():
    """The 1-DOF optimizer must clamp the chosen θ to the joint's mechanical
    range. We tighten min/max around 0° so the optimizer can only move the
    cluster a couple of degrees; the unconstrained optimum is well outside
    that window, so a buggy optimizer would land far from the bounds."""
    from backend.core.lattice import generate_linker_topology

    seeded = _seed_with_two_clusters_and_one_joint()
    # Restrict the joint to ±2°. The unconstrained relax for this geometry
    # picks |θ| of tens of degrees (verified by the unbounded test above),
    # so the bounds are genuinely active.
    bounded_joint = seeded.cluster_joints[0].model_copy(
        update={"min_angle_deg": -2.0, "max_angle_deg": 2.0},
    )
    seeded = seeded.model_copy(update={"cluster_joints": [bounded_joint]})
    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ds", length_value=8, length_unit="bp",
    )
    seeded_with_conn = generate_linker_topology(
        seeded.model_copy(update={"overhang_connections": [conn]}),
        conn,
    )
    design_state.set_design(seeded_with_conn)

    r = client.post(f"/api/design/overhang-connections/{conn.id}/relax")
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    theta_deg = math.degrees(info["thetas_rad"][0])
    # Tolerate the optimizer's xatol (~5e-6 rad ≈ 3e-4°) when checking the
    # bound — anything noticeably outside ±2° is a bug.
    assert -2.0 - 1e-3 <= theta_deg <= 2.0 + 1e-3, (
        f"Optimizer returned θ={theta_deg:.4f}°, outside the joint's [-2°, +2°] window"
    )


def test_relax_status_endpoint_reflects_dof():
    """The lightweight /relax-status endpoint mirrors `dof_topology` so the
    frontend can render the menu entry enabled or grayed out without paying
    for an optimization."""
    seeded = _seed_with_two_clusters_and_one_joint()
    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ds", length_value=8, length_unit="bp",
    )
    design_state.set_design(seeded.model_copy(update={"overhang_connections": [conn]}))
    r = client.get(f"/api/design/overhang-connections/{conn.id}/relax-status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["n_dof"] == 1


def test_linker_complement_inherits_cluster_membership():
    """When a cluster contains an overhang's domain, generating the linker for
    that overhang must add the linker's complement domain to the same cluster
    so the linker stick rigidly follows the overhang under cluster transforms."""
    from backend.core.lattice import (
        _find_overhang_domain_ref,
        generate_linker_topology,
        remove_linker_topology,
    )
    from backend.core.models import ClusterRigidTransform, DomainRef

    base = _seed_with_real_oh_domains()
    a_ref = _find_overhang_domain_ref(base, "oh_a_5p")
    assert a_ref is not None
    cluster = ClusterRigidTransform(
        name="test",
        helix_ids=["oh_helix_a"],
        domain_ids=[DomainRef(strand_id=a_ref[0], domain_index=a_ref[1])],
        translation=[1.0, 0.0, 0.0],
    )
    seeded = base.model_copy(update={"cluster_transforms": [cluster]})

    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p",
        overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p",
        overhang_b_attach="root",
        linker_type="ds",
        length_value=8,
        length_unit="bp",
    )
    pre_reconcile = generate_linker_topology(
        seeded.model_copy(update={"overhang_connections": [conn]}),
        conn,
    )
    from backend.core.cluster_reconcile import MutationReport, reconcile_cluster_membership
    bridge_orphan_report = MutationReport(new_helix_origins={f"__lnk__{conn.id}": None})
    after = reconcile_cluster_membership(seeded, pre_reconcile, bridge_orphan_report)

    # Linker A's complement domain (the one on oh_helix_a) should now be in the cluster.
    keys = {(d.strand_id, d.domain_index) for d in after.cluster_transforms[0].domain_ids}
    assert (a_ref[0], a_ref[1]) in keys, "overhang's own domain should still be in the cluster"
    lnk_a_id = f"__lnk__{conn.id}__a"
    lnk_a_strand = next(s for s in after.strands if s.id == lnk_a_id)
    complement_idx = next(
        di for di, d in enumerate(lnk_a_strand.domains)
        if d.helix_id == "oh_helix_a"
    )
    assert (lnk_a_id, complement_idx) in keys

    # Linker B's overhang isn't in the cluster, so its complement shouldn't be either.
    lnk_b_id = f"__lnk__{conn.id}__b"
    assert not any(d.strand_id == lnk_b_id for d in after.cluster_transforms[0].domain_ids)

    # remove_linker_topology + reconciler drop the linker's DomainRefs from the
    # cluster (stale ref drop), leaving the overhang's own domain intact.
    pre_remove_reconcile = remove_linker_topology(after, conn.id)
    after_remove = reconcile_cluster_membership(after, pre_remove_reconcile)
    remaining = {(d.strand_id, d.domain_index) for d in after_remove.cluster_transforms[0].domain_ids}
    assert (a_ref[0], a_ref[1]) in remaining
    assert not any(sid.startswith("__lnk__") for (sid, _di) in remaining)


def test_round_trip_json_preserves_connections():
    design = assign_overhang_connection_names(
        _seed_with_two_overhangs().model_copy(update={
            "overhang_connections": [
                OverhangConnection(
                    overhang_a_id="ovhg_inline_a_5p",
                    overhang_a_attach="free_end",
                    overhang_b_id="ovhg_inline_a_3p",
                    overhang_b_attach="root",
                    linker_type="ds",
                    length_value=21,
                    length_unit="bp",
                ),
            ],
        })
    )
    text = design.to_json()
    parsed = Design.from_json(text)
    assert len(parsed.overhang_connections) == 1
    assert parsed.overhang_connections[0].name == "L1"
    assert parsed.overhang_connections[0].linker_type == "ds"


# ── Compatibility rules ───────────────────────────────────────────────────────


@pytest.fixture
def _seed_5p_pair():
    design_state.set_design(_seed_with_two_5p_overhangs())
    yield
    design_state.set_design(_demo_design())


def _post_5p(linker_type, attach_a, attach_b):
    return client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "ovhg_inline_a_5p",
        "overhang_a_attach": attach_a,
        "overhang_b_id": "ovhg_inline_b_5p",
        "overhang_b_attach": attach_b,
        "linker_type": linker_type,
        "length_value": 8,
        "length_unit": "bp",
    })


@pytest.mark.usefixtures("_seed_5p_pair")
class TestSameEndRules:
    """Same-end (5p+5p or 3p+3p) overhangs trigger compatibility constraints."""

    def test_ds_with_matching_attach_is_allowed(self):
        assert _post_5p("ds", "root", "root").status_code == 201

    def test_ds_with_matching_attach_free_end_is_allowed(self):
        assert _post_5p("ds", "free_end", "free_end").status_code == 201

    def test_ds_with_mismatched_attach_is_400(self):
        r = _post_5p("ds", "root", "free_end")
        assert r.status_code == 400
        assert "matching attach" in r.text and "antiparallel" in r.text

    def test_ss_with_mismatched_attach_is_allowed(self):
        assert _post_5p("ss", "root", "free_end").status_code == 201

    def test_ss_with_mismatched_attach_other_order_is_allowed(self):
        assert _post_5p("ss", "free_end", "root").status_code == 201

    def test_ss_with_matching_attach_is_400(self):
        r = _post_5p("ss", "root", "root")
        assert r.status_code == 400
        assert "OPPOSITE attach" in r.text


def _is_comp_first(end: str, attach: str) -> bool:
    """Mirror of backend `_comp_first_polarity` for tests."""
    return (end == "5p" and attach == "free_end") or (end == "3p" and attach == "root")


def test_polarity_rule_accepts_only_physical_combos():
    """Watson-Crick polarity test (unified across all 4 end-pair categories):

      - dsDNA accepted iff comp_first(A) == comp_first(B)
        → bridge halves on the virtual helix run antiparallel.
      - ssDNA accepted iff comp_first(A) != comp_first(B)
        → single bridge can be one continuous 5'→3' strand.

    Iterates every (end_a, attach_a) × (end_b, attach_b) × {ss, ds} = 32
    combinations. The synthetic seed exposes one OH per (end_type), so each
    attempt resets state to keep the per-end uniqueness rule from blocking.
    """
    cases = []
    ovhg_for = {"5p": "ovhg_inline_a_5p", "3p": "ovhg_inline_a_3p"}
    ovhg_for_b = {"5p": "ovhg_inline_b_5p", "3p": "ovhg_inline_b_3p"}
    for end_a in ("5p", "3p"):
        for attach_a in ("root", "free_end"):
            for end_b in ("5p", "3p"):
                for attach_b in ("root", "free_end"):
                    for linker_type in ("ss", "ds"):
                        cfa = _is_comp_first(end_a, attach_a)
                        cfb = _is_comp_first(end_b, attach_b)
                        expect_ok = (cfa == cfb) if linker_type == "ds" else (cfa != cfb)
                        cases.append((end_a, attach_a, end_b, attach_b, linker_type, expect_ok))

    for end_a, attach_a, end_b, attach_b, linker_type, expect_ok in cases:
        design_state.set_design(_seed_with_two_overhangs())
        r = client.post("/api/design/overhang-connections", json={
            "overhang_a_id":     ovhg_for[end_a],
            "overhang_a_attach": attach_a,
            "overhang_b_id":     ovhg_for_b[end_b],
            "overhang_b_attach": attach_b,
            "linker_type":       linker_type,
            "length_value":      5,
            "length_unit":       "bp",
        })
        actual_ok = r.status_code == 201
        tag = f"{linker_type}  {end_a}+{attach_a}  /  {end_b}+{attach_b}"
        assert actual_ok == expect_ok, (
            f"{tag}: expected {'accept' if expect_ok else 'reject'}, "
            f"got HTTP {r.status_code}: {r.text}"
        )


# ── PATCH (editable name + length) ────────────────────────────────────────────


def test_patch_renames_connection():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "MyLink"})
    assert r.status_code == 200
    assert r.json()["design"]["overhang_connections"][0]["name"] == "MyLink"


def test_patch_updates_length_and_unit():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}",
                     json={"length_value": 6.8, "length_unit": "nm"})
    assert r.status_code == 200
    conn = r.json()["design"]["overhang_connections"][0]
    assert conn["length_value"] == 6.8
    assert conn["length_unit"] == "nm"


def test_patch_only_name_does_not_touch_length():
    r = _post_conn(length_value=20, length_unit="bp")
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "Bridge"})
    conn = r.json()["design"]["overhang_connections"][0]
    assert conn["name"] == "Bridge"
    assert conn["length_value"] == 20
    assert conn["length_unit"] == "bp"


def test_patch_empty_name_is_400():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "  "})
    assert r.status_code == 400


def test_patch_duplicate_name_is_400():
    _post_conn()
    _post_conn_2()
    conns = client.get("/api/design").json()["design"]["overhang_connections"]
    l2 = next(c for c in conns if c["name"] == "L2")
    r = client.patch(f"/api/design/overhang-connections/{l2['id']}", json={"name": "L1"})
    assert r.status_code == 400


def test_patch_unknown_id_is_404():
    r = client.patch("/api/design/overhang-connections/nope", json={"name": "x"})
    assert r.status_code == 404


def test_patch_zero_length_is_400():
    r = _post_conn()
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"length_value": 0})
    assert r.status_code == 400


# ── Per-end uniqueness ───────────────────────────────────────────────────────


def test_reusing_overhang_end_is_400():
    """Each (overhang, attach) pair can only be in one connection."""
    _post_conn()  # uses (OH1, free_end) and (OH2, root)
    r = _post_conn(overhang_b_id="ovhg_inline_b_3p")  # would re-use (OH1, free_end)
    assert r.status_code == 400
    assert "already linked" in r.text


def test_reusing_root_end_is_400():
    _post_conn()  # uses (OH2, root)
    r = _post_conn(overhang_a_id="ovhg_inline_b_5p", overhang_b_id="ovhg_inline_a_3p")
    # would re-use (OH2, root)
    assert r.status_code == 400


def test_two_connections_per_overhang_when_other_end_is_free():
    """OH can appear in two connections if it uses both root and free_end."""
    _post_conn()  # (OH1 free_end) + (OH2 root)
    # Second connection uses OH1's root end + a fresh OH3.
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "ovhg_inline_a_5p", "overhang_a_attach": "root",
        "overhang_b_id": "ovhg_inline_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ss", "length_value": 5, "length_unit": "bp",
    })
    assert r.status_code == 201, r.text


# ── Linker topology generation ────────────────────────────────────────────────


def _linker_strands_for(design_dict, conn_id):
    prefix = f"__lnk__{conn_id}"
    return [s for s in design_dict["strands"] if s["id"].startswith(prefix)]


def _linker_helices_for(design_dict, conn_id):
    prefix = f"__lnk__{conn_id}"
    return [h for h in design_dict["helices"] if h["id"].startswith(prefix)]


def test_ss_linker_creates_two_complement_strands_no_bridge_helix():
    """ss linker against a real-OH-domain seed: 2 complement strands, NO virtual
    bridge helix (the bridge is the frontend arc only).
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "root",
        "linker_type": "ss", "length_value": 12, "length_unit": "bp",
    })
    assert r.status_code == 201, r.text
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    strands = _linker_strands_for(design, cid)
    helices = _linker_helices_for(design, cid)
    assert len(strands) == 2, "ss linker should create one complement strand per overhang"
    assert len(helices) == 0, "ss linker should not create a virtual bridge helix"
    # Each complement strand has exactly 1 domain — the complement on a real OH helix.
    for s in strands:
        assert s["strand_type"] == "linker"
        assert s["color"] == "#ffffff"
        assert len(s["domains"]) == 1
        assert not s["domains"][0]["helix_id"].startswith("__lnk__"), \
            f"ss linker complement domain should be on a real helix, got {s['domains'][0]['helix_id']}"


def test_ss_linker_no_strands_when_overhangs_lack_domains():
    """Synthetic seed (no real OH domains): ss linker has nothing to anchor —
    no strands, no virtual helix. Connection metadata is still recorded.
    """
    r = _post_conn(linker_type="ss", length_value=10)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    assert len(_linker_strands_for(design, cid)) == 0
    assert len(_linker_helices_for(design, cid)) == 0


def test_ds_linker_creates_two_strands_one_bridge_helix():
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=8)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    # 2 strands (one per overhang side); 1 virtual bridge helix shared between them.
    assert len(_linker_strands_for(design, cid)) == 2
    assert len(_linker_helices_for(design, cid)) == 1
    types = sorted(s["strand_type"] for s in _linker_strands_for(design, cid))
    assert types == ["linker", "linker"]


def test_ds_linker_bridge_helix_has_separated_cadnano_cell():
    """The ds bridge is a real virtual helix for pathview, but it should not be
    adjacent to the bundle lattice cells; otherwise cadnano suggests it is a
    neighboring origami helix.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    })
    assert r.status_code == 201, r.text
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    bridge = _linker_helices_for(design, cid)[0]
    assert bridge["grid_pos"] is not None

    br, bc = bridge["grid_pos"]
    real_cells = [
        tuple(h["grid_pos"])
        for h in design["helices"]
        if h.get("grid_pos") is not None and not h["id"].startswith("__lnk__")
    ]
    assert real_cells
    assert all(max(abs(br - r), abs(bc - c)) >= 2 for r, c in real_cells)


def test_ds_linker_complement_domains_on_real_oh_helices():
    """The two ds-linker strands each carry a complement domain on the same
    real helix as the overhang they pair with, with antiparallel direction.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    })
    assert r.status_code == 201, r.text
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]

    strand_a = next(s for s in design["strands"] if s["id"] == f"__lnk__{cid}__a")
    strand_b = next(s for s in design["strands"] if s["id"] == f"__lnk__{cid}__b")

    # 2 domains each: complement (real OH helix) + bridge (virtual __lnk__ helix).
    assert len(strand_a["domains"]) == 2
    assert len(strand_b["domains"]) == 2

    # Complement A on oh_helix_a, opposite direction to OH-A (FORWARD → REVERSE),
    # same bp range, swapped start/end (start=oh.end_bp, end=oh.start_bp).
    comp_a, bridge_a = strand_a["domains"]
    assert comp_a["helix_id"]  == "oh_helix_a"
    assert comp_a["direction"] == "REVERSE"
    assert comp_a["start_bp"]  == 7
    assert comp_a["end_bp"]    == 0
    assert bridge_a["helix_id"] == f"__lnk__{cid}"
    assert bridge_a["direction"] == "FORWARD"

    # Complement B on oh_helix_b, opposite to OH-B (REVERSE → FORWARD).
    comp_b, bridge_b = strand_b["domains"]
    assert comp_b["helix_id"]  == "oh_helix_b"
    assert comp_b["direction"] == "FORWARD"
    assert comp_b["start_bp"]  == 7
    assert comp_b["end_bp"]    == 0
    assert bridge_b["helix_id"] == f"__lnk__{cid}"
    assert bridge_b["direction"] == "REVERSE"


def test_ds_linker_complement_renders_via_geometry_pipeline():
    """The complement nucleotides must appear in /design/geometry tagged with
    the linker strand id and color so the frontend can render them.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    })
    cid = r.json()["design"]["overhang_connections"][0]["id"]

    geom = client.get("/api/design/geometry").json()
    nucs = geom["nucleotides"]

    # Strand A's complement nucs: helix=oh_helix_a, REVERSE, bp 0..7. The
    # strand also has bridge nucs on the virtual __lnk__ helix now (real
    # geometry payload entries), so filter by helix to scope to the
    # complement domain only.
    a_comp = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__a"
              and not n["helix_id"].startswith("__lnk__")]
    assert len(a_comp) == 8, f"expected 8 complement nucs for strand A, got {len(a_comp)}"
    assert all(n["strand_type"] == "linker" for n in a_comp)
    assert all(n["direction"] == "REVERSE" for n in a_comp)
    assert {n["bp_index"] for n in a_comp} == set(range(8))

    b_comp = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__b"
              and not n["helix_id"].startswith("__lnk__")]
    assert len(b_comp) == 8
    assert all(n["direction"] == "FORWARD" for n in b_comp)

    # And the bridge domain now produces real geometry too — should be 6 bp
    # per side, on the virtual __lnk__ helix.
    a_bridge = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__a"
                and n["helix_id"].startswith("__lnk__")]
    b_bridge = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__b"
                and n["helix_id"].startswith("__lnk__")]
    assert len(a_bridge) == 6, f"expected 6 bridge nucs for strand A, got {len(a_bridge)}"
    assert len(b_bridge) == 6, f"expected 6 bridge nucs for strand B, got {len(b_bridge)}"


def test_ss_linker_complement_renders_via_geometry_pipeline():
    """ss linker (like ds) emits complement nucleotides on each real OH helix,
    tagged strand_type='linker' so the frontend renders them.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "root",
        "linker_type": "ss", "length_value": 10, "length_unit": "bp",
    })
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    geom = client.get("/api/design/geometry").json()
    nucs = geom["nucleotides"]
    a_nucs = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__a"]
    b_nucs = [n for n in nucs if n.get("strand_id") == f"__lnk__{cid}__b"]
    assert len(a_nucs) == 8
    assert len(b_nucs) == 8
    assert all(n["strand_type"] == "linker" for n in a_nucs + b_nucs)
    assert all(n["helix_id"] in ("oh_helix_a", "oh_helix_b") for n in a_nucs + b_nucs)


def test_dedicated_overhang_phase_shared_by_cg_and_atomistic():
    """Dedicated overhang helices carry custom phase even when they have a
    cadnano grid_pos. CG and atomistic must both use that stored pose instead
    of independently re-normalizing from the lattice cell.
    """
    design = _seed_with_real_oh_domains()
    helix = next(h for h in design.helices if h.id == "oh_helix_a")
    effective = effective_helix_for_geometry(helix, design)
    assert effective.phase_offset == helix.phase_offset

    normalized = _normalize_helix_for_grid(helix, design.lattice_type)
    assert not math.isclose(normalized.phase_offset, helix.phase_offset)

    stored_nuc = next(
        n for n in nucleotide_positions(helix)
        if n.bp_index == 0 and n.direction == Direction.FORWARD
    )
    arrs = deformed_nucleotide_arrays(helix, design)
    idx = next(
        i for i, (bp, d) in enumerate(zip(arrs["bp_indices"], arrs["directions"]))
        if int(bp) == 0 and int(d) == 0
    )
    assert np.linalg.norm(arrs["positions"][idx] - stored_nuc.position) < 1e-9

    model = build_atomistic_model(design)
    p_atom = next(
        a for a in model.atoms
        if a.name == "P"
        and a.strand_id == "oh_strand_a"
        and a.helix_id == "oh_helix_a"
        and a.bp_index == 0
        and a.direction == "FORWARD"
    )
    axis_start = helix.axis_start.to_array()
    axis_end = helix.axis_end.to_array()
    axis_hat = (axis_end - axis_start) / np.linalg.norm(axis_end - axis_start)
    axis_pt = axis_start + (stored_nuc.bp_index - helix.bp_start) * BDNA_RISE_PER_BP * axis_hat
    origin, R = _atom_frame(stored_nuc, Direction.FORWARD, axis_point=axis_pt, helix_direction=helix.direction)
    _, _, n, y, z = _SUGAR[0]
    expected_p = origin + R @ np.array([n, y, z])
    actual_p = np.array([p_atom.x, p_atom.y, p_atom.z])
    assert np.linalg.norm(actual_p - expected_p) < 1e-9


def test_ss_linker_complement_renders_in_atomistic_model():
    """Atomistic generation must include both real-helix complement domains for
    ss linkers. One side uses the linker's swapped endpoint convention, which
    previously produced an empty atomistic range.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "root",
        "linker_type": "ss", "length_value": 10, "length_unit": "bp",
    })
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    atoms = client.get("/api/design/atomistic").json()["atoms"]
    pairs = {
        (a["strand_id"], a["helix_id"])
        for a in atoms
        if a["strand_id"].startswith(f"__lnk__{cid}")
    }
    assert (f"__lnk__{cid}__a", "oh_helix_a") in pairs
    assert (f"__lnk__{cid}__b", "oh_helix_b") in pairs
    assert all(not helix_id.startswith(f"__lnk__{cid}") for _, helix_id in pairs)


def test_ds_linker_bridge_and_complements_render_in_atomistic_model():
    """ds linkers should atomistically include the overhang complement domains
    plus both strands on the virtual duplex bridge helix.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    })
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    bridge_id = f"__lnk__{cid}"
    bridge = _linker_helices_for(r.json()["design"], cid)[0]
    axis_mid = [
        (bridge["axis_start"][k] + bridge["axis_end"][k]) * 0.5
        for k in ("x", "y", "z")
    ]
    assert math.dist(axis_mid, [0.0, 0.0, 0.0]) > 1.0

    atoms = client.get("/api/design/atomistic").json()["atoms"]
    pairs = {
        (a["strand_id"], a["helix_id"])
        for a in atoms
        if a["strand_id"].startswith(bridge_id)
    }
    assert (f"{bridge_id}__a", "oh_helix_a") in pairs
    assert (f"{bridge_id}__b", "oh_helix_b") in pairs
    assert (f"{bridge_id}__a", bridge_id) in pairs
    assert (f"{bridge_id}__b", bridge_id) in pairs

    bridge_atoms = [a for a in atoms if a["helix_id"] == bridge_id]
    atom_mid = [
        sum(a[k] for a in bridge_atoms) / len(bridge_atoms)
        for k in ("x", "y", "z")
    ]
    assert math.dist(atom_mid, [0.0, 0.0, 0.0]) > 1.0
    assert math.dist(atom_mid, axis_mid) < 1.0


def test_atomistic_repositions_legacy_origin_ds_linker_helix():
    """Reloaded designs may have ds linker bridge helices saved with the old
    origin-placeholder axis. Atomistic generation should pose them at the same
    midpoint bridge without requiring a manual length patch/rebuild.
    """
    design_state.set_design(_seed_with_real_oh_domains())
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a_5p", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b_5p", "overhang_b_attach": "free_end",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp",
    })
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    bridge_id = f"__lnk__{cid}"

    design = design_state.get_or_404()
    legacy_helices = [
        h.model_copy(update={
            "axis_start": Vec3(x=0.0, y=0.0, z=0.0),
            "axis_end": Vec3(x=0.0, y=0.0, z=6 * BDNA_RISE_PER_BP),
            "phase_offset": 0.0,
        }) if h.id == bridge_id else h
        for h in design.helices
    ]
    design_state.set_design(design.model_copy(update={"helices": legacy_helices}))

    atoms = client.get("/api/design/atomistic").json()["atoms"]
    bridge_atoms = [a for a in atoms if a["helix_id"] == bridge_id]
    atom_mid = [
        sum(a[k] for a in bridge_atoms) / len(bridge_atoms)
        for k in ("x", "y", "z")
    ]
    assert math.dist(atom_mid, [0.0, 0.0, 0.0]) > 1.0


def test_nm_unit_converts_to_bp():
    """4 nm ≈ 12 bp at 0.334 nm/bp. Tested on the ds bridge (only ds creates a
    virtual helix whose length we can read back)."""
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=4.0, length_unit="nm")
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    helices = _linker_helices_for(design, cid)
    assert len(helices) == 1
    assert helices[0]["length_bp"] == 12   # round(4.0 / 0.334) == 12


def test_delete_cleans_up_linker_topology():
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=8)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    assert _linker_strands_for(design, cid)   # sanity

    r = client.delete(f"/api/design/overhang-connections/{cid}")
    design = r.json()["design"]
    assert _linker_strands_for(design, cid) == []
    assert _linker_helices_for(design, cid) == []


def test_delete_linker_strand_deletes_entire_linker():
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=8)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    strand_id = _linker_strands_for(design, cid)[0]["id"]

    r = client.delete(f"/api/design/strands/{strand_id}")
    assert r.status_code == 200, r.text
    design = r.json()["design"]
    assert [c for c in design["overhang_connections"] if c["id"] == cid] == []
    assert _linker_strands_for(design, cid) == []
    assert _linker_helices_for(design, cid) == []


def test_delete_linker_domain_deletes_entire_linker():
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=8)
    design = r.json()["design"]
    cid = design["overhang_connections"][0]["id"]
    strand_id = _linker_strands_for(design, cid)[0]["id"]

    r = client.delete(f"/api/design/strands/{strand_id}/domains/0")
    assert r.status_code == 200, r.text
    design = r.json()["design"]
    assert [c for c in design["overhang_connections"] if c["id"] == cid] == []
    assert _linker_strands_for(design, cid) == []
    assert _linker_helices_for(design, cid) == []


def test_patch_length_rebuilds_linker():
    """ds linker: PATCHing length must rebuild the bridge helix to the new bp."""
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=5)
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    r = client.patch(f"/api/design/overhang-connections/{cid}",
                     json={"length_value": 25})
    design = r.json()["design"]
    helices = _linker_helices_for(design, cid)
    assert len(helices) == 1
    assert helices[0]["length_bp"] == 25
    # Still 2 ds linker strands (one per overhang side).
    assert len(_linker_strands_for(design, cid)) == 2


def test_patch_name_only_does_not_rebuild():
    """ds linker: renaming must NOT touch the bridge helix."""
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=5)
    cid = r.json()["design"]["overhang_connections"][0]["id"]
    helix_id_before = _linker_helices_for(r.json()["design"], cid)[0]["id"]

    r = client.patch(f"/api/design/overhang-connections/{cid}", json={"name": "MyLink"})
    design = r.json()["design"]
    helices = _linker_helices_for(design, cid)
    # Helix wasn't rebuilt — same id, same length.
    assert len(helices) == 1
    assert helices[0]["id"] == helix_id_before


def test_linker_strands_excluded_from_validator():
    """Adding a linker shouldn't trip the 'unknown helix reference' validator."""
    r = _post_conn(linker_type="ds", overhang_b_attach="root", length_value=8)
    assert r.status_code == 201
    validation = r.json()["validation"]
    # No bad-reference error — virtual __lnk__ helices are skipped by validator.
    failures = [v for v in validation["results"] if not v["ok"]]
    bad_ref_failures = [v for v in failures if "unknown helix" in v["message"]]
    assert bad_ref_failures == []


# ── Misc ──────────────────────────────────────────────────────────────────────


def test_assign_names_preserves_existing_and_picks_lowest_unused():
    """An incoming connection without a name is given L1 even if other Ln exist."""
    design = _seed_with_two_overhangs().model_copy(update={
        "overhang_connections": [
            OverhangConnection(
                name="L3",
                overhang_a_id="ovhg_inline_a_5p",
                overhang_a_attach="root",
                overhang_b_id="ovhg_inline_a_3p",
                overhang_b_attach="root",
                linker_type="ss",
                length_value=5,
                length_unit="bp",
            ),
            OverhangConnection(
                overhang_a_id="ovhg_inline_a_5p",
                overhang_a_attach="free_end",
                overhang_b_id="ovhg_inline_a_3p",
                overhang_b_attach="free_end",
                linker_type="ds",
                length_value=10,
                length_unit="bp",
            ),
        ],
    })
    out = assign_overhang_connection_names(design)
    assert out.overhang_connections[0].name == "L3"
    assert out.overhang_connections[1].name == "L1"


# ── /design/refresh-bridges (Plan B companion) ────────────────────────────────


def _seed_ds_linker_design():
    """Build a design with one ds linker between two real OH helices, two
    clusters (one per OH), and one joint. Mirrors the relax-test fixture but
    runs `generate_linker_topology` so the bridge strands and `__lnk__<conn>`
    helix are present — required for `_emit_bridge_nucs` to do anything."""
    from backend.core.lattice import generate_linker_topology

    seeded = _seed_with_two_clusters_and_one_joint()
    conn = OverhangConnection(
        name="L1",
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ds", length_value=8, length_unit="bp",
    )
    return generate_linker_topology(
        seeded.model_copy(update={"overhang_connections": [conn]}),
        conn,
    )


def test_refresh_bridges_returns_only_bridge_nucs():
    """Endpoint must return only nucs on `__lnk__*` helices, not the OH
    nucs that were computed as a dependency."""
    design_state.set_design(_seed_ds_linker_design())
    r = client.post("/api/design/refresh-bridges", json={"cluster_ids": []})
    assert r.status_code == 200, r.text
    bridge_nucs = r.json()["bridge_nucs"]
    assert bridge_nucs, "expected at least one bridge nuc for the ds linker"
    for n in bridge_nucs:
        assert n["helix_id"].startswith("__lnk__")
        # Every bridge nuc carries a usable backbone position for the renderer.
        assert isinstance(n["backbone_position"], list) and len(n["backbone_position"]) == 3


def test_refresh_bridges_filters_by_cluster_id():
    """Passing only an unrelated cluster ID must yield zero bridge nucs;
    passing a cluster whose helices include an OH anchor must yield the
    same set as the no-filter call."""
    design_state.set_design(_seed_ds_linker_design())

    full = client.post("/api/design/refresh-bridges", json={"cluster_ids": []}).json()["bridge_nucs"]
    assert full, "fixture sanity: ds linker should produce bridges"

    # Clusters in the fixture are 'cluster_a' (contains oh_helix_a) and
    # 'cluster_b' (contains oh_helix_b). Either should be enough to mark the
    # connection as affected.
    only_a = client.post("/api/design/refresh-bridges", json={"cluster_ids": ["cluster_a"]}).json()["bridge_nucs"]
    assert len(only_a) == len(full)

    nonexistent = client.post("/api/design/refresh-bridges", json={"cluster_ids": ["does_not_exist"]}).json()["bridge_nucs"]
    assert nonexistent == []


def test_refresh_bridges_reflects_cluster_transform():
    """After translating cluster A, the recomputed bridge nuc positions must
    differ from the pre-translation positions — the bridge midpoint must
    follow the live anchors."""
    design = _seed_ds_linker_design()
    design_state.set_design(design)

    pre = client.post("/api/design/refresh-bridges", json={"cluster_ids": []}).json()["bridge_nucs"]
    assert pre, "fixture sanity: ds linker should produce bridges"
    pre_by_key = {(n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
                  for n in pre}

    # Translate cluster A by a non-trivial offset.
    moved = design.model_copy(update={
        "cluster_transforms": [
            (ct.model_copy(update={"translation": [3.0, 4.0, 0.0]})
             if ct.id == "cluster_a" else ct)
            for ct in design.cluster_transforms
        ],
    })
    design_state.set_design(moved)

    post = client.post("/api/design/refresh-bridges", json={"cluster_ids": ["cluster_a"]}).json()["bridge_nucs"]
    assert post and len(post) == len(pre)

    moved_keys = []
    for n in post:
        key = (n["helix_id"], n["bp_index"], n["direction"])
        before = pre_by_key.get(key)
        if before is None:
            continue
        after = n["backbone_position"]
        if any(abs(a - b) > 1e-6 for a, b in zip(after, before)):
            moved_keys.append(key)
    assert moved_keys, (
        "Expected at least one bridge nuc to change position after the "
        "cluster A translation; none did."
    )


def test_refresh_bridges_no_ds_linkers_returns_empty():
    """Sanity: a design without ds linkers responds quickly with an empty list."""
    design_state.set_design(_demo_design())   # demo has no overhang_connections
    r = client.post("/api/design/refresh-bridges", json={"cluster_ids": []})
    assert r.status_code == 200
    assert r.json()["bridge_nucs"] == []
