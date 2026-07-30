#!/usr/bin/env python3
"""One-knob-at-a-time 2 ns production runs: NADOC defaults -> Aksimentiev tutorial.

Every arm starts from the SAME structure — the released (k=0 / MGHH-only) endpoint of
the 2hb_1xT ENM ladder, job ``c8bcf4c1406f``, in its PRE-COLLAPSE box
(44.147 x 66.635 x 113.568).  That is exactly the state from which the original 2 ns
production ran and shrank the cell by 38 %, so each arm answers "does this knob change
that, and does anything break?".

The timestep is deliberately NOT varied — 4 fs + HMR stays in every arm
(``feedback_namd_4fs_production_only``).

Measurement settings (xstFreq / dcdFreq / outputEnergies) are held IDENTICAL across arms
and are finer than production defaults, so the box trace is actually resolvable.  The
production default ``xstFreq 125000`` = one box sample per 500 ps, which is part of why
the original collapse went unnoticed; that is reported as a finding, not tested as an arm.

    uv run python experiments/exp47_protocol_delta/run_arms.py --list
    uv run python experiments/exp47_protocol_delta/run_arms.py            # run all, in order
    uv run python experiments/exp47_protocol_delta/run_arms.py --only A0 A8
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

SRC_JOB = Path("/media/jojo/Archive/NADOC_archive/c8bcf4c1406f/package/2hb_1xT_namd_solvated")
START = "2hb_1xT_04_300K_NPT_MGHH_only_p50"          # released ladder endpoint
WORK = Path("/media/jojo/Archive/exp47_protocol_delta")
STEM = "2hb_1xT"
NS = 2.0
DT_FS = 4.0
STEPS = int(NS * 1e6 / DT_FS)                         # 500,000 steps = 2 ns
THREADS = 16

# ── the NADOC production baseline, knob by knob ──────────────────────────────
BASE = {
    "switchdist": "10.0", "cutoff": "12.0", "pairlistdist": "14.0",
    "PMEGridSpacing": "1.0",
    "fullElectFrequency": "1", "stepspercycle": "10",
    "langevinDamping": "5",
    "useGroupPressure": "yes",
    "langevinPistonPeriod": "200.0", "langevinPistonDecay": "100.0",
    "wrapAll": "on", "wrapWater": "on",
}
# ── each arm = BASE with ONE group of keys moved to the tutorial value ────────
AKS = {
    "A1_piston":      {"langevinPistonPeriod": "1000.0", "langevinPistonDecay": "500.0"},
    "A2_cutoff":      {"switchdist": "8.0", "cutoff": "10.0", "pairlistdist": "12.0"},
    "A3_pmegrid":     {"PMEGridSpacing": "1.5"},
    "A4_fullelect":   {"fullElectFrequency": "2"},
    "A5_cycle":       {"stepspercycle": "12"},
    "A6_grouppress":  {"useGroupPressure": "no"},
    "A7_wrap":        {"wrapAll": "off", "wrapWater": "off"},
}
ARMS: dict[str, dict] = {"A0_baseline": {}}
ARMS.update(AKS)
ARMS["A8_all"] = {k: v for d in AKS.values() for k, v in d.items()}

NOTES = {
    "A0_baseline": "NADOC production exactly as shipped (control)",
    "A1_piston": "barostat 200/100 -> 1000/500 (tutorial); the knob most likely to matter",
    "A2_cutoff": "switch/cutoff/pairlist 10/12/14 -> 8/10/12 (tutorial; cheaper)",
    "A3_pmegrid": "PMEGridSpacing 1.0 -> 1.5 (tutorial; coarser, cheaper)",
    "A4_fullelect": "fullElectFrequency 1 -> 2 (tutorial; PME every other step)",
    "A5_cycle": "stepspercycle 10 -> 12 (tutorial)",
    "A6_grouppress": "useGroupPressure yes -> no (tutorial leaves it unset)",
    "A7_wrap": "wrapAll/wrapWater on -> off (tutorial; output-only, but fixes analysis)",
    "A8_all": "every conf-level tutorial value at once, still at 4 fs + HMR",
}
# NOT tested here — they need a re-solvation, not a conf change.  See rebuild_arms.py.
DEFERRED = {
    "padding_nm 1.2 -> 2.0": "tutorial pads the DNA bbox by +/-20 A per face",
    "water_shell_nm 1.2 -> 0": "tutorial fills the whole box; the carve is NADOC-only",
}


def conf(arm: str, over: dict) -> str:
    p = {**BASE, **over}
    # NAMD requires `run` to be a whole number of cycles; arms that change
    # stepspercycle therefore need their step count rounded to that multiple.
    spc = int(p["stepspercycle"])
    steps = int(round(STEPS / spc)) * spc
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
timestep           {DT_FS:g}
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
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  {p['langevinPistonPeriod']}
langevinPistonDecay   {p['langevinPistonDecay']}
langevinPistonTemp 300

# measurement settings — IDENTICAL in every arm, finer than production defaults so the
# box trace is resolvable (production ships xstFreq 125000 = one sample per 500 ps)
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
run                {steps}
"""


def stage() -> Path:
    pkg = WORK / "pkg"
    if not (pkg / f"{STEM}_hmr.psf").exists():
        pkg.mkdir(parents=True, exist_ok=True)
        for f in (f"{STEM}.psf", f"{STEM}_hmr.psf", f"{STEM}.pdb", "mgh_extrabonds.txt"):
            shutil.copy2(SRC_JOB / f, pkg / f)
        shutil.copytree(SRC_JOB / "forcefield", pkg / "forcefield", dirs_exist_ok=True)
        (pkg / "start").mkdir(exist_ok=True)
        for ext in ("coor", "vel", "xsc"):
            shutil.copy2(SRC_JOB / "output" / f"{START}.{ext}", pkg / "start" / f"{START}.{ext}")
    return pkg


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--threads", type=int, default=THREADS)
    args = ap.parse_args(argv)

    if args.list:
        for a in ARMS:
            print(f"{a:<16s} {NOTES[a]}")
            for k, v in ARMS[a].items():
                print(f"                   {k}: {BASE.get(k)} -> {v}")
        print("\nDEFERRED (need a re-solvation, not a conf change):")
        for k, v in DEFERRED.items():
            print(f"  {k:<28s} {v}")
        return 0

    namd = os.environ.get("NADOC_NAMD_BIN") or shutil.which("namd3")
    if not namd or not Path(namd).exists():
        raise SystemExit("NAMD not found — set NADOC_NAMD_BIN")

    pkg = stage()
    wanted = [a for a in ARMS if not args.only
              or any(a == o or a.startswith(o + "_") or a.split("_")[0] == o
                     for o in args.only)]
    manifest = WORK / "arms.json"
    done = json.loads(manifest.read_text()) if manifest.exists() else {}

    for arm in wanted:
        out = pkg / "out" / arm
        log = pkg / f"{arm}.log"
        if done.get(arm, {}).get("status") == "ok":
            print(f"[skip] {arm} already done")
            continue
        out.mkdir(parents=True, exist_ok=True)
        (pkg / f"{arm}.conf").write_text(conf(arm, ARMS[arm]))
        print(f"[run ] {arm}: {NOTES[arm]}", flush=True)
        t0 = time.time()
        with open(log, "w") as fh:
            rc = subprocess.call(
                [namd, "+p", str(args.threads), "+setcpuaffinity",
                 "+devices", "0", f"{arm}.conf"],
                cwd=pkg, stdout=fh, stderr=subprocess.STDOUT)
        dt = time.time() - t0
        txt = log.read_text(errors="replace")
        ok = rc == 0 and "End of program" in txt
        done[arm] = {
            "status": "ok" if ok else "FAILED", "rc": rc, "wall_s": round(dt, 1),
            "overrides": ARMS[arm], "note": NOTES[arm],
            "ns_per_day": next((float(l.split("averaging")[1].split("ns/day")[0])
                                for l in reversed(txt.splitlines())
                                if "PERFORMANCE:" in l and "averaging" in l), None),
        }
        manifest.write_text(json.dumps(done, indent=1))
        print(f"[{'ok  ' if ok else 'FAIL'}] {arm} in {dt/60:.1f} min "
              f"({done[arm]['ns_per_day']} ns/day)", flush=True)
    print("manifest:", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
