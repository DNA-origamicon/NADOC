#!/usr/bin/env python3
"""Recover diagnostics from an intentionally stopped unstable 6HB trajectory."""

from __future__ import annotations

import json
import re
import traceback

import netCDF4
import parmed as pmd

from experiments.exp58_amber_gbion.model import GBIONNaClConfig
import runpod_worker_6hb as worker


def main() -> None:
    work = worker.WORK
    out = worker.OUT
    metadata = json.loads((work / "origami_map.json").read_text())
    config = GBIONNaClConfig(
        sphere_radius_angstrom=metadata["sphere_radius_angstrom"]
    )
    with netCDF4.Dataset(work / "gb_production.nc") as dataset:
        frames = len(dataset.dimensions["frame"])
    completed_steps = frames * worker.TRAJECTORY_INTERVAL
    mdout = (work / "gb_production.mdout").read_text(errors="replace")
    payload = {
        "reason": "production intentionally stopped after overflowed energy and temperature fields",
        "trajectory_frames": frames,
        "completed_steps_from_frames": completed_steps,
        "completed_ps_from_frames": completed_steps * config.timestep_ps,
        "asterisk_overflow_fields": len(re.findall(r"\*{5,}", mdout)),
        "temperature_overflow": bool(re.search(r"TEMP\(K\)\s*=\s*\*", mdout)),
        "energy_overflow": bool(
            re.search(r"(?:Etot|EPtot|EGB|VDWAALS)\s*=\s*\*", mdout)
        ),
    }
    try:
        parm = pmd.load_file(
            str(work / "gbion.parm7"), xyz=str(work / "gbion.rst7")
        )
        topology = worker.base.topology_summary(parm)
        topology.update(
            {
                "bonds": len(parm.bonds),
                "dna_residues": metadata["dna_residues"],
                "strand_count": metadata["strand_count"],
                "phosphorus": sum(
                    atom.name.strip() == "P" for atom in parm.atoms
                ),
                "intended_base_pairs": metadata["intended_pair_count"],
                "designed_unpaired_residues": metadata[
                    "designed_unpaired_residues"
                ],
            }
        )
        payload["topology"] = topology
        payload["analysis"] = worker.analyze_gbion(
            parm, metadata, completed_steps, config
        )
    except Exception as exc:  # preserve the numerical failure instead of hiding it
        payload["analysis_error"] = str(exc)
        payload["analysis_traceback"] = traceback.format_exc()

    parity_cpu_text = (work / "parity_cpu.mdout").read_text(errors="replace")
    parity_gpu_text = (work / "parity_gpu.mdout").read_text(errors="replace")
    cpu_energy = worker.base.parse_energies(parity_cpu_text)
    gpu_energy = worker.base.parse_energies(parity_gpu_text)
    payload["native_validation"] = {
        "cpu_energy_kcal_mol": cpu_energy[-1] if cpu_energy else None,
        "gpu_energy_kcal_mol": gpu_energy[-1] if gpu_energy else None,
        "absolute_delta_kcal_mol": (
            abs(cpu_energy[-1] - gpu_energy[-1])
            if cpu_energy and gpu_energy
            else None
        ),
        "cuda_banner": "GPU DEVICE INFO" in parity_gpu_text,
        "gbion_v3_echo": bool(re.search(r"gbion\s*=\s*3", parity_gpu_text)),
        "cuda_build_scope": "sm89-only-source-patched",
    }
    benchmark_text = (work / "gb_benchmark.mdout").read_text(errors="replace")
    chain_text = (worker.ROOT / "nadoc_chain.out").read_text(errors="replace")
    wall_hits = re.findall(r'"benchmark_ns_per_day":\s*([0-9.]+)', chain_text)
    payload["throughput"] = {
        "wall_ns_per_day": float(wall_hits[-1]) if wall_hits else None,
        "amber_reported_ns_per_day": worker.base.parse_amber_ns_per_day(
            benchmark_text
        ),
        "namd_reference_ns_per_day": 90.9034,
        "wall_ratio_vs_namd": (
            float(wall_hits[-1]) / 90.9034 if wall_hits else None
        ),
    }
    leap_text = (worker.OUT / "tleap-gbion.log").read_text(errors="replace")
    contacts = [
        float(value)
        for value in re.findall(r"Close contact of\s+([0-9.]+) angstroms", leap_text)
    ]
    warning_hits = re.findall(
        r"Exiting LEaP: Errors =\s*(\d+); Warnings =\s*(\d+)", leap_text
    )
    payload["leap_diagnostics"] = {
        "errors": int(warning_hits[-1][0]) if warning_hits else None,
        "warnings": int(warning_hits[-1][1]) if warning_hits else None,
        "close_contact_count": len(contacts),
        "minimum_close_contact_angstrom": min(contacts) if contacts else None,
    }
    payload["stage_overflow"] = {}
    for stage in ("parity_gpu", "gb_min", "gb_heat", "gb_equil", "gb_benchmark", "gb_production"):
        text = (work / f"{stage}.mdout").read_text(errors="replace")
        payload["stage_overflow"][stage] = {
            "asterisk_fields": len(re.findall(r"\*{5,}", text)),
            "temperature_overflow": bool(re.search(r"TEMP\(K\)\s*=\s*\*", text)),
        }
    (out / "partial_analysis.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
