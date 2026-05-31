"""Tests for flexible ssDNA segments (pose & explore mechanisms).

Rigid arms are the user's EXISTING clusters. Marking an unpaired run flexible
derives a fixed-contour connection between the two clusters it bridges; the gate
says whether a cluster can use real-time "ssDNA constrained" drag. Display-layer
only — marking never mutates topology or cluster_transforms.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP, SSDNA_RISE_PER_BASE_NM
from backend.core.flexible_segments import (
    all_cluster_gates,
    apply_marks,
    cluster_flexible_gate,
    derive_flexible_connections,
    unpaired_bead_keys,
)
from backend.core.models import (
    ClusterRigidTransform, Design, Direction, Domain, FlexibleSegmentMark,
    Helix, Strand, StrandType, Vec3,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


# ── Fixture: two clusters (arms) joined by one 6-base ssDNA scaffold run ─────
_L = 12
_SS_A = (9, 11)   # h_a ssDNA bp range (scaffold)
_SS_B = (0, 2)    # h_b ssDNA bp range (scaffold)


def _hinge_design() -> Design:
    base = _demo_design()
    h_a = Helix(id="h_a", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
                axis_end=Vec3(x=0.0, y=0.0, z=_L * BDNA_RISE_PER_BP),
                phase_offset=0.0, length_bp=_L, grid_pos=(0, 0))
    h_b = Helix(id="h_b", axis_start=Vec3(x=2.5, y=0.0, z=0.0),
                axis_end=Vec3(x=2.5, y=0.0, z=_L * BDNA_RISE_PER_BP),
                phase_offset=0.0, length_bp=_L, grid_pos=(0, 1))
    scaffold = Strand(
        id="scaf", strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h_a", start_bp=0, end_bp=8, direction=Direction.FORWARD),
            Domain(helix_id="h_a", start_bp=_SS_A[0], end_bp=_SS_A[1],
                   direction=Direction.FORWARD, overhang_id="ss_a"),
            Domain(helix_id="h_b", start_bp=_SS_B[0], end_bp=_SS_B[1],
                   direction=Direction.FORWARD, overhang_id="ss_b"),
            Domain(helix_id="h_b", start_bp=3, end_bp=11, direction=Direction.FORWARD),
        ],
    )
    staple_a = Strand(id="stap_a", strand_type=StrandType.STAPLE,
                      domains=[Domain(helix_id="h_a", start_bp=0, end_bp=8,
                                      direction=Direction.REVERSE)])
    staple_b = Strand(id="stap_b", strand_type=StrandType.STAPLE,
                      domains=[Domain(helix_id="h_b", start_bp=3, end_bp=11,
                                      direction=Direction.REVERSE)])
    cluster_a = ClusterRigidTransform(id="cl_a", name="Arm A", helix_ids=["h_a"])
    cluster_b = ClusterRigidTransform(id="cl_b", name="Arm B", helix_ids=["h_b"])
    return base.model_copy(update={
        "helices": [h_a, h_b],
        "strands": [scaffold, staple_a, staple_b],
        "cluster_transforms": [cluster_a, cluster_b],
        "crossovers": [],
        "forced_ligations": [],
    })


def _mark_run(design: Design) -> Design:
    marks = [
        FlexibleSegmentMark(strand_id="scaf", domain_index=1, bp_index=bp, direction=Direction.FORWARD)
        for bp in range(_SS_A[0], _SS_A[1] + 1)
    ] + [
        FlexibleSegmentMark(strand_id="scaf", domain_index=2, bp_index=bp, direction=Direction.FORWARD)
        for bp in range(_SS_B[0], _SS_B[1] + 1)
    ]
    return design.copy_with(flexible_segment_marks=marks)


# ── Derivation ───────────────────────────────────────────────────────────────

def test_no_marks_no_connections():
    assert derive_flexible_connections(_hinge_design()) == []


def test_run_connects_the_two_existing_clusters():
    conns = derive_flexible_connections(_mark_run(_hinge_design()))
    assert len(conns) == 1
    c = conns[0]
    assert {c.cluster_a_id, c.cluster_b_id} == {"cl_a", "cl_b"}
    assert c.n_ss_bases == 6
    assert c.contour_length_nm == pytest.approx(6 * SSDNA_RISE_PER_BASE_NM)
    assert len(c.segment_bead_keys) == 6


def test_no_new_clusters_created():
    out = apply_marks(_mark_run(_hinge_design()))
    assert [c.id for c in out.cluster_transforms] == ["cl_a", "cl_b"]


# ── Gate ─────────────────────────────────────────────────────────────────────

def test_gate_true_when_run_marked():
    d = _mark_run(_hinge_design())
    g = cluster_flexible_gate(d, "cl_a")
    assert g["gate"] is True
    assert g["n_crossings"] >= 1
    assert g["rigid_blocking"] == []


def test_gate_false_when_unmarked_rigid_crossing():
    # No marks → the scaffold backbone crossing cl_a↔cl_b is a rigid bond.
    g = cluster_flexible_gate(_hinge_design(), "cl_a")
    assert g["gate"] is False
    assert len(g["rigid_blocking"]) >= 1


# ── Three-layer guard ──────────────────────────────────────────────────────────

def test_apply_marks_only_touches_connections():
    d = _mark_run(_hinge_design())
    before = {f: d.model_dump()[f] for f in
              ("strands", "helices", "crossovers", "forced_ligations",
               "cluster_transforms", "flexible_segment_marks")}
    out = apply_marks(d)
    after = out.model_dump()
    for f, val in before.items():
        assert after[f] == val, f"{f} changed during apply_marks"
    assert len(out.flexible_connections) == 1


# ── Persistence ──────────────────────────────────────────────────────────────

def test_roundtrip_marks_and_connections():
    d = apply_marks(_mark_run(_hinge_design()))
    again = Design.model_validate_json(d.model_dump_json())
    assert len(again.flexible_segment_marks) == 6
    assert len(again.flexible_connections) == 1


def test_axis_segments_skip_flexible_bps():
    """The helix axis stick is not drawn over a flexible ssDNA run."""
    from backend.core.deformation import _segments_for_helix
    d = _hinge_design()
    h_a = next(h for h in d.helices if h.id == "h_a")
    before = _segments_for_helix(d, h_a)
    assert any(s["bp_lo"] <= 9 <= s["bp_hi"] for s in before)  # bp9-11 covered pre-mark
    d2 = _mark_run(d)
    after = _segments_for_helix(d2, h_a)
    covered = {bp for s in after for bp in range(s["bp_lo"], s["bp_hi"] + 1)}
    assert covered.isdisjoint({9, 10, 11})          # flexible bps have no axis stick
    assert {0, 1, 2, 3, 4, 5, 6, 7, 8} <= covered    # rigid bps still do


def test_marks_change_forces_full_geometry():
    """A marks-only diff must NOT take the positions_only fast path (which omits
    per-bead is_flexible_segment) — else undo leaves the segment invisible."""
    from backend.api.crud import _topology_diff_field
    d0 = _hinge_design()
    d1 = apply_marks(_mark_run(d0))
    assert _topology_diff_field(d0, d1) == "flexible_segment_marks"
    assert _topology_diff_field(d1, d0) == "flexible_segment_marks"
    assert _topology_diff_field(d0, d0) is None


def test_undo_mark_restores_rigid_beads():
    design_state.set_design(_hinge_design())
    r = client.post("/api/design/flexible-segment", json={
        "strand_id": "scaf", "domain_index": 1, "bp_index": 9, "direction": "FORWARD"})
    assert r.status_code == 200, r.text
    assert any(n.get("is_flexible_segment") for n in (r.json().get("nucleotides") or []))
    u = client.post("/api/design/undo").json()
    # Full geometry (not positions_only/cluster_only) so is_flexible_segment is recomputed.
    assert u.get("diff_kind") not in ("positions_only", "cluster_only")
    nucs = u.get("nucleotides") or []
    assert nucs and not any(n.get("is_flexible_segment") for n in nucs)
    assert design_state.get_or_404().flexible_segment_marks == []


def test_old_file_without_fields_loads_empty():
    raw = _demo_design().model_dump()
    raw.pop("flexible_segment_marks", None)
    raw.pop("flexible_connections", None)
    d = Design.model_validate(raw)
    assert d.flexible_segment_marks == []
    assert d.flexible_connections == []


# ── API ──────────────────────────────────────────────────────────────────────

def test_api_mark_requires_unpaired():
    design_state.set_design(_hinge_design())
    # Paired scaffold bead (domain 0, h_a) → rejected.
    r = client.post("/api/design/flexible-segment", json={
        "strand_id": "scaf", "domain_index": 0, "bp_index": 0, "direction": "FORWARD"})
    assert r.status_code == 400, r.text
    assert "unpaired" in r.json()["detail"].lower()
    # Unpaired ssDNA bead (domain 1) → accepted; geometry carries is_flexible_segment.
    r = client.post("/api/design/flexible-segment", json={
        "strand_id": "scaf", "domain_index": 1, "bp_index": 9, "direction": "FORWARD"})
    assert r.status_code == 200, r.text
    nucs = r.json().get("nucleotides") or []
    assert any(n.get("is_flexible_segment") for n in nucs)


def test_api_mark_adds_feature_log_entry_and_reverts():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    r = client.post("/api/design/flexible-segment", json={
        "strand_id": "scaf", "domain_index": 1, "bp_index": 9, "direction": "FORWARD"})
    assert r.status_code == 200, r.text
    log = design_state.get_or_404().feature_log
    assert len(log) == n0 + 1
    entry = log[-1].model_dump()
    assert entry["feature_type"] == "snapshot"
    assert entry["op_kind"] == "flexible-segment-mark"
    assert design_state.get_or_404().flexible_segment_marks  # marked
    # Revert the feature-log entry → marks gone.
    rr = client.post(f"/api/design/features/{n0}/revert")
    assert rr.status_code == 200, rr.text
    assert design_state.get_or_404().flexible_segment_marks == []


def test_api_mark_feature_log_deletable():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    client.post("/api/design/flexible-segment", json={
        "strand_id": "scaf", "domain_index": 1, "bp_index": 9, "direction": "FORWARD"})
    assert design_state.get_or_404().flexible_segment_marks
    rd = client.delete(f"/api/design/features/{n0}")
    assert rd.status_code == 200, rd.text
    d = design_state.get_or_404()
    # Delete forgets the log row but keeps current state (app-wide convention —
    # like deleting an auto-break keeps the nicks). The row is gone.
    assert len(d.feature_log) == n0
    assert not any(e.feature_type == "snapshot" and e.op_kind.startswith("flexible-segment")
                   for e in d.feature_log)


def test_api_batch_then_connections_then_clear():
    design_state.set_design(_hinge_design())
    marks = [{"strand_id": "scaf", "domain_index": 1, "bp_index": bp, "direction": "FORWARD"}
             for bp in range(_SS_A[0], _SS_A[1] + 1)]
    marks += [{"strand_id": "scaf", "domain_index": 2, "bp_index": bp, "direction": "FORWARD"}
              for bp in range(_SS_B[0], _SS_B[1] + 1)]
    r = client.post("/api/design/flexible-segment/batch", json={"marks": marks, "replace": True})
    assert r.status_code == 200, r.text
    info = client.get("/api/design/flexible-connections").json()
    assert len(info["connections"]) == 1
    assert info["gates"]["cl_a"]["gate"] is True
    assert info["n_marks"] == 6
    # Clear all.
    r = client.post("/api/design/flexible-segment/batch", json={"replace": True})
    assert r.status_code == 200, r.text
    info = client.get("/api/design/flexible-connections").json()
    assert info["connections"] == []
    assert info["n_marks"] == 0


# ── Real design (the worked example) ───────────────────────────────────────────

_MINI = "workspace/mini_hinge.nadoc"


@pytest.mark.skipif(not os.path.exists(_MINI), reason="mini_hinge.nadoc not present")
def test_mini_hinge_four_connections_both_gates_open():
    d = Design.model_validate_json(open(_MINI).read())
    unp = unpaired_bead_keys(d)
    marks = [FlexibleSegmentMark(strand_id=s.id, domain_index=di, bp_index=bp, direction=dom.direction)
             for s in d.strands for di, dom in enumerate(s.domains)
             for bp in range(min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp) + 1)
             if (dom.helix_id, bp, dom.direction) in unp]
    d = apply_marks(d.copy_with(flexible_segment_marks=marks))
    cids = {c.id for c in d.cluster_transforms}
    assert len(d.flexible_connections) == 4
    for c in d.flexible_connections:
        assert {c.cluster_a_id, c.cluster_b_id} <= cids
        assert c.cluster_a_id != c.cluster_b_id  # all inter-cluster
    assert sorted(c.n_ss_bases for c in d.flexible_connections) == [2, 2, 16, 16]
    gates = all_cluster_gates(d)
    assert all(gates[cid]["gate"] for cid in cids)
