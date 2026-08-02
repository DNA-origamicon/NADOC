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


def _select_p_order(u, chain_map, run_dir, coordinate_path):
    """Choose the DNA-P → (helix, bp, dir) order for a NAMD PSF/DCD Universe.

    Prefer the PSF-segid map (the package's ``charge_audit.json``): CHARMM psfgen
    collapses NADOC's multi-char chain ids (``A``, ``AA``, ``AB``, …) into the
    reference PDB's single-char ``chainID`` field, so the PDB-key path
    (``build_p_pdb_order``) collides across strands and DROPS atoms for many-strand
    designs.  That makes ``len(p_order) != `` the universe DNA-P count, which the
    strict per-frame length guard in ``md_rmsf`` / the trajectory extractor treats as
    "no usable frames" — silently voiding the flexibility map.  Fall back to the
    reference PDB only when the package has no ``charge_audit`` or the segid map is
    incomplete.  Mirrors ws.py's live-display NAMD branch.  Returns ``(p_order,
    source)`` where ``source`` is ``"segid"`` or ``"reference-pdb"``.
    """
    from backend.core.atomistic_to_nadoc import (
        build_p_order_from_universe,
        build_p_pdb_order,
        load_segid_chain_map,
    )
    seg2chain = load_segid_chain_map(Path(run_dir))
    if seg2chain:
        cand, n_unmapped = build_p_order_from_universe(u, chain_map, seg2chain)
        if n_unmapped == 0 and cand:
            return cand, "segid"
    pdb_text = Path(coordinate_path).read_text(errors="replace")
    return build_p_pdb_order(pdb_text, chain_map), "reference-pdb"


def _build_md_nadoc_ctx(topology_path, trajectory_paths, coordinate_path, design,
                        with_atoms: bool = False, with_termini: bool = False) -> dict:
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
        centroid_offset,
        load_segid_chain_map,
        md_rigid_reference,
        md_snap_mask,
    )

    model = build_atomistic_model(design)
    cm = build_chain_map(model)

    paths = [str(p) for p in trajectory_paths]
    u = mda.Universe(str(topology_path), paths if len(paths) > 1 else paths[0])
    # NOTE: no whole-system ``mda_unwrap`` transformation.  It make-wholes ALL ~1 M
    # atoms (incl. solvent) on EVERY frame seek — ~180 s/frame for a solvated origami,
    # the dominant cost of the flex map / trajectory.  It is redundant here: both
    # per-frame extractors already reconstruct DNA positions from the RAW (wrapped)
    # coordinates — the bead path via the vectorised ``_unwrap_min_image`` + the
    # design-equilibrium minimum-image correction, and the heavy-atom path via
    # residue-local ``minimum_image(atom − its P)``.  The only thing the global unwrap
    # affected was the P→C1' base-normal vector for a nucleotide split across a
    # periodic boundary, which ``_extract_md_nadoc_frame`` now handles with a direct
    # minimum-image on that 2-atom vector.  (Equivalence to the unwrapped path is
    # asserted to ~1e-8 nm by test_md_extraction_matches_unwrap_reference, gated on
    # NADOC_RUN_HEAVY_MD_FIXTURE since the reference side pays the ~180 s/frame unwrap.)

    # P-order = the design (helix, bp, dir) key per trajectory DNA P atom.
    n_dna_p = len(u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES)))
    p_order, p_order_source = _select_p_order(
        u, cm, Path(topology_path).parent, coordinate_path)

    # Equilibrium P-atom reference + rigid mask for the Kabsch alignment (shared with
    # the live-display ws handler; handles crossover extra-base "__xb__" inserts).
    eq_positions, eq_valid, rigid_mask = md_rigid_reference(model, p_order)
    # snap_mask = rigid dsDNA PLUS crossover extra-base (__xb__) + extension (__ext_) inserts:
    # the atoms that get the design-eq nearest-image PBC snap so a strand-boundary reset in the
    # sequential unwrap can't strand one a full box away (the "few bases wrapped" bug — visible on
    # extra-crossover-base designs whose 676 unpaired ssDNA inserts hang out one side of the box).
    # Mirrors ws.py's live path (:849); for a plain dsDNA run it EQUALS rigid_mask (no synthetics),
    # so the trajectory output is byte-identical for standard designs.
    snap_mask = md_snap_mask(p_order, eq_valid, rigid_mask)
    if int(rigid_mask.sum()) < 3:
        eq_centroid = np.zeros(3)
        eq_centered = None
    else:
        eq_centroid = eq_positions[rigid_mask].mean(axis=0)
        eq_centered = eq_positions - eq_centroid
        eq_centered[~rigid_mask] = 0.0

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
        # Design identity (strand/helix/bp/direction) rides along with each atom so the
        # trajectory-frame and surface views colour by strand like the design's own
        # atoms do; without it they are stuck on CPK.  Cosmetic — never fail a frame
        # extraction over it.
        from backend.core.atomistic_to_nadoc import build_atom_design_meta
        try:
            ident = build_atom_design_meta(
                u, dna_heavy, p_order, model, cm, load_segid_chain_map(Path(topology_path).parent))
        except Exception:  # noqa: BLE001
            ident = None
        atom_meta = [{"serial": int(a.index), "element": _element(a),
                      **(ident[i] if ident else {})}
                     for i, a in enumerate(dna_heavy)]

    # 5'-terminal nucleotides (one per strand) have NO phosphate — pdb2gmx strips the
    # 5' P — so they are absent from the P-indexed p_order and go un-positioned/un-coloured
    # in the flexibility map.  Recover each via its O5' atom, placed in the aligned frame
    # off its 3'-neighbour's P (which IS in p_order): O5'_aligned = neighbourP_aligned +
    # R·minimage(O5'_raw − neighbourP_raw), exact under the rigid transform.  Only built on
    # demand (md_rmsf) so the metrics / live-display P path is byte-unchanged.
    term_specs: list[tuple] = []
    if with_termini:
        from backend.core.atomistic_to_nadoc import (
            build_termini_specs,
            load_segid_chain_map,
        )
        seg2chain = load_segid_chain_map(Path(topology_path).parent)
        term_specs = build_termini_specs(u, cm, seg2chain, p_order)

    return {
        "universe": u, "p_order": p_order, "n_frames": n_frames,
        "centroid_T": T, "eq_positions": eq_positions, "eq_valid": eq_valid,
        "rigid_mask": rigid_mask, "snap_mask": snap_mask,
        "eq_centroid": eq_centroid, "eq_centered": eq_centered,
        "c1p_idx": c1p_idx, "heavy_idx": heavy_idx, "atom_meta": atom_meta,
        "R_prev": None, "prev_frame_idx": -999,
        "n_dna_p": n_dna_p, "p_order_source": p_order_source,
        "term_specs": term_specs,
    }


def _extract_md_nadoc_frame(ctx: dict, frame_idx: int, with_c1p: bool = False,
                            with_termini: bool = False):
    """Per-frame DNA P-atom positions (nm, NADOC frame) + base normals for one DCD
    frame. Ported from ws.py ``_seek_sync`` (nadoc path). Returns ``(p_nm, normals)``
    where ``p_nm`` is (N,3) and ``normals`` is (N,3) or ``None``.

    ``with_c1p=True`` additionally returns the per-nucleotide **aligned C1' positions**
    (nm, same NADOC frame as ``p_nm``) as a third element — the sugar-ring anchor used
    as a native Watson-Crick base-pairing proxy (C1'…C1' distance) by
    :func:`md_metric_series`.  It is the P position plus the (min-imaged, Kabsch-rotated)
    P→C1' vector already computed for the base normal, so it costs nothing extra."""
    from backend.core.atomistic_to_nadoc import (
        _GRO_DNA_RESNAMES, _unwrap_min_image, reassemble_to_posed_reference)

    u = ctx["universe"]
    p_order = ctx["p_order"]
    T = ctx["centroid_T"]
    eq_pos = ctx["eq_positions"]
    eq_valid = ctx["eq_valid"]
    rigid_mask = ctx["rigid_mask"]
    snap_mask = ctx.get("snap_mask")
    if snap_mask is None:      # older ctx (pre-snap-mask) → fall back to rigid-only restore
        snap_mask = rigid_mask
    eq_centered = ctx["eq_centered"]
    eq_centroid = ctx["eq_centroid"]

    u.trajectory[frame_idx]
    dna_p = u.select_atoms("name P and resname " + " ".join(_GRO_DNA_RESNAMES))
    p_raw = dna_p.positions / 10.0
    dims = u.dimensions

    if dims is not None and dims[0] > 0:
        box_nm = dims[:3] / 10.0
        p_box = _unwrap_min_image(p_raw, box_nm)
        # POSE-FIRST PBC reassembly — mirror ws.py's live path (:657).  The old translation-
        # only design-eq snap placed the reference by shifting the design centroid to the box
        # centroid, WITHOUT rotating it, then nearest-image-snapped every atom.  When the box
        # frame differs from the design frame by a rotation (this 24hb run sits ~180° flipped
        # in its solvation box) the rod ends land > L/2 from their un-rotated reference and the
        # snap grabs the WRONG periodic image → the whole structure streaks a full box across
        # the viewer.  reassemble_to_posed_reference estimates the rigid pose FIRST, poses the
        # design reference into the box frame, then snaps — so every bead's reference sits
        # beside its true position.  Free ssDNA (~snap_mask) keeps its sequential-unwrap spot.
        if (eq_pos is not None and eq_centroid is not None
                and snap_mask is not None and len(eq_pos) == len(p_box)):
            p_box_corr, _c_box = reassemble_to_posed_reference(
                p_box, box_nm, eq_pos, eq_centroid, rigid_mask, snap_mask)
            _T_dyn = eq_centroid - _c_box
            p_nm = p_box_corr + _T_dyn
        else:
            if rigid_mask is not None and rigid_mask.any():
                _c_box = np.median(p_box[rigid_mask], axis=0)
            else:
                _c_box = p_box.mean(axis=0)
            _T_dyn = eq_centroid - _c_box if eq_centroid is not None else T
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
    c1p_nm = None
    if c1p_idx is not None and np.all(c1p_idx >= 0) and len(c1p_idx) == len(p_order):
        c1p_raw = u.atoms[c1p_idx].positions / 10.0
        dn = c1p_raw - p_raw
        # Minimum-image the intra-nucleotide P→C1' vector: without the (removed)
        # whole-system unwrap a residue straddling a periodic boundary would give a
        # box-length spurious dn.  P and C1' are ~0.5 nm apart, so the nearest image
        # is always the true bond.  On already-whole coords this is a no-op.
        if dims is not None and dims[0] > 0:
            box_nm = dims[:3] / 10.0
            for _d in range(3):
                if box_nm[_d] > 0:
                    dn[:, _d] -= np.round(dn[:, _d] / box_nm[_d]) * box_nm[_d]
        if R_align is not None:
            dn = dn @ R_align.T
        # Aligned C1' = aligned P + the rotated P→C1' vector (same frame as p_nm).
        c1p_nm = p_nm + dn
        norms = np.linalg.norm(dn, axis=1, keepdims=True)
        norms = np.where(norms > 1e-6, norms, 1.0)
        normals = dn / norms

    # 5'-terminal nucleotides via their O5' atom, placed off the aligned 3'-neighbour P.
    if with_termini:
        from backend.core.atomistic_to_nadoc import recover_termini
        _box = (dims[:3] / 10.0) if (dims is not None and dims[0] > 0) else None
        term_pos, term_norm = recover_termini(
            u, ctx.get("term_specs") or [], p_raw, p_nm, R_align, _box)
        if with_c1p:
            return p_nm, normals, c1p_nm, term_pos, term_norm
        return p_nm, normals, term_pos, term_norm

    if with_c1p:
        return p_nm, normals, c1p_nm
    return p_nm, normals


def _build_heavy_anchor_rows(heavy_ag, dna_p) -> "np.ndarray":
    """For each heavy atom, the ROW in ``dna_p`` whose P anchors its residue-local
    reconstruction (-1 when none can be found).

    Pure topology — residue index first, then a nearby resid in the same segment (a 5'
    terminal residue has no P of its own; psfgen strips it), then the nearest resid in
    that segment. Identical every frame, so it is built once per context.

    Ties resolve LAST-wins, matching the dict-comprehension this replaced: a residue
    carrying more than one P must keep addressing the same one as before.
    """
    p_row_by_res: dict[int, int] = {}
    p_row_by_key: dict[tuple[str, int], int] = {}
    p_resids_by_seg: dict[str, list[int]] = {}
    for row, a in enumerate(dna_p):
        res_ix = int(a.residue.ix)
        segid = str(getattr(a.residue, "segid", "") or getattr(a, "segid", ""))
        resid = int(a.residue.resid)
        p_row_by_res[res_ix] = row
        p_row_by_key[(segid, resid)] = row
        p_resids_by_seg.setdefault(segid, []).append(resid)
    for segid in p_resids_by_seg:
        p_resids_by_seg[segid].sort()

    def _row_for(atom) -> int:
        row = p_row_by_res.get(int(atom.residue.ix))
        if row is not None:
            return row
        segid = str(getattr(atom.residue, "segid", "") or getattr(atom, "segid", ""))
        resid = int(atom.residue.resid)
        for delta_resid in (1, -1, 2, -2):
            near = p_row_by_key.get((segid, resid + delta_resid))
            if near is not None:
                return near
        candidates = p_resids_by_seg.get(segid)
        if candidates:
            nearest = min(candidates, key=lambda r: abs(r - resid))
            near = p_row_by_key.get((segid, nearest))
            if near is not None:
                return near
        return -1

    return np.fromiter((_row_for(a) for a in heavy_ag), dtype=np.int64,
                       count=len(heavy_ag))


def _extract_md_atoms_frame(ctx: dict, frame_idx: int,
                            frame_out: dict | None = None) -> list[dict]:
    """DNA heavy-atom coordinates (nm, NADOC frame) for one DCD frame, as
    ``[{serial, element, strand_id, helix_id, bp_index, direction, x, y, z}, …]``.
    Ported from ws.py ``_seek_sync`` (ballstick
    path): residue-local reconstruction of each heavy atom relative to its corrected
    P atom, then the same Kabsch alignment as the bead path so the all-atom and CG
    views coincide. Requires a ctx built with ``with_atoms=True``.

    Pass ``frame_out`` (an empty dict) to also receive this frame's DISPLAY AFFINE
    and the raw/pre heavy-atom positions it was applied to — what the solvent and
    periodic-box overlays need in order to land in the same frame as the DNA.  The
    return value is unchanged, so every existing caller is unaffected.  Solvent code
    must take the transform from here rather than recompute it: a second copy of
    this arithmetic is how the PBC-snap fix once shipped without changing anything
    on screen (see memory/project_md_viz_tools.md).
    """
    from backend.core.atomistic_to_nadoc import (
        _GRO_DNA_RESNAMES, _unwrap_min_image, reassemble_to_posed_reference)

    u = ctx["universe"]
    p_order = ctx["p_order"]
    T = ctx["centroid_T"]
    heavy_idx = ctx["heavy_idx"]
    atom_meta = ctx["atom_meta"]
    eq_pos = ctx["eq_positions"]
    rigid_mask = ctx["rigid_mask"]
    snap_mask = ctx.get("snap_mask")
    if snap_mask is None:      # older ctx (pre-snap-mask) → fall back to rigid-only restore
        snap_mask = rigid_mask
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
            # POSE-FIRST PBC reassembly — same fix as the bead path (mirror ws.py :657): pose
            # the design reference into the (possibly ~180°-rotated) box frame BEFORE the
            # nearest-image snap, else a large rotated bundle's rod ends get mis-imaged a full
            # box away.  Free ssDNA (~snap_mask) keeps its sequential-unwrap position.
            if (eq_pos is not None and eq_centroid is not None
                    and snap_mask is not None and len(eq_pos) == len(p_box)):
                p_box_corr, c_box = reassemble_to_posed_reference(
                    p_box, box_nm, eq_pos, eq_centroid, rigid_mask, snap_mask)
                T_dyn = eq_centroid - c_box
                p_pre = p_box_corr + T_dyn
            else:
                if rigid_mask is not None and rigid_mask.any():
                    c_box = np.median(p_box[rigid_mask], axis=0)
                else:
                    c_box = p_box.mean(axis=0)
                T_dyn = eq_centroid - c_box if eq_centroid is not None else T
                p_pre = p_box + T_dyn

            # Residue-local reconstruction: heavy atom = corrected P +
            # minimum-image(raw atom − raw P), anchored to each residue's P.
            #
            # Which P anchors which heavy atom is a TOPOLOGY question (residue ix, segid,
            # resid) — identical for every frame of the run. Resolving it per frame meant
            # ~302 k MDAnalysis `.residue` lookups each time, which profiling showed was
            # the bulk of a 2.25 s frame. Build it ONCE per context and reuse.
            anchor_rows = ctx.get("_heavy_anchor_rows")
            if anchor_rows is None:
                anchor_rows = _build_heavy_anchor_rows(ag, dna_p)
                ctx["_heavy_anchor_rows"] = anchor_rows

            pos_pre = pos_nm.copy()
            have = anchor_rows >= 0
            if have.any():
                rows = anchor_rows[have]
                # Vectorized min-image: one array op instead of 3 scalar np.round calls
                # per atom (906 k of them per frame on a 300 k-atom system).
                delta = pos_raw[have] - p_raw[rows]
                box = np.asarray(box_nm, dtype=float)
                good = box > 0
                if good.any():
                    delta[:, good] -= np.round(delta[:, good] / box[good]) * box[good]
                pos_pre[have] = p_pre[rows] + delta

            mob_c = None
            R_align = None
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

            if frame_out is not None:
                # The affine THIS frame's DNA actually rode, handed over rather
                # than re-derived downstream. When the Kabsch branch was skipped
                # the display frame IS the pre frame, so mob_c/eq_centroid/R are
                # left at the identity.
                frame_out.update(
                    pos_raw=pos_raw, pos_pre=pos_pre, box_nm=box_nm,
                    T_dyn=T_dyn, c_box=c_box, mob_c=mob_c, R_align=R_align,
                    eq_centroid=eq_centroid if R_align is not None else None,
                )
    except Exception:
        pass

    # strand_id/helix_id/bp_index/direction come from the ctx's atom_meta (static across
    # frames) — the frontend colours by them exactly as it does the design's own atoms.
    return [
        {"serial": m["serial"], "element": m["element"],
         "strand_id": m.get("strand_id", ""), "helix_id": m.get("helix_id", ""),
         "bp_index": m.get("bp_index", -1), "direction": m.get("direction", ""),
         "x": float(pos_nm[i, 0]), "y": float(pos_nm[i, 1]), "z": float(pos_nm[i, 2])}
        for i, m in enumerate(atom_meta)
    ]


class _SurfAtom:
    """Minimal atom for compute_surface (reads .x/.y/.z/.element + .strand_id)."""
    __slots__ = ("x", "y", "z", "element", "strand_id")

    def __init__(self, x, y, z, element, strand_id=""):
        self.x = x; self.y = y; self.z = z; self.element = element
        self.strand_id = strand_id


def composite_raw_frame_map(segments, max_frames: int = 200,
                            stride: int | None = None) -> list[int]:
    """Composite frame index → RAW (concatenated-universe) frame index.

    The bead trajectory the user scrubs is DOWNSAMPLED, so its frame 12 is not the
    universe's frame 12.  Anything that renders "the same frame" a different way —
    the per-frame heavy atoms and surface — has to translate first, or the atomistic
    view silently shows a different point in the run than the beads next to it.
    Reads DCD headers only (no coordinates), and takes the SAME ``max_frames``/
    ``stride`` the trajectory was built with, since a frame index only means the same
    thing within one downsample."""
    from MDAnalysis.coordinates.DCD import DCDReader  # type: ignore

    counts = []
    for _name, _kind, dcd in segments:
        try:
            counts.append(len(DCDReader(str(dcd))))
        except Exception:
            counts.append(0)
    return [g for seg in _composite_indices(counts, max_frames, stride) for g in seg]


def heavy_bond_pairs(u, heavy_indices, *, nested: bool = False):
    """Topology bonds restricted to the heavy atoms the ball-and-stick view draws.

    Ends are the universe-global ``Atom.index`` — the SAME serial space ``atom_meta``
    uses — so the frontend resolves each through the serial→row map it already builds.
    Bonds with an endpoint outside the heavy subset (every X–H bond) are dropped: those
    atoms are not in the atom table, so the renderer would discard them anyway.

    ``nested`` picks the wire shape, and the two consumers genuinely differ:

    * ``False`` → flat ``[i0, j0, i1, j1, …]``. The live WS stream, whose frontend runs
      it through ``md_display_state.toBondPairs`` into a typed array. Flat saves ~30 % of
      the JSON, which matters at ~325 k pairs.
    * ``True``  → nested ``[[i, j], …]``. The REST model, which is handed straight to
      ``atomistic_renderer._rebuild``. That reader treats a **plain** array as nested and
      only a **typed** array as flat, so a flat plain list would be silently misparsed
      into no bonds at all.

    Returns None when the topology carries no bonds (GRO files don't), leaving the
    display exactly as it was: spheres, no sticks.

    Single owner for both callers on purpose — ``ws.py`` delegates here. The serial space
    has to match ``atom_meta`` exactly, and two copies of that rule drift.
    """
    try:
        idx = u.bonds.to_indices()      # raises NoDataError when there is no bond data
    except Exception:  # noqa: BLE001
        return None
    if idx is None or len(idx) == 0:
        return None
    in_heavy = np.zeros(len(u.atoms), dtype=bool)
    in_heavy[np.asarray(heavy_indices, dtype=np.int64)] = True
    keep = in_heavy[idx[:, 0]] & in_heavy[idx[:, 1]]
    if not keep.any():
        return None
    kept = np.asarray(idx[keep], dtype=np.int32)
    return kept.tolist() if nested else kept.ravel().tolist()


def md_atomistic_model(topology_path, segments, coordinate_path, design) -> dict:
    """The NAMD job's STATIC heavy-atom set → ``{atoms, bonds, n_serials}``.

    Atom identity (serial/element/strand/helix/bp/direction) does not change frame to
    frame, so the display fetches it ONCE and then streams coordinates only.  Sending it
    per frame is what made an all-atom trajectory unaffordable: 302 k atoms as JSON
    objects is ~53 MB and ~72 MB of JavaScript objects *per frame*, against 5.4 MB for
    the same frame's coordinates alone.

    ``n_serials`` = max serial + 1, i.e. the length a serial-indexed position array must
    have.  MD serials are the atom's index in the whole SOLVATED universe, so they are
    sparse (302 197 heavy atoms spread over 0…469 349) — the gaps cost ~1.5x memory and
    are worth it: ``applyPositionLerp`` indexes by serial, so renumbering would have to
    stay in lockstep with every other MD atom path.

    Positions are frame 0's, so the model alone renders a valid structure."""
    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_atoms=True)
    atoms = _extract_md_atoms_frame(ctx, 0) if ctx["n_frames"] > 0 else []
    n_serials = (max((int(a["serial"]) for a in atoms), default=-1) + 1)
    # Bonds, NESTED — see heavy_bond_pairs: this payload is handed straight to
    # atomistic_renderer._rebuild, which reads a plain array as [[i, j], …] and only a
    # TYPED array as flat, so flat-plain would silently render as no sticks at all.
    bonds = None
    if atoms and ctx.get("heavy_idx") is not None:
        try:
            bonds = heavy_bond_pairs(ctx["universe"], ctx["heavy_idx"], nested=True)
        except Exception:  # noqa: BLE001 - never fail the model over sticks
            bonds = None
    # The scrub view DOES serve sticks now (2026-07-31). It used to return bonds: [] with
    # a note to port ws.py's version "when the scrub view needs sticks" — which is exactly
    # what watching the CPD weld overlay on a finished run needs.
    #
    # bonds_available is a DECLARATION, not just "is the list non-empty": it tells the
    # display there is nothing more to fetch, so flipping vdw→ball-and-stick doesn't
    # re-run this ~30 s reconstruction hunting for bonds that were never going to arrive.
    # A topology with no bond records at all (GRO) still declares False and renders as
    # spheres, which is the honest answer rather than a spinner.
    return {"atoms": atoms, "bonds": bonds or [], "bonds_available": bool(bonds),
            "n_serials": n_serials, "n_atoms": len(atoms)}


def md_frames_atomistic(topology_path, segments, coordinate_path, design,
                        frame_indices, max_frames: int = 200,
                        stride: int | None = None,
                        positions_only: bool = False) -> dict:
    """Per-frame DNA heavy atoms for the given COMPOSITE-trajectory frame indices →
    ``{ "<idx>": {atoms:[{serial,element,strand_id,helix_id,bp_index,direction,x,y,z}],
    bonds:[]} }``. The atom set is the
    NAMD model's own DNA heavy atoms (Phase 2b renders these directly rather than
    mapping onto the design's idealized template).

    Keys are the caller's COMPOSITE indices; the frame each one reads is translated
    through :func:`composite_raw_frame_map`, so pass the same ``stride`` the
    trajectory was loaded with.

    ``positions_only`` switches to the form an all-atom trajectory can actually afford:
    ``{ "<idx>": [x0,y0,z0, …] }`` indexed by SERIAL (gaps zero-filled), to be paired
    with one :func:`md_atomistic_model` fetch.  ~10x smaller on the wire and no
    per-frame JavaScript objects at all — see that function's note on the arithmetic.

    Batching many indices into ONE call matters: the context build (PSF parse + model)
    costs ~32 s on a 300 k-atom system against ~2.8 s per additional frame, and it is
    paid once per CALL, not once per frame."""
    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_atoms=True)
    n = ctx["n_frames"]
    raw_of = composite_raw_frame_map(segments, max_frames, stride)
    n_serials = 0
    if positions_only:
        n_serials = max((int(m["serial"]) for m in (ctx.get("atom_meta") or [])),
                        default=-1) + 1
    out: dict[str, object] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= len(raw_of):
            continue
        gidx = raw_of[idx]
        if gidx >= n:
            continue
        atoms = _extract_md_atoms_frame(ctx, gidx)
        if positions_only:
            flat = [0.0] * (n_serials * 3)
            for a in atoms:
                s = int(a["serial"]) * 3
                flat[s] = round(a["x"], 4)
                flat[s + 1] = round(a["y"], 4)
                flat[s + 2] = round(a["z"], 4)
            out[str(idx)] = flat
        else:
            out[str(idx)] = {"atoms": atoms, "bonds": []}
    return out


def md_frames_solvent(topology_path, segments, coordinate_path, design,
                      frame_indices, max_frames: int = 200,
                      stride: int | None = None, opts: dict | None = None) -> bytes:
    """Per-frame explicit solvent + periodic cell for COMPOSITE frame indices, as one
    binary blob (see :func:`backend.core.md_solvent.pack_solvent_bin`).

    Whole-box atomistic water on a large job is millions of numbers per frame, so
    this route is binary rather than JSON — a Float32 view onto the transferred
    buffer instead of a ``JSON.parse`` that materialises a JS number array first.

    ``opts`` mirrors the request body: ``water``/``ions``/``box`` toggles,
    ``shell_ang`` (None ⇒ the whole cell), ``atomistic``, ``max_waters`` and
    ``include_dna``.  With ``include_dna`` the payload also carries the
    serial-indexed DNA coordinates in the ``md_frames_atomistic(positions_only=True)``
    shape — the context build is ~30 s and is paid PER REQUEST (killable subprocess),
    so an atomistic-rep scrub must not pay it twice for the same frames.

    The display affine comes from :func:`_extract_md_atoms_frame`'s ``frame_out``;
    it is never recomputed here."""
    from backend.core.md_solvent import (
        DisplayXform, build_solvent_ctx, empty_solvent_bin, pack_solvent_bin,
    )

    o = dict(opts or {})
    shell_ang = o.get("shell_ang", 5.0)
    include_dna = bool(o.get("include_dna"))

    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_atoms=True)
    u = ctx["universe"]
    sctx = build_solvent_ctx(u)
    n = ctx["n_frames"]
    raw_of = composite_raw_frame_map(segments, max_frames, stride)

    n_serials = 0
    if include_dna:
        n_serials = max((int(m["serial"]) for m in (ctx.get("atom_meta") or [])),
                        default=-1) + 1

    frames: dict[int, dict] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= len(raw_of):
            continue
        gidx = raw_of[idx]
        if gidx >= n:
            continue
        fo: dict = {}
        atoms = _extract_md_atoms_frame(ctx, gidx, frame_out=fo)
        if not fo:
            continue                    # no periodic box on this frame → nothing to draw
        xf = DisplayXform.build(
            T_dyn=fo["T_dyn"], c_box=fo["c_box"], box_nm=fo["box_nm"],
            mob_c=fo["mob_c"], eq_centroid=fo["eq_centroid"], R=fo["R_align"])
        frames[idx] = extract_solvent_frame_for(
            u, sctx, fo, xf,
            water=bool(o.get("water", True)), ions=bool(o.get("ions", True)),
            box=bool(o.get("box", True)),
            shell_nm=None if shell_ang is None else float(shell_ang) / 10.0,
            atomistic=bool(o.get("atomistic")),
            max_waters=o.get("max_waters"))
        if include_dna:
            flat = np.zeros(n_serials * 3, dtype=np.float32)
            for a in atoms:
                s = int(a["serial"]) * 3
                flat[s] = a["x"]; flat[s + 1] = a["y"]; flat[s + 2] = a["z"]
            frames[idx]["dna"] = flat

    if not frames:
        return empty_solvent_bin()
    return pack_solvent_bin(frames, meta={"n_serials": n_serials} if include_dna else None)


def extract_solvent_frame_for(u, sctx, frame_out: dict, xf, **kw) -> dict:
    """Thin adapter: hand :func:`md_solvent.extract_solvent_frame` the DNA anchor
    arrays that ``_extract_md_atoms_frame``'s ``frame_out`` already carries."""
    from backend.core.md_solvent import extract_solvent_frame

    return extract_solvent_frame(
        u, sctx, frame_out["pos_raw"], frame_out["pos_pre"], xf, **kw)


def md_frames_surface(topology_path, segments, coordinate_path, design, frame_indices,
                      probe_radius: float = 0.28, grid_spacing: float = 0.20,
                      radius_inflate: float = 1.30, smooth: int = 15,
                      max_frames: int = 200, stride: int | None = None,
                      **_ignore) -> dict:
    """Per-frame molecular surface from the NAMD DNA heavy atoms → surface-batch
    shape ``{ "<idx>": {vertices, faces} }`` (uniform colour for v1).  Indices are
    COMPOSITE, translated like md_frames_atomistic's."""
    from backend.core.surface import compute_surface, smooth_mesh

    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_atoms=True)
    n = ctx["n_frames"]
    raw_of = composite_raw_frame_map(segments, max_frames, stride)
    out: dict[str, dict] = {}
    for idx in sorted(set(int(i) for i in frame_indices)):
        if idx < 0 or idx >= len(raw_of):
            continue
        gidx = raw_of[idx]
        if gidx >= n:
            continue
        atoms = [_SurfAtom(a["x"], a["y"], a["z"], a["element"], a.get("strand_id", ""))
                 for a in _extract_md_atoms_frame(ctx, gidx)]
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
    # with_termini: also recover each strand's 5'-terminal base (no P atom → absent from
    # p_order) so the flexibility map positions + colours every nucleotide, not only the
    # P-bearing ones.  Only md_rmsf opts in — the metrics / live-display P path is unchanged.
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_termini=True)
    p_order = ctx["p_order"]
    n = ctx["n_frames"]
    n_keys = len(p_order)
    n_dna_p = ctx.get("n_dna_p", n_keys)
    if n <= 0 or n_keys == 0:
        return {"ready": False, "n_frames": 0, "positions": [],
                "reason": "no trajectory frames or no mapped nucleotides"}

    idxs = list(range(n)) if n <= max_frames else _stride_pick(list(range(n)), max_frames)

    term_specs = ctx.get("term_specs") or []
    n_term = len(term_specs)

    # One-pass accumulation: RMSF^2 = mean_f|p_f|^2 - |mean_f p_f|^2 (per nucleotide).
    sum_pos = np.zeros((n_keys, 3))
    sum_sq = np.zeros(n_keys)        # Σ_f |p_f|^2
    sum_norm = np.zeros((n_keys, 3))
    sum_tpos = np.zeros((n_term, 3))
    sum_tsq = np.zeros(n_term)
    sum_tnorm = np.zeros((n_term, 3))
    have_norm = False
    used = 0
    for gidx in idxs:
        p_nm, normals, tpos, tnorm = _extract_md_nadoc_frame(ctx, gidx, with_termini=True)
        if p_nm is None or len(p_nm) != n_keys:
            continue
        sum_pos += p_nm
        sum_sq += np.einsum("ij,ij->i", p_nm, p_nm)
        if normals is not None and len(normals) == n_keys:
            sum_norm += normals
            have_norm = True
        if n_term and tpos is not None and len(tpos) == n_term:
            sum_tpos += tpos
            sum_tsq += np.einsum("ij,ij->i", tpos, tpos)
            sum_tnorm += tnorm
        used += 1
    if used == 0:
        reason = "no usable trajectory frames"
        if n_dna_p != n_keys:
            reason = (
                f"design/topology atom mismatch: the loaded design maps {n_keys} "
                f"nucleotides but the simulated structure has {n_dna_p} DNA phosphate "
                f"atoms (P-order source: {ctx.get('p_order_source', '?')}). Load the "
                "design this job was prepared from."
            )
        return {"ready": False, "n_frames": 0, "positions": [], "reason": reason}

    mean_pos = sum_pos / used
    msd = sum_sq / used - np.einsum("ij,ij->i", mean_pos, mean_pos)
    rmsf = np.sqrt(np.maximum(msd, 0.0))

    if have_norm:
        nrm = np.linalg.norm(sum_norm, axis=1, keepdims=True)
        mean_norm = sum_norm / np.where(nrm > 1e-6, nrm, 1.0)
    else:
        mean_norm = np.tile([0.0, 0.0, 1.0], (n_keys, 1))

    positions = []
    for i, key in enumerate(p_order):
        hid, bp, direction = key[0], key[1], key[2]
        copy = key[3] if len(key) > 3 else 0   # loop-insertion copy index (0 = base)
        positions.append({
            "helix_id": hid,
            "bp_index": bp,
            "direction": direction,
            "copy": copy,
            "backbone_position": [float(mean_pos[i, 0]), float(mean_pos[i, 1]),
                                  float(mean_pos[i, 2])],
            "nx": float(mean_norm[i, 0]),
            "ny": float(mean_norm[i, 1]),
            "nz": float(mean_norm[i, 2]),
            "rmsf": float(rmsf[i]),
        })

    # Append the recovered 5'-terminal nucleotides (same payload shape, real keys).
    rmsf_all = rmsf
    if n_term:
        mean_t = sum_tpos / used
        rmsf_t = np.sqrt(np.maximum(sum_tsq / used - np.einsum("ij,ij->i", mean_t, mean_t), 0.0))
        tn = np.linalg.norm(sum_tnorm, axis=1, keepdims=True)
        mean_tnorm = sum_tnorm / np.where(tn > 1e-6, tn, 1.0)
        for j, (key, *_rest) in enumerate(term_specs):
            positions.append({
                "helix_id": key[0],
                "bp_index": key[1],
                "direction": key[2],
                "copy": key[3] if len(key) > 3 else 0,   # 5'-termini are base copies (0)
                "backbone_position": [float(mean_t[j, 0]), float(mean_t[j, 1]),
                                      float(mean_t[j, 2])],
                "nx": float(mean_tnorm[j, 0]),
                "ny": float(mean_tnorm[j, 1]),
                "nz": float(mean_tnorm[j, 2]),
                "rmsf": float(rmsf_t[j]),
            })
        rmsf_all = np.concatenate([rmsf, rmsf_t]) if len(rmsf_t) else rmsf

    return {
        "ready": True,
        "n_frames": used,
        "positions": positions,
        "min_rmsf": float(rmsf_all.min()),
        "max_rmsf": float(rmsf_all.max()),
        "mean_rmsf": float(rmsf_all.mean()),
    }


# Native-MD Watson-Crick pairing cutoff: two designed-partner nucleotides count as
# "paired" when their C1'…C1' distance is within this (nm).  The MD codebase uses the
# calibrated C1' distance as the primary base-pairing metric (WC heavy-atom distances
# are ~25% inflated by the idealized build templates — see feedback_wc_calibration), so
# the MD "Graphs and Metrics" base-pairing series is a C1'…C1' fraction, not the oxDNA
# base-site fraction.  ``C1_PAIRED_MAX_DEFAULT`` is 12.0 Å; here in nm.
from backend.core.md_health import C1_PAIRED_MAX_DEFAULT as _C1_PAIRED_MAX_ANG  # noqa: E402
MD_BP_CUTOFF_NM = _C1_PAIRED_MAX_ANG / 10.0


def count_md_frames(segments) -> int:
    """Total DCD frame count across every segment (DCD header only, no coordinate
    read) — sizes the "Graphs and Metrics" ETA/progress bar without a full parse.
    Mirrors :func:`oxdna_health.count_trajectory_frames` for the MD side."""
    from MDAnalysis.coordinates.DCD import DCDReader  # type: ignore

    total = 0
    for _name, _kind, dcd in segments:
        if not Path(dcd).exists():
            continue
        try:
            total += len(DCDReader(str(dcd)))
        except Exception:
            pass
    return total


def md_metric_series(topology_path, segments, coordinate_path, design,
                     analytic_reference, *, n_slices: int = 0, on_frame=None) -> dict:
    """SINGLE-PASS per-frame twist, curvature AND base-pairing over a NAMD run — the
    MD analogue of :func:`oxdna_health.production_metric_series`, and the compute behind
    the MD "Graphs and Metrics" card.

    Reads every written DCD frame ONCE (the frame seek + DNA reconstruction dominates
    the cost) and, per frame, measures: differential bundle twist and curvature
    (``measure_bundle_* − analytic``) on the reference dsDNA core, and the base-pairing
    fraction — the fraction of designed (helix, bp) columns whose FORWARD/REVERSE C1'
    atoms are within :data:`MD_BP_CUTOFF_NM` (the native MD WC proxy; oxDNA uses a base-
    site distance instead, so the two engines' pairing curves are comparable in *trend*
    but not in absolute cutoff).  Twist/curvature geometry reuses the engine-agnostic
    ``oxdna_health`` bundle measures verbatim; only the frame source (NAMD PSF/DCD via
    ``_extract_md_nadoc_frame``) and the pairing metric (C1'…C1') differ.

    Accumulates the time-mean structure for the spatial twist/curvature profiles (made
    differential vs the analytic profiles) and each pair's formed-frame count for the
    base-pairing spatial profile.  ``on_frame()`` fires once per measured frame so a
    caller can drive an ETA bar.  Returns the SAME payload shape as
    ``production_metric_series`` (per-metric ``{temporal, spatial}``); ``ready`` is
    False on no frames / fewer than two helices / an unmappable topology."""
    from backend.core.oxdna_health import (
        _filter_to_reference_core,
        base_pairing_spatial_profile,
        differential_profile,
        measure_bundle_curvature,
        measure_bundle_curvature_profile,
        measure_bundle_twist,
        measure_bundle_twist_profile,
        twist_series_stats,
    )

    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design)
    p_order = ctx["p_order"]
    n = ctx["n_frames"]
    if n <= 0 or not p_order:
        return {"ready": False, "n_frames": 0}
    keys = [(k[0], k[1], k[2]) for k in p_order]
    n_keys = len(keys)

    analytic_twist = measure_bundle_twist(analytic_reference, n_slices=n_slices)
    analytic_curv = measure_bundle_curvature(analytic_reference, n_slices=n_slices)

    # FORWARD/REVERSE index of each designed (helix, bp) column, for the C1' pairing test.
    fwd_idx = {(k[0], k[1]): i for i, k in enumerate(keys) if k[2] == "FORWARD"}
    rev_idx = {(k[0], k[1]): i for i, k in enumerate(keys) if k[2] == "REVERSE"}
    designed = sorted(set(fwd_idx) & set(rev_idx))
    n_designed = len(designed)

    twist_pf: list[float] = []
    curv_pf: list[float] = []
    bp_pf: list[float] = []
    acc: dict[tuple, list] = {}                 # key → [bb xyz, …] for the mean structure
    formed: dict[tuple, int] = {}               # (helix,bp) → frames the pair was within cutoff
    total_pair: dict[tuple, int] = {}           # (helix,bp) → frames the pair was measured
    n_frames = 0
    for idx in range(n):
        p_nm, _normals, c1p_nm = _extract_md_nadoc_frame(ctx, idx, with_c1p=True)
        if p_nm is None or len(p_nm) != n_keys:
            continue
        frame_positions = []
        for i, key in enumerate(keys):
            bb = p_nm[i]
            frame_positions.append({"helix_id": key[0], "bp_index": key[1],
                                    "direction": key[2], "backbone_position": bb})
            acc.setdefault(key, []).append(bb)
        core = _filter_to_reference_core(frame_positions, analytic_reference)
        try:
            twist_pf.append(measure_bundle_twist(core, n_slices=n_slices) - analytic_twist)
            curv_pf.append(measure_bundle_curvature(core, n_slices=n_slices) - analytic_curv)
        except ValueError:
            continue                            # degenerate frame (too few helices) — skip
        if c1p_nm is not None and designed:
            n_formed = 0
            for hb in designed:
                d = float(np.linalg.norm(c1p_nm[fwd_idx[hb]] - c1p_nm[rev_idx[hb]]))
                total_pair[hb] = total_pair.get(hb, 0) + 1
                if d <= MD_BP_CUTOFF_NM:
                    formed[hb] = formed.get(hb, 0) + 1
                    n_formed += 1
            bp_pf.append(n_formed / len(designed))
        else:
            bp_pf.append(0.0)
        n_frames += 1
        if on_frame is not None:
            on_frame()

    if n_frames == 0 or not twist_pf:
        return {"ready": False, "n_frames": 0}

    mean_positions = [{"helix_id": k[0], "bp_index": k[1], "direction": k[2],
                       "backbone_position": np.mean(v, axis=0)} for k, v in acc.items()]
    mean_core = _filter_to_reference_core(mean_positions, analytic_reference)
    twist_sp = differential_profile(measure_bundle_twist_profile(mean_core, n_slices=n_slices),
                                    measure_bundle_twist_profile(analytic_reference, n_slices=n_slices))
    curv_sp = differential_profile(measure_bundle_curvature_profile(mean_core, n_slices=n_slices),
                                   measure_bundle_curvature_profile(analytic_reference, n_slices=n_slices))
    pair_frac = {k: formed.get(k, 0) / total_pair[k] for k in total_pair}
    bp_sp = base_pairing_spatial_profile(pair_frac, mean_positions, n_slices=n_slices)

    return {
        "ready": True, "n_frames": n_frames,
        "twist": {"temporal": {"per_frame": [round(x, 3) for x in twist_pf],
                               "stats": twist_series_stats(twist_pf),
                               "analytic": round(analytic_twist, 3)},
                  "spatial": twist_sp},
        "curvature": {"temporal": {"per_frame": [round(x, 4) for x in curv_pf],
                                   "stats": twist_series_stats(curv_pf),
                                   "analytic": round(analytic_curv, 4)},
                      "spatial": curv_sp},
        "base_pairing": {"temporal": {"per_frame": [round(x, 4) for x in bp_pf],
                                      "n_designed": n_designed},
                         "spatial": bp_sp},
    }


def md_composite_meta(segments, max_frames: int = 200, stride: int | None = None) -> dict:
    """Lightweight metadata for the NAMD composite — ``{n_frames, markers, stages}``
    — from DCD frame counts only (DCD header, no PSF parse, no coordinate read), so
    the trajectory-keyframe slider sizes itself in milliseconds. Shares
    :func:`_composite_indices` with md_composite_trajectory so indices match exactly.

    ``stages`` entries also carry ``n_raw`` (the segment's undownsampled DCD frame
    count) and the payload carries ``total_raw``, so a caller can show "N of M frames"
    or recompute the count for a different ``stride`` without another request."""
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
        return {"n_frames": 0, "stages": [], "markers": [], "total_raw": 0}

    picked = _composite_indices([c for _, _, c in counts], max_frames, stride)
    out_n = 0
    out_stages: list[dict] = []
    markers: list[dict] = []
    for (name, kind, c), keep_idxs in zip(counts, picked):
        if c <= 0:
            continue
        if out_n:
            markers.append({"frame": out_n, "label": f"→ {name}",
                            "kind": kind or "md", "stage_name": name})
        out_stages.append({"name": name, "kind": kind or "md",
                           "n_frames": len(keep_idxs), "n_raw": c})
        out_n += len(keep_idxs)
    return {"n_frames": out_n, "stages": out_stages, "markers": markers,
            "total_raw": total}


def _stride_pick(items: list, keep: int) -> list:
    if keep >= len(items) or keep <= 0:
        return items
    return [items[round(i * (len(items) - 1) / (keep - 1))] for i in range(keep)] \
        if keep > 1 else [items[0]]


def _composite_indices(seg_counts, max_frames: int = 200,
                       stride: int | None = None) -> list[list[int]]:
    """Which GLOBAL (concatenated-universe) frame indices the composite keeps, per
    segment.  The single source of truth for both md_composite_meta and
    md_composite_trajectory — they used to carry separate copies of this arithmetic,
    and any drift between them desyncs the slider from the frames it scrubs.

    Two modes:

    * ``stride is None`` — the legacy budget: at most ``max_frames`` frames TOTAL,
      split across segments in proportion to their length (≥1 each), evenly picked
      within a segment.  Unchanged, index for index.
    * ``stride >= 1`` — a user-set frame INTERVAL, applied per segment (frames
      ``0, stride, 2*stride, …`` of each written segment), which is what VMD's DCD
      stride does to each loaded file.  Every non-empty segment therefore keeps at
      least its own frame 0, so the segment-boundary markers stay meaningful.
    """
    counts = [int(c) for c in seg_counts]
    total = sum(c for c in counts if c > 0)
    out: list[list[int]] = []
    offset = 0
    for count in counts:
        if count <= 0:
            out.append([])
            continue
        global_idxs = list(range(offset, offset + count))
        if stride is not None and stride >= 1:
            out.append(global_idxs[::int(stride)])
        else:
            keep = max(1, round(count * max_frames / total)) if total > max_frames else count
            out.append(_stride_pick(global_idxs, keep))
        offset += count
    return out


def md_composite_trajectory(topology_path, segments, coordinate_path, design,
                            max_frames: int = 200, stride: int | None = None) -> dict:
    """Composite scrub-able NAMD trajectory for a trajectory keyframe.

    ``segments`` = ordered ``[(name, stage, dcd_path), …]`` (every segment that has
    written a DCD). All DCDs load into ONE MDAnalysis Universe (continuous frame
    index); frames are downsampled per segment via :func:`_composite_indices` — either
    the legacy ``max_frames`` budget or, when ``stride`` is given, a user-set frame
    INTERVAL (every Nth frame of each segment) — with a boundary marker at each segment
    start. Returns the same shape as ``oxdna_health.composite_trajectory``."""
    import MDAnalysis as mda  # type: ignore

    seg_paths = [s[2] for s in segments]
    # with_termini: recover each strand's 5'-terminal base (no P atom) so the scrubbable
    # trajectory positions + colours every nucleotide, matching the flexibility map + the
    # ghost-free render (single-stranded regions no longer draw phantom bases).
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_termini=True)
    p_order = ctx["p_order"]
    term_specs = ctx.get("term_specs") or []
    # keys = P-order nucleotides THEN the recovered 5' termini (frame floats follow the
    # same order below), so the frontend's key→nucleotide map covers every base.
    key_list = [list(k) for k in p_order] + [list(s[0]) for s in term_specs]

    # Per-segment frame counts (for boundary markers + per-segment downsample).
    seg_counts: list[int] = []
    for _, _, dcd in segments:
        su = mda.Universe(str(topology_path), str(dcd))
        seg_counts.append(len(su.trajectory))
    total = sum(seg_counts)
    if total == 0:
        return {"n_frames": 0, "n_nucleotides": len(key_list),
                "keys": key_list, "frames": [], "stages": [], "markers": []}

    seg_picked = _composite_indices(seg_counts, max_frames, stride)
    out_frames: list[list[float]] = []
    out_stages: list[dict] = []
    markers: list[dict] = []
    run_no = 0
    for (name, stage, _dcd), count, picked in zip(segments, seg_counts, seg_picked):
        if count <= 0:
            continue
        if out_frames:
            run_no += 1
            markers.append({"frame": len(out_frames), "label": f"→ {name}",
                            "kind": stage or "md", "stage_name": name})
        out_stages.append({"name": name, "kind": stage or "md", "n_frames": len(picked)})
        for gidx in picked:
            p_nm, normals, tpos, tnorm = _extract_md_nadoc_frame(ctx, gidx, with_termini=True)
            flat: list[float] = []
            for i in range(len(p_order)):
                flat.extend((float(p_nm[i, 0]), float(p_nm[i, 1]), float(p_nm[i, 2])))
                if normals is not None:
                    flat.extend((float(normals[i, 0]), float(normals[i, 1]), float(normals[i, 2])))
                else:
                    flat.extend((0.0, 0.0, 1.0))
            for j in range(len(term_specs)):
                if j < len(tpos):
                    flat.extend((float(tpos[j, 0]), float(tpos[j, 1]), float(tpos[j, 2])))
                    flat.extend((float(tnorm[j, 0]), float(tnorm[j, 1]), float(tnorm[j, 2])))
                else:
                    flat.extend((0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
            out_frames.append(flat)

    return {"n_frames": len(out_frames), "n_nucleotides": len(key_list),
            "keys": key_list, "frames": out_frames,
            "stages": out_stages, "markers": markers}


# ── Occupancy clouds ─────────────────────────────────────────────────────────────
#: Stage-label markers for dynamics that is NOT free sampling. The equilibrium-aware
#: protocol ramps elastic-network restraints k=0.5 → 0.1 → 0.01 → None, labelling each
#: ``"300K NPT ENM k=<scale>"`` and the unrestrained one ``"300K NPT k=0"``
#: (``md_protocols`` builds both from the same ``scale is None`` test), plus a
#: ``"300K NPT settle (DNA fixed)"`` stage and an ENM minimisation.
#:
#: This matters more here than anywhere else: a restraint RAMP is a one-way relaxation by
#: construction, so clustering across it finds "early vs late" — a drift — and buries
#: whatever the free ensemble actually does. oxDNA's equivalent is keeping only
#: production/field stages.
_MD_RESTRAINED_MARKERS = ("enm", "fixed", "minim")


def md_free_sampling_segments(segments) -> list[int]:
    """Indices of the segments that are FREE (unrestrained) dynamics.

    Returns every index when no segment can be identified as free — an unfamiliar protocol
    should degrade to "use everything, and say so", not to an empty ensemble.
    """
    free = [i for i, seg in enumerate(segments)
            if not any(m in str(seg[1]).lower() for m in _MD_RESTRAINED_MARKERS)]
    return free if free else list(range(len(segments)))


def md_occupancy(topology_path, segments, coordinate_path, design, max_frames: int = 200,
                 n_clusters: int = 0, basis: str = "nt", selection=None,
                 all_stages: bool = False) -> dict:
    """Top-N most likely CONFIGURATIONS of a NAMD ensemble.

    The NAMD counterpart of :func:`backend.core.oxdna_occupancy.production_occupancy`.
    Everything downstream of the feature matrix — PCA, k-means, the medoid, the
    drift/unimodal verdict, the autocorrelation-aware population errors — is the SAME
    engine-agnostic core (:mod:`backend.core.occupancy_core`), because MD and oxDNA already
    speak the same nucleotide keys (``md_pkey`` emits the identical tuples, ``__xb__`` and
    ``__ext_`` forms included).

    What is NOT shared is the feature assembly, and deliberately so:

    * MD has **no ``a3``**, and its ``p_nm`` is already the backbone site (the P atom),
      whereas oxDNA stores a centre of mass from which the site is derived. Running
      oxDNA's ``occupancy_features`` over MD data would fabricate an offset.
    * The FENE window is an oxDNA potential. It is not the calibrated gate for a NAMD
      frame, so no torn-frame rejection is applied here; MD frames arrive PBC-corrected
      and Kabsch-aligned from :func:`_extract_md_nadoc_frame` already.

    Unlike ``md_rmsf``'s one-pass accumulator this RETAINS every sampled frame — clustering
    needs them all at once — so cost scales with ``max_frames`` in memory as well as time.

    Runs inside ``md_analysis_runner``'s killable subprocess, so it must stay picklable in
    and out and must not rely on any module-level cache surviving the call.
    """
    import MDAnalysis as mda  # type: ignore  # noqa: PLC0415  (heavy; lazy like its siblings)

    from backend.core.occupancy_core import occupancy_clusters, resolve_selection_keys

    seg_paths = [s[2] for s in segments]
    ctx = _build_md_nadoc_ctx(topology_path, seg_paths, coordinate_path, design,
                              with_termini=True)
    p_order = ctx["p_order"]
    term_specs = ctx.get("term_specs") or []
    key_list = [tuple(k) for k in p_order] + [tuple(s[0]) for s in term_specs]
    if not key_list:
        return {"ready": False, "reason": "no mapped nucleotides"}

    seg_counts: list[int] = []
    for _, _, dcd in segments:
        su = mda.Universe(str(topology_path), str(dcd))
        seg_counts.append(len(su.trajectory))
    if sum(seg_counts) == 0:
        return {"ready": False, "reason": "no trajectory frames yet"}

    free_idx = list(range(len(segments))) if all_stages else md_free_sampling_segments(segments)
    fell_back = not all_stages and free_idx == list(range(len(segments))) and any(
        any(m in str(s[1]).lower() for m in _MD_RESTRAINED_MARKERS) for s in segments)

    # Global frame indices belonging to the sampling segments only.
    starts, at = [], 0
    for c in seg_counts:
        starts.append(at)
        at += c
    pool: list[int] = []
    for i in free_idx:
        pool.extend(range(starts[i], starts[i] + seg_counts[i]))
    if not pool:
        return {"ready": False, "reason": "no free-sampling frames in this run"}

    picked = pool if len(pool) <= max_frames else _stride_pick(pool, max_frames)

    scoped = resolve_selection_keys(design, key_list, selection)
    if selection and not scoped:
        return {"ready": False, "reason": "the selection matched no nucleotides"}
    is_scoped = bool(selection) and len(scoped) < len(key_list)
    want = set(scoped)
    sel_idx = [i for i, k in enumerate(key_list) if k in want] if is_scoped else None

    n_p = len(p_order)
    rows: list[np.ndarray] = []
    kept: list[int] = []
    frames_out: dict[int, list[float]] = {}
    for gidx in picked:
        p_nm, normals, tpos, tnorm = _extract_md_nadoc_frame(ctx, gidx, with_termini=True)
        if p_nm is None or len(p_nm) != n_p:
            continue
        pos = np.vstack([p_nm, tpos]) if term_specs and tpos is not None and len(tpos) else p_nm
        if len(pos) != len(key_list):
            continue
        nrm = normals if normals is not None and len(normals) == n_p else np.tile([0.0, 0.0, 1.0], (n_p, 1))
        if term_specs and tnorm is not None and len(tnorm) == len(term_specs):
            nrm = np.vstack([nrm, tnorm])
        elif term_specs:
            nrm = np.vstack([nrm, np.tile([0.0, 0.0, 1.0], (len(term_specs), 1))])

        v = pos[sel_idx] if sel_idx is not None else pos
        rows.append(np.asarray(v, dtype=float).ravel())
        kept.append(gidx)
        # Same 6-float stride as md_composite_trajectory / _flatten_cg_frame, so the
        # frontend consumes an MD medoid with the oxDNA code path unchanged.
        flat: list[float] = []
        for i in range(len(key_list)):
            flat.extend((float(pos[i, 0]), float(pos[i, 1]), float(pos[i, 2])))
            flat.extend((float(nrm[i, 0]), float(nrm[i, 1]), float(nrm[i, 2])))
        frames_out[gidx] = flat

    if len(rows) < 20:
        return {"ready": False,
                "reason": f"need at least 20 frames to cluster (have {len(rows)})",
                "n_frames": len(rows)}

    res = occupancy_clusters(np.array(rows, dtype=float), n_clusters=n_clusters)
    if not res.get("ready"):
        return res

    res["method"] = "pca"
    res["basis"] = "nt"          # MD has one site per nucleotide; no bp-midpoint basis yet
    res["basis_requested"] = basis
    res["scoped"] = bool(is_scoped)
    res["n_selected"] = len(sel_idx) if sel_idx is not None else len(key_list)
    res["n_total"] = len(key_list)
    res["n_frames_total"] = sum(seg_counts)
    res["n_frames_torn"] = 0
    res["sampling_stages"] = [str(segments[i][1]) for i in free_idx]
    res["all_stages"] = bool(all_stages or fell_back)
    if fell_back:
        res["sampling_note"] = ("no unrestrained stage identified in this protocol — "
                                "clustered every stage, which mixes restrained dynamics")
    res["keys"] = [list(k) for k in key_list]
    for cl in res["clusters"]:
        gidx = kept[cl["medoid_index"]]
        cl["medoid_frame"] = int(gidx)
        cl["frames"] = [int(kept[r]) for r in cl["frames"]]
        cl["frame"] = frames_out[gidx]
    return res
