#!/usr/bin/env python3
"""mrdna's interhelical "push bond" rule, applied to a NADOC lattice design.

Transcribed from ``mrdna/segmentmodel.py::write_atomic_ENM`` (the ``push_bonds`` block).
These are the k=1.0 kcal/mol/A^2, r0=31 A phosphate-phosphate bonds that hold helices at
their proper spacing in vacuum, where Coulomb is truncated at 10 A and cannot.

THE RULE (verbatim in behaviour, not in code):
  1. Only pairs of dsDNA segments joined by >= 2 crossovers.
  2. Consecutive crossover pairs along the contour of segment I.
  3. Both ends must be PARALLEL (tangent.tangent > 0.5 at each crossover). mrdna
     `continue`s on antiparallel with an explicit "not yet implemented".
  4. Walk the nucleotides between the two crossovers, interpolating the index on
     whichever segment spans fewer nucleotides.
  5. SKIP anything within 11 nt of either crossover, on either segment.
  6. Both strand directions; bond the P atoms; dedupe.

CONSEQUENCE WORTH KNOWING: step 5 means a span must exceed ~22 nt to contribute at all.
Honeycomb crossovers to a given neighbour recur every 21 bp, so a densely crossed-over
bundle generates ZERO push bonds — they appear only where crossovers are sparse, which
is exactly where a structure would otherwise collapse without electrostatic support.
This reproduces the end-weighted distribution measured on the tutorial's hextube.
"""
from __future__ import annotations

from dataclasses import dataclass

#: mrdna: `if i < 11 or j < 11: continue` and the mirrored test at the far crossover.
CROSSOVER_EXCLUSION_NT = 11
PUSH_K = 1.0        # kcal/mol/A^2
PUSH_R0_ANG = 31.0


@dataclass
class PushBondResult:
    n_bonds: int
    text: str
    reason: str
    #: Qualifying (helix_i, idx_i, helix_j, idx_j) positions before atom resolution.
    positions: list


def qualifying_positions(design) -> list:
    """Positions that survive the rule, as (helix_i, idx_i, helix_j, idx_j).

    Pure: depends only on the crossover graph, not on coordinates. In a lattice every
    helix axis is parallel by construction, so the tangent test of step 3 is satisfied
    whenever the two crossovers run the same way along both helices; a pair that runs
    backwards on J is the antiparallel case mrdna skips, and is skipped here too.
    """
    by_pair: dict = {}
    for c in design.crossovers:
        a, b = c.half_a, c.half_b
        key = tuple(sorted((a.helix_id, b.helix_id)))
        # Orient each crossover consistently with the sorted key.
        if a.helix_id == key[0]:
            by_pair.setdefault(key, []).append((int(a.index), int(b.index)))
        else:
            by_pair.setdefault(key, []).append((int(b.index), int(a.index)))

    out: list = []
    for (hi, hj), xs in sorted(by_pair.items()):
        if len(xs) < 2:
            continue
        xs = sorted(set(xs))
        for (i1, j1), (i2, j2) in zip(xs[:-1], xs[1:]):
            nts_i = i2 - i1 + 1
            nts_j = j2 - j1 + 1
            if nts_i <= 0 or nts_j <= 0:
                continue        # antiparallel run: mrdna's explicit `continue`
            for ijmin in range(min(nts_i, nts_j)):
                i = j = ijmin
                if nts_i < nts_j:
                    j = int(round(float(nts_j * i) / nts_i))
                elif nts_j < nts_i:
                    i = int(round(float(nts_i * j) / nts_j))
                idx_i = int(round(i1 + i))
                idx_j = int(round(j1 + j))
                if i < CROSSOVER_EXCLUSION_NT or j < CROSSOVER_EXCLUSION_NT:
                    continue
                if (i2 - idx_i) < CROSSOVER_EXCLUSION_NT:
                    continue
                if (j2 - idx_j) < CROSSOVER_EXCLUSION_NT:
                    continue
                out.append((hi, idx_i, hj, idx_j))
    return out


#: A psfgen heavy atom keeps the coordinate it was handed, so a model P atom and its
#: PDB counterpart agree to PDB print precision. Anything past this is a mis-match.
_COORD_TOL_ANG = 0.05
#: AtomisticModel carries NANOMETRES; the PDB writer emits ANGSTROM (pdb_export.py:152).
_NM_TO_ANG = 10.0


def _pdb_named_atoms(pdb_text: str, names):
    """(positions, ordinals) of every atom whose name is in ``names``.

    The ordinal is NAMD's 0-based atom order. Mirrors
    md_protocols._parse_base_ring_residues: count ATOM records only, skip TER, so the
    ordinals index the same atom list that extraBonds is resolved against.
    """
    import numpy as np

    names = set(names)
    pos, ordinals, n = [], [], 0
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM  "):
            continue
        if line[12:16].strip() in names:
            pos.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
            ordinals.append(n)
        n += 1
    return np.asarray(pos, dtype=float), np.asarray(ordinals, dtype=np.int64)


def _pdb_p_atoms(pdb_text: str):
    return _pdb_named_atoms(pdb_text, {"P"})


def atom_resolver(design, pdb_text: str, names):
    """(helix_id, bp_index, direction, atom_name) -> 0-based ordinal in the psfgen PDB.

    Generalises the P-atom lookup to any atom names — used to build a TOPOLOGY-correct
    Watson-Crick pair list, which geometric nearest-neighbour matching cannot do on an
    idealised build (perfectly regular geometry leaves many atoms equidistant).
    """
    import numpy as np
    from scipy.spatial import cKDTree

    from backend.core.atomistic import build_atomistic_model

    names = set(names)
    model = build_atomistic_model(design, include_proteins=True)
    keys, wanted = [], []
    for a in model.atoms:
        if a.name not in names or getattr(a, "extra_base_k", None) is not None:
            continue
        if a.helix_id is None or a.bp_index is None:
            continue
        keys.append((a.helix_id, int(a.bp_index), str(a.direction), a.name))
        wanted.append((a.x * _NM_TO_ANG, a.y * _NM_TO_ANG, a.z * _NM_TO_ANG))
    if not keys:
        return {}
    pdb_pos, pdb_ord = _pdb_named_atoms(pdb_text, names)
    if not len(pdb_pos):
        return {}
    dist, idx = cKDTree(pdb_pos).query(np.asarray(wanted, dtype=float))
    return {k: int(pdb_ord[i]) for k, i, d in zip(keys, idx, dist) if d <= _COORD_TOL_ANG}


#: The Watson-Crick hydrogen-bond nitrogen: N1 on a purine, N3 on a pyrimidine.
#: EVERY nucleobase carries both an N1 and an N3, so the atom must be picked by residue
#: type — "whichever of N1/N3 is present" silently pairs the wrong nitrogens and reads
#: as a half-broken duplex on a perfectly good idealised build.
_WC_NITROGEN = {"ADE": "N1", "GUA": "N1", "THY": "N3", "CYT": "N3"}


def _pdb_resnames_by_ordinal(pdb_text: str) -> dict:
    out, n = {}, 0
    for line in pdb_text.splitlines():
        if line.startswith("ATOM  "):
            out[n] = line[17:20].strip()
            n += 1
    return out


def watson_crick_pairs(design, pdb_text: str):
    """[(ordinal_fwd, ordinal_rev)] for every duplex base pair, from TOPOLOGY.

    A pair is (helix, bp_index, FORWARD) against (helix, bp_index, REVERSE), bonded
    purine-N1 to pyrimidine-N3. Verified on an idealised 2hb build: A-T lands at 2.60 A
    and G-C at 3.39 A, versus 4.7-6.6 A for every mis-assigned combination.
    """
    res = atom_resolver(design, pdb_text, set(_WC_NITROGEN.values()))
    resnames = _pdb_resnames_by_ordinal(pdb_text)
    by_slot: dict = {}
    for (h, bp, d, name), ordinal in res.items():
        by_slot.setdefault((h, bp, d), {})[name] = ordinal

    def pick(slot):
        for name, ordinal in slot.items():
            if _WC_NITROGEN.get(resnames.get(ordinal, "")) == name:
                return ordinal
        return None

    out = []
    for (h, bp, d), atoms in by_slot.items():
        if d != "FORWARD":
            continue
        other = by_slot.get((h, bp, "REVERSE"))
        if not other:
            continue
        a, b = pick(atoms), pick(other)
        if a is not None and b is not None:
            out.append((a, b))
    return out


def _p_atom_resolver(design, pdb_text: str):
    """(helix_id, index, direction) -> 0-based P atom ordinal in the psfgen PDB.

    Resolved by COORDINATE, not by reconstructing psfgen's residue ordering: the model
    atom and the PDB atom are the same atom, so nearest-neighbour matching is exact and
    self-checking. Inserted bases (``extra_base_k``) are excluded — a push bond restrains
    the duplex backbone, not a base sitting in a junction.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    from backend.core.atomistic import build_atomistic_model

    model = build_atomistic_model(design, include_proteins=True)
    keys, wanted = [], []
    for a in model.atoms:
        if a.name != "P" or getattr(a, "extra_base_k", None) is not None:
            continue
        if a.helix_id is None or a.bp_index is None:
            continue
        keys.append((a.helix_id, int(a.bp_index), str(a.direction)))
        wanted.append((a.x * _NM_TO_ANG, a.y * _NM_TO_ANG, a.z * _NM_TO_ANG))
    if not keys:
        return {}
    pdb_pos, pdb_ord = _pdb_p_atoms(pdb_text)
    if not len(pdb_pos):
        return {}
    dist, idx = cKDTree(pdb_pos).query(np.asarray(wanted, dtype=float))
    return {k: int(pdb_ord[i]) for k, i, d in zip(keys, idx, dist) if d <= _COORD_TOL_ANG}


def interhelical_push_bonds(design, pdb_text: str, *,
                            r0_ang: "float | None" = PUSH_R0_ANG) -> PushBondResult:
    """Push-bond extraBonds text for ``design`` against ``pdb_text``'s atom order.

    ``r0_ang`` is the target P-P separation. mrdna hard-codes 31 A as a REPULSION
    SURROGATE — in vacuum, Coulomb is truncated at 10 A, so nothing stops helices
    collapsing together, and the spring is deliberately longer than the equilibrium
    spacing to push them apart. Whether 31 A is right for NADOC's geometry is an open
    question: NADOC's honeycomb is 2.25 nm centre-to-centre and the phosphates this rule
    selects face each other at ~20.6 A on an idealised 6hb build, so 31 A would expand
    those sites by ~50%. Pass ``None`` to use each bond's MEASURED length instead, which
    makes the term shape-preserving rather than shape-setting.
    """
    positions = qualifying_positions(design)
    if not positions:
        spans = []
        by_pair: dict = {}
        for c in design.crossovers:
            key = tuple(sorted((c.half_a.helix_id, c.half_b.helix_id)))
            by_pair.setdefault(key, []).append(int(c.half_a.index))
        for key, idxs in by_pair.items():
            idxs = sorted(idxs)
            spans += [b - a + 1 for a, b in zip(idxs[:-1], idxs[1:])]
        widest = max(spans) if spans else 0
        return PushBondResult(
            0, "",
            f"none qualify: widest crossover-free span is {widest} nt, and the rule "
            f"needs > {2 * CROSSOVER_EXCLUSION_NT} nt to place even one bond. This is "
            f"the expected result for a densely crossed-over or 2-helix design, not a "
            f"failure.",
            positions)

    p_of = _p_atom_resolver(design, pdb_text)

    # mrdna bonds BOTH strand directions at each qualifying position, and tolerates a
    # missing P (a 5' terminal residue has none): "could not find 'P' atom ... skipping".
    bonds, missing = set(), 0
    for hi, idx_i, hj, idx_j in positions:
        for direction in ("FORWARD", "REVERSE"):
            a = p_of.get((hi, idx_i, direction))
            b = p_of.get((hj, idx_j, direction))
            if a is None or b is None:
                missing += 1
                continue
            bonds.add((min(a, b), max(a, b)))

    import numpy as np

    xyz = np.asarray([(float(l[30:38]), float(l[38:46]), float(l[46:54]))
                      for l in pdb_text.splitlines() if l.startswith("ATOM  ")])
    lines, measured = [], []
    for a, b in sorted(bonds):
        d = float(np.linalg.norm(xyz[a] - xyz[b]))
        measured.append(d)
        lines.append(f"bond {a} {b} {PUSH_K:f} {(r0_ang if r0_ang else d):.2f}")

    reason = (f"{len(positions)} qualifying positions over "
              f"{len({(h, k) for h, _, k, _ in positions})} helix pairs")
    if missing:
        reason += f"; {missing} skipped for a missing P atom (5' termini)"
    if measured:
        med = float(np.median(measured))
        reason += (f"; built P-P {min(measured):.1f}-{max(measured):.1f} A (median "
                   f"{med:.1f})")
        reason += (f", r0={r0_ang:.1f} A -> {100 * (r0_ang / med - 1):+.0f}% at the median"
                   if r0_ang else ", r0=measured (shape-preserving)")
    return PushBondResult(len(bonds), "# PUSHBONDS\n" + "\n".join(lines) + "\n",
                          reason, positions)


def _self_test() -> None:
    """The arithmetic of step 5, on synthetic crossover graphs."""
    class _H:
        def __init__(self, h, i):
            self.helix_id, self.index = h, i

    class _X:
        def __init__(self, ha, hb):
            self.half_a, self.half_b = ha, hb

    class _D:
        def __init__(self, xs):
            self.crossovers = xs

    def xo(i, j):
        return _X(_H("A", i), _H("B", j))

    # A single Holliday junction (2hb_1xT: crossovers at 13 and 14) -> nothing.
    assert qualifying_positions(_D([xo(13, 13), xo(14, 14)])) == []
    # A 21-bp honeycomb repeat -> still nothing (span 22 needs i>=11 AND i2-idx>=11).
    assert qualifying_positions(_D([xo(0, 0), xo(21, 21)])) == []
    # A 40-nt gap -> a run of bonds strictly inside the 11-nt exclusion zones.
    got = qualifying_positions(_D([xo(0, 0), xo(40, 40)]))
    assert got, "a 40-nt crossover-free span must generate push bonds"
    idxs = [i for _, i, _, _ in got]
    assert min(idxs) >= 11 and max(idxs) <= 29, idxs
    # Antiparallel run on J is skipped, exactly as mrdna does.
    assert qualifying_positions(_D([xo(0, 40), xo(40, 0)])) == []
    # One crossover is never enough.
    assert qualifying_positions(_D([xo(0, 0)])) == []
    print("push_bonds self-test: OK")


if __name__ == "__main__":
    _self_test()
