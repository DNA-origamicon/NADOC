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
    _gate,
    all_cluster_gates,
    apply_marks,
    cluster_flexible_gate,
    derive_flexible_connections,
    unpaired_bead_keys,
)
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Direction,
    Domain,
    FlexibleSegmentMark,
    Helix,
    Strand,
    StrandType,
    Vec3,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


# ── Fixture: two clusters (arms) joined by one 6-base ssDNA scaffold run ─────
_L = 12
_SS_A = (9, 11)  # h_a ssDNA bp range (scaffold)
_SS_B = (0, 2)  # h_b ssDNA bp range (scaffold)


def _hinge_design() -> Design:
    base = _demo_design()
    h_a = Helix(
        id="h_a",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=_L * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=_L,
        grid_pos=(0, 0),
    )
    h_b = Helix(
        id="h_b",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=_L * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=_L,
        grid_pos=(0, 1),
    )
    scaffold = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h_a", start_bp=0, end_bp=8, direction=Direction.FORWARD),
            Domain(
                helix_id="h_a",
                start_bp=_SS_A[0],
                end_bp=_SS_A[1],
                direction=Direction.FORWARD,
                overhang_id="ss_a",
            ),
            Domain(
                helix_id="h_b",
                start_bp=_SS_B[0],
                end_bp=_SS_B[1],
                direction=Direction.FORWARD,
                overhang_id="ss_b",
            ),
            Domain(helix_id="h_b", start_bp=3, end_bp=11, direction=Direction.FORWARD),
        ],
    )
    staple_a = Strand(
        id="stap_a",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h_a", start_bp=0, end_bp=8, direction=Direction.REVERSE)
        ],
    )
    staple_b = Strand(
        id="stap_b",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h_b", start_bp=3, end_bp=11, direction=Direction.REVERSE)
        ],
    )
    cluster_a = ClusterRigidTransform(id="cl_a", name="Arm A", helix_ids=["h_a"])
    cluster_b = ClusterRigidTransform(id="cl_b", name="Arm B", helix_ids=["h_b"])
    return base.model_copy(
        update={
            "helices": [h_a, h_b],
            "strands": [scaffold, staple_a, staple_b],
            "cluster_transforms": [cluster_a, cluster_b],
            "crossovers": [],
            "forced_ligations": [],
        }
    )


def _mark_run(design: Design) -> Design:
    marks = [
        FlexibleSegmentMark(
            strand_id="scaf", domain_index=1, bp_index=bp, direction=Direction.FORWARD
        )
        for bp in range(_SS_A[0], _SS_A[1] + 1)
    ] + [
        FlexibleSegmentMark(
            strand_id="scaf", domain_index=2, bp_index=bp, direction=Direction.FORWARD
        )
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


def test_gate_treats_duplex_child_cluster_as_transparent():
    """An overhang-duplex CHILD cluster is a movable connector, not a rigid pin — its
    junction crossing must NOT disable a parent cluster's 'ssDNA constrained' gate.
    (Regression: materializing a duplex into its own cluster flipped the parents' gate
    to False.) Synthetic graph: cl_a has a MARKED flexible crossing to cl_b (should gate
    open) AND an UNMARKED rigid crossing to the duplex child cl_dup (must be ignored)."""
    F = Direction.FORWARD
    a1, a2 = ("h_a", 5, F), ("h_a", 9, F)  # cl_a beads
    d1 = ("h_d", 5, F)  # duplex-child bead (overhang junction)
    b1 = ("h_b", 0, F)  # cl_b bead across a marked ssDNA run
    adj = {a1: [d1], d1: [a1], a2: [b1], b1: [a2]}
    bead_domain = {
        a1: ("scaf", 0),
        a2: ("scaf", 1),
        d1: ("ohstrand", 0),
        b1: ("scaf", 2),
    }
    marked = {a2, b1}
    owner = lambda k: {a1: "cl_a", a2: "cl_a", d1: "cl_dup", b1: "cl_b"}[k]  # noqa: E731

    # Control: WITHOUT duplex transparency the overhang junction blocks the gate.
    g_off = _gate("cl_a", adj, bead_domain, marked, owner, frozenset())
    assert g_off["gate"] is False
    assert len(g_off["rigid_blocking"]) == 1

    # With cl_dup marked as a duplex child, its junction crossing is skipped → the
    # marked cl_a↔cl_b crossing alone opens the gate.
    g_on = _gate("cl_a", adj, bead_domain, marked, owner, frozenset({"cl_dup"}))
    assert g_on["gate"] is True
    assert g_on["rigid_blocking"] == []
    assert g_on["n_crossings"] == 1


# ── Three-layer guard ──────────────────────────────────────────────────────────


def test_apply_marks_only_touches_connections():
    d = _mark_run(_hinge_design())
    before = {
        f: d.model_dump()[f]
        for f in (
            "strands",
            "helices",
            "crossovers",
            "forced_ligations",
            "cluster_transforms",
            "flexible_segment_marks",
        )
    }
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
    assert covered.isdisjoint({9, 10, 11})  # flexible bps have no axis stick
    assert {0, 1, 2, 3, 4, 5, 6, 7, 8} <= covered  # rigid bps still do


def test_axis_segments_split_overlapping_domains_and_keep_all_owners():
    """A short conjugate/overhang must not borrow a longer domain's axis stick."""
    from backend.core.deformation import _segments_for_helix

    d = _hinge_design()
    short = Strand(
        id="conjugate",
        strand_type=StrandType.STAPLE,
        domains=[Domain(
            helix_id="h_a", start_bp=3, end_bp=5,
            direction=Direction.REVERSE, overhang_id="protein_oh",
        )],
    )
    d = d.model_copy(update={"strands": [*d.strands, short]})
    h_a = next(h for h in d.helices if h.id == "h_a")
    segments = _segments_for_helix(d, h_a)

    assert [(s["bp_lo"], s["bp_hi"]) for s in segments[:3]] == [(0, 2), (3, 5), (6, 8)]
    middle_owners = {
        (ref["strand_id"], ref["domain_index"])
        for ref in segments[1]["domain_ids"]
    }
    assert ("scaf", 0) in middle_owners
    assert ("conjugate", 0) in middle_owners
    assert all(
        ("conjugate", 0) not in {
            (ref["strand_id"], ref["domain_index"])
            for ref in s["domain_ids"]
        }
        for s in (segments[0], segments[2])
    )


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
    # Mark the full bridging run so a connection forms and the beads are excluded
    # from rigid rendering (is_flexible_segment True); undo must restore them.
    r = client.post(
        "/api/design/flexible-segment/batch",
        json={"marks": _run_mark_bodies(), "replace": True},
    )
    assert r.status_code == 200, r.text
    assert any(
        n.get("is_flexible_segment") for n in (r.json().get("nucleotides") or [])
    )
    u = client.post("/api/design/undo").json()
    # Full geometry (not positions_only/cluster_only) so is_flexible_segment is recomputed.
    assert u.get("diff_kind") not in ("positions_only", "cluster_only")
    nucs = u.get("nucleotides") or []
    assert nucs and not any(n.get("is_flexible_segment") for n in nucs)
    assert design_state.get_or_404().flexible_segment_marks == []


def test_topology_change_replace_keeps_flexible_flag():
    """A non-marks topology change (e.g. add/remove an OH-binder strand) on a design
    WITH flexible connections must ship per-nuc geometry on undo/redo/seek. The
    compact_deformed arrays drop is_flexible_segment, which silently re-rigidifies a
    bowed scaffold run — the 'generate OH binder → undo → flexible region renders
    rigid' bug. The flag must survive any replace whose target still has connections."""
    from backend.api.crud import _design_replace_response
    from backend.core.validator import validate_design

    d_marked = apply_marks(_mark_run(_hinge_design()))
    assert d_marked.flexible_connections  # the run formed a connection

    # Simulate the topology change whose UNDO triggered the bug: a binder strand was
    # added; undo restores `d_marked` (no binder), which still carries connections.
    binder = Strand(
        id="ohbind_x",
        strand_type=StrandType.OH_BINDER,
        domains=[
            Domain(
                helix_id="h_a",
                start_bp=_SS_A[0],
                end_bp=_SS_A[1],
                direction=Direction.REVERSE,
            )
        ],
    )
    d_with_binder = d_marked.copy_with(strands=[*d_marked.strands, binder])

    # prev = post-change (binder present), target = restored marked design.
    resp = _design_replace_response(d_with_binder, d_marked, validate_design(d_marked))
    assert "nucleotides_compact" not in resp  # NOT the flag-dropping compact path
    nucs = resp.get("nucleotides") or []
    assert nucs and any(n.get("is_flexible_segment") for n in nucs)


def test_old_file_without_fields_loads_empty():
    raw = _demo_design().model_dump()
    raw.pop("flexible_segment_marks", None)
    raw.pop("flexible_connections", None)
    d = Design.model_validate(raw)
    assert d.flexible_segment_marks == []
    assert d.flexible_connections == []


# ── API ──────────────────────────────────────────────────────────────────────


def _run_mark_bodies() -> list[dict]:
    """Batch-mark bodies for the full bridging ssDNA run (cl_a↔cl_b)."""
    return [
        {"strand_id": "scaf", "domain_index": 1, "bp_index": bp, "direction": "FORWARD"}
        for bp in range(_SS_A[0], _SS_A[1] + 1)
    ] + [
        {"strand_id": "scaf", "domain_index": 2, "bp_index": bp, "direction": "FORWARD"}
        for bp in range(_SS_B[0], _SS_B[1] + 1)
    ]


def test_api_mark_requires_unpaired():
    design_state.set_design(_hinge_design())
    # Paired scaffold bead (domain 0, h_a) → rejected.
    r = client.post(
        "/api/design/flexible-segment",
        json={
            "strand_id": "scaf",
            "domain_index": 0,
            "bp_index": 0,
            "direction": "FORWARD",
        },
    )
    assert r.status_code == 400, r.text
    assert "unpaired" in r.json()["detail"].lower()
    # Marking the full unpaired run bridges cl_a↔cl_b → a connection forms, so the
    # geometry carries is_flexible_segment (the flag tracks connection membership,
    # not raw marks — an unconnected mark leaves its bead rigid-rendered).
    r = client.post(
        "/api/design/flexible-segment/batch",
        json={"marks": _run_mark_bodies(), "replace": True},
    )
    assert r.status_code == 200, r.text
    nucs = r.json().get("nucleotides") or []
    assert any(n.get("is_flexible_segment") for n in nucs)


def test_unconnected_mark_leaves_bead_rigid():
    """Safety net: a marked run that forms NO connection (both ends on the same
    cluster) must NOT exclude its beads from rigid rendering — is_flexible_segment
    stays False so marking can never silently delete geometry."""
    design_state.set_design(_hinge_design())
    # A single mid-run bead: its rigid neighbours are both on cl_a → no bridge.
    r = client.post(
        "/api/design/flexible-segment",
        json={
            "strand_id": "scaf",
            "domain_index": 1,
            "bp_index": 9,
            "direction": "FORWARD",
        },
    )
    assert r.status_code == 200, r.text  # accepted (unpaired) …
    assert design_state.get_or_404().flexible_segment_marks  # … and the mark persists
    assert design_state.get_or_404().flexible_connections == []  # but no connection
    nucs = r.json().get("nucleotides") or []
    assert nucs and not any(
        n.get("is_flexible_segment") for n in nucs
    )  # bead stays rigid


def test_api_mark_adds_feature_log_entry_and_reverts():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    r = client.post(
        "/api/design/flexible-segment",
        json={
            "strand_id": "scaf",
            "domain_index": 1,
            "bp_index": 9,
            "direction": "FORWARD",
        },
    )
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


def test_seek_before_mark_drops_flexible_marks():
    """Seeking the feature-log slider before the flexible-mark op REMOVES the
    marks and their derived connections.

    Regression: ``_topology_substitute`` now restores ``flexible_segment_marks``
    (+ the ``flexible_connections`` cache) from the seek snapshot, so a back-seek
    drops a mark placed after that point. They used to persist at every position
    — including the empty state — leaving the ssDNA run rendering flexible before
    it had been marked.
    """
    design_state.set_design(_hinge_design())
    r = client.post(
        "/api/design/flexible-segment/batch",
        json={"marks": _run_mark_bodies(), "replace": True},
    )
    assert r.status_code == 200, r.text
    assert design_state.get_or_404().flexible_segment_marks
    assert design_state.get_or_404().flexible_connections

    # Seek to the empty state (before the mark) → marks + connections gone.
    rr = client.post("/api/design/features/seek", json={"position": -2})
    assert rr.status_code == 200, rr.text
    assert design_state.get_or_404().flexible_segment_marks == []
    assert design_state.get_or_404().flexible_connections == []

    # Seek back to latest → both restored.
    rr = client.post("/api/design/features/seek", json={"position": -1})
    assert rr.status_code == 200, rr.text
    assert design_state.get_or_404().flexible_segment_marks
    assert design_state.get_or_404().flexible_connections


def test_api_mark_feature_log_deletable():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    client.post(
        "/api/design/flexible-segment",
        json={
            "strand_id": "scaf",
            "domain_index": 1,
            "bp_index": 9,
            "direction": "FORWARD",
        },
    )
    assert design_state.get_or_404().flexible_segment_marks
    rd = client.delete(f"/api/design/features/{n0}")
    assert rd.status_code == 200, rd.text
    d = design_state.get_or_404()
    # Delete forgets the log row but keeps current state (app-wide convention —
    # like deleting an auto-break keeps the nicks). The row is gone.
    assert len(d.feature_log) == n0
    assert not any(
        e.feature_type == "snapshot" and e.op_kind.startswith("flexible-segment")
        for e in d.feature_log
    )


def test_api_batch_then_connections_then_clear():
    design_state.set_design(_hinge_design())
    marks = [
        {"strand_id": "scaf", "domain_index": 1, "bp_index": bp, "direction": "FORWARD"}
        for bp in range(_SS_A[0], _SS_A[1] + 1)
    ]
    marks += [
        {"strand_id": "scaf", "domain_index": 2, "bp_index": bp, "direction": "FORWARD"}
        for bp in range(_SS_B[0], _SS_B[1] + 1)
    ]
    r = client.post(
        "/api/design/flexible-segment/batch", json={"marks": marks, "replace": True}
    )
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


# ── Relax commit (one atomic, revertable/deletable/undoable feature-log step) ──


def _ct(design, cid):
    return next(c for c in design.cluster_transforms if c.id == cid)


def test_api_relax_applies_transforms_one_feature_log_entry():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    r = client.post(
        "/api/design/flexible-relax",
        json={
            "transforms": [
                {
                    "cluster_id": "cl_a",
                    "pivot": [0, 0, 0],
                    "translation": [1.0, 2.0, 3.0],
                    "rotation": [0, 0, 0, 1],
                }
            ],
            "label": "Relax flexible segment",
        },
    )
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    # Transform applied, the OTHER cluster untouched.
    assert _ct(d, "cl_a").translation == [1.0, 2.0, 3.0]
    assert _ct(d, "cl_b").translation == [0.0, 0.0, 0.0]
    # Exactly one new feature-log entry of the right kind.
    log = d.feature_log
    assert len(log) == n0 + 1
    entry = log[-1].model_dump()
    assert entry["feature_type"] == "snapshot"
    assert entry["op_kind"] == "flexible-relax"


def test_api_relax_is_revertable():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    client.post(
        "/api/design/flexible-relax",
        json={
            "transforms": [
                {
                    "cluster_id": "cl_a",
                    "pivot": [0, 0, 0],
                    "translation": [5.0, 0.0, 0.0],
                    "rotation": [0, 0, 0, 1],
                }
            ]
        },
    )
    assert _ct(design_state.get_or_404(), "cl_a").translation == [5.0, 0.0, 0.0]
    rr = client.post(f"/api/design/features/{n0}/revert")
    assert rr.status_code == 200, rr.text
    assert _ct(design_state.get_or_404(), "cl_a").translation == [0.0, 0.0, 0.0]


def test_api_relax_is_deletable_rolls_back_pose():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    client.post(
        "/api/design/flexible-relax",
        json={
            "transforms": [
                {
                    "cluster_id": "cl_a",
                    "pivot": [0, 0, 0],
                    "translation": [5.0, 0.0, 0.0],
                    "rotation": [0, 0, 0, 1],
                }
            ]
        },
    )
    rd = client.delete(f"/api/design/features/{n0}")
    assert rd.status_code == 200, rd.text
    d = design_state.get_or_404()
    # Option-1 delete: the relax row AND its pose roll back (flexible-relax is a
    # non-replayable snapshot op, so deleting it restores the pre-relax pose).
    assert len(d.feature_log) == n0
    assert _ct(d, "cl_a").translation == [0.0, 0.0, 0.0]


def test_api_relax_undo_redo():
    design_state.set_design(_hinge_design())
    client.post(
        "/api/design/flexible-relax",
        json={
            "transforms": [
                {
                    "cluster_id": "cl_a",
                    "pivot": [0, 0, 0],
                    "translation": [7.0, 0.0, 0.0],
                    "rotation": [0, 0, 0, 1],
                }
            ]
        },
    )
    assert _ct(design_state.get_or_404(), "cl_a").translation == [7.0, 0.0, 0.0]
    assert client.post("/api/design/undo").status_code == 200
    assert _ct(design_state.get_or_404(), "cl_a").translation == [0.0, 0.0, 0.0]
    assert client.post("/api/design/redo").status_code == 200
    assert _ct(design_state.get_or_404(), "cl_a").translation == [7.0, 0.0, 0.0]


def test_api_relax_multi_cluster_single_entry_single_undo():
    design_state.set_design(_hinge_design())
    n0 = len(design_state.get_or_404().feature_log)
    r = client.post(
        "/api/design/flexible-relax",
        json={
            "transforms": [
                {
                    "cluster_id": "cl_a",
                    "pivot": [0, 0, 0],
                    "translation": [1.0, 0, 0],
                    "rotation": [0, 0, 0, 1],
                },
                {
                    "cluster_id": "cl_b",
                    "pivot": [0, 0, 0],
                    "translation": [0, 1.0, 0],
                    "rotation": [0, 0, 0, 1],
                },
            ],
            "label": "Relax all flexible segments",
        },
    )
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert _ct(d, "cl_a").translation == [1.0, 0.0, 0.0]
    assert _ct(d, "cl_b").translation == [0.0, 1.0, 0.0]
    # Two clusters moved, but ONE feature-log entry and ONE undo reverses both.
    assert len(d.feature_log) == n0 + 1
    assert client.post("/api/design/undo").status_code == 200
    d2 = design_state.get_or_404()
    assert _ct(d2, "cl_a").translation == [0.0, 0.0, 0.0]
    assert _ct(d2, "cl_b").translation == [0.0, 0.0, 0.0]


def test_api_relax_unknown_cluster_404():
    design_state.set_design(_hinge_design())
    r = client.post(
        "/api/design/flexible-relax",
        json={
            "transforms": [
                {
                    "cluster_id": "nope",
                    "pivot": [0, 0, 0],
                    "translation": [1, 0, 0],
                    "rotation": [0, 0, 0, 1],
                }
            ]
        },
    )
    assert r.status_code == 404


def test_api_relax_empty_400():
    design_state.set_design(_hinge_design())
    assert (
        client.post("/api/design/flexible-relax", json={"transforms": []}).status_code
        == 400
    )


# ── Real design (the worked example) ───────────────────────────────────────────

_MINI = "workspace/mini_hinge.nadoc"


@pytest.mark.skipif(not os.path.exists(_MINI), reason="mini_hinge.nadoc not present")
def test_mini_hinge_four_connections_both_gates_open():
    d = Design.model_validate_json(open(_MINI).read())
    unp = unpaired_bead_keys(d)
    marks = [
        FlexibleSegmentMark(
            strand_id=s.id, domain_index=di, bp_index=bp, direction=dom.direction
        )
        for s in d.strands
        for di, dom in enumerate(s.domains)
        for bp in range(
            min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp) + 1
        )
        if (dom.helix_id, bp, dom.direction) in unp
    ]
    d = apply_marks(d.copy_with(flexible_segment_marks=marks))
    cids = {c.id for c in d.cluster_transforms}
    assert len(d.flexible_connections) == 4
    for c in d.flexible_connections:
        assert {c.cluster_a_id, c.cluster_b_id} <= cids
        assert c.cluster_a_id != c.cluster_b_id  # all inter-cluster
    assert sorted(c.n_ss_bases for c in d.flexible_connections) == [2, 2, 16, 16]
    gates = all_cluster_gates(d)
    assert all(gates[cid]["gate"] for cid in cids)
