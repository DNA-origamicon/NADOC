#!/usr/bin/env python3
"""Create short 310 K NPT restraint-ladder tests for the F013 explicit package."""

from __future__ import annotations

import argparse
from pathlib import Path


COMMON = """\
structure          B_tube.psf
coordinates        B_tube.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix_dna_only.str

cellBasisVector1   156.313  0.000    0.000
cellBasisVector2   0.000    153.711  0.000
cellBasisVector3   0.000    0.000    1049.629
cellOrigin         78.156   76.856   524.815

wrapAll            on
wrapWater          on

PME                yes
PMEGridSpacing     1.0

cutoff             12.0
switching          on
switchdist         10.0
pairlistdist       14.0
exclude            scaled1-4
oneFourScaling     1.0

rigidBonds         all
rigidTolerance     1.0e-8

langevin           on
langevinHydrogen   off
langevinTemp       310
langevinDamping    5

useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  400.0
langevinPistonDecay   200.0
langevinPistonTemp 310

timestep           1.0
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10

outputEnergies     100
xstFreq            1000
restartfreq        1000
binaryrestart      yes
"""


def write_conf(
    package_dir: Path,
    name: str,
    previous: str,
    *,
    scale: float | None,
    run_steps: int,
    dcd_freq: int = 200,
) -> None:
    lines = [COMMON]
    lines.append(f"outputName         output/{name}\n")
    lines.append(f"dcdFile            output/{name}.dcd\n")
    lines.append(f"dcdFreq            {dcd_freq}\n")
    lines.append(f"xstFile            output/{name}.xst\n")
    if scale is None:
        lines.append("constraints        off\n")
    else:
        lines.append("constraints        on\n")
        lines.append("consref            restraints_dna_heavy.pdb\n")
        lines.append("conskfile          restraints_dna_heavy.pdb\n")
        lines.append("conskcol           B\n")
        lines.append(f"constraintScaling  {scale:g}\n")
    lines.append(f"binCoordinates     output/{previous}.coor\n")
    lines.append(f"binVelocities      output/{previous}.vel\n")
    lines.append(f"extendedSystem     output/{previous}.xsc\n")
    lines.append(f"run                {run_steps}\n")
    (package_dir / f"{name}.conf").write_text("".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package_dir", type=Path)
    args = ap.parse_args()
    package_dir = args.package_dir.resolve()

    stages = [
        ("F014_00_k5_310K_NPT_1ps", "F013_06_310K_NPT_2ps", 5.0),
        ("F014_00a_k4_310K_NPT_1ps", "F013_06_310K_NPT_2ps", 4.0),
        ("F014_00b_k3_310K_NPT_1ps", "F013_06_310K_NPT_2ps", 3.0),
        ("F014_00c_k2_310K_NPT_1ps", "F013_06_310K_NPT_2ps", 2.0),
        ("F014_01_k1_310K_NPT_1ps", "F013_06_310K_NPT_2ps", 1.0),
        ("F014_02_k0p5_310K_NPT_1ps", "F014_01_k1_310K_NPT_1ps", 0.5),
        ("F014_03_k0p2_310K_NPT_1ps", "F014_02_k0p5_310K_NPT_1ps", 0.2),
        ("F014_04_k0p1_310K_NPT_1ps", "F014_03_k0p2_310K_NPT_1ps", 0.1),
        ("F014_05_k0p05_310K_NPT_1ps", "F014_04_k0p1_310K_NPT_1ps", 0.05),
        ("F014_06_unrestrained_310K_NPT_1ps", "F014_05_k0p05_310K_NPT_1ps", None),
    ]
    for name, previous, scale in stages:
        write_conf(package_dir, name, previous, scale=scale, run_steps=1000)
    write_conf(
        package_dir,
        "F014_10_k5_310K_NPT_4ps",
        "F014_00_k5_310K_NPT_1ps",
        scale=5.0,
        run_steps=4000,
        dcd_freq=1000,
    )
    write_conf(
        package_dir,
        "F014_20_k5_310K_NPT_20ps",
        "F014_10_k5_310K_NPT_4ps",
        scale=5.0,
        run_steps=20000,
        dcd_freq=5000,
    )
    print(f"Wrote {len(stages) + 2} F014 restraint-ladder configs in {package_dir}")


if __name__ == "__main__":
    main()
