"""Bevel cuts strands without rerouting or moving retained duplex material."""
import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import crud, headless_build as hb, state
from backend.api.part_bevel_commands import BevelRequest, bevel_guide
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_bevel import CreateBevelRequest, create_bevel
from backend.api.routes_deformation import AddDeformationBody, add_deformation
from backend.core.models import Design, LatticeType
from backend.core.part_history_contract import assess_part_history
from backend.core.design_geometry import native_full_arrays_for_helix
from tests.conftest import SIX_HB_CELLS


def request(source, revision, **patch):
    return CreateBevelRequest(cluster_id=source.cluster_transforms[-1].id, position_bp=84,
        angle_deg=30, direction_deg=15, expected_design_id=source.id,
        expected_revision=revision, **patch)


def bases(design):
    result = {}
    for strand in design.strands:
        offset = 0
        for domain in strand.domains:
            step = 1 if domain.end_bp >= domain.start_bp else -1
            for bp in range(domain.start_bp, domain.end_bp + step, step):
                result[domain.helix_id, bp, domain.direction] = strand.sequence[offset] if strand.sequence else None
                offset += 1
    return result


@pytest.mark.parametrize('end,curved', [('start', False), ('end', False), ('start', True), ('end', True)])
def test_recorded_bevel_retains_sequence_geometry_and_replays(end, curved):
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 168, lattice=LatticeType.HONEYCOMB, separate_fresh_extrusions=False)
        hb.auto_scaffold(seamless=True)
        hb.assign_scaffold_sequence(custom_sequence='ACGT' * 512)
        hb.assign_staple_sequences()
        hb.add_cluster('Bevel source', [h.id for h in state.get_or_404().helices], log=True)
        if curved:
            add_deformation(AddDeformationBody(type='bend', plane_a_bp=7, plane_b_bp=140,
                cluster_ids=[state.get_or_404().cluster_transforms[-1].id],
                params={'kind': 'bend', 'curvature_deg_per_bp': .2, 'direction_deg': 30}))
        source, revision = state.copy_for_persist()
        body = request(source, revision, trim_end=end)
        guide = bevel_guide(source, body)
        create_bevel(body)
        result = state.get_or_404()
        old, new = bases(source), bases(result)
        assert 0 < len(new) < len(old)
        assert all(old[key] == value for key, value in new.items())
        assert result.helices == source.helices
        assert result.deformations == source.deformations
        for row in guide['cuts']:
            positions = [bp for hid, bp, _ in new if hid == row['helix_id']]
            assert positions
            assert max(positions) <= row['cut_bp'] + 1e-9 if end == 'end' else min(positions) >= row['cut_bp'] - 1e-9
        for a, b in zip(source.helices, result.helices):
            np.testing.assert_allclose(native_full_arrays_for_helix(a, source)['positions'],
                native_full_arrays_for_helix(b, result)['positions'], atol=1e-9, rtol=0)
        assert len(result.crossovers) < len(source.crossovers)
        assert sum(s.strand_type.value == 'scaffold' for s in result.strands) > 1
        assert not result.forced_ligations
        assert result.feature_log[:-1] == source.feature_log
        reopened = Design.model_validate_json(result.model_dump_json())
        assert reopened.feature_log[-1].op_kind == 'bevel'
        proof = assess_part_history(reopened, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        state.undo()
        assert state.get_or_404().strands == source.strands
        state.redo()
        assert state.get_or_404().strands == result.strands
        with pytest.raises(HTTPException) as caught:
            create_bevel(body)
        assert caught.value.status_code == 409
        crud.edit_feature(len(result.feature_log)-1, crud.EditFeatureBody(params={'angle_deg': 0}))
        edited = state.get_or_404()
        proof = assess_part_history(edited, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        assert edited.feature_log[-1].params['angle_deg'] == 0
        if not curved:
            expected = {key: value for key, value in old.items() if (key[1] <= 84 if end == 'end' else key[1] >= 84)}
            assert bases(edited) == expected
        crud.delete_feature(len(edited.feature_log)-1)
        assert state.get_or_404().strands == source.strands


def test_bevel_parameters_reject_parallel_plane_and_unknown_end():
    for patch in ({'angle_deg': 90}, {'trim_end': 'both'}):
        with pytest.raises(ValueError):
            BevelRequest.model_validate(dict(cluster_id='bundle', position_bp=42,
                angle_deg=0, direction_deg=0) | patch)


def test_bevel_guarded_save_reopen_and_independent_audit(tmp_path):
    from scripts.agent_structure_guard import publish, audit
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, 0], [0, 1]], 168, lattice=LatticeType.SQUARE, separate_fresh_extrusions=False)
        hb.add_cluster('Bevel source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        create_bevel(request(source, revision))
        path = tmp_path / '__e2e__bevel.nadoc'
        try:
            publish(state.get_or_404(), path)
            reopened = Design.model_validate_json(path.read_text())
            assert reopened.feature_log[-1].op_kind == 'bevel'
            assert reopened.feature_log[:-1] == source.feature_log
            audit(reopened)
        finally:
            path.unlink(missing_ok=True)


def test_preview_commit_is_bound_to_inputs_and_source(monkeypatch):
    import json
    from backend.api.routes_bevel import preview_bevel
    from backend.api.corner_preview_projection import project_corner_preview
    monkeypatch.setattr('backend.api.corner_projection_worker.project_corner_in_worker', project_corner_preview)
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, 0], [0, 1]], 168, lattice=LatticeType.SQUARE, separate_fresh_extrusions=False)
        hb.add_cluster('Bevel source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        body = request(source, revision)
        preview = preview_bevel(body, prepare_only=True)
        assert 'candidate' not in preview
        assert state.get_or_404().strands == source.strands
        token = preview['preview_token']
        # A late overlapping request must not evict the displayed result.
        preview_bevel(body.model_copy(update={'angle_deg': 20}))
        with pytest.raises(HTTPException) as caught:
            create_bevel(body.model_copy(update={'preview_token': token, 'trim_end': 'start'}))
        assert caught.value.status_code == 409
        response = json.loads(create_bevel(body.model_copy(update={'preview_token': token})).body)
        assert response['bevel']['reused_preview']
        with pytest.raises(HTTPException):
            create_bevel(body.model_copy(update={'preview_token': token}))
        assert state.get_or_404().feature_log[-1].op_kind == 'bevel'


def test_live_source_uses_axis_only_request_and_recorded_edit_prefix(monkeypatch):
    import json
    from backend.api.routes_bevel import bevel_source
    calls = []
    def project(design, *, include_straight):
        assert include_straight is False
        calls.append(design)
        return {'source_bases': len(bases(design))}
    monkeypatch.setattr('backend.api.corner_projection_worker.project_corner_in_worker', project)
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, 0], [0, 1]], 168, lattice=LatticeType.SQUARE, separate_fresh_extrusions=False)
        hb.add_cluster('Bevel source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        body = request(source, revision)
        response = json.loads(bevel_source(body, include_geometry=False).body)
        assert calls == [] and response['component'] is None
        assert len(response['paths']) == 2
        assert state.get_or_404().feature_log == source.feature_log
        create_bevel(body)
        cut, revision = state.copy_for_persist()
        assert cut.feature_log[-1].params['_proof_version'] == 2
        with monkeypatch.context() as patch:
            def forbidden(*args, **kwargs):
                raise AssertionError('A read-only preview encoded recovery snapshots')
            patch.setattr(state, 'encode_design_snapshot', forbidden)
            response = json.loads(bevel_source(request(cut, revision), feature_id=cut.feature_log[-1].id,
                                               include_geometry=False).body)
        assert response['component']['source_bases'] == len(bases(source))
        assert len(calls) == 1
        from backend.core.part_overlay_commands import command_input
        assert [(e.id, command_input(e)) for e in calls[0].feature_log] == [
            (e.id, command_input(e)) for e in source.feature_log]
        from backend.api.bevel_edit_source import replay_source
        corrupted = cut.model_copy(deep=True)
        corrupted.strands.pop()
        with pytest.raises(HTTPException) as caught:
            replay_source(corrupted, len(corrupted.feature_log)-1)
        assert caught.value.status_code == 409


def test_legacy_bevel_version_is_preserved_by_recording():
    from backend.api.feature_recording import record_feature
    from backend.api.part_bevel_commands import BevelCommand, build
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, 0], [0, 1]], 168, lattice=LatticeType.SQUARE, separate_fresh_extrusions=False)
        source, revision = state.copy_for_persist()
        inputs = {key: getattr(request(source, revision), key) for key in BevelRequest.model_fields}
        params = BevelCommand(**inputs, _proof_version=1, operation_id='legacy').model_dump(mode='json', by_alias=True)
        candidate, _, entry = record_feature(state._DesignSession(design=source), 'bevel', 'Legacy bevel', params,
                                             lambda d: build(d, params))
        assert entry.params['_proof_version'] == 1
        assert assess_part_history(candidate, execute=execute, dependencies=dependencies)['status'] == 'verified'


def test_material_frames_survive_trimming_but_invalidate_changed_pose(monkeypatch):
    from backend.api import bevel_live
    from backend.core import bevel_geometry_cache
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, 0], [0, 1]], 168, lattice=LatticeType.SQUARE, separate_fresh_extrusions=False)
        source, revision = state.copy_for_persist()
        owner = source.cluster_transforms[-1].id
        bevel_live.source_axes(source, owner)
        create_bevel(request(source, revision))
        cut = state.get_or_404().model_copy(deep=True)
        with monkeypatch.context() as patch:
            def forbidden(*args, **kwargs):
                raise AssertionError('Retained construction frames were recalculated')
            patch.setattr(bevel_live, '_material_frame', forbidden)
            cached = bevel_live.source_axes(cut, owner)
        bevel_geometry_cache.clear()
        assert bevel_live.source_axes(cut, owner) == cached
        moved = cut.model_copy(deep=True)
        moved.cluster_transforms[-1].translation[0] += 1
        assert bevel_live.source_axes(moved, owner) != cached
