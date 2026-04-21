"""
NADOC → mrdna SegmentModel bridge.

Converts a NADOC Design object directly to an mrdna SegmentModel without
any intermediate cadnano or scadnano file conversion.

Usage::

    from backend.core.mrdna_bridge import mrdna_model_from_nadoc
    model = mrdna_model_from_nadoc(design)
    model.simulate(output_name='my_design', directory='/tmp/mrdna_out')

mrdna and its dependencies must be installed (see docs/mrdna_setup.md).

Coordinate convention: NADOC uses nm; mrdna uses Ångströms (×10).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.core.constants import (
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    BDNA_RISE_PER_BP,
    HELIX_RADIUS,
)
from backend.core.models import Design, Direction
from backend.core.sequences import _build_loop_skip_map, domain_bp_range

_NM_TO_ANGSTROM = 10.0


_MRDNA_TOOL_PATH = "/tmp/mrdna-tool"


def _ensure_mrdna() -> None:
    """Add mrdna's install path to sys.path if not already importable."""
    import sys
    try:
        import mrdna  # noqa: F401
    except ImportError:
        if _MRDNA_TOOL_PATH not in sys.path:
            sys.path.insert(0, _MRDNA_TOOL_PATH)


def mrdna_model_from_nadoc(design: Design, *, return_nt_key: bool = False, **model_params):
    """
    Convert a NADOC Design to an mrdna SegmentModel.

    Parameters
    ----------
    return_nt_key : bool
        If True, return (model, nt_index_to_key) where nt_index_to_key is a
        list mapping each bead index → (helix_id, bp_index, direction_str).
        Useful for mapping ARBD simulation positions back to NADOC nucleotides.

    Returns an mrdna SegmentModel ready for .simulate() or atomistic output.
    (or a (model, nt_index_to_key) tuple when return_nt_key=True)
    """
    _ensure_mrdna()
    from mrdna.readers.segmentmodel_from_lists import model_from_basepair_stack_3prime

    r, bp, stack, three_prime, orientation, seq, nt_key = _build_nt_arrays(
        design, return_nt_key=True
    )
    model = model_from_basepair_stack_3prime(
        r, bp, stack, three_prime,
        sequence=seq,
        orientation=orientation,
        **model_params,
    )
    if return_nt_key:
        # Invert nt_key: bead index → (h_id, bp_idx, direction_str)
        # Only k==0 entries; loop copies (k>0) map to the same key without k.
        index_to_key: List[Optional[Tuple[str, int, str]]] = [None] * len(r)
        for (h_id, bp_idx, direction, k), idx in nt_key.items():
            if k == 0:
                index_to_key[idx] = (h_id, bp_idx, direction)
        return model, index_to_key
    return model


def nuc_pos_override_from_mrdna(
    design: Design,
    psf_path: str,
    dcd_path: str,
    frame: int = -1,
    sigma_nt: float = 2.0,
) -> "dict[tuple[str,int,str], np.ndarray]":
    """
    Read CG bead positions from an mrdna ARBD simulation (fine stage, 1bp/bead)
    and return a nuc_pos_override dict for use in build_gromacs_package.

    The fine-stage DCD has one bead per nucleotide at 1nt/bead resolution.
    Bead positions map directly to (helix_id, bp_index, direction) keys via the
    nt_key built during model construction.  Gaussian smoothing (sigma_nt nt)
    is applied per helix domain to suppress ARBD thermal noise (~0.1-0.3 Å/nt)
    while preserving crossover junction geometry.

    Parameters
    ----------
    design    : NADOC Design used to generate the mrdna model.
    psf_path  : Path to the fine-stage PSF (e.g. u6hb_v3-2.psf).
    dcd_path  : Path to the fine-stage DCD (e.g. output/u6hb_v3-2.dcd).
    frame     : DCD frame to read (-1 = last frame, coordinate averaged if available).
    sigma_nt  : Gaussian smoothing width in nucleotides.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → position in nm
    """
    import sys
    sys.path.insert(0, _MRDNA_TOOL_PATH)
    import MDAnalysis as mda
    from scipy.ndimage import gaussian_filter1d

    # Rebuild nt_key — fast since we don't run simulation, just build arrays.
    _, _, _, _, _, _, nt_key = _build_nt_arrays(design, return_nt_key=True)

    # Invert: bead index → (h_id, bp_idx, dir, k)
    n_beads = max(idx for idx in nt_key.values()) + 1
    index_to_key: list = [None] * n_beads
    for (h_id, bp_idx, direction, k), idx in nt_key.items():
        index_to_key[idx] = (h_id, bp_idx, direction, k)

    # Read bead positions from DCD
    u     = mda.Universe(psf_path, dcd_path)
    atoms = u.select_atoms('all')
    traj  = u.trajectory
    if frame == -1:
        traj[-1]
    else:
        traj[frame]
    bead_positions_ang = atoms.positions.copy()  # (N_beads, 3) in Å

    # Group raw positions by domain (helix + direction) for smoothing,
    # preserving insertion order (5'→3' within each domain).
    from collections import defaultdict
    domain_indices: dict = defaultdict(list)   # (h_id, dir) → [(bp_idx, bead_idx)]
    for bead_idx, key in enumerate(index_to_key):
        if key is None:
            continue
        h_id, bp_idx, direction, k = key
        if k == 0:   # skip loop copies — use first copy as representative
            domain_indices[(h_id, direction)].append((bp_idx, bead_idx))

    # Sort each domain by bp_idx so smoothing is along the helix axis.
    for domain_key in domain_indices:
        domain_indices[domain_key].sort(key=lambda x: x[0])

    # Smooth and populate override dict (positions in nm).
    override: dict[tuple, np.ndarray] = {}
    for (h_id, direction), bp_bead_list in domain_indices.items():
        bp_indices  = [x[0] for x in bp_bead_list]
        bead_idxs   = [x[1] for x in bp_bead_list]
        raw_pos     = np.array([bead_positions_ang[i] for i in bead_idxs])  # Å

        if len(raw_pos) >= 3 and sigma_nt > 0:
            smoothed = gaussian_filter1d(raw_pos, sigma=sigma_nt, axis=0, mode='nearest')
        else:
            smoothed = raw_pos

        for bp_idx, pos_ang in zip(bp_indices, smoothed):
            override[(h_id, bp_idx, direction)] = pos_ang / 10.0  # Å → nm

    return override


# ── Internal helpers ──────────────────────────────────────────────────────────

# Cache for (x_hat, y_hat) perpendicular frames per helix axis direction.
_xy_frame_cache: Dict[tuple, Tuple[np.ndarray, np.ndarray]] = {}


def _xy_frame(axis_hat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return two orthonormal vectors perpendicular to axis_hat."""
    key = tuple(np.round(axis_hat, 8))
    if key not in _xy_frame_cache:
        ref = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(axis_hat, ref)) > 0.9:
            ref = np.array([1.0, 0.0, 0.0])
        x_hat = np.cross(ref, axis_hat)
        x_hat /= np.linalg.norm(x_hat)
        y_hat = np.cross(axis_hat, x_hat)
        _xy_frame_cache[key] = (x_hat, y_hat)
    return _xy_frame_cache[key]


def _radial(angle: float, x_hat: np.ndarray, y_hat: np.ndarray) -> np.ndarray:
    return math.cos(angle) * x_hat + math.sin(angle) * y_hat


def _orientation_matrix(
    radial: np.ndarray, axis_hat: np.ndarray
) -> np.ndarray:
    """3×3 orientation matrix with columns [radial, azimuthal, axis_hat]."""
    azimuthal = np.cross(axis_hat, radial)
    return np.column_stack([radial, azimuthal, axis_hat])


def _build_nt_arrays(
    design: Design,
    return_nt_key: bool = False,
):
    """
    Build the per-nucleotide arrays required by model_from_basepair_stack_3prime.

    Returns
    -------
    r          : (N,3) float  — backbone positions in Ångströms
    bp         : (N,)  int   — base-pair partner index (−1 if unpaired)
    stack      : (N,)  int   — 3′-stacking neighbour index (−1 if none)
    three_prime: (N,)  int   — 3′-phosphodiester neighbour index (−1 for 3′ end)
    orientation: (N,3,3) float — local nucleotide orientation matrices
    seq        : list[str] or None — sequence characters
    nt_key     : dict (h_id, bp_idx, dir_str, k) → index  (only if return_nt_key=True)
    """
    ls_map = _build_loop_skip_map(design)
    helix_by_id = {h.id: h for h in design.helices}

    # Pre-compute per-helix axis geometry once.
    helix_geom: Dict[str, tuple] = {}
    for h in design.helices:
        ax_s = h.axis_start.to_array()
        ax_e = h.axis_end.to_array()
        axis_hat = ax_e - ax_s
        axis_hat /= np.linalg.norm(axis_hat)
        # Grove offset sign: +GROOVE for FORWARD helix, −GROOVE for REVERSE/None
        groove = (BDNA_MINOR_GROOVE_ANGLE_RAD
                  if h.direction == Direction.FORWARD
                  else -BDNA_MINOR_GROOVE_ANGLE_RAD)
        helix_geom[h.id] = (ax_s, axis_hat, h.phase_offset, h.twist_per_bp_rad, h.bp_start, groove)

    # ── Pass 1: enumerate nucleotides and assign indices ──────────────────────
    # Index map: (helix_id, bp_index, 'FORWARD'|'REVERSE') → global nt index
    nt_key: Dict[Tuple[str, int, str], int] = {}

    positions: List[np.ndarray] = []
    orientations: List[np.ndarray] = []
    seq_chars: List[str] = []

    # Per-strand list of global indices in 5′→3′ order.
    strand_seqs: List[List[int]] = []

    has_sequence = any(s.sequence is not None for s in design.strands)

    for strand in design.strands:
        strand_indices: List[int] = []
        seq_offset = 0

        for domain in strand.domains:
            h_id = domain.helix_id
            ax_s, axis_hat, phase_offset, twist, bp_start, groove = helix_geom[h_id]
            x_hat, y_hat = _xy_frame(axis_hat)
            direction = domain.direction.value  # 'FORWARD' or 'REVERSE'

            for bp_idx in domain_bp_range(domain):
                delta = ls_map.get((h_id, bp_idx), 0)
                if delta <= -1:
                    continue  # skip — no nucleotide at this position

                local_i = bp_idx - bp_start
                # delta=0 → 1 copy; delta=+1 → 2 copies evenly straddling the bp.
                n_copies = max(1, delta + 1)

                # REVERSE strand moves in −axis direction; loop copies must be
                # encountered k=1 (higher axial) first, then k=0 (lower axial).
                k_range = (range(n_copies - 1, -1, -1)
                           if direction == 'REVERSE' else range(n_copies))
                for k in k_range:
                    # Axial offset: same formula as geometry.py nucleotide_positions().
                    copy_frac = (k - (n_copies - 1) / 2.0) if n_copies > 1 else 0.0
                    axis_pt = ax_s + (local_i * BDNA_RISE_PER_BP
                                      + copy_frac * BDNA_RISE_PER_BP) * axis_hat

                    # Twist angle: use integer local_i (same as geometry.py).
                    fwd_angle = phase_offset + local_i * twist
                    angle = fwd_angle if direction == 'FORWARD' else fwd_angle + groove

                    rad = _radial(angle, x_hat, y_hat)
                    backbone_ang = (axis_pt + HELIX_RADIUS * rad) * _NM_TO_ANGSTROM
                    orient = _orientation_matrix(rad, axis_hat)

                    char = 'N'
                    if strand.sequence is not None and seq_offset < len(strand.sequence):
                        char = strand.sequence[seq_offset]
                    seq_offset += 1  # one sequence character per copy

                    idx = len(positions)
                    nt_key[(h_id, bp_idx, direction, k)] = idx
                    positions.append(backbone_ang)
                    orientations.append(orient)
                    seq_chars.append(char)
                    strand_indices.append(idx)

        strand_seqs.append(strand_indices)

    N = len(positions)
    if N == 0:
        raise ValueError("Design has no nucleotides (all bases skipped?).")

    r = np.array(positions, dtype=float)
    orient_arr = np.array(orientations, dtype=float)

    # ── Pass 2: base-pair array ───────────────────────────────────────────────
    bp_arr = -np.ones(N, dtype=int)
    for (h_id, bp_idx, direction, k), idx in nt_key.items():
        partner_dir = 'REVERSE' if direction == 'FORWARD' else 'FORWARD'
        partner_idx = nt_key.get((h_id, bp_idx, partner_dir, k), -1)
        bp_arr[idx] = partner_idx

    # ── Pass 3: 3′-phosphodiester array ──────────────────────────────────────
    three_prime_arr = -np.ones(N, dtype=int)
    for indices in strand_seqs:
        for i in range(len(indices) - 1):
            three_prime_arr[indices[i]] = indices[i + 1]

    # ── Pass 4: stacking array ────────────────────────────────────────────────
    # Within a domain, consecutive nucleotides stack (prev → current).
    # At domain end, check for intrahelical continuation on the same helix
    # (two adjacent domains on the same helix: nicked helix case).
    stack_arr = -np.ones(N, dtype=int)

    for strand in design.strands:
        for domain in strand.domains:
            h_id = domain.helix_id
            direction = domain.direction.value
            prev_idx: Optional[int] = None

            for bp_idx in domain_bp_range(domain):
                delta = ls_map.get((h_id, bp_idx), 0)
                if delta <= -1:
                    continue

                n_copies = max(1, delta + 1)
                k_range = (range(n_copies - 1, -1, -1)
                           if direction == 'REVERSE' else range(n_copies))
                for k in k_range:
                    idx = nt_key.get((h_id, bp_idx, direction, k))
                    if idx is None:
                        continue
                    if prev_idx is not None:
                        stack_arr[prev_idx] = idx
                    prev_idx = idx

            # Check for intrahelical continuation past the domain end.
            if prev_idx is not None:
                next_bp = (domain.end_bp + 1
                           if direction == 'FORWARD'
                           else domain.end_bp - 1)
                # For REVERSE direction, the first copy encountered is k=n_copies-1.
                next_delta = ls_map.get((h_id, next_bp), 0)
                next_n_copies = max(1, next_delta + 1) if next_delta > -1 else 0
                next_k = 0 if direction == 'FORWARD' else next_n_copies - 1
                next_idx = nt_key.get((h_id, next_bp, direction, next_k))
                if next_idx is not None:
                    stack_arr[prev_idx] = next_idx

    seq_list = seq_chars if has_sequence else None
    if return_nt_key:
        return r, bp_arr, stack_arr, three_prime_arr, orient_arr, seq_list, nt_key
    return r, bp_arr, stack_arr, three_prime_arr, orient_arr, seq_list
