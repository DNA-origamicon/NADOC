"""Regression contracts for R1–R9 (no native engines or workspace fixtures)."""
import pytest

from backend.core.lattice import make_bundle_design, _ligate
from backend.core.models import (Crossover, Design, Direction, Domain, ForcedLigation,
                                HalfCrossover, LatticeType, LoopSkip, Strand, StrandType)
from backend.core.scaffold_reset import reset_scaffold_to_structure
from backend.core.scaffold_safety import sequence_keys, _has_backbone_edge
from backend.core.seamed_router import (auto_scaffold_seamed, auto_scaffold_matched,
                                       auto_scaffold_seamed_bounded, _place_xover)
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.sequences import strand_sequence_length
from backend.core.topology_integrity import occupancy_errors, forced_edge
from backend.core.validator import validate_design

ROUTERS = [auto_scaffold_seamed, auto_scaffold_matched, auto_scaffold_seamed_bounded, auto_scaffold_seamless]


def bundle(lattice=LatticeType.HONEYCOMB):
    return make_bundle_design([(0, 0), (0, 1), (1, 0), (1, 1)], 84, lattice_type=lattice)


def owners(d):
    return {k for s in d.strands if not s.is_reference for k in sequence_keys(d, s)}


@pytest.mark.parametrize("router", ROUTERS)
@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("face", ["low", "high"])
def test_obstructed_turn_rejects_atomically(router, lattice, face):
    original = bundle(lattice)
    clean, _ = router(original)
    added = sorted(k for k in owners(clean) - owners(original) if (k[1] < 0 if face == "low" else k[1] >= 84))
    assert added, "control must actually extend this face"
    hid, bp, dr, _ = added[len(added) // 2]
    obstacle = Strand(id="deliberate_linker", strand_type=StrandType.LINKER,
                      domains=[Domain(helix_id=hid, start_bp=bp, end_bp=bp, direction=dr)])
    d = original.copy_with(strands=[*original.strands, obstacle])
    before = d.model_dump()
    out, report = router(d)
    assert out.model_dump() == before
    assert d.model_dump() == before
    assert not occupancy_errors(out)
    assert not report.valid
    assert any("rejected" in w.lower() for w in report.warnings)


@pytest.mark.parametrize("router", ROUTERS)
def test_reference_does_not_change_route(router):
    d = bundle()
    obstacle = Strand(id="reference", strand_type=StrandType.LINKER, is_reference=True,
                      domains=[Domain(helix_id=d.helices[1].id, start_bp=-4, end_bp=-9, direction=Direction.REVERSE)])
    a, _ = router(d)
    b, _ = router(d.copy_with(strands=[*d.strands, obstacle]))
    def path(x):
        return sorted((dm.helix_id, dm.start_bp, dm.end_bp, dm.direction.value)
                      for s in x.strands if not s.is_reference for dm in s.domains)
    assert path(a) == path(b)


def forced_design():
    d = bundle()
    a, b = [s for s in d.strands if s.is_scaffold][:2]
    da, db = a.domains[-1], b.domains[0]
    fl = ForcedLigation(id="user_deliberate_join", three_prime_helix_id=da.helix_id,
        three_prime_bp=da.end_bp, three_prime_direction=da.direction,
        five_prime_helix_id=db.helix_id, five_prime_bp=db.start_bp,
        five_prime_direction=db.direction, extra_bases="TT", is_periodic_seam=True)
    d = _ligate(d, a, b).copy_with(forced_ligations=[fl])
    return d, fl


@pytest.mark.parametrize("router", ROUTERS)
def test_user_forced_scaffold_ligation_survives_routing_and_reset(router):
    d, fl = forced_design()
    before = d.model_dump()
    reset, warnings = reset_scaffold_to_structure(d)
    assert reset.model_dump() == before
    assert warnings
    out, _ = router(d)
    assert d.model_dump() == before
    assert _has_backbone_edge(out, forced_edge(fl))
    assert next(f for f in out.forced_ligations if f.id == fl.id).model_dump() == fl.model_dump()
    again, _ = router(out)
    assert _has_backbone_edge(again, forced_edge(fl))
    assert next(f for f in again.forced_ligations if f.id == fl.id).model_dump() == fl.model_dump()


def test_reset_never_deletes_unstapled_piece_of_existing_path():
    d, _ = forced_design()
    d = d.copy_with(forced_ligations=[])
    hid = d.helices[1].id
    d.strands = [s for s in d.strands if not (s.strand_type == StrandType.STAPLE and s.domains[0].helix_id == hid)]
    before = d.model_dump()
    out, _ = reset_scaffold_to_structure(d)
    assert out.model_dump() == before


def test_reset_keeps_gap_even_in_previously_routed_design():
    d, _ = auto_scaffold_seamed(bundle())
    # Remove a nine-base interval from an internal scaffold domain while retaining
    # the prior route markers. This models deliberate edits after autorouting.
    s = next(s for s in d.strands if s.is_scaffold)
    di, dm = next((i, dm) for i, dm in enumerate(s.domains)
                  if dm.direction == Direction.FORWARD and abs(dm.end_bp-dm.start_bp) > 30)
    lo = max(5, dm.start_bp + 5)
    s.domains[di:di+1] = [dm.model_copy(update={"end_bp": lo}), dm.model_copy(update={"start_bp": lo+10})]
    out, _ = reset_scaffold_to_structure(d)
    assert all((dm.helix_id, bp, "FORWARD", 0) not in owners(out) for bp in range(lo+1, lo+10))


@pytest.mark.parametrize("router", ROUTERS)
def test_routing_and_reset_preserve_assigned_nucleotide_identities(router):
    d = bundle()
    d.helices[0].loop_skips = [LoopSkip(bp_index=10, delta=1), LoopSkip(bp_index=12, delta=-1)]
    for s in d.strands:
        if s.is_scaffold:
            n = strand_sequence_length(d, s)
            s.sequence = ("ACGT" * (n//4+1))[:n]
    assigned = {k: base for s in d.strands if s.is_scaffold for k, base in zip(sequence_keys(d, s), s.sequence)}
    routed, _ = router(d)
    assert any(x.process_id for x in routed.crossovers), "must route, not just reject"
    for result in (routed, reset_scaffold_to_structure(routed)[0], router(routed)[0]):
        for s in result.strands:
            if s.is_scaffold:
                assert s.sequence is not None
                assert len(s.sequence) == strand_sequence_length(result, s)
                for key, base in zip(sequence_keys(result, s), s.sequence):
                    assert base == assigned.get(key, "N")


def test_rejected_crossover_does_not_leave_nicks():
    d = bundle()
    a = HalfCrossover(helix_id=d.helices[0].id, index=20, strand=Direction.FORWARD)
    b = HalfCrossover(helix_id=d.helices[1].id, index=21, strand=Direction.REVERSE)
    before = d.model_dump()
    out, xo = _place_xover(d, a, b, 20, 20, "test", [])
    assert xo is None
    assert out.model_dump() == before


@pytest.mark.parametrize("kind", ["overlap", "self_overlap", "direction", "missing_helix", "orphan_fl", "duplicate_xo", "missing_records"])
def test_validator_catches_corrupt_topology(kind):
    d = bundle()
    s = d.strands[0]
    if kind == "overlap": d.strands.append(s.model_copy(update={"id": "duplicate"}))
    elif kind == "self_overlap": s.domains.append(s.domains[0].model_copy())
    elif kind == "direction": s.domains[0].start_bp, s.domains[0].end_bp = 83, 0
    elif kind == "missing_helix":
        d.crossovers = [Crossover(half_a=HalfCrossover(helix_id="absent-a", index=5, strand="FORWARD"),
                                  half_b=HalfCrossover(helix_id="absent-b", index=5, strand="REVERSE"))]
    elif kind == "orphan_fl":
        _, fl = forced_design()
        d.forced_ligations = [fl.model_copy(update={"three_prime_helix_id": "absent"})]
    else:
        d, _ = auto_scaffold_seamed(d)
        if kind == "duplicate_xo": d.crossovers.append(d.crossovers[0].model_copy(update={"id": "duplicate"}))
        else: d.crossovers = []
    assert not validate_design(Design.model_validate(d.model_dump())).passed


def test_validator_accepts_correct_insertion_sequence_rejects_short_one():
    d = bundle()
    s = d.strands[0]
    d.helices[0].loop_skips = [LoopSkip(bp_index=10, delta=1)]
    s.sequence = "A" * 85
    assert validate_design(d).passed
    s.sequence = "A" * 84
    assert not validate_design(d).passed


def test_validator_preserves_valid_forced_periodic_connection():
    d, _ = forced_design()
    assert validate_design(d).passed


def test_rejected_route_does_not_commit_feature_history(monkeypatch):
    from fastapi import HTTPException
    from backend.api import state
    from backend.api.routes_scaffold_routing import _run_auto_scaffold_with_feature_log
    monkeypatch.setattr(state, "_sessions", {})
    d = bundle()
    d.strands.append(Strand(id="obstacle", strand_type=StrandType.LINKER,
        domains=[Domain(helix_id=d.helices[1].id, start_bp=-4, end_bp=-9, direction="REVERSE")]))
    state.load_design(d)
    before = state.get_or_404().model_dump()
    with pytest.raises(HTTPException) as exc:
        _run_auto_scaffold_with_feature_log("auto-scaffold-seamed", "test", {}, auto_scaffold_seamed)
    assert exc.value.status_code == 422
    assert state.get_or_404().model_dump() == before
