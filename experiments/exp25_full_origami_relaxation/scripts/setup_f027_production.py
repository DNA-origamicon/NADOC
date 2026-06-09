#!/usr/bin/env python3
"""Prepare the F027 full B_tube literature-aligned production-candidate run.

This script builds a fresh explicit-solvent MGH package when needed, writes the
F027 staged NAMD configs, generates a manifest, and writes a restartable runner
script. The long runner is intentionally separate so setup can be inspected and
the run can be resumed after any failed health gate.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.models import Design  # noqa: E402
from backend.core.namd_solvate import build_namd_solvated_package  # noqa: E402


EXP = ROOT / "experiments" / "exp25_full_origami_relaxation"
DEFAULT_DESIGN = ROOT / "workspace" / "B_tube_relaxed_atomistic_F001.nadoc"
DEFAULT_RUN_DIR = EXP / "results" / "runs" / "F027_literature_aligned_enm_production"


def _find_package_dir(run_dir: Path) -> Path | None:
    candidates = sorted(run_dir.glob("*_namd_solvated"))
    return candidates[0] if candidates else None


def _read_box_from_pdb(pdb_path: Path) -> tuple[float, float, float]:
    for line in pdb_path.read_text(errors="replace").splitlines():
        if line.startswith("CRYST1"):
            return (float(line[6:15]), float(line[15:24]), float(line[24:33]))
    raise RuntimeError(f"No CRYST1 record found in {pdb_path}")


def _write_restraints_pdb(pdb_path: Path, dst_path: Path) -> None:
    lines: list[str] = []
    for raw in pdb_path.read_text(errors="replace").splitlines(keepends=True):
        if raw.startswith("ATOM"):
            atom_name = raw[12:16].strip()
            value = 0.0 if atom_name.startswith("H") else 1.0
            raw = f"{raw[:60]}{value:6.2f}{raw[66:].rstrip()}\n"
        elif raw.startswith("HETATM"):
            raw = f"{raw[:60]}{0.0:6.2f}{raw[66:].rstrip()}\n"
        lines.append(raw)
    dst_path.write_text("".join(lines))


def _common(name_stem: str, package_dir: Path) -> str:
    bx, by, bz = _read_box_from_pdb(package_dir / f"{name_stem}.pdb")
    extra = ""
    if (package_dir / "mgh_extrabonds.txt").exists():
        extra = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n"
    return f"""\
structure          {name_stem}.psf
coordinates        {name_stem}.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
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

outputEnergies     1000
xstFreq            10000
restartfreq        50000
binaryrestart      yes
"""


def _restraints(scale: float | None) -> str:
    if scale is None:
        return "constraints        off\n"
    return f"""\
constraints        on
consref            restraints_dna_heavy.pdb
conskfile          restraints_dna_heavy.pdb
conskcol           B
constraintScaling  {scale:g}
"""


def _write_conf(
    package_dir: Path,
    common: str,
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
    extra_bonds_files: list[str] | None = None,
) -> None:
    lines = [common]
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
    lines.append(_restraints(scale))
    for extra in extra_bonds_files or []:
        lines.append("extraBonds         on\n")
        lines.append(f"extraBondsFile     {extra}\n")
    if previous is not None:
        lines.append(f"binCoordinates     output/{previous}.coor\n")
        if not reinit:
            lines.append(f"binVelocities      output/{previous}.vel\n")
        lines.append(f"extendedSystem     output/{previous}.xsc\n")
    if reinit:
        lines.append(f"reinitvels         {temp:g}\n")
    if minimize_steps:
        lines.append(f"minimize           {minimize_steps}\n")
    if steps:
        lines.append(f"run                {steps}\n")
    (package_dir / f"{name}.conf").write_text("".join(lines))


def _verify_mgh(package_dir: Path) -> None:
    path = package_dir / "mgh_extrabonds.txt"
    if not path.exists():
        raise RuntimeError("F027 requires MGH; mgh_extrabonds.txt was not generated.")
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("mgh_extrabonds.txt is empty.")
    bad = [line for line in lines[:1000] if " 1.0000 1.9400" not in line]
    if bad:
        raise RuntimeError(
            "mgh_extrabonds.txt does not use the F027 literature default "
            f"(first bad line: {bad[0]!r})"
        )


def _runner_text() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../../../.." && pwd)"
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="$PKG_DIR/F027_manifest.json"
NAMD="${NAMD_BIN:-/home/jojo/Applications/NAMD_3.0.2/namd3}"
THREADS="${NAMD_THREADS:-12}"
PEMAP="${NAMD_PEMAP:-0-15}"
DEVICES="${NAMD_DEVICES:-0}"
HEALTH="$ROOT/experiments/exp25_full_origami_relaxation/scripts/f027_health_check.py"
ENM_SCRIPT="$ROOT/experiments/exp25_full_origami_relaxation/scripts/generate_dense_enm_restraints.py"

cd "$PKG_DIR"
mkdir -p output
namd_args=("+p${THREADS}" "+setcpuaffinity")
if [[ -n "$PEMAP" ]]; then
  namd_args+=("+pemap" "$PEMAP")
fi

name_stem="$(python - <<'PY'
import json
print(json.load(open('F027_manifest.json'))['name_stem'])
PY
)"

if [[ ! -f dense_enm_k0p1_5A.extrabonds ]]; then
  echo "[F027] Generating dense ENM restraints"
  python "$ENM_SCRIPT" \
    --psf "${name_stem}.psf" \
    --pdb "${name_stem}.pdb" \
    --out dense_enm_k0p1_5A.extrabonds \
    --report dense_enm_k0p1_5A.report.json \
    --k 0.1 \
    --cutoff-ang 5.0
fi

python - <<'PY' > output/F027_stage_names.txt
import json
data=json.load(open('F027_manifest.json'))
for s in data['stages']:
    print(s['name'])
PY

while read -r stage_name; do
  [[ -z "$stage_name" ]] && continue
  done_file="output/${stage_name}.coor"
  if [[ -f "$done_file" ]]; then
    echo "[F027] Skip completed $stage_name"
  else
    echo "[F027] Running $stage_name"
    "$NAMD" "${namd_args[@]}" +devices "$DEVICES" "${stage_name}.conf" > "${stage_name}.log" 2>&1
  fi

  needs_health="$(python - "$stage_name" <<'PY'
import json, sys
data=json.load(open('F027_manifest.json'))
stage=next(s for s in data['stages'] if s['name']==sys.argv[1])
print('yes' if stage.get('health', True) else 'no')
PY
)"
  if [[ "$needs_health" == "yes" ]]; then
    echo "[F027] Health check $stage_name"
    python "$HEALTH" \
      --package-dir "$PKG_DIR" \
      --segment "$stage_name" \
      --stage "$stage_name" \
      --name-stem "$name_stem" \
      --min-c1 0.85 \
      --min-wc 0.85 \
      --paired-max-ang 13.5 \
      --wc-policy warn
  fi
done < output/F027_stage_names.txt

echo "[F027] Pipeline complete"
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design", type=Path, default=DEFAULT_DESIGN)
    ap.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    ap.add_argument("--padding-nm", type=float, default=1.2)
    ap.add_argument("--nacl-mM", type=float, default=150.0)
    ap.add_argument("--mgcl2-mM", type=float, default=12.5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force-rebuild", action="store_true")
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    package_dir = _find_package_dir(run_dir)
    if args.force_rebuild and package_dir is not None:
        raise RuntimeError(
            f"Refusing to delete existing package automatically: {package_dir}. "
            "Move it aside and rerun."
        )
    if package_dir is None:
        design = Design.model_validate_json(args.design.read_text())
        print("[F027] Building fresh explicit-solvent MGH package; this can take a while.")
        data = build_namd_solvated_package(
            design,
            padding_nm=args.padding_nm,
            ion_conc_mM=args.nacl_mM,
            mg_conc_mM=args.mgcl2_mM,
            mg_hexahydrate=True,
            seed=args.seed,
        )
        zip_path = run_dir / "explicit_mgh_package.zip"
        zip_path.write_bytes(data)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(run_dir)
        package_dir = _find_package_dir(run_dir)
        if package_dir is None:
            raise RuntimeError("Package extraction produced no *_namd_solvated directory.")

    assert package_dir is not None
    psfs = sorted(package_dir.glob("*.psf"))
    if not psfs:
        raise RuntimeError(f"No PSF found in {package_dir}")
    name_stem = psfs[0].stem
    _verify_mgh(package_dir)
    _write_restraints_pdb(package_dir / f"{name_stem}.pdb", package_dir / "restraints_dna_heavy.pdb")

    common = _common(name_stem, package_dir)
    (package_dir / "output").mkdir(exist_ok=True)

    stages: list[dict] = []
    previous: str | None = None

    def add(
        name: str,
        *,
        temp: float,
        damping: float,
        scale: float | None,
        steps: int,
        npt: bool,
        dcd_freq: int,
        minimize_steps: int = 0,
        reinit: bool = False,
        health: bool = True,
        extra_bonds_files: list[str] | None = None,
    ) -> None:
        nonlocal previous
        _write_conf(
            package_dir,
            common,
            name=name,
            previous=previous,
            temp=temp,
            damping=damping,
            scale=scale,
            steps=steps,
            npt=npt,
            dcd_freq=dcd_freq,
            minimize_steps=minimize_steps,
            reinit=reinit,
            extra_bonds_files=extra_bonds_files,
        )
        stages.append({
            "name": name,
            "temp": temp,
            "damping": damping,
            "scale": scale,
            "steps": steps,
            "npt": npt,
            "dcd_freq": dcd_freq,
            "minimize_steps": minimize_steps,
            "health": health,
            "extra_bonds_files": extra_bonds_files or [],
        })
        previous = name

    add("F027_00_min_k1", temp=25, damping=10, scale=1.0, steps=0,
        npt=False, dcd_freq=0, minimize_steps=10_000, health=False)
    add("F027_01_050K_NVT_k1_10ps", temp=50, damping=10, scale=1.0,
        steps=10_000, npt=False, dcd_freq=2_000, reinit=True)
    add("F027_02_100K_NVT_k1_20ps", temp=100, damping=5, scale=1.0,
        steps=20_000, npt=False, dcd_freq=4_000, reinit=True)
    add("F027_03_200K_NVT_k1_50ps", temp=200, damping=2, scale=1.0,
        steps=50_000, npt=False, dcd_freq=10_000, reinit=True)
    add("F027_04_310K_NVT_k1_100ps", temp=310, damping=1, scale=1.0,
        steps=100_000, npt=False, dcd_freq=10_000, reinit=True)
    add("F027_05_310K_NPT_k1_1ns", temp=310, damping=1, scale=1.0,
        steps=1_000_000, npt=True, dcd_freq=50_000)
    add("F027_06_310K_NPT_pos0p1_enm0p1_1ns", temp=310, damping=1, scale=0.1,
        steps=1_000_000, npt=True, dcd_freq=50_000,
        extra_bonds_files=["dense_enm_k0p1_5A.extrabonds"])
    add("F027_07_310K_NPT_enm0p1_15ns", temp=310, damping=1, scale=None,
        steps=15_000_000, npt=True, dcd_freq=100_000,
        extra_bonds_files=["dense_enm_k0p1_5A.extrabonds"])
    add("F027_08_310K_NVT_enm0p1_prod50ns", temp=310, damping=1, scale=None,
        steps=50_000_000, npt=False, dcd_freq=100_000,
        extra_bonds_files=["dense_enm_k0p1_5A.extrabonds"])

    manifest = {
        "protocol": "F027_literature_aligned_enm_production",
        "name_stem": name_stem,
        "package_dir": str(package_dir),
        "design": str(args.design),
        "nacl_mM": args.nacl_mM,
        "mgcl2_mM": args.mgcl2_mM,
        "mg_hexahydrate": True,
        "health_gates": {
            "min_c1_paired": 0.90,
            "min_wc_ref_relative": 0.85,
            "paired_max_ang": 13.0,
        },
        "stages": stages,
    }
    (package_dir / "F027_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    runner = package_dir / "run_f027_pipeline.sh"
    runner.write_text(_runner_text())
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"[F027] Package: {package_dir}")
    print(f"[F027] Manifest: {package_dir / 'F027_manifest.json'}")
    print(f"[F027] Runner: {runner}")


if __name__ == "__main__":
    main()
