#!/usr/bin/env python3
"""Cut a clean 12-bp dsDNA fragment from a post-eq 1xT frame -> PDB for Curves+, + the matching
recipe steps for MY extractor, so I can diff {shift,slide,rise,tilt,roll,twist} step-by-step and
resolve the convention (roll axis / sign) against a community-standard reference.
"""
import sys, numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, '/home/jojo/Work/NADOC')
from pathlib import Path
import MDAnalysis as mda
from dcd_fast import read_layout, read_frame
from backend.core import md_health as H, md_protocols as P

psf, pdb, dcd, out_prefix = sys.argv[1:5]
frame_i = int(sys.argv[5]) if len(sys.argv) > 5 else None

unpaired = P.identify_unpaired_residues(Path(psf), Path(pdb))
pairs = H.build_c1_pairs(Path(psf), Path(pdb), exclude_residues=unpaired)
u = mda.Universe(psf, pdb)
c1 = u.select_atoms("name C1'")
resA = c1.resindices[pairs.pi]; resB = c1.resindices[pairs.pj]
res_to_bp = {int(resA[k]): k for k in range(len(resA))}
res_to_bp.update({int(resB[k]): k for k in range(len(resB))})

# find a strand segment with >=14 consecutive PAIRED residues; take the middle 12 bp
best = None
for seg in u.segments:
    rid = [int(r.resindex) for r in seg.residues if r.atoms.select_atoms("name C1'").n_atoms]
    run = []
    for r in rid:
        if r in res_to_bp:
            run.append(r)
            if len(run) >= 14 and best is None:
                best = run[:]
        else:
            if best is None and len(run) >= 14:
                best = run[:]
            run = []
    if best:
        break
if not best:
    print("no clean 14-bp duplex run found"); sys.exit(1)
mid = len(best) // 2
strandA = best[mid - 6:mid + 6]                       # 12 consecutive bp on strand A
bps = [res_to_bp[r] for r in strandA]
strandB = [int(resB[b]) if int(resA[b]) == r else int(resA[b]) for b, r in zip(bps, strandA)]
print(f"fragment: strandA resindices {strandA[0]}..{strandA[-1]}  ({len(bps)} bp)")

# load a post-eq frame's coordinates
lay = read_layout(dcd)
fi = frame_i if frame_i is not None else lay.n_frames - 5
xyz, _ = read_frame(dcd, lay, fi)
u.atoms.positions = np.asarray(xyz, float)
print(f"using DCD frame {fi} of {lay.n_frames}")

# write the 24-residue fragment PDB (strand A 5'->3', then strand B) with clean renumbering
frag_res = strandA + strandB[::-1]                    # antiparallel: B reversed
sel = u.residues[frag_res].atoms
# renumber: MDAnalysis writes original resids; give Curves+ contiguous ids via segid A/B
import MDAnalysis.transformations  # noqa
ag = sel
# tag chains: first 12 -> A, next 12 -> B
frag_pdb = f"{out_prefix}.pdb"
with mda.Writer(frag_pdb, n_atoms=ag.n_atoms) as w:
    w.write(ag)
print(f"wrote {frag_pdb}  ({ag.n_atoms} atoms, {len(frag_res)} residues)")

# save the recipe (full-structure indices) for MY extractor on the same steps
c1_full = c1.indices
c1_a = c1_full[[pairs.pi[b] for b in bps]]; c1_b = c1_full[[pairs.pj[b] for b in bps]]
# ring atoms per bp (both bases) for base-normal + kabsch extractors
def ring_idx(resindices):
    RING = ("N1", "C2", "N3", "C4", "C5", "C6")
    out = []
    for ri in resindices:
        r = u.residues[ri]
        out.append([r.atoms.select_atoms(f"name {nm}")[0].index for nm in RING])
    return np.array(out)
np.savez(f"{out_prefix}_steps.npz",
         c1_a=c1_a, c1_b=c1_b,
         ring_a=ring_idx([int(resA[b]) for b in bps]),
         ring_b=ring_idx([int(resB[b]) for b in bps]),
         steps=np.array([[k, k + 1] for k in range(len(bps) - 1)], dtype=np.int64),
         frame=fi)
print(f"wrote {out_prefix}_steps.npz  ({len(bps)-1} steps)")
