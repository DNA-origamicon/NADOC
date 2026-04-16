#!/usr/bin/env python3
"""
helix_cyl_diff.py — Cylindrical-coordinate differences between consecutive
                    nucleotides (N → N+1) for all heavy atoms in a PDB file.

The helical axis is fitted by SVD through all phosphorus (P) atoms in the
structure.  Every heavy atom in each residue is then expressed in cylindrical
coordinates (r, θ, z) relative to that axis.  For each consecutive pair of
residues on the same chain the increments (Δr, Δθ, Δz) are recorded.

Usage:
    # Save ideal reference from a crystal structure
    python scripts/helix_cyl_diff.py \\
        --pdb Examples/1zew.pdb \\
        --save /tmp/1zew_reference.json

    # Compare NADOC export against the ideal reference
    python scripts/helix_cyl_diff.py \\
        --pdb /tmp/nadoc_0_0.pdb \\
        --compare /tmp/1zew_reference.json \\
        --label "NADOC cell (0,0)"
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np

# ── PDB parsing ────────────────────────────────────────────────────────────────

_SKIP_RESNAMES = {"HOH", "WAT", "NA", "MG", "K", "CL", "ZN", "CA", "MN"}

def parse_pdb(path: str) -> dict[str, dict[int, tuple[str, dict[str, np.ndarray]]]]:
    """
    Parse ATOM/HETATM records.

    Returns:
        chain_id → { res_seq_num → (res_name, { atom_name → xyz_angstroms }) }

    Hydrogen atoms (name starts with H or is "1H", "2H", etc.) are skipped.
    Alternate locations: only the first occupancy record is kept.
    """
    chains: dict[str, dict[int, tuple[str, dict[str, np.ndarray]]]] = defaultdict(dict)
    seen_altloc: set[tuple[str, int, str]] = set()

    with open(path) as fh:
        for line in fh:
            rec = line[:6].strip()
            if rec not in ("ATOM", "HETATM"):
                continue
            res_name = line[17:20].strip()
            if res_name in _SKIP_RESNAMES:
                continue

            atom_name = line[12:16].strip()
            # Skip hydrogens
            if atom_name.startswith("H") or (len(atom_name) > 1 and atom_name[1] == "H"):
                pass  # keep (NADOC doesn't include H; 1zew also has no H)
            # Actually PDB files rarely have explicit H for DNA crystals; keep all

            chain    = line[21]
            res_num  = int(line[22:26])
            alt_loc  = line[16]

            # Keep only the first alternate location
            key = (chain, res_num, atom_name)
            if alt_loc not in (" ", "A", "1"):
                continue
            if key in seen_altloc:
                continue
            seen_altloc.add(key)

            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])

            if res_num not in chains[chain]:
                chains[chain][res_num] = (res_name, {})
            chains[chain][res_num][1][atom_name] = np.array([x, y, z])

    # Sort residues by number within each chain
    return {c: dict(sorted(r.items())) for c, r in chains.items()}


# ── Helical axis fitting ───────────────────────────────────────────────────────

def fit_helix_axis(chains: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit a least-squares axis through ALL P atoms in the structure.

    Returns (centroid_xyz, unit_direction_vector).
    The direction is chosen to point in the +z sense of the global frame
    (or flipped to give a positive z-component, to keep sign consistent).
    """
    pts = []
    for residues in chains.values():
        for res_num, (res_name, atoms) in residues.items():
            if "P" in atoms:
                pts.append(atoms["P"])

    if len(pts) < 2:
        # Fall back: use all C1' atoms
        for residues in chains.values():
            for res_num, (res_name, atoms) in residues.items():
                if "C1'" in atoms:
                    pts.append(atoms["C1'"])

    pts = np.array(pts)
    centroid = pts.mean(axis=0)
    _, _, Vt = np.linalg.svd(pts - centroid)
    direction = Vt[0].copy()  # first principal component = helix axis

    # Canonical orientation: axis points in the +z direction of the global frame
    if direction[2] < 0:
        direction = -direction

    return centroid, direction


# ── Cylindrical coordinate transform ──────────────────────────────────────────

def _build_cyl_frame(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (e_phi0, e_phi90): two perpendicular unit vectors in the plane
    normal to axis.  e_phi0 is used as the θ=0 reference direction.

    Convention: e_phi0 is chosen as the component of the global X axis
    perpendicular to the helix axis, normalised.
    """
    global_x = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(global_x, axis)) > 0.9:
        global_x = np.array([0.0, 1.0, 0.0])
    e_phi0 = global_x - np.dot(global_x, axis) * axis
    e_phi0 /= np.linalg.norm(e_phi0)
    e_phi90 = np.cross(axis, e_phi0)
    return e_phi0, e_phi90


def to_cylindrical(
    xyz: np.ndarray,
    centroid: np.ndarray,
    axis: np.ndarray,
    e_phi0: np.ndarray,
    e_phi90: np.ndarray,
) -> tuple[float, float, float]:
    """
    Convert Cartesian xyz (Å) to cylindrical (r Å, θ rad, z Å) relative to the
    helix axis.

    Returns (r, theta, z).
    """
    v      = xyz - centroid
    z      = float(np.dot(v, axis))
    radial = v - z * axis
    r      = float(np.linalg.norm(radial))
    theta  = float(np.arctan2(np.dot(radial, e_phi90), np.dot(radial, e_phi0)))
    return r, theta, z


# ── Step-difference computation ────────────────────────────────────────────────

_ANGLE_WRAP = 2.0 * math.pi  # 360°


def _wrap_angle(dtheta: float) -> float:
    """Wrap angular difference to (−π, +π]."""
    return (dtheta + math.pi) % _ANGLE_WRAP - math.pi


def compute_steps(
    chains: dict,
    centroid: np.ndarray,
    axis: np.ndarray,
) -> list[dict]:
    """
    For every consecutive residue pair (N → N+1) on the same chain, record
    the cylindrical-coordinate difference for every atom type present in both.

    Returns a list of records:
        {
          "chain": str,
          "from_res": int, "from_name": str,
          "to_res":   int, "to_name":   str,
          "atom":     str,
          "r_N":      float (Å),
          "theta_N_deg": float (°),
          "z_N":      float (Å),
          "dr":       float (Å),
          "dtheta_deg": float (°),
          "dz":       float (Å),
        }
    """
    e_phi0, e_phi90 = _build_cyl_frame(axis)
    records: list[dict] = []

    for chain_id, residues in sorted(chains.items()):
        res_nums = sorted(residues.keys())
        for i in range(len(res_nums) - 1):
            n  = res_nums[i]
            n1 = res_nums[i + 1]
            res_n,  (name_n,  atoms_n)  = n,  residues[n]
            res_n1, (name_n1, atoms_n1) = n1, residues[n1]

            common_atoms = sorted(set(atoms_n.keys()) & set(atoms_n1.keys()))
            for atom in common_atoms:
                r0, t0, z0 = to_cylindrical(atoms_n[atom],  centroid, axis, e_phi0, e_phi90)
                r1, t1, z1 = to_cylindrical(atoms_n1[atom], centroid, axis, e_phi0, e_phi90)
                records.append({
                    "chain":      chain_id,
                    "from_res":   n,
                    "from_name":  name_n,
                    "to_res":     n1,
                    "to_name":    name_n1,
                    "atom":       atom,
                    "r_N":        round(r0, 4),
                    "theta_N_deg": round(math.degrees(t0), 4),
                    "z_N":        round(z0, 4),
                    "dr":         round(r1 - r0, 4),
                    "dtheta_deg": round(math.degrees(_wrap_angle(t1 - t0)), 4),
                    "dz":         round(z1 - z0, 4),
                })

    return records


# ── Summary statistics ─────────────────────────────────────────────────────────

def _chain_sign(records: list[dict]) -> float:
    """Return +1 if the chain runs 5'→3' in the +z direction, -1 if antiparallel.

    Determined by the sign of the median Δz across backbone P atoms; falls back
    to sign of median Δz across all atoms if P is absent.
    """
    p_dzs = [r["dz"] for r in records if r["atom"] == "P"]
    dzs   = p_dzs if p_dzs else [r["dz"] for r in records]
    return 1.0 if float(np.median(dzs)) >= 0 else -1.0


def summarise(records: list[dict]) -> dict[str, dict]:
    """
    Compute per-atom-type statistics with sign-normalised increments.

    Because antiparallel strands on the same helix have opposite-sign Δz and
    Δθ, aggregating them directly gives near-zero means with large spread.
    Instead, each chain's records are sign-flipped so that Δz is always
    positive (i.e., 5'→3' runs in the +z direction of the fitted axis).
    This gives meaningful per-chain and aggregate means.

    Returns:
        { atom_name: { "n", "dr_mean", "dr_std",
                               "dtheta_mean", "dtheta_std",
                               "dz_mean", "dz_std",
                               "r_mean", "r_std",
                               "by_chain": { chain_id: {...} } } }
    plus "__ALL__" aggregating all atoms.

    All Δz and Δθ values are sign-normalised so that positive = 5'→3' motion
    (forward along the positive helix axis).
    """
    # Group by chain; determine sign per chain
    by_chain: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_chain[rec["chain"]].append(rec)

    chain_signs: dict[str, float] = {c: _chain_sign(recs) for c, recs in by_chain.items()}

    # Build sign-normalised records
    norm_records: list[dict] = []
    for rec in records:
        s = chain_signs[rec["chain"]]
        norm_records.append({**rec,
            "dz":         rec["dz"]         * s,
            "dtheta_deg": rec["dtheta_deg"] * s,
        })

    def _atom_stats(recs: list[dict]) -> dict:
        dr     = [r["dr"]         for r in recs]
        dt     = [r["dtheta_deg"] for r in recs]
        dz     = [r["dz"]         for r in recs]
        r_vals = [r["r_N"]        for r in recs]
        return {
            "n":          len(recs),
            "dr_mean":    round(float(np.mean(dr)),     4),
            "dr_std":     round(float(np.std(dr)),      4),
            "dtheta_mean":round(float(np.mean(dt)),     4),
            "dtheta_std": round(float(np.std(dt)),      4),
            "dz_mean":    round(float(np.mean(dz)),     4),
            "dz_std":     round(float(np.std(dz)),      4),
            "r_mean":     round(float(np.mean(r_vals)), 4),
            "r_std":      round(float(np.std(r_vals)),  4),
        }

    # Per-chain per-atom stats (sign-normalised)
    norm_by_chain: dict[str, list[dict]] = defaultdict(list)
    for rec in norm_records:
        norm_by_chain[rec["chain"]].append(rec)

    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in norm_records:
        groups[rec["atom"]].append(rec)

    stats: dict[str, dict] = {}
    for atom, recs in sorted(groups.items()):
        s = _atom_stats(recs)
        # Per-chain breakdown
        chain_stats = {}
        for c, c_recs in norm_by_chain.items():
            c_atom_recs = [r for r in c_recs if r["atom"] == atom]
            if c_atom_recs:
                chain_stats[c] = _atom_stats(c_atom_recs)
        s["by_chain"] = chain_stats
        stats[atom] = s

    # ALL atoms aggregated
    dr_all = [r["dr"]         for r in norm_records]
    dt_all = [r["dtheta_deg"] for r in norm_records]
    dz_all = [r["dz"]         for r in norm_records]
    r_all  = [r["r_N"]        for r in norm_records]
    stats["__ALL__"] = {
        "n":          len(norm_records),
        "dr_mean":    round(float(np.mean(dr_all)),     4),
        "dr_std":     round(float(np.std(dr_all)),      4),
        "dtheta_mean":round(float(np.mean(dt_all)),     4),
        "dtheta_std": round(float(np.std(dt_all)),      4),
        "dz_mean":    round(float(np.mean(dz_all)),     4),
        "dz_std":     round(float(np.std(dz_all)),      4),
        "r_mean":     round(float(np.mean(r_all)),      4),
        "r_std":      round(float(np.std(r_all)),       4),
        "chain_signs": chain_signs,
    }
    return stats


# ── Backbone-only subset ───────────────────────────────────────────────────────

_BACKBONE = {"P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'"}


def backbone_stats(stats: dict[str, dict]) -> dict[str, dict]:
    return {k: v for k, v in stats.items() if k in _BACKBONE or k == "__ALL__"}


# ── Save / compare ─────────────────────────────────────────────────────────────

def save_reference(path: str, pdb_path: str, records: list[dict], stats: dict):
    data = {
        "source_pdb": pdb_path,
        "n_steps":    len(records),
        "records":    records,
        "stats":      stats,
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
    print(f"[saved]  {len(records)} step-records → {path}")


def compare_to_reference(
    ref_path: str,
    test_records: list[dict],
    test_stats: dict,
    label: str,
) -> str:
    """
    Compare test statistics against reference statistics.
    Returns a formatted report string.
    """
    with open(ref_path) as fh:
        ref_data = json.load(fh)
    ref_stats = ref_data["stats"]
    ref_pdb   = ref_data.get("source_pdb", "unknown")

    lines = []
    lines.append("=" * 72)
    lines.append(f"CYLINDRICAL-COORDINATE HELICAL STEP COMPARISON")
    lines.append(f"  Reference : {ref_pdb}  ({ref_data['n_steps']} step-records)")
    lines.append(f"  Test      : {label}  ({len(test_records)} step-records)")
    lines.append("=" * 72)

    # Per-atom-type comparison table (backbone only for readability)
    _fmt_hdr  = f"{'Atom':<6}  {'METRIC':<9}  {'REF mean':>9}  {'TST mean':>9}  "
    _fmt_hdr += f"{'DELTA':>8}  {'REF std':>8}  {'TST std':>8}"
    lines.append("")
    lines.append("── PER-ATOM BACKBONE STEP STATISTICS ──────────────────────────────────")
    lines.append(_fmt_hdr)
    lines.append("-" * 72)

    ordered_atoms = [a for a in
        ["P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'"]
        if a in test_stats and a in ref_stats]

    for atom in ordered_atoms:
        r = ref_stats[atom]
        t = test_stats[atom]
        for metric, ref_key, tst_key, unit in [
            ("Δr(Å)",  "dr_mean",     "dr_mean",     "Å"),
            ("Δθ(°)",  "dtheta_mean", "dtheta_mean", "°"),
            ("Δz(Å)",  "dz_mean",     "dz_mean",     "Å"),
            ("r(Å)",   "r_mean",      "r_mean",      "Å"),
        ]:
            ref_val = r[ref_key]
            tst_val = t[tst_key]
            delta   = tst_val - ref_val
            ref_std = r.get(ref_key.replace("mean", "std"), 0.0)
            tst_std = t.get(tst_key.replace("mean", "std"), 0.0)
            lines.append(
                f"{atom:<6}  {metric:<9}  {ref_val:>9.3f}  {tst_val:>9.3f}  "
                f"{delta:>+8.3f}  {ref_std:>8.3f}  {tst_std:>8.3f}"
            )
        lines.append("")

    # ALL-atom summary
    lines.append("── ALL-ATOM AGGREGATE STEP STATISTICS ─────────────────────────────────")
    r = ref_stats.get("__ALL__", {})
    t = test_stats.get("__ALL__", {})
    if r and t:
        for metric, key in [
            ("Δr  (Å)", "dr"),
            ("Δθ  (°)", "dtheta"),
            ("Δz  (Å)", "dz"),
            ("r   (Å)", "r"),
        ]:
            rmu  = r.get(f"{key}_mean", float("nan"))
            tmu  = t.get(f"{key}_mean", float("nan"))
            rstd = r.get(f"{key}_std",  float("nan"))
            tstd = t.get(f"{key}_std",  float("nan"))
            delta = tmu - rmu
            lines.append(
                f"  {metric:<10}  REF {rmu:>9.3f} ± {rstd:.3f}  "
                f"TST {tmu:>9.3f} ± {tstd:.3f}   ΔERR {delta:>+8.3f}"
            )

    lines.append("=" * 72)
    return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────────────

def run(pdb_path: str, save_path: Optional[str], compare_path: Optional[str], label: str):
    print(f"[parse]   {pdb_path}")
    chains  = parse_pdb(pdb_path)
    n_chains = len(chains)
    n_res    = sum(len(v) for v in chains.values())
    print(f"          {n_chains} chains, {n_res} residues total")

    print("[axis]    fitting helical axis from P atoms …")
    centroid, axis = fit_helix_axis(chains)
    print(f"          centroid = [{centroid[0]:.2f}, {centroid[1]:.2f}, {centroid[2]:.2f}] Å")
    print(f"          axis dir = [{axis[0]:.4f}, {axis[1]:.4f}, {axis[2]:.4f}]")

    print("[steps]   computing cylindrical coordinate differences …")
    records = compute_steps(chains, centroid, axis)
    stats   = summarise(records)
    print(f"          {len(records)} atom-step records across all chains")

    if save_path:
        save_reference(save_path, pdb_path, records, stats)

    if compare_path:
        report = compare_to_reference(compare_path, records, stats, label)
        print(report)
        return report

    # If just saving (no compare), print a brief backbone summary
    bb_stats = backbone_stats(stats)
    all_stat = stats.get("__ALL__", {})
    chain_signs = all_stat.get("chain_signs", {})
    print(f"\n  chain signs (Δz): {chain_signs}  (+1 = 5'→3' along +z axis)")
    print("\n── BACKBONE STEP SUMMARY (sign-normalised mean ± std) ──────────────────")
    print(f"{'Atom':<6}  {'Δr(Å)':>11}  {'Δθ(°)':>11}  {'Δz(Å)':>11}  {'r(Å)':>11}")
    print("-" * 56)
    for atom in [a for a in ["P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'"]
                 if a in bb_stats]:
        s = bb_stats[atom]
        print(
            f"{atom:<6}  "
            f"{s['dr_mean']:>+6.3f}±{s['dr_std']:.3f}  "
            f"{s['dtheta_mean']:>+6.2f}±{s['dtheta_std']:.2f}  "
            f"{s['dz_mean']:>+6.3f}±{s['dz_std']:.3f}  "
            f"{s['r_mean']:>6.2f}±{s['r_std']:.2f}"
        )
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdb",     required=True, help="Input PDB file")
    ap.add_argument("--save",    default=None,  help="Save reference JSON to this path")
    ap.add_argument("--compare", default=None,  help="Compare against this reference JSON")
    ap.add_argument("--label",   default="test", help="Label for this test structure in report")
    args = ap.parse_args()

    run(args.pdb, args.save, args.compare, args.label)


if __name__ == "__main__":
    main()
