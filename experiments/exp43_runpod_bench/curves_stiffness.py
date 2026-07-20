#!/usr/bin/env python3
"""Per-frame Curves+ -> temporal covariance -> regular_bp 6x6 stiffness. The field-standard engine.

Picks a CLEAN Watson-Crick-complementary 12-bp duplex fragment (not a mispaired region), then for each
DCD frame writes a star-atom-name PDB of that fragment, runs Cur+, parses the inter-BP step params, and
accumulates the per-step TEMPORAL covariance. k = kB*T * Cov^-1 (nm/rad) -> EA/GJ/EI + persistence lengths
+ the twist-stretch coupling, comparable to SNUPI's regular_bp values.
"""
import sys, os, subprocess, tempfile, numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, '/home/jojo/Work/NADOC')
from pathlib import Path
from dcd_fast import read_layout, read_frame

CUR = os.path.expanduser("~/miniforge3/envs/curves/bin/Cur+")
LIB = os.path.expanduser("~/miniforge3/envs/curves/.curvesplus/standard")
_WC = {("ADE", "THY"), ("THY", "ADE"), ("GUA", "CYT"), ("CYT", "GUA"),
       ("DA", "DT"), ("DT", "DA"), ("DG", "DC"), ("DC", "DG"),
       ("A", "T"), ("T", "A"), ("G", "C"), ("C", "G")}


def pick_wc_fragment(psf, pdb, nbp=12, sel_coords=None):
    """Return metadata for a clean nbp-duplex fragment. The 24hb atomistic build used a NON-design
    (arbitrary) sequence, so WC resname-complementarity is not expected — the geometric C1' pairs
    (~10 A) ARE the real duplex partners; we pick a run whose steps are geometrically clean B-DNA
    on the SELECTION frame (an equilibrated DCD frame if sel_coords given, else the PDB)."""
    import MDAnalysis as mda
    from backend.core import md_health as H, md_protocols as P
    unpaired = P.identify_unpaired_residues(Path(psf), Path(pdb))
    pairs = H.build_c1_pairs(Path(psf), Path(pdb), exclude_residues=unpaired)
    u = mda.Universe(psf, pdb)
    if sel_coords is not None:
        u.atoms.positions = sel_coords            # select on an equilibrated frame, not the raw build
    c1 = u.select_atoms("name C1'")
    resA = c1.resindices[pairs.pi]; resB = c1.resindices[pairs.pj]
    r2bp = {int(resA[k]): k for k in range(len(resA))}
    rn = {int(r.resindex): r.resname for r in u.residues}
    cpos = c1.positions
    # geometrically clean step = consecutive bp with midpoint spacing ~rise (2.9-4.3 A) and C1'-C1'
    # ~10.4 A on both bp (well-formed WC geometry, whatever the sequence)
    mid = 0.5 * (cpos[pairs.pi] + cpos[pairs.pj])
    d0 = np.linalg.norm(cpos[pairs.pi] - cpos[pairs.pj], axis=1)
    best = None
    for seg in u.segments:
        rid = [int(r.resindex) for r in seg.residues if r.atoms.select_atoms("name C1'").n_atoms]
        run = []
        prev_bp = None
        for r in rid:
            b = r2bp.get(r)
            ok = (b is not None) and (8.5 < d0[b] < 12.0)   # loosened for strained (2xT) bundles
            if ok and prev_bp is not None:
                step = np.linalg.norm(mid[b] - mid[prev_bp])
                ok = 2.5 < step < 5.0
            if ok:
                run.append(b)
                if len(run) >= nbp:
                    best = run[-nbp:]; break
            else:
                run = [b] if (b is not None and 8.5 < d0[b] < 12.0) else []
            prev_bp = b
        if best:
            break
    if not best:
        raise RuntimeError("no clean duplex run found")
    # residues: strand A (12 in 5'->3'), strand B (their partners, reversed for antiparallel)
    strandA = [int(resA[b]) for b in best]
    strandB = [int(resB[b]) for b in best][::-1]
    frag_res = strandA + strandB
    # per-atom metadata for PDB writing (star names), ordered by residue then atom
    idx, names, rname, rid_out, chain = [], [], [], [], []
    for local, ri in enumerate(frag_res):
        res = u.residues[ri]
        ch = "A" if local < nbp else "B"
        rsq = (local % nbp) + 1                          # 1..12 per chain
        for a in res.atoms:
            if a.name.startswith("H"):                    # drop H (Curves+ uses heavy atoms)
                continue
            idx.append(a.index); names.append(a.name.replace("'", "*"))
            rname.append(res.resname); rid_out.append(rsq); chain.append(ch)
    return dict(atom_idx=np.array(idx), names=names, rname=rname, rid=rid_out, chain=chain,
                nbp=nbp, seq=[rn[r] for r in strandA])


def write_frag_pdb(coords, meta, path):
    """Write a star-atom PDB for one frame's fragment coords (strict PDB columns Curves+ parses)."""
    xyz = coords[meta["atom_idx"]]
    with open(path, "w") as f:
        for s, (nm, rn, ri, ch, p) in enumerate(zip(meta["names"], meta["rname"], meta["rid"],
                                                     meta["chain"], xyz), start=1):
            an = f" {nm:<3s}" if len(nm) <= 3 else f"{nm:<4s}"   # cols 13-16
            f.write(f"ATOM  {s:5d} {an} {rn:<3s} {ch}{ri:4d}    "  # +altLoc space (col 17)
                    f"{p[0]:8.3f}{p[1]:8.3f}{p[2]:8.3f}  1.00  0.00\n")
        f.write("END\n")


def run_curves(pdb_path, nbp, workdir):
    lis = os.path.join(workdir, "cur")
    for f in Path(workdir).glob("cur*"):        # clean stale outputs — Cur+ won't overwrite them,
        f.unlink()                              # so a failed re-run would leave the previous .lis
    inp = (f"&inp\n file={pdb_path},\n lis={lis},\n lib={LIB},\n fit=.t.,\n&end\n"
           f"2 1 -1 0 0\n1:{nbp}\n{2*nbp}:{nbp+1}\n")
    subprocess.run([CUR], input=inp, text=True, capture_output=True, cwd=workdir, timeout=60)
    out = lis + ".lis"
    if not os.path.exists(out):
        return None
    lines = Path(out).read_text().splitlines()
    try:
        i = next(k for k, l in enumerate(lines) if "(C) Inter-BP" in l)
    except StopIteration:
        return None
    rows = []
    for l in lines[i + 1:]:
        s = l.strip()
        if not s:
            if rows:
                break
            continue
        if ")" in s and "/" in s:
            toks = s.split()
            try:
                vals = [float(x) for x in toks[-8:]]
                rows.append(vals[:6])                     # Shift Slide Rise Tilt Roll Twist
            except ValueError:
                continue
    return np.array(rows) if rows else None


def main():
    psf, pdb, dcd = sys.argv[1:4]
    nframes = int(sys.argv[4]) if len(sys.argv) > 4 else 60
    nbp = int(sys.argv[5]) if len(sys.argv) > 5 else 12
    lay0 = read_layout(dcd)
    sel_xyz, _ = read_frame(dcd, lay0, lay0.n_frames - 5)     # select fragment on an equilibrated frame
    meta = pick_wc_fragment(psf, pdb, nbp=nbp, sel_coords=np.asarray(sel_xyz, float))
    print(f"WC fragment seq: {'-'.join(s[0] for s in meta['seq'])}  ({meta['nbp']} bp, {len(meta['atom_idx'])} atoms)")
    lay = read_layout(dcd)
    fr = list(range(max(0, lay.n_frames - nframes), lay.n_frames - 2))
    nS = meta["nbp"] - 1
    mean = np.zeros((nS, 6)); M2 = np.zeros((nS, 6, 6)); cnt = 0
    with tempfile.TemporaryDirectory() as wd:
        pdbp = os.path.join(wd, "frag.pdb")
        for fi in fr:
            xyz, _ = read_frame(dcd, lay, fi)
            write_frag_pdb(np.asarray(xyz, float), meta, pdbp)
            P = run_curves(pdbp, meta["nbp"], wd)
            if P is None or len(P) != nS:
                continue
            cnt += 1; d = P - mean; mean += d / cnt; d2 = P - mean; M2 += np.einsum("si,sj->sij", d, d2)
    print(f"frames analyzed by Curves+: {cnt}/{len(fr)}")
    if cnt < 10:
        print("too few — check Curves+ output"); return
    cov = M2 / (cnt - 1)
    S6 = np.array([0.1, 0.1, 0.1, np.pi/180, np.pi/180, np.pi/180]); KT = 4.142
    Cm = np.nanmean(cov, axis=0) * np.outer(S6, S6)      # mean per-step temporal cov (nm/rad)
    std = np.sqrt(np.diag(Cm))
    print(f"CURVES+ regular_bp ({cnt} frames, seq {'-'.join(s[0] for s in meta['seq'])}):")
    print(f"  step means: twist {mean[:,5].mean():.1f} rise {mean[:,2].mean():.2f}A (B-DNA ~34/3.3)")
    print(f"  temporal std: shift {std[0]*10:.2f} slide {std[1]*10:.2f} rise {std[2]*10:.2f}A | "
          f"tilt {np.degrees(std[3]):.1f} roll {np.degrees(std[4]):.1f} twist {np.degrees(std[5]):.1f}deg "
          f"(B-DNA ~0.7/0.6/0.3A, ~4/6/5deg)")
    ev = np.linalg.eigvalsh(Cm)
    print(f"  cov eigenvalues: {np.array2string(ev, precision=4)}  (singular if any ~0)")
    K = KT * np.linalg.pinv(Cm)                          # pseudo-inverse (robust to Curves+ rounding rank loss)
    h = 0.34
    EA, GJ, EIy, EIz = K[2, 2]*h, K[5, 5]*h, K[3, 3]*h, K[4, 4]*h
    print(f"  EA {EA:.0f} pN | GJ {GJ:.0f} EIy {EIy:.0f} EIz {EIz:.0f} pN*nm^2")
    print(f"  twist Lp {GJ/KT:.0f} nm  bend Lp(roll) {EIz/KT:.0f} nm  tilt Lp {EIy/KT:.0f} nm  (B-DNA twist~75 bend~50)")
    print(f"  twist-stretch coupling {K[2,5]*h:.0f} pN*nm  (SNUPI regular_bp ~ -277)")


if __name__ == "__main__":
    main()
