"""
API layer — WebSocket handlers for MD trajectory streaming and mrdna CG relaxation.

Routes
──────
  /ws/md-run       — GROMACS trajectory streamer (load / seek / get_latest)
  /ws/mrdna-relax  — one-shot mrdna CG relaxation pipeline

(XPBD physics + FEM solver routes were removed 2026-05-10; archived under
`archive/physics_xpbd_fem/`. See archive README for context.)
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api import state as design_state
import numpy as np

router = APIRouter()


# ── MD trajectory streaming WebSocket ─────────────────────────────────────────


@router.websocket("/ws/md-run")
async def md_run_ws(websocket: WebSocket) -> None:
    """
    WebSocket for streaming GROMACS trajectory frames into NADOC.

    Protocol
    ────────
    Client → Server
      {"action": "load",
       "topology_path": str,   # abs path to .gro or .tpr
       "xtc_path":      str,   # abs path to .xtc
       "mode": "nadoc"|"beads"|"ballstick"}
      {"action": "seek",       "frame_idx": int}
      {"action": "get_latest"}

    Server → Client
      {"type": "log",     "message": str}          (emitted during load)
      {"type": "ready",   "n_frames": int, "n_p_atoms": int,
                          "ns_per_day": float|null, "temperature_k": float|null,
                          "total_ns": float|null, "dt_ps": float|null,
                          "nstxout_comp": int|null}
      {"type": "frame",   "frame_idx": int, "n_frames": int, "time_ps": float,
                          "positions": [{helix_id, bp_index, direction, x, y, z}, ...]}
        (ballstick) same but "atoms": [{serial, element, x, y, z}, ...]
      {"type": "error",   "message": str}
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
    }

    def _try_unwrap(u, logs: list) -> None:
        """Add PBC make-whole transformation to the Universe if bond data exists.

        GRO topologies carry no bond information — calling guess_bonds() on a
        solvated system (200k+ atoms) would take hours (O(n²)).  Only TPR files
        provide bonds directly, so we skip unwrapping for GRO.  The centroid
        offset computed in _load_sync still re-centres the structure correctly.
        """
        try:
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

    def _load_sync(topology_str: str, xtc_str: str, mode: str, design) -> dict:
        """Synchronous load — runs inside asyncio.to_thread."""
        from pathlib import Path

        import MDAnalysis as mda  # type: ignore

        from backend.core.atomistic import build_atomistic_model
        from backend.core.atomistic_to_nadoc import (
            _GRO_DNA_RESNAMES,
            _extract_universe,
            _unwrap_min_image,
            build_chain_map,
            build_p_gro_order,
            centroid_offset,
        )
        from backend.core.md_metrics import derive_total_ns, parse_log_metrics

        logs: list[str] = []
        load_warnings: list[str] = []

        topology_path = Path(topology_str)
        xtc_path      = Path(xtc_str)
        run_dir       = topology_path.parent

        logs.append(f"Topology : {topology_path.name}")
        logs.append(f"Trajectory: {xtc_path.name}")

        # Require input_nadoc.pdb in the same directory for chain mapping.
        input_pdb = run_dir / "input_nadoc.pdb"
        if not input_pdb.exists():
            raise ValueError(
                f"input_nadoc.pdb not found in {run_dir}. "
                "Select a topology from a NADOC-generated GROMACS run directory."
            )

        # Build chain map from current design.
        model    = build_atomistic_model(design)
        cm       = build_chain_map(model)
        pdb_text = input_pdb.read_text(errors="replace")
        p_order  = build_p_gro_order(pdb_text, cm)
        logs.append(f"Chain map : {len(cm)} P atoms, {len(p_order)} GRO P entries")

        # Design equilibrium positions for each entry in p_order (nm, NADOC frame).
        # Used for Kabsch rotation alignment.  Entries in p_order that have no
        # matching P-atom in the current design get np.zeros(3); track these with
        # eq_valid so they can be excluded from the Kabsch computation (including
        # them would skew the centroid and H matrix).
        _p_ref = {(a.helix_id, a.bp_index, a.direction): np.array([a.x, a.y, a.z])
                  for a in model.atoms if a.name == "P"}
        _eq_list  = [_p_ref.get((hid, bpi, d)) for hid, bpi, d in p_order]
        eq_valid  = np.array([v is not None for v in _eq_list], dtype=bool)
        eq_positions = np.array([v if v is not None else np.zeros(3) for v in _eq_list])
        n_valid = int(eq_valid.sum())
        logs.append(f"Eq-pos    : {n_valid}/{len(p_order)} valid design P-atoms")

        # Rigid mask: exclude ssDNA (bp_index < 0) from Kabsch rotation computation.
        # Terminal / loop nucleotides have large thermal fluctuations that would
        # bias the rigid-body rotation fit away from the true dsDNA orientation.
        rigid_mask = eq_valid & np.array([bpi >= 0 for _, bpi, _ in p_order], dtype=bool)
        n_rigid = int(rigid_mask.sum())
        logs.append(f"Rigid P   : {n_rigid}/{len(p_order)} (bp≥0 for Kabsch)")

        if n_rigid < 3:
            eq_centroid = np.zeros(3)
            eq_centered = None
        else:
            eq_centroid  = eq_positions[rigid_mask].mean(axis=0)
            eq_centered  = eq_positions - eq_centroid
            eq_centered[~rigid_mask] = 0.0   # only rigid atoms contribute to H

        # Open MDAnalysis Universe.
        logs.append("Opening MDAnalysis Universe…")
        u        = mda.Universe(str(topology_path), str(xtc_path))
        n_frames = len(u.trajectory)
        logs.append(f"Frames    : {n_frames}")

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
            "p_order":       p_order,
            "eq_positions":  eq_positions,
            "eq_valid":      eq_valid,
            "rigid_mask":    rigid_mask,
            "eq_centroid":   eq_centroid,
            "eq_centered":   eq_centered,
            "centroid_T":    T,
            "n_frames":      n_frames,
            "n_p_atoms":     len(cm),
            "dt_ps":         metrics.dt_ps         if metrics else None,
            "nstxout_comp":  metrics.nstxout_comp  if metrics else None,
            "ns_per_day":    metrics.ns_per_day    if metrics else None,
            "temperature_k": metrics.temperature_k if metrics else None,
            "total_ns":      total_ns,
            "atom_meta":     None,
            "heavy_idx":     None,
            "c1p_idx":       c1p_idx,
            "logs":          logs,
            "warnings":      load_warnings,
            # Sequential rotation tracking: reset on load.
            "R_prev":        None,
            "prev_frame_idx": -999,
        }

        if mode == "ballstick":
            # Use name-based hydrogen filter — GRO topologies carry no element
            # data so "not element H" raises AttributeError.  GROMACS outputs
            # hydrogen atom names starting with H (CHARMM36, AMBER, etc.).
            # Digit-prefixed AMBER hydrogens (e.g. 1H2) are also excluded via
            # the second pattern.
            resnames = " ".join(_GRO_DNA_RESNAMES)
            try:
                dna_heavy = u.select_atoms(
                    f"not element H and resname {resnames}"
                )
            except Exception:
                dna_heavy = u.select_atoms(
                    f"(not name H* and not name [0-9]H*) and resname {resnames}"
                )

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

            result["heavy_idx"] = dna_heavy.indices
            result["atom_meta"] = [
                {"serial": int(a.index), "element": _element(a)}
                for a in dna_heavy
            ]

        return result

    def _seek_sync(frame_idx: int) -> dict:
        """Extract one frame — runs in asyncio.to_thread."""
        import numpy as _np
        from backend.core.atomistic_to_nadoc import _GRO_DNA_RESNAMES, _unwrap_min_image

        u        = _ctx["universe"]
        p_order  = _ctx["p_order"]
        T        = _ctx["centroid_T"]
        mode     = _ctx["mode"]
        n_frames = _ctx["n_frames"]

        ts      = u.trajectory[frame_idx]
        time_ps = float(ts.time)

        if mode in ("nadoc", "beads"):
            dna_p       = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
            p_raw       = dna_p.positions / 10.0                   # Å → nm, box coords
            dims        = u.dimensions
            eq_pos      = _ctx.get("eq_positions")
            eq_valid    = _ctx.get("eq_valid")
            rigid_mask  = _ctx.get("rigid_mask")
            eq_centered = _ctx.get("eq_centered")
            eq_centroid = _ctx.get("eq_centroid")

            # All PBC corrections must happen in box coordinates (before adding T).
            if dims is not None and dims[0] > 0:
                box_nm = dims[:3] / 10.0

                # Step 1 — sequential nearest-image (fixes intra-strand PBC splits).
                p_box = _unwrap_min_image(p_raw, box_nm)

                # Dynamic T: use the CURRENT centroid from sequential-unwrapped atoms.
                # Use the MEDIAN of rigid (dsDNA, bp≥0) atoms rather than the mean so
                # that a minority of wrongly-relocated atoms (sequential unwrap errors at
                # strand boundaries / extreme frames) do not bias the centroid estimate.
                if rigid_mask is not None and rigid_mask.any():
                    _c_box = _np.median(p_box[rigid_mask], axis=0)
                else:
                    _c_box = p_box.mean(axis=0)

                # Step 2 — hybrid PBC correction:
                #   Rigid dsDNA atoms (rigid_mask = bp≥0): per-atom nearest-image to
                #     design eq (in dynamic-T box frame).  Their MD positions are always
                #     within ~5 nm of design (thermal + FF), safely < half-box.
                #   ssDNA atoms (bp<0): raw sequential-unwrap + T_dyn.  ssDNA can be
                #     anywhere in the box; comparing to ideal B-DNA design positions
                #     gives unreliable DC that the nearest-image step may snap to the
                #     wrong periodic image.
                _T_dyn = eq_centroid - _c_box   # current box → NADOC frame (dynamic)
                if (eq_pos is not None and eq_centroid is not None
                        and rigid_mask is not None and len(eq_pos) == len(p_box)):
                    _eq_box = eq_pos - _T_dyn          # design eq in current box frame
                    _dc     = p_box - _eq_box
                    for _d in range(3):
                        if box_nm[_d] > 0:
                            _dc[:, _d] -= _np.round(_dc[:, _d] / box_nm[_d]) * box_nm[_d]
                    # Start from design position + nearest-imaged displacement
                    p_box_corr = _eq_box + _dc          # corrected box-frame positions
                    # Overwrite ssDNA atoms: keep sequential-unwrap position (no design-eq snap)
                    p_box_corr[~rigid_mask] = p_box[~rigid_mask]
                    p_nm = p_box_corr + _T_dyn          # NADOC frame
                else:
                    _T_dyn = eq_centroid - _c_box if (eq_centroid is not None) else T
                    p_nm = p_box + _T_dyn
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
                        print(f"[ws seek] frame={frame_idx} rotation jump {_angle_deg:.1f}° "
                              f"→ inlier Kabsch applied", flush=True)

                p_nm = _mc @ R_align.T + eq_centroid
                _ctx["R_prev"]         = R_align
                _ctx["prev_frame_idx"] = frame_idx

                # Server-side diagnostic (one line per frame).
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
                c1p_raw = u.atoms[c1p_idx].positions / 10.0        # Å → nm
                dn      = c1p_raw - p_raw                          # intra-residue vector (no PBC issue)
                if R_align is not None:
                    dn = dn @ R_align.T                            # rotate into aligned frame
                norms   = _np.linalg.norm(dn, axis=1, keepdims=True)
                norms   = _np.where(norms > 1e-6, norms, 1.0)
                normals = dn / norms                               # unit vectors

            positions = []
            for i, (hid, bpi, d) in enumerate(p_order):
                entry: dict = {
                    "helix_id":  hid,
                    "bp_index":  bpi,
                    "direction": d,
                    "x": float(p_nm[i, 0]),
                    "y": float(p_nm[i, 1]),
                    "z": float(p_nm[i, 2]),
                }
                if normals is not None:
                    entry["nx"] = float(normals[i, 0])
                    entry["ny"] = float(normals[i, 1])
                    entry["nz"] = float(normals[i, 2])
                positions.append(entry)
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
            pos_nm    = ag.positions / 10.0 + T
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

    try:
        while True:
            msg    = await websocket.receive_json()
            action = msg.get("action")

            if action == "load":
                topology_str = msg.get("topology_path", "")
                xtc_str      = msg.get("xtc_path", "")
                mode         = msg.get("mode", "nadoc")
                design       = design_state.get_design()
                if design is None:
                    await websocket.send_json({"type": "error", "message": "No design loaded."})
                    continue
                if not topology_str or not xtc_str:
                    await websocket.send_json({"type": "error", "message": "topology_path and xtc_path are required."})
                    continue
                try:
                    loaded = await asyncio.to_thread(_load_sync, topology_str, xtc_str, mode, design)
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue

                _ctx.update(loaded)
                _ctx["mode"] = mode

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
                    "warnings":      loaded.get("warnings", []),
                })

            elif action == "seek":
                if _ctx["universe"] is None:
                    await websocket.send_json({"type": "error", "message": "No trajectory loaded."})
                    continue
                frame_idx = int(msg.get("frame_idx", 0))
                frame_idx = max(0, min(frame_idx, _ctx["n_frames"] - 1))
                try:
                    frame_msg = await asyncio.to_thread(_seek_sync, frame_idx)
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                await websocket.send_json(frame_msg)

            elif action == "get_latest":
                if _ctx["universe"] is None:
                    await websocket.send_json({"type": "error", "message": "No trajectory loaded."})
                    continue

                def _refresh_and_seek() -> dict:
                    """Rebuild Universe from disk to discover frames written since load, then seek last."""
                    import MDAnalysis as mda  # type: ignore
                    new_u = mda.Universe(_ctx["topology_path"], _ctx["xtc_path"])
                    _ctx["universe"] = new_u
                    _ctx["n_frames"] = len(new_u.trajectory)
                    return _seek_sync(_ctx["n_frames"] - 1)

                try:
                    frame_msg = await asyncio.to_thread(_refresh_and_seek)
                except Exception as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                await websocket.send_json(frame_msg)

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
            import subprocess
            import sys
            _MRDNA_PATH = "/tmp/mrdna-tool"
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
                uv = os.path.expanduser("~/.local/bin/uv")
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
                import numpy as np
                sys.path.insert(0, "/tmp/mrdna-tool")
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
