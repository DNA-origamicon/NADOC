"""Displayed history must equal construction prefixes, not merely render something."""
import pytest

from backend.api import crud, part_proof_commands as commands, state
from backend.api.routes_feature_log import GeometryBatchBody, geometry_batch
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.part_overlay_commands import command_input
from backend.core.part_history_proof import root_design
from tools.member_motion_native_example import build


@pytest.fixture(scope='module')
def construction():
    tip = Design.from_json(build().to_json())
    prefix = root_design(tip.recipe_root)
    stages = {-2: prefix}
    for index, entry in enumerate(tip.feature_log):
        kind, params = command_input(entry)
        prefix = commands.execute(kind, prefix, params)
        stages[index] = prefix
    stages[-1] = prefix
    return tip, stages


@pytest.mark.parametrize('optimized', [False, True])
def test_scrub_back_forward_and_reset_match_independent_prefixes(construction, optimized):
    tip, stages = construction
    live = tip
    # Include a repeated tip/reset/initial visit: seeking itself replaces live state.
    for position in [0, 10, 2, 6, 7, -2, -1, 5, 1, 9, 3, 8, 4, 0, -1]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        expected = stages[position]
        assert live.nucleotide_transforms == expected.nucleotide_transforms
        assert _geometry_for_design(live) == _geometry_for_design(expected)
        assert build_atomistic_model(live, fast_bridges=True) == build_atomistic_model(expected, fast_bridges=True)


def test_animation_batch_uses_historical_base_poses_without_mutating_live_state(construction):
    tip, stages = construction
    state.load_design(tip)
    before = state.get_or_404().model_dump_json()
    try:
        samples = geometry_batch(GeometryBatchBody(positions=list(range(len(tip.feature_log)))))
        for position in range(len(tip.feature_log)):
            historical = Design.model_validate(samples[str(position)]['display_design'])
            assert historical.nucleotide_transforms == stages[position].nucleotide_transforms
            assert _geometry_for_design(historical) == _geometry_for_design(stages[position])
        assert state.get_or_404().model_dump_json() == before
    finally:
        state.close_session()


def test_make_cluster_does_not_move_geometry_and_next_feature_moves_it(construction):
    tip, stages = construction
    for index in (3, 8):
        assert tip.feature_log[index].feature_type == 'cluster_create'
        assert command_input(tip.feature_log[index + 1])[0] in {'cluster_op', 'placement-poses'}
        assert _geometry_for_design(stages[index]) == _geometry_for_design(stages[index - 1])
        assert build_atomistic_model(stages[index], fast_bridges=True) == build_atomistic_model(stages[index - 1], fast_bridges=True)
        assert _geometry_for_design(stages[index + 1]) != _geometry_for_design(stages[index])
    assert [k.feature_log_index for k in tip.animations[0].keyframes] == list(range(11))


def test_first_separation_names_overhang_and_cluster_move_extends_it(construction):
    from backend.core.deformation import deformed_helix_axes
    _, stages = construction
    first, moved = stages[2], stages[4]
    assert len(first.overhangs) == len(moved.overhangs) == 1
    assert first.overhangs[0].label == moved.overhangs[0].label == 'OH1'
    assert first.overhangs[0].id == moved.overhangs[0].id
    assert first.overhangs[0].sub_domains[0].length_bp == 1
    assert moved.overhangs[0].sub_domains[0].length_bp == 4
    hid = moved.helices[0].id
    axis = next(a for a in deformed_helix_axes(moved) if a['helix_id'] == hid)
    assert [(s['bp_lo'], s['bp_hi']) for s in axis['segments']] == [(0, 2), (4, 7)]
    assert axis['segments'][0]['start'][:2] != axis['segments'][1]['start'][:2]
    assert not stages[1].overhangs


def test_regular_cluster_move_records_overhang_growth_and_undo(construction):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.core.part_history_contract import assess_part_history
    from tests.test_part_member_motion_order import M
    tip, _ = construction
    source = crud._seek_feature_log(tip, 3).copy_with(
        feature_log=tip.feature_log[:4], feature_log_cursor=-1)
    state.load_design(source)
    try:
        with TestClient(app) as client:
            response = client.patch('/api/design/cluster/first-group-move', json={**M, 'commit': True})
            assert response.status_code == 200, response.text
            result = state.get_or_404()
            assert len(result.feature_log) == 5
            assert result.feature_log[-1].op_kind == 'placement-poses'
            assert result.overhangs[0].id == source.overhangs[0].id
            assert result.overhangs[0].label == 'OH1'
            assert result.overhangs[0].sub_domains[0].length_bp == 4
            from backend.core.part_overlay_commands import build as overlay
            posed = overlay('cluster_op', source, {'cluster_id': 'first-group-move', **M})
            def atom_positions(design):
                return {(a.strand_id, a.bp_index, a.direction, a.name, a.copy_k, a.extra_base_k): (a.x, a.y, a.z)
                        for a in build_atomistic_model(design, fast_bridges=True).atoms}
            before_atoms, after_atoms = atom_positions(posed), atom_positions(result)
            assert before_atoms.keys() == after_atoms.keys()
            for key in before_atoms:
                assert after_atoms[key] == pytest.approx(before_atoms[key], abs=1e-12)
            restored = Design.from_json(result.to_json())
            report = assess_part_history(restored, execute=commands.execute, dependencies=commands.dependencies)
            assert report['status'] == 'verified', report
            assert client.post('/api/design/undo').status_code == 200
            assert state.get_or_404().overhangs == source.overhangs
            assert client.post('/api/design/redo').status_code == 200
            assert state.get_or_404().overhangs == result.overhangs
    finally:
        state.close_session()


def test_cluster_move_with_overhang_growth_keeps_native_history_editor(construction):
    from backend.api import part_transform_preview as preview
    from backend.api.part_transform_preview_dto import prepare_display
    from tests.test_part_transform_frontend_contract import assert_frontend
    from tests.test_transform_unpair_history import owned_capture
    tip, _ = construction
    prepared = preview.prepare_from_capture(owned_capture(tip), tip.feature_log[4].id)
    evaluated = preview.evaluate(prepared, {})
    packet = prepare_display(prepared.copy_prefix(), evaluated)
    assert evaluated.design.overhangs[0].label == 'OH1'
    assert evaluated.design.overhangs[0].sub_domains[0].length_bp == 4
    assert_frontend(packet)


def test_unpairing_move_wins_over_earlier_cluster_pose_rows(construction):
    from backend.api.part_group_recording import prepare_group_update
    from tests.test_part_member_motion_order import M
    tip, _ = construction
    source = crud._seek_feature_log(tip, 3).copy_with(
        feature_log=tip.feature_log[:4], feature_log_cursor=-1)
    renamed, _ = prepare_group_update(source, 'first-group-move', {'name': 'Moved scaffold'})
    moved, _ = prepare_group_update(renamed, 'first-group-move', M)
    expected = _geometry_for_design(moved)
    live = moved
    for index in [3, 5, 4, -1]:
        live = crud._seek_feature_log(live, index)
        if index in (5, -1):
            assert _geometry_for_design(live) == expected


def test_common_cluster_pose_does_not_block_residue_unpairing(construction):
    from backend.core.models import ClusterRigidTransform, NucleotideTransform, Direction
    from backend.core.unpair_reclassification import separated_staple_keys
    _, stages = construction
    source = stages[1]
    hid = source.helices[0].id
    source = source.copy_with(cluster_transforms=[ClusterRigidTransform(
        id='common', helix_ids=[hid], translation=[5, 0, 0])])
    posed = source.copy_with(nucleotide_transforms=[NucleotideTransform(
        kind='base', helix_id=hid, bp_index=0, direction=Direction.FORWARD, translation=[2, 0, 0])])
    assert separated_staple_keys(source, posed, [(hid, 0, 'FORWARD', 0)]) == [(hid, 0, 'REVERSE', 0)]
