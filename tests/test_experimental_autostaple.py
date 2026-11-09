"""42 bp routing on native, recorded standard honeycomb bundles."""
from collections import defaultdict
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api import headless_build as hb
from backend.core.experimental_autostaple import ExperimentalAutostaple, retain_boundary
from backend.core.models import Design, LatticeType, StrandType
from backend.core.occupancy import occupancy_conflicts
from scripts.agent_structure_guard import audit, publish

HC6 = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
# Read the existing standard design's cross-section only; author the test through
# the native bundle and routing commands, never through a captured/import root.
HC18 = [(h['row'], h['col']) for h in json.loads(
    (Path(__file__).parents[1] / 'Examples/cadnano/Honeycomb_18hb_test1.json').read_text())['vstrands']]


def coverage(design):
    return {(d.helix_id, b, d.direction) for s in design.strands if s.strand_type == StrandType.STAPLE
            for d in s.domains for b in range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp) + 1)}


def sites(design):
    groups = defaultdict(list)
    for x in design.crossovers:
        if x.process_id == 'auto_crossover':
            groups[(*sorted((x.half_a.helix_id, x.half_b.helix_id)), x.half_a.index % 21)].append(x.half_a.index)
    return groups


def test_pair_boundary_selection():
    a, b = ExperimentalAutostaple(), ExperimentalAutostaple(pattern=1)
    for lower in range(-84, 85):
        assert retain_boundary(lower, a) != retain_boundary(lower, b)
        assert retain_boundary(lower, a) == retain_boundary(lower + 42, a)
        assert retain_boundary(lower, None)
    assert retain_boundary(20, a) and not retain_boundary(41, a)


@pytest.mark.parametrize('cells', [HC6, HC18], ids=['6hb', '18hb'])
@pytest.mark.parametrize('pattern', [0, 1])
def test_42bp_bundle_recorded_roundtrip(cells, pattern, tmp_path):
    with hb.scratch_session():
        original = hb.create_bundle(cells, 168, lattice=LatticeType.HONEYCOMB, name='Experimental spacing')
        assert len(original.helices) == len(cells)
        hb.auto_scaffold()
        standard = hb.full_autostaple()
        routed = hb.full_autostaple(experimental={'pattern': pattern})
        assert coverage(routed) == coverage(original)
        assert not occupancy_conflicts(routed)[0]
        assert [s for s in routed.strands if s.strand_type == StrandType.SCAFFOLD] == [
            s for s in standard.strands if s.strand_type == StrandType.SCAFFOLD]
        connected = {routed.helices[0].id}
        edges = [(key[0], key[1]) for key in sites(routed)]
        for _ in routed.helices:
            connected |= {h for pair in edges if connected.intersection(pair) for h in pair}
        assert connected == {h.id for h in routed.helices}
        diffs = [b-a for values in sites(routed).values() for a, b in zip(sorted(values), sorted(values)[1:])]
        assert 42 in diffs
        assert all(gap >= 42 and gap % 42 == 0 for gap in diffs)
        assert sum(map(len, sites(routed).values())) < sum(map(len, sites(standard).values()))
        for values in sites(routed).values():
            for bp in values:
                lower = bp - 1 if bp % 21 in (0, 7, 14) else bp
                assert (lower // 21) % 2 == pattern
        long_domains = lambda d: sum(abs(dom.end_bp - dom.start_bp) + 1 >= 28
                                     for strand in d.strands if strand.strand_type == StrandType.STAPLE
                                     for dom in strand.domains)
        assert long_domains(routed) > long_domains(standard)
        assert routed.feature_log[-1].params['experimental']['crossover_repeat_bp'] == 42
        # Each auto crossover must actually be traversed by a staple.
        traversed = {(a.helix_id, a.end_bp, b.helix_id, b.start_bp)
                     for s in routed.strands if s.strand_type == StrandType.STAPLE
                     for a, b in zip(s.domains, s.domains[1:])}
        for x in routed.crossovers:
            if x.process_id == 'auto_crossover':
                a, b = x.half_a, x.half_b
                assert (a.helix_id, a.index, b.helix_id, b.index) in traversed or (b.helix_id, b.index, a.helix_id, a.index) in traversed
        saved = tmp_path / 'experimental.nadoc'
        try:
            assert publish(routed, saved)['status'] == 'verified'
            reopened = Design.model_validate_json(saved.read_text())
            assert reopened.feature_log[-1].params['experimental']['pattern'] == pattern
            assert audit(reopened)['status'] == 'verified'
        finally:
            saved.unlink(missing_ok=True)


def test_invalid_options():
    with pytest.raises(ValueError):
        ExperimentalAutostaple(crossover_repeat_bp=32)
    with pytest.raises(ValueError):
        ExperimentalAutostaple(min_length=80, max_merged_length=56)
    with hb.scratch_session():
        hb.create_bundle([(0, 0), (0, 1)], 84, lattice=LatticeType.SQUARE)
        with pytest.raises(HTTPException, match='honeycomb'):
            hb.full_autostaple(experimental={})


def topology(design):
    return sorted(tuple((d.helix_id, d.start_bp, d.end_bp, d.direction.value) for d in s.domains)
                  for s in design.strands if s.strand_type == StrandType.STAPLE)


def test_standard_compatibility_and_regional_isolation():
    from backend.api.part_autostaple_command import region_staple_ids
    from backend.api.routes_assign_sequences import _RegionInterval
    from backend.core.experimental_autostaple import length_report
    with hb.scratch_session():
        hb.create_bundle(HC6, 168, lattice=LatticeType.HONEYCOMB)
        hb.auto_scaffold()
        standard = hb.full_autostaple()
        every = hb.full_autostaple(experimental={'crossover_repeat_bp': 21})
        assert topology(every) == topology(standard)
        region = [{'helix_id': every.helices[0].id, 'lo_bp': 0, 'hi_bp': 30}]
        inside = region_staple_ids(every, [_RegionInterval(**r) for r in region])
        kept = {s.id: s for s in every.strands if s.strand_type == StrandType.STAPLE and s.id not in inside}
        regional = hb.full_autostaple(region=region, experimental={})
        now = {s.id: s for s in regional.strands}
        assert kept and all(now[sid] == s for sid, s in kept.items())
        assert coverage(regional) == coverage(standard)
        assert audit(regional)['status'] == 'verified'
        longer = hb.full_autostaple(experimental={'max_merged_length': 84})
        assert max(map(int, length_report(longer)['staple_lengths'])) > 56
        assert not occupancy_conflicts(longer)[0]
        # Returning to Standard recovers the original routing, without rewriting history.
        restored = hb.full_autostaple()
        assert topology(restored) == topology(standard)
        assert audit(restored)['status'] == 'verified'


def test_length_report_counts_loop_skips_without_mutating_routing():
    from backend.core.experimental_autostaple import length_report
    with hb.scratch_session():
        initial = hb.create_bundle(HC6, 42, lattice=LatticeType.HONEYCOMB)
        changed = hb.loop_skip(initial.helices[0].id, 10, 1)
        report = length_report(changed)
        assert report['staple_lengths'] == {42: 5, 43: 1}
        assert report['domain_lengths'] == {42: 6}
        assert audit(changed)['status'] == 'verified'


@pytest.mark.parametrize('cells', [HC6, HC18], ids=['6hb', '18hb'])
@pytest.mark.parametrize('experimental', [None, {'max_merged_length': 84}])
def test_hard_maximum_native_replay(cells, experimental, tmp_path):
    from backend.core.staple_length_limit import staple_lengths
    with hb.scratch_session():
        original = hb.create_bundle(cells, 168, lattice=LatticeType.HONEYCOMB)
        hb.auto_scaffold()
        uncapped = hb.full_autostaple(experimental=experimental)
        capped = hb.full_autostaple(experimental=experimental, max_staple_length=42)
        assert max(staple_lengths(uncapped)[0].values()) > 42
        assert max(staple_lengths(capped)[0].values()) <= 42
        assert coverage(capped) == coverage(original)
        assert sites(capped) == sites(uncapped)
        assert not occupancy_conflicts(capped)[0]
        assert capped.feature_log[-1].params['max_staple_length'] == 42
        assert all(len(s.sequence) <= 42 for s in capped.strands if s.strand_type == StrandType.STAPLE)
        saved = tmp_path / 'capped.nadoc'
        try:
            assert publish(capped, saved)['status'] == 'verified'
            reopened = Design.model_validate_json(saved.read_text())
            assert audit(reopened)['status'] == 'verified'
        finally:
            saved.unlink(missing_ok=True)


def test_maximum_counts_insertions_and_regional_exclusions():
    from backend.core.staple_length_limit import staple_lengths
    from backend.api.part_autostaple_command import region_staple_ids
    from backend.api.routes_assign_sequences import _RegionInterval
    with hb.scratch_session():
        original = hb.create_bundle(HC6, 168, lattice=LatticeType.HONEYCOMB)
        hb.auto_scaffold()
        hb.loop_skip(original.helices[0].id, 10, 1)
        hb.loop_skip(original.helices[1].id, 10, -1)
        initial = hb.full_autostaple(experimental={'max_merged_length': 84})
        region = [{'helix_id': initial.helices[0].id, 'lo_bp': 0, 'hi_bp': 30}]
        inside = region_staple_ids(initial, [_RegionInterval(**r) for r in region])
        outside = {s.id: s for s in initial.strands if s.strand_type == StrandType.STAPLE and s.id not in inside}
        capped = hb.full_autostaple(region=region, max_staple_length=42, experimental={})
        assert {s.id: s for s in capped.strands if s.id in outside} == outside
        assert max(n for sid, n in staple_lengths(capped)[0].items() if sid not in outside) <= 42
        assert audit(capped)['status'] == 'verified'


def test_maximum_validation_and_protected_failure_is_atomic():
    from backend.api.routes_assign_sequences import _FullAutostapleBody
    from backend.api.routes_assign_sequences import design_state
    for maximum in (0, 20, 301, 42.5, True):
        with pytest.raises(ValueError):
            _FullAutostapleBody(max_staple_length=maximum)
    with hb.scratch_session():
        hb.create_bundle(HC6, 168, lattice=LatticeType.HONEYCOMB)
        hb.auto_scaffold()
        routed = hb.full_autostaple()
        staple = next(s for s in routed.strands if s.strand_type == StrandType.STAPLE)
        before = hb.add_strand_extension(staple.id, end='five_prime', sequence='T' * 80)
        with pytest.raises(HTTPException, match='protected'):
            hb.full_autostaple(max_staple_length=42)
        assert design_state.get_or_404() == before
        assert audit(before)['status'] == 'verified'
        allowed = hb.full_autostaple(max_staple_length=300)
        assert allowed.extensions == before.extensions
        assert next(s for s in allowed.strands if s.id == staple.id).domains == staple.domains
        assert audit(allowed)['status'] == 'verified'
