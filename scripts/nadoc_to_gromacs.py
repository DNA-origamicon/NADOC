#!/usr/bin/env python3
"""
nadoc_to_gromacs.py — NADOC atomistic viewer model → GROMACS-ready PDB
========================================================================

The atom positions written to disk are EXACTLY the same as the ball-and-stick
representation rendered in the NADOC viewer, guaranteed by calling the same
backend function: build_atomistic_model(design, chi_fwd_cell_rad, chi_rev_cell_rad).

The only post-processing steps are:
  • Chain ID remapped from per-strand  →  per-helix  (A/B/C … one per helix)
  • Residue seq_num renumbered per-helix in (bp_index, FORWARD-first) order
  • Coordinates converted nm → Å for the PDB ATOM records
  • Validation suite run on the shared atom positions

Usage
-----
    python scripts/nadoc_to_gromacs.py <design.nadoc> [output.pdb]
        [--chi-fwd-deg=0] [--chi-rev-deg=0]

    --chi-fwd-deg  Azimuthal chi correction for FORWARD-cell helices (degrees).
                   Viewer default: 0.  Estimated calibration target: −51°.
    --chi-rev-deg  Azimuthal chi correction for REVERSE-cell helices (degrees).
                   Viewer default: 0.  Estimated calibration target: −81°.

Dependencies: NADOC backend package only (no MDAnalysis / parmed).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
from typing import Optional

import numpy as np

# ── NADOC backend ──────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.core.atomistic import (
    Atom,
    AtomisticModel,
    build_atomistic_model,
)
from backend.core.geometry  import nucleotide_positions
from backend.core.models    import Design, Direction
from backend.core.sequences import domain_bp_range

# ══════════════════════════════════════════════════════════════════════════════
# §1  DESIGN LOADING
# ══════════════════════════════════════════════════════════════════════════════

def load_design(filepath: str) -> Design:
    with open(filepath) as fh:
        return Design.from_json(fh.read())


# ══════════════════════════════════════════════════════════════════════════════
# §2  CHAIN REMAPPING  (per-strand → per-helix)
# ══════════════════════════════════════════════════════════════════════════════

_CHAIN_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _helix_chain_map(design: Design) -> dict[str, str]:
    """Return {helix_id: single_char_chain_id}, one letter per helix."""
    return {h.id: _CHAIN_CHARS[i % len(_CHAIN_CHARS)]
            for i, h in enumerate(design.helices)}


def remap_chains(model: AtomisticModel, design: Design) -> AtomisticModel:
    """
    Return a new AtomisticModel with chain_id and seq_num remapped per-helix.

    build_atomistic_model assigns one chain per strand (A = strand 0, B = strand 1, …).
    GROMACS convention (and PDB readability) benefits from one chain per helix so the
    entire double-stranded region is in a single chain.

    Remapping:
      chain_id  → single char from _CHAIN_CHARS, indexed by helix list position
      seq_num   → 1-based, per helix, ordered by (bp_index ascending, FORWARD first)
                  so the chain reads 5'→3' scaffold-first within each helix column.

    Bond serials are unchanged because we return a new list with replaced atoms
    (serial values stay the same; only chain_id and seq_num change).
    """
    hchain = _helix_chain_map(design)

    # Build (helix_id, bp_index, direction) → seq_num within that helix.
    # Order: bp_index ascending; FORWARD (0) before REVERSE (1) at each bp.
    nuc_keys_by_helix: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    seen: set[tuple[str, int, str]] = set()
    for atom in model.atoms:
        key = (atom.helix_id, atom.bp_index, atom.direction)
        if key not in seen:
            seen.add(key)
            dir_sort = 0 if atom.direction == "FORWARD" else 1
            nuc_keys_by_helix[atom.helix_id].append((atom.bp_index, dir_sort, atom.direction))

    # Sort and build seq_num lookup
    seq_num_lookup: dict[tuple[str, int, str], int] = {}
    for h_id, entries in nuc_keys_by_helix.items():
        entries.sort()   # (bp_index, dir_sort, direction)
        for seq, (bp, _, dir_str) in enumerate(entries, start=1):
            seq_num_lookup[(h_id, bp, dir_str)] = seq

    # Rebuild atoms with new chain_id / seq_num
    new_atoms = []
    for a in model.atoms:
        chain  = hchain.get(a.helix_id, "A")
        seq    = seq_num_lookup.get((a.helix_id, a.bp_index, a.direction), a.seq_num)
        new_atoms.append(Atom(
            serial=a.serial, name=a.name, element=a.element,
            residue=a.residue, chain_id=chain, seq_num=seq,
            x=a.x, y=a.y, z=a.z,
            strand_id=a.strand_id, helix_id=a.helix_id,
            bp_index=a.bp_index, direction=a.direction,
            is_modified=a.is_modified,
        ))

    return AtomisticModel(atoms=new_atoms, bonds=model.bonds)


# ══════════════════════════════════════════════════════════════════════════════
# §3  VALIDATION SUITE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class NucValidation:
    helix_id:  str
    bp_index:  int
    direction: str
    residue:   str
    bp_width:  Optional[float]   # Å, minor groove width (canonical WC pairs only)
    stack_rise: Optional[float]  # Å, P-to-P axial rise to next bp
    hbond:     Optional[float]   # Å, best WC donor–acceptor distance
    n_clashes: int


def validate(model: AtomisticModel, design: Design) -> tuple[list[NucValidation], list[str]]:
    """
    Run validation checks on the atomistic model and return (per_nuc, warnings).

    Checks:
    1. Base-plane flatness  (ring atom RMS from best-fit plane; warn > 0.05 Å)
    2. Minor groove width   (canonical WC pairs only; warn outside 9.5–13.0 Å)
    3. WC H-bond distances  (warn outside 2.6–3.4 Å)
    4. Stacking rise        (P-to-P axial component; warn outside 2.5–4.5 Å)
    5. Clash detection      (non-bonded inter-residue pairs < 1.5 Å)
    """
    warnings: list[str] = []

    # ── Build per-nucleotide lookup ───────────────────────────────────────────
    # key = (helix_id, bp_index, direction)
    NucKey = tuple[str, int, str]
    nuc_atoms: dict[NucKey, dict[str, np.ndarray]] = defaultdict(dict)
    nuc_list:  list[NucKey] = []
    nuc_meta:  dict[NucKey, tuple[str, str]] = {}   # key → (helix_id_str, residue)

    for atom in model.atoms:
        key = (atom.helix_id, atom.bp_index, atom.direction)
        nuc_atoms[key][atom.name] = np.array([atom.x, atom.y, atom.z])
        if key not in nuc_meta:
            nuc_list.append(key)
            nuc_meta[key] = (atom.helix_id, atom.residue)

    nuc_set = set(nuc_list)

    def partner(key: NucKey) -> Optional[NucKey]:
        h, bp, d = key
        opp = "REVERSE" if d == "FORWARD" else "FORWARD"
        pk = (h, bp, opp)
        return pk if pk in nuc_set else None

    # ── Base-ring atom names ──────────────────────────────────────────────────
    RING: dict[str, list[str]] = {
        "DA": ["N9", "C8", "N7", "C5", "C4", "N3", "C2", "N1", "C6"],
        "DT": ["N1", "C2", "N3", "C4", "C5", "C6"],
        "DG": ["N9", "C8", "N7", "C5", "C4", "N3", "C2", "N1", "C6"],
        "DC": ["N1", "C2", "N3", "C4", "C5", "C6"],
    }

    # ── 1. Base-plane flatness ────────────────────────────────────────────────
    for key in nuc_list:
        _, res = nuc_meta[key]
        pts = [nuc_atoms[key][nm] for nm in RING.get(res, []) if nm in nuc_atoms[key]]
        if len(pts) < 3:
            continue
        arr = np.array(pts)
        cent = arr.mean(0)
        _, _, Vt = np.linalg.svd(arr - cent)
        normal = Vt[-1]
        rms = float(np.sqrt(np.mean(np.dot(arr - cent, normal)**2))) * 10.0   # → Å
        if rms > 0.05:
            h, bp, d = key
            warnings.append(
                f"WARNING flatness: {h}[{bp}]{d[0]} {res} ring RMS = {rms:.3f} Å (> 0.05 Å)"
            )

    # ── 2+3. Minor groove width + WC H-bonds ─────────────────────────────────
    # Only canonical Watson-Crick pairs:
    _MG: dict[tuple[str,str], tuple[str,str]] = {
        ("DA", "DT"): ("N3", "O2"), ("DT", "DA"): ("O2", "N3"),
        ("DG", "DC"): ("N3", "O2"), ("DC", "DG"): ("O2", "N3"),
    }
    _WC: dict[tuple[str,str], list[tuple[str,str]]] = {
        ("DA", "DT"): [("N6", "O4"), ("N1", "N3")],
        ("DT", "DA"): [("O4", "N6"), ("N3", "N1")],
        ("DG", "DC"): [("N1", "N3"), ("N2", "O2"), ("O6", "N4")],
        ("DC", "DG"): [("N3", "N1"), ("O2", "N2"), ("N4", "O6")],
    }

    bp_width:  dict[NucKey, Optional[float]] = {k: None for k in nuc_list}
    hbond_min: dict[NucKey, Optional[float]] = {k: None for k in nuc_list}

    for key in nuc_list:
        pk = partner(key)
        if pk is None:
            continue
        _, res_s = nuc_meta[key]
        _, res_p = nuc_meta[pk]
        pair = (res_s, res_p)

        mg = _MG.get(pair)
        if mg:
            p1 = nuc_atoms[key].get(mg[0])
            p2 = nuc_atoms[pk].get(mg[1])
            if p1 is not None and p2 is not None:
                w = float(np.linalg.norm(p2 - p1)) * 10.0
                bp_width[key] = w
                if not (9.5 <= w <= 13.0):
                    h, bp, d = key
                    warnings.append(
                        f"WARNING groove: {h}[{bp}] {res_s}:{mg[0]}···{res_p}:{mg[1]}"
                        f" = {w:.2f} Å  (target 11.0–11.7, range 9.5–13.0 Å)"
                    )

        best = None
        for don_nm, acc_nm in _WC.get(pair, []):
            pd = nuc_atoms[key].get(don_nm)
            pa = nuc_atoms[pk].get(acc_nm)
            if pd is None or pa is None:
                continue
            d_dist = float(np.linalg.norm(pa - pd)) * 10.0
            if best is None or d_dist < best:
                best = d_dist
            if not (2.6 <= d_dist <= 3.4):
                h, bp, dr = key
                warnings.append(
                    f"WARNING H-bond: {h}[{bp}] {res_s}:{don_nm}···{res_p}:{acc_nm}"
                    f" = {d_dist:.2f} Å  (target 2.6–3.4 Å)"
                )
        hbond_min[key] = best

    # ── 4. P-to-P axial stacking rise ────────────────────────────────────────
    # Use the helix axis_tangent from geometry.py (authoritative, same source as
    # the atomistic model used).  Only check same-helix consecutive nucleotides.
    axis_tangent_cache: dict[str, np.ndarray] = {}
    for h in design.helices:
        s = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        e = np.array([h.axis_end.x,   h.axis_end.y,   h.axis_end.z])
        v = e - s
        n = np.linalg.norm(v)
        axis_tangent_cache[h.id] = v / n if n > 1e-9 else v

    stack_rise: dict[NucKey, Optional[float]] = {k: None for k in nuc_list}

    for strand in design.strands:
        prev_key: Optional[NucKey] = None
        prev_helix: Optional[str] = None
        for domain in strand.domains:
            for bp in domain_bp_range(domain):
                key = (domain.helix_id, bp, domain.direction.value)
                if key not in nuc_set:
                    prev_key = None; prev_helix = None; continue
                if (prev_key is not None
                        and prev_helix == domain.helix_id
                        and prev_key in nuc_atoms
                        and key in nuc_atoms):
                    p_prev = nuc_atoms[prev_key].get("P")
                    p_curr = nuc_atoms[key].get("P")
                    if p_prev is not None and p_curr is not None:
                        e_t = axis_tangent_cache[domain.helix_id]
                        rise = abs(float(np.dot(p_curr - p_prev, e_t))) * 10.0
                        stack_rise[prev_key] = rise
                        if not (2.5 <= rise <= 4.5):
                            h, bp2, d = prev_key
                            _, bp3, _ = key
                            warnings.append(
                                f"WARNING stacking: {h}[{bp2}]→[{bp3}]"
                                f" P-axial rise = {rise:.2f} Å  (target 3.32–3.38 Å)"
                            )
                prev_key   = key
                prev_helix = domain.helix_id

    # ── 5. Clash detection (non-bonded inter-residue < 1.5 Å) ────────────────
    CLASH_NM = 0.15

    # Build bonded-pair set so we skip intra-residue (already bonded) pairs
    flat: list[tuple[NucKey, str, np.ndarray]] = []
    atom_nuc_key: dict[int, NucKey] = {}
    for atom in model.atoms:
        key = (atom.helix_id, atom.bp_index, atom.direction)
        flat.append((key, atom.name, np.array([atom.x, atom.y, atom.z])))
        atom_nuc_key[atom.serial] = key

    clash_counts: dict[NucKey, int] = {k: 0 for k in nuc_list}
    clash_lines:  list[str] = []

    # Spatial grid for O(N) clash search
    cell = CLASH_NM
    grid: dict[tuple[int,int,int], list[int]] = {}
    for fi, (_, _, pos) in enumerate(flat):
        gc = (int(pos[0]//cell), int(pos[1]//cell), int(pos[2]//cell))
        grid.setdefault(gc, []).append(fi)

    checked: set[tuple[int,int]] = set()
    for fi, (ki, an, pos) in enumerate(flat):
        gc = (int(pos[0]//cell), int(pos[1]//cell), int(pos[2]//cell))
        for dx in (-1,0,1):
         for dy in (-1,0,1):
          for dz in (-1,0,1):
            for fj in grid.get((gc[0]+dx, gc[1]+dy, gc[2]+dz), []):
                if fj <= fi: continue
                pair = (fi, fj)
                if pair in checked: continue
                checked.add(pair)
                kj, bn, posj = flat[fj]
                if ki == kj: continue   # skip intra-residue
                d = float(np.linalg.norm(posj - pos))
                if d < CLASH_NM:
                    clash_counts[ki] += 1
                    clash_counts[kj] += 1
                    h, bp2, dr = ki
                    res_a = nuc_meta[ki][1]; res_b = nuc_meta[kj][1]
                    _, bp3, _ = kj
                    clash_lines.append(
                        f"  {res_a}{bp2}:{an} ↔ {res_b}{bp3}:{bn}  {d*10:.2f} Å"
                    )

    if clash_lines:
        warnings.append(f"WARNING {len(clash_lines)} inter-residue clashes < 1.5 Å:")
        warnings.extend(clash_lines[:50])
        if len(clash_lines) > 50:
            warnings.append(f"  … {len(clash_lines)-50} more")

    # ── Assemble results ──────────────────────────────────────────────────────
    results = [
        NucValidation(
            helix_id=key[0], bp_index=key[1], direction=key[2],
            residue=nuc_meta[key][1],
            bp_width=bp_width[key],
            stack_rise=stack_rise.get(key),
            hbond=hbond_min[key],
            n_clashes=clash_counts[key],
        )
        for key in nuc_list
    ]
    return results, warnings


# ══════════════════════════════════════════════════════════════════════════════
# §4  PDB WRITER
# ══════════════════════════════════════════════════════════════════════════════

_H36 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _h36(value: int, width: int) -> str:
    dec_max = 10 ** width
    if 0 <= value < dec_max:
        return f"{value:{width}d}"
    value -= dec_max
    per_letter = 10 ** (width - 1)
    for letter in _H36:
        if value < per_letter:
            return letter + f"{value:0{width-1}d}"
        value -= per_letter
    raise ValueError(f"hybrid-36 overflow: {value + dec_max}")


def _atom_name_field(name: str, element: str) -> str:
    return f" {name:<3s}" if len(element) == 1 and len(name) <= 3 else f"{name:<4s}"


def _cryst1(atoms: list[Atom], margin_nm: float = 5.0) -> str:
    xs = [a.x for a in atoms]; ys = [a.y for a in atoms]; zs = [a.z for a in atoms]
    ax = (max(xs) - min(xs) + 2*margin_nm) * 10.0
    ay = (max(ys) - min(ys) + 2*margin_nm) * 10.0
    az = (max(zs) - min(zs) + 2*margin_nm) * 10.0
    return f"CRYST1{ax:9.3f}{ay:9.3f}{az:9.3f}  90.00  90.00  90.00 P 1           1"


def write_pdb(model: AtomisticModel, output_path: str) -> None:
    """
    Write GROMACS-ready PDB.
    Assumes model.atoms already have per-helix chain_id and renumbered seq_num
    (call remap_chains first).
    Atoms are sorted by (chain_id, seq_num, serial) for contiguous chains.
    """
    atoms = sorted(model.atoms, key=lambda a: (a.chain_id, a.seq_num, a.serial))

    lines: list[str] = [
        "REMARK  NADOC → GROMACS heavy-atom PDB (positions identical to viewer)",
        "REMARK  Template: 1zew.pdb / CHARMM36 calibration.  Units: Angstroms.",
        "REMARK  One chain per helix (A–Z). Use pdb2gmx with AMBER/CHARMM36 FF.",
        _cryst1(atoms),
    ]

    ter_serial = atoms[-1].serial + 2 if atoms else 1
    for chain_id, chain_iter in groupby(atoms, key=lambda a: a.chain_id):
        chain_atoms = list(chain_iter)
        for a in chain_atoms:
            lines.append(
                f"ATOM  {_h36(a.serial+1,5)} {_atom_name_field(a.name, a.element)}"
                f" {a.residue:>3s} {chain_id}{_h36(a.seq_num,4)}    "
                f"{a.x*10:8.3f}{a.y*10:8.3f}{a.z*10:8.3f}"
                f"  1.00  0.00"
                f"          {a.element:>2s}  "
            )
        last = chain_atoms[-1]
        lines.append(
            f"TER   {_h36(ter_serial,5)}      "
            f"{last.residue:>3s} {chain_id}{_h36(last.seq_num,4)}"
        )
        ter_serial += 1

    # CONECT records
    adj: dict[int, list[int]] = defaultdict(list)
    for i, j in model.bonds:
        adj[i].append(j); adj[j].append(i)
    for s in sorted(adj):
        partners = sorted(adj[s])
        ss = _h36(s+1, 5)
        for start in range(0, len(partners), 4):
            lines.append(f"CONECT{ss}" + "".join(_h36(p+1,5) for p in partners[start:start+4]))

    lines.append("END")
    with open(output_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[write_pdb] {len(atoms)} atoms, {len(model.bonds)} bonds → {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# §5  VALIDATION REPORT WRITER
# ══════════════════════════════════════════════════════════════════════════════

def write_report(results: list[NucValidation], warnings: list[str], path: str) -> None:
    hdr = (f"{'HELIX':>24} {'BP':>6} {'D':>1} {'RES':>3}"
           f" {'MG_W(Å)':>8} {'RISE(Å)':>8} {'HBOND(Å)':>9} {'CLASHES':>8}\n")
    sep = "-" * len(hdr.rstrip()) + "\n"
    with open(path, "w") as fh:
        fh.write("NADOC → GROMACS Validation Report\n" + "="*50 + "\n\n")
        fh.write(hdr); fh.write(sep)
        for r in results:
            bw = f"{r.bp_width:8.2f}"    if r.bp_width   is not None else "     N/A"
            sr = f"{r.stack_rise:8.2f}"  if r.stack_rise is not None else "     N/A"
            hb = f"{r.hbond:9.2f}"       if r.hbond      is not None else "      N/A"
            fh.write(
                f"{r.helix_id:>24} {r.bp_index:>6d} {r.direction[0]:>1} {r.residue:>3}"
                f" {bw} {sr} {hb} {r.n_clashes:>8d}\n"
            )
        fh.write("\n" + "="*50 + "\n")
        fh.write(f"WARNINGS ({len(warnings)}):\n\n")
        for w in warnings:
            fh.write(w + "\n")
    print(f"[report]   {len(results)} nucleotides → {path}")


# ══════════════════════════════════════════════════════════════════════════════
# §6  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Export NADOC atomistic model (identical to viewer) as GROMACS PDB"
    )
    ap.add_argument("input",  help=".nadoc design file")
    ap.add_argument("output", nargs="?", default="output_atomistic.pdb")
    ap.add_argument("--chi-fwd-deg", type=float, default=0.0,
                    help="Chi for FORWARD-cell helices (deg). Viewer default: 0. "
                         "Estimated calibration target: −51°.")
    ap.add_argument("--chi-rev-deg", type=float, default=0.0,
                    help="Chi for REVERSE-cell helices (deg). Viewer default: 0. "
                         "Estimated calibration target: −81°.")
    args = ap.parse_args()

    report_path = (args.output.replace(".pdb", "_validation_report.txt")
                   if args.output.endswith(".pdb") else "validation_report.txt")
    chi_fwd = math.radians(args.chi_fwd_deg)
    chi_rev = math.radians(args.chi_rev_deg)

    # ── 1. Load + build model (same path as the viewer API) ───────────────────
    print(f"[load]     {args.input}")
    design = load_design(args.input)
    n_strands = len(design.strands)
    print(f"           {len(design.helices)} helices, {n_strands} strands")

    print(f"[atomistic] build_atomistic_model(chi_fwd={args.chi_fwd_deg}°, "
          f"chi_rev={args.chi_rev_deg}°)  ← same as viewer")
    model = build_atomistic_model(design,
                                  chi_fwd_cell_rad=chi_fwd,
                                  chi_rev_cell_rad=chi_rev)
    print(f"           {len(model.atoms)} atoms, {len(model.bonds)} bonds")

    # ── 2. Remap chains per-helix ─────────────────────────────────────────────
    model = remap_chains(model, design)

    chains = sorted({a.chain_id for a in model.atoms})
    print(f"[chains]   {len(chains)} chains ({' '.join(chains)})")

    # ── 3. Validate ───────────────────────────────────────────────────────────
    print("[validate] running…")
    results, warnings = validate(model, design)

    n_groove = sum(1 for r in results if r.bp_width  is not None and not (9.5 <= r.bp_width  <= 13.0))
    n_stack  = sum(1 for r in results if r.stack_rise is not None and not (2.5 <= r.stack_rise <= 4.5))
    n_clash  = sum(r.n_clashes for r in results)
    n_wc     = sum(1 for r in results if r.hbond is not None and not (2.6 <= r.hbond <= 3.4))

    print(f"           groove-width warnings : {n_groove}")
    print(f"           stacking warnings     : {n_stack}")
    print(f"           WC H-bond warnings    : {n_wc}")
    print(f"           clash events          : {n_clash}")
    for w in warnings[:6]:
        print(f"  {w[:100]}")
    if len(warnings) > 6:
        print(f"  … {len(warnings)-6} more warnings in report")

    # ── 4. Chi calibration status ─────────────────────────────────────────────
    if chi_fwd == 0.0 and chi_rev == 0.0:
        n_canonical = sum(1 for r in results if r.bp_width is not None)
        if n_canonical > 0 and n_groove / n_canonical > 0.25:
            print("\n[chi]  NOTE: chi=0° — base azimuth uncalibrated.")
            print("       Run with --chi-fwd-deg=-51 --chi-rev-deg=-81 (estimated)")
            print("       or calibrate against a known B-DNA crystal structure.")
        else:
            print("[chi]  chi=0° — groove widths within range for this design.")

    # ── 5. Backbone gap note ──────────────────────────────────────────────────
    n_xover_gaps = sum(1 for w in warnings if "backbone gap" in w)
    if n_xover_gaps:
        print(f"\n[crossovers] {n_xover_gaps} backbone gaps at crossover junctions.")
        print("             These are expected — a rigid-template backmapper cannot")
        print("             reconstruct crossover geometry without energy minimization.")
        print("             Run GROMACS energy minimization (gmx mdrun -maxwarn) to close them.")

    # ── 6. Write outputs ──────────────────────────────────────────────────────
    write_pdb(model, args.output)
    write_report(results, warnings, report_path)

    print(f"\n[done]")
    print(f"  PDB    : {args.output}")
    print(f"  Report : {report_path}")
    print()
    print("Next steps:")
    print("  pdb2gmx -f output_atomistic.pdb -o conf.gro -p topol.top -ignh")
    print("  (AMBER99SB-ILDN or CHARMM36 force field; choose DNA residue names)")


if __name__ == "__main__":
    main()
