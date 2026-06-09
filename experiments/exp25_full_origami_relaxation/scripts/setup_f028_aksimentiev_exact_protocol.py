#!/usr/bin/env python3
"""Set up the Aksimentiev tutorial protocol on the full B_tube package.

This intentionally mirrors the public DNA-origami NAMD tutorial staging:

1. `equil_min`: ENM k=0.5 + MGHH restraints, `minimize 4800`
2. `equil_k0.5`: ENM k=0.5 + MGHH restraints, `run 2400000`
3. `equil_k0.1`: ENM k=0.1 + MGHH restraints, `run 2400000`
4. `equil_k0.01`: ENM k=0.01 + MGHH restraints, `run 2400000`
5. `equil_k0`: MGHH restraints only, `run 2400000`

The source system is the existing explicit-solvent B_tube/MGHH package from
F027.  Files are symlinked where possible to avoid duplicating the multi-GB
solvated system.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_SOURCE = (
    ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
    / "F027_literature_aligned_enm_production/B_tube_namd_solvated"
)
DEFAULT_OUT = (
    ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
    / "F028_aksimentiev_exact_btube/B_tube_namd_solvated"
)


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        return
    rel = os.path.relpath(src, dst.parent)
    dst.symlink_to(rel, target_is_directory=src.is_dir())


def _read_box_from_pdb(path: Path) -> tuple[float, float, float]:
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("CRYST1"):
            return (float(line[6:15]), float(line[15:24]), float(line[24:33]))
    raise RuntimeError(f"No CRYST1 record found in {path}")


def _scale_extrabonds(src: Path, dst: Path, k: float) -> None:
    out: list[str] = []
    for line in src.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0] == "bond":
            parts[3] = f"{k:.4f}"
            out.append(" ".join(parts))
        elif line.strip():
            out.append(line)
    dst.write_text("\n".join(out) + "\n")


def _ensure_enm_files(out_dir: Path, stem: str) -> None:
    base = out_dir / f"{stem}_k0.5.enm.extra"
    report = out_dir / f"{stem}_k0.5.enm.report.json"
    if not base.exists():
        from experiments.exp25_full_origami_relaxation.scripts.generate_dense_enm_restraints import (
            main as _unused_main,
        )

        # Use the script entry point via subprocess-shaped argv so the generated
        # report has the same schema as existing dense ENM reports.
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "generate_dense_enm_restraints.py",
                "--psf", str(out_dir / f"{stem}.psf"),
                "--pdb", str(out_dir / f"{stem}.pdb"),
                "--out", str(base),
                "--report", str(report),
                "--k", "0.5",
                "--cutoff-ang", "5.0",
            ]
            _unused_main()
        finally:
            sys.argv = old_argv
    _scale_extrabonds(base, out_dir / f"{stem}_k0.1.enm.extra", 0.1)
    _scale_extrabonds(base, out_dir / f"{stem}_k0.01.enm.extra", 0.01)


def _common(stem: str, bx: float, by: float, bz: float) -> str:
    return f"""\
structure          {stem}.psf
coordinates        {stem}.pdb

outputName         __OUTPUT_NAME__
binaryoutput       yes

set temperature    300

cellBasisVector1   {bx:.3f}  0.0      0.0
cellBasisVector2   0.0      {by:.3f}  0.0
cellBasisVector3   0.0      0.0      {bz:.3f}

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str

exclude            scaled1-4
1-4scaling         1.0
switching          on
switchdist         8
cutoff             10
pairlistdist       12

timestep           2
rigidBonds         all
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      12

PME                yes
PMEGridSpacing     1.5

langevin           on
langevinDamping    5
langevinTemp       $temperature
langevinHydrogen   off

langevinPiston       on
langevinPistonTarget 1.01325
langevinPistonPeriod 1000.
langevinPistonDecay  500.
langevinPistonTemp   $temperature

xstFreq            9600
outputEnergies     9600
dcdFreq            9600
restartfreq        9600
outputPressure     9600

wrapAll            off
wrapWater          off
"""


def _restart_block(previous: str | None) -> str:
    if previous is None:
        return "temperature        $temperature\n"
    return f"""\
set input          output/{previous}
bincoordinates     $input.coor
binvelocities      $input.vel
extendedSystem     $input.xsc

proc get_first_ts {{ xscfile }} {{
  set fd [open $xscfile r]
  gets $fd
  gets $fd
  gets $fd line
  set ts [lindex $line 0]
  close $fd
  return $ts
}}
set firsttime [get_first_ts $input.xsc]
firsttimestep $firsttime
"""


def _write_conf(
    out_dir: Path,
    *,
    stem: str,
    name: str,
    previous: str | None,
    enm_file: str | None,
    minimize: bool,
    common: str,
) -> None:
    text = common.replace("__OUTPUT_NAME__", f"output/{name}")
    text += f"dcdFile            output/{name}.dcd\n"
    text += f"xstFile            output/{name}.xst\n"
    text += _restart_block(previous)
    text += "\nextraBonds         on\n"
    if enm_file is not None:
        text += f"extraBondsFile     {enm_file}\n"
    text += "extraBondsFile     mgh_extrabonds.txt\n\n"
    if minimize:
        text += "minimize           4800\n"
    else:
        text += "run                2400000\n"
    (out_dir / f"{name}.namd").write_text(text)


def _runner(out_dir: Path, stages: list[str]) -> None:
    quoted = " ".join(stages)
    text = f"""#!/usr/bin/env bash
set -euo pipefail

NAMD="${{NAMD_BIN:-/home/jojo/Applications/NAMD_3.0.2/namd3}}"
THREADS="${{NAMD_THREADS:-12}}"
PEMAP="${{NAMD_PEMAP:-0-15}}"

cd "$(dirname "$0")"
mkdir -p output

namd_args=("+p${{THREADS}}" "+setcpuaffinity")
if [[ -n "${{PEMAP}}" ]]; then
  namd_args+=("+pemap" "${{PEMAP}}")
fi

for stage in {quoted}; do
  if [[ -f "output/${{stage}}.coor" ]]; then
    echo "[F028] Skip completed $stage"
    continue
  fi
  echo "[F028] Running $stage"
  "$NAMD" "${{namd_args[@]}}" "${{stage}}.namd" > "${{stage}}.log" 2>&1
done
"""
    path = out_dir / "run_f028_aksimentiev_exact.sh"
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-package", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    src = args.source_package.resolve()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "output").mkdir(exist_ok=True)

    psfs = sorted(src.glob("*.psf"))
    if not psfs:
        raise RuntimeError(f"No PSF found in {src}")
    stem = psfs[0].stem

    for name in (f"{stem}.psf", f"{stem}.pdb", "mgh_extrabonds.txt"):
        _link_or_copy(src / name, out / name)
    _link_or_copy(src / "forcefield", out / "forcefield")

    _ensure_enm_files(out, stem)
    bx, by, bz = _read_box_from_pdb(out / f"{stem}.pdb")
    common = _common(stem, bx, by, bz)

    stages = [
        ("equil_min", None, f"{stem}_k0.5.enm.extra", True),
        ("equil_k0.5", "equil_min", f"{stem}_k0.5.enm.extra", False),
        ("equil_k0.1", "equil_k0.5", f"{stem}_k0.1.enm.extra", False),
        ("equil_k0.01", "equil_k0.1", f"{stem}_k0.01.enm.extra", False),
        ("equil_k0", "equil_k0.01", None, False),
    ]
    for name, previous, enm_file, minimize in stages:
        _write_conf(
            out,
            stem=stem,
            name=name,
            previous=previous,
            enm_file=enm_file,
            minimize=minimize,
            common=common,
        )
    _runner(out, [stage[0] for stage in stages])

    manifest = {
        "protocol": "F028_aksimentiev_exact_btube",
        "source_package": str(src),
        "package_dir": str(out),
        "name_stem": stem,
        "stages": [
            {"name": name, "previous": previous, "enm_file": enm_file, "minimize": minimize}
            for name, previous, enm_file, minimize in stages
        ],
        "tutorial_parameters": {
            "minimize_steps": 4800,
            "stage_run_steps": 2400000,
            "timestep_fs": 2,
            "temperature_K": 300,
            "langevin_damping_ps_inv": 5,
            "cutoff_scheme_ang": "8-10-12",
            "pme_grid_spacing_ang": 1.5,
            "npt": True,
            "enm_k_ladder_kcal_mol_A2": [0.5, 0.1, 0.01, 0.0],
        },
        "note": (
            "Uses the existing explicit-solvent MGHH B_tube package. ENM files "
            "are generated with the local dense ENM approximation, then scaled "
            "to the tutorial k values."
        ),
    }
    (out / "F028_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "README.md").write_text(
        "# F028 Aksimentiev Exact B-tube Protocol\n\n"
        "Run with:\n\n"
        "```bash\n"
        "cd experiments/exp25_full_origami_relaxation/results/runs/"
        "F028_aksimentiev_exact_btube/B_tube_namd_solvated\n"
        "NAMD_THREADS=12 NAMD_PEMAP=0-15 ./run_f028_aksimentiev_exact.sh\n"
        "```\n\n"
        "Stages mirror the public tutorial: `equil_min`, `equil_k0.5`, "
        "`equil_k0.1`, `equil_k0.01`, `equil_k0`.\n"
        "\nThe generated launcher uses `+setcpuaffinity +pemap 0-15` by default, "
        "matching the 2026-05-22 F028 benchmark result.\n"
    )
    print(f"Wrote {out}")
    print(f"Runner: {out / 'run_f028_aksimentiev_exact.sh'}")


if __name__ == "__main__":
    main()
