"""Attached construction must not silently choose between separated strands."""
import pytest

from backend.core.models import Direction
from backend.core.sweep import SweepRequest, build_sweep, sweep_preview
from tests.test_part_member_motion_order import _source, _owner, _nucleotide, _pose
from tests.test_part_transform_preview import snapshot


def separated_source(direction='FORWARD', end='end', kind='owner', motion='rotation'):
    source = _source()
    hid = source.helices[0].id
    bp = 0 if end == 'start' else 7
    pose = _pose('z', 90 if motion == 'rotation' else 0, [2, -1, .5],
                 [1, 2, 3] if motion == 'translation' else [0, 0, 0])
    if kind == 'residue':
        return _nucleotide(source, dict(kind='base', helix_id=hid, bp_index=bp,
                                       direction=direction, copy_k=0), pose, 'separate')
    source = snapshot(source, 'nick', dict(helix_id=hid, bp_index=3,
                                          direction=direction), 'nick')
    strand = next(s for s in source.strands for d in s.domains
                  if d.helix_id == hid and d.direction == Direction(direction)
                  and min(d.start_bp, d.end_bp) <= bp <= max(d.start_bp, d.end_bp))
    source = _owner(source, strand)
    # Use a real recorded owner operation so replay sees the same separation.
    from tests.test_part_deformation_preview import _append
    from backend.core.models import ClusterOpLogEntry
    return _append(source, ClusterOpLogEntry(id='separate', cluster_id='probe-owner',
                                            proof_version=1, **pose))


def request(source, end='end', detached=False):
    return SweepRequest(cells=[(0, 0)], points_nm=[(0, 0, 0), (0, 0, -3 if end == 'start' else 3)],
                        source_helix_id=source.helices[0].id, source_end=end,
                        detach_source=detached, ligate_adjacent=False)


@pytest.mark.parametrize('direction', ['FORWARD', 'REVERSE'])
@pytest.mark.parametrize('end', ['start', 'end'])
@pytest.mark.parametrize('kind', ['owner', 'residue'])
@pytest.mark.parametrize('motion', ['translation', 'rotation'])
def test_separated_attachment_refused_without_mutation(direction, end, kind, motion):
    source = separated_source(direction, end, kind, motion)
    before = source.model_dump_json()
    for operation in (sweep_preview, build_sweep):
        with pytest.raises(ValueError, match='no longer share a duplex frame'):
            operation(source, request(source, end))
        assert source.model_dump_json() == before


@pytest.mark.parametrize('end', ['start', 'end'])
def test_detached_sweep_remains_available(end):
    source = separated_source(end=end)
    before = source.model_dump_json()
    result = build_sweep(source, request(source, end, detached=True))
    assert len(result.helices) > len(source.helices)
    assert source.model_dump_json() == before


def test_whole_duplex_motion_keeps_a_common_attachment_frame():
    source = _owner(_source())
    build_sweep(source, request(source))


def test_unoccupied_complementary_site_does_not_block_attachment():
    source = separated_source(kind='residue')
    source = source.copy_with(strands=[s for s in source.strands
                              if s.domains[0].direction != Direction.REVERSE])
    sweep_preview(source, request(source))


def test_direct_http_commit_cannot_bypass_attachment_refusal():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import state

    source = separated_source()
    state.set_design(source)
    before = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()
    client = TestClient(app)
    for path in ('/api/design/sweep/preview', '/api/design/sweep'):
        response = client.post(path, json=request(source).model_dump(mode='json'))
        assert response.status_code == 422, response.text
        assert 'no longer share a duplex frame' in response.json()['detail']
        assert (state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()) == before


def test_earlier_move_edit_reports_the_attached_sweep_as_failed():
    from backend.api import part_transform_preview_worker as worker
    from tests.test_part_deformation_preview import owned_capture

    source = separated_source(motion='identity')
    source = snapshot(source, 'sweep', request(source).model_dump(mode='json'), 'attached-sweep')
    before = source.model_dump_json()
    result = worker.evaluate_operation(owned_capture(source), {
        'action': 'apply', 'feature_id': 'separate', 'params': {'translation': [1, 2, 3]}})
    assert result['status'] == 'failed', result
    detail = result['issues'][0]['detail']
    assert detail['feature_id'] == 'attached-sweep', result
    assert 'no longer share a duplex frame' in detail['detail'], result
    assert source.model_dump_json() == before
