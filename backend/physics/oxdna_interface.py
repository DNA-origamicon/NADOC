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

import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

import math

from backend.core.constants import (
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    BDNA_RISE_PER_BP,
    HELIX_RADIUS,
    NM_TO_OXDNA,
    OXDNA_LENGTH_UNIT,
)
from backend.core.models import Design, Direction


# ── Geometry helpers ─────────────────────────────────────────────────────────


def _compute_nuc_geometry_copy(
    design: Design,
    helix_id: str,
    bp_index: int,
    direction: str,
    copy_k: int,
    n_copies: int,
) -> dict:
    """Like _compute_nuc_geometry but offset along the axis for loop copies."""
    nuc = _compute_nuc_geometry(design, helix_id, bp_index, direction)
    if nuc is None or n_copies <= 1:
        return nuc
    # Apply fractional axial offset: same formula as geometry.py nucleotide_positions().
    helix = design.find_helix(helix_id)
    if helix is None:
        return nuc
    start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])
    end   = np.array([helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z])
    axis_hat = end - start
    axis_len = np.linalg.norm(axis_hat)
    if axis_len == 0:
        return nuc
    axis_hat /= axis_len
    copy_frac = (copy_k - (n_copies - 1) / 2.0)
    offset = copy_frac * BDNA_RISE_PER_BP * axis_hat
    pos_shifted = np.array(nuc["backbone_position"]) + offset
    return {**nuc, "backbone_position": pos_shifted.tolist()}


def _compute_nuc_geometry(
    design: Design,
    helix_id: str,
    bp_index: int,
    direction: str,
) -> dict:
    """
    Compute geometry for a nucleotide that may be outside the helix's defined
    bp range (e.g. an overhang domain that extends beyond helix.length_bp).
    Returns a dict with the same keys as the geometry API response.
    """
    helix = design.find_helix(helix_id)
    if helix is None:
        return None

    start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])
    end   = np.array([helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z])
    axis_vec = end - start
    axis_len = np.linalg.norm(axis_vec)
    if axis_len == 0:
        return None

    axis_hat = axis_vec / axis_len
    # Build local frame (same as geometry.py's _frame_from_helix_axis)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(axis_hat, ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    x_hat = np.cross(ref, axis_hat)
    x_hat /= np.linalg.norm(x_hat)
    y_hat = np.cross(axis_hat, x_hat)

    local_i = bp_index - helix.bp_start
    axis_point = start + axis_hat * (local_i * BDNA_RISE_PER_BP)

    is_fwd_helix = (helix.direction == Direction.FORWARD)
    groove_offset = -BDNA_MINOR_GROOVE_ANGLE_RAD if is_fwd_helix else BDNA_MINOR_GROOVE_ANGLE_RAD

    fwd_angle = helix.phase_offset + local_i * helix.twist_per_bp_rad
    rev_angle = fwd_angle + groove_offset

    fwd_radial = math.cos(fwd_angle) * x_hat + math.sin(fwd_angle) * y_hat
    rev_radial = math.cos(rev_angle) * x_hat + math.sin(rev_angle) * y_hat

    fwd_backbone = axis_point + HELIX_RADIUS * fwd_radial
    rev_backbone = axis_point + HELIX_RADIUS * rev_radial

    base_pair_vec = rev_backbone - fwd_backbone
    base_pair_hat = base_pair_vec / (np.linalg.norm(base_pair_vec) + 1e-14)

    if direction == "FORWARD":
        backbone = fwd_backbone
        base_normal = base_pair_hat
    else:
        backbone = rev_backbone
        base_normal = -base_pair_hat

    return {
        "helix_id": helix_id,
        "bp_index": bp_index,
        "direction": direction,
        "backbone_position": backbone.tolist(),
        "base_normal": base_normal.tolist(),
        "axis_tangent": axis_hat.tolist(),
    }


# ── Nucleotide ordering helper ────────────────────────────────────────────────


def _build_ls_lookup(design: Design) -> dict[tuple[str, int], int]:
    """Return {(helix_id, bp_index): delta_sum} for all loop_skip sites."""
    ls: dict[tuple[str, int], int] = {}
    for h in design.helices:
        for loop_skip in h.loop_skips:
            key = (h.id, loop_skip.bp_index)
            ls[key] = ls.get(key, 0) + loop_skip.delta
    return ls


def _strand_nucleotide_order(design: Design) -> list[tuple]:
    """
    Return a flat list of nucleotide keys in the oxDNA order.

    Normal positions use 3-tuples (helix_id, bp_index, direction).
    Loop insertions (delta≥1) emit n_copies 4-tuples
    (helix_id, bp_index, direction, copy_k) for k=0..n_copies-1.

    Deleted positions (delta=-1) are excluded entirely.
    This order must be consistent between topology and configuration files.
    """
    ls_lookup = _build_ls_lookup(design)
    order: list[tuple] = []
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            if domain.direction == Direction.FORWARD:
                bp_range = range(lo, hi + 1)
            else:
                bp_range = range(hi, lo - 1, -1)
            for bp in bp_range:
                delta = ls_lookup.get((domain.helix_id, bp), 0)
                if delta <= -1:
                    continue  # deleted position: no nucleotide
                n_copies = max(1, delta + 1)
                if n_copies == 1:
                    order.append((domain.helix_id, bp, domain.direction.value))
                else:
                    for k in range(n_copies):
                        order.append((domain.helix_id, bp, domain.direction.value, k))
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

    # Build per-nucleotide sequence lookup (key matches order tuple format).
    ls_lookup = _build_ls_lookup(design)
    seq_lookup: dict[tuple, str] = {}
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
                delta = ls_lookup.get((domain.helix_id, bp), 0)
                if delta <= -1:
                    continue  # deletion: no character in scadnano sequence string
                n_copies = max(1, delta + 1)
                for copy_k in range(n_copies):
                    base = seq[seq_idx] if seq_idx < len(seq) else 'N'
                    if n_copies == 1:
                        seq_lookup[(domain.helix_id, bp, domain.direction.value)] = base
                    else:
                        seq_lookup[(domain.helix_id, bp, domain.direction.value, copy_k)] = base
                    seq_idx += 1

    # Build index map for neighbour lookup (4-tuple key for loop copies).
    index_map: dict[tuple, int] = {k: i for i, k in enumerate(order)}

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
                delta = ls_lookup.get((domain.helix_id, bp), 0)
                if delta <= -1:
                    continue
                n_copies = max(1, delta + 1)
                for copy_k in range(n_copies):
                    if n_copies == 1:
                        key: tuple = (domain.helix_id, bp, domain.direction.value)
                    else:
                        key = (domain.helix_id, bp, domain.direction.value, copy_k)
                    if key in index_map:
                        strand_nuc_indices.append(index_map[key])

        for k, idx in enumerate(strand_nuc_indices):
            if k + 1 < len(strand_nuc_indices):
                three_prime_nbr[idx] = strand_nuc_indices[k + 1]
            if k - 1 >= 0:
                five_prime_nbr[idx] = strand_nuc_indices[k - 1]

    # Build strand index lookup (1-based per oxDNA convention).
    strand_idx_map: dict[tuple, int] = {}
    for si, strand in enumerate(design.strands, start=1):
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            delta_map = {bp: ls_lookup.get((domain.helix_id, bp), 0)
                         for bp in range(lo, hi + 1)}
            for bp in range(lo, hi + 1):
                delta = delta_map.get(bp, 0)
                if delta <= -1:
                    continue
                n_copies = max(1, delta + 1)
                for copy_k in range(n_copies):
                    if n_copies == 1:
                        strand_idx_map[(domain.helix_id, bp, domain.direction.value)] = si
                    else:
                        strand_idx_map[(domain.helix_id, bp, domain.direction.value, copy_k)] = si

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
    box_nm: float | None = None,
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
    box_nm   : simulation box edge length in nm.  Defaults to the maximum
               backbone position extent + 20 nm margin.
    """
    # Build geometry lookup: (helix_id, bp_index, direction) → nuc dict.
    geo_map: dict[tuple[str, int, str], dict] = {
        (n["helix_id"], n["bp_index"], n["direction"]): n
        for n in geometry
    }

    order = _strand_nucleotide_order(design)

    # Resolve any missing geometry entries by extrapolating along the helix axis.
    # For loop copies (4-tuple keys), geo_map won't have an entry; use the
    # copy-aware helper that applies the fractional axial offset.
    ls_lookup_conf = _build_ls_lookup(design)
    resolved_map: dict[tuple, dict] = {}
    for key in order:
        nuc = geo_map.get(key[:3])  # geo_map always uses 3-tuple keys
        if len(key) == 4:
            # Loop copy: always recompute with fractional axial offset.
            _h_id, _bp, _dir, _copy_k = key
            _delta = ls_lookup_conf.get((_h_id, _bp), 0)
            _n_copies = max(1, _delta + 1)
            nuc = _compute_nuc_geometry_copy(design, _h_id, _bp, _dir, _copy_k, _n_copies)
        else:
            if nuc is None:
                nuc = _compute_nuc_geometry(design, key[0], key[1], key[2])
        if nuc is not None:
            resolved_map[key] = nuc

    if box_nm is None:
        # Size box from actual backbone position extents + 20 nm margin (10 nm per side).
        # oxDNA handles positions outside [0, L] via PBC, so no centering is needed.
        all_pos = np.array([n["backbone_position"] for n in resolved_map.values()], dtype=float)
        if len(all_pos) > 0:
            extents = all_pos.max(axis=0) - all_pos.min(axis=0)
            box_nm = max(50.0, float(extents.max()) + 20.0)
        else:
            box_nm = 50.0

    box   = box_nm * NM_TO_OXDNA

    lines = [
        "t = 0",
        f"b = {box:.6f} {box:.6f} {box:.6f}",
        "E = 0.000000 0.000000 0.000000",
    ]

    for key in order:
        nuc = resolved_map.get(key)
        if nuc is None:
            # Truly unresolvable — skip (should not happen after _compute_nuc_geometry).
            ctr = box / 2.0
            lines.append(f"{ctr:.6f} {ctr:.6f} {ctr:.6f}  1.0 0.0 0.0  0.0 0.0 1.0  0.0 0.0 0.0  0.0 0.0 0.0")
            continue

        # Position in oxDNA units (natural coordinates — no centering).
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
        pos_nm = pos_oxdna * OXDNA_LENGTH_UNIT
        # Always store under the 3-tuple key; for loop copies last one wins
        # (callers use 3-tuple keys; averaging all copies would be ideal but
        # the last copy's position is a reasonable proxy for the CG centroid).
        result[key[:3]] = pos_nm

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
    steps:            int = 10_000,
    relaxation_steps: int = 1000,  # kept for API compatibility, unused by MIN
) -> None:
    """
    Write a minimal oxDNA input file for energy minimisation (sim_type = MIN).

    Parameters
    ----------
    topology_path      : path to the .top file (written by write_topology).
    configuration_path : path to the .dat file (written by write_configuration).
    output_path        : path to write the input file.
    steps              : number of minimisation steps.
    relaxation_steps   : unused (kept for call-site compatibility).
    """
    content = f"""\
sim_type = MC
backend = CPU

ensemble = NVT
T = 296K

steps = {steps}
restart_step_counter = true
verlet_skin = 0.20

delta_translation = 0.1
delta_rotation = 0.1

max_backbone_force = 5
max_backbone_force_far = 10

topology = {Path(topology_path).name}
conf_file = {Path(configuration_path).name}
trajectory_file = trajectory.dat
energy_file = energy.dat
lastconf_file = last_conf.dat

interaction_type = DNA2
salt_concentration = 0.5

time_scale = linear
print_conf_interval = {max(1, steps // 10)}
print_energy_every = {max(1, steps // 100)}
"""
    Path(output_path).write_text(content, encoding="utf-8")
