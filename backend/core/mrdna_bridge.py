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
    Read CG bead positions from an mrdna ARBD simulation (fine stage) and
    return a nuc_pos_override dict for use in build_gromacs_package.

    The fine stage has one (DNA, O) bead PAIR per base pair:
      - DNA bead ≈ FORWARD strand backbone position (~5 Å from helix axis)
      - O bead   ≈ orientation indicator at 1.5 Å, pointing OPPOSITE to FORWARD

    Mapping strategy (axis-line assignment):
      Each DNA bead is assigned to the nearest NADOC helix by perpendicular
      distance to the helix axis-line, and the bp index is computed from the
      axial projection.  Smoothing is applied per helix to suppress ARBD noise.
      The INITIAL fine model PDB (same stem as psf_path with .pdb extension)
      must be in the NADOC coordinate frame; the DCD can be from any subsequent
      run on the same topology.

    FORWARD override = DNA bead position (encodes relaxed twist angle).
    REVERSE override = ideal axis point + HELIX_RADIUS × rot(FWD_radial, 150°),
                       preserving the mrdna-derived helical axis position.

    Parameters
    ----------
    design    : NADOC Design used to generate the mrdna model.
    psf_path  : Fine-stage PSF whose companion .pdb is in NADOC coordinate frame.
    dcd_path  : Fine-stage DCD to read simulation positions from.
    frame     : DCD frame to read (-1 = last frame).
    sigma_nt  : Gaussian smoothing width in base pairs.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → position in nm
    """
    import sys
    sys.path.insert(0, _MRDNA_TOOL_PATH)
    import MDAnalysis as mda
    from collections import defaultdict
    from scipy.ndimage import gaussian_filter1d

    # ── Step 1: helix axis geometry ────────────────────────────────────────
    helix_info: dict = {}   # h_id → (ax_s_ang, axis_hat, bp_start)
    for h in design.helices:
        ax_s = h.axis_start.to_array() * 10.0   # nm → Å
        ax_e = h.axis_end.to_array()   * 10.0
        v = ax_e - ax_s
        axis_hat = v / np.linalg.norm(v)
        helix_info[h.id] = (ax_s, axis_hat, h.bp_start)

    h_ids     = list(helix_info.keys())
    ax_s_arr  = np.array([helix_info[h][0] for h in h_ids])   # (H, 3)
    axhat_arr = np.array([helix_info[h][1] for h in h_ids])   # (H, 3)

    # ── Step 2: build axis-line assignment from initial fine PDB ──────────
    # The initial PDB must be in NADOC coordinate frame.
    init_pdb = psf_path.replace(".psf", ".pdb")
    u_init   = mda.Universe(psf_path, init_pdb)
    init_pos = u_init.atoms.positions                           # (N_beads, 3) Å
    init_names = np.array([a.name for a in u_init.atoms])
    dna_init_idx = np.where(init_names == 'DNA')[0]
    dna_init_pos = init_pos[dna_init_idx]                       # (N_dna, 3)

    # Perpendicular distance from each DNA bead to each helix axis-line
    n_dna     = len(dna_init_pos)
    n_helices = len(h_ids)
    perp = np.zeros((n_dna, n_helices), dtype=float)
    proj = np.zeros((n_dna, n_helices), dtype=float)
    for j in range(n_helices):
        diff = dna_init_pos - ax_s_arr[j]           # (N, 3)
        axial = (diff * axhat_arr[j]).sum(axis=1)   # (N,)
        perp_vec = diff - axial[:, None] * axhat_arr[j]
        perp[:, j] = np.linalg.norm(perp_vec, axis=1)
        proj[:, j] = axial

    best_j    = perp.argmin(axis=1)                 # (N_dna,) best helix index
    best_perp = perp[np.arange(n_dna), best_j]
    best_proj = proj[np.arange(n_dna), best_j]

    # bp_idx from axial projection
    bp_idx_arr = np.zeros(n_dna, dtype=int)
    for i in range(n_dna):
        j = best_j[i]
        bp_start = helix_info[h_ids[j]][2]
        bp_idx_arr[i] = int(round(bp_start + best_proj[i] / (BDNA_RISE_PER_BP * 10.0)))

    # Build mapping: (h_id, bp_idx) → pair_i with smallest perp distance
    bp_to_pair: dict = {}   # (h_id, bp_idx) → (pair_i, perp)
    for pair_i in range(n_dna):
        h_id   = h_ids[best_j[pair_i]]
        bp_idx = bp_idx_arr[pair_i]
        perp_d = best_perp[pair_i]
        key    = (h_id, bp_idx)
        if key not in bp_to_pair or perp_d < bp_to_pair[key][1]:
            bp_to_pair[key] = (pair_i, perp_d)

    # ── Step 3: read DCD simulation frame ─────────────────────────────────
    u     = mda.Universe(psf_path, dcd_path)
    atoms = u.select_atoms('all')
    if frame == -1:
        u.trajectory[-1]
    else:
        u.trajectory[frame]
    positions  = atoms.positions.copy()              # (N_beads, 3) Å
    atom_names = np.array([a.name for a in atoms])
    dna_sim_idx = np.where(atom_names == 'DNA')[0]
    dna_sim_pos = positions[dna_sim_idx]             # (N_dna, 3) Å

    # ── Step 4: group by helix, smooth, compute overrides ─────────────────
    helix_entries: dict = defaultdict(list)   # h_id → [(bp_idx, pair_i)]
    for (h_id, bp_idx), (pair_i, _) in bp_to_pair.items():
        helix_entries[h_id].append((bp_idx, pair_i))
    for entries in helix_entries.values():
        entries.sort(key=lambda x: x[0])

    def _rotate(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
        c, s = math.cos(angle), math.sin(angle)
        return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1.0 - c)

    helix_radius_ang = HELIX_RADIUS * 10.0

    override: dict[tuple, np.ndarray] = {}

    for h_id, entries in helix_entries.items():
        ax_s, axis_hat, bp_start = helix_info[h_id]

        bp_idxs = [e[0] for e in entries]
        pair_is = [e[1] for e in entries]

        dna_raw = np.array([dna_sim_pos[pi] for pi in pair_is], dtype=float)

        if len(dna_raw) >= 3 and sigma_nt > 0:
            dna_sm = gaussian_filter1d(dna_raw, sigma=sigma_nt, axis=0, mode='nearest')
        else:
            dna_sm = dna_raw

        for bp_idx, dna_p in zip(bp_idxs, dna_sm):
            local_i  = bp_idx - bp_start
            # Ideal helix axis point at this bp (Å) — axial position is fixed to
            # ideal B-DNA spacing; only the radial direction comes from mrdna.
            axis_pt  = ax_s + local_i * (BDNA_RISE_PER_BP * 10.0) * axis_hat
            radial   = dna_p - axis_pt
            radial_ax = np.dot(radial, axis_hat)
            radial_perp = radial - radial_ax * axis_hat
            rp_norm  = np.linalg.norm(radial_perp)
            if rp_norm < 1e-6:
                continue
            fwd_radial_hat = radial_perp / rp_norm

            # FORWARD: place at ideal axis + HELIX_RADIUS in mrdna twist direction.
            # _atom_frame will rescale radius to _ATOMISTIC_P_RADIUS automatically.
            # Axial displacement is stripped so thermal fluctuations of CG beads
            # do not propagate into backbone bond lengths.
            fwd_ang = axis_pt + helix_radius_ang * fwd_radial_hat
            override[(h_id, bp_idx, 'FORWARD')] = fwd_ang / 10.0   # Å → nm

            # REVERSE: rotate fwd_radial by minor groove angle about ideal axis.
            rev_radial_hat = _rotate(fwd_radial_hat, axis_hat, BDNA_MINOR_GROOVE_ANGLE_RAD)
            rev_ang = axis_pt + helix_radius_ang * rev_radial_hat
            override[(h_id, bp_idx, 'REVERSE')] = rev_ang / 10.0  # Å → nm

    xover_keys = _crossover_junction_keys(design)
    override = {k: v for k, v in override.items() if k not in xover_keys}
    print(
        f"[mrdna fine] {len(override)} override entries after crossover exclusion "
        f"({len(xover_keys)} crossover keys removed)",
        flush=True,
    )
    return override


def nuc_pos_override_from_mrdna_coarse(
    design: Design,
    psf_path: str,
    dcd_path: str,
    frame: int = -1,
    sigma_nt: float = 1.0,
) -> "dict[tuple[str,int,str], np.ndarray]":
    """
    Phase 3b: per-helix cubic spline reconstruction from the mrdna COARSE stage.

    Works for large deformations (U-shape folds, etc.) where fine-model axis-line
    matching fails.  Each coarse DNA bead (5 bp/bead) is a base-pair centroid ≈
    helix axis position.  A per-helix cubic spline is fitted through the sorted
    bead positions and evaluated at every NADOC bp position, giving a smooth
    relaxed helix axis trajectory.  FORWARD and REVERSE nucleotide positions are
    placed at HELIX_RADIUS from the spline axis, using the ideal B-DNA twist angle
    projected onto the plane perpendicular to the spline tangent.

    Parameters
    ----------
    design    : NADOC Design used to generate the mrdna model.
    psf_path  : Coarse-stage PSF whose companion .pdb is in NADOC coordinate frame.
    dcd_path  : Coarse-stage DCD to read simulation positions from.
    frame     : DCD frame to read (-1 = last frame).
    sigma_nt  : Gaussian smoothing (in coarse beads) before spline fitting; default 1.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → position in nm
    """
    import sys
    sys.path.insert(0, _MRDNA_TOOL_PATH)
    import MDAnalysis as mda
    from collections import defaultdict
    from scipy.interpolate import CubicSpline
    from scipy.ndimage import gaussian_filter1d

    # ── Step 1: helix axis geometry ────────────────────────────────────────
    helix_info: dict = {}   # h_id → (ax_s_ang, axis_hat, bp_start, length_bp)
    for h in design.helices:
        ax_s = h.axis_start.to_array() * 10.0
        ax_e = h.axis_end.to_array()   * 10.0
        v = ax_e - ax_s
        axis_hat = v / np.linalg.norm(v)
        helix_info[h.id] = (ax_s, axis_hat, h.bp_start, h.length_bp,
                             h.phase_offset, h.twist_per_bp_rad, h.direction)

    h_ids     = list(helix_info.keys())
    ax_s_arr  = np.array([helix_info[h][0] for h in h_ids])
    axhat_arr = np.array([helix_info[h][1] for h in h_ids])

    # ── Step 2: axis-line assignment from initial coarse PDB ──────────────
    init_pdb  = psf_path.replace(".psf", ".pdb")
    u_init    = mda.Universe(psf_path, init_pdb)
    init_pos  = u_init.atoms.positions
    init_names = np.array([a.name for a in u_init.atoms])
    dna_init_idx = np.where(init_names == 'DNA')[0]
    dna_init_pos = init_pos[dna_init_idx]   # (N_dna, 3) Å

    n_dna     = len(dna_init_pos)
    n_helices = len(h_ids)
    perp = np.zeros((n_dna, n_helices))
    proj = np.zeros((n_dna, n_helices))
    for j in range(n_helices):
        diff  = dna_init_pos - ax_s_arr[j]
        axial = (diff * axhat_arr[j]).sum(axis=1)
        perp_vec = diff - axial[:, None] * axhat_arr[j]
        perp[:, j] = np.linalg.norm(perp_vec, axis=1)
        proj[:, j] = axial

    best_j    = perp.argmin(axis=1)
    best_perp = perp[np.arange(n_dna), best_j]
    best_proj = proj[np.arange(n_dna), best_j]

    # bp_idx: coarse bead represents center of a 5-bp window
    bp_per_bead = 5
    bp_idx_arr = np.zeros(n_dna, dtype=int)
    for i in range(n_dna):
        j = best_j[i]
        bp_start = helix_info[h_ids[j]][2]
        bp_idx_arr[i] = int(round(
            bp_start + best_proj[i] / (BDNA_RISE_PER_BP * 10.0)
        ))

    # Deduplicate: for same (h_id, bp_idx), keep smallest perp distance
    bp_to_pair: dict = {}
    for pair_i in range(n_dna):
        h_id   = h_ids[best_j[pair_i]]
        bp_idx = bp_idx_arr[pair_i]
        pd     = best_perp[pair_i]
        key    = (h_id, bp_idx)
        if key not in bp_to_pair or pd < bp_to_pair[key][1]:
            bp_to_pair[key] = (pair_i, pd)

    # ── Step 3: read DCD frame ─────────────────────────────────────────────
    u     = mda.Universe(psf_path, dcd_path)
    atoms = u.select_atoms('all')
    if frame == -1:
        u.trajectory[-1]
    else:
        u.trajectory[frame]
    sim_pos    = atoms.positions.copy()
    atom_names = np.array([a.name for a in atoms])
    dna_sim_idx = np.where(atom_names == 'DNA')[0]
    dna_sim_pos = sim_pos[dna_sim_idx]   # (N_dna, 3) Å

    # ── Step 4: per-helix spline fit and override computation ─────────────
    helix_entries: dict = defaultdict(list)
    for (h_id, bp_idx), (pair_i, _) in bp_to_pair.items():
        helix_entries[h_id].append((bp_idx, pair_i))
    for entries in helix_entries.values():
        entries.sort(key=lambda x: x[0])

    def _rotate(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
        c, s = math.cos(angle), math.sin(angle)
        return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1.0 - c)

    helix_radius_ang = HELIX_RADIUS * 10.0
    override: dict[tuple, np.ndarray] = {}

    for h_id, entries in helix_entries.items():
        ax_s, ideal_axis_hat, bp_start, length_bp, phase_offset, twist, h_dir = \
            helix_info[h_id]
        x_hat, y_hat = _xy_frame(ideal_axis_hat)

        bp_idxs = np.array([e[0] for e in entries])
        pair_is = [e[1] for e in entries]

        # Simulated coarse bead positions for this helix
        raw_pos = np.array([dna_sim_pos[pi] for pi in pair_is], dtype=float)

        # Light smoothing in bead space before spline fitting
        if len(raw_pos) >= 3 and sigma_nt > 0:
            raw_pos = gaussian_filter1d(raw_pos, sigma=sigma_nt, axis=0, mode='nearest')

        # Cubic spline parameterised by bp_idx
        if len(bp_idxs) < 2:
            continue
        cs = CubicSpline(bp_idxs.astype(float), raw_pos, bc_type='not-a-knot')

        # Evaluate at every bp position in this helix
        bp_lo = bp_start
        bp_hi = bp_start + length_bp - 1
        # Clamp extrapolation to spline range
        t_lo = float(bp_idxs[0])
        t_hi = float(bp_idxs[-1])

        for bp_idx in range(bp_lo, bp_hi + 1):
            t = float(np.clip(bp_idx, t_lo, t_hi))

            local_i  = bp_idx - bp_start

            # Spline-derived axis direction (captures helix bending).
            tangent  = cs(t, 1)
            tang_n   = np.linalg.norm(tangent)
            axis_hat = tangent / tang_n if tang_n > 1e-6 else ideal_axis_hat

            # IDEAL axis point at this bp (Å) — position is fixed to ideal spacing.
            # Axial thermal fluctuations in the coarse bead positions are discarded
            # so backbone bond lengths match the GROMACS topology.
            ideal_axis_pt = ax_s + local_i * (BDNA_RISE_PER_BP * 10.0) * ideal_axis_hat

            # FORWARD radial from ideal B-DNA phase, projected ⊥ to spline tangent.
            fwd_angle = phase_offset + local_i * twist
            ideal_fwd_rad = math.cos(fwd_angle) * x_hat + math.sin(fwd_angle) * y_hat
            perp_comp = ideal_fwd_rad - np.dot(ideal_fwd_rad, axis_hat) * axis_hat
            pn = np.linalg.norm(perp_comp)
            fwd_rad = perp_comp / pn if pn > 1e-6 else ideal_fwd_rad

            fwd_ang = ideal_axis_pt + helix_radius_ang * fwd_rad
            rev_rad = _rotate(fwd_rad, axis_hat, BDNA_MINOR_GROOVE_ANGLE_RAD)
            rev_ang = ideal_axis_pt + helix_radius_ang * rev_rad

            override[(h_id, bp_idx, 'FORWARD')] = fwd_ang / 10.0
            override[(h_id, bp_idx, 'REVERSE')] = rev_ang / 10.0

    xover_keys = _crossover_junction_keys(design)
    override = {k: v for k, v in override.items() if k not in xover_keys}
    n_helices_covered = len(helix_entries)
    print(
        f"[mrdna coarse spline] {n_helices_covered}/{len(h_ids)} helices | "
        f"{len(override)} override entries after crossover exclusion "
        f"({len(xover_keys)} crossover keys removed)",
        flush=True,
    )
    return override


def _crossover_junction_keys(design: Design) -> set:
    """
    Return the set of (helix_id, bp_idx, direction_str) override keys that fall
    at domain-boundary crossover junctions.  These positions must be excluded from
    the mrdna override so that _minimize_backbone_bridge can place them using ideal
    B-DNA geometry — the mrdna bead positions place crossover nucleotides at their
    respective helix radii (up to 2 nm apart), which breaks backbone continuity.
    """
    excluded: set = set()
    for strand in design.strands:
        for k in range(len(strand.domains) - 1):
            d0, d1 = strand.domains[k], strand.domains[k + 1]
            if d0.helix_id == d1.helix_id:
                continue
            excluded.add((d0.helix_id, d0.end_bp,   d0.direction.value))
            excluded.add((d1.helix_id, d1.start_bp,  d1.direction.value))
    return excluded


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
