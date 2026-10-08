"""Sweep realization oracles: arc-length gradient, local signs, safe topology, history."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import headless_build as hb, state
from backend.api.main import app
from backend.api.doc_context import get_current_doc
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import Design, LatticeType, LoopSkip
from backend.core.sweep import build_sweep, SweepRequest
from backend.core.sweep_loop_skips import sweep_loop_skips, sweep_strain_vectors
from backend.core.loop_skip_calculator import forbidden_loop_skip_bps, _bundle_centroid_and_tangent, _helix_cross_section_offset

CELLS = [(0,1), (1,1), (1,2), (1,3), (0,3), (0,2)]


def arc_points(plane='XY', radius=40, angle=1.2):
    return [dict(XY=(radius*(1-np.cos(t)), 0, radius*np.sin(t)),
                 XZ=(radius*(1-np.cos(t)), radius*np.sin(t), 0),
                 YZ=(radius*np.sin(t), radius*(1-np.cos(t)), 0))[plane]
            for t in np.linspace(0, angle, 33)]


def bundle(points=None, plane='XY', lattice=LatticeType.HONEYCOMB):
    return build_sweep(Design(lattice_type=lattice), SweepRequest(cells=CELLS, plane=plane,
                       points_nm=points or arc_points(plane), ligate_adjacent=False))


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
def test_circular_sweep_matches_arc_length_gradient(plane):
    design = bundle(plane=plane)
    mods = sweep_loop_skips(design)
    centroid, tangent = _bundle_centroid_and_tangent(design.helices)
    right = np.array([0,1,0] if plane == 'YZ' else [1,0,0])
    forbidden = forbidden_loop_skip_bps(design)
    for h in design.helices:
        offset = float(_helix_cross_section_offset(h, centroid, tangent) @ right)
        net = sum(m.delta for m in mods.get(h.id, []))
        assert abs(net - round(-offset * 1.2 / RISE)) <= 1
        assert all(m.bp_index not in forbidden[h.id] for m in mods.get(h.id, []))
    assert sum(len(m) for m in mods.values()) > 10


def test_straight_sweep_has_no_bending_marks():
    assert sweep_loop_skips(bundle([(0,0,0), (0,0,60)])) == {}


def test_s_curve_preserves_both_local_signs_instead_of_cancelling():
    design = bundle([(0,0,0), (0,0,15), (12,0,35), (0,0,55), (0,0,75)])
    mods = sweep_loop_skips(design)
    centroid, tangent = _bundle_centroid_and_tangent(design.helices)
    bps, strain = sweep_strain_vectors(design.deformations[0], tangent)
    for h in design.helices:
        marks = mods.get(h.id, [])
        offset = _helix_cross_section_offset(h, centroid, tangent)
        if abs(offset[0]) < 1e-8:
            continue
        assert {m.delta for m in marks} == {-1, 1}
        demand = strain @ offset
        assert all(np.sign(demand[m.bp_index - bps[0]]) == m.delta for m in marks)


def test_rigid_placement_does_not_change_realization():
    design = bundle([(0,0,0), (0,0,20), (10,8,40), (20,-8,65)])
    moved = design.copy_with(cluster_transforms=[c.model_copy(update={
        'translation': [18,29,-10], 'rotation': [0,0,np.sin(.4),np.cos(.4)]}) for c in design.cluster_transforms])
    assert sweep_loop_skips(moved) == sweep_loop_skips(design)


@pytest.mark.parametrize('end', ['start', 'end'])
def test_continuation_uses_global_bp_and_leaves_source_unmodified(end):
    source = bundle([(0,0,0), (0,0,30)])
    points = arc_points()
    if end == 'start':
        points = [(x,y,-z) for x,y,z in points]
    design = build_sweep(source, SweepRequest(cells=CELLS, points_nm=points,
                         source_helix_id=source.helices[0].id, source_end=end))
    mods = sweep_loop_skips(design)
    new = design.helices[len(source.helices):]
    assert mods and set(mods).issubset({h.id for h in new})
    for h in new:
        assert all(h.bp_start <= m.bp_index < h.bp_start + h.length_bp for m in mods.get(h.id, []))


def test_duplex_gaps_reference_helices_and_reserved_marks_are_excluded():
    design = bundle()
    hid = design.helices[0].id
    strands = [s.model_copy(update={'domains': [d.model_copy(update={'start_bp': max(55,d.start_bp), 'end_bp': max(55,d.end_bp)}) for d in s.domains]})
               if any(d.helix_id == hid for d in s.domains) else s for s in design.strands]
    design = design.copy_with(strands=strands)
    reserve = {h.id: [LoopSkip(bp_index=bp, delta=-1) for bp in range(10, h.length_bp-10, 8)] for h in design.helices}
    ignored = design.helices[-1].id
    mods = sweep_loop_skips(design, existing=reserve, ignored_helix_ids={ignored})
    assert ignored not in mods
    assert all(m.bp_index >= 55 for m in mods.get(hid, []))
    for h, marks in mods.items():
        assert not {m.bp_index for m in marks} & {m.bp_index for m in reserve[h]}


def test_unrealizable_sweep_fails_without_silent_loss_of_marks():
    with pytest.raises(ValueError, match='density'):
        sweep_loop_skips(bundle(arc_points(radius=3)))
    design = bundle()
    reserved = {h.id: [LoopSkip(bp_index=bp, delta=-1) for bp in range(h.length_bp)] for h in design.helices}
    with pytest.raises(ValueError, match='safe sites'):
        sweep_loop_skips(design, existing=reserved)


def routed_sweep(lattice=LatticeType.HONEYCOMB):
    hb.sweep(CELLS, arc_points(), ligate_adjacent=False)
    hb.auto_scaffold(seamless=False)
    hb.auto_crossover()
    hb.auto_break()
    return state.get_or_404()


@pytest.mark.parametrize('lattice', list(LatticeType))
def test_tool_api_recomputes_atomically_and_supports_history(lattice):
    with hb.scratch_session(lattice):
        before = routed_sweep(lattice)
        # Seed stale marks: recompute must replace, not merge them back in.
        state.set_design(before.copy_with(helices=[h.model_copy(update={'loop_skips': [LoopSkip(bp_index=h.bp_start, delta=1)]}) for h in before.helices]))
        old = state.get_or_404()
        client = TestClient(app, headers={'X-NADOC-Doc': get_current_doc(), 'X-NADOC-Skip-Geometry': '1'})
        response = client.post('/api/design/loop-skip/apply-deformations')
        assert response.status_code == 200, response.text
        after = state.get_or_404()
        marks = {h.id: h.loop_skips for h in after.helices}
        assert any(marks.values())
        forbidden = forbidden_loop_skip_bps(after)
        assert not [(h, m.bp_index) for h, ms in marks.items() for m in ms if m.bp_index in forbidden[h]]
        assert after.feature_log[-1].op_kind == 'apply-loop-skips'
        assert client.post('/api/design/undo').status_code == 200
        assert [h.loop_skips for h in state.get_or_404().helices] == [h.loop_skips for h in old.helices]
        assert client.post('/api/design/redo').status_code == 200
        assert {h.id: h.loop_skips for h in state.get_or_404().helices} == marks
        again = hb.apply_loop_skip_deformations()
        assert {h.id: h.loop_skips for h in again.helices} == marks
        assert Design.model_validate_json(again.model_dump_json()).helices == again.helices
        index = len(again.feature_log) - 1
        assert client.post(f'/api/design/features/{index}/revert').status_code == 200
        assert {h.id: h.loop_skips for h in state.get_or_404().helices} == marks


def test_tool_rejects_unrealizable_sweep_atomically(monkeypatch):
    import backend.core.sweep_loop_skips as module
    with hb.scratch_session():
        routed_sweep()
        before = state.get_or_404().model_dump_json()
        depth = state.undo_depth()
        def fail(*args, **kwargs):
            raise ValueError('Sweep requires more safe sites')
        monkeypatch.setattr(module, 'sweep_loop_skips', fail)
        client = TestClient(app, headers={'X-NADOC-Doc': get_current_doc(), 'X-NADOC-Skip-Geometry': '1'})
        response = client.post('/api/design/loop-skip/apply-deformations')
        assert response.status_code == 422
        assert state.get_or_404().model_dump_json() == before
        assert state.undo_depth() == depth


def test_tool_rejects_stale_computation(monkeypatch):
    import backend.core.sweep_loop_skips as module
    original = module.sweep_loop_skips
    with hb.scratch_session():
        routed_sweep()
        before_marks = [h.loop_skips for h in state.get_or_404().helices]
        def concurrent_change(*args, **kwargs):
            result = original(*args, **kwargs)
            state.set_design(state.get_or_404().copy_with(name='Changed during calculation'))
            return result
        monkeypatch.setattr(module, 'sweep_loop_skips', concurrent_change)
        client = TestClient(app, headers={'X-NADOC-Doc': get_current_doc(), 'X-NADOC-Skip-Geometry': '1'})
        response = client.post('/api/design/loop-skip/apply-deformations')
        assert response.status_code == 409
        assert state.get_or_404().name == 'Changed during calculation'
        assert [h.loop_skips for h in state.get_or_404().helices] == before_marks


@pytest.mark.parametrize('lattice', list(LatticeType))
def test_creation_generates_safe_marks_and_menu_is_idempotent_without_crossovers(lattice):
    with hb.scratch_session(lattice):
        hb.sweep(CELLS, arc_points(), ligate_adjacent=False)
        created = state.get_or_404()
        marks = {h.id: h.loop_skips for h in created.helices}
        assert any(marks.values())
        assert created.deformations[-1].params.auto_loop_skips
        for _ in range(2):
            after = hb.apply_loop_skip_deformations()
            assert {h.id: h.loop_skips for h in after.helices} == marks
        forbidden = forbidden_loop_skip_bps(created)
        for h in created.helices:
            assert not {m.bp_index for m in h.loop_skips} & forbidden.get(h.id, set())


@pytest.mark.parametrize('end', ['start','end'])
def test_automatic_corrections_preserve_existing_source_marks(end):
    source = bundle([(0,0,0),(0,0,30)], lattice=LatticeType.SQUARE)
    source = source.copy_with(helices=[h.model_copy(update={'loop_skips':[LoopSkip(bp_index=12,delta=1)]}) for h in source.helices])
    points = arc_points()
    if end == 'start':
        points = [(x,y,-z) for x,y,z in points]
    result = build_sweep(source, SweepRequest(cells=CELLS,points_nm=points,source_helix_id=source.helices[0].id,source_end=end))
    assert [h.loop_skips for h in result.helices[:len(source.helices)]] == [h.loop_skips for h in source.helices]
    assert any(h.loop_skips for h in result.helices[len(source.helices):])


def test_sharp_sweep_creates_safe_partial_corrections_and_durable_warning_regions():
    design = bundle(arc_points(radius=5), lattice=LatticeType.SQUARE)
    op = design.deformations[-1]
    assert op.params.warning_bps and op.params.loop_skip_warnings
    assert any(h.loop_skips for h in design.helices)
    forbidden = forbidden_loop_skip_bps(design)
    for h in design.helices:
        assert not {m.bp_index for m in h.loop_skips} & forbidden.get(h.id, set())
        assert len({m.bp_index for m in h.loop_skips}) == len(h.loop_skips)
        cells = {}
        for mark in h.loop_skips:
            cell=(mark.bp_index-op.plane_a_bp)//7
            cells[cell]=cells.get(cell,0)+abs(mark.delta)
        assert all(n<=3 for n in cells.values())
    restored=Design.model_validate_json(design.model_dump_json())
    assert restored.deformations[-1].params.warning_bps==op.params.warning_bps


def test_saved_warning_export_anchors_to_actual_dna_positions():
    from tests.test_vr_routes import _serialize_fixture_scene
    design=bundle(arc_points(radius=5), lattice=LatticeType.SQUARE)
    op=design.deformations[-1]
    assert op.params.warning_bps
    bp=op.params.warning_bps[0]
    records=[dict(helix_id=design.helices[0].id,bp_index=bp,strand_id=design.strands[0].id,backbone_position=[2,4,6])]
    from types import SimpleNamespace
    scene=_serialize_fixture_scene(design, records, [], representations=["full"], atomistic_model=SimpleNamespace(atoms=[],bonds=[]))
    assert '# SWEEP_WARNING 2 4 6' in scene
