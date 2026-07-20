#!/usr/bin/env python3
"""Full extra-base CROSSOVER motif 6x6 stiffness via the Curves+-CALIBRATED Kabsch-3DNA extractor.

The Kabsch base frames reproduce Curves+ per-step to corr~1.0/slope~1.0 on the duplex (curves_kabsch_
calib.py), so their orientation is trustworthy — and unlike Curves+, they apply to a CROSS-HELIX step.
For each design extra-base crossover we build the two crossover-bp Kabsch frames, express the relative
pose in the fixed beam frame (axial = inter-helix offset), and accumulate the per-crossover TEMPORAL 6x6
covariance -> k = kB*T * Cov^-1 = EA/shear + torsion/bending + the 15 couplings. First trustworthy
rotational junction stiffness; replaces fem_solver.py:490's k_rot=0 placeholder.
"""
import sys, numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, '/home/jojo/Work/NADOC')
from pathlib import Path
from dcd_fast import read_layout, read_frame
import snupi_step_params as S
import kabsch_frame_test as KF
from curves_kabsch_calib import _kabsch_arrays_for


def build_xover(psf, pdb, design):
    """All-bp Kabsch arrays + crossover bp-index pairs (design-based) + reference beam frames."""
    import MDAnalysis as mda
    from backend.core import md_health as H, md_protocols as P
    unpaired = P.identify_unpaired_residues(Path(psf), Path(pdb))
    pairs = H.build_c1_pairs(Path(psf), Path(pdb), exclude_residues=unpaired)
    u = mda.Universe(psf, pdb)
    c1 = u.select_atoms("name C1'")
    resA = c1.resindices[pairs.pi]; resB = c1.resindices[pairs.pj]
    c1_a = c1.indices[pairs.pi]; c1_b = c1.indices[pairs.pj]
    r2bp = {int(resA[k]): k for k in range(len(resA))}
    r2bp.update({int(resB[k]): k for k in range(len(resB))})   # map BOTH bases (flank can be either strand)
    have = set(int(x) for x in c1.resindices)
    # crossover steps from the design's true extra bases
    ins = S.extra_base_insert_keys(design, psf)
    is_ins = {int(r.resindex): (str(r.segid), str(r.resid)) in ins for r in u.residues}
    xsteps = []
    for seg in u.segments:
        res = [int(r.resindex) for r in seg.residues if int(r.resindex) in have]
        i = 0
        while i < len(res):
            if is_ins.get(res[i]):
                j = i
                while j < len(res) and is_ins.get(res[j]):
                    j += 1
                if i - 1 >= 0 and j < len(res):
                    b5, b3 = r2bp.get(res[i - 1]), r2bp.get(res[j])
                    if b5 is not None and b3 is not None and b5 != b3:
                        xsteps.append((b5, b3))
                i = j
            else:
                i += 1
    xsteps = np.array(xsteps, dtype=np.int64)
    ka = _kabsch_arrays_for(u, [int(x) for x in resA], [int(x) for x in resB])   # all bp
    return u, c1_a, c1_b, ka, xsteps


def beam_from_ref(coords, c1_a, c1_b, ka, xsteps):
    o, _ = KF.bp_frames_kabsch(coords, c1_a, c1_b, ka)
    ax = S._unit(o[xsteps[:, 1]] - o[xsteps[:, 0]])
    up = np.tile(np.array([0., 0., 1.]), (len(xsteps), 1))
    alt = np.tile(np.array([0., 1., 0.]), (len(xsteps), 1))
    up = np.where((np.abs(np.sum(ax * up, 1)) > 0.9)[:, None], alt, up)
    p1 = S._unit(up - np.sum(up * ax, 1)[:, None] * ax)
    return np.stack([ax, p1, np.cross(ax, p1)], axis=-1)


def main():
    psf, pdb, dcd, design = sys.argv[1:5]
    u, c1_a, c1_b, ka, xsteps = build_xover(psf, pdb, design)
    lay = read_layout(dcd)
    ref_xyz = np.asarray(read_frame(dcd, lay, lay.n_frames - 5)[0], float)
    beam = beam_from_ref(ref_xyz, c1_a, c1_b, ka, xsteps)
    i, j = xsteps[:, 0], xsteps[:, 1]; Bt = np.transpose(beam, (0, 2, 1))
    # reference relative rotation per crossover: fluctuations are measured RELATIVE to this, so the
    # large cross-helix mean angle (log-map ill-conditioned near 180deg) cancels -> small, clean deltas
    o_ref, R_ref = KF.bp_frames_kabsch(ref_xyz, c1_a, c1_b, ka)
    Rrel_ref = R_ref[j] @ np.transpose(R_ref[i], (0, 2, 1))
    print(f"crossovers: {len(xsteps)}")
    nX = len(xsteps); mean = np.zeros((nX, 6)); M2 = np.zeros((nX, 6, 6)); cnt = 0
    for fi in range(lay.n_frames - 2):
        xyz = np.asarray(read_frame(dcd, lay, fi)[0], float)
        o, R = KF.bp_frames_kabsch(xyz, c1_a, c1_b, ka)
        q_t = np.einsum('sab,sb->sa', Bt, o[j] - o[i])              # translation in beam frame (A)
        Rrel = R[j] @ np.transpose(R[i], (0, 2, 1))
        dR = np.transpose(Rrel_ref, (0, 2, 1)) @ Rrel               # fluctuation from equilibrium
        q_r = np.degrees(np.einsum('sab,sb->sa', Bt, S._log_rotvec(dR)))  # small rotation, well-conditioned
        Q = np.concatenate([q_t, q_r], axis=1)
        cnt += 1; d = Q - mean; mean += d / cnt; d2 = Q - mean; M2 += np.einsum('si,sj->sij', d, d2)
    cov = M2 / (cnt - 1)
    S6 = np.array([0.1, 0.1, 0.1, np.pi/180, np.pi/180, np.pi/180]); KT = 4.142
    Cm = np.nanmean(cov, axis=0) * np.outer(S6, S6)
    std = np.sqrt(np.diag(Cm)); K = KT * np.linalg.pinv(Cm)
    L = abs(np.nanmean(mean[:, 0])) * 0.1
    print(f"2xT EXTRA-BASE CROSSOVER 6x6 (Curves+-calibrated Kabsch, {cnt} frames, {nX} xovers, L={L:.2f}nm):")
    print(f"  std: axial {std[0]*10:.2f} perp1 {std[1]*10:.2f} perp2 {std[2]*10:.2f}A | "
          f"tors {np.degrees(std[3]):.1f} bend1 {np.degrees(std[4]):.1f} bend2 {np.degrees(std[5]):.1f}deg")
    print(f"  TRANSLATIONAL: EA {K[0,0]*L:.0f}  GAy {K[1,1]*L:.0f}  GAz {K[2,2]*L:.0f} pN")
    print(f"  ROTATIONAL:    GJ {K[3,3]*L:.0f}  EIy {K[4,4]*L:.0f}  EIz {K[5,5]*L:.0f} pN*nm^2")
    print(f"  key couplings: axial-torsion {K[0,3]*L:.0f}  bend-bend {K[4,5]*L:.0f} pN*nm")
    D = K * L                                     # SNUPI D (moduli): EA/GAy/GAz [pN], GJ/EIy/EIz [pN·nm²]
    out = Path("/media/jojo/Archive/nadoc_jobs/dab9e728433e/extra_base_co_D.npz")
    np.savez(out, D=D, mean=np.nanmean(mean, axis=0), L=L, n_xover=nX, n_frames=cnt)
    print(f"  saved D (6x6 moduli) + geometry -> {out}")


if __name__ == "__main__":
    main()
