"""Oracle for S2 — unified deviation + RMSF profiles (shape_metrics.py).

The pass criterion is a *comparable prediction with a property assertion*, not "it
ran".  These three primitives are the engine-agnostic sources S3's ``compare_descriptors``
consumes, so each is pinned to a KNOWN synthetic input:

  deviation_profile   identical frame -> RMSD 0; a known non-rigid displacement -> that
                      exact per-nt deviation; a pure rigid pose difference -> ~0 after
                      Kabsch (align=True) but the raw offset with align=False.
  rmsf_from_ensemble  a static ensemble -> RMSF 0; a known oscillation amplitude round-
                      trips to A/sqrt(2); a more-flexible site reads a larger RMSF.
  normalize_rmsf_profile  max -> 1, min >= 0, ordering preserved, rescales back exactly.

A display frame is a list of {helix_id, bp_index, direction, backbone_position} dicts —
the same substrate every engine's overlay already emits (mirrors test_shape_metrics).
"""
import math

import numpy as np

from backend.core.shape_metrics import (
    deviation_profile,
    normalize_rmsf_profile,
    rmsf_from_ensemble,
)


def _pos(hid, bp, direction, xyz, **extra):
    d = {"helix_id": hid, "bp_index": bp, "direction": direction,
         "backbone_position": list(xyz)}
    d.update(extra)
    return d


def _grid_frame(n_helix=3, n_axial=20, radius=1.2, rise=0.34):
    """A small straight bundle — the reference frame the deviation/rmsf fixtures
    perturb."""
    out = []
    for h in range(n_helix):
        ang = 2 * math.pi * h / n_helix
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        for i in range(n_axial):
            out.append(_pos(h, i, "forward", (x, y, rise * i)))
    return out


# ── deviation_profile ────────────────────────────────────────────────────────────

def test_identical_frame_has_zero_deviation():
    ref = _grid_frame()
    d = deviation_profile(ref, ref, align=True)
    assert d["rmsd_nm"] < 1e-9
    assert d["max_deviation"] < 1e-9
    assert d["n"] == len(ref)
    d0 = deviation_profile(ref, ref, align=False)
    assert d0["rmsd_nm"] < 1e-9


def test_known_displacement_recovered_exactly_unaligned():
    """align=False must report the EXACT per-nt displacement (frames already share a
    frame) — displace a known subset by a known vector, the rest stay put."""
    ref = _grid_frame(n_helix=3, n_axial=20)
    shift = np.array([0.0, 0.0, 0.7])
    moved_keys = {(0, i) for i in range(5)}          # 5 nucleotides on helix 0
    cand = []
    for p in ref:
        xyz = np.array(p["backbone_position"], float)
        if (p["helix_id"], p["bp_index"]) in moved_keys:
            xyz = xyz + shift
        cand.append(_pos(p["helix_id"], p["bp_index"], p["direction"], xyz))
    d = deviation_profile(cand, ref, align=False)
    per = {(o["helix_id"], o["bp_index"]): o["deviation"] for o in d["positions"]}
    for k in moved_keys:
        assert abs(per[k] - 0.7) < 1e-9             # exactly the shift magnitude
    n_moved = len(moved_keys)
    for (h, bp), dev in per.items():
        if (h, bp) not in moved_keys:
            assert dev < 1e-9
    expected_rmsd = math.sqrt(n_moved * 0.7 ** 2 / len(ref))
    assert abs(d["rmsd_nm"] - expected_rmsd) < 1e-9


def test_rigid_pose_difference_is_removed_by_kabsch():
    """A candidate that is the reference rigidly rotated + translated has ~0 shape
    deviation after align=True, but a large raw offset with align=False — proving the
    alignment removes pose, not shape."""
    ref = _grid_frame(n_helix=3, n_axial=20)
    P = np.array([p["backbone_position"] for p in ref], float)
    th = math.radians(37.0)
    R = np.array([[math.cos(th), -math.sin(th), 0.0],
                  [math.sin(th), math.cos(th), 0.0],
                  [0.0, 0.0, 1.0]])
    Pr = P @ R.T + np.array([5.0, -3.0, 2.0])
    cand = [_pos(p["helix_id"], p["bp_index"], p["direction"], Pr[i])
            for i, p in enumerate(ref)]
    d_aligned = deviation_profile(cand, ref, align=True)
    d_raw = deviation_profile(cand, ref, align=False)
    assert d_aligned["rmsd_nm"] < 1e-6              # pure pose → nothing survives Kabsch
    assert d_raw["rmsd_nm"] > 1.0                   # the raw offset is large


def test_deviation_goes_red_on_nonrigid_shear():
    """A non-rigid shear (a bend the design doesn't intend) SURVIVES Kabsch — the
    descriptor discriminates real shape mismatch from pose."""
    ref = _grid_frame(n_helix=3, n_axial=20)
    cand = []
    for p in ref:
        x, y, z = p["backbone_position"]
        cand.append(_pos(p["helix_id"], p["bp_index"], p["direction"],
                         (x + 0.15 * z, y, z)))     # shear grows along the axis
    d = deviation_profile(cand, ref, align=True)
    assert d["rmsd_nm"] > 0.1                        # would violate the identical-frame null


# ── rmsf_from_ensemble ───────────────────────────────────────────────────────────

def test_static_ensemble_has_zero_rmsf():
    ref = _grid_frame()
    d = rmsf_from_ensemble([ref, ref, ref])
    assert d["n_frames"] == 3
    assert d["max_rmsf"] < 1e-9


def test_known_amplitude_oscillation_round_trips():
    """Nucleotide i oscillates along +x with amplitude A_i across F frames; the RMSF of
    a sinusoid sampled over full periods is A/sqrt(2).  Recovering that from the ensemble
    is the round-trip."""
    base = _grid_frame(n_helix=2, n_axial=10)
    amps = {}
    for idx, p in enumerate(base):
        amps[(p["helix_id"], p["bp_index"], p["direction"])] = 0.1 + 0.02 * (idx % 7)
    F = 400
    frames = []
    for f in range(F):
        phase = 2 * math.pi * f / F
        fr = []
        for p in base:
            k = (p["helix_id"], p["bp_index"], p["direction"])
            x, y, z = p["backbone_position"]
            fr.append(_pos(*k, (x + amps[k] * math.sin(phase), y, z)))
        frames.append(fr)
    # align=False: the ensemble is already in a common frame; Kabsch would fold the
    # per-site motion into a spurious global rotation for this tiny bundle.
    d = rmsf_from_ensemble(frames, align=False)
    per = {(o["helix_id"], o["bp_index"], o["direction"]): o["rmsf_nm"]
           for o in d["positions"]}
    for k, a in amps.items():
        assert abs(per[k] - a / math.sqrt(2)) < 0.01     # A/sqrt(2) within tol


def test_more_flexible_site_reads_larger_rmsf():
    base = _grid_frame(n_helix=2, n_axial=6)
    flex_key = (0, 3, "forward")
    F = 200
    frames = []
    for f in range(F):
        phase = 2 * math.pi * f / F
        fr = []
        for p in base:
            k = (p["helix_id"], p["bp_index"], p["direction"])
            amp = 0.5 if k == flex_key else 0.05
            x, y, z = p["backbone_position"]
            fr.append(_pos(*k, (x + amp * math.sin(phase), y, z)))
        frames.append(fr)
    d = rmsf_from_ensemble(frames, align=False)
    per = {(o["helix_id"], o["bp_index"], o["direction"]): o["rmsf_nm"]
           for o in d["positions"]}
    assert per[flex_key] == max(per.values())
    assert per[flex_key] > 5 * min(per.values())


def test_align_removes_bulk_drift_but_keeps_site_fluctuation():
    """The align=True path is the production mode (a trajectory diffuses/tumbles in a
    box): a whole-bundle translation per frame must be removed, while a genuine single-
    site oscillation survives ~A/sqrt(2).  Loose tol — Kabsch bleeds a little on a small
    bundle."""
    base = _grid_frame(n_helix=3, n_axial=16)
    flex_key = (0, 8, "forward")
    amp = 0.6
    F = 240
    frames = []
    for f in range(F):
        phase = 2 * math.pi * f / F
        drift = np.array([3.0 * math.sin(phase), 0.0, 2.0 * math.cos(phase)])  # bulk pose
        fr = []
        for p in base:
            k = (p["helix_id"], p["bp_index"], p["direction"])
            xyz = np.array(p["backbone_position"], float) + drift
            if k == flex_key:
                xyz = xyz + np.array([amp * math.sin(phase), 0.0, 0.0])
            fr.append(_pos(*k, xyz))
        frames.append(fr)
    d = rmsf_from_ensemble(frames, align=True)
    per = {(o["helix_id"], o["bp_index"], o["direction"]): o["rmsf_nm"]
           for o in d["positions"]}
    assert per[flex_key] == max(per.values())        # the fluctuating site stands out
    # bulk drift (amplitude ~3.6 nm) removed → the rigid sites read near-zero, far below
    # the site's own ~A/sqrt(2); the site itself recovers within a loose Kabsch-bleed tol.
    rigid = [v for k, v in per.items() if k != flex_key]
    assert max(rigid) < 0.15                          # pose stripped, not leaking in
    assert abs(per[flex_key] - amp / math.sqrt(2)) < 0.12


# ── normalize_rmsf_profile ─────────────────────────────────────────────────────────

def test_normalize_maps_max_to_one_and_rescales_back():
    prof = [
        {"helix_id": 0, "bp_index": 0, "direction": "forward", "rmsf_nm": 0.2},
        {"helix_id": 0, "bp_index": 1, "direction": "forward", "rmsf_nm": 0.8},
        {"helix_id": 1, "bp_index": 0, "direction": "forward", "rmsf_nm": 0.4},
    ]
    norm = normalize_rmsf_profile(prof)
    vals = list(norm.values())
    assert abs(max(vals) - 1.0) < 1e-12
    assert min(vals) >= 0.0
    # ordering preserved + rescale-back recovers the original values.
    assert norm["0:1:forward"] > norm["1:0:forward"] > norm["0:0:forward"]
    assert abs(norm["0:0:forward"] * 0.8 - 0.2) < 1e-12


def test_normalize_all_zero_is_safe():
    prof = [{"helix_id": 0, "bp_index": 0, "direction": "forward", "rmsf_nm": 0.0}]
    norm = normalize_rmsf_profile(prof)
    assert norm["0:0:forward"] == 0.0               # no divide-by-zero blow-up
