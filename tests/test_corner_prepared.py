"""A completed native preview is the exact source-bound commit, never a refit."""
import asyncio
import json
import orjson
from time import monotonic

import pytest
from fastapi import HTTPException

from backend.api import doc_context, headless_build as hb, state
from backend.api import corner_prepared as prepared
from backend.api.routes_corner import CreateCornerRequest, create_corner, preview_corner
from backend.core.models import LatticeType
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history


@pytest.mark.slow
def test_preview_commits_exact_candidate_once_without_rebuilding_and_preserves_replay(monkeypatch):
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([[0, 0], [0, 1]], 84, lattice=LatticeType.HONEYCOMB, separate_fresh_extrusions=False)
        source, revision = state.copy_for_persist()
        body = CreateCornerRequest(cluster_id=source.cluster_transforms[0].id, position_bp=42,
            angle_deg=90, direction_deg=15, expected_design_id=source.id, expected_revision=revision)
        response = preview_corner(body)
        async def collect():
            return [json.loads(row) async for row in response.body_iterator]
        events = asyncio.run(collect())
        ready = events[-1]
        assert ready['type'] == 'ready', ready
        body = body.model_copy(update={'preview_token': ready['preview_token']})
        before = state.get_or_404().model_dump()
        for changes in [{'angle_deg': 75}, {'position_bp': 43}, {'direction_deg': 30},
                        {'expected_revision': revision + 1}, {'expected_design_id': 'other'},
                        {'preview_token': 'x' * 32}]:
            with pytest.raises(HTTPException) as caught:
                create_corner(body.model_copy(update=changes))
            assert caught.value.status_code == 409
        with pytest.raises(HTTPException):
            prepared.commit(body, 'different-feature')
        token = doc_context._current_doc.set('different-document')
        try:
            with pytest.raises(HTTPException):
                create_corner(body)
        finally:
            doc_context._current_doc.reset(token)
        assert state.get_or_404().model_dump() == before
        def forbidden(*args, **kwargs):
            raise AssertionError('Apply repeated native Corner calculation')
        with monkeypatch.context() as patch:
            patch.setattr('backend.api.routes_corner.build', forbidden)
            patch.setattr('backend.api.crud._design_response_with_geometry', forbidden)
            patch.setattr('backend.api.corner_projection_worker.project_corner_in_worker', forbidden)
            started = monotonic()
            result = create_corner(body)
            elapsed = monotonic() - started
        assert elapsed < 2, elapsed
        assert result['corner']['reused_preview']
        for field in ('nucleotides', 'helix_axes', 'straight_positions_by_helix', 'straight_helix_axes'):
            assert result[field] == ready['candidate'][field]
        candidate = state.get_or_404()
        assert candidate.feature_log[-1].id == ready['feature_id']
        assert candidate.feature_log[-1].post_state_gz_b64
        assert result['revision'] == revision + 1
        from backend.api.crud import _design_response_with_geometry
        canonical = _design_response_with_geometry(candidate, state.validate_design(candidate), normalize_legacy=False)
        for field in ('nucleotides', 'helix_axes', 'straight_positions_by_helix', 'straight_helix_axes'):
            assert result[field] == orjson.loads(orjson.dumps(canonical[field], option=orjson.OPT_SERIALIZE_NUMPY))
        assert assess_part_history(candidate, execute=execute, dependencies=dependencies)['status'] == 'verified'
        with pytest.raises(HTTPException):
            create_corner(body)
        state.undo()
        assert state.get_or_404().model_dump() == source.model_dump()
        state.redo()
        assert state.get_or_404().model_dump() == candidate.model_dump()


@pytest.mark.parametrize('change', ['revision', 'session', 'policy', 'expired'])
def test_prepared_result_refuses_stale_ownership(change, monkeypatch):
    # No molecular authoring is needed to exercise the ownership boundary.
    with hb.scratch_session(LatticeType.HONEYCOMB):
        source, revision = state.copy_for_persist()
        body = CreateCornerRequest(cluster_id='c', position_bp=42, angle_deg=90, direction_deg=0,
            expected_design_id=source.id, expected_revision=revision)
        _, owner = prepared.capture(body)
        preview_token = prepared.retain(owner, body, None, source, {})
        if change == 'revision':
            state.set_design(source.model_copy(deep=True))
        elif change == 'session':
            with state._lock:
                monkeypatch.setattr(state._session(), 'identity', 'replacement-session')
        elif change == 'policy':
            from dataclasses import replace
            original = prepared.resolve(owner.doc)
            monkeypatch.setattr('backend.api.part_publication_policy.resolve', lambda doc: replace(original, generation=original.generation+1))
        else:
            monkeypatch.setattr(prepared, 'monotonic', lambda: owner.revision + 1e12)
        before = state.get_or_404().model_dump()
        with pytest.raises(HTTPException) as caught:
            create_corner(body.model_copy(update={'preview_token': preview_token}))
        assert caught.value.status_code == 409
        assert state.get_or_404().model_dump() == before
        with prepared._lock:
            prepared._entries.pop(preview_token, None)
