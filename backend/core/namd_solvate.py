"""
NAMD Explicit-Solvent Package Builder
======================================
Builds a self-contained NAMD simulation package with TIP3P explicit water
and NaCl ions from a NADOC design.

Physics:
  - Explicit TIP3P water + 150 mM NaCl (adjustable)
  - CUDASOAintegrate on (GPU-resident MD, fastest NAMD3 mode)
  - PME electrostatics, 12 Å cutoff
  - rigidBonds water (SHAKE on O-H bonds, 2 fs timestep)
  - Langevin thermostat 310 K / barostat 1 atm (NPT)

Solvation pipeline:
  1. Export atomistic PDB (heavy atoms, CHARMM36 naming)
  2. gmx editconf  → rectangular box with padding
  3. gmx solvate   → TIP3P water from spc216.gro template
  4. Parse solvated GRO → water positions (nm)
  5. Python ion placement → replace random waters with Na+/Cl-
  6. Merge water/ions into PSF (extend NATOM/NBOND/NTHETA sections)
  7. Build solvated PDB (DNA ATOM + water/ion HETATM)
  8. Emit NAMD conf + ZIP

ZIP layout::

    {name}_namd_solvated/
    ├── {name}.pdb          ← DNA + water + ions (CHARMM36 naming)
    ├── {name}.psf          ← complete topology (atoms/bonds/angles/dihedrals)
    ├── namd.conf
    ├── forcefield/
    │   ├── top_all36_na.rtf
    │   ├── par_all36_na.prm
    │   └── toppar_water_ions_cufix.str
    ├── scripts/monitor.py
    ├── README.txt
    └── AI_ASSISTANT_PROMPT.txt
"""

from __future__ import annotations

import dataclasses
import io
import math
import os
import random
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from backend.core.models import Design
from backend.core.pdb_export import export_pdb
from backend.core.namd_package import complete_psf

_FF_DIR = Path(__file__).parent.parent / "data" / "forcefield"
_FF_FILES = [
    "top_all36_na.rtf",
    "par_all36_na.prm",
    "toppar_water_ions_na.str",   # DNA-safe cufix: protein/lipid NBFIX removed
]

# ── Ion parameters (CHARMM36 / toppar_water_ions_cufix.str) ───────────────────
# SOD: Na+  type SOD  charge +1.00  mass 22.98977
# CLA: Cl-  type CLA  charge -1.00  mass 35.45000
_ION_PARAMS = {
    "SOD": ("SOD",  1.00, 22.98977),   # (atomtype, charge, mass)
    "CLA": ("CLA", -1.00, 35.45000),
}

# TIP3P water parameters (CHARMM36 / toppar_water_ions_cufix.str)
_TIP3_PARAMS = {
    "OH2": ("OT",  -0.834, 15.99940),
    "H1":  ("HT",  +0.417,  1.00800),
    "H2":  ("HT",  +0.417,  1.00800),
}

# Avogadro constant for ion count calculation
_NA = 6.02214076e23


# ══════════════════════════════════════════════════════════════════════════════
# §1  DATA TYPES
# ══════════════════════════════════════════════════════════════════════════════

@dataclasses.dataclass
class _Water:
    """TIP3P water molecule with atom positions in nm."""
    ox: float;  oy: float;  oz: float   # OW → OH2
    h1x: float; h1y: float; h1z: float  # HW1 → H1
    h2x: float; h2y: float; h2z: float  # HW2 → H2


# ══════════════════════════════════════════════════════════════════════════════
# §2  GROMACS SOLVATION
# ══════════════════════════════════════════════════════════════════════════════

def _find_gmx() -> str:
    """Return the gmx binary path, or raise RuntimeError."""
    for name in ("gmx", "gmx_mpi", "gmx_d"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError(
        "GROMACS not found in PATH.  Install with:\n"
        "    sudo apt-get install -y gromacs"
    )


def _run(cmd: list, cwd: Optional[Path] = None, stdin: str = "") -> subprocess.CompletedProcess:
    """Run a subprocess; raise RuntimeError if it fails."""
    result = subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(str(c) for c in cmd)}\n"
            f"stderr:\n{result.stderr[-3000:]}"
        )
    return result


def _parse_gro(gro_text: str) -> tuple[list[_Water], tuple[float, float, float]]:
    """Parse a GROMACS GRO file; return (water_list, (bx, by, bz) in nm).

    Only SOL residues are collected; DNA residues are ignored.
    Assumes GROMACS atom names: OW / HW1 / HW2.

    Uses sequential parsing (not grouped by resnum) to handle GRO's
    residue-number wraparound at 100,000 for large systems.
    """
    lines = gro_text.splitlines()
    # Last non-empty line is the box vector line
    box_line = lines[-1].strip()
    parts = box_line.split()
    box_nm = (float(parts[0]), float(parts[1]), float(parts[2]))

    # GRO atom line format (fixed-width):
    #   cols  0- 4: residue number (wraps at 100000 for large systems)
    #   cols  5- 9: residue name
    #   cols 10-14: atom name
    #   cols 15-19: atom number
    #   cols 20-27: x (nm, 8.3f)
    #   cols 28-35: y (nm, 8.3f)
    #   cols 36-43: z (nm, 8.3f)
    #
    # Collect SOL atoms sequentially; group into triplets (OW, HW1, HW2).
    # This avoids the residue-number wraparound issue that occurs at ~100k atoms.
    sol_buf: dict[str, tuple[float, float, float]] = {}
    waters: list[_Water] = []

    for line in lines[2:-1]:
        if len(line) < 44:
            continue
        resname  = line[5:10].strip()
        atomname = line[10:15].strip()
        if resname != "SOL":
            # Flush any incomplete water on transition out of SOL (edge case)
            if sol_buf:
                sol_buf = {}
            continue
        x = float(line[20:28])
        y = float(line[28:36])
        z = float(line[36:44])
        sol_buf[atomname] = (x, y, z)
        if len(sol_buf) == 3:
            try:
                ox, oy, oz     = sol_buf["OW"]
                h1x, h1y, h1z  = sol_buf["HW1"]
                h2x, h2y, h2z  = sol_buf["HW2"]
                waters.append(_Water(ox, oy, oz, h1x, h1y, h1z, h2x, h2y, h2z))
            except KeyError:
                pass  # unexpected atom names — skip molecule
            sol_buf = {}

    return waters, box_nm


def _gmx_solvate(
    pdb_text: str,
    padding_nm: float,
    tmpdir: Path,
) -> tuple[list[_Water], tuple[float, float, float]]:
    """Place TIP3P water around the DNA using GROMACS.

    Returns (waters, (bx, by, bz)) where positions are in nm.
    """
    gmx = _find_gmx()

    (tmpdir / "dry.pdb").write_text(pdb_text)

    # editconf: centre structure in a rectangular box with given padding
    _run([
        gmx, "editconf",
        "-f", "dry.pdb",
        "-o", "dry.gro",
        "-c",
        "-d", str(padding_nm),
        "-bt", "triclinic",
        "-nobackup",
    ], cwd=tmpdir)

    # solvate: fill box with pre-equilibrated TIP3P water (spc216.gro geometry)
    _run([
        gmx, "solvate",
        "-cp", "dry.gro",
        "-cs", "spc216.gro",
        "-o", "solvated.gro",
        "-nobackup",
    ], cwd=tmpdir)

    gro_text = (tmpdir / "solvated.gro").read_text()
    return _parse_gro(gro_text)


def _gmx_solvate_periodic(
    pdb_text: str,
    padding_nm: float,
    periodic_z_nm: float,
    tmpdir: Path,
) -> tuple[list[_Water], tuple[float, float, float]]:
    """Place TIP3P water in a box whose Z dimension is exactly periodic_z_nm.

    Unlike _gmx_solvate (which uses -d padding to auto-size the box), this
    function computes bx/by from the atom bounding box + 2*padding and forces
    bz = periodic_z_nm so the box matches the crossover repeat period exactly.

    Returns (waters, (bx, by, bz)) — same type as _gmx_solvate.
    """
    import numpy as np
    gmx = _find_gmx()

    (tmpdir / "dry.pdb").write_text(pdb_text)

    # Parse atom positions from the PDB to compute XY bounding box
    xs, ys = [], []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            try:
                xs.append(float(line[30:38]) / 10.0)  # Å → nm
                ys.append(float(line[38:46]) / 10.0)
            except ValueError:
                pass

    if not xs:
        raise RuntimeError("No ATOM/HETATM records found in PDB for periodic solvation.")

    bx = (max(xs) - min(xs)) + 2 * padding_nm
    by = (max(ys) - min(ys)) + 2 * padding_nm
    bz = periodic_z_nm

    # editconf: centre structure in the explicit box (no auto-padding)
    _run([
        gmx, "editconf",
        "-f", "dry.pdb",
        "-o", "dry.gro",
        "-c",
        "-box", f"{bx:.4f}", f"{by:.4f}", f"{bz:.4f}",
        "-nobackup",
    ], cwd=tmpdir)

    # solvate: fill box with pre-equilibrated TIP3P water
    _run([
        gmx, "solvate",
        "-cp", "dry.gro",
        "-cs", "spc216.gro",
        "-o", "solvated.gro",
        "-nobackup",
    ], cwd=tmpdir)

    gro_text = (tmpdir / "solvated.gro").read_text()
    waters, box_from_gro = _parse_gro(gro_text)
    # Use the explicit box dimensions we set, not whatever gmx reports
    return waters, (bx, by, bz)


def _periodic_cell_header(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
    *,
    mode: str,
) -> str:
    bx, by, bz = box_nm
    bx_a, by_a = bx * 10, by * 10
    bz_a = periodic_z_nm * 10   # exact period in Å
    cx, cy, cz = bx_a / 2, by_a / 2, bz_a / 2
    return f"""\
# NAMD periodic unit-cell configuration generated by NADOC
# System: {name}  ({n_atoms:,} atoms, TIP3P water + 150 mM NaCl)
# Mode:   {mode}
# Cell:   initial Z = {periodic_z_nm:.4f} nm crossover period

structure          {name}.psf
coordinates        {name}.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_na.str

# ── Periodic boundary conditions ──────────────────────────────────────────────
cellBasisVector1   {bx_a:.3f}  0.000    0.000
cellBasisVector2   0.000    {by_a:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz_a:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
wrapNearest        on

# ── PME electrostatics ────────────────────────────────────────────────────────
PME                yes
PMEGridSpacing     1.0

# ── Nonbonded ─────────────────────────────────────────────────────────────────
cutoff             12.0
switching          on
switchdist         10.0
pairlistdist       16.0
exclude            scaled1-4
oneFourScaling     1.0

# ── Constraints ───────────────────────────────────────────────────────────────
rigidBonds         water
rigidTolerance     1.0e-8

# ── Thermostat — Langevin 310 K ────────────────────────────────────────────────
temperature        310
langevin           on
langevinDamping    5
langevinTemp       310
langevinHydrogen   off
"""


def _periodic_output_block(name: str, suffix: str, *, dcd_freq: int = 5000) -> str:
    out = f"output/{name}_{suffix}"
    return f"""\
# ── Output ────────────────────────────────────────────────────────────────────
outputName         {out}
outputEnergies     500
dcdFreq            {dcd_freq}
dcdFile            {out}.dcd
xstFreq            5000
xstFile            {out}.xst
restartfreq        50000
binaryrestart      yes
"""


def _render_periodic_equilibrate_npt_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
) -> str:
    """Restrained NPT box-discovery phase for a periodic unit cell.

    This phase is intentionally conservative: DNA heavy atoms are restrained so
    water/ions and lateral box dimensions can relax before the locked-Z
    production run. Z may fluctuate here; downstream scripts only harvest stable
    tail X/Y and restore Z to the exact crossover period.
    """
    header = _periodic_cell_header(
        name, box_nm, n_atoms, periodic_z_nm,
        mode="standard CUDA, restrained NPT box discovery",
    )
    return header + f"""\

# ── Barostat — restrained NPT box discovery ──────────────────────────────────
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  200.0
langevinPistonDecay   100.0
langevinPistonTemp    310

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           2.0        ;# 2 fs — safe with rigidBonds water
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── GPU acceleration (standard CUDA, not GPU-resident) ────────────────────────
# CUDASOAintegrate (GPU-resident) is disabled: wrap bonds span the periodic cell
# (O3' at z_end bonded to P at z_start, 7 nm apart in real space).  GPU-resident
# mode builds its exclusion list from pairlist distances and cannot find those
# partners → "Low global CUDA exclusion count" abort.  Standard CUDA mode handles
# PBC-wrapped bonded exclusions correctly via CPU bonded-force path.

{_periodic_output_block(name, "equilibrate_npt")}

# ── DNA restraints: B-factor column stores force constant kcal/mol/Å² ─────────
constraints        on
consref            {name}_restraints.pdb
conskfile          {name}_restraints.pdb
conskcol           B

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           2000       ;# brief EM to relieve any solvation clashes
reinitvels         310
constraintScaling  1.0        ;# DNA heavy atoms restrained at k=1 kcal/mol/Å²
run                250000     ;# 500 ps restrained NPT box discovery
"""


def _render_periodic_locked_nvt_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
    *,
    suffix: str = "production_locked_nvt",
    run_steps: int = 25_000_000,
    restart_from: str | None = None,
    restraint_scaling: float | None = None,
) -> str:
    """Fixed-box locked-Z NVT phase.

    `scripts/lock_box_from_xst.py` patches X/Y from the stable NPT tail while
    preserving the exact Z period. The unpatched template starts from the
    generated box and PDB coordinates.
    """
    header = _periodic_cell_header(
        name, box_nm, n_atoms, periodic_z_nm,
        mode="standard CUDA, fixed-box locked-Z NVT",
    )
    if restart_from:
        start_block = f"""\
binCoordinates     output/{name}_{restart_from}.restart.coor
minimize           2000       ;# relax after restoring exact locked-Z cell
reinitvels         310        ;# do not reuse NPT velocities after box reset
"""
    else:
        start_block = "reinitvels         310\n"
    restraint_block = ""
    if restraint_scaling is not None:
        restraint_block = f"""\
# ── DNA restraints: B-factor column stores force constant kcal/mol/Å² ─────────
constraints        on
consref            {name}_restraints.pdb
conskfile          {name}_restraints.pdb
conskcol           B
constraintScaling  {restraint_scaling:.3f}

"""

    return header + f"""\

# ── Barostat — disabled for locked-Z production ──────────────────────────────
# Pressure is handled by the preceding NPT box-discovery phase. This phase fixes
# X/Y from the stable NPT tail and forces Z back to the exact 21 bp period.

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           2.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── GPU acceleration (standard CUDA, not GPU-resident) ────────────────────────
# See benchmark_gpu_resident.conf for the experimental CUDASOA probe.

{_periodic_output_block(name, suffix)}

{restraint_block}\
# ── Run ───────────────────────────────────────────────────────────────────────
{start_block}run                {run_steps}
"""


def _render_periodic_benchmark_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
    *,
    gpu_resident: bool,
    n_steps: int = 5000,
) -> str:
    """Short benchmark config for standard CUDA or experimental CUDASOA."""
    suffix = "bench_gpu_resident" if gpu_resident else "bench_standard_cuda"
    mode = (
        "EXPERIMENTAL CUDASOAintegrate, fixed-box NVT"
        if gpu_resident else
        "standard CUDA, fixed-box NVT benchmark"
    )
    header = _periodic_cell_header(name, box_nm, n_atoms, periodic_z_nm, mode=mode)
    pairlist = 16.0
    gpu_block = ""
    if gpu_resident:
        gpu_block = """\

# ── GPU-resident integration probe ────────────────────────────────────────────
# Periodic wrap bonds are ~70 Å apart in real-space coordinates. NAMD 3.0.2
# GPUresident currently builds bonded exclusions from local CUDA tile/pair lists,
# so this topology is expected to fail unless NAMD gains PBC-aware GPUresident
# bonded exclusions or NADOC changes the topology representation. Kept as an
# explicit benchmark probe, not as a production recommendation.
GPUresident        on
"""
    return header.replace("pairlistdist       16.0", f"pairlistdist       {pairlist:.1f}") + f"""\

# ── Barostat — disabled for benchmark ────────────────────────────────────────

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           2.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10
{gpu_block}
{_periodic_output_block(name, suffix, dcd_freq=999999999)}

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           500
reinitvels         310
run                {n_steps}
"""


def _render_periodic_namd_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
    periodic_z_nm: float,
) -> str:
    """Backward-compatible default config: restrained NPT box discovery."""
    return _render_periodic_equilibrate_npt_conf(name, box_nm, n_atoms, periodic_z_nm)


def _build_constraint_pdb_from_solvated(
    solvated_pdb: str,
    *,
    dna_k: float = 1.0,
) -> str:
    """Return a NAMD constraints PDB matching the solvated atom order.

    DNA ATOM records get B-factor `dna_k`; water and ions get B-factor 0.
    """
    out: list[str] = []
    for line in solvated_pdb.splitlines():
        if line.startswith("ATOM  "):
            out.append(f"{line[:60]}{dna_k:6.2f}{line[66:]}")
        elif line.startswith("HETATM"):
            out.append(f"{line[:60]}{0.0:6.2f}{line[66:]}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


_LOCK_BOX_FROM_XST_PY = r'''#!/usr/bin/env python3
"""Patch locked-Z production config using averaged X/Y from an NPT XST tail."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _rows(path: Path):
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            rows.append([float(x) for x in parts[:13]])
        except ValueError:
            pass
    return rows


def _replace_cell(text: str, ax: float, by: float, z: float, ox: float, oy: float, oz: float) -> str:
    out = []
    for line in text.splitlines():
        key = line.split()[0] if line.split() else ""
        if key == "cellBasisVector1":
            out.append(f"cellBasisVector1   {ax:.3f}  0.000    0.000")
        elif key == "cellBasisVector2":
            out.append(f"cellBasisVector2   0.000    {by:.3f}  0.000")
        elif key == "cellBasisVector3":
            out.append(f"cellBasisVector3   0.000    0.000    {z:.3f}")
        elif key == "cellOrigin":
            out.append(f"cellOrigin         {ox:.3f}   {oy:.3f}   {oz:.3f}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xst", type=Path, required=True)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--z-angstrom", type=float, required=True)
    ap.add_argument("--tail-fraction", type=float, default=0.25)
    ap.add_argument("--tail-frames", type=int, default=0)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    rows = _rows(args.xst)
    if not rows:
        raise SystemExit(f"No numeric XST rows found in {args.xst}")

    if args.tail_frames > 0:
        tail = rows[-args.tail_frames:]
    else:
        n = max(1, int(len(rows) * args.tail_fraction))
        tail = rows[-n:]

    ax = sum(r[1] for r in tail) / len(tail)
    by = sum(r[5] for r in tail) / len(tail)
    ox = sum(r[10] for r in tail) / len(tail)
    oy = sum(r[11] for r in tail) / len(tail)
    oz = sum(r[12] for r in tail) / len(tail)

    patched = _replace_cell(args.template.read_text(), ax, by, args.z_angstrom, ox, oy, oz)
    args.out.write_text(patched)
    json_out = args.json_out or args.out.with_suffix(args.out.suffix + ".lock.json")
    json_out.write_text(json.dumps({
        "xst": str(args.xst),
        "template": str(args.template),
        "out": str(args.out),
        "tail_fraction": args.tail_fraction,
        "tail_frames_requested": args.tail_frames,
        "tail_frames_used": len(tail),
        "rows_total": len(rows),
        "locked_box_angstrom": {"x": ax, "y": by, "z": args.z_angstrom},
        "origin_angstrom": {"x": ox, "y": oy, "z": oz},
        "source_tail_mean_z_angstrom": sum(r[9] for r in tail) / len(tail),
    }, indent=2))
    print(f"Wrote {args.out}")
    print(f"Wrote {json_out}")
    print(f"Tail frames: {len(tail)} / {len(rows)}")
    print(f"Locked box: X={ax:.3f} Å  Y={by:.3f} Å  Z={args.z_angstrom:.3f} Å")
    print(f"Origin:     X={ox:.3f} Å  Y={oy:.3f} Å  Z={oz:.3f} Å")


if __name__ == "__main__":
    main()
'''

# ══════════════════════════════════════════════════════════════════════════════
# §3  ION PLACEMENT
# ══════════════════════════════════════════════════════════════════════════════

def _count_dna_charge(pdb_text: str) -> float:
    """Return the net DNA charge by counting backbone phosphate atoms.

    Each phosphate group carries -1 charge in solution (one charge per P atom).
    Heavy-atom PSF partial charges are NOT used because they omit H charges,
    making their sum meaningless for neutralisation purposes.
    """
    n_p = sum(
        1 for line in pdb_text.splitlines()
        if line.startswith("ATOM") and line[12:16].strip() == "P"
    )
    return float(-n_p)


def _ion_counts(
    n_waters: int,
    dna_charge: float,
    ion_conc_mM: float,
    box_nm: tuple[float, float, float],
) -> tuple[int, int]:
    """Return (n_Na, n_Cl) to neutralise DNA and reach target NaCl concentration.

    Strategy:
      1. Neutralise: add enough Na+ to cancel DNA charge (DNA is negative).
      2. Bulk salt: add NaCl pairs to reach ion_conc_mM in the water volume.
    """
    # Neutralisation ions (DNA charge is negative, so we need Na+)
    dna_neg_charge = -int(round(dna_charge))  # positive integer (number of Na+ needed)
    n_neutralise = max(0, dna_neg_charge)

    # Volume of the water phase (approximate as full box volume)
    # 1 nm³ = 1e-27 m³ = 1e-24 L  (since 1 m³ = 1000 L)
    bx, by, bz = box_nm
    vol_L = bx * by * bz * 1e-24  # nm³ → L
    n_salt = int(round(ion_conc_mM * 1e-3 * _NA * vol_L))

    n_na = n_neutralise + n_salt
    n_cl = n_salt
    return n_na, n_cl


def _place_ions(
    waters: list[_Water],
    n_na: int,
    n_cl: int,
    seed: int = 42,
) -> tuple[list[_Water], list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Replace n_na + n_cl randomly selected water molecules with ions.

    Returns (remaining_waters, na_positions, cl_positions).
    Positions are (x, y, z) in nm at the former oxygen site.
    """
    rng = random.Random(seed)
    total_ions = n_na + n_cl
    if total_ions > len(waters):
        raise RuntimeError(
            f"Not enough water molecules ({len(waters)}) to place {total_ions} ions."
        )
    chosen_idx = rng.sample(range(len(waters)), total_ions)
    na_idx = set(chosen_idx[:n_na])
    cl_idx = set(chosen_idx[n_na:])

    remaining: list[_Water] = []
    na_pos: list[tuple[float, float, float]] = []
    cl_pos: list[tuple[float, float, float]] = []

    for i, w in enumerate(waters):
        if i in na_idx:
            na_pos.append((w.ox, w.oy, w.oz))
        elif i in cl_idx:
            cl_pos.append((w.ox, w.oy, w.oz))
        else:
            remaining.append(w)

    return remaining, na_pos, cl_pos


# ══════════════════════════════════════════════════════════════════════════════
# §4  PSF MERGING
# ══════════════════════════════════════════════════════════════════════════════

# NAMD matches PSF atoms to PDB atoms by (segid, resid, atomname).
# PDB resid is a 4-char field: values > 9999 are not parseable as plain integers
# by NAMD's PDB reader (atoi fails on hybrid-36 strings like "A001"), causing
# false key collisions and "atoms not the same" errors.  Cap at _MAX_RESID per
# segment and spread water across SOLV/SOL1/SOL2/… segments to stay within limit.
_MAX_RESID = 9000
_WATER_SEG_NAMES = ["SOLV"] + [f"SOL{i}" for i in range(1, 30)]


def _water_seg_info(wi: int) -> tuple[str, int]:
    """Return (segid, local_resid) for the wi-th water molecule (0-based)."""
    seg_num   = wi // _MAX_RESID
    local_rid = (wi % _MAX_RESID) + 1
    return _WATER_SEG_NAMES[seg_num], local_rid


# PSF atom line format (same extended layout as pdb_export.export_psf):
# %10d %-8s %-8s %-8s %-8s %-6s %14.6f%14.6f%9d
def _psf_atom_line(
    serial: int,
    segid: str,
    resid: int,
    resname: str,
    atomname: str,
    atomtype: str,
    charge: float,
    mass: float,
) -> str:
    return (
        f"{serial:>10d} "
        f"{segid:<8s} "
        f"{str(resid):<8s} "
        f"{resname:<8s} "
        f"{atomname:<8s} "
        f"{atomtype:<6s} "
        f"{charge:>14.6f}"
        f"{mass:>14.6f}"
        f"{'0':>9s}"
    )


def _psf_bond_lines(bonds: list[tuple[int, int]]) -> list[str]:
    """Format PSF NBOND data lines (4 pairs per line, 8-char serial cols)."""
    lines = []
    for i in range(0, len(bonds), 4):
        chunk = bonds[i:i + 4]
        lines.append("".join(f"{a:8d}{b:8d}" for a, b in chunk))
    return lines


def _psf_angle_lines(angles: list[tuple[int, int, int]]) -> list[str]:
    """Format PSF NTHETA data lines (3 triplets per line, 8-char serial cols)."""
    lines = []
    for i in range(0, len(angles), 3):
        chunk = angles[i:i + 3]
        lines.append("".join(f"{a:8d}{b:8d}{c:8d}" for a, b, c in chunk))
    return lines


def _find_last_atom_serial(psf_text: str) -> int:
    """Return the highest serial number in the !NATOM section."""
    in_natom = False
    last_serial = 0
    for line in psf_text.splitlines():
        if "!NATOM" in line:
            in_natom = True
            continue
        if in_natom:
            stripped = line.strip()
            if not stripped or stripped.startswith("!"):
                break
            try:
                serial = int(line.split()[0])
                last_serial = max(last_serial, serial)
            except (ValueError, IndexError):
                pass
    return last_serial


def _extend_psf(
    dna_psf: str,
    waters: list[_Water],
    na_pos: list[tuple[float, float, float]],
    cl_pos: list[tuple[float, float, float]],
) -> str:
    """Extend a complete DNA PSF with TIP3P water and NaCl ions.

    Modifies NATOM, NBOND, NTHETA section counts and appends new entries.
    Water angles (H1-OH2-H2) and bonds (OH2-H1, OH2-H2, H1-H2) are added.
    Ions have no bonds or angles.
    """
    base_serial = _find_last_atom_serial(dna_psf)

    # ── Build new atom lines and bond/angle tables ────────────────────────────
    new_atom_lines: list[str] = []
    new_bonds: list[tuple[int, int]] = []
    new_angles: list[tuple[int, int, int]] = []

    serial = base_serial

    for wi, w in enumerate(waters):
        s_oh2 = serial + 1
        s_h1  = serial + 2
        s_h2  = serial + 3
        serial += 3
        segid, resid = _water_seg_info(wi)

        new_atom_lines.append(
            _psf_atom_line(s_oh2, segid, resid, "TIP3", "OH2", *_TIP3_PARAMS["OH2"])
        )
        new_atom_lines.append(
            _psf_atom_line(s_h1,  segid, resid, "TIP3", "H1",  *_TIP3_PARAMS["H1"])
        )
        new_atom_lines.append(
            _psf_atom_line(s_h2,  segid, resid, "TIP3", "H2",  *_TIP3_PARAMS["H2"])
        )
        # Bonds: OH2-H1, OH2-H2, H1-H2 (H1-H2 needed for SHAKE in NAMD)
        new_bonds.extend([(s_oh2, s_h1), (s_oh2, s_h2), (s_h1, s_h2)])
        # Angle: H1-OH2-H2
        new_angles.append((s_h1, s_oh2, s_h2))

    ion_resid = 1
    for i, (x, y, z) in enumerate(na_pos):
        serial += 1
        new_atom_lines.append(
            _psf_atom_line(serial, "IONS", ion_resid + i, "SOD", "SOD", *_ION_PARAMS["SOD"])
        )
    ion_resid += len(na_pos)

    for i, (x, y, z) in enumerate(cl_pos):
        serial += 1
        new_atom_lines.append(
            _psf_atom_line(serial, "IONS", ion_resid + i, "CLA", "CLA", *_ION_PARAMS["CLA"])
        )

    # ── Patch PSF sections ────────────────────────────────────────────────────
    # We scan the PSF line by line, update each !NXXX count, and append data.

    n_new_atoms  = len(new_atom_lines)
    n_new_bonds  = len(new_bonds)
    n_new_angles = len(new_angles)

    natom_re  = re.compile(r"^(\s*)(\d+)(\s+!NATOM.*)")
    nbond_re  = re.compile(r"^(\s*)(\d+)(\s+!NBOND.*)")
    ntheta_re = re.compile(r"^(\s*)(\d+)(\s+!NTHETA.*)")

    out: list[str] = []
    lines = dna_psf.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        m = natom_re.match(line)
        if m:
            old_count = int(m.group(2))
            out.append(f"{old_count + n_new_atoms:>8d}{m.group(3)}")
            i += 1
            # Copy existing atom data lines
            while i < n and lines[i].strip() and not lines[i].strip().startswith("!"):
                out.append(lines[i])
                i += 1
            # Append new atoms
            out.extend(new_atom_lines)
            out.append("")   # blank separator
            continue

        m = nbond_re.match(line)
        if m:
            old_count = int(m.group(2))
            out.append(f"{old_count + n_new_bonds:>8d}{m.group(3)}")
            i += 1
            # Copy existing bond data lines
            while i < n and lines[i].strip() and not lines[i].strip().startswith("!"):
                out.append(lines[i])
                i += 1
            # Append new bonds
            out.extend(_psf_bond_lines(new_bonds))
            out.append("")
            continue

        m = ntheta_re.match(line)
        if m:
            old_count = int(m.group(2))
            out.append(f"{old_count + n_new_angles:>8d}{m.group(3)}")
            i += 1
            # Copy existing angle data lines
            while i < n and lines[i].strip() and not lines[i].strip().startswith("!"):
                out.append(lines[i])
                i += 1
            # Append new angles
            out.extend(_psf_angle_lines(new_angles))
            out.append("")
            continue

        out.append(line)
        i += 1

    return "\n".join(out) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# §5  SOLVATED PDB
# ══════════════════════════════════════════════════════════════════════════════

_H36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def _h36(value: int, width: int) -> str:
    """Hybrid-36 encoding: integers beyond 10^width get letter prefixes."""
    limit = 10 ** width
    if value < limit:
        return str(value).rjust(width)
    # Standard hybrid-36 algorithm
    value -= limit
    base = 26 * (limit // 10)
    if value < base:
        prefix = "A"
    else:
        value -= base
        prefix = "a"
    digits = []
    v = value
    for _ in range(width - 1):
        digits.append(_H36_DIGITS[v % 36])
        v //= 36
    digits.append(prefix)
    return "".join(reversed(digits))


def _hetatm_record(
    serial: int,
    name: str,
    resname: str,
    chain: str,
    resseq: int,
    x: float,   # Angstrom
    y: float,
    z: float,
    segname: str = "",
) -> str:
    """Format a PDB HETATM record.

    segname (optional): written at cols 73-76 so NAMD can match PSF segid to
    PDB atoms.  Omitting it produces a standard 66-column record.  resseq must
    be ≤9999 (plain integer); values above 9999 produce hybrid-36 strings that
    NAMD cannot parse as residue numbers.
    """
    # PDB HETATM format:
    # cols 1-6:   record name "HETATM"
    # cols 7-11:  serial (5-char, hybrid-36)
    # col  12:    space
    # cols 13-16: atom name (left-pad 1 space for 1-letter element, else no pad)
    # col  17:    alternate location indicator (space)
    # cols 18-20: residue name (3-char right-justified; here 3-4 char)
    # col  21:    space (or chain in some variants)
    # col  22:    chain ID
    # cols 23-26: residue seq num (plain decimal, must be ≤9999)
    # col  27:    insertion code (space)
    # cols 28-30: spaces
    # cols 31-38: x (8.3f)
    # cols 39-46: y (8.3f)
    # cols 47-54: z (8.3f)
    # cols 55-60: occupancy  "  1.00"
    # cols 61-66: temp factor "  0.00"
    # cols 67-76: (optional) 6 spaces + 4-char segname
    # NAMD matches PDB atoms by (segid,resid,atomname) — not serial.
    # Cap at 9999 so the serial field always has a leading space (HETATM + space +
    # 4-digit serial = unambiguous record-type detection by NAMD's PDB parser).
    # 5-digit serials (10000+) abut "HETATM" with no space, causing NAMD to
    # misread the record type and silently skip the atom → count mismatch.
    pdb_serial = (serial - 1) % 9999 + 1
    name_field = f" {name:<3s}" if len(name) < 4 else f"{name:<4s}"
    base = (
        f"HETATM{pdb_serial:5d} {name_field} {resname:<4s}{chain}{resseq:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00"
    )
    if segname:
        base += f"      {segname:<4s}"
    return base


def _build_solvated_pdb(
    dna_pdb: str,
    waters: list[_Water],
    na_pos: list[tuple[float, float, float]],
    cl_pos: list[tuple[float, float, float]],
    box_nm: tuple[float, float, float],
    base_serial: int,
) -> str:
    """Build a PDB with DNA ATOM records + water/ion HETATM records.

    DNA atoms are taken verbatim from dna_pdb (ATOM/TER/LINK/REMARK lines).
    Water and ions are appended as HETATM records.
    CRYST1 is rewritten with solvated box dimensions.
    """
    NM_TO_A = 10.0
    bx, by, bz = box_nm

    # Replace or prepend CRYST1 with solvated box
    cryst1 = (
        f"CRYST1{bx * NM_TO_A:9.3f}{by * NM_TO_A:9.3f}{bz * NM_TO_A:9.3f}"
        f"  90.00  90.00  90.00 P 1           1"
    )

    # Strip old CRYST1 and END from dna_pdb; keep everything else
    dna_lines = [
        ln for ln in dna_pdb.splitlines()
        if not ln.startswith("CRYST1") and not ln.startswith("END")
    ]

    out: list[str] = [cryst1] + dna_lines

    serial = base_serial

    for wi, w in enumerate(waters):
        s_oh2 = serial + 1
        s_h1  = serial + 2
        s_h2  = serial + 3
        serial += 3
        segid, resid = _water_seg_info(wi)
        ox_a  = w.ox  * NM_TO_A
        oy_a  = w.oy  * NM_TO_A
        oz_a  = w.oz  * NM_TO_A
        h1x_a = w.h1x * NM_TO_A
        h1y_a = w.h1y * NM_TO_A
        h1z_a = w.h1z * NM_TO_A
        h2x_a = w.h2x * NM_TO_A
        h2y_a = w.h2y * NM_TO_A
        h2z_a = w.h2z * NM_TO_A
        out.append(_hetatm_record(s_oh2, "OH2", "TIP3", "W", resid, ox_a,  oy_a,  oz_a,  segname=segid))
        out.append(_hetatm_record(s_h1,  "H1",  "TIP3", "W", resid, h1x_a, h1y_a, h1z_a, segname=segid))
        out.append(_hetatm_record(s_h2,  "H2",  "TIP3", "W", resid, h2x_a, h2y_a, h2z_a, segname=segid))

    ion_resid = 1
    for i, (x_nm, y_nm, z_nm) in enumerate(na_pos):
        serial += 1
        out.append(_hetatm_record(
            serial, "SOD", "SOD", "I", ion_resid + i,
            x_nm * NM_TO_A, y_nm * NM_TO_A, z_nm * NM_TO_A,
            segname="IONS",
        ))

    ion_resid = len(na_pos) + 1
    for i, (x_nm, y_nm, z_nm) in enumerate(cl_pos):
        serial += 1
        out.append(_hetatm_record(
            serial, "CLA", "CLA", "I", ion_resid + i,
            x_nm * NM_TO_A, y_nm * NM_TO_A, z_nm * NM_TO_A,
            segname="IONS",
        ))

    out.append("END")
    return "\n".join(out) + "\n"


# ══════════════════════════════════════════════════════════════════════════════
# §6  NAMD CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

def _render_solvated_namd_conf(
    name: str,
    box_nm: tuple[float, float, float],
    n_atoms: int,
) -> str:
    bx, by, bz = box_nm
    bx_a, by_a, bz_a = bx * 10, by * 10, bz * 10
    cx, cy, cz = bx_a / 2, by_a / 2, bz_a / 2
    return f"""\
# NAMD explicit-solvent configuration generated by NADOC
# System: {name}  ({n_atoms:,} atoms, TIP3P water + 150 mM NaCl)
# Mode:   CUDASOAintegrate (GPU-resident), PME electrostatics, NPT 310 K / 1 atm

structure          {name}.psf
coordinates        {name}.pdb
outputName         output/{name}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_na.str

# ── Periodic boundary conditions ──────────────────────────────────────────────
cellBasisVector1   {bx_a:.3f}  0.000    0.000
cellBasisVector2   0.000    {by_a:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz_a:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on

# ── PME electrostatics ────────────────────────────────────────────────────────
PME                yes
PMEGridSpacing     1.0

# ── Nonbonded ─────────────────────────────────────────────────────────────────
cutoff             12.0
switching          on
switchdist         10.0
pairlistdist       14.0
exclude            scaled1-4
oneFourScaling     1.0

# ── Constraints ───────────────────────────────────────────────────────────────
rigidBonds         water
rigidTolerance     1.0e-8

# ── Thermostat — Langevin 310 K ────────────────────────────────────────────────
temperature        310
langevin           on
langevinDamping    5
langevinTemp       310
langevinHydrogen   off

# ── Barostat — Langevin piston (NPT) ──────────────────────────────────────────
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  200.0
langevinPistonDecay   100.0
langevinPistonTemp    310

# ── Integrator ────────────────────────────────────────────────────────────────
timestep           2.0        ;# 2 fs — safe with rigidBonds water
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# ── GPU-resident integration (NAMD3, requires explicit solvent + PME) ─────────
CUDASOAintegrate   on

# ── Output ────────────────────────────────────────────────────────────────────
outputEnergies     500
dcdFreq            5000
dcdFile            output/{name}.dcd
xstFreq            5000
xstFile            output/{name}.xst
restartfreq        50000
binaryrestart      yes

# ── Run ───────────────────────────────────────────────────────────────────────
minimize           2000       ;# brief EM to relieve any solvation clashes
reinitvels         310
run                250000     ;# 500 ps NPT equilibration (default)
"""


# ══════════════════════════════════════════════════════════════════════════════
# §7  README / LAUNCH
# ══════════════════════════════════════════════════════════════════════════════

_README = """\
{name} — NAMD Explicit-Solvent Simulation Package
=======================================================
Generated by NADOC.

Contents
--------
{name}.pdb          Solvated structure (DNA + TIP3P water + NaCl ions)
{name}.psf          Complete topology (bonds/angles/dihedrals)
namd.conf           NAMD configuration (GPU-resident, PME, NPT 310 K / 1 atm)
forcefield/         CHARMM36 parameters
launch.sh           Automated launch script (installs NAMD3 if absent)

Quick start
-----------
    bash launch.sh

Alternatively, run manually:
    mkdir -p output
    namd3 +p4 +devices 0 namd.conf > output/namd.log &

Requirements
------------
- NAMD 3.0+ (CUDA build) — automatically downloaded by launch.sh
- CUDA-capable GPU
- ~16 GB RAM for large DNA origami

Performance
-----------
CUDASOAintegrate on: GPU-resident integration.  All force evaluations
(bonded, nonbonded, PME reciprocal) run on the GPU.  Typical 300k-atom
system: 10-15 ns/day on RTX 2080 Super.

Typical workflow
----------------
1. launch.sh runs 2000-step EM + 500 ps NPT equilibration by default.
2. Extend production in namd.conf (increase `run` or restart from .restart.coor).
3. Analyse with VMD: vmd {name}.psf output/{name}.dcd
"""

_LAUNCH_SH = """\
#!/usr/bin/env bash
# NADOC NAMD Explicit-Solvent Launch Script
# Usage: bash launch.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

# ── Locate NAMD3 ──────────────────────────────────────────────────────────────
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
$NAMD +p$N_THREADS +devices 0 namd.conf 2>&1 | tee output/{name}_namd.log
echo "Done. Trajectory: output/{name}.dcd"
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
# §8  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def build_namd_solvated_package(
    design: Design,
    *,
    padding_nm: float = 1.2,
    ion_conc_mM: float = 150.0,
    seed: int = 42,
) -> bytes:
    """Return raw ZIP bytes of a complete NAMD explicit-solvent package.

    Parameters
    ----------
    design:
        Active NADOC design.
    padding_nm:
        Water padding around the DNA bounding box (nm). Default 1.2 nm.
    ion_conc_mM:
        Target NaCl bulk concentration (mM). Default 150 mM.
    seed:
        Random seed for reproducible ion placement.

    Returns
    -------
    bytes
        ZIP file contents ready to write to disk or serve as a download.
    """
    _check_ff_files()

    name = (design.metadata.name or "design").replace(" ", "_")
    prefix = f"{name}_namd_solvated/"

    # 1. Build DNA-only PDB and complete PSF
    dna_pdb = export_pdb(design, box_margin_nm=padding_nm)
    dna_psf = complete_psf(design)

    with tempfile.TemporaryDirectory(prefix="nadoc_solvate_") as _tmpdir:
        tmpdir = Path(_tmpdir)

        # 2. GROMACS solvation → water positions + solvated box dimensions
        waters, box_nm = _gmx_solvate(dna_pdb, padding_nm, tmpdir)

    # 3. Count DNA net charge (1 phosphate = -1 charge) and calculate ion counts
    dna_charge = _count_dna_charge(dna_pdb)
    n_na, n_cl = _ion_counts(len(waters), dna_charge, ion_conc_mM, box_nm)

    # 4. Place ions (replace water molecules)
    waters, na_pos, cl_pos = _place_ions(waters, n_na, n_cl, seed=seed)

    # 5. Find last DNA atom serial for sequential numbering
    dna_n_atoms = _find_last_atom_serial(dna_psf)
    n_total = dna_n_atoms + len(waters) * 3 + n_na + n_cl

    # 6. Build solvated PSF
    solvated_psf = _extend_psf(dna_psf, waters, na_pos, cl_pos)

    # 7. Build solvated PDB
    solvated_pdb = _build_solvated_pdb(
        dna_pdb, waters, na_pos, cl_pos, box_nm, dna_n_atoms
    )

    # 8. Render NAMD conf
    namd_conf = _render_solvated_namd_conf(name, box_nm, n_total)

    readme  = _README.format(name=name)
    prompt  = _AI_PROMPT.replace("{name}", name)
    launch  = _LAUNCH_SH.format(name=name)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + f"{name}.pdb",             solvated_pdb)
        zf.writestr(prefix + f"{name}.psf",             solvated_psf)
        zf.writestr(prefix + "namd.conf",               namd_conf)
        zf.writestr(prefix + "README.txt",              readme)
        zf.writestr(prefix + "AI_ASSISTANT_PROMPT.txt", prompt)
        zf.writestr(prefix + "scripts/monitor.py",      _MONITOR_PY)

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


def get_solvation_stats(
    design: Design,
    *,
    padding_nm: float = 1.2,
    ion_conc_mM: float = 150.0,
) -> dict:
    """Return a dict with estimated system size without building the package.

    Runs gmx editconf + solvate to count water molecules, then returns
    atom counts and box dimensions.  Fast (~10 s) compared to the full
    PSF/PDB build (~60-120 s for large designs).
    """
    dna_pdb = export_pdb(design, box_margin_nm=padding_nm)
    dna_psf = complete_psf(design)
    dna_n_atoms = _find_last_atom_serial(dna_psf)
    dna_charge  = _count_dna_charge(dna_pdb)

    with tempfile.TemporaryDirectory(prefix="nadoc_solvate_stats_") as _tmp:
        tmpdir = Path(_tmp)
        waters, box_nm = _gmx_solvate(dna_pdb, padding_nm, tmpdir)

    n_na, n_cl = _ion_counts(len(waters), dna_charge, ion_conc_mM, box_nm)
    n_water_atoms = len(waters) * 3
    n_total = dna_n_atoms + n_water_atoms + n_na + n_cl

    bx, by, bz = box_nm
    return {
        "dna_atoms":    dna_n_atoms,
        "n_waters":     len(waters),
        "water_atoms":  n_water_atoms,
        "n_na":         n_na,
        "n_cl":         n_cl,
        "total_atoms":  n_total,
        "box_nm":       box_nm,
        "box_volume_nm3": bx * by * bz,
        "dna_charge":   dna_charge,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check_ff_files() -> None:
    missing = [f for f in _FF_FILES if not (_FF_DIR / f).exists()]
    if missing:
        raise RuntimeError(
            "Force field files not found in backend/data/forcefield/: "
            + ", ".join(missing)
        )


_AI_PROMPT = """\
You are assisting with a NAMD explicit-solvent molecular dynamics simulation of
a DNA origami nanostructure called {name}.

The system was set up by NADOC using:
  - CHARMM36 force field for DNA
  - TIP3P explicit water model
  - 150 mM NaCl
  - CUDASOAintegrate (GPU-resident integration)
  - PME electrostatics
  - NPT ensemble (310 K, 1 atm)

Key files:
  {name}.pdb    — solvated structure
  {name}.psf    — complete topology
  namd.conf     — simulation parameters
  output/       — trajectory output

To extend the simulation, increase `run` in namd.conf and restart from the
latest .restart.coor / .restart.vel / .restart.xsc files in output/.

For analysis, use VMD:
  vmd {name}.psf output/{name}.dcd
"""
