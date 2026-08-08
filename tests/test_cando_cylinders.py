"""CanDo-style "jointed cylinder" geometry (the "CanDo style output" display toggle).

`compute_cylinders` turns a job's cached display positions into CanDo's familiar
representation: one axis tube per helix (bp-ordered) + thin crossover joint connectors.
The axis of a duplex bp is the midpoint of its two strand backbones; ssDNA ends / loop
copies (no clean axis) are excluded, matching CanDo's duplex-only tubes.
"""

from __future__ import annotations

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.cando_cylinders import (
    JOINT_RADIUS_NM,
    TUBE_RADIUS_NM,
    axis_from_backbones,
    compute_cylinders,
)
from backend.core.models import LatticeType
from backend.physics.fem_solver import predict_shape

HC = LatticeType.HONEYCOMB
SIX_HB_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
LEN = 210


def _helix(hid: str):
    """A minimal Helix (compute_cylinders only reads .id + iterates the axis map)."""
    from backend.core.models import Helix

    z0 = {"x": 0.0, "y": 0.0, "z": 0.0}
    z1 = {"x": 0.0, "y": 0.0, "z": 10.0}
    return Helix(id=hid, axis_start=z0, axis_end=z1, length_bp=10)


def test_axis_from_backbones_is_midpoint_restricted_to_rmsf_duplex_core():
    """The fallback axis = midpoint of a bp's FORWARD+REVERSE backbones, but ONLY for bp
    that carry an RMSF node (the meshed duplex core) → ssDNA ends and loop copies drop."""
    disp = [
        {
            "helix_id": "h0",
            "bp_index": 0,
            "direction": "FORWARD",
            "copy": 0,
            "backbone_position": [0.0, 0.0, 0.0],
        },
        {
            "helix_id": "h0",
            "bp_index": 0,
            "direction": "REVERSE",
            "copy": 0,
            "backbone_position": [2.0, 0.0, 0.0],
        },
        # ssDNA bp (h0, 5): both strands present in display but NOT an RMSF node → excluded
        {
            "helix_id": "h0",
            "bp_index": 5,
            "direction": "FORWARD",
            "copy": 0,
            "backbone_position": [9.0, 0.0, 0.0],
        },
        {
            "helix_id": "h0",
            "bp_index": 5,
            "direction": "REVERSE",
            "copy": 0,
            "backbone_position": [9.0, 2.0, 0.0],
        },
        # loop copy (copy>0) → ignored
        {
            "helix_id": "h0",
            "bp_index": 0,
            "direction": "FORWARD",
            "copy": 1,
            "backbone_position": [0.0, 0.0, 0.0],
        },
    ]
    rmsf = [
        {"helix_id": "h0", "bp_index": 0, "rmsf_nm": 1.0}
    ]  # only bp 0 is duplex core
    axis = axis_from_backbones(disp, rmsf)
    assert axis == [{"helix_id": "h0", "bp_index": 0, "position": [1.0, 0.0, 0.0]}]


def test_compute_cylinders_orders_axis_nodes_by_bp_and_reports_radii():
    """Three helix-centre axis nodes given out of order → points come back bp-ordered."""
    from backend.core.models import Design

    design = Design(helices=[_helix("h0")])
    axis_nodes = [
        {"helix_id": "h0", "bp_index": 2, "position": [20.0, 1.0, 0.0]},
        {"helix_id": "h0", "bp_index": 0, "position": [0.0, 1.0, 0.0]},
        {"helix_id": "h0", "bp_index": 1, "position": [10.0, 1.0, 0.0]},
    ]
    out = compute_cylinders(design, axis_nodes)
    assert out["tube_radius_nm"] == TUBE_RADIUS_NM
    assert out["joint_radius_nm"] == JOINT_RADIUS_NM
    assert out["n_helices"] == 1
    pts = out["helices"][0]["points"]
    assert [p[0] for p in pts] == [0.0, 10.0, 20.0]  # sorted by bp
    assert all(p[1] == 1.0 for p in pts)


def test_real_6hb_yields_a_tube_per_helix_and_crossover_joints():
    """On a routed 6HB the representation has one tube per helix and one joint per
    crossover whose both ends are duplex-core axis nodes."""
    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB_CELLS, LEN, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    res = predict_shape(design, nonlinear=False, with_rmsf=False)
    assert res["axis"], "predict_shape emits helix-centre axis nodes"
    out = compute_cylinders(design, res["axis"])

    assert out["n_helices"] == 6  # one tube per helix
    for h in out["helices"]:
        assert len(h["points"]) >= 2  # a drawable chain
        assert all(len(p) == 3 for p in h["points"])
        assert len(h["rmsf"]) == len(h["points"])  # parallel per-node RMSF slot
    # Joints are a non-empty subset of the crossovers (both ends must be duplex-core).
    assert 0 < out["n_joints"] <= len(design.crossovers)
    for j in out["joints"]:
        assert len(j) == 2 and len(j[0]) == 3 and len(j[1]) == 3
    # No RMSF supplied → grey fallback (has_rmsf False), rmsf slots all None.
    assert out["has_rmsf"] is False
    assert all(v is None for h in out["helices"] for v in h["rmsf"])


def test_axis_nodes_are_helix_centre_not_backbone_midpoint():
    """The solver's axis nodes are the FEM helix-CENTRE positions (one per mesh node),
    distinct from the backbone-midpoint reconstruction — and every axis bp is a duplex
    (RMSF) node, so there are NO ssDNA nodes to grey out."""
    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB_CELLS, LEN, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    res = predict_shape(design, nonlinear=False, with_rmsf=True)
    rmsf_bp = {(r["helix_id"], r["bp_index"]) for r in res["rmsf"]}
    axis_bp = {(n["helix_id"], n["bp_index"]) for n in res["axis"]}
    # Axis nodes ARE the RMSF/mesh (duplex-core) nodes → no ssDNA, full colour coverage.
    assert axis_bp == rmsf_bp
    # The cached axis differs from the backbone-midpoint fallback (helical wobble removed).
    fallback = {
        (n["helix_id"], n["bp_index"]): n["position"]
        for n in axis_from_backbones(res["positions"], res["rmsf"])
    }
    solver = {(n["helix_id"], n["bp_index"]): n["position"] for n in res["axis"]}
    shared = set(fallback) & set(solver)
    assert shared
    diffs = [
        abs(fallback[k][0] - solver[k][0])
        + abs(fallback[k][1] - solver[k][1])
        + abs(fallback[k][2] - solver[k][2])
        for k in shared
    ]
    assert max(diffs) > 1e-6  # the two axis definitions genuinely differ


def test_rmsf_heatmap_attached_per_node_with_p95_ramp():
    """When the job's RMSF is supplied, every axis node carries its RMSF and the ramp
    reports min / 95th-percentile / max — CanDo's structure_NMA_RMSF heat-map bounds."""
    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB_CELLS, LEN, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    res = predict_shape(design, nonlinear=False, with_rmsf=True)
    out = compute_cylinders(design, res["axis"], res["rmsf"])

    assert out["has_rmsf"] is True
    assert out["rmsf_min"] <= out["rmsf_p95"] <= out["rmsf_max"]
    # The FEM nodes ARE the RMSF nodes, so almost every axis node gets an RMSF (a few
    # edge bp outside the meshed duplex core fall back to grey — the overlay handles it).
    vals = [v for h in out["helices"] for v in h["rmsf"]]
    got = [v for v in vals if v is not None]
    assert len(got) > 0.9 * len(vals)
    assert all(v > 0 for v in got)
    # Joints carry their mean-endpoint RMSF, parallel to the joints list.
    assert len(out["joint_rmsf"]) == out["n_joints"]
    assert any(v is not None for v in out["joint_rmsf"])


def test_empty_display_yields_empty_representation():
    from backend.core.models import Design

    design = Design(helices=[_helix("h0")])
    out = compute_cylinders(design, [])
    assert out["helices"] == [] and out["joints"] == []
    assert out["n_helices"] == 0 and out["n_joints"] == 0
