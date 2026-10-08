"""Route an authored continuous duplex across helix records without capping its join."""

from __future__ import annotations

import uuid

import pytest

from backend.core.constants import BDNA_RISE_PER_BP, HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
from backend.core.crossover_positions import scaffold_seam_positions
from backend.core.lattice import make_bundle_design
from backend.core.models import Design, ForcedLigation, LatticeType, LoopSkip
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.scaffold_safety import sequence_keys
from backend.core.seamed_router import auto_scaffold_seamed
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.sequences import strand_sequence_length
from backend.core.sweep import SweepRequest, build_sweep
from backend.core.validator import validate_design


HC_SOURCE = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
HC_SWEEP = [(1, 2), (0, 3), (0, 2), (0, 1), (1, 1), (1, 3), (1, 4), (1, 5), (0, 5), (0, 4)]
SQ_SOURCE = [(r, c) for r in range(2) for c in range(2)]
SQ_SWEEP = [(r, c) for r in range(2) for c in range(4)]
ROUTERS = [pytest.param(auto_scaffold_seamed, True, id="seamed"),
           pytest.param(auto_scaffold_seamless, False, id="seamless")]


def _seed(*, end="end", lattice=LatticeType.HONEYCOMB, chained=False):
    """Same 6→10 topology and bend as Sweep_test, without using its workspace file."""
    cells, swept = (HC_SOURCE, HC_SWEEP) if lattice == LatticeType.HONEYCOMB else (SQ_SOURCE, SQ_SWEEP)
    source = make_bundle_design(cells, 63, lattice_type=lattice)
    sign = 1 if end == "end" else -1
    points = [(0, 0, 0), (0, 9.198, sign * 22.928), (-14.455, 34.910, sign * 27.109)]
    design = build_sweep(source, SweepRequest(
        sweep_id=uuid.UUID(int=1001), cells=swept, points_nm=points,
        source_helix_id=source.helices[0].id, source_end=end,
        ligate_adjacent=False,
    ))
    if chained:
        design = build_sweep(design, SweepRequest(
            sweep_id=uuid.UUID(int=1002), cells=swept,
            points_nm=[(0, 0, 0), (5, 5, 15)],
            source_helix_id=design.helices[-1].id,
            ligate_adjacent=False,
        ))
    return design


def _edges(design, *, scaffold=True):
    return {
        ((a.helix_id, a.end_bp, a.direction.value), (b.helix_id, b.start_bp, b.direction.value))
        for strand in design.strands if not strand.is_reference and strand.is_scaffold == scaffold
        for a, b in zip(strand.domains, strand.domains[1:])
        if a.helix_id != b.helix_id
    }


def _with_records(design, mode):
    edges = set()
    if mode in {"scaffold", "both"}:
        edges |= _edges(design)
    if mode in {"staple", "both"}:
        edges |= _edges(design, scaffold=False)
    records = [ForcedLigation(
        id=f"authored-interface-{i}",
        three_prime_helix_id=a[0], three_prime_bp=a[1], three_prime_direction=a[2],
        five_prime_helix_id=b[0], five_prime_bp=b[1], five_prime_direction=b[2],
        is_periodic_seam=(i == 0),
    ) for i, (a, b) in enumerate(sorted(edges))]
    return design.copy_with(forced_ligations=records)


def _topology(design):
    return (
        sorted((h.id, h.bp_start, h.length_bp, round(h.phase_offset, 9)) for h in design.helices),
        sorted((d.helix_id, d.start_bp, d.end_bp, d.direction.value)
               for s in design.scaffolds() for d in s.domains),
        sorted(tuple(sorted((h.helix_id, h.index, h.strand.value)
                            for h in (x.half_a, x.half_b))) for x in design.crossovers),
    )


def _assert_routed_contract(seed, out, *, seamed):
    scaffolds = [s for s in out.scaffolds() if not s.is_reference]
    assert len(scaffolds) == 1
    assert _edges(seed) <= _edges(out), "A pre-existing directed scaffold connection was interrupted"
    assert _edges(seed, scaffold=False) == _edges(out, scaffold=False)
    assert out.forced_ligations == seed.forced_ligations
    assert out.deformations == seed.deformations
    assert out.lattice_frames == seed.lattice_frames
    assert out.cluster_transforms == seed.cluster_transforms
    assert [s for s in out.strands if not s.is_scaffold] == [s for s in seed.strands if not s.is_scaffold]

    report = validate_design(out)
    assert report.passed, report
    assert scaffold_routing_invariants(out, require_seams=seamed) == []
    if not seamed:
        assert scaffold_seam_positions(out) == {}, "Seamless routing introduced an internal double crossover"
    first, last = scaffolds[0].domains[0], scaffolds[0].domains[-1]
    assert first.helix_id == last.helix_id
    assert first.direction == last.direction
    step = 1 if first.direction.value == "FORWARD" else -1
    assert last.end_bp + step == first.start_bp, "The sole scaffold nick must reopen a closed route"

    originals = {h.id: h for h in seed.helices}
    restored = {h.id: h for h in out.helices}
    assert originals.keys() == restored.keys()
    period = HC_CROSSOVER_PERIOD if seed.lattice_type == LatticeType.HONEYCOMB else SQ_CROSSOVER_PERIOD
    for hid, old in originals.items():
        new = restored[hid]
        assert new.grid_pos == old.grid_pos
        assert new.direction == old.direction
        assert new.lattice_frame_id == old.lattice_frame_id
        assert new.loop_skips == old.loop_skips
        assert 0 <= old.bp_start - new.bp_start <= period
        assert 0 <= (new.bp_start + new.length_bp) - (old.bp_start + old.length_bp) <= period
    for a, b in _edges(seed) | _edges(seed, scaffold=False):
        low, high = (a, b) if a[1] < b[1] else (b, a)
        assert restored[low[0]].bp_start + restored[low[0]].length_bp - 1 == low[1]
        assert restored[high[0]].bp_start == high[1]

    original_sites = {key for s in seed.scaffolds() for key in sequence_keys(seed, s)}
    routed_sites = {key for s in out.scaffolds() for key in sequence_keys(out, s)}
    assert original_sites <= routed_sites, "Routing lost existing scaffold material"


@pytest.mark.parametrize("router,seamed", ROUTERS)
@pytest.mark.parametrize("records", ["ordinary", "scaffold", "staple", "both"])
def test_expanding_sweep_routes_one_scaffold_and_preserves_all_interface_bonds(router, seamed, records):
    seed = _with_records(_seed(), records)
    assert len(_edges(seed)) == 6
    before = seed.model_dump()
    out, result = router(seed)
    assert result.valid, result.errors
    assert seed.model_dump() == before
    _assert_routed_contract(seed, out, seamed=seamed)


@pytest.mark.parametrize("router,seamed", ROUTERS)
@pytest.mark.parametrize("variant", ["negative-end", "square", "chained"])
def test_continuation_routing_handles_reversed_ends_square_lattice_and_multiple_segments(router, seamed, variant):
    seed = _seed(end="start" if variant == "negative-end" else "end",
                 lattice=LatticeType.SQUARE if variant == "square" else LatticeType.HONEYCOMB,
                 chained=variant == "chained")
    before = seed.model_dump()
    out, result = router(seed)
    assert result.valid, result.errors
    assert seed.model_dump() == before
    _assert_routed_contract(seed, out, seamed=seamed)


@pytest.mark.parametrize("router,seamed", ROUTERS)
def test_routing_saved_sweep_is_idempotent_and_keeps_assigned_nucleotide_identity(router, seamed):
    seed = _with_records(_seed(), "both")
    seed.helices[0].loop_skips = [LoopSkip(bp_index=10, delta=1), LoopSkip(bp_index=12, delta=-1)]
    for i, strand in enumerate(seed.scaffolds()):
        n = strand_sequence_length(seed, strand)
        strand.sequence = ("ACGT" * (n // 4 + 2))[i % 4:i % 4 + n]
    original = {key: base for s in seed.scaffolds() for key, base in zip(sequence_keys(seed, s), s.sequence)}
    before = seed.model_dump()
    once, report = router(seed)
    assert report.valid, report.errors
    restored = Design.from_json(once.to_json())
    twice, report = router(restored)
    assert report.valid, report.errors
    assert _topology(twice) == _topology(once)
    assert seed.model_dump() == before
    for out in (once, twice):
        _assert_routed_contract(seed, out, seamed=seamed)
        for strand in out.scaffolds():
            assert strand.sequence is not None
            assert len(strand.sequence) == strand_sequence_length(out, strand)
            for key, base in zip(sequence_keys(out, strand), strand.sequence):
                assert base == original.get(key, "N")


@pytest.mark.parametrize("router,seamed", ROUTERS)
def test_a_forced_interface_with_inserted_bases_is_preserved_on_rejected_routing(router, seamed):
    seed = _with_records(_seed(), "both")
    scaffold_edge = min(_edges(seed))
    records = []
    for fl in seed.forced_ligations:
        edge = ((fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction.value),
                (fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction.value))
        records.append(fl.model_copy(update={"extra_bases": "TT"}) if edge == scaffold_edge else fl)
    seed = seed.copy_with(forced_ligations=records)
    before = seed.model_dump()
    out, result = router(seed)
    assert not result.valid
    assert out.model_dump() == before
    assert seed.model_dump() == before


@pytest.mark.parametrize("router,seamed", ROUTERS)
@pytest.mark.parametrize("nick_all", [False, True], ids=["one-scaffold-nick", "all-scaffold-nicks"])
def test_staple_continuity_identifies_the_track_even_when_scaffold_is_nicked(router, seamed, nick_all):
    seed = _seed()
    strands, split_count = [], 0
    for strand in seed.strands:
        if strand.is_scaffold and len(strand.domains) > 1 and (nick_all or split_count == 0):
            strands.extend(strand.model_copy(update={"id": f"{strand.id}_piece_{i}", "domains": [dm]})
                           for i, dm in enumerate(strand.domains))
            split_count += 1
        else:
            strands.append(strand)
    seed = seed.copy_with(strands=strands)
    assert split_count == (6 if nick_all else 1)
    assert len(_edges(seed, scaffold=False)) == 6
    before = seed.model_dump()
    out, result = router(seed)
    assert result.valid, result.errors
    assert seed.model_dump() == before
    _assert_routed_contract(seed, out, seamed=seamed)


@pytest.mark.parametrize("router,seamed", ROUTERS)
def test_internal_forced_join_cannot_recut_a_helix_to_manufacture_an_end(router, seamed):
    seed = _with_records(_seed(), "both")
    a, b = min(_edges(seed))
    source = a if a[1] < b[1] else b
    old = seed.find_helix(source[0])
    # The authored backbone still joins at 62→63, but the source helix itself
    # intentionally extends another five empty base-pair positions. Routing
    # cannot silently shorten that helix to turn an internal join into an end.
    longer = old.model_copy(update={
        "length_bp": old.length_bp + 5,
        "axis_end": old.axis_end.model_copy(update={"z": old.axis_end.z + 5 * BDNA_RISE_PER_BP}),
    })
    seed = seed.copy_with(helices=[longer if h.id == old.id else h for h in seed.helices])
    before = seed.model_dump()
    out, result = router(seed)
    assert not result.valid
    assert any("ends of its helix segments" in error for error in result.errors)
    assert out.model_dump() == before
    assert seed.model_dump() == before


def test_six_to_eight_sweep_without_seamless_cycle_rejects_interior_seam_fallback():
    source = make_bundle_design(HC_SOURCE, 63, lattice_type=LatticeType.HONEYCOMB)
    seed = build_sweep(source, SweepRequest(
        sweep_id=uuid.UUID(int=1003), cells=[*HC_SOURCE, (0, 4), (0, 5)],
        points_nm=[(0, 0, 0), (0, 0, 56)],
        source_helix_id=source.helices[0].id, ligate_adjacent=False,
    ))
    assert len(_edges(seed)) == 6
    before = seed.model_dump()
    out, result = auto_scaffold_seamless(seed)
    assert not result.valid
    assert any("No seamless route preserving the track ends" in error for error in result.errors)
    assert out.model_dump() == before, "A failed cycle search must not commit interior seams or fragments"
    assert seed.model_dump() == before
