"""Source-bound confirmation, atomic Move/unpair, and native history replay."""
from fastapi.testclient import TestClient
import pytest

from backend.api import state, part_proof_commands as commands
from backend.api.main import app
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from tests.test_part_member_motion_order import _source


def bodies(design, directions=("REVERSE",)):
    return [{"kind": "base", "helix_id": design.helices[0].id, "bp_index": bp,
             "direction": direction, "copy_k": 0, "pivot": [1, 2, 3],
             "rotation": [0, 0, 0, 1], "translation": [2, 0, 0], "compose": True}
            for direction in directions for bp in [0, 1]]


@pytest.mark.parametrize("directions,count", [(('REVERSE',), 1), (('FORWARD',), 1),
                                              (('REVERSE', 'FORWARD'), 0)])
def test_confirmation_is_readonly_and_apply_replays_with_one_undo(directions, count):
    source = _source()
    state.set_design(source.model_copy(deep=True))
    client = TestClient(app)
    request = {"transforms": bodies(source, directions)}
    before = state.get_design().model_dump_json()
    preview = client.post('/api/design/nucleotide-transforms/reclassification', json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()['overhang_count'] == count
    assert state.get_design().model_dump_json() == before
    response = client.put('/api/design/nucleotide-transforms', json={**request,
        'unpair_confirmation': preview.json()['confirmation_token']})
    assert response.status_code == 200, response.text
    result = state.get_design()
    assert len(result.overhangs) == count
    assert len(result.feature_log) == len(source.feature_log) + 1
    restored = Design.model_validate_json(result.model_dump_json())
    report = assess_part_history(restored, execute=commands.execute, dependencies=commands.dependencies)
    assert report['status'] == 'verified', report
    assert client.post('/api/design/undo').status_code == 200
    assert state.get_design().strands == source.strands
    assert state.get_design().overhangs == source.overhangs
    assert client.post('/api/design/redo').status_code == 200
    assert state.get_design().strands == result.strands


@pytest.mark.parametrize('change', ['inputs', 'source'])
def test_changed_confirmation_refuses_without_mutation(change):
    source = _source()
    state.set_design(source.model_copy(deep=True))
    client = TestClient(app)
    request = {'transforms': bodies(source)}
    preview = client.post('/api/design/nucleotide-transforms/reclassification', json=request)
    assert preview.status_code == 200, preview.text
    if change == 'inputs':
        request['transforms'][0]['translation'] = [3, 0, 0]
    else:
        state.set_design(source.copy_with(metadata=source.metadata.model_copy(update={'name': 'Changed'})))
    before = state.get_design().model_dump_json()
    response = client.put('/api/design/nucleotide-transforms', json={**request,
        'unpair_confirmation': preview.json()['confirmation_token']})
    assert response.status_code == 409, response.text
    assert state.get_design().model_dump_json() == before


def test_whole_staple_is_reported_as_free_ssdna_not_an_anchored_overhang():
    source = _source()
    state.set_design(source.model_copy(deep=True))
    client = TestClient(app)
    template = bodies(source)[0]
    request = {'transforms': [{**template, 'bp_index': bp} for bp in range(8)]}
    preview = client.post('/api/design/nucleotide-transforms/reclassification', json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()['overhang_count'] == 0
    assert preview.json()['free_strand_count'] == 1
    response = client.put('/api/design/nucleotide-transforms', json={**request,
        'unpair_confirmation': preview.json()['confirmation_token']})
    assert response.status_code == 200, response.text
    [endpoint] = state.get_design().overhangs
    assert endpoint.auxiliary_endpoint and endpoint.label == 'Free ssDNA'


def test_individual_loop_copy_refuses_before_confirmation_without_mutation():
    from backend.core.models import LoopSkip
    source = _source()
    source = source.copy_with(helices=[h.model_copy(update={
        'loop_skips': [LoopSkip(bp_index=0, delta=1)]}) for h in source.helices])
    state.set_design(source)
    before = state.get_design().model_dump_json()
    client = TestClient(app)
    request = {'transforms': [{**bodies(source)[0], 'copy_k': 1}]}
    preview = client.post('/api/design/nucleotide-transforms/reclassification', json=request)
    assert preview.status_code == 422, preview.text
    assert state.get_design().model_dump_json() == before


def test_independent_owner_does_not_guess_pairing_from_residue_pose_alone():
    from tests.test_part_member_motion_order import _owner
    source = _source()
    staple = next(s for s in source.strands if s.strand_type.value == 'staple')
    source = _owner(source, staple)
    state.set_design(source)
    before = source.model_dump_json()
    response = TestClient(app).post('/api/design/nucleotide-transforms/reclassification',
                                   json={'transforms': bodies(source)})
    assert response.status_code == 422, response.text
    assert 'independently posed' in response.json()['detail']
    assert state.get_design().model_dump_json() == before
