#!/usr/bin/env python3
"""SNUPI-relevant per-base-pair-step observable from a NAMD trajectory.

The convergence watcher needs a per-frame observable whose statistical convergence
tells us whether the post-equilibration ensemble suffices to re-estimate SNUPI's
per-motif elastic parameters (k = kB*T * Cov({shift,slide,rise,tilt,roll,twist})^-1).

This module supplies the two DOMINANT, most-robust DOF — **helical twist** (-> torsional
rigidity GJ) and **rise** (-> stretch EA) — computed per base-pair STEP from C1' geometry.
They are ROTATION/TRANSLATION INVARIANT (built from internal bp-frame geometry), so no
Kabsch alignment is needed and the same math runs identically locally and on a bare pod
(numpy only, no MDAnalysis, no NADOC repo) given a precomputed atom-index "recipe".

Split of labour:
  * ``build_recipe`` (LOCAL, uses the NADOC ctx machinery + MDAnalysis) resolves, per helix,
    the design-ordered base pairs and their two C1' full-atom indices, and emits STEP tuples
    (a_i, b_i, a_j, b_j) of C1' atom indices for consecutive bp along each helix.
  * ``step_twist_rise`` (PURE NUMPY, portable) takes a raw (N,3) frame + the recipe and
    returns per-step twist(deg) & rise(Ang) — the on-pod worker calls this.
"""
from __future__ import annotations
import numpy as np


# ── pure-numpy geometry (portable: local + on-pod) ────────────────────────────
def step_twist_rise(coords_ang: np.ndarray, steps: np.ndarray):
    """Per-step helical twist (deg) and rise (Ang) for one frame.

    ``coords_ang`` : (N,3) raw atomic coordinates (Angstrom) for the frame.
    ``steps``      : (M,4) int array; each row = (a_i, b_i, a_j, b_j) C1' atom indices,
                     where bp_i = (fwd a_i / rev b_i) and bp_j = the next bp along the helix.
    Returns (twist_deg (M,), rise_ang (M,)). Steps whose rise is non-physical for a dsDNA
    step (outside [2.0, 5.5] Ang — i.e. a nick/crossover gap) are returned as NaN so the
    caller can drop them.
    """
    a_i = coords_ang[steps[:, 0]]; b_i = coords_ang[steps[:, 1]]
    a_j = coords_ang[steps[:, 2]]; b_j = coords_ang[steps[:, 3]]
    m_i = 0.5 * (a_i + b_i)                      # bp_i center
    m_j = 0.5 * (a_j + b_j)                      # bp_j center
    y_i = a_i - b_i                              # bp_i long (C1'-C1') axis
    y_j = a_j - b_j
    step_vec = m_j - m_i
    rise = np.linalg.norm(step_vec, axis=1)
    h = step_vec / np.where(rise[:, None] > 1e-9, rise[:, None], 1.0)   # local helix axis
    # project the two long axes into the plane perpendicular to h, signed angle about h
    yi_p = y_i - (np.sum(y_i * h, axis=1))[:, None] * h
    yj_p = y_j - (np.sum(y_j * h, axis=1))[:, None] * h
    ni = np.linalg.norm(yi_p, axis=1); nj = np.linalg.norm(yj_p, axis=1)
    ok = (ni > 1e-6) & (nj > 1e-6)
    yi_u = yi_p / np.where(ni[:, None] > 1e-9, ni[:, None], 1.0)
    yj_u = yj_p / np.where(nj[:, None] > 1e-9, nj[:, None], 1.0)
    cosang = np.clip(np.sum(yi_u * yj_u, axis=1), -1.0, 1.0)
    cross = np.cross(yi_u, yj_u)
    sign = np.sign(np.sum(cross * h, axis=1))
    twist = np.degrees(np.arccos(cosang)) * np.where(sign == 0, 1.0, sign)
    valid = ok & (rise >= 2.0) & (rise <= 5.5)
    twist = np.where(valid, twist, np.nan)
    rise = np.where(valid, rise, np.nan)
    return twist, rise


def frame_pooled(coords_ang: np.ndarray, steps: np.ndarray) -> dict:
    """One-frame pooled SNUPI observable: mean/var of |twist| & rise over all valid steps.

    We pool |twist|: helix chains are walked without a fixed 5'->3' polarity, so the twist
    SIGN is per-chain arbitrary; the magnitude (~34 deg) and its fluctuation (the quantity
    that sets the torsional rigidity) are polarity-independent.
    """
    tw, ri = step_twist_rise(coords_ang, steps)
    m = np.isfinite(tw)
    tw = np.abs(tw[m]); ri = ri[m]
    return {
        "n_steps": int(tw.size),
        "twist_mean": float(np.mean(tw)) if tw.size else float("nan"),
        "twist_var":  float(np.var(tw))  if tw.size else float("nan"),
        "rise_mean":  float(np.mean(ri)) if ri.size else float("nan"),
        "rise_var":   float(np.var(ri))  if ri.size else float("nan"),
    }


# ── local recipe builder (design-FREE: geometric bp pairing + chaining) ───────
def build_recipe(topology_psf: str, coordinate_pdb: str, ref_coor: str = None) -> np.ndarray:
    """Resolve consecutive-bp STEP tuples of C1' atom indices — DESIGN-FREE.

    Returns an (M,4) int array of (a_i, b_i, a_j, b_j) C1' full-atom indices. Pairs bases
    via ``md_health.build_c1_pairs`` (C1'...C1' proximity, ssDNA excluded), then chains
    consecutive base pairs by 3D proximity of their midpoints (a dsDNA step advances the
    bp center ~3.4 A along the helix; the nearest OTHER-helix bp is ~25 A away, so a
    [2.5, 4.5] A midpoint-distance graph has no cross-helix edges). Each connected chain is
    a duplex run; walking it gives the consecutive steps. No design.json needed (these jobs
    don't carry one), which also makes it work for any NAMD job.
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
    pairs = H.build_c1_pairs(psf, pdb, exclude_residues=unpaired)   # C1Pairs(pi, pj, d0)
    u = mda.Universe(str(psf), str(pdb))
    c1 = u.select_atoms("name C1'")
    c1_full = c1.indices                       # full-atom index per C1' selection atom
    c1pos = c1.positions.astype(float)
    a_idx = c1_full[pairs.pi]; b_idx = c1_full[pairs.pj]
    mid = 0.5 * (c1pos[pairs.pi] + c1pos[pairs.pj])   # bp centers (from reference PDB)
    # graph of consecutive bp (midpoint distance ~ rise)
    t = cKDTree(mid)
    cand = t.query_pairs(r=4.5, output_type="ndarray")
    d = np.linalg.norm(mid[cand[:, 0]] - mid[cand[:, 1]], axis=1)
    edges = cand[(d >= 2.5) & (d <= 4.5)]
    adj = defaultdict(list)
    for i, j in edges:
        adj[int(i)].append(int(j)); adj[int(j)].append(int(i))
    # walk each simple chain from a degree-1 end (nicks/crossovers split into separate chains)
    visited = set(); steps = []
    starts = [n for n in range(len(mid)) if len(adj[n]) == 1] + list(range(len(mid)))
    for s in starts:
        if s in visited or len(adj[s]) > 2:
            continue
        prev, cur, chain = None, s, [s]
        visited.add(s)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in visited and len(adj[n]) <= 2]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            chain.append(cur); visited.add(cur)
        for k in range(len(chain) - 1):
            i0, i1 = chain[k], chain[k + 1]
            steps.append((a_idx[i0], b_idx[i0], a_idx[i1], b_idx[i1]))
    steps = np.array(steps, dtype=np.int64)
    # Keep only WELL-FORMED dsDNA steps: mis-chained/mis-paired steps (crossover/nick
    # regions) have non-physical twist/rise. Filter on a real equilibrated frame so the
    # tracked step set is a fixed, clean subset (the per-frame observable stays comparable).
    if ref_coor is not None and len(steps):
        u2 = mda.Universe(str(psf), str(ref_coor))
        tw, ri = step_twist_rise(u2.atoms.positions.astype(float), steps)
        tw = np.abs(tw)
        clean = np.isfinite(tw) & (tw >= 20) & (tw <= 50) & (ri >= 2.9) & (ri <= 4.3)
        steps = steps[clean]
    return steps


if __name__ == "__main__":
    # Self-test: build the recipe for 2xT and verify twist~34 deg, rise~3.4 Ang on a real frame.
    import sys
    sys.path.insert(0, "/home/jojo/Work/NADOC")
    from pathlib import Path
    pk = Path("/media/jojo/Archive/nadoc_jobs/336a067ba241/package/24hb_2xT_namd_solvated")
    psf = str(pk / "24hb_2xT_hmr.psf"); pdb = str(pk / "24hb_2xT.pdb")
    coor = str(pk / "output/24hb_2xT_03_300K_NPT_ENM_k0p01_p10.coor")
    steps = build_recipe(psf, pdb, ref_coor=coor)
    print(f"recipe: {len(steps)} clean consecutive-bp steps")
    import MDAnalysis as mda
    u = mda.Universe(psf, coor)
    tw, ri = step_twist_rise(u.atoms.positions.astype(float), steps)
    m = np.isfinite(tw)
    tw_a = np.abs(tw[m])
    print(f"valid steps: {m.sum()}/{len(tw)}")
    print(f"|twist|: mean={np.mean(tw_a):.1f} deg  std={np.std(tw_a):.1f}  (B-DNA ~34 deg)")
    print(f"rise   : mean={np.mean(ri[m]):.2f} Ang  std={np.std(ri[m]):.2f}  (B-DNA ~3.4 Ang)")
    import numpy as _np
    _np.save("/tmp/claude-1000/-home-jojo-Work-NADOC/011c3b4d-993f-4381-80b1-96348254e906/scratchpad/2xT_recipe.npy", steps)
    print("recipe saved -> 2xT_recipe.npy")
