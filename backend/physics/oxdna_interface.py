"""
Physical layer — oxDNA file format interface.

Provides write and read helpers for the oxDNA coarse-grained DNA model.
oxDNA uses its own unit system; all conversions are handled here so the
rest of the codebase stays in nanometres.

References
──────────
  oxDNA format: https://oxdna.org/format.html
  1 oxDNA length unit = 0.8518 nm  (OXDNA_LENGTH_UNIT in constants.py)

File formats
────────────
  .top   — topology: N nucleotides, S strands; one line per nucleotide
           "<strand_idx(1-based)> <base(A/T/C/G/N)> <3p_nbr> <5p_nbr>"
           Neighbour indices are 0-based; -1 means no neighbour.

  .dat   — configuration: header then one line per nucleotide
           "t = <int>"
           "b = <Lx> <Ly> <Lz>"
           "E = <pot> <kin> <tot>"
           "<pos_x> <pos_y> <pos_z>  <a1_x> <a1_y> <a1_z>  <a3_x> <a3_y> <a3_z>
            <vel_x> <vel_y> <vel_z>  <L_x> <L_y> <L_z>"
           a1 = base-normal (backbone → base direction), a3 = 3′→5′ along chain.

Architecture note: this module is physical-layer only.  It converts Design
(topological) + geometry (geometric) into oxDNA format and back.  It never
modifies Design objects.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

from backend.core.constants import NM_TO_OXDNA, OXDNA_LENGTH_UNIT
from backend.core.geometry import nucleotide_positions
from backend.core.models import Design, Direction


# ── Nucleotide ordering helper ────────────────────────────────────────────────


def _strand_nucleotide_order(design: Design) -> list[tuple[str, int, str]]:
    """
    Return a flat list of (helix_id, bp_index, direction) keys in the oxDNA
    nucleotide order: all nucleotides of strand 0 in 5′→3′ order, then strand 1,
    etc.

    This order must be consistent between the topology file and the
    configuration file.
    """
    order: list[tuple[str, int, str]] = []
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            if domain.direction == Direction.FORWARD:
                bp_range = range(lo, hi + 1)
            else:
                bp_range = range(hi, lo - 1, -1)
            for bp in bp_range:
                order.append((domain.helix_id, bp, domain.direction.value))
    return order


# ── Topology writer ───────────────────────────────────────────────────────────


def write_topology(design: Design, path: str | Path) -> None:
    """
    Write an oxDNA topology (.top) file for *design*.

    The nucleotide order used here must match the order in write_configuration.
    Sequences are written as 'N' (unknown base) unless design strands carry a
    sequence string.
    """
    order = _strand_nucleotide_order(design)
    n_nucleotides = len(order)
    n_strands     = len(design.strands)

    # Build per-nucleotide sequence lookup.
    seq_lookup: dict[tuple[str, int, str], str] = {}
    for strand in design.strands:
        seq = strand.sequence or ""
        seq_idx = 0
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            if domain.direction == Direction.FORWARD:
                bp_range = range(lo, hi + 1)
            else:
                bp_range = range(hi, lo - 1, -1)
            for bp in bp_range:
                base = seq[seq_idx] if seq_idx < len(seq) else 'N'
                seq_lookup[(domain.helix_id, bp, domain.direction.value)] = base
                seq_idx += 1

    # Build index map for neighbour lookup.
    index_map: dict[tuple[str, int, str], int] = {k: i for i, k in enumerate(order)}

    # Build neighbour maps (5′ and 3′ in oxDNA convention).
    # oxDNA a3 axis points in 5′→3′ direction.  neighbour lists:
    #   3p_nbr: index of the nucleotide that this one is bonded to on the 3′ side
    #   5p_nbr: index of the nucleotide that this one is bonded to on the 5′ side
    three_prime_nbr: dict[int, int] = {}
    five_prime_nbr:  dict[int, int] = {}

    for strand in design.strands:
        strand_nuc_indices: list[int] = []
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            if domain.direction == Direction.FORWARD:
                bp_range = range(lo, hi + 1)
            else:
                bp_range = range(hi, lo - 1, -1)
            for bp in bp_range:
                key = (domain.helix_id, bp, domain.direction.value)
                if key in index_map:
                    strand_nuc_indices.append(index_map[key])

        for k, idx in enumerate(strand_nuc_indices):
            if k + 1 < len(strand_nuc_indices):
                three_prime_nbr[idx] = strand_nuc_indices[k + 1]
            if k - 1 >= 0:
                five_prime_nbr[idx] = strand_nuc_indices[k - 1]

    # Build strand index lookup (1-based per oxDNA convention).
    strand_idx_map: dict[tuple[str, int, str], int] = {}
    for si, strand in enumerate(design.strands, start=1):
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                strand_idx_map[(domain.helix_id, bp, domain.direction.value)] = si

    lines = [f"{n_nucleotides} {n_strands}"]
    for i, key in enumerate(order):
        si    = strand_idx_map.get(key, 1)
        base  = seq_lookup.get(key, 'N')
        n3    = three_prime_nbr.get(i, -1)
        n5    = five_prime_nbr.get(i, -1)
        lines.append(f"{si} {base} {n3} {n5}")

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Configuration writer ──────────────────────────────────────────────────────


def write_configuration(
    design: Design,
    geometry: list[dict],
    path: str | Path,
    box_nm: float = 50.0,
) -> None:
    """
    Write an oxDNA configuration (.dat) file.

    Parameters
    ----------
    design   : Design — used for strand topology / nucleotide order.
    geometry : list of nucleotide dicts from GET /api/design/geometry.
               Must contain: helix_id, bp_index, direction, backbone_position,
               base_normal, axis_tangent.
    path     : output file path.
    box_nm   : simulation box half-edge length in nm (written as a cubic box).
    """
    # Build geometry lookup: (helix_id, bp_index, direction) → nuc dict.
    geo_map: dict[tuple[str, int, str], dict] = {
        (n["helix_id"], n["bp_index"], n["direction"]): n
        for n in geometry
    }

    order = _strand_nucleotide_order(design)
    box   = box_nm * NM_TO_OXDNA

    lines = [
        "t = 0",
        f"b = {box:.6f} {box:.6f} {box:.6f}",
        "E = 0.000000 0.000000 0.000000",
    ]

    for key in order:
        nuc = geo_map.get(key)
        if nuc is None:
            # Fallback: place at origin with identity orientation.
            lines.append("0.0 0.0 0.0  1.0 0.0 0.0  0.0 0.0 1.0  0.0 0.0 0.0  0.0 0.0 0.0")
            continue

        # Position in oxDNA units.
        pos_nm = np.array(nuc["backbone_position"], dtype=float)
        pos    = pos_nm * NM_TO_OXDNA

        # a1 = base-normal (backbone → base direction, cross-strand).
        a1 = np.array(nuc["base_normal"], dtype=float)
        a1 /= np.linalg.norm(a1) + 1e-14

        # a3 = 5′→3′ direction (axis_tangent for FORWARD, -axis_tangent for REVERSE).
        tangent = np.array(nuc["axis_tangent"], dtype=float)
        if nuc["direction"] == "FORWARD":
            a3 = tangent
        else:
            a3 = -tangent
        a3 /= np.linalg.norm(a3) + 1e-14

        lines.append(
            f"{pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}  "
            f"{a1[0]:.6f} {a1[1]:.6f} {a1[2]:.6f}  "
            f"{a3[0]:.6f} {a3[1]:.6f} {a3[2]:.6f}  "
            "0.000000 0.000000 0.000000  "
            "0.000000 0.000000 0.000000"
        )

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Configuration reader ──────────────────────────────────────────────────────


def read_configuration(
    conf_path:  str | Path,
    design:     Design,
) -> dict[tuple[str, int, str], np.ndarray]:
    """
    Read an oxDNA configuration (.dat) file and return a position map.

    Parameters
    ----------
    conf_path : path to the .dat file.
    design    : Design used to recover the nucleotide order.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → np.ndarray shape (3,)
    with backbone positions in nanometres (converted from oxDNA units).
    """
    order = _strand_nucleotide_order(design)
    lines = Path(conf_path).read_text(encoding="utf-8").splitlines()

    # Skip the 3-line header.
    data_lines = [l for l in lines if l.strip() and not l.startswith(('t ', 'b ', 'E '))]

    result: dict[tuple[str, int, str], np.ndarray] = {}
    for i, key in enumerate(order):
        if i >= len(data_lines):
            break
        parts = data_lines[i].split()
        if len(parts) < 3:
            continue
        pos_oxdna = np.array([float(parts[0]), float(parts[1]), float(parts[2])])
        result[key] = pos_oxdna * OXDNA_LENGTH_UNIT  # convert to nm

    return result


# ── oxDNA runner ──────────────────────────────────────────────────────────────


def run_oxdna(
    input_path: str | Path,
    oxdna_bin:  str = "oxDNA",
    timeout:    int = 300,
) -> Optional[int]:
    """
    Run oxDNA minimisation/simulation.

    Parameters
    ----------
    input_path : path to the oxDNA input file.
    oxdna_bin  : name or full path of the oxDNA executable.
    timeout    : maximum run time in seconds.

    Returns
    -------
    int return code on success, or None if oxDNA is not installed / not found.
    """
    try:
        result = subprocess.run(
            [oxdna_bin, str(input_path)],
            cwd=str(Path(input_path).parent),
            capture_output=True,
            timeout=timeout,
        )
        return result.returncode
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None


# ── oxDNA input file writer ───────────────────────────────────────────────────


def write_oxdna_input(
    topology_path:    str | Path,
    configuration_path: str | Path,
    output_path:      str | Path,
    steps:            int = 1000,
    relaxation_steps: int = 1000,
) -> None:
    """
    Write a minimal oxDNA input file for energy minimisation.

    Parameters
    ----------
    topology_path      : path to the .top file (written by write_topology).
    configuration_path : path to the .dat file (written by write_configuration).
    output_path        : path to write the input file.
    steps              : number of Monte Carlo / MD steps.
    relaxation_steps   : number of initial relaxation steps.
    """
    content = f"""\
sim_type = MC
backend = CPU
backend_precision = double

steps = {steps}
equilibration_steps = {relaxation_steps}

T = 296K
dt = 0.001
verlet_skin = 0.15

topology = {Path(topology_path).name}
conf_file = {Path(configuration_path).name}
trajectory_file = trajectory.dat
energy_file = energy.dat
lastconf_file = last_conf.dat

interaction_type = DNA2
salt_concentration = 0.5

print_conf_interval = {max(1, steps // 10)}
print_energy_every = {max(1, steps // 100)}
"""
    Path(output_path).write_text(content, encoding="utf-8")
