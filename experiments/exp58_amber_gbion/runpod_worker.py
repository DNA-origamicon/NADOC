#!/usr/bin/env python3
"""Pod-side native Amber26 OL15/GBION-v3 validation.

This runs only on the rented GPU.  It builds a deterministic 21-bp test duplex,
checks CPU/GPU GBION energy parity, samples 1 ns with pmemd.cuda, and measures a
same-GPU explicit-TIP3P reference.  The output is deliberately self-auditing so
that a structural pass cannot be confused with a CUDA or model-selection pass.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

import netCDF4
import numpy as np
import parmed as pmd

from experiments.exp58_amber_gbion.model import (
    GBION_NACL_NAMELIST,
    GBIONNaClConfig,
    render_ion_restraints,
)


ROOT = Path(os.environ.get("NADOC_REMOTE_ROOT", "/root/nadoc-amber-gbion"))
OUT = Path(os.environ.get("NADOC_OUTPUT_DIR", ROOT / "output"))
WORK = ROOT / "work"
AMBERHOME = Path(os.environ.get("AMBERHOME", "/opt/amber26"))
PMEMD = AMBERHOME / "bin" / "pmemd"
PMEMD_CUDA = AMBERHOME / "bin" / "pmemd.cuda"
TLEAP = Path(os.environ.get("TLEAP", "/opt/ambertools26/bin/tleap"))
CONFIG = GBIONNaClConfig()
SEQUENCE = "CGCGAATTCGCGATCGATCGA"
DNA_RESIDUES = 2 * len(SEQUENCE)
GB_PRODUCTION_STEPS = 500_000
BENCHMARK_STEPS = 100_000
TRAJECTORY_INTERVAL = 5_000


def emit_status(phase: str, **fields) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"phase": phase, "at": time.time(), **fields}
    tmp = OUT / "status.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(OUT / "status.json")
    print(json.dumps(payload, sort_keys=True), flush=True)


def run_logged(command: list[str], log_name: str, *, cwd: Path = WORK) -> dict:
    """Run a command while streaming and preserving its combined output."""

    log_path = OUT / log_name
    started = time.perf_counter()
    with log_path.open("w") as handle:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            handle.write(line)
            handle.flush()
            print(line, end="", flush=True)
        rc = proc.wait()
    wall = time.perf_counter() - started
    if rc != 0:
        tail = log_path.read_text(errors="replace")[-5000:]
        raise RuntimeError(
            f"command failed with rc={rc}: {' '.join(command)}\n{tail}"
        )
    return {"command": command, "wall_seconds": wall, "log": log_name}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_duplex_pdb() -> tuple[str, np.ndarray, np.ndarray]:
    from backend.core.models import Design
    from backend.core.pdb_export import export_pdb

    design = Design.from_json((ROOT / "input.nadoc").read_text())
    rendered = export_pdb(design, box_margin_nm=0.0)
    rendered_lines = rendered.splitlines()
    raw_atoms = [line for line in rendered_lines if line.startswith("ATOM")]
    # NADOC's NAMD/CHARMM export retains a 5'-terminal phosphate (P/OP1/OP2)
    # on each strand.  The standard Amber OL15 5' residue is unphosphorylated;
    # remove those three atoms before LEaP assigns its *5 terminal templates.
    # Keep TER records: LEaP uses them to prevent a covalent join between strands.
    first_residue_by_chain: dict[str, tuple[str, str]] = {}
    for line in raw_atoms:
        chain = line[21:22]
        first_residue_by_chain.setdefault(chain, (line[22:26], line[26:27]))

    atom_lines = []
    pdb_lines = []
    for line in rendered_lines:
        if line.startswith("ATOM"):
            chain = line[21:22]
            residue_key = (line[22:26], line[26:27])
            atom_name = line[12:16].strip()
            if (
                residue_key == first_residue_by_chain[chain]
                and atom_name in {"P", "OP1", "OP2"}
            ):
                continue
            atom_lines.append(line)
            pdb_lines.append(line)
        elif line.startswith("TER"):
            pdb_lines.append(line)
    if not atom_lines:
        raise RuntimeError("NADOC PDB export contained no DNA atoms")
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
    if len(first_residue_by_chain) != 2 or len(phosphorus) != DNA_RESIDUES - 2:
        raise RuntimeError(
            "Amber terminal conversion did not produce a two-strand duplex with "
            f"{DNA_RESIDUES - 2} phosphates: chains={sorted(first_residue_by_chain)}, "
            f"phosphates={len(phosphorus)}"
        )
    pdb = "\n".join(pdb_lines) + "\nEND\n"
    (WORK / "dna.pdb").write_text(pdb)
    return pdb, coordinates, phosphorus


def random_point_in_sphere(rng: np.random.Generator, radius: float) -> np.ndarray:
    direction = rng.normal(size=3)
    direction /= np.linalg.norm(direction)
    return direction * radius * rng.random() ** (1.0 / 3.0)


def place_ions(
    pdb: str,
    solute_xyz: np.ndarray,
    phosphorus_xyz: np.ndarray,
    n_na: int,
    n_cl: int,
) -> dict:
    """Add well-separated ions uniformly within the GBION restraining sphere."""

    rng = np.random.default_rng(CONFIG.random_seed)
    center = phosphorus_xyz.mean(axis=0)
    ion_xyz: list[np.ndarray] = []
    max_start_radius = CONFIG.sphere_radius_angstrom - 1.0
    for _ in range(n_na + n_cl):
        for _attempt in range(200_000):
            candidate = center + random_point_in_sphere(rng, max_start_radius)
            if np.min(np.linalg.norm(solute_xyz - candidate, axis=1)) < 3.5:
                continue
            if ion_xyz and min(
                np.linalg.norm(existing - candidate) for existing in ion_xyz
            ) < 4.0:
                continue
            ion_xyz.append(candidate)
            break
        else:
            raise RuntimeError("could not place all GBION ions without a clash")

    base_lines = [
        line
        for line in pdb.splitlines()
        if line.startswith("ATOM") or line.startswith("TER")
    ]
    lines = list(base_lines)
    # TER records also carry serial numbers; start ions above both ATOM and TER
    # records so the combined PDB has no duplicate record identifiers.
    first_serial = max(int(line[6:11]) for line in base_lines) + 1
    for offset, xyz in enumerate(ion_xyz):
        sodium = offset < n_na
        name = "Na+" if sodium else "Cl-"
        element = "Na" if sodium else "Cl"
        serial = first_serial + offset
        residue = offset + 1
        lines.append(
            f"HETATM{serial:5d} {name:>4s} {name:>3s} I{residue:4d}    "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}"
            f"  1.00  0.00          {element:>2s}"
        )
    lines.append("END")
    (WORK / "gbion_input.pdb").write_text("\n".join(lines) + "\n")
    radii = np.linalg.norm(np.asarray(ion_xyz) - center, axis=1)
    return {
        "phosphorus_center_angstrom": center.tolist(),
        "minimum_ion_solute_distance_angstrom": float(
            min(np.min(np.linalg.norm(solute_xyz - xyz, axis=1)) for xyz in ion_xyz)
        ),
        "minimum_ion_ion_distance_angstrom": float(
            min(
                np.linalg.norm(ion_xyz[i] - ion_xyz[j])
                for i in range(len(ion_xyz))
                for j in range(i)
            )
        ),
        "maximum_initial_ion_radius_angstrom": float(radii.max()),
    }


def tleap_script(input_pdb: str, parm7: str, rst7: str) -> str:
    return f"""source leaprc.DNA.OL15
source leaprc.water.tip3p
loadAmberParams frcmod.ionsjc_tip3p
set default PBRadii mbondi3
mol = loadPdb {input_pdb}
check mol
saveAmberParm mol {parm7} {rst7}
quit
"""


def atom_is_na(atom) -> bool:
    return atom.atomic_number == 11 or atom.name.strip().upper() in {"NA", "NA+"}


def atom_is_cl(atom) -> bool:
    return atom.atomic_number == 17 or atom.name.strip().upper() in {"CL", "CL-"}


def topology_summary(parm) -> dict:
    sodium = [atom for atom in parm.atoms if atom_is_na(atom)]
    chloride = [atom for atom in parm.atoms if atom_is_cl(atom)]
    return {
        "atoms": len(parm.atoms),
        "residues": len(parm.residues),
        "net_charge_e": float(sum(atom.charge for atom in parm.atoms)),
        "sodium": len(sodium),
        "chloride": len(chloride),
        "chloride_gb_radii_angstrom": sorted(
            {round(float(atom.solvent_radius), 8) for atom in chloride}
        ),
    }


def derive_solute_charge() -> int:
    """Parameterize DNA alone so salt counts follow the actual OL15 topology."""

    (WORK / "tleap_dna.in").write_text(
        tleap_script("dna.pdb", "dna.parm7", "dna.rst7")
    )
    run_logged([str(TLEAP), "-f", "tleap_dna.in"], "tleap-dna.log")
    parm = pmd.load_file(str(WORK / "dna.parm7"), xyz=str(WORK / "dna.rst7"))
    charge = float(sum(atom.charge for atom in parm.atoms))
    rounded = int(round(charge))
    if abs(charge - rounded) > 1.0e-5:
        raise RuntimeError(f"OL15 DNA charge is unexpectedly nonintegral: {charge}")
    return rounded


def build_gbion_topology(n_na: int, n_cl: int) -> tuple[object, dict]:
    script = tleap_script("gbion_input.pdb", "gbion.parm7", "gbion.rst7")
    (WORK / "tleap_gbion.in").write_text(script)
    run_logged([str(TLEAP), "-f", "tleap_gbion.in"], "tleap-gbion.log")
    parm = pmd.load_file(str(WORK / "gbion.parm7"), xyz=str(WORK / "gbion.rst7"))
    chloride = [atom for atom in parm.atoms if atom_is_cl(atom)]
    for atom in chloride:
        atom.solvent_radius = 1.4
    parm.box = None
    parm.save(str(WORK / "gbion.parm7"), overwrite=True)
    parm = pmd.load_file(str(WORK / "gbion.parm7"), xyz=str(WORK / "gbion.rst7"))
    summary = topology_summary(parm)
    charge = int(round(summary["net_charge_e"]))
    if abs(summary["net_charge_e"] - charge) > 1.0e-5 or charge != 0:
        raise RuntimeError(f"GBION topology is not exactly neutral: {summary}")
    if summary["sodium"] != n_na or summary["chloride"] != n_cl:
        raise RuntimeError(f"GBION ion count mismatch: {summary}")
    if summary["chloride_gb_radii_angstrom"] != [1.4]:
        raise RuntimeError(f"chloride GB radius was not changed to 1.4 A: {summary}")
    strand_a = set(range(len(SEQUENCE)))
    strand_b = set(range(len(SEQUENCE), DNA_RESIDUES))
    interstrand_bonds = [
        (bond.atom1.idx + 1, bond.atom2.idx + 1)
        for bond in parm.bonds
        if (bond.atom1.residue.idx in strand_a and bond.atom2.residue.idx in strand_b)
        or (bond.atom1.residue.idx in strand_b and bond.atom2.residue.idx in strand_a)
    ]
    if interstrand_bonds:
        raise RuntimeError(
            f"LEaP created covalent bonds between duplex strands: {interstrand_bonds}"
        )
    phosphorus = [atom.idx + 1 for atom in parm.atoms if atom.name.strip() == "P"]
    ions = [atom.idx + 1 for atom in parm.atoms if atom_is_na(atom) or atom_is_cl(atom)]
    (WORK / "disang_NaCl.txt").write_text(
        render_ion_restraints(phosphorus, ions, CONFIG)
    )
    summary.update(
        {
            "phosphorus_atom_indices": phosphorus,
            "ion_atom_indices": ions,
            "interstrand_covalent_bonds": interstrand_bonds,
            "parm7_sha256": sha256(WORK / "gbion.parm7"),
        }
    )
    return parm, summary


def gbion_tail() -> str:
    return GBION_NACL_NAMELIST + "  nmropt=1,\n"


def restraint_footer() -> str:
    return """ &wt type='END' /
 DISANG=disang_NaCl.txt
 LISTIN=POUT
 LISTOUT=POUT
"""


def write_gb_inputs() -> None:
    common = gbion_tail()
    (WORK / "gb_parity.mdin").write_text(
        "GBION CPU/GPU one-cycle parity\n &cntrl\n"
        "  imin=1, maxcyc=1, ncyc=1, ntpr=1,\n"
        "  ntb=0, cut=1000.0, ntr=0,\n"
        + common
        + " /\n"
        + restraint_footer()
    )
    (WORK / "gb_min.mdin").write_text(
        "GBION restrained minimization\n &cntrl\n"
        "  imin=1, maxcyc=5000, ncyc=2500, ntpr=100,\n"
        "  ntb=0, cut=1000.0, ntr=1, restraint_wt=5.0,\n"
        f"  restraintmask=':1-{DNA_RESIDUES}',\n"
        + common
        + " /\n"
        + restraint_footer()
    )
    (WORK / "gb_heat.mdin").write_text(
        "GBION restrained 10 to 300 K heating\n &cntrl\n"
        "  imin=0, irest=0, ntx=1, nstlim=10000, dt=0.002,\n"
        "  tempi=10.0, temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        "  ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0,\n"
        "  ntpr=1000, ntwx=0, ntwr=10000, ntxo=2,\n"
        "  ntr=1, restraint_wt=5.0, "
        f"restraintmask=':1-{DNA_RESIDUES}',\n"
        + common
        + " /\n"
        " &wt type='TEMP0', istep1=0, istep2=10000, value1=10.0, value2=300.0 /\n"
        + restraint_footer()
    )
    (WORK / "gb_equil.mdin").write_text(
        "GBION restrained 300 K equilibration\n &cntrl\n"
        "  imin=0, irest=1, ntx=5, nstlim=40000, dt=0.002,\n"
        "  temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        "  ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0,\n"
        "  ntpr=4000, ntwx=0, ntwr=40000, ntxo=2,\n"
        "  ntr=1, restraint_wt=5.0, "
        f"restraintmask=':1-{DNA_RESIDUES}',\n"
        + common
        + " /\n"
        + restraint_footer()
    )
    (WORK / "gb_benchmark.mdin").write_text(
        "GBION clean GPU benchmark\n &cntrl\n"
        f"  imin=0, irest=1, ntx=5, nstlim={BENCHMARK_STEPS}, dt=0.002,\n"
        "  temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        "  ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0,\n"
        f"  ntpr={BENCHMARK_STEPS}, ntwx=0, ntwr={BENCHMARK_STEPS}, ntxo=2,\n"
        "  ntr=0,\n"
        + common
        + " /\n"
        + restraint_footer()
    )
    (WORK / "gb_production.mdin").write_text(
        "GBION 1 ns unrestrained-DNA production\n &cntrl\n"
        f"  imin=0, irest=1, ntx=5, nstlim={GB_PRODUCTION_STEPS}, dt=0.002,\n"
        "  temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        "  ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0,\n"
        f"  ntpr={TRAJECTORY_INTERVAL}, ntwx={TRAJECTORY_INTERVAL}, "
        f"ntwr={GB_PRODUCTION_STEPS}, ioutfm=1, ntxo=2,\n"
        "  ntr=0,\n"
        + common
        + " /\n"
        + restraint_footer()
    )


def amber_run(
    binary: Path,
    mdin: str,
    input_rst: str,
    prefix: str,
    *,
    reference_rst: str | None = None,
    trajectory: bool = False,
) -> dict:
    command = [
        str(binary),
        "-O",
        "-i",
        mdin,
        "-p",
        "gbion.parm7",
        "-c",
        input_rst,
        "-o",
        f"{prefix}.mdout",
        "-r",
        f"{prefix}.rst7",
        "-inf",
        f"{prefix}.mdinfo",
    ]
    if reference_rst:
        command.extend(["-ref", reference_rst])
    if trajectory:
        command.extend(["-x", f"{prefix}.nc"])
    result = run_logged(command, f"{prefix}.stdout.log")
    mdout = (WORK / f"{prefix}.mdout").read_text(errors="replace")
    result.update(
        {
            "mdout": f"{prefix}.mdout",
            "mdout_sha256": sha256(WORK / f"{prefix}.mdout"),
            "energies_kcal_mol": parse_energies(mdout),
            "amber_ns_per_day": parse_amber_ns_per_day(mdout),
            "cuda_banner": "GPU DEVICE INFO" in mdout,
            "gbion_v3_echo": bool(re.search(r"gbion\s*=\s*3", mdout)),
        }
    )
    return result


def parse_energies(text: str) -> list[float]:
    values = []
    for token in re.findall(
        r"(?:Etot|EPtot|ENERGY)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][-+]?\d+)?)",
        text,
        flags=re.IGNORECASE,
    ):
        values.append(float(token))
    lines = text.splitlines()
    for index, line in enumerate(lines[:-1]):
        if "NSTEP" in line and "ENERGY" in line and "RMS" in line:
            for candidate in lines[index + 1 : index + 5]:
                fields = re.findall(
                    r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", candidate
                )
                if len(fields) >= 4:
                    values.append(float(fields[1]))
                    break
    return values


def parse_amber_ns_per_day(text: str) -> float | None:
    patterns = (
        r"Performance:\s*([0-9.]+)\s*ns/day",
        r"ns/day\s*=\s*([0-9.]+)",
        r"([0-9.]+)\s*ns/day",
    )
    for pattern in patterns:
        hits = re.findall(pattern, text, flags=re.IGNORECASE)
        if hits:
            return float(hits[-1])
    return None


def run_gbion() -> dict:
    write_gb_inputs()
    emit_status("gbion_cpu_gpu_parity")
    cpu = amber_run(PMEMD, "gb_parity.mdin", "gbion.rst7", "parity_cpu")
    gpu = amber_run(PMEMD_CUDA, "gb_parity.mdin", "gbion.rst7", "parity_gpu")
    if not cpu["energies_kcal_mol"] or not gpu["energies_kcal_mol"]:
        raise RuntimeError("could not parse CPU/GPU parity energies")
    cpu_energy = cpu["energies_kcal_mol"][-1]
    gpu_energy = gpu["energies_kcal_mol"][-1]
    parity = {
        "cpu_energy_kcal_mol": cpu_energy,
        "gpu_energy_kcal_mol": gpu_energy,
        "absolute_delta_kcal_mol": abs(cpu_energy - gpu_energy),
        "relative_delta": abs(cpu_energy - gpu_energy) / max(1.0, abs(cpu_energy)),
        # A one-cycle minimization includes a force/update operation, so mixed-precision
        # CUDA and double-precision CPU coordinates need not be bitwise identical.
        "tolerance_relative": 1.0e-4,
        "passed": abs(cpu_energy - gpu_energy) / max(1.0, abs(cpu_energy)) < 1.0e-4,
        "cuda_banner": gpu["cuda_banner"],
        "gbion_v3_echo": gpu["gbion_v3_echo"],
    }

    emit_status("gbion_minimize")
    minimum = amber_run(
        PMEMD_CUDA,
        "gb_min.mdin",
        "gbion.rst7",
        "gb_min",
        reference_rst="gbion.rst7",
    )
    emit_status("gbion_heat")
    heat = amber_run(
        PMEMD_CUDA,
        "gb_heat.mdin",
        "gb_min.rst7",
        "gb_heat",
        reference_rst="gbion.rst7",
    )
    emit_status("gbion_equilibrate")
    equil = amber_run(
        PMEMD_CUDA,
        "gb_equil.mdin",
        "gb_heat.rst7",
        "gb_equil",
        reference_rst="gbion.rst7",
    )
    emit_status("gbion_benchmark")
    benchmark = amber_run(
        PMEMD_CUDA,
        "gb_benchmark.mdin",
        "gb_equil.rst7",
        "gb_benchmark",
    )
    benchmark["wall_ns_per_day"] = (
        BENCHMARK_STEPS * CONFIG.timestep_ps / 1000.0
    ) * 86_400.0 / benchmark["wall_seconds"]
    emit_status("gbion_production", sampled_ns=1.0)
    production = amber_run(
        PMEMD_CUDA,
        "gb_production.mdin",
        "gb_benchmark.rst7",
        "gb_production",
        trajectory=True,
    )
    return {
        "parity": parity,
        "minimum": minimum,
        "heat": heat,
        "equilibration": equil,
        "benchmark": benchmark,
        "production": production,
    }


def unit_cell_volume(box) -> float:
    a, b, c, alpha, beta, gamma = [float(value) for value in box]
    ar, br, gr = np.deg2rad([alpha, beta, gamma])
    factor = math.sqrt(
        1.0
        + 2.0 * math.cos(ar) * math.cos(br) * math.cos(gr)
        - math.cos(ar) ** 2
        - math.cos(br) ** 2
        - math.cos(gr) ** 2
    )
    return a * b * c * factor


def build_explicit_topology() -> dict:
    first = """source leaprc.DNA.OL15
source leaprc.water.tip3p
loadAmberParams frcmod.ionsjc_tip3p
mol = loadPdb dna.pdb
solvateOct mol TIP3PBOX 10.0
addIonsRand mol Na+ 0
saveAmberParm mol explicit_probe.parm7 explicit_probe.rst7
quit
"""
    (WORK / "tleap_explicit_probe.in").write_text(first)
    run_logged([str(TLEAP), "-f", "tleap_explicit_probe.in"], "tleap-explicit-probe.log")
    probe = pmd.load_file(
        str(WORK / "explicit_probe.parm7"), xyz=str(WORK / "explicit_probe.rst7")
    )
    volume = unit_cell_volume(probe.box)
    salt_pairs = max(
        1,
        round(volume * CONFIG.concentration_molar * 6.02214076e-4),
    )
    final = f"""source leaprc.DNA.OL15
source leaprc.water.tip3p
loadAmberParams frcmod.ionsjc_tip3p
mol = loadPdb dna.pdb
solvateOct mol TIP3PBOX 10.0
addIonsRand mol Na+ 0
addIonsRand mol Na+ {salt_pairs} Cl- {salt_pairs} 4.0
saveAmberParm mol explicit.parm7 explicit.rst7
quit
"""
    (WORK / "tleap_explicit.in").write_text(final)
    run_logged([str(TLEAP), "-f", "tleap_explicit.in"], "tleap-explicit.log")
    parm = pmd.load_file(
        str(WORK / "explicit.parm7"), xyz=str(WORK / "explicit.rst7")
    )
    waters = sum(residue.name in {"WAT", "HOH"} for residue in parm.residues)
    summary = topology_summary(parm)
    summary.update(
        {
            "waters": waters,
            "box_volume_angstrom3": unit_cell_volume(parm.box),
            "added_salt_pairs": salt_pairs,
            "nominal_salt_molar": salt_pairs
            / (unit_cell_volume(parm.box) * 6.02214076e-4),
        }
    )
    return summary


def write_explicit_inputs() -> None:
    (WORK / "explicit_min.mdin").write_text(
        "Explicit TIP3P minimization\n &cntrl\n"
        " imin=1, maxcyc=2000, ncyc=1000, ntpr=100, ntb=1, cut=9.0,\n"
        f" ntr=1, restraint_wt=5.0, restraintmask=':1-{DNA_RESIDUES}',\n /\n"
    )
    (WORK / "explicit_heat.mdin").write_text(
        "Explicit TIP3P heating\n &cntrl\n"
        " imin=0, irest=0, ntx=1, nstlim=10000, dt=0.002,\n"
        " tempi=10.0, temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        " ntb=1, ntp=0, ntc=2, ntf=2, cut=9.0, ntpr=1000, ntwx=0,\n"
        f" ntr=1, restraint_wt=5.0, restraintmask=':1-{DNA_RESIDUES}',\n /\n"
        " &wt type='TEMP0', istep1=0, istep2=10000, value1=10.0, value2=300.0 /\n"
        " &wt type='END' /\n"
    )
    (WORK / "explicit_equil.mdin").write_text(
        "Explicit TIP3P equilibration\n &cntrl\n"
        " imin=0, irest=1, ntx=5, nstlim=10000, dt=0.002,\n"
        " temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        " ntb=1, ntp=0, ntc=2, ntf=2, cut=9.0, ntpr=1000, ntwx=0,\n"
        f" ntr=1, restraint_wt=5.0, restraintmask=':1-{DNA_RESIDUES}',\n /\n"
    )
    (WORK / "explicit_benchmark.mdin").write_text(
        "Explicit TIP3P clean GPU benchmark\n &cntrl\n"
        f" imin=0, irest=1, ntx=5, nstlim={BENCHMARK_STEPS}, dt=0.002,\n"
        " temp0=300.0, ntt=3, gamma_ln=1.0, ig=20260827,\n"
        " ntb=1, ntp=0, ntc=2, ntf=2, cut=9.0,\n"
        f" ntpr={BENCHMARK_STEPS}, ntwx=0, ntwr={BENCHMARK_STEPS}, ntxo=2,\n /\n"
    )


def explicit_run(mdin: str, input_rst: str, prefix: str, *, ref: str | None = None):
    command = [
        str(PMEMD_CUDA),
        "-O",
        "-i",
        mdin,
        "-p",
        "explicit.parm7",
        "-c",
        input_rst,
        "-o",
        f"{prefix}.mdout",
        "-r",
        f"{prefix}.rst7",
        "-inf",
        f"{prefix}.mdinfo",
    ]
    if ref:
        command.extend(["-ref", ref])
    result = run_logged(command, f"{prefix}.stdout.log")
    text = (WORK / f"{prefix}.mdout").read_text(errors="replace")
    result.update(
        {
            "amber_ns_per_day": parse_amber_ns_per_day(text),
            "cuda_banner": "GPU DEVICE INFO" in text,
            "energies_kcal_mol": parse_energies(text),
        }
    )
    return result


def run_explicit_reference() -> dict:
    emit_status("explicit_parameterize")
    topology = build_explicit_topology()
    write_explicit_inputs()
    emit_status("explicit_minimize", atoms=topology["atoms"])
    minimum = explicit_run(
        "explicit_min.mdin", "explicit.rst7", "explicit_min", ref="explicit.rst7"
    )
    emit_status("explicit_heat")
    heat = explicit_run(
        "explicit_heat.mdin", "explicit_min.rst7", "explicit_heat", ref="explicit.rst7"
    )
    emit_status("explicit_equilibrate")
    equil = explicit_run(
        "explicit_equil.mdin", "explicit_heat.rst7", "explicit_equil", ref="explicit.rst7"
    )
    emit_status("explicit_benchmark")
    benchmark = explicit_run(
        "explicit_benchmark.mdin", "explicit_equil.rst7", "explicit_benchmark"
    )
    benchmark["wall_ns_per_day"] = (
        BENCHMARK_STEPS * CONFIG.timestep_ps / 1000.0
    ) * 86_400.0 / benchmark["wall_seconds"]
    return {
        "topology": topology,
        "minimum": minimum,
        "heat": heat,
        "equilibration": equil,
        "benchmark": benchmark,
    }


def normalize_base(name: str) -> str:
    name = name.upper().replace("5", "").replace("3", "")
    if name not in {"DA", "DT", "DG", "DC"}:
        raise RuntimeError(f"unexpected DNA residue name {name!r}")
    return name


def residue_atom(residue, name: str) -> int:
    for atom in residue.atoms:
        if atom.name.strip() == name:
            return atom.idx
    raise RuntimeError(f"{residue.name} is missing atom {name}")


def kabsch_rmsd_angstrom(reference: np.ndarray, current: np.ndarray) -> float:
    p = current - current.mean(axis=0)
    q = reference - reference.mean(axis=0)
    u, _, vt = np.linalg.svd(p.T @ q)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    delta = p @ rotation - q
    return float(np.sqrt(np.mean(np.sum(delta * delta, axis=1))))


def analyze_gbion(parm) -> dict:
    trajectory_path = WORK / "gb_production.nc"
    with netCDF4.Dataset(trajectory_path) as dataset:
        frames = np.asarray(dataset.variables["coordinates"][:], dtype=float)
    reference_parm = pmd.load_file(
        str(WORK / "gbion.parm7"), xyz=str(WORK / "gb_benchmark.rst7")
    )
    reference = np.asarray(reference_parm.coordinates, dtype=float)
    dna = list(parm.residues[:DNA_RESIDUES])
    strand_a = dna[: len(SEQUENCE)]
    strand_b = dna[len(SEQUENCE) :]
    pairs = [(strand_a[i], strand_b[-1 - i]) for i in range(len(SEQUENCE))]
    c1_pairs = [
        (residue_atom(a, "C1'"), residue_atom(b, "C1'")) for a, b in pairs
    ]
    c1_indices = sorted({index for pair in c1_pairs for index in pair})
    wc_pairs: list[list[tuple[int, int]]] = []
    for a, b in pairs:
        bases = {normalize_base(a.name): a, normalize_base(b.name): b}
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
            raise RuntimeError(f"non-Watson-Crick residue pair {a.name}/{b.name}")
        wc_pairs.append(
            [(residue_atom(x, xn), residue_atom(y, yn)) for x, xn, y, yn in names]
        )
    core = range(2, len(pairs) - 2)
    phosphorus = [atom.idx for atom in parm.atoms if atom.name.strip() == "P"]
    ions = [atom.idx for atom in parm.atoms if atom_is_na(atom) or atom_is_cl(atom)]
    series = []
    for frame_index, xyz in enumerate(frames):
        wc_dist = np.asarray(
            [np.linalg.norm(xyz[i] - xyz[j]) for bp in core for i, j in wc_pairs[bp]]
        )
        c1_dist = np.asarray(
            [np.linalg.norm(xyz[i] - xyz[j]) for i, j in c1_pairs[2:-2]]
        )
        center = xyz[phosphorus].mean(axis=0)
        ion_radius = np.linalg.norm(xyz[ions] - center, axis=1)
        series.append(
            {
                "time_ps": (frame_index + 1)
                * TRAJECTORY_INTERVAL
                * CONFIG.timestep_ps,
                "core_wc_contact_fraction": float(np.mean(wc_dist < 3.6)),
                "core_wc_mean_distance_nm": float(wc_dist.mean() / 10.0),
                "core_c1_pair_mean_nm": float(c1_dist.mean() / 10.0),
                "core_c1_pair_max_nm": float(c1_dist.max() / 10.0),
                "c1_aligned_rmsd_nm": kabsch_rmsd_angstrom(
                    reference[c1_indices], xyz[c1_indices]
                )
                / 10.0,
                "maximum_ion_radius_angstrom": float(ion_radius.max()),
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
    energy_text = (WORK / "gb_production.mdout").read_text(errors="replace")
    energies = parse_energies(energy_text)
    final = series[-1]
    return {
        "sampled_frames": len(frames),
        "sampled_ns": len(frames)
        * TRAJECTORY_INTERVAL
        * CONFIG.timestep_ps
        / 1000.0,
        "mean_core_wc_occupancy": float(
            np.mean([row["core_wc_contact_fraction"] for row in series])
        ),
        "minimum_core_wc_occupancy": float(
            np.min([row["core_wc_contact_fraction"] for row in series])
        ),
        "final": final,
        "maximum_sampled_ion_radius_angstrom": float(
            max(row["maximum_ion_radius_angstrom"] for row in series)
        ),
        "bond_lengths_nm": {
            "count": len(bond_lengths),
            "minimum": float(bond_lengths.min() / 10.0),
            "maximum": float(bond_lengths.max() / 10.0),
            "outside_0.08_to_0.20_nm": int(
                np.count_nonzero((bond_lengths < 0.8) | (bond_lengths > 2.0))
            ),
            "rms_deviation_from_equilibrium_nm": float(
                np.sqrt(np.nanmean((bond_lengths - equilibrium) ** 2)) / 10.0
            ),
            "maximum_deviation_from_equilibrium_nm": float(
                np.nanmax(np.abs(bond_lengths - equilibrium)) / 10.0
            ),
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
        emit_status("worker_start")
        if not PMEMD.is_file() or not PMEMD_CUDA.is_file() or not TLEAP.is_file():
            raise RuntimeError(
                f"required binaries missing: pmemd={PMEMD}, pmemd.cuda={PMEMD_CUDA}, "
                f"tleap={TLEAP}"
            )
        pdb, solute_xyz, phosphorus_xyz = make_duplex_pdb()
        solute_charge = derive_solute_charge()
        n_na, n_cl = CONFIG.ion_counts(solute_charge)
        placement = place_ions(pdb, solute_xyz, phosphorus_xyz, n_na, n_cl)
        emit_status("gbion_parameterize", sodium=n_na, chloride=n_cl)
        parm, topology = build_gbion_topology(n_na, n_cl)

        build = {
            "pmemd_cuda": str(PMEMD_CUDA),
            "pmemd_cuda_sha256": sha256(PMEMD_CUDA),
            "tleap": str(TLEAP),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "nvidia_smi": subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total",
                    "--format=csv,noheader",
                ],
                text=True,
            ).strip(),
        }
        gbion = run_gbion()
        emit_status("gbion_analyze")
        analysis = analyze_gbion(parm)
        explicit = run_explicit_reference()
        speedup = (
            gbion["benchmark"]["wall_ns_per_day"]
            / explicit["benchmark"]["wall_ns_per_day"]
        )
        final = analysis["final"]
        gate = {
            "sampled_at_least_1ns": analysis["sampled_ns"] >= 1.0,
            "mean_core_wc_occupancy_at_least_0_8": analysis[
                "mean_core_wc_occupancy"
            ]
            >= 0.8,
            "final_c1prime_rmsd_at_most_0_5nm": final["c1_aligned_rmsd_nm"] <= 0.5,
            "final_core_c1prime_pair_at_most_1_4nm": final[
                "core_c1_pair_max_nm"
            ]
            <= 1.4,
            "finite_energy": analysis["finite_energy"],
            "all_bonds_0_08_to_0_20nm": analysis["bond_lengths_nm"][
                "outside_0.08_to_0.20_nm"
            ]
            == 0,
            "measured_throughput": gbion["benchmark"]["wall_ns_per_day"] > 0,
            "cuda_banner": gbion["benchmark"]["cuda_banner"],
            "gbion_v3_echo": gbion["benchmark"]["gbion_v3_echo"],
            "cpu_gpu_parity": gbion["parity"]["passed"],
            "ion_wall_operational": analysis[
                "maximum_sampled_ion_radius_angstrom"
            ]
            <= CONFIG.sphere_radius_angstrom + 0.5,
            "speedup_over_same_gpu_explicit": speedup > 1.0,
        }
        result = {
            "schema_version": 1,
            "model": "Amber26 pmemd.cuda + OL15 + GBneck2/GBION-v3",
            "sequence": SEQUENCE,
            "length_bp": len(SEQUENCE),
            "nominal_salt_molar": CONFIG.concentration_molar,
            "ion_counts": {"sodium": n_na, "chloride": n_cl},
            "solute_charge_e": solute_charge,
            "placement": placement,
            "topology": topology,
            "build": build,
            "gbion": gbion,
            "analysis": analysis,
            "explicit_reference": explicit,
            "speedup_vs_same_gpu_explicit": speedup,
            "gates": gate,
            "basic_validation_passed": all(gate.values()),
            "wall_seconds_total": time.time() - started,
        }
        (OUT / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        for name in (
            "gbion.parm7",
            "gbion.rst7",
            "disang_NaCl.txt",
            "gb_benchmark.rst7",
            "gb_production.rst7",
            "gb_production.nc",
            "gb_production.mdout",
            "explicit.parm7",
            "explicit.rst7",
            "explicit_benchmark.mdout",
        ):
            source = WORK / name
            if source.is_file():
                target = OUT / name
                if target.exists():
                    target.unlink()
                source.replace(target)
        emit_status(
            "complete",
            passed=result["basic_validation_passed"],
            gbion_ns_per_day=gbion["benchmark"]["wall_ns_per_day"],
            speedup=speedup,
        )
    except Exception as exc:
        failure = {
            "phase": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "wall_seconds": time.time() - started,
        }
        (OUT / "failure.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n"
        )
        emit_status("failed", **failure)
        raise


if __name__ == "__main__":
    main()
