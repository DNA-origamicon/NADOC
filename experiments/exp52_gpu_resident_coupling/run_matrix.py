#!/usr/bin/env python3
"""exp52 — is GPU-resident coupled to the integrator, or only to system size?

THE PROBLEM.  ``build_production_conf`` drops ``GPUresident`` whenever the timestep is
1 fs (md_protocols.py, ``gpu_line = "" if ts == 1.0 else _res_line``), overriding the
user's own Advanced-card choice, on the stated grounds that "at the sizes anyone picks
1 fs for, resident is a measured loss".  That is a THROUGHPUT heuristic welded onto a
PHYSICS axis, and it makes the dropdown silently inoperative at 1 fs.

A second, stronger claim is still live in two places — md_protocols.py:798-801 and
LESSONS.md K6:

    "the 4 fs timestep survives only under GPUresident's GPU constraint solver.
     Without it, the CPU RATTLE path blows up on the first step"

That claim is contradicted ~60 lines below its own statement (md_protocols.py:860-866,
"SUPERSEDED 2026-07-12"), and the two measurements behind the disagreement were made on
DIFFERENT systems (1.44M-atom GT_corner_v2 vs a carved 6hbx100_90deg).  exp51 already ran
4 fs + HMR with no GPUresident line for 25 ps at 101.5 ns/day with zero RATTLE failures,
which is evidence against it at this size — but exp51 never ran the resident-ON arm, so it
could not compare.

THE MATRIX.  The three sound integrator settings x GPUresident {on, off}, on the SAME
solvated, minimised, equilibrated system exp51 built (reused, not rebuilt — so this is
comparable cell-for-cell with exp51's numbers).

                        resident off        resident on
    1 fs, flexible      exp51 baseline      does NAMD even ACCEPT it?
    2 fs, rigid         exp51 baseline      throughput delta at 32.7k atoms
    4 fs, rigid + HMR   exp51 baseline      throughput delta + the K6 claim

PRE-REGISTERED PREDICTIONS:

  Q1  GPUresident is ACCEPTED at 1 fs with rigidBonds none.  If NAMD refuses it, the
      coupling in the code is a real incompatibility and should stay (but be stated as
      one).  If NAMD accepts it, the coupling is a throughput opinion overriding a user
      choice, and should become a default rather than a rule.
  Q2  Resident is a LOSS at this size (32.7k atoms, below the ~100k crossover), at every
      timestep — so the heuristic is right about the direction even if wrong to enforce it.
  Q3  4 fs + HMR runs with resident OFF (refuting K6 at this size), which exp51 already
      showed once.

    python experiments/exp52_gpu_resident_coupling/run_matrix.py \\
        --package experiments/exp51_integrator_factorial/runs/2hb_1xT/pkg_fast/package/2hb_1xT_namd_solvated \\
        -o experiments/exp52_gpu_resident_coupling/runs/2hb_1xT

Do not run while another NAMD job owns the GPU — every number here is a timing.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core.md_protocols import (  # noqa: E402
    CUTOFF_ANG,
    PAIRLISTDIST_ANG,
    PME_GRID_SPACING,
    SWITCHDIST_ANG,
)
from backend.core.namd_runner import find_namd  # noqa: E402

PROBE_PS = 25.0

#: (label, dt, rigidBonds, masses) — the three combinations exp51 found sound.
INTEGRATORS = [
    ("1fs", 1.0, "none", "std"),
    ("2fs", 2.0, "all", "std"),
    ("4fs", 4.0, "all", "hmr"),
]


def _run_namd(conf: Path, cwd: Path, namd: str, threads: int) -> dict:
    log = cwd / f"{conf.stem}.log"
    t0 = time.monotonic()
    with log.open("w") as fh:
        proc = subprocess.run([namd, f"+p{threads}", "+setcpuaffinity", conf.name],
                              cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    wall = time.monotonic() - t0
    text = log.read_text(errors="ignore")
    died = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("ERROR:", "FATAL ERROR")):
            died = s
            break
    finished = "End of program" in text
    last_step = 0
    for line in reversed(text.splitlines()):
        if line.startswith("ENERGY:"):
            try:
                last_step = int(line.split()[1])
            except (IndexError, ValueError):
                pass
            break
    ns_day = ms_step = None
    bm = re.findall(r"Benchmark time:.*?([\d.eE+-]+) s/step\s+([\d.eE+-]+) (ns/day|days/ns)",
                    text)
    if bm:
        ms_step = float(bm[-1][0]) * 1000.0
        val, unit = float(bm[-1][1]), bm[-1][2]
        ns_day = val if unit == "ns/day" else (1.0 / val if val else None)
    # Did NAMD actually engage the resident path, or silently ignore the directive?
    engaged = bool(re.search(r"CUDASOAintegrate|GPU-resident mode|SOA integrat",
                             text, re.IGNORECASE))
    return {"ok": proc.returncode == 0 and died is None and finished,
            "error": died, "finished": finished, "last_step": last_step,
            "ns_day": ns_day, "ms_step": None if ms_step is None else round(ms_step, 3),
            "resident_engaged": engaged, "wall_s": round(wall, 1), "log": log.name}


def _conf(*, name: str, psf: str, stem: str, extras: str, start: str, rigid: str,
          dt: float, steps: int, resident: bool) -> str:
    """Identical to exp51's cell conf except for ONE line: GPUresident."""
    res = "GPUresident        on\n" if resident else ""
    return f"""\
structure          {psf}
coordinates        {stem}.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
wrapAll            off
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         {SWITCHDIST_ANG:.1f}
cutoff             {CUTOFF_ANG:.1f}
pairlistdist       {PAIRLISTDIST_ANG:.1f}
PME                yes
PMEGridSpacing     {PME_GRID_SPACING:g}

rigidBonds         {rigid}
rigidTolerance     1.0e-8
timestep           {dt:g}
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10

{res}langevin           on
langevinTemp       300
langevinDamping    1
langevinHydrogen   off
{start}
outputname         output/{name}
outputEnergies     {max(20, int(round(100.0 / dt)))}
restartfreq        {max(steps, 1)}
binaryrestart      yes
dcdfreq            {max(20, steps // 5)}

run                {steps}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True,
                    help="an exp51 package dir (reused so the numbers are comparable)")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--equil", default=None,
                    help="checkpoint name to start from (default: the exp51 equilibration)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    pkg = args.package.resolve()
    manifest = json.loads((pkg / "manifest.json").read_text())
    stem = manifest["name_stem"]
    equil = args.equil or f"{stem}_x51_equil"
    for ext in ("coor", "xsc"):
        if not (pkg / "output" / f"{equil}.{ext}").exists():
            print(f"missing {equil}.{ext} in {pkg/'output'} — run exp51 first")
            return 1
    if args.fresh and args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)

    namd = find_namd()
    pdb = pkg / f"{stem}.pdb"
    n_atoms = sum(1 for ln in pdb.read_text().splitlines()
                  if ln.startswith(("ATOM", "HETATM")))
    extras = ("extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n"
              if (pkg / "mgh_extrabonds.txt").exists() else "")
    start = (f"binCoordinates     output/{equil}.coor\n"
             f"extendedSystem     output/{equil}.xsc\n"
             f"temperature        300\n")
    print(f"NAMD:    {namd}\npackage: {pkg.name}\natoms:   {n_atoms:,}\n"
          f"start:   {equil}\n")

    report = {"package": str(pkg), "n_atoms": n_atoms, "probe_ps": PROBE_PS, "cells": {}}
    print(f"    {'cell':18s} {'run':>6s} {'engaged':>8s} {'ns/day':>9s} {'ms/step':>9s}  error")
    for label, dt, rigid, mass in INTEGRATORS:
        psf = f"{stem}_hmr.psf" if mass == "hmr" else f"{stem}.psf"
        steps = max(100, int(round(PROBE_PS * 1000.0 / dt)))
        steps -= steps % 20
        for resident in (False, True):
            cid = f"{label}_resident_{'on' if resident else 'off'}"
            name = f"{stem}_x52_{cid}"
            (pkg / f"{name}.conf").write_text(_conf(
                name=name, psf=psf, stem=stem, extras=extras, start=start,
                rigid=rigid, dt=dt, steps=steps, resident=resident))
            r = _run_namd(pkg / f"{name}.conf", pkg, namd, args.threads)
            report["cells"][cid] = {"timestep_fs": dt, "rigidbonds": rigid,
                                    "masses": mass, "resident_requested": resident, **r}
            print(f"    {cid:18s} {'ok' if r['ok'] else 'FAIL':>6s} "
                  f"{str(r['resident_engaged']):>8s} {(r['ns_day'] or 0):>9.1f} "
                  f"{(r['ms_step'] or 0):>9.3f}  {r['error'] or ''}")

    # ── Score the questions ─────────────────────────────────────────────────────
    cells = report["cells"]

    def ok(cid):
        return bool(cells.get(cid, {}).get("ok"))

    def nsday(cid):
        return cells.get(cid, {}).get("ns_day") or 0.0

    q1 = ok("1fs_resident_on")
    speedups = {}
    for label, _dt, _r, _m in INTEGRATORS:
        off, on = nsday(f"{label}_resident_off"), nsday(f"{label}_resident_on")
        speedups[label] = round(on / off, 3) if off else None
    q2 = all(v is not None and v < 1.0 for v in speedups.values())
    q3 = ok("4fs_resident_off")
    report["speedup_resident_on_over_off"] = speedups
    report["answers"] = {
        "Q1 resident is accepted at 1 fs with flexible bonds": q1,
        "Q2 resident is a loss at this size, at every timestep": q2,
        "Q3 4 fs + HMR runs with resident OFF (refutes K6 here)": q3,
    }
    (args.out / "exp52_report.json").write_text(json.dumps(report, indent=2))

    print("\n=== ANSWERS ===")
    for text, held in report["answers"].items():
        print(f"  {'YES' if held else 'NO ':3s}  {text}")
    print("\n  resident speedup (on/off): "
          + ", ".join(f"{k} {v}x" for k, v in speedups.items()))
    print(f"  report: {args.out / 'exp52_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
