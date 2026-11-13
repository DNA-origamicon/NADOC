"""Signed square-lattice correction, scoped composition and history compatibility."""
import pytest

from backend.api import headless_build as hb, state
from backend.api.part_loop_commands import plan, LEGACY_ALGORITHM, CURRENT_ALGORITHM
from backend.core.models import LatticeType, LoopSkip
from backend.core.loop_skip_calculator import forbidden_loop_skip_bps
from backend.core.square_twist_correction import compose_square_twist_marks
from scripts.agent_structure_guard import audit


@pytest.fixture
def source():
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([(r,c) for r in range(2) for c in range(3)],128,
                         lattice=LatticeType.SQUARE, name='__e2e__square twist')
        yield hb.full_autostaple(method='standard')


def totals(mods):
    return {hid: sum(m.delta for m in marks) for hid, marks in mods.items()}


def test_straight_baseline_unchanged(source):
    assert plan(source)[0] == plan(source, algorithm=LEGACY_ALGORITHM)[0]


@pytest.mark.parametrize('angle,sign', [(180,1),(-180,-1)])
def test_handedness_and_cluster_scope(source, angle, sign):
    ids = [h.id for h in source.helices[:3]]
    baseline = totals(plan(source)[0])
    twisted = hb.add_twist(0,127,total_degrees=angle,affected_helix_ids=ids)
    mods, _ = plan(twisted)
    final = totals(mods)
    for hid in baseline:
        if hid in ids:
            assert (final[hid] - baseline[hid]) * sign > 0
        else:
            assert final[hid] == baseline[hid]
    forb = forbidden_loop_skip_bps(twisted)
    assert all(m.bp_index not in forb[hid] for hid, marks in mods.items() for m in marks)


def test_signed_budget_preserved_even_when_marks_collide(source):
    d = hb.add_twist(0,127,total_degrees=180)
    hid = d.helices[0].id
    # Four baseline skips, three twist loops, including one exact collision.
    marks = [LoopSkip(bp_index=bp,delta=-1) for bp in (12,32,52,72)]
    marks += [LoopSkip(bp_index=bp,delta=1) for bp in (12,42,82)]
    out = compose_square_twist_marks(d,{hid: marks})[hid]
    assert len(out) == 1 and out[0].delta == -1


def test_adjacent_opposite_twists_do_not_cancel_across_windows(source):
    hb.add_twist(0,63,total_degrees=180)
    d = hb.add_twist(64,127,total_degrees=-180)
    mods,_ = plan(d)
    for marks in mods.values():
        assert sum(m.delta for m in marks if m.bp_index < 63) > 0
        assert sum(m.delta for m in marks if 64 <= m.bp_index < 127) < 0


def test_overlapping_opposite_twists_cancel(source):
    baseline = totals(plan(source)[0])
    hb.add_twist(0,127,total_degrees=180)
    d = hb.add_twist(0,127,total_degrees=-180)
    assert totals(plan(d)[0]) == baseline


def test_per_nm_matches_actual_plane_span(source):
    from backend.core.constants import BDNA_RISE_PER_BP
    hb.add_twist(0,127,degrees_per_nm=180/(127*BDNA_RISE_PER_BP))
    per_nm = totals(plan(state.get_or_404())[0])
    with hb.scratch_session(LatticeType.SQUARE):
        state.load_design(source)
        d = hb.add_twist(0,127,total_degrees=180)
        assert totals(plan(d)[0]) == per_nm


def test_public_command_is_versioned_repeatable_and_independently_replays(source):
    hb.add_twist(0,127,total_degrees=180)
    d = hb.apply_loop_skip_deformations()
    assert d.feature_log[-1].params['algorithm'] == CURRENT_ALGORITHM
    saved = type(d).model_validate_json(d.model_dump_json())
    assert audit(saved)['status'] == 'verified'
    before = [h.loop_skips for h in d.helices]
    again = hb.apply_loop_skip_deformations()
    assert [h.loop_skips for h in again.helices] == before


def test_unknown_algorithm_refused(source):
    with pytest.raises(ValueError,match='Unsupported'):
        plan(source,algorithm='future')


def test_same_sign_collision_keeps_both_contributions(source):
    d = hb.add_twist(0,127,total_degrees=-180)
    hid = d.helices[0].id
    out = compose_square_twist_marks(d,{hid:[LoopSkip(bp_index=32,delta=-1)]*2})[hid]
    assert len(out) == 2 and sum(m.delta for m in out) == -2
    assert len({m.bp_index for m in out}) == 2


def test_unplaceable_budget_fails_instead_of_dropping_marks(source):
    d = hb.add_twist(0,127,total_degrees=180)
    hid = d.helices[0].id
    with pytest.raises(ValueError,match='safe sites'):
        compose_square_twist_marks(d,{hid:[LoopSkip(bp_index=32,delta=1)]*128})


def test_exact_cancellation_can_apply_an_empty_mark_set(source, monkeypatch):
    from backend.core import loop_skip_calculator as calc
    hb.add_twist(0,127,total_degrees=180)
    baseline = calc.sq_lattice_periodic_skips(state.get_or_404())
    monkeypatch.setattr(calc, 'twist_loop_skips', lambda *args, **kwargs: {
        hid: [LoopSkip(bp_index=m.bp_index, delta=-m.delta) for m in marks]
        for hid, marks in baseline.items()
    })
    d = hb.apply_loop_skip_deformations()
    assert all(not h.loop_skips for h in d.helices)
    assert d.feature_log[-1].params['mark_count'] == 0
