#!/usr/bin/env python3
"""Create conservative explicit-solvent Mg warmup inputs for full B-tube."""

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

timestep           1.0
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10

outputEnergies     100
xstFreq            1000
restartfreq        1000
binaryrestart      yes
"""


def _rewrite_bfactor(line: str, value: float) -> str:
    if len(line) < 66:
        line = line.rstrip("\n").ljust(66)
    return f"{line[:60]}{value:6.2f}{line[66:].rstrip()}\n"


def write_restraints(package_dir: Path) -> None:
    src = package_dir / "B_tube.pdb"
    dst = package_dir / "restraints_dna_heavy.pdb"
    with src.open() as inp, dst.open("w") as out:
        for line in inp:
            if line.startswith("ATOM"):
                atom_name = line[12:16].strip()
                value = 0.0 if atom_name.startswith("H") else 1.0
                out.write(_rewrite_bfactor(line, value))
            elif line.startswith("HETATM"):
                out.write(_rewrite_bfactor(line, 0.0))
            else:
                out.write(line)


def stage_config(
    *,
    name: str,
    output_name: str,
    temp: float,
    damping: float,
    scale: float,
    run_steps: int,
    minimize_steps: int = 0,
    previous: str | None = None,
    reinit: bool = False,
    npt: bool = False,
    restraints: bool = True,
    dcd_freq: int = 50000,
) -> str:
    lines = [COMMON]
    lines.append(f"outputName         output/{output_name}\n")
    lines.append(f"dcdFile            output/{output_name}.dcd\n")
    lines.append(f"dcdFreq            {dcd_freq}\n")
    lines.append(f"xstFile            output/{output_name}.xst\n")
    if not previous or reinit:
        lines.append(f"temperature        {temp:g}\n")
    lines.append(f"langevinTemp       {temp:g}\n")
    lines.append(f"langevinDamping    {damping:g}\n")
    if npt:
        lines.append("useGroupPressure   yes\n")
        lines.append("useFlexibleCell    no\n")
        lines.append("useConstantArea    no\n")
        lines.append("langevinPiston     on\n")
        lines.append("langevinPistonTarget  1.01325\n")
        lines.append("langevinPistonPeriod  400.0\n")
        lines.append("langevinPistonDecay   200.0\n")
        lines.append(f"langevinPistonTemp {temp:g}\n")
    else:
        lines.append("langevinPiston     off\n")
    if restraints:
        lines.append("constraints        on\n")
        lines.append("consref            restraints_dna_heavy.pdb\n")
        lines.append("conskfile          restraints_dna_heavy.pdb\n")
        lines.append("conskcol           B\n")
        lines.append(f"constraintScaling  {scale:g}\n")
    else:
        lines.append("constraints        off\n")
    if previous:
        lines.append(f"binCoordinates     output/{previous}.coor\n")
        if not reinit:
            lines.append(f"binVelocities      output/{previous}.vel\n")
        lines.append(f"extendedSystem     output/{previous}.xsc\n")
    if reinit:
        lines.append(f"reinitvels         {temp:g}\n")
    if minimize_steps:
        lines.append(f"minimize           {minimize_steps}\n")
    lines.append(f"run                {run_steps}\n")
    return "".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package_dir", type=Path)
    args = ap.parse_args()
    package_dir = args.package_dir.resolve()
    (package_dir / "output").mkdir(exist_ok=True)
    write_restraints(package_dir)

    stages = [
        ("F013_00_min", dict(
            output_name="F013_00_min",
            temp=25,
            damping=10,
            scale=5.0,
            minimize_steps=500,
            run_steps=0,
        )),
        ("F013_01_25K_1ps", dict(
            output_name="F013_01_25K_1ps",
            temp=25,
            damping=10,
            scale=5.0,
            run_steps=1000,
            previous="F013_00_min",
            reinit=True,
        )),
        ("F013_02_50K_1ps", dict(
            output_name="F013_02_50K_1ps",
            temp=50,
            damping=10,
            scale=5.0,
            run_steps=1000,
            previous="F013_01_25K_1ps",
        )),
        ("F013_03_100K_1ps", dict(
            output_name="F013_03_100K_1ps",
            temp=100,
            damping=10,
            scale=3.0,
            run_steps=1000,
            previous="F013_02_50K_1ps",
        )),
        ("F013_04_200K_1ps", dict(
            output_name="F013_04_200K_1ps",
            temp=200,
            damping=5,
            scale=2.0,
            run_steps=1000,
            previous="F013_03_100K_1ps",
        )),
        ("F013_05_310K_2ps", dict(
            output_name="F013_05_310K_2ps",
            temp=310,
            damping=5,
            scale=1.0,
            run_steps=2000,
            previous="F013_04_200K_1ps",
        )),
        ("F013_06_310K_NPT_2ps", dict(
            output_name="F013_06_310K_NPT_2ps",
            temp=310,
            damping=5,
            scale=1.0,
            run_steps=2000,
            previous="F013_05_310K_2ps",
            npt=True,
        )),
        ("F013_07_310K_NPT_unrestrained_2ps", dict(
            output_name="F013_07_310K_NPT_unrestrained_2ps",
            temp=310,
            damping=5,
            scale=0.0,
            run_steps=2000,
            previous="F013_06_310K_NPT_2ps",
            npt=True,
            restraints=False,
        )),
        ("F013_08_310K_NPT_unrestrained_monitor_1ps", dict(
            output_name="F013_08_310K_NPT_unrestrained_monitor_1ps",
            temp=310,
            damping=5,
            scale=0.0,
            run_steps=1000,
            previous="F013_07_310K_NPT_unrestrained_2ps",
            npt=True,
            restraints=False,
            dcd_freq=200,
        )),
    ]
    for name, kwargs in stages:
        (package_dir / f"{name}.conf").write_text(stage_config(name=name, **kwargs))
    print(f"Wrote restraints and {len(stages)} warmup configs in {package_dir}")


if __name__ == "__main__":
    main()
