"""Composite NAMD/MD trajectory for animation **trajectory keyframes**.

This is the MD analogue of ``oxdna_health.composite_trajectory``: it produces the
same compact ``{keys, frames, markers, stages}`` payload (6 floats per nucleotide —
backbone xyz + base-normal a1) the animation player's trajectory path consumes, but
from a NAMD PSF/DCD run instead of an oxDNA trajectory.

The per-frame DNA→NADOC bead extraction (PBC unwrap → hybrid design-eq correction →
Kabsch alignment → P→C1' base normals) is **ported from the live "Display MD"
WebSocket** (``backend/api/ws.py`` ``_load_sync`` / ``_seek_sync``, the ``nadoc``
path). That WebSocket remains the reference implementation for the live display;
**keep the math here in sync with it.** Kept as a separate (duplicated) reader so
this never touches the validated live-display code path.

CG only (per-nucleotide backbone + normal). NAMD heavy reps (atomistic/surface) are
a later phase — MD all-atom topology does not match the design's atomistic serial
order, so it needs its own mapping.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _build_md_nadoc_ctx(topology_path, trajectory_paths, coordinate_path, design,
                        with_atoms: bool = False) -> dict:
    """Open the PSF + DCD(s), build the P-atom → (helix,bp,dir) order, design
    equilibrium positions, Kabsch reference, and C1' index map. Mirrors the
    ``nadoc``-relevant setup of ws.py ``_load_sync`` (NAMD branch).

    ``with_atoms=True`` also builds the DNA heavy-atom index + element metadata
    (ballstick setup) so per-frame all-atom extraction is available — used by the
    NAMD atomistic/surface trajectory path (Phase 2b)."""
    import MDAnalysis as mda  # type: ignore

    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import (
        _GRO_DNA_RESNAMES,
        _extract_universe,
        build_chain_map,
        build_p_pdb_order,
        centroid_offset,
        md_rigid_reference,
    )

    model = build_atomistic_model(design)
    cm = build_chain_map(model)
    pdb_text = Path(coordinate_path).read_text(errors="replace")
    p_order = build_p_pdb_order(pdb_text, cm)

    # Equilibrium P-atom reference + rigid mask for the Kabsch alignment (shared with
    # the live-display ws handler; handles crossover extra-base "__xb__" inserts).
    eq_positions, eq_valid, rigid_mask = md_rigid_reference(model, p_order)
    if int(rigid_mask.sum()) < 3:
        eq_centroid = np.zeros(3)
        eq_centered = None
    else:
        eq_centroid = eq_positions[rigid_mask].mean(axis=0)
        eq_centered = eq_positions - eq_centroid
        eq_centered[~rigid_mask] = 0.0

    paths = [str(p) for p in trajectory_paths]
    u = mda.Universe(str(topology_path), paths if len(paths) > 1 else paths[0])
    # Best-effort PBC make-whole (mirrors ws._try_unwrap).
    try:
        from MDAnalysis.transformations import unwrap as mda_unwrap  # type: ignore
        if hasattr(u.atoms, "bonds") and len(u.atoms.bonds) > 0:
            u.trajectory.add_transformations(mda_unwrap(u.atoms))
    except Exception:
        pass

    n_frames = len(u.trajectory)
    beads_0 = _extract_universe(u, 0, p_order)
    T = centroid_offset(beads_0, design)

    dna_p_sel = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
    c1p_list: list[int] = []
    for p_atom in dna_p_sel:
        c1p_atoms = p_atom.residue.atoms.select_atoms("name C1'")
        c1p_list.append(int(c1p_atoms[0].index) if len(c1p_atoms) > 0 else -1)
    c1p_idx = np.array(c1p_list, dtype=np.int64)

    heavy_idx = None
    atom_meta = None
    if with_atoms:
        # DNA heavy atoms (no hydrogens, no solvent) — same selection + element
        # derivation as ws.py _load_sync ballstick setup.
        resnames = " ".join(_GRO_DNA_RESNAMES)
        try:
            dna_heavy = u.select_atoms(f"not element H and resname {resnames}")
        except Exception:
            dna_heavy = u.select_atoms(
                f"(not name H* and not name [0-9]H*) and resname {resnames}")

        def _element(a) -> str:
            try:
                e = a.element
                if e:
                    return e
            except Exception:
                pass
            name = a.name.lstrip("0123456789")
            return name[0].upper() if name else "C"

        heavy_idx = dna_heavy.indices
        atom_meta = [{"serial": int(a.index), "element": _element(a)} for a in dna_heavy]

    return {
        "universe": u, "p_order": p_order, "n_frames": n_frames,
        "centroid_T": T, "eq_positions": eq_positions, "eq_valid": eq_valid,
        "rigid_mask": rigid_mask, "eq_centroid": eq_centroid, "eq_centered": eq_centered,
        "c1p_idx": c1p_idx, "heavy_idx": heavy_idx, "atom_meta": atom_meta,
        "R_prev": None, "prev_frame_idx": -999,
    }


def _extract_md_nadoc_frame(ctx: dict, frame_idx: int):
    """Per-frame DNA P-atom positions (nm, NADOC frame) + base normals for one DCD
    frame. Ported from ws.py ``_seek_sync`` (nadoc path). Returns ``(p_nm, normals)``
    where ``p_nm`` is (N,3) and ``normals`` is (N,3) or ``None``."""
    from backend.core.atomistic_to_nadoc import _GRO_DNA_RESNAMES, _unwrap_min_image

    u = ctx["universe"]
    p_order = ctx["p_order"]
    T = ctx["centroid_T"]
    eq_pos = ctx["eq_positions"]
    eq_valid = ctx["eq_valid"]
    rigid_mask = ctx["rigid_mask"]
    eq_centered = ctx["eq_centered"]
    eq_centroid = ctx["eq_centroid"]

    u.trajectory[frame_idx]
    dna_p = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
    p_raw = dna_p.positions / 10.0
    dims = u.dimensions

    if dims is not None and dims[0] > 0:
        box_nm = dims[:3] / 10.0
        p_box = _unwrap_min_image(p_raw, box_nm)
        if rigid_mask is not None and rigid_mask.any():
            _c_box = np.median(p_box[rigid_mask], axis=0)
        else:
            _c_box = p_box.mean(axis=0)
        _T_dyn = eq_centroid - _c_box
        if (eq_pos is not None and eq_centroid is not None
                and rigid_mask is not None and len(eq_pos) == len(p_box)):
            _eq_box = eq_pos - _T_dyn
            _dc = p_box - _eq_box
            for _d in range(3):
                if box_nm[_d] > 0:
                    _dc[:, _d] -= np.round(_dc[:, _d] / box_nm[_d]) * box_nm[_d]
            p_box_corr = _eq_box + _dc
            p_box_corr[~rigid_mask] = p_box[~rigid_mask]
            p_nm = p_box_corr + _T_dyn
        else:
            p_nm = p_box + _T_dyn
    else:
        p_nm = p_raw + T

    # Kabsch rotation aligned to the design equilibrium (rigid dsDNA atoms only),
    # with the sequential rotation-flip guard from _seek_sync.
    R_align = None
    R_prev = ctx.get("R_prev")
    prev_frame = ctx.get("prev_frame_idx", -999)
    _is_sequential = abs(frame_idx - prev_frame) <= 3
    if (eq_centered is not None and eq_centroid is not None
            and len(eq_centered) == len(p_nm)):
        _rm = rigid_mask if (rigid_mask is not None and rigid_mask.any()) else (
            eq_valid if (eq_valid is not None and eq_valid.any()) else None)
        _mob_c = p_nm[_rm].mean(axis=0) if _rm is not None else p_nm.mean(axis=0)
        _mc = p_nm - _mob_c
        _H = _mc.T @ eq_centered
        _U2, _, _Vt2 = np.linalg.svd(_H)
        _d2 = np.linalg.det(_Vt2.T @ _U2.T)
        R_align = _Vt2.T @ np.diag([1.0, 1.0, _d2]) @ _U2.T

        if R_prev is not None and _is_sequential:
            _dR = R_align @ R_prev.T
            _cos = max(-1.0, min(1.0, (float(np.trace(_dR)) - 1.0) / 2.0))
            _angle_deg = np.degrees(np.arccos(_cos))
            if _angle_deg > 60.0:
                _p_nm_raw = _mc @ R_align.T + eq_centroid
                _pre_d = np.linalg.norm(_p_nm_raw - eq_pos, axis=1)
                _med_d = np.median(_pre_d[_rm]) if _rm is not None else np.median(_pre_d)
                _inlier = _rm & (_pre_d < _med_d * 3.0) if _rm is not None else (_pre_d < _med_d * 3.0)
                if _inlier.sum() >= 10:
                    _mob_c2 = p_nm[_inlier].mean(axis=0)
                    _mc2 = p_nm - _mob_c2
                    _eq_c2 = eq_pos - eq_centroid
                    _eq_c2[~_inlier] = 0.0
                    _H2 = _mc2.T @ _eq_c2
                    _U3, _, _Vt3 = np.linalg.svd(_H2)
                    _d3 = np.linalg.det(_Vt3.T @ _U3.T)
                    R_inlier = _Vt3.T @ np.diag([1.0, 1.0, _d3]) @ _U3.T
                    _dR2 = R_inlier @ R_prev.T
                    _cos2 = max(-1.0, min(1.0, (float(np.trace(_dR2)) - 1.0) / 2.0))
                    if np.arccos(_cos2) < np.arccos(_cos):
                        R_align = R_inlier
                        _mob_c = _mob_c2
                        _mc = _mc2
        p_nm = _mc @ R_align.T + eq_centroid
        ctx["R_prev"] = R_align
        ctx["prev_frame_idx"] = frame_idx

    # Base normals (P→C1') rotated into the aligned frame.
    c1p_idx = ctx.get("c1p_idx")
    normals = None
    if c1p_idx is not None and np.all(c1p_idx >= 0) and len(c1p_idx) == len(p_order):
        c1p_raw = u.atoms[c1p_idx].positions / 10.0
        dn = c1p_raw - p_raw
        if R_align is not None:
            dn = dn @ R_align.T
        norms = np.linalg.norm(dn, axis=1, keepdims=True)
        norms = np.where(norms > 1e-6, norms, 1.0)
        normals = dn / norms

    return p_nm, normals


def _extract_md_atoms_frame(ctx: dict, frame_idx: int) -> list[dict]:
    """DNA heavy-atom coordinates (nm, NADOC frame) for one DCD frame, as
    ``[{serial, element, x, y, z}, …]``. Ported from ws.py ``_seek_sync`` (ballstick
    path): residue-local reconstruction of each heavy atom relative to its corrected
    P atom, then the same Kabsch alignment as the bead path so the all-atom and CG
    views coincide. Requires a ctx built with ``with_atoms=True``."""
    from backend.core.atomistic_to_nadoc import _GRO_DNA_RESNAMES, _unwrap_min_image

    u = ctx["universe"]
    p_order = ctx["p_order"]
    T = ctx["centroid_T"]
    heavy_idx = ctx["heavy_idx"]
    atom_meta = ctx["atom_meta"]
    eq_pos = ctx["eq_positions"]
    rigid_mask = ctx["rigid_mask"]
    eq_centroid = ctx["eq_centroid"]
    eq_centered = ctx["eq_centered"]

    u.trajectory[frame_idx]
    ag = u.atoms[heavy_idx]
    pos_raw = ag.positions / 10.0
    pos_nm = pos_raw + T

    try:
        dna_p = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
        p_raw = dna_p.positions / 10.0
        dims = u.dimensions
        if dims is not None and dims[0] > 0 and len(p_raw) == len(p_order):
            box_nm = dims[:3] / 10.0
            p_box = _unwrap_min_image(p_raw, box_nm)
            if rigid_mask is not None and rigid_mask.any():
                c_box = np.median(p_box[rigid_mask], axis=0)
            else:
                c_box = p_box.mean(axis=0)
            T_dyn = eq_centroid - c_box if eq_centroid is not None else T
            if (eq_pos is not None and eq_centroid is not None
                    and rigid_mask is not None and len(eq_pos) == len(p_box)):
                eq_box = eq_pos - T_dyn
                dc = p_box - eq_box
                for d in range(3):
                    if box_nm[d] > 0:
                        dc[:, d] -= np.round(dc[:, d] / box_nm[d]) * box_nm[d]
                p_box_corr = eq_box + dc
                p_box_corr[~rigid_mask] = p_box[~rigid_mask]
                p_pre = p_box_corr + T_dyn
            else:
                p_pre = p_box + T_dyn

            # Residue-local reconstruction: heavy atom = corrected P +
            # minimum-image(raw atom − raw P), anchored to each residue's P.
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

            def _anchor_residue_ix(atom):
                res_ix = int(atom.residue.ix)
                if res_ix in p_raw_by_res:
                    return res_ix
                segid = str(getattr(atom.residue, "segid", "") or getattr(atom, "segid", ""))
                resid = int(atom.residue.resid)
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
                        delta[d] -= np.round(delta[d] / box_nm[d]) * box_nm[d]
                pos_pre[i] = pc + delta

            if (eq_centered is not None and eq_centroid is not None
                    and len(eq_centered) == len(p_pre)):
                rm = rigid_mask if (rigid_mask is not None and rigid_mask.any()) else None
                mob_c = p_pre[rm].mean(axis=0) if rm is not None else p_pre.mean(axis=0)
                mc = p_pre - mob_c
                H = mc.T @ eq_centered
                U2, _, Vt2 = np.linalg.svd(H)
                det = np.linalg.det(Vt2.T @ U2.T)
                R_align = Vt2.T @ np.diag([1.0, 1.0, det]) @ U2.T
                pos_nm = (pos_pre - mob_c) @ R_align.T + eq_centroid
            else:
                pos_nm = pos_pre
    except Exception:
        pass

    return [
        {"serial": m["serial"], "element": m["element"],
         "x": float(pos_nm[i, 0]), "y": float(pos_nm[i, 1]), "z": float(pos_nm[i, 2])}
        for i, m in enumerate(atom_meta)
    ]


class _SurfAtom:
    """Minimal atom for compute_surface (reads .x/.y/.z/.element + .strand_id)."""
    __slots__ = ("x", "y", "z", "element", "strand_id")

    def __init__(self, x, y, z, element):
        self.x = x; self.y = y; self.z = z; self.element = element
        self.strand_id = ""


def md_frames_atomistic(topology_path, segments, coordinate_path, design,
                        frame_indices) -> dict:
    """Per-frame DNA heavy atoms for the given composite-frame indices →
    ``{ "<idx>": {atoms:[{serial,element,x,y,z}], bonds:[]} }``. The atom set is the
    NAMD model's own DNA heavy atoms (Phase 2b renders these directly rather than
    mapping onto the design's idealized template)."""
    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_atoms=True)
    n = ctx["n_frames"]
    out: dict[str, dict] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= n:
            continue
        out[str(idx)] = {"atoms": _extract_md_atoms_frame(ctx, idx), "bonds": []}
    return out


def md_frames_surface(topology_path, segments, coordinate_path, design, frame_indices,
                      probe_radius: float = 0.28, grid_spacing: float = 0.20,
                      radius_inflate: float = 1.30, smooth: int = 15, **_ignore) -> dict:
    """Per-frame molecular surface from the NAMD DNA heavy atoms → surface-batch
    shape ``{ "<idx>": {vertices, faces} }`` (uniform colour for v1)."""
    from backend.core.surface import compute_surface, smooth_mesh

    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_atoms=True)
    n = ctx["n_frames"]
    out: dict[str, dict] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= n:
            continue
        atoms = [_SurfAtom(a["x"], a["y"], a["z"], a["element"])
                 for a in _extract_md_atoms_frame(ctx, idx)]
        mesh = compute_surface(atoms, grid_spacing=grid_spacing,
                               probe_radius=probe_radius, radius_scale=1.2 * radius_inflate)
        mesh = smooth_mesh(mesh, iterations=smooth)
        out[str(idx)] = {"vertices": [round(float(v), 5) for v in mesh.vertices.ravel()],
                         "faces": [int(f) for f in mesh.faces.ravel()]}
    return out


def md_rmsf(topology_path, segments, coordinate_path, design,
            max_frames: int = 150) -> dict:
    """Per-nucleotide average backbone position + RMSF over the NAMD run.

    The MD analogue of ``oxdna_health.production_rmsf``: pools frames from EVERY
    written segment (the user's flex-map gating is "all segments"), Kabsch-aligns
    each frame to the design equilibrium (rigid-body motion removed, identical math
    to the live Display-MD path via ``_extract_md_nadoc_frame``), and computes per
    nucleotide the mean backbone-bead position, the mean base normal (a1), and the
    RMSF = sqrt(mean_f |p_f - mean|^2).

    Returns the SAME payload shape as ``GET /oxdna/jobs/{id}/rmsf`` so the frontend
    flexibility-map code (rmsfColorMap / displayRmsf) consumes it unchanged:
    ``{ready, n_frames, positions:[{helix_id, bp_index, direction, backbone_position,
    nx, ny, nz, rmsf}], min_rmsf, max_rmsf, mean_rmsf}``.

    Frames are sampled evenly to at most ``max_frames`` to bound the per-frame Kabsch
    cost; each sampled frame is aligned independently (the sequential rotation-flip
    guard only fires for adjacent frames, which strided sampling never hits)."""
    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design)
    p_order = ctx["p_order"]
    n = ctx["n_frames"]
    n_keys = len(p_order)
    if n <= 0 or n_keys == 0:
        return {"ready": False, "n_frames": 0, "positions": []}

    idxs = list(range(n)) if n <= max_frames else _stride_pick(list(range(n)), max_frames)

    # One-pass accumulation: RMSF^2 = mean_f|p_f|^2 - |mean_f p_f|^2 (per nucleotide).
    sum_pos = np.zeros((n_keys, 3))
    sum_sq = np.zeros(n_keys)        # Σ_f |p_f|^2
    sum_norm = np.zeros((n_keys, 3))
    have_norm = False
    used = 0
    for gidx in idxs:
        p_nm, normals = _extract_md_nadoc_frame(ctx, gidx)
        if p_nm is None or len(p_nm) != n_keys:
            continue
        sum_pos += p_nm
        sum_sq += np.einsum("ij,ij->i", p_nm, p_nm)
        if normals is not None and len(normals) == n_keys:
            sum_norm += normals
            have_norm = True
        used += 1
    if used == 0:
        return {"ready": False, "n_frames": 0, "positions": []}

    mean_pos = sum_pos / used
    msd = sum_sq / used - np.einsum("ij,ij->i", mean_pos, mean_pos)
    rmsf = np.sqrt(np.maximum(msd, 0.0))

    if have_norm:
        nrm = np.linalg.norm(sum_norm, axis=1, keepdims=True)
        mean_norm = sum_norm / np.where(nrm > 1e-6, nrm, 1.0)
    else:
        mean_norm = np.tile([0.0, 0.0, 1.0], (n_keys, 1))

    positions = []
    for i, (hid, bp, direction) in enumerate(p_order):
        positions.append({
            "helix_id": hid,
            "bp_index": bp,
            "direction": direction,
            "backbone_position": [float(mean_pos[i, 0]), float(mean_pos[i, 1]),
                                  float(mean_pos[i, 2])],
            "nx": float(mean_norm[i, 0]),
            "ny": float(mean_norm[i, 1]),
            "nz": float(mean_norm[i, 2]),
            "rmsf": float(rmsf[i]),
        })

    return {
        "ready": True,
        "n_frames": used,
        "positions": positions,
        "min_rmsf": float(rmsf.min()),
        "max_rmsf": float(rmsf.max()),
        "mean_rmsf": float(rmsf.mean()),
    }


def md_composite_meta(segments, max_frames: int = 200) -> dict:
    """Lightweight metadata for the NAMD composite — ``{n_frames, markers, stages}``
    — from DCD frame counts only (DCD header, no PSF parse, no coordinate read), so
    the trajectory-keyframe slider sizes itself in milliseconds. Replicates
    md_composite_trajectory's per-segment downsample so indices match exactly."""
    from MDAnalysis.coordinates.DCD import DCDReader  # type: ignore

    counts = []
    for name, kind, dcd in segments:
        try:
            n = len(DCDReader(str(dcd)))
        except Exception:
            n = 0
        counts.append((name, kind, n))
    total = sum(c for _, _, c in counts)
    if total == 0:
        return {"n_frames": 0, "stages": [], "markers": []}

    out_n = 0
    out_stages: list[dict] = []
    markers: list[dict] = []
    for name, kind, c in counts:
        if c <= 0:
            continue
        keep = max(1, round(c * max_frames / total)) if total > max_frames else c
        if out_n:
            markers.append({"frame": out_n, "label": f"→ {name}",
                            "kind": kind or "md", "stage_name": name})
        out_stages.append({"name": name, "kind": kind or "md", "n_frames": keep})
        out_n += keep
    return {"n_frames": out_n, "stages": out_stages, "markers": markers}


def _stride_pick(items: list, keep: int) -> list:
    if keep >= len(items) or keep <= 0:
        return items
    return [items[round(i * (len(items) - 1) / (keep - 1))] for i in range(keep)] \
        if keep > 1 else [items[0]]


def md_composite_trajectory(topology_path, segments, coordinate_path, design,
                            max_frames: int = 200) -> dict:
    """Composite scrub-able NAMD trajectory for a trajectory keyframe.

    ``segments`` = ordered ``[(name, stage, dcd_path), …]`` (every segment that has
    written a DCD). All DCDs load into ONE MDAnalysis Universe (continuous frame
    index); frames are downsampled per segment (≥1 each) to ≤ ``max_frames`` with a
    boundary marker at each segment start. Returns the same shape as
    ``oxdna_health.composite_trajectory``."""
    import MDAnalysis as mda  # type: ignore

    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design)
    p_order = ctx["p_order"]
    key_list = [list(k) for k in p_order]

    # Per-segment frame counts (for boundary markers + per-segment downsample).
    seg_counts: list[int] = []
    for _, _, dcd in segments:
        su = mda.Universe(str(topology_path), str(dcd))
        seg_counts.append(len(su.trajectory))
    total = sum(seg_counts)
    if total == 0:
        return {"n_frames": 0, "n_nucleotides": len(key_list),
                "keys": key_list, "frames": [], "stages": [], "markers": []}

    out_frames: list[list[float]] = []
    out_stages: list[dict] = []
    markers: list[dict] = []
    offset = 0
    run_no = 0
    for (name, stage, _dcd), count in zip(segments, seg_counts):
        if count <= 0:
            continue
        global_idxs = list(range(offset, offset + count))
        keep = max(1, round(count * max_frames / total)) if total > max_frames else count
        picked = _stride_pick(global_idxs, keep)
        if out_frames:
            run_no += 1
            markers.append({"frame": len(out_frames), "label": f"→ {name}",
                            "kind": stage or "md", "stage_name": name})
        out_stages.append({"name": name, "kind": stage or "md", "n_frames": len(picked)})
        for gidx in picked:
            p_nm, normals = _extract_md_nadoc_frame(ctx, gidx)
            flat: list[float] = []
            for i in range(len(p_order)):
                flat.extend((float(p_nm[i, 0]), float(p_nm[i, 1]), float(p_nm[i, 2])))
                if normals is not None:
                    flat.extend((float(normals[i, 0]), float(normals[i, 1]), float(normals[i, 2])))
                else:
                    flat.extend((0.0, 0.0, 1.0))
            out_frames.append(flat)
        offset += count

    return {"n_frames": len(out_frames), "n_nucleotides": len(key_list),
            "keys": key_list, "frames": out_frames,
            "stages": out_stages, "markers": markers}
