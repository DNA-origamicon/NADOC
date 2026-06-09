#!/usr/bin/env python3
"""Append an AutoNAMD-style NAMD production branch to an existing MD job."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.md_protocols import SegmentSpec


PCTS = [(10.0, 0.10), (50.0, 0.40), (100.0, 0.50)]


def _display_dcd_freq(steps: int) -> int:
    return max(100, min(10_000, int(steps) // 50))


def _autonamd_common(name_stem: str, box: tuple[float, float, float], mgh_extrabonds: bool) -> str:
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    extras = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n" if mgh_extrabonds else ""
    return f"""\
structure          {name_stem}.psf
coordinates        {name_stem}.pdb

seed               54321
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         8
cutoff             10
pairlistdist       12

timestep           2.0
rigidBonds         all
rigidTolerance     1.0e-8
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

PME                on
PMEGridSpacing     1.6
PMEInterpOrder     4

langevin           on
langevinHydrogen   off
langevinDamping    0.1
langevinTemp       310

useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.0
langevinPistonTemp 310
langevinPistonPeriod  200
langevinPistonDecay   100

outputEnergies     2000
xstFreq            2000
restartfreq        2000
binaryrestart      yes
constraints        off
"""


def _conf(spec: SegmentSpec, name_stem: str, box: tuple[float, float, float], mgh_extrabonds: bool) -> str:
    return _autonamd_common(name_stem, box, mgh_extrabonds) + f"""\
outputName         output/{spec.name}
dcdFile            output/{spec.name}.dcd
dcdFreq            {spec.dcd_freq}
xstFile            output/{spec.name}.xst
binCoordinates     output/{spec.previous}.coor
binVelocities      output/{spec.previous}.vel
extendedSystem     output/{spec.previous}.xsc
run                {spec.steps}
"""


def _segments(name_stem: str, previous: str, start_stage_idx: int) -> list[SegmentSpec]:
    total_steps = 500_000  # 1 ns at 2 fs
    out: list[SegmentSpec] = []
    for pct, frac in PCTS:
        steps = max(100, int(total_steps * frac))
        name = f"{name_stem}_{start_stage_idx:02d}_AutoNAMD_prod1ns_k0_p{int(pct)}"
        out.append(SegmentSpec(
            name=name,
            stage="310K NPT AutoNAMD-style 1 ns unrestrained",
            percent=pct,
            steps=steps,
            temp=310.0,
            damping=0.1,
            scale=None,
            npt=True,
            previous=previous,
            reinit=False,
            dcd_freq=_display_dcd_freq(steps),
            min_c1_paired=0.90,
            min_wc_ref_relative=0.80,
        ))
        previous = name
    return out


def append_branch(job_id: str, workspace: Path, previous: str) -> None:
    job_path = workspace / "md_jobs" / job_id / "job.json"
    job = json.loads(job_path.read_text())
    package_dir = workspace / "md_jobs" / job_id / job["package_subdir"]
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    name_stem = manifest["name_stem"]
    box = tuple(float(x) for x in manifest["box_ang"])
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))
    start_stage_idx = len({s["stage"] for s in manifest["segments"]}) + 1
    existing = {s["name"] for s in manifest["segments"]}
    segments = [s for s in _segments(name_stem, previous, start_stage_idx) if s.name not in existing]
    if not segments:
        print("No new AutoNAMD-style segments needed.")
        return

    start_idx = len(manifest["segments"])
    for spec in segments:
        (package_dir / f"{spec.name}.conf").write_text(_conf(spec, name_stem, box, mgh_extrabonds))

    manifest["segments"].extend(asdict(s) for s in segments)
    manifest["autonamd_style_branch"] = {
        "status": "queued",
        "previous": previous,
        "source_settings": "/home/jojo/Work/AutoNAMD/simulations/benchmark/benchmark.namd",
        "differences_remaining": [
            "NADOC system still uses MGH hydrated magnesium plus neutralizing sodium, not AutoNAMD free MG ions.",
            "NADOC system is 10hb origami-sized, not the AutoNAMD Holliday-junction benchmark/umbrella system.",
            "No AutoNAMD colvars restraint is applied; this is unrestrained production.",
        ],
        "health_gate": {
            "min_c1_paired": 0.90,
            "min_wc_ref_relative": 0.80,
        },
        "first_new_segment": segments[0].name,
        "last_new_segment": segments[-1].name,
    }
    text = json.dumps(manifest, indent=2)
    manifest_path.write_text(text)
    (package_dir / "nadoc_md_run.json").write_text(text)

    for seg in job["segments"]:
        if seg["status"] in {"failed", "pending"}:
            seg["status"] = "superseded"
    job["segments"].extend({
        "name": s.name,
        "stage": s.stage,
        "percent": s.percent,
        "steps": s.steps,
        "status": "pending",
    } for s in segments)
    job["status"] = "queued"
    job["error"] = None
    job["current_segment_idx"] = start_idx
    job_path.write_text(json.dumps(job, indent=2) + "\n")

    print(f"Appended {len(segments)} AutoNAMD-style production segments to {job_id}.")
    print(f"Starts at index {start_idx}: {segments[0].name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--previous", default="10hb_23_310K_NPT_k0_probe_wc80_p100")
    args = parser.parse_args()
    append_branch(args.job_id, args.workspace, args.previous)


if __name__ == "__main__":
    main()
