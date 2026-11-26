import asyncio
import json

import pytest
from fastapi import HTTPException

from backend.api import headless_build as hb, state
from backend.api.corner_history import evaluate_corner_edit
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_corner import CreateCornerRequest, create_corner, edit_corner, preview_corner
from backend.core.models import LatticeType
from backend.core.part_history_contract import assess_part_history
from tests.conftest import SIX_HB_CELLS


@pytest.mark.slow
def test_corner_edit_previews_its_prefix_and_replays_later_corners_without_publishing(monkeypatch):
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 252, lattice=LatticeType.HONEYCOMB, separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        cluster = next(c for c in state.get_or_404().cluster_transforms if c.name == 'Corner source')
        for position, direction in [(84, 0), (168, 90)]:
            source, revision = state.copy_for_persist()
            create_corner(CreateCornerRequest(cluster_id=cluster.id, position_bp=position,
                angle_deg=90, direction_deg=direction, expected_design_id=source.id, expected_revision=revision))
        source, revision = state.copy_for_persist()
        original = source.model_dump()
        selected, later = source.feature_log[-2:]
        inputs = dict(cluster_id=cluster.id, position_bp=84, angle_deg=75, direction_deg=15)
        progress, guides = [], []
        packet, candidate = evaluate_corner_edit(source, inputs, selected.id,
            on_progress=progress.append, on_guide=guides.append)
        assert len(guides) == 1 and len(guides[0]['cuts']) == 6
        assert candidate.feature_log[-2].id == selected.id
        assert candidate.feature_log[-2].params['angle_deg'] == 75
        assert candidate.feature_log[-2].params['operation_id'] == selected.params['operation_id']
        assert candidate.feature_log[-1].id == later.id
        assert candidate.feature_log[-1].params == later.params
        assert len(candidate.helices) == 18 and len(candidate.forced_ligations) == 24
        assert packet['feature_id'] == selected.id
        assert len(packet['candidate']['seam_inserts']) == 24
        assert any(p['stage'] == 'Rebuilding corner seams' for p in progress)
        assert progress[0]['percent'] == 0 and progress[-1]['percent'] == 100
        assert all(p['percent'] < 100 for p in progress[:-1])
        assert [p['percent'] for p in progress] == sorted(p['percent'] for p in progress)
        assert any(p['remaining_seconds'] is not None and p['remaining_seconds'] > 0
                   for p in progress[:-1])
        proof = assess_part_history(candidate, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        assert source.model_dump() == original == state.get_or_404().model_dump()
        assert state.copy_for_persist()[1] == revision
        body = CreateCornerRequest(**inputs, expected_design_id=source.id, expected_revision=revision)
        response = preview_corner(body, feature_id=selected.id)
        async def collect():
            return [json.loads(chunk) async for chunk in response.body_iterator]
        events = asyncio.run(collect())
        assert events[-1]['type'] == 'ready', events[-1]
        assert events[-1]['feature_id'] == selected.id
        assert [e for e in events if e['type'] == 'guide']
        body = body.model_copy(update={'preview_token': events[-1]['preview_token']})
        def forbidden(*args, **kwargs):
            raise AssertionError('Apply must reuse the evaluated recipe and geometry')
        with monkeypatch.context() as patch:
            patch.setattr('backend.api.part_recipe_edit.prepare_change', forbidden)
            patch.setattr('backend.api.crud._design_response_with_geometry', forbidden)
            result = edit_corner(selected.id, body)
        assert result['corner']['reused_preview'] is True
        assert result['nucleotides'] == events[-1]['candidate']['nucleotides']
        assert result['helix_axes'] == events[-1]['candidate']['helix_axes']
        updated = state.get_or_404()
        assert updated.helices == candidate.helices
        assert updated.strands == candidate.strands
        assert updated.forced_ligations == candidate.forced_ligations
        assert updated.deformations == candidate.deformations
        state.undo()
        assert state.get_or_404().strands == source.strands
        state.redo()
        assert state.get_or_404().strands == candidate.strands
        before_failure = state.get_or_404().model_dump()
        with pytest.raises(HTTPException) as caught:
            edit_corner(selected.id, body)
        assert caught.value.status_code == 409
        assert state.get_or_404().model_dump() == before_failure
