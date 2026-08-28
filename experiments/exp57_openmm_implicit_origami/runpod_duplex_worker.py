#!/usr/bin/env python3
"""Pod-side duplex validation and same-GPU explicit/implicit benchmark."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import numpy as np

OUT = Path(os.environ.get("NADOC_OUTPUT_DIR", "/root/nadoc-openmm-duplex/output"))
OUT.mkdir(parents=True, exist_ok=True)

SEQUENCE = "CGCGAATTCGCGATCGATCGA"  # 21 bp; mixed composition, no long homopolymer
SEED = 20260827
TIMESTEP_FS = 2.0


def emit_status(phase: str, **fields) -> None:
    payload = {"phase": phase, "at": time.time(), **fields}
    tmp = OUT / "status.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(OUT / "status.json")
    print(json.dumps(payload, sort_keys=True), flush=True)


def make_duplex():
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import (
        Design,
        DesignMetadata,
        Direction,
        Domain,
        Helix,
        LatticeType,
        Strand,
        StrandType,
        Vec3,
    )

    length = len(SEQUENCE)
    complement = str.maketrans("ACGT", "TGCA")
    reverse_complement = SEQUENCE.translate(complement)[::-1]
    helix = Helix(
        id="duplex_h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length,
    )
    return Design(
        id="exp57_runpod_duplex",
        metadata=DesignMetadata(name="exp57 RunPod 21-bp duplex"),
        lattice_type=LatticeType.SQUARE,
        helices=[helix],
        strands=[
            Strand(
                id="scaffold",
                strand_type=StrandType.SCAFFOLD,
                sequence=SEQUENCE,
                domains=[
                    Domain(
                        helix_id=helix.id,
                        start_bp=0,
                        end_bp=length - 1,
                        direction=Direction.FORWARD,
                    )
                ],
            ),
            Strand(
                id="staple",
                strand_type=StrandType.STAPLE,
                sequence=reverse_complement,
                domains=[
                    Domain(
                        helix_id=helix.id,
                        start_bp=length - 1,
                        end_bp=0,
                        direction=Direction.REVERSE,
                    )
                ],
            ),
        ],
    )


def cuda_properties(platform, context) -> dict[str, str]:
    names = set(platform.getPropertyNames())
    return {
        name: platform.getPropertyValue(context, name)
        for name in ("DeviceIndex", "DeviceName", "Precision")
        if name in names
    }


def make_simulation(topology, system, positions):
    from openmm import LangevinMiddleIntegrator, Platform, unit
    from openmm.app import Simulation

    integrator = LangevinMiddleIntegrator(
        300.0 * unit.kelvin,
        1.0 / unit.picosecond,
        TIMESTEP_FS * unit.femtoseconds,
    )
    integrator.setConstraintTolerance(1.0e-6)
    integrator.setRandomNumberSeed(SEED)
    platform = Platform.getPlatformByName("CUDA")
    simulation = Simulation(
        topology,
        system,
        integrator,
        platform,
        {"Precision": "mixed", "DeviceIndex": "0"},
    )
    simulation.context.setPositions(positions)
    return simulation, platform


def timed_steps(simulation, steps: int) -> dict[str, float]:
    # Synchronize before and after the timed block through a state request.
    simulation.context.getState(getEnergy=True)
    started = time.perf_counter()
    simulation.step(steps)
    simulation.context.getState(getEnergy=True)
    wall_s = time.perf_counter() - started
    simulated_ns = steps * TIMESTEP_FS / 1_000_000.0
    return {
        "steps": steps,
        "simulated_ns": simulated_ns,
        "wall_seconds": wall_s,
        "microseconds_per_step": wall_s * 1.0e6 / steps,
        "ns_per_day": simulated_ns * 86_400.0 / wall_s,
    }


def atom_index(topology) -> dict[tuple[str, int, str], int]:
    result = {}
    for atom in topology.atoms():
        result[(atom.residue.chain.id, int(atom.residue.id), atom.name)] = atom.index
    return result


def pairing_spec(design, topology):
    from backend.core.atomistic import build_atomistic_model

    model = build_atomistic_model(design)
    residue_map = {}
    for atom in model.atoms:
        residue_map.setdefault(
            (atom.helix_id, atom.bp_index, atom.direction),
            (atom.chain_id, atom.seq_num, atom.residue),
        )
    indices = atom_index(topology)
    c1_pairs = []
    hbonds = []
    for bp in range(len(SEQUENCE)):
        forward = residue_map[("duplex_h0", bp, "FORWARD")]
        reverse = residue_map[("duplex_h0", bp, "REVERSE")]
        f_chain, f_seq, f_base = forward
        r_chain, r_seq, r_base = reverse
        c1_pairs.append(
            (indices[(f_chain, f_seq, "C1'")], indices[(r_chain, r_seq, "C1'")])
        )
        by_base = {f_base: (f_chain, f_seq), r_base: (r_chain, r_seq)}
        if {f_base, r_base} == {"DA", "DT"}:
            a_chain, a_seq = by_base["DA"]
            t_chain, t_seq = by_base["DT"]
            atom_pairs = ((a_chain, a_seq, "N6", t_chain, t_seq, "O4"),
                          (a_chain, a_seq, "N1", t_chain, t_seq, "N3"))
        elif {f_base, r_base} == {"DG", "DC"}:
            g_chain, g_seq = by_base["DG"]
            c_chain, c_seq = by_base["DC"]
            atom_pairs = ((g_chain, g_seq, "O6", c_chain, c_seq, "N4"),
                          (g_chain, g_seq, "N1", c_chain, c_seq, "N3"),
                          (g_chain, g_seq, "N2", c_chain, c_seq, "O2"))
        else:
            raise RuntimeError(f"non-Watson-Crick pair at bp {bp}: {f_base}/{r_base}")
        hbonds.append(
            [(indices[(a, b, c)], indices[(d, e, f)]) for a, b, c, d, e, f in atom_pairs]
        )
    c1_indices = sorted({index for pair in c1_pairs for index in pair})
    return c1_pairs, hbonds, c1_indices


def kabsch_rmsd_nm(reference: np.ndarray, current: np.ndarray) -> float:
    p = current - current.mean(axis=0)
    q = reference - reference.mean(axis=0)
    u, _, vt = np.linalg.svd(p.T @ q)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    delta = p @ rotation - q
    return float(np.sqrt(np.mean(np.sum(delta * delta, axis=1))))


def duplex_metrics(positions_nm, c1_pairs, hbonds, c1_indices, reference_c1):
    c1_distances = np.array(
        [np.linalg.norm(positions_nm[a] - positions_nm[b]) for a, b in c1_pairs]
    )
    core_bp = range(2, len(c1_pairs) - 2)
    core_hb = [
        np.linalg.norm(positions_nm[a] - positions_nm[b])
        for bp in core_bp
        for a, b in hbonds[bp]
    ]
    c1_now = positions_nm[c1_indices]
    return {
        "core_wc_contact_fraction": float(np.mean(np.asarray(core_hb) < 0.36)),
        "core_wc_mean_distance_nm": float(np.mean(core_hb)),
        "core_c1_pair_mean_nm": float(np.mean(c1_distances[2:-2])),
        "core_c1_pair_max_nm": float(np.max(c1_distances[2:-2])),
        "c1_aligned_rmsd_nm": kabsch_rmsd_nm(reference_c1, c1_now),
        "c1_radius_of_gyration_nm": float(
            np.sqrt(np.mean(np.sum((c1_now - c1_now.mean(axis=0)) ** 2, axis=1)))
        ),
    }


def state_positions_nm(simulation):
    from openmm import unit

    state = simulation.context.getState(getPositions=True, getEnergy=True)
    positions = state.getPositions(asNumpy=True).value_in_unit(unit.nanometer)
    energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    return np.asarray(positions), float(energy)


def run_implicit(design):
    from openmm import app, unit

    from backend.core.openmm_implicit import OpenMMImplicitProtocol, prepare_implicit_system

    emit_status("implicit_parameterize")
    protocol = OpenMMImplicitProtocol(
        random_seed=SEED,
        equilibration_steps=10_000,
        production_steps=500_000,
    )
    prepared = prepare_implicit_system(design, protocol)
    c1_pairs, hbonds, c1_indices = pairing_spec(design, prepared.topology)
    simulation, platform = make_simulation(
        prepared.topology, prepared.system, prepared.positions
    )
    properties = cuda_properties(platform, simulation.context)
    emit_status(
        "implicit_minimize",
        atoms=prepared.n_atoms,
        strands=prepared.n_strands,
        cuda=properties,
    )
    simulation.minimizeEnergy(maxIterations=5_000)
    simulation.context.setVelocitiesToTemperature(300.0 * unit.kelvin, SEED)
    simulation.step(10_000)  # 20 ps equilibration
    reference_positions, energy_after_equil = state_positions_nm(simulation)
    reference_c1 = reference_positions[c1_indices].copy()

    emit_status("implicit_benchmark")
    benchmark = timed_steps(simulation, 100_000)  # 200 ps, no reporters
    trajectory = OUT / "implicit.dcd"
    simulation.reporters.append(app.DCDReporter(str(trajectory), 10_000))
    series = []
    for block in range(40):
        simulation.step(10_000)  # 20 ps per block; 800 ps total
        positions, energy = state_positions_nm(simulation)
        metrics = duplex_metrics(
            positions, c1_pairs, hbonds, c1_indices, reference_c1
        )
        metrics.update(
            {
                "time_ps": 220.0 + 20.0 * (block + 1),
                "potential_energy_kj_mol": energy,
            }
        )
        series.append(metrics)
        if block % 5 == 4:
            emit_status(
                "implicit_stability",
                completed_blocks=block + 1,
                total_blocks=40,
                latest=metrics,
            )

    final_positions, final_energy = state_positions_nm(simulation)
    final_metrics = duplex_metrics(
        final_positions, c1_pairs, hbonds, c1_indices, reference_c1
    )
    simulation.saveCheckpoint(str(OUT / "implicit-final.chk"))
    simulation.saveState(str(OUT / "implicit-final-state.xml"))
    with (OUT / "implicit-final.cif").open("w") as handle:
        app.PDBxFile.writeFile(prepared.topology, final_positions * unit.nanometer, handle)
    return {
        "model": "AMBER14/OL15 + GBn2",
        "salt": "0.150 M generic monovalent implicit screening",
        "atoms": prepared.n_atoms,
        "heavy_atoms": prepared.n_heavy_atoms,
        "net_charge_e": prepared.net_charge_e,
        "cuda_properties": properties,
        "energy_after_equil_kj_mol": energy_after_equil,
        "final_energy_kj_mol": final_energy,
        "benchmark": benchmark,
        "final_metrics": final_metrics,
        "series": series,
    }


def run_explicit_reference(design):
    from openmm import app, unit

    from backend.core.openmm_implicit import (
        amber_terminal_templates,
        build_openmm_topology,
    )

    emit_status("explicit_parameterize")
    topology, positions, _ = build_openmm_topology(design)
    forcefield = app.ForceField("amber14-all.xml", "amber14/tip3p.xml")
    modeller = app.Modeller(topology, positions)
    modeller.addHydrogens(
        forcefield,
        pH=7.0,
        residueTemplates=amber_terminal_templates(modeller.topology),
    )
    residue_templates = amber_terminal_templates(modeller.topology)
    modeller.addSolvent(
        forcefield,
        model="tip3p",
        padding=1.0 * unit.nanometer,
        ionicStrength=0.150 * unit.molar,
        neutralize=True,
        residueTemplates=residue_templates,
    )
    residue_templates = amber_terminal_templates(modeller.topology)
    system = forcefield.createSystem(
        modeller.topology,
        nonbondedMethod=app.PME,
        nonbondedCutoff=1.0 * unit.nanometer,
        constraints=app.HBonds,
        ewaldErrorTolerance=5.0e-4,
        residueTemplates=residue_templates,
    )
    simulation, platform = make_simulation(modeller.topology, system, modeller.positions)
    properties = cuda_properties(platform, simulation.context)
    emit_status(
        "explicit_minimize",
        atoms=system.getNumParticles(),
        cuda=properties,
    )
    simulation.minimizeEnergy(maxIterations=2_000)
    simulation.context.setVelocitiesToTemperature(300.0 * unit.kelvin, SEED + 1)
    simulation.step(10_000)
    emit_status("explicit_benchmark")
    benchmark = timed_steps(simulation, 100_000)
    _, final_energy = state_positions_nm(simulation)
    return {
        "model": "AMBER14/OL15 + explicit TIP3P/PME",
        "salt": "0.150 M explicit NaCl plus neutralizing counterions",
        "atoms": system.getNumParticles(),
        "cuda_properties": properties,
        "final_energy_kj_mol": final_energy,
        "benchmark": benchmark,
    }


def main() -> None:
    import openmm

    started = time.time()
    emit_status("starting", openmm_version=openmm.version.version)
    design = make_duplex()
    (OUT / "design.nadoc").write_text(design.to_json())
    implicit = run_implicit(design)
    explicit = run_explicit_reference(design)
    speedup = (
        implicit["benchmark"]["ns_per_day"]
        / explicit["benchmark"]["ns_per_day"]
    )
    final = implicit["final_metrics"]
    stable = bool(
        math.isfinite(implicit["final_energy_kj_mol"])
        and final["core_wc_contact_fraction"] >= 0.80
        and final["core_c1_pair_max_nm"] <= 1.40
        and final["c1_aligned_rmsd_nm"] <= 0.50
    )
    result = {
        "schema_version": 1,
        "sequence": SEQUENCE,
        "length_bp": len(SEQUENCE),
        "seed": SEED,
        "timestep_fs": TIMESTEP_FS,
        "implicit_simulated_ns": 1.02,
        "wall_seconds_total": time.time() - started,
        "implicit": implicit,
        "explicit_reference": explicit,
        "implicit_speedup_vs_same_gpu_explicit": speedup,
        "basic_stability_passed": stable,
        "stability_gate": {
            "core_wc_contact_fraction_min": 0.80,
            "core_c1_pair_max_nm_max": 1.40,
            "c1_aligned_rmsd_nm_max": 0.50,
            "energy_must_be_finite": True,
        },
        "scope_warning": (
            "A 1 ns duplex run is a smoke/stability result, not validation of "
            "origami ensembles or ion-specific physics."
        ),
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    emit_status(
        "completed",
        basic_stability_passed=stable,
        speedup=speedup,
        implicit_ns_day=implicit["benchmark"]["ns_per_day"],
        explicit_ns_day=explicit["benchmark"]["ns_per_day"],
    )


if __name__ == "__main__":
    main()
