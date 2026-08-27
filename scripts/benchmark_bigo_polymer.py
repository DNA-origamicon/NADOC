#!/usr/bin/env python3
"""Benchmark real headless BigO polymers on the installed adaptive oxDNA build."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api import headless_assembly_build as hab
from backend.core.assembly_flatten import flatten_assembly
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.physics.oxdna_interface import write_configuration, write_topology
from scripts.benchmark_oxdna_memory import run_case


def _write_input(path: Path, topology: Path, configuration: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "backend = CUDA",
                "backend_precision = mixed",
                "CUDA_list = verlet",
                "CUDA_device = 0",
                "use_edge = true",
                "sim_type = MD",
                "restart_step_counter = true",
                "verlet_skin = 0.40",
                "T = 296K",
                "dt = 0.005",
                "thermostat = bussi",
                "bussi_tau = 1000",
                "newtonian_steps = 53",
                "refresh_vel = true",
                "interaction_type = DNA2",
                "salt_concentration = 0.5",
                "max_backbone_force = 5",
                "max_backbone_force_far = 10",
                "external_forces = false",
                "fix_diffusion = false",
                "configuration_print_energy = false",
                "print_initial_energy = false",
                "no_stdout_energy = true",
                "time_scale = linear",
                "max_io = 1000.0",
                f"topology = {topology}",
                f"conf_file = {configuration}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def build_case(part: Design, length: int, destination: Path) -> tuple[Path, dict]:
    started = time.perf_counter()
    with hab.assembly_scratch_session():
        assembly = hab.new_assembly(f"BigO x{length}")
        assembly = hab.add_inline_instance(part, name="BigO")
        if length > 1:
            assembly = hab.polymerize_periodic(
                assembly.instances[0].id, length, direction="forward"
            )
        polymerized = time.perf_counter()
        flat = flatten_assembly(assembly)
        flattened = time.perf_counter()
        geometry = _geometry_for_design(flat)
        geometrized = time.perf_counter()

    destination.mkdir(parents=True, exist_ok=True)
    topology = destination / "topology.top"
    configuration = destination / "conf.dat"
    input_path = destination / "input.txt"
    write_topology(flat, topology)
    # oxDNA cannot simulate NADOC's unknown-base marker. Use a deterministic
    # placeholder if a future benchmark part has incomplete sequence assignment;
    # the current fully sequenced BigO requires zero substitutions.
    topology_text = topology.read_text(encoding="utf-8")
    unknown_bases = topology_text.count(" N ")
    topology.write_text(topology_text.replace(" N ", " A "), encoding="utf-8")
    write_configuration(flat, geometry, configuration, oxdna_native_seed=True)
    _write_input(input_path, topology, configuration)
    exported = time.perf_counter()
    metrics = {
        "length": length,
        "instances": len(assembly.instances),
        "nucleotides": len(geometry),
        "strands": len(flat.strands),
        "unknown_bases_substituted": unknown_bases,
        "polymerize_s": polymerized - started,
        "flatten_s": flattened - polymerized,
        "geometry_s": geometrized - flattened,
        "export_s": exported - geometrized,
        "setup_s": exported - started,
    }
    return input_path, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=Path, default=Path("workspace/BigO.nadoc"))
    parser.add_argument(
        "--binary",
        type=Path,
        default=Path.home()
        / ".local/share/nadoc/engines/oxdna/current/bin/oxDNA",
    )
    parser.add_argument("--lengths", type=int, nargs="+", default=[1, 2, 4, 8, 16, 32])
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    part = Design.from_json(args.part.read_text(encoding="utf-8"))
    results: list[dict] = []
    def render_report() -> str:
        return json.dumps(
            {
                "part": str(args.part.resolve()),
                "binary": str(args.binary.resolve()),
                "steps": args.steps,
                "results": results,
            },
            indent=2,
        )

    with tempfile.TemporaryDirectory(prefix="nadoc-bigo-polymer-") as tmp:
        root = Path(tmp)
        for length in args.lengths:
            input_path, metrics = build_case(part, length, root / str(length))
            print(f"BigO x{length}: {metrics['nucleotides']:,} nt; running oxDNA...", flush=True)
            run = run_case(
                args.binary.resolve(),
                input_path,
                steps=args.steps,
                adaptive=True,
                discard_output=True,
                suppress_periodic_output=True,
            )
            metrics.update(run)
            results.append(metrics)
            print(json.dumps(metrics), flush=True)
            if args.output:
                args.output.write_text(render_report() + "\n", encoding="utf-8")
            if run["returncode"] != 0:
                break

    rendered = render_report()
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if results and results[-1]["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
