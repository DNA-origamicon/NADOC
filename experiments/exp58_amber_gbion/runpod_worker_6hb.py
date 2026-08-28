#!/usr/bin/env python3
"""Pod-side origami-scale Amber26 OL15/GBION-v3 validation.

This deliberately reuses the native Amber helpers proven by the exp58 duplex gate,
but replaces every duplex-only topology and analysis assumption.  The first target is
the archived 656-nt ``6hb_2xT`` design: nine covalent strands, 252 intended base pairs,
and 152 deliberately unpaired crossover/terminal nucleotides.
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
import subprocess
import time
from pathlib import Path

import netCDF4
import numpy as np
import parmed as pmd

from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design
from backend.core.pdb_export import _chain_char, export_pdb
from experiments.exp58_amber_gbion.model import GBIONNaClConfig, render_ion_restraints
from experiments.exp58_amber_gbion import runpod_worker as base


SPHERE_PADDING_ANGSTROM = 12.0
MINIMIZATION_CYCLES = 2_000
HEATING_STEPS = 10_000          # 20 ps
EQUILIBRATION_STEPS = 10_000    # 20 ps
BENCHMARK_STEPS = 5_000         # 10 ps
TARGET_PRODUCTION_WALL_S = 20 * 60
MIN_PRODUCTION_STEPS = 5_000    # 10 ps
MAX_PRODUCTION_STEPS = 50_000   # 100 ps
TRAJECTORY_INTERVAL = 1_000     # 2 ps
ION_CENTER_PHOSPHORUS_COUNT = 32

ROOT = base.ROOT
OUT = base.OUT
WORK = base.WORK
PMEMD = base.PMEMD
PMEMD_CUDA = base.PMEMD_CUDA
TLEAP = base.TLEAP


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _atom_name_alias(name: str) -> str:
    """Normalize the CHARMM phosphate spelling to Amber/PDB spelling."""

    return {"O1P": "OP1", "O2P": "OP2", "C5M": "C7"}.get(
        name.strip(), name.strip()
    )


def seed_from_namd_reseed(
    rendered: str, chain_order: list[str]
) -> tuple[str, dict]:
    """Replace raw CAD coordinates with the archived relaxed NAMD DNA coordinates."""

    seed_pdb = ROOT / "namd_seed.pdb"
    seed_coor = ROOT / "namd_seed.coor"
    if not seed_pdb.is_file() or not seed_coor.is_file():
        raise RuntimeError("archived NAMD seed PDB/binCoordinates were not staged")
    pdb_records = [
        line
        for line in seed_pdb.read_text(errors="replace").splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]
    with seed_coor.open("rb") as handle:
        atom_count = struct.unpack("<i", handle.read(4))[0]
        coordinates = np.fromfile(handle, dtype="<f8", count=atom_count * 3).reshape(
            atom_count, 3
        )
    if len(pdb_records) != atom_count or not np.all(np.isfinite(coordinates)):
        raise RuntimeError(
            f"NAMD seed topology/coordinate mismatch: PDB={len(pdb_records)}, "
            f"binary={atom_count}, finite={np.all(np.isfinite(coordinates))}"
        )
    allowed = set(chain_order)
    seed = {}
    for line, xyz in zip(pdb_records, coordinates, strict=True):
        chain = line[21]
        residue_name = line[17:20].strip()
        if chain not in allowed or residue_name not in {"ADE", "CYT", "GUA", "THY"}:
            continue
        key = (chain, int(line[22:26]), _atom_name_alias(line[12:16]))
        if key in seed:
            raise RuntimeError(f"duplicate DNA atom in NAMD seed: {key}")
        seed[key] = xyz

    replaced = []
    mapped = 0
    displacement = []
    for line in rendered.splitlines():
        if not line.startswith("ATOM"):
            replaced.append(line)
            continue
        key = (line[21], int(line[22:26]), _atom_name_alias(line[12:16]))
        xyz = seed.get(key)
        if xyz is None:
            raise RuntimeError(f"Amber DNA atom is absent from NAMD relaxed seed: {key}")
        raw = np.asarray(
            [float(line[30:38]), float(line[38:46]), float(line[46:54])]
        )
        displacement.append(float(np.linalg.norm(xyz - raw)))
        replaced.append(
            line[:30]
            + f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}"
            + line[54:]
        )
        mapped += 1
    return "\n".join(replaced) + "\n", {
        "source_pdb": seed_pdb.name,
        "source_coordinates": seed_coor.name,
        "source_atoms": atom_count,
        "mapped_heavy_atoms": mapped,
        "raw_to_seed_rms_displacement_angstrom": float(
            np.sqrt(np.mean(np.square(displacement)))
        ),
        "raw_to_seed_max_displacement_angstrom": max(displacement),
    }


def make_origami_pdb() -> tuple[str, np.ndarray, np.ndarray, dict]:
    design = Design.from_json((ROOT / "input.nadoc").read_text())
    model = build_atomistic_model(design)
    rendered = export_pdb(
        design,
        box_margin_nm=0.0,
        model=model,
        viewer_terminals=True,
    )
    raw_lines = rendered.splitlines()
    raw_chain_order = []
    for line in raw_lines:
        if line.startswith("ATOM") and line[21] not in raw_chain_order:
            raw_chain_order.append(line[21])
    rendered, seed_metadata = seed_from_namd_reseed(rendered, raw_chain_order)
    lines = rendered.splitlines()
    pdb_lines = [line for line in lines if line.startswith(("ATOM", "TER"))]
    atom_lines = [line for line in pdb_lines if line.startswith("ATOM")]
    if not atom_lines:
        raise RuntimeError("NADOC PDB export contained no DNA atoms")

    # The viewer-terminal export is also the Amber-safe export: one sorted block per
    # real strand, a TER after each, and P/OP1/OP2 omitted only at true 5' termini.
    chain_order: list[str] = []
    residue_keys: list[tuple[str, int]] = []
    seen_residues: set[tuple[str, int]] = set()
    first_atom_names: dict[str, set[str]] = {}
    for line in atom_lines:
        chain = line[21]
        resid = int(line[22:26])
        key = (chain, resid)
        if chain not in chain_order:
            chain_order.append(chain)
        if key not in seen_residues:
            residue_keys.append(key)
            seen_residues.add(key)
        if resid == min(r for c, r in seen_residues if c == chain):
            first_atom_names.setdefault(chain, set()).add(line[12:16].strip())

    ter_chains = [line[21] for line in pdb_lines if line.startswith("TER")]
    if ter_chains != chain_order:
        raise RuntimeError(
            f"PDB did not contain exactly one ordered TER per strand: "
            f"chains={chain_order}, TER={ter_chains}"
        )
    for chain, names in first_atom_names.items():
        if names.intersection({"P", "OP1", "OP2"}):
            raise RuntimeError(f"5' terminal phosphate remains on chain {chain}")

    residue_index = {key: index for index, key in enumerate(residue_keys)}
    c1_by_site: dict[tuple[str, int, str, int], tuple[str, int, str]] = {}
    for atom in model.atoms:
        if (
            atom.name != "C1'"
            or atom.crossover_id is not None
            or atom.extension_id is not None
        ):
            continue
        direction = str(getattr(atom.direction, "value", atom.direction))
        site = (atom.helix_id, int(atom.bp_index), direction, int(atom.copy_k or 0))
        c1_by_site[site] = (_chain_char(atom.chain_id), int(atom.seq_num), atom.residue)

    pairs = []
    for (helix, bp, direction, copy_k), first in c1_by_site.items():
        if direction != "FORWARD":
            continue
        second = c1_by_site.get((helix, bp, "REVERSE", copy_k))
        if second is None:
            continue
        key_a, key_b = first[:2], second[:2]
        if key_a not in residue_index or key_b not in residue_index:
            raise RuntimeError(f"intended pair missing from exported PDB: {first}/{second}")
        pairs.append(
            {
                "residue_a": residue_index[key_a],
                "residue_b": residue_index[key_b],
                "base_a": first[2],
                "base_b": second[2],
                "helix": helix,
                "bp": bp,
            }
        )
    pairs.sort(key=lambda row: (row["helix"], row["bp"]))

    coordinates = np.asarray(
        [
            [float(line[30:38]), float(line[38:46]), float(line[46:54])]
            for line in atom_lines
        ],
        dtype=float,
    )
    phosphorus = np.asarray(
        [
            xyz
            for line, xyz in zip(atom_lines, coordinates, strict=True)
            if line[12:16].strip() == "P"
        ]
    )
    center = phosphorus.mean(axis=0)
    maximum_radius = float(np.linalg.norm(coordinates - center, axis=1).max())
    radius = float(math.ceil(maximum_radius + SPHERE_PADDING_ANGSTROM))
    metadata = {
        "dna_residues": len(residue_keys),
        "strand_count": len(chain_order),
        "chain_order": chain_order,
        "chain_lengths": {
            chain: sum(1 for c, _ in residue_keys if c == chain)
            for chain in chain_order
        },
        "intended_base_pairs": pairs,
        "intended_pair_count": len(pairs),
        "designed_unpaired_residues": len(residue_keys) - 2 * len(pairs),
        "heavy_atoms": len(atom_lines),
        "phosphorus_atoms": len(phosphorus),
        "phosphorus_center_angstrom": center.tolist(),
        "maximum_solute_radius_angstrom": maximum_radius,
        "sphere_padding_angstrom": SPHERE_PADDING_ANGSTROM,
        "sphere_radius_angstrom": radius,
        "bounding_box_span_angstrom": np.ptp(coordinates, axis=0).tolist(),
        "coordinate_seed": seed_metadata,
    }
    if metadata["strand_count"] != 9 or metadata["dna_residues"] != 656:
        raise RuntimeError(f"unexpected 6HB design dimensions: {metadata}")
    if len(phosphorus) != metadata["dna_residues"] - metadata["strand_count"]:
        raise RuntimeError(f"terminal phosphorus count is inconsistent: {metadata}")
    if len(pairs) != 252:
        raise RuntimeError(f"expected 252 designed pairs, found {len(pairs)}")

    pdb = "\n".join(pdb_lines) + "\nEND\n"
    (WORK / "dna.pdb").write_text(pdb)
    _write_json(WORK / "origami_map.json", metadata)
    return pdb, coordinates, phosphorus, metadata


def build_gbion_topology(
    n_na: int,
    n_cl: int,
    config: GBIONNaClConfig,
    metadata: dict,
) -> tuple[object, dict]:
    (WORK / "tleap_gbion.in").write_text(
        base.tleap_script("gbion_input.pdb", "gbion.parm7", "gbion.rst7")
    )
    base.run_logged([str(TLEAP), "-f", "tleap_gbion.in"], "tleap-gbion.log")
    parm = pmd.load_file(str(WORK / "gbion.parm7"), xyz=str(WORK / "gbion.rst7"))
    chloride = [atom for atom in parm.atoms if base.atom_is_cl(atom)]
    for atom in chloride:
        atom.solvent_radius = 1.4
    parm.box = None
    parm.save(str(WORK / "gbion.parm7"), overwrite=True)
    parm = pmd.load_file(str(WORK / "gbion.parm7"), xyz=str(WORK / "gbion.rst7"))
    summary = base.topology_summary(parm)

    expected_residues = metadata["dna_residues"] + n_na + n_cl
    if len(parm.residues) != expected_residues:
        raise RuntimeError(
            f"LEaP residue count changed: {len(parm.residues)} != {expected_residues}"
        )
    charge = int(round(summary["net_charge_e"]))
    if abs(summary["net_charge_e"] - charge) > 1.0e-5 or charge != 0:
        raise RuntimeError(f"GBION topology is not neutral: {summary}")
    if summary["sodium"] != n_na or summary["chloride"] != n_cl:
        raise RuntimeError(f"GBION ion count mismatch: {summary}")
    if summary["chloride_gb_radii_angstrom"] != [1.4]:
        raise RuntimeError(f"chloride GB radius was not changed to 1.4 A: {summary}")

    chain_lengths = list(metadata["chain_lengths"].values())
    boundaries = np.cumsum([0] + chain_lengths)
    residue_chain = {}
    for chain_index, (start, stop) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        for residue_index in range(int(start), int(stop)):
            residue_chain[residue_index] = chain_index
    interstrand = []
    for bond in parm.bonds:
        a, b = bond.atom1.residue.idx, bond.atom2.residue.idx
        if a < metadata["dna_residues"] and b < metadata["dna_residues"]:
            if residue_chain[a] != residue_chain[b]:
                interstrand.append((bond.atom1.idx + 1, bond.atom2.idx + 1))
    if interstrand:
        raise RuntimeError(f"LEaP created inter-strand covalent bonds: {interstrand[:20]}")

    bond_keys = {
        tuple(sorted((bond.atom1.idx, bond.atom2.idx))) for bond in parm.bonds
    }
    missing_backbone = []
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        for residue_index in range(int(start), int(stop) - 1):
            o3 = base.residue_atom(parm.residues[residue_index], "O3'")
            phosphorus = base.residue_atom(parm.residues[residue_index + 1], "P")
            if tuple(sorted((o3, phosphorus))) not in bond_keys:
                missing_backbone.append((residue_index, residue_index + 1))
    if missing_backbone:
        raise RuntimeError(f"missing consecutive O3'-P bonds: {missing_backbone[:20]}")

    phosphorus = [atom.idx + 1 for atom in parm.atoms if atom.name.strip() == "P"]
    ions = [
        atom.idx + 1
        for atom in parm.atoms
        if base.atom_is_na(atom) or base.atom_is_cl(atom)
    ]
    initial_xyz = np.asarray(parm.coordinates, dtype=float)
    initial_bonds = np.asarray(
        [
            np.linalg.norm(initial_xyz[bond.atom1.idx] - initial_xyz[bond.atom2.idx])
            for bond in parm.bonds
        ]
    )
    abnormal_initial_bonds = int(
        np.count_nonzero((initial_bonds < 0.8) | (initial_bonds > 2.0))
    )
    if abnormal_initial_bonds:
        raise RuntimeError(
            f"relaxed NAMD seed still produced {abnormal_initial_bonds} bonds outside 0.8-2.0 A"
        )

    # Repeating all 647 phosphorus atoms in each of ~1,650 NMR restraints creates
    # roughly one million group operations per step.  A 32-bin stratified set follows
    # the bundle center to sub-angstrom precision while reducing that work ~20-fold.
    p_zero = np.asarray(phosphorus, dtype=int) - 1
    p_xyz = initial_xyz[p_zero]
    centered = p_xyz - p_xyz.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    order = np.argsort(centered @ vt[0])
    selected = []
    groups = np.array_split(order, ION_CENTER_PHOSPHORUS_COUNT)
    for group in groups:
        group_center = p_xyz[group].mean(axis=0)
        selected.append(int(group[np.argmin(np.linalg.norm(p_xyz[group] - group_center, axis=1))]))
    # Keep one representative per axial bin, but swap representatives to make their
    # unweighted coordinate average reproduce the all-phosphorus center.  Two passes
    # converged from 3.66 A to 0.055 A on the 6HB seed.
    all_p_center = p_xyz.mean(axis=0)
    for _ in range(20):
        changed = 0
        for group_index, group in enumerate(groups):
            other_sum = p_xyz[selected].sum(axis=0) - p_xyz[selected[group_index]]
            errors = np.linalg.norm(
                (other_sum + p_xyz[group]) / len(selected) - all_p_center,
                axis=1,
            )
            replacement = int(group[np.argmin(errors)])
            if replacement != selected[group_index]:
                selected[group_index] = replacement
                changed += 1
        if not changed:
            break
    selected_phosphorus = [phosphorus[index] for index in selected]
    center_error = float(
        np.linalg.norm(p_xyz[selected].mean(axis=0) - all_p_center)
    )
    (WORK / "disang_NaCl.txt").write_text(
        render_ion_restraints(selected_phosphorus, ions, config)
    )
    summary.update(
        {
            "dna_residues": metadata["dna_residues"],
            "strand_count": metadata["strand_count"],
            "phosphorus": len(phosphorus),
            "ions": len(ions),
            "interstrand_covalent_bonds": interstrand,
            "missing_consecutive_backbone_bonds": missing_backbone,
            "expected_consecutive_backbone_bonds": metadata["dna_residues"]
            - metadata["strand_count"],
            "initial_bond_lengths_angstrom": {
                "minimum": float(initial_bonds.min()),
                "maximum": float(initial_bonds.max()),
                "outside_0_8_to_2_0": abnormal_initial_bonds,
            },
            "ion_center_phosphorus": selected_phosphorus,
            "ion_center_phosphorus_count": len(selected_phosphorus),
            "ion_center_error_vs_all_phosphorus_angstrom": center_error,
            "parm7_sha256": base.sha256(WORK / "gbion.parm7"),
        }
    )
    return parm, summary


def _write_gb_inputs(config: GBIONNaClConfig, dna_residues: int) -> None:
    common = base.GBION_NACL_NAMELIST + "  nmropt=1,\n"
    footer = base.restraint_footer()
    mask = f"':1-{dna_residues}'"
    (WORK / "gb_parity.mdin").write_text(
        "6HB GBION CPU/GPU one-cycle parity\n &cntrl\n"
        " imin=1, maxcyc=1, ncyc=1, ntpr=1, ntb=0, cut=1000.0, ntr=0,\n"
        + common + " /\n" + footer
    )
    (WORK / "gb_min.mdin").write_text(
        "6HB GBION restrained minimization\n &cntrl\n"
        f" imin=1, maxcyc={MINIMIZATION_CYCLES}, ncyc={MINIMIZATION_CYCLES // 2}, ntpr=100,\n"
        f" ntb=0, cut=1000.0, ntr=1, restraint_wt=5.0, restraintmask={mask},\n"
        + common + " /\n" + footer
    )
    (WORK / "gb_heat.mdin").write_text(
        "6HB GBION restrained heating\n &cntrl\n"
        f" imin=0, irest=0, ntx=1, nstlim={HEATING_STEPS}, dt=0.002,\n"
        " tempi=10.0, temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        " ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0,\n"
        f" ntpr=1000, ntwx=0, ntwr={HEATING_STEPS}, ntxo=2, ntr=1,\n"
        f" restraint_wt=5.0, restraintmask={mask},\n"
        + common + " /\n"
        f" &wt type='TEMP0', istep1=0, istep2={HEATING_STEPS}, value1=10.0, value2=300.0 /\n"
        + footer
    )
    (WORK / "gb_equil.mdin").write_text(
        "6HB GBION restrained equilibration\n &cntrl\n"
        f" imin=0, irest=1, ntx=5, nstlim={EQUILIBRATION_STEPS}, dt=0.002,\n"
        " temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        " ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0,\n"
        f" ntpr=1000, ntwx=0, ntwr={EQUILIBRATION_STEPS}, ntxo=2, ntr=1,\n"
        f" restraint_wt=5.0, restraintmask={mask},\n"
        + common + " /\n" + footer
    )
    (WORK / "gb_benchmark.mdin").write_text(
        "6HB GBION clean GPU benchmark\n &cntrl\n"
        f" imin=0, irest=1, ntx=5, nstlim={BENCHMARK_STEPS}, dt=0.002,\n"
        " temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        " ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0, ntr=0,\n"
        f" ntpr={BENCHMARK_STEPS}, ntwx=0, ntwr={BENCHMARK_STEPS}, ntxo=2,\n"
        + common + " /\n" + footer
    )


def run_gbion(config: GBIONNaClConfig, dna_residues: int) -> tuple[dict, int]:
    _write_gb_inputs(config, dna_residues)
    base.emit_status("gbion_cpu_gpu_parity")
    cpu = base.amber_run(PMEMD, "gb_parity.mdin", "gbion.rst7", "parity_cpu")
    gpu = base.amber_run(PMEMD_CUDA, "gb_parity.mdin", "gbion.rst7", "parity_gpu")
    if not cpu["energies_kcal_mol"] or not gpu["energies_kcal_mol"]:
        raise RuntimeError("could not parse CPU/GPU parity energies")
    cpu_energy = cpu["energies_kcal_mol"][-1]
    gpu_energy = gpu["energies_kcal_mol"][-1]
    relative = abs(cpu_energy - gpu_energy) / max(1.0, abs(cpu_energy))
    parity = {
        "cpu_energy_kcal_mol": cpu_energy,
        "gpu_energy_kcal_mol": gpu_energy,
        "absolute_delta_kcal_mol": abs(cpu_energy - gpu_energy),
        "relative_delta": relative,
        "tolerance_relative": 1.0e-4,
        "passed": relative < 1.0e-4,
        "cuda_banner": gpu["cuda_banner"],
        "gbion_v3_echo": gpu["gbion_v3_echo"],
    }
    if not parity["passed"] or not np.isfinite([cpu_energy, gpu_energy]).all():
        raise RuntimeError(f"6HB CPU/GPU parity gate failed before dynamics: {parity}")

    def require_stage(stage: str) -> None:
        text = (WORK / f"{stage}.mdout").read_text(errors="replace")
        overflow = bool(
            re.search(
                r"(?:TEMP\(K\)|Etot|EKtot|EPtot|ANGLE|VDWAALS|EELEC|EGB|RESTRAINT)\s*=\s*\*{3,}",
                text,
            )
        )
        energies = base.parse_energies(text)
        if overflow or not energies or not np.all(np.isfinite(energies)):
            raise RuntimeError(
                f"{stage} numerical gate failed: overflow={overflow}, "
                f"parsed_energy_samples={len(energies)}"
            )

    base.emit_status("gbion_minimize")
    minimum = base.amber_run(
        PMEMD_CUDA, "gb_min.mdin", "gbion.rst7", "gb_min",
        reference_rst="gbion.rst7",
    )
    require_stage("gb_min")
    base.emit_status("gbion_heat")
    heat = base.amber_run(
        PMEMD_CUDA, "gb_heat.mdin", "gb_min.rst7", "gb_heat",
        reference_rst="gbion.rst7",
    )
    require_stage("gb_heat")
    base.emit_status("gbion_equilibrate")
    equil = base.amber_run(
        PMEMD_CUDA, "gb_equil.mdin", "gb_heat.rst7", "gb_equil",
        reference_rst="gbion.rst7",
    )
    require_stage("gb_equil")
    base.emit_status("gbion_benchmark")
    benchmark = base.amber_run(
        PMEMD_CUDA, "gb_benchmark.mdin", "gb_equil.rst7", "gb_benchmark"
    )
    require_stage("gb_benchmark")
    benchmark["wall_ns_per_day"] = (
        BENCHMARK_STEPS * config.timestep_ps / 1000.0
    ) * 86_400.0 / benchmark["wall_seconds"]

    rate = benchmark["wall_ns_per_day"]
    adaptive_steps = int(
        rate * TARGET_PRODUCTION_WALL_S / 86_400.0
        * 1000.0 / config.timestep_ps
    )
    production_steps = max(
        MIN_PRODUCTION_STEPS,
        min(MAX_PRODUCTION_STEPS, adaptive_steps),
    )
    (WORK / "gb_production.mdin").write_text(
        "6HB adaptive unrestrained-DNA production\n &cntrl\n"
        f" imin=0, irest=1, ntx=5, nstlim={production_steps}, dt=0.002,\n"
        " temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        " ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0, ntr=0,\n"
        f" ntpr={TRAJECTORY_INTERVAL}, ntwx={TRAJECTORY_INTERVAL}, "
        f"ntwr={production_steps}, ioutfm=1, ntxo=2,\n"
        + base.GBION_NACL_NAMELIST + "  nmropt=1,\n /\n"
        + base.restraint_footer()
    )
    base.emit_status(
        "gbion_production",
        benchmark_ns_per_day=rate,
        adaptive_steps=production_steps,
        planned_ns=production_steps * config.timestep_ps / 1000.0,
    )
    production = base.amber_run(
        PMEMD_CUDA, "gb_production.mdin", "gb_benchmark.rst7", "gb_production",
        trajectory=True,
    )
    return {
        "parity": parity,
        "minimum": minimum,
        "heat": heat,
        "equilibration": equil,
        "benchmark": benchmark,
        "production": production,
    }, production_steps


def _wc_atom_pairs(res_a, res_b) -> list[tuple[int, int]]:
    bases = {base.normalize_base(res_a.name): res_a, base.normalize_base(res_b.name): res_b}
    if set(bases) == {"DA", "DT"}:
        aa, tt = bases["DA"], bases["DT"]
        names = ((aa, "N6", tt, "O4"), (aa, "N1", tt, "N3"))
    elif set(bases) == {"DG", "DC"}:
        gg, cc = bases["DG"], bases["DC"]
        names = (
            (gg, "O6", cc, "N4"),
            (gg, "N1", cc, "N3"),
            (gg, "N2", cc, "O2"),
        )
    else:
        raise RuntimeError(f"non-Watson-Crick intended pair {res_a.name}/{res_b.name}")
    return [(base.residue_atom(a, an), base.residue_atom(b, bn)) for a, an, b, bn in names]


def _shape_metrics(xyz: np.ndarray, c1_pairs: list[tuple[int, int]]) -> dict:
    centers = np.asarray([(xyz[a] + xyz[b]) / 2.0 for a, b in c1_pairs])
    centered = centers - centers.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    axis = vt[0]
    axial = centered @ axis
    radial_vectors = centered - np.outer(axial, axis)
    radial = np.linalg.norm(radial_vectors, axis=1)
    return {
        "axial_p95_p05_length_nm": float(
            (np.percentile(axial, 95) - np.percentile(axial, 5)) / 10.0
        ),
        "radial_rms_nm": float(np.sqrt(np.mean(radial * radial)) / 10.0),
        "radial_p90_nm": float(np.percentile(radial, 90) / 10.0),
    }


def analyze_gbion(
    parm,
    metadata: dict,
    production_steps: int,
    config: GBIONNaClConfig,
    ion_center_phosphorus_one_based: list[int] | None = None,
) -> dict:
    with netCDF4.Dataset(WORK / "gb_production.nc") as dataset:
        frames = np.asarray(dataset.variables["coordinates"][:], dtype=float)
    reference_parm = pmd.load_file(
        str(WORK / "gbion.parm7"), xyz=str(WORK / "gb_benchmark.rst7")
    )
    reference = np.asarray(reference_parm.coordinates, dtype=float)
    dna_residues = metadata["dna_residues"]
    dna = parm.residues[:dna_residues]
    c1_pairs = []
    wc_pairs = []
    for row in metadata["intended_base_pairs"]:
        a = dna[row["residue_a"]]
        b = dna[row["residue_b"]]
        c1_pairs.append((base.residue_atom(a, "C1'"), base.residue_atom(b, "C1'")))
        wc_pairs.append(_wc_atom_pairs(a, b))
    c1_indices = sorted({index for pair in c1_pairs for index in pair})
    phosphorus = [atom.idx for atom in parm.atoms if atom.name.strip() == "P"]
    ion_center_phosphorus = (
        [index - 1 for index in ion_center_phosphorus_one_based]
        if ion_center_phosphorus_one_based
        else phosphorus
    )
    ions = [atom.idx for atom in parm.atoms if base.atom_is_na(atom) or base.atom_is_cl(atom)]
    reference_shape = _shape_metrics(reference, c1_pairs)

    series = []
    for frame_index, xyz in enumerate(frames):
        c1_distance = np.asarray([np.linalg.norm(xyz[a] - xyz[b]) for a, b in c1_pairs])
        wc_per_pair = np.asarray(
            [max(np.linalg.norm(xyz[a] - xyz[b]) for a, b in pair) for pair in wc_pairs]
        )
        all_p_center = xyz[phosphorus].mean(axis=0)
        center = xyz[ion_center_phosphorus].mean(axis=0)
        ion_radius = np.linalg.norm(xyz[ions] - center, axis=1)
        shape = _shape_metrics(xyz, c1_pairs)
        series.append(
            {
                "time_ps": (frame_index + 1) * TRAJECTORY_INTERVAL * config.timestep_ps,
                "c1_paired_fraction_12A": float(np.mean(c1_distance <= 12.0)),
                "c1_mean_nm": float(c1_distance.mean() / 10.0),
                "c1_p90_nm": float(np.percentile(c1_distance, 90) / 10.0),
                "wc_all_hbonds_below_3_6A_fraction": float(np.mean(wc_per_pair <= 3.6)),
                "wc_max_hbond_mean_nm": float(wc_per_pair.mean() / 10.0),
                "c1_aligned_rmsd_nm": base.kabsch_rmsd_angstrom(
                    reference[c1_indices], xyz[c1_indices]
                ) / 10.0,
                "maximum_ion_radius_angstrom": float(ion_radius.max()),
                "ion_center_offset_vs_all_phosphorus_angstrom": float(
                    np.linalg.norm(center - all_p_center)
                ),
                **shape,
            }
        )
    final_xyz = frames[-1]
    bond_lengths = np.asarray(
        [
            np.linalg.norm(final_xyz[bond.atom1.idx] - final_xyz[bond.atom2.idx])
            for bond in parm.bonds
        ]
    )
    equilibrium = np.asarray(
        [float(bond.type.req) if bond.type is not None else np.nan for bond in parm.bonds]
    )
    energies = base.parse_energies((WORK / "gb_production.mdout").read_text(errors="replace"))
    final = series[-1]
    return {
        "sampled_frames": len(frames),
        "sampled_ns": production_steps * config.timestep_ps / 1000.0,
        "reference_shape": reference_shape,
        "mean_c1_paired_fraction_12A": float(np.mean([x["c1_paired_fraction_12A"] for x in series])),
        "mean_wc_absolute_fraction": float(np.mean([x["wc_all_hbonds_below_3_6A_fraction"] for x in series])),
        "maximum_sampled_ion_radius_angstrom": float(max(x["maximum_ion_radius_angstrom"] for x in series)),
        "final": final,
        "bond_lengths_nm": {
            "count": len(bond_lengths),
            "minimum": float(bond_lengths.min() / 10.0),
            "maximum": float(bond_lengths.max() / 10.0),
            "outside_0.08_to_0.20_nm": int(np.count_nonzero((bond_lengths < 0.8) | (bond_lengths > 2.0))),
            "rms_deviation_from_equilibrium_nm": float(np.sqrt(np.nanmean((bond_lengths - equilibrium) ** 2)) / 10.0),
            "maximum_deviation_from_equilibrium_nm": float(np.nanmax(np.abs(bond_lengths - equilibrium)) / 10.0),
        },
        "finite_energy": bool(energies and np.all(np.isfinite(energies))),
        "energy_samples_kcal_mol": energies,
        "series": series,
    }


def main() -> None:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        base.emit_status("worker_start")
        if not PMEMD.is_file() or not PMEMD_CUDA.is_file() or not TLEAP.is_file():
            raise RuntimeError("required Amber executables are missing")
        pdb, solute_xyz, phosphorus_xyz, metadata = make_origami_pdb()
        config = GBIONNaClConfig(
            sphere_radius_angstrom=metadata["sphere_radius_angstrom"]
        )
        # Reuse only the generic charge and ion-placement helpers, after replacing
        # their module-level configuration with this geometry-derived sphere.
        base.CONFIG = config
        solute_charge = base.derive_solute_charge()
        n_na, n_cl = config.ion_counts(solute_charge)
        placement = base.place_ions(
            pdb, solute_xyz, phosphorus_xyz, n_na, n_cl
        )
        base.emit_status(
            "gbion_parameterize",
            sodium=n_na,
            chloride=n_cl,
            radius_angstrom=config.sphere_radius_angstrom,
        )
        parm, topology = build_gbion_topology(n_na, n_cl, config, metadata)
        build = {
            "pmemd_cuda": str(PMEMD_CUDA),
            "pmemd_cuda_sha256": base.sha256(PMEMD_CUDA),
            "tleap": str(TLEAP),
            "cuda_build_scope": os.environ.get(
                "NADOC_CUDA_BUILD_SCOPE", "portable-default"
            ),
            "nvidia_smi": subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total",
                    "--format=csv,noheader",
                ],
                text=True,
            ).strip(),
        }
        gbion, production_steps = run_gbion(config, metadata["dna_residues"])
        base.emit_status("gbion_analyze")
        analysis = analyze_gbion(
            parm,
            metadata,
            production_steps,
            config,
            topology["ion_center_phosphorus"],
        )
        namd_reference = json.loads((ROOT / "namd_reference.json").read_text())
        final = analysis["final"]
        shape_ref = analysis["reference_shape"]
        gates = {
            "topology_9_strands_656_nt": topology["strand_count"] == 9 and topology["dna_residues"] == 656,
            "all_647_backbone_links_present": not topology["missing_consecutive_backbone_bonds"],
            "no_interstrand_covalent_bonds": not topology["interstrand_covalent_bonds"],
            "finite_energy": analysis["finite_energy"],
            "all_bonds_0_08_to_0_20nm": analysis["bond_lengths_nm"]["outside_0.08_to_0.20_nm"] == 0,
            "cpu_gpu_parity": gbion["parity"]["passed"],
            "cuda_banner": gbion["benchmark"]["cuda_banner"],
            "gbion_v3_echo": gbion["benchmark"]["gbion_v3_echo"],
            "ion_wall_operational": analysis["maximum_sampled_ion_radius_angstrom"] <= config.sphere_radius_angstrom + 0.5,
            "final_c1_paired_fraction_at_least_0_85": final["c1_paired_fraction_12A"] >= 0.85,
            "final_c1_rmsd_at_most_0_5nm": final["c1_aligned_rmsd_nm"] <= 0.5,
            "bundle_length_change_at_most_10pct": abs(final["axial_p95_p05_length_nm"] / shape_ref["axial_p95_p05_length_nm"] - 1.0) <= 0.10,
            "bundle_radial_rms_change_at_most_15pct": abs(final["radial_rms_nm"] / shape_ref["radial_rms_nm"] - 1.0) <= 0.15,
            "measured_throughput": gbion["benchmark"]["wall_ns_per_day"] > 0,
        }
        result = {
            "schema_version": 1,
            "model": "Amber26 pmemd.cuda OL15 + igb=8/GBION-v3 + explicit 150mM NaCl",
            "build": build,
            "origami": metadata,
            "configuration": {
                "sphere_radius_angstrom": config.sphere_radius_angstrom,
                "sphere_volume_angstrom3": config.solvent_volume_angstrom3,
                "concentration_molar": config.concentration_molar,
                "production_steps": production_steps,
                "production_ns": production_steps * config.timestep_ps / 1000.0,
            },
            "solute_charge_e": solute_charge,
            "ion_counts": {"sodium": n_na, "chloride": n_cl},
            "placement": placement,
            "topology": topology,
            "gbion": gbion,
            "analysis": analysis,
            "namd_reference": namd_reference,
            "throughput_ratio_vs_namd_3080ti": gbion["benchmark"]["wall_ns_per_day"] / namd_reference["throughput_ns_per_day"],
            "gates": gates,
            "basic_validation_passed": all(gates.values()),
            "wall_seconds": time.time() - started,
        }
        _write_json(OUT / "result.json", result)
        for artifact in (
            "dna.pdb", "origami_map.json", "gbion.parm7", "gbion.rst7",
            "disang_NaCl.txt", "gb_benchmark.rst7", "gb_production.rst7",
            "gb_production.nc", "gb_production.mdout",
        ):
            source = WORK / artifact
            if source.is_file():
                target = OUT / artifact
                if source.resolve() != target.resolve():
                    target.write_bytes(source.read_bytes())
        base.emit_status(
            "complete",
            passed=result["basic_validation_passed"],
            ns_per_day=gbion["benchmark"]["wall_ns_per_day"],
            sampled_ns=analysis["sampled_ns"],
        )
    except Exception as exc:
        _write_json(
            OUT / "failure.json",
            {"error": str(exc), "type": type(exc).__name__, "wall_seconds": time.time() - started},
        )
        base.emit_status("failed", error=str(exc), error_type=type(exc).__name__)
        raise


if __name__ == "__main__":
    main()
