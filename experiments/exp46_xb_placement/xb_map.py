#!/usr/bin/env python3
"""Shared mapping: NADOC design  <->  NAMD package PDB/PSF/DCD rows.

The package's own ``{stem}.pdb`` is in PSF/DCD row order (psfgen interleaves hydrogens,
so the heavy-atom AtomisticModel order does NOT line up — see
``junction_topology.package_connector_rows``).  This module reproduces that same
strand walk, but keeps the FULL per-residue key map (nucleotides *and* inserts) so any
atom can be addressed by (helix_id, bp, direction, atom_name) or (crossover_id, k, atom).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _dir_value(d) -> str:
    return d.value if hasattr(d, "value") else str(d)


@dataclass
class Insert:
    crossover_id: str
    k: int                       # 0-based index within this crossover's inserts
    n: int                       # total inserts on this crossover
    base: str
    segid: str
    resid: int
    strand_id: str
    src: tuple                   # (helix_id, bp, dir) 3' exit  (domain end)
    dst: tuple                   # (helix_id, bp, dir) 5' entry (next domain start)


@dataclass
class PackageMap:
    rows: dict = field(default_factory=dict)      # (segid, resid, name) -> row index
    nt: dict = field(default_factory=dict)        # (helix, bp, dir) -> (segid, resid)
    inserts: list = field(default_factory=list)   # list[Insert]
    n_atoms: int = 0

    def row(self, segid, resid, name):
        return self.rows.get((segid, resid, name))

    def nt_row(self, key, name):
        sr = self.nt.get(key)
        return None if sr is None else self.rows.get((sr[0], sr[1], name))


def _junction_index(design) -> dict:
    """frozenset({(helix,bp,dir), ...}) -> (crossover_id, extra_bases)."""
    idx = {}
    for xo in design.crossovers:
        ka = (xo.half_a.helix_id, xo.half_a.index, _dir_value(xo.half_a.strand))
        kb = (xo.half_b.helix_id, xo.half_b.index, _dir_value(xo.half_b.strand))
        idx[frozenset((ka, kb))] = (xo.id, xo.extra_bases or "")
    for fl in design.forced_ligations:
        ka = (fl.three_prime_helix_id, fl.three_prime_bp, _dir_value(fl.three_prime_direction))
        kb = (fl.five_prime_helix_id, fl.five_prime_bp, _dir_value(fl.five_prime_direction))
        idx[frozenset((ka, kb))] = (fl.id, fl.extra_bases or "")
    return idx


def _strand_chain_id(index: int) -> str:
    """Return the chain id assigned by ``atomistic.build_atomistic_model``.

    Full psfgen packages sort those chain ids lexicographically before assigning
    ``D000``, ``D001``, ... segment ids.  Design order and package segment order
    therefore diverge after strand Z (``A, AA, AB, ..., B, ...``).
    """
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < 26:
        return letters[index]
    return letters[index // 26 - 1] + letters[index % 26]


def build_package_map(design, package_pdb: str | Path) -> PackageMap:
    pm = PackageMap()
    per_seg: dict = {}
    n = 0
    for line in Path(package_pdb).read_text().splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        row = n
        n += 1
        seg = line[72:76].strip()
        if not seg.startswith("D"):
            continue
        resid = int(line[22:26])
        pm.rows[(seg, resid, line[12:16].strip())] = row
        per_seg.setdefault(seg, set()).add(resid)
    pm.n_atoms = n

    segnames = sorted(per_seg)
    junctions = _junction_index(design)

    # ``namd_topology._write_segment_pdbs`` sorts atomistic chain ids before
    # assigning psfgen segment ids.  This is identical to design order for small
    # fixtures, but is essential for 24hb (76 strands).
    package_strands = sorted(
        enumerate(design.strands), key=lambda item: _strand_chain_id(item[0])
    )
    for si, (_design_index, strand) in enumerate(package_strands):
        if si >= len(segnames):
            break
        seg = segnames[si]
        resid = 0
        doms = strand.domains
        for di, dom in enumerate(doms):
            step = 1 if dom.end_bp >= dom.start_bp else -1
            for bp in range(dom.start_bp, dom.end_bp + step, step):
                resid += 1
                pm.nt[(dom.helix_id, bp, _dir_value(dom.direction))] = (seg, resid)
            if di + 1 < len(doms):
                nxt = doms[di + 1]
                ka = (dom.helix_id, dom.end_bp, _dir_value(dom.direction))
                kb = (nxt.helix_id, nxt.start_bp, _dir_value(nxt.direction))
                xid, extra = junctions.get(frozenset((ka, kb)), (None, ""))
                for k, ch in enumerate(extra):
                    resid += 1
                    pm.inserts.append(Insert(
                        crossover_id=xid, k=k, n=len(extra), base=ch,
                        segid=seg, resid=resid, strand_id=strand.id,
                        src=ka, dst=kb,
                    ))
        if resid != len(per_seg[seg]):
            raise ValueError(
                f"{seg}: walked {resid} residues but the package PDB has "
                f"{len(per_seg[seg])} — package residue layout changed")
    return pm


def load_design(path: str | Path):
    from backend.core.models import Design
    return Design.model_validate_json(Path(path).read_text())


class FrameJoiner:
    """Rebuild ONE consistent periodic image of the DNA from a NAMD ``wrapAll on`` frame.

    ``wrapAll`` wraps each covalent fragment by its own centre, so (a) a fragment can be
    split across the boundary and (b) two fragments can sit in different images.  The
    solute here is ~45 x 47 x 87 A in a ~38 x 57 x 97 A box, so a single-atom
    minimum-image fix is NOT enough (the true span exceeds half the box in every
    dimension).  Instead:

    1. bond-based ``unwrap(compound='fragments')`` makes every fragment whole (exact —
       no covalent bond is longer than half a box);
    2. each fragment is then shifted into the anchor fragment's image by the MODAL box
       shift over every base pair it shares with an already-placed fragment (modal, so a
       melted pair cannot outvote the intact ones).
    """

    def __init__(self, universe, pm, design, dna_selection="nucleic or segid D000 D001 D002"):
        import numpy as _np
        self.pm = pm
        try:
            self.dna = universe.select_atoms(dna_selection)
        except Exception:
            self.dna = universe.select_atoms("segid D000 D001 D002")
        self.off = int(self.dna.indices.min())
        if not _np.array_equal(self.dna.indices,
                               _np.arange(self.off, self.off + len(self.dna))):
            raise ValueError("DNA atom indices are not contiguous")
        self.frags = list(self.dna.fragments)

        # which fragment owns each (helix, bp, dir) key
        row_to_frag = {}
        for fi, f in enumerate(self.frags):
            for idx in f.indices:
                row_to_frag[int(idx)] = fi
        self.key_frag = {}
        for key, (seg, rid) in pm.nt.items():
            r = pm.rows.get((seg, rid, "C1'"))
            if r is not None and r in row_to_frag:
                self.key_frag[key] = (row_to_frag[r], r)

        # ordered placement: biggest fragment first, then whoever shares base pairs
        order = sorted(range(len(self.frags)), key=lambda i: -len(self.frags[i]))
        placed = {order[0]}
        self.plan = []                            # (frag_index, [(row_here, row_there)])
        remaining = order[1:]
        while remaining:
            progressed = False
            for fi in list(remaining):
                pairs = []
                for (hel, bp, d), (of, row) in self.key_frag.items():
                    if of != fi:
                        continue
                    opp = "REVERSE" if d == "FORWARD" else "FORWARD"
                    other = self.key_frag.get((hel, bp, opp))
                    if other and other[0] in placed:
                        pairs.append((row, other[1]))
                if pairs:
                    self.plan.append((fi, pairs))
                    placed.add(fi)
                    remaining.remove(fi)
                    progressed = True
            if not progressed:                    # unpaired fragment: leave as-is
                for fi in remaining:
                    self.plan.append((fi, []))
                break
        self.frag_local = [f.indices - self.off for f in self.frags]

    def positions(self, box):
        """Joined DNA coordinates, indexed by package row (DNA rows start at 0)."""
        import numpy as _np
        pos = self.dna.unwrap(compound="fragments", inplace=False)
        for fi, pairs in self.plan:
            if not pairs:
                continue
            shifts = _np.array([
                _np.round((pos[b - self.off] - pos[a - self.off]) / box)
                for a, b in pairs])
            uniq, counts = _np.unique(shifts, axis=0, return_counts=True)
            shift = uniq[int(_np.argmax(counts))] * box
            pos[self.frag_local[fi]] += shift
        return pos


def pdb_coords(package_pdb: str | Path) -> np.ndarray:
    xyz = []
    for line in Path(package_pdb).read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            xyz.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return np.asarray(xyz, dtype=float)
