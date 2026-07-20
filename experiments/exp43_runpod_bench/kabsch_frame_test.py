#!/usr/bin/env python3
"""Validate the 3DNA standard-frame (Kabsch-to-idealized-base) de-noising on the 1xT duplex.

If the base orientation comes from a RIGID least-squares fit of the base's known idealized geometry
(Olson 2001) to its actual ring atoms — instead of a 6-atom plane-fit normal — the per-frame rotational
noise should drop and the duplex bend/twist Lp should recover ~50/75 nm (vs ~21-29 with the plane fit).
"""
import sys, numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, '/home/jojo/Work/NADOC')
import snupi_step_params as S
from dcd_fast import read_layout, read_frame

# Olson-2001 idealized base ring coords (Å, z=0), atom -> (x,y). Ring atoms only.
_IDEAL = {
    'PUR': {'N9': (-1.289, 4.551), 'C8': (0.023, 4.962), 'N7': (0.870, 3.969), 'C5': (0.071, 2.833),
            'C4': (-1.265, 3.177), 'N3': (-2.342, 2.364), 'C2': (-1.999, 1.087), 'N1': (-0.700, 0.641),
            'C6': (0.424, 1.460)},
    'PYR': {'N1': (-1.284, 4.500), 'C2': (-1.462, 3.135), 'N3': (-0.298, 2.407), 'C4': (0.994, 2.897),
            'C5': (1.106, 4.338), 'C6': (-0.024, 5.057)},
}
_PUR = {'DA', 'DG', 'ADE', 'GUA', 'A', 'G', 'RA', 'RG'}


def base_ideal(resname):
    return 'PUR' if resname.upper() in _PUR else 'PYR'


def _kabsch_R(actual, ideal):
    """Batched Kabsch: rotation mapping ideal->actual + the fitted ORIGIN (where ideal (0,0,0) lands =
    the 3DNA standard base-frame origin). Returns (R (K,3,3), origin (K,3))."""
    ac = actual.mean(1, keepdims=True); ic = ideal.mean(1, keepdims=True)
    A = actual - ac; I = ideal - ic
    H = np.einsum('kni,knj->kij', I, A)          # (K,3,3) cross-covariance
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(np.einsum('kij,kjl->kil', Vt.transpose(0, 2, 1), U.transpose(0, 2, 1))))
    D = np.tile(np.eye(3), (len(H), 1, 1)); D[:, 2, 2] = d
    R = np.einsum('kij,kjl,klm->kim', Vt.transpose(0, 2, 1), D, U.transpose(0, 2, 1))
    origin = ac[:, 0, :] - np.einsum('kij,kj->ki', R, ic[:, 0, :])   # fitted position of ideal origin
    return R, origin                              # columns = ideal frame axes in actual/lab frame


def base_frames_kabsch(coords, atom_idx, ideal_xy):
    """coords (N,3); atom_idx (K,n); ideal_xy (n,2) -> full rigid base frames R (K,3,3)."""
    actual = coords[atom_idx]
    ideal = np.concatenate([ideal_xy, np.zeros((len(ideal_xy), 1))], axis=1)
    return _kabsch_R(actual, np.tile(ideal, (len(actual), 1, 1)))


_FLIP = np.diag([1.0, -1.0, -1.0])               # complementary base: 180deg about x (3DNA convention)


def bp_frames_kabsch(coords, c1_a, c1_b, ka):
    """Full 3DNA bp frame: geodesic-average of base I's frame and the FLIPPED base II frame; origin =
    average of the two 3DNA base-frame origins (NOT the C1' midpoint — that made rise/slide mismatch)."""
    M = len(c1_a)
    Ra = np.tile(np.eye(3), (M, 1, 1)); Rb = np.tile(np.eye(3), (M, 1, 1))
    oa = np.zeros((M, 3)); ob = np.zeros((M, 3))
    for side, Rout, oout in (('a', Ra, oa), ('b', Rb, ob)):
        for grp in ('PUR', 'PYR'):
            idx = ka[f'{side}_{grp}_rows']
            if len(idx):
                R, o = base_frames_kabsch(coords, ka[f'{side}_{grp}_at'], np.array(list(_IDEAL[grp].values())))
                Rout[idx] = R; oout[idx] = o
    Rbf = Rb @ _FLIP                              # flip complementary base into base I's convention
    rel = np.transpose(Ra, (0, 2, 1)) @ Rbf
    Rbp = Ra @ S._exp_rotvec(0.5 * S._log_rotvec(rel))
    return 0.5 * (oa + ob), Rbp


def build_kabsch_arrays(u, pairs):
    """Per bp side, grouped ring atom indices matching the idealized atom order, split by pur/pyr."""
    c1 = u.select_atoms("name C1'")
    # residue -> {atomname: index}
    resmap = {}
    for a in u.atoms:
        resmap.setdefault(a.residue.resindex, {})[a.name] = a.index
    ka = {}
    for side, sel in (('a', pairs.pi), ('b', pairs.pj)):
        ri = c1.resindices[sel]
        rn = [c1[s].residue.resname for s in sel]
        for grp in ('PUR', 'PYR'):
            names = list(_IDEAL[grp].keys())
            rows = [k for k in range(len(sel)) if base_ideal(rn[k]) == grp]
            at = []
            good = []
            for k in rows:
                m = resmap.get(int(ri[k]), {})
                if all(nm in m for nm in names):
                    at.append([m[nm] for nm in names]); good.append(k)
            ka[f'{side}_{grp}_rows'] = np.array(good, dtype=int)
            ka[f'{side}_{grp}_at'] = np.array(at, dtype=int) if at else np.zeros((0, len(names)), int)
    return ka


def main():
    psf, pdb, ref, design, dcd = sys.argv[1:6]
    import MDAnalysis as mda
    from backend.core import md_health as H, md_protocols as P
    from pathlib import Path
    unpaired = P.identify_unpaired_residues(Path(psf), Path(pdb))
    pairs = H.build_c1_pairs(Path(psf), Path(pdb), exclude_residues=unpaired)
    u = mda.Universe(psf, pdb)
    c1 = u.select_atoms("name C1'")
    c1_a = c1.indices[pairs.pi]; c1_b = c1.indices[pairs.pj]
    ka = build_kabsch_arrays(u, pairs)
    # duplex steps: reuse build_recipe_full's chaining via a helix-axis recipe already built
    z = np.load(sys.argv[6]); dup_steps = z['dup_steps']
    lay = read_layout(dcd); nf = lay.n_frames
    frames = list(range(max(0, nf - 250), nf - 2))
    nD = len(dup_steps); mean = np.zeros((nD, 6)); M2 = np.zeros((nD, 6, 6)); cnt = 0
    for fi in frames:
        xyz, _ = read_frame(dcd, lay, fi); xyz = np.asarray(xyz, float)
        o, R = bp_frames_kabsch(xyz, c1_a, c1_b, ka)
        q = S.step_params(o, R, dup_steps)
        cnt += 1; d = q - mean; mean += d / cnt; d2 = q - mean; M2 += np.einsum('si,sj->sij', d, d2)
    cov = M2 / (cnt - 1)
    S6 = np.array([0.1, 0.1, 0.1, np.pi/180, np.pi/180, np.pi/180]); KT = 4.142
    Cm = np.nanmean(cov, axis=0) * np.outer(S6, S6); K = KT * np.linalg.inv(Cm); std = np.sqrt(np.diag(Cm))
    EA = K[2, 2]*0.34; GJ = K[5, 5]*0.34; EIy = K[3, 3]*0.34; EIz = K[4, 4]*0.34
    print(f"KABSCH (3DNA) + TEMPORAL ({cnt} frames):")
    print(f"  temporal std: twist {np.degrees(std[5]):.1f} roll {np.degrees(std[4]):.1f} tilt {np.degrees(std[3]):.1f} rise {std[2]*10:.2f}A (B-DNA ~5/6/4/0.3)")
    print(f"  EA {EA:.0f} pN | GJ {GJ:.0f} EIy {EIy:.0f} EIz {EIz:.0f} pN*nm^2")
    print(f"  twist Lp {GJ/KT:.0f} nm  bend Lp {EIz/KT:.0f} nm  tilt Lp {EIy/KT:.0f} nm  (B-DNA twist~75 bend~50)")
    print(f"  twist-stretch {K[2,5]*0.34:.0f} pN*nm (SNUPI ~ -277)")


if __name__ == "__main__":
    main()
