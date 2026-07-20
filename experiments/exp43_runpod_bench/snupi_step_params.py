#!/usr/bin/env python3
"""Full 6-parameter base-pair-STEP extractor for SNUPI convergence — numpy only, on-pod portable.

The convergence checker must watch the SAME six DOF SNUPI parameterizes — {shift, slide, rise,
tilt, roll, twist} — because SNUPI's per-motif stiffness is k = kB*T * Cov^-1 of that 6-vector, so
the OFF-DIAGONAL couplings (which converge slower than the diagonals) gate sufficiency. The prior
observable had only twist+rise from C1' geometry; this adds the other four and, crucially, real
base-pair FRAMES (needed for shift/slide/tilt/roll).

Method — El Hassan-Calladine / CEHS mid-step triad:
  * Each base's frame: normal ẑ from an SVD plane-fit to its 6-membered ring (N1,C2,N3,C4,C5,C6 —
    the same atom names in purines and pyrimidines); long axis ŷ from the C1'-C1' vector; x̂ = ŷ×ẑ.
  * bp frame = symmetrised over the two paired bases (antiparallel → base-B normal flips, reinforcing ẑ).
  * Step params between consecutive bp frames R_i,R_j: rotation Θ = log(R_j R_iᵀ); mid-step triad
    R_m = exp(Θ/2)·R_i; {tilt,roll,twist} = Θ·{x_m,y_m,z_m}; {shift,slide,rise} = (o_j−o_i)·{x_m,y_m,z_m}.

The frame here is CONSISTENT and physically faithful (captures all six DOF incl. base-normal tilt/roll),
which is what a convergence decision needs — a covariance that has converged is converged in any linear
frame. Exact agreement with 3DNA's standard reference frame (needed only for the FINAL SNUPI-frame
stiffness values, a downstream step) is NOT required to decide WHEN the ensemble is converged.
"""
from __future__ import annotations
import numpy as np

RING6 = ("N1", "C2", "N3", "C4", "C5", "C6")   # 6-membered ring, shared by purines & pyrimidines


# ── rotation helpers (batched, numpy) ─────────────────────────────────────────
def _log_rotvec(R):
    """Rotation matrices (...,3,3) -> rotation vectors (...,3) (axis*angle). Stable near 0 and π."""
    R = np.asarray(R, float)
    tr = np.trace(R, axis1=-2, axis2=-1)
    cos = np.clip((tr - 1.0) * 0.5, -1.0, 1.0)
    ang = np.arccos(cos)
    # axis from the skew-symmetric part
    ax = np.stack([R[..., 2, 1] - R[..., 1, 2],
                   R[..., 0, 2] - R[..., 2, 0],
                   R[..., 1, 0] - R[..., 0, 1]], axis=-1)
    s = np.linalg.norm(ax, axis=-1, keepdims=True)
    small = s[..., 0] < 1e-8
    # generic: axis = ax/(2 sin ang); rotvec = ang*axis = ang/(2 sinang) * ax
    denom = np.where(s[..., 0] > 1e-12, s[..., 0], 1.0)
    vec = ax * (ang / denom)[..., None]
    # near-zero rotation: rotvec ≈ 0.5*ax (first order)
    vec = np.where(small[..., None], 0.5 * ax, vec)
    return vec


def _exp_rotvec(v):
    """Rotation vectors (...,3) -> rotation matrices (...,3,3) via Rodrigues (batched)."""
    v = np.asarray(v, float)
    ang = np.linalg.norm(v, axis=-1, keepdims=True)
    k = v / np.where(ang > 1e-12, ang, 1.0)
    kx, ky, kz = k[..., 0], k[..., 1], k[..., 2]
    z = np.zeros_like(kx)
    K = np.stack([np.stack([z, -kz, ky], -1),
                  np.stack([kz, z, -kx], -1),
                  np.stack([-ky, kx, z], -1)], axis=-2)
    a = ang[..., 0][..., None, None]
    I = np.eye(3) + np.zeros(K.shape)
    return I + np.sin(a) * K + (1.0 - np.cos(a)) * (K @ K)


def _unit(v, axis=-1):
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.where(n > 1e-12, n, 1.0)


# ── base & bp frames from atoms ───────────────────────────────────────────────
def base_normals(coords, ring_idx):
    """coords (N,3); ring_idx (M,6) atom indices of each base's 6-ring -> unit normals (M,3)."""
    ring = coords[ring_idx]                      # (M,6,3)
    c = ring - ring.mean(axis=1, keepdims=True)  # center
    # batched SVD; normal = right-singular vector of smallest singular value (last row of Vt)
    _, _, Vt = np.linalg.svd(c, full_matrices=False)
    return Vt[:, 2, :]                            # (M,3)


def bp_frames(coords, c1_a, c1_b, ring_a, ring_b, z_ref=None):
    """Symmetrised base-pair frames.

    Returns (origins (M,3), R (M,3,3)) with R columns = [x̂ (short), ŷ (long, C1'a->C1'b), ẑ (helical)].
    If ``z_ref`` (M,3) is given, each bp's ẑ is flipped to the same hemisphere as z_ref (its normal
    in a fixed REFERENCE structure) — the SVD normal sign is per-frame arbitrary, and a reference
    anchor makes ẑ (hence the cross-helix relative rotation R_iᵀR_j) TEMPORALLY consistent across a
    trajectory. Without it the crossover 6-DOF sign-flips frame-to-frame and its covariance is junk.
    """
    C1a = coords[c1_a]; C1b = coords[c1_b]
    na = base_normals(coords, ring_a)
    nb = base_normals(coords, ring_b)
    # antiparallel bases: nb ~ -na. Flip nb to agree with na, then average -> helical normal.
    nb = nb * np.sign(np.sum(na * nb, axis=1))[:, None]
    z0 = _unit(na + nb)
    if z_ref is not None:
        z0 = z0 * np.sign(np.sum(z0 * z_ref, axis=1))[:, None]
    y0 = C1a - C1b                               # long axis (C1'-C1')
    y = _unit(y0 - np.sum(y0 * z0, axis=1)[:, None] * z0)
    x = _unit(np.cross(y, z0))
    z = np.cross(x, y)                            # re-orthogonalise (right-handed)
    R = np.stack([x, y, z], axis=-1)             # columns are the axes
    o = 0.5 * (C1a + C1b)
    return o, R


def helix_axes(centers, window):
    """Robust per-bp helix axis ẑ from a PCA over a WINDOW of neighbouring bp-centers along the duplex.

    ``centers`` (M,3) bp-centers; ``window`` (M,K) int bp-indices (the ±W chain neighbours, padded).
    Averaging over K precise C1'-midpoints kills the per-frame base-normal noise that made the single-
    base-ring SVD normal wobble ~several degrees (which softened every rotational stiffness ~4x). The
    axis is oriented along the window's ordering (chain 5'->3'), so it is temporally consistent.
    """
    W = centers[window]                          # (M,K,3)
    Wc = W - W.mean(axis=1, keepdims=True)
    _, _, Vt = np.linalg.svd(Wc, full_matrices=False)
    ax = Vt[:, 0, :]                             # first principal component
    dirn = W[:, -1, :] - W[:, 0, :]
    return ax * np.sign(np.sum(ax * dirn, axis=1))[:, None]


def bp_frames_h(coords, c1_a, c1_b, window):
    """C1'-only base-pair frames with ẑ = the robust PCA helix axis (no base-normal, no ring atoms).

    Returns (origins (M,3), R (M,3,3)); columns = [x̂ (short), ŷ (long, C1'a->C1'b), ẑ (helix)].
    """
    C1a = coords[c1_a]; C1b = coords[c1_b]
    o = 0.5 * (C1a + C1b)
    z = helix_axes(o, window)
    y0 = C1a - C1b
    y = _unit(y0 - np.sum(y0 * z, axis=1)[:, None] * z)
    x = _unit(np.cross(y, z))
    z = np.cross(x, y)
    R = np.stack([x, y, z], axis=-1)
    return o, R


def crossover_params(o, R, xsteps, beam):
    """SNUPI-convention crossover 6-DOF from precomputed helix-axis frames (o,R) + fixed beam frames.

    ``xsteps`` (S,2) cross-helix bp-index pairs; ``beam`` (S,3,3) per-crossover frames (axial = ref
    inter-helix offset). Returns (S,7): [q_axial, q_perp1, q_perp2 (Å), r_tors, r_bend1, r_bend2 (deg),
    theta_interhelical (deg)]. q_axial ≈ the ~18 Å inter-helix span; theta = angle between the two
    helix axes (now robust — a genuine interhelical angle, not base-normal noise).
    """
    i = xsteps[:, 0]; j = xsteps[:, 1]
    Bt = np.transpose(beam, (0, 2, 1))
    dt = o[j] - o[i]
    q_t = np.einsum("sab,sb->sa", Bt, dt)
    dR = R[j] @ np.transpose(R[i], (0, 2, 1))
    rv = _log_rotvec(dR)
    q_r = np.degrees(np.einsum("sab,sb->sa", Bt, rv))
    zi = R[i][:, :, 2]; zj = R[j][:, :, 2]
    theta = np.degrees(np.arccos(np.clip(np.sum(zi * zj, axis=1), -1.0, 1.0)))
    return np.concatenate([q_t, q_r, theta[:, None]], axis=1)


# ── step parameters (CEHS mid-step triad) ─────────────────────────────────────
def step_params(origins, R, steps):
    """origins (M,3), R (M,3,3); steps (S,2) indices (i,j) of consecutive bp along a chain.
    Returns (S,6): [shift, slide, rise (Å), tilt, roll, twist (deg)]."""
    i = steps[:, 0]; j = steps[:, 1]
    oi = origins[i]; oj = origins[j]
    Ri = R[i].copy(); Rj = R[j].copy()
    # The SVD base-normal sign is arbitrary, so each bp's ẑ points 5'->3' or 3'->5' at random,
    # which flips rise/twist sign per step (symmetric-about-0 distribution). Orient BOTH frames'
    # ẑ along the actual step direction (o_j - o_i); flip x̂ too (180° about ŷ, the bp pseudo-dyad)
    # to preserve right-handedness. This makes rise>0 and twist/tilt/roll consistently signed.
    u = _unit(oj - oi)
    for Rf in (Ri, Rj):
        flip = np.sum(Rf[:, :, 2] * u, axis=1) < 0
        Rf[flip, :, 0] *= -1.0
        Rf[flip, :, 2] *= -1.0
    T = Rj @ np.transpose(Ri, (0, 2, 1))         # rotation i->j
    Th = _log_rotvec(T)                          # (S,3) rotation vector (rad)
    Rm = _exp_rotvec(0.5 * Th) @ Ri              # mid-step triad
    xm = Rm[:, :, 0]; ym = Rm[:, :, 1]; zm = Rm[:, :, 2]
    tilt = np.degrees(np.sum(Th * xm, axis=1))
    roll = np.degrees(np.sum(Th * ym, axis=1))
    twist = np.degrees(np.sum(Th * zm, axis=1))
    d = origins[j] - origins[i]
    shift = np.sum(d * xm, axis=1)
    slide = np.sum(d * ym, axis=1)
    rise = np.sum(d * zm, axis=1)
    return np.stack([shift, slide, rise, tilt, roll, twist], axis=1)


def frame_step_params(coords, recipe):
    """One-shot: coords (N,3) + a bp recipe dict -> (S,6) step params for recipe['steps']."""
    o, R = bp_frames(coords, recipe["c1_a"], recipe["c1_b"], recipe["ring_a"], recipe["ring_b"])
    return step_params(o, R, recipe["steps"])


# ── local recipe builder (design-FREE: geometric pairing + chaining + ring atoms) ──
def build_frame_recipe(topology_psf, coordinate_pdb, ref_coor=None):
    """Resolve, DESIGN-FREE, the per-bp frame atoms + consecutive-bp STEP index pairs.

    Returns a dict of numpy arrays: c1_a,c1_b (M,), ring_a,ring_b (M,6) full-atom indices per bp;
    steps (S,2) bp-index pairs of consecutive base pairs along each duplex chain. Reuses
    md_health.build_c1_pairs (C1' proximity, ssDNA excluded) + midpoint-proximity chaining
    (2.5-4.5 A = one rise, no cross-helix edges), same as snupi_bp_observable.build_recipe.
    """
    import sys
    sys.path.insert(0, "/home/jojo/Work/NADOC")
    from pathlib import Path
    from collections import defaultdict
    import MDAnalysis as mda
    from scipy.spatial import cKDTree
    from backend.core import md_health as H, md_protocols as P
    psf, pdb = Path(topology_psf), Path(coordinate_pdb)
    unpaired = P.identify_unpaired_residues(psf, pdb)
    pairs = H.build_c1_pairs(psf, pdb, exclude_residues=unpaired)
    u = mda.Universe(str(psf), str(pdb))
    c1 = u.select_atoms("name C1'")
    c1pos = c1.positions.astype(float)
    c1_full = c1.indices
    # per-residue ring-atom map (one pass over all ring atoms)
    ring_atoms = u.select_atoms("name " + " ".join(RING6))
    res_ring = defaultdict(dict)
    for a in ring_atoms:
        res_ring[a.residue.resindex][a.name] = a.index
    resindex = c1.resindices                       # residue index per C1' selection atom

    def ring_for(sel_ids):
        out = np.full((len(sel_ids), 6), -1, dtype=np.int64)
        for k, si in enumerate(sel_ids):
            rr = res_ring.get(int(resindex[si]), {})
            for r, nm in enumerate(RING6):
                if nm in rr:
                    out[k, r] = rr[nm]
        return out

    c1_a = c1_full[pairs.pi]; c1_b = c1_full[pairs.pj]
    ring_a = ring_for(pairs.pi); ring_b = ring_for(pairs.pj)
    mid = 0.5 * (c1pos[pairs.pi] + c1pos[pairs.pj])
    # chain consecutive bp (midpoint distance ~ rise)
    t = cKDTree(mid)
    cand = t.query_pairs(r=4.5, output_type="ndarray")
    d = np.linalg.norm(mid[cand[:, 0]] - mid[cand[:, 1]], axis=1)
    edges = cand[(d >= 2.5) & (d <= 4.5)]
    adj = defaultdict(list)
    for a, b in edges:
        adj[int(a)].append(int(b)); adj[int(b)].append(int(a))
    visited = set(); steps = []
    starts = [n for n in range(len(mid)) if len(adj[n]) == 1] + list(range(len(mid)))
    for s in starts:
        if s in visited or len(adj[s]) > 2:
            continue
        prev, cur = None, s; chain = [s]; visited.add(s)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in visited and len(adj[n]) <= 2]
            if not nxt:
                break
            prev, cur = cur, nxt[0]; chain.append(cur); visited.add(cur)
        for k in range(len(chain) - 1):
            steps.append((chain[k], chain[k + 1]))
    steps = np.array(steps, dtype=np.int64) if steps else np.zeros((0, 2), np.int64)
    # keep only steps whose both bp have a complete ring (frame is well-defined)
    good_bp = (ring_a.min(axis=1) >= 0) & (ring_b.min(axis=1) >= 0)
    if len(steps):
        steps = steps[good_bp[steps[:, 0]] & good_bp[steps[:, 1]]]
    rec = dict(c1_a=c1_a, c1_b=c1_b, ring_a=ring_a, ring_b=ring_b, steps=steps)
    # filter to clean dsDNA steps on a reference frame (drop mis-chained crossover/nick steps)
    if ref_coor is not None and len(steps):
        u2 = mda.Universe(str(psf), str(ref_coor))
        P6 = frame_step_params(u2.atoms.positions.astype(float), rec)
        rise = P6[:, 2]; tw = np.abs(P6[:, 5])
        clean = np.isfinite(tw) & (tw >= 20) & (tw <= 50) & (rise >= 2.9) & (rise <= 4.3)
        rec["steps"] = steps[clean]
    return rec


def _pair_bp_arrays(u, pairs):
    """Shared: per-bp frame-atom arrays (c1_a,c1_b,ring_a,ring_b) + a resindex->bp map."""
    from collections import defaultdict
    c1 = u.select_atoms("name C1'")
    c1_full = c1.indices
    ring_atoms = u.select_atoms("name " + " ".join(RING6))
    res_ring = defaultdict(dict)
    for a in ring_atoms:
        res_ring[a.residue.resindex][a.name] = a.index
    resindex = c1.resindices

    def ring_for(sel_ids):
        out = np.full((len(sel_ids), 6), -1, dtype=np.int64)
        for k, si in enumerate(sel_ids):
            rr = res_ring.get(int(resindex[si]), {})
            for r, nm in enumerate(RING6):
                if nm in rr:
                    out[k, r] = rr[nm]
        return out

    c1_a = c1_full[pairs.pi]; c1_b = c1_full[pairs.pj]
    ring_a = ring_for(pairs.pi); ring_b = ring_for(pairs.pj)
    res_to_bp = {}
    for bpk in range(len(pairs.pi)):
        res_to_bp[int(resindex[pairs.pi[bpk]])] = bpk
        res_to_bp[int(resindex[pairs.pj[bpk]])] = bpk
    have_c1 = set(int(x) for x in resindex)
    return dict(c1_a=c1_a, c1_b=c1_b, ring_a=ring_a, ring_b=ring_b), res_to_bp, have_c1


def extra_base_insert_keys(design_path, psf):
    """(segid, resid) strings of the DESIGN's true crossover extra bases — NOT all unpaired residues
    (that sweeps in scaffold ssDNA loops + bulges). Uses the proven ordinal bridge in
    namd_topology.extra_base_segid_resids off the design's per-atom crossover_id tags."""
    import sys
    sys.path.insert(0, "/home/jojo/Work/NADOC")
    from pathlib import Path
    from backend.core.models import Design
    from backend.core.atomistic import build_atomistic_model
    from backend.core.namd_topology import extra_base_segid_resids
    design = Design.model_validate_json(Path(design_path).read_text())
    model = build_atomistic_model(design)
    return set(extra_base_segid_resids(model, Path(psf)))   # {(segid, resid) as str}


def build_crossover_recipe(topology_psf, coordinate_pdb, design_path, ref_coor=None):
    """Recipe for the EXTRA-BASE CROSSOVER motif: the cross-helix bp-step between the two
    crossover-connected base pairs that flank each design extra-base insert run.

    The insert set comes from the DESIGN (extra_base_insert_keys), so scaffold ssDNA loops and
    intra-helix bulges are excluded — only true crossover inserts remain. Within each strand
    (segment, 5'->3' topology order) a maximal run of inserts is one crossover; the paired bp
    immediately 5' and 3' of the run sit on the two DIFFERENT helices the strand bridges, so
    (flank5_bp, flank3_bp) is the crossover step. step_params orients its axial along the inter-helix
    offset (o_j - o_i, ~1.9-2.25 nm) — SNUPI's CO-beam convention. n_insert records the run length.
    """
    import sys
    sys.path.insert(0, "/home/jojo/Work/NADOC")
    from pathlib import Path
    import MDAnalysis as mda
    from backend.core import md_health as H, md_protocols as P
    psf, pdb = Path(topology_psf), Path(coordinate_pdb)
    unpaired = P.identify_unpaired_residues(psf, pdb)
    pairs = H.build_c1_pairs(psf, pdb, exclude_residues=unpaired)
    u = mda.Universe(str(psf), str(pdb))
    rec, res_to_bp, have_c1 = _pair_bp_arrays(u, pairs)
    insert_keys = extra_base_insert_keys(design_path, psf)     # {(segid, resid)} true inserts
    # per-residue (segid, resid) -> is-insert flag
    is_insert = {}
    for r in u.residues:
        is_insert[int(r.resindex)] = (str(r.segid), str(r.resid)) in insert_keys
    xsteps = []; n_insert = []
    for seg in u.segments:
        res = [int(r.resindex) for r in seg.residues if int(r.resindex) in have_c1]
        i = 0
        while i < len(res):
            if is_insert.get(res[i], False):            # start of a true insert run
                j = i
                while j < len(res) and is_insert.get(res[j], False):
                    j += 1
                if i - 1 >= 0 and j < len(res):
                    b5, b3 = res_to_bp.get(res[i - 1]), res_to_bp.get(res[j])
                    if b5 is not None and b3 is not None and b5 != b3:
                        xsteps.append((b5, b3)); n_insert.append(j - i)
                i = j
            else:
                i += 1
    rec["steps"] = np.array(xsteps, dtype=np.int64) if xsteps else np.zeros((0, 2), np.int64)
    rec["n_insert"] = np.array(n_insert, dtype=np.int64)
    # Reference anchors from the ref structure (temporal sign consistency + fixed beam frames).
    ref = coordinate_pdb if ref_coor is None else ref_coor
    u2 = mda.Universe(str(psf), str(ref))
    posr = u2.atoms.positions.astype(float)
    # reference bp normals (na+nb, sign-arbitrary but FIXED — every frame anchors to these)
    na = base_normals(posr, rec["ring_a"]); nb = base_normals(posr, rec["ring_b"])
    nb = nb * np.sign(np.sum(na * nb, axis=1))[:, None]
    rec["z_ref"] = _unit(na + nb)                                  # (M,3)
    o_ref, _ = bp_frames(posr, rec["c1_a"], rec["c1_b"], rec["ring_a"], rec["ring_b"], z_ref=rec["z_ref"])
    st = rec["steps"]
    if len(st):
        axial = _unit(o_ref[st[:, 1]] - o_ref[st[:, 0]])          # ref offset direction (S,3)
        # two perpendiculars (Gram-Schmidt against a fixed global up, then cross)
        up = np.tile(np.array([0.0, 0.0, 1.0]), (len(st), 1))
        alt = np.tile(np.array([0.0, 1.0, 0.0]), (len(st), 1))
        up = np.where((np.abs(np.sum(axial * up, axis=1)) > 0.9)[:, None], alt, up)
        p1 = _unit(up - np.sum(up * axial, axis=1)[:, None] * axial)
        p2 = np.cross(axial, p1)
        rec["beam"] = np.stack([axial, p1, p2], axis=-1)          # (S,3,3) columns = [axial,perp1,perp2]
    else:
        rec["beam"] = np.zeros((0, 3, 3))
    return rec


def build_recipe_full(topology_psf, coordinate_pdb, design_path, ref_coor=None, window=3):
    """UNIFIED helix-axis recipe: shared C1' bp-arrays + per-bp PCA-window + duplex steps + crossover
    steps + crossover beam frames. Frames are C1'-only (bp_frames_h) with ẑ = robust PCA helix axis —
    NO base-normal (the noise source that softened rotational stiffness ~4x). Returns numpy arrays:
    c1_a,c1_b (M,), window (M,2*window+1), dup_steps (Sd,2), xo_steps (Sx,2), beam (Sx,3,3).
    """
    import sys
    sys.path.insert(0, "/home/jojo/Work/NADOC")
    from pathlib import Path
    from collections import defaultdict
    import MDAnalysis as mda
    from scipy.spatial import cKDTree
    from backend.core import md_health as H, md_protocols as P
    psf, pdb = Path(topology_psf), Path(coordinate_pdb)
    unpaired = P.identify_unpaired_residues(psf, pdb)
    pairs = H.build_c1_pairs(psf, pdb, exclude_residues=unpaired)
    u = mda.Universe(str(psf), str(pdb))
    c1 = u.select_atoms("name C1'")
    c1_full = c1.indices; resindex = c1.resindices
    c1_a = c1_full[pairs.pi]; c1_b = c1_full[pairs.pj]
    M = len(pairs.pi)
    res_to_bp = {}
    for k in range(M):
        res_to_bp[int(resindex[pairs.pi[k]])] = k
        res_to_bp[int(resindex[pairs.pj[k]])] = k
    have_c1 = set(int(x) for x in resindex)
    # duplex chaining -> ordered chains
    mid = 0.5 * (c1.positions.astype(float)[pairs.pi] + c1.positions.astype(float)[pairs.pj])
    t = cKDTree(mid); cand = t.query_pairs(r=4.5, output_type="ndarray")
    d = np.linalg.norm(mid[cand[:, 0]] - mid[cand[:, 1]], axis=1)
    adj = defaultdict(list)
    for a, b in cand[(d >= 2.5) & (d <= 4.5)]:
        adj[int(a)].append(int(b)); adj[int(b)].append(int(a))
    chains = []; visited = set()
    for s in [n for n in range(M) if len(adj[n]) == 1] + list(range(M)):
        if s in visited or len(adj[s]) > 2:
            continue
        prev, cur, ch = None, s, [s]; visited.add(s)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in visited and len(adj[n]) <= 2]
            if not nxt:
                break
            prev, cur = cur, nxt[0]; ch.append(cur); visited.add(cur)
        chains.append(ch)
    dup_steps = []; bp_pos = {}
    for ch in chains:
        for k in range(len(ch) - 1):
            dup_steps.append((ch[k], ch[k + 1]))
        for pos, bp in enumerate(ch):
            bp_pos[bp] = (ch, pos)
    K = 2 * window + 1
    win = np.zeros((M, K), dtype=np.int64)
    for bp in range(M):
        if bp in bp_pos:
            ch, pos = bp_pos[bp]
            win[bp] = [ch[min(max(pos + off, 0), len(ch) - 1)] for off in range(-window, window + 1)]
        else:
            win[bp] = bp
    # crossover steps from the design's true extra bases
    insert_keys = extra_base_insert_keys(design_path, psf)
    is_ins = {int(r.resindex): (str(r.segid), str(r.resid)) in insert_keys for r in u.residues}
    xsteps = []
    for seg in u.segments:
        res = [int(r.resindex) for r in seg.residues if int(r.resindex) in have_c1]
        i = 0
        while i < len(res):
            if is_ins.get(res[i], False):
                j = i
                while j < len(res) and is_ins.get(res[j], False):
                    j += 1
                if i - 1 >= 0 and j < len(res):
                    b5, b3 = res_to_bp.get(res[i - 1]), res_to_bp.get(res[j])
                    if b5 is not None and b3 is not None and b5 != b3:
                        xsteps.append((b5, b3))
                i = j
            else:
                i += 1
    xsteps = np.array(xsteps, dtype=np.int64) if xsteps else np.zeros((0, 2), np.int64)
    dup_steps = np.array(dup_steps, dtype=np.int64) if dup_steps else np.zeros((0, 2), np.int64)
    rec = dict(c1_a=c1_a, c1_b=c1_b, window=win, dup_steps=dup_steps, xo_steps=xsteps)
    # reference frames: filter clean duplex steps + build crossover beam frames (axial = ref offset)
    ref = pdb if ref_coor is None else ref_coor
    posr = mda.Universe(str(psf), str(ref)).atoms.positions.astype(float)
    o_ref, R_ref = bp_frames_h(posr, c1_a, c1_b, win)
    if len(dup_steps):
        Pr = step_params(o_ref, R_ref, dup_steps)
        tw = np.abs(Pr[:, 5]); ri = Pr[:, 2]
        clean = np.isfinite(tw) & (tw >= 20) & (tw <= 50) & (ri >= 2.9) & (ri <= 4.3)
        rec["dup_steps"] = dup_steps[clean]
    if len(xsteps):
        axial = _unit(o_ref[xsteps[:, 1]] - o_ref[xsteps[:, 0]])
        up = np.tile(np.array([0.0, 0.0, 1.0]), (len(xsteps), 1))
        alt = np.tile(np.array([0.0, 1.0, 0.0]), (len(xsteps), 1))
        up = np.where((np.abs(np.sum(axial * up, axis=1)) > 0.9)[:, None], alt, up)
        p1 = _unit(up - np.sum(up * axial, axis=1)[:, None] * axial)
        rec["beam"] = np.stack([axial, p1, np.cross(axial, p1)], axis=-1)
    else:
        rec["beam"] = np.zeros((0, 3, 3))
    return rec


# ── self-validation (analytic round-trip + ideal B-DNA) ───────────────────────
def _forward_step(R_i, o_i, p):
    """Build (R_j, o_j) from step params p=[shift,slide,rise,tilt,roll,twist] via the SAME CEHS
    convention, so extractor∘forward = identity is a rigorous correctness test."""
    sh, sl, ri, ti, ro, tw = p
    Th_local = np.radians(np.array([ti, ro, tw]))          # in mid-frame axes
    # mid frame = exp(Th/2) R_i ; but Th is expressed in mid-frame -> solve consistently:
    # R_j = exp(Th_world) R_i with Th_world = R_m @ Th_local, R_m = exp(Th_world/2) R_i.
    Th_w = Th_local.copy()
    for _ in range(50):                                    # fixed-point (converges fast)
        Rm = _exp_rotvec(0.5 * Th_w) @ R_i
        Th_w = Rm @ Th_local
    Rm = _exp_rotvec(0.5 * Th_w) @ R_i
    R_j = _exp_rotvec(Th_w) @ R_i
    d = Rm @ np.array([sh, sl, ri])
    return R_j, o_i + d


def _selftest():
    rng = np.random.default_rng(0)
    print("── analytic round-trip (random frames + random params) ──")
    maxerr = 0.0
    for t in range(200):
        # random start frame
        R_i = _exp_rotvec(rng.normal(0, 1, 3))
        o_i = rng.normal(0, 5, 3)
        p = np.array([rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(2.8, 4.0),
                      rng.uniform(-15, 15), rng.uniform(-15, 15), rng.uniform(20, 45)])
        R_j, o_j = _forward_step(R_i, o_i, p)
        got = step_params(np.stack([o_i, o_j]),
                          np.stack([R_i, R_j]), np.array([[0, 1]]))[0]
        maxerr = max(maxerr, np.max(np.abs(got - p)))
    print(f"  max |recovered - true| over 200 random steps = {maxerr:.2e}  "
          f"({'PASS' if maxerr < 1e-6 else 'FAIL'})")

    print("── ideal B-DNA stack (twist 34.3°, rise 3.4 Å, others 0) ──")
    tw = np.radians(34.3); ri = 3.4
    R = np.eye(3); o = np.zeros(3); Rs = [R]; os = [o]
    for _ in range(20):
        Rz = _exp_rotvec(np.array([0, 0, tw]))
        R = Rz @ R; o = o + R @ np.array([0, 0, ri])       # advance along current z
        Rs.append(R); os.append(o)
    steps = np.array([[k, k + 1] for k in range(len(Rs) - 1)])
    P = step_params(np.array(os), np.array(Rs), steps)
    m = P.mean(axis=0)
    print(f"  shift {m[0]:+.3f} slide {m[1]:+.3f} rise {m[2]:.3f} | "
          f"tilt {m[3]:+.2f} roll {m[4]:+.2f} twist {m[5]:.2f}")
    ok = abs(m[2] - 3.4) < 1e-3 and abs(m[5] - 34.3) < 1e-2 and max(abs(m[0]), abs(m[1]), abs(m[3]), abs(m[4])) < 1e-2
    print(f"  -> {'PASS' if ok else 'FAIL'} (rise=3.4, twist=34.3, rest≈0)")


if __name__ == "__main__":
    _selftest()
