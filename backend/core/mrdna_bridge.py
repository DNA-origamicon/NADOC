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
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HELIX_RADIUS,
    SSDNA_CONTOUR_PER_NT_NM,
)
from backend.core.geometry import groove_offset_rad
from backend.core.models import Design
from backend.core.sequences import _build_loop_skip_map, domain_bp_range

_NM_TO_ANGSTROM = 10.0


def _rodrigues(v: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rotate *v* about the unit vector *axis* by *angle* (Rodrigues).

    Was four byte-identical nested closures — three named ``_rotate``, one ``_rot`` — one
    per override builder.  ``axis`` must already be normalised; every caller here passes
    a helix ``axis_hat``.
    """
    c, s = math.cos(angle), math.sin(angle)
    return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1.0 - c)


# Synthetic helix_id prefix of a strand-extension tail bead — the key the geometry layer,
# oxDNA and the atomistic model already share (``("__ext_<ext_id>", bead_index, dir)``).
# Kept in sync with ``oxdna_interface._EXT_PREFIX``.
_EXT_PREFIX = "__ext_"


def unwrap_periodic_positions(
    positions: np.ndarray,
    bonds: np.ndarray,
    box: np.ndarray,
    *,
    reference: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Unwrap bonded components from an orthorhombic periodic ARBD cell."""
    pos = np.asarray(positions, dtype=float)
    out = pos.copy()
    dims = np.asarray(box, dtype=float)[:3]
    if (
        len(pos) == 0
        or dims.shape != (3,)
        or not np.all(np.isfinite(dims))
        or np.any(dims <= 0)
    ):
        return out
    adjacency: list[list[int]] = [[] for _ in range(len(pos))]
    for a, b in np.asarray(bonds, dtype=int).reshape((-1, 2)):
        if 0 <= a < len(pos) and 0 <= b < len(pos):
            adjacency[a].append(b)
            adjacency[b].append(a)
    seen = np.zeros(len(pos), dtype=bool)
    ref = None if reference is None else np.asarray(reference, dtype=float)
    for root in range(len(pos)):
        if seen[root]:
            continue
        seen[root] = True
        component = [root]
        stack = [root]
        while stack:
            a = stack.pop()
            for b in adjacency[a]:
                if seen[b]:
                    continue
                delta = pos[b] - pos[a]
                delta -= dims * np.round(delta / dims)
                out[b] = out[a] + delta
                seen[b] = True
                component.append(b)
                stack.append(b)
        if ref is not None and ref.shape == pos.shape:
            idx = np.asarray(component, dtype=int)
            shift = dims * np.round((ref[idx].mean(0) - out[idx].mean(0)) / dims)
            out[idx] += shift
    return out


def _unwrapped_universe_positions(universe, reference=None) -> np.ndarray:
    """Return an MDAnalysis Universe's coordinates with bonded PBCs removed."""
    bonds = getattr(getattr(universe, "bonds", None), "indices", np.empty((0, 2)))
    box = universe.dimensions[:3] if universe.dimensions is not None else np.zeros(3)
    return unwrap_periodic_positions(
        universe.atoms.positions, bonds, box, reference=reference
    )


def mrdna_tool_path() -> str:
    """Canonical location of the mrdna source checkout (editable-installed).

    Single source of truth shared by every mrdna consumer (this module, the
    ``/ws/mrdna-relax`` clone-on-first-use in ``api/ws.py``, and the
    ``parameterization/mrdna_inject.py`` importers).

    Resolution: ``$MRDNA_TOOL_PATH`` override → conventional ``~/mrdna-tool``.
    The default is HOME-relative and PERSISTENT — matching the ``~/oxDNA`` /
    ``~/anm-oxdna`` house convention — so the checkout survives reboots instead
    of being re-cloned every boot (the previous ``/tmp/mrdna-tool`` default was
    wiped on restart; the older ``/home/jojo/...`` default was another machine's
    home and never resolved here).
    """
    override = os.environ.get("MRDNA_TOOL_PATH", "").strip()
    return override or os.path.expanduser("~/mrdna-tool")


_MRDNA_TOOL_PATH = mrdna_tool_path()

# WSL2 exposes the real GPU driver libs (libcuda.so) under /usr/lib/wsl/lib.
_WSL_LIB_DIR = "/usr/lib/wsl/lib"


def _is_wsl() -> bool:
    """True when running under WSL (cheap local check; avoids importing engines)."""
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def ensure_wsl_cuda_libs() -> None:
    """Put WSL's GPU driver libs first on ``LD_LIBRARY_PATH`` so ARBD sees the GPU.

    The classic WSL2 CUDA snag: a Linux-side NVIDIA driver package installs
    ``/usr/lib/x86_64-linux-gnu/libcuda.so.1`` which **shadows** the real WSL
    passthrough driver at ``/usr/lib/wsl/lib``.  ARBD then loads the desktop
    ``libcuda`` and reports "Found 0 GPU(s)" even though ``nvidia-smi`` works.
    Prepending ``/usr/lib/wsl/lib`` makes the loader find the correct WSL driver.
    mrdna spawns ``arbd`` as a subprocess inheriting this process's environment, so
    setting it here (before any simulate) fixes every ARBD launch.  No-op off WSL.
    """
    if not _is_wsl() or not os.path.isdir(_WSL_LIB_DIR):
        return
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    parts = cur.split(os.pathsep) if cur else []
    if _WSL_LIB_DIR in parts:
        return
    os.environ["LD_LIBRARY_PATH"] = (
        os.pathsep.join([_WSL_LIB_DIR, *parts]) if parts else _WSL_LIB_DIR
    )


# Apply immediately on import so any ARBD launch from the NADOC backend, the
# /ws/mrdna-relax handler, the skip-twist relax, or the round-trip benchmark
# inherits the corrected library path.
ensure_wsl_cuda_libs()


def _ensure_mrdna() -> None:
    """Add mrdna's install path to sys.path if not already importable."""
    import sys

    try:
        import mrdna  # noqa: F401
    except ImportError:
        if _MRDNA_TOOL_PATH not in sys.path:
            sys.path.insert(0, _MRDNA_TOOL_PATH)


def find_mrdna() -> Optional[str]:
    """Path of the installed mrdna Python package, or None if not installed.

    Used by the "MD Engines" panel to show mrdna's status.  Two ways it can be
    present: already importable in the running venv, or an editable checkout at
    ``mrdna_tool_path()`` (what ``scripts/setup-mrdna.sh`` produces).  Returns a
    human-meaningful path (the package dir) in both cases; never raises.
    """
    import importlib.util

    try:
        spec = importlib.util.find_spec("mrdna")
        if spec is not None:
            return os.path.dirname(spec.origin) if spec.origin else mrdna_tool_path()
    except Exception:
        pass
    checkout = mrdna_tool_path()
    if os.path.isdir(os.path.join(checkout, "mrdna")):
        return checkout
    return None


# Where the download-finish flow builds ARBD (see engine_artifact.install_arbd_archive).
_ARBD_SRC = os.path.expanduser("~/arbd-src")
# Conventional installed locations NADOC looks for a *Linux* arbd binary in.
_ARBD_INSTALL_LOCS = ("/usr/local/bin/arbd", os.path.expanduser("~/.local/bin/arbd"))
# Where a successful build leaves the binary before it's installed onto PATH.
_ARBD_BUILD_LOCS = (
    os.path.join(_ARBD_SRC, "build", "arbd"),
    os.path.join(_ARBD_SRC, "build", "bin", "arbd"),
)


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_arbd() -> Optional[str]:
    """Path of the *installed* ARBD binary (on PATH or a conventional loc), else None.

    ARBD is the compiled Brownian-dynamics engine mrdna drives.  Installed to
    ``/usr/local/bin/arbd`` (``sudo make install``) or ``~/.local/bin/arbd``
    (no-password finish), or anywhere on PATH.  A binary sitting only in the build
    tree (``~/arbd-src/build/arbd``) is NOT "installed" — see `find_arbd_build`.
    Never raises.
    """
    import shutil

    found = shutil.which("arbd")
    if found:
        return found
    for loc in _ARBD_INSTALL_LOCS:
        if _executable(loc):
            return loc
    return None


def find_arbd_build() -> Optional[str]:
    """Path of a *built-but-not-installed* ARBD binary in the build tree, else None.

    After NADOC's download-finish flow runs cmake+make, the Linux binary sits at
    ``~/arbd-src/build/arbd`` until the user installs it onto PATH.  The MD-Engines
    guide uses this to detect the common WSL snag — "built on the Linux side but
    the install step wasn't finished" — and offer a one-click no-password finish.
    """
    for loc in _ARBD_BUILD_LOCS:
        if _executable(loc):
            return loc
    return None


def mrdna_model_from_nadoc(
    design: Design, *, return_nt_key: bool = False, **model_params
):
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
        r,
        bp,
        stack,
        three_prime,
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
    helix_info: dict = {}  # h_id → (ax_s_ang, axis_hat, bp_start, groove)
    for h in design.helices:
        ax_s = h.axis_start.to_array() * 10.0  # nm → Å
        ax_e = h.axis_end.to_array() * 10.0
        v = ax_e - ax_s
        axis_hat = v / np.linalg.norm(v)
        helix_info[h.id] = (ax_s, axis_hat, h.bp_start, groove_offset_rad(h.direction))

    h_ids = list(helix_info.keys())
    ax_s_arr = np.array([helix_info[h][0] for h in h_ids])  # (H, 3)
    axhat_arr = np.array([helix_info[h][1] for h in h_ids])  # (H, 3)

    # ── Step 2: build axis-line assignment from initial fine PDB ──────────
    # The initial PDB must be in NADOC coordinate frame.
    init_pdb = psf_path.replace(".psf", ".pdb")
    u_init = mda.Universe(psf_path, init_pdb)
    init_pos = u_init.atoms.positions  # (N_beads, 3) Å
    init_names = np.array([a.name for a in u_init.atoms])
    dna_init_idx = np.where(init_names == "DNA")[0]
    dna_init_pos = init_pos[dna_init_idx]  # (N_dna, 3)

    # Perpendicular distance from each DNA bead to each helix axis-line
    n_dna = len(dna_init_pos)
    n_helices = len(h_ids)
    perp = np.zeros((n_dna, n_helices), dtype=float)
    proj = np.zeros((n_dna, n_helices), dtype=float)
    for j in range(n_helices):
        diff = dna_init_pos - ax_s_arr[j]  # (N, 3)
        axial = (diff * axhat_arr[j]).sum(axis=1)  # (N,)
        perp_vec = diff - axial[:, None] * axhat_arr[j]
        perp[:, j] = np.linalg.norm(perp_vec, axis=1)
        proj[:, j] = axial

    best_j = perp.argmin(axis=1)  # (N_dna,) best helix index
    best_perp = perp[np.arange(n_dna), best_j]
    best_proj = proj[np.arange(n_dna), best_j]

    # bp_idx from axial projection
    bp_idx_arr = np.zeros(n_dna, dtype=int)
    for i in range(n_dna):
        j = best_j[i]
        bp_start = helix_info[h_ids[j]][2]
        bp_idx_arr[i] = int(round(bp_start + best_proj[i] / (BDNA_RISE_PER_BP * 10.0)))

    # Build mapping: (h_id, bp_idx) → pair_i with smallest perp distance
    bp_to_pair: dict = {}  # (h_id, bp_idx) → (pair_i, perp)
    for pair_i in range(n_dna):
        h_id = h_ids[best_j[pair_i]]
        bp_idx = bp_idx_arr[pair_i]
        perp_d = best_perp[pair_i]
        key = (h_id, bp_idx)
        if key not in bp_to_pair or perp_d < bp_to_pair[key][1]:
            bp_to_pair[key] = (pair_i, perp_d)

    # ── Step 3: read DCD simulation frame ─────────────────────────────────
    u = mda.Universe(psf_path, dcd_path)
    atoms = u.select_atoms("all")
    if frame == -1:
        u.trajectory[-1]
    else:
        u.trajectory[frame]
    positions = _unwrapped_universe_positions(u, init_pos)  # (N_beads, 3) Å
    atom_names = np.array([a.name for a in atoms])
    dna_sim_idx = np.where(atom_names == "DNA")[0]
    dna_sim_pos = positions[dna_sim_idx]  # (N_dna, 3) Å

    # ── Step 4: group by helix, smooth, compute overrides ─────────────────
    helix_entries: dict = defaultdict(list)  # h_id → [(bp_idx, pair_i)]
    for (h_id, bp_idx), (pair_i, _) in bp_to_pair.items():
        helix_entries[h_id].append((bp_idx, pair_i))
    for entries in helix_entries.values():
        entries.sort(key=lambda x: x[0])

    helix_radius_ang = HELIX_RADIUS * 10.0

    override: dict[tuple, np.ndarray] = {}

    for h_id, entries in helix_entries.items():
        ax_s, axis_hat, bp_start, groove = helix_info[h_id]

        bp_idxs = [e[0] for e in entries]
        pair_is = [e[1] for e in entries]

        dna_raw = np.array([dna_sim_pos[pi] for pi in pair_is], dtype=float)

        if len(dna_raw) >= 3 and sigma_nt > 0:
            dna_sm = gaussian_filter1d(dna_raw, sigma=sigma_nt, axis=0, mode="nearest")
        else:
            dna_sm = dna_raw

        for bp_idx, dna_p in zip(bp_idxs, dna_sm):
            local_i = bp_idx - bp_start
            # Ideal helix axis point at this bp (Å) — axial position is fixed to
            # ideal B-DNA spacing; only the radial direction comes from mrdna.
            axis_pt = ax_s + local_i * (BDNA_RISE_PER_BP * 10.0) * axis_hat
            radial = dna_p - axis_pt
            radial_ax = np.dot(radial, axis_hat)
            radial_perp = radial - radial_ax * axis_hat
            rp_norm = np.linalg.norm(radial_perp)
            if rp_norm < 1e-6:
                continue
            fwd_radial_hat = radial_perp / rp_norm

            # FORWARD: place at ideal axis + HELIX_RADIUS in mrdna twist direction.
            # _atom_frame will rescale radius to _ATOMISTIC_P_RADIUS automatically.
            # Axial displacement is stripped so thermal fluctuations of CG beads
            # do not propagate into backbone bond lengths.
            fwd_ang = axis_pt + helix_radius_ang * fwd_radial_hat
            override[(h_id, bp_idx, "FORWARD")] = fwd_ang / 10.0  # Å → nm

            # REVERSE: rotate fwd_radial by the minor groove angle about the ideal axis.
            #
            # This site used to apply +GROOVE unconditionally, the only one of the five in
            # this file that did not branch on the helix's lattice cell type — so on a
            # REVERSE-cell helix the reverse strand was placed on the wrong groove side,
            # 1.0 nm from where the geometric layer puts it.  Fixed 2026-08-06, TD-27
            # Stage 2.  The forward radial here comes from a smoothed mrDNA bead rather
            # than the design phase, but the groove is a property of the CELL, not of how
            # the forward radial was obtained, so the same rule applies.
            rev_radial_hat = _rodrigues(fwd_radial_hat, axis_hat, groove)
            rev_ang = axis_pt + helix_radius_ang * rev_radial_hat
            override[(h_id, bp_idx, "REVERSE")] = rev_ang / 10.0  # Å → nm

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
    helix_info: dict = {}  # h_id → (ax_s_ang, axis_hat, bp_start, length_bp)
    for h in design.helices:
        ax_s = h.axis_start.to_array() * 10.0
        ax_e = h.axis_end.to_array() * 10.0
        v = ax_e - ax_s
        axis_hat = v / np.linalg.norm(v)
        helix_info[h.id] = (
            ax_s,
            axis_hat,
            h.bp_start,
            h.length_bp,
            h.phase_offset,
            h.twist_per_bp_rad,
            h.direction,
        )

    h_ids = list(helix_info.keys())
    ax_s_arr = np.array([helix_info[h][0] for h in h_ids])
    axhat_arr = np.array([helix_info[h][1] for h in h_ids])

    # ── Step 2: axis-line assignment from initial coarse PDB ──────────────
    init_pdb = psf_path.replace(".psf", ".pdb")
    u_init = mda.Universe(psf_path, init_pdb)
    init_pos = u_init.atoms.positions
    init_names = np.array([a.name for a in u_init.atoms])
    dna_init_idx = np.where(init_names == "DNA")[0]
    dna_init_pos = init_pos[dna_init_idx]  # (N_dna, 3) Å

    n_dna = len(dna_init_pos)
    n_helices = len(h_ids)
    perp = np.zeros((n_dna, n_helices))
    proj = np.zeros((n_dna, n_helices))
    for j in range(n_helices):
        diff = dna_init_pos - ax_s_arr[j]
        axial = (diff * axhat_arr[j]).sum(axis=1)
        perp_vec = diff - axial[:, None] * axhat_arr[j]
        perp[:, j] = np.linalg.norm(perp_vec, axis=1)
        proj[:, j] = axial

    best_j = perp.argmin(axis=1)
    best_perp = perp[np.arange(n_dna), best_j]
    best_proj = proj[np.arange(n_dna), best_j]

    # bp_idx: coarse bead represents center of a 5-bp window
    bp_idx_arr = np.zeros(n_dna, dtype=int)
    for i in range(n_dna):
        j = best_j[i]
        bp_start = helix_info[h_ids[j]][2]
        bp_idx_arr[i] = int(round(bp_start + best_proj[i] / (BDNA_RISE_PER_BP * 10.0)))

    # Deduplicate: for same (h_id, bp_idx), keep smallest perp distance
    # Skip out-of-range junction beads (mrdna places 1 bead at contour=1.0 → bp=length_bp)
    bp_to_pair: dict = {}
    for pair_i in range(n_dna):
        h_id = h_ids[best_j[pair_i]]
        bp_idx = bp_idx_arr[pair_i]
        bp_start = helix_info[h_id][2]
        length_bp = helix_info[h_id][3]
        if bp_idx < bp_start or bp_idx >= bp_start + length_bp:
            continue
        pd = best_perp[pair_i]
        key = (h_id, bp_idx)
        if key not in bp_to_pair or pd < bp_to_pair[key][1]:
            bp_to_pair[key] = (pair_i, pd)

    # ── Step 3: read DCD frame ─────────────────────────────────────────────
    u = mda.Universe(psf_path, dcd_path)
    atoms = u.select_atoms("all")
    if frame == -1:
        u.trajectory[-1]
    else:
        u.trajectory[frame]
    sim_pos = _unwrapped_universe_positions(u, init_pos)
    atom_names = np.array([a.name for a in atoms])
    dna_sim_idx = np.where(atom_names == "DNA")[0]
    dna_sim_pos = sim_pos[dna_sim_idx]  # (N_dna, 3) Å

    # ── Step 4: per-helix spline fit and override computation ─────────────
    helix_entries: dict = defaultdict(list)
    for (h_id, bp_idx), (pair_i, _) in bp_to_pair.items():
        helix_entries[h_id].append((bp_idx, pair_i))
    for entries in helix_entries.values():
        entries.sort(key=lambda x: x[0])

    helix_radius_ang = HELIX_RADIUS * 10.0
    override: dict[tuple, np.ndarray] = {}

    for h_id, entries in helix_entries.items():
        ax_s, ideal_axis_hat, bp_start, length_bp, phase_offset, twist, h_dir = (
            helix_info[h_id]
        )
        x_hat, y_hat = _xy_frame(ideal_axis_hat)

        bp_idxs = np.array([e[0] for e in entries])
        pair_is = [e[1] for e in entries]

        # Simulated coarse bead positions for this helix
        raw_pos = np.array([dna_sim_pos[pi] for pi in pair_is], dtype=float)

        # Light smoothing in bead space before spline fitting
        if len(raw_pos) >= 3 and sigma_nt > 0:
            raw_pos = gaussian_filter1d(raw_pos, sigma=sigma_nt, axis=0, mode="nearest")

        # Project bead positions onto the ideal axis (removes the ~2.59 Å off-axis
        # helix component that otherwise pollutes the spline tangent direction).
        # For straight helices this gives colinear points → tangent = ideal_axis_hat.
        # For globally bent helices the projected feet trace the deformed axis.
        axial_dots = (raw_pos - ax_s).dot(ideal_axis_hat)  # (N,) scalar projections
        raw_pos_on_axis = ax_s + np.outer(axial_dots, ideal_axis_hat)  # (N, 3) feet

        # Cubic spline parameterised by bp_idx through axis-projected positions
        if len(bp_idxs) < 2:
            continue
        cs = CubicSpline(bp_idxs.astype(float), raw_pos_on_axis, bc_type="not-a-knot")

        # Evaluate at every bp position in this helix
        bp_lo = bp_start
        bp_hi = bp_start + length_bp - 1
        # Clamp extrapolation to spline range
        t_lo = float(bp_idxs[0])
        t_hi = float(bp_idxs[-1])

        for bp_idx in range(bp_lo, bp_hi + 1):
            t = float(np.clip(bp_idx, t_lo, t_hi))

            local_i = bp_idx - bp_start

            # Axis direction from projected spline (free of off-axis oscillation).
            tangent = cs(t, 1)
            tang_n = np.linalg.norm(tangent)
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

            groove = groove_offset_rad(h_dir)
            fwd_ang = ideal_axis_pt + helix_radius_ang * fwd_rad
            rev_rad = _rodrigues(fwd_rad, axis_hat, groove)
            rev_ang = ideal_axis_pt + helix_radius_ang * rev_rad

            override[(h_id, bp_idx, "FORWARD")] = fwd_ang / 10.0
            override[(h_id, bp_idx, "REVERSE")] = rev_ang / 10.0

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


def extra_base_flank_keys(design: Design) -> "list[tuple[str, str, tuple, tuple]]":
    """``[(crossover_id, extra_bases, prev_key, next_key)]`` for every crossover that
    carries extra bases, where ``prev_key`` / ``next_key`` are the
    ``(helix_id, bp_index, direction)`` display keys of the two REAL nucleotides the
    single-stranded insert bridges (last real nt of the owning strand's prior domain,
    first real nt of the next domain).  Reuses the oxDNA owning-strand junction map so
    the mrDNA and oxDNA engines place the inserts at the same junction.

    Used by the DISPLAY path to position the native extra-base beads/slabs at the
    relaxed junction (chord-lerp between the two flanks).  Empty when the design has
    no extra bases.  Physical-layer / display only — no topology read-back."""
    from backend.physics.oxdna_interface import crossover_extra_base_junctions

    ls_map = _build_loop_skip_map(design)
    junctions = crossover_extra_base_junctions(design)
    by_id = {s.id: s for s in design.strands}
    out: list[tuple[str, str, tuple, tuple]] = []
    for (strand_id, di), (xo_id, extra) in junctions.items():
        strand = by_id.get(strand_id)
        if strand is None or di + 1 >= len(strand.domains):
            continue
        prev, nxt = strand.domains[di], strand.domains[di + 1]
        prev_bps = [
            b for b in domain_bp_range(prev) if ls_map.get((prev.helix_id, b), 0) > -1
        ]
        next_bps = [
            b for b in domain_bp_range(nxt) if ls_map.get((nxt.helix_id, b), 0) > -1
        ]
        if not prev_bps or not next_bps:
            continue
        prev_key = (prev.helix_id, prev_bps[-1], prev.direction.value)
        next_key = (nxt.helix_id, next_bps[0], nxt.direction.value)
        out.append((xo_id, extra, prev_key, next_key))
    return out


def _relaxed_axis_at_bp(cs, bp, t_lo, t_hi, ideal_axis_hat, rise_ang):
    """Relaxed-axis point (Å) + unit tangent at integer ``bp`` on a per-helix cubic
    spline ``cs`` (parameterized by bp index, fitted through the bead-covered range
    ``[t_lo, t_hi]``).

    Within the covered range the spline is evaluated directly.  BEYOND it — a helix
    END the fine-stage bead→axis assignment left beadless — the axis is continued
    STRAIGHT along the endpoint tangent at the ideal B-DNA ``rise_ang`` per bp,
    instead of clipping ``bp`` to the endpoint.  Clipping pins every uncovered bp to
    the single spline-end point, and the duplex twist reconstruction that follows then
    fans those pinned nucleotides into a flat HELIX_RADIUS circle — the "a helix
    collapsed onto a 2-D plane to make a ring" display artifact.  Linear (not cubic)
    extrapolation keeps the tail bounded and physically extended; ideal rise keeps its
    backbone bond spacing canonical so it never trips the stretched-bond fallback.
    """
    if t_lo <= bp <= t_hi:
        pt = np.asarray(cs(float(bp)), dtype=float)
        tan = np.asarray(cs(float(bp), 1), dtype=float)
        tn = np.linalg.norm(tan)
        return pt, (tan / tn if tn > 1e-6 else ideal_axis_hat)
    t_end = t_lo if bp < t_lo else t_hi
    tan = np.asarray(cs(t_end, 1), dtype=float)
    tn = np.linalg.norm(tan)
    axis_hat = tan / tn if tn > 1e-6 else np.asarray(ideal_axis_hat, dtype=float)
    pt = np.asarray(cs(t_end), dtype=float) + (bp - t_end) * rise_ang * axis_hat
    return pt, axis_hat


def nuc_pos_override_display_from_coarse(
    design: Design,
    psf_path: str,
    dcd_path: str,
    frame: int = -1,
    sigma_nt: float = 1.0,
) -> "dict[tuple[str,int,str], np.ndarray]":
    """DISPLAY reconstruction from the coarse stage — shows the ACTUAL relaxed shape.

    Unlike ``nuc_pos_override_from_mrdna_coarse`` (which re-idealises: fixes the
    axial spacing + twist to ideal B-DNA and captures only global axis *bending*,
    so a mostly-straight bundle reconstructs to ~the design), this places each
    nucleotide's backbone at HELIX_RADIUS around the **real relaxed helix axis**
    (the cubic spline through the actual DCD bead positions, Kabsch-aligned into the
    NADOC frame).  So local bends, breathing, and axial compression the relaxation
    produced are visible.  Duplex radius + twist phase are still reconstructed from
    ideal B-DNA (the coarse model carries one bead per bp, no per-strand backbone),
    but anchored at the true relaxed axis point.  Crossover keys are KEPT (display
    should move junctions too).  Physical-layer / display only.

    Returns dict mapping (helix_id, bp_index, direction_str) → position in nm.
    """
    import sys

    sys.path.insert(0, _MRDNA_TOOL_PATH)
    import MDAnalysis as mda
    from collections import defaultdict
    from scipy.interpolate import CubicSpline
    from scipy.ndimage import gaussian_filter1d

    # ── Step 1: helix axis geometry ────────────────────────────────────────
    helix_info: dict = {}
    for h in design.helices:
        ax_s = h.axis_start.to_array() * 10.0
        ax_e = h.axis_end.to_array() * 10.0
        v = ax_e - ax_s
        axis_hat = v / np.linalg.norm(v)
        helix_info[h.id] = (
            ax_s,
            axis_hat,
            h.bp_start,
            h.length_bp,
            h.phase_offset,
            h.twist_per_bp_rad,
            h.direction,
        )

    h_ids = list(helix_info.keys())
    ax_s_arr = np.array([helix_info[h][0] for h in h_ids])
    axhat_arr = np.array([helix_info[h][1] for h in h_ids])

    # ── Step 2: bead → (h_id, bp_idx) assignment from the initial coarse PDB ─
    init_pdb = psf_path.replace(".psf", ".pdb")
    u_init = mda.Universe(psf_path, init_pdb)
    init_names = np.array([a.name for a in u_init.atoms])
    dna_init_idx = np.where(init_names == "DNA")[0]
    dna_init_pos = u_init.atoms.positions[dna_init_idx].astype(float)  # NADOC frame, Å

    n_dna = len(dna_init_pos)
    n_helices = len(h_ids)
    perp = np.zeros((n_dna, n_helices))
    proj = np.zeros((n_dna, n_helices))
    for j in range(n_helices):
        diff = dna_init_pos - ax_s_arr[j]
        axial = (diff * axhat_arr[j]).sum(axis=1)
        perp_vec = diff - axial[:, None] * axhat_arr[j]
        perp[:, j] = np.linalg.norm(perp_vec, axis=1)
        proj[:, j] = axial
    best_j = perp.argmin(axis=1)
    best_perp = perp[np.arange(n_dna), best_j]
    best_proj = proj[np.arange(n_dna), best_j]

    bp_idx_arr = np.zeros(n_dna, dtype=int)
    for i in range(n_dna):
        bp_start = helix_info[h_ids[best_j[i]]][2]
        bp_idx_arr[i] = int(round(bp_start + best_proj[i] / (BDNA_RISE_PER_BP * 10.0)))

    bp_to_pair: dict = {}
    for pair_i in range(n_dna):
        h_id = h_ids[best_j[pair_i]]
        bp_idx = bp_idx_arr[pair_i]
        bp_start = helix_info[h_id][2]
        length_bp = helix_info[h_id][3]
        if bp_idx < bp_start or bp_idx >= bp_start + length_bp:
            continue
        pd = best_perp[pair_i]
        key = (h_id, bp_idx)
        if key not in bp_to_pair or pd < bp_to_pair[key][1]:
            bp_to_pair[key] = (pair_i, pd)

    # ── Step 3: read the relaxed DCD frame + Kabsch-align into the NADOC frame ─
    u = mda.Universe(psf_path, dcd_path)
    if frame == -1:
        u.trajectory[-1]
    else:
        u.trajectory[frame]
    atom_names = np.array([a.name for a in u.atoms])
    dna_sim_idx = np.where(atom_names == "DNA")[0]
    all_sim_pos = _unwrapped_universe_positions(u, u_init.atoms.positions)
    dna_sim_pos = all_sim_pos[dna_sim_idx].astype(float)  # drifted, unwrapped Å

    if len(dna_sim_pos) == n_dna and n_dna >= 3:
        mc = dna_sim_pos.mean(axis=0)
        tc = dna_init_pos.mean(axis=0)
        H = (dna_sim_pos - mc).T @ (dna_init_pos - tc)
        U, _, Vt = np.linalg.svd(H)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
        dna_sim_pos = (dna_sim_pos - mc) @ R.T + tc  # aligned, Å

    # ── Step 4: per-helix spline through ACTUAL positions; duplex reconstruction ─
    helix_entries: dict = defaultdict(list)
    for (h_id, bp_idx), (pair_i, _) in bp_to_pair.items():
        helix_entries[h_id].append((bp_idx, pair_i))
    for entries in helix_entries.values():
        entries.sort(key=lambda x: x[0])

    helix_radius_ang = HELIX_RADIUS * 10.0
    override: dict[tuple, np.ndarray] = {}

    for h_id, entries in helix_entries.items():
        ax_s, ideal_axis_hat, bp_start, length_bp, phase_offset, twist, h_dir = (
            helix_info[h_id]
        )
        x_hat, y_hat = _xy_frame(ideal_axis_hat)

        bp_idxs = np.array([e[0] for e in entries])
        raw_pos = np.array([dna_sim_pos[e[1]] for e in entries], dtype=float)  # ACTUAL
        if len(raw_pos) >= 3 and sigma_nt > 0:
            raw_pos = gaussian_filter1d(raw_pos, sigma=sigma_nt, axis=0, mode="nearest")
        if len(bp_idxs) < 2:
            continue

        cs = CubicSpline(bp_idxs.astype(float), raw_pos, bc_type="not-a-knot")
        t_lo, t_hi = float(bp_idxs[0]), float(bp_idxs[-1])

        for bp_idx in range(bp_start, bp_start + length_bp):
            local_i = bp_idx - bp_start

            # ACTUAL relaxed axis position (Å) on the spline within the bead-covered
            # range; STRAIGHT tangent extrapolation past a beadless end (NOT clipped
            # to the spline endpoint — that pins the tail into a flat ring, see
            # _relaxed_axis_at_bp).
            axis_pt, axis_hat = _relaxed_axis_at_bp(
                cs, bp_idx, t_lo, t_hi, ideal_axis_hat, BDNA_RISE_PER_BP * 10.0
            )

            fwd_angle = phase_offset + local_i * twist
            ideal_fwd_rad = math.cos(fwd_angle) * x_hat + math.sin(fwd_angle) * y_hat
            perp_comp = ideal_fwd_rad - np.dot(ideal_fwd_rad, axis_hat) * axis_hat
            pn = np.linalg.norm(perp_comp)
            fwd_rad = perp_comp / pn if pn > 1e-6 else ideal_fwd_rad

            groove = groove_offset_rad(h_dir)
            override[(h_id, bp_idx, "FORWARD")] = (
                axis_pt + helix_radius_ang * fwd_rad
            ) / 10.0
            rev_rad = _rodrigues(fwd_rad, axis_hat, groove)
            override[(h_id, bp_idx, "REVERSE")] = (
                axis_pt + helix_radius_ang * rev_rad
            ) / 10.0

    print(
        f"[mrdna coarse DISPLAY] {len(helix_entries)}/{len(h_ids)} helices | "
        f"{len(override)} override entries (actual relaxed axis)",
        flush=True,
    )
    return override


def nuc_pos_override_from_arbd_strands(
    design: Design,
    psf_path: str,
    dcd_path: str,
    frame: int = -1,
    sigma_nt: float = 1.5,
) -> "dict[tuple[str,int,str], np.ndarray]":
    """
    Phase 3b: per-helix cubic spline from mrdna ARBD fine-stage positions.

    The fine stage has 1 DNA bead per base pair at the FORWARD backbone position.
    This function assigns each bead to a helix using the INITIAL fine PDB
    (which is already in NADOC frame), aligns the DCD frame back to NADOC via
    rigid-body fit, then fits a per-helix CubicSpline through the aligned bead
    positions and evaluates at every nucleotide.

    Key improvement over nuc_pos_override_from_mrdna: crossover junction keys
    are INCLUDED rather than excluded, so the atomistic builder starts from a
    CG-realistic gap (~0.3-0.5 nm) rather than an ideal B-DNA clash (0.05 nm).

    Parameters
    ----------
    design    : NADOC Design used to generate the mrdna model.
    psf_path  : Fine-stage PSF (e.g. ``stem-2.psf``).
    dcd_path  : Fine-stage DCD trajectory (e.g. ``output/stem-2.dcd``).
    frame     : DCD frame to use (-1 = last frame).
    sigma_nt  : Gaussian smoothing width in base pairs (default 1.5).

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
    from scipy.spatial.transform import Rotation

    # ── Step 1: helix axis geometry ────────────────────────────────────────
    helix_info: dict = {}
    for h in design.helices:
        ax_s = h.axis_start.to_array() * 10.0  # nm → Å
        ax_e = h.axis_end.to_array() * 10.0
        v = ax_e - ax_s
        axis_hat = v / np.linalg.norm(v)
        x_hat, y_hat = _xy_frame(axis_hat)
        helix_info[h.id] = (
            ax_s,
            axis_hat,
            h.bp_start,
            h.length_bp,
            h.phase_offset,
            h.twist_per_bp_rad,
            x_hat,
            y_hat,
            h.direction,
        )

    h_ids = list(helix_info.keys())
    ax_s_arr = np.array([helix_info[h][0] for h in h_ids])
    axhat_arr = np.array([helix_info[h][1] for h in h_ids])

    # ── Step 2: initial PDB → bead assignment in NADOC frame ─────────────
    # The initial fine PDB is written in NADOC coordinates; use it (not the
    # DCD) for helix/bp assignment so that PBC drift in ARBD doesn't matter.
    init_pdb = psf_path.replace(".psf", ".pdb")
    u_init = mda.Universe(psf_path, init_pdb)
    init_names = np.array([a.name for a in u_init.atoms])
    dna_init_idx = np.where(init_names == "DNA")[0]
    dna_init_pos = u_init.atoms.positions[dna_init_idx].copy()  # (N_dna, 3) Å

    n_dna = len(dna_init_pos)
    n_helices = len(h_ids)
    perp_mat = np.zeros((n_dna, n_helices), dtype=float)
    proj_mat = np.zeros((n_dna, n_helices), dtype=float)
    for j in range(n_helices):
        diff = dna_init_pos - ax_s_arr[j]
        axial = (diff * axhat_arr[j]).sum(axis=1)
        perp_vec = diff - axial[:, None] * axhat_arr[j]
        perp_mat[:, j] = np.linalg.norm(perp_vec, axis=1)
        proj_mat[:, j] = axial

    best_j = perp_mat.argmin(axis=1)
    best_proj = proj_mat[np.arange(n_dna), best_j]
    best_perp = perp_mat[np.arange(n_dna), best_j]

    bp_idx_arr = np.zeros(n_dna, dtype=int)
    for i in range(n_dna):
        bp_start = helix_info[h_ids[best_j[i]]][2]
        bp_idx_arr[i] = int(round(bp_start + best_proj[i] / (BDNA_RISE_PER_BP * 10.0)))

    # ── Step 3: read DCD frame and align to NADOC frame ───────────────────
    # ARBD may drift the COM; rigid-body fit removes translation + rotation.
    u = mda.Universe(psf_path, dcd_path)
    if frame == -1:
        u.trajectory[-1]
    else:
        u.trajectory[frame]
    all_pos = _unwrapped_universe_positions(u, u_init.atoms.positions)
    all_names = np.array([a.name for a in u.atoms])
    dna_sim_idx = np.where(all_names == "DNA")[0]
    dna_sim_pos = all_pos[dna_sim_idx].copy()  # (N_dna, 3) Å, ARBD frame

    # Rigid-body alignment: rotate/translate dna_sim_pos → NADOC frame
    center_init = dna_init_pos.mean(0)
    center_sim = dna_sim_pos.mean(0)
    rot, _rmsd = Rotation.align_vectors(
        dna_init_pos - center_init,
        dna_sim_pos - center_sim,
    )
    dna_aligned = rot.apply(dna_sim_pos - center_sim) + center_init  # (N_dna, 3) Å

    # ── Step 4: deduplicate: keep closest bead per (h_id, bp_idx) ─────────
    # Each DNA bead in the fine stage represents the FORWARD backbone of 1 bp.
    # No direction assignment is needed; REVERSE positions are reconstructed
    # below from the helix axis + minor-groove rotation.
    bp_to_bead: dict[tuple, tuple] = {}  # (h_id, bp_idx) → (aligned_pos, perp_dist)
    for i in range(n_dna):
        h_id = h_ids[int(best_j[i])]
        bp_idx = bp_idx_arr[i]
        pd = float(best_perp[i])
        key = (h_id, bp_idx)
        if key not in bp_to_bead or pd < bp_to_bead[key][1]:
            bp_to_bead[key] = (dna_aligned[i].copy(), pd)

    # ── Step 5: per-helix spline + FORWARD/REVERSE override ───────────────
    helix_entries: dict = defaultdict(list)
    for (h_id, bp_idx), (pos, _) in bp_to_bead.items():
        helix_entries[h_id].append((bp_idx, pos))
    for entries in helix_entries.values():
        entries.sort(key=lambda x: x[0])

    helix_radius_ang = HELIX_RADIUS * 10.0
    override: dict[tuple, np.ndarray] = {}

    for h_id, entries in helix_entries.items():
        (
            ax_s,
            ideal_axis_hat,
            bp_start,
            length_bp,
            phase_offset,
            twist,
            x_hat,
            y_hat,
            h_dir,
        ) = helix_info[h_id]

        bp_idxs = np.array([e[0] for e in entries])
        raw_pos = np.array([e[1] for e in entries], dtype=float)  # (K, 3) Å

        # Gaussian smoothing in bead space
        if len(raw_pos) >= 3 and sigma_nt > 0:
            raw_pos = gaussian_filter1d(raw_pos, sigma=sigma_nt, axis=0, mode="nearest")

        if len(bp_idxs) < 2:
            continue

        cs = CubicSpline(bp_idxs.astype(float), raw_pos, bc_type="not-a-knot")
        t_lo = float(bp_idxs[0])
        t_hi = float(bp_idxs[-1])

        for bp_idx in range(bp_start, bp_start + length_bp):
            local_i = bp_idx - bp_start

            # mrDNA's per-bp 'DNA' bead is an AXIS/centroid bead — it sits on the helix
            # centreline (~2-4 Å off), NOT on the spiralling backbone.  The ~34 deg/bp
            # helical twist lives in the separate ORIENTATION ('O') bead, which this
            # override does not read.  So the DNA-bead spline is the relaxed AXIS, and
            # the backbone must be reconstructed by imposing IDEAL B-DNA twist AROUND
            # that axis (mrDNA's orientation potential holds local twist near B-DNA).
            # Deriving the azimuth from the DNA-bead radial instead (the old code) read
            # the helix's rigid lateral relaxation offset as if it were twist phase —
            # a constant direction per helix → a near-zero-twist ladder seed.  This
            # mirrors the display path (nuc_pos_override_display_from_coarse); straight
            # tangent extrapolation past a beadless end (see _relaxed_axis_at_bp).
            axis_pt, axis_hat = _relaxed_axis_at_bp(
                cs, bp_idx, t_lo, t_hi, ideal_axis_hat, BDNA_RISE_PER_BP * 10.0
            )

            fwd_angle = phase_offset + local_i * twist
            ideal_fwd_rad = math.cos(fwd_angle) * x_hat + math.sin(fwd_angle) * y_hat
            perp_comp = ideal_fwd_rad - np.dot(ideal_fwd_rad, axis_hat) * axis_hat
            pn = np.linalg.norm(perp_comp)
            fwd_rad = perp_comp / pn if pn > 1e-6 else ideal_fwd_rad

            groove = groove_offset_rad(h_dir)
            fwd_ang = axis_pt + helix_radius_ang * fwd_rad
            rev_rad = _rodrigues(fwd_rad, axis_hat, groove)
            rev_ang = axis_pt + helix_radius_ang * rev_rad

            override[(h_id, bp_idx, "FORWARD")] = fwd_ang / 10.0  # Å → nm
            override[(h_id, bp_idx, "REVERSE")] = rev_ang / 10.0

    n_helices_covered = len(helix_entries)
    print(
        f"[arbd strands] {n_helices_covered}/{len(h_ids)} helices | "
        f"{len(override)} override entries (crossovers included)",
        flush=True,
    )
    return override


def _ssdna_runs(design: Design) -> list:
    """Enumerate contiguous single-stranded (unpaired) nucleotide runs, each with
    its anchoring 'root' — the paired nucleotide adjacent to the run in the same
    strand's 5'→3' chain.  Overhangs and interior unpaired runs both surface here.

    Reuses ``_build_nt_arrays`` (the SAME enumerator mrDNA is built from) for the
    pairing + 5'→3' topology, so no independent — and error-prone — strand/polarity
    traversal is done here (CLAUDE.md DNA-topology rule).  Pure: no mrDNA/ARBD/GPU.

    Returns a list of dicts:
      ``keys``          : [(h_id, bp, dir_str), ...] ss nucleotides, 5'→3'
      ``ideal_nm``      : matching ideal backbone positions (nm, NADOC frame)
      ``root_key``      : (h_id, bp, dir_str) of the anchoring paired nt, or None
      ``root_ideal_nm`` : its ideal position (nm), or None
      ``root_side``     : '5p' if the root precedes the run, '3p' if it follows
    """
    import numpy as np

    r, bp, _stack, three_prime, _orient, _seq, nt_key = _build_nt_arrays(
        design, return_nt_key=True
    )
    N = len(bp)
    idx_to_key: list = [None] * N
    for (h_id, bp_idx, direction, k), i in nt_key.items():
        if k == 0:
            idx_to_key[i] = (h_id, bp_idx, direction)

    has_incoming = np.zeros(N, dtype=bool)
    for i in range(N):
        j = int(three_prime[i])
        if j >= 0:
            has_incoming[j] = True

    runs: list = []
    for start in range(N):
        if has_incoming[start]:
            continue  # not a 5' chain start
        chain: list = []
        i, guard = start, 0
        while i >= 0 and guard <= N:
            chain.append(i)
            i = int(three_prime[i])
            guard += 1

        n = len(chain)
        p = 0
        while p < n:
            if bp[chain[p]] >= 0:
                p += 1
                continue
            q = p
            while q < n and bp[chain[q]] < 0:
                q += 1
            run_idxs = chain[p:q]
            # 5′-side root = the paired nt just before the run; 3′-side = just after.
            # A crossover-spanning run (ds…ss→crossover→ss…ds) has BOTH — kept so the
            # DISPLAY can anchor both ends (single-anchor floats the far junction).
            root5 = chain[p - 1] if (p - 1 >= 0 and bp[chain[p - 1]] >= 0) else None
            root3 = chain[q] if (q < n and bp[chain[q]] >= 0) else None
            root_idx, root_side = (root5, "5p") if root5 is not None else (root3, "3p")
            runs.append(
                {
                    "keys": [idx_to_key[j] for j in run_idxs],
                    "ideal_nm": [r[j] / 10.0 for j in run_idxs],
                    "root_key": idx_to_key[root_idx] if root_idx is not None else None,
                    "root_ideal_nm": (r[root_idx] / 10.0)
                    if root_idx is not None
                    else None,
                    "root_side": root_side,
                    "root5_key": idx_to_key[root5] if root5 is not None else None,
                    "root5_ideal_nm": (r[root5] / 10.0) if root5 is not None else None,
                    "root3_key": idx_to_key[root3] if root3 is not None else None,
                    "root3_ideal_nm": (r[root3] / 10.0) if root3 is not None else None,
                }
            )
            p = q
    return runs


def _blend_run_both_ends(ideal, d5, d3):
    """Place a bridging ss run by adding each nucleotide the ideal→relaxed displacement
    of its NEAR root, linearly blended 5′→3′ (``d5`` at the 5′ end, ``d3`` at the 3′).

    ``ideal`` is the run's ideal backbone positions in 5′→3′ order.  The run's first nt
    is one bond from the 5′ root and its last nt one bond from the 3′ root, so applying
    each root's displacement lands BOTH ends one bond from their relaxed roots while the
    smoothly-varying offset preserves the run's ideal (crossover-loop) shape.  Fixes the
    stretched far junction a single-end anchor leaves floating.  Pure geometry."""
    n = len(ideal)
    out = []
    for i in range(n):
        f = 0.5 if n == 1 else i / (n - 1)
        out.append(
            np.asarray(ideal[i], dtype=float)
            + (1.0 - f) * np.asarray(d5, dtype=float)
            + f * np.asarray(d3, dtype=float)
        )
    return out


def nuc_pos_override_ssdna_from_arbd(
    design: Design,
    psf_path: str,
    dcd_path: str,
    ds_override: "dict[tuple[str,int,str], np.ndarray]",
    frame: int = -1,
    min_beads_for_spline: int = 2,
    prefer_continuity: bool = False,
) -> "dict[tuple[str,int,str], np.ndarray]":
    """ssDNA / overhang seed positions from a fine-stage mrDNA run.

    The dsDNA override (``nuc_pos_override_from_arbd_strands``) covers only in-helix
    base pairs; overhang and interior-unpaired nucleotides get NO entry and would
    otherwise seed at the ORIGINAL design-axis extrapolation — detached from the
    now-relaxed body (the sticky-end clash source).  This fills them two ways:

      A (relaxed CG conformation): mrDNA already simulates ssDNA as ``NAS`` beads.
        For a run with ≥ ``min_beads_for_spline`` assigned NAS beads, spline the
        Kabsch-aligned bead positions and evaluate per nucleotide, then shift the
        run so its root-side end meets the relaxed root (continuity).
      B (root-anchored fallback): for short runs (too few NAS beads to resolve a
        curve — the typical 2-8 nt sticky end, which mrDNA beads at ~1 per 5 nt),
        translate the run's ideal geometry so its root nt sits on the RELAXED root
        position.  No CG detail, but continuous with the moved helix and no jump.

    Returns ``{(h_id, bp, dir_str) → pos_nm}`` for ss nucleotides only.  Merge as
    ``{**ds_override, **ss_override}`` so ss wins at any shared (interior) key.
    Physical-layer only.
    """
    import sys

    sys.path.insert(0, _MRDNA_TOOL_PATH)
    import numpy as np
    import MDAnalysis as mda
    from scipy.interpolate import CubicSpline
    from scipy.spatial.transform import Rotation

    runs = _ssdna_runs(design)
    if not runs:
        return {}

    init_pdb = psf_path.replace(".psf", ".pdb")
    u_init = mda.Universe(psf_path, init_pdb)
    names = np.array([a.name for a in u_init.atoms])
    dna_i = np.where(names == "DNA")[0]
    nas_i = np.where(names == "NAS")[0]
    dna_init = u_init.atoms.positions[dna_i].astype(float)  # Å, NADOC frame
    nas_init = u_init.atoms.positions[nas_i].astype(float)

    u = mda.Universe(psf_path, dcd_path)
    u.trajectory[-1 if frame == -1 else frame]
    all_sim = _unwrapped_universe_positions(u, u_init.atoms.positions)
    dna_sim = all_sim[dna_i].astype(float)
    nas_sim = all_sim[nas_i].astype(float)

    # Align the ssDNA beads with the SAME rigid transform as the ds body (from the
    # DNA beads) so ss stays consistent with the relaxed dsDNA it attaches to.
    if len(dna_init) >= 3 and len(dna_sim) == len(dna_init) and len(nas_sim):
        ci, cs = dna_init.mean(0), dna_sim.mean(0)
        rot, _ = Rotation.align_vectors(dna_init - ci, dna_sim - cs)
        nas_algn_nm = (rot.apply(nas_sim - cs) + ci) / 10.0
    else:
        nas_algn_nm = nas_sim / 10.0
    nas_init_nm = nas_init / 10.0

    # Assign each NAS bead to the run holding its nearest ideal ss nucleotide.
    run_beads: list = [[] for _ in runs]
    if len(nas_i):
        ideal_pts, ideal_run = [], []
        for ri, run in enumerate(runs):
            for pt in run["ideal_nm"]:
                ideal_pts.append(pt)
                ideal_run.append(ri)
        ideal_pts = np.array(ideal_pts)
        for bi in range(len(nas_i)):
            d = np.linalg.norm(ideal_pts - nas_init_nm[bi], axis=1)
            run_beads[ideal_run[int(d.argmin())]].append(nas_algn_nm[bi])

    # DO-NO-HARM selector: a long overhang in a dense bundle can clash the body under
    # ANY straight placement (including the current ideal one).  Rather than trust one
    # heuristic, we generate up to three candidates per run and keep whichever sits
    # FARTHEST from the relaxed dsDNA body — so the ss handling can only ever improve
    # (or match) the clearance the ideal placement already had.  The body proxy is the
    # relaxed ds backbone cloud (ds_override, ss keys removed); coarse but sufficient
    # for a RELATIVE choice (the atomistic clash is checked by the seed oracle).
    from scipy.spatial import cKDTree

    ss_keys = {k for run in runs for k in run["keys"] if k is not None}
    body_pts = np.array([v for k, v in ds_override.items() if k not in ss_keys])
    body_tree = cKDTree(body_pts) if len(body_pts) else None

    def _clearance(pts) -> float:
        if body_tree is None:
            return float("inf")
        return float(body_tree.query(np.asarray(pts))[0].min())

    override: dict = {}
    n_spline = n_translate = n_blend = n_ideal = 0
    for ri, run in enumerate(runs):
        keys, ideal = run["keys"], [np.asarray(p) for p in run["ideal_nm"]]
        n = len(keys)
        root_relaxed = ds_override.get(run["root_key"]) if run["root_key"] else None
        anchor_idx = 0 if run["root_side"] != "3p" else n - 1

        candidates: list = [("ideal", ideal)]  # detached ideal = today's behavior

        # B: translate the ideal run rigidly onto the relaxed root — PRESERVES the
        # junction backbone bond (root-adjacent nt lands one bond-length from the
        # root, NOT on top of it, which would make atoms coincident → LJ=2e37).
        if root_relaxed is not None and run["root_ideal_nm"] is not None:
            disp = np.asarray(root_relaxed) - np.asarray(run["root_ideal_nm"])
            pos_b = [ideal[i] + disp for i in range(n)]
            candidates.append(("translate", pos_b))
        else:
            pos_b = ideal

        # A: spline the assigned NAS beads (real relaxed ss conformation), hooked onto
        # B's anchor position so the junction bond is preserved.
        beads = run_beads[ri]
        if len(beads) >= min_beads_for_spline and n >= 2:
            B = np.array(beads)
            axis = ideal[-1] - ideal[0]
            if np.linalg.norm(axis) >= 1e-6:
                B = B[np.argsort(B @ (axis / np.linalg.norm(axis)))]
            seg = np.linalg.norm(np.diff(B, axis=0), axis=1)
            t = np.concatenate([[0.0], np.cumsum(seg)])
            if t[-1] >= 1e-6:
                try:
                    cs_spline = CubicSpline(t / t[-1], B, axis=0)
                    pos_a = [np.asarray(cs_spline(i / (n - 1))) for i in range(n)]
                    shift = pos_b[anchor_idx] - pos_a[anchor_idx]
                    candidates.append(("spline", [p + shift for p in pos_a]))
                except Exception:  # noqa: BLE001 — spline failure → drop candidate
                    pass

        # C (both-ends anchor): a run bridging two ds segments (a crossover-spanning
        # scaffold loop: ds…ss→crossover→ss…ds) has a relaxed root at BOTH ends.
        # Anchoring only one (B/spline) leaves the FAR junction floating → a stretched
        # ss/ds bond (6hb_2xT far end).  Pin both by adding each nucleotide the
        # ideal→relaxed displacement of its NEAR root, linearly blended along the run.
        # Preserves the ideal loop shape (incl. the crossover excursion) while landing
        # both ends one bond-length from their relaxed roots.  DISPLAY only — appended
        # last so prefer_continuity picks it when both roots exist.
        r5r = ds_override.get(run.get("root5_key")) if run.get("root5_key") else None
        r3r = ds_override.get(run.get("root3_key")) if run.get("root3_key") else None
        if (
            prefer_continuity
            and r5r is not None
            and r3r is not None
            and run.get("root5_ideal_nm") is not None
            and run.get("root3_ideal_nm") is not None
        ):
            d5 = np.asarray(r5r) - np.asarray(run["root5_ideal_nm"])
            d3 = np.asarray(r3r) - np.asarray(run["root3_ideal_nm"])
            candidates.append(("blend", _blend_run_both_ends(ideal, d5, d3)))

        if prefer_continuity:
            # DISPLAY: continuity beats clearance.  The render must show each ss run
            # attached to its relaxed root(s) — short ss/ds junction + crossover
            # backbone bonds — even if that sits closer to the body (clash avoidance
            # only matters for the MD seed, not the picture).  Take the highest-fidelity
            # candidate available; they were appended in increasing priority
            # (ideal < translate < spline < blend), so the last one is best.  A
            # bridging run gets 'blend' (both ends pinned); a one-sided overhang gets
            # spline/translate; a rootless run stays 'ideal' → no override → a free
            # overhang keeps its current phantom display.
            label, chosen = candidates[-1]
            # Sparse/mis-assigned NAS beads can make a nominal spline double back
            # or leap across a shared child helix. Never let display fidelity trump
            # covalent continuity: reject a spline whose internal or root-junction
            # steps exceed a generous phosphodiester envelope. The translated ideal
            # candidate preserves the relaxed attachment and every native bond.
            if label == "spline":
                steps = [
                    float(np.linalg.norm(np.asarray(b) - np.asarray(a)))
                    for a, b in zip(chosen, chosen[1:])
                ]
                if root_relaxed is not None:
                    edge = chosen[0] if anchor_idx == 0 else chosen[-1]
                    steps.append(float(np.linalg.norm(np.asarray(edge) - root_relaxed)))
                if steps and (min(steps) < 0.25 or max(steps) > 1.20):
                    label, chosen = next(
                        (candidate for candidate in reversed(candidates[:-1])
                         if candidate[0] == "translate"),
                        ("ideal", ideal),
                    )
        else:
            label, chosen = max(candidates, key=lambda c: _clearance(c[1]))
        n_spline += label == "spline"
        n_translate += label == "translate"
        n_blend += label == "blend"
        n_ideal += label == "ideal"
        # 'ideal' == leaving the nt at its detached design position; emit NO override
        # for it so build_atomistic uses exactly the current path (no change).
        if label != "ideal":
            for i, key in enumerate(keys):
                if key is not None:
                    override[key] = np.asarray(chosen[i], dtype=float)

    print(
        f"[ssdna seed] {len(runs)} ss run(s) | {len(override)} nt overrides | "
        f"placement: {n_spline} spline, {n_translate} translate, {n_blend} blend, "
        f"{n_ideal} left-ideal",
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
            excluded.add((d0.helix_id, d0.end_bp, d0.direction.value))
            excluded.add((d1.helix_id, d1.start_bp, d1.direction.value))
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


def _orientation_matrix(radial: np.ndarray, axis_hat: np.ndarray) -> np.ndarray:
    """3×3 orientation matrix with columns [radial, azimuthal, axis_hat]."""
    azimuthal = np.cross(axis_hat, radial)
    return np.column_stack([radial, azimuthal, axis_hat])


def _extension_bead_positions(
    ext,
    anchor_pos: np.ndarray,
    radial: np.ndarray,
    axis_hat: np.ndarray,
    direction: str,
) -> List[np.ndarray]:
    """Ideal backbone positions (Å) of a strand extension's sequence beads, bead
    ``i`` = distance-rank from the anchor (i=0 nearest the duplex).

    The SAME outward quadratic Bézier the display and oxDNA already lay tails on
    (``design_geometry._strand_extension_geometry``), recomputed here in the
    UNDEFORMED helix frame ``_build_nt_arrays`` works in: arc length
    ``n_total * SSDNA_CONTOUR_PER_NT_NM`` with bead *i* at ``t=(i+1)/n_total``, so
    consecutive beads sit ~one ssDNA contour length (0.68 nm) apart and the last one
    lands ON the arc end.  ``n_total`` counts a modification bead if there is one
    (it occupies the outermost slot in the geometry layer, though it is NOT DNA and
    never becomes a bead here) — so all three engines put the DNA beads at the same
    fractions of the same arc.

    The bow is taken in the ANCHOR'S OWN frame (⟂ its outward radial, along the
    direction the strand was heading), never a world axis: a world bow degenerates
    when a rotation lines the radial up with it.
    """
    from backend.core.design_geometry import _EXT_BOW_FRAC

    n_seq = len(ext.sequence or "")
    n_total = n_seq + (1 if ext.modification is not None else 0)
    if n_seq == 0 or n_total == 0:
        return []

    arc_len = n_total * SSDNA_CONTOUR_PER_NT_NM * _NM_TO_ANGSTROM
    p0 = np.asarray(anchor_pos, dtype=float)
    p2 = p0 + radial * arc_len

    chain_tan = axis_hat if direction == "FORWARD" else -axis_hat
    bow_dir = chain_tan if ext.end == "three_prime" else -chain_tan
    bow_dir = bow_dir - float(np.dot(bow_dir, radial)) * radial  # ⟂ radial
    bow_len = float(np.linalg.norm(bow_dir))
    if bow_len < 1e-6:  # degenerate frame (tangent ∥ radial): any ⟂ direction
        bow_dir = np.cross(radial, np.array([0.0, 0.0, 1.0]))
        if float(np.linalg.norm(bow_dir)) < 1e-6:
            bow_dir = np.cross(radial, np.array([0.0, 1.0, 0.0]))
        bow_len = float(np.linalg.norm(bow_dir))
    bow_dir = bow_dir / bow_len

    p1 = (p0 + p2) * 0.5 + bow_dir * (arc_len * _EXT_BOW_FRAC)

    out: List[np.ndarray] = []
    for i in range(n_seq):
        t = (i + 1) / n_total
        out.append((1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t**2 * p2)
    return out


def _build_nt_arrays(
    design: Design,
    return_nt_key: bool = False,
    return_identity: bool = False,
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

    Synthetic beads: crossover extra-base inserts carry NO nt_key (they are keyed only
    by their flanking real nucleotides), while strand-extension tail beads DO — under
    the shared geometry key ``("__ext_<ext_id>", bead_index, direction, 0)``, so the
    display / ssDNA read-back paths can address them the way oxDNA and NAMD already do.
    Any consumer walking nt_key must therefore skip ``h_id.startswith("__")``.
    """
    ls_map = _build_loop_skip_map(design)

    # ── The HELICAL SITE, read rather than re-derived (Phase 2, 2026-08-07) ────────
    #
    # This function used to re-implement geometry.py's helix formula inline — axis point
    # with loop copies, twist angle, radial, bead at HELIX_RADIUS — reading `h.phase_offset`
    # / `h.twist_per_bp_rad` STRAIGHT OFF the stored helix.  Every other representation goes
    # through `effective_helix_for_geometry`, which re-derives phase, axis and twist from
    # `grid_pos` for a lattice helix, so mrDNA was the only engine seeded on the stored
    # values.  Measured, that was not academic:
    #
    #   * every HONEYCOMB design kept the pre-TD-29 incommensurate twist (34.3 vs the
    #     commensurate 34.2857 deg/bp) — the crossover-strain ramp that was fixed
    #     everywhere else on 2026-08-06, and it grows without bound along a helix;
    #   * `Examples/6hb_test.nadoc` was 175 deg out of phase on one helix, i.e. 19.97 A
    #     (a full helix diameter) away from the geometry the user is looking at.
    #
    # Keyed (helix_id, bp_index, direction, copy_k) with copy_k the emission order within a
    # bp, which is the same convention `atomistic.py` uses for loop copies.
    from backend.core.deformation import effective_helix_for_geometry  # noqa: PLC0415
    from backend.core.geometry import nucleotide_positions  # noqa: PLC0415

    site: Dict[Tuple[str, int, str, int], object] = {}
    helix_geom: Dict[str, tuple] = {}
    for h in design.helices:
        eh = effective_helix_for_geometry(h, design)
        ax_s = eh.axis_start.to_array()
        ax_e = eh.axis_end.to_array()
        axis_hat = ax_e - ax_s
        axis_hat /= np.linalg.norm(axis_hat)
        helix_geom[h.id] = (ax_s, axis_hat, eh.bp_start)
        seen: Dict[Tuple[int, str], int] = {}
        for n in nucleotide_positions(eh):
            dk = (n.bp_index, n.direction.value)
            k = seen.get(dk, 0)
            seen[dk] = k + 1
            site[(h.id, n.bp_index, n.direction.value, k)] = n

    # Extruded overhang domains may intentionally retain parent-rail bp labels far
    # outside their dedicated short helix's stored span.  The renderer already
    # creates these occupied extended sites; mrDNA must enumerate the same topology
    # or the overhang is silently absent from the simulation.  Add only missing
    # occupied keys so the long-established in-span duplex frames remain unchanged.
    from types import SimpleNamespace

    from backend.core.design_geometry import _geometry_for_helices

    seen_extended: Dict[Tuple[str, int, str], int] = {}
    for g in _geometry_for_helices(design, None, junction_balance=False):
        dk = (g["helix_id"], g["bp_index"], g["direction"])
        k = seen_extended.get(dk, 0)
        seen_extended[dk] = k + 1
        sk = (*dk, k)
        if sk in site or str(g["helix_id"]).startswith("__"):
            continue
        bn = np.asarray(g["base_normal"], dtype=float)
        site[sk] = SimpleNamespace(
            position=np.asarray(g["backbone_position"], dtype=float),
            radial_hat=-bn,
            axis_tangent=np.asarray(g["axis_tangent"], dtype=float),
        )

    # ── Pass 1: enumerate nucleotides and assign indices ──────────────────────
    # Index map: (helix_id, bp_index, 'FORWARD'|'REVERSE') → global nt index
    nt_key: Dict[Tuple[str, int, str], int] = {}

    positions: List[np.ndarray] = []
    orientations: List[np.ndarray] = []
    seq_chars: List[str] = []
    identity_meta: List[dict] = []

    # Per-strand list of global indices in 5′→3′ order.
    strand_seqs: List[List[int]] = []

    has_sequence = any(s.sequence is not None for s in design.strands)

    # Crossover extra bases (e.g. "TT") are single-stranded nucleotides on the
    # crossover-owning strand, inserted at the domain→domain transition.  Reuse the
    # oxDNA path's owning-strand junction map so the two engines agree on where the
    # inserts go (same reciprocal-crossover handling).  Keyed (strand_id, prev_di).
    # Lazy import avoids any import-time cycle between core and physics.
    from backend.physics.oxdna_interface import (
        crossover_extra_base_junctions,
        strand_extension_tails,
    )

    xb_junctions = crossover_extra_base_junctions(design)

    # Strand extensions (5′/3′ terminal ssDNA tails).  ONE anchor instead of the
    # extra base's two: the tail hangs off the strand's first/last real nucleotide and
    # its far end is free.  ``strand_extension_tails`` drops modification-only
    # extensions (a fluorophore is not DNA → zero beads).
    ext_tails = strand_extension_tails(design)

    # Recorded for the stacking pass: (prev_real_idx, [extra_base_idx...], next_real_idx).
    extra_base_inserts: List[Tuple[int, List[int], int]] = []
    # Recorded for the stacking pass: each tail's bead chain in 5′→3′ order, INCLUDING
    # its anchor (5′ tail: [tip … bead0, anchor]; 3′ tail: [anchor, bead0 … tip]).
    extension_chains: List[List[int]] = []

    for strand in design.strands:
        strand_indices: List[int] = []
        seq_offset = 0

        strand_tails = ext_tails.get(strand.id, {})
        # (idx, backbone_pos_ang, radial, axis_hat, direction) of this strand's FIRST
        # and LAST emitted real nucleotide — the anchors its 5′ / 3′ tails hang off.
        first_anchor: Optional[tuple] = None
        last_anchor: Optional[tuple] = None

        # Which domains emit ≥1 nucleotide — guards against arming an insert whose
        # following domain is entirely skipped (its flank would land on the wrong nt).
        domain_emits = [
            any(ls_map.get((dom.helix_id, b), 0) > -1 for b in domain_bp_range(dom))
            for dom in strand.domains
        ]

        # (crossover_id, extra_bases_str, prev_real_idx) awaiting the next flank nt.
        pending_xb: Optional[Tuple[str, str, int]] = None

        for di, domain in enumerate(strand.domains):
            domain_ordinal = 0
            h_id = domain.helix_id
            ax_s, axis_hat, bp_start = helix_geom[h_id]
            direction = domain.direction.value  # 'FORWARD' or 'REVERSE'

            for bp_idx in domain_bp_range(domain):
                delta = ls_map.get((h_id, bp_idx), 0)
                if delta <= -1:
                    continue  # skip — no nucleotide at this position

                # delta=0 → 1 copy; delta=+1 → 2 copies evenly straddling the bp.
                n_copies = max(1, delta + 1)

                # REVERSE strand moves in −axis direction; loop copies must be
                # encountered k=1 (higher axial) first, then k=0 (lower axial).
                k_range = (
                    range(n_copies - 1, -1, -1)
                    if direction == "REVERSE"
                    else range(n_copies)
                )
                for k in k_range:
                    nuc = site.get((h_id, bp_idx, direction, k))
                    if nuc is None:
                        continue  # geometry emitted no nucleotide here (skip/short helix)

                    rad = nuc.radial_hat
                    backbone_ang = nuc.position * _NM_TO_ANGSTROM
                    orient = _orientation_matrix(rad, nuc.axis_tangent)

                    char = "N"
                    if strand.sequence is not None and seq_offset < len(
                        strand.sequence
                    ):
                        char = strand.sequence[seq_offset]
                    seq_offset += 1  # one sequence character per copy

                    idx = len(positions)
                    nt_key[(h_id, bp_idx, direction, k)] = idx
                    positions.append(backbone_ang)
                    orientations.append(orient)
                    seq_chars.append(char)
                    identity_meta.append({
                        "strand_id": strand.id,
                        "segment_kind": "domain",
                        "segment_id": str(di),
                        "nucleotide_ordinal": domain_ordinal,
                        "copy": k,
                        "helix_id": h_id,
                        "bp_index": bp_idx,
                        "direction": direction,
                        "strand_type": strand.strand_type.value,
                        "classification": (
                            "loop_copy" if k else
                            "overhang" if domain.overhang_id else
                            "linker" if strand.strand_type.value == "linker" else
                            "unpaired" if domain.binds_overhang_id else
                            "duplex"
                        ),
                    })
                    domain_ordinal += 1

                    anchor_rec = (idx, backbone_ang, rad, axis_hat, direction)
                    if first_anchor is None:
                        first_anchor = anchor_rec
                    last_anchor = anchor_rec

                    # This real nt is the *next* flank of a pending extra-base insert:
                    # materialise the single-stranded beads between prev and this nt,
                    # threading their indices into the strand chain (prev → eb… → this).
                    if pending_xb is not None:
                        xo_id, extra, prev_idx = pending_xb
                        p0 = positions[prev_idx]
                        p1 = backbone_ang
                        n = len(extra)
                        eb_idxs: List[int] = []
                        for j, base in enumerate(extra):
                            t = (j + 1) / (n + 1)
                            eb_idx = len(positions)
                            positions.append(p0 * (1.0 - t) + p1 * t)
                            orientations.append(orientations[prev_idx])
                            seq_chars.append(base)
                            identity_meta.append({
                                "strand_id": strand.id,
                                "segment_kind": "crossover_insert",
                                "segment_id": xo_id,
                                "nucleotide_ordinal": j,
                                "copy": 0,
                                "helix_id": "__xb__",
                                "bp_index": xo_id,
                                "direction": j,
                                "strand_type": strand.strand_type.value,
                                "classification": "crossover_insert",
                            })
                            strand_indices.append(eb_idx)
                            eb_idxs.append(eb_idx)
                        extra_base_inserts.append((prev_idx, eb_idxs, idx))
                        pending_xb = None

                    strand_indices.append(idx)

            # Arm an insert if this domain owns an extra-base crossover AND the next
            # domain will emit a flank nucleotide to bridge to.
            hit = xb_junctions.get((strand.id, di))
            if (
                hit is not None
                and di + 1 < len(strand.domains)
                and domain_emits[di + 1]
                and strand_indices
            ):
                pending_xb = (hit[0], hit[1], strand_indices[-1])

        # ── Strand-extension tails ────────────────────────────────────────────
        # Bead ``i`` is the geometry layer's distance-rank from the anchor (i=0
        # nearest the duplex), so a 5′ tail runs 5′→3′ only when walked OUTERMOST
        # FIRST (i = n-1 … 0) — the outermost bead IS the strand's 5′ terminus — and a
        # 3′ tail innermost-first (i = 0 … n-1).  Either way ``ordinal`` indexes
        # ``ext.sequence`` directly (scadnano stores it 5′→3′): the tail carries its OWN
        # base identity and must never consume the strand's sequence cursor.
        def _emit_tail(ext, anchor: tuple) -> List[int]:
            a_idx, a_pos, a_rad, a_axis, a_dir = anchor
            pts = _extension_bead_positions(ext, a_pos, a_rad, a_axis, a_dir)
            n = len(pts)
            beads = range(n - 1, -1, -1) if ext.end == "five_prime" else range(n)
            out: List[int] = []
            for ordinal, i in enumerate(beads):
                b_idx = len(positions)
                nt_key[(f"{_EXT_PREFIX}{ext.id}", i, a_dir, 0)] = b_idx
                positions.append(pts[i])
                orientations.append(orientations[a_idx])
                seq_chars.append(ext.sequence[ordinal])
                identity_meta.append({
                    "strand_id": strand.id,
                    "segment_kind": "extension",
                    "segment_id": ext.id,
                    "nucleotide_ordinal": ordinal,
                    "copy": 0,
                    "helix_id": f"{_EXT_PREFIX}{ext.id}",
                    "bp_index": i,
                    "direction": a_dir,
                    "strand_type": strand.strand_type.value,
                    "classification": "extension",
                })
                out.append(b_idx)
            return out

        ext5 = strand_tails.get("five_prime")
        if ext5 is not None and first_anchor is not None:
            tail = _emit_tail(ext5, first_anchor)
            if tail:
                strand_indices[0:0] = tail  # tip … bead0 → anchor …
                extension_chains.append([*tail, first_anchor[0]])

        ext3 = strand_tails.get("three_prime")
        if ext3 is not None and last_anchor is not None:
            tail = _emit_tail(ext3, last_anchor)
            if tail:
                strand_indices.extend(tail)  # … anchor → bead0 … tip
                extension_chains.append([last_anchor[0], *tail])

        strand_seqs.append(strand_indices)

    N = len(positions)
    if N == 0:
        raise ValueError("Design has no nucleotides (all bases skipped?).")

    r = np.array(positions, dtype=float)
    orient_arr = np.array(orientations, dtype=float)

    # ── Pass 2: base-pair array ───────────────────────────────────────────────
    bp_arr = -np.ones(N, dtype=int)
    for (h_id, bp_idx, direction, k), idx in nt_key.items():
        # Extension tail beads are free ssDNA — no WC partner, so they stay at −1.
        # Guard on the EXTENSION prefix, never on `isinstance(bp_idx, int)`: a tail's
        # bp_index is an ordinary int ≥ 0 (unlike __xb__'s crossover-id string), so it
        # passes every isinstance filter written to catch extra bases.  Note the test is
        # `__ext_`, not `__`: a ``__lnk__`` linker helix is a VIRTUAL helix carrying real
        # WC-paired duplex, and must keep pairing normally.
        if h_id.startswith(_EXT_PREFIX):
            continue
        partner_dir = "REVERSE" if direction == "FORWARD" else "FORWARD"
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
                k_range = (
                    range(n_copies - 1, -1, -1)
                    if direction == "REVERSE"
                    else range(n_copies)
                )
                for k in k_range:
                    idx = nt_key.get((h_id, bp_idx, direction, k))
                    if idx is None:
                        continue
                    if prev_idx is not None:
                        stack_arr[prev_idx] = idx
                    prev_idx = idx

            # Check for intrahelical continuation past the domain end.
            if prev_idx is not None:
                next_bp = (
                    domain.end_bp + 1 if direction == "FORWARD" else domain.end_bp - 1
                )
                # For REVERSE direction, the first copy encountered is k=n_copies-1.
                next_delta = ls_map.get((h_id, next_bp), 0)
                next_n_copies = max(1, next_delta + 1) if next_delta > -1 else 0
                next_k = 0 if direction == "FORWARD" else next_n_copies - 1
                next_idx = nt_key.get((h_id, next_bp, direction, next_k))
                if next_idx is not None:
                    stack_arr[prev_idx] = next_idx

    # Thread stacking through crossover extra-base inserts (the domain walk above
    # skips them, and cross-helix junctions leave the flank stack unset).  The
    # 3′-chain is already threaded via strand_seqs in Pass 3.
    for prev_idx, eb_idxs, next_idx in extra_base_inserts:
        chain = [prev_idx, *eb_idxs, next_idx]
        for a, b in zip(chain[:-1], chain[1:]):
            stack_arr[a] = b

    # Thread stacking along each extension tail (anchor → tail for 3′, tail → anchor
    # for 5′).  Runs AFTER the domain walk on purpose: a 3′ tail's anchor may have been
    # given an intrahelical (across-the-nick) stack partner above, but its real 3′
    # neighbour is the tail, so the tail wins.
    for chain in extension_chains:
        for a, b in zip(chain[:-1], chain[1:]):
            stack_arr[a] = b

    seq_list = seq_chars if has_sequence else None
    if return_identity:
        return (
            r, bp_arr, stack_arr, three_prime_arr, orient_arr, seq_list,
            nt_key if return_nt_key else None, identity_meta, strand_seqs,
        )
    if return_nt_key:
        return r, bp_arr, stack_arr, three_prime_arr, orient_arr, seq_list, nt_key
    return r, bp_arr, stack_arr, three_prime_arr, orient_arr, seq_list
