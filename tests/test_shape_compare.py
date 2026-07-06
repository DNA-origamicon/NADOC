"""Oracle for S3 — compare_descriptors + reference_for (shape_metrics.py).

The pass criterion is a *comparable prediction with a property assertion*: given two
engine descriptor bundles, the agreement math must recover KNOWN deltas/correlations,
and the per-observable reference selection must honour the stated policy (oxDNA=shape/
field, CanDo=RMSF, NAMD overrides once present).

A source bundle is ``{engine, descriptors (compute_shape_descriptors output), rmsf
(per-nt {helix_id,bp_index,rmsf_nm,...} list), shape_frame (display-position map)}`` —
the same substrate S1/S2 already produce, so S3 is a pure composition layer.
"""
import math

import numpy as np

from backend.core.shape_metrics import compare_descriptors, reference_for


def _pos(hid, bp, direction, xyz, **extra):
    d = {"helix_id": hid, "bp_index": bp, "direction": direction,
         "backbone_position": list(xyz)}
    d.update(extra)
    return d


def _grid_frame(n_helix=3, n_axial=20, radius=1.2, rise=0.34):
    out = []
    for h in range(n_helix):
        ang = 2 * math.pi * h / n_helix
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        for i in range(n_axial):
            out.append(_pos(h, i, "forward", (x, y, rise * i)))
    return out


def _descriptors(**over):
    base = {"twist_total_deg": 100.0, "twist_per_turn_deg": 34.0,
            "bend_angle_deg": 12.0, "bend_radius_nm": 40.0,
            "radius_of_gyration_nm": 5.0, "end_to_end_nm": 6.5,
            "axial_span_nm": 6.8, "n_nucleotides": 60}
    base.update(over)
    return base


def _rmsf_profile(values, hid=0):
    return [{"helix_id": hid, "bp_index": i, "direction": "forward", "rmsf_nm": float(v)}
            for i, v in enumerate(values)]


def _bundle(engine, descriptors=None, rmsf=None, shape_frame=None):
    return {"engine": engine, "descriptors": descriptors, "rmsf": rmsf,
            "shape_frame": shape_frame}


# ── compare_descriptors: identical inputs -> perfect agreement ─────────────────────

def test_identical_sources_perfect_agreement():
    d = _descriptors()
    rmsf = _rmsf_profile([1.0, 2.0, 3.0, 4.0, 5.0])
    frame = _grid_frame()
    cand = _bundle("cando", d, rmsf, frame)
    ref = _bundle("oxdna", dict(d), list(rmsf), list(frame))
    out = compare_descriptors(cand, ref)

    assert out["candidate"] == "cando"
    assert out["reference"] == "oxdna"
    for name, s in out["scalars"].items():
        assert abs(s["abs_delta"]) < 1e-9, name
        assert abs(s["signed_pct_delta"]) < 1e-9, name
    assert out["rmsf"]["pearson"] == 1.0
    assert out["rmsf"]["spearman"] > 0.999999
    assert out["rmsf"]["n"] == 5
    assert out["shape_rmsd_nm"] < 1e-9


# ── scalar signed %-delta ──────────────────────────────────────────────────────────

def test_scalar_signed_pct_delta_sign_and_magnitude():
    ref = _bundle("oxdna", _descriptors(twist_total_deg=100.0))
    hi = compare_descriptors(_bundle("cando", _descriptors(twist_total_deg=110.0)), ref)
    lo = compare_descriptors(_bundle("cando", _descriptors(twist_total_deg=90.0)), ref)
    assert hi["scalars"]["twist_total_deg"]["abs_delta"] == 10.0
    assert hi["scalars"]["twist_total_deg"]["signed_pct_delta"] == 10.0
    assert lo["scalars"]["twist_total_deg"]["signed_pct_delta"] == -10.0


def test_scalar_none_and_zero_reference_are_safe():
    # reference descriptor None -> both deltas None (can't compare)
    out = compare_descriptors(
        _bundle("cando", _descriptors(bend_angle_deg=5.0)),
        _bundle("oxdna", _descriptors(bend_angle_deg=None)))
    assert out["scalars"]["bend_angle_deg"]["abs_delta"] is None
    assert out["scalars"]["bend_angle_deg"]["signed_pct_delta"] is None
    # reference exactly zero -> abs_delta defined, percent undefined (no divide-by-zero)
    out0 = compare_descriptors(
        _bundle("cando", _descriptors(twist_total_deg=3.0)),
        _bundle("oxdna", _descriptors(twist_total_deg=0.0)))
    assert out0["scalars"]["twist_total_deg"]["abs_delta"] == 3.0
    assert out0["scalars"]["twist_total_deg"]["signed_pct_delta"] is None


# ── RMSF correlation ───────────────────────────────────────────────────────────────

def test_rmsf_scaled_profile_is_rank_and_linear_correlated():
    base = [1.0, 3.0, 2.0, 5.0, 4.0]
    out = compare_descriptors(
        _bundle("cando", rmsf=_rmsf_profile([2 * v for v in base])),
        _bundle("oxdna", rmsf=_rmsf_profile(base)))
    assert out["rmsf"]["pearson"] == 1.0          # y = 2x is perfectly linear
    assert out["rmsf"]["spearman"] > 0.999999


def test_rmsf_reversed_profile_is_anticorrelated():
    base = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = compare_descriptors(
        _bundle("cando", rmsf=_rmsf_profile(list(reversed(base)))),
        _bundle("oxdna", rmsf=_rmsf_profile(base)))
    assert out["rmsf"]["pearson"] < -0.99
    assert out["rmsf"]["spearman"] < -0.99


def test_rmsf_constant_profile_yields_none_not_nan():
    out = compare_descriptors(
        _bundle("cando", rmsf=_rmsf_profile([2.0, 2.0, 2.0, 2.0])),
        _bundle("oxdna", rmsf=_rmsf_profile([1.0, 2.0, 3.0, 4.0])))
    assert out["rmsf"]["pearson"] is None
    assert out["rmsf"]["spearman"] is None


def test_rmsf_cando_directionless_vs_ensemble_per_strand_correlates():
    """The primary designated RMSF pairing: CanDo (reference) emits ONE direction-less
    entry per base pair; an ensemble engine (oxDNA/NAMD) emits TWO per-strand entries per
    base pair.  Collapsing both to per-bp must let them correlate — not silently return
    None because the strand keys never met."""
    # CanDo-style: direction-less, one per bp
    cando = [{"helix_id": 0, "bp_index": i, "rmsf_nm": v}
             for i, v in enumerate([1.0, 3.0, 2.0, 5.0, 4.0])]
    # oxDNA-style: forward + reverse per bp; per-bp mean tracks the CanDo profile
    ensemble = []
    for i, v in enumerate([1.1, 2.9, 2.2, 4.8, 4.1]):
        ensemble.append({"helix_id": 0, "bp_index": i, "direction": "forward",
                         "rmsf_nm": v + 0.05})
        ensemble.append({"helix_id": 0, "bp_index": i, "direction": "reverse",
                         "rmsf_nm": v - 0.05})
    out = compare_descriptors(_bundle("oxdna", rmsf=ensemble),
                              _bundle("cando", rmsf=cando))
    assert out["reference"] == "cando"
    assert out["rmsf"] is not None
    assert out["rmsf"]["n"] == 5                      # matched on all 5 base pairs
    assert out["rmsf"]["spearman"] > 0.9             # same rank order


def test_rmsf_absent_on_either_side_is_none():
    out = compare_descriptors(
        _bundle("cando", rmsf=None),
        _bundle("oxdna", rmsf=_rmsf_profile([1.0, 2.0, 3.0])))
    assert out["rmsf"] is None


# ── aligned-shape RMSD (reuses deviation_profile align=True) ────────────────────────

def test_shape_rmsd_ignores_rigid_pose_but_catches_shape():
    ref = _grid_frame()
    # pure rigid translation+rotation of the SAME shape -> ~0 after Kabsch
    theta = 0.4
    R = np.array([[math.cos(theta), -math.sin(theta), 0],
                  [math.sin(theta), math.cos(theta), 0], [0, 0, 1]])
    moved = [_pos(p["helix_id"], p["bp_index"], p["direction"],
                  (R @ np.asarray(p["backbone_position"])) + np.array([10.0, -3.0, 2.0]))
             for p in ref]
    rigid = compare_descriptors(_bundle("cando", shape_frame=moved),
                                _bundle("oxdna", shape_frame=ref))
    assert rigid["shape_rmsd_nm"] < 1e-6

    # a genuine non-rigid shear survives the alignment
    sheared = [_pos(p["helix_id"], p["bp_index"], p["direction"],
                    (p["backbone_position"][0] + 0.3 * p["backbone_position"][2],
                     p["backbone_position"][1], p["backbone_position"][2]))
               for p in ref]
    bent = compare_descriptors(_bundle("cando", shape_frame=sheared),
                               _bundle("oxdna", shape_frame=ref))
    assert bent["shape_rmsd_nm"] > 0.1


def test_shape_rmsd_absent_frame_is_none():
    out = compare_descriptors(_bundle("cando", shape_frame=None),
                              _bundle("oxdna", shape_frame=_grid_frame()))
    assert out["shape_rmsd_nm"] is None


# ── reference_for: per-observable policy + NAMD override ────────────────────────────

def test_reference_for_policy_defaults():
    engines = ["cando", "oxdna"]
    assert reference_for(engines, "shape") == "oxdna"
    assert reference_for(engines, "field") == "oxdna"
    assert reference_for(engines, "rmsf") == "cando"


def test_reference_for_namd_overrides_every_observable():
    engines = ["cando", "oxdna", "namd"]
    assert reference_for(engines, "shape") == "namd"
    assert reference_for(engines, "field") == "namd"
    assert reference_for(engines, "rmsf") == "namd"


def test_reference_for_missing_preferred_engine_is_none():
    # RMSF reference is CanDo; absent -> None (not a silent wrong pick)
    assert reference_for(["oxdna", "mrdna"], "rmsf") is None
    # unknown observable class -> None
    assert reference_for(["oxdna", "cando"], "bogus") is None
    assert reference_for([], "shape") is None
