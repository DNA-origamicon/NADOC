#!/usr/bin/env python3
"""Calibrate a Kabsch-3DNA-frame step extractor against Curves+ on a duplex fragment, per-step.

Runs BOTH engines on the SAME 12-bp fragment over many frames and reports, per parameter, the linear
fit (my = a*curves + b) + correlation. a~1,b~0 = matched convention; a~-1 = sign flip; b!=0 = offset.
Once the Kabsch extractor matches Curves+ on the duplex, the SAME extractor can be applied to the
cross-helix crossover step (which Curves+ cannot analyze). This is the calibration the earlier
analytic-only self-tests could not provide.
"""
import sys, os, tempfile, numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, '/home/jojo/Work/NADOC')
from pathlib import Path
from dcd_fast import read_layout, read_frame
import snupi_step_params as S
import curves_stiffness as CS
import kabsch_frame_test as KF


def fragment_bp(psf, pdb, dcd, nbp=8):
    """Pick a clean duplex fragment; return atom-level PDB meta + per-bp Kabsch data."""
    import MDAnalysis as mda
    from backend.core import md_health as H, md_protocols as P
    lay = read_layout(dcd)
    sel_xyz = np.asarray(read_frame(dcd, lay, lay.n_frames - 5)[0], float)
    meta = CS.pick_wc_fragment(psf, pdb, nbp=nbp, sel_coords=sel_xyz)   # atom-level (for Curves+ PDB)
    # redo pairing to get the bp indices of THIS fragment (strand A residues in meta['seq'] order)
    unpaired = P.identify_unpaired_residues(Path(psf), Path(pdb))
    pairs = H.build_c1_pairs(Path(psf), Path(pdb), exclude_residues=unpaired)
    u = mda.Universe(psf, pdb)
    c1 = u.select_atoms("name C1'")
    resA = c1.resindices[pairs.pi]; resB = c1.resindices[pairs.pj]
    # the fragment's strand-A resids are meta['rid']==1..nbp on chain 'A'; recover resindices
    strandA_res = [ri for local, ri in enumerate(_frag_resindices(u, meta)) if local < nbp]
    r2bp = {int(resA[k]): k for k in range(len(resA))}
    bps = [r2bp[r] for r in strandA_res]
    c1_a = c1.indices[[pairs.pi[b] for b in bps]]
    c1_b = c1.indices[[pairs.pj[b] for b in bps]]
    # Kabsch ring arrays for these bp (both bases), grouped by pur/pyr
    ka = _kabsch_arrays_for(u, [int(resA[b]) for b in bps], [int(resB[b]) for b in bps])
    return meta, c1_a, c1_b, ka, nbp


def _frag_resindices(u, meta):
    """Recover the resindices of the fragment residues (in the order they were written to the PDB)."""
    # meta doesn't store resindices directly; re-derive from atom_idx (first atom of each residue block)
    seen = []
    last = None
    for ai in meta["atom_idx"]:
        ri = int(u.atoms[ai].residue.resindex)
        if ri != last:
            seen.append(ri); last = ri
    return seen


def _kabsch_arrays_for(u, resA_list, resB_list):
    resmap = {}
    for a in u.atoms:
        resmap.setdefault(a.residue.resindex, {})[a.name] = a.index
    ka = {}
    for side, rlist in (('a', resA_list), ('b', resB_list)):
        for grp in ('PUR', 'PYR'):
            names = list(KF._IDEAL[grp].keys())
            rows, at = [], []
            for k, ri in enumerate(rlist):
                if KF.base_ideal(u.residues[ri].resname) != grp:
                    continue
                m = resmap.get(ri, {})
                if all(nm in m for nm in names):
                    rows.append(k); at.append([m[nm] for nm in names])
            ka[f'{side}_{grp}_rows'] = np.array(rows, dtype=int)
            ka[f'{side}_{grp}_at'] = np.array(at, dtype=int) if at else np.zeros((0, len(names)), int)
    return ka


def main():
    psf, pdb, dcd = sys.argv[1:4]
    nframes = int(sys.argv[4]) if len(sys.argv) > 4 else 80
    nbp = int(sys.argv[5]) if len(sys.argv) > 5 else 8
    meta, c1_a, c1_b, ka, nbp = fragment_bp(psf, pdb, dcd, nbp=nbp)
    steps = np.array([[k, k + 1] for k in range(nbp - 1)], dtype=np.int64)
    print(f"fragment: {'-'.join(s[0] for s in meta['seq'])}  ({nbp} bp, {nbp-1} steps)")
    lay = read_layout(dcd)
    fr = list(range(max(0, lay.n_frames - nframes), lay.n_frames - 2))
    myP, curP = [], []
    with tempfile.TemporaryDirectory() as wd:
        pdbp = os.path.join(wd, "frag.pdb")
        for fi in fr:
            xyz = np.asarray(read_frame(dcd, lay, fi)[0], float)
            CS.write_frag_pdb(xyz, meta, pdbp)
            C = CS.run_curves(pdbp, nbp, wd)
            if C is None or len(C) != nbp - 1:
                continue
            o, R = KF.bp_frames_kabsch(xyz, c1_a, c1_b, ka)
            M = S.step_params(o, R, steps)             # my Kabsch step params
            myP.append(M); curP.append(C)
    myP = np.array(myP); curP = np.array(curP)         # (F, nbp-1, 6)
    print(f"frames compared: {len(myP)}")
    lab = ['shift', 'slide', 'rise', 'tilt', 'roll', 'twist']
    print(f"{'param':6} {'my_mean':>8} {'cur_mean':>8} {'corr':>6} {'slope':>7} {'intcpt':>7}")
    for k, nm in enumerate(lab):
        m = myP[:, :, k].ravel(); c = curP[:, :, k].ravel()
        good = np.isfinite(m) & np.isfinite(c)
        m, c = m[good], c[good]
        if np.std(c) > 1e-6 and np.std(m) > 1e-6:
            a, b = np.polyfit(c, m, 1); corr = np.corrcoef(m, c)[0, 1]
        else:
            a = b = corr = float('nan')
        print(f"{nm:6} {m.mean():8.2f} {c.mean():8.2f} {corr:6.2f} {a:7.2f} {b:7.2f}")


if __name__ == "__main__":
    main()
