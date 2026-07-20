"""Prepare, launch, and inspect the 7-bp crossover transition experiment.

Preparation and execution are deliberately separate. ``prepare`` may solvate and
write NAMD inputs, but only ``launch --confirm-start`` can consume the GPU.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import LatticeType, StrandType
from backend.core.sequences import assign_scaffold_sequence, assign_staple_sequences

EXP_DIR = Path(__file__).resolve().parent
RUN_ROOT = EXP_DIR / "runs"
RESULTS = EXP_DIR / "results"
# The center helix (1, 1) faces (1, 2) at bp 7 and (0, 1) at bp 14.
# Successive 7-bp honeycomb crossover opportunities address different neighbors;
# a two-helix system therefore cannot represent both token boundaries.
CELLS = [(0, 1), (1, 1), (1, 2)]
LENGTH_BP = 21
TOKEN = {"start_bp": 7, "end_bp_exclusive": 14, "length_bp": 7}
CONDITIONS = {
    "no_crossover": set(),
    "left_crossover": {7},
    "bracketed_crossovers": {7, 14},
}


def _xover_bp(xover) -> int:
    return int(xover.half_a.index)


def build_condition(name: str):
    """Build one matched three-helix honeycomb design and assign DNA sequences."""
    if name not in CONDITIONS:
        raise ValueError(f"unknown condition {name!r}")
    keep = CONDITIONS[name]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(CELLS, LENGTH_BP, lattice=LatticeType.HONEYCOMB,
                         name=f"exp43_{name}")
        hb.auto_crossover()
        for xo in list(design_state.get_or_404().crossovers):
            if _xover_bp(xo) not in keep:
                hb.delete_crossover(xo.id)
        design = design_state.get_or_404().model_copy(deep=True)

    # Each uncrossed scaffold is an independent strand. Assign the same preset
    # deterministically to every scaffold, then derive Watson-Crick staples.
    for sid in [s.id for s in design.strands if s.strand_type == StrandType.SCAFFOLD]:
        design, _, _ = assign_scaffold_sequence(design, "M13mp18", strand_id=sid)
    design = assign_staple_sequences(design)
    actual = {_xover_bp(x) for x in design.crossovers}
    if actual != keep:
        raise RuntimeError(f"{name}: expected crossovers {sorted(keep)}, got {sorted(actual)}")
    return design


def build_designs(*, overwrite: bool = False) -> dict:
    """Write inexpensive NADOC designs and provenance; does not solvate or run MD."""
    design_root = EXP_DIR / "designs"
    design_root.mkdir(parents=True, exist_ok=True)
    records = {}
    for name in CONDITIONS:
        out = design_root / name
        if out.exists() and overwrite:
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
        design = build_condition(name)
        (out / "design.nadoc").write_text(design.to_json())
        record = {
            "condition": name,
            "lattice": "honeycomb",
            "cells": CELLS,
            "length_bp": LENGTH_BP,
            "prediction_token": TOKEN,
            "crossover_bp": sorted(CONDITIONS[name]),
            "temperature_K": 300.0,
            "NaCl_mM": 150.0,
            "MgCl2_mM": 0.0,
            "sequence_source": "M13mp18 prefix per scaffold strand",
            "dataset_role": "matched_crossover_mechanics_pilot",
        }
        (out / "system.json").write_text(json.dumps(record, indent=2))
        records[name] = record
    return records


def prepare(*, workspace: Path, overwrite: bool = False) -> dict:
    """Solvate and emit the full reference ladder, but leave every job unstarted."""
    from backend.core.md_protocols import prepare_propagator_reference
    from backend.ml.propagator.local_run import attach_and_queue, new_local_job

    build_designs(overwrite=overwrite)
    workspace.mkdir(parents=True, exist_ok=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    registry = {"experiment": "exp43_7bp_crossover_transition", "started": False,
                "workspace": str(workspace.resolve()), "jobs": {}}
    for name in CONDITIONS:
        design = build_condition(name)
        job = new_local_job(f"exp43_{name}")
        job.save(workspace)
        subdir, stem, segments = prepare_propagator_reference(
            design, job.job_dir(workspace), ion_conc_mM=150.0, mg_conc_mM=0.0,
            salt_mode="custom", minimize_steps=24_000)
        attach_and_queue(job, workspace, subdir, stem, segments)
        # Queued is the runner's prepared state; nothing calls start_job/run_job here.
        registry["jobs"][name] = {"job_id": job.job_id, "package_subdir": subdir,
                                  "name_stem": stem, "started": False}
    (RUN_ROOT / "registry.json").write_text(json.dumps(registry, indent=2))
    return registry


def launch(*, workspace: Path, condition: str, confirm_start: bool) -> None:
    """Run exactly one prepared condition, synchronously, after an explicit arm."""
    if not confirm_start:
        raise SystemExit("Refusing to start NAMD without --confirm-start")
    registry_path = RUN_ROOT / "registry.json"
    registry = json.loads(registry_path.read_text())
    if condition not in registry["jobs"]:
        raise SystemExit(f"condition {condition!r} is not prepared")
    from backend.ml.propagator.local_run import run_prepared_job
    entry = registry["jobs"][condition]
    entry["started"] = True
    registry["started"] = True
    registry_path.write_text(json.dumps(registry, indent=2))
    final = run_prepared_job(entry["job_id"], workspace)
    if str(final.status.value if hasattr(final.status, "value") else final.status) != "completed":
        raise SystemExit(f"job ended as {final.status}: {final.error}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("build", "prepare", "launch", "monitor", "process"))
    p.add_argument("--workspace", type=Path, default=ROOT / "workspace")
    p.add_argument("--condition", choices=tuple(CONDITIONS))
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--confirm-start", action="store_true")
    args = p.parse_args()
    if args.command == "build":
        print(json.dumps(build_designs(overwrite=args.overwrite), indent=2))
    elif args.command == "prepare":
        print(json.dumps(prepare(workspace=args.workspace, overwrite=args.overwrite), indent=2))
    elif args.command == "launch":
        if not args.condition:
            p.error("launch requires --condition")
        launch(workspace=args.workspace, condition=args.condition,
               confirm_start=args.confirm_start)
    elif args.command == "monitor":
        from experiments.exp43_7bp_crossover_transition.monitor import monitor_all
        raise SystemExit(monitor_all(args.workspace, write=True))
    else:
        from experiments.exp43_7bp_crossover_transition.process import process_all
        process_all(args.workspace)


if __name__ == "__main__":
    main()
