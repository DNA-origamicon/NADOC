#!/usr/bin/env python3
"""Create deliberately labeled fast-screening NAMD configs for F027.

These are not production-MD configs.  They are intended to measure how quickly
we can get relative stability signals from the same solvated B_tube system.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PKG_DIR = (
    ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
    / "F027_literature_aligned_enm_production/B_tube_namd_solvated"
)


@dataclass(frozen=True)
class Variant:
    name: str
    full_elect_frequency: int
    dense_enm: bool
    positional_scale: float | None
    note: str


VARIANTS = [
    Variant(
        "F027_fast_01_2fs_fef2_enm_pos0p1_10ps",
        2,
        True,
        0.1,
        "MTS comparator: dense ENM plus weak DNA positional restraints.",
    ),
    Variant(
        "F027_fast_02_2fs_fef2_enm_only_10ps",
        2,
        True,
        None,
        "Dense ENM retained, positional restraints removed.",
    ),
    Variant(
        "F027_fast_03_2fs_fef2_unrestrained_10ps",
        2,
        False,
        None,
        "Fully unrestrained solvated origami except MGH Mg-O bonds.",
    ),
    Variant(
        "F027_fast_04_2fs_fef1_unrestrained_10ps",
        1,
        False,
        None,
        "Unrestrained control with conservative electrostatics.",
    ),
]


def render_conf(v: Variant) -> str:
    constraint_block = ""
    if v.positional_scale is not None:
        constraint_block = f"""constraints        on
consref            restraints_dna_heavy.pdb
conskfile          restraints_dna_heavy.pdb
conskcol           B
constraintScaling  {v.positional_scale}
"""

    enm_block = "extraBondsFile     dense_enm_k0p1_5A.extrabonds\n" if v.dense_enm else ""

    return f"""# Fast-screening variant, not a production-MD protocol.
# {v.note}
structure          B_tube.psf
coordinates        B_tube.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
extraBonds         on
extraBondsFile     mgh_extrabonds.txt

cellBasisVector1   160.313  0.000    0.000
cellBasisVector2   0.000    157.711  0.000
cellBasisVector3   0.000    0.000    1053.629
cellOrigin         80.156   78.856   526.814

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

timestep           2.0
nonbondedFreq      1
fullElectFrequency {v.full_elect_frequency}
stepspercycle      20

outputEnergies     500
xstFreq            1000
restartfreq        5000
binaryrestart      yes
outputName         output/{v.name}
dcdFile            output/{v.name}.dcd
dcdFreq            1000
xstFile            output/{v.name}.xst
langevinTemp       310
langevinDamping    1
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  400.0
langevinPistonDecay   200.0
langevinPistonTemp 310
{constraint_block}{enm_block}binCoordinates     output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.coor
binVelocities      output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.vel
extendedSystem     output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.xsc
run                5000
"""


def render_runner() -> str:
    variant_names = " ".join(v.name for v in VARIANTS)
    return f"""#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../../../.." && pwd)"
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMD="${{NAMD_BIN:-/home/jojo/Applications/NAMD_3.0.2/namd3}}"
THREADS="${{NAMD_THREADS:-12}}"
PEMAP="${{NAMD_PEMAP:-0-15}}"
DEVICES="${{NAMD_DEVICES:-0}}"
HEALTH="$ROOT/experiments/exp25_full_origami_relaxation/scripts/f027_health_check.py"

all_variants=({variant_names})
if [[ "$#" -gt 0 ]]; then
  variants=("$@")
else
  variants=("${{all_variants[@]}}")
fi

cd "$PKG_DIR"
mkdir -p output
namd_args=("+p${{THREADS}}" "+setcpuaffinity")
if [[ -n "$PEMAP" ]]; then
  namd_args+=("+pemap" "$PEMAP")
fi

if ! nvidia-smi >/dev/null 2>&1; then
  echo "[F027-fast] GPU is not available through NVML; refusing to start NAMD." >&2
  nvidia-smi >&2 || true
  exit 18
fi

for required in \\
  output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.coor \\
  output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.vel \\
  output/F027_06a_310K_NPT_pos0p1_enm0p1_2fs_fef1_probe50ps.xsc; do
  if [[ ! -f "$required" ]]; then
    echo "[F027-fast] Missing required input: $required" >&2
    exit 1
  fi
done

for stage in "${{variants[@]}}"; do
  if [[ ! -f "${{stage}}.conf" ]]; then
    echo "[F027-fast] Missing config: ${{stage}}.conf" >&2
    exit 2
  fi
  if [[ -f "output/${{stage}}.coor" ]]; then
    echo "[F027-fast] Skip completed $stage"
  else
    echo "[F027-fast] Running $stage with ${{namd_args[*]}} +devices $DEVICES"
    "$NAMD" "${{namd_args[@]}}" +devices "$DEVICES" "${{stage}}.conf" > "${{stage}}.log" 2>&1
  fi

  echo "[F027-fast] Health check $stage"
  python "$HEALTH" \\
    --package-dir "$PKG_DIR" \\
    --segment "$stage" \\
    --stage "$stage" \\
    --name-stem B_tube \\
    --min-c1 0.80 \\
    --min-wc 0.85 \\
    --paired-max-ang 14.0 \\
    --wc-policy warn \\
    --jsonl "output/F027_fast_screen_health.jsonl" \\
    --summary "output/F027_fast_screen_latest_health.json"
done

echo "[F027-fast] Fast-screen batch complete"
"""


def main() -> None:
    PKG_DIR.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        (PKG_DIR / f"{variant.name}.conf").write_text(render_conf(variant))
    runner = PKG_DIR / "run_f027_fast_screen.sh"
    runner.write_text(render_runner())
    runner.chmod(0o755)
    print(f"Wrote {len(VARIANTS)} fast-screen configs and {runner}")


if __name__ == "__main__":
    main()
