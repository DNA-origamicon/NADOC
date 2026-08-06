"""Bonds threaded through a nucleotide ring — backend/core/ring_piercing.py.

The 2026-07-31 ``2hb_2xT`` relaxation (job ``c8c4a87e2033``) shipped a seed whose
inter-insert phosphodiester bond ran through the ribose ring of the *partner*
crossover's insert.  Like a catenated pair, that is permanent: the 10 000-step
minimisation could only relieve it by stretching the bond 1.60 A -> 3.08 A, and it
stayed at ~2.98 A — the longest heavy-atom bond in the structure — through every
ladder stage of the run.

The catenation detector cannot see it (its connector polyline takes the C4'->C3' step,
so the sugar ring is off-curve) and neither can the clash counters (a bond through the
ring centre keeps every ring atom 2.2-2.6 A away).  The defect was *introduced* by the
catenation repair ladder itself: on the shipped design the raw build is catenated and
unpierced, and the rung that unlinked it was pierced.

As in ``test_junction_topology``, the load-bearing tests are the POSITIVE CONTROLS —
``_piercing_check_disabled`` reproduces the pre-fix ranking, so the detector is still
observed going red and the ranking term is pinned as what prevents the defect.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.junction_topology import gate_seed_topology
from backend.core.ring_piercing import (
    PYRIMIDINE_RING,
    SUGAR_RING,
    PierceScope,
    RingPiercedError,
    assert_not_pierced,
    model_piercings,
    piercing_report,
    ring_names_for,
    segment_pierces_ring,
)
from tests.test_junction_topology import _reciprocal_design

# Phases at which the pre-fix ranking shipped a threaded ring, found by sweeping a full
# helical turn with the piercing term disabled.  TT (two inserts) is hit at 6 of 11
# phases, T at 1 — which is why this surfaced on a 2xT run.
_KNOWN_PIERCING = [("T", 14), ("TT", 8)]
_PHASE_SWEEP = range(8, 19)


@contextlib.contextmanager
def _piercing_check_disabled():
    """Build as the pre-fix code did — repair ladder ranked on clashes alone.

    Zeroing ``PierceScope.count`` reproduces the old behaviour exactly: the pair is then
    only "defective" when its linking number says so, the rung score collapses to the
    old ``(penalty, clashes, n_try)`` ordering, and the early exit no longer waits for an
    unthreaded rung.
    """
    import backend.core.atomistic_minimisers as _minimisers

    original = PierceScope.count
    PierceScope.count = lambda self, atoms: 0
    _minimisers._XB_CACHE.clear()
    try:
        yield
    finally:
        PierceScope.count = original
        _minimisers._XB_CACHE.clear()


@pytest.fixture(scope="module", autouse=True)
def _warm_atomistic_build():
    """Pay the one-off template load + L-BFGS-B warm-up in SETUP, not in a test."""
    build_atomistic_model(_reciprocal_design(None, bp=12))


# ── The intersection primitive: pure geometry ─────────────────────────────────


def _pentagon(radius=0.23, centre=(0.0, 0.0, 0.0)):
    """A ring the size of a deoxyribose (C1'-C4' span ~0.23 nm), in the xy plane."""
    t = np.linspace(0.0, 2.0 * np.pi, 5, endpoint=False)
    ring = np.stack([radius * np.cos(t), radius * np.sin(t), np.zeros_like(t)], axis=1)
    return ring + np.asarray(centre, dtype=float)


def test_segment_through_the_ring_centre_is_a_piercing():
    hit, t = segment_pierces_ring([0.0, 0.0, -0.2], [0.0, 0.0, 0.2], _pentagon())
    assert hit
    assert t == pytest.approx(0.5, abs=1e-6)


def test_segment_beside_the_ring_is_not_a_piercing():
    hit, _ = segment_pierces_ring([0.5, 0.0, -0.2], [0.5, 0.0, 0.2], _pentagon())
    assert not hit


def test_segment_in_the_ring_plane_is_not_a_piercing():
    """A bond lying across the ring is a clash, not a threading — it can slide out."""
    hit, _ = segment_pierces_ring([-0.5, 0.0, 0.0], [0.5, 0.0, 0.0], _pentagon())
    assert not hit


def test_segment_stopping_inside_the_ring_is_not_a_piercing():
    """Endpoints are excluded: an atom sitting in the ring has not gone through it."""
    hit, _ = segment_pierces_ring([0.0, 0.0, -0.2], [0.0, 0.0, 0.0], _pentagon())
    assert not hit


def test_a_grazing_segment_outside_the_polygon_edge_misses():
    """Just outside a vertex-to-vertex edge must miss — guards the fan triangulation
    against reporting the ring's circumscribed circle instead of the polygon."""
    ring = _pentagon()
    edge_mid = 0.5 * (ring[0] + ring[1])
    outside = edge_mid * 1.15
    hit, _ = segment_pierces_ring([outside[0], outside[1], -0.2],
                                  [outside[0], outside[1], 0.2], ring)
    assert not hit


# ── Ring identification ───────────────────────────────────────────────────────


def test_purine_and_pyrimidine_rings_are_told_apart():
    """N9 is the discriminator — a pyrimidine must not be scanned for a 5-ring."""
    pyrimidine = set(SUGAR_RING) | set(PYRIMIDINE_RING)
    kinds = {k for k, _ in ring_names_for(pyrimidine)}
    assert kinds == {"sugar", "pyrimidine"}

    purine = set(SUGAR_RING) | {"N9", "C8", "N7", "C5", "C4", "C6", "N1", "C2", "N3"}
    assert {k for k, _ in ring_names_for(purine)} == {"sugar", "purine5", "purine6"}


def test_a_residue_missing_a_sugar_atom_contributes_no_ring():
    assert ring_names_for(set(SUGAR_RING) - {"O4'"}) == []


# ── Model-level detector on a hand-built structure ────────────────────────────


@dataclass
class _FakeAtom:
    serial: int
    name: str
    x: float
    y: float
    z: float
    residue: str = "DT"
    chain_id: str = "A"
    seq_num: int = 1
    strand_id: str = "s"
    helix_id: str = "h"
    bp_index: int = 0
    direction: str = "FORWARD"
    crossover_id = None
    extra_base_k = None
    copy_k = None
    extension_id = None
    ext_k = None


class _FakeModel:
    def __init__(self, atoms, bonds):
        self.atoms = atoms
        self.bonds = bonds


def _ring_plus_bond(bond_x: float):
    """One residue's sugar ring, plus a two-atom bond on a second residue that runs
    along z through ``bond_x`` — through the ring centre at x=0, clear of it at x=1."""
    ring = _pentagon()
    atoms = [_FakeAtom(i, n, *p) for i, (n, p) in enumerate(zip(SUGAR_RING, ring))]
    n = len(atoms)
    atoms.append(_FakeAtom(n, "O3'", bond_x, 0.0, -0.2, seq_num=2))
    atoms.append(_FakeAtom(n + 1, "P", bond_x, 0.0, 0.2, seq_num=2))
    return _FakeModel(atoms, [(n, n + 1)])


def test_model_detector_finds_a_threaded_bond():
    hits = model_piercings(_ring_plus_bond(0.0))
    assert len(hits) == 1
    assert hits[0]["ring_kind"] == "sugar"
    assert hits[0]["bond"] == "A2DT:O3'-A2DT:P"


def test_model_detector_is_quiet_on_a_clear_bond():
    assert model_piercings(_ring_plus_bond(1.0)) == []


def test_a_bond_sharing_an_atom_with_the_ring_is_never_a_piercing():
    """The glycosidic bond leaves C1', which IS a ring atom; so do C3'-O3' and C4'-C5'.
    Those must never be reported, however the ring is oriented."""
    model = _ring_plus_bond(1.0)
    c1 = next(a for a in model.atoms if a.name == "C1'")
    n1 = _FakeAtom(len(model.atoms), "N1", -c1.x, -c1.y, 0.0)   # straight across the ring
    model.atoms.append(n1)
    model.bonds.append((c1.serial, n1.serial))
    assert model_piercings(model) == []


def test_scope_never_invents_a_bond_across_a_junction():
    """REGRESSION — the ladder's scope infers connectivity, and chain adjacency is wrong
    exactly where it matters.

    At a crossover carrying extra bases the two seq-adjacent duplex residues are no
    longer directly bonded (the inserts sit between them), and mid-build the inserts are
    not yet numbered into the chain.  Linking O3'(i) to P(i+1) there invented an ~0.8 nm
    bond straight across the junction, which then "pierced" every ring near it — on
    2hb_2xT that made three sound rungs, including the best one, look defective.
    """
    from backend.core.ring_piercing import _synthesise_bonds

    ring = _pentagon()
    residues = {}
    atoms = []
    # Residue 1: a full sugar ring, with its O3' 0.8 nm away from residue 3's P.
    for name, p in zip(SUGAR_RING, ring):
        atoms.append(_FakeAtom(len(atoms), name, *p, seq_num=1))
    atoms.append(_FakeAtom(len(atoms), "O3'", 0.0, 0.0, -0.4, seq_num=1))
    residues[("r1",)] = {a.name: a.serial for a in atoms}
    # Residue 3 — seq-adjacent to nothing real; its P is far away.
    p_atom = _FakeAtom(len(atoms), "P", 0.0, 0.0, 0.4, seq_num=2)
    atoms.append(p_atom)
    residues[("r3",)] = {"P": p_atom.serial}

    bonds = _synthesise_bonds(atoms, residues)
    assert (residues[("r1",)]["O3'"], p_atom.serial) not in bonds
    assert (p_atom.serial, residues[("r1",)]["O3'"]) not in bonds


def test_scope_still_finds_a_real_phosphodiester():
    """The distance rule must not throw the real bond away with the phantom."""
    from backend.core.ring_piercing import _synthesise_bonds

    o3 = _FakeAtom(0, "O3'", 0.0, 0.0, 0.0, seq_num=1)
    p = _FakeAtom(1, "P", 0.16, 0.0, 0.0, seq_num=2)      # canonical 1.6 A
    bonds = _synthesise_bonds([o3, p], {("r1",): {"O3'": 0}, ("r2",): {"P": 1}})
    assert (0, 1) in bonds


def test_scope_re_derives_connectivity_when_the_geometry_moves():
    """REGRESSION — a rung moves whole inserts, so which P an O3' bonds to changes with
    it.  Freezing the phosphodiester list at index time dropped the very bond a later
    rung created, and one threaded junction in 6hb_2xT went unseen by the ladder.
    """
    ring = _pentagon()
    atoms = [_FakeAtom(i, n, *p) for i, (n, p) in enumerate(zip(SUGAR_RING, ring))]
    n = len(atoms)
    # At index time the O3' is nowhere near the P — no bond, so nothing to pierce.
    atoms.append(_FakeAtom(n, "O3'", 5.0, 0.0, -0.2, seq_num=2))
    atoms.append(_FakeAtom(n + 1, "P", 0.0, 0.0, 0.2, seq_num=3))
    scope = PierceScope(atoms, {n, n + 1}, radius_nm=10.0)
    assert scope.count(atoms) == 0

    # Now a "rung" swings the O3' into place: the bond exists, and it runs through the
    # ring.  A frozen bond list would still report zero.
    atoms[n] = _FakeAtom(n, "O3'", 0.0, 0.0, -0.2, seq_num=2)
    assert scope.count(atoms) == 1


def test_assert_not_pierced_raises_and_the_override_lets_it_through():
    model = _ring_plus_bond(0.0)
    with pytest.raises(RingPiercedError):
        assert_not_pierced(None, model=model)
    report = assert_not_pierced(None, model=model, allow=True)
    assert report["override_used"] and report["n_pierced"] == 1


# ── Positive controls on real builds ──────────────────────────────────────────


@pytest.mark.parametrize("extra,bp", _KNOWN_PIERCING)
def test_known_piercing_phases_are_clean(extra, bp):
    """FAST GATE — every phase that used to ship a threaded ring must now come out
    clean.  ``TT`` at bp 8 is the synthetic analogue of the 2hb_2xT run."""
    report = piercing_report(_reciprocal_design(extra, bp=bp))
    assert report["n_pierced"] == 0, [h["bond"] for h in report["pierced"]]


@pytest.mark.slow
def test_detector_fires_when_the_piercing_check_is_disabled():
    """POSITIVE CONTROL — the detector is worthless if it is never seen going red.

    Also pins the causal claim: the pre-fix ladder is what threaded the ring, so the
    ranking term (not some incidental geometry change) is what prevents it.
    """
    design = _reciprocal_design("TT", bp=8)
    with _piercing_check_disabled():
        before = piercing_report(design, model=build_atomistic_model(design))
    assert before["n_pierced"] > 0

    import backend.core.atomistic_minimisers as _minimisers
    _minimisers._XB_CACHE.clear()
    after = piercing_report(design, model=build_atomistic_model(design))
    assert after["n_pierced"] == 0


@pytest.mark.slow
@pytest.mark.parametrize("extra", ["T", "TT"])
@pytest.mark.parametrize("bp", list(_PHASE_SWEEP))
def test_no_phase_pierces(extra, bp):
    """EXHAUSTIVE GATE — no helical phase may thread a ring, for any insert count.

    Whether a junction pierces is phase-dependent exactly as catenation is, so a
    fixture pinned to one bp proves nothing; the full-turn sweep is the criterion.
    """
    report = piercing_report(_reciprocal_design(extra, bp=bp))
    assert report["n_pierced"] == 0, [h["bond"] for h in report["pierced"]]


# ── The build gate ────────────────────────────────────────────────────────────


def test_gate_reports_both_defects():
    design = _reciprocal_design("TT", bp=8)
    report = gate_seed_topology(design)
    assert report["gate"] == "passed"
    assert report["n_catenated"] == 0
    assert report["n_ring_pierced"] == 0


def test_gate_refuses_a_pierced_seed():
    """The gate must refuse a threaded ring even when nothing is catenated.

    Needs `solve_extra_base_pose=True`: the per-insert joint solve is the only
    thing that manufactures a threaded ring (3 of them on this fixture), and it
    stopped being the default on 2026-08-05 — the default Bezier arc pose gives
    a clean seed here, so without the opt-in there is nothing for the gate to
    refuse and this asserts on an empty premise.
    """
    design = _reciprocal_design("TT", bp=8)
    with _piercing_check_disabled():
        model = build_atomistic_model(design, solve_extra_base_pose=True)
        with pytest.raises(RingPiercedError):
            gate_seed_topology(design, model=model)
        overridden = gate_seed_topology(design, model=model, allow=True)
    assert overridden["gate"] == "overridden"
    assert overridden["n_ring_pierced"] > 0


def test_designs_without_inserts_skip_the_gate_entirely():
    report = gate_seed_topology(_reciprocal_design(None, bp=12))
    assert report["gate"] == "skipped_no_extra_bases"
    assert report["n_ring_pierced"] == 0


# ── The ladder's scoped check agrees with the model-level one ─────────────────


@pytest.mark.slow
def test_scoped_and_model_detectors_agree_on_a_pierced_build():
    """The ladder cannot afford the model-level scan, so it uses a neighbourhood scope.
    If the two disagree, the ladder is optimising against a different defect than the
    gate refuses."""
    design = _reciprocal_design("TT", bp=8)
    with _piercing_check_disabled():
        # Same reason as test_gate_refuses_a_pierced_seed: only the joint solve
        # builds a pierced model, and it is no longer the default.
        model = build_atomistic_model(design, solve_extra_base_pose=True)
    model_hits = model_piercings(model)
    assert model_hits

    focus = {s for h in model_hits for s in h["bond_serials"] + h["ring_serials"]}
    scope = PierceScope(model.atoms, focus)
    scoped = scope.hits(model.atoms)
    assert {tuple(sorted(h["bond_serials"])) for h in scoped} == \
           {tuple(sorted(h["bond_serials"])) for h in model_hits}
