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
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.core.constants import OXDNA_LENGTH_UNIT
from backend.core.models import Design
from backend.physics.oxdna_interface import (
    backbone_bond_pairs,
    count_hbonds,
    is_synthetic_nuc_key,
    oxdna_backbone_site,
    oxdna_backbone_sites,
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

# Display reconstruction may still use the common duplex-axis placer for a loose,
# distorted pair outside the strict hydrogen-bond cutoff.  Beyond this much wider
# separation there is no meaningful shared helix axis: averaging the two strands
# invents positions unrelated to either oxDNA particle.  Kept separate from the
# health metric above because its purpose is geometric reconstruction, not claiming
# that a hydrogen bond remains formed.
DUPLEX_AXIS_MAX_BASE_SEPARATION_NM: float = 2.0

# oxDNA's hydrogen-bond equilibrium separation between the two BASE sites of a
# Watson–Crick pair (model.h HYDR_R0), in oxDNA units.  A relaxed pair sits here;
# a stretched/opening pair reads longer, an over-compressed one shorter.  This is
# the WC counterpart of FENE_R0_OXDNA2 below and the reference for the ``wc``
# strain metric (see :func:`strain_map`).
HYDR_R0_OXDNA2: float = 0.4

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
    copies: bool = False,
    align: bool = True,
    n_trailing_extra: int = 0,
    trailing_extra_strand_length: int = 0,
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
    # copies=True keeps each loop-insertion copy under its own 4-tuple key so the
    # flexibility/deviation maps carry a per-copy value instead of collapsing them.
    ref = read_configuration_full(
        reference_conf_path, design, copies=copies, n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)
    paths = (list(production_traj_path)
             if isinstance(production_traj_path, (list, tuple))
             else [production_traj_path])

    acc: dict[tuple, dict] = {}   # key → {"pos": [bb xyz...], "a1": [a1...]}
    n_frames = 0
    for path in paths:
        frames = read_trajectory_frames_full(
            path, design, copies=copies, n_trailing_extra=n_trailing_extra,
            trailing_extra_strand_length=trailing_extra_strand_length)
        box = _parse_box_nm(path)
        for fr in frames:
            aligned = (unwrap_align_to_reference(fr, ref, design, box, align=align)
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
    for key, slot in acc.items():
        hid, bp, direction = key[0], key[1], key[2]
        copy = key[3] if len(key) == 4 else 0   # loop-copy index (0 for plain nucleotides)
        P = np.array(slot["pos"])                      # (F, 3)
        mean_pos = P.mean(axis=0)
        rmsf = float(np.sqrt(((P - mean_pos) ** 2).sum(axis=1).mean()))
        a1m = np.array(slot["a1"]).mean(axis=0)
        a1m = a1m / (np.linalg.norm(a1m) + 1e-14)
        positions.append({
            "helix_id": hid, "bp_index": bp, "direction": direction, "copy": copy,
            "backbone_position": mean_pos.tolist(),
            "nx": float(a1m[0]), "ny": float(a1m[1]), "nz": float(a1m[2]),
            "rmsf": rmsf,
        })
        rmsfs.append(rmsf)
        if include_average_frame:
            cmm = np.array(slot["cm"]).mean(axis=0)
            a3m = np.array(slot["a3"]).mean(axis=0)
            a3m = a3m / (np.linalg.norm(a3m) + 1e-14)
            average_frame[key] = {
                "backbone_position": cmm, "a1": a1m, "a3": a3m,
            }

    r = np.array(rmsfs)
    out = {"ready": True, "n_frames": n_frames, "positions": positions,
           "min_rmsf": float(r.min()), "max_rmsf": float(r.max()),
           "mean_rmsf": float(r.mean())}
    if include_average_frame:
        out["average_frame"] = average_frame
    return out


# RMSF is expensive on large jobs because every trajectory frame is parsed,
# unwrapped, aligned, and accumulated. The user necessarily computes this once
# to view the flexibility map; retain that exact result (including the average
# orientation frame needed by PDB export) so export does not repeat the work.
_PRODUCTION_RMSF_CACHE = None
_PRODUCTION_RMSF_CACHE_MAX = 4


def production_rmsf_cached(design, production_traj_path, reference_conf_path,
                           *, copies: bool = False, align: bool = True,
                           n_trailing_extra: int = 0,
                           trailing_extra_strand_length: int = 0) -> dict:
    """LRU-cached :func:`production_rmsf` including its average reconstruction frame.

    File size+mtime signatures naturally invalidate running trajectories as they
    grow. Completed trajectories reuse the same calculation across RMSF display,
    deviation display, atomistic display, and PDB export.
    """
    global _PRODUCTION_RMSF_CACHE
    from collections import OrderedDict

    paths = (list(production_traj_path)
             if isinstance(production_traj_path, (list, tuple))
             else [production_traj_path])
    key = (tuple(_traj_file_sig(p) for p in paths), _traj_file_sig(reference_conf_path),
           bool(copies), bool(align), int(n_trailing_extra),
           int(trailing_extra_strand_length))
    if _PRODUCTION_RMSF_CACHE is not None:
        cached = _PRODUCTION_RMSF_CACHE.get(key)
        if cached is not None:
            _PRODUCTION_RMSF_CACHE.move_to_end(key)
            return cached
    result = production_rmsf(
        design, paths, reference_conf_path, include_average_frame=True, copies=copies,
        align=align, n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)
    if _PRODUCTION_RMSF_CACHE is None:
        _PRODUCTION_RMSF_CACHE = OrderedDict()
    _PRODUCTION_RMSF_CACHE[key] = result
    _PRODUCTION_RMSF_CACHE.move_to_end(key)
    while len(_PRODUCTION_RMSF_CACHE) > _PRODUCTION_RMSF_CACHE_MAX:
        _PRODUCTION_RMSF_CACHE.popitem(last=False)
    return result


def twist_series_stats(series) -> dict:
    """Mean + correlation-corrected sampling error of a per-frame scalar time series.

    A production trajectory's frames are NOT independent: a slow collective mode (e.g. a long
    bundle's global twist) decorrelates over an integrated autocorrelation time ``tau_int`` of
    many frames, so the naive ``std/sqrt(N)`` badly UNDER-states the error.  This returns the
    honest version:

      ``tau_int = 1 + 2·Σ_{t≥1} rho(t)``  (rho = normalised autocovariance, summed up to the
      first non-positive lag — the standard automatic window), ``N_eff = N / tau_int`` effectively
      independent samples, and ``sem = std / sqrt(N_eff)``.

    ``N_eff`` is the key diagnostic: if ``N_eff`` is only a handful despite hundreds of frames,
    the slow mode is under-sampled and a LONGER run (or more seeds) is needed; if ``N_eff`` ≈ N,
    the frames are effectively independent and the run length is fine.  Returns
    ``{n, mean, std, tau_int, n_eff, sem}``.
    """
    a = np.asarray(series, dtype=float)
    n = int(a.size)
    if n < 2:
        m = float(a.mean()) if n else 0.0
        return {"n": n, "mean": m, "std": 0.0, "tau_int": 1.0, "n_eff": float(n), "sem": 0.0}
    mean = float(a.mean())
    d = a - mean
    var = float((d * d).mean())
    if var <= 0.0:                                  # constant series → fully correlated-free
        return {"n": n, "mean": mean, "std": 0.0, "tau_int": 1.0, "n_eff": float(n), "sem": 0.0}
    tau = 1.0
    for t in range(1, n):
        rho = float((d[:-t] * d[t:]).mean()) / var
        if rho <= 0.0:                              # automatic windowing at first zero-crossing
            break
        tau += 2.0 * rho
    tau = max(1.0, tau)
    n_eff = n / tau
    std = var ** 0.5
    return {"n": n, "mean": mean, "std": std, "tau_int": tau,
            "n_eff": n_eff, "sem": std / (n_eff ** 0.5)}


def detect_equilibration(series, *, min_remaining: int = 20) -> dict:
    """Automatic equilibration / burn-in detection (Chodera, *JCTC* 2016): pick the discard
    cutoff ``t0`` that MAXIMISES the effective sample count ``N_eff`` of the kept tail
    ``series[t0:]``.

    A production trajectory often opens with a monotonic TRANSIENT (e.g. a freshly-built bundle
    relaxing its over-wound global twist) before it reaches the stationary fluctuating regime.
    Including that ramp biases the mean AND inflates the integrated autocorrelation time (a drift
    reads as a long τ), so the honest estimate discards it.  Keeping the transient lowers N_eff
    (high τ); the cutoff that maximises N_eff sits just after equilibration — so this finds the
    burn-in automatically with no hand-tuned threshold.

    Returns ``{t0, n_eff, stats}`` where ``stats = twist_series_stats(series[t0:])``.  ``t0`` is a
    FRAME index (multiply by steps-per-frame for physical burn-in length).
    """
    a = np.asarray(series, dtype=float)
    n = a.size
    if n < min_remaining + 2:
        st = twist_series_stats(series)
        return {"t0": 0, "n_eff": st["n_eff"], "stats": st}
    step = max(1, n // 200)                          # coarse scan — n is ≤ a few thousand frames
    best_t0, best_neff, best_stats = 0, -1.0, None
    for t0 in range(0, n - min_remaining, step):
        st = twist_series_stats(a[t0:])
        if st["n_eff"] > best_neff:
            best_t0, best_neff, best_stats = t0, st["n_eff"], st
    return {"t0": best_t0, "n_eff": best_neff, "stats": best_stats}


def production_twist_series(
    design,
    production_traj_path,
    reference_conf_path,
    analytic_reference,
    *,
    n_slices: int = 0,
) -> dict:
    """Per-FRAME differential bundle twist over a production trajectory, vs the single value
    measured on the time-AVERAGE structure.

    The flexibility-map path (:func:`production_rmsf`) averages each nucleotide's POSITION over
    frames and then measures twist on that one mean structure.  Averaging the positions of a
    fluctuating helix pulls every site toward its mean (a "shrinkage" that can bias a twist
    measure), AND collapses the whole run to a single number with no error bar.  This instead
    measures twist on EACH frame (differential sim − analytic, the same quantity the steering
    uses) and returns the time series + its correlation-corrected statistics
    (:func:`twist_series_stats`), so we can (a) compare the two estimators and (b) see how many
    effectively-independent twist samples an 8M run actually contains.

    Mirrors ``production_rmsf``'s frame handling (PBC-unwrap + Kabsch-align each frame, backbone
    site, pooled across a list of trajectory paths).  Returns ``{n_frames, analytic_twist,
    twist_per_frame, twist_on_mean_structure, stats}`` (``stats`` is over the per-frame
    differential series).  ``ready=False`` if no frames or fewer than two helices.
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
    analytic_twist = measure_bundle_twist(analytic_reference, n_slices=n_slices)

    per_frame: list[float] = []
    acc: dict[tuple, list] = {}                     # key → [bb xyz, …] for the mean-structure twist
    n_frames = 0
    for path in paths:
        frames = read_trajectory_frames_full(path, design)
        box = _parse_box_nm(path)
        for fr in frames:
            aligned = (unwrap_align_to_reference(fr, ref, design, box)
                       if box is not None and np.all(box > 0) else fr)
            frame_positions = []
            for k, v in aligned.items():
                bb = oxdna_backbone_site(v["backbone_position"], v["a1"], v["a3"])
                frame_positions.append({"helix_id": k[0], "bp_index": k[1], "direction": k[2],
                                        "backbone_position": bb})
                acc.setdefault(k, []).append(bb)
            core = _filter_to_reference_core(frame_positions, analytic_reference)
            try:
                per_frame.append(measure_bundle_twist(core, n_slices=n_slices) - analytic_twist)
            except ValueError:
                continue                            # degenerate frame (too few helices) — skip
            n_frames += 1

    if n_frames == 0 or not per_frame:
        return {"ready": False, "n_frames": 0, "twist_per_frame": [],
                "twist_on_mean_structure": None, "analytic_twist": analytic_twist, "stats": None}

    mean_positions = [{"helix_id": k[0], "bp_index": k[1], "direction": k[2],
                       "backbone_position": np.mean(v, axis=0)} for k, v in acc.items()]
    mean_core = _filter_to_reference_core(mean_positions, analytic_reference)
    twist_on_mean = measure_bundle_twist(mean_core, n_slices=n_slices) - analytic_twist
    return {"ready": True, "n_frames": n_frames, "analytic_twist": analytic_twist,
            "twist_per_frame": [round(t, 3) for t in per_frame],
            "twist_on_mean_structure": round(twist_on_mean, 3),
            "stats": twist_series_stats(per_frame),
            "equilibrated": detect_equilibration(per_frame)}


# path -> {size, reported, offset, count, anchor}: an INCREMENTAL frame-count memo.
#   offset   byte position of the last line boundary already counted
#   count    frames strictly before `offset`
#   anchor   the bytes just before `offset` — proves the prefix we counted is unchanged
#   size     file size when `reported` was last computed (stat-only fast path)
_COUNT_CACHE: dict = {}
_COUNT_CACHE_MAX = 512
_COUNT_CHUNK = 1 << 20           # 1 MiB scan chunk
_COUNT_ANCHOR = 4096             # bytes of counted-prefix kept to detect a rewrite


def _scan_frames(fh, start: int, count: int) -> tuple[int, int, bytes]:
    """Count ``t `` frame headers from byte *start* to EOF, resuming at *count*.

    Returns ``(frames_before_boundary, boundary_offset, trailing_partial_line)``.
    The trailing fragment (a line with no terminating newline — the frame oxDNA is
    still writing) is deliberately left uncounted at the boundary so the next
    incremental scan can resume on a clean line edge."""
    fh.seek(start)
    pos, n, tail = start, count, b""
    while True:
        chunk = fh.read(_COUNT_CHUNK)
        if not chunk:
            break
        buf = tail + chunk           # buf begins at byte `pos`
        lines = buf.split(b"\n")
        tail = lines.pop()           # possibly-truncated final line
        n += sum(1 for ln in lines if ln.startswith(b"t "))
        pos += len(buf) - len(tail)
    return n, pos, tail


def count_trajectory_frames(traj_path) -> int:
    """Fast, memory-light frame count of an oxDNA ``.dat`` trajectory — the number of
    ``t = …`` header lines (frames are split on those, see
    ``read_trajectory_frames_full``).  Streams the file in chunks so a multi-GB
    trajectory isn't materialised; used to size the metric-compute progress bar/ETA
    without paying the full per-nucleotide parse twice.

    **Incrementally memoized.**  The composite-trajectory build counts every ancestor
    stage's frames on EVERY load (to size the per-stage stride), and the export card
    re-asks whenever the panel re-renders — so re-streaming a multi-hundred-MB file per
    call was pinning the backend at ~500 MB/s while a job ran (it starved oxDNA's CUDA
    host thread and pushed every other request past the frontend's slow-request popup).
    Unchanged size → stat-only hit.  A file that has GROWN is scanned only over its new
    tail, so the live stage's still-growing trajectory costs one chunk per poll instead
    of a full re-read.  Truncation, or a rewrite that changed the bytes before the
    resume point (a restarted stage rewinds to ``t = 0``), falls back to a full recount."""
    from pathlib import Path
    p = Path(traj_path)
    try:
        size = p.stat().st_size
    except OSError:
        return 0
    if size <= 0:
        return 0
    key = str(p)
    ent = _COUNT_CACHE.get(key)
    if ent is not None and ent["size"] == size:
        return ent["reported"]
    try:
        with p.open("rb") as fh:
            start, base = 0, 0
            if ent is not None and 0 < ent["offset"] <= size:
                # Resume only if the prefix we already counted is byte-identical.
                a0 = max(0, ent["offset"] - _COUNT_ANCHOR)
                fh.seek(a0)
                if fh.read(ent["offset"] - a0) == ent["anchor"]:
                    start, base = ent["offset"], ent["count"]
            n, pos, tail = _scan_frames(fh, start, base)
            # A dangling header with no newline yet is reported (parity with a plain
            # line-wise count) but NOT committed to the resume point.
            reported = n + (1 if tail.startswith(b"t ") else 0)
            fh.seek(max(0, pos - _COUNT_ANCHOR))
            anchor = fh.read(pos - max(0, pos - _COUNT_ANCHOR))
    except OSError:
        return 0
    _COUNT_CACHE[key] = {"size": size, "reported": reported,
                         "offset": pos, "count": n, "anchor": anchor}
    if len(_COUNT_CACHE) > _COUNT_CACHE_MAX:
        _COUNT_CACHE.pop(next(iter(_COUNT_CACHE)), None)   # drop oldest (insertion order)
    return reported


def differential_profile(sim_profile, analytic_profile):
    """``sim − analytic`` of two cumulative profiles that share a shape but NOT their exact
    sample positions.  The spatial profiles (:func:`measure_bundle_twist_profile`,
    :func:`measure_bundle_curvature_profile`) are meant to be read DIFFERENTIALLY, but the
    simulated mean and the analytic reference have different slab centres (different
    nucleotide sets), so a plain element-wise subtract is ill-defined.  Both are normalised
    to a 0..1 axial parameter over their own span, the analytic curve is linearly
    interpolated onto the sim's sample points, and subtracted — returning
    ``[(sim_axial_t_nm, sim_val − analytic_val), …]``.  Empty ``analytic_profile`` → the sim
    profile unchanged (no reference to subtract)."""
    sim = [(float(t), float(v)) for t, v in sim_profile]
    if not sim:
        return []
    ana = [(float(t), float(v)) for t, v in analytic_profile]
    if not ana:
        return sim
    st = np.array([t for t, _ in sim]); sv = np.array([v for _, v in sim])
    at = np.array([t for t, _ in ana]); av = np.array([v for _, v in ana])

    def _norm(x):
        lo, hi = float(x.min()), float(x.max())
        return (x - lo) / (hi - lo) if hi - lo > 1e-9 else np.zeros_like(x)

    sn, an = _norm(st), _norm(at)
    # np.interp needs ascending xp; the analytic profile's normalised t is monotone by span.
    order = np.argsort(an)
    interp = np.interp(sn, an[order], av[order])
    return [(round(float(t), 3), round(float(s - i), 3)) for t, s, i in zip(st, sv, interp)]


def base_pairing_spatial_profile(per_pair_formed_frac, mean_positions, *, n_slices: int = 0):
    """Fraction-of-pairs-formed vs axial position ``[(axial_t_nm, fraction), …]`` — localises
    WHERE a bundle melts (ends fray first, core holds), the spatial companion to the per-frame
    base-pairing series.  ``per_pair_formed_frac`` maps ``(helix_id, bp_index) → fraction of
    frames that pair was H-bonded`` (from :func:`base_pair_retention`'s formed test accumulated
    over the trajectory); ``mean_positions`` is the time-averaged per-nucleotide structure used
    only to place each pair on the bundle axis.  Bins pairs into ~1-turn axial slabs (same
    machinery as the twist/curvature profiles) and averages the formed fraction per slab.  Not
    differential — a fraction is already absolute.  Returns ``[]`` when the geometry is degenerate."""
    if not per_pair_formed_frac or not mean_positions:
        return []
    bp_pts: dict = {}
    for p in mean_positions:
        bp = p["bp_index"]
        if not isinstance(bp, int):
            continue                       # crossover extra-base inserts (bp_index = crossover id, ssDNA — not a designed pair)
        key = (p["helix_id"], bp)
        if key in per_pair_formed_frac:
            bp_pts.setdefault(key, []).append(np.asarray(p["backbone_position"], dtype=float))
    keys = list(bp_pts.keys())
    if len(keys) < 3:
        return []
    pts = np.array([np.mean(bp_pts[k], axis=0) for k in keys])
    C, L, _e1, _e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    span = float(t.max() - t.min())
    if span < 1e-6:
        return []
    if n_slices <= 0:
        n_slices = max(3, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)
    fracs = np.array([per_pair_formed_frac[k] for k in keys])
    out: list[tuple[float, float]] = []
    for k in range(n_slices):
        m = slab == k
        if np.any(m):
            out.append((round(float(t[m].mean()), 3), round(float(fracs[m].mean()), 4)))
    return out


def production_metric_series(
    design,
    production_traj_path,
    reference_conf_path,
    analytic_reference,
    *,
    n_slices: int = 0,
    on_frame=None,
) -> dict:
    """SINGLE-PASS per-frame twist, curvature AND base-pairing over a production trajectory,
    plus the three mean-structure spatial profiles — the compute behind the "Graphs and
    Metrics" card.  Reading frames dominates the cost, so all metrics are gathered in one
    walk (do NOT read the trajectory three times).

    Per frame: differential bundle twist (``measure_bundle_twist − analytic``) and curvature
    (``measure_bundle_curvature − analytic``) on the reference CORE, and the base-pairing
    fraction (:func:`base_pair_retention` on the FULL frame map — melting is a whole-structure
    readout, not core-only).  Accumulates the time-mean structure (for the twist/curvature
    spatial profiles, made differential vs the analytic profiles) and each pair's formed-frame
    count (for :func:`base_pairing_spatial_profile`).  ``on_frame()`` is invoked once per
    measured frame so a caller can drive an ETA bar.

    Frame handling mirrors :func:`production_twist_series` exactly (PBC-unwrap + Kabsch-align,
    backbone site, pooled across a list of trajectory paths).  Returns a per-metric dict with
    ``temporal`` (per_frame + stats) and ``spatial`` ([(axial_t, value)]) sections; ``ready``
    is False if no frames or fewer than two helices.
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
    analytic_twist = measure_bundle_twist(analytic_reference, n_slices=n_slices)
    analytic_curv = measure_bundle_curvature(analytic_reference, n_slices=n_slices)

    twist_pf: list[float] = []
    curv_pf: list[float] = []
    bp_pf: list[float] = []
    acc: dict[tuple, list] = {}                     # key → [bb xyz, …] for the mean structure
    formed: dict[tuple, int] = {}                   # (helix,bp) → frames the pair was H-bonded
    total_pair: dict[tuple, int] = {}               # (helix,bp) → frames the pair was designed
    n_frames = 0
    n_designed = 0
    for path in paths:
        frames = read_trajectory_frames_full(path, design)
        box = _parse_box_nm(path)
        for fr in frames:
            aligned = (unwrap_align_to_reference(fr, ref, design, box)
                       if box is not None and np.all(box > 0) else fr)
            frame_positions = []
            for k, v in aligned.items():
                bb = oxdna_backbone_site(v["backbone_position"], v["a1"], v["a3"])
                frame_positions.append({"helix_id": k[0], "bp_index": k[1], "direction": k[2],
                                        "backbone_position": bb})
                acc.setdefault(k, []).append(bb)
            core = _filter_to_reference_core(frame_positions, analytic_reference)
            try:
                twist_pf.append(measure_bundle_twist(core, n_slices=n_slices) - analytic_twist)
                curv_pf.append(measure_bundle_curvature(core, n_slices=n_slices) - analytic_curv)
            except ValueError:
                continue                            # degenerate frame (too few helices) — skip
            # base pairing on the FULL frame map + per-pair accumulation (mirrors base_pair_retention)
            fwd = {(a, b) for (a, b, d) in aligned if d == "FORWARD"}
            rev = {(a, b) for (a, b, d) in aligned if d == "REVERSE"}
            designed = fwd & rev
            n_designed = max(n_designed, len(designed))
            n_formed = 0
            for hid, bp in designed:
                f = aligned[(hid, bp, "FORWARD")]; r = aligned[(hid, bp, "REVERSE")]
                fb = f["backbone_position"] + OXDNA_BASE_SITE_NM * f["a1"]
                rb = r["backbone_position"] + OXDNA_BASE_SITE_NM * r["a1"]
                total_pair[(hid, bp)] = total_pair.get((hid, bp), 0) + 1
                if float(np.linalg.norm(fb - rb)) <= BP_FORMED_CUTOFF_NM:
                    formed[(hid, bp)] = formed.get((hid, bp), 0) + 1
                    n_formed += 1
            bp_pf.append(n_formed / len(designed) if designed else 0.0)
            n_frames += 1
            if on_frame is not None:
                on_frame()

    if n_frames == 0 or not twist_pf:
        return {"ready": False, "n_frames": 0}

    mean_positions = [{"helix_id": k[0], "bp_index": k[1], "direction": k[2],
                       "backbone_position": np.mean(v, axis=0)} for k, v in acc.items()]
    mean_core = _filter_to_reference_core(mean_positions, analytic_reference)
    twist_sp = differential_profile(measure_bundle_twist_profile(mean_core, n_slices=n_slices),
                                    measure_bundle_twist_profile(analytic_reference, n_slices=n_slices))
    curv_sp = differential_profile(measure_bundle_curvature_profile(mean_core, n_slices=n_slices),
                                   measure_bundle_curvature_profile(analytic_reference, n_slices=n_slices))
    pair_frac = {k: formed.get(k, 0) / total_pair[k] for k in total_pair}
    bp_sp = base_pairing_spatial_profile(pair_frac, mean_positions, n_slices=n_slices)

    return {
        "ready": True, "n_frames": n_frames,
        "twist": {"temporal": {"per_frame": [round(x, 3) for x in twist_pf],
                               "stats": twist_series_stats(twist_pf),
                               "analytic": round(analytic_twist, 3)},
                  "spatial": twist_sp},
        "curvature": {"temporal": {"per_frame": [round(x, 4) for x in curv_pf],
                                   "stats": twist_series_stats(curv_pf),
                                   "analytic": round(analytic_curv, 4)},
                      "spatial": curv_sp},
        "base_pairing": {"temporal": {"per_frame": [round(x, 4) for x in bp_pf],
                                      "n_designed": n_designed},
                         "spatial": bp_sp},
    }


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


def measure_geometry_rmsd(positions, reference_positions) -> float:
    """Per-nucleotide RMSD (nm) of a relaxed/mean position map to an *analytic
    reference* geometry, after optimal rigid (Kabsch) superposition.

    This is the self-consistency measure (option (a)): "does the simulated
    time-averaged structure match the geometry the design *depicts*?"  ``positions``
    is the production mean structure (from :func:`production_rmsf`); ``reference_positions``
    is the analytic B-DNA geometry of the SAME design (same ``_geometry_for_design``
    shape — a list of ``{helix_id, bp_index, direction, backbone_position}`` dicts).
    Both are keyed by ``(helix_id, bp_index, direction)``; the RMSD is computed over
    the nucleotides present in BOTH maps, so passing a *core-only* reference (paired
    duplex, ragged ssDNA ends dropped) restricts the comparison to the rigid core.

    Kabsch removes only the overall translation + rotation (where the bundle floats in
    the oxDNA box is irrelevant); a residual global twist or bend is NOT a rigid motion
    and therefore SURVIVES into the RMSD — exactly the signal we want.  Pure magnitude
    (a distance), so direction-/handedness-agnostic.  Read-only over the Physical layer.

    Raises ``ValueError`` on an empty map or fewer than three shared nucleotides (a
    rigid superposition is undetermined below three non-collinear points).
    """
    if not positions:
        raise ValueError("measure_geometry_rmsd: empty position map")
    if not reference_positions:
        raise ValueError("measure_geometry_rmsd: empty reference map")
    cur = _backbone_lookup(positions)
    ref = _backbone_lookup(reference_positions)
    shared = sorted(set(cur) & set(ref))
    if len(shared) < 3:
        raise ValueError(
            f"measure_geometry_rmsd: only {len(shared)} nucleotide(s) shared between "
            "the mean structure and the analytic reference — need >= 3 to superpose")
    P = np.array([cur[k] for k in shared])      # simulated mean
    Q = np.array([ref[k] for k in shared])      # analytic reference
    _R, Pa, Qc, _Qm = _kabsch_superpose(P, Q)
    return float(np.sqrt(((Pa - Qc) ** 2).sum(axis=1).mean()))


def _kabsch_superpose(P, Q):
    """Optimal rigid (Kabsch) superposition of point set ``P`` onto ``Q``.

    Returns ``(R, Pa, Qc, Qmean)`` where ``R`` is the rotation (rows convention:
    ``Pa = (P − P̄) @ R.T``), ``Pa`` the rotation-aligned centred ``P``, ``Qc`` the
    centred ``Q``, and ``Qmean`` ``Q``'s centroid — so ``Pa + Qmean`` places the
    aligned ``P`` in ``Q``'s frame.  Reflection-guarded."""
    P = np.asarray(P, float)
    Q = np.asarray(Q, float)
    Pc = P - P.mean(axis=0)
    Qmean = Q.mean(axis=0)
    Qc = Q - Qmean
    H = Pc.T @ Qc
    U, _s, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return R, Pc @ R.T, Qc, Qmean


def geometry_deviation_map(positions, reference_positions, *, align_output: bool = True) -> dict:
    """PER-NUCLEOTIDE deviation of a relaxed/mean structure from the analytic design,
    after Kabsch superposition — the spatial breakdown of :func:`measure_geometry_rmsd`.

    Returns ``{positions:[{helix_id, bp_index, direction, backbone_position (the aligned
    MEAN position, in the design frame), nx, ny, nz (mean a1, rotated), deviation (nm)}],
    min_deviation, max_deviation, mean_deviation, n_shared}`` — the display feed for the
    autorefine "deviation map" (mean structure recoloured by distance from design).
    Read-only over the Physical layer."""
    if not positions:
        raise ValueError("geometry_deviation_map: empty position map")
    if not reference_positions:
        raise ValueError("geometry_deviation_map: empty reference map")
    # Copy-aware keys ((helix,bp,dir,copy), copy defaults 0) so loop-insertion copies
    # stay distinct on BOTH the mean structure and the design reference instead of
    # collapsing to one — every loop bead then gets its own deviation value.
    def _k(p):
        return (p["helix_id"], int(p["bp_index"]),
                getattr(p["direction"], "value", p["direction"]), int(p.get("copy", 0)))
    cur_pos = {_k(p): np.array(p["backbone_position"], float) for p in positions}
    cur_a1 = {_k(p): np.array([p.get("nx", 0.0), p.get("ny", 0.0), p.get("nz", 0.0)], float)
              for p in positions}
    ref = {_k(p): np.array(p["backbone_position"], float) for p in reference_positions}
    shared = sorted(set(cur_pos) & set(ref))
    if len(shared) < 3:
        raise ValueError(
            f"geometry_deviation_map: only {len(shared)} shared nucleotide(s) — "
            "need >= 3 to superpose")
    P = np.array([cur_pos[k] for k in shared])
    Q = np.array([ref[k] for k in shared])
    R, Pa, Qc, Qmean = _kabsch_superpose(P, Q)
    dev = np.linalg.norm(Pa - Qc, axis=1)       # per-nucleotide deviation (nm)
    aligned = Pa + Qmean                         # aligned mean positions in design frame
    out = []
    for i, k in enumerate(shared):
        a1 = (R @ cur_a1.get(k, np.zeros(3)) if align_output
              else cur_a1.get(k, np.zeros(3)))
        shown = aligned[i] if align_output else cur_pos[k]
        out.append({"helix_id": k[0], "bp_index": k[1], "direction": k[2], "copy": k[3],
                    "backbone_position": shown.tolist(),
                    "nx": float(a1[0]), "ny": float(a1[1]), "nz": float(a1[2]),
                    "deviation": float(dev[i])})
    return {"positions": out, "min_deviation": float(dev.min()),
            "max_deviation": float(dev.max()), "mean_deviation": float(dev.mean()),
            "n_shared": len(shared)}


def _bundle_axis_frame(pts):
    """Right-handed frame ``(centroid C, axis L, e1, e2)`` for a bundle point cloud.

    ``L`` is the bundle's principal (long) direction; ``e1``/``e2`` span the
    cross-sectional plane with ``e1 x e2 == L`` — so a rotation carrying ``e1`` toward
    ``e2`` is a RIGHT-handed twist about ``L``.  ``L`` is sign-normalised (largest
    component positive) for determinism; the twist sign is invariant to that choice
    (reversing ``L`` reverses both the traversal order and the frame handedness, which
    cancel).
    """
    pts = np.asarray(pts, dtype=float)
    C = pts.mean(axis=0)
    _, sv, vh = np.linalg.svd(pts - C, full_matrices=False)
    if sv[0] < 1e-9:
        raise ValueError("_bundle_axis_frame: points are coincident — no axis")
    L = vh[0]
    if L[int(np.argmax(np.abs(L)))] < 0:
        L = -L
    e1 = vh[1] - float(vh[1] @ L) * L
    n1 = np.linalg.norm(e1)
    if n1 < 1e-9:                                # degenerate 2nd singular vector
        seed = np.array([1.0, 0.0, 0.0]) if abs(L[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        e1 = seed - float(seed @ L) * L
        n1 = np.linalg.norm(e1)
    e1 = e1 / n1
    e2 = np.cross(L, e1)                         # e1 x e2 == L (right-handed)
    return C, L, e1, e2


def measure_bundle_twist(positions, *, n_slices: int = 0) -> float:
    """SIGNED global twist (degrees, right-handed about the bundle axis) accumulated
    from one end of the bundle to the other.

    A straight (untwisted) bundle keeps the SAME cross-sectional arrangement of helices
    at every axial level → 0.  A globally twisted bundle (the square-lattice
    over-/under-wind that skips correct) rotates that cross-section progressively along
    the long axis; this returns the total rotation, signed (+ right-handed, − left-handed).

    USE DIFFERENTIALLY.  On real lattice geometry a small reproducible OFFSET survives
    (ragged ends + the base-pair groove asymmetry the per-turn slab average does not
    fully cancel — e.g. a dead-straight analytic 2×3 bundle reads ≈ −9°, not 0).  For
    self-consistency steering (option (a)) the signal is ``twist(sim) − twist(analytic)``
    of the SAME design: the offset cancels and the residual is the real over/under-wind.

    Method: fit the bundle axis ``L`` + a right-handed cross-section frame
    (:func:`_bundle_axis_frame`); bin every nucleotide into ``n_slices`` axial slabs;
    per slab, average each helix's backbone sites to a 2-D cross-section centre; for
    each consecutive slab pair, best-fit the signed 2-D rotation
    (``atan2(Σ aᵢ×bᵢ, Σ aᵢ·bᵢ)``) over the helices common to both slabs (centred to
    drop translation/bend), and ACCUMULATE — so a twist beyond ±180° is unwound
    correctly rather than aliased.  ``positions`` should be the rigid duplex CORE (pass
    a core-filtered map); ssDNA ends have ill-defined cross-section centres.

    Raises ``ValueError`` on an empty map, fewer than two helices (no cross-section to
    rotate), or a degenerate axis.
    """
    if not positions:
        raise ValueError("measure_bundle_twist: empty position map")
    # Collapse each (helix, bp) column to its base-pair midpoint: averaging the two
    # complementary backbone sites lands ON the helix axis, so the fast per-helix
    # backbone spiral (~34°/bp) — which, combined with the lattice's per-helix phase
    # offsets, would otherwise masquerade as a coherent cross-section rotation — is
    # killed at the source rather than left for the slab average to fight.
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    keys = list(bp_pts.keys())
    pts = np.array([np.mean(bp_pts[k], axis=0) for k in keys])
    helix_ids = [k[0] for k in keys]
    if len(set(helix_ids)) < 2:
        raise ValueError(
            "measure_bundle_twist: need >= 2 helices to define a cross-section twist")
    C, L, e1, e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L                                   # axial coordinate
    u = np.column_stack([(pts - C) @ e1, (pts - C) @ e2])   # 2-D cross-section coords
    span = float(t.max() - t.min())
    if span < 1e-6:
        raise ValueError("measure_bundle_twist: zero axial span")
    if n_slices <= 0:                                   # ~one B-DNA turn (~3.5 nm) per slab
        n_slices = max(3, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)

    # Per slab: {helix_id: mean 2-D cross-section centre} + the slab's mean axial level.
    slab_centres: list[dict] = [dict() for _ in range(n_slices)]
    slab_t: list[float] = [0.0] * n_slices
    acc: list[dict] = [dict() for _ in range(n_slices)]
    acc_t: list[list] = [[] for _ in range(n_slices)]
    for i, hid in enumerate(helix_ids):
        acc[slab[i]].setdefault(hid, []).append(u[i])
        acc_t[slab[i]].append(t[i])
    for k in range(n_slices):
        for hid, vs in acc[k].items():
            slab_centres[k][hid] = np.mean(vs, axis=0)
        if acc_t[k]:
            slab_t[k] = float(np.mean(acc_t[k]))

    total = 0.0
    prev = prev_t = None
    first_t = last_t = None
    for k in range(n_slices):
        cur = slab_centres[k]
        if prev is not None:
            common = sorted(set(prev) & set(cur))
            if len(common) >= 2:
                A = np.array([prev[h] for h in common])
                B = np.array([cur[h] for h in common])
                A = A - A.mean(axis=0)                  # drop translation/bend
                B = B - B.mean(axis=0)
                cross = float(np.sum(A[:, 0] * B[:, 1] - A[:, 1] * B[:, 0]))
                dot = float(np.sum(A[:, 0] * B[:, 0] + A[:, 1] * B[:, 1]))
                total += float(np.degrees(np.arctan2(cross, dot)))
                if first_t is None:
                    first_t = prev_t
                last_t = slab_t[k]
        if cur:
            prev, prev_t = cur, slab_t[k]
    # The accumulation spans only first-slab-centre → last-slab-centre, i.e.
    # (1 − 1/n_slices) of the bundle; rescale to the full axial span (exact for a
    # uniform twist, the regime skips correct).
    if first_t is not None and last_t is not None and abs(last_t - first_t) > 1e-6:
        total *= span / (last_t - first_t)
    return total


def measure_bundle_twist_profile(positions, *, n_slices: int = 0) -> list[tuple[float, float]]:
    """Per-slab CUMULATIVE twist profile ``[(axial_t_nm, cumulative_twist_deg), …]`` — the
    spatially-resolved breakdown of :func:`measure_bundle_twist` (whose scalar return is the
    last value of this profile).  Drives the Phase-5 iterative profile-matcher: the residual
    over-twist RATE between adjacent slabs (the slope of ``profile_sim − profile_analytic``)
    says WHERE the bundle locally over-winds and therefore where deletion density must rise.

    Same method as :func:`measure_bundle_twist` (bp-midpoint collapse → axis frame → ~1-turn
    slabs → centred per-slab cross-section rotation, accumulated), returning the running total
    at each slab centre rather than only the end.  Logic is intentionally duplicated rather
    than refactored — ``measure_bundle_twist``'s behaviour is locked/load-bearing (its small
    reproducible offset is relied on differentially).  Use the profile DIFFERENTIALLY too.
    """
    if not positions:
        raise ValueError("measure_bundle_twist_profile: empty position map")
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    keys = list(bp_pts.keys())
    pts = np.array([np.mean(bp_pts[k], axis=0) for k in keys])
    helix_ids = [k[0] for k in keys]
    if len(set(helix_ids)) < 2:
        raise ValueError("measure_bundle_twist_profile: need >= 2 helices")
    C, L, e1, e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    u = np.column_stack([(pts - C) @ e1, (pts - C) @ e2])
    span = float(t.max() - t.min())
    if span < 1e-6:
        raise ValueError("measure_bundle_twist_profile: zero axial span")
    if n_slices <= 0:
        n_slices = max(3, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)

    slab_centres: list[dict] = [dict() for _ in range(n_slices)]
    slab_t: list[float] = [0.0] * n_slices
    acc: list[dict] = [dict() for _ in range(n_slices)]
    acc_t: list[list] = [[] for _ in range(n_slices)]
    for i, hid in enumerate(helix_ids):
        acc[slab[i]].setdefault(hid, []).append(u[i])
        acc_t[slab[i]].append(t[i])
    for k in range(n_slices):
        for hid, vs in acc[k].items():
            slab_centres[k][hid] = np.mean(vs, axis=0)
        if acc_t[k]:
            slab_t[k] = float(np.mean(acc_t[k]))

    profile: list[tuple[float, float]] = []
    total = 0.0
    prev = prev_t = None
    first_t = last_t = None
    for k in range(n_slices):
        cur = slab_centres[k]
        if prev is not None:
            common = sorted(set(prev) & set(cur))
            if len(common) >= 2:
                A = np.array([prev[h] for h in common]); B = np.array([cur[h] for h in common])
                A = A - A.mean(axis=0); B = B - B.mean(axis=0)
                cross = float(np.sum(A[:, 0] * B[:, 1] - A[:, 1] * B[:, 0]))
                dot = float(np.sum(A[:, 0] * B[:, 0] + A[:, 1] * B[:, 1]))
                total += float(np.degrees(np.arctan2(cross, dot)))
                if first_t is None:
                    first_t = prev_t
                last_t = slab_t[k]
        if cur:
            prev, prev_t = cur, slab_t[k]
            profile.append((slab_t[k], total))
    # Rescale so the endpoint matches measure_bundle_twist's full-span value.
    if first_t is not None and last_t is not None and abs(last_t - first_t) > 1e-6:
        scale = span / (last_t - first_t)
        profile = [(tt, val * scale) for tt, val in profile]
    return profile


def measure_bundle_bend(positions, *, n_slices: int = 0) -> float:
    """Global AXIS BEND (degrees): the end-to-end deflection of the bundle's centroid
    polyline.  A straight bundle's per-slab centroids are collinear → ~0; a bowed/bent
    bundle deflects.  Companion GUARD to :func:`measure_bundle_twist` for regional skip
    placement — redistributing deletions to match the local twist profile must not silently
    introduce net bend (the twist↔bend coupling pitfall).  Use DIFFERENTIALLY (regional −
    uniform of the SAME design) so a fixed lattice offset cancels.  Returns 0.0 when there
    are too few slabs to define curvature.

    Method mirrors :func:`measure_bundle_twist`: collapse each (helix, bp) column to its
    base-pair midpoint (kills the per-helix backbone spiral), fit the bundle axis, bin into
    ~1-turn axial slabs, take each slab's 3-D centroid, and return the angle between the
    first and last segments of that centroid polyline.  Pass the rigid duplex CORE.
    """
    if not positions:
        raise ValueError("measure_bundle_bend: empty position map")
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    pts = np.array([np.mean(v, axis=0) for v in bp_pts.values()])
    if len(pts) < 4:
        return 0.0
    C, L, _e1, _e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    span = float(t.max() - t.min())
    if span < 1e-6:
        return 0.0
    if n_slices <= 0:
        n_slices = max(3, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)
    centroids = [pts[slab == k].mean(axis=0) for k in range(n_slices) if np.any(slab == k)]
    if len(centroids) < 3:
        return 0.0
    centroids = np.array(centroids)
    d0, d1 = centroids[1] - centroids[0], centroids[-1] - centroids[-2]
    n0, n1 = float(np.linalg.norm(d0)), float(np.linalg.norm(d1))
    if n0 < 1e-9 or n1 < 1e-9:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(np.dot(d0, d1) / (n0 * n1), -1.0, 1.0))))


def measure_bundle_curvature(positions, *, n_slices: int = 0) -> float:
    """INTEGRATED total absolute curvature of the bundle centreline (degrees per nm).

    Companion to :func:`measure_bundle_twist`: a skip pattern that cancels global twist is
    only useful if the bundle also stays STRAIGHT.  :func:`measure_bundle_bend` reports the
    end-to-end deflection (angle between the first and last centroid segment) and so reads
    ~0 for an S-bend whose two halves curve oppositely and cancel — yet that bundle is just
    as deformed.  This instead sums the |turning angle| at EVERY interior vertex of the
    slab-centroid polyline and normalises by the polyline arc length, so any local curving
    (single bow, S-bend, or kink) contributes.  A straight bundle reads ~0; a uniform arc of
    radius ``R`` reads ``degrees(1/R)`` (its constant κ).  Like twist, use DIFFERENTIALLY
    (``curvature(sim) − curvature(analytic)``) so the small fixed lattice offset cancels.

    Method mirrors :func:`measure_bundle_bend`: collapse each ``(helix, bp)`` column to its
    base-pair midpoint (kills the per-helix backbone spiral), fit the bundle axis, bin into
    ~1-turn axial slabs, take each slab's 3-D centroid, then accumulate the turning angle
    between consecutive segments of that centroid polyline divided by its total length.
    Returns 0.0 when there are too few slabs to define curvature.  Pass the rigid duplex CORE.
    """
    if not positions:
        raise ValueError("measure_bundle_curvature: empty position map")
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    pts = np.array([np.mean(v, axis=0) for v in bp_pts.values()])
    if len(pts) < 4:
        return 0.0
    C, L, _e1, _e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    span = float(t.max() - t.min())
    if span < 1e-6:
        return 0.0
    if n_slices <= 0:
        n_slices = max(3, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)
    centroids = [pts[slab == k].mean(axis=0) for k in range(n_slices) if np.any(slab == k)]
    if len(centroids) < 3:
        return 0.0
    centroids = np.array(centroids)
    segs = np.diff(centroids, axis=0)                       # consecutive polyline segments
    seg_len = np.linalg.norm(segs, axis=1)
    arc = float(seg_len.sum())
    if arc < 1e-9:
        return 0.0
    total_turn = 0.0
    for k in range(len(segs) - 1):
        n0, n1 = float(seg_len[k]), float(seg_len[k + 1])
        if n0 < 1e-9 or n1 < 1e-9:
            continue
        cos = float(np.dot(segs[k], segs[k + 1]) / (n0 * n1))
        total_turn += float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))
    return total_turn / arc                                  # deg per nm


def _chord_sagitta_bend(centerline) -> tuple[float, float]:
    """Total bend angle (deg) + radius of curvature (nm) of an ordered centerline via
    chord+sagitta — the A9-safe estimator that reads ~0 for a STRAIGHT rod and the true arc
    angle for a circular arc (unlike a segment-tangent angle, which reads LOW as arc ends
    straighten, or a turning-angle integral, which blows up on jitter).  ``centerline`` is
    an (N,3) array ordered ALONG the axis.  This is the estimator the exp36 CanDo bend
    validation uses (``tests/automation_harness._chord_sagitta_bend`` — kept in sync)."""
    cen = np.asarray(centerline, dtype=float)
    if len(cen) < 5:
        return 0.0, float("inf")
    a, b = cen[0], cen[-1]
    chord_v = b - a
    c = float(np.linalg.norm(chord_v))
    if c < 1e-9:
        return 0.0, float("inf")
    u = chord_v / c
    perp = (cen - a) - np.outer((cen - a) @ u, u)
    s = float(np.linalg.norm(perp, axis=1).max())            # sagitta (max deviation)
    if s < 1e-6:
        return 0.0, float("inf")
    R = (c * c / 4.0 + s * s) / (2.0 * s)
    bend = float(np.degrees(2.0 * np.arcsin(np.clip((c / 2.0) / R, -1.0, 1.0))))
    if s > R:                                                # arc past 180° (hairpin)
        bend = 360.0 - bend
    return bend, R


def measure_bundle_arc_bend(positions, *, n_slices: int = 0) -> float:
    """FAITHFUL total bend ANGLE (deg) of a bundle from a backbone-position list, via the
    chord+sagitta of its slab-centroid centreline (:func:`_chord_sagitta_bend`).  Unlike
    :func:`measure_bundle_bend` (segment-tangent angle, reads LOW), this reads the TRUE arc
    angle — a realised 90° bend reads ~85-90°, matching the programmed intent — so it is the
    right estimator for a user-facing "current vs target bend" readout.  Reads ~0 on a straight
    bundle.  Method mirrors :func:`measure_bundle_bend`: collapse (helix, bp) columns to bp
    midpoints, fit the bundle axis, bin into ~1-turn axial slabs, take each slab's 3-D centroid,
    then chord+sagitta the ordered centroid polyline.  Returns 0.0 when too few slabs to resolve.
    Pass the rigid duplex CORE."""
    if not positions:
        raise ValueError("measure_bundle_arc_bend: empty position map")
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    pts = np.array([np.mean(v, axis=0) for v in bp_pts.values()])
    if len(pts) < 5:
        return 0.0
    C, L, _e1, _e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    span = float(t.max() - t.min())
    if span < 1e-6:
        return 0.0
    if n_slices <= 0:
        n_slices = max(5, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)
    centroids = [pts[slab == k].mean(axis=0) for k in range(n_slices) if np.any(slab == k)]
    if len(centroids) < 5:
        return 0.0
    bend, _R = _chord_sagitta_bend(np.array(centroids))
    return bend


def bundle_slab_centreline(positions, *, n_slices: int = 0):
    """The ordered slab-centroid centreline ``(M, 3)`` of a bundle — the shared
    substrate the bend estimators derive from, exposed so a caller can get bend ANGLE
    and RADIUS from the SAME polyline (via :func:`_chord_sagitta_bend`) rather than
    recomputing the axis fit twice.  Same construction as :func:`measure_bundle_arc_bend`:
    collapse each ``(helix, bp)`` column to its base-pair midpoint (kills the per-helix
    backbone spiral), fit the bundle axis, bin into ~1-turn axial slabs, take each
    slab's 3-D centroid in axial order.  Returns an empty ``(0, 3)`` array when there
    are too few points/slabs to resolve a centreline.  Pass the rigid duplex CORE."""
    if not positions:
        raise ValueError("bundle_slab_centreline: empty position map")
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    pts = np.array([np.mean(v, axis=0) for v in bp_pts.values()])
    if len(pts) < 5:
        return np.zeros((0, 3))
    C, L, _e1, _e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    span = float(t.max() - t.min())
    if span < 1e-6:
        return np.zeros((0, 3))
    if n_slices <= 0:
        n_slices = max(5, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)
    centroids = [pts[slab == k].mean(axis=0) for k in range(n_slices) if np.any(slab == k)]
    return np.array(centroids) if len(centroids) >= 2 else np.zeros((0, 3))


def measure_bundle_curvature_profile(positions, *, n_slices: int = 0) -> list[tuple[float, float]]:
    """Per-position CUMULATIVE bending profile ``[(axial_t_nm, cumulative_turning_deg), …]`` — the
    curvature analogue of :func:`measure_bundle_twist_profile`.  The running sum of |turning angle|
    along the slab-centroid polyline: a straight bundle stays ~flat near 0, a bent region ramps,
    and the LOCAL SLOPE between adjacent points is the local curvature (deg/nm) — so the profile
    says WHERE the bundle bends, the way the twist profile says where it over-winds.  The endpoint
    equals the total absolute turning (the un-normalised cousin of :func:`measure_bundle_curvature`).
    Use DIFFERENTIALLY (sim − analytic) like the twist profile.  Pass the rigid duplex CORE.
    """
    if not positions:
        raise ValueError("measure_bundle_curvature_profile: empty position map")
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    pts = np.array([np.mean(v, axis=0) for v in bp_pts.values()])
    if len(pts) < 4:
        return []
    C, L, _e1, _e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    span = float(t.max() - t.min())
    if span < 1e-6:
        return []
    if n_slices <= 0:
        n_slices = max(3, int(round(span / 3.5)))
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)
    cen, cen_t = [], []
    for k in range(n_slices):
        m = slab == k
        if np.any(m):
            cen.append(pts[m].mean(axis=0)); cen_t.append(float(t[m].mean()))
    if len(cen) < 3:
        return []
    cen = np.array(cen)
    segs = np.diff(cen, axis=0)
    seg_len = np.linalg.norm(segs, axis=1)
    profile = [(cen_t[0], 0.0), (cen_t[1], 0.0)]            # turning is defined at interior vertices
    total = 0.0
    for k in range(len(segs) - 1):
        n0, n1 = float(seg_len[k]), float(seg_len[k + 1])
        if n0 >= 1e-9 and n1 >= 1e-9:
            cos = float(np.dot(segs[k], segs[k + 1]) / (n0 * n1))
            total += float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))
        profile.append((cen_t[k + 2], total))
    return profile


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


def _full_map_to_positions(full_map) -> list[dict]:
    """A ``read_configuration_full`` map (``{(helix,bp,dir): {backbone_position,
    a1, a3}}``, ``copies=False``) → the per-nucleotide position list the
    list-based measures (:func:`measure_field_response`,
    :func:`measure_radius_of_gyration`) expect."""
    return [{"helix_id": k[0], "bp_index": k[1], "direction": k[2],
             "backbone_position": v["backbone_position"]}
            for k, v in full_map.items()]


def field_equilibrium_observables(
    field_full_map,
    reference_full_map,
    field_dir,
    anchor_keys,
    *,
    design,
) -> dict:
    """The EQUILIBRIUM observables of a field-relaxed structure vs its field-off
    reference — the reusable comparison currency for the burst-stepped (oxpy) vs
    one-shot (batch) parity oracle (AF-21).

    ``field_full_map`` / ``reference_full_map`` are ``read_configuration_full``
    maps (``copies=False``) of the post-field and field-off configurations.
    Composes three independently-proven measures into one equilibrium fingerprint:

    - ``alignment_nm`` — mean displacement of the FREE (non-anchored) nucleotides
      ALONG the field, vs the reference (:func:`measure_field_response`'s
      ``free_proj_along_field_nm`` — the equilibrium pose the field drives to);
    - ``radius_of_gyration_nm`` — global compactness of the field structure
      (:func:`measure_radius_of_gyration`); swelling/collapse a single projection
      cannot see;
    - ``bp_retention`` — fraction of designed WC pairs still hydrogen-bonded
      (:func:`base_pair_retention`); the "did it survive the field" readout.

    Pure (takes already-read maps, no I/O), magnitudes only (direction-agnostic),
    Three-Layer-clean (reads geometry, never writes ``Design``).  Returns
    ``{alignment_nm, radius_of_gyration_nm, bp_retention, n_free, n_anchored}``.
    """
    field_positions = _full_map_to_positions(field_full_map)
    reference_positions = _full_map_to_positions(reference_full_map)
    resp = measure_field_response(
        field_positions, reference_positions, field_dir, anchor_keys)
    rg = measure_radius_of_gyration(field_positions)
    bp, _n_pairs = base_pair_retention(design, field_full_map)
    return {
        "alignment_nm": resp["free_proj_along_field_nm"],
        "radius_of_gyration_nm": rg,
        "bp_retention": bp,
        "n_free": resp["n_free"],
        "n_anchored": resp["n_anchored"],
    }


def field_equilibrium_from_confs(
    design,
    field_conf_path,
    reference_conf_path,
    *,
    field_dir,
    anchor_keys,
) -> dict:
    """:func:`field_equilibrium_observables` driven from two oxDNA configuration
    files — the batch-side counterpart for the AF-21 parity oracle (the one-shot
    binary run's equilibrium fingerprint).  ``field_conf_path`` is the post-field
    configuration; ``reference_conf_path`` the field-off (relaxed) seed."""
    from backend.physics.oxdna_interface import read_configuration_full
    return field_equilibrium_observables(
        read_configuration_full(field_conf_path, design),
        read_configuration_full(reference_conf_path, design),
        field_dir, anchor_keys, design=design)


def measure_field_equilibration(
    frames,
    field_dir,
    anchor_keys,
    *,
    design: Design,
    steps_per_frame: float = 1.0,
    melt_floor: float = 0.0,
    plateau_frac: float = 1.0 - 1.0 / math.e,
    plateau_slope_frac: float = 0.3,
    min_rise_nm: float = 0.5,
    monotone_tol_frac: float = 0.15,
) -> dict:
    """Extract the *time course* of a structure's response to an electric-field stage
    — the equilibration timeline τ + a transient-melt watch (AF-19, Tier 6).

    Where :func:`measure_field_response` is **endpoint-only** (the final relaxed pose
    vs the field-off reference), this reads the WHOLE field-stage trajectory and
    measures, frame by frame, how the free body aligns to the field AND whether the
    structure holds together *during* the swing.  ``frames`` is the list of
    per-nucleotide maps :func:`read_trajectory_frames_full` returns (each
    ``{(helix_id, bp_index, direction): {backbone_position, a1, …}}``), in time order;
    frame 0 is the field-off start the displacement is measured against.  ``field_dir``
    is the field direction (only its unit direction matters — projection magnitudes are
    measured, so no sign/handedness reasoning enters here); ``anchor_keys`` are the
    pinned ``(helix_id, bp_index, direction)`` keys (their nucleotides are excluded
    from the free-body projection — they are held by traps).

    Two per-frame observables:

    * **alignment** — the mean displacement of the *free* (non-anchored) nucleotides
      along the field direction, relative to frame 0 (the same projection
      :func:`measure_field_response` reports as ``free_proj_along_field_nm``, now per
      frame).  Under a DC field an anchored body swings to a new pose and the
      projection rises and **saturates**.
    * **bp retention** — :func:`base_pair_retention` per frame (fraction of designed WC
      pairs still hydrogen-bonded), so a *transient* melt mid-swing is visible, not just
      the endpoint.

    The monotone approach is fit to its plateau (mean of the tail frames) and τ is the
    time (in steps, via ``steps_per_frame``) to reach ``plateau_frac`` of the plateau
    (``1 − 1/e`` ≈ 63%, linearly interpolated between bracketing frames).  ``converged``
    is True only when the response is **non-vacuous** (total rise ≥ ``min_rise_nm``),
    **monotone within noise** (no frame drops more than ``monotone_tol_frac`` of the
    plateau below its predecessor), and has actually **plateaued** (the late-frame slope
    has fallen to ≤ ``plateau_slope_frac`` of the early-frame slope — a run still
    climbing at the end has *not* equilibrated, so τ is reported as ``None``).

    ``melted`` is True when bp retention dips below ``melt_floor`` at ANY frame (the
    "without ripping it apart" invariant — the floor is breached even transiently).

    Returns ``{n_frames, alignment_timecourse, bp_timecourse, plateau, aligned_final,
    tau_frames, tau_steps, converged, bp_min, melted, reason}``.  *Physical-layer only*
    — it reads trajectory geometry, never writes it back into ``Design``.  Raises on
    fewer than two frames or a zero field direction (no silent degenerate timeline).
    """
    if frames is None or len(frames) < 2:
        raise ValueError(
            "measure_field_equilibration: need at least two trajectory frames to "
            "measure a time course")
    fdir = np.asarray(field_dir, dtype=float)
    fnorm = float(np.linalg.norm(fdir))
    if fnorm <= 1e-9:
        raise ValueError("measure_field_equilibration: field_dir is ~zero")
    fdir = fdir / fnorm
    anchor_set = {_landmark_key(tuple(k)[:3]) for k in anchor_keys}

    ref = frames[0]
    free_keys = [k for k in ref if k not in anchor_set]
    if not free_keys:
        raise ValueError(
            "measure_field_equilibration: no free (non-anchored) nucleotides to "
            "measure — every key is anchored")

    alignment: list[float] = []
    for fr in frames:
        projs = []
        for k in free_keys:
            if k not in fr:
                continue
            disp = np.asarray(fr[k]["backbone_position"], dtype=float) - \
                np.asarray(ref[k]["backbone_position"], dtype=float)
            projs.append(float(np.dot(disp, fdir)))
        alignment.append(float(np.mean(projs)) if projs else 0.0)

    bp_timecourse = [base_pair_retention(design, fr)[0] for fr in frames]
    bp_min = min(bp_timecourse)
    melted = bp_min < melt_floor

    n = len(alignment)
    tail_n = max(2, n // 4)
    plateau = float(np.mean(alignment[-tail_n:]))
    aligned_final = alignment[-1]
    total_rise = aligned_final - alignment[0]

    reasons: list[str] = []
    if total_rise < min_rise_nm:
        reasons.append(
            f"free-body response {total_rise:.2f} nm < {min_rise_nm} nm min "
            "(no field response / field-independent)")

    back_tol = monotone_tol_frac * abs(plateau)
    backsteps = sum(1 for i in range(1, n)
                    if alignment[i] < alignment[i - 1] - back_tol)
    if backsteps:
        reasons.append(
            f"approach is non-monotone ({backsteps} frame(s) recede past noise)")

    third = max(1, n // 3)
    early_slope = (alignment[third] - alignment[0]) / third
    late_slope = (alignment[-1] - alignment[-1 - third]) / third
    plateaued = early_slope > 0 and late_slope <= plateau_slope_frac * early_slope
    if not plateaued:
        reasons.append(
            "trajectory has not plateaued (late-frame slope "
            f"{late_slope:.3f} vs early {early_slope:.3f} nm/frame) — not equilibrated")

    converged = not reasons
    tau_frames: float | None = None
    tau_steps: float | None = None
    if converged:
        target = alignment[0] + plateau_frac * (plateau - alignment[0])
        for i in range(1, n):
            if alignment[i] >= target:
                lo, hi = alignment[i - 1], alignment[i]
                frac = 0.0 if hi == lo else (target - lo) / (hi - lo)
                tau_frames = (i - 1) + frac
                break
        if tau_frames is None:
            tau_frames = float(n - 1)
        tau_steps = tau_frames * steps_per_frame

    return {
        "n_frames": n,
        "alignment_timecourse": alignment,
        "bp_timecourse": bp_timecourse,
        "plateau": plateau,
        "aligned_final": aligned_final,
        "tau_frames": tau_frames,
        "tau_steps": tau_steps,
        "converged": converged,
        "bp_min": bp_min,
        "melted": melted,
        "reason": "; ".join(reasons) or "monotone approach to a stable plateau",
    }


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
    {"end_to_end", "radius_of_gyration", "segment_angle", "inter_helix_spacing",
     "geometry_match", "bundle_twist"})
# How many landmarks each measure consumes.  0 = whole-structure (no landmarks).
# NB: target_nm/tol_nm carry the measure's native unit — nm for length measures
# (end_to_end, radius_of_gyration, inter_helix_spacing, geometry_match), DEGREES for
# the angular measures (segment_angle, bundle_twist).  The field names are kept for
# backward compatibility.  For inter_helix_spacing the two landmarks each only NAME a
# helix (any nucleotide on it); the measure groups every site of that helix to fit its
# axis.  geometry_match + bundle_twist are whole-structure *self-consistency* measures
# (no landmarks) that compare the mean structure to the design's ANALYTIC geometry —
# they require a ``reference_positions`` supplied at check time (not in the spec).
_REFERENCE_MEASURES = frozenset({"geometry_match", "bundle_twist"})
_MEASURE_LANDMARK_COUNT = {
    "end_to_end": 2, "radius_of_gyration": 0, "segment_angle": 3,
    "inter_helix_spacing": 2, "geometry_match": 0, "bundle_twist": 0}
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


def _core_column_key(p):
    """``(helix_id, bp_index, direction)`` for a position dict, or ``None`` when
    ``bp_index`` is not an integer column — i.e. a crossover extra-base insert, whose
    key is ``("__xb__", crossover_id, k)`` (bp_index = a crossover id string). Those
    ssDNA inserts are never part of the dsDNA reference core, so they drop out."""
    bp = p["bp_index"]
    if not isinstance(bp, int):
        return None
    return (p["helix_id"], bp, getattr(p["direction"], "value", p["direction"]))


def _filter_to_reference_core(positions, reference):
    """Sub-list of ``positions`` whose ``(helix_id, bp_index, direction)`` key is
    present in ``reference`` — the reference (a core-only analytic geometry) doubles
    as the CORE MASK, so ragged ssDNA ends absent from the reference are dropped from
    the simulated mean before a self-consistency measure runs."""
    ref_keys = {k for p in reference if (k := _core_column_key(p)) is not None}
    return [p for p in positions
            if (k := _core_column_key(p)) is not None and k in ref_keys]


def _dispatch_measure(measure: str, positions, landmarks, reference=None):
    """Compute the named relaxed-structure measure from a position map + the
    parsed (already-validated) landmark list.  Adding a new ``measure_*`` kind =
    add it to :data:`_CONSTRAINT_MEASURES` + :data:`_MEASURE_LANDMARK_COUNT` and a
    branch here.  ``reference`` (the design's analytic geometry) is required by the
    self-consistency measures in :data:`_REFERENCE_MEASURES`."""
    if measure == "end_to_end":
        return measure_end_to_end(positions, landmarks[0], landmarks[1])
    if measure == "radius_of_gyration":
        return measure_radius_of_gyration(positions)
    if measure == "segment_angle":
        return measure_segment_angle(
            positions, landmarks[0], landmarks[1], landmarks[2])
    if measure == "inter_helix_spacing":
        return measure_inter_helix_spacing(positions, landmarks[0], landmarks[1])
    if measure in _REFERENCE_MEASURES:
        if not reference:
            raise ConstraintSpecError(
                f"constraint measure {measure!r} is a self-consistency measure — it "
                "needs the design's analytic reference geometry (reference_positions)")
        core = _filter_to_reference_core(positions, reference)
        if measure == "geometry_match":
            return measure_geometry_rmsd(core, reference)
        # bundle_twist: report the SIGNED residual vs the analytic depiction, so the
        # reproducible measurement offset cancels (target a 0° residual).
        return measure_bundle_twist(core) - measure_bundle_twist(reference)
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


def check_relaxed_constraint(constraint, relaxed_output, reference_positions=None) -> dict:
    """REPORT (do not assert) whether a relaxed structure meets a declarative
    constraint — the AF-13 P3 reporter that AF-13 P4's iterate-until-met loop and
    the AF-11 grammar's ``constraints`` block consume.

    ``constraint`` is a constraint spec (raw or already parsed — it is normalised
    via :func:`parse_constraint_spec`).  ``relaxed_output`` is the dict returned by
    :func:`~backend.api.headless_oxdna_build.read_flexibility_map` (the production
    mean structure): ``{ready, positions, confidence:{n_frames,...}, ...}``.
    ``reference_positions`` is the design's ANALYTIC geometry (core-only) — required
    by the self-consistency measures (``geometry_match`` / ``bundle_twist``) and
    ignored by the others.  For ``geometry_match`` the verdict also carries a
    ``steering`` block (``{bundle_twist_residual_deg}``) — the SIGNED over/under-wind
    vs the depiction, since the RMSD gate itself is unsigned.

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
    steering = None
    if has_structure:
        if c["measure"] in _REFERENCE_MEASURES and reference_positions:
            # Compute BOTH self-consistency metrics so the verdict carries the unsigned
            # RMSD-to-design AND the SIGNED twist residual regardless of which one gates
            # — the other is the companion the optimizer (direction) and the before/after
            # panel read.  geometry_match RMSD is too insensitive to a distributed global
            # twist to gate a large bundle, so bundle_twist is the right gate for plain
            # square lattices; both are still reported either way.
            rmsd = _dispatch_measure("geometry_match", positions, [],
                                     reference=reference_positions)
            twist = _dispatch_measure("bundle_twist", positions, [],
                                      reference=reference_positions)
            steering = {"geometry_rmsd_nm": rmsd, "bundle_twist_residual_deg": twist}
            measured = rmsd if c["measure"] == "geometry_match" else twist
        else:
            measured = _dispatch_measure(
                c["measure"], positions, c["landmarks"], reference=reference_positions)

    if not has_structure or n_frames < min_conf:
        status, met = "inconclusive", False
    elif abs(measured - target) <= tol:
        status, met = "met", True
    else:
        status, met = "unmet", False

    result = {"met": met, "status": status, "measured_nm": measured,
              "target_nm": target, "tol_nm": tol, "n_frames": n_frames,
              "min_confidence": min_conf, "confidence": confidence}
    if steering is not None:
        result["steering"] = steering
    return result


# Reading + PBC-unwrapping + Kabsch-aligning a whole multi-stage trajectory is the
# dominant cost of EVERY trajectory request (≈14 s for a 199-frame 6hb).  The CG
# composite, each per-frame atomistic/surface fetch, and the audit all re-derived it
# from scratch — so scrubbing an atomistic trajectory paid it once PER frame.  The
# aligned frames depend only on the immutable stage/reference files, so memoize them
# keyed by a (path,size,mtime) signature: a completed job aligns once; a still-writing
# job's signature changes as files grow, so it re-aligns (stays live-correct).
_ALIGNED_CACHE = None   # lazily-created collections.OrderedDict[cache_key -> result]
_ALIGNED_CACHE_MAX = 6

# Per-FRAME aligned cache: an individual trajectory frame, PBC-unwrapped + Kabsch-aligned
# to the design reference, keyed by (trajectory-file signature, reference CONTENT hash,
# copies, raw frame index).  The whole-composite ``_ALIGNED_CACHE`` above misses when you
# switch to a SIBLING job (different stages tuple), even though the two lineages share
# every ancestor stage (root relaxation + shared production runs).  Keying a frame by its
# file + reference-content lets a sibling REUSE those shared aligned frames — so selecting
# a job with a common parent while a trajectory is on screen re-does only the frames that
# differ (its own leaf run), not the whole lineage.  Keyed by reference *content* (not
# path) because sibling jobs write byte-identical ``design_ref.dat`` files at different
# paths.  Bounded by cumulative nucleotide-frames (memory-proportional for big structures).
_FRAME_CACHE = None     # lazily-created OrderedDict[frame_key -> aligned frame dict]
_FRAME_CACHE_NT = 0     # running Σ len(frame) across the cache (for memory-bounded evict)
_FRAME_CACHE_MAX_NT = 3_000_000   # ~a couple of large lineages' shared ancestors

# Per-frame DISPLAY OUTPUT cache: the finished atomistic flat-XYZ list / surface JSON
# for one relaxed or trajectory frame.  The two caches above memoize the *aligned frame*
# (the expensive PBC-unwrap + Kabsch step); they do NOT memoize the all-atom rebuild that
# turns that frame into ~23 atoms/nucleotide — which the frontend comment rightly calls
# "≈ several seconds each".  Re-scrubbing to a frame you already visited, or flipping the
# representation atomistic→surface→atomistic on the SAME frame, used to re-pay that rebuild
# every time.  This cache makes the second visit free.  Keyed by a caller-supplied tuple
# that fully determines the output (aligned-cache-key + frame idx + any surface params, or
# for the relaxed single frame the conf-file signature + align).  Bounded by cumulative
# element count (floats/ints across cached payloads), so memory scales with structure size
# the same way the frame cache does.
_DISPLAY_OUT_CACHE = None   # lazily-created OrderedDict[key -> list|dict payload]
_DISPLAY_OUT_ELEMS = 0      # running Σ payload element count (for memory-bounded evict)
_DISPLAY_OUT_MAX_ELEMS = 6_000_000   # ~30 large-origami frames, or hundreds of small ones


def _out_payload_elems(payload) -> int:
    """Rough element count of a display payload for the memory budget: the flat-XYZ
    list length, or a surface dict's vertices+faces(+colors) lengths."""
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        n = len(payload.get("vertices", ())) + len(payload.get("faces", ()))
        n += len(payload.get("vertex_colors", ())) + len(payload.get("vertex_rmsf", ()))
        return n
    return 0


def _display_out_get(key):
    """Return a cached display payload (LRU-touched) or None."""
    global _DISPLAY_OUT_CACHE
    if _DISPLAY_OUT_CACHE is None:
        return None
    v = _DISPLAY_OUT_CACHE.get(key)
    if v is not None:
        try:
            _DISPLAY_OUT_CACHE.move_to_end(key)
        except KeyError:
            pass
    return v


def _display_out_put(key, payload):
    """Insert a display payload, evicting oldest until under the element budget."""
    global _DISPLAY_OUT_CACHE, _DISPLAY_OUT_ELEMS
    from collections import OrderedDict
    if _DISPLAY_OUT_CACHE is None:
        _DISPLAY_OUT_CACHE = OrderedDict(); _DISPLAY_OUT_ELEMS = 0
    if key in _DISPLAY_OUT_CACHE:
        return
    _DISPLAY_OUT_CACHE[key] = payload
    _DISPLAY_OUT_ELEMS += _out_payload_elems(payload)
    while _DISPLAY_OUT_ELEMS > _DISPLAY_OUT_MAX_ELEMS and len(_DISPLAY_OUT_CACHE) > 1:
        try:
            _, ev = _DISPLAY_OUT_CACHE.popitem(last=False)
            _DISPLAY_OUT_ELEMS -= _out_payload_elems(ev)
        except KeyError:
            break


def display_out_cache_clear():
    """Drop the whole display-output cache (test hook / manual invalidation)."""
    global _DISPLAY_OUT_CACHE, _DISPLAY_OUT_ELEMS
    _DISPLAY_OUT_CACHE = None
    _DISPLAY_OUT_ELEMS = 0


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


def _traj_file_sig(path):
    """(path, size, mtime_ns) — changes when a still-writing trajectory grows, so a live
    run naturally invalidates its cached frames instead of serving stale ones."""
    import os
    try:
        st = os.stat(path)
        return (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(path), -1, -1)


def _ref_content_sig(reference_conf_path):
    """Hash of the reference conf's bytes (one small frame).  Sibling jobs of the same
    design write byte-identical ``design_ref.dat`` at DIFFERENT paths, so keying the frame
    cache by content — not path — lets them share the aligned ancestor frames."""
    import hashlib
    try:
        with open(reference_conf_path, "rb") as fh:
            return hashlib.blake2b(fh.read(), digest_size=16).digest()
    except OSError:
        return None


def _frame_cache_get(key):
    """Return a cached aligned frame (LRU-touched) or None."""
    global _FRAME_CACHE
    if _FRAME_CACHE is None:
        return None
    v = _FRAME_CACHE.get(key)
    if v is not None:
        try:
            _FRAME_CACHE.move_to_end(key)      # LRU touch (tolerate a concurrent evict)
        except KeyError:
            pass
    return v


def _frame_cache_put(key, frame):
    """Insert an aligned frame, evicting oldest until under the nucleotide-frame budget."""
    global _FRAME_CACHE, _FRAME_CACHE_NT
    from collections import OrderedDict
    if _FRAME_CACHE is None:
        _FRAME_CACHE = OrderedDict(); _FRAME_CACHE_NT = 0
    if key in _FRAME_CACHE:
        return
    _FRAME_CACHE[key] = frame
    _FRAME_CACHE_NT += len(frame)
    while _FRAME_CACHE_NT > _FRAME_CACHE_MAX_NT and len(_FRAME_CACHE) > 1:
        try:
            _, ev = _FRAME_CACHE.popitem(last=False)
            _FRAME_CACHE_NT -= len(ev)
        except KeyError:
            break


def _aligned_downsampled_frames(design, stages, reference_conf_path, max_frames: int = 200,
                                *, copies: bool = False, progress=None, align: bool = True,
                                n_trailing_extra: int = 0,
                                trailing_extra_strand_length: int = 0):
    """Shared core for the composite trajectory: per stage, downsample to a ≤
    ``max_frames`` budget FIRST (cheap header count → stride), then PBC-unwrap +
    Kabsch-align only the surviving frames to the design reference.  The seed
    configuration is prepended (position 0 of the first non-empty stage) as a stride
    candidate so the player still starts on the true starting structure.

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
    cache_key = (_aligned_cache_key(stages, reference_conf_path, max_frames, copies),
                 bool(align), int(n_trailing_extra), int(trailing_extra_strand_length))
    hit = _ALIGNED_CACHE.get(cache_key)
    if hit is not None:
        try:
            _ALIGNED_CACHE.move_to_end(cache_key)   # LRU touch (tolerate a concurrent evict)
        except KeyError:
            pass
        return hit

    from backend.physics.oxdna_interface import (
        _build_unwrap_plan,
        _parse_box_nm,
        _capture_particle_key, _strand_nucleotide_order,
        read_configuration_full,
        read_trajectory_frames_at,
        unwrap_align_to_reference,
    )
    ref = read_configuration_full(reference_conf_path, design, copies=copies,
                                  n_trailing_extra=n_trailing_extra,
                                  trailing_extra_strand_length=trailing_extra_strand_length)
    # SEPARATE read for the prepended seed frame: the alignment reference deliberately
    # omits synthetic particles (extra bases / extension tails would otherwise join the
    # Kabsch fit as floppy outliers), but the seed frame IS a displayed frame and must
    # carry them — design_ref.dat has real rows for every one of them.  Without this the
    # first frame of every trajectory drew all extra bases + extension tails at the world
    # origin (missing key → six zeros in _flatten_cg_frame), which snapped away at frame 1.
    ref_display = read_configuration_full(
        reference_conf_path, design, copies=copies,
        include_extra_bases=True, include_extensions=True,
        n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)
    ref_sig = _ref_content_sig(reference_conf_path)   # content hash → siblings share frames
    # copies=True keeps loop-insertion copies distinct (full 4-tuple key); else collapse
    # to the 3-tuple so the CG trajectory key list is one entry per (helix,bp,dir).
    key_list = list(dict.fromkeys(
        (k if copies else k[:3]) for k in _strand_nucleotide_order(design)))
    if n_trailing_extra > 0 and trailing_extra_strand_length > 0:
        key_list.extend(_capture_particle_key(i, trailing_extra_strand_length)
                        for i in range(int(n_trailing_extra)))

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

    # A stage tuple is ``(name, kind, path)``, ``(…, marker_label)`` or
    # ``(…, marker_label, field)`` (field = the run's E-field descriptor or None).
    #
    # DOWNSAMPLE FIRST.  The scrub player keeps ≤ ``max_frames`` (~200), so reading and
    # Kabsch-aligning EVERY frame of a multi-thousand-frame run only to discard 95 % of it
    # is the dominant load cost.  Instead: cheaply count each stage's frames (header scan,
    # no coordinate parse), decide the per-stage stride, then parse + align ONLY the frames
    # that survive it.  The seed configuration is still prepended at position 0 of the first
    # non-empty stage so it remains a stride candidate exactly as before.
    raw_counts = [count_trajectory_frames(item[2]) for item in stages]
    first_nonempty = next((i for i, c in enumerate(raw_counts) if c > 0), None)
    if first_nonempty is None:
        return key_list, [], [], []
    # effective length includes the prepended seed on the first non-empty stage
    eff_lens = [c + (1 if i == first_nonempty else 0) for i, c in enumerate(raw_counts)]
    total = sum(eff_lens)

    # The unwrap traversal structure (bond graph → DFS order, parents, components)
    # depends only on topology + the frame's key SET (constant across a stage's complete
    # frames), not the coordinates — so build it ONCE per distinct key set and reuse it,
    # letting every frame unwrap via vectorized numpy instead of a per-nucleotide graph
    # walk rebuilt ~200 times.
    _plan_cache: dict = {}

    def _plan_for(fr):
        ks = frozenset(fr)
        p = _plan_cache.get(ks)
        if p is None:
            p = _build_unwrap_plan(fr, design)
            _plan_cache[ks] = p
        return p

    def _keep_for(e):
        # max_frames <= 0 → UNLIMITED (the full-trajectory view): keep every written
        # frame, no stride.  Otherwise share the budget across stages as before.
        if max_frames <= 0 or total <= max_frames:
            return e
        return max(1, round(e * max_frames / total))
    total_kept = sum(_keep_for(e) for e in eff_lens if e > 0)   # progress denominator
    if n_trailing_extra > 0 and trailing_extra_strand_length > 0:
        total_kept += 1  # raw frame 0 supplies capture coordinates for the design seed
    done = 0
    if progress:
        progress(0, total_kept)

    ordered_frames: list[dict] = []
    out_stages: list[dict] = []
    markers: list[dict] = []
    for i, item in enumerate(stages):
        name, kind, path = item[0], item[1], item[2]
        marker_label = item[3] if len(item) > 3 else None
        field = item[4] if len(item) > 4 else None
        eff = eff_lens[i]
        if eff == 0:
            continue
        keep = _keep_for(eff)
        picked = _stride_pick(list(range(eff)), keep)   # positions into this stage's eff list

        # Map each kept eff-position to a raw trajectory-header index (position 0 of the
        # first non-empty stage is the prepended seed ref, which needs no parse), then parse
        # + align only those raw frames.
        seed_here = (i == first_nonempty)
        needed = sorted({(p - 1 if seed_here else p) for p in picked
                         if not (seed_here and p == 0)})
        if seed_here and n_trailing_extra > 0 and trailing_extra_strand_length > 0:
            needed = sorted(set(needed) | {0})

        # Reuse any aligned frame already cached from a previously-viewed lineage that
        # shares this ancestor stage (a common-parent sibling), so only the frames unique
        # to THIS job get parsed + aligned — the load's heavy work.
        tsig = _traj_file_sig(path)
        aligned = {}
        missing = []
        for idx in needed:
            frame_key = (tsig, ref_sig, copies, bool(align), int(n_trailing_extra),
                         int(trailing_extra_strand_length), idx)
            hit = _frame_cache_get(frame_key) if ref_sig is not None else None
            if hit is not None:
                aligned[idx] = hit
                done += 1
                if progress:
                    progress(done, total_kept)
            else:
                missing.append(idx)
        if missing:
            parsed = read_trajectory_frames_at(
                path, design, missing, copies=copies,
                n_trailing_extra=n_trailing_extra,
                trailing_extra_strand_length=trailing_extra_strand_length)
            box = _parse_box_nm(path)
            do_align = box is not None and np.all(box > 0)
            for idx, fr in parsed.items():   # the per-frame align is the load's heavy work
                af = (unwrap_align_to_reference(fr, ref, design, box, plan=_plan_for(fr), align=align)
                      if do_align else fr)
                aligned[idx] = af
                if ref_sig is not None:
                    _frame_cache_put((tsig, ref_sig, copies, bool(align),
                                      int(n_trailing_extra),
                                      int(trailing_extra_strand_length), idx), af)
                done += 1
                if progress:
                    progress(done, total_kept)

        stage_frames: list[dict] = []
        for p in picked:
            if seed_here and p == 0:
                # The design-origin reference has no appended particles. Seed their
                # renderer identities from the first physical trajectory frame so
                # playback never starts with every capture bead at [0,0,0].
                # (Extra bases + extension tails DO exist in design_ref.dat — they come
                # from ref_display, at their design-pose positions.)
                seed = dict(ref_display)
                first = aligned.get(0) or {}
                seed.update({k: v for k, v in first.items()
                             if isinstance(k[0], str) and k[0].startswith("cap")})
                stage_frames.append(seed)
                continue
            fr = aligned.get((p - 1) if seed_here else p)
            if fr is not None:          # a malformed / half-written frame drops out (as before)
                stage_frames.append(fr)
        if not stage_frames:
            continue

        if ordered_frames:  # a transition into this stage (skip the very first frame)
            markers.append({"frame": len(ordered_frames),
                            "label": marker_label or f"→ {kind}",
                            "kind": kind, "stage_name": name})
        out_stages.append({"name": name, "kind": kind, "n_frames": len(stage_frames),
                           "field": field})
        ordered_frames.extend(stage_frames)

    if progress:
        progress(total_kept, total_kept)   # snap to 100% (the seed frame needs no align)
    if not ordered_frames:
        return key_list, [], [], []
    return _store((key_list, ordered_frames, out_stages, markers))


def _flatten_cg_frame(frame: dict, key_list) -> list:
    """Flatten one full per-nucleotide frame dict to the compact CG float list
    (backbone site x,y,z + a1 nx,ny,nz per key).

    Vectorized: gather every key's cm/a1/a3 into ``(N, 3)`` arrays and compute the
    backbone sites in one batched call, instead of a per-nucleotide ``np.cross`` (whose
    numpy dispatch overhead was the single biggest cost of the composite build).  A
    missing key stays all-zeros — cm/a1/a3 default to 0 → backbone site 0 → six zeros,
    identical to the old per-key fallback."""
    from backend.physics.oxdna_interface import oxdna_backbone_sites
    n = len(key_list)
    cm = np.zeros((n, 3)); a1 = np.zeros((n, 3)); a3 = np.zeros((n, 3))
    for i, key in enumerate(key_list):
        v = frame.get(key)
        if v is None:
            continue
        cm[i] = v["backbone_position"]; a1[i] = v["a1"]; a3[i] = v["a3"]
    out = np.zeros((n, 6))
    out[:, 0:3] = oxdna_backbone_sites(cm, a1, a3)
    out[:, 3:6] = a1
    return out.reshape(-1).tolist()


def composite_trajectory(
    design,
    stages,
    reference_conf_path,
    max_frames: int = 200,
    progress=None,
    align: bool = True,
    n_trailing_extra: int = 0,
    trailing_extra_strand_length: int = 0,
) -> dict:
    """Build the composite scrub-able trajectory for the View-trajectory player.

    ``progress`` is an optional ``callback(done, total)`` invoked as frames are
    aligned (``total`` = the downsampled frame budget), so the route can surface an
    accurate frames-processed loading bar for a large structure's multi-second build.

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
      ``stages`` = [{name, kind, n_frames, field}]         (field = the run's
                   E-field descriptor {dir, field_pN} or None — lets the player
                   point the field arrow at whichever run is on screen)
      ``markers``= [{frame, label, kind, stage_name}]      (transition at each
                   stage's first composite-frame; the very first frame is omitted)
    """
    # copies=True → loop-insertion copies stay distinct so every loop bead scrubs.
    key_list, ordered, out_stages, markers = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames, copies=True, progress=progress,
        align=align, n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)
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
    (each frame starts with a ``t = …`` line). Cheap — no coordinate parsing.

    Thin alias for :func:`count_trajectory_frames`: this used to be a second,
    UN-memoized copy of that scan, so ``composite_trajectory_meta`` re-read every
    ancestor stage's trajectory (~1.4 GB on a lineage with three relax stages) on
    every call and bypassed the cache added to stop exactly that."""
    return count_trajectory_frames(path)


def composite_trajectory_meta(design, stages, max_frames: int = 200) -> dict:
    """Lightweight metadata for the composite trajectory — ``{n_frames, markers,
    stages, n_nucleotides}`` — WITHOUT reading/aligning any coordinates. Replicates
    composite_trajectory's seed-prepend + per-stage downsample using only frame
    COUNTS, so n_frames + marker frame indices match the full composite exactly.
    Lets the trajectory-keyframe slider size itself in milliseconds instead of
    downloading the multi-MB trajectory."""
    from backend.physics.oxdna_interface import _strand_nucleotide_order

    # Full keys (loop copies distinct) so n_nucleotides matches composite_trajectory's.
    key_list = list(dict.fromkeys(_strand_nucleotide_order(design)))
    per_stage = []
    for item in stages:
        name, kind, path = item[0], item[1], item[2]
        marker_label = item[3] if len(item) > 3 else None
        field = item[4] if len(item) > 4 else None
        per_stage.append({"name": name, "kind": kind,
                          "count": _count_dat_frames(path), "marker_label": marker_label,
                          "field": field})
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
        # Mirrors _aligned_downsampled_frames._keep_for, including the
        # max_frames <= 0 → UNLIMITED case, so the slider matches the payload.
        keep = c if (max_frames <= 0 or total <= max_frames) \
            else max(1, round(c * max_frames / total))
        if out_n:
            markers.append({"frame": out_n, "label": s.get("marker_label") or f"→ {s['kind']}",
                            "kind": s["kind"], "stage_name": s["name"]})
        out_stages.append({"name": s["name"], "kind": s["kind"], "n_frames": keep,
                           "field": s.get("field")})
        out_n += keep
    return {"n_frames": out_n, "n_nucleotides": len(key_list),
            "stages": out_stages, "markers": markers}


def _frame_atomistic_overrides(design, frame: dict, base_orient: str = "design_axis"):
    """Build (nuc_pos_override, axis_override) for one relaxed/trajectory frame.

    ``base_orient`` is forwarded to ``deformed_helix_axes`` and selects the base
    stacking-axis source for the DUPLEX path (``"oxdna_a3"`` = oxDNA's own a3, which
    removes the ~12° off-axis tilt the design-axis tangent carries; see that function).

    Positions each nucleotide at its true backbone site reconstructed from the oxDNA
    CM (``oxdna_backbone_site``), and supplies a Gaussian-smoothed DEFORMED helix
    centerline so the all-atom base orientation is derived against the BENT axis
    (``_atom_frame`` measures the radial vs the centerline) — the validated
    reconstruction the NAMD-seed path uses.

    NOTE — why NOT the full per-nucleotide oxDNA a1/a3 rigid-frame placer: that placer
    (``build_atomistic_model(frame_override=…)``, the 2026-06-21 first cut) collapsed
    base pairs on real relaxed frames (WC C1'–C1' 0.48 nm vs 0.94 nm here) because
    oxDNA's relaxed a1 does not map onto the all-atom base direction the calibration
    assumed, AND each base was stamped to its OWN a3 (FWD/REV a3 are only ~157° apart —
    real propeller — so per-base stamping tilts the two half-bases inconsistently and
    folds them together).  The axis-derived path below keeps the radial/position
    machinery (correct WC pairing) and instead corrects only the base STACKING axis
    (``e_z``) via ``base_orient`` (see ``deformed_helix_axes``): ``"oxdna_a3"`` (the
    DISPLAY default) uses the pair's SHARED a3 (``a3_fwd − a3_rev``), which removes the
    ~12° off-axis tilt of the ``design_axis`` centerline tangent while preserving
    pairing (measured 0.96 nm, no collapse).  The long sequential O3'→P bonds are
    handled separately by ``close_backbone=True`` (display-only backbone closure),
    which made the σ per-domain position smoother (a prior band-aid) unnecessary."""
    from backend.physics.oxdna_interface import (
        oxdna_backbone_site, _XB_SENTINEL, is_extension_key, is_synthetic_nuc_key,
    )
    from backend.core.cg_to_atomistic import deformed_helix_axes

    def _sited(rec) -> bool:
        return (rec.get("backbone_position") is not None
                and rec.get("a1") is not None and rec.get("a3") is not None)

    # Crossover extra-base inserts: keyed (_XB_SENTINEL, crossover_id, k).  Their
    # backbone-site positions drive the heavy-rep placement; they are EXCLUDED from
    # frame3 (real-nucleotide overrides only) so deformed_helix_axes never forms a
    # junk "__xb__" helix group.
    xb_pos_override = {
        (key[1], key[2]): {
            "cm": np.asarray(rec["backbone_position"], dtype=float),
            "position": oxdna_backbone_site(
                rec["backbone_position"], rec["a1"], rec["a3"]),
            "a1": np.asarray(rec["a1"], dtype=float),
            "a3": np.asarray(rec["a3"], dtype=float),
        }
        for key, rec in frame.items()
        if key[0] == _XB_SENTINEL and _sited(rec)
    }
    # Strand-extension tail beads: keyed ("__ext_<id>", bead_index, direction).  Same
    # deal — they place the heavy rep's tail residues, but must NOT reach frame3.
    # NOTE an extension key is a 3-tuple whose bp_index is an int >= 0, so it passes
    # every `isinstance(k[1], int)` filter written to catch __xb__: it has to be
    # excluded EXPLICITLY or deformed_helix_axes builds a junk one-nucleotide "helix".
    ext_pos_override = {
        (key[0][len("__ext_"):], key[1]): {
            "cm": np.asarray(rec["backbone_position"], dtype=float),
            "position": oxdna_backbone_site(
                rec["backbone_position"], rec["a1"], rec["a3"]),
            "a1": np.asarray(rec["a1"], dtype=float),
            "a3": np.asarray(rec["a3"], dtype=float),
        }
        for key, rec in frame.items()
        if is_extension_key(key) and _sited(rec)
    }
    # Collapse loop-insertion copies to their 3-tuple base (last copy wins) — both the
    # backbone-site override and deformed_helix_axes are keyed by (helix, bp, dir).
    frame3 = {key[:3]: rec for key, rec in frame.items()
              if not is_synthetic_nuc_key(key) and _sited(rec)}
    nuc_pos_override = {
        key: oxdna_backbone_site(rec["backbone_position"], rec["a1"], rec["a3"])
        for key, rec in frame3.items()
    }
    axis_override = deformed_helix_axes(design, frame3, sigma=2.0, base_orient=base_orient)
    return nuc_pos_override, axis_override, xb_pos_override, ext_pos_override


def _ssdna_frame_override(design, frame: dict) -> dict:
    """Build a per-nucleotide oxDNA a1/a3 rigid-frame override for the UNPAIRED (ssDNA)
    nucleotides in a relaxed frame — the free overhangs / tails / loops.

    The axis-derived display placement (``_frame_atomistic_overrides`` + ``_atom_frame``)
    fits a helix centerline and measures each base's radial against it.  For floppy ssDNA
    there is no helix to fit, so the centerline is meaningless and those nucleotides are
    flung tens of nm off their true simulated site (VoltronCore: ssDNA max 74 nm).  ssDNA
    has NO Watson–Crick partner, so the a1/a3 rigid stamp — rejected for DUPLEX because it
    collapses base pairs — places it EXACTLY at the relaxed pose (max drops to ~1.5 nm).
    So: rigid-stamp the unpaired nucleotides, leave the *formed* duplex on the axis
    path.  "Formed" is deliberately a geometric test, not merely the presence of
    the opposite design key.  A locally melted designed pair still has both keys;
    treating it as duplex makes ``deformed_helix_axes`` combine two particles that
    can be many nanometres apart and invents a third, unrelated all-atom pose.

    Returns ``{(helix, bp, dir[, copy]): (CM, a1, a3)}`` for unpaired real nucleotides."""
    import numpy as _np
    from backend.physics.oxdna_interface import (
        _strand_nucleotide_order, is_synthetic_nuc_key, topology_rows,
        oxdna_backbone_site,
    )
    from backend.core.atomistic import _extra_base_frame

    def _real(k) -> bool:
        return (isinstance(k, tuple) and len(k) >= 3 and isinstance(k[1], int)
                and not is_synthetic_nuc_key(k))

    present = {k[:3] for k in frame if _real(k)}
    order = _strand_nucleotide_order(design)
    rows, _ = topology_rows(design)

    def _site(k):
        v = frame.get(k)
        if v is None or v.get("backbone_position") is None:
            return None
        if v.get("a1") is not None and v.get("a3") is not None:
            return oxdna_backbone_site(v["backbone_position"], v["a1"], v["a3"])
        return np.asarray(v["backbone_position"], float)

    # A single wildly displaced particle is more likely a broken/incomplete frame
    # and historically stays on the guarded axis path (the validation audit relies
    # on that behavior).  Local melting is a segment phenomenon: require at least
    # two covalently adjacent designed pairs to be separated before switching their
    # residues to independent rigid frames.
    separated_pairs: set[tuple] = set()
    for k in order:
        if not _real(k):
            continue
        v0 = frame.get(k)
        h0, bp0, d0 = k[:3]
        other0 = (h0, bp0, "REVERSE" if d0 == "FORWARD" else "FORWARD")
        v1 = frame.get(other0)
        if (v0 is None or v1 is None or v0.get("backbone_position") is None
                or v1.get("backbone_position") is None or v0.get("a1") is None
                or v1.get("a1") is None):
            continue
        b0 = (_np.asarray(v0["backbone_position"], float)
              + OXDNA_BASE_SITE_NM * _np.asarray(v0["a1"], float))
        b1 = (_np.asarray(v1["backbone_position"], float)
              + OXDNA_BASE_SITE_NM * _np.asarray(v1["a1"], float))
        if float(_np.linalg.norm(b0 - b1)) > DUPLEX_AXIS_MAX_BASE_SEPARATION_NM:
            separated_pairs.add(k[:3])

    melted_segment: set[tuple] = set()
    for idx, k in enumerate(order):
        if k[:3] not in separated_pairs:
            continue
        _strand, _base, n3, n5 = rows[idx]
        neighbours = (order[j][:3] for j in (n3, n5) if j >= 0 and _real(order[j]))
        if any(nk in separated_pairs for nk in neighbours):
            melted_segment.add(k[:3])

    fo: dict = {}
    for idx, k in enumerate(order):
        v = frame.get(k)
        if not _real(k):
            continue
        if v is None:
            continue
        h, bp, d = k[:3]
        other = "REVERSE" if d == "FORWARD" else "FORWARD"
        partner_key = (h, bp, other)
        if partner_key in present:
            if k[:3] in melted_segment:
                pass  # locally melted duplex segment → independent rigid frame below
            else:
                continue                       # formed/near or isolated outlier → shared axis
            partner_site = _site(partner_key)
            # Backbone sites remain about a duplex diameter apart even for a formed
            # pair, so compare oxDNA's actual base interaction sites instead.  The
            # display cutoff is intentionally looser than hydrogen-bond retention:
            # a distorted-but-near pair still has a meaningful shared helix axis.
            partner = frame.get(partner_key)
            if (partner is not None and partner_site is not None
                    and v.get("backbone_position") is not None and v.get("a1") is not None
                    and partner.get("backbone_position") is not None
                    and partner.get("a1") is not None):
                base = (_np.asarray(v["backbone_position"], float)
                        + OXDNA_BASE_SITE_NM * _np.asarray(v["a1"], float))
                partner_base = (_np.asarray(partner["backbone_position"], float)
                                + OXDNA_BASE_SITE_NM * _np.asarray(partner["a1"], float))
                if (float(_np.linalg.norm(base - partner_base))
                        <= DUPLEX_AXIS_MAX_BASE_SEPARATION_NM):
                    continue                           # defensive: formed duplex → axis path
        if (v.get("backbone_position") is None or v.get("a1") is None or v.get("a3") is None):
            continue
        site = _site(k)
        if site is None:
            continue
        _strand, _base, n3, n5 = rows[idx]
        p5 = _site(order[n5]) if n5 >= 0 else None
        p3 = _site(order[n3]) if n3 >= 0 else None
        if p5 is not None and p3 is not None:
            chain_dir = p3 - p5
        elif p3 is not None:
            chain_dir = p3 - site
        elif p5 is not None:
            chain_dir = site - p5
        else:
            chain_dir = np.asarray(v["a3"], float)
        if float(np.linalg.norm(chain_dir)) < 1e-9:
            chain_dir = np.asarray(v["a3"], float)
        # a1 points toward the base in oxDNA and supplies the base-facing/bow
        # direction; the strand tangent independently fixes ribose polarity.
        fo[k] = _extra_base_frame(
            np.asarray(site, float), np.asarray(chain_dir, float),
            np.asarray(v["a1"], float),
        )
    return fo


# Base stacking-axis source for the relaxed-frame DISPLAY + trajectory-export
# reconstruction (NOT the clash-tuned NAMD seed).  "oxdna_a3" uses oxDNA's own a3
# vectors for e_z, removing the ~12° off-axis tilt the design-axis tangent injects
# (which pushed the displayed base inclination into the A-form range).  Override with
# NADOC_ATOMISTIC_BASE_ORIENT=design_axis (+ server restart) to revert to the old look.
_DISPLAY_BASE_ORIENT = os.environ.get("NADOC_ATOMISTIC_BASE_ORIENT", "oxdna_a3")


def build_display_model(design, frame: dict, frame_sink: dict | None = None,
                        close_backbone: bool = True, base_orient: str | None = None):
    """The canonical relaxed-frame DISPLAY reconstruction — ONE builder shared by the
    atomistic/surface display sinks AND the validation audit, so what's measured is
    exactly what's drawn.  Axis-derived base placement (correct WC pairing/stacking)
    + display-only backbone closure (connected O3'→P).  Atom serial ordering is
    identical to ``build_atomistic_model(design)`` (overrides change positions, never
    topology), so the renderer's serial-keyed bond list stays valid.

    ``base_orient`` (default ``_DISPLAY_BASE_ORIENT``) picks the duplex base
    stacking-axis source — ``"oxdna_a3"`` restores the ideal-build base orientation
    from oxDNA's a3 (fixes the A-form-range display tilt); ``"design_axis"`` is the
    legacy off-axis tangent.  ``frame_sink`` (out-param): if given, receives
    ``{(h,bp,dir,copy): (origin, R)}`` — the per-nucleotide UNDEFORMED rigid frame —
    for the fast display path (``display_frames_payload``)."""
    from backend.core.atomistic import build_atomistic_model
    orient = base_orient if base_orient is not None else _DISPLAY_BASE_ORIENT
    (nuc_pos_override, axis_override,
     xb_pos_override, ext_pos_override) = _frame_atomistic_overrides(design, frame, base_orient=orient)
    # Anchor floppy UNPAIRED ssDNA (overhangs/tails/loops) at its true relaxed pose via the
    # a1/a3 rigid stamp — the axis-derived path has no helix to fit there and flings it tens
    # of nm off.  Paired duplex stays on the axis path (correct WC pairing).
    frame_override = _ssdna_frame_override(design, frame)
    return build_atomistic_model(
        design, nuc_pos_override=nuc_pos_override, axis_override=axis_override,
        frame_override=frame_override,
        xb_pos_override=xb_pos_override, ext_pos_override=ext_pos_override,
        close_backbone=close_backbone, relaxed_oxdna_phase=True, frame_sink=frame_sink,
        fast_bridges=True,   # DISPLAY: cheap interpolated phosphate linkers (6× faster; ≤2.4 Å at junctions)
        # The relaxed CG override already supplies each nucleotide's FINAL world position
        # (deformed + cluster-transformed, then simulated) and the axis is fit from those
        # positions — so DON'T re-apply the design's deformation/cluster transform, which
        # would DOUBLE it on the clustered helices (VoltronCore: the 2×3 cluster shifted
        # ~3.2 nm vs the CG display).  Same reason the oxDNA/mrDNA seed path uses False.
        apply_design_geometry=False)


def display_frames_payload(design, frame: dict) -> dict:
    """Compact per-frame payload for the FAST CG→atomistic display path: per-nucleotide
    rigid frames (origin + R) plus the small set of non-rigid atom positions, instead
    of every atom's XYZ.  The client holds the design-fixed ``atomistic_stamp_descriptor``
    (fetched once) and expands ``world = origin + R @ local`` for the rigid majority.

    Runs the AUTHORITATIVE ``build_display_model`` once (memoised upstream by the route),
    so the non-rigid coordinates are byte-exact and the rigid frames come from the same
    loop.  ``build_display_model`` uses ``apply_design_geometry=False`` (the sim frame is
    already the FINAL deformed + cluster-transformed world, and the axis is fit from it),
    so the recorded frames are final as-is — no deformation/cluster fold is needed.

    Returns ``{ready, n_nuc, frames:[12*n_nuc], nonrigid_xyz:[3*k], topology_hash}``
    where ``frames`` is ``origin[3] + R[9]`` (row-major) per nucleotide in the
    descriptor's ``nuc_keys`` order.  Reproduces ``frame_atomistic_flat`` to ~1e-4 nm
    (see ``tests/test_atomistic_display_split.py``)."""
    from backend.core.atomistic import atomistic_stamp_descriptor

    desc = atomistic_stamp_descriptor(design)
    sink: dict = {}
    model = build_display_model(design, frame, frame_sink=sink)

    frames: list = []
    for key in desc.nuc_keys:
        origin, R = sink[key]
        frames.extend((round(float(origin[0]), 6), round(float(origin[1]), 6), round(float(origin[2]), 6),
                       round(float(R[0, 0]), 7), round(float(R[0, 1]), 7), round(float(R[0, 2]), 7),
                       round(float(R[1, 0]), 7), round(float(R[1, 1]), 7), round(float(R[1, 2]), 7),
                       round(float(R[2, 0]), 7), round(float(R[2, 1]), 7), round(float(R[2, 2]), 7)))

    atoms = model.atoms
    nonrigid_xyz: list = []
    for s in desc.nonrigid_serials:
        a = atoms[s]
        nonrigid_xyz.extend((round(a.x, 6), round(a.y, 6), round(a.z, 6)))

    return {"ready": True, "n_nuc": len(desc.nuc_keys), "frames": frames,
            "nonrigid_xyz": nonrigid_xyz, "topology_hash": desc.topology_hash}


def frame_atomistic_flat(design, frame: dict) -> list:
    """Atomistic flat-XYZ (atom-serial order, nm) for ONE per-nucleotide frame
    ``{key: {backbone_position(CM), a1, a3}}`` — the SAME wire format as
    ``/design/features/atomistic-batch``. Shared sink for the composite trajectory
    AND the single relaxed-display / rmsf-average frames."""
    from backend.core.atomistic import atomistic_positions_flat
    return atomistic_positions_flat(build_display_model(design, frame))


def _vertex_rmsf(mesh, atoms, rmsf_by_key: dict) -> list:
    """Per-vertex RMSF (nm) via nearest-atom KD-tree lookup — each surface vertex
    inherits the RMSF of its closest atom's nucleotide so the frontend can colour
    the mesh by the SAME viridis ramp/scale as the beads. Mirrors
    ``surface._assign_vertex_strand_ids`` but resolves to the flexibility value."""
    import numpy as np
    from scipy.spatial import cKDTree

    pos = np.array([[a.x, a.y, a.z] for a in atoms], dtype=np.float64)
    tree = cKDTree(pos)
    _, nn = tree.query(mesh.vertices, workers=-1)
    out: list[float] = []
    for i in nn:
        a = atoms[int(i)]
        d = a.direction.value if hasattr(a.direction, "value") else a.direction
        out.append(round(float(rmsf_by_key.get((a.helix_id, a.bp_index, d), 0.0)), 5))
    return out


def _strand_id_map(design) -> dict:
    """{(helix_id, bp_index, direction): strand_id} from design geometry — for colouring the
    coarse CG-bead surface (which has no all-atom model to carry strand ids)."""
    from backend.core.design_geometry import _geometry_for_design
    return {(g["helix_id"], g["bp_index"], g["direction"]): g.get("strand_id", "")
            for g in _geometry_for_design(design)}


def _cg_beads_from_frame(design, frame: dict) -> list:
    """Coarse per-nucleotide spheres (backbone site + base site) from a relaxed FRAME — the
    fast CG-surface input, skipping the ~300k-atom rebuild.  Base site ≈ CM + a1·0.34 nm
    (oxDNA POS_BASE); backbone site via oxdna_backbone_site."""
    from backend.physics.oxdna_interface import oxdna_backbone_site, is_synthetic_nuc_key
    from backend.core.surface import make_cg_bead
    _BASE_OFF_NM = 0.34
    sid = _strand_id_map(design)
    beads: list = []
    for k, v in frame.items():
        if not (isinstance(k, tuple) and len(k) >= 3 and isinstance(k[1], int)
                and not is_synthetic_nuc_key(k)):
            continue
        if v.get("backbone_position") is None or v.get("a1") is None or v.get("a3") is None:
            continue
        cm = np.asarray(v["backbone_position"], float)
        a1 = np.asarray(v["a1"], float)
        bb = oxdna_backbone_site(cm, a1, np.asarray(v["a3"], float))
        base = cm + a1 * _BASE_OFF_NM
        s = sid.get((k[0], k[1], k[2]), "")
        for p in (bb, base):
            beads.append(make_cg_bead(p[0], p[1], p[2], strand_id=s,
                                      helix_id=k[0], bp_index=k[1], direction=k[2]))
    return beads


def frame_surface_json(design, frame: dict, color_mode: str = "strand",
                       probe_radius: float = 0.28, grid_spacing: float = 0.20,
                       radius_inflate: float = 1.30, smooth: int = 15,
                       rmsf_by_key: dict | None = None, detail: str = "coarse") -> dict:
    """Molecular surface ``{vertices, faces, vertex_colors?|vertex_rmsf?}`` for ONE
    per-nucleotide frame — the SAME wire format as ``/design/features/surface-batch``.
    Shared sink for the composite trajectory AND the single relaxed/rmsf frames.
    ``color_mode='rmsf'`` (with ``rmsf_by_key``) emits a per-vertex RMSF list so the
    flexibility map colours the surface the same way it colours the beads.

    ``detail='coarse'`` (default) builds the envelope from ~2 CG spheres/nucleotide (no
    all-atom rebuild — ~3× faster, ~2.8 Å from the atomic surface); ``'fine'`` uses the
    full all-atom model."""
    from backend.core.surface import (compute_surface, smooth_mesh, surface_to_json,
                                       adaptive_grid_spacing, cg_surface_mesh,
                                       vertex_index_tables)
    if detail == "coarse":
        beads = _cg_beads_from_frame(design, frame)
        mesh = cg_surface_mesh(beads, grid_spacing=grid_spacing, probe_radius=probe_radius, smooth=smooth)
        rmsf_atoms = beads
    else:
        # Surface = a VdW envelope, so it needs atom POSITIONS, not a connected backbone —
        # skip the phosphate-linker closure (close_backbone=False) to shave the build.
        model = build_display_model(design, frame, close_backbone=False)
        if detail == "chimerax":
            # EXPERIMENTAL ChimeraX-quality SES: fine 0.5 Å grid + 1.4 Å probe + true VdW.
            from backend.core.surface import (CHIMERAX_GRID_SPACING, CHIMERAX_PROBE_RADIUS,
                                              CHIMERAX_RADIUS_SCALE, CHIMERAX_VOXEL_CAP,
                                              CHIMERAX_MAX_SPACING, CHIMERAX_SMOOTH)
            gs = adaptive_grid_spacing(model.atoms, CHIMERAX_GRID_SPACING,
                                       cap_voxels=CHIMERAX_VOXEL_CAP, max_spacing=CHIMERAX_MAX_SPACING)
            mesh = compute_surface(model.atoms, grid_spacing=gs,
                                   probe_radius=CHIMERAX_PROBE_RADIUS, radius_scale=CHIMERAX_RADIUS_SCALE)
            mesh = smooth_mesh(mesh, iterations=CHIMERAX_SMOOTH)
        else:
            gs = adaptive_grid_spacing(model.atoms, grid_spacing)
            mesh = compute_surface(model.atoms, grid_spacing=gs,
                                   probe_radius=probe_radius, radius_scale=1.2 * radius_inflate)
            mesh = smooth_mesh(mesh, iterations=smooth)
        rmsf_atoms = model.atoms
    entry = {"vertices": [round(float(v), 5) for v in mesh.vertices.ravel()],
             "faces": [int(f) for f in mesh.faces.ravel()]}
    # Per-vertex identity, exactly as the DESIGN surface ships it. Without it a simulated
    # surface carries no way to resolve a cluster, so per-cluster colour and opacity were
    # silently ignored on every engine overlay. Both the coarse (CG-bead) and fine
    # (all-atom) meshes above already carry it — this used to build `entry` by hand and
    # throw it away. Cheap: two int lists plus a small string table.
    entry.update(vertex_index_tables(mesh))
    if color_mode == "rmsf" and rmsf_by_key:
        entry["vertex_rmsf"] = _vertex_rmsf(mesh, rmsf_atoms, rmsf_by_key)
    elif color_mode == "strand":
        vc = surface_to_json(mesh, design, color_mode="strand").get("vertex_colors")
        if vc:
            entry["vertex_colors"] = [round(float(c), 4) for c in vc]
    return entry


def pack_surface_bin(data: dict) -> bytes:
    """Pack a surface mesh dict ({vertices, faces, vertex_colors?|vertex_rmsf?}) into a
    compact little-endian binary blob — ~2× smaller than the JSON text AND no million-number
    ``JSON.parse`` on the client (it wraps the buffer as typed arrays directly).

    Layout:  uint32 magic(0x4E535246) · uint32 n_verts · uint32 n_faces · uint32 color_kind
             float32[n_verts*3] vertices · uint32[n_faces*3] faces
             color_kind 1 → uint8[n_verts*3] rgb(0-255) ; 2 → float32[n_verts] rmsf ; 0 → none
             uint32 strand_kind
             strand_kind 1 → uint32 table_len · bytes[table_len] (UTF-8 JSON strand-id list)
                            · uint32[n_verts] vertex_strand_index ; 0 → none
             uint32 nuc_kind
             nuc_kind 1 → uint32 table_len · bytes[table_len] (UTF-8 JSON "helix:bp:dir" list)
                            · uint32[n_verts] vertex_nuc_index ; 0 → none
    The trailing strand block lets a surface recolour client-side by strand/group/cluster
    WITHOUT a re-fetch. Both the design surface and the simulation-frame surfaces ship it.
    The nucleotide block (added 2026-08-01) is what makes per-CLUSTER colouring correct: a
    strand can span several clusters and the scaffold spans nearly all of them, so a
    strand-keyed lookup paints the whole scaffold one colour (LESSONS D15).

    There is deliberately NO version field. Both trailing blocks are optional and
    self-describing, so a decoder that predates one simply stops early — which is exactly
    how the nucleotide block was added without breaking anything.
    n_verts == 0 signals "not ready / empty"."""
    import struct
    v = np.asarray(data.get("vertices") or [], dtype=np.float32)
    f = np.asarray(data.get("faces") or [], dtype=np.uint32)
    nv, nf = v.size // 3, f.size // 3
    if data.get("vertex_colors"):
        rgb = np.clip(np.asarray(data["vertex_colors"], dtype=np.float32) * 255.0, 0, 255).astype(np.uint8)
        color_kind, color_bytes = 1, rgb.tobytes()
    elif data.get("vertex_rmsf"):
        color_kind, color_bytes = 2, np.asarray(data["vertex_rmsf"], dtype=np.float32).tobytes()
    else:
        color_kind, color_bytes = 0, b""
    import json

    def _index_block(table_key: str, index_key: str) -> bytes:
        """``u32 kind · u32 tableLen · UTF-8 JSON string table · u32[nVerts] index``,
        or a bare ``u32 0`` when absent. Two of these are appended back to back — the
        strand block first (unchanged since the format shipped), then the nucleotide
        block. Both are optional and self-describing, which is what makes this
        extensible without a magic/version bump: an OLD decoder stops after the strand
        block and simply never sees the second one."""
        table = data.get(table_key)
        index = data.get(index_key)
        if not nv or table is None or index is None:
            return struct.pack("<I", 0)
        tbl_bytes = json.dumps(table).encode("utf-8")
        return (struct.pack("<II", 1, len(tbl_bytes)) + tbl_bytes
                + np.asarray(index, dtype=np.uint32).tobytes())

    strand_block = _index_block("vertex_strand_index_table", "vertex_strand_index")
    # Per-vertex NUCLEOTIDE key (helix:bp:direction). Lets per-cluster colouring resolve
    # a strand that spans several clusters — the scaffold spans nearly all of them
    # (LESSONS D15). Absent from producers that have no nucleotide identity (the oxDNA
    # frame-surface overlay), and the client falls back to the strand table.
    nuc_block = _index_block("vertex_nuc_index_table", "vertex_nuc_index")
    return (struct.pack("<IIII", 0x4E535246, nv, nf, color_kind)
            + v.tobytes() + f.tobytes() + color_bytes + strand_block + nuc_block)


def composite_trajectory_atomistic(design, stages, reference_conf_path,
                                   frame_indices, max_frames: int = 200,
                                   align: bool = True,
                                   n_trailing_extra: int = 0,
                                   trailing_extra_strand_length: int = 0,
                                   progress=None) -> dict:
    """Per-frame atomistic flat-XYZ for the requested composite-frame indices.
    Returns ``{ "<idx>": [x0,y0,z0, …] }`` — the SAME wire format as
    ``/design/features/atomistic-batch`` (atom-serial order, nm). Frame indices
    match ``composite_trajectory``'s ``frames`` ordering exactly.

    ``progress(done, total)`` (optional) fires after each frame's rebuild. The rebuild
    is the long pole for a big export — without a callback the caller's progress bar
    has nothing to report for minutes and reads as a hung job. It is NOT called for
    the alignment pass below, which is a single opaque unwrap+fit with no frame loop.

    Materialises EVERY requested frame at once (~4 MB per 100k atoms), so a large range
    is a large dict. Callers that consume frames one at a time — the trajectory-range
    export — should use ``iter_composite_trajectory_atomistic`` instead."""
    return {str(idx): flat for idx, flat in iter_composite_trajectory_atomistic(
        design, stages, reference_conf_path, frame_indices, max_frames=max_frames,
        align=align, n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length, progress=progress)}


def iter_composite_trajectory_atomistic(design, stages, reference_conf_path,
                                        frame_indices, max_frames: int = 200,
                                        align: bool = True,
                                        n_trailing_extra: int = 0,
                                        trailing_extra_strand_length: int = 0,
                                        progress=None, cache: bool = True):
    """Streaming sibling of ``composite_trajectory_atomistic``: yields ``(idx, flat)`` one
    frame at a time, in ascending index order, so a consumer can write each frame out and
    drop it instead of holding the whole range in memory.

    ``cache=False`` skips the shared display-output cache. A 51-frame export of a 330k-atom
    design is ~50 M elements against a 6 M budget, so caching it evicts the entire live
    display cache to retain ~6 export frames nobody will request again — all cost, no hit.
    Interactive callers (which re-request the frames they just scrubbed) keep ``cache=True``.
    """
    _, ordered, _, _ = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames, copies=True, align=align,
        n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)
    akey = (_aligned_cache_key(stages, reference_conf_path, max_frames, True),
            bool(align), int(n_trailing_extra), int(trailing_extra_strand_length))
    wanted = sorted(set(int(i) for i in frame_indices))
    # Count against every requested index (not just the in-range ones) so a range that
    # overruns the trajectory still walks the bar to 100% instead of stopping short.
    for done, idx in enumerate(wanted, start=1):
        if 0 <= idx < len(ordered):
            ck = ("cta", akey, idx)
            payload = _display_out_get(ck) if cache else None
            if payload is None:
                payload = frame_atomistic_flat(design, ordered[idx])
                if cache:
                    _display_out_put(ck, payload)
            yield idx, payload
        # Fires as the consumer asks for the next frame, i.e. once frame `idx` is written.
        if progress:
            progress(done, len(wanted))


def composite_trajectory_surface(design, stages, reference_conf_path, frame_indices,
                                 color_mode: str = "strand", probe_radius: float = 0.28,
                                 grid_spacing: float = 0.20, radius_inflate: float = 1.30,
                                 smooth: int = 15, max_frames: int = 200,
                                 align: bool = True,
                                 n_trailing_extra: int = 0,
                                 trailing_extra_strand_length: int = 0) -> dict:
    """Per-frame molecular surface for the requested composite-frame indices.
    Returns ``{ "<idx>": {vertices, faces, vertex_colors?} }`` — the SAME wire
    format as ``/design/features/surface-batch``. Topology can vary per frame
    (marching cubes); the frontend rebuilds the buffer on a count change."""
    _, ordered, _, _ = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames, copies=True, align=align,
        n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)
    akey = (_aligned_cache_key(stages, reference_conf_path, max_frames, True),
            bool(align), int(n_trailing_extra), int(trailing_extra_strand_length))
    sparams = (color_mode, round(probe_radius, 4), round(grid_spacing, 4),
               round(radius_inflate, 4), int(smooth))
    out: dict[str, dict] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= len(ordered):
            continue
        ck = ("cts", akey, idx, sparams)
        payload = _display_out_get(ck)
        if payload is None:
            payload = frame_surface_json(
                design, ordered[idx], color_mode, probe_radius, grid_spacing,
                radius_inflate, smooth)
            _display_out_put(ck, payload)
        out[str(idx)] = payload
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


def backbone_strain_field(
    design: Design,
    full_map: dict[tuple[str, int, str], dict],
    *,
    r0_units: float = FENE_R0_OXDNA2,
) -> dict[tuple[str, int], float]:
    """PER-(helix, bp) backbone strain of a relaxed/mean structure — the spatial
    breakdown of :func:`backbone_fene_stretch`'s scalar maximum.

    For every bonded backbone pair, the strain is ``|bond_length - r0|`` in oxDNA units
    (deviation of the reconstructed backbone-site spacing from the relaxed B-DNA value;
    0 == relaxed).  Each bond's strain is attributed to BOTH its nucleotides as the MAX
    over that nucleotide's incident bonds, then the two strands at a ``(helix, bp)``
    column are collapsed by MAX (worst-case local tensile strain at that position).

    This is the "where is the structure mechanically stressed" field that biases regional
    skip placement (a deletion adds local tensile strain, so placement is steered AWAY
    from already-strained sites — see :mod:`backend.core.regional_skip_placer`).
    Read-only over the Physical layer; never written back into topology.
    """
    pairs = backbone_bond_pairs(design)
    per_nt: dict[tuple[str, int, str], float] = {}
    for a, b in pairs:
        pa = full_map.get(a)
        pb = full_map.get(b)
        if pa is None or pb is None:
            continue
        sa = oxdna_backbone_site(pa["backbone_position"], pa["a1"], pa["a3"])
        sb = oxdna_backbone_site(pb["backbone_position"], pb["a1"], pb["a3"])
        strain = abs(float(np.linalg.norm(sa - sb)) / OXDNA_LENGTH_UNIT - r0_units)
        for k in (a, b):
            if strain > per_nt.get(k, -1.0):
                per_nt[k] = strain
    out: dict[tuple[str, int], float] = {}
    for (helix_id, bp_index, _direction), s in per_nt.items():
        key = (helix_id, int(bp_index))
        if s > out.get(key, -1.0):
            out[key] = s
    return out


def strain_field(
    design: Design,
    full_map: dict[tuple, dict],
    *,
    metric: str = "backbone",
    r0_units: float = FENE_R0_OXDNA2,
    wc_r0_units: float = HYDR_R0_OXDNA2,
) -> dict[tuple[str, int, str], float]:
    """PER-NUCLEOTIDE signed strain of ONE configuration, keyed by the 3-tuple
    ``(helix_id, bp_index, direction)`` — the per-frame kernel behind
    :func:`strain_map` and :func:`production_strain_field`.

    See :func:`strain_map` for the definition of each ``metric``.  Nucleotides with
    nothing measurable (no bonded partner in this frame / no designed WC partner) are
    ABSENT from the result rather than reported as 0.  Pure geometry over ``full_map``
    (``{key: {backbone_position (CM, nm), a1, a3}}``); loop-copy 4-tuple keys collapse
    onto their base 3-tuple, since :func:`backbone_bond_pairs` does the same.
    """
    if metric not in ("backbone", "wc"):
        raise ValueError(f"strain_field: unknown metric {metric!r} (expected 'backbone' or 'wc')")
    base = _strain_base_map(full_map)
    keys = list(base)
    ia, ib = _strain_index(design, keys, metric)
    if not ia.size:
        return {}
    arrs = _gather_frame(base, keys)
    if arrs is None:
        return {}
    vals, _att, _rej = _strain_values(*arrs, ia, ib, metric=metric,
                                      r0_units=r0_units, wc_r0_units=wc_r0_units)
    return {k: float(v) for k, v in zip(keys, vals) if not np.isnan(v)}


def _strain_base_map(full_map: dict[tuple, dict]) -> dict[tuple, dict]:
    """Copy-collapsed physics index for the strain metrics: prefer copy 0 (the real
    nucleotide) at each ``(helix, bp, direction)``, else whichever copy is present.
    :func:`backbone_bond_pairs` collapses loop copies the same way."""
    base: dict[tuple, dict] = {}
    for k, v in full_map.items():
        k3 = (k[0], k[1], k[2])
        if k3 not in base or (len(k) > 3 and int(k[3]) == 0):
            base[k3] = v
    return base


def _strain_index(design: Design, keys: list[tuple], metric: str):
    """Integer endpoint arrays ``(ia, ib)`` into ``keys`` for every measurable strain
    element: bonded 3′-neighbour pairs (``backbone``) or designed WC partners (``wc``).

    Built ONCE for a key ordering and reused across every frame of a trajectory — the
    topology it encodes cannot change mid-run, and rebuilding it per frame (a full
    strand walk) dominated the cost of a trajectory-averaged map."""
    pos = {k: i for i, k in enumerate(keys)}
    if metric == "backbone":
        ia, ib = [], []
        for a, b in backbone_bond_pairs(design):
            i, j = pos.get(a), pos.get(b)
            if i is None or j is None:
                continue
            ia.append(i)
            ib.append(j)
    else:
        # WC pairing is defined only for REAL (helix, bp) columns.  Synthetic particles —
        # crossover extra-base inserts and 5′/3′ strand-extension tail beads — are unpaired
        # ssDNA; an extension key is a 3-tuple carrying a direction string, so it would
        # otherwise be eligible to pair with anything sharing its synthetic helix id.
        fwd = {(k[0], k[1]): i for k, i in pos.items()
               if k[2] == "FORWARD" and not is_synthetic_nuc_key(k)}
        rev = {(k[0], k[1]): i for k, i in pos.items()
               if k[2] == "REVERSE" and not is_synthetic_nuc_key(k)}
        paired = sorted(fwd.keys() & rev.keys())
        ia = [fwd[p] for p in paired]
        ib = [rev[p] for p in paired]
    return np.asarray(ia, dtype=int), np.asarray(ib, dtype=int)


def _gather_frame(base: dict[tuple, dict], keys: list[tuple]):
    """``(cm, a1, a3)`` arrays aligned to ``keys``, or ``None`` if any key is missing
    from ``base`` (a ragged/half-written frame — the caller skips it)."""
    try:
        cm = np.array([base[k]["backbone_position"] for k in keys], dtype=float)
        a1 = np.array([base[k]["a1"] for k in keys], dtype=float)
        a3 = np.array([base[k]["a3"] for k in keys], dtype=float)
    except KeyError:
        return None
    return cm, a1, a3


def _fene_violation_fraction(cm, a1, a3, ia, ib, *, r0_units: float = FENE_R0_OXDNA2) -> float:
    """Fraction of BACKBONE bonds outside oxDNA's FENE window in one reconstructed frame.

    A production frame cannot contain even one such bond — the potential is undefined past
    ``r0 ± delta`` and oxDNA aborts at config load — so a nonzero fraction means the frame's
    PBC unwrap TORE the assembly: neighbouring bonded components snapped to different
    periodic images once the structure diffused far from the design reference.

    This is a per-frame QUALITY GATE for both strain metrics, not a backbone-only concern.
    ``wc`` has no physical bound of its own (a genuinely melted pair really does drift
    apart), so without this a torn frame contributes hundreds of percent of phantom pair
    stretch that is indistinguishable from real melting — measured on a resumed
    VoltronCoreScad run whose base-pair retention was 98.85 %, i.e. barely melted at all.
    """
    if not ia.size:
        return 0.0
    sites = oxdna_backbone_sites(cm, a1, a3)
    d = sites[ia] - sites[ib]
    s = np.sqrt((d * d).sum(axis=1)) / (OXDNA_LENGTH_UNIT * r0_units) - 1.0
    return float((np.abs(s) > (FENE_DELTA / r0_units)).mean())


def _strain_values(cm, a1, a3, ia, ib, *, metric: str,
                   r0_units: float = FENE_R0_OXDNA2,
                   wc_r0_units: float = HYDR_R0_OXDNA2):
    """Vectorized per-nucleotide strain for ONE gathered configuration, aligned to the
    same key order.  Returns ``(values, n_attempted, n_rejected)``; ``values`` is ``NaN``
    where nothing was measurable, and the two counts cover FENE-window rejection (see
    below; both 0 for ``wc``).

    Backbone strain is attributed to each endpoint by largest MAGNITUDE; that is done
    with a magnitude-sorted scatter (ascending, so the last write per nucleotide is its
    worst bond) rather than a per-bond Python loop."""
    keys_n = len(cm)
    n_attempted = 0
    n_rejected = 0
    if metric == "backbone":
        sites = oxdna_backbone_sites(cm, a1, a3)
        l0 = r0_units
    else:
        sites = cm + OXDNA_BASE_SITE_NM * a1
        l0 = wc_r0_units
    d = sites[ia] - sites[ib]
    s = np.sqrt((d * d).sum(axis=1)) / (OXDNA_LENGTH_UNIT * l0) - 1.0
    out = np.full(keys_n, np.nan)
    if metric == "backbone":
        # REJECT PHYSICALLY IMPOSSIBLE BONDS.  The FENE potential is only defined on
        # r0 ± delta; a production frame containing a bond outside that window cannot
        # exist — oxDNA aborts at config load on the first one.  Such a measurement is
        # therefore an artifact of FRAME RECONSTRUCTION, not of the simulation: the
        # PBC unwrap box-shifts each bonded component toward its reference image, and
        # once the assembly has diffused far from the design reference (late frames of
        # long/resumed runs) neighbouring components can snap to DIFFERENT images and be
        # torn apart, which reads as a bond of order the box size.  Averaging those in
        # poisons the field (measured: 38 % of nucleotides "FENE-impossible" on the last
        # frame of a resumed VoltronCoreScad run).  Drop the sample instead, so each
        # nucleotide averages over the frames it was reconstructed sanely in.
        # No such bound exists for `wc` — a melted pair genuinely does drift apart.
        keep = np.abs(s) <= (FENE_DELTA / l0)
        n_attempted = int(s.size)
        n_rejected = int(n_attempted - keep.sum())
        ia, ib, s = ia[keep], ib[keep], s[keep]
        idx = np.concatenate([ia, ib])
        vv = np.concatenate([s, s])
        order = np.argsort(np.abs(vv), kind="stable")   # ascending |s| → worst wins
        out[idx[order]] = vv[order]
    else:
        out[ia] = s
        out[ib] = s
    return out, n_attempted, n_rejected


def strain_map(
    design: Design,
    full_map: dict[tuple, dict],
    *,
    metric: str = "backbone",
    r0_units: float = FENE_R0_OXDNA2,
    wc_r0_units: float = HYDR_R0_OXDNA2,
    field: dict[tuple[str, int, str], float] | None = None,
) -> dict:
    """PER-NUCLEOTIDE LOCAL STRAIN of a relaxed/mean structure — the display feed for
    the oxDNA "strain map" false-colouring (the strain counterpart of
    :func:`geometry_deviation_map`).

    Strain is the SIGNED, DIMENSIONLESS engineering strain ``(L − L0) / L0`` about the
    metric's equilibrium length: ``0`` == relaxed, ``> 0`` == stretched (tension),
    ``< 0`` == compressed, ``0.1`` == 10 % over-extended.  A diverging colormap centred
    on 0 therefore reads directly as tension/compression.  Two metrics:

    ``backbone`` — FENE backbone-bond strain, ``L0 = r0_units``.  For every bonded
      3′-neighbour pair, ``L = |site_a − site_b|`` between the reconstructed BACKBONE SITES (the exact
      quantity oxDNA's FENE term acts on — the ``.dat`` centre of mass sits ~0.34 units
      inward and badly under-reads the bond).  Each bond's strain is attributed to BOTH
      its nucleotides as the value of largest MAGNITUDE over that nucleotide's incident
      bonds, so a junction reports its worst bond rather than an average that hides it.
      This is the per-nucleotide form of what :func:`backbone_strain_field` collapses
      per ``(helix, bp)``.  Highlights crossovers, skip/loop sites and forced
      connections the relaxation could not fully absorb.

    ``wc`` — Watson–Crick base-pair stretch, ``L0 = wc_r0_units`` (HYDR_R0).  At every
      designed ``(helix, bp)`` with both strands present, ``L = |base_site_F −
      base_site_R|`` (base site = ``CM + POS_BASE·a1``), attributed to both partners.
      Highlights melted, opening or mis-registered pairs — a fully melted pair reads
      several hundred percent, so the display's bounds are rescalable.  Nucleotides with
      no designed partner (ssDNA loops, overhangs, ragged ends) carry no WC strain and
      are OMITTED from the map.

    ``full_map`` is a ``{key: {backbone_position (CM, nm), a1, a3}}`` position map —
    a relaxed frame from ``read_configuration_full``, or the ``average_frame`` of
    :func:`production_rmsf`.  Keys may be the 3-tuple ``(helix, bp, direction)`` or the
    4-tuple loop-copy form; :func:`backbone_bond_pairs` collapses copies, so the physics
    is indexed by the 3-tuple (copy 0 wins) and the result is broadcast back to every
    copy at that position, so each loop bead still gets a colour.

    NEVER measure the strain OF a time-averaged structure: averaging positions collapses
    bond lengths (|⟨r_a⟩ − ⟨r_b⟩| ≤ ⟨|r_a − r_b|⟩), and the effect is not small — on a
    real 1-helix field run the mean structure reads −26 % mean backbone and −67 % mean WC
    strain where any single frame reads −1.8 % / +0.9 %.  So a trajectory map must pass
    the time-averaged FIELD via ``field=`` (see :func:`production_strain_field`) while
    ``full_map`` supplies only the DISPLAY geometry (the mean structure the RMSF and
    deviation maps also draw, so all three overlays sit in the same place).  With
    ``field=None`` the strain is computed from ``full_map`` itself — correct only when
    ``full_map`` is a single instantaneous configuration.

    Returns ``{positions: [{helix_id, bp_index, direction, copy, backbone_position, nx, ny,
    nz, strain, ss}], min_strain, max_strain, mean_strain, abs_max_strain,
    display_abs_strain, dsdna, n_shared, n_positions, metric, unit ("fraction"),
    r0_units}``.

    EVERY nucleotide in ``full_map`` is emitted — ``positions`` is the overlay's move list,
    not just its colour list — with ``strain: None`` where nothing was measurable and ``ss``
    marking designed single-stranded bases (see :func:`designed_ssdna_flags`).  ``n_shared``
    counts the MEASURED ones; ``dsdna`` repeats the statistics over the designed-duplex
    subset so the display can exclude ssDNA without a refetch.  Read-only over the Physical
    layer — never written back into topology.
    """
    if metric not in ("backbone", "wc"):
        raise ValueError(f"strain_map: unknown metric {metric!r} (expected 'backbone' or 'wc')")
    per3 = field if field is not None else strain_field(
        design, full_map, metric=metric, r0_units=r0_units, wc_r0_units=wc_r0_units)

    ss_of = designed_ssdna_flags(full_map)
    out: list[dict] = []
    vals: list[float] = []
    ds_vals: list[float] = []
    for k, v in full_map.items():
        # EVERY key is emitted, measured or not.  `positions` is the overlay's MOVE list as
        # well as its colour list: a nucleotide left out of it keeps its DESIGN coordinates
        # while the rest of the structure deforms to the simulated mean.  For `wc` that is
        # every unpaired base — ssDNA overhangs, unstapled scaffold loops, extension tails,
        # extra-base inserts — which would sit stranded in mid-air (measured: 2260 beads on
        # VoltronCoreScad).  Unmeasured nucleotides carry ``strain: None`` and simply get no
        # colour, so they ride along at their simulated positions in their native colour.
        s = per3.get((k[0], k[1], k[2]))
        a1 = np.asarray(v["a1"], dtype=float)
        site = oxdna_backbone_site(v["backbone_position"], a1, np.asarray(v["a3"], dtype=float))
        ss = ss_of(k)
        out.append({
            # Emitted RAW, exactly as /display does: a synthetic key's bp_index slot holds
            # a crossover id (extra bases) or a bead index (extension tails) and must not
            # be coerced — int() on a string crossover id would throw.
            "helix_id": k[0], "bp_index": k[1], "direction": k[2],
            "copy": int(k[3]) if len(k) > 3 else 0,
            "backbone_position": np.asarray(site, dtype=float).tolist(),
            "nx": float(a1[0]), "ny": float(a1[1]), "nz": float(a1[2]),
            "strain": s,
            "ss": ss,
        })
        if s is not None:
            vals.append(s)
            if not ss:
                ds_vals.append(s)

    unit_r0 = r0_units if metric == "backbone" else wc_r0_units
    if not vals:
        return {"positions": out, "min_strain": None, "max_strain": None,
                "mean_strain": None, "abs_max_strain": None, "display_abs_strain": None,
                "n_shared": 0, "n_positions": len(out), "dsdna": None,
                "metric": metric, "unit": "fraction", "r0_units": unit_r0}
    a = np.asarray(vals, dtype=float)
    return {"positions": out, "min_strain": float(a.min()), "max_strain": float(a.max()),
            "mean_strain": float(a.mean()), "abs_max_strain": float(np.abs(a).max()),
            "display_abs_strain": _display_strain_bound(a, metric),
            # Companion stats over the designed-dsDNA subset alone, so the "exclude ssDNA"
            # display option can rescale instantly without a refetch — and so a lone flailing
            # overhang cannot set the colour range for the duplex the user is inspecting.
            "dsdna": _strain_stats(ds_vals, metric),
            "n_shared": len(vals), "n_positions": len(out),
            "metric": metric, "unit": "fraction", "r0_units": unit_r0}


def _strain_stats(vals, metric: str) -> dict | None:
    """``{min,max,mean,abs_max,display_abs,n}`` for a strain subset, or None if empty."""
    if not len(vals):
        return None
    a = np.asarray(vals, dtype=float)
    return {"min_strain": float(a.min()), "max_strain": float(a.max()),
            "mean_strain": float(a.mean()), "abs_max_strain": float(np.abs(a).max()),
            "display_abs_strain": _display_strain_bound(a, metric), "n": int(a.size)}


def designed_ssdna_flags(full_map: dict[tuple, dict]):
    """``key -> True when that nucleotide is DESIGNED single-stranded``.

    Classification is TOPOLOGICAL, from the design's own nucleotide set (``full_map`` is
    keyed by the design walk, so presence in it *is* presence in the design) — never from
    how the simulation happened to end up.  A ``(helix, bp)`` column carrying nucleotides
    on BOTH directions is designed duplex; anything else is designed ssDNA:

      * an unstapled scaffold stretch — a deliberate ssDNA loop, not a defect
        (see ``memory/feedback_staples_are_user_intent.md``),
      * a single-stranded overhang,
      * a 5′/3′ extension tail or a crossover extra-base insert (synthetic keys, never
        paired by construction).

    Loop-insertion copies inherit their base ``(helix, bp)``'s classification, matching how
    the strain value itself is broadcast to copies.

    This is what lets the strain map colour ONLY the regions that are supposed to be duplex,
    so a disrupted one stands out instead of competing with ssDNA that is floppy by design.
    """
    fwd = {(k[0], k[1]) for k in full_map if k[2] == "FORWARD" and not is_synthetic_nuc_key(k)}
    rev = {(k[0], k[1]) for k in full_map if k[2] == "REVERSE" and not is_synthetic_nuc_key(k)}
    duplex = fwd & rev

    def _ss(k) -> bool:
        return is_synthetic_nuc_key(k) or (k[0], k[1]) not in duplex
    return _ss


# Robust display half-width per metric — the auto-range the false-colouring opens with.
# The two metrics have genuinely different tails, so one percentile cannot serve both:
#   backbone — FENE-BOUNDED.  The potential is only defined out to r0 + delta, so the
#     strain physically cannot exceed ~+33 %; the distribution is tight (a real bundle
#     runs p50 ≈ 4 %, p98 ≈ 7 %, max ≈ 8 %).  A high percentile costs almost nothing and
#     keeps the worst-strained crossovers distinguishable instead of all-saturated.
#   wc — UNBOUNDED.  A melted pair just drifts apart, so the tail runs to several hundred
#     percent (measured p90 ≈ 8 %, p95 ≈ 81 %, p98 ≈ 233 % on the same bundle).  Ranging on
#     that flattens the entire intact duplex onto the midpoint colour.  A lower percentile
#     spans the intact duplex and lets melted pairs saturate the ramp's end — which is the
#     signal the user is looking for anyway.
# backbone can afford a high percentile (tight, FENE-bounded population — p98 sits a hair
# under the max).  wc cannot: even after restricting to bonded pairs the spread runs
# p50 ≈ 2 %, p90 ≈ 22 %, p98 ≈ 91 % (measured, VoltronCoreScad), because pairs stretched
# most of the way to the H-bond cutoff are still "bonded".  p90 keeps the intact duplex
# across the ramp and saturates the stretched/frayed minority.
_STRAIN_DISPLAY_PERCENTILE = {"backbone": 98.0, "wc": 90.0}

# WC strain at which a pair stops being hydrogen-bonded: the separation
# :data:`BP_FORMED_CUTOFF_NM` expressed in the metric's own units.  Past it the pair is
# simply UNPAIRED and extra distance carries no further information, so it is both the
# saturation point of the ramp and the cut that separates the bonded population (whose
# spread the display should resolve) from the melted one.
WC_UNPAIRED_STRAIN: float = BP_FORMED_CUTOFF_NM / (OXDNA_LENGTH_UNIT * HYDR_R0_OXDNA2) - 1.0


def _display_strain_bound(values, metric: str) -> float:
    """Robust symmetric half-width for false-colouring a signed strain field.

    ``backbone`` — a high percentile of |strain| over everything.  The population is
    already FENE-bounded (and torn frames are gated out upstream), so there is no runaway
    tail to defend against and clipping stays minimal.

    ``wc`` — the same percentile, but over the BONDED subpopulation only.  A WC field is
    intrinsically bimodal: an intact duplex sits near 0 (measured p50 ≈ 2 %) while frayed
    terminal pairs and melted regions run to several hundred percent, and *every* real
    origami has some of the latter — end-fraying is universal.  Ranging over both modes
    puts the entire intact structure on the midpoint colour and shows nothing.  Scaling on
    the bonded mode resolves it and lets unpaired bases saturate the ramp's end, which is
    the signal the user is actually looking for.  Falls back to the full population if
    nothing is bonded (a fully melted structure).
    """
    a = np.abs(np.asarray(values, dtype=float))
    if not a.size:
        return 0.0
    pct = _STRAIN_DISPLAY_PERCENTILE.get(metric, 98.0)
    if metric == "wc":
        bonded = a[a <= WC_UNPAIRED_STRAIN]
        if bonded.size:
            a = bonded
    return float(np.percentile(a, pct))


# The strain map needs its OWN trajectory walk (the RMSF cache keeps only the averaged
# frame, and strain must be averaged AFTER it is computed per frame — see strain_map).
# Bounded: a strain field converges on far fewer frames than an RMSF does, and each kept
# frame costs a parse + unwrap.
_STRAIN_MAX_FRAMES: int = 60
# A reconstructed frame is DISCARDED once this fraction of its backbone bonds falls
# outside the FENE window (see :func:`_fene_violation_fraction`).  Measured on a resumed
# VoltronCoreScad run: intact frames score exactly 0.0000, torn ones 0.0015 → 0.3861, so
# anything above a hair of float noise separates them cleanly.
_STRAIN_FRAME_REJECT_FRAC: float = 0.001
_PRODUCTION_STRAIN_CACHE = None
_PRODUCTION_STRAIN_CACHE_MAX = 4


def _even_indices(n: int, keep: int) -> list[int]:
    """``keep`` evenly-spaced 0-based indices spanning ``range(n)`` (all of them when
    ``keep >= n``).  Deterministic, endpoints included."""
    if n <= 0:
        return []
    if keep >= n or keep <= 1:
        return list(range(n)) if keep >= n else [n - 1]
    step = (n - 1) / (keep - 1)
    return sorted({int(round(i * step)) for i in range(keep)})


def production_strain_field(
    design: Design,
    production_traj_path,
    reference_conf_path,
    *,
    metric: str = "backbone",
    max_frames: int = _STRAIN_MAX_FRAMES,
    copies: bool = True,
    align: bool = True,
    n_trailing_extra: int = 0,
    trailing_extra_strand_length: int = 0,
) -> dict:
    """TIME-AVERAGED per-nucleotide strain field over a production trajectory —
    ``⟨strain⟩``, computed per frame and THEN averaged — plus the mean frame it was
    averaged over.

    This is the correct time-average for the strain map: measuring the strain OF the
    mean structure instead collapses every bond (see :func:`strain_map`).  Each sampled
    frame is PBC-unwrapped against the reference so a bond spanning the periodic boundary
    isn't read as an enormous stretch.

    SYNTHETIC PARTICLES ARE INCLUDED.  The reference is read with ``include_extra_bases``
    and ``include_extensions``, so crossover extra-base inserts and 5′/3′ strand-extension
    tail beads are measured like any other nucleotide.  That is the whole point for a
    strain map: a tail's bonds are the most FENE-fragile in a design (see
    ``memory/project_strand_extensions_sim.md`` — three separate blow-up modes, all at
    tails, and a too-SHORT bond kills a run as dead as a too-long one), so a map that
    dropped them would omit exactly what it exists to find.  They are excluded from the
    Kabsch fit via ``align_keys`` (unpaired ssDNA flails and would bias the superposition,
    the same reason ``atomistic_to_nadoc`` masks them out), so the returned mean frame is
    in the SAME pose as :func:`production_rmsf`'s.  They are also excluded from the ``wc``
    metric by :func:`_strain_index` — a tail has no designed partner.

    Frames are sampled EVENLY (up to ``max_frames`` across all pooled trajectories) — a
    strain field converges far faster than an RMSF does, and each frame costs a parse plus
    an unwrap.  Returns ``{field: {(helix, bp, direction): mean strain}, frame: {key:
    {backbone_position (mean CM), a1, a3}}, n_frames, n_rejected, rejected_fraction}``;
    ``frame`` is the display geometry for keys :func:`production_rmsf`'s ``average_frame``
    does not carry (it drops the synthetic ones), and the rejection counts report bond
    samples discarded as outside the FENE window (see :func:`_strain_values` — an unwrap
    artifact, not physics).  Read-only over the Physical layer.
    """
    from backend.physics.oxdna_interface import (
        _build_unwrap_plan,
        _parse_box_nm,
        read_configuration_full,
        read_trajectory_frames_at,
        unwrap_align_to_reference,
    )
    paths = (list(production_traj_path)
             if isinstance(production_traj_path, (list, tuple))
             else [production_traj_path])
    ref = read_configuration_full(
        reference_conf_path, design, copies=copies, include_extra_bases=True,
        include_extensions=True, n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)

    counts = [count_trajectory_frames(p) for p in paths]
    total = sum(counts)
    if total <= 0:
        return {"field": {}, "frame": {}, "n_frames": 0,
                "rejected_fraction": 0.0, "n_rejected": 0, "n_frames_torn": 0}

    # The key ordering + endpoint index are topology, not geometry: build them once from
    # the reference and reuse for every frame (rebuilding per frame walks every strand).
    keys = list(_strain_base_map(ref))
    ia, ib = _strain_index(design, keys, metric)
    # The backbone index is built for EVERY metric: it drives the per-frame torn-unwrap
    # gate below, which `wc` needs even more than `backbone` does (it has no bound of its
    # own).  Reused directly when the requested metric IS backbone.
    ia_bb, ib_bb = (ia, ib) if metric == "backbone" else _strain_index(design, keys, "backbone")
    if not ia.size:
        return {"field": {}, "frame": {}, "n_frames": 0,
                "rejected_fraction": 0.0, "n_rejected": 0, "n_frames_torn": 0}
    # Superpose on the REAL nucleotides only — matching production_rmsf, whose reference
    # drops synthetic keys entirely.  Without this the tails would both bias the fit and
    # land the mean structure in a different pose than the RMSF/deviation overlays.
    fit_keys = [k for k in ref if not is_synthetic_nuc_key(k)] if align else None
    # The unwrap's traversal structure depends only on the KEY SET, so build it once and
    # hand it to every frame — without this each frame re-walks the bonded graph, which
    # measured as the single largest cost of this loop (13.1 s of 21.4 s on a 15 k-nt job).
    _plan_cache: dict = {}

    def _plan_for(fr):
        ks = frozenset(fr)
        p = _plan_cache.get(ks)
        if p is None:
            p = _build_unwrap_plan(fr, design)
            _plan_cache[ks] = p
        return p

    total_s = np.zeros(len(keys))
    counted = np.zeros(len(keys))
    n_attempted = 0
    n_rejected = 0
    n_frames_torn = 0
    sum_cm = np.zeros((len(keys), 3))
    sum_a1 = np.zeros((len(keys), 3))
    sum_a3 = np.zeros((len(keys), 3))
    n_frames = 0
    for path, n in zip(paths, counts):
        if n <= 0:
            continue
        # Share the frame budget across pooled runs in proportion to their length, so a
        # long production run isn't drowned out by a short field child (or vice versa).
        keep = max(1, int(round(max_frames * n / total)))
        frames = read_trajectory_frames_at(
            path, design, _even_indices(n, keep), copies=copies,
            n_trailing_extra=n_trailing_extra,
            trailing_extra_strand_length=trailing_extra_strand_length)
        box = _parse_box_nm(path)
        for fr in frames.values():
            whole = (unwrap_align_to_reference(fr, ref, design, box, align=align,
                                               align_keys=fit_keys, plan=_plan_for(fr))
                     if box is not None and np.all(box > 0) else fr)
            arrs = _gather_frame(_strain_base_map(whole), keys)
            if arrs is None:
                continue                 # ragged/short frame — doesn't match the topology
            cm, a1, a3 = arrs
            # Torn-unwrap gate FIRST — a frame whose backbone reconstruction is impossible
            # is unusable for either metric, so discard it whole rather than trying to
            # salvage individual measurements out of a structure that isn't connected.
            if _fene_violation_fraction(cm, a1, a3, ia_bb, ib_bb) > _STRAIN_FRAME_REJECT_FRAC:
                n_frames_torn += 1
                continue
            vals, att, rej = _strain_values(cm, a1, a3, ia, ib, metric=metric)
            n_frames += 1
            n_attempted += att
            n_rejected += rej
            sum_cm += cm
            sum_a1 += a1
            sum_a3 += a3
            ok = ~np.isnan(vals)
            total_s[ok] += vals[ok]
            counted[ok] += 1

    if n_frames == 0:
        return {"field": {}, "frame": {}, "n_frames": 0, "rejected_fraction": 0.0,
                "n_rejected": 0, "n_frames_torn": n_frames_torn}
    seen = counted > 0
    mean = np.divide(total_s, counted, out=np.zeros_like(total_s), where=seen)
    mcm = sum_cm / n_frames
    ma1 = sum_a1 / (np.linalg.norm(sum_a1, axis=1, keepdims=True) + 1e-14)
    ma3 = sum_a3 / (np.linalg.norm(sum_a3, axis=1, keepdims=True) + 1e-14)
    return {"field": {k: float(mean[i]) for i, k in enumerate(keys) if seen[i]},
            "frame": {k: {"backbone_position": mcm[i], "a1": ma1[i], "a3": ma3[i]}
                      for i, k in enumerate(keys)},
            "n_frames": n_frames, "n_rejected": n_rejected,
            "n_frames_torn": n_frames_torn,
            "rejected_fraction": (n_rejected / n_attempted) if n_attempted else 0.0}


def production_strain_field_cached(design, production_traj_path, reference_conf_path, *,
                                   metric: str = "backbone",
                                   max_frames: int = _STRAIN_MAX_FRAMES,
                                   copies: bool = True,
                                   align: bool = True,
                                   n_trailing_extra: int = 0,
                                   trailing_extra_strand_length: int = 0) -> dict:
    """LRU-cached :func:`production_strain_field`.  File size+mtime signatures naturally
    invalidate a still-growing trajectory; a finished one is reused across metric toggles
    and re-selections of the same job."""
    global _PRODUCTION_STRAIN_CACHE
    from collections import OrderedDict

    paths = (list(production_traj_path)
             if isinstance(production_traj_path, (list, tuple))
             else [production_traj_path])
    key = (tuple(_traj_file_sig(p) for p in paths), _traj_file_sig(reference_conf_path),
           str(metric), int(max_frames), bool(copies), bool(align), int(n_trailing_extra),
           int(trailing_extra_strand_length))
    if _PRODUCTION_STRAIN_CACHE is not None:
        cached = _PRODUCTION_STRAIN_CACHE.get(key)
        if cached is not None:
            _PRODUCTION_STRAIN_CACHE.move_to_end(key)
            return cached
    result = production_strain_field(
        design, paths, reference_conf_path, metric=metric, max_frames=max_frames,
        copies=copies, align=align, n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)
    if _PRODUCTION_STRAIN_CACHE is None:
        _PRODUCTION_STRAIN_CACHE = OrderedDict()
    _PRODUCTION_STRAIN_CACHE[key] = result
    _PRODUCTION_STRAIN_CACHE.move_to_end(key)
    while len(_PRODUCTION_STRAIN_CACHE) > _PRODUCTION_STRAIN_CACHE_MAX:
        _PRODUCTION_STRAIN_CACHE.popitem(last=False)
    return result


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
