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


@dataclass
class OxdnaHealthResult:
    bp_retained_fraction: float | None = None
    n_pairs:              int = 0
    potential_energy:     float | None = None
    energy_converged:     bool = False
    max_backbone_stretch: float | None = None
    n_clashes:            int = 0
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
) -> dict:
    """Per-NUCLEOTIDE average position + RMSF (root-mean-square fluctuation, nm)
    over a production trajectory — the flexibility map.

    Each frame is PBC-unwrapped + Kabsch-aligned to the relaxed reference (rigid
    diffusion/tumbling removed), then for every nucleotide we take the mean of its
    true backbone-site position across frames and the RMSF about that mean.  Low
    RMSF = rigid, high RMSF = flexible.  The backbone site (not the raw oxDNA
    centre of mass) is used so the displayed mean structure has the correct duplex
    width.

    Returns {ready, n_frames, positions:[{helix_id, bp_index, direction,
    backbone_position:[mean xyz], nx, ny, nz (mean a1), rmsf}], min_rmsf,
    max_rmsf, mean_rmsf}.
    """
    from backend.physics.oxdna_interface import (
        _parse_box_nm,
        oxdna_backbone_site,
        read_configuration_full,
        read_trajectory_frames_full,
        unwrap_align_to_reference,
    )
    ref = read_configuration_full(reference_conf_path, design)
    frames = read_trajectory_frames_full(production_traj_path, design)
    box = _parse_box_nm(production_traj_path)

    acc: dict[tuple, dict] = {}   # key → {"pos": [bb xyz...], "a1": [a1...]}
    n_frames = 0
    for fr in frames:
        aligned = (unwrap_align_to_reference(fr, ref, design, box)
                   if box is not None and np.all(box > 0) else fr)
        n_frames += 1
        for k, v in aligned.items():
            bb = oxdna_backbone_site(v["backbone_position"], v["a1"], v["a3"])
            slot = acc.setdefault(k, {"pos": [], "a1": []})
            slot["pos"].append(bb)
            slot["a1"].append(v["a1"])

    if n_frames == 0 or not acc:
        return {"ready": False, "n_frames": 0, "positions": [],
                "min_rmsf": None, "max_rmsf": None, "mean_rmsf": None}

    positions: list[dict] = []
    rmsfs: list[float] = []
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

    r = np.array(rmsfs)
    return {"ready": True, "n_frames": n_frames, "positions": positions,
            "min_rmsf": float(r.min()), "max_rmsf": float(r.max()),
            "mean_rmsf": float(r.mean())}


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
    return res
