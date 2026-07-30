#!/usr/bin/env python3
"""Build a vacuum ENRG-MD shape-relaxation package from a NADOC design.

WHY THIS EXISTS
---------------
The Aksimentiev origami pipeline relaxes large-scale shape CHEAPLY first (vacuum
ENRG-MD, no solvent, no PME) and only then solvates and runs the restrained k-ladder.
NADOC solvates the *idealised* build and does all of the shape relaxation in explicit
water, which is the most expensive place to do it.  This script builds the missing
cheap step so we can measure whether it (a) shortens the overall relax and (b) lets us
cut ladder stages.

WHY NOT `enrgmd` (the console script mrdna installs)
----------------------------------------------------
``enrgmd`` accepts cadnano JSON / vHelix / PDB and calls ``_generate_atomic_model()``,
i.e. it builds its OWN atomic model.  cadnano has no representation for extra bases at
crossovers — the entire subject of these runs — so a JSON round-trip silently drops
them, and the regenerated atom ordering would not match a NADOC PSF anyway.  So we
reuse mrdna's *recipe* against NADOC's own topology and atom indices.

WHAT IS FAITHFUL AND WHAT IS NOT
--------------------------------
Faithful (read from mrdna/segmentmodel.py, ``write_namd_configuration``):
  PME off, cutoff 10 / switch 8 / pairlist 12, fixed cell = structure bbox + margin 30,
  wrapAll off, NO barostat, 2 fs with rigidBonds all, langevinDamping 0.1 ("less
  friction for faster relaxation"), langevinHydrogen off, two-stage minimisation.

Deviation, deliberate: the ENM.  mrdna's vacuum ENM is a 52-key TEMPLATE table of
measured atom-pair distances keyed by (pairtype, seq1, seq2) over pair/stack/cross/
paircross neighbours at k=0.1.  We use NADOC's existing tutorial-style base-ring ENM
(nine ring atoms, inter-residue, 8 A cutoff, measured lengths) because it already maps
onto our atom indices and is already validated in our pipeline.  Both hold local duplex
geometry while global shape moves; they are not identical and this is recorded here so
the comparison is not mistaken for a reproduction.

Interhelical "push" bonds (k=1.0 kcal/mol/A^2, r0=31 A) ARE implemented to mrdna's rule
-- see push_bonds.py.  On a 2-helix design they correctly yield zero.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from backend.core.md_protocols import write_aksimentiev_enm_files  # noqa: E402
from backend.core.models import Design  # noqa: E402
from backend.core.namd_topology import build_charmm_psfgen_topology  # noqa: E402

from push_bonds import interhelical_push_bonds  # noqa: E402

# ── mrdna vacuum-run constants (mrdna/segmentmodel.py) ────────────────────────
MARGIN_ANG = 30.0
CUTOFF_ANG = 10.0
SWITCHDIST_ANG = 8.0
PAIRLISTDIST_ANG = 12.0
TIMESTEP_FS = 2.0
LANGEVIN_DAMPING = 0.1        # deliberately low: relax fast, this is not sampling
LANGEVIN_TEMP = 295.0         # mrdna's default; initial velocities are drawn at 300
MINIMIZE_STEPS = 2400         # per stage; mrdna does 4800//2 fixed then 4800//2 free
#: Minimisation has to scale with the structure. An idealised origami build starts with
#: enormous VDW strain (1e9 kcal/mol on a 224k-atom 24hb) concentrated at inserted bases,
#: and mrdna's fixed 4800 steps leaves thousands of atoms still flagged "BAD CONTACTS".
#: That residual strain does not fail at startup — the 24hb ran cleanly for 0.26 ns and
#: then lost an atom to a RATTLE constraint failure. One step per 10 atoms clears it.
MINIMIZE_ATOMS_PER_STEP = 10
#: Cell padding beyond the solute bbox.  Vacuum + no PME means empty space is nearly
#: free, and a generous cell keeps `margin 30` from ever clipping the patch grid.
CELL_PAD_ANG = 80.0

ENM_K = 0.5                   # the ladder's stiffest rung; nothing is released in vacuum


def load_design(path: Path) -> Design:
    raw = path.read_bytes()
    if raw[:2] == b"PK":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith(".json"))
            return Design.from_dict(json.loads(z.read(name)))
    return Design.from_dict(json.loads(raw))


def _pdb_positions(pdb_text: str) -> np.ndarray:
    out = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            out.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return np.asarray(out, dtype=float)


def write_vacuum_conf(out: Path, stem: str, cell: np.ndarray, *, num_steps: int,
                      extrabonds: list[str], minimize_steps: int = MINIMIZE_STEPS) -> Path:
    eb = "\n".join(f"extraBondsFile      {f}" for f in extrabonds)
    conf = f"""# Vacuum ENRG-MD shape relaxation — recipe from mrdna/segmentmodel.py
# (Maffeo & Aksimentiev; the same lab's successor to the 2016 ENRG-MD web service).
set prefix {stem}
set out output/$prefix

structure           $prefix.psf
coordinates         $prefix.pdb
outputName          $out
XSTfile             $out.xst
DCDfile             $out.dcd

paraTypeCharmm      on
parameters          forcefield/par_all36_na.prm
parameters          forcefield/par_stub_ions_nbfix.str

wrapAll             off

exclude             scaled1-4
1-4scaling          1.0
switching           on
switchdist          {SWITCHDIST_ANG:g}
cutoff              {CUTOFF_ANG:g}
pairlistdist        {PAIRLISTDIST_ANG:g}
margin              {MARGIN_ANG:g}

timestep            {TIMESTEP_FS:g}
rigidBonds          all
nonbondedFreq       1
fullElectFrequency  3
stepspercycle       12

# No solvent, no periodic electrostatics.  Coulomb is TRUNCATED at the cutoff, which
# is what makes an unscreened polyanion tractable in vacuum at all; the interhelical
# push bonds re-supply the long-range spacing that truncation throws away.
PME                 no

langevin            on
langevinDamping     {LANGEVIN_DAMPING:g}
langevinTemp        {LANGEVIN_TEMP:g}
langevinHydrogen    off

# NO barostat: the cell is fixed and empty.  A piston here is what collapsed the
# carved-box runs (see backend/core/md_cell_health.py).
useGroupPressure    yes

xstFreq             4800
outputEnergies      4800
dcdfreq             4800
restartfreq         48000

extraBonds          on
{eb}

cellBasisVector1    {cell[0]:.1f} 0 0
cellBasisVector2    0 {cell[1]:.1f} 0
cellBasisVector3    0 0 {cell[2]:.1f}
cellOrigin          0 0 0

# Initial velocities. mrdna draws these at 300 K even though the Langevin bath is held
# at 295 K; NAMD also REQUIRES a temperature (or a velocity file) before `minimize`.
temperature         300

minimize            {minimize_steps}
run                 {num_steps}
"""
    path = out / f"{stem}_vacuum.conf"
    path.write_text(conf)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("design", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--ns", type=float, default=2.0,
                    help="vacuum dynamics length in ns (mrdna's default is 2 ns)")
    ap.add_argument("--push-r0", default="31",
                    help="interhelical push-bond target: mrdna's '31' (A), 'measured' "
                         "(each bond keeps its built length — shape-preserving), or "
                         "'off' to omit the term entirely")
    args = ap.parse_args()
    if args.push_r0 == "off":
        push_r0, push_on = None, False
    elif args.push_r0 == "measured":
        push_r0, push_on = None, True
    else:
        push_r0, push_on = float(args.push_r0), True

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "output").mkdir(exist_ok=True)

    design = load_design(args.design)
    stem = (design.metadata.name or args.design.stem).replace(" ", "_")
    print(f"[1/5] {stem}: {len(design.helices)} helices, {len(design.strands)} strands, "
          f"{len(design.crossovers)} crossovers")

    print("[2/5] psfgen: building all-hydrogen CHARMM DNA topology (extra bases intact)…")
    build = build_charmm_psfgen_topology(design)
    (out / f"{stem}.psf").write_text(build.psf_text)
    (out / f"{stem}.pdb").write_text(build.pdb_text)
    pos = _pdb_positions(build.pdb_text)
    print(f"      {len(pos):,} atoms")

    print(f"[3/5] base-ring ENM at k={ENM_K} (8 A cutoff, inter-residue)…")
    enm = write_aksimentiev_enm_files(out / f"{stem}.pdb", out, stem,
                                      scales=(ENM_K,), cut_ang=8.0)
    enm_file = f"{stem}_k{ENM_K:g}.enm.extra"
    print(f"      {enm.get('n_bonds', '?')} restraints -> {enm_file}")

    print(f"[4/5] interhelical push bonds (k=1.0, r0={args.push_r0}, mrdna rule)…")
    pb = interhelical_push_bonds(design, build.pdb_text, r0_ang=push_r0)
    push_file = f"{stem}_push.exb"
    (out / push_file).write_text(pb.text)
    print(f"      {pb.n_bonds} push bonds — {pb.reason}")

    use_push = push_on and pb.n_bonds > 0
    extrabonds = [enm_file] + ([push_file] if use_push else [])

    span = pos.max(axis=0) - pos.min(axis=0)
    cell = span + 2 * CELL_PAD_ANG
    num_steps = int(round(args.ns * 1e6 / TIMESTEP_FS / 12) * 12)
    # NAMD requires both step counts to be a multiple of stepsPerCycle (12).
    min_steps = max(MINIMIZE_STEPS, len(pos) // MINIMIZE_ATOMS_PER_STEP)
    min_steps = -(-min_steps // 12) * 12
    conf = write_vacuum_conf(out, stem, cell, num_steps=num_steps,
                             extrabonds=extrabonds, minimize_steps=min_steps)
    print(f"[5/5] cell {cell[0]:.0f}x{cell[1]:.0f}x{cell[2]:.0f} A, minimise "
          f"{min_steps:,}, {num_steps:,} steps = {args.ns:g} ns -> {conf.name}")

    ff = out / "forcefield"
    ff.mkdir(exist_ok=True)
    for f in ("par_all36_na.prm", "par_stub_ions_nbfix.str"):
        (ff / f).write_bytes((REPO / "backend" / "data" / "forcefield" / f).read_bytes())

    (out / "build_info.json").write_text(json.dumps({
        "design": str(args.design), "stem": stem, "n_atoms": int(len(pos)),
        "n_enm_bonds": enm.get("n_bonds"), "n_push_bonds": pb.n_bonds,
        "push_r0": args.push_r0, "push_applied": use_push,
        "push_reason": pb.reason, "cell_ang": [float(x) for x in cell],
        "ns": args.ns, "steps": num_steps, "minimize_steps": min_steps, "enm_k": ENM_K,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
