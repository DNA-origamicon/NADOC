#!/usr/bin/env python3
"""Assemble a MINIMAL, self-contained NAMD benchmark package for 24hb_0xT and tar it.

A benchmark needs only what determines ms/step: the HMR PSF, the forcefield, the extra
bonds, a relaxed seed (coor/vel/xsc), and a short production-cadence conf. It does NOT need
the 102 MB PDB, the 3x50 MB ENM restraint files, or the ladder logs — dropping them takes
the upload from 4.2 GB to ~250 MB, which matters because on the container-disk bench path we
upload it to each (billing) GPU pod.

The bench conf uses the PRODUCTION integrator cadence (fullElectFrequency 1, stepspercycle
10) so the number is comparable to the runbook's RTX PRO 4500 baseline (26.4 ms/step) — the
relaxation cadence (fullElect 2) would flatter every card by ~1.35x (runbook L7 / §1).

Output: <ARCHIVE>/nadoc_bench_pkg/24hb_0xT/  and  24hb_0xT_bench.tar  (uncompressed — the
180 MB PSF is the bulk and it is text that tars fast; NAMD itself is the compressible part
and travels separately).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path("/media/jojo/Archive/nadoc_jobs/383f7dcc4a5d/package/24hb_0xT_namd_solvated")
OUT = Path("/media/jojo/Archive/nadoc_bench_pkg/24hb_0xT")
SEED = "24hb_0xT_04_300K_NPT_MGHH_only_p100"      # final relaxed ladder checkpoint
STEPS = 2000


def build_conf() -> str:
    conf = (SRC / "namd_fast.conf").read_text()
    # production PME cadence (the shipped integrator), short run, no trajectory
    conf = re.sub(r"(?m)^fullElectFrequency\s+\d+", "fullElectFrequency 1", conf)
    conf = re.sub(r"(?m)^stepspercycle\s+\d+", "stepspercycle      10", conf)
    conf = re.sub(r"(?m)^run\s+\d+", f"run                {STEPS}", conf)
    conf = re.sub(r"(?m)^outputEnergies\s+\d+", f"outputEnergies     {STEPS}", conf)
    conf = re.sub(r"(?m)^dcdFreq\s+\d+", "dcdFreq            0", conf)
    conf = re.sub(r"(?m)^xstFreq\s+\d+", "xstFreq            0", conf)
    conf = re.sub(r"(?m)^restartfreq\s+\d+", f"restartfreq        {STEPS * 10}", conf)
    conf = re.sub(r"(?m)^outputName\s+\S+", "outputName         output/bench", conf)
    # seed from the relaxed checkpoint; a bench of un-equilibrated coords is a different system
    conf = re.sub(r"(?m)^temperature\s+\d+", "", conf)   # can't set temp AND binvelocities
    conf = re.sub(r"(?m)^coordinates\s+\S+", "coordinates        24hb_0xT.pdb", conf)
    # ⚠️ NAMD FATALs on a periodic cell defined twice. namd_fast.conf hardcodes
    # cellBasisVector*/cellOrigin; we seed the cell from the checkpoint's .xsc via
    # extendedSystem, so the hardcoded block MUST be stripped (this exact duplication killed
    # the first H100 launch at 2581 bytes — caught by the launch confirmation, not a number).
    conf = re.sub(r"(?m)^cellBasisVector[123]\s+.*$\n?", "", conf)
    conf = re.sub(r"(?m)^cellOrigin\s+.*$\n?", "", conf)
    # ⚠️ The seed block MUST come BEFORE `run` — NAMD executes `run` at parse time, so any
    # bin*/extendedSystem keyword AFTER it is never read and setup dies with "Must have either
    # an initial temperature or a velocity file" (caught on the L40S canary, not an H100).
    # camelCase to match the proven ladder-restart syntax exactly.
    seed_block = (
        f"# ── seeded from relaxed checkpoint (bench) ──\n"
        f"binCoordinates     output/{SEED}.coor\n"
        f"binVelocities      output/{SEED}.vel\n"
        f"extendedSystem     output/{SEED}.xsc\n"
    )
    conf = re.sub(r"(?m)^(run\s+\d+.*)$", seed_block + r"\1", conf, count=1)
    return conf


def main() -> int:
    if not SRC.exists():
        print(f"source package missing: {SRC}", file=sys.stderr)
        return 2
    for e in ("coor", "vel", "xsc"):
        if not (SRC / "output" / f"{SEED}.{e}").exists():
            print(f"seed checkpoint missing: {SEED}.{e}", file=sys.stderr)
            return 2

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "output").mkdir(exist_ok=True)
    (OUT / "forcefield").mkdir(exist_ok=True)

    # a real coordinates file is still required by NAMD's parser even when seeding from a
    # checkpoint; the 102 MB pdb would double the upload, so ship a 1-frame placeholder? No —
    # NAMD reads natom from it. Simplest correct choice: ship the pdb (102 MB) but it stays
    # off the wire because we seed coords from the .coor. Keep it; correctness over 100 MB.
    shutil.copy2(SRC / "24hb_0xT.pdb", OUT / "24hb_0xT.pdb")
    shutil.copy2(SRC / "24hb_0xT_hmr.psf", OUT / "24hb_0xT_hmr.psf")
    shutil.copy2(SRC / "mgh_extrabonds.txt", OUT / "mgh_extrabonds.txt")
    for ff in (SRC / "forcefield").glob("*"):
        shutil.copy2(ff, OUT / "forcefield" / ff.name)
    for e in ("coor", "vel", "xsc"):
        shutil.copy2(SRC / "output" / f"{SEED}.{e}", OUT / "output" / f"{SEED}.{e}")
    (OUT / "bench.conf").write_text(build_conf())

    # gzip: the 180 MB PSF + 102 MB PDB are text and compress ~4x; on a ~1 MB/s uplink to an
    # expensive H100 that halves the per-card upload bill. (The coor/vel binaries don't shrink.)
    tar = OUT.parent / "24hb_0xT_bench.tar.gz"
    subprocess.run(["tar", "-czf", str(tar), "-C", str(OUT.parent), OUT.name], check=True)
    size_mb = tar.stat().st_size / 1e6
    print(f"package: {OUT}")
    print(f"tar:     {tar}  ({size_mb:.0f} MB)")
    print(f"seed:    {SEED}")
    print(f"conf:    production cadence (fullElectFrequency 1, stepspercycle 10), "
          f"{STEPS} steps, 4 fs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
