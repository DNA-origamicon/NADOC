"""Repair topologically catenated crossover junctions in the atomistic seed.

## Why this exists

At an antiparallel *reciprocal* crossover pair — two crossovers at adjacent bp between
the same two helices, with their 3' exits on OPPOSITE helices — the joint L-BFGS-B
backbone solve (``_minimize_{1,2,3}_extra_base``) is free to walk an inserted base's
whole rigid body across the junction and thread it through the partner crossover's
backbone.  The result is a pair of backbones with Gauss linking number ``Lk = +/-1``
(occasionally +/-2) instead of 0.

Because both chain ends are covalently pinned into the origami network, that
entanglement is not something relaxation can undo: it survives minimisation and every
NAMD ENM stage, and it is invisible to base-pairing health checks (a catenated 2hb run
reported ``c1_paired_fraction = 1.0``).  So it has to be fixed at build time.

## Measured basis for the search below

Sweeping a full helical turn on a synthetic 2-helix reciprocal pair:

===============================  ==========  ===========
build path                       1 insert    2 inserts
===============================  ==========  ===========
joint solve (unbounded)          5/11 links  6/11 links
joint solve, |delta| <= 0.08 nm  1/11        1/11
joint solve, |delta| <= 0.04 nm  0/11        1/11
arc pose only (no joint solve)   0/11        0/11
===============================  ==========  ===========

So no single tightening is a guarantee, and the fix must MEASURE and RETRY.  Note also
that the arc pose is only unlinked for small insert counts — at n >= 4 it links at one
phase too, so it is not a guaranteed-unlinked fallback either.

**The retry knob is the SPIN seed, not the translation bound.**  Each insert's spin DOF
rotates about ``target_c1n``, and ``_align_glycosidic`` has already made C1'->N parallel
to that axis, so ``_glycosidic_cost_grad`` returns cost 0 and zero gradient for every
theta.  The objective is therefore INDIFFERENT to the spin seed: re-seeding cannot bias
the converged geometry, it only changes which local basin L-BFGS-B falls into.  A bound
on the translation, by contrast, constrains the optimum itself and measurably degrades
the linker.  Measured on real designs (clashes, unrepaired -> repaired):

    bound ladder:  2hb_1xT 2 -> 2    2hb_2xT 6 -> 10
    spin seeds:    2hb_1xT 2 -> 0    2hb_2xT 6 -> 5

i.e. spin re-seeding leaves the structure with FEWER clashes than the unrepaired build,
because accepting a different basin often finds a better minimum of the same objective.

Attempt order is: 16 deterministic spin seeds (seed 0 = today's behaviour exactly, so
clean pairs and unpaired crossovers stay bit-identical), then bounded translation, then
the pure arc pose as a last resort.  Acceptance requires an unlinked pair; among unlinked
attempts the ranking prefers sound linker geometry, then fewest clashes into the
surrounding structure, then attempt order.  Only a FATALLY degenerate linker (collapsed
bridge angle — NAMD's angle force divides by sin(theta)) is excluded outright: leaving a
pair catenated is worse than leaving it strained, because strain relaxes out in
minimisation and a linking number never does.
"""
from __future__ import annotations

import math as _math

from dataclasses import dataclass, field
from typing import Callable

import numpy as _np

# A repair attempt is (spin_a, spin_b, delta_cap_a, delta_cap_b).
#
# PRIMARY = spin re-seeding.  Each insert's spin DOF is about ``target_c1n``, the very
# axis ``_align_glycosidic`` aligned C1'->N to, so the glycosidic term is flat in it:
# the objective is INDIFFERENT to the seed, and re-seeding only changes which local
# basin L-BFGS-B lands in.  That is why it does not degrade geometry the way a bound
# does — the converged structure is a genuine minimum of the unmodified objective.
# Seed 0 is (0, 0), i.e. exactly today's behaviour, so a pair that was never linked and
# every unpaired crossover come out bit-identical.
#
# BACKSTOP = bounded rigid-body translation, for the rare pair no spin seed clears.
# This one DOES bias the optimum, so it is tried only after the spin ladder.
#
# LAST RESORT = drop a member to its pure arc pose (inserts left exactly where the Bezier
# put them, only the linkers closed).  It is reliably unlinked but can leave the bridge
# angles degenerate — min sin(theta) ~ 0 is a divide-by-zero in NAMD's angle force at
# minimisation step 0 — so it is NOT banned outright but is placed last and, like every
# other rung, must pass the geometry check before it can be accepted.  If it is degenerate
# at a given junction it is rejected and the gate refuses the build.
_QUARTER = _math.pi / 2.0
SPIN_SEEDS: tuple[tuple[float, float], ...] = tuple(
    (a * _QUARTER, b * _QUARTER) for a in range(4) for b in range(4)
)
DELTA_BACKSTOP: tuple[tuple, ...] = (
    (0.12, None), (None, 0.12), (0.12, 0.12), (0.06, 0.06), (0.03, 0.03),
)
ARC_LAST_RESORT: tuple[tuple, ...] = (
    (True, False), (False, True), (True, True),
)

# Canonical phosphodiester geometry the repaired linker must still respect.  A rung that
# unlinks the pair but leaves a bond 4 A long or an angle collapsed to 0 is not a repair.
_MAX_BOND_DEV_NM = 0.10
_MIN_ANGLE_SIN = 0.05
# Below this the angle force (which divides by sin(theta)) is a step-0 blow-up, so such a
# rung is EXCLUDED outright.  Everything between this and _MIN_ANGLE_SIN is merely ranked
# down: leaving a pair catenated is worse than leaving it strained, because strain relaxes
# out in minimisation and a linking number never does.
_FATAL_ANGLE_SIN = 0.02
# Extra attempts explored after the first sound one, looking for fewer clashes.
# 10 matches an exhaustive search on every case measured; 5 was materially worse.
_LOOK_AHEAD = 10

_BACKBONE_ORDER = ("P", "O5'", "C5'", "C4'", "C3'", "O3'")
_LK_LINKED = 0.5
_MAX_PASSES = 2
# A repaired pair whose backbones sit at least this far apart (nm) is accepted straight
# away; below it the ladder keeps looking for a roomier rung. Canonical non-bonded heavy
# atom contact is ~0.3 nm, and the unrepaired 2hb_1xT junction sat at 0.036 nm.
_GOOD_SEPARATION_NM = 0.30
# Heavy-atom contact distance used to score a rung's sterics (matches the display
# audit's CLASH_NM). A rung that unlinks the pair but shoves an insert into a
# neighbouring helix is not an improvement.
_CLASH_NM = 0.30


@dataclass
class ExtraBaseRecord:
    """Everything needed to re-run one crossover's insert placement from scratch."""

    crossover_id: str
    n: int
    src_s: dict
    dst_s: dict
    eb_s: list
    glyco: list
    target_c1n: _np.ndarray
    repel_pos: list
    all_s: list
    snapshot: dict = field(default_factory=dict)   # atom serial -> (x, y, z)

    def capture(self, atoms) -> None:
        """Snapshot every atom the solve may move, so a retry starts from the arc pose."""
        for sd in self.all_s:
            for serial in set(sd.values()):
                a = atoms[serial]
                self.snapshot[serial] = (a.x, a.y, a.z)

    def restore(self, atoms) -> None:
        for serial, (x, y, z) in self.snapshot.items():
            a = atoms[serial]
            a.x, a.y, a.z = x, y, z


def connector_path(atoms, record: ExtraBaseRecord) -> _np.ndarray:
    """Backbone polyline 5'->3' across this crossover, flanking nt through inserts."""
    pts = []
    for sd in record.all_s:
        for name in _BACKBONE_ORDER:
            serial = sd.get(name)
            if serial is not None:
                a = atoms[serial]
                pts.append((a.x, a.y, a.z))
    return _np.asarray(pts, dtype=float)


def _min_separation(atoms, rec_a: ExtraBaseRecord, rec_b: ExtraBaseRecord) -> float:
    """Closest approach (nm) between the two connectors' backbone polylines."""
    from backend.core.junction_topology import _min_segment_distance

    pa, pb = connector_path(atoms, rec_a), connector_path(atoms, rec_b)
    if len(pa) < 2 or len(pb) < 2:
        return float("inf")
    return _min_segment_distance(pa, pb)


def _geometry_score(atoms, record: ExtraBaseRecord) -> tuple:
    """(worst bond deviation from canonical, worst |sin(angle)|) over the linker.

    The O3'-P-O5' chain joining each consecutive residue pair.  A collapsed angle matters
    because NAMD's angle force divides by sin(theta): a rung that drives it to ~0 blows up
    at minimisation step 0.  (That is what rules out the "drop to the pure arc pose"
    escape — reliably unlinked, but min sin(theta) ~ 0.)
    """
    from backend.core.atomistic_helpers import (  # noqa: PLC0415
        _CANON_C3O3, _CANON_O3P, _CANON_PO5, _CANON_O5C5,
    )

    def pos(sd, name):
        ser = sd.get(name)
        return None if ser is None else _np.array(
            [atoms[ser].x, atoms[ser].y, atoms[ser].z], dtype=float)

    worst_bond = 0.0
    worst_sin = 1.0
    for prev_sd, next_sd in zip(record.all_s, record.all_s[1:]):
        c3, o3 = pos(prev_sd, "C3'"), pos(prev_sd, "O3'")
        p_, o5, c5 = pos(next_sd, "P"), pos(next_sd, "O5'"), pos(next_sd, "C5'")
        for a, b, canon in ((c3, o3, _CANON_C3O3), (o3, p_, _CANON_O3P),
                            (p_, o5, _CANON_PO5), (o5, c5, _CANON_O5C5)):
            if a is None or b is None:
                continue
            worst_bond = max(worst_bond,
                             abs(float(_np.linalg.norm(b - a)) - canon))
        for a, b, c in ((c3, o3, p_), (o3, p_, o5), (p_, o5, c5)):
            if a is None or b is None or c is None:
                continue
            u, v = a - b, c - b
            nu, nv = float(_np.linalg.norm(u)), float(_np.linalg.norm(v))
            if nu < 1e-9 or nv < 1e-9:
                return (float("inf"), 0.0)
            cos = max(-1.0, min(1.0, float(_np.dot(u, v)) / (nu * nv)))
            worst_sin = min(worst_sin, (1.0 - cos * cos) ** 0.5)
    return (worst_bond, worst_sin)


def _geometry_fatal(score: tuple) -> bool:
    """A rung NAMD cannot even start from: collapsed angle or non-finite bond."""
    bond, sin_a = score
    return not _np.isfinite(bond) or sin_a < _FATAL_ANGLE_SIN


def _geometry_penalty(score: tuple, baseline: tuple) -> int:
    """0 if the linker is as good as the baseline (or good absolutely), else 1.

    Deliberately a RANKING term, not a filter.  An earlier version filtered on this and
    could veto the only unlinking rung, leaving the pair catenated — and the build gate
    then refuses the whole design.  That is the wrong trade: strain relaxes out during
    minimisation, a linking number never does.
    """
    bond, sin_a = score
    base_bond, base_sin = baseline
    bond_ok = bond <= _MAX_BOND_DEV_NM or bond <= base_bond * 1.05 + 1e-9
    angle_ok = sin_a >= _MIN_ANGLE_SIN or sin_a >= base_sin - 1e-9
    return 0 if (bond_ok and angle_ok) else 1


def _moved_serials(rec: ExtraBaseRecord) -> set:
    """Serials this record's solve can move (exactly what ``capture`` snapshots)."""
    return set(rec.snapshot)


def _repositioned_serials(rec: ExtraBaseRecord) -> set:
    """The subset the solve actually RELOCATES: the insert bodies and the linker atoms.

    Scoring must be restricted to these.  The flanking nucleotides are in ``all_s`` (so
    they are snapshotted and restored) but only their O3'/P/O5' move; counting all their
    atoms swamps the score with a large constant and hides the change the repair made.
    """
    out: set = set()
    for sd in rec.eb_s:
        out |= set(sd.values())
    if rec.src_s and "O3'" in rec.src_s:
        out.add(rec.src_s["O3'"])
    for name in ("P", "OP1", "OP2", "O5'"):
        if rec.dst_s and name in rec.dst_s:
            out.add(rec.dst_s[name])
    return out


class _Surroundings:
    """Static neighbour lookup for scoring a repair rung's sterics.

    Only the pair's own atoms move while its ladder is searched, so everything else can
    be indexed once.  Every covalent partner of a moved atom lies inside the pair's own
    records (an insert's P bonds to the flanking nucleotide's O3', which ``all_s``
    includes), so a moved-vs-outside contact is never a bonded pair — no exclusion list
    is needed.
    """

    def __init__(self, atoms, exclude: set, clash_nm: float):
        from scipy.spatial import cKDTree  # noqa: PLC0415

        self.clash_nm = clash_nm
        pts, keep = [], []
        for i, a in enumerate(atoms):
            if i in exclude:
                continue
            pts.append((a.x, a.y, a.z))
            keep.append(i)
        self._tree = cKDTree(_np.asarray(pts, dtype=float)) if pts else None

    def clash_count(self, atoms, serials: set) -> int:
        if self._tree is None or not serials:
            return 0
        q = _np.asarray([(atoms[s].x, atoms[s].y, atoms[s].z) for s in serials],
                        dtype=float)
        return int(sum(len(hits) for hits in
                       self._tree.query_ball_point(q, r=self.clash_nm)))


def pair_linking_number(atoms, rec_a: ExtraBaseRecord, rec_b: ExtraBaseRecord) -> float:
    from backend.core.junction_topology import _close_loop, gauss_linking_number

    pa, pb = connector_path(atoms, rec_a), connector_path(atoms, rec_b)
    if len(pa) < 3 or len(pb) < 3:
        return 0.0
    return gauss_linking_number(_close_loop(pa), _close_loop(pb))


def _apply_attempt(atoms, record: ExtraBaseRecord, spin, delta_cap,
                   bridge_fn, minimisers: dict, arc: bool = False) -> None:
    """Re-place one crossover's inserts under (spin seed, delta cap), from the arc pose."""
    record.restore(atoms)
    solver = None if arc else minimisers.get(record.n)
    if solver is None:                      # arc pose, or n > 3 (no joint solve to re-seed)
        for prev_sd, next_sd in zip(record.all_s, record.all_s[1:]):
            bridge_fn(atoms, prev_sd, next_sd)
        return

    spin0 = None if spin in (None, 0.0) else tuple([float(spin)] * record.n)
    args = [atoms, record.src_s, record.dst_s, *record.eb_s, *record.glyco,
            record.target_c1n, record.repel_pos]
    # cache_key=None: a repaired result must never be served back for an unrepaired
    # call, and the search is deterministic anyway.
    solver(*args, cache_key=None,
           delta_cap=(None if delta_cap is None else float(delta_cap)), spin0=spin0)


def _attempts():
    """Deterministic order: spin re-seeds, then bounded translation, then the arc pose."""
    for sa, sb in SPIN_SEEDS:
        yield {"spin": (sa, sb), "delta": (None, None), "arc": (False, False)}
    for da, db in DELTA_BACKSTOP:
        yield {"spin": (0.0, 0.0), "delta": (da, db), "arc": (False, False)}
    for aa, ab in ARC_LAST_RESORT:
        yield {"spin": (0.0, 0.0), "delta": (None, None), "arc": (aa, ab)}


def repair_catenated_pairs(
    atoms,
    records: dict,
    pairs: list,
    bridge_fn: Callable,
    minimisers: dict,
) -> dict:
    """Measure every reciprocal pair and repair the linked ones in place.

    ``records`` maps crossover id -> :class:`ExtraBaseRecord`; ``pairs`` is a list of
    ``(crossover_id_a, crossover_id_b)``.  Returns a summary for the build report.

    Repairs are applied pair by pair, then every pair is re-measured — a crossover can
    belong to two reciprocal pairs (bp-1 and bp+1), so fixing one can in principle
    disturb the other.  Bounded at ``_MAX_PASSES`` so a pathological design cannot spin.
    """
    live = [(a, b) for a, b in pairs if a in records and b in records]
    if not live:
        return {"n_pairs": 0, "n_repaired": 0, "n_unrepaired": 0, "repairs": []}

    repairs: list[dict] = []
    unrepaired: list[dict] = []

    for _pass in range(_MAX_PASSES):
        linked = []
        for a, b in live:
            lk = pair_linking_number(atoms, records[a], records[b])
            if abs(lk) >= _LK_LINKED:
                linked.append((a, b, lk))
        if not linked:
            break

        progressed = False
        for a, b, lk0 in linked:
            rec_a, rec_b = records[a], records[b]
            # Unlinking is necessary but not sufficient: a rung can trade the link for a
            # steric clash (measured: 2hb_2xT went 6 -> 13 clashes when the first
            # unlinking rung was taken blindly). So score every unlinking rung by how far
            # apart it leaves the two backbones and keep the best, exiting early once a
            # rung is comfortably clear.
            moved = _moved_serials(rec_a) | _moved_serials(rec_b)
            scored = _repositioned_serials(rec_a) | _repositioned_serials(rec_b)
            # Exclude the whole pair from the tree (so intra-pair and bonded contacts do
            # not count) but score only the atoms the solve relocates.
            surroundings = _Surroundings(atoms, moved, _CLASH_NM)
            baseline_clashes = surroundings.clash_count(atoms, scored)
            # Reference = what the unrepaired solve (today's shipped code) produced.
            base_geo_a = _geometry_score(atoms, rec_a)
            base_geo_b = _geometry_score(atoms, rec_b)

            fixed = None
            best_score = None
            best_gap = -1.0
            first_good = None
            for n_try, attempt in enumerate(_attempts()):
                sa, sb = attempt["spin"]
                da, db = attempt["delta"]
                aa, ab = attempt["arc"]
                _apply_attempt(atoms, rec_a, sa, da, bridge_fn, minimisers, arc=aa)
                _apply_attempt(atoms, rec_b, sb, db, bridge_fn, minimisers, arc=ab)
                if abs(pair_linking_number(atoms, rec_a, rec_b)) >= _LK_LINKED:
                    continue
                # Unlinked is necessary but not sufficient: the linker must still be
                # buildable, and the rung must not shove an insert into a neighbour.
                geo_a = _geometry_score(atoms, rec_a)
                geo_b = _geometry_score(atoms, rec_b)
                if _geometry_fatal(geo_a) or _geometry_fatal(geo_b):
                    continue                      # NAMD could not start from this
                gap = _min_separation(atoms, rec_a, rec_b)
                penalty = (_geometry_penalty(geo_a, base_geo_a)
                           + _geometry_penalty(geo_b, base_geo_b))
                # Rank: sound linker geometry, then fewest clashes into the surrounding
                # structure, then attempt order (determinism).
                score = (penalty, surroundings.clash_count(atoms, scored), n_try)
                if best_score is None or score < best_score:
                    best_score, best_gap, fixed = score, gap, attempt
                if penalty == 0:
                    if first_good is None:
                        first_good = n_try
                    # Stop once the pair is sound and clash-neutral, or after a short
                    # look-ahead past the first sound solution.  Exhausting all attempts
                    # chasing a marginally better clash count costs an L-BFGS-B solve
                    # each and dominates build time on crowded designs.
                    if score[1] <= baseline_clashes or n_try - first_good >= _LOOK_AHEAD:
                        break
            if fixed is not None:
                # Re-apply the winner (the loop may have moved on to a worse attempt).
                _apply_attempt(atoms, rec_a, fixed["spin"][0], fixed["delta"][0],
                               bridge_fn, minimisers, arc=fixed["arc"][0])
                _apply_attempt(atoms, rec_b, fixed["spin"][1], fixed["delta"][1],
                               bridge_fn, minimisers, arc=fixed["arc"][1])
            if fixed is None:
                # Leave the pair at the last ladder rung; the build gate refuses it.
                unrepaired.append({"crossover_ids": [a, b], "lk": round(lk0, 3)})
            else:
                progressed = True
                repairs.append({
                    "crossover_ids": [a, b],
                    "lk_before": round(lk0, 3),
                    "spin": [round(v, 4) for v in fixed["spin"]],
                    "delta_cap": [str(v) for v in fixed["delta"]],
                    "arc": list(fixed["arc"]),
                    "attempts": (best_score[2] + 1) if best_score else None,
                    "geometry_penalty": (best_score[0] if best_score else None),
                    "separation_nm": round(best_gap, 4),
                    "clashes": (best_score[1] if best_score else None),
                    "clashes_before": baseline_clashes,
                })
        if not progressed:
            break

    return {
        "n_pairs": len(live),
        "n_repaired": len(repairs),
        "n_unrepaired": len(unrepaired),
        "repairs": repairs[:50],
        "unrepaired": unrepaired[:50],
    }
