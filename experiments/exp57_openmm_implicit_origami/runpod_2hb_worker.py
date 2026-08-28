#!/usr/bin/env python3
"""Pod-side 2HB crossover validation and same-GPU solvent benchmark."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

import runpod_duplex_worker as common

OUT = common.OUT
SEED = common.SEED + 10
INPUT = Path("input.nadoc")


def load_design():
    from backend.core.models import Design

    return Design.model_validate_json(INPUT.read_text())


def structural_spec(design, topology):
    """Map WC contacts, all C1' atoms, and cross-helix O3'-P bonds."""
    from backend.core.atomistic import build_atomistic_model

    model = build_atomistic_model(design)
    indices = common.atom_index(topology)
    residues = {}
    serial_atoms = {}
    for atom in model.atoms:
        serial_atoms[atom.serial] = atom
        residues.setdefault(
            (atom.helix_id, atom.bp_index, atom.direction),
            (atom.chain_id, atom.seq_num, atom.residue),
        )

    hbonds = []
    c1_pairs = []
    sites = sorted({(helix, bp) for helix, bp, _ in residues})
    for helix, bp in sites:
        forward = residues.get((helix, bp, "FORWARD"))
        reverse = residues.get((helix, bp, "REVERSE"))
        if forward is None or reverse is None:
            continue
        f_chain, f_seq, f_base = forward
        r_chain, r_seq, r_base = reverse
        c1_pairs.append(
            (indices[(f_chain, f_seq, "C1'")], indices[(r_chain, r_seq, "C1'")])
        )
        by_base = {f_base: (f_chain, f_seq), r_base: (r_chain, r_seq)}
        if {f_base, r_base} == {"DA", "DT"}:
            a_chain, a_seq = by_base["DA"]
            t_chain, t_seq = by_base["DT"]
            atom_pairs = (
                (a_chain, a_seq, "N6", t_chain, t_seq, "O4"),
                (a_chain, a_seq, "N1", t_chain, t_seq, "N3"),
            )
        elif {f_base, r_base} == {"DG", "DC"}:
            g_chain, g_seq = by_base["DG"]
            c_chain, c_seq = by_base["DC"]
            atom_pairs = (
                (g_chain, g_seq, "O6", c_chain, c_seq, "N4"),
                (g_chain, g_seq, "N1", c_chain, c_seq, "N3"),
                (g_chain, g_seq, "N2", c_chain, c_seq, "O2"),
            )
        else:
            raise RuntimeError(
                f"non-Watson-Crick pair at {helix}:{bp}: {f_base}/{r_base}"
            )
        hbonds.extend(
            (indices[(a, b, c)], indices[(d, e, f)])
            for a, b, c, d, e, f in atom_pairs
        )

    crossover_bonds = []
    crossover_labels = []
    for serial_a, serial_b in model.bonds:
        atom_a = serial_atoms[serial_a]
        atom_b = serial_atoms[serial_b]
        names = {atom_a.name, atom_b.name}
        if names != {"O3'", "P"} or atom_a.helix_id == atom_b.helix_id:
            continue
        crossover_bonds.append(
            (
                indices[(atom_a.chain_id, atom_a.seq_num, atom_a.name)],
                indices[(atom_b.chain_id, atom_b.seq_num, atom_b.name)],
            )
        )
        crossover_labels.append(
            f"{atom_a.helix_id}:{atom_a.bp_index}-{atom_b.helix_id}:{atom_b.bp_index}"
        )

    c1_indices = sorted(
        atom.index for atom in topology.atoms() if atom.name == "C1'"
    )
    if not hbonds or not crossover_bonds:
        raise RuntimeError(
            f"incomplete 2HB metric map: hbonds={len(hbonds)}, "
            f"crossovers={len(crossover_bonds)}"
        )
    return c1_pairs, hbonds, c1_indices, crossover_bonds, crossover_labels


def metrics(positions, spec, reference_c1):
    c1_pairs, hbonds, c1_indices, crossover_bonds, _ = spec
    hbond_distances = np.asarray(
        [np.linalg.norm(positions[a] - positions[b]) for a, b in hbonds]
    )
    pair_distances = np.asarray(
        [np.linalg.norm(positions[a] - positions[b]) for a, b in c1_pairs]
    )
    crossover_distances = np.asarray(
        [np.linalg.norm(positions[a] - positions[b]) for a, b in crossover_bonds]
    )
    c1_now = positions[c1_indices]
    return {
        "wc_contact_fraction": float(np.mean(hbond_distances < 0.36)),
        "wc_mean_distance_nm": float(np.mean(hbond_distances)),
        "c1_pair_mean_nm": float(np.mean(pair_distances)),
        "c1_pair_max_nm": float(np.max(pair_distances)),
        "c1_aligned_rmsd_nm": common.kabsch_rmsd_nm(reference_c1, c1_now),
        "crossover_o3p_mean_nm": float(np.mean(crossover_distances)),
        "crossover_o3p_max_nm": float(np.max(crossover_distances)),
    }


def run_implicit(design):
    from openmm import app, unit
    from backend.core.openmm_implicit import OpenMMImplicitProtocol, prepare_implicit_system

    common.emit_status("implicit_parameterize")
    protocol = OpenMMImplicitProtocol(
        random_seed=SEED,
        equilibration_steps=10_000,
        production_steps=500_000,
    )
    prepared = prepare_implicit_system(design, protocol)
    spec = structural_spec(design, prepared.topology)
    simulation, platform = common.make_simulation(
        prepared.topology, prepared.system, prepared.positions
    )
    properties = common.cuda_properties(platform, simulation.context)
    common.emit_status(
        "implicit_minimize",
        atoms=prepared.n_atoms,
        strands=prepared.n_strands,
        crossovers=len(spec[3]),
        cuda=properties,
    )
    simulation.minimizeEnergy(maxIterations=5_000)
    simulation.context.setVelocitiesToTemperature(300.0 * unit.kelvin, SEED)
    simulation.step(10_000)
    reference_positions, energy_after_equil = common.state_positions_nm(simulation)
    reference_c1 = reference_positions[spec[2]].copy()

    common.emit_status("implicit_benchmark")
    benchmark = common.timed_steps(simulation, 100_000)
    simulation.reporters.append(app.DCDReporter(str(OUT / "implicit.dcd"), 10_000))
    series = []
    for block in range(40):
        simulation.step(10_000)
        positions, energy = common.state_positions_nm(simulation)
        frame = metrics(positions, spec, reference_c1)
        frame.update(
            time_ps=220.0 + 20.0 * (block + 1),
            potential_energy_kj_mol=energy,
        )
        series.append(frame)
        if block % 5 == 4:
            common.emit_status(
                "implicit_stability",
                completed_blocks=block + 1,
                total_blocks=40,
                latest=frame,
            )

    final_positions, final_energy = common.state_positions_nm(simulation)
    final_metrics = metrics(final_positions, spec, reference_c1)
    simulation.saveCheckpoint(str(OUT / "implicit-final.chk"))
    simulation.saveState(str(OUT / "implicit-final-state.xml"))
    with (OUT / "implicit-final.cif").open("w") as handle:
        app.PDBxFile.writeFile(
            prepared.topology, final_positions * unit.nanometer, handle
        )
    return {
        "model": "AMBER14/OL15 + GBn2",
        "salt": "0.150 M generic monovalent implicit screening",
        "atoms": prepared.n_atoms,
        "heavy_atoms": prepared.n_heavy_atoms,
        "net_charge_e": prepared.net_charge_e,
        "cuda_properties": properties,
        "mapped_wc_pairs": len(spec[0]),
        "mapped_wc_contacts": len(spec[1]),
        "mapped_crossovers": len(spec[3]),
        "crossover_labels": spec[4],
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

    common.emit_status("explicit_parameterize")
    topology, positions, _ = build_openmm_topology(design)
    forcefield = app.ForceField("amber14-all.xml", "amber14/tip3p.xml")
    modeller = app.Modeller(topology, positions)
    modeller.addHydrogens(
        forcefield,
        pH=7.0,
        residueTemplates=amber_terminal_templates(modeller.topology),
    )
    modeller.addSolvent(
        forcefield,
        model="tip3p",
        padding=1.0 * unit.nanometer,
        ionicStrength=0.150 * unit.molar,
        neutralize=True,
        residueTemplates=amber_terminal_templates(modeller.topology),
    )
    system = forcefield.createSystem(
        modeller.topology,
        nonbondedMethod=app.PME,
        nonbondedCutoff=1.0 * unit.nanometer,
        constraints=app.HBonds,
        ewaldErrorTolerance=5.0e-4,
        residueTemplates=amber_terminal_templates(modeller.topology),
    )
    spec = structural_spec(design, modeller.topology)
    simulation, platform = common.make_simulation(
        modeller.topology, system, modeller.positions
    )
    properties = common.cuda_properties(platform, simulation.context)
    common.emit_status(
        "explicit_minimize",
        atoms=system.getNumParticles(),
        crossovers=len(spec[3]),
        cuda=properties,
    )
    simulation.minimizeEnergy(maxIterations=5_000)
    simulation.context.setVelocitiesToTemperature(300.0 * unit.kelvin, SEED)
    simulation.step(10_000)
    reference_positions, energy_after_equil = common.state_positions_nm(simulation)
    reference_c1 = reference_positions[spec[2]].copy()

    common.emit_status("explicit_benchmark")
    benchmark = common.timed_steps(simulation, 100_000)
    simulation.reporters.append(app.DCDReporter(str(OUT / "explicit.dcd"), 10_000))
    series = []
    for block in range(40):
        simulation.step(10_000)
        positions_now, energy = common.state_positions_nm(simulation)
        frame = metrics(positions_now, spec, reference_c1)
        frame.update(
            time_ps=220.0 + 20.0 * (block + 1),
            potential_energy_kj_mol=energy,
        )
        series.append(frame)
        if block % 5 == 4:
            common.emit_status(
                "explicit_stability",
                completed_blocks=block + 1,
                total_blocks=40,
                latest=frame,
            )

    final_positions, final_energy = common.state_positions_nm(simulation)
    final_metrics = metrics(final_positions, spec, reference_c1)
    simulation.saveCheckpoint(str(OUT / "explicit-final.chk"))
    simulation.saveState(str(OUT / "explicit-final-state.xml"))
    with (OUT / "explicit-final.cif").open("w") as handle:
        app.PDBxFile.writeFile(
            modeller.topology, final_positions * unit.nanometer, handle
        )
    return {
        "model": "AMBER14/OL15 + explicit TIP3P/PME",
        "salt": "0.150 M explicit NaCl plus neutralizing counterions",
        "atoms": system.getNumParticles(),
        "cuda_properties": properties,
        "mapped_wc_pairs": len(spec[0]),
        "mapped_wc_contacts": len(spec[1]),
        "mapped_crossovers": len(spec[3]),
        "energy_after_equil_kj_mol": energy_after_equil,
        "final_energy_kj_mol": final_energy,
        "benchmark": benchmark,
        "final_metrics": final_metrics,
        "series": series,
    }


def main() -> None:
    import openmm

    started = time.time()
    common.emit_status("starting", openmm_version=openmm.version.version)
    design = load_design()
    (OUT / "design.nadoc").write_text(design.to_json())
    implicit = run_implicit(design)
    explicit = run_explicit_reference(design)
    speedup = implicit["benchmark"]["ns_per_day"] / explicit["benchmark"]["ns_per_day"]
    final = implicit["final_metrics"]
    stable = bool(
        math.isfinite(implicit["final_energy_kj_mol"])
        and final["wc_contact_fraction"] >= 0.70
        and final["c1_pair_max_nm"] <= 1.50
        and final["c1_aligned_rmsd_nm"] <= 0.70
        and final["crossover_o3p_max_nm"] <= 0.25
    )
    explicit_final = explicit["final_metrics"]
    explicit_stable = bool(
        math.isfinite(explicit["final_energy_kj_mol"])
        and explicit_final["wc_contact_fraction"] >= 0.70
        and explicit_final["c1_pair_max_nm"] <= 1.50
        and explicit_final["c1_aligned_rmsd_nm"] <= 0.70
        and explicit_final["crossover_o3p_max_nm"] <= 0.25
    )
    result = {
        "schema_version": 1,
        "case": "fully sequenced 2HB crossover motif",
        "seed": SEED,
        "timestep_fs": common.TIMESTEP_FS,
        "implicit_simulated_ns": 1.02,
        "wall_seconds_total": time.time() - started,
        "implicit": implicit,
        "explicit_reference": explicit,
        "implicit_speedup_vs_same_gpu_explicit": speedup,
        "basic_stability_passed": stable,
        "explicit_basic_stability_passed": explicit_stable,
        "stability_gate": {
            "wc_contact_fraction_min": 0.70,
            "c1_pair_max_nm_max": 1.50,
            "c1_aligned_rmsd_nm_max": 0.70,
            "crossover_o3p_max_nm_max": 0.25,
            "energy_must_be_finite": True,
        },
        "scope_warning": (
            "A 1 ns two-helix crossover smoke test does not establish long-time "
            "origami mechanics, large-bundle stability, or ion-specific physics."
        ),
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    common.emit_status(
        "completed",
        basic_stability_passed=stable,
        speedup=speedup,
        implicit_ns_day=implicit["benchmark"]["ns_per_day"],
        explicit_ns_day=explicit["benchmark"]["ns_per_day"],
    )


if __name__ == "__main__":
    main()
