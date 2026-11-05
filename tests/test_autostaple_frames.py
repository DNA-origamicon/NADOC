"""Recorded sweep continuations must not shadow their source lattice cells."""
import pytest

from backend.api import headless_build as hb, state
from backend.api.routes_sweep import create_sweep
from backend.core.models import Design, LatticeType
from backend.core.sweep import SweepRequest
from backend.core.crossover_positions import all_valid_crossover_sites
from scripts.agent_structure_guard import publish, audit


@pytest.fixture
def swept_part():
    with hb.scratch_session():
        d = hb.create_bundle([(0, 1), (1, 1), (0, 2), (1, 2)], 56,
                             lattice=LatticeType.HONEYCOMB)
        create_sweep(SweepRequest(cells=[(0, 1), (1, 1), (0, 2), (1, 2)],
            points_nm=[(0, 0, 0), (0, 4, 10), (0, 10, 20)],
            source_helix_id=d.helices[0].id, source_end='end', ligate_adjacent=True))
        yield state.get_or_404()


@pytest.mark.parametrize("filter_coverage", [True, False])
def test_candidates_keep_each_lattice_frame_and_are_order_independent(swept_part, filter_coverage):
    d = swept_part
    frames = {h.id: h.lattice_frame_id for h in d.helices}
    sites = all_valid_crossover_sites(d, filter_by_strand_coverage=filter_coverage)
    assert {frames[s['helix_a_id']] for s in sites} == set(frames.values())
    assert all(frames[s['helix_a_id']] == frames[s['helix_b_id']] for s in sites)
    # Ordering a read-only query must not select a different geometric section.
    from copy import copy
    reordered = copy(d)
    reordered.helices = list(reversed(d.helices))
    key = lambda s: (s['helix_a_id'], s['helix_b_id'], s['index'])
    assert sorted(map(key, sites)) == sorted(map(key, all_valid_crossover_sites(reordered, filter_by_strand_coverage=filter_coverage)))


def test_autostaple_routes_both_frames_and_replays_saved_process(swept_part, tmp_path):
    hb.auto_scaffold()
    routed = hb.full_autostaple()
    frames = {h.id: h.lattice_frame_id for h in routed.helices}
    staple_xos = [c for c in routed.crossovers if c.process_id == 'auto_crossover']
    assert {frames[c.half_a.helix_id] for c in staple_xos} == set(frames.values())
    assert all(frames[c.half_a.helix_id] == frames[c.half_b.helix_id] for c in staple_xos)
    saved = tmp_path / 'swept-autostaple.nadoc'
    try:
        assert publish(routed, saved)['status'] == 'verified'
        assert audit(Design.model_validate_json(saved.read_text()))['status'] == 'verified'
    finally:
        saved.unlink(missing_ok=True)


def test_legacy_autostaple_without_frame_parameter_replays_old_semantics(swept_part):
    from backend.api.part_auto_commands import build
    from experiments.recorded_review_process import structural_value

    hb.auto_scaffold()
    before = state.get_or_404()
    routed = hb.full_autostaple(frame_scoped_crossovers=False)
    params = dict(routed.feature_log[-1].params)
    params.pop('frame_scoped_crossovers')
    replayed = build('full-autostaple', before, params)
    assert structural_value(replayed) == structural_value(routed)
    # A new command repairs a previously routed part without rewriting its history.
    repaired = hb.full_autostaple()
    frames = {h.id: h.lattice_frame_id for h in repaired.helices}
    assert {frames[c.half_a.helix_id] for c in repaired.crossovers
            if c.process_id == 'auto_crossover'} == set(frames.values())
    assert audit(repaired)['status'] == 'verified'


def test_standalone_auto_crossovers_record_frame_semantics_and_replay(swept_part):
    routed = hb.auto_crossover()
    frames = {h.id: h.lattice_frame_id for h in routed.helices}
    assert {frames[c.half_a.helix_id] for c in routed.crossovers} == set(frames.values())
    assert routed.feature_log[-1].params['frame_scoped_crossovers'] is True
    assert audit(routed)['status'] == 'verified'
