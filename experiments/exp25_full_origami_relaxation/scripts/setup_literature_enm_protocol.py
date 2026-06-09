#!/usr/bin/env python3
"""Create literature-aligned explicit-solvent ENM tests for full B-tube.

The Aksimentiev DNA-origami protocols use explicit Mg-containing solvent,
NAMD/CHARMM36, 300 K Langevin dynamics with damping near 1 ps^-1, and a staged
elastic network that preserves base pairing and stacking while allowing global
relaxation.  These configs start from the stable F014 explicit-solvent state and
replace strong Cartesian DNA restraints with extraBonds ENM restraints.
"""

from __future__ import annotations

import argparse
import re
import shutil
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
"""


BOND_RE = re.compile(r"^(bond\s+\d+\s+\d+\s+)([-+0-9.eE]+)(\s+[-+0-9.eE]+.*)$")


def scale_extrabonds(src: Path, dst: Path, factor: float) -> None:
    out: list[str] = []
    for line in src.read_text().splitlines():
        match = BOND_RE.match(line)
        if not match:
            out.append(line)
            continue
        k = float(match.group(2)) * factor
        out.append(f"{match.group(1)}{k:.4f}{match.group(3)}")
    dst.write_text("\n".join(out) + "\n")


def write_conf(
    package_dir: Path,
    *,
    name: str,
    previous: str,
    run_steps: int,
    extrabonds: str | None,
    temp: int = 300,
) -> None:
    text = COMMON.replace("langevinTemp       300", f"langevinTemp       {temp}")
    lines = [text]
    lines.append(f"outputName         output/{name}\n")
    lines.append(f"dcdFile            output/{name}.dcd\n")
    lines.append(f"xstFile            output/{name}.xst\n")
    if extrabonds:
        lines.append("extraBonds         on\n")
        lines.append(f"extraBondsFile     {extrabonds}\n")
    else:
        lines.append("extraBonds         off\n")
    lines.append("constraints        off\n")
    lines.append(f"binCoordinates     output/{previous}.coor\n")
    lines.append(f"binVelocities      output/{previous}.vel\n")
    lines.append(f"extendedSystem     output/{previous}.xsc\n")
    lines.append(f"run                {run_steps}\n")
    (package_dir / f"{name}.conf").write_text("".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package_dir", type=Path)
    ap.add_argument(
        "--source-enm",
        type=Path,
        default=Path("/home/jojo/Work/NADOC/experiments/exp25_full_origami_relaxation/results/runs/F010_established_practice_gbis_enm/local_order_enm.extrabonds"),
    )
    ap.add_argument("--start", default="F014_10_k5_310K_NPT_4ps")
    args = ap.parse_args()
    package_dir = args.package_dir.resolve()

    base = package_dir / "local_order_enm_lit_k0p5.extrabonds"
    shutil.copyfile(args.source_enm, base)
    scale_extrabonds(base, package_dir / "local_order_enm_lit_k0p1.extrabonds", 0.2)
    scale_extrabonds(base, package_dir / "local_order_enm_lit_k0p01.extrabonds", 0.02)

    stages = [
        ("F015_01_enm_k0p5_300K_NVT_2ps", args.start, 2000, "local_order_enm_lit_k0p5.extrabonds"),
        ("F015_02_enm_k0p1_300K_NVT_2ps", "F015_01_enm_k0p5_300K_NVT_2ps", 2000, "local_order_enm_lit_k0p1.extrabonds"),
        ("F015_03_enm_k0p01_300K_NVT_2ps", "F015_02_enm_k0p1_300K_NVT_2ps", 2000, "local_order_enm_lit_k0p01.extrabonds"),
        ("F015_04_unrestrained_300K_NVT_2ps", "F015_03_enm_k0p01_300K_NVT_2ps", 2000, None),
    ]
    for name, previous, run_steps, extrabonds in stages:
        write_conf(
            package_dir,
            name=name,
            previous=previous,
            run_steps=run_steps,
            extrabonds=extrabonds,
        )
    print(f"Wrote {len(stages)} F015 literature-aligned ENM configs in {package_dir}")


if __name__ == "__main__":
    main()
