"""Importer classification of cross-helix domain transitions.

After this audit, ``extract_crossovers_from_strands`` classifies each
transition as either a Crossover (same bp index AND lattice-valid neighbour)
or a ForcedLigation (everything else — bp mismatch, non-neighbour helices,
scadnano-style loopouts).
"""

from __future__ import annotations

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.crossover_positions import extract_crossovers_from_strands
from backend.core.models import (
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)


def _helix(h_id: str, *, grid_pos: tuple[int, int], length: int = 200, bp_start: int = 0) -> Helix:
    return Helix(
        id=h_id,
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=length * BDNA_RISE_PER_BP),
        length_bp=length,
        bp_start=bp_start,
        grid_pos=list(grid_pos),
    )


# ── Same bp + valid lattice neighbour → Crossover ────────────────────────────


def test_same_bp_valid_neighbor_emits_crossover():
    """SQ scaffold offset table maps (True, 7) → (+1, 0): two cells one row apart
    are neighbours at bp index 7 in the FORWARD scaffold direction.
    """
    h0 = _helix("h0", grid_pos=(0, 0))
    h1 = _helix("h1", grid_pos=(1, 0))
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=7,  direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=7,  end_bp=20, direction=Direction.REVERSE),
        ],
    )
    xos, fls = extract_crossovers_from_strands([s], [h0, h1], LatticeType.SQUARE)
    assert len(xos) == 1
    assert len(fls) == 0


# ── Different bp index on either side → ForcedLigation ──────────────────────


def test_mismatched_bp_emits_forced_ligation():
    """Mirrors scadnano-style loopouts: d0.end_bp != d1.start_bp must produce
    a ForcedLigation, not a Crossover (and not silently dropped).
    """
    h0 = _helix("h0", grid_pos=(0, 0))
    h1 = _helix("h1", grid_pos=(1, 0))
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=10, direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=15, end_bp=25, direction=Direction.REVERSE),
        ],
    )
    xos, fls = extract_crossovers_from_strands([s], [h0, h1], LatticeType.SQUARE)
    assert len(xos) == 0
    assert len(fls) == 1
    fl = fls[0]
    assert (fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction) == (
        "h0", 10, Direction.FORWARD,
    )
    assert (fl.five_prime_helix_id,  fl.five_prime_bp,  fl.five_prime_direction) == (
        "h1", 15, Direction.REVERSE,
    )


# ── Same bp but helices are NOT lattice neighbours → ForcedLigation ─────────


def test_same_bp_non_neighbor_emits_forced_ligation():
    """Two helices three rows apart cannot form a DX crossover even at a
    valid bp index — must be classified as ForcedLigation.
    """
    h0 = _helix("h0", grid_pos=(0, 0))
    h_far = _helix("h_far", grid_pos=(3, 0))
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0",    start_bp=0, end_bp=7, direction=Direction.FORWARD),
            Domain(helix_id="h_far", start_bp=7, end_bp=20, direction=Direction.REVERSE),
        ],
    )
    xos, fls = extract_crossovers_from_strands([s], [h0, h_far], LatticeType.SQUARE)
    assert len(xos) == 0
    assert len(fls) == 1


# ── Same helix transition is never a junction ───────────────────────────────


def test_same_helix_consecutive_domains_skipped():
    """Two consecutive same-helix domains are NOT a cross-helix junction;
    they must produce neither a Crossover nor a ForcedLigation.
    """
    h0 = _helix("h0", grid_pos=(0, 0))
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=10, direction=Direction.FORWARD),
            Domain(helix_id="h0", start_bp=11, end_bp=20, direction=Direction.FORWARD),
        ],
    )
    xos, fls = extract_crossovers_from_strands([s], [h0], LatticeType.SQUARE)
    assert len(xos) == 0
    assert len(fls) == 0


# ── No-context fallback preserves old behaviour ─────────────────────────────


def test_no_lattice_context_falls_back_to_same_bp_only():
    """When called without helices/lattice (legacy callers without Design
    context), the lattice-neighbour test is skipped and only same-bp
    transitions are classified as Crossovers.
    """
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=7,  direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=7,  end_bp=20, direction=Direction.REVERSE),
            Domain(helix_id="h2", start_bp=25, end_bp=30, direction=Direction.FORWARD),
        ],
    )
    xos, fls = extract_crossovers_from_strands([s])
    # h0→h1 same-bp → Crossover; h1→h2 different-bp → ForcedLigation.
    assert len(xos) == 1
    assert len(fls) == 1


# ── Each transition recorded once across overlapping strands ─────────────────


def test_from_json_backfills_dropped_forced_ligations():
    """A .nadoc saved by an old importer (which silently dropped mismatched-bp
    cross-helix transitions) gets its missing ForcedLigations restored on load.
    Existing Crossover and ForcedLigation records are preserved verbatim.
    """
    from backend.core.models import Design

    h0 = _helix("h0", grid_pos=(0, 0))
    h1 = _helix("h1", grid_pos=(1, 0))
    h2 = _helix("h2", grid_pos=(2, 0))
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=7,  direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=7,  end_bp=20, direction=Direction.REVERSE),
            # Cross-helix transition with mismatched bp (loopout-style):
            Domain(helix_id="h2", start_bp=25, end_bp=30, direction=Direction.FORWARD),
        ],
    )
    # Hand-craft a design that has the h0→h1 crossover but is MISSING the
    # h1→h2 forced ligation (mimics a file saved by the old importer).
    from backend.core.models import Crossover, HalfCrossover
    pre_xo = Crossover(
        half_a=HalfCrossover(helix_id="h0", index=7, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="h1", index=7, strand=Direction.REVERSE),
    )
    d = Design(
        helices=[h0, h1, h2],
        strands=[s],
        crossovers=[pre_xo],
        lattice_type=LatticeType.SQUARE,
    )
    json_text = d.to_json()
    reloaded = Design.from_json(json_text)
    # Original crossover preserved.
    assert len(reloaded.crossovers) == 1
    assert reloaded.crossovers[0].half_a.index == 7
    # Missing FL backfilled for the h1→h2 transition.
    assert len(reloaded.forced_ligations) == 1
    fl = reloaded.forced_ligations[0]
    assert (fl.three_prime_helix_id, fl.three_prime_bp) == ("h1", 20)
    assert (fl.five_prime_helix_id,  fl.five_prime_bp)  == ("h2", 25)


def test_from_json_backfill_idempotent():
    """Loading twice (e.g. save → load → save → load) produces no duplicate
    FLs because the second pass sees the previously-backfilled records as
    'covered' and skips them.
    """
    from backend.core.models import Design

    h0 = _helix("h0", grid_pos=(0, 0))
    h1 = _helix("h1", grid_pos=(1, 0))
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=10, direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=15, end_bp=20, direction=Direction.REVERSE),
        ],
    )
    d = Design(helices=[h0, h1], strands=[s], lattice_type=LatticeType.SQUARE)
    once = Design.from_json(d.to_json())
    twice = Design.from_json(once.to_json())
    assert len(once.forced_ligations) == 1
    assert len(twice.forced_ligations) == 1


def test_from_json_reclassifies_non_neighbour_crossovers_as_fls():
    """Crossover records whose two halves share a bp index but whose helices
    aren't lattice-neighbours at that bp must be reclassified as
    ForcedLigations on load (older cadnano imports kept them as Crossovers).
    """
    from backend.core.models import Crossover, Design, HalfCrossover

    h0 = _helix("h0",   grid_pos=(0, 0))
    h_far = _helix("h2", grid_pos=(2, 0))   # 2 rows away → never a neighbour
    s = Strand(
        id="s",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0, end_bp=10, direction=Direction.FORWARD),
            Domain(helix_id="h2", start_bp=10, end_bp=20, direction=Direction.REVERSE),
        ],
    )
    bad_xo = Crossover(
        half_a=HalfCrossover(helix_id="h0", index=10, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="h2", index=10, strand=Direction.REVERSE),
    )
    d = Design(
        helices=[h0, h_far],
        strands=[s],
        crossovers=[bad_xo],
        lattice_type=LatticeType.SQUARE,
    )
    reloaded = Design.from_json(d.to_json())
    assert len(reloaded.crossovers) == 0
    assert len(reloaded.forced_ligations) == 1
    fl = reloaded.forced_ligations[0]
    assert (fl.three_prime_helix_id, fl.three_prime_bp) == ("h0", 10)
    assert (fl.five_prime_helix_id,  fl.five_prime_bp)  == ("h2", 10)


def test_from_json_keeps_valid_neighbour_crossovers():
    """Valid same-bp + lattice-neighbour Crossovers must NOT be reclassified."""
    from backend.core.models import Crossover, Design, HalfCrossover

    h0 = _helix("h0", grid_pos=(0, 0))
    h1 = _helix("h1", grid_pos=(1, 0))   # adjacent
    s = Strand(
        id="s",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=7, end_bp=20, direction=Direction.REVERSE),
        ],
    )
    good_xo = Crossover(
        half_a=HalfCrossover(helix_id="h0", index=7, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="h1", index=7, strand=Direction.REVERSE),
    )
    d = Design(
        helices=[h0, h1],
        strands=[s],
        crossovers=[good_xo],
        lattice_type=LatticeType.SQUARE,
    )
    reloaded = Design.from_json(d.to_json())
    assert len(reloaded.crossovers) == 1
    assert len(reloaded.forced_ligations) == 0


def test_duplicate_transitions_dedup():
    h0 = _helix("h0", grid_pos=(0, 0))
    h1 = _helix("h1", grid_pos=(1, 0))
    sA = Strand(
        id="sA",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=10, direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=15, end_bp=20, direction=Direction.REVERSE),
        ],
    )
    sB = Strand(
        id="sB",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=10, direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=15, end_bp=20, direction=Direction.REVERSE),
        ],
    )
    xos, fls = extract_crossovers_from_strands([sA, sB], [h0, h1], LatticeType.SQUARE)
    assert len(xos) == 0
    assert len(fls) == 1
