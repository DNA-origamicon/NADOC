#!/usr/bin/env python3
"""Prepare a restrained B-tube GBIS screen from the 1hb-stable recipe.

This is deliberately a *restrained relative-stability probe*, not unrestrained
production MD.  The 1hb control showed that dry DNA-only GBIS melts on release,
so the B-tube package keeps DNA positional restraints and uses conservative
timesteps/damping.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "experiments/exp25_full_origami_relaxation/results/runs/F027_gbis_implicit_screen/B_tube_gbis_dna_only"
OUT = ROOT / "experiments/exp25_full_origami_relaxation/results/runs/F028_implicit_screen/B_tube_gbis_restrained_1M"
NAMD = "/home/jojo/Applications/NAMD_3.0.2/namd3"


COMMON = """\
# B-tube GBIS restrained stress-screen, not unrestrained production MD.
structure          B_tube_gbis.psf
coordinates        B_tube_gbis.pdb
outputName         output/{name}

set temperature    {temperature}
{temperature_line}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm

GBIS               on
solventDielectric  78.5
ionConcentration   1.0
alphaCutoff        14
SASA               off

switching          on
switchdist         15
cutoff             16
pairlistdist       22
margin             20
exclude            scaled1-4
oneFourScaling     1.0

timestep           {timestep}
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10

langevin           {langevin}
langevinHydrogen   off
langevinTemp       $temperature
langevinDamping    {damping}

rigidBonds         none
wrapAll            off

constraints        on
consref            constraints_all_dna.pdb
conskfile          constraints_all_dna.pdb
conskcol           B
constraintScaling  {constraint_scale}

outputEnergies     {energy_freq}
restartFreq        {restart_freq}
binaryRestart      yes
dcdFile            output/{name}.dcd
dcdFreq            {dcd_freq}

{restart_block}
{commands}
"""


RUNS = [
    {
        "name": "B001_min_pos10_2k",
        "temperature": 1,
        "temperature_line": "temperature        $temperature",
        "timestep": 0.25,
        "langevin": "off",
        "damping": 20,
        "constraint_scale": 10.0,
        "energy_freq": 100,
        "restart_freq": 1000,
        "dcd_freq": 1000,
        "restart_from": None,
        "use_velocities": False,
        "commands": "minimize           2000",
    },
    {
        "name": "B002_warm50_0p25fs_pos5_1ps",
        "temperature": 50,
        "temperature_line": "temperature        $temperature",
        "timestep": 0.25,
        "langevin": "on",
        "damping": 20,
        "constraint_scale": 5.0,
        "energy_freq": 200,
        "restart_freq": 4000,
        "dcd_freq": 1000,
        "restart_from": "B001_min_pos10_2k",
        "use_velocities": False,
        "commands": "reinitvels         $temperature\nrun                4000        ;# 1 ps",
    },
    {
        "name": "B003_300K_0p25fs_pos3_2ps",
        "temperature": 300,
        "temperature_line": "temperature        $temperature",
        "timestep": 0.25,
        "langevin": "on",
        "damping": 20,
        "constraint_scale": 3.0,
        "energy_freq": 500,
        "restart_freq": 8000,
        "dcd_freq": 1000,
        "restart_from": "B002_warm50_0p25fs_pos5_1ps",
        "use_velocities": False,
        "commands": "reinitvels         $temperature\nrun                8000        ;# 2 ps",
    },
    {
        "name": "B004_300K_0p5fs_pos2_5ps",
        "temperature": 300,
        "temperature_line": "",
        "timestep": 0.5,
        "langevin": "on",
        "damping": 10,
        "constraint_scale": 2.0,
        "energy_freq": 500,
        "restart_freq": 10000,
        "dcd_freq": 1000,
        "restart_from": "B003_300K_0p25fs_pos3_2ps",
        "use_velocities": True,
        "commands": "run                10000       ;# 5 ps",
    },
]


def relink(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(src)


def restart_block(name: str | None, use_velocities: bool) -> str:
    if not name:
        return ""
    lines = [f"binCoordinates     output/{name}.restart.coor"]
    if use_velocities:
        lines.append(f"binVelocities      output/{name}.restart.vel")
    return "\n".join(lines)


def write_package(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "output").mkdir(exist_ok=True)
    (out / "forcefield").mkdir(exist_ok=True)
    relink(SRC / "B_tube_gbis.psf", out / "B_tube_gbis.psf")
    relink(SRC / "B_tube_gbis.pdb", out / "B_tube_gbis.pdb")
    relink(SRC / "constraints_all_dna.pdb", out / "constraints_all_dna.pdb")
    relink(SRC / "forcefield/par_all36_na.prm", out / "forcefield/par_all36_na.prm")

    for spec in RUNS:
        text = COMMON.format(
            restart_block=restart_block(spec["restart_from"], spec["use_velocities"]),
            **{k: v for k, v in spec.items() if k not in {"restart_from", "use_velocities"}},
        )
        (out / f"{spec['name']}.conf").write_text(text)

    (out / "run_sequence.sh").write_text(f"""#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../../../.." && pwd)"
NAMD="${{NAMD_BIN:-{NAMD}}}"
THREADS="${{NAMD_THREADS:-12}}"
PEMAP="${{NAMD_PEMAP:-0-15}}"
HEALTH="$ROOT/experiments/exp25_full_origami_relaxation/scripts/f027_health_check.py"
cd "$(dirname "$0")"
mkdir -p output
namd_args=("+p${{THREADS}}" "+setcpuaffinity")
if [[ -n "$PEMAP" ]]; then
  namd_args+=("+pemap" "$PEMAP")
fi
for conf in B*.conf; do
  stage="${{conf%.conf}}"
  echo "==> $stage"
  "$NAMD" "${{namd_args[@]}}" "$conf" > "$stage.log" 2>&1 || true
  python "$HEALTH" --package-dir "$PWD" --segment "$stage" --stage "$stage" \\
    --name-stem B_tube_gbis --min-c1 0.70 --min-wc 0.85 \\
    --paired-max-ang 16.0 --wc-policy warn --max-temp-k 450 \\
    --jsonl output/B_tube_gbis_restrained_health.jsonl \\
    --summary output/B_tube_gbis_restrained_latest_health.json || true
done
""")
    (out / "run_sequence.sh").chmod(0o755)

    (out / "README.md").write_text("""\
# B-tube GBIS Restrained 1.0 M Screen

This package scales the only partly successful 1hb GBIS mode to B-tube:
restrained DNA, 1.0 M GBIS, high damping, and 0.25-0.5 fs timesteps.

It is not unrestrained production MD.  Use it only as a fast restrained
relative-stability/stress probe.
""")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    write_package(args.out.resolve())
    print(args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
