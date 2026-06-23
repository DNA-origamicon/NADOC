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


def count_undefined_bases(
    design: Design, exclude_reference: bool = True
) -> tuple[int, int]:
    """Count nucleotides whose assigned base is *not* a definite A/C/G/T.

    Mirrors ``write_topology``'s per-nucleotide sequence assignment exactly
    (loop copies expanded, skips/deletions dropped), so the count reflects what
    oxDNA actually receives — every position that would be written as ``'N'``.

    Reference 'backdrop' strands (``Strand.is_reference``) are skipped by
    default, matching how they are excluded from every export/validation path.

    Returns ``(undefined_count, total_count)``.
    """
    ls_lookup = _build_ls_lookup(design)
    undefined = 0
    total = 0
    for strand in design.strands:
        if exclude_reference and strand.is_reference:
            continue
        seq = (strand.sequence or "").upper()
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
                    continue  # deletion: no nucleotide written
                for _ in range(max(1, delta + 1)):
                    base = seq[seq_idx] if seq_idx < len(seq) else 'N'
                    total += 1
                    if base not in "ACGT":
                        undefined += 1
                    seq_idx += 1
    return undefined, total


# ── Topology writer ───────────────────────────────────────────────────────────


def topology_rows(design: Design) -> tuple[list[tuple[int, str, int, int]], int]:
    """Build the per-nucleotide topology rows for *design*.

    Returns ``(rows, n_strands)`` where each row is
    ``(strand_idx_1based, base, n3, n5)`` with **0-based** DNA particle indices
    (``n3``/``n5`` = ``-1`` when there is no 3′/5′ neighbour).  The order matches
    ``write_configuration``.  Extracted from ``write_topology`` so the hybrid
    protein+DNA topology writer (``oxdna_protein``) can reuse it — there the DNA
    particle indices are shifted by ``+N_protein`` because protein beads occupy
    the leading indices in the ANM-oxDNA convention.
    """
    order = _strand_nucleotide_order(design)
    n_strands = len(design.strands)

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

    rows: list[tuple[int, str, int, int]] = []
    for i, key in enumerate(order):
        rows.append((
            strand_idx_map.get(key, 1),
            seq_lookup.get(key, 'N'),
            three_prime_nbr.get(i, -1),
            five_prime_nbr.get(i, -1),
        ))
    return rows, n_strands


def write_topology(design: Design, path: str | Path) -> None:
    """
    Write an oxDNA topology (.top) file for *design*.

    The nucleotide order used here must match the order in write_configuration.
    Sequences are written as 'N' (unknown base) unless design strands carry a
    sequence string.
    """
    rows, n_strands = topology_rows(design)
    lines = [f"{len(rows)} {n_strands}"]
    for si, base, n3, n5 in rows:
        lines.append(f"{si} {base} {n3} {n5}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Configuration writer ──────────────────────────────────────────────────────


def write_configuration(
    design: Design,
    geometry: list[dict],
    path: str | Path,
    box_nm: float | None = None,
    *,
    oxdna_native_seed: bool = False,
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
    oxdna_native_seed : when True, slide each centre-of-mass inward along its base
               normal (:func:`oxdna_native_seed_map`) so designed WC pairs START
               bonded at oxDNA's native duplex width instead of NADOC's wide B-DNA —
               eliminates the startup "collapse"/melt of a relaxation seed.  Off by
               default so display/reference/export configs keep raw NADOC geometry.
    """
    resolved_map = resolved_nuc_map(design, geometry)
    if oxdna_native_seed:
        resolved_map = oxdna_native_seed_map(design, resolved_map)
    order = _strand_nucleotide_order(design)

    if box_nm is None:
        positions = [n["backbone_position"] for n in resolved_map.values()]
        box_nm = box_nm_for_positions(positions)

    box = box_nm * NM_TO_OXDNA
    lines = [
        "t = 0",
        f"b = {box:.6f} {box:.6f} {box:.6f}",
        "E = 0.000000 0.000000 0.000000",
    ]
    for key in order:
        nuc = resolved_map.get(key)
        lines.append(nuc_conf_line(nuc) if nuc is not None else _conf_center_fallback(box))

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolved_nuc_map(design: Design, geometry: list[dict]) -> dict[tuple, dict]:
    """Resolve every nucleotide key to a geometry dict (extrapolating any missing
    entries along the helix axis; loop copies get the fractional axial offset).

    Extracted from ``write_configuration`` so the hybrid protein+DNA writer reuses
    the identical DNA geometry resolution.
    """
    geo_map: dict[tuple[str, int, str], dict] = {
        (n["helix_id"], n["bp_index"], n["direction"]): n for n in geometry
    }
    order = _strand_nucleotide_order(design)
    ls_lookup_conf = _build_ls_lookup(design)
    resolved_map: dict[tuple, dict] = {}
    for key in order:
        nuc = geo_map.get(key[:3])  # geo_map always uses 3-tuple keys
        if len(key) == 4:
            _h_id, _bp, _dir, _copy_k = key
            _delta = ls_lookup_conf.get((_h_id, _bp), 0)
            _n_copies = max(1, _delta + 1)
            nuc = _compute_nuc_geometry_copy(design, _h_id, _bp, _dir, _copy_k, _n_copies)
        elif nuc is None:
            nuc = _compute_nuc_geometry(design, key[0], key[1], key[2])
        if nuc is not None:
            resolved_map[key] = nuc
    return resolved_map


# oxDNA's base (H-bond) interaction site sits at CM + POS_BASE·a1 (model.h
# POS_BASE = 0.4 oxDNA units); the .dat position IS the centre of mass.
_POS_BASE_NM: float = 0.4 * OXDNA_LENGTH_UNIT   # ≈ 0.341 nm

# Target base-site separation (nm) for the oxDNA-native seed.  oxDNA2's hydrogen-
# bond equilibrium sits at ~0.37 nm — the separation a relaxed duplex settles at
# on this machine (measured, §18 of project_oxdna_relaxation).  NADOC's idealised
# B-DNA seeds the pair ~1.25 nm apart (HELIX_RADIUS = 1.0 nm), far outside oxDNA's
# ~0.34 nm bonding range, so a free MD melts every designed pair at startup.
OXDNA_NATIVE_HBOND_NM: float = 0.37


def oxdna_native_seed_map(
    design: Design, resolved_map: dict[tuple, dict]
) -> dict[tuple, dict]:
    """Return a copy of *resolved_map* with every nucleotide centre-of-mass slid
    inward along its base normal so designed Watson-Crick pairs START at oxDNA's
    native bonding geometry (base sites ~0.37 nm apart, backbone ~1.63 nm wide)
    instead of NADOC's wide idealised B-DNA (~1.25 nm base-site separation, outside
    oxDNA's H-bond range).

    The shift is a single uniform distance ``delta`` along each nucleotide's own
    ``base_normal`` (a1) — a1 points cross-strand toward the partner, so ``+delta·a1``
    narrows the duplex and lands the reconstructed backbone at oxDNA's native width.
    ``delta`` is derived from THIS design's median designed-pair base-site
    separation, so it adapts to the lattice (HC/SQ) automatically.  Applying the
    SAME shift to paired AND unpaired nucleotides keeps every backbone bond length
    intact (no paired↔unpaired discontinuity), so it introduces no over-stretch — in
    fact it REMOVES the FENE over-stretch NADOC's wide seed carries.

    Physical-layer only: this is the oxDNA simulation's STARTING configuration,
    never written back into Design topology.  Orientation (a1/a3) is untouched.
    Returns the map unchanged when there are no designed pairs to seed.
    """
    a1_of: dict[tuple, np.ndarray] = {}
    for key, nuc in resolved_map.items():
        a1 = np.asarray(nuc["base_normal"], dtype=float)
        a1_of[key] = a1 / (np.linalg.norm(a1) + 1e-14)

    fwd = {(k[0], k[1]) for k in resolved_map if k[2] == "FORWARD"}
    rev = {(k[0], k[1]) for k in resolved_map if k[2] == "REVERSE"}
    seps: list[float] = []
    for hid, bp in fwd & rev:
        f = resolved_map[(hid, bp, "FORWARD")]
        r = resolved_map[(hid, bp, "REVERSE")]
        f_base = np.asarray(f["backbone_position"], float) + _POS_BASE_NM * a1_of[(hid, bp, "FORWARD")]
        r_base = np.asarray(r["backbone_position"], float) + _POS_BASE_NM * a1_of[(hid, bp, "REVERSE")]
        seps.append(float(np.linalg.norm(f_base - r_base)))
    if not seps:
        return resolved_map

    delta = max(0.0, (float(np.median(seps)) - OXDNA_NATIVE_HBOND_NM) / 2.0)
    if delta == 0.0:
        return resolved_map

    out: dict[tuple, dict] = {}
    for key, nuc in resolved_map.items():
        shifted = dict(nuc)
        shifted["backbone_position"] = (
            np.asarray(nuc["backbone_position"], float) + delta * a1_of[key]
        )
        out[key] = shifted
    return out


def box_nm_for_positions(positions_nm: list) -> float:
    """Box edge (nm) sizing a list of nm positions: max extent + 20 nm, ≥ 50 nm.
    oxDNA handles positions outside [0, L] via PBC, so no centering is needed."""
    all_pos = np.array(positions_nm, dtype=float)
    if len(all_pos) == 0:
        return 50.0
    extents = all_pos.max(axis=0) - all_pos.min(axis=0)
    return max(50.0, float(extents.max()) + 20.0)


def nuc_conf_line(nuc: dict) -> str:
    """The 15-float configuration line (oxDNA units) for one resolved nucleotide.
    ``a1`` = base-normal, ``a3`` = 5′→3′ (axis tangent, negated for REVERSE)."""
    pos = np.array(nuc["backbone_position"], dtype=float) * NM_TO_OXDNA
    a1 = np.array(nuc["base_normal"], dtype=float)
    a1 /= np.linalg.norm(a1) + 1e-14
    tangent = np.array(nuc["axis_tangent"], dtype=float)
    a3 = tangent if nuc["direction"] == "FORWARD" else -tangent
    a3 /= np.linalg.norm(a3) + 1e-14
    return (
        f"{pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}  "
        f"{a1[0]:.6f} {a1[1]:.6f} {a1[2]:.6f}  "
        f"{a3[0]:.6f} {a3[1]:.6f} {a3[2]:.6f}  "
        "0.000000 0.000000 0.000000  0.000000 0.000000 0.000000"
    )


def _conf_center_fallback(box: float) -> str:
    """Box-centre placeholder line for a nucleotide with no resolvable geometry
    (should not happen after ``resolved_nuc_map``)."""
    ctr = box / 2.0
    return f"{ctr:.6f} {ctr:.6f} {ctr:.6f}  1.0 0.0 0.0  0.0 0.0 1.0  0.0 0.0 0.0  0.0 0.0 0.0"


# ── Configuration reader ──────────────────────────────────────────────────────


def _protein_lead_offset(data_lines: list, order: list) -> int:
    """Number of leading non-DNA particle lines in a configuration.

    A hybrid ANM-oxDNA (DNANM) conf writes the protein beads FIRST, then the DNA
    nucleotides, so it has ``N_protein + len(order)`` data lines.  A DNA-only conf
    has exactly ``len(order)``.  The difference is the count of leading protein
    lines to skip so the DNA keys line up with the trailing DNA lines.  Robust to
    a truncated mid-write frame (clamped at 0)."""
    return max(0, len(data_lines) - len(order))


def read_protein_bead_positions(conf_path: str | Path, n_dna: int) -> list:
    """The LEADING protein-bead positions (nm) of a hybrid conf — the first
    ``total_data_lines - n_dna`` particle lines (protein beads precede the DNA in
    the ANM-oxDNA convention).  Empty for a DNA-only conf.  ``n_dna`` =
    ``len(_strand_nucleotide_order(design))``."""
    lines = Path(conf_path).read_text(encoding="utf-8").splitlines()
    data = [l for l in lines if l.strip() and not l.startswith(('t ', 'b ', 'E '))]
    n_prot = max(0, len(data) - n_dna)
    out = []
    for ln in data[:n_prot]:
        parts = ln.split()
        if len(parts) >= 3:
            out.append(np.array([float(parts[0]), float(parts[1]), float(parts[2])])
                       * OXDNA_LENGTH_UNIT)
    return out


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

    # Hybrid (DNANM) confs carry protein beads in the LEADING particle indices; the
    # DNA nucleotides follow.  Skip the leading protein lines so DNA keys line up.
    offset = _protein_lead_offset(data_lines, order)

    result: dict[tuple[str, int, str], np.ndarray] = {}
    for i, key in enumerate(order):
        if offset + i >= len(data_lines):
            break
        parts = data_lines[offset + i].split()
        if len(parts) < 3:
            continue
        pos_oxdna = np.array([float(parts[0]), float(parts[1]), float(parts[2])])
        pos_nm = pos_oxdna * OXDNA_LENGTH_UNIT
        # Always store under the 3-tuple key; for loop copies last one wins
        # (callers use 3-tuple keys; averaging all copies would be ideal but
        # the last copy's position is a reasonable proxy for the CG centroid).
        result[key[:3]] = pos_nm

    return result


def read_configuration_full(
    conf_path: str | Path,
    design:    Design,
    *,
    copies:    bool = False,
) -> dict[tuple, dict]:
    """
    Read an oxDNA configuration (.dat) and return position + orientation per nuc.

    Like ``read_configuration`` but also recovers the a1 (base-normal) and a3
    (5′→3′) unit vectors from the file, so callers can both render faithful
    orientation (display) and compute base-site positions (base-pair-retention
    health).

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → {
        "backbone_position": np.ndarray (3,) nm,
        "a1":                np.ndarray (3,) unit (backbone→base, cross-strand),
        "a3":                np.ndarray (3,) unit (5′→3′ along chain),
    }
    By default loop copies the last copy wins (matches ``read_configuration``).
    With ``copies=True`` each loop-insertion copy is kept under its own 4-tuple key
    (helix_id, bp_index, direction_str, copy_k) — used by the atomistic/surface
    display reconstruction so insertion copies get their own relaxed rigid frame
    instead of sitting at the design position (the long-bond artifact).  Designs
    without insertions are unaffected (``_strand_nucleotide_order`` emits only
    3-tuples there), so this is a no-op for them.
    """
    order = _strand_nucleotide_order(design)
    lines = Path(conf_path).read_text(encoding="utf-8").splitlines()
    data_lines = [l for l in lines if l.strip() and not l.startswith(('t ', 'b ', 'E '))]
    offset = _protein_lead_offset(data_lines, order)   # skip leading protein beads (hybrid)

    result: dict[tuple[str, int, str], dict] = {}
    for i, key in enumerate(order):
        if offset + i >= len(data_lines):
            break
        parts = data_lines[offset + i].split()
        if len(parts) < 9:
            continue
        vals = [float(x) for x in parts[:9]]
        pos_nm = np.array(vals[0:3]) * OXDNA_LENGTH_UNIT
        a1 = np.array(vals[3:6])
        a3 = np.array(vals[6:9])
        result[key if copies else key[:3]] = {
            "backbone_position": pos_nm,
            "a1": a1 / (np.linalg.norm(a1) + 1e-14),
            "a3": a3 / (np.linalg.norm(a3) + 1e-14),
        }

    return result


# oxDNA2 backbone-site offset from the centre of mass (model.h POS_MM_BACK1/2),
# in oxDNA length units.  The .dat position is the CM; the backbone sits at
# CM + POS_MM_BACK1·a1 + POS_MM_BACK2·a2 (a2 = a3 × a1).
_POS_MM_BACK1: float = -0.34
_POS_MM_BACK2: float = 0.3408


def oxdna_backbone_site(cm_nm: np.ndarray, a1: np.ndarray, a3: np.ndarray) -> np.ndarray:
    """Reconstruct a nucleotide's true backbone position (nm) from its centre of
    mass + orientation, for display.  oxDNA stores the CM (which sits inward of the
    backbone), so rendering the raw CM collapses the apparent helical diameter
    (paired backbones ~1.0 nm apart instead of ~1.6 nm) and overlaps the base-pair
    slabs.  This puts the rendered backbone where the real phosphate is."""
    a2 = np.cross(a3, a1)
    return cm_nm + (_POS_MM_BACK1 * a1 + _POS_MM_BACK2 * a2) * OXDNA_LENGTH_UNIT


def _parse_box_nm(conf_path: str | Path) -> Optional[np.ndarray]:
    """Read the oxDNA box edge lengths (`b = Lx Ly Lz`) → per-axis nm, or None."""
    for line in Path(conf_path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("b"):
            parts = s.replace("=", " ").split()
            try:
                return np.array([float(parts[1]), float(parts[2]), float(parts[3])]) * OXDNA_LENGTH_UNIT
            except (IndexError, ValueError):
                return None
    return None


def read_configuration_unwrapped(
    conf_path:      str | Path,
    design:         Design,
    reference_path: str | Path,
    *,
    align_keys: Optional[list] = None,
    rotate:     bool = True,
    align:      bool = True,
    copies:     bool = False,
) -> dict[tuple, dict]:
    """Read a relaxed oxDNA config and undo periodic-boundary wrapping for display.

    oxDNA writes coordinates wrapped into the simulation box [0, L), so an intact
    structure that straddles a box face (or whose centre-of-mass diffused into a
    far image) renders as an exploded mess of beads scattered across the box.
    This rebuilds whole molecules and re-seats them at the design location:

      1. Connect all nucleotides by backbone bonds AND designed base pairs.  In an
         origami (crossovers + WC pairs) this makes the whole structure ONE
         connected component; a bundle with no crossovers is one component per
         helix-duplex.
      2. BFS each component, placing every neighbour at the minimum-image position
         relative to its already-placed neighbour → the component is whole (never
         torn — only whole-component box shifts happen).
      3. Box-shift each whole component to the image nearest its centroid in
         *reference_path* (the initial conf.dat), then **rigid-body superpose**
         (Kabsch: best-fit rotation + translation) the whole assembly onto the
         reference.  This removes the molecule's rigid-body diffusion (drift +
         tumbling) — expected oxDNA MD motion — so the display shows the relaxed
         structure in the design's original frame, with only the internal
         relaxation visible (not the whole thing "thrown out of position").

    Returns the same shape as ``read_configuration_full`` (positions nm + a1 + a3);
    the a1/a3 orientation vectors are rotated by the same alignment.
    """
    relax = read_configuration_full(conf_path, design, copies=copies)
    ref = read_configuration_full(reference_path, design, copies=copies)
    box = _parse_box_nm(conf_path)
    if box is None or not np.all(box > 0):
        return relax
    return unwrap_align_to_reference(relax, ref, design, box,
                                     align_keys=align_keys, rotate=rotate, align=align)


def unwrap_align_to_reference(
    relax: dict[tuple, dict],
    ref:   dict[tuple, dict],
    design: Design,
    box:   np.ndarray,
    *,
    align_keys: Optional[list] = None,
    rotate:     bool = True,
    align:      bool = True,
    extra_points: Optional[list] = None,
):
    """In-memory core of read_configuration_unwrapped: BFS-unwrap each bonded
    component to whole, box-shift it toward its reference image, then superpose
    onto *ref*.  Used for display AND per-frame RMSD.

    ``align=False`` stops after the unwrap + box-shift (the structure is made whole
    and kept on-screen) but does NOT superpose onto the reference — the display
    then shows the relaxed structure in its OWN simulation frame (e.g. how it
    actually settled against a hard surface), not re-posed onto the design.

    ``align_keys`` restricts the superposition to a subset of nucleotides (e.g. a
    field run's ANCHORED beads — the fixed reference points); ``None`` uses the
    whole assembly.  ``rotate=False`` does a TRANSLATION-ONLY fit (match the subset
    centroid to its reference, no rotation), so a field-induced reorientation of
    the rest stays visible — the anchored region is a positional, not rotational,
    reference."""
    # Adjacency: backbone bonds + designed WC pairs (3-tuple keys present in relax).
    adj: dict[tuple, list[tuple]] = {k: [] for k in relax}
    for a, b in backbone_bond_pairs(design):
        if a in relax and b in relax:
            adj[a].append(b)
            adj[b].append(a)
    # Loop-insertion copies (4-tuple keys, copies=True): tie each copy to its base
    # 3-tuple (or the previous copy) so it joins the same connected component as its
    # sibling and rides the same unwrap/box-shift/superpose transform.
    for k in relax:
        if len(k) == 4:
            base = k[:3] if k[3] == 0 else (k[0], k[1], k[2], k[3] - 1)
            if base in relax:
                adj[k].append(base)
                adj[base].append(k)
    # WC pairs only between the canonical 3-tuple nucleotides (copies are unpaired
    # loop bases — keying them here would collide multiple copies onto one (h,bp)).
    fwd = {(k[0], k[1]): k for k in relax if len(k) == 3 and k[2] == "FORWARD"}
    rev = {(k[0], k[1]): k for k in relax if len(k) == 3 and k[2] == "REVERSE"}
    for hb in set(fwd) & set(rev):
        a, b = fwd[hb], rev[hb]
        adj[a].append(b)
        adj[b].append(a)

    placed: dict[tuple, np.ndarray] = {}
    for seed in relax:
        if seed in placed:
            continue
        # BFS this component, unwrapping to whole.
        comp = [seed]
        placed[seed] = relax[seed]["backbone_position"].copy()
        stack = [seed]
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v in placed:
                    continue
                p = relax[v]["backbone_position"].copy()
                placed[v] = p - box * np.round((p - placed[u]) / box)
                comp.append(v)
                stack.append(v)
        # Box-shift the whole component toward its reference image.
        ref_keys = [k for k in comp if k in ref]
        if ref_keys:
            rc = np.mean([placed[k] for k in comp], axis=0)
            oc = np.mean([ref[k]["backbone_position"] for k in ref_keys], axis=0)
            shift = box * np.round((oc - rc) / box)
            for k in comp:
                placed[k] = placed[k] + shift

    # Protein beads (extra_points): unwrap the protein as one rigid component and
    # box-shift it toward the DNA assembly (it is tethered/near the DNA), so it
    # rides through the SAME alignment transform below as the DNA.  Returned as a
    # parallel list of nm positions in the aligned display frame.
    placed_extra: list[np.ndarray] = []
    if extra_points:
        p0 = np.asarray(extra_points[0], dtype=float)
        placed_extra = [np.asarray(p, dtype=float) - box * np.round(
            (np.asarray(p, dtype=float) - p0) / box) for p in extra_points]
        if placed:
            dna_c = np.mean(list(placed.values()), axis=0)
            prot_c = np.mean(placed_extra, axis=0)
            eshift = box * np.round((dna_c - prot_c) / box)
            placed_extra = [p + eshift for p in placed_extra]

    def _ret(dna_dict: dict, xform=None):
        if extra_points is None:
            return dna_dict
        ex = [xform(p) if xform else p for p in placed_extra]
        return dna_dict, ex

    # No-align mode: structure is whole + on-screen, but left in its own frame
    # (don't re-pose onto the design — show where it actually settled).
    if not align:
        return _ret({k: {**relax[k], "backbone_position": placed[k]} for k in list(placed)})

    # Superpose onto the reference frame over the chosen subset (the anchored
    # beads for a field run, else the whole assembly).
    keys = list(placed)
    align_set = {tuple(k)[:3] for k in align_keys} if align_keys else None
    subset = [k for k in keys if (align_set is None or k in align_set) and k in ref]

    if not rotate:
        # Translation-only: match the subset centroid to its reference (anchored
        # region = fixed POSITION) without rotating — the rest's field-induced
        # reorientation stays visible.  Orientation vectors are left untouched.
        T = (np.mean([ref[k]["backbone_position"] for k in subset], axis=0)
             - np.mean([placed[k] for k in subset], axis=0)) if subset else np.zeros(3)
        return _ret({k: {**relax[k], "backbone_position": placed[k] + T} for k in keys},
                    xform=lambda p: p + T)

    # Rigid-body superpose (Kabsch) so diffusion + tumbling are removed and only
    # the internal relaxation shows.
    if len(subset) >= 3:
        P = np.array([placed[k] for k in subset])               # relaxed (mobile)
        Q = np.array([ref[k]["backbone_position"] for k in subset])  # reference (target)
        Pc, Qc = P.mean(0), Q.mean(0)
        H = (P - Pc).T @ (Q - Qc)
        U, _, Vt = np.linalg.svd(H)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T                  # rotation: relaxed → reference
        out: dict[tuple, dict] = {}
        for k in keys:
            v = relax[k]
            out[k] = {
                "backbone_position": R @ (placed[k] - Pc) + Qc,
                "a1": R @ v["a1"],
                "a3": R @ v["a3"],
            }
        return _ret(out, xform=lambda p: R @ (p - Pc) + Qc)

    return _ret({k: {**relax[k], "backbone_position": placed[k]} for k in keys})


def read_trajectory_frames_full(
    traj_path: str | Path,
    design:    Design,
    *,
    copies:    bool = False,
) -> list[dict[tuple, dict]]:
    """Parse every frame of an oxDNA trajectory (.dat) into a list of per-nucleotide
    maps (same shape as read_configuration_full: position nm + a1 + a3).  Frames are
    split on the ``t = …`` header lines.  ``copies=True`` keeps loop-insertion copies
    under their own 4-tuple key (see ``read_configuration_full``)."""
    order = _strand_nucleotide_order(design)
    lines = Path(traj_path).read_text(encoding="utf-8").splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith("t ")]
    frames: list[dict] = []
    for fi, s in enumerate(starts):
        e = starts[fi + 1] if fi + 1 < len(starts) else len(lines)
        data = [l for l in lines[s:e] if l.strip() and not l.startswith(("t ", "b ", "E "))]
        offset = _protein_lead_offset(data, order)   # skip leading protein beads (hybrid)
        m: dict[tuple, dict] = {}
        for i, key in enumerate(order):
            if offset + i >= len(data):
                break
            parts = data[offset + i].split()
            if len(parts) < 9:
                continue
            try:
                vals = [float(x) for x in parts[:9]]
            except ValueError:
                # A frame still being written by a live oxDNA run can leave a
                # half-flushed numeric token on the final line — skip it rather
                # than crash the mid-run flexibility-map / trajectory read.
                continue
            a1 = np.array(vals[3:6]); a3 = np.array(vals[6:9])
            m[key if copies else key[:3]] = {
                "backbone_position": np.array(vals[0:3]) * OXDNA_LENGTH_UNIT,
                "a1": a1 / (np.linalg.norm(a1) + 1e-14),
                "a3": a3 / (np.linalg.norm(a3) + 1e-14),
            }
        if m:
            frames.append(m)
    return frames


def count_hbonds(
    conf_path:         str | Path,
    topology_path:     str | Path,
    dnanalysis_bin:    str,
    *,
    salt_concentration: float = 0.5,
    temperature:       str = "296K",
    timeout:           int = 60,
) -> Optional[int]:
    """Count the actual Watson-Crick hydrogen bonds in *conf_path* using oxDNA's
    own ``HBList`` observable (via the ``DNAnalysis`` binary built alongside oxDNA).

    This is the ground-truth base-pair count — oxDNA's energy-based H-bond
    detector, not a geometric proxy.  Returns the bond count, or None if
    DNAnalysis is unavailable / fails (caller falls back to the geometric proxy).
    """
    import subprocess
    import tempfile

    conf_path = Path(conf_path).resolve()
    topology_path = Path(topology_path).resolve()
    inp = (
        "backend = CPU\n"
        f"conf_file = {conf_path}\n"
        f"topology = {topology_path}\n"
        f"trajectory_file = {conf_path}\n"
        "interaction_type = DNA2\n"
        f"salt_concentration = {salt_concentration}\n"
        f"T = {temperature}\n"
        "verlet_skin = 0.2\n"
        # Modified backbone potential so DNAnalysis can load strained configs
        # (NADOC backbone bonds start longer than oxDNA's standard FENE range).
        "max_backbone_force = 5\n"
        "max_backbone_force_far = 10\n"
        "analysis_data_output_1 = {\n"
        "name = stdout\n"
        "print_every = 1\n"
        "col_1 = {\n"
        "type = hb_list\n"
        "only_count = true\n"
        "}\n"
        "}\n"
    )
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(inp)
            inp_path = fh.name
        # Capture as bytes — DNAnalysis can emit non-UTF8 on stderr/stdout, which
        # would crash text mode (and the health check).  Decode leniently.
        result = subprocess.run(
            [dnanalysis_bin, inp_path],
            capture_output=True, timeout=timeout,
        )
        Path(inp_path).unlink(missing_ok=True)
        stdout = result.stdout.decode("utf-8", errors="replace")
        for line in stdout.splitlines():
            if line.strip().isdigit():
                return int(line.strip())
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def write_mutual_traps(
    design: Design,
    path:   str | Path,
    *,
    stiff:  float = 1.0,
    r0:     float = 1.2,
    extra_text: str = "",
    particle_offset: int = 0,
) -> int:
    """Write an oxDNA external-forces file with mutual traps for every designed
    Watson-Crick pair, and return the number of pairs trapped.

    The NADOC oxDNA *export* already lands designed WC pairs at their bonded geometry
    (verified 2026-06-23: a fresh export reads 42/42 H-bonds by oxDNA's own ``HBList``,
    base sites ~0.37 nm apart, ``a1·a1 = a3·a3 = −1.00``).  The problem is that a
    *free* MD lets pairs drift apart early in the relaxation and they only re-anneal
    over a long (~1e6-step) ``md_relax``.  Mutual traps hold each WC partner pair near
    CM-CM separation ``r0`` oxDNA units (stiffness ``stiff``) during the MC/MD
    relaxation stages so the pairs re-form while the backbone settles — the standard
    oxDNA relaxation aid (relaxation.html / oxView).  (A too-short md_relax never
    finishes re-annealing — see ``project_oxdna_relaxation`` 2026-06-23.)

    Designed pairs = (helix, bp) carrying both FORWARD and REVERSE nucleotides.
    Particle indices are the 0-based topology order (``_strand_nucleotide_order``),
    matching the .top file written by ``write_topology``.
    """
    order = _strand_nucleotide_order(design)
    idx = {k: i for i, k in enumerate(order)}
    fwd = {(k[0], k[1]): idx[k] for k in order if len(k) == 3 and k[2] == "FORWARD"}
    rev = {(k[0], k[1]): idx[k] for k in order if len(k) == 3 and k[2] == "REVERSE"}
    pairs = sorted(set(fwd) & set(rev))

    blocks: list[str] = []
    for key in pairs:
        # particle_offset shifts DNA indices in a hybrid topology where protein
        # beads occupy the leading particle indices (0..N_prot-1).
        i, j = fwd[key] + particle_offset, rev[key] + particle_offset
        for a, b in ((i, j), (j, i)):   # symmetric: trap each toward the other
            blocks.append(
                "{\n"
                "type = mutual_trap\n"
                f"particle = {a}\n"
                f"ref_particle = {b}\n"
                f"stiff = {stiff}\n"
                f"r0 = {r0}\n"
                "PBC = 1\n"
                "}\n"
            )
    text = "\n".join(blocks)
    # Append shared hard-surface / anchor blocks (relax-on-a-surface): the mutual
    # traps hold WC pairs while the repulsion plane + anchors keep the structure
    # bound during the same relax stage.
    if extra_text:
        text = (text + "\n" + extra_text) if text else extra_text
    Path(path).write_text(text, encoding="utf-8")
    return len(pairs)


def backbone_bond_pairs(design: Design) -> list[tuple[tuple, tuple]]:
    """
    Return consecutive (3′-neighbour) backbone-bonded nucleotide key pairs.

    Each pair is ((helix_id, bp, dir), (helix_id, bp, dir)) of two nucleotides
    adjacent along a strand backbone.  Keys are the 3-tuple form (loop copies
    collapsed to their base bp).  Used by the relaxation health check to measure
    over-stretched backbone bonds (steric-clash proxy) on a relaxed config.
    """
    pairs: list[tuple[tuple, tuple]] = []
    ls_lookup = _build_ls_lookup(design)
    for strand in design.strands:
        seq_keys: list[tuple] = []
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
                seq_keys.append((domain.helix_id, bp, domain.direction.value))
        for a, b in zip(seq_keys, seq_keys[1:]):
            pairs.append((a, b))
    return pairs


# ── Electric-field forces (uniform string force + anchor traps) ─────────────────

OXDNA_FORCE_PN: float = 48.63  # 1 oxDNA simulation force unit ≈ 48.63 pN
# Anchor-trap stiffness (oxDNA units).  Chosen high so an anchored nucleotide is
# EFFECTIVELY IMMOBILE: trap thermal jitter scales as ⟨dx²⟩≈kT/stiff, so 1000
# pins each anchored bead to ~0.03 nm RMS (≈10× below normal bead motion) while
# staying MD-stable at the field stage's dt (dt·√stiff≈0.16 ≪ 2).  Empirically
# verified on 1hb_efield_test: drift 0.35 nm @5 → 0.027 nm @1000, run still completes.
DEFAULT_ANCHOR_STIFF: float = 1000.0


def pn_to_oxdna_force(pn: float) -> float:
    """Force per nucleotide: pN → oxDNA simulation force units."""
    return float(pn) / OXDNA_FORCE_PN


def _normalize3(v) -> list[float]:
    a = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(a))
    return (a / n).tolist() if n > 1e-12 else [0.0, 0.0, 0.0]


def _strand_nucleotide_provenance(design: Design) -> list[dict]:
    """Like :func:`_strand_nucleotide_order` but tags each nucleotide with the
    strand / domain / overhang it came from, in the SAME order (so the list index
    IS the 0-based oxDNA particle index).  Lets anchor selections (cluster /
    domain / overhang) resolve to particle indices without re-deriving the
    topology traversal."""
    ls_lookup = _build_ls_lookup(design)
    prov: list[dict] = []
    for strand in design.strands:
        for di, domain in enumerate(strand.domains):
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            bp_range = (range(lo, hi + 1) if domain.direction == Direction.FORWARD
                        else range(hi, lo - 1, -1))
            for bp in bp_range:
                delta = ls_lookup.get((domain.helix_id, bp), 0)
                if delta <= -1:
                    continue
                n_copies = max(1, delta + 1)
                for k in range(n_copies):
                    key = ((domain.helix_id, bp, domain.direction.value)
                           if n_copies == 1
                           else (domain.helix_id, bp, domain.direction.value, k))
                    prov.append({
                        "particle":     len(prov),
                        "strand_id":    strand.id,
                        "domain_index": di,
                        "helix_id":     domain.helix_id,
                        "bp":           bp,
                        "direction":    domain.direction.value,
                        "overhang_id":  domain.overhang_id,
                        "key":          key,
                    })
    return prov


def resolve_anchor_particles(
    design: Design, anchors: list[dict]
) -> tuple[list[int], list[tuple]]:
    """Resolve anchor descriptors to (sorted particle indices, their keys).

    Descriptor kinds (the three scopes the UI offers — overhang recommended):
      ``{'kind':'overhang', 'id': <overhang_id>}`` → nucleotides of the domains
          whose ``overhang_id`` matches (the surface-tethered overhang).
      ``{'kind':'cluster',  'id': <cluster_id>}``  → nucleotides on any helix in
          the cluster's ``helix_ids``.
      ``{'kind':'domain', 'strand_id'|'strandId', 'domain_index'|'domainIndex'}``
          → that one domain's nucleotides.

    Unknown ids / kinds contribute nothing, so a stale selection silently drops
    rather than raising.  Particle indices match the topology / configuration
    order (:func:`_strand_nucleotide_order`)."""
    prov = _strand_nucleotide_provenance(design)
    cluster_helices = {c.id: set(c.helix_ids) for c in design.cluster_transforms}
    selected: dict[int, tuple] = {}
    for a in anchors or []:
        kind = a.get("kind")
        if kind == "overhang":
            oid = a.get("id")
            for p in prov:
                if p["overhang_id"] == oid:
                    selected[p["particle"]] = p["key"]
        elif kind == "cluster":
            helset = cluster_helices.get(a.get("id"), set())
            for p in prov:
                if p["helix_id"] in helset:
                    selected[p["particle"]] = p["key"]
        elif kind == "domain":
            sid = a.get("strand_id", a.get("strandId"))
            didx = a.get("domain_index", a.get("domainIndex"))
            for p in prov:
                if p["strand_id"] == sid and p["domain_index"] == didx:
                    selected[p["particle"]] = p["key"]
    parts = sorted(selected)
    return parts, [selected[i] for i in parts]


def read_cm_positions_oxdna(conf_path: str | Path) -> list[list[float]]:
    """Per-particle centre-of-mass positions (oxDNA simulation units, topology
    order) parsed from a configuration file — the first three numbers of each
    particle line.  Used as anchor-trap rest positions so an anchor pins a
    nucleotide to exactly where it sits at the start of the field stage."""
    lines = Path(conf_path).read_text().splitlines()
    out: list[list[float]] = []
    for ln in lines[3:]:  # skip the t= / b= / E= header
        parts = ln.split()
        if len(parts) < 3:
            continue
        out.append([float(parts[0]), float(parts[1]), float(parts[2])])
    return out


def field_string_block(field_oxdna: float, field_dir) -> str:
    """An oxDNA ``string`` force (constant ``field_oxdna`` along ``field_dir``)
    applied to EVERY nucleotide (``particle = -1``).  A uniform electric field
    acts equally on each (uniformly-charged) backbone bead.  Anchored nucleotides
    feel the field too, but their high-stiffness traps hold them immobile against
    it (oxDNA's ConstantRateForce rejects range particle-specs, so excluding
    anchors from the field isn't viable — and the trap dominates regardless)."""
    dx, dy, dz = _normalize3(field_dir)
    return ("{\n"
            "type = string\n"
            "particle = -1\n"
            f"F0 = {field_oxdna:.6g}\n"
            "rate = 0\n"
            f"dir = {dx:.6g},{dy:.6g},{dz:.6g}\n"
            "}\n")


def anchor_trap_block(particle: int, pos0, stiff: float) -> str:
    """A static harmonic ``trap`` pinning ``particle`` to ``pos0`` (oxDNA units).
    ``rate = 0`` → the trap does not move; ``dir`` is the (unused) move direction."""
    x, y, z = float(pos0[0]), float(pos0[1]), float(pos0[2])
    return ("{\n"
            "type = trap\n"
            f"particle = {particle}\n"
            f"pos0 = {x:.6g},{y:.6g},{z:.6g}\n"
            f"stiff = {stiff:.6g}\n"
            "rate = 0\n"
            "dir = 1,0,0\n"
            "}\n")


def write_field_forces(
    path: str | Path,
    design: Design,
    conf_path: str | Path,
    *,
    field_oxdna: float,
    field_dir,
    anchors: list[dict],
    anchor_stiff: float = DEFAULT_ANCHOR_STIFF,
) -> dict:
    """Write the external-forces file for an electric-field stage: one uniform
    ``string`` force on all nucleotides + a static ``trap`` pinning every anchored
    nucleotide to its position in ``conf_path`` (the configuration the field stage
    starts from).

    Anchors are required — an unanchored uniform force nets a centre-of-mass drift
    that streams the whole structure across the periodic box (see
    ``memory/project_oxdna_efield.md`` GOTCHA 1).  Raises ``ValueError`` if the
    anchor selection resolves to zero nucleotides.

    Returns ``{n_anchored, n_total, field_oxdna, dir, anchor_particles}``."""
    particles, anchor_keys = resolve_anchor_particles(design, anchors)
    if not particles:
        raise ValueError(
            "an electric-field stage needs ≥1 anchor; the selection resolved to "
            "no nucleotides (without an anchor the field just drifts the whole "
            "structure across the box)")
    cm = read_cm_positions_oxdna(conf_path)
    n_total = len(cm)
    blocks: list[str] = [field_string_block(field_oxdna, field_dir)]
    for p in particles:
        if p < n_total:
            blocks.append(anchor_trap_block(p, cm[p], anchor_stiff))
    Path(path).write_text("\n".join(blocks), encoding="utf-8")
    return {
        "n_anchored": len(particles),
        "n_total": n_total,
        "field_oxdna": float(field_oxdna),
        "dir": _normalize3(field_dir),
        "anchor_particles": particles,
        # 3-tuple nucleotide keys (helix, bp, direction) of the anchored beads —
        # the display uses these as a positional (non-rotational) alignment frame.
        "anchor_keys": [list(k[:3]) for k in anchor_keys],
    }


def repulsion_plane_block(stiff: float, plane_dir, position: float) -> str:
    """An oxDNA ``repulsion_plane`` external force — a one-sided hard wall.

    The plane is ``dir·r + position = 0``; particles are confined to the half-space
    where ``dir·r + position >= 0`` (the side ``dir`` points toward).  A particle that
    crosses to the forbidden side feels ``F = -stiff·(dir·r + position)·dir`` pushing
    it back; zero force on the allowed side.  ``particle = -1`` applies it to every
    nucleotide, so the whole structure rests on the surface."""
    dx, dy, dz = _normalize3(plane_dir)
    return ("{\n"
            "type = repulsion_plane\n"
            "particle = -1\n"
            f"stiff = {float(stiff):.6g}\n"
            f"dir = {dx:.6g},{dy:.6g},{dz:.6g}\n"
            f"position = {float(position):.6g}\n"
            "}\n")


def wall_position_from_extent(cm_positions, wall_dir, offset_oxdna: float = 0.0):
    """Derive the repulsion-plane ``position`` scalar so the wall sits just past the
    structure's lowest point along ``wall_dir`` (everything in oxDNA units).

    ``cm_positions`` are the centre-of-mass positions (oxDNA units, e.g. from
    :func:`read_cm_positions_oxdna`).  The plane is placed at the minimum projection
    onto ``wall_dir`` minus ``offset_oxdna`` (a positive offset gives the structure
    clearance above the surface), so the whole structure starts on the allowed side.

    Returns ``(position, min_proj)`` where ``position = offset_oxdna - min_proj`` makes
    ``dir·r + position >= 0`` for every nucleotide at the seed configuration."""
    dx, dy, dz = _normalize3(wall_dir)
    projs = [p[0] * dx + p[1] * dy + p[2] * dz for p in cm_positions]
    min_proj = min(projs) if projs else 0.0
    return offset_oxdna - min_proj, min_proj


def write_run_forces(
    path: str | Path,
    design: Design,
    conf_path: str | Path,
    *,
    field: dict | None = None,
    wall: dict | None = None,
    anchors: list[dict] | None = None,
    anchor_stiff: float = DEFAULT_ANCHOR_STIFF,
) -> dict:
    """Write the external-forces file for a composed production run: any combination
    of a uniform ``string`` field (all nucleotides), a ``repulsion_plane`` hard
    surface (all nucleotides), and ``trap`` anchors pinning selected nucleotides.

    ``field`` is ``{"force_oxdna": f, "dir": [x,y,z]}`` or None; ``wall`` is
    ``{"dir": [x,y,z], "offset_nm": d, "stiff": s}`` or None; ``anchors`` is the
    anchor-descriptor list.  Each element is independent — pass only the ones the
    user enabled.  Anchor traps pin to each particle's position in ``conf_path``
    (the configuration the run starts from).

    Returns ``{n_anchored, n_total, anchor_particles, anchor_keys, field, wall,
    has_forces}`` (``field``/``wall`` are the resolved meta dicts, or None)."""
    sa_text, info = surface_anchor_forces_text(
        design, conf_path, wall=wall, anchors=anchors, anchor_stiff=anchor_stiff)

    field_text = ""
    field_meta = None
    if field:
        f_oxdna = float(field.get("force_oxdna", 0.0))
        if f_oxdna > 0:
            field_text = field_string_block(f_oxdna, field.get("dir"))
            field_meta = {"force_oxdna": f_oxdna, "dir": _normalize3(field.get("dir"))}

    parts = [t for t in (field_text, sa_text) if t]   # field first, then wall + anchors
    Path(path).write_text("\n".join(parts), encoding="utf-8")
    return {**info, "field": field_meta, "has_forces": bool(parts)}


def surface_anchor_forces_text(
    design: Design,
    conf_path: str | Path,
    *,
    wall: dict | None = None,
    anchors: list[dict] | None = None,
    anchor_stiff: float = DEFAULT_ANCHOR_STIFF,
) -> tuple[str, dict]:
    """Compose the hard-surface ``repulsion_plane`` + anchor ``trap`` block text —
    the part shared by the relax-stage forces and the production-run forces (a
    structure relaxed on a surface differs from one relaxed free, so relaxation
    carries these too; only the electric field is production-only).

    The wall plane is placed from the structure's extent in ``conf_path`` and the
    anchor traps pin to their positions there.  Returns ``(text, info)`` where
    ``info`` = ``{n_anchored, n_total, anchor_particles, anchor_keys, wall}``."""
    anchors = anchors or []
    if anchors:
        particles, anchor_keys = resolve_anchor_particles(design, anchors)
    else:
        particles, anchor_keys = [], []
    cm = read_cm_positions_oxdna(conf_path)
    n_total = len(cm)

    blocks: list[str] = []
    wall_meta = None
    if wall:
        stiff = float(wall.get("stiff", 0.0))
        if stiff > 0:
            offset_nm = float(wall.get("offset_nm", 0.0))
            position, min_proj = wall_position_from_extent(
                cm, wall.get("dir"), offset_nm * NM_TO_OXDNA)
            blocks.append(repulsion_plane_block(stiff, wall.get("dir"), position))
            wall_meta = {
                "dir": _normalize3(wall.get("dir")), "stiff": stiff,
                "offset_nm": offset_nm, "position": position, "min_proj": min_proj,
            }

    for p in particles:
        if p < n_total:
            blocks.append(anchor_trap_block(p, cm[p], anchor_stiff))

    return "\n".join(blocks), {
        "n_anchored": len(particles),
        "n_total": n_total,
        "anchor_particles": particles,
        "anchor_keys": [list(k[:3]) for k in anchor_keys],
        "wall": wall_meta,
    }


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
