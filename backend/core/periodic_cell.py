"""
Periodic Unit Cell MD Package for DNA Origami
==============================================
Builds a NAMD explicit-solvent package for one (or more) crossover-repeat
periods of a honeycomb DNA origami structure, with axial periodic boundary
conditions.

Motivation
----------
Full solvated structures like B_tube (24hb, 305 bp) have ~2.46M atoms and
OOM-kill on 16 GB machines.  Honeycomb lattice designs have an exact 21 bp
crossover repeat period.  Simulating one period (~170k atoms) with PBC along
the helix axis gives the same bulk thermodynamics at 14–20× lower cost.

Public API
----------
build_periodic_cell_package(design, ...)  → bytes (ZIP)
get_periodic_cell_stats(design, ...)      → dict

Pipeline (build_periodic_cell_package)
--------------------------------------
1.  _detect_periodic_start         → bp_start (first aligned bulk bp)
2.  _slice_to_bp_range             → sliced_design (1 period, no end effects)
3.  build_atomistic_model          → model
4.  _build_wrap_bonds              → wrap_bonds (48 for 24hb)
5.  _apply_wrap_bond_geometry      → canonical O3'–P at periodic boundary
6.  export_pdb / export_psf        → dna_pdb / psf_stub (with wrap bonds)
7.  _complete_psf_from_stub        → dna_psf (angles/dihedrals from bond graph)
8.  GROMACS solvation (periodic Z) → waters, box_nm
9.  Ion placement                  → solvated PSF + PDB
10. _render_periodic_namd_conf     → namd.conf (semiisotropic NPT, wrapNearest)
11. ZIP bundle
"""

from __future__ import annotations

import io
import stat
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np

from backend.core.atomistic import (
    AtomisticModel,
    build_atomistic_model,
    _minimize_backbone_bridge,  # private but accessible for image trick
)
from backend.core.constants import BDNA_RISE_PER_BP, HC_CROSSOVER_PERIOD
from backend.core.models import Design, Direction, Helix, Vec3
from backend.core.namd_package import _complete_psf_from_stub
from backend.core.namd_solvate import (
    _FF_DIR,
    _FF_FILES,
    _LOCK_BOX_FROM_XST_PY,
    _build_constraint_pdb_from_solvated,
    _build_solvated_pdb,
    _check_ff_files,
    _count_dna_charge,
    _extend_psf,
    _find_last_atom_serial,
    _gmx_solvate_periodic,
    _ion_counts,
    _parse_gro,
    _place_ions,
    _render_periodic_benchmark_conf,
    _render_periodic_locked_nvt_conf,
    _render_periodic_namd_conf,
)
from backend.core.pdb_export import export_pdb, export_psf
from backend.core.sequences import assign_consensus_sequence


# ══════════════════════════════════════════════════════════════════════════════
# §1  PERIOD DETECTION
# ══════════════════════════════════════════════════════════════════════════════


def _detect_periodic_start(design: Design, n_periods: int) -> int:
    """Return the first bulk bp aligned to the crossover grid.

    'Bulk' means at least HC_CROSSOVER_PERIOD bp away from both ends of the
    global bp range, to avoid end-cap crossover artifacts.

    For B_tube (global range [-9, 296)): returns 21.
    """
    bp_starts = [h.bp_start for h in design.helices]
    bp_ends   = [h.bp_start + h.length_bp for h in design.helices]
    global_start = min(bp_starts)
    global_end   = max(bp_ends)

    bulk_start = global_start + HC_CROSSOVER_PERIOD
    bulk_end   = global_end   - HC_CROSSOVER_PERIOD
    period_bp  = n_periods * HC_CROSSOVER_PERIOD

    for bp in range(bulk_start, bulk_end - period_bp + 1):
        if bp % HC_CROSSOVER_PERIOD == 0:
            return bp

    raise RuntimeError(
        f"No aligned periodic start found in bulk region "
        f"[{bulk_start}, {bulk_end}) for n_periods={n_periods}.  "
        f"Design may be too short or not a honeycomb lattice."
    )


# ══════════════════════════════════════════════════════════════════════════════
# §2  DESIGN SLICING
# ══════════════════════════════════════════════════════════════════════════════


def _slice_to_bp_range(design: Design, bp_start: int, bp_end: int) -> Design:
    """Return a new Design containing only bp range [bp_start, bp_end).

    Helix axes are recomputed to span exactly bp_start..bp_end-1.
    Strands/domains are clipped to the window.
    Crossovers with either endpoint outside the window are dropped.
    Heavy state (deformations, cluster_transforms, extensions, etc.) is cleared.
    """
    new_helices = []
    for h in design.helices:
        ax_s = h.axis_start.to_array()
        ax_e = h.axis_end.to_array()
        ax_vec = ax_e - ax_s
        ax_len = float(np.linalg.norm(ax_vec))
        if ax_len < 1e-9:
            continue

        ax_hat = ax_vec / ax_len

        # Compute new axis endpoints from global bp indices
        local_s = bp_start - h.bp_start
        local_e = bp_end - 1 - h.bp_start

        new_axis_start = ax_s + local_s * BDNA_RISE_PER_BP * ax_hat
        new_axis_end   = ax_s + local_e * BDNA_RISE_PER_BP * ax_hat

        new_loop_skips = [
            ls for ls in h.loop_skips
            if bp_start <= ls.bp_index < bp_end
        ]

        new_helices.append(h.model_copy(update={
            "axis_start": Vec3.from_array(new_axis_start),
            "axis_end":   Vec3.from_array(new_axis_end),
            "length_bp":  bp_end - bp_start,
            "bp_start":   bp_start,
            "loop_skips": new_loop_skips,
        }))

    new_strands = []
    for strand in design.strands:
        new_domains = []
        for domain in strand.domains:
            if domain.direction == Direction.FORWARD:
                d_lo, d_hi = domain.start_bp, domain.end_bp
                new_lo = max(d_lo, bp_start)
                new_hi = min(d_hi, bp_end - 1)
                if new_lo > new_hi:
                    continue
                new_domains.append(domain.model_copy(update={
                    "start_bp": new_lo,
                    "end_bp":   new_hi,
                }))
            else:  # REVERSE: start_bp >= end_bp
                d_lo = domain.end_bp    # lower global bp (end_bp for REVERSE)
                d_hi = domain.start_bp  # higher global bp (start_bp for REVERSE)
                new_lo = max(d_lo, bp_start)
                new_hi = min(d_hi, bp_end - 1)
                if new_lo > new_hi:
                    continue
                new_domains.append(domain.model_copy(update={
                    "start_bp": new_hi,  # REVERSE: start_bp = higher value
                    "end_bp":   new_lo,
                }))

        if not new_domains:
            continue

        new_strands.append(strand.model_copy(update={
            "domains":  new_domains,
            "sequence": None,  # partial slice sequence is meaningless
        }))

    new_crossovers = [
        xo for xo in design.crossovers
        if bp_start <= xo.half_a.index < bp_end
        and bp_start <= xo.half_b.index < bp_end
    ]

    return design.model_copy(update={
        "helices":                 new_helices,
        "strands":                 new_strands,
        "crossovers":              new_crossovers,
        "forced_ligations":        [],
        "deformations":            [],
        "cluster_transforms":      [],
        "cluster_joints":          [],
        "extensions":              [],
        "overhangs":               [],
        "overhang_connections":    [],
        "photoproduct_junctions":  [],
        "feature_log":             [],
        "feature_log_cursor":      -1,
        "feature_log_sub_cursor":  None,
        "animations":              [],
        "camera_poses":            [],
    })


# ══════════════════════════════════════════════════════════════════════════════
# §3  WRAP BOND GEOMETRY
# ══════════════════════════════════════════════════════════════════════════════


def _build_wrap_bonds(
    model: AtomisticModel,
    helices: list[Helix],
    bp_start: int,
    bp_end: int,
) -> list[tuple[int, int]]:
    """Return (serial_O3, serial_P) pairs for periodic boundary wrap bonds.

    For each helix × strand direction, a wrap bond O3'→P is added ONLY when
    both atoms are "free" — i.e., the O3' has no existing downstream P bond
    and the P has no existing upstream O3' bond.

    Most O3' and P atoms at the period boundary are already connected via
    crossover backbone bonds (bp_start and bp_end-1 are canonical HC crossover
    positions).  Wrap bonds are only needed for strands that cross the period
    boundary without a crossover (typically the scaffold strand, ~4 bonds for
    B_tube 24hb, 1 period).

    FORWARD: O3'(bp_end-1) → P(bp_start)
    REVERSE: O3'(bp_start) → P(bp_end-1)
    """
    atom_name = {a.serial: a.name for a in model.atoms}

    # Identify O3' atoms that already have a downstream P bond,
    # and P atoms that already have an upstream O3' bond.
    o3_bonded_p: set[int] = set()
    p_bonded_o3: set[int] = set()
    for si, sj in model.bonds:
        ni, nj = atom_name.get(si, ""), atom_name.get(sj, "")
        if ni == "O3'" and nj == "P":
            o3_bonded_p.add(si)
            p_bonded_o3.add(sj)
        elif nj == "O3'" and ni == "P":
            o3_bonded_p.add(sj)
            p_bonded_o3.add(si)

    atom_key: dict[tuple[str, int, str, str], int] = {}
    for atom in model.atoms:
        atom_key[(atom.helix_id, atom.bp_index, atom.direction, atom.name)] = atom.serial

    helix_ids = {h.id for h in helices}
    wrap_bonds: list[tuple[int, int]] = []

    for h_id in helix_ids:
        for dir_str, o3_bp, p_bp in (
            ("FORWARD", bp_end - 1, bp_start),   # O3' at high end → P at low end
            ("REVERSE", bp_start,   bp_end - 1),  # O3' at low end  → P at high end
        ):
            o3 = atom_key.get((h_id, o3_bp, dir_str, "O3'"))
            p  = atom_key.get((h_id, p_bp,  dir_str, "P"))
            if o3 is None or p is None:
                continue
            # Only add if both sides are truly terminal (no existing O3'-P bond)
            if o3 not in o3_bonded_p and p not in p_bonded_o3:
                wrap_bonds.append((o3, p))

    return wrap_bonds


def _apply_wrap_bond_geometry(
    model: AtomisticModel,
    helices: list[Helix],
    bp_start: int,
    bp_end: int,
    wrap_bonds: list[tuple[int, int]],
) -> None:
    """Correct wrap-bond atom geometry using the image trick.

    Only the pairs in wrap_bonds (as computed by _build_wrap_bonds) are
    corrected.  This avoids corrupting crossover geometry at bp_start and
    bp_end-1, which are canonical HC crossover positions.

    For each wrap bond, the O3' and P atoms are ~7 nm apart in real space.
    Trick: temporarily shift the P-side nucleotide atoms into the periodic
    image (+bz for FORWARD, -bz for REVERSE), run _minimize_backbone_bridge
    which sees a canonical C3'–C5' gap, then shift back.  After back-
    translation, NAMD minimum-image convention gives canonical O3'–P distance.

    Modifies model.atoms in-place.
    """
    if not wrap_bonds:
        return

    # Build (helix_id, bp_index, direction) → {atom_name: serial}
    sugar_map: dict[tuple[str, int, str], dict[str, int]] = defaultdict(dict)
    for atom in model.atoms:
        sugar_map[(atom.helix_id, atom.bp_index, atom.direction)][atom.name] = atom.serial

    # Build serial → (helix_id, bp_index, direction) for O3' and P lookups
    serial_to_key: dict[int, tuple[str, int, str]] = {
        a.serial: (a.helix_id, a.bp_index, a.direction)
        for a in model.atoms
    }

    # Build helix axis cache
    helix_by_id = {h.id: h for h in helices}

    atoms      = model.atoms
    period_bp  = bp_end - bp_start
    bz_nm      = period_bp * BDNA_RISE_PER_BP

    for o3_serial, p_serial in wrap_bonds:
        o3_key = serial_to_key.get(o3_serial)
        p_key  = serial_to_key.get(p_serial)
        if o3_key is None or p_key is None:
            continue

        h_id_o3, o3_bp, o3_dir = o3_key
        h_id_p,  p_bp,  p_dir  = p_key

        if h_id_o3 != h_id_p or o3_dir != p_dir:
            continue  # wrap bond crosses helices or directions — skip

        h = helix_by_id.get(h_id_o3)
        if h is None:
            continue

        ax_s = h.axis_start.to_array()
        ax_e = h.axis_end.to_array()
        ax_vec = ax_e - ax_s
        ax_len = float(np.linalg.norm(ax_vec))
        if ax_len < 1e-9:
            continue
        ax_hat = ax_vec / ax_len

        # FORWARD: O3' at high bp, P at low bp → shift P-side toward +Z image
        # REVERSE: O3' at low bp, P at high bp → shift P-side toward -Z image
        sign = +1 if o3_dir == "FORWARD" else -1
        shift = (sign * bz_nm) * ax_hat

        # src = the nucleotide containing O3' (the "from" end)
        src_s = sugar_map.get(o3_key)
        # dst = the nucleotide containing P (the "to" end)
        dst_s = sugar_map.get(p_key)
        if not src_s or not dst_s:
            continue
        if "C3'" not in src_s or "C5'" not in dst_s or "P" not in dst_s:
            continue

        # Translate ALL dst nucleotide atoms into the periodic image
        for serial in dst_s.values():
            a = atoms[serial]
            a.x += float(shift[0])
            a.y += float(shift[1])
            a.z += float(shift[2])

        # Place O3'(src), P(dst), O5'(dst) at canonical geometry
        _minimize_backbone_bridge(atoms, src_s, dst_s)

        # Translate dst atoms back — C5' returns to original position;
        # P/O5'/OP1/OP2 end up just outside the cell boundary so that
        # NAMD minimum-image gives a canonical O3'–P distance.
        for serial in dst_s.values():
            a = atoms[serial]
            a.x -= float(shift[0])
            a.y -= float(shift[1])
            a.z -= float(shift[2])


# ══════════════════════════════════════════════════════════════════════════════
# §4  README / LAUNCH
# ══════════════════════════════════════════════════════════════════════════════


_README_PERIODIC = """\
{name} — NAMD Periodic Unit Cell MD Package
============================================
Generated by NADOC.

This package simulates ONE crossover-repeat period of the DNA origami
structure with axial periodic boundary conditions (PBC), enabling
~20-30 ns/day on a consumer GPU vs ~1-2 ns/day for the full solvated system.

Contents
--------
{name}.pdb          Solvated structure (1 period: DNA + TIP3P + NaCl)
{name}.psf          Complete topology (wrap bonds + angles/dihedrals)
{name}_restraints.pdb
                    Constraint mask: DNA heavy atoms k=1, solvent/ions k=0
namd.conf           Alias of equilibrate_npt.conf
equilibrate_npt.conf
                    Restrained NPT box-discovery phase
production_locked_nvt.template.conf
                    Fixed-box unrestrained production template
relax_locked_nvt.template.conf
                    Fixed-box restrained relaxation template
ramp_locked_nvt_*.template.conf
                    Fixed-box restraint ramp stages
benchmark_standard_cuda.conf
                    Short fixed-box standard CUDA benchmark
benchmark_gpu_resident.conf
                    Experimental NAMD GPUresident benchmark probe
forcefield/         CHARMM36 parameters
launch.sh           Runs NPT, patches locked relaxation/production configs
                    from XST tail, then starts locked-Z NVT production
scripts/lock_box_from_xst.py
                    Averages stable NPT X/Y tail and restores exact Z
scripts/monitor.py  Energy monitor

Cell geometry
-------------
Axial (Z): locked to {period_nm:.4f} nm ({n_periods}× 21 bp crossover period)
Lateral (XY): chosen from stable-tail average of restrained NPT
Wrap bonds: {n_wrap_bonds} O3'→P pairs at the periodic boundary (auto-minimized)

Quick start
-----------
    bash launch.sh

Or manually:
    mkdir -p output
    namd3 +p16 +devices 0 equilibrate_npt.conf > output/{name}_equilibrate_npt.log
    python3 scripts/lock_box_from_xst.py \\
        --xst output/{name}_equilibrate_npt.xst \\
        --template relax_locked_nvt.template.conf \\
        --out relax_locked_nvt.conf \\
        --z-angstrom {period_ang:.3f}
    namd3 +p16 +devices 0 relax_locked_nvt.conf > output/{name}_relax_locked_nvt.log
    for f in ramp_locked_nvt_*.template.conf; do
        out="${{f%.template.conf}}.conf"
        python3 scripts/lock_box_from_xst.py \\
            --xst output/{name}_equilibrate_npt.xst \\
            --template "$f" \\
            --out "$out" \\
            --z-angstrom {period_ang:.3f}
        namd3 +p16 +devices 0 "$out" > "output/{name}_${{out%.conf}}.log"
    done
    python3 scripts/lock_box_from_xst.py \\
        --xst output/{name}_equilibrate_npt.xst \\
        --template production_locked_nvt.template.conf \\
        --out production_locked_nvt.conf \\
        --z-angstrom {period_ang:.3f}
    namd3 +p16 +devices 0 production_locked_nvt.conf > output/{name}_production_locked_nvt.log

GPU-resident experiment:
    bash scripts/benchmark_gpu_modes.sh

Trust the GPU-resident result only if it completes without fatal low-exclusion
or CUDA memory errors and is faster than benchmark_standard_cuda.conf.

Requirements
------------
- NAMD 3.0+ (CUDA build) — auto-downloaded by launch.sh
- CUDA-capable GPU
- ~2-4 GB RAM (vs ~12+ GB for full solvated)
"""

_LAUNCH_SH_PERIODIC = """\
#!/usr/bin/env bash
# NADOC Periodic Cell NAMD Launch Script
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

if command -v namd3 &>/dev/null; then
    NAMD=namd3
elif [ -x "$HOME/Applications/NAMD_3.0.2/namd3" ]; then
    NAMD="$HOME/Applications/NAMD_3.0.2/namd3"
else
    echo "NAMD3 not found.  Downloading NAMD 3.0.2 (Linux/CUDA)..."
    wget -q "https://www.ks.uiuc.edu/Research/namd/3.0.2/download/NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz" -O /tmp/namd3.tar.gz
    tar -xzf /tmp/namd3.tar.gz -C "$HOME/Applications/"
    NAMD="$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3"
fi

echo "Using NAMD: $NAMD"
N_THREADS=$(( $(nproc) > 8 ? 8 : $(nproc) ))

echo
echo "[1/3] Restrained NPT box discovery"
$NAMD +p$N_THREADS +devices 0 equilibrate_npt.conf 2>&1 | tee output/{name}_equilibrate_npt.log

echo
echo "[2/4] Averaging stable NPT tail and restoring locked Z"
python3 scripts/lock_box_from_xst.py \\
    --xst output/{name}_equilibrate_npt.xst \\
    --template relax_locked_nvt.template.conf \\
    --out relax_locked_nvt.conf \\
    --z-angstrom {period_ang:.3f}
python3 scripts/lock_box_from_xst.py \\
    --xst output/{name}_equilibrate_npt.xst \\
    --template production_locked_nvt.template.conf \\
    --out production_locked_nvt.conf \\
    --z-angstrom {period_ang:.3f}
for f in ramp_locked_nvt_*.template.conf; do
    out="${{f%.template.conf}}.conf"
    python3 scripts/lock_box_from_xst.py \\
        --xst output/{name}_equilibrate_npt.xst \\
        --template "$f" \\
        --out "$out" \\
        --z-angstrom {period_ang:.3f}
done

echo
echo "[3/4] Locked-Z restrained NVT relaxation"
$NAMD +p$N_THREADS +devices 0 relax_locked_nvt.conf 2>&1 | tee output/{name}_relax_locked_nvt.log

echo
echo "[4/4] Locked-Z restraint ramp and unrestrained NVT production"
for conf in ramp_locked_nvt_*.conf; do
    tag="${{conf%.conf}}"
    $NAMD +p$N_THREADS +devices 0 "$conf" 2>&1 | tee "output/{name}_${{tag}}.log"
done
$NAMD +p$N_THREADS +devices 0 production_locked_nvt.conf 2>&1 | tee output/{name}_production_locked_nvt.log

echo "Done. Trajectory: output/{name}_production_locked_nvt.dcd"
"""

_BENCHMARK_GPU_MODES_SH = """\
#!/usr/bin/env bash
# Compare standard CUDA and experimental GPU-resident periodic MD configs.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

if command -v namd3 &>/dev/null; then
    NAMD=namd3
elif [ -x "$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3" ]; then
    NAMD="$HOME/Applications/NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3"
elif [ -x "$HOME/Applications/NAMD_3.0.2/namd3" ]; then
    NAMD="$HOME/Applications/NAMD_3.0.2/namd3"
else
    echo "namd3 not found" >&2
    exit 1
fi

N_THREADS=$(( $(nproc) > 16 ? 16 : $(nproc) ))
for conf in benchmark_standard_cuda.conf benchmark_gpu_resident.conf; do
    tag="${{conf%.conf}}"
    echo
    echo "=== $tag ==="
    "$NAMD" +p$N_THREADS +devices 0 "$conf" 2>&1 | tee "output/{name}_${{tag}}.log"
    if grep -qi "Low global CUDA exclusion\\|FATAL\\|ERROR" "output/{name}_${{tag}}.log"; then
        echo "WARNING: $tag logged exclusion/error warnings; inspect before trusting timing."
    fi
done
"""

_MONITOR_PY = """\
#!/usr/bin/env python3
\"\"\"Tail the NAMD log and print energy/step summary.\"\"\"
import sys, re, time
log = sys.argv[1] if len(sys.argv) > 1 else "output/namd.log"
pat = re.compile(r"^ENERGY:\\s+(\\d+)\\s+[\\d.+-]+\\s+[\\d.+-]+\\s+[\\d.+-]+\\s+[\\d.+-]+\\s+([\\d.+-]+)")
seen = 0
while True:
    try:
        with open(log) as f:
            lines = f.readlines()[seen:]
        for ln in lines:
            m = pat.match(ln)
            if m:
                print(f"step {m.group(1):>10s}  Etotal = {float(m.group(2)):12.1f} kcal/mol")
            seen += 1 if ln.strip() else 0
    except FileNotFoundError:
        pass
    time.sleep(2)
"""


# ══════════════════════════════════════════════════════════════════════════════
# §5  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════


def build_periodic_cell_package(
    design: Design,
    *,
    n_periods: int = 1,
    padding_nm: float = 1.2,
    ion_conc_mM: float = 150.0,
    bp_start: Optional[int] = None,
    seed: int = 42,
) -> bytes:
    """Return raw ZIP bytes of a complete NAMD periodic unit-cell package.

    Parameters
    ----------
    design:
        Active NADOC design (honeycomb lattice assumed).
    n_periods:
        Number of 21 bp crossover periods to include. Default 1.
    padding_nm:
        Water padding around the DNA bounding box in XY (nm). Default 1.2.
    ion_conc_mM:
        Target NaCl concentration (mM). Default 150.
    bp_start:
        Override periodic start bp. Auto-detected if None.
    seed:
        Random seed for ion placement.

    Returns
    -------
    bytes
        ZIP file contents ready to write to disk or serve as a download.
    """
    _check_ff_files()

    name = (design.metadata.name or "design").replace(" ", "_")
    name = f"{name}_periodic_{n_periods}x"
    prefix = f"{name}/"

    # ── 1. Detect periodic start ─────────────────────────────────────────────
    if bp_start is None:
        bp_start = _detect_periodic_start(design, n_periods)
    bp_end = bp_start + n_periods * HC_CROSSOVER_PERIOD
    periodic_z_nm = n_periods * HC_CROSSOVER_PERIOD * BDNA_RISE_PER_BP

    # ── 2. Slice design to one period ────────────────────────────────────────
    sliced_design = _slice_to_bp_range(design, bp_start, bp_end)

    # ── 2b. Assign consensus sequences from the full design ──────────────────
    # Each position (helix, bp%period, direction) gets the most common base
    # across all periods in the full design; REVERSE = complement(FORWARD).
    sliced_design, _consensus = assign_consensus_sequence(
        design, sliced_design, bp_start, n_periods * HC_CROSSOVER_PERIOD,
    )

    # ── 3. Build atomistic model for the slice ───────────────────────────────
    model = build_atomistic_model(sliced_design)

    # ── 4. Find wrap bonds ───────────────────────────────────────────────────
    wrap_bonds = _build_wrap_bonds(model, sliced_design.helices, bp_start, bp_end)

    # ── 5. Apply image-trick geometry correction to wrap-bond atoms ──────────
    _apply_wrap_bond_geometry(model, sliced_design.helices, bp_start, bp_end, wrap_bonds)

    # ── 6–7. Export PDB and PSF stub with wrap bonds ─────────────────────────
    dna_pdb  = export_pdb(sliced_design, non_std_bonds=wrap_bonds, model=model)
    psf_stub = export_psf(sliced_design, non_std_bonds=wrap_bonds, model=model)

    # ── 8. Complete PSF (angles/dihedrals generated from bond graph) ─────────
    dna_psf = _complete_psf_from_stub(psf_stub)

    # ── 9. GROMACS solvation with exact periodic Z ───────────────────────────
    with tempfile.TemporaryDirectory(prefix="nadoc_pcell_") as _tmpdir:
        tmpdir = Path(_tmpdir)
        waters, box_nm = _gmx_solvate_periodic(dna_pdb, padding_nm, periodic_z_nm, tmpdir)

    # ── 10. Ion placement ─────────────────────────────────────────────────────
    dna_charge = _count_dna_charge(dna_pdb)
    n_na, n_cl = _ion_counts(len(waters), dna_charge, ion_conc_mM, box_nm)
    waters, na_pos, cl_pos = _place_ions(waters, n_na, n_cl, seed=seed)

    # ── 11. Assemble solvated PSF and PDB ────────────────────────────────────
    dna_n_atoms  = _find_last_atom_serial(dna_psf)
    n_total      = dna_n_atoms + len(waters) * 3 + n_na + n_cl
    solvated_psf = _extend_psf(dna_psf, waters, na_pos, cl_pos)
    solvated_pdb = _build_solvated_pdb(dna_pdb, waters, na_pos, cl_pos, box_nm, dna_n_atoms)

    # ── 12. NAMD configurations ───────────────────────────────────────────────
    namd_conf = _render_periodic_namd_conf(name, box_nm, n_total, periodic_z_nm)
    relax_conf = _render_periodic_locked_nvt_conf(
        name, box_nm, n_total, periodic_z_nm,
        suffix="relax_locked_nvt",
        run_steps=250_000,
        restart_from="equilibrate_npt",
        restraint_scaling=1.0,
    )
    ramp_schedule = [0.5, 0.25, 0.10, 0.03]
    ramp_confs: list[tuple[str, str]] = []
    previous_suffix = "relax_locked_nvt"
    for i, scaling in enumerate(ramp_schedule):
        suffix = f"ramp_locked_nvt_{i:02d}"
        ramp_confs.append((
            f"{suffix}.template.conf",
            _render_periodic_locked_nvt_conf(
                name, box_nm, n_total, periodic_z_nm,
                suffix=suffix,
                run_steps=50_000,
                restart_from=previous_suffix,
                restraint_scaling=scaling,
            ),
        ))
        previous_suffix = suffix
    production_conf = _render_periodic_locked_nvt_conf(
        name, box_nm, n_total, periodic_z_nm,
        suffix="production_locked_nvt",
        restart_from=previous_suffix,
    )
    bench_standard_conf = _render_periodic_benchmark_conf(
        name, box_nm, n_total, periodic_z_nm, gpu_resident=False,
    )
    bench_gpu_conf = _render_periodic_benchmark_conf(
        name, box_nm, n_total, periodic_z_nm, gpu_resident=True,
    )
    restraints_pdb = _build_constraint_pdb_from_solvated(solvated_pdb, dna_k=1.0)

    # ── 13. Ancillary files ───────────────────────────────────────────────────
    readme = _README_PERIODIC.format(
        name=name,
        period_nm=periodic_z_nm,
        period_ang=periodic_z_nm * 10.0,
        n_periods=n_periods,
        n_wrap_bonds=len(wrap_bonds),
    )
    launch = _LAUNCH_SH_PERIODIC.format(name=name, period_ang=periodic_z_nm * 10.0)
    benchmark_gpu_modes = _BENCHMARK_GPU_MODES_SH.format(name=name)

    # ── 14. ZIP bundle ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + f"{name}.pdb",        solvated_pdb)
        zf.writestr(prefix + f"{name}.psf",        solvated_psf)
        zf.writestr(prefix + f"{name}_restraints.pdb", restraints_pdb)
        zf.writestr(prefix + "namd.conf",           namd_conf)
        zf.writestr(prefix + "equilibrate_npt.conf", namd_conf)
        zf.writestr(prefix + "relax_locked_nvt.template.conf", relax_conf)
        for rel_name, conf_text in ramp_confs:
            zf.writestr(prefix + rel_name, conf_text)
        zf.writestr(prefix + "production_locked_nvt.template.conf", production_conf)
        zf.writestr(prefix + "benchmark_standard_cuda.conf", bench_standard_conf)
        zf.writestr(prefix + "benchmark_gpu_resident.conf", bench_gpu_conf)
        zf.writestr(prefix + "README.txt",          readme)
        zf.writestr(prefix + "scripts/monitor.py",  _MONITOR_PY)
        zf.writestr(prefix + "scripts/lock_box_from_xst.py", _LOCK_BOX_FROM_XST_PY)
        zf.writestr(prefix + "scripts/benchmark_gpu_modes.sh", benchmark_gpu_modes)

        for ff_file in _FF_FILES:
            ff_path = _FF_DIR / ff_file
            if ff_path.exists():
                zf.writestr(prefix + f"forcefield/{ff_file}", ff_path.read_bytes())

        info = zipfile.ZipInfo(prefix + "launch.sh")
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (
            stat.S_IFREG
            | stat.S_IRWXU
            | stat.S_IRGRP | stat.S_IXGRP
            | stat.S_IROTH | stat.S_IXOTH
        ) << 16
        zf.writestr(info, launch)

    buf.seek(0)
    return buf.getvalue()


def get_periodic_cell_stats(
    design: Design,
    *,
    n_periods: int = 1,
    padding_nm: float = 1.2,
    ion_conc_mM: float = 150.0,
    bp_start: Optional[int] = None,
) -> dict:
    """Return estimated system size without building the full package.

    Runs gmx editconf + solvate to count water molecules, then returns atom
    counts and box dimensions.  Faster than the full build (~10–30 s).
    """
    if bp_start is None:
        bp_start = _detect_periodic_start(design, n_periods)
    bp_end = bp_start + n_periods * HC_CROSSOVER_PERIOD
    periodic_z_nm = n_periods * HC_CROSSOVER_PERIOD * BDNA_RISE_PER_BP

    sliced_design, _ = assign_consensus_sequence(
        design, _slice_to_bp_range(design, bp_start, bp_end),
        bp_start, n_periods * HC_CROSSOVER_PERIOD,
    )
    model         = build_atomistic_model(sliced_design)
    wrap_bonds    = _build_wrap_bonds(model, sliced_design.helices, bp_start, bp_end)

    dna_pdb      = export_pdb(sliced_design, non_std_bonds=wrap_bonds, model=model)
    psf_stub     = export_psf(sliced_design, non_std_bonds=wrap_bonds, model=model)
    dna_psf      = _complete_psf_from_stub(psf_stub)
    dna_n_atoms  = _find_last_atom_serial(dna_psf)
    dna_charge   = _count_dna_charge(dna_pdb)

    with tempfile.TemporaryDirectory(prefix="nadoc_pcell_stats_") as _tmp:
        tmpdir = Path(_tmp)
        waters, box_nm = _gmx_solvate_periodic(dna_pdb, padding_nm, periodic_z_nm, tmpdir)

    n_na, n_cl    = _ion_counts(len(waters), dna_charge, ion_conc_mM, box_nm)
    n_water_atoms = len(waters) * 3
    n_total       = dna_n_atoms + n_water_atoms + n_na + n_cl

    bx, by, bz = box_nm
    return {
        "bp_start":       bp_start,
        "bp_end":         bp_end,
        "n_periods":      n_periods,
        "periodic_z_nm":  periodic_z_nm,
        "n_wrap_bonds":   len(wrap_bonds),
        "n_crossovers":   len(sliced_design.crossovers),
        "dna_atoms":      dna_n_atoms,
        "n_waters":       len(waters),
        "water_atoms":    n_water_atoms,
        "n_na":           n_na,
        "n_cl":           n_cl,
        "total_atoms":    n_total,
        "box_nm":         box_nm,
        "box_volume_nm3": bx * by * bz,
        "dna_charge":     dna_charge,
    }
