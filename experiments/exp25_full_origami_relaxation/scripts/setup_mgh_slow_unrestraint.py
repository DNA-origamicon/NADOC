#!/usr/bin/env python3
"""Create long, slow MGH minimization and restraint-release configs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_cell(package_dir: Path) -> tuple[float, float, float]:
    for line in (package_dir / "B_tube.pdb").read_text(errors="replace").splitlines():
        if line.startswith("CRYST1"):
            return (float(line[6:15]), float(line[15:24]), float(line[24:33]))
    raise RuntimeError("No CRYST1 record found in B_tube.pdb")


def common(package_dir: Path) -> str:
    bx, by, bz = read_cell(package_dir)
    extra = ""
    if (package_dir / "mgh_extrabonds.txt").exists():
        extra = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n"
    return f"""\
structure          B_tube.psf
coordinates        B_tube.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix_dna_only.str
{extra}
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {bx / 2:.3f}   {by / 2:.3f}   {bz / 2:.3f}

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


def restraints_block(scale: float | None) -> str:
    if scale is None:
        return "constraints        off\n"
    return f"""\
constraints        on
consref            restraints_dna_heavy.pdb
conskfile          restraints_dna_heavy.pdb
conskcol           B
constraintScaling  {scale:g}
"""


def write_restraints(package_dir: Path) -> None:
    src = package_dir / "B_tube.pdb"
    dst = package_dir / "restraints_dna_heavy.pdb"
    with src.open() as inp, dst.open("w") as out:
        for line in inp:
            if line.startswith("ATOM"):
                atom_name = line[12:16].strip()
                value = 0.0 if atom_name.startswith("H") else 1.0
                out.write(f"{line[:60]}{value:6.2f}{line[66:].rstrip()}\n")
            elif line.startswith("HETATM"):
                out.write(f"{line[:60]}{0.0:6.2f}{line[66:].rstrip()}\n")
            else:
                out.write(line)


def write_conf(
    package_dir: Path,
    base_common: str,
    *,
    name: str,
    previous: str | None,
    temp: float,
    damping: float,
    scale: float | None,
    steps: int,
    npt: bool,
    dcd_freq: int,
    minimize_steps: int = 0,
    reinit: bool = False,
) -> None:
    lines = [base_common]
    lines.append(f"outputName         output/{name}\n")
    lines.append(f"dcdFile            output/{name}.dcd\n")
    lines.append(f"dcdFreq            {dcd_freq}\n")
    lines.append(f"xstFile            output/{name}.xst\n")
    if previous is None or reinit:
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
    lines.append(restraints_block(scale))
    if previous is not None:
        lines.append(f"binCoordinates     output/{previous}.coor\n")
        if not reinit:
            lines.append(f"binVelocities      output/{previous}.vel\n")
        lines.append(f"extendedSystem     output/{previous}.xsc\n")
    if reinit:
        lines.append(f"reinitvels         {temp:g}\n")
    if minimize_steps:
        lines.append(f"minimize           {minimize_steps}\n")
    lines.append(f"run                {steps}\n")
    (package_dir / f"{name}.conf").write_text("".join(lines))


def split_steps(total: int) -> list[tuple[str, int, float]]:
    first = max(1, int(round(total * 0.10)))
    second = max(1, int(round(total * 0.40)))
    third = total - first - second
    return [("p10", first, 10.0), ("p50", second, 50.0), ("p100", third, 100.0)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package_dir", type=Path)
    ap.add_argument("--minimize-steps", type=int, default=50000)
    ap.add_argument("--minimize-scale", type=float, default=5.0)
    ap.add_argument("--start-scale", type=float, default=5.0)
    ap.add_argument("--prefix", default="F018")
    args = ap.parse_args()

    package_dir = args.package_dir.resolve()
    (package_dir / "output").mkdir(exist_ok=True)
    write_restraints(package_dir)
    base_common = common(package_dir)

    stages = []
    prefix = args.prefix
    min_tag = f"k{args.minimize_scale:g}".replace(".", "p")
    min_name = f"{prefix}_00_min_{min_tag}"
    write_conf(
        package_dir,
        base_common,
        name=min_name,
        previous=None,
        temp=25,
        damping=10,
        scale=args.minimize_scale,
        steps=0,
        npt=False,
        dcd_freq=args.minimize_steps,
        minimize_steps=args.minimize_steps,
    )
    previous = min_name

    start_tag = f"k{args.start_scale:g}".replace(".", "p")
    stage_specs = [
        (f"{prefix}_01_050K_NVT_{start_tag}_10ps", 50, 10, args.start_scale, False, 10_000),
        (f"{prefix}_02_100K_NVT_{start_tag}_10ps", 100, 10, args.start_scale, False, 10_000),
        (f"{prefix}_03_200K_NVT_{start_tag}_10ps", 200, 5, args.start_scale, False, 10_000),
        (f"{prefix}_04_300K_NVT_{start_tag}_20ps", 300, 2, args.start_scale, False, 20_000),
        (f"{prefix}_05_310K_NPT_{start_tag}_50ps", 310, 1, args.start_scale, True, 50_000),
        (f"{prefix}_06_310K_NPT_k10_50ps", 310, 1, 10.0, True, 50_000),
        (f"{prefix}_07_310K_NPT_k5_50ps", 310, 1, 5.0, True, 50_000),
        (f"{prefix}_08_310K_NPT_k4_50ps", 310, 1, 4.0, True, 50_000),
        (f"{prefix}_09_310K_NPT_k3_50ps", 310, 1, 3.0, True, 50_000),
        (f"{prefix}_10_310K_NPT_k2_50ps", 310, 1, 2.0, True, 50_000),
        (f"{prefix}_11_310K_NPT_k1_50ps", 310, 1, 1.0, True, 50_000),
        (f"{prefix}_12_310K_NPT_k0p5_50ps", 310, 1, 0.5, True, 50_000),
        (f"{prefix}_13_310K_NPT_k0p2_50ps", 310, 1, 0.2, True, 50_000),
        (f"{prefix}_14_310K_NPT_k0p1_50ps", 310, 1, 0.1, True, 50_000),
        (f"{prefix}_15_310K_NPT_k0p05_50ps", 310, 1, 0.05, True, 50_000),
        (f"{prefix}_16_310K_NPT_unrestrained_20ps", 310, 1, None, True, 20_000),
    ]

    for stage_prefix, temp, damping, scale, npt, total in stage_specs:
        for suffix, steps, percent in split_steps(total):
            name = f"{stage_prefix}_{suffix}"
            write_conf(
                package_dir,
                base_common,
                name=name,
                previous=previous,
                temp=temp,
                damping=damping,
                scale=scale,
                steps=steps,
                npt=npt,
                dcd_freq=steps,
                reinit=False,
            )
            stages.append({
                "name": name,
                "stage": stage_prefix,
                "percent": percent,
                "steps": steps,
                "temp": temp,
                "damping": damping,
                "scale": scale,
                "npt": npt,
            })
            previous = name

    manifest = {
        "minimization": {
            "name": min_name,
            "steps": args.minimize_steps,
            "scale": args.minimize_scale,
        },
        "stages": stages,
        "health_checks": "After every segment: 10%, 50%, and 100% of each stage.",
    }
    (package_dir / f"{prefix}_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote F018 minimization plus {len(stages)} segmented run configs in {package_dir}")


if __name__ == "__main__":
    main()
