"""
API layer — WebSocket handlers for MD trajectory streaming and mrdna CG relaxation.

Routes
──────
  /ws/md-run         — GROMACS trajectory streamer (load / seek / get_latest)
  /ws/mrdna-relax    — one-shot mrdna CG relaxation pipeline
  /ws/engines/install — auto-build a source MD engine (oxDNA / ANM fork), streamed

(XPBD physics + FEM solver routes were removed 2026-05-10; archived under
`archive/physics_xpbd_fem/`. See archive README for context.)
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections import OrderedDict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api import state as design_state
from backend.core.models import Design
import numpy as np

router = APIRouter()

# Per-frame [ws seek] alignment diagnostics (RMSD/rotation-jump) print to the
# server log.  Useful for watching a live run's alignment quality, but noisy under
# fast scrub playback — set NADOC_MD_SEEK_QUIET=1 to silence.  Default: emit.
_MD_SEEK_DIAG = os.environ.get("NADOC_MD_SEEK_QUIET", "") not in ("1", "true", "yes")

# Above this atom count, skip MDAnalysis' whole-system mda_unwrap make-whole (it
# walks the bond graph on every frame access — minutes for a solvated origami).
# The in-house per-frame P-atom unwrap in _seek_sync handles displayed-DNA PBC, so
# this only drops redundant, pathologically-slow work.  Small (validated) systems
# keep the transformation unchanged.
_UNWRAP_MAX_ATOMS = 200_000

# ── Parsed-Universe cache ─────────────────────────────────────────────────────
# A solvated origami PSF is 100–200 MB and MDAnalysis parses it in ~8 s (pure-Python,
# O(atoms)); the DCD frame table adds more.  That parse is identical across re-opens
# of the SAME topology+trajectory, so cache the Universe keyed by FILE IDENTITY
# (path + mtime + size).  A growing DCD (live job) changes size/mtime → cache miss →
# fresh parse, so live correctness is preserved.  ONLY systems above the unwrap
# threshold are cached: below it `_try_unwrap` adds an in-place trajectory
# transformation that must NOT be stacked on reuse (and small systems parse fast
# anyway).  Bounded LRU — an evicted Universe's trajectory handle is closed.
# NOTE: single-user tool — a cached Universe is shared across connections; concurrent
# scrub from two displays would race the file position, which the app never does.
_UNIVERSE_CACHE: "OrderedDict[str, object]" = OrderedDict()
_UNIVERSE_CACHE_MAX = 2
_UNIVERSE_CACHE_LOCK = threading.Lock()

# Backstop so a genuinely stuck/pathological load surfaces an error instead of an
# eternal "loading" spinner.  The parse thread is not cancellable, so on timeout it
# keeps running and populates the cache — the user's retry is then fast.
_LOAD_TIMEOUT_S = float(os.environ.get("NADOC_MD_LOAD_TIMEOUT_S", "240"))


def _file_identity(path) -> str:
    """path + mtime + size — changes the instant a file is regenerated or grows."""
    try:
        st = os.stat(path)
        return f"{os.fspath(path)}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return f"{os.fspath(path)}:missing"


def _universe_cache_key(topology_path, xtc_path) -> str:
    return _file_identity(topology_path) + "||" + _file_identity(xtc_path)


def _cache_get_universe(key: str):
    with _UNIVERSE_CACHE_LOCK:
        u = _UNIVERSE_CACHE.get(key)
        if u is not None:
            _UNIVERSE_CACHE.move_to_end(key)   # LRU touch
        return u


def _cache_put_universe(key: str, universe) -> None:
    with _UNIVERSE_CACHE_LOCK:
        _UNIVERSE_CACHE[key] = universe
        _UNIVERSE_CACHE.move_to_end(key)
        while len(_UNIVERSE_CACHE) > _UNIVERSE_CACHE_MAX:
            _k, _u = _UNIVERSE_CACHE.popitem(last=False)
            try:
                _u.trajectory.close()
            except Exception:  # noqa: BLE001 — best-effort handle release
                pass


def _psf_natom(path) -> "int | None":
    """Atom count from a PSF header — reads only the first lines up to `!NATOM`,
    so it's ~free even for a 200 MB PSF (used only for a progress message)."""
    try:
        with open(path, "r", errors="replace") as fh:
            for _ in range(50):
                line = fh.readline()
                if not line:
                    break
                if "!NATOM" in line:
                    return int(line.split()[0])
    except Exception:  # noqa: BLE001
        return None
    return None


def _heavy_bond_pairs(u, heavy_indices) -> "list[int] | None":
    """Topology bonds restricted to the heavy atoms the ball-and-stick view draws.

    Returned FLAT (``[i0, j0, i1, j1, …]``) in the SAME serial space ``atom_meta``
    uses — the universe-global ``Atom.index`` — so the frontend resolves each end
    through the serial→row map it already builds.  Flat rather than ``[[i, j], …]``
    because this is ~325 k pairs for a 3 kbp origami and the nested form costs ~30 %
    more JSON for nothing; the renderer already accepts a flat typed array.

    Bonds with an endpoint outside the heavy subset (every X–H bond) are dropped:
    those atoms are not in the atom table, so the renderer would discard the bond
    anyway.  Covalent bonds never cross a strand run, which is the unit
    ``reassemble_to_posed_reference`` snaps to a single periodic image — so a kept
    bond cannot span the box.

    Returns None when the topology carries no bonds (GRO files don't), leaving the
    display exactly as it was: spheres, no sticks.

    Delegates to ``md_trajectory.heavy_bond_pairs``, which the REST atomistic-model path
    also uses. Both have to emit ends in the SAME serial space ``atom_meta`` uses, and
    two copies of that rule drift — so there is one implementation, with the flat/nested
    wire shape as its only knob.
    """
    from backend.core.md_trajectory import heavy_bond_pairs

    return heavy_bond_pairs(u, heavy_indices, nested=False)


def _preload_size_note(config_str: str, topology_str: str) -> "str | None":
    """A cheap 'what we're about to parse' message so a large first-open reads as
    working (with its size), not a bare spinner.  Best-effort — returns None (no
    message) for small systems or on any error; never raises into the load path."""
    try:
        from pathlib import Path

        from backend.core.md_import import resolve_md_config

        top = resolve_md_config(config_str).topology_path if config_str else Path(topology_str)
        if not top or top.suffix.lower() != ".psf" or not top.exists():
            return None
        natom = _psf_natom(top)
        if not natom or natom <= _UNWRAP_MAX_ATOMS:
            return None
        size_mb = top.stat().st_size / (1024 * 1024)
        return (f"Parsing {natom:,}-atom solvated topology ({size_mb:.0f} MB) — "
                "first open of a large run takes ~10–60 s; re-opens are cached and instant.")
    except Exception:  # noqa: BLE001
        return None


# ── MD trajectory streaming WebSocket ─────────────────────────────────────────


@router.websocket("/ws/md-run")
async def md_run_ws(websocket: WebSocket) -> None:
    """
    WebSocket for streaming GROMACS trajectory frames into NADOC.

    Protocol
    ────────
    Client → Server
      {"action": "load",
       "config_path":   str,   # optional abs path to NAMD .json/.namd/.conf
       "topology_path": str,   # abs path to .gro/.tpr or .psf
       "xtc_path":      str,   # abs path to .xtc or .dcd
       "coordinate_path": str, # optional abs path to .pdb for PSF/DCD
       "mode": "nadoc"|"beads"|"ballstick"}
      {"action": "seek",       "frame_idx": int}
      {"action": "get_latest"}
      {"action": "set_solvent", "water": bool, "ions": bool, "box": bool,
       "shell_ang": float|null,   # null = the whole cell; else the hydration shell
       "atomistic": bool,         # real O + 2 H instead of one sphere per molecule
       "max_waters": int|null}    # client-side memory cap, enforced server-side
        Turns the explicit-solvent / periodic-cell overlay on or off for this
        stream. All three false = off, and a stream that never sends this pays
        nothing. Acknowledged with {"type":"solvent_ack"}, then the frame already
        on screen is re-emitted with solvent so the toggle is immediate.

    Server → Client
      {"type": "log",     "message": str}          (emitted during load)
      {"type": "ready",   "n_frames": int, "n_p_atoms": int,
                          "ns_per_day": float|null, "temperature_k": float|null,
                          "total_ns": float|null, "dt_ps": float|null,
                          "nstxout_comp": int|null,
                          "atom_ident": {strands, helices, dirs, strand_idx, helix_idx,
                                         dir_idx, bp}|null}
        (ballstick only) atom_ident is the STATIC per-heavy-atom design identity, in
        interned parallel arrays — sent once here, not per frame, because the frames
        are hundreds of thousands of atoms.  The client zips it onto each frame's
        atoms so they colour by strand / base / cluster like the design's own atoms.
      {"type": "frame",   "frame_idx": int, "n_frames": int, "time_ps": float,
                          "positions": [{helix_id, bp_index, direction, x, y, z}, ...]}
        (ballstick) same but "atoms": [{serial, element, x, y, z}, ...]
      {"type": "solvent_ack", "active": bool}
      {"type": "error",   "message": str}
      <BINARY>  the solvent/periodic-cell blob for the frame just sent, when the
                overlay is on — see backend/core/md_solvent.pack_solvent_bin and
                frontend/src/scene/md_solvent_bin.js. Binary and separate from the
                frame because a whole-cell frame is millions of coordinates; the
                client must set ws.binaryType = 'arraybuffer'.
    """
    await websocket.accept()

    _ctx: dict = {
        "universe":     None,
        "p_order":      None,
        "centroid_T":   None,
        "n_frames":     0,
        "mode":         "nadoc",
        "atom_meta":    None,
        "heavy_idx":    None,
        "c1p_idx":      None,   # numpy int64 array: C1' MDAnalysis index per p_order entry
        "dt_ps":        None,
        "nstxout_comp": None,
        "coordinate_path": None,
        "latest_frame_cache": None,
        "latest_frame_sig": None,
        # Solvent overlay (Water / Ions / Periodic box). `solvent_opts` is None
        # until the client sends `set_solvent`, so a viewer that never turns the
        # toggles on pays nothing. `xf_parts` + the anchor arrays are refreshed by
        # every _seek_sync; `solvent_ctx` is topology and is built once.
        "solvent_opts": None,
        "solvent_ctx": None,
        "xf_parts": None,
        "heavy_raw": None,
        "heavy_pre": None,
        "last_frame_idx": 0,
    }
    _latest_refresh_lock = asyncio.Lock()

    def _try_unwrap(u, logs: list) -> None:
        """Add PBC make-whole transformation to the Universe if bond data exists.

        GRO topologies carry no bond information — calling guess_bonds() on a
        solvated system (200k+ atoms) would take hours (O(n²)).  Only TPR/PSF files
        provide bonds directly, so we skip unwrapping for GRO.  The centroid
        offset computed in _load_sync still re-centres the structure correctly.

        Even WITH bonds, ``mda_unwrap`` walks the full bond graph on every frame
        access — pathological for a solvated system (measured to run for MINUTES on
        the 1.03 M-atom 3x6x200 PSF, effectively hanging the load).  We only ever
        display DNA, and ``_seek_sync`` already makes the displayed atoms whole
        per-frame with the in-house P-atom pipeline (``_unwrap_min_image`` +
        dynamic-T + Kabsch for CG; residue-local nearest-image for ballstick), which
        is exactly why the GRO path works fine WITHOUT this transformation.  So for
        large systems we skip the whole-system make-whole entirely and lean on that
        pipeline — the difference between an instant-ish load and a multi-minute one.
        """
        try:
            n_atoms = len(u.atoms)
            if n_atoms > _UNWRAP_MAX_ATOMS:
                logs.append(
                    f"PBC make_whole skipped ({n_atoms} atoms > {_UNWRAP_MAX_ATOMS} "
                    "threshold — mda_unwrap is O(bond-graph)/frame and would stall "
                    "the load). The in-house per-frame P-atom unwrap handles PBC for "
                    "the displayed DNA."
                )
                return

            from MDAnalysis.transformations import unwrap as mda_unwrap  # type: ignore
            try:
                _ = u.bonds   # raises NoDataError when topology has no bonds
                has_bonds = True
            except Exception:
                has_bonds = False

            if not has_bonds:
                logs.append(
                    "No bond data in topology (GRO files lack bonds). "
                    "PBC unwrap skipped — use a .tpr topology for make_whole. "
                    "Centroid alignment is still applied."
                )
                return

            u.trajectory.add_transformations(mda_unwrap(u.atoms))
            logs.append("PBC unwrapping applied (make_whole).")
        except Exception as exc:
            logs.append(
                f"PBC unwrap skipped ({type(exc).__name__}); "
                "centroid shift still applied."
            )

    def _load_sync(
        topology_str: str,
        xtc_str: str,
        mode: str,
        design,
        coordinate_str: str | None = None,
        config_str: str | None = None,
        expected_design_name: str | None = None,
    ) -> dict:
        """Synchronous load — runs inside asyncio.to_thread."""
        from pathlib import Path

        import MDAnalysis as mda  # type: ignore

        from backend.core.atomistic_cache import build_atomistic_model_cached
        from backend.core.atomistic_to_nadoc import (
            _GRO_DNA_RESNAMES,
            _extract_universe,
            _unwrap_min_image,
            build_chain_map,
            build_p_gro_order,
            build_p_order_from_universe,
            build_p_pdb_order,
            centroid_offset,
            load_segid_chain_map,
            md_rigid_reference,
            md_snap_mask,
        )
        from backend.core.md_metrics import derive_total_ns, parse_log_metrics
        from backend.core.md_import import resolve_md_config

        logs: list[str] = []
        load_warnings: list[str] = []

        resolved = resolve_md_config(config_str) if config_str else None
        topology_path = resolved.topology_path if resolved else Path(topology_str)
        xtc_path      = resolved.trajectory_path if resolved else Path(xtc_str)
        coordinate_path = resolved.coordinate_path if resolved else (Path(coordinate_str) if coordinate_str else None)
        run_dir       = topology_path.parent
        is_namd       = topology_path.suffix.lower() == ".psf" or xtc_path.suffix.lower() == ".dcd"

        if resolved:
            logs.append(f"Config    : {resolved.config_path.name}")
            if resolved.stage_name:
                logs.append(f"Stage     : {resolved.stage_name}")
        logs.append(f"Topology : {topology_path.name}")
        if coordinate_path:
            logs.append(f"Reference: {coordinate_path.name}")
        logs.append(f"Trajectory: {xtc_path.name}")

        if is_namd:
            if coordinate_path is None or not coordinate_path.exists():
                candidate = topology_path.with_suffix(".pdb")
                if candidate.exists():
                    coordinate_path = candidate
                else:
                    raise ValueError(
                        "NAMD PSF/DCD loading requires a reference PDB. "
                        "Use a NADOC NAMD manifest/config or place <name>.pdb next to <name>.psf."
                    )
            input_pdb = coordinate_path
        else:
            # Require input_nadoc.pdb in the same directory for chain mapping.
            input_pdb = run_dir / "input_nadoc.pdb"
            if not input_pdb.exists():
                raise ValueError(
                    f"input_nadoc.pdb not found in {run_dir}. "
                    "Select a topology from a NADOC-generated GROMACS run directory."
                )

        # Build chain map from current design.  Cached + single-flight: rapid
        # re-opens (repr changes, reconnects) for the same design collapse to one
        # build instead of piling up N concurrent multi-GB models (see
        # backend/core/atomistic_cache.py).
        model    = build_atomistic_model_cached(design)
        cm       = build_chain_map(model)

        # Open the Universe up front — for NAMD we build p_order from the PSF's own
        # segids (below), which needs the topology.  Reuse a cached parse when the
        # topology+trajectory files are byte-identical (completed/archived run) — this
        # is the ~8 s solvated-PSF parse we skip on every re-open.  Only large systems
        # (which skip _try_unwrap) are cached, so no transformation is ever stacked.
        _u_key = _universe_cache_key(topology_path, xtc_path)
        u = _cache_get_universe(_u_key)
        if u is not None:
            logs.append("Opening MDAnalysis Universe… (cached — re-parse skipped)")
            try:
                u.trajectory[0]   # shared object may be mid-scrub → reset to frame 0
            except Exception:  # noqa: BLE001
                pass
        else:
            logs.append("Opening MDAnalysis Universe…")
            u = mda.Universe(str(topology_path), str(xtc_path))
            if len(u.atoms) > _UNWRAP_MAX_ATOMS:
                _cache_put_universe(_u_key, u)
        n_frames = len(u.trajectory)
        logs.append(f"Frames    : {n_frames}")

        # Build p_order: the design (helix,bp,dir) key per trajectory DNA P atom, in
        # trajectory atom order (the index-based frame extraction relies on this).
        term_specs: list = []   # 5'-terminal bases (no P) recovered via O5' — NAMD only
        seg2chain: dict = {}    # segid→chain_id (NAMD/PSF only; also feeds atom identity)
        if is_namd:
            # Prefer mapping via the PSF segids + the package's charge_audit
            # segid→chain_id table.  psfgen collapses NADOC's multi-char chain ids
            # into the reference PDB's 1-char chainID field, so the PDB-key path
            # (build_p_pdb_order) collides across strands and drops atoms; the segid
            # map is collision-free.  Fall back to the reference PDB when the package
            # has no charge_audit or the map is incomplete.
            seg2chain = load_segid_chain_map(run_dir)
            p_order = None
            if seg2chain:
                cand, n_unmapped = build_p_order_from_universe(u, cm, seg2chain)
                if n_unmapped == 0 and cand:
                    p_order = cand
                    logs.append(f"P-order   : segid-mapped ({len(p_order)} DNA P atoms)")
                else:
                    # MISMATCH GUARD.  The segid map is design-INDEPENDENT, so a large
                    # unmapped fraction means the design driving this display isn't the
                    # run's design — mapping the trajectory onto it would put beads in the
                    # wrong (helix,bp) slots and streak lines across the structure.  Refuse
                    # with a clear message instead of drawing garbage.  (A SMALL unmapped
                    # count still falls back to the reference-PDB path, as before.)
                    n_dna_p = len(u.select_atoms(
                        "name P and resname " + " ".join(_GRO_DNA_RESNAMES)))
                    if n_unmapped > 0.25 * max(n_dna_p, 1):
                        _which = f" It was built from '{expected_design_name}'." if expected_design_name else ""
                        raise ValueError(
                            f"This trajectory doesn't match the design being displayed "
                            f"({n_unmapped} of {n_dna_p} atoms couldn't be mapped)."
                            f"{_which} Load that design (or reopen this run from its job) "
                            "and try again."
                        )
                    logs.append(
                        f"P-order   : segid map incomplete ({n_unmapped} unmapped) "
                        "— falling back to reference PDB"
                    )
            if p_order is None:
                pdb_text = input_pdb.read_text(errors="replace")
                p_order = build_p_pdb_order(pdb_text, cm)
                logs.append(f"P-order   : reference-PDB ({len(p_order)} entries)")
            # Recover each strand's 5'-terminal base (stripped of its P by pdb2gmx) via its
            # O5', so the live display covers every nucleotide — matching the ghost-free
            # geometry + the flexibility map (returns [] when the segid map is unavailable).
            from backend.core.atomistic_to_nadoc import build_termini_specs
            term_specs = build_termini_specs(u, cm, seg2chain, p_order)
            if term_specs:
                logs.append(f"5' termini: recovered {len(term_specs)} (O5'-anchored)")
        else:
            pdb_text = input_pdb.read_text(errors="replace")
            p_order = build_p_gro_order(pdb_text, cm)
            logs.append(f"P-order   : GRO/XTC ({len(p_order)} entries)")

        logs.append(f"Chain map : {len(cm)} design P atoms")

        # Design equilibrium positions for each entry in p_order (nm, NADOC frame).
        # Used for Kabsch rotation alignment.  Entries in p_order that have no
        # matching P-atom in the current design get np.zeros(3); track these with
        # eq_valid so they can be excluded from the Kabsch computation (including
        # them would skew the centroid and H matrix).
        # Equilibrium P-atom reference + rigid mask for the Kabsch alignment.  Shared
        # with md_trajectory so the extra-base ("__xb__") handling can't drift (the
        # str-vs-int rigid-mask compare crashed the live display before this).
        eq_positions, eq_valid, rigid_mask = md_rigid_reference(model, p_order)
        n_valid = int(eq_valid.sum())
        logs.append(f"Eq-pos    : {n_valid}/{len(p_order)} valid design P-atoms")
        n_rigid = int(rigid_mask.sum())
        logs.append(f"Rigid P   : {n_rigid}/{len(p_order)} (bp≥0 for Kabsch)")

        # PBC snap membership (rigid dsDNA + crossover extra bases).  Centroid and
        # Kabsch keep using rigid_mask only — extra bases must not perturb the
        # rigid-body fit — but the whole-box design-eq snap DOES cover them, else a
        # sequential-unwrap reset can strand one a full box away (see md_snap_mask).
        snap_mask = md_snap_mask(p_order, eq_valid, rigid_mask)
        logs.append(f"Snap P    : {int(snap_mask.sum())}/{len(p_order)} (rigid+extra-base for PBC snap)")

        if n_rigid < 3:
            eq_centroid = np.zeros(3)
            eq_centered = None
        else:
            eq_centroid  = eq_positions[rigid_mask].mean(axis=0)
            eq_centered  = eq_positions - eq_centroid
            eq_centered[~rigid_mask] = 0.0   # only rigid atoms contribute to H

        # PBC unwrapping (make molecules whole).
        _try_unwrap(u, logs)

        # === PBC quality check ===
        # 1. Warn if view_whole.xtc is available but not loaded.
        _view_whole = run_dir / "view_whole.xtc"
        if xtc_path.name != "view_whole.xtc" and _view_whole.exists():
            _vw_msg = (
                f"view_whole.xtc is available in this run directory and has better "
                f"PBC handling than {xtc_path.name} (pre-processed with "
                f"'gmx trjconv -pbc whole'). Consider loading it instead."
            )
            logs.append(f"[PBC] {_vw_msg}")
            load_warnings.append(_vw_msg)

        # 2. Sample a mid-trajectory frame: check how many P-atoms the sequential
        #    unwrapper had to correct.  trjconv -pbc whole pre-processing leaves
        #    0 atoms needing correction.  Raw GROMACS trajectories may have 10–200+
        #    atoms shifted per frame.  > 5 relocated atoms indicates the trajectory
        #    was not pre-processed with '-pbc whole'.
        if n_frames > 2:
            _mid = n_frames // 2
            u.trajectory[_mid]
            _dna_p_chk = u.select_atoms(
                "name P and resname " + " ".join(_GRO_DNA_RESNAMES)
            )
            _p_chk = _dna_p_chk.positions / 10.0
            _dims_chk = u.dimensions
            if _dims_chk is not None and _dims_chk[0] > 0:
                _box_chk = _dims_chk[:3] / 10.0
                _p_uw_chk = _unwrap_min_image(_p_chk, _box_chk)
                _shift = np.linalg.norm(_p_uw_chk - _p_chk, axis=1)
                _n_moved = int((_shift > 0.3).sum())   # atoms relocated > 3 Å
                logs.append(
                    f"PBC check (frame {_mid}): "
                    f"{_n_moved}/{len(_p_chk)} P-atoms relocated by sequential unwrap"
                )
                if _n_moved > 5:
                    _pbc_msg = (
                        f"{xtc_path.name} has {_n_moved} PBC-wrapped P-atoms at "
                        f"frame {_mid}. Sequential unwrap corrects intra-strand "
                        f"splits, but large rotational drift (>60°) at late frames "
                        f"may still cause alignment errors. "
                        f"For best results, pre-process the full trajectory: "
                        f"gmx trjconv -pbc whole -f {xtc_path.name} "
                        f"-s em.tpr -o view_whole.xtc"
                    )
                    load_warnings.append(_pbc_msg)
            # Restore frame 0 for centroid computation.
            u.trajectory[0]

        # Centroid offset — computed on the (possibly unwrapped) frame 0.
        beads_0 = _extract_universe(u, 0, p_order)
        T       = centroid_offset(beads_0, design)
        logs.append(
            f"Centroid shift: ({T[0]*10:.1f}, {T[1]*10:.1f}, {T[2]*10:.1f}) Å"
        )

        # Metrics from log files in the run directory.
        _LOG_PRIORITY = ["prod.log", "nvt.log", "npt.log", "em.log"]
        log_path: Path | None = None
        for name in _LOG_PRIORITY:
            c = run_dir / name
            if c.exists():
                log_path = c
                break
        if log_path is None:
            all_logs = sorted(run_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
            log_path = all_logs[-1] if all_logs else None

        if resolved:
            metrics = None
            total_ns = (
                max(0, n_frames - 1) * resolved.dt_ps * resolved.nstxout_comp / 1000.0
                if resolved.dt_ps is not None and resolved.nstxout_comp is not None
                else None
            )
            load_warnings.extend(resolved.warnings)
            if resolved.log_path:
                logs.append(f"Log       : {resolved.log_path.name}")
        else:
            metrics  = parse_log_metrics(log_path) if log_path else None
            total_ns = derive_total_ns(metrics, n_frames) if metrics else None
        if metrics:
            logs.append(
                f"Log       : {log_path.name} — "
                f"{metrics.dt_ps} ps/step, "
                f"nstxout={metrics.nstxout_comp}, "
                f"{metrics.ns_per_day} ns/day"
            )

        # Precompute C1' atom index for each P atom (same order as p_order).
        # C1' is in the same residue as P; the intra-residue P→C1' vector is
        # used as the base-normal proxy for slab orientation updates.
        dna_p_sel = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
        c1p_list: list[int] = []
        for p_atom in dna_p_sel:
            c1p_atoms = p_atom.residue.atoms.select_atoms("name C1'")
            c1p_list.append(int(c1p_atoms[0].index) if len(c1p_atoms) > 0 else -1)
        import numpy as _np
        c1p_idx = _np.array(c1p_list, dtype=_np.int64)
        logs.append(
            f"C1' map: {int((c1p_idx >= 0).sum())}/{len(c1p_idx)} entries valid"
        )

        result: dict = {
            "universe":      u,
            "topology_path": str(topology_path),
            "xtc_path":      str(xtc_path),
            "coordinate_path": str(coordinate_path) if coordinate_path else None,
            "p_order":       p_order,
            "eq_positions":  eq_positions,
            "eq_valid":      eq_valid,
            "rigid_mask":    rigid_mask,
            "snap_mask":     snap_mask,
            "eq_centroid":   eq_centroid,
            "eq_centered":   eq_centered,
            "centroid_T":    T,
            "n_frames":      n_frames,
            "n_p_atoms":     len(cm),
            "dt_ps":         resolved.dt_ps if resolved else (metrics.dt_ps if metrics else None),
            "nstxout_comp":  resolved.nstxout_comp if resolved else (metrics.nstxout_comp if metrics else None),
            "ns_per_day":    resolved.ns_per_day if resolved else (metrics.ns_per_day if metrics else None),
            "temperature_k": resolved.temperature_k if resolved else (metrics.temperature_k if metrics else None),
            "total_ns":      total_ns,
            "atom_meta":     None,
            "atom_ident":    None,
            "atom_bonds":    None,
            "heavy_idx":     None,
            "c1p_idx":       c1p_idx,
            "term_specs":    term_specs,          # 5'-terminal bases recovered via O5'
            "dna_p_idx":     dna_p_sel.indices,   # cached for the O(1) last-frame fast path
            "logs":          logs,
            "warnings":      load_warnings,
            # Sequential rotation tracking: reset on load.
            "R_prev":        None,
            "prev_frame_idx": -999,
        }

        # DNA heavy atoms are selected for EVERY mode, not just ballstick: the
        # hydration-shell overlay measures its distance to heavy atoms, so the
        # coarse (nadoc/beads) display needs them too — a phosphate-only shell
        # would be a different quantity from the one the trajectory view draws at
        # the same setting.  The selection itself is cheap (an index array); the
        # expensive part is `atom_meta` + the design-identity build below, which
        # stay ballstick-only.
        #
        # Use a name-based hydrogen filter — GRO topologies carry no element data
        # so "not element H" raises AttributeError.  GROMACS writes hydrogen atom
        # names starting with H (CHARMM36, AMBER, …); digit-prefixed AMBER
        # hydrogens (e.g. 1H2) are excluded by the second pattern.
        resnames = " ".join(_GRO_DNA_RESNAMES)
        try:
            dna_heavy = u.select_atoms(f"not element H and resname {resnames}")
        except Exception:
            dna_heavy = u.select_atoms(
                f"(not name H* and not name [0-9]H*) and resname {resnames}"
            )
        result["heavy_idx"] = dna_heavy.indices

        if mode == "ballstick":

            def _element(a) -> str:
                """Derive element symbol tolerantly (GRO has no element info)."""
                try:
                    e = a.element
                    if e:
                        return e
                except Exception:
                    pass
                # Strip leading digits then take first uppercase letter.
                name = a.name.lstrip("0123456789")
                return name[0].upper() if name else "C"

            result["atom_meta"] = [
                {"serial": int(a.index), "element": _element(a)}
                for a in dna_heavy
            ]
            # The STICK half of ball-and-stick.  Connectivity is static across
            # frames, so it rides the 'ready' message once rather than every frame
            # (a frame is already hundreds of thousands of atoms).  Without this the
            # renderer receives `bonds: []` and a live NAMD run draws bare spheres —
            # oxDNA never had the symptom because its atomistic bundle derives bonds
            # from the DESIGN topology instead of from the simulation's own.
            result["atom_bonds"] = _heavy_bond_pairs(u, dna_heavy.indices)
            if result["atom_bonds"]:
                logs.append(f"Bond topology: {len(result['atom_bonds']) // 2} bonds "
                            f"over {len(dna_heavy)} heavy atoms")
            else:
                logs.append("Bond topology: unavailable (topology carries no bonds) "
                            "— atoms will render without sticks")
            # Per-atom design identity (strand/helix/bp/direction), sent ONCE in the
            # 'ready' message rather than per frame — it is static across frames and a
            # ball-and-stick frame is hundreds of thousands of atoms.  Without it the
            # frontend colour resolver has no strand to look up and every MD atom is
            # stuck on CPK, deaf to the strand/base/cluster colouring buttons.
            from backend.core.atomistic_to_nadoc import (  # noqa: PLC0415
                build_atom_design_meta,
                intern_atom_design_meta,
            )
            try:
                result["atom_ident"] = intern_atom_design_meta(
                    build_atom_design_meta(u, dna_heavy, p_order, model, cm, seg2chain))
                logs.append(f"Atom ident: {len(result['atom_ident']['strands'])} strands "
                            f"over {len(dna_heavy)} heavy atoms")
            except Exception as exc:  # noqa: BLE001
                # Colouring is cosmetic — never fail a display over it.
                result["atom_ident"] = None
                logs.append(f"Atom ident: unavailable ({type(exc).__name__}: {exc}) "
                            "— atoms will render CPK")

        return result

    def _seek_sync(frame_idx: int, _injected=None) -> dict:
        """Extract one frame — runs in asyncio.to_thread.

        ``_injected = (all_positions_A, dims_A, time_ps)`` supplies a frame already
        read by the O(1) ``dcd_fast`` last-frame path, bypassing the MDAnalysis
        trajectory seek (and its offset-recalc retry storm on a live, growing DCD).
        When None, the frame is read from the Universe as before (full-trajectory
        scrub / ballstick path)."""
        import numpy as _np
        from backend.core.atomistic_to_nadoc import (
            _GRO_DNA_RESNAMES,
            _unwrap_min_image,
            reassemble_to_posed_reference,
        )

        u        = _ctx["universe"]
        p_order  = _ctx["p_order"]
        T        = _ctx["centroid_T"]
        mode     = _ctx["mode"]
        n_frames = _ctx["n_frames"]

        # Per-frame solvent inputs start empty, so a frame that fails to build a
        # transform can never let the overlay draw against the PREVIOUS frame's.
        _ctx["xf_parts"] = None
        _ctx["heavy_raw"] = None
        _ctx["heavy_pre"] = None

        if _injected is None:
            ts      = u.trajectory[frame_idx]
            time_ps = float(ts.time)
        else:
            _all_pos, _dims_inj, time_ps = _injected

        if mode in ("nadoc", "beads"):
            if _injected is None:
                dna_p   = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
                p_raw   = dna_p.positions / 10.0                   # Å → nm, box coords
                dims    = u.dimensions
            else:
                p_raw   = _all_pos[_ctx["dna_p_idx"]] / 10.0       # Å → nm, box coords
                dims    = _dims_inj
            eq_pos      = _ctx.get("eq_positions")
            eq_valid    = _ctx.get("eq_valid")
            rigid_mask  = _ctx.get("rigid_mask")
            snap_mask   = _ctx.get("snap_mask")
            eq_centered = _ctx.get("eq_centered")
            eq_centroid = _ctx.get("eq_centroid")
            # Atoms snapped to design-eq: rigid dsDNA + crossover extra bases.
            # Fall back to rigid_mask if an older ctx has no snap_mask.
            if snap_mask is None:
                snap_mask = rigid_mask

            # All PBC corrections must happen in box coordinates (before adding T).
            if dims is not None and dims[0] > 0:
                box_nm = dims[:3] / 10.0

                # Step 1 — sequential nearest-image (fixes intra-strand PBC splits).
                p_box = _unwrap_min_image(p_raw, box_nm)

                # Step 2 — POSE-FIRST PBC reassembly onto the design reference.
                #   The old code placed the design reference by TRANSLATION only, then
                #   nearest-image-snapped.  For an origami larger than half the box that
                #   has rotated in the cell, a distant atom's un-rotated reference is
                #   > L/2 away → the snap grabbed the wrong periodic image and the atom
                #   streaked a full box across the scene.  reassemble_to_posed_reference
                #   estimates the rigid-body pose (rotation+translation) FIRST, poses the
                #   design reference into the box frame, and only then snaps — so every
                #   atom's reference sits beside its true position.  Free ssDNA
                #   (~snap_mask) keeps its raw sequential-unwrap position, as before.
                #   c_box is the PBC-robust (circular-mean) centroid, used for T_dyn.
                if (eq_pos is not None and eq_centroid is not None
                        and snap_mask is not None and len(eq_pos) == len(p_box)):
                    p_box_corr, _c_box = reassemble_to_posed_reference(
                        p_box, box_nm, eq_pos, eq_centroid, rigid_mask, snap_mask,
                    )
                    _T_dyn = eq_centroid - _c_box       # current box → NADOC frame
                    p_nm   = p_box_corr + _T_dyn        # NADOC frame
                else:
                    # No design reference — median-centroid translation only (median is
                    # robust to a minority of strand-boundary unwrap errors).
                    if rigid_mask is not None and rigid_mask.any():
                        _c_box = _np.median(p_box[rigid_mask], axis=0)
                    else:
                        _c_box = p_box.mean(axis=0)
                    _T_dyn = eq_centroid - _c_box if (eq_centroid is not None) else T
                    p_nm = p_box + _T_dyn
                # The solvent/box overlay rides the SAME affine as the DNA; stash
                # what this frame used rather than letting it re-derive anything.
                _ctx["xf_parts"] = {"T_dyn": _T_dyn, "c_box": _c_box, "box_nm": box_nm}
                _ctx["p_pre"] = p_nm.copy()      # before the Kabsch below
                _ctx["p_raw"] = p_raw
            else:
                p_nm = p_raw + T

            # Step 3 — Kabsch rotation aligned to design equilibrium.
            # Only rigid dsDNA atoms (rigid_mask = bp≥0) contribute to the H matrix;
            # ssDNA rows are zeroed in eq_centered so they don't bias the rotation.
            #
            # Sequential consistency check: when playing frame-by-frame (|N - N_prev| ≤ 3),
            # compare the new rotation to R_prev.  If the rotation change exceeds 60°,
            # the Kabsch likely flipped into an equivalent mirror solution (gimbal lock
            # near 90° rotation).  In that case, re-run Kabsch using only inlier atoms
            # (pre-Kabsch delta < median_delta * 3) to get a more robust estimate.
            R_align = None
            R_prev     = _ctx.get("R_prev")
            prev_frame = _ctx.get("prev_frame_idx", -999)
            _is_sequential = abs(frame_idx - prev_frame) <= 3
            if (eq_centered is not None and eq_centroid is not None
                    and len(eq_centered) == len(p_nm)):
                _rm = rigid_mask if (rigid_mask is not None and rigid_mask.any()) else (
                      eq_valid  if (eq_valid   is not None and eq_valid.any())   else None)
                _mob_c  = p_nm[_rm].mean(axis=0) if _rm is not None else p_nm.mean(axis=0)
                _mc     = p_nm - _mob_c
                _H      = _mc.T @ eq_centered
                _U2, _, _Vt2 = _np.linalg.svd(_H)
                _d2     = _np.linalg.det(_Vt2.T @ _U2.T)
                R_align = _Vt2.T @ _np.diag([1.0, 1.0, _d2]) @ _U2.T

                # Sequential consistency: detect sudden rotation jumps.
                if R_prev is not None and _is_sequential:
                    _dR    = R_align @ R_prev.T
                    _trace = float(_np.trace(_dR))
                    # angle = arccos((trace-1)/2); if > 60° → suspicious flip
                    _cos   = max(-1.0, min(1.0, (_trace - 1.0) / 2.0))
                    _angle_deg = _np.degrees(_np.arccos(_cos))
                    if _angle_deg > 60.0:
                        # Re-run Kabsch using inlier atoms only (robust to gimbal lock).
                        _p_nm_raw = _mc @ R_align.T + eq_centroid
                        _pre_d    = _np.linalg.norm(_p_nm_raw - eq_pos, axis=1)
                        _med_d    = _np.median(_pre_d[_rm]) if _rm is not None else _np.median(_pre_d)
                        _inlier   = _rm & (_pre_d < _med_d * 3.0) if _rm is not None else (_pre_d < _med_d * 3.0)
                        if _inlier.sum() >= 10:
                            _mob_c2 = p_nm[_inlier].mean(axis=0)
                            _mc2    = p_nm - _mob_c2
                            _eq_c2  = eq_pos - eq_centroid
                            _eq_c2[~_inlier] = 0.0
                            _H2     = _mc2.T @ _eq_c2
                            _U3, _, _Vt3 = _np.linalg.svd(_H2)
                            _d3     = _np.linalg.det(_Vt3.T @ _U3.T)
                            R_inlier = _Vt3.T @ _np.diag([1.0, 1.0, _d3]) @ _U3.T
                            # Accept inlier rotation only if it's more consistent with R_prev.
                            _dR2   = R_inlier @ R_prev.T
                            _cos2  = max(-1.0, min(1.0, (float(_np.trace(_dR2)) - 1.0) / 2.0))
                            if _np.arccos(_cos2) < _np.arccos(_cos):
                                R_align = R_inlier
                                _mob_c  = _mob_c2
                                _mc     = _mc2
                        if _MD_SEEK_DIAG:
                            print(f"[ws seek] frame={frame_idx} rotation jump {_angle_deg:.1f}° "
                                  f"→ inlier Kabsch applied", flush=True)

                p_nm = _mc @ R_align.T + eq_centroid
                _ctx["R_prev"]         = R_align
                _ctx["prev_frame_idx"] = frame_idx
                if _ctx.get("xf_parts") is not None:
                    _ctx["xf_parts"].update(
                        mob_c=_mob_c, eq_centroid=eq_centroid, R=R_align)

                # Server-side diagnostic (one line per frame).
                if _MD_SEEK_DIAG:
                    _delta = _np.linalg.norm(p_nm - eq_pos, axis=1)
                    _nr = int(_rm.sum()) if _rm is not None else len(p_nm)
                    _rd = _delta[_rm] if _rm is not None else _delta
                    print(f"[ws seek] frame={frame_idx} n_rigid={_nr} "
                          f"RMSD_all={_np.sqrt((_delta**2).mean())*10:.2f}Å "
                          f"RMSD_rigid={_np.sqrt((_rd**2).mean())*10:.2f}Å "
                          f"max={_delta.max()*10:.2f}Å "
                          f"n>2Å={int((_delta>0.2).sum())} "
                          f"n>5Å={int((_delta>0.5).sum())}", flush=True)

            # Step 4 — Base normals (P→C1') rotated into the aligned frame.
            c1p_idx = _ctx.get("c1p_idx")
            normals = None
            if c1p_idx is not None and _np.all(c1p_idx >= 0) and len(c1p_idx) == len(p_order):
                c1p_raw = (u.atoms[c1p_idx].positions if _injected is None
                           else _all_pos[c1p_idx]) / 10.0          # Å → nm
                dn      = c1p_raw - p_raw                          # intra-residue vector (no PBC issue)
                if R_align is not None:
                    dn = dn @ R_align.T                            # rotate into aligned frame
                norms   = _np.linalg.norm(dn, axis=1, keepdims=True)
                norms   = _np.where(norms > 1e-6, norms, 1.0)
                normals = dn / norms                               # unit vectors

            positions = []
            for i, key in enumerate(p_order):
                hid, bpi, d = key[0], key[1], key[2]
                entry: dict = {
                    "helix_id":  hid,
                    "bp_index":  bpi,
                    "direction": d,
                    "copy": key[3] if len(key) > 3 else 0,   # loop-copy index (0 = base)
                    "x": float(p_nm[i, 0]),
                    "y": float(p_nm[i, 1]),
                    "z": float(p_nm[i, 2]),
                }
                if normals is not None:
                    entry["nx"] = float(normals[i, 0])
                    entry["ny"] = float(normals[i, 1])
                    entry["nz"] = float(normals[i, 2])
                positions.append(entry)

            # 5'-terminal bases (no P atom) recovered via O5', anchored off the aligned
            # 3'-neighbour P — so the live display covers every nucleotide.
            term_specs = _ctx.get("term_specs") or []
            if term_specs and R_align is not None:
                from backend.core.atomistic_to_nadoc import recover_termini
                _box = (dims[:3] / 10.0) if (dims is not None and dims[0] > 0) else None
                tpos, tnorm = recover_termini(
                    u, term_specs, p_raw, p_nm, R_align, _box,
                    all_pos_A=(_all_pos if _injected is not None else None))
                for j, spec in enumerate(term_specs):
                    if j >= len(tpos):
                        break
                    key = spec[0]
                    tentry: dict = {
                        "helix_id": key[0], "bp_index": key[1], "direction": key[2],
                        "x": float(tpos[j, 0]), "y": float(tpos[j, 1]), "z": float(tpos[j, 2]),
                    }
                    if len(tnorm):
                        tentry["nx"] = float(tnorm[j, 0])
                        tentry["ny"] = float(tnorm[j, 1])
                        tentry["nz"] = float(tnorm[j, 2])
                    positions.append(tentry)
            return {
                "type":      "frame",
                "frame_idx": frame_idx,
                "n_frames":  n_frames,
                "time_ps":   time_ps,
                "positions": positions,
            }
        else:  # ballstick
            heavy_idx = _ctx["heavy_idx"]
            atom_meta = _ctx["atom_meta"]
            ag        = u.atoms[heavy_idx]
            pos_raw   = ag.positions / 10.0
            pos_nm    = pos_raw + T

            # Keep atomistic MD display in one coherent periodic image.  The CG
            # NADOC/bead path above corrects P atoms against the design reference;
            # mirror that for atomistic display, then reconstruct each residue's
            # heavy atoms from the nearest image relative to its corrected P atom.
            # This avoids the common visual failure where a strand is displayed
            # one periodic box away while preserving actual intra-residue MD
            # coordinates.
            try:
                dna_p = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
                p_raw = dna_p.positions / 10.0
                dims = u.dimensions
                eq_pos = _ctx.get("eq_positions")
                rigid_mask = _ctx.get("rigid_mask")
                snap_mask = _ctx.get("snap_mask")
                if snap_mask is None:
                    snap_mask = rigid_mask
                eq_centroid = _ctx.get("eq_centroid")
                eq_centered = _ctx.get("eq_centered")
                if dims is not None and dims[0] > 0 and len(p_raw) == len(p_order):
                    box_nm = dims[:3] / 10.0
                    p_box = _unwrap_min_image(p_raw, box_nm)
                    if rigid_mask is not None and rigid_mask.any():
                        c_box = _np.median(p_box[rigid_mask], axis=0)
                    else:
                        c_box = p_box.mean(axis=0)

                    T_dyn = eq_centroid - c_box if eq_centroid is not None else T
                    if (eq_pos is not None and eq_centroid is not None
                            and snap_mask is not None and len(eq_pos) == len(p_box)):
                        # Use the SHARED reassembly, not a local copy.  This branch used
                        # to inline its own translation-only, PER-ATOM nearest-image snap
                        # — which both (a) predated the pose-first fix the bead path above
                        # already uses, and (b) tore the backbone: an atom whose ideal
                        # design reference is >L/2 from its simulated position rounds to a
                        # different periodic image than its chain neighbours and jumps a
                        # full box alone.  That is the "a few bases dislocated from their
                        # strands" artefact, and because the copy lived here it survived
                        # fixing the shared function.  reassemble_to_posed_reference poses
                        # the reference first and snaps per STRAND RUN, so contiguity
                        # holds by construction.
                        p_box_corr, c_box = reassemble_to_posed_reference(
                            p_box, box_nm, eq_pos, eq_centroid, rigid_mask, snap_mask,
                        )
                        T_dyn = eq_centroid - c_box
                        p_pre = p_box_corr + T_dyn
                    else:
                        p_pre = p_box + T_dyn

                    # Residue-local reconstruction: heavy atom = corrected P +
                    # minimum-image(raw atom - raw P).  Use residue ix because it
                    # is stable inside this MDAnalysis Universe.
                    p_raw_by_res = {int(a.residue.ix): p_raw[i] for i, a in enumerate(dna_p)}
                    p_pre_by_res = {int(a.residue.ix): p_pre[i] for i, a in enumerate(dna_p)}
                    p_res_by_key: dict[tuple[str, int], int] = {}
                    p_resids_by_seg: dict[str, list[int]] = {}
                    for a in dna_p:
                        segid = str(getattr(a.residue, "segid", "") or getattr(a, "segid", ""))
                        resid = int(a.residue.resid)
                        p_res_by_key[(segid, resid)] = int(a.residue.ix)
                        p_resids_by_seg.setdefault(segid, []).append(resid)
                    for segid in p_resids_by_seg:
                        p_resids_by_seg[segid].sort()

                    def _anchor_residue_ix(atom) -> int | None:
                        res_ix = int(atom.residue.ix)
                        if res_ix in p_raw_by_res:
                            return res_ix
                        segid = str(getattr(atom.residue, "segid", "") or getattr(atom, "segid", ""))
                        resid = int(atom.residue.resid)
                        # Terminal residues may not have a P atom.  Anchor them
                        # to the nearest residue with a P in the same segment.
                        for delta_resid in (1, -1, 2, -2):
                            near = p_res_by_key.get((segid, resid + delta_resid))
                            if near is not None:
                                return near
                        candidates = p_resids_by_seg.get(segid)
                        if candidates:
                            nearest_resid = min(candidates, key=lambda r: abs(r - resid))
                            return p_res_by_key.get((segid, nearest_resid))
                        return None

                    pos_pre = pos_nm.copy()
                    for i, a in enumerate(ag):
                        res_ix = _anchor_residue_ix(a)
                        if res_ix is None:
                            continue
                        p0 = p_raw_by_res.get(res_ix)
                        pc = p_pre_by_res.get(res_ix)
                        if p0 is None or pc is None:
                            continue
                        delta = pos_raw[i] - p0
                        for d in range(3):
                            if box_nm[d] > 0:
                                delta[d] -= _np.round(delta[d] / box_nm[d]) * box_nm[d]
                        pos_pre[i] = pc + delta

                    # Use the same rigid-body Kabsch alignment as the P-bead path
                    # so atomistic and NADOC representations occupy the same view.
                    if (eq_centered is not None and eq_centroid is not None
                            and len(eq_centered) == len(p_pre)):
                        rm = rigid_mask if (rigid_mask is not None and rigid_mask.any()) else None
                        mob_c = p_pre[rm].mean(axis=0) if rm is not None else p_pre.mean(axis=0)
                        mc = p_pre - mob_c
                        H = mc.T @ eq_centered
                        U2, _, Vt2 = _np.linalg.svd(H)
                        det = _np.linalg.det(Vt2.T @ U2.T)
                        R_align = Vt2.T @ _np.diag([1.0, 1.0, det]) @ U2.T
                        pos_nm = (pos_pre - mob_c) @ R_align.T + eq_centroid
                    else:
                        pos_nm = pos_pre
                        mob_c = R_align = None
                    # Hand the solvent/box overlay this frame's affine and the DNA
                    # anchor arrays it already built — never re-derive them.
                    _ctx["xf_parts"] = {
                        "T_dyn": T_dyn, "c_box": c_box, "box_nm": box_nm,
                        "mob_c": mob_c, "R": R_align,
                        "eq_centroid": eq_centroid if R_align is not None else None,
                    }
                    _ctx["heavy_raw"] = pos_raw
                    _ctx["heavy_pre"] = pos_pre
                    _ctx["p_raw"] = p_raw
                    _ctx["p_pre"] = p_pre
            except Exception as exc:
                print(
                    f"[ws seek] atomistic PBC correction skipped "
                    f"({type(exc).__name__}: {exc})",
                    flush=True,
                )
            atoms = [
                {
                    "serial":  m["serial"],
                    "element": m["element"],
                    "x": float(pos_nm[i, 0]),
                    "y": float(pos_nm[i, 1]),
                    "z": float(pos_nm[i, 2]),
                }
                for i, m in enumerate(atom_meta)
            ]
            return {
                "type":      "frame",
                "frame_idx": frame_idx,
                "n_frames":  n_frames,
                "time_ps":   time_ps,
                "atoms":     atoms,
            }

    def _trajectory_signature() -> tuple[int, int] | None:
        from pathlib import Path

        xtc_path = _ctx.get("xtc_path")
        if not xtc_path:
            return None
        st = Path(xtc_path).stat()
        return (int(st.st_mtime_ns), int(st.st_size))

    def _refresh_latest_sync(force: bool = False) -> dict:
        """Return the latest trajectory frame, re-reading only when the file changed.

        A live DCD that NAMD is mid-write on changes mtime/size every poll, so the
        signature cache never hits while a run is active.  Rather than rebuild the
        whole ``mda.Universe`` (which re-parses the PSF — ~1.7 s for a 0.5 M-atom
        system and worse for multi-GB trajectories, easily exceeding the 5 s live
        cadence), reuse the existing Universe and only re-read the trajectory with
        ``Universe.load_new``.  load_new re-reads the DCD header so newly-flushed
        frames are discovered (``_reopen()`` does NOT — see the live-reload lesson),
        while the parsed topology and all the precomputed eq/p_order/c1p arrays in
        ``_ctx`` (keyed by atom index, stable across reloads of the same PSF) stay
        valid.

        The final frame of an actively-written DCD may be torn (NAMD flushed the
        frame-count header before the coordinate block fully landed).  MDAnalysis
        floors n_frames by file size so a half-written trailing frame is usually
        simply not counted, but to be safe against a torn read we seek the latest
        frame and fall back one frame on any error.
        """
        sig = _trajectory_signature()
        cached = _ctx.get("latest_frame_cache")
        if not force and cached is not None and sig == _ctx.get("latest_frame_sig"):
            return dict(cached)

        u = _ctx.get("universe")
        if u is None:
            raise RuntimeError("No trajectory loaded.")

        # Fast path — O(1) direct last-frame read.  A DCD is fixed-record, so the
        # latest frame's byte offset is arithmetic from the file size; we skip
        # MDAnalysis' load_new (which rescans offsets and, on a file NAMD is mid-write
        # on, retry-storms a core).  CG/bead display only; ballstick and any non
        # fixed-record DCD fall through to the MDAnalysis path below.
        if _ctx.get("mode") in ("nadoc", "beads"):
            from backend.core import dcd_fast  # noqa: PLC0415
            try:
                layout = dcd_fast.read_layout(_ctx["xtc_path"])
            except Exception:  # noqa: BLE001 — unsupported layout → MDAnalysis fallback
                layout = None
            if layout is not None and layout.n_atoms == len(u.atoms) and layout.n_frames > 0:
                _ctx["n_frames"] = layout.n_frames
                _ctx["R_prev"] = None
                _ctx["prev_frame_idx"] = -999
                for idx in (layout.n_frames - 1, layout.n_frames - 2):
                    if idx < 0:
                        break
                    try:
                        coords, cell = dcd_fast.read_frame(_ctx["xtc_path"], layout, idx)
                        frame_msg = _seek_sync(idx, _injected=(
                            coords, dcd_fast.cell_to_dimensions(cell),
                            layout.first_ps + idx * layout.delta_ps))
                        _ctx["latest_frame_cache"] = frame_msg
                        _ctx["latest_frame_sig"] = sig
                        return frame_msg
                    except Exception:  # noqa: BLE001 — torn trailing frame → try one back
                        continue

        # Fallback: MDAnalysis load_new + seek (full-trajectory scrub, ballstick mode,
        # or a DCD whose layout dcd_fast can't treat as fixed-record).
        u.load_new(_ctx["xtc_path"])
        n_frames = len(u.trajectory)
        _ctx["n_frames"] = n_frames
        _ctx["R_prev"] = None
        _ctx["prev_frame_idx"] = -999
        if n_frames <= 0:
            raise RuntimeError("Trajectory has no complete frames yet.")

        # Seek the latest frame; on a torn final frame fall back one frame.
        last_err: Exception | None = None
        for idx in (n_frames - 1, n_frames - 2):
            if idx < 0:
                break
            try:
                frame_msg = _seek_sync(idx)
                _ctx["latest_frame_cache"] = frame_msg
                _ctx["latest_frame_sig"] = sig
                return frame_msg
            except Exception as exc:  # noqa: BLE001 — torn/partial trailing frame
                last_err = exc
                continue
        raise last_err if last_err else RuntimeError("Could not read latest frame.")

    async def _refresh_latest(force: bool = False) -> dict:
        async with _latest_refresh_lock:
            return await asyncio.to_thread(_refresh_latest_sync, force)

    def _seek_growing_sync(frame_idx: int) -> dict:
        """Seek a frame for scrub/playback, discovering frames appended since load.

        The live ``get_latest`` fast path (``dcd_fast``) advances ``_ctx['n_frames']``
        past what the MDAnalysis Universe knows — the Universe indexed all frame
        offsets at open time, so ``u.trajectory[idx]`` for one of the newer frames
        would raise IndexError and surface as an error toast + blank scene.  Reload
        the trajectory (``load_new`` re-reads offsets) only when the requested frame
        is beyond the Universe's current length; the common in-range scrub stays on
        the plain MDAnalysis seek and keeps its sequential-Kabsch tracking.
        """
        u = _ctx.get("universe")
        if u is None:
            raise RuntimeError("No trajectory loaded.")
        if frame_idx >= len(u.trajectory):
            u.load_new(_ctx["xtc_path"])
            _ctx["n_frames"] = len(u.trajectory)
            _ctx["R_prev"] = None
            _ctx["prev_frame_idx"] = -999
        idx = max(0, min(frame_idx, len(u.trajectory) - 1))
        return _seek_sync(idx)

    def _solvent_bytes_sync() -> bytes | None:
        """Explicit solvent + periodic cell for the frame `_seek_sync` just built.

        Reads the affine and the DNA anchor arrays that frame stashed in `_ctx`
        rather than recomputing anything — the transform has exactly one owner
        (backend/core/md_solvent.py), and a second derivation would silently put
        the water somewhere else from the DNA it belongs to.

        The coarse (nadoc/beads) branch has only P atoms on hand, so heavy-atom
        anchors are reconstructed here; that costs one array op per frame after the
        first (the anchor rows are a topology fact, memoised on `_ctx`). Returns
        None whenever solvent is off or the frame carried no periodic box.
        """
        opts = _ctx.get("solvent_opts")
        if not opts or not (opts.get("water") or opts.get("ions") or opts.get("box")):
            return None
        parts = _ctx.get("xf_parts")
        if not parts:
            return None
        from backend.core import md_solvent as _MS
        from backend.core.atomistic_to_nadoc import _GRO_DNA_RESNAMES

        u = _ctx["universe"]
        sctx = _ctx.get("solvent_ctx")
        if sctx is None:
            sctx = _ctx["solvent_ctx"] = _MS.build_solvent_ctx(u)

        xf = _MS.DisplayXform.build(
            T_dyn=parts.get("T_dyn"), c_box=parts.get("c_box"),
            box_nm=parts.get("box_nm"), mob_c=parts.get("mob_c"),
            eq_centroid=parts.get("eq_centroid"), R=parts.get("R"))

        heavy_raw = _ctx.get("heavy_raw")
        heavy_pre = _ctx.get("heavy_pre")
        if heavy_raw is None:                       # coarse branch → rebuild anchors
            heavy_idx = _ctx.get("heavy_idx")
            p_raw, p_pre = _ctx.get("p_raw"), _ctx.get("p_pre")
            if heavy_idx is None or p_raw is None or p_pre is None:
                return None
            heavy_ag = u.atoms[heavy_idx]
            heavy_raw = heavy_ag.positions / 10.0
            dna_p = u.select_atoms(
                "name P and resname " + " ".join(_GRO_DNA_RESNAMES))
            heavy_pre = _MS.reconstruct_heavy_pre(
                heavy_ag, dna_p, heavy_raw, p_raw, p_pre, xf.box_nm, rows_cache=_ctx)

        frame = _MS.extract_solvent_frame(
            u, sctx, heavy_raw, heavy_pre, xf,
            water=bool(opts.get("water")), ions=bool(opts.get("ions")),
            box=bool(opts.get("box")),
            shell_nm=(None if opts.get("shell_ang") is None
                      else float(opts["shell_ang"]) / 10.0),
            atomistic=bool(opts.get("atomistic")),
            max_waters=opts.get("max_waters"))
        return _MS.pack_solvent_bin({int(_ctx.get("last_frame_idx") or 0): frame})

    async def _send_frame(frame_msg: dict) -> None:
        """Send a frame, followed by its solvent blob when the overlay is on.

        Binary, and a SEPARATE message: a whole-cell frame is millions of numbers,
        which as JSON would dwarf the frame it accompanies."""
        await websocket.send_json(frame_msg)
        if not _ctx.get("solvent_opts"):
            return
        _ctx["last_frame_idx"] = frame_msg.get("frame_idx", 0)
        try:
            buf = await asyncio.to_thread(_solvent_bytes_sync)
        except Exception as exc:                                    # noqa: BLE001
            print(f"[ws solvent] skipped ({type(exc).__name__}: {exc})", flush=True)
            return
        if buf:
            await websocket.send_bytes(buf)

    try:
        while True:
            msg    = await websocket.receive_json()
            action = msg.get("action")

            if action == "load":
                config_str   = msg.get("config_path") or ""
                topology_str = msg.get("topology_path", "")
                xtc_str      = msg.get("xtc_path", "")
                coordinate_str = msg.get("coordinate_path") or None
                mode         = msg.get("mode", "nadoc")
                job_id_msg   = msg.get("job_id") or None
                design_payload = msg.get("design")
                # Prefer the RUN's OWN design (resolved from job_id) over whatever design
                # is open in the editor.  Mapping a trajectory onto a mismatched design
                # scrambles the P-atom→(helix,bp) assignment into cross-structure streaks,
                # so the open design is only a last-resort fallback.
                design = None
                expected_design_name = None
                if job_id_msg:
                    try:
                        from backend.api.routes_md import md_display_design_for_job
                        design, expected_design_name = md_display_design_for_job(job_id_msg)
                    except Exception:  # noqa: BLE001 — fall back to the payload design
                        design = None
                if design is None and design_payload:
                    try:
                        design = Design.model_validate(design_payload)
                    except Exception as exc:
                        await websocket.send_json({"type": "error", "message": f"Invalid design payload: {exc}"})
                        continue
                if design is None:
                    design = design_state.get_design()
                if design is None:
                    await websocket.send_json({"type": "error", "message": "No design loaded. Reload the design or reopen this MD run from NADOC."})
                    continue
                if not config_str and (not topology_str or not xtc_str):
                    await websocket.send_json({"type": "error", "message": "config_path or topology_path and xtc_path are required."})
                    continue
                # Progress: a large first-open re-parse is ~tens of seconds — surface the
                # system size up front so the spinner reads as "working", not "hung".
                _note = _preload_size_note(config_str, topology_str)
                if _note:
                    await websocket.send_json({"type": "loading", "message": _note})
                try:
                    loaded = await asyncio.wait_for(
                        asyncio.to_thread(
                            _load_sync,
                            topology_str,
                            xtc_str,
                            mode,
                            design,
                            coordinate_str,
                            config_str or None,
                            expected_design_name,
                        ),
                        timeout=_LOAD_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    await websocket.send_json({
                        "type": "error",
                        "message": (
                            f"Loading timed out after {int(_LOAD_TIMEOUT_S)}s — this is "
                            "usually a very large solvated system still parsing. The parse "
                            "continues in the background, so try again in a moment (re-opens "
                            "are cached and load fast)."
                        ),
                    })
                    continue
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue

                _ctx.update(loaded)
                _ctx["mode"] = mode
                _ctx["latest_frame_cache"] = None
                _ctx["latest_frame_sig"] = None

                for log_line in loaded.get("logs", []):
                    await websocket.send_json({"type": "log", "message": log_line})

                await websocket.send_json({
                    "type":          "ready",
                    "n_frames":      loaded["n_frames"],
                    "n_p_atoms":     loaded["n_p_atoms"],
                    "ns_per_day":    loaded["ns_per_day"],
                    "temperature_k": loaded["temperature_k"],
                    "total_ns":      loaded["total_ns"],
                    "dt_ps":         loaded["dt_ps"],
                    "nstxout_comp":  loaded["nstxout_comp"],
                    "topology_path":  loaded["topology_path"],
                    "trajectory_path": loaded["xtc_path"],
                    "coordinate_path": loaded.get("coordinate_path"),
                    "warnings":      loaded.get("warnings", []),
                    # Ball-and-stick only: static per-atom design identity so the
                    # frontend can colour MD atoms by strand/base/cluster (null in
                    # bead modes, and when the mapping was unavailable).
                    "atom_ident":    loaded.get("atom_ident"),
                    # Ball-and-stick only: flat serial pairs for the bond cylinders,
                    # also static across frames (null in bead modes / bond-less
                    # topologies).
                    "atom_bonds":    loaded.get("atom_bonds"),
                })

            elif action == "seek":
                if _ctx["universe"] is None:
                    await websocket.send_json({"type": "error", "message": "No trajectory loaded."})
                    continue
                frame_idx = max(0, int(msg.get("frame_idx", 0)))
                try:
                    frame_msg = await asyncio.to_thread(_seek_growing_sync, frame_idx)
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                if frame_msg.get("frame_idx") == _ctx["n_frames"] - 1:
                    _ctx["latest_frame_cache"] = frame_msg
                    _ctx["latest_frame_sig"] = _trajectory_signature()
                await _send_frame(frame_msg)

            elif action == "set_solvent":
                # Turn the Water / Ions / Periodic-box overlay on or off for this
                # stream, and re-emit the frame already on screen so the change is
                # immediate rather than waiting for the next poll.
                on = bool(msg.get("water") or msg.get("ions") or msg.get("box"))
                _ctx["solvent_opts"] = {
                    "water": bool(msg.get("water")),
                    "ions": bool(msg.get("ions")),
                    "box": bool(msg.get("box")),
                    "shell_ang": msg.get("shell_ang", 5.0),
                    "atomistic": bool(msg.get("atomistic")),
                    "max_waters": msg.get("max_waters"),
                } if on else None
                await websocket.send_json({"type": "solvent_ack", "active": on})
                if on and _ctx["universe"] is not None and _ctx.get("xf_parts"):
                    try:
                        buf = await asyncio.to_thread(_solvent_bytes_sync)
                    except Exception as exc:                        # noqa: BLE001
                        await websocket.send_json(
                            {"type": "error", "message": f"Solvent: {exc}"})
                        continue
                    if buf:
                        await websocket.send_bytes(buf)

            elif action == "get_latest":
                if _ctx["universe"] is None:
                    await websocket.send_json({"type": "error", "message": "No trajectory loaded."})
                    continue
                try:
                    frame_msg = await _refresh_latest()
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                await _send_frame(frame_msg)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ── mrdna CG relaxation WebSocket ─────────────────────────────────────────────

@router.websocket("/ws/mrdna-relax")
async def mrdna_relax_ws(websocket: WebSocket) -> None:
    """
    One-shot WebSocket: build a parameterized mrdna CG model, run ARBD simulation,
    extract relaxed backbone positions via coarse spline, stream results.

    Protocol (Server → Client)
    ──────────────────────────
    {"type": "mrdna_progress", "stage": str, "pct": float}
        Stages: building_model → simulating → extracting → done

    {"type": "mrdna_result",
     "positions": [{helix_id, bp_index, direction, backbone_position}, ...],
     "stats": {"n_nucleotides": int, "sim_seconds": float, "n_override": int}}

    {"type": "mrdna_error", "message": str}
    """
    import os
    import tempfile
    import time

    await websocket.accept()
    design = design_state.get_design()
    if design is None:
        await websocket.send_json({"type": "mrdna_error", "message": "No design loaded."})
        await websocket.close()
        return

    async def _prog(stage: str, pct: float) -> None:
        await websocket.send_json({"type": "mrdna_progress", "stage": stage, "pct": pct})

    async def _heartbeat(coro, stage: str, start_pct: float, end_pct: float,
                         interval: float = 1.0):
        task = asyncio.create_task(coro)
        pct = start_pct
        step = (end_pct - start_pct) * interval / 120.0  # assume ≤120 s
        while not task.done():
            await asyncio.sleep(interval)
            if task.done():
                break
            pct = min(pct + step, end_pct - 1.0)
            await websocket.send_json({"type": "mrdna_progress", "stage": stage, "pct": pct})
        return await task

    try:
        await _prog("building_model", 0)

        def _build_model():
            import shutil
            import subprocess
            import sys
            from backend.core.mrdna_bridge import mrdna_tool_path
            _MRDNA_PATH = mrdna_tool_path()
            _MRDNA_REPO = "https://gitlab.engr.illinois.edu/tbgl/tools/mrdna"
            _PATCHES = [
                ("mrdna/readers/segmentmodel_from_lists.py", "s/np\\.in1d(/np.isin(/g"),
                ("mrdna/readers/segmentmodel_from_pdb.py",   "s/np\\.in1d(/np.isin(/g"),
                ("mrdna/readers/libs/base.py",               "s/np\\.finfo(np\\.float)/np.finfo(float)/g"),
                ("mrdna/arbdmodel/submodule/engine.py",      "s/integers(1,99999,1)/integers(1,99999)/g"),
                ("mrdna/model/spring_from_lp.py",            "s/np\\.trapz(/np.trapezoid(/g"),
                ("mrdna/simulate.py",                        "s/rmsdThreshold=1/rmsd_threshold=1/g"),
            ]
            if not os.path.isdir(_MRDNA_PATH):
                subprocess.run(
                    ["git", "clone", "--depth=1", _MRDNA_REPO, _MRDNA_PATH],
                    check=True, capture_output=True,
                )
                for rel_path, expr in _PATCHES:
                    subprocess.run(
                        ["sed", "-i", expr, os.path.join(_MRDNA_PATH, rel_path)],
                        check=True,
                    )
                uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
                subprocess.run(
                    [uv, "pip", "install", "-e", _MRDNA_PATH, "--no-deps", "-q"],
                    check=True, capture_output=True,
                )

            sys.path.insert(0, _MRDNA_PATH)
            from backend.parameterization.mrdna_inject import (
                CrossoverPotentialOverride,
                mrdna_model_from_nadoc_parameterized,
            )
            override = CrossoverPotentialOverride.from_database("T0")
            return mrdna_model_from_nadoc_parameterized(design, override)

        model = await asyncio.to_thread(_build_model)
        await _prog("simulating", 10)

        tmp_dir = tempfile.mkdtemp(prefix="/tmp/nadoc_mrdna_")
        try:
            t0 = time.monotonic()

            def _simulate():
                model.simulate(
                    output_name="nadoc_relax",
                    directory=tmp_dir,
                    coarse_steps=1e5,
                    fine_steps=0,
                    output_period=1e4,
                )

            await _heartbeat(
                asyncio.to_thread(_simulate),
                stage="simulating", start_pct=10, end_pct=80,
            )
            sim_elapsed = time.monotonic() - t0

            await _prog("extracting", 80)

            def _extract():
                import sys
                from backend.core.mrdna_bridge import mrdna_tool_path
                sys.path.insert(0, mrdna_tool_path())
                from backend.core.mrdna_bridge import nuc_pos_override_from_mrdna_coarse
                from backend.core.geometry import nucleotide_positions

                psf = os.path.join(tmp_dir, "nadoc_relax.psf")
                dcd = os.path.join(tmp_dir, "output", "nadoc_relax.dcd")
                override_dict = nuc_pos_override_from_mrdna_coarse(design, psf, dcd)

                # Fill gaps (crossover junctions and ssDNA ends) using nearest-bp
                # displacement within the same helix so ALL nucleotides move
                # consistently — no frozen islands at scaffold turns.
                result = []
                for helix in design.helices:
                    nuc_list = list(nucleotide_positions(helix))

                    # Per-direction sorted (bp_idx → displacement) for this helix
                    dir_disps: dict[str, dict[int, np.ndarray]] = {
                        'FORWARD': {}, 'REVERSE': {}
                    }
                    for nuc in nuc_list:
                        key = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
                        if key in override_dict:
                            disp = override_dict[key] - nuc.position
                            dir_disps[nuc.direction.value][nuc.bp_index] = disp

                    for nuc in nuc_list:
                        key = (nuc.helix_id, nuc.bp_index, nuc.direction.value)
                        if key in override_dict:
                            pos = override_dict[key]
                        else:
                            d_map = dir_disps[nuc.direction.value]
                            if d_map:
                                nearest = min(d_map, key=lambda b: abs(b - nuc.bp_index))
                                pos = nuc.position + d_map[nearest]
                            else:
                                pos = nuc.position
                        result.append({
                            "helix_id":          nuc.helix_id,
                            "bp_index":          nuc.bp_index,
                            "direction":         nuc.direction.value,
                            "backbone_position": pos.tolist(),
                        })
                return result, len(override_dict)

            positions, n_override = await asyncio.to_thread(_extract)

            await _prog("done", 100)
            await websocket.send_json({
                "type":      "mrdna_result",
                "positions": positions,
                "stats": {
                    "n_nucleotides": len(positions),
                    "sim_seconds":   round(sim_elapsed, 2),
                    "n_override":    n_override,
                },
            })

        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as exc:
        await websocket.send_json({"type": "mrdna_error", "message": str(exc)})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── MD job status streaming WebSocket ──────────────────────────────────────────


@router.websocket("/ws/md-jobs/{job_id}")
async def md_job_status_ws(websocket: WebSocket, job_id: str) -> None:
    """
    Stream NAMD job status updates to the UI.

    Protocol (Server → Client only)
    ────────────────────────────────
    {"type": "state", "job": {...}}   — full job dict + live_metrics if running
    {"type": "error", "message": str} — job not found

    Sent immediately on connect, then every 3 s while running.
    Connection closes when status reaches completed / failed / stopped.
    """
    from backend.api.assembly import _WORKSPACE_DIR
    from backend.core.md_job import MdJob, MdStatus
    from backend.core.md_prep_progress import read_prep_progress
    from backend.core.namd_metrics import parse_namd_log
    from backend.core.namd_runner import pending_early_stop, reconcile_job_status

    await websocket.accept()
    try:
        while True:
            try:
                job = reconcile_job_status(MdJob.load(job_id, _WORKSPACE_DIR), _WORKSPACE_DIR)
            except FileNotFoundError:
                await websocket.send_json({"type": "error", "message": f"Job {job_id!r} not found"})
                break
            except Exception as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                break

            payload = job.to_dict()
            # Mid-run early-stop override queued but not yet consumed at a chunk
            # boundary — lets the live toggle show "pending" instead of snapping back
            # to the (still-stale) persisted flag on every 3 s state push.
            payload["early_stop_pending"] = pending_early_stop(job_id)

            # While preparing, attach the live solvation/ENM progress snapshot
            # (phase, fraction, ETA, stall warning) the background worker writes.
            if job.status == MdStatus.preparing:
                prep = read_prep_progress(job.job_dir(_WORKSPACE_DIR))
                if prep is not None:
                    payload["prep_progress"] = prep

            # Attach live NAMD log metrics for the current segment when running
            if job.status == MdStatus.running and 0 <= job.current_segment_idx < len(job.segments):
                seg = job.segments[job.current_segment_idx]
                log_path = job.package_dir(_WORKSPACE_DIR) / f"{seg.name}.log"
                if log_path.exists():
                    try:
                        m = parse_namd_log(log_path)
                        payload["live_metrics"] = {
                            "temperature_k":  m.temperature_k,
                            "pressure_bar":   m.pressure_bar,
                            "pressure_avg_bar": m.pressure_avg_bar,
                            "gpressure_bar":  m.gpressure_bar,
                            "gpressure_avg_bar": m.gpressure_avg_bar,
                            "volume_ang3":    m.volume_ang3,
                            "ns_per_day":     m.ns_per_day,
                            "n_energy_lines": m.n_energy_lines,
                            "timestep":       m.timestep,
                            "segment_steps":  seg.steps,
                            "segment_progress": (
                                min(1.0, max(0.0, float(m.timestep or 0) / float(seg.steps)))
                                if seg.steps else None
                            ),
                        }
                    except Exception:
                        pass

            # Overall progress fraction (0..1) for the master job card's bar.  This is
            # stamped by list_md_jobs on REST polls, but the bar reads progress_fraction
            # from the live WS state too — without it a running job whose master card
            # isn't self-polling (e.g. an oxDNA-SEEDED run that first appeared as a draft,
            # so the master never adopted it as its active node) shows a frozen / "hung"
            # bar even though the detail timeline advances.  Same helper the REST list
            # uses, so the two channels never disagree.
            from backend.api.routes_md import _namd_live_progress  # lazy: avoids a router import cycle
            try:
                # Both numbers, from the same helper the REST list uses: the bar's text
                # would otherwise gain and lose its time-remaining estimate depending on
                # which channel last painted it.
                frac, eta = _namd_live_progress(job, _WORKSPACE_DIR)
                if frac is not None:
                    payload["progress_fraction"] = frac
                if eta is not None:
                    payload["eta_seconds"] = eta
            except Exception:
                pass

            await websocket.send_json({"type": "state", "job": payload})

            if job.status in (MdStatus.completed, MdStatus.failed, MdStatus.stopped):
                break

            # Poll faster while preparing so the solvation progress bar is smooth.
            await asyncio.sleep(1.0 if job.status == MdStatus.preparing else 3.0)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ── MD-engine auto-install WebSocket ──────────────────────────────────────────


@router.websocket("/ws/engines/install")
async def engines_install_ws(websocket: WebSocket) -> None:
    """Auto-build a source MD engine (oxDNA / ANM-oxDNA fork), streaming progress.

    Protocol
    ────────
    Client → Server (once), either:
      {"engine": "oxdna" | "oxdna_anm" | "mrdna"}        — auto-build/install here
      {"engine": "namd", "archive_path": "/path.tar.gz"} — finish a downloaded package
      {"engine": "arbd", "archive_path": "/path.tar.gz"} — build a downloaded source tarball
      {"engine": "arbd", "install_built": true}          — copy an already-built arbd onto PATH (no sudo)
      {"engine": "arbd", "sudo_install": true, "password": "…"} — run `sudo make install` for the user
    Server → Client:
      {"type": "progress",    "stage": str, "pct": int}
      {"type": "log",         "line": str}
      {"type": "complete",    "engine": str, "path": str}
      {"type": "manual_step", "engine": str, "command": str, "note": str}  — built, but
                                               one manual (sudo) line finishes it (ARBD)
      {"type": "error",       "message": str} — bad request, or build/extract failed;
                                                the UI then shows the manual steps.

    Thin wrapper over `engine_install.run_install` / `engine_artifact.install_*_archive`
    (FEATURE_DEVELOPMENT sprout rule — the logic lives in the modules, not here).
    """
    from backend.core.engine_install import InstallError, run_install
    from backend.core.engine_artifact import (
        ArtifactError, install_arbd_archive, install_arbd_binary,
        install_arbd_sudo, install_namd_archive,
    )
    from backend.core.engines import installable_engine_keys

    await websocket.accept()
    try:
        req = await websocket.receive_json() or {}
        engine = req.get("engine")
        archive_path = req.get("archive_path")
        try:
            if engine == "arbd" and req.get("install_built"):
                # No-password finish: copy an already-built ARBD binary onto PATH.
                await install_arbd_binary(websocket.send_json)
            elif engine == "arbd" and req.get("sudo_install"):
                # Run `sudo make install` for the user (password fed to sudo -S).
                await install_arbd_sudo(req.get("password") or "", websocket.send_json)
            elif archive_path:
                # Finish a downloaded package: NAMD (extract) or ARBD (build).
                if engine == "namd":
                    await install_namd_archive(archive_path, websocket.send_json)
                elif engine == "arbd":
                    await install_arbd_archive(archive_path, websocket.send_json)
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"No downloaded-package install for {engine!r}.",
                    })
                    return
            elif engine in installable_engine_keys():
                await run_install(engine, websocket.send_json)
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"{engine!r} cannot be auto-installed here.",
                })
        except (InstallError, ArtifactError) as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception as exc:  # toolchain missing, OSError, bad tar, …
            await websocket.send_json({
                "type": "error",
                "message": f"Install could not run: {exc}",
            })
    except WebSocketDisconnect:
        pass
