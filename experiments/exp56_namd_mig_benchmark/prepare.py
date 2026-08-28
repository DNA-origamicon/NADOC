#!/usr/bin/env python3
"""Stage the completed 2hb_1-0xT system for an Alpine RTX MIG benchmark."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = (
    REPO
    / "workspace/md_jobs/802f80ec405c/package/2hb_1-0xT_namd_solvated"
)
DEST = REPO / "workspace/mig_benchmarks/exp56_2hb_1-0xT_rtx_2g48"
NAMD = (
    "/projects/jojo6687/nadoc_jobs/nadoc_builds/namd-git/"
    "NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3"
)

FILES = {
    "2hb_1-0xT_hmr.psf": "2hb_1-0xT_hmr.psf",
    "2hb_1-0xT.pdb": "2hb_1-0xT.pdb",
    "mgh_extrabonds.txt": "mgh_extrabonds.txt",
    "restraints_anchors.pdb": "restraints_anchors.pdb",
    "output/2hb_1-0xT_00_reseed.coor": "start.coor",
    "output/2hb_1-0xT_00_reseed.vel": "start.vel",
    "output/2hb_1-0xT_00_reseed.xsc": "start.xsc",
}

CONF = """\
structure          2hb_1-0xT_hmr.psf
coordinates        2hb_1-0xT.pdb

seed               1838513223
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
extraBonds         on
extraBondsFile     mgh_extrabonds.txt

cellBasisVector1   60.147  0.000    0.000
cellBasisVector2   0.000    82.635  0.000
cellBasisVector3   0.000    0.000    129.568
cellOrigin         30.073   41.318   64.784
wrapAll            off
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         8.0
cutoff             10.0
pairlistdist       12.0
PME                yes
PMEGridSpacing     1.5
rigidBonds         all
rigidTolerance     1.0e-8
timestep           4
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
langevin           on
langevinTemp       300
langevinDamping    5
langevinHydrogen   off
margin             3
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget 1.01325
langevinPistonPeriod 200.0
langevinPistonDecay 100.0
langevinPistonTemp 300
outputEnergies     500
restartfreq        1000000
binaryrestart      yes
constraints        on
consref            restraints_anchors.pdb
conskfile          restraints_anchors.pdb
conskcol           B
consexp            2
GPUresident        on
outputName         output/benchmark
binCoordinates     start.coor
binVelocities      start.vel
extendedSystem     start.xsc

# benchmarkTime on the command line terminates this intentionally oversized run.
run                100000000
"""

SBATCH = f"""\
#!/bin/bash
#SBATCH --job-name=nadoc_2hb_mig2g
#SBATCH --partition=artxpro6000
#SBATCH --qos=gpu-normal
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --gres=gpu:rtx_pro_6000_2g.48gb:1
#SBATCH --mem=16GB
#SBATCH --time=00:10:00
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

set -eo pipefail
source /etc/profile
module purge
module load gcc/11.2.0 cuda/12.1.1 fftw/3.3.10
mkdir -p output

echo "NADOC_BENCHMARK design=2hb_1-0xT atoms=62673 gres=rtx_pro_6000_2g.48gb"
nvidia-smi -L || true
nvidia-smi --query-gpu=name,uuid,memory.total,driver_version --format=csv,noheader || true

{NAMD} +p8 +setcpuaffinity +devices 0 \\
  --outputTiming 500 --benchmarkTime 180 benchmark.conf \\
  > benchmark.log 2>&1

grep -E 'Benchmark time:|PERFORMANCE:|WallClock:|End of program' benchmark.log || true
"""


def main() -> None:
    if not SOURCE.is_dir():
        raise SystemExit(f"source package is missing: {SOURCE}")
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "output").mkdir(exist_ok=True)
    for source_name, dest_name in FILES.items():
        source = SOURCE / source_name
        if not source.is_file():
            raise SystemExit(f"required source file is missing: {source}")
        shutil.copy2(source, DEST / dest_name)
    forcefield_dest = DEST / "forcefield"
    if forcefield_dest.exists():
        shutil.rmtree(forcefield_dest)
    shutil.copytree(SOURCE / "forcefield", forcefield_dest)
    (DEST / "benchmark.conf").write_text(CONF)
    (DEST / "benchmark.sbatch").write_text(SBATCH)
    manifest = {
        "experiment": "exp56_namd_mig_benchmark",
        "source_job_id": "802f80ec405c",
        "design": "2hb_1-0xT",
        "atoms": 62673,
        "partition": "artxpro6000",
        "gres_type": "rtx_pro_6000_2g.48gb",
        "benchmark_seconds": 180,
        "cpu_cores": 8,
        "submitted": False,
    }
    (DEST / "benchmark_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(DEST)


if __name__ == "__main__":
    main()
