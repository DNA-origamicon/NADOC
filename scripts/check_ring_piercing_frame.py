#!/usr/bin/env python3
"""Screen an ALREADY-BUILT structure (PSF + any coordinate file) for threaded rings.

``scripts/check_catenation.py`` screens a *design* by rebuilding it.  This screens what a
job actually ran: the packaged seed, or any frame of its trajectory.  Use it to decide
whether an existing run's data is usable — a bond threaded through a nucleotide ring can
never come out, so every frame of that run carries it.

    # the seed a job shipped, and the last frame it reached
    uv run python scripts/check_ring_piercing_frame.py JOB/package/*/2hb_2xT.psf \
        JOB/package/*/2hb_2xT_build.pdb JOB/package/*/output/*_MGHH_only_p100.coor

    # a whole trajectory, every 100th frame
    uv run python scripts/check_ring_piercing_frame.py sys.psf traj.dcd --stride 100

A piercing found in the seed was built in; one that appears only later would be a strand
passage, which is worth investigating on its own (it has never been observed here).

Exit status is 1 if any frame carries a piercing, so it can gate a script.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from backend.core.ring_piercing import SEARCH_NM, ring_names_for, segment_pierces_ring

# Everything here is in ANGSTROM (MDAnalysis' unit), not the nm the model builder uses.
_SEARCH_ANG = SEARCH_NM * 10.0


def _rings_and_bonds(universe, selection: str):
    dna = universe.select_atoms(selection)
    if len(dna) == 0:
        raise SystemExit(f"selection matched no atoms: {selection!r}")

    rings = []
    for res in dna.residues:
        names = list(res.atoms.names)
        for kind, ring in ring_names_for(names):
            rings.append((f"{res.segid}:{res.resname}{res.resid}", kind,
                          [int(res.atoms[names.index(n)].index) for n in ring]))

    idx = set(dna.indices)
    bonds = [(int(a.index), int(b.index)) for a, b in
             ((bd.atoms[0], bd.atoms[1]) for bd in universe.bonds)
             if a.index in idx and b.index in idx
             and not a.name.startswith("H") and not b.name.startswith("H")]
    return dna, rings, bonds


def _scan_frame(u, rings, bonds, label: str, quiet: bool) -> list[str]:
    from scipy.spatial import cKDTree

    pos = u.atoms.positions
    centres = np.array([pos[r].mean(axis=0) for _, _, r in rings])
    mids = np.array([0.5 * (pos[i] + pos[j]) for i, j in bonds])
    near = cKDTree(centres).query_ball_point(mids, r=_SEARCH_ANG)

    hits = []
    for bi, cands in enumerate(near):
        i, j = bonds[bi]
        for ri in cands:
            label_r, kind, serials = rings[ri]
            if i in serials or j in serials:
                continue
            hit, _ = segment_pierces_ring(pos[i], pos[j], pos[serials])
            if not hit:
                continue
            a, b = u.atoms[i], u.atoms[j]
            hits.append(f"{a.segid}:{a.resname}{a.resid}:{a.name}"
                        f"-{b.segid}:{b.resname}{b.resid}:{b.name} through {label_r} {kind}"
                        f"  (bond {np.linalg.norm(pos[i] - pos[j]):.2f} A)")
    flag = "OK " if not hits else "BAD"
    print(f"{flag} {label:<46s} piercings={len(hits)}")
    if not quiet:
        for h in hits:
            print(f"      {h}")
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topology", type=Path, help="PSF (needs bonds)")
    ap.add_argument("coordinates", nargs="+", type=Path,
                    help="PDB / .coor / .dcd — any MDAnalysis-readable coordinates")
    ap.add_argument("--select", default="nucleic or (not resname TIP3 HOH SOD CLA MG MGH)",
                    help="atom selection to treat as DNA")
    ap.add_argument("--stride", type=int, default=1, help="frame stride for trajectories")
    ap.add_argument("--quiet", action="store_true", help="one line per frame")
    args = ap.parse_args(argv)

    import MDAnalysis as mda

    n_bad = 0
    for coord in args.coordinates:
        u = mda.Universe(str(args.topology), str(coord))
        _, rings, bonds = _rings_and_bonds(u, args.select)
        n_frames = len(u.trajectory)
        for k, _ts in enumerate(u.trajectory[::args.stride]):
            label = coord.name if n_frames == 1 else f"{coord.name}[{k * args.stride}]"
            if _scan_frame(u, rings, bonds, label, args.quiet):
                n_bad += 1
    print(f"\n{n_bad} frame(s) carry a threaded ring")
    return 1 if n_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
