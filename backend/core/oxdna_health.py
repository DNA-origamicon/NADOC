"""
oxDNA relaxation health metrics.

Computed from a stage's oxDNA outputs and surfaced per stage in the Dynamics
panel (analogue of the NAMD ``md_health``):

  • base-pair retention — fraction of designed Watson-Crick pairs still formed,
    from base-site proximity on the relaxed configuration.
  • potential-energy convergence — per-particle U trend parsed from energy.dat.
  • max backbone stretch (steric-clash proxy) — the longest backbone bond on the
    relaxed config; large right after lattice construction, should drop after the
    min stage.

All metrics are read-only over the Physical layer — they never touch Design
topology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.core.constants import OXDNA_LENGTH_UNIT
from backend.core.models import Design
from backend.physics.oxdna_interface import (
    backbone_bond_pairs,
    count_hbonds,
    oxdna_backbone_site,
    read_configuration_full,
)


# oxDNA's hydrogen-bond (base) interaction site sits at CM + POS_BASE·a1, where the
# .dat position IS the centre of mass and POS_BASE = 0.4 oxDNA units (model.h).
OXDNA_BASE_SITE_NM: float = 0.4 * OXDNA_LENGTH_UNIT   # ≈ 0.341 nm

# A designed WC pair counts as "formed" when the two oxDNA base sites are within
# this distance — i.e. actually hydrogen-bonded (oxDNA forms H-bonds at ~0.34 nm).
# Calibrated against oxDNA's own HBList observable on a relaxed 6-helix origami:
# 0.8 nm → 221 formed vs oxDNA's 223 H-bonds (99% match).  (The old 1.8 nm cutoff
# was ~5× too loose — it counted partners as "paired" while they were far outside
# bonding range, so it read ~100% even as the structure melted.)
BP_FORMED_CUTOFF_NM: float = 0.8

# A backbone bond longer than this (nm) is treated as an unresolved steric
# clash / over-stretch.  Healthy CG backbone bonds are ~0.6–0.8 nm.
BACKBONE_CLASH_NM: float = 1.5

# ── FENE backbone-bond limit (oxDNA2) ─────────────────────────────────────────
# oxDNA's backbone is a FENE spring between the BACKBONE SITES of consecutive
# nucleotides (NOT the centres of mass the .dat stores — the site sits ~0.34 units
# outward, so a CM–CM distance badly under-reads the real bond length).  The FENE
# potential is only defined out to ``r0 + delta``; beyond that oxDNA aborts the run
# with "Distance between bonded neighbors … exceeds acceptable values".  The relax
# stages cap the backbone force (``max_backbone_force``) so an over-stretched bond
# is held by a finite linear spring instead of diverging — but a stage that REMOVES
# the cap (a bare-FENE equil) then dies at config load on the first over-limit bond.
#
# Calibrated against oxDNA's own report on the VoltronCore equil crash: oxDNA aborted
# on a bond it measured at 1.024 units; the site-based metric below independently put
# that same bond at 1.024 (exactly one bond over r_max), while a CM-based metric
# mis-reported 880 "over" bonds.  So the site-based distance is the one that predicts
# the abort.
FENE_R0_OXDNA2:   float = 0.7564           # oxDNA units (model.h FENE_R0_OXDNA2)
FENE_DELTA:       float = 0.25             # oxDNA units (FENE_DELTA)
FENE_RMAX_UNITS:  float = FENE_R0_OXDNA2 + FENE_DELTA   # ≈ 1.0064 — the hard cliff
# A bond at/over this is "not equil-ready": below the cliff with a margin for the
# first velocity-refresh kick (~0.025 units observed) that can tip a borderline bond
# over r_max before the integrator ever runs a step.
FENE_SAFE_MAX_UNITS: float = 0.98


@dataclass
class OxdnaHealthResult:
    bp_retained_fraction: float | None = None
    n_pairs:              int = 0
    potential_energy:     float | None = None
    energy_converged:     bool = False
    max_backbone_stretch: float | None = None
    n_clashes:            int = 0
    # FENE equil-readiness (site-based, oxDNA units): the longest backbone bond and
    # how many exceed oxDNA's FENE cliff.  ``fene_safe`` is False when an uncapped
    # (bare-FENE) stage would risk aborting at config load.  Advisory — drives the
    # runner's escalate-and-retry, NOT the ``passed`` gate (a capped equil tolerates
    # a residual over-stretch, so this never on its own fails a stage).
    max_backbone_fene_units: float | None = None
    n_fene_over:          int = 0
    fene_safe:            bool = True
    passed:               bool = True
    reason:               str = ""
    error:                str | None = None


# ── energy.dat parsing ────────────────────────────────────────────────────────


def parse_energy_dat(path: str | Path) -> list[tuple[float, float]]:
    """Return [(time, potential_energy_per_particle), …] from an oxDNA energy.dat.

    oxDNA writes whitespace columns ``time  U  K  total`` (U = potential energy
    per particle).  Lines that don't parse are skipped.
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[tuple[float, float]] = []
    for line in p.read_text(errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        try:
            out.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return out


def energy_is_converged(
    samples: list[tuple[float, float]],
    *,
    window: int = 10,
    rel_tol: float = 0.02,
) -> bool:
    """Plateau test: the last *window* potential-energy samples vary by less than
    *rel_tol* of the run's energy range.  Returns False if too few samples."""
    if len(samples) < window + 1:
        return False
    u = np.array([s[1] for s in samples], dtype=float)
    rng = float(u.max() - u.min())
    if rng <= 1e-9:
        return True
    tail = u[-window:]
    return float(tail.max() - tail.min()) <= rel_tol * rng


# ── geometric metrics on a relaxed configuration ──────────────────────────────


def base_pair_retention(
    design: Design,
    full_map: dict[tuple[str, int, str], dict],
    *,
    cutoff_nm: float = BP_FORMED_CUTOFF_NM,
) -> tuple[float, int]:
    """Fraction of designed WC pairs actually hydrogen-bonded + the pair count.

    A designed pair is a (helix, bp) where both FORWARD and REVERSE nucleotides
    are present.  Each nucleotide's oxDNA base (H-bond) site = position +
    OXDNA_BASE_SITE_NM·a1 (the .dat position is the centre of mass; the base site
    is 0.4 oxDNA units along a1).  A pair is "formed" when the two base sites are
    within *cutoff_nm* — i.e. within hydrogen-bonding range, calibrated to oxDNA's
    HBList observable (≈0.34 nm bonded; 0.8 nm cutoff matches it to ~1%).
    """
    # Collect (helix, bp) with both strands present.
    fwd = {(k[0], k[1]) for k in full_map if k[2] == "FORWARD"}
    rev = {(k[0], k[1]) for k in full_map if k[2] == "REVERSE"}
    designed = sorted(fwd & rev)
    if not designed:
        return (0.0, 0)

    formed = 0
    for hid, bp in designed:
        f = full_map[(hid, bp, "FORWARD")]
        r = full_map[(hid, bp, "REVERSE")]
        f_base = f["backbone_position"] + OXDNA_BASE_SITE_NM * f["a1"]
        r_base = r["backbone_position"] + OXDNA_BASE_SITE_NM * r["a1"]
        if float(np.linalg.norm(f_base - r_base)) <= cutoff_nm:
            formed += 1
    return (formed / len(designed), len(designed))


def production_rmsd(
    design,
    production_traj_path,
    reference_conf_path,
) -> dict:
    """Per-frame backbone RMSD (nm) of a production trajectory vs the relaxed
    reference structure.  Each frame is PBC-unwrapped and Kabsch-aligned to the
    reference (so rigid-body diffusion/tumbling is removed) — the RMSD is the
    genuine internal structural deviation during production.  Returns
    {n_frames, series, mean, max, min}."""
    from backend.physics.oxdna_interface import (
        _parse_box_nm,
        read_configuration_full,
        read_trajectory_frames_full,
        unwrap_align_to_reference,
    )
    ref = read_configuration_full(reference_conf_path, design)
    frames = read_trajectory_frames_full(production_traj_path, design)
    box = _parse_box_nm(production_traj_path)
    series: list[float] = []
    for fr in frames:
        aligned = (unwrap_align_to_reference(fr, ref, design, box)
                   if box is not None and np.all(box > 0) else fr)
        keys = [k for k in aligned if k in ref]
        if not keys:
            continue
        d = np.array([aligned[k]["backbone_position"] - ref[k]["backbone_position"] for k in keys])
        series.append(float(np.sqrt((d ** 2).sum(1).mean())))
    if not series:
        return {"n_frames": 0, "series": [], "mean": None, "max": None, "min": None}
    s = np.array(series)
    return {"n_frames": len(series), "series": series,
            "mean": float(s.mean()), "max": float(s.max()), "min": float(s.min())}


def production_rmsf(
    design,
    production_traj_path,
    reference_conf_path,
    include_average_frame: bool = False,
) -> dict:
    """Per-NUCLEOTIDE average position + RMSF (root-mean-square fluctuation, nm)
    over a production trajectory — the flexibility map.

    ``production_traj_path`` may be a single path or a LIST of paths; when several
    production runs exist their frames are pooled so the map reflects ALL runs.

    Each frame is PBC-unwrapped + Kabsch-aligned to the relaxed reference (rigid
    diffusion/tumbling removed), then for every nucleotide we take the mean of its
    true backbone-site position across frames and the RMSF about that mean.  Low
    RMSF = rigid, high RMSF = flexible.  The backbone site (not the raw oxDNA
    centre of mass) is used so the displayed mean structure has the correct duplex
    width.

    Returns {ready, n_frames, positions:[{helix_id, bp_index, direction,
    backbone_position:[mean xyz], nx, ny, nz (mean a1), rmsf}], min_rmsf,
    max_rmsf, mean_rmsf}.

    When ``include_average_frame`` is set, also returns ``average_frame`` — a
    per-nucleotide ``{key: {backbone_position(mean CM), a1, a3}}`` dict in the
    SAME shape the relaxed-display ``full_map`` uses, so the heavy-rep
    reconstruction (``frame_atomistic_flat`` / ``frame_surface_json``) can build
    atomistic/surface for the average ("flexibility map") structure. The mean is
    taken over the raw oxDNA CM + a1 + a3 (not the backbone site) because the
    reconstruction re-derives the backbone site and the deformed centerline from
    the CM, exactly as it does for a trajectory frame.
    """
    from backend.physics.oxdna_interface import (
        _parse_box_nm,
        oxdna_backbone_site,
        read_configuration_full,
        read_trajectory_frames_full,
        unwrap_align_to_reference,
    )
    ref = read_configuration_full(reference_conf_path, design)
    paths = (list(production_traj_path)
             if isinstance(production_traj_path, (list, tuple))
             else [production_traj_path])

    acc: dict[tuple, dict] = {}   # key → {"pos": [bb xyz...], "a1": [a1...]}
    n_frames = 0
    for path in paths:
        frames = read_trajectory_frames_full(path, design)
        box = _parse_box_nm(path)
        for fr in frames:
            aligned = (unwrap_align_to_reference(fr, ref, design, box)
                       if box is not None and np.all(box > 0) else fr)
            n_frames += 1
            for k, v in aligned.items():
                bb = oxdna_backbone_site(v["backbone_position"], v["a1"], v["a3"])
                slot = acc.setdefault(k, {"pos": [], "a1": [], "cm": [], "a3": []})
                slot["pos"].append(bb)
                slot["a1"].append(v["a1"])
                if include_average_frame:
                    slot["cm"].append(np.asarray(v["backbone_position"], dtype=float))
                    slot["a3"].append(np.asarray(v["a3"], dtype=float))

    if n_frames == 0 or not acc:
        return {"ready": False, "n_frames": 0, "positions": [],
                "min_rmsf": None, "max_rmsf": None, "mean_rmsf": None}

    positions: list[dict] = []
    rmsfs: list[float] = []
    average_frame: dict = {}
    for (hid, bp, direction), slot in acc.items():
        P = np.array(slot["pos"])                      # (F, 3)
        mean_pos = P.mean(axis=0)
        rmsf = float(np.sqrt(((P - mean_pos) ** 2).sum(axis=1).mean()))
        a1m = np.array(slot["a1"]).mean(axis=0)
        a1m = a1m / (np.linalg.norm(a1m) + 1e-14)
        positions.append({
            "helix_id": hid, "bp_index": bp, "direction": direction,
            "backbone_position": mean_pos.tolist(),
            "nx": float(a1m[0]), "ny": float(a1m[1]), "nz": float(a1m[2]),
            "rmsf": rmsf,
        })
        rmsfs.append(rmsf)
        if include_average_frame:
            cmm = np.array(slot["cm"]).mean(axis=0)
            a3m = np.array(slot["a3"]).mean(axis=0)
            a3m = a3m / (np.linalg.norm(a3m) + 1e-14)
            average_frame[(hid, bp, direction)] = {
                "backbone_position": cmm, "a1": a1m, "a3": a3m,
            }

    r = np.array(rmsfs)
    out = {"ready": True, "n_frames": n_frames, "positions": positions,
           "min_rmsf": float(r.min()), "max_rmsf": float(r.max()),
           "mean_rmsf": float(r.mean())}
    if include_average_frame:
        out["average_frame"] = average_frame
    return out


# Below this many pooled frames the flexibility map is flagged "preliminary"
# (rel. error ≳ 10%).  RMSF converges slowly, so a short run is untrustworthy.
RMSF_PRELIM_FRAMES = 50


def rmsf_confidence(n_frames: int) -> dict:
    """Statistical reliability of an RMSF map estimated from ``n_frames`` pooled
    trajectory frames.

    The relative standard error of an RMS/standard-deviation estimator from N
    independent samples is ≈ ``1/sqrt(2N)``.  Trajectory frames are
    autocorrelated, so treating them as independent is OPTIMISTIC — the true
    error is at least this large; the value is a lower bound that still makes a
    short run read as untrustworthy.  Below ``RMSF_PRELIM_FRAMES`` the map is
    flagged ``preliminary`` so the user does not over-interpret it.

    Returns ``{n_frames, rel_error (fraction or None), preliminary (bool)}``.
    """
    n = max(0, int(n_frames))
    if n < 2:
        return {"n_frames": n, "rel_error": None, "preliminary": True}
    return {
        "n_frames": n,
        "rel_error": 1.0 / math.sqrt(2.0 * n),
        "preliminary": n < RMSF_PRELIM_FRAMES,
    }


# ── Relaxed-structure measurements (the constraint primitives, AF-13 P2) ───────
# Pure geometric measurements over a relaxed/mean position map — the building
# blocks of constraint-driven design ("make these two ends 50 nm apart").  Each
# takes the per-nucleotide position list produced by ``production_rmsf`` (mean
# structure) or the OxDNA-display readback (single relaxed frame): a list of
# ``{helix_id, bp_index, direction, backbone_position:[x,y,z]}`` dicts.  A
# landmark is the ``(helix_id, bp_index, direction)`` key of one nucleotide
# (the addressing convention chosen for AF-13 — the raw geometry key, so no
# strand-polarity/terminus resolution is needed here).  Read-only over the
# Physical layer; nothing here writes a relaxed coordinate back into topology.

def _landmark_key(landmark) -> tuple:
    """Normalise a ``(helix_id, bp_index, direction)`` landmark to a hashable key.

    ``direction`` may arrive as a ``Direction`` enum or its string value; both
    map to the same key, matching the keys produced from a position map below.
    """
    hid, bp, direction = landmark
    return (hid, int(bp), getattr(direction, "value", direction))


def measure_end_to_end(positions, landmark_a, landmark_b) -> float:
    """Euclidean end-to-end distance (nm) between two landmark nucleotides'
    backbone sites in a relaxed/mean position map.

    ``positions`` is the per-nucleotide list from :func:`production_rmsf` (the
    noise-averaged mean structure — preferred) or the OxDNA display readback (a
    single relaxed frame).  ``landmark_a`` / ``landmark_b`` are
    ``(helix_id, bp_index, direction)`` keys.

    Raises ``ValueError`` on an empty map, an identical pair (a trivially-zero
    measurement), or a landmark absent from the map — so a mis-addressed or
    dropped landmark fails loudly rather than returning a silent 0/NaN.
    """
    if not positions:
        raise ValueError("measure_end_to_end: empty position map")
    lookup = {
        (p["helix_id"], int(p["bp_index"]),
         getattr(p["direction"], "value", p["direction"])): p["backbone_position"]
        for p in positions
    }
    ka, kb = _landmark_key(landmark_a), _landmark_key(landmark_b)
    if ka == kb:
        raise ValueError(
            f"measure_end_to_end: the two landmarks are identical ({ka}) — "
            "end-to-end distance would be trivially 0")
    for k in (ka, kb):
        if k not in lookup:
            raise ValueError(
                f"measure_end_to_end: landmark {k} is not a nucleotide of the "
                "position map")
    a = np.asarray(lookup[ka], dtype=float)
    b = np.asarray(lookup[kb], dtype=float)
    return float(np.linalg.norm(a - b))


def measure_radius_of_gyration(positions) -> float:
    """Radius of gyration (nm) of a relaxed/mean position map — the whole
    structure's overall compactness, ``sqrt(mean_i |r_i − r_cm|²)`` over every
    nucleotide's backbone site.

    Unlike :func:`measure_end_to_end` (two landmarks), R_g is a single scalar over
    ALL positions and so takes no landmarks — it captures global swelling/collapse
    that a point-pair distance cannot (a structure can hold its end-to-end while
    its bulk balloons).  ``positions`` is the per-nucleotide list from
    :func:`production_rmsf` (the noise-averaged mean structure — preferred) or the
    OxDNA display readback (a single relaxed frame).

    Raises ``ValueError`` on an empty map (so a dropped/empty readback fails loudly
    rather than returning a silent 0/NaN).
    """
    if not positions:
        raise ValueError("measure_radius_of_gyration: empty position map")
    pts = np.array(
        [np.asarray(p["backbone_position"], dtype=float) for p in positions])
    cm = pts.mean(axis=0)
    return float(np.sqrt(((pts - cm) ** 2).sum(axis=1).mean()))


def _backbone_lookup(positions):
    """{(helix_id, bp_index, direction): np.array backbone_position} for a
    production_rmsf-style / display position list."""
    return {
        (p["helix_id"], int(p["bp_index"]),
         getattr(p["direction"], "value", p["direction"])):
            np.asarray(p["backbone_position"], dtype=float)
        for p in positions
    }


def measure_segment_angle(positions, landmark_a, landmark_b, landmark_c) -> float:
    """Interior bend angle (DEGREES) at the middle landmark ``b`` of the three-point
    chain ``a — b — c`` in a relaxed/mean position map.

    The vertex is ``landmark_b``; the angle is the one between the two legs ``b→a``
    and ``b→c`` (``arccos((a−b)·(c−b) / (|a−b||c−b|))``).  Three collinear landmarks
    along a straight duplex give ~180°; a bend at ``b`` drops it below 180° in
    proportion to the curvature — so this is the natural measure for "how sharply is
    this segment kinked."  It is a pure **magnitude** (an ``arccos``), so it is
    direction-/handedness-agnostic — there is no sign or frame convention to get
    wrong (no Three-Layer ASK-FIRST concern).

    Unlike :func:`measure_end_to_end` / :func:`measure_radius_of_gyration` (both nm),
    this returns **degrees** — the first non-length constraint measure.  Each landmark
    is a ``(helix_id, bp_index, direction)`` key into ``positions`` (the per-nucleotide
    list from :func:`production_rmsf` or the display readback).

    Raises ``ValueError`` on an empty map, any landmark absent from the map, any two
    landmarks coinciding (a degenerate zero-length leg), or a leg of zero length — so
    a mis-addressed or collapsed measurement fails loudly rather than returning a
    silent 0/NaN.
    """
    if not positions:
        raise ValueError("measure_segment_angle: empty position map")
    lookup = _backbone_lookup(positions)
    ka = _landmark_key(landmark_a)
    kb = _landmark_key(landmark_b)
    kc = _landmark_key(landmark_c)
    if len({ka, kb, kc}) != 3:
        raise ValueError(
            f"measure_segment_angle: landmarks must be three distinct nucleotides, "
            f"got a={ka}, b={kb}, c={kc} — the angle would be degenerate")
    for k in (ka, kb, kc):
        if k not in lookup:
            raise ValueError(
                f"measure_segment_angle: landmark {k} is not a nucleotide of the "
                "position map")
    b = lookup[kb]
    leg_a = lookup[ka] - b      # b → a
    leg_c = lookup[kc] - b      # b → c
    na = float(np.linalg.norm(leg_a))
    nc = float(np.linalg.norm(leg_c))
    if na < 1e-12 or nc < 1e-12:
        raise ValueError(
            "measure_segment_angle: a leg has ~zero length — coincident landmarks")
    cos_theta = float(np.dot(leg_a, leg_c) / (na * nc))
    cos_theta = max(-1.0, min(1.0, cos_theta))      # guard arccos domain
    return float(np.degrees(np.arccos(cos_theta)))


def _fit_helix_axis(points):
    """Fit a straight axis line to a helix's backbone sites: return
    ``(centroid, unit_direction)``.

    The backbone sites spiral around the central axis at the backbone radius, so a
    plain centroid lands ON the axis (the spiral cancels over a turn) and the
    principal direction (largest singular vector of the centred points) is the axis
    direction.  Raises ``ValueError`` if the points are coincident (no axis to fit).
    """
    pts = np.asarray(points, dtype=float)
    centroid = pts.mean(axis=0)
    _, sv, vh = np.linalg.svd(pts - centroid, full_matrices=False)
    if sv[0] < 1e-9:
        raise ValueError(
            "_fit_helix_axis: backbone sites are coincident — no axis to fit")
    return centroid, vh[0]


def measure_inter_helix_spacing(positions, landmark_a, landmark_b) -> float:
    """Centre-to-centre spacing (nm) between the axes of the two helices named by
    ``landmark_a`` / ``landmark_b`` in a relaxed/mean position map.

    Unlike the point-landmark measures (:func:`measure_end_to_end`,
    :func:`measure_segment_angle`), this is the first measure that needs **helix-axis
    grouping**: each landmark only *identifies a helix* (via its ``helix_id``); ALL of
    that helix's backbone sites are gathered and a straight axis is fit to each
    (:func:`_fit_helix_axis`).  The spacing is then the separation of the two axis
    **centroids** measured *perpendicular to the common (mean) axis direction* — the
    radial gap, with the axial offset removed.

    This is deliberately NOT the minimal distance between the two infinite axis lines:
    two near-parallel helices with a slight relative tilt have infinite lines that
    nearly intersect far away (distance → 0), so that notion is fragile in exactly the
    near-parallel regime inter-helix spacing means.  Anchoring at the centroids and
    projecting out the common-axis component is exact for parallel helices and robust
    to the small tilts of a relaxed bundle.  It is a pure **magnitude** (a length), so
    it is direction-/handedness-agnostic — no sign or frame convention to get wrong.

    Returns nm (the field name ``target_nm``/``tol_nm`` is literal here, unlike the
    angular :func:`measure_segment_angle`).  Each landmark is a
    ``(helix_id, bp_index, direction)`` key into ``positions`` (the per-nucleotide
    list from :func:`production_rmsf` or the display readback).

    Raises ``ValueError`` on an empty map, a landmark absent from the map, two
    landmarks naming the SAME helix (spacing to itself is undefined), or a named helix
    with fewer than two nucleotides (no axis to fit) — so a mis-addressed measurement
    fails loudly rather than returning a silent 0/NaN.
    """
    if not positions:
        raise ValueError("measure_inter_helix_spacing: empty position map")
    lookup = _backbone_lookup(positions)
    ka = _landmark_key(landmark_a)
    kb = _landmark_key(landmark_b)
    for k in (ka, kb):
        if k not in lookup:
            raise ValueError(
                f"measure_inter_helix_spacing: landmark {k} is not a nucleotide of "
                "the position map")
    hid_a, hid_b = ka[0], kb[0]
    if hid_a == hid_b:
        raise ValueError(
            f"measure_inter_helix_spacing: both landmarks are on the same helix "
            f"({hid_a!r}) — inter-helix spacing needs two distinct helices")
    by_helix = {}
    for p in positions:
        by_helix.setdefault(p["helix_id"], []).append(
            np.asarray(p["backbone_position"], dtype=float))
    for hid in (hid_a, hid_b):
        if len(by_helix.get(hid, [])) < 2:
            raise ValueError(
                f"measure_inter_helix_spacing: helix {hid!r} has fewer than two "
                "nucleotides — cannot fit an axis")
    c_a, d_a = _fit_helix_axis(by_helix[hid_a])
    c_b, d_b = _fit_helix_axis(by_helix[hid_b])
    if float(np.dot(d_a, d_b)) < 0.0:           # PCA sign is arbitrary — align them
        d_b = -d_b
    mean_dir = d_a + d_b
    n = float(np.linalg.norm(mean_dir))
    mean_dir = d_a if n < 1e-9 else mean_dir / n
    w = c_b - c_a
    perp = w - float(np.dot(w, mean_dir)) * mean_dir    # drop the axial component
    return float(np.linalg.norm(perp))


def measure_field_response(
    field_positions,
    reference_positions,
    field_dir,
    anchor_keys,
    *,
    anchor_tol_nm: float = 1.0,
    min_free_proj_nm: float = 0.5,
) -> dict:
    """Quantify how a structure responded to an electric-field stage, vs a
    field-off reference — the anti-shovel oracle for the E-field feature.

    ``field_positions`` / ``reference_positions`` are per-nucleotide position
    lists (the :func:`production_rmsf` mean structure, or a display readback).
    ``anchor_keys`` is the iterable of anchored ``(helix_id, bp_index, direction)``
    keys (the parts pinned by traps); ``field_dir`` is the field direction.

    The verdict ``passed`` asserts a *physical property*, not an HTTP status: the
    anchored nucleotides barely moved (held by their traps, ≤ ``anchor_tol_nm``)
    AND the free nucleotides displaced, on average, ALONG the field direction
    (≥ ``min_free_proj_nm``).  It fails if the anchors didn't hold or the structure
    didn't deflect the right way.

    Returns ``{anchored_max_drift_nm, anchored_mean_drift_nm, free_mean_disp_nm,
    free_proj_along_field_nm, n_anchored, n_free, passed, reason}``.  Raises on a
    zero field direction or no free nucleotides to measure."""
    fmap = _backbone_lookup(field_positions)
    rmap = _backbone_lookup(reference_positions)
    fdir = np.asarray(field_dir, dtype=float)
    fnorm = float(np.linalg.norm(fdir))
    if fnorm <= 1e-9:
        raise ValueError("measure_field_response: field_dir is ~zero")
    fdir = fdir / fnorm
    anchor_set = {_landmark_key(tuple(k)[:3]) for k in anchor_keys}

    anchored_drifts: list[float] = []
    free_disps: list[float] = []
    free_projs: list[float] = []
    for key, fpos in fmap.items():
        if key not in rmap:
            continue
        disp = fpos - rmap[key]
        dist = float(np.linalg.norm(disp))
        if key in anchor_set:
            anchored_drifts.append(dist)
        else:
            free_disps.append(dist)
            free_projs.append(float(np.dot(disp, fdir)))

    if not free_disps:
        raise ValueError("measure_field_response: no free (non-anchored) nucleotides to measure")

    anchored_max = max(anchored_drifts) if anchored_drifts else 0.0
    anchored_mean = float(np.mean(anchored_drifts)) if anchored_drifts else 0.0
    free_mean = float(np.mean(free_disps))
    free_proj = float(np.mean(free_projs))

    held = anchored_max <= anchor_tol_nm
    deflected = free_proj >= min_free_proj_nm
    reasons = []
    if not held:
        reasons.append(f"anchors drifted {anchored_max:.2f} nm > {anchor_tol_nm} nm tol")
    if not deflected:
        reasons.append(f"free motion along field {free_proj:.2f} nm < {min_free_proj_nm} nm min")
    return {
        "anchored_max_drift_nm": anchored_max,
        "anchored_mean_drift_nm": anchored_mean,
        "free_mean_disp_nm": free_mean,
        "free_proj_along_field_nm": free_proj,
        "n_anchored": len(anchored_drifts),
        "n_free": len(free_disps),
        "passed": held and deflected,
        "reason": "; ".join(reasons) or "anchors held; structure deflected along the field",
    }


def measure_wall_response(
    positions,
    wall_dir,
    position_nm,
    *,
    penetration_tol_nm: float = 0.5,
) -> dict:
    """Quantify whether a structure stays on the allowed side of a hard surface —
    the anti-shovel oracle for the hard-surface feature.

    ``positions`` is a per-nucleotide position list (the :func:`production_rmsf`
    mean structure, or a display readback, in nm).  The plane is
    ``wall_dir·r + position_nm = 0`` with the structure confined to the
    ``wall_dir·r + position_nm >= 0`` side, so the per-nucleotide *clearance* is
    ``wall_dir·r + position_nm`` (≥ 0 = above the surface, < 0 = penetrating).

    The verdict ``passed`` asserts a *physical property*, not an HTTP status: no
    nucleotide penetrates the surface by more than ``penetration_tol_nm``.  Returns
    ``{min_clearance_nm, mean_clearance_nm, n_below, n_total, passed, reason}``.
    Raises on a zero wall direction or empty positions."""
    pmap = _backbone_lookup(positions)
    wdir = np.asarray(wall_dir, dtype=float)
    wnorm = float(np.linalg.norm(wdir))
    if wnorm <= 1e-9:
        raise ValueError("measure_wall_response: wall_dir is ~zero")
    wdir = wdir / wnorm
    if not pmap:
        raise ValueError("measure_wall_response: no nucleotides to measure")

    clearances = [float(np.dot(pos, wdir) + position_nm) for pos in pmap.values()]
    min_clear = min(clearances)
    mean_clear = float(np.mean(clearances))
    n_below = sum(1 for c in clearances if c < -penetration_tol_nm)
    passed = min_clear >= -penetration_tol_nm
    reason = (f"{n_below} nucleotide(s) penetrate the surface "
              f"(min clearance {min_clear:.2f} nm < -{penetration_tol_nm} nm)"
              if not passed else "all nucleotides rest on or above the surface")
    return {
        "min_clearance_nm": min_clear,
        "mean_clearance_nm": mean_clear,
        "n_below": n_below,
        "n_total": len(clearances),
        "passed": passed,
        "reason": reason,
    }


def field_response_from_confs(
    design,
    field_conf_path,
    reference_conf_path,
    *,
    field_dir,
    anchors=None,
    anchor_keys=None,
    **kw,
) -> dict:
    """:func:`measure_field_response` driven straight from two oxDNA configuration
    files — the reusable validation entry point for the E-field flow.

    ``field_conf_path`` is the configuration after the field stage; ``reference_conf_path``
    is the field-off (relaxed) configuration the field stage started from.  Pass
    either ``anchors`` (descriptors — resolved here to keys) or ``anchor_keys``
    directly.  Positions are the raw CM backbone positions (NOT Kabsch-aligned —
    aligning would remove the very field-driven motion we measure; the anchored
    region IS the common frame)."""
    from backend.physics.oxdna_interface import (
        read_configuration_full,
        resolve_anchor_particles,
    )

    if anchor_keys is None:
        _parts, anchor_keys = resolve_anchor_particles(design, anchors or [])

    def _to_positions(path):
        fm = read_configuration_full(path, design)
        return [{"helix_id": k[0], "bp_index": k[1], "direction": k[2],
                 "backbone_position": v["backbone_position"]} for k, v in fm.items()]

    return measure_field_response(
        _to_positions(field_conf_path), _to_positions(reference_conf_path),
        field_dir, anchor_keys, **kw)


# ── Declarative relaxed-structure constraints (AF-13 P3) ───────────────────────
# A constraint is a *declarative* statement about the relaxed structure, e.g.
# "the two ends are 50 nm ± 5 nm apart, certified by >= 50 pooled frames".  It
# slots into the AF-11 build-spec grammar as a design ``constraints`` block.
# ``parse_constraint_spec`` validates it (PURE, no oxDNA run) and
# ``check_relaxed_constraint`` *REPORTS* whether a relaxed output meets it — it
# does NOT assert (that is the oracle ``assert_relaxed_measurement``'s job).  The
# distinction matters: a closed-loop builder (AF-13 P4 iterate-until-met) needs a
# verdict to branch on, not a test that raises.  The load-bearing invariant is
# the confidence gate: ``met`` is NEVER True on an under-sampled run, even if the
# measured value happens to land within tolerance.  Physical-layer only.

class ConstraintSpecError(ValueError):
    """Raised when a declarative relaxed-structure constraint spec is malformed."""


_CONSTRAINT_MEASURES = frozenset(
    {"end_to_end", "radius_of_gyration", "segment_angle", "inter_helix_spacing"})
# How many landmarks each measure consumes.  0 = whole-structure (no landmarks).
# NB: target_nm/tol_nm carry the measure's native unit — nm for length measures
# (end_to_end, radius_of_gyration, inter_helix_spacing), DEGREES for the angular
# segment_angle (the field names are kept for backward compatibility).  For
# inter_helix_spacing the two landmarks each only NAME a helix (any nucleotide on
# it); the measure groups every site of that helix to fit its axis.
_MEASURE_LANDMARK_COUNT = {
    "end_to_end": 2, "radius_of_gyration": 0, "segment_angle": 3,
    "inter_helix_spacing": 2}
_CONSTRAINT_KEYS = frozenset(
    {"measure", "landmarks", "target_nm", "tol_nm", "min_confidence"})


def _validate_landmark(lm, *, which: str) -> tuple:
    if not isinstance(lm, (list, tuple)) or len(lm) != 3:
        raise ConstraintSpecError(
            f"constraint landmark {which} must be a (helix_id, bp_index, "
            f"direction) triple, got {lm!r}")
    hid, bp, direction = lm
    try:
        bp_int = int(bp)
    except (TypeError, ValueError):
        raise ConstraintSpecError(
            f"constraint landmark {which}: bp_index must be an integer, got {bp!r}")
    return (hid, bp_int, getattr(direction, "value", direction))


def _require_number(value, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise ConstraintSpecError(
            f"constraint {name} must be a finite number, got {value!r}")
    if positive and value <= 0:
        raise ConstraintSpecError(
            f"constraint {name} must be positive, got {value!r}")
    if not positive and value < 0:
        raise ConstraintSpecError(
            f"constraint {name} must be non-negative, got {value!r}")
    return float(value)


def _dispatch_measure(measure: str, positions, landmarks):
    """Compute the named relaxed-structure measure from a position map + the
    parsed (already-validated) landmark list.  Adding a new ``measure_*`` kind =
    add it to :data:`_CONSTRAINT_MEASURES` + :data:`_MEASURE_LANDMARK_COUNT` and a
    branch here."""
    if measure == "end_to_end":
        return measure_end_to_end(positions, landmarks[0], landmarks[1])
    if measure == "radius_of_gyration":
        return measure_radius_of_gyration(positions)
    if measure == "segment_angle":
        return measure_segment_angle(
            positions, landmarks[0], landmarks[1], landmarks[2])
    if measure == "inter_helix_spacing":
        return measure_inter_helix_spacing(positions, landmarks[0], landmarks[1])
    raise ConstraintSpecError(  # unreachable — parse pins the measure
        f"no measurement implemented for {measure!r}")


def parse_constraint_spec(spec) -> dict:
    """Validate + normalise a declarative relaxed-structure constraint (PURE — no
    execution, no oxDNA run).

    Shape::

        {"measure": "end_to_end", "landmarks": [a, b],
         "target_nm": 50, "tol_nm": 5, "min_confidence": 50}

    where each landmark is a ``(helix_id, bp_index, direction)`` key (``direction``
    a :class:`Direction` enum or its string value).  ``min_confidence`` is optional
    (defaults to :data:`RMSF_PRELIM_FRAMES`) — the minimum pooled production frames
    required before a ``met`` verdict can be certified.  Raises
    :class:`ConstraintSpecError` on any malformed field, so a bad constraint fails
    at parse time *before* any expensive relaxation runs.  Idempotent on its own
    normalised output.
    """
    if not isinstance(spec, dict):
        raise ConstraintSpecError(
            f"constraint spec must be a dict, got {type(spec).__name__}")
    unknown = set(spec) - _CONSTRAINT_KEYS
    if unknown:
        raise ConstraintSpecError(
            f"constraint spec has unknown key(s): {sorted(unknown)}")
    measure = spec.get("measure")
    if measure not in _CONSTRAINT_MEASURES:
        raise ConstraintSpecError(
            f"constraint measure must be one of {sorted(_CONSTRAINT_MEASURES)}, "
            f"got {measure!r}")
    n_landmarks = _MEASURE_LANDMARK_COUNT[measure]
    landmarks_in = spec.get("landmarks")
    if n_landmarks == 0:
        # Whole-structure measure (e.g. radius_of_gyration): no landmarks allowed.
        if landmarks_in:
            raise ConstraintSpecError(
                f"constraint '{measure}' takes no landmarks (it measures the whole "
                f"structure), got {landmarks_in!r}")
        landmarks = []
    else:
        if not isinstance(landmarks_in, (list, tuple)) \
                or len(landmarks_in) != n_landmarks:
            raise ConstraintSpecError(
                f"constraint '{measure}' needs exactly {n_landmarks} landmarks, "
                f"got {landmarks_in!r}")
        landmarks = [_validate_landmark(lm, which=chr(ord("a") + i))
                     for i, lm in enumerate(landmarks_in)]
        if len(set(landmarks)) != len(landmarks):
            raise ConstraintSpecError(
                f"constraint landmarks are identical ({landmarks[0]}) — the "
                "measurement is trivially 0")
    target = _require_number(spec.get("target_nm"), "target_nm")
    tol = _require_number(spec.get("tol_nm"), "tol_nm", positive=True)
    min_conf = spec.get("min_confidence", RMSF_PRELIM_FRAMES)
    if isinstance(min_conf, bool) or not isinstance(min_conf, int) or min_conf < 1:
        raise ConstraintSpecError(
            f"constraint min_confidence must be an integer >= 1, got {min_conf!r}")
    return {"measure": measure, "landmarks": landmarks, "target_nm": target,
            "tol_nm": tol, "min_confidence": int(min_conf)}


def check_relaxed_constraint(constraint, relaxed_output) -> dict:
    """REPORT (do not assert) whether a relaxed structure meets a declarative
    constraint — the AF-13 P3 reporter that AF-13 P4's iterate-until-met loop and
    the AF-11 grammar's ``constraints`` block consume.

    ``constraint`` is a constraint spec (raw or already parsed — it is normalised
    via :func:`parse_constraint_spec`).  ``relaxed_output`` is the dict returned by
    :func:`~backend.api.headless_oxdna_build.read_flexibility_map` (the production
    mean structure): ``{ready, positions, confidence:{n_frames,...}, ...}``.

    Returns ``{met, status, measured_nm, target_nm, tol_nm, n_frames,
    min_confidence, confidence}`` where ``status`` is one of:

    - ``"met"``          — ``n_frames >= min_confidence`` AND ``|measured −
      target| <= tol``;
    - ``"unmet"``        — enough frames pooled, BUT the measurement is out of
      tolerance;
    - ``"inconclusive"`` — too few frames pooled (or no production mean structure
      yet) to certify.  **The load-bearing guard: ``met`` is NEVER True here, even
      if the measured value is within tolerance — run a longer production.**

    The measured value is still reported when positions exist (so a closed loop
    can watch it converge), but ``met`` follows ``status`` strictly.
    *Physical-layer only*: reads relaxed geometry, never writes it back.
    """
    c = parse_constraint_spec(constraint)
    target, tol, min_conf = c["target_nm"], c["tol_nm"], c["min_confidence"]

    out = relaxed_output or {}
    confidence = out.get("confidence") or {}
    n_frames = confidence.get("n_frames")
    if n_frames is None:
        n_frames = out.get("n_frames", 0)
    n_frames = int(n_frames or 0)
    positions = out.get("positions") or []
    has_structure = bool(out.get("ready")) and bool(positions)

    measured = None
    if has_structure:
        measured = _dispatch_measure(c["measure"], positions, c["landmarks"])

    if not has_structure or n_frames < min_conf:
        status, met = "inconclusive", False
    elif abs(measured - target) <= tol:
        status, met = "met", True
    else:
        status, met = "unmet", False

    return {"met": met, "status": status, "measured_nm": measured,
            "target_nm": target, "tol_nm": tol, "n_frames": n_frames,
            "min_confidence": min_conf, "confidence": confidence}


# Reading + PBC-unwrapping + Kabsch-aligning a whole multi-stage trajectory is the
# dominant cost of EVERY trajectory request (≈14 s for a 199-frame 6hb).  The CG
# composite, each per-frame atomistic/surface fetch, and the audit all re-derived it
# from scratch — so scrubbing an atomistic trajectory paid it once PER frame.  The
# aligned frames depend only on the immutable stage/reference files, so memoize them
# keyed by a (path,size,mtime) signature: a completed job aligns once; a still-writing
# job's signature changes as files grow, so it re-aligns (stays live-correct).
_ALIGNED_CACHE = None   # lazily-created collections.OrderedDict[cache_key -> result]
_ALIGNED_CACHE_MAX = 6


def _aligned_cache_key(stages, reference_conf_path, max_frames, copies):
    import os
    sig = []
    for item in (*stages, ("__ref__", "", reference_conf_path)):
        path = item[2]
        try:
            st = os.stat(path)
            sig.append((str(path), st.st_size, st.st_mtime_ns))
        except OSError:
            sig.append((str(path), -1, -1))
    return (tuple(sig), int(max_frames), bool(copies))


def _aligned_downsampled_frames(design, stages, reference_conf_path, max_frames: int = 200,
                                *, copies: bool = False):
    """Shared core for the composite trajectory: read every stage's frames,
    PBC-unwrap + Kabsch-align each to the design reference, prepend the seed frame,
    and downsample per stage (≥1 each) to ≤ ``max_frames``.

    Returns ``(key_list, ordered_frames, out_stages, markers)`` where
    ``ordered_frames`` is the list of FULL per-nucleotide dicts (key →
    {backbone_position, a1, a3}) in composite-frame order — the same order the flat
    ``frames`` list uses. Used by ``composite_trajectory`` (flattens to CG floats,
    3-tuple keys) and by the per-frame atomistic/surface builders (which pass
    ``copies=True`` so loop-insertion copies carry their own relaxed rigid frame).

    Result is memoized by file signature (see ``_ALIGNED_CACHE``) — repeated frame
    requests for the same (completed) job reuse the alignment instead of redoing it.
    """
    global _ALIGNED_CACHE
    from collections import OrderedDict
    if _ALIGNED_CACHE is None:
        _ALIGNED_CACHE = OrderedDict()
    cache_key = _aligned_cache_key(stages, reference_conf_path, max_frames, copies)
    hit = _ALIGNED_CACHE.get(cache_key)
    if hit is not None:
        try:
            _ALIGNED_CACHE.move_to_end(cache_key)   # LRU touch (tolerate a concurrent evict)
        except KeyError:
            pass
        return hit

    from backend.physics.oxdna_interface import (
        _parse_box_nm,
        _strand_nucleotide_order,
        read_configuration_full,
        read_trajectory_frames_full,
        unwrap_align_to_reference,
    )
    ref = read_configuration_full(reference_conf_path, design, copies=copies)
    key_list = list(dict.fromkeys(k[:3] for k in _strand_nucleotide_order(design)))

    # A stage tuple is ``(name, kind, path)`` or ``(name, kind, path, marker_label)``.
    per_stage: list[dict] = []
    for item in stages:
        name, kind, path = item[0], item[1], item[2]
        marker_label = item[3] if len(item) > 3 else None
        frames = read_trajectory_frames_full(path, design, copies=copies)
        box = _parse_box_nm(path)
        aligned = [
            (unwrap_align_to_reference(fr, ref, design, box)
             if box is not None and np.all(box > 0) else fr)
            for fr in frames
        ]
        per_stage.append({"name": name, "kind": kind, "frames": aligned,
                          "marker_label": marker_label})

    # oxDNA's first trajectory write lands at print_conf_interval (not t=0); prepend
    # the seed configuration so the player starts on the true starting structure.
    for s in per_stage:
        if s["frames"]:
            s["frames"].insert(0, ref)
            break

    total = sum(len(s["frames"]) for s in per_stage)
    if total == 0:
        return key_list, [], [], []

    def _store(result):
        _ALIGNED_CACHE[cache_key] = result
        try:
            while len(_ALIGNED_CACHE) > _ALIGNED_CACHE_MAX:
                _ALIGNED_CACHE.popitem(last=False)   # evict oldest (tolerate concurrent pop)
        except KeyError:
            pass
        return result

    def _stride_pick(items: list, keep: int) -> list:
        if keep >= len(items) or keep <= 0:
            return items
        return [items[round(i * (len(items) - 1) / (keep - 1))] for i in range(keep)] \
            if keep > 1 else [items[0]]

    ordered_frames: list[dict] = []
    out_stages: list[dict] = []
    markers: list[dict] = []
    for s in per_stage:
        f = s["frames"]
        if not f:
            continue
        keep = max(1, round(len(f) * max_frames / total)) if total > max_frames else len(f)
        picked = _stride_pick(f, keep)
        if ordered_frames:  # a transition into this stage (skip the very first frame)
            markers.append({"frame": len(ordered_frames),
                            "label": s.get("marker_label") or f"→ {s['kind']}",
                            "kind": s["kind"], "stage_name": s["name"]})
        out_stages.append({"name": s["name"], "kind": s["kind"], "n_frames": len(picked)})
        ordered_frames.extend(picked)

    return _store((key_list, ordered_frames, out_stages, markers))


def _flatten_cg_frame(frame: dict, key_list) -> list:
    """Flatten one full per-nucleotide frame dict to the compact CG float list
    (backbone site x,y,z + a1 nx,ny,nz per key)."""
    from backend.physics.oxdna_interface import oxdna_backbone_site
    flat: list[float] = []
    for key in key_list:
        v = frame.get(key)
        if v is None:
            flat.extend((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            continue
        bb = oxdna_backbone_site(v["backbone_position"], v["a1"], v["a3"])
        a1 = v["a1"]
        flat.extend((float(bb[0]), float(bb[1]), float(bb[2]),
                     float(a1[0]), float(a1[1]), float(a1[2])))
    return flat


def composite_trajectory(
    design,
    stages,
    reference_conf_path,
    max_frames: int = 200,
) -> dict:
    """Build the composite scrub-able trajectory for the View-trajectory player.

    ``stages`` is an ordered list of ``(stage_name, kind, trajectory_path)`` —
    every stage that has written a ``trajectory.dat`` (relaxation stages + all
    production runs).  Each frame is PBC-unwrapped + Kabsch-aligned to the design
    reference (same as the OxDNA-display toggle) so the whole sequence plays in
    place.  Frames are downsampled PER STAGE (≥1 each) to keep the total ≤
    ``max_frames`` while preserving every stage boundary.

    Compact payload (keys sent once, each frame a flat float list) to keep the
    preload small:
      ``keys``   = [[helix_id, bp_index, direction], …]   (M nucleotides)
      ``frames`` = [[x,y,z,nx,ny,nz, … per key], …]        (backbone site + a1)
      ``stages`` = [{name, kind, n_frames}]
      ``markers``= [{frame, label, kind, stage_name}]      (transition at each
                   stage's first composite-frame; the very first frame is omitted)
    """
    key_list, ordered, out_stages, markers = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames)
    if not ordered:
        return {"n_frames": 0, "n_nucleotides": len(key_list),
                "keys": [list(k) for k in key_list], "frames": [],
                "stages": [], "markers": []}
    out_frames = [_flatten_cg_frame(fr, key_list) for fr in ordered]
    return {"n_frames": len(out_frames), "n_nucleotides": len(key_list),
            "keys": [list(k) for k in key_list], "frames": out_frames,
            "stages": out_stages, "markers": markers}


def _count_dat_frames(path) -> int:
    """Count configurations in an oxDNA trajectory .dat by its frame headers
    (each frame starts with a ``t = …`` line). Cheap — no coordinate parsing."""
    try:
        with open(path) as fh:
            return sum(1 for line in fh if line.startswith("t "))
    except OSError:
        return 0


def composite_trajectory_meta(design, stages, max_frames: int = 200) -> dict:
    """Lightweight metadata for the composite trajectory — ``{n_frames, markers,
    stages, n_nucleotides}`` — WITHOUT reading/aligning any coordinates. Replicates
    composite_trajectory's seed-prepend + per-stage downsample using only frame
    COUNTS, so n_frames + marker frame indices match the full composite exactly.
    Lets the trajectory-keyframe slider size itself in milliseconds instead of
    downloading the multi-MB trajectory."""
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    key_list = list(dict.fromkeys(k[:3] for k in _strand_nucleotide_order(design)))
    per_stage = []
    for item in stages:
        name, kind, path = item[0], item[1], item[2]
        marker_label = item[3] if len(item) > 3 else None
        per_stage.append({"name": name, "kind": kind,
                          "count": _count_dat_frames(path), "marker_label": marker_label})
    # Seed frame is prepended to the first non-empty stage (mirrors the composite).
    for s in per_stage:
        if s["count"] > 0:
            s["count"] += 1
            break

    total = sum(s["count"] for s in per_stage)
    if total == 0:
        return {"n_frames": 0, "n_nucleotides": len(key_list), "stages": [], "markers": []}

    out_n = 0
    out_stages: list[dict] = []
    markers: list[dict] = []
    for s in per_stage:
        c = s["count"]
        if c <= 0:
            continue
        keep = max(1, round(c * max_frames / total)) if total > max_frames else c
        if out_n:
            markers.append({"frame": out_n, "label": s.get("marker_label") or f"→ {s['kind']}",
                            "kind": s["kind"], "stage_name": s["name"]})
        out_stages.append({"name": s["name"], "kind": s["kind"], "n_frames": keep})
        out_n += keep
    return {"n_frames": out_n, "n_nucleotides": len(key_list),
            "stages": out_stages, "markers": markers}


def _frame_atomistic_overrides(design, frame: dict):
    """Build (nuc_pos_override, axis_override) for one relaxed/trajectory frame.

    Positions each nucleotide at its true backbone site reconstructed from the oxDNA
    CM (``oxdna_backbone_site``), and supplies a Gaussian-smoothed DEFORMED helix
    centerline so the all-atom base orientation is derived against the BENT axis
    (``_atom_frame`` measures the radial vs the centerline) — the validated
    reconstruction the NAMD-seed path uses.

    NOTE — why NOT the per-nucleotide oxDNA a1/a3 rigid-frame placer: that placer
    (``build_atomistic_model(frame_override=…)``, the 2026-06-21 first cut) collapsed
    base pairs on real relaxed frames (WC C1'–C1' 0.48 nm vs 0.94 nm here) because
    oxDNA's relaxed a1 does not map onto the all-atom base direction the calibration
    assumed.  The axis-derived path below reproduces correct B-DNA pairing/stacking,
    so DISPLAY uses it; the long sequential O3'→P bonds are handled separately by
    ``close_backbone=True`` (display-only backbone closure), which made the σ
    per-domain position smoother (a prior band-aid) unnecessary."""
    from backend.physics.oxdna_interface import oxdna_backbone_site
    from backend.core.cg_to_atomistic import deformed_helix_axes
    # Collapse loop-insertion copies to their 3-tuple base (last copy wins) — both the
    # backbone-site override and deformed_helix_axes are keyed by (helix, bp, dir).
    frame3 = {key[:3]: rec for key, rec in frame.items()
              if rec.get("backbone_position") is not None
              and rec.get("a1") is not None and rec.get("a3") is not None}
    nuc_pos_override = {
        key: oxdna_backbone_site(rec["backbone_position"], rec["a1"], rec["a3"])
        for key, rec in frame3.items()
    }
    axis_override = deformed_helix_axes(design, frame3, sigma=2.0)
    return nuc_pos_override, axis_override


def build_display_model(design, frame: dict):
    """The canonical relaxed-frame DISPLAY reconstruction — ONE builder shared by the
    atomistic/surface display sinks AND the validation audit, so what's measured is
    exactly what's drawn.  Axis-derived base placement (correct WC pairing/stacking)
    + display-only backbone closure (connected O3'→P).  Atom serial ordering is
    identical to ``build_atomistic_model(design)`` (overrides change positions, never
    topology), so the renderer's serial-keyed bond list stays valid."""
    from backend.core.atomistic import build_atomistic_model
    nuc_pos_override, axis_override = _frame_atomistic_overrides(design, frame)
    return build_atomistic_model(
        design, nuc_pos_override=nuc_pos_override, axis_override=axis_override,
        close_backbone=True, relaxed_oxdna_phase=True)


def frame_atomistic_flat(design, frame: dict) -> list:
    """Atomistic flat-XYZ (atom-serial order, nm) for ONE per-nucleotide frame
    ``{key: {backbone_position(CM), a1, a3}}`` — the SAME wire format as
    ``/design/features/atomistic-batch``. Shared sink for the composite trajectory
    AND the single relaxed-display / rmsf-average frames."""
    from backend.core.atomistic import atomistic_positions_flat
    return atomistic_positions_flat(build_display_model(design, frame))


def frame_surface_json(design, frame: dict, color_mode: str = "strand",
                       probe_radius: float = 0.28, grid_spacing: float = 0.20,
                       radius_inflate: float = 1.30, smooth: int = 15) -> dict:
    """Molecular surface ``{vertices, faces, vertex_colors?}`` for ONE per-nucleotide
    frame — the SAME wire format as ``/design/features/surface-batch``. Shared sink
    for the composite trajectory AND the single relaxed/rmsf frames."""
    from backend.core.surface import compute_surface, smooth_mesh, surface_to_json
    model = build_display_model(design, frame)
    mesh = compute_surface(model.atoms, grid_spacing=grid_spacing,
                           probe_radius=probe_radius, radius_scale=1.2 * radius_inflate)
    mesh = smooth_mesh(mesh, iterations=smooth)
    entry = {"vertices": [round(float(v), 5) for v in mesh.vertices.ravel()],
             "faces": [int(f) for f in mesh.faces.ravel()]}
    if color_mode == "strand":
        vc = surface_to_json(mesh, design, color_mode="strand").get("vertex_colors")
        if vc:
            entry["vertex_colors"] = [round(float(c), 4) for c in vc]
    return entry


def composite_trajectory_atomistic(design, stages, reference_conf_path,
                                   frame_indices, max_frames: int = 200) -> dict:
    """Per-frame atomistic flat-XYZ for the requested composite-frame indices.
    Returns ``{ "<idx>": [x0,y0,z0, …] }`` — the SAME wire format as
    ``/design/features/atomistic-batch`` (atom-serial order, nm). Frame indices
    match ``composite_trajectory``'s ``frames`` ordering exactly."""
    _, ordered, _, _ = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames, copies=True)
    out: dict[str, list] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= len(ordered):
            continue
        out[str(idx)] = frame_atomistic_flat(design, ordered[idx])
    return out


def composite_trajectory_surface(design, stages, reference_conf_path, frame_indices,
                                 color_mode: str = "strand", probe_radius: float = 0.28,
                                 grid_spacing: float = 0.20, radius_inflate: float = 1.30,
                                 smooth: int = 15, max_frames: int = 200) -> dict:
    """Per-frame molecular surface for the requested composite-frame indices.
    Returns ``{ "<idx>": {vertices, faces, vertex_colors?} }`` — the SAME wire
    format as ``/design/features/surface-batch``. Topology can vary per frame
    (marching cubes); the frontend rebuilds the buffer on a count change."""
    _, ordered, _, _ = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames, copies=True)
    out: dict[str, dict] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= len(ordered):
            continue
        out[str(idx)] = frame_surface_json(
            design, ordered[idx], color_mode, probe_radius, grid_spacing,
            radius_inflate, smooth)
    return out


def max_backbone_stretch(
    design: Design,
    full_map: dict[tuple[str, int, str], dict],
    *,
    clash_nm: float = BACKBONE_CLASH_NM,
) -> tuple[float, int]:
    """Return (max backbone-bond length in nm, count of bonds over *clash_nm*)."""
    pairs = backbone_bond_pairs(design)
    max_d = 0.0
    n_clash = 0
    for a, b in pairs:
        pa = full_map.get(a)
        pb = full_map.get(b)
        if pa is None or pb is None:
            continue
        d = float(np.linalg.norm(pa["backbone_position"] - pb["backbone_position"]))
        if d > max_d:
            max_d = d
        if d > clash_nm:
            n_clash += 1
    return (max_d, n_clash)


def backbone_fene_stretch(
    design: Design,
    full_map: dict[tuple[str, int, str], dict],
    *,
    rmax_units: float = FENE_RMAX_UNITS,
) -> tuple[float, int]:
    """Return (longest backbone-bond length in oxDNA units, count over *rmax_units*).

    Measures the distance between the reconstructed BACKBONE SITES of consecutive
    bonded nucleotides — the exact quantity oxDNA's FENE term checks — so the result
    predicts whether a bare-FENE (uncapped) stage will abort at config load.  This is
    distinct from ``max_backbone_stretch`` (CM–CM distance, in nm), which sits inward
    of the real backbone and badly under-reads the bond length.
    """
    pairs = backbone_bond_pairs(design)
    max_u = 0.0
    n_over = 0
    for a, b in pairs:
        pa = full_map.get(a)
        pb = full_map.get(b)
        if pa is None or pb is None:
            continue
        sa = oxdna_backbone_site(pa["backbone_position"], pa["a1"], pa["a3"])
        sb = oxdna_backbone_site(pb["backbone_position"], pb["a1"], pb["a3"])
        d_units = float(np.linalg.norm(sa - sb)) / OXDNA_LENGTH_UNIT
        if d_units > max_u:
            max_u = d_units
        if d_units >= rmax_units:
            n_over += 1
    return (max_u, n_over)


# ── top-level stage health check ──────────────────────────────────────────────


def run_oxdna_health_check(
    design:          Design,
    stage_dir:       Path,
    *,
    kind:            str,
    min_bp_retained: float,
    topology_path:   Path | None = None,
    dnanalysis_bin:  str | None = None,
    salt_concentration: float = 0.5,
    temperature:     str = "296K",
) -> OxdnaHealthResult:
    """Evaluate a finished stage's health from its ``last_conf.dat`` + ``energy.dat``.

    *kind* is the stage kind ("mc" / "md_relax" / "equil" / "production").  The mc
    stage gates on clash resolution only (no bp gate); the rest gate on base-pair
    retention.

    Base-pair retention is taken from oxDNA's own ``HBList`` observable (the
    ground-truth energy-based H-bond count) when ``dnanalysis_bin`` +
    ``topology_path`` are available, falling back to the geometric proxy
    (``base_pair_retention``) otherwise.
    """
    res = OxdnaHealthResult()
    conf = stage_dir / "last_conf.dat"
    if not conf.exists():
        res.passed = False
        res.error = f"last_conf.dat not found in {stage_dir.name}"
        res.reason = res.error
        return res

    try:
        full_map = read_configuration_full(conf, design)
    except Exception as exc:  # noqa: BLE001
        res.passed = False
        res.error = f"failed to read {conf.name}: {exc}"
        res.reason = res.error
        return res

    # Designed WC pair count (geometric — also the denominator for retention).
    geo_frac, n_pairs = base_pair_retention(design, full_map)
    res.n_pairs = n_pairs

    # Prefer oxDNA's own HBList (ground truth); fall back to the geometric proxy.
    frac = geo_frac
    if dnanalysis_bin and topology_path and n_pairs > 0:
        n_hb = count_hbonds(conf, topology_path, dnanalysis_bin,
                            salt_concentration=salt_concentration, temperature=temperature)
        if n_hb is not None:
            frac = min(n_hb, n_pairs) / n_pairs
    res.bp_retained_fraction = frac

    max_d, n_clash = max_backbone_stretch(design, full_map)
    res.max_backbone_stretch = max_d
    res.n_clashes = n_clash

    # FENE equil-readiness (site-based, oxDNA units): does an uncapped next stage risk
    # aborting at config load?  Advisory — surfaced in the reason + used by the runner
    # to escalate-and-retry the relax; it does NOT set ``passed`` (a capped equil is
    # robust to a residual over-stretch).
    max_fene, n_fene = backbone_fene_stretch(design, full_map)
    res.max_backbone_fene_units = max_fene
    res.n_fene_over = n_fene
    res.fene_safe = max_fene < FENE_SAFE_MAX_UNITS

    samples = parse_energy_dat(stage_dir / "energy.dat")
    if samples:
        res.potential_energy = samples[-1][1]
        res.energy_converged = energy_is_converged(samples)
        if not math.isfinite(res.potential_energy):
            res.passed = False
            res.reason = "potential energy is non-finite (simulation blew up)"
            return res

    # Gate.
    if kind == "mc":
        # MC relaxation only needs to clear gross clashes; no base-pair gate yet.
        res.passed = True
        res.reason = f"clash bonds={n_clash}, max stretch={max_d:.2f} nm"
    else:
        if frac < min_bp_retained:
            res.passed = False
            res.reason = (
                f"base-pair retention {frac:.0%} below gate {min_bp_retained:.0%}"
            )
        else:
            res.passed = True
            res.reason = f"base-pair retention {frac:.0%}"
            if not res.fene_safe:
                res.reason += (
                    f"; {n_fene} backbone bond(s) over-stretched "
                    f"(max {max_fene:.3f} units, FENE cliff {FENE_RMAX_UNITS:.3f}) — "
                    f"not equil-ready"
                )
    return res
