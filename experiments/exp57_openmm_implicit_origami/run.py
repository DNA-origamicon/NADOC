#!/usr/bin/env python3
"""Prepare or run an OL15/GBn2 OpenMM validation arm.

Nothing runs at import time.  ``run`` and ``resume`` both enforce NADOC's live
heavy-simulation guard before an OpenMM CUDA Context can be created.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.core.models import Design
from backend.core.openmm_implicit import (
    OpenMMImplicitProtocol,
    assert_simulation_slot_available,
    attach_production_reporters,
    create_cuda_simulation,
    prepare_implicit_system,
    write_run_manifest,
)


def _protocol(args: argparse.Namespace) -> OpenMMImplicitProtocol:
    return OpenMMImplicitProtocol(
        random_seed=args.seed,
        device_index=args.device,
        nonbonded_mode=args.nonbonded_mode,
        cutoff_nm=args.cutoff_nm,
        equilibration_steps=args.equilibration_steps,
        production_steps=args.production_steps,
    )


def _load_design(path: Path) -> Design:
    return Design.from_json(path.read_text())


def prepare(args: argparse.Namespace):
    protocol = _protocol(args)
    prepared = prepare_implicit_system(_load_design(args.design), protocol)
    manifest = write_run_manifest(args.output, protocol, prepared)
    print(
        json.dumps(
            {
                "manifest": str(manifest),
                "atoms": prepared.n_atoms,
                "strands": prepared.n_strands,
                "net_charge_e": prepared.net_charge_e,
                "warning": (
                    "Preparation creates no CUDA Context. Do not launch the run "
                    "until the current NAMD job has finished."
                ),
            },
            indent=2,
        )
    )
    return protocol, prepared


def run(args: argparse.Namespace) -> None:
    if not args.confirm_namd_finished:
        raise RuntimeError(
            "Refusing to launch: pass --confirm-namd-finished only after the "
            "current NAMD production run has completed"
        )
    # Check before CPU parameterization and again inside create_cuda_simulation.
    assert_simulation_slot_available()
    protocol, prepared = prepare(args)
    simulation = create_cuda_simulation(prepared, protocol)
    simulation.minimizeEnergy(maxIterations=protocol.minimize_max_iterations)
    from openmm import unit

    simulation.context.setVelocitiesToTemperature(
        protocol.temperature_k * unit.kelvin,
        protocol.random_seed,
    )
    simulation.step(protocol.equilibration_steps)
    simulation.saveCheckpoint(str(args.output / "equilibrated.chk"))
    attach_production_reporters(simulation, args.output, protocol)
    simulation.step(protocol.production_steps)
    simulation.saveCheckpoint(str(args.output / "final.chk"))
    simulation.saveState(str(args.output / "final-state.xml"))


def resume(args: argparse.Namespace) -> None:
    if not args.confirm_namd_finished:
        raise RuntimeError(
            "Refusing to resume: pass --confirm-namd-finished only after the "
            "current NAMD production run has completed"
        )
    assert_simulation_slot_available()
    protocol, prepared = prepare(args)
    simulation = create_cuda_simulation(prepared, protocol)
    checkpoint = args.checkpoint or args.output / "checkpoint.chk"
    state = args.output / "state.xml"
    if checkpoint.exists():
        simulation.loadCheckpoint(str(checkpoint))
    elif state.exists():
        simulation.loadState(str(state))
    else:
        raise FileNotFoundError(f"no checkpoint or portable state in {args.output}")
    attach_production_reporters(simulation, args.output, protocol, append=True)
    simulation.step(protocol.production_steps)
    simulation.saveCheckpoint(str(args.output / "final.chk"))
    simulation.saveState(str(args.output / "final-state.xml"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, handler in (("prepare", prepare), ("run", run), ("resume", resume)):
        child = subparsers.add_parser(command)
        child.add_argument("design", type=Path)
        child.add_argument("output", type=Path)
        child.add_argument("--seed", type=int, default=20260827)
        child.add_argument("--device", default="0")
        child.add_argument(
            "--nonbonded-mode",
            choices=("no_cutoff", "cutoff_nonperiodic"),
            default="no_cutoff",
        )
        child.add_argument("--cutoff-nm", type=float, default=3.0)
        child.add_argument("--equilibration-steps", type=int, default=250_000)
        child.add_argument("--production-steps", type=int, default=5_000_000)
        if command in {"run", "resume"}:
            child.add_argument("--confirm-namd-finished", action="store_true")
        if command == "resume":
            child.add_argument("--checkpoint", type=Path)
        child.set_defaults(handler=handler)
    return parser


if __name__ == "__main__":
    parsed = _parser().parse_args()
    parsed.handler(parsed)
