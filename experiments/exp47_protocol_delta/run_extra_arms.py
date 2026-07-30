#!/usr/bin/env python3
"""Wave 1b — the REMEDIES for the failure wave 1 reproduces.

Wave 1's baseline arm dies at ~0.95 ns with

    FATAL ERROR: Periodic cell has become too small for original patch grid!

which is the same crash the original 2 ns production hit (`auto_resumes: 1`, 32 copies of
the string in its log) and which NADOC's runner silently auto-resumed past.  The tutorial
names this exact failure (Note 3: *"It might be necessary to disable Flexible cells and to
run the simulation in the NVT ensemble ... Running these types of simulations in NPT
guarantees this error will eventually occur"*) and names two remedies (Note 4).

    B1_nvt        barostat off — what NADOC's own carve-shell guard does for the ladder
                  but never for production
    B2_fixdna     the tutorial's PREFERRED remedy: NPT with the DNA held fixed so the box
                  can find the volume the water actually needs, without the solute being
                  squeezed
    B3_margin30   NAMD-side mitigation only (bigger patch grid margin); NOT from the
                  tutorial, included to separate "the cell is genuinely too small" from
                  "the patch grid was sized too tightly"

Run only after wave 1 finishes — one NAMD process at a time on this box.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_arms import BASE, START, STEM, STEPS, THREADS, WORK, stage  # noqa: E402

DNA_SEGIDS = ("D000", "D001", "D002")

EXTRA = {
    "B1_nvt":      {"_piston": "off"},
    "B2_fixdna":   {"_fix": True},
    "B3_margin30": {"_margin": "30"},
}
NOTES = {
    "B1_nvt": "langevinPiston off (NVT) — the carve-shell guard's rule, applied to production",
    "B2_fixdna": "NPT with fixedAtoms on the DNA — the tutorial's preferred remedy (Note 4)",
    "B3_margin30": "baseline + margin 30 — NAMD patch-grid headroom, not a tutorial setting",
}


def write_fixed_pdb(pkg: Path) -> str:
    """Full-system PDB with beta=1 on DNA — NAMD needs every atom present."""
    out = pkg / "fix_dna.pdb"
    if out.exists():
        return out.name
    lines = []
    for line in (pkg / f"{STEM}.pdb").read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            seg = line[72:76].strip()
            beta = "  1.00" if seg in DNA_SEGIDS else "  0.00"
            line = line[:60] + beta + line[66:]
        lines.append(line)
    out.write_text("\n".join(lines) + "\n")
    return out.name


def conf(arm: str, over: dict, pkg: Path) -> str:
    p = dict(BASE)
    piston = over.get("_piston", "on")
    margin = over.get("_margin")
    fix = over.get("_fix", False)
    extra = ""
    if margin:
        extra += f"margin             {margin}\n"
    if fix:
        extra += ("fixedAtoms         on\n"
                  f"fixedAtomsFile     {write_fixed_pdb(pkg)}\n"
                  "fixedAtomsCol      B\n"
                  "fixedAtomsForces   off\n")
    return f"""\
# exp47 arm {arm}: {NOTES[arm]}
structure          {STEM}_hmr.psf
coordinates        {STEM}.pdb
seed               54321
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
extraBonds         on
extraBondsFile     mgh_extrabonds.txt

cellBasisVector1   44.147  0.000    0.000
cellBasisVector2   0.000    66.635  0.000
cellBasisVector3   0.000    0.000    113.568
cellOrigin         22.073   33.318   56.784
wrapAll            {p['wrapAll']}
wrapWater          {p['wrapWater']}
{extra}
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         {p['switchdist']}
cutoff             {p['cutoff']}
pairlistdist       {p['pairlistdist']}
PME                yes
PMEGridSpacing     {p['PMEGridSpacing']}

rigidBonds         all
rigidTolerance     1.0e-8
timestep           4
nonbondedFreq      1
fullElectFrequency {p['fullElectFrequency']}
stepspercycle      {p['stepspercycle']}

langevin           on
langevinTemp       300
langevinDamping    {p['langevinDamping']}
langevinHydrogen   off

useGroupPressure   {p['useGroupPressure']}
useFlexibleCell    no
useConstantArea    no
langevinPiston     {piston}
langevinPistonTarget  1.01325
langevinPistonPeriod  {p['langevinPistonPeriod']}
langevinPistonDecay   {p['langevinPistonDecay']}
langevinPistonTemp 300

outputEnergies     2500
xstFreq            500
dcdFreq            2500
restartfreq        25000
binaryrestart      yes
constraints        off

firsttimestep      0
outputName         out/{arm}/{STEM}
dcdFile            out/{arm}/{STEM}.dcd
xstFile            out/{arm}/{STEM}.xst
binCoordinates     start/{START}.coor
binVelocities      start/{START}.vel
extendedSystem     start/{START}.xsc
run                {STEPS}
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--threads", type=int, default=THREADS)
    args = ap.parse_args(argv)

    namd = os.environ.get("NADOC_NAMD_BIN") or shutil.which("namd3")
    pkg = stage()
    manifest = WORK / "arms.json"
    done = json.loads(manifest.read_text()) if manifest.exists() else {}

    for arm in (args.only or list(EXTRA)):
        if done.get(arm, {}).get("status") == "ok":
            print(f"[skip] {arm}")
            continue
        (pkg / "out" / arm).mkdir(parents=True, exist_ok=True)
        (pkg / f"{arm}.conf").write_text(conf(arm, EXTRA[arm], pkg))
        print(f"[run ] {arm}: {NOTES[arm]}", flush=True)
        t0 = time.time()
        with open(pkg / f"{arm}.log", "w") as fh:
            rc = subprocess.call(
                [namd, "+p", str(args.threads), "+setcpuaffinity", "+devices", "0",
                 f"{arm}.conf"], cwd=pkg, stdout=fh, stderr=subprocess.STDOUT)
        txt = (pkg / f"{arm}.log").read_text(errors="replace")
        ok = rc == 0 and "End of program" in txt
        done[arm] = {"status": "ok" if ok else "FAILED", "rc": rc,
                     "wall_s": round(time.time() - t0, 1),
                     "overrides": {k: str(v) for k, v in EXTRA[arm].items()},
                     "note": NOTES[arm],
                     "ns_per_day": next((float(l.split("averaging")[1].split("ns/day")[0])
                                         for l in reversed(txt.splitlines())
                                         if "PERFORMANCE:" in l and "averaging" in l), None)}
        manifest.write_text(json.dumps(done, indent=1))
        print(f"[{'ok  ' if ok else 'FAIL'}] {arm}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
