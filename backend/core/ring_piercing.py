"""Detect a covalent bond threaded through a nucleotide ring.

## Why this exists

A bond that passes through the *interior* of a sugar or base ring is a topological
defect of the same family as a catenated crossover pair (see
:mod:`backend.core.junction_topology`) and just as permanent: the bond cannot leave
the ring without one of them breaking, so no minimisation and no MD undoes it.

Observed on the 2026-07-31 ``2hb_2xT`` relaxation (job ``c8c4a87e2033``): the
phosphodiester bond joining the two inserts of one crossover
(``O3'(T8) - P(T9)``) was built through the ribose ring of the *partner*
crossover's insert.  The 10 000-step declash minimisation could not remove it and
instead relieved the overlap the only way left — by stretching that covalent bond
from 1.60 A to 3.08 A — and it stayed at ~2.98 A (the longest heavy-atom bond in
the structure, ~250 kcal/mol of permanent strain) through every ladder stage to the
end of the run.

## Why the catenation detector cannot see it

``junction_topology`` walks each connector along
``_BACKBONE_ORDER = P, O5', C5', C4', C3', O3'`` — the direct C4'->C3' step.  The
sugar ring closes through the *other* path (C4'-O4'-C1'-C2'-C3'), so it is entirely
off-curve, and threading it changes no linking number between two backbone curves.
The two detectors are complementary, not redundant: on ``2hb_2xT`` the raw build is
catenated and unpierced, and the repaired build is unpierced-of-catenation and
pierced.

## Why the clash counters cannot see it either

A sugar ring is ~4.6 A across, so a bond can pass through its centre while every
ring atom stays 2.2-2.6 A away.  That is above ``extra_base_repair._CLASH_NM``
(0.30 nm) for some of the ring and far above ``atomistic_validation.CLASH_NM``
(0.08 nm) for all of it.  Piercing has to be measured as *geometry*, not proximity.

Layer note (CLAUDE.md Three-Layer Law): this module READS the geometric layer only.
It never writes topology or geometry.
"""

from __future__ import annotations

import numpy as _np

SCHEMA = "nadoc.ring_piercing.v1"

# Ring atom names, in ring order.  A fan triangulation from the centroid needs the
# cyclic order to be correct, so these are sequences, not sets.
SUGAR_RING = ("C1'", "C2'", "C3'", "C4'", "O4'")
PURINE_RING_5 = ("N9", "C8", "N7", "C5", "C4")
PURINE_RING_6 = ("C4", "C5", "C6", "N1", "C2", "N3")
PYRIMIDINE_RING = ("N1", "C2", "N3", "C4", "C5", "C6")

# A bond can only pierce a ring whose centroid is within (half the bond + the ring
# radius) of the bond midpoint.  Sugar radius ~0.23 nm, longest built backbone bond
# ~0.34 nm, so 0.6 nm is a wide margin over the ~0.41 nm bound.
SEARCH_NM = 0.6

# Identity fields that distinguish one residue from another in an AtomisticModel.
# Loop copies (copy_k), crossover inserts (crossover_id/extra_base_k) and extension
# tails (extension_id/ext_k) all share the anchor nucleotide's helix/bp key, so they
# have to be part of the grouping or their atoms merge into one pseudo-residue.
_RESIDUE_KEY_FIELDS = (
    "strand_id",
    "helix_id",
    "bp_index",
    "direction",
    "crossover_id",
    "extra_base_k",
    "copy_k",
    "extension_id",
    "ext_k",
)


class RingPiercedError(RuntimeError):
    """Raised when a build would ship a bond threaded through a nucleotide ring."""

    def __init__(self, report: dict):
        self.report = report
        n = report.get("n_pierced", 0)
        first = (report.get("pierced") or [{}])[0]
        super().__init__(
            f"{n} covalent bond(s) are threaded through a nucleotide ring "
            f"(e.g. {first.get('bond', '?')} through {first.get('ring', '?')}). "
            "This is a permanent topological defect — relaxation cannot undo it, it "
            "only trades it for a stretched bond. Rebuild, or override deliberately."
        )


def residue_key(atom) -> tuple:
    """Identity of the residue an atom belongs to."""
    return tuple(getattr(atom, f, None) for f in _RESIDUE_KEY_FIELDS)


def ring_names_for(names) -> list[tuple[str, tuple[str, ...]]]:
    """Which rings a residue holding ``names`` has, as ``(kind, atom_names)``."""
    have = set(names)
    out: list[tuple[str, tuple[str, ...]]] = []
    if have.issuperset(SUGAR_RING):
        out.append(("sugar", SUGAR_RING))
    if "N9" in have:  # purine
        if have.issuperset(PURINE_RING_5):
            out.append(("purine5", PURINE_RING_5))
        if have.issuperset(PURINE_RING_6):
            out.append(("purine6", PURINE_RING_6))
    elif have.issuperset(PYRIMIDINE_RING):  # pyrimidine
        out.append(("pyrimidine", PYRIMIDINE_RING))
    return out


def segment_pierces_ring(p0, p1, ring_pos) -> tuple[bool, float]:
    """Does the segment ``p0 -> p1`` pass through the polygon ``ring_pos``?

    Moller-Trumbore against a fan triangulation from the ring centroid.  Returns
    ``(hit, t)`` where ``t`` is the fractional position along the segment.  Endpoints
    are excluded, so an atom merely sitting in the ring plane does not count.
    """
    p0 = _np.asarray(p0, dtype=float)
    p1 = _np.asarray(p1, dtype=float)
    P = _np.asarray(ring_pos, dtype=float)
    n = len(P)
    if n < 3:
        return False, 0.0
    centre = P.mean(axis=0)
    v0 = _np.repeat(centre[None, :], n, axis=0)
    v1 = P
    v2 = _np.roll(P, -1, axis=0)

    d = p1 - p0
    e1, e2 = v1 - v0, v2 - v0
    h = _np.cross(d, e2)
    a = _np.einsum("ij,ij->i", e1, h)
    ok = _np.abs(a) > 1e-14
    f = _np.zeros_like(a)
    f[ok] = 1.0 / a[ok]
    s = p0 - v0
    u = f * _np.einsum("ij,ij->i", s, h)
    ok &= (u >= 0.0) & (u <= 1.0)
    q = _np.cross(s, e1)
    v = f * _np.einsum("j,ij->i", d, q)
    ok &= (v >= 0.0) & (u + v <= 1.0)
    t = f * _np.einsum("ij,ij->i", e2, q)
    ok &= (t > 1e-9) & (t < 1.0 - 1e-9)
    if not ok.any():
        return False, 0.0
    return True, float(t[ok][0])


def _scan(positions, bonds, rings, *, max_report: int, search_nm: float = SEARCH_NM):
    """Core loop: every bond against every ring whose centroid is close enough.

    ``rings`` is a list of ``(label, kind, serials)``.  Bonds sharing an atom with a
    ring are skipped — that covers the ring's own bonds and the glycosidic bond.
    """
    if not bonds or not rings:
        return []
    ring_serials = [set(s) for _, _, s in rings]
    ring_centres = _np.array([positions[list(s)].mean(axis=0) for _, _, s in rings])

    bond_arr = _np.asarray(bonds, dtype=int)
    mids = 0.5 * (positions[bond_arr[:, 0]] + positions[bond_arr[:, 1]])

    try:  # O(n log n) when scipy is there
        from scipy.spatial import cKDTree  # noqa: PLC0415

        tree = cKDTree(ring_centres)
        neighbours = tree.query_ball_point(mids, r=search_nm)
    except Exception:  # pragma: no cover - fallback
        neighbours = [
            _np.where(_np.linalg.norm(ring_centres - m, axis=1) < search_nm)[0]
            for m in mids
        ]

    hits: list[dict] = []
    for bi, near in enumerate(neighbours):
        i, j = int(bond_arr[bi, 0]), int(bond_arr[bi, 1])
        for ri in near:
            if i in ring_serials[ri] or j in ring_serials[ri]:
                continue
            label, kind, serials = rings[ri]
            hit, t = segment_pierces_ring(
                positions[i], positions[j], positions[list(serials)]
            )
            if not hit:
                continue
            if len(hits) >= max_report:
                return hits
            hits.append(
                {
                    "bond_serials": [i, j],
                    "ring_serials": list(serials),
                    "ring_kind": kind,
                    "ring": label,
                    "t": round(t, 3),
                    "bond_len_nm": round(
                        float(_np.linalg.norm(positions[i] - positions[j])), 4
                    ),
                }
            )
    return hits


def model_piercings(model, *, positions=None, max_report: int = 200) -> list[dict]:
    """Every bond in an ``AtomisticModel`` that threads a nucleotide ring.

    ``positions`` (an ``(n_atoms, 3)`` array in the model's own atom order) overrides
    the model's coordinates, so a trajectory frame can be measured without rebuilding.
    """
    atoms = model.atoms
    pos = (
        _np.asarray(positions, dtype=float)
        if positions is not None
        else _np.array([[a.x, a.y, a.z] for a in atoms], dtype=float)
    )

    by_res: dict[tuple, dict[str, int]] = {}
    for i, a in enumerate(atoms):
        by_res.setdefault(residue_key(a), {})[a.name] = i

    rings: list[tuple[str, str, list[int]]] = []
    for key, name_to_serial in by_res.items():
        for kind, names in ring_names_for(name_to_serial):
            rings.append(
                (
                    _label(atoms, name_to_serial),
                    kind,
                    [name_to_serial[n] for n in names],
                )
            )

    # Hydrogens cannot thread a ring without their heavy partner doing so first, and
    # the seed builder emits heavy atoms only — skip them so a solvated model is cheap.
    bonds = [
        (i, j)
        for i, j in model.bonds
        if not atoms[i].name.startswith("H") and not atoms[j].name.startswith("H")
    ]

    hits = _scan(pos, bonds, rings, max_report=max_report)
    for h in hits:
        i, j = h["bond_serials"]
        h["bond"] = (
            f"{_label(atoms, {atoms[i].name: i})}:{atoms[i].name}"
            f"-{_label(atoms, {atoms[j].name: j})}:{atoms[j].name}"
        )
        h["crossover_ids"] = sorted(
            {
                c
                for c in (
                    atoms[i].crossover_id,
                    atoms[j].crossover_id,
                    atoms[h["ring_serials"][0]].crossover_id,
                )
                if c
            }
        )
    return hits


def _label(atoms, name_to_serial: dict[str, int]) -> str:
    """Human-readable residue label from any one of its atom serials."""
    a = atoms[next(iter(name_to_serial.values()))]
    tag = ""
    if a.crossover_id:
        tag = f"[xb{a.extra_base_k}]"
    elif a.extension_id:
        tag = f"[ext{a.ext_k}]"
    return f"{a.chain_id}{a.seq_num}{a.residue}{tag}"


def piercing_report(
    design, *, model=None, positions=None, max_report: int = 200
) -> dict:
    """Audit a design's atomistic seed for ring piercings."""
    if model is None:
        from backend.core.atomistic import build_atomistic_model  # noqa: PLC0415

        model = build_atomistic_model(design)
    pierced = model_piercings(model, positions=positions, max_report=max_report)
    return {
        "schema": SCHEMA,
        "ok": not pierced,
        "n_pierced": len(pierced),
        "pierced": pierced,
    }


def assert_not_pierced(
    design, *, model=None, positions=None, allow: bool = False
) -> dict:
    """Build gate: raise :class:`RingPiercedError` unless ``allow``."""
    report = piercing_report(design, model=model, positions=positions)
    report["override_used"] = bool(allow and not report["ok"])
    if not report["ok"] and not allow:
        raise RingPiercedError(report)
    return report


# ── Scoped check for the extra-base repair ladder ─────────────────────────────
#
# The ladder runs mid-build, before any bond list exists, and has to re-measure after
# every rung — so it needs a check it can afford to repeat.  :class:`PierceScope`
# indexes the junction's neighbourhood ONCE (rings + synthesised bonds, from atom
# names) and then re-reads coordinates per rung.  The neighbourhood matters: on
# 6hbx100_2xT a rung threaded a *duplex* residue's phosphate through a sugar two
# residues along, which a pair-only scope would miss.

# How far from the moved atoms a residue can be and still be reachable by a rung: the
# spin re-seed walks an insert's rigid body by well under 1 nm.
_SCOPE_RADIUS_NM = 1.2


# Longest an inter-residue O3'-P is allowed to be and still be treated as a bond when
# connectivity is inferred from geometry.  A built phosphodiester is ~0.16 nm and the
# worst impaled one measured was 0.31 nm after minimisation; the phantom this rules out
# (see below) is ~0.8 nm.
_MAX_PHOSPHODIESTER_NM = 0.40


def _synthesise_bonds(
    atoms, residues: dict[tuple, dict[str, int]]
) -> list[tuple[int, int]]:
    """Covalent bonds among ``residues``, derived from atom names and geometry.

    Mid-build there is no bond list yet, so intra-residue connectivity comes from the
    same templates the builder emits (sugar/phosphate bonds plus the residue type's base
    bonds).  The inter-residue phosphodiester is inferred as *nearest P within a bond
    length of each O3'* — deliberately NOT from chain adjacency.

    Chain adjacency is wrong exactly where this check is needed: at a crossover carrying
    extra bases, the two seq-adjacent duplex residues are no longer directly bonded (the
    inserts sit between them), and mid-build the inserts are not yet numbered into the
    chain at all.  Drawing O3'(i) -> P(i+1) there invents an ~0.8 nm bond straight across
    the junction, which then "pierces" every ring near the crossover — measured on
    2hb_2xT, where it made three sound rungs (including the best one) look defective.
    """
    bonds, o3_serials, p_serials = _intra_residue_bonds(atoms, residues)
    pos = {
        s: _np.array([atoms[s].x, atoms[s].y, atoms[s].z])
        for s in set(o3_serials) | set(p_serials)
    }
    o3_pos = (
        _np.array([pos[s] for s in o3_serials]) if o3_serials else _np.empty((0, 3))
    )
    p_pos = _np.array([pos[s] for s in p_serials]) if p_serials else _np.empty((0, 3))
    for a, b in _phosphodiester_links(o3_pos, p_pos):
        bonds.append((o3_serials[a], p_serials[b]))
    return bonds


def _intra_residue_bonds(atoms, residues: dict[tuple, dict[str, int]]):
    """Geometry-independent half: the bonds inside each residue, plus its O3' and P."""
    from backend.core.atomistic import (  # noqa: PLC0415
        BASE_TEMPLATES,
        _SUGAR_BONDS,
    )

    bonds: list[tuple[int, int]] = []
    o3_serials: list[int] = []
    p_serials: list[int] = []
    for sd in residues.values():
        a = atoms[next(iter(sd.values()))]
        table = list(_SUGAR_BONDS)
        tmpl = BASE_TEMPLATES.get(a.residue)
        if tmpl is not None:
            table += list(tmpl[1])
        for a_name, b_name in table:
            if a_name in sd and b_name in sd:
                bonds.append((sd[a_name], sd[b_name]))
        if "O3'" in sd:
            o3_serials.append(sd["O3'"])
        if "P" in sd:
            p_serials.append(sd["P"])
    return bonds, o3_serials, p_serials


def _phosphodiester_links(o3_pos, p_pos) -> list[tuple[int, int]]:
    """Geometry-dependent half: nearest P within a bond length of each O3'.

    Must be re-derived from the CURRENT coordinates every time the scope is measured.
    A repair rung moves whole inserts, so which P an O3' is bonded to changes with it;
    freezing this list at index time silently drops the very bond a later rung created
    (measured on 6hb_2xT — one threaded junction went unseen by the ladder that way).
    """
    out: list[tuple[int, int]] = []
    if len(o3_pos) == 0 or len(p_pos) == 0:
        return out
    for i, q in enumerate(o3_pos):
        d = _np.linalg.norm(p_pos - q, axis=1)
        k = int(_np.argmin(d))
        if d[k] <= _MAX_PHOSPHODIESTER_NM:
            out.append((i, k))
    return out


class PierceScope:
    """Ring-piercing check over one junction's neighbourhood, cheap to repeat.

    Built once per repaired pair from the atoms the solve may move (``focus``); the
    surrounding residues within :data:`_SCOPE_RADIUS_NM` come along so a rung that
    shoves a linker into a neighbour is seen too.  ``count(atoms)`` re-reads
    coordinates and re-measures, which is what the ladder calls per rung.
    """

    def __init__(
        self, atoms, focus_serials, radius_nm: float = _SCOPE_RADIUS_NM, all_pos=None
    ):
        focus = {int(s) for s in focus_serials}
        if not focus:
            self._serials: list[int] = []
            return
        centre = _np.array(
            [[atoms[s].x, atoms[s].y, atoms[s].z] for s in sorted(focus)]
        )
        # Caller-supplied for a design with many junctions: rebuilding the whole-model
        # position array per pair costs more than every rung of the ladder.
        if all_pos is None:
            all_pos = _np.array([[a.x, a.y, a.z] for a in atoms], dtype=float)
        lo = centre.min(axis=0) - radius_nm
        hi = centre.max(axis=0) + radius_nm
        near = _np.where(((all_pos >= lo) & (all_pos <= hi)).all(axis=1))[0]

        residues: dict[tuple, dict[str, int]] = {}
        for i in near:
            residues.setdefault(residue_key(atoms[i]), {})[atoms[i].name] = int(i)
        # Drop hydrogens: they cannot thread a ring without their heavy partner first.
        residues = {
            k: {n: s for n, s in sd.items() if not n.startswith("H")}
            for k, sd in residues.items()
        }

        focus_res = {k for k, sd in residues.items() if focus & set(sd.values())}
        self._focus_res = focus_res

        rings: list[tuple[tuple, str, list[int]]] = []
        for key, sd in residues.items():
            for kind, names in ring_names_for(sd):
                rings.append((key, kind, [sd[n] for n in names]))
        intra, o3, p = _intra_residue_bonds(atoms, residues)

        self._serials = sorted(
            {s for _, _, ser in rings for s in ser}
            | {s for b in intra for s in b}
            | set(o3)
            | set(p)
        )
        order = {s: k for k, s in enumerate(self._serials)}
        self._rings = [(key, kind, [order[s] for s in ser]) for key, kind, ser in rings]
        self._intra = [(order[i], order[j]) for i, j in intra]
        self._o3 = [order[s] for s in o3]
        self._p = [order[s] for s in p]
        self._res_of = {order[s]: residue_key(atoms[s]) for s in self._serials}

    def _positions(self, atoms):
        return _np.array(
            [[atoms[s].x, atoms[s].y, atoms[s].z] for s in self._serials], dtype=float
        )

    def hits(self, atoms) -> list[dict]:
        """Piercings that involve at least one residue the solve moves."""
        if not self._serials:
            return []
        pos = self._positions(atoms)
        # Intra-residue connectivity is fixed; the phosphodiester links are not — a rung
        # moves whole inserts, so re-derive them from the coordinates being measured.
        bonds = list(self._intra) + [
            (self._o3[a], self._p[b])
            for a, b in _phosphodiester_links(pos[self._o3], pos[self._p])
        ]
        raw = _scan(
            pos, bonds, [(k, kind, s) for k, kind, s in self._rings], max_report=50
        )
        out = []
        for h in raw:
            i, j = h["bond_serials"]
            ring_key = h["ring"]
            bond_keys = (self._res_of.get(i), self._res_of.get(j))
            if ring_key not in self._focus_res and not (
                set(bond_keys) & self._focus_res
            ):
                continue  # pre-existing, not this rung's doing
            h["bond_serials"] = [self._serials[i], self._serials[j]]
            h["ring_serials"] = [self._serials[k] for k in h["ring_serials"]]
            a1, a2 = atoms[h["bond_serials"][0]], atoms[h["bond_serials"][1]]
            h["bond"] = (
                f"{a1.chain_id}{a1.seq_num}{a1.residue}:{a1.name}"
                f"-{a2.chain_id}{a2.seq_num}{a2.residue}:{a2.name}"
            )
            r0 = atoms[h["ring_serials"][0]]
            h["ring"] = f"{r0.chain_id}{r0.seq_num}{r0.residue}"
            out.append(h)
        return out

    def count(self, atoms) -> int:
        return len(self.hits(atoms))
