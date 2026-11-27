import asyncio
import json
import pytest
from fastapi import HTTPException

from backend.api import headless_build as hb, state
from backend.api.routes_corner import CreateCornerRequest, preview_corner
from backend.core.models import LatticeType
from tests.conftest import SIX_HB_CELLS


@pytest.mark.slow
def test_stream_delivers_guide_progress_and_complete_native_candidate_without_mutation():
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 168, lattice=LatticeType.HONEYCOMB, separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        cluster = next(c for c in source.cluster_transforms if c.name == 'Corner source')
        response = preview_corner(CreateCornerRequest(cluster_id=cluster.id, position_bp=84,
            angle_deg=90, direction_deg=0, expected_design_id=source.id, expected_revision=revision))
        assert response.headers['content-encoding'] == 'identity'
        async def collect():
            return [json.loads(row) async for row in response.body_iterator]
        events = asyncio.run(collect())
        assert events[0]['type'] == 'guide'
        assert events[-1]['type'] == 'ready', events[-1]
        assert len(events[-1]['candidate']['seam_inserts']) == 12
        progress = [row['percent'] for row in events if row['type'] == 'progress']
        assert progress == sorted(progress) and progress[-1] == 100
        assert all(row['remaining_seconds'] is None for row in events
                   if row['type'] == 'progress' and row['percent'] <= 30)
        assert state.get_or_404().model_dump() == source.model_dump()
        assert state.copy_for_persist()[1] == revision
        body = CreateCornerRequest(cluster_id=cluster.id, position_bp=84,
            angle_deg=90, direction_deg=15, expected_design_id=source.id, expected_revision=revision)
        response = preview_corner(body)
        async def disconnect():
            assert json.loads(await anext(response.body_iterator))['type'] == 'guide'
            await response.body_iterator.aclose()
        asyncio.run(disconnect())
        # A disconnected stream must release its worker allowance, including
        # when cancellation happens while the bounded event queue is full.
        from backend.api.corner_preview_stream import _slots
        acquired = 0
        try:
            for _ in range(2):
                assert _slots.acquire(timeout=3)
                acquired += 1
        finally:
            for _ in range(acquired):
                _slots.release()
        assert state.get_or_404().model_dump() == source.model_dump()
        with pytest.raises(HTTPException) as caught:
            preview_corner(body.model_copy(update={'expected_revision': revision - 1}))
        assert caught.value.status_code == 409
