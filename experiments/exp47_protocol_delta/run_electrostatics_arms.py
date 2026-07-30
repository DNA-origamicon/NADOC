#!/usr/bin/env python3
"""Are the tutorial's electrostatics safe to adopt, now that the box behaves?

exp47 wave 1 measured +37 % throughput from the tutorial's electrostatics but could not
judge them: every arm died of the carved-box collapse first, and the smaller cutoff made
a FINER patch grid so it crashed *sooner*.  With the collapse fixed (carved -> NVT,
margin on NPT stages) that objection goes away and the question becomes answerable.

Both arms run on the FULL-WATER-BOX 2hb_1xT package (job aa78c4df833c, `water_shell_nm=0`)
from the same ENM ladder checkpoint, and E0 is literally what `build_production_conf`
now emits — so this measures the shipped configuration against the tutorial's.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SRC = Path("/media/jojo/Archive/NADOC_archive/aa78c4df833c/package/2hb_1xT_namd_solvated")
START = "2hb_1xT_02_300K_NPT_ENM_k0p1_p10"
WORK = Path("/media/jojo/Archive/exp47_electrostatics")
STEM = "2hb_1xT"
BOX = (44.147, 66.635, 113.568)
STEPS = 500_000          # 2 ns at 4 fs
THREADS = 16

# NADOC (= Roodhuizen/ACS Nano) -> Aksimentiev tutorial
TUTORIAL = [
    ("switchdist         10.0", "switchdist         8.0"),
    ("cutoff             12.0", "cutoff             10.0"),
    ("pairlistdist       14.0", "pairlistdist       12.0"),
    ("PMEGridSpacing     1.0", "PMEGridSpacing     1.5"),
    ("fullElectFrequency 1", "fullElectFrequency 2"),
]
ARMS = {
    "E0_nadoc": [],
    "E1_tutorial": TUTORIAL,
}


def stage() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "output").mkdir(exist_ok=True)
    for f in (f"{STEM}.psf", f"{STEM}_hmr.psf", f"{STEM}.pdb", "mgh_extrabonds.txt"):
        if not (WORK / f).exists():
            shutil.copy2(SRC / f, WORK / f)
    if not (WORK / "forcefield").exists():
        shutil.copytree(SRC / "forcefield", WORK / "forcefield")
    for ext in ("coor", "vel", "xsc"):
        dst = WORK / "output" / f"{START}.{ext}"
        if not dst.exists():
            shutil.copy2(SRC / "output" / f"{START}.{ext}", dst)
    return WORK


def conf_for(arm: str) -> str:
    from backend.core.md_protocols import SegmentSpec, build_production_conf

    spec = SegmentSpec(
        name=arm, stage=f"{arm} 2 ns", percent=100.0, steps=STEPS, temp=300.0,
        damping=5.0, scale=None, npt=True, previous=START, reinit=False,
    )
    c = build_production_conf(spec, STEM, BOX, True, fast=True, timestep_fs=4.0,
                              structure_psf=f"{STEM}_hmr.psf", n_atoms=32572,
                              force_resident=True, npt=True)
    for old, new in ARMS[arm]:
        if old not in c:
            raise RuntimeError(f"{arm}: expected {old!r} in the generated conf")
        c = c.replace(old, new)
    # resolve outputs into the shared package, one prefix per arm
    return c.replace(f"output/{arm}", f"output/{arm}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args(argv)

    namd = os.environ.get("NADOC_NAMD_BIN") or shutil.which("namd3")
    pkg = stage()
    manifest = WORK / "arms.json"
    done = json.loads(manifest.read_text()) if manifest.exists() else {}

    for arm in (args.only or list(ARMS)):
        if done.get(arm, {}).get("status") == "ok":
            print(f"[skip] {arm}")
            continue
        (pkg / f"{arm}.conf").write_text(conf_for(arm))
        print(f"[run ] {arm}", flush=True)
        t0 = time.time()
        with open(pkg / f"{arm}.log", "w") as fh:
            rc = subprocess.call([namd, "+p", str(THREADS), "+setcpuaffinity",
                                  "+devices", "0", f"{arm}.conf"],
                                 cwd=pkg, stdout=fh, stderr=subprocess.STDOUT)
        txt = (pkg / f"{arm}.log").read_text(errors="replace")
        ok = rc == 0 and "End of program" in txt
        done[arm] = {
            "status": "ok" if ok else "FAILED", "rc": rc,
            "wall_s": round(time.time() - t0, 1),
            "overrides": [f"{a} -> {b}" for a, b in ARMS[arm]],
            "ns_per_day": next((float(l.split("averaging")[1].split("ns/day")[0])
                                for l in reversed(txt.splitlines())
                                if "PERFORMANCE:" in l and "averaging" in l), None),
        }
        manifest.write_text(json.dumps(done, indent=1))
        print(f"[{'ok  ' if ok else 'FAIL'}] {arm} {done[arm]['ns_per_day']} ns/day",
              flush=True)
    print("manifest:", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
