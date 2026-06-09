#!/usr/bin/env python3
"""Create dense literature-style ENM tests for the explicit-solvent B-tube."""

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

cutoff             10.0
switching          on
switchdist         8.0
pairlistdist       12.0
exclude            scaled1-4
oneFourScaling     1.0

rigidBonds         all
rigidTolerance     1.0e-8

langevin           on
langevinHydrogen   off
langevinTemp       300
langevinDamping    1

timestep           1.0
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10

outputEnergies     100
dcdFreq            1000
xstFreq            1000
restartfreq        1000
binaryrestart      yes

langevinPiston     off
constraints        off
extraBonds         on
extraBondsFile     dense_enm_k0p1_5A.extrabonds
"""


def write_conf(package_dir: Path, *, name: str, previous: str, steps: int) -> None:
    text = COMMON + f"""\
outputName         output/{name}
dcdFile            output/{name}.dcd
xstFile            output/{name}.xst
binCoordinates     output/{previous}.coor
binVelocities      output/{previous}.vel
extendedSystem     output/{previous}.xsc
run                {steps}
"""
    (package_dir / f"{name}.conf").write_text(text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package_dir", type=Path)
    ap.add_argument("--start", default="F014_20_k5_310K_NPT_20ps")
    ap.add_argument("--steps", type=int, default=2000)
    args = ap.parse_args()

    package_dir = args.package_dir.resolve()
    write_conf(
        package_dir,
        name="F016_01_dense_enm_k0p1_300K_NVT_2ps",
        previous=args.start,
        steps=args.steps,
    )
    print(f"Wrote F016 dense ENM config in {package_dir}")


if __name__ == "__main__":
    main()
