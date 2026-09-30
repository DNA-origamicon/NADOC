import numpy as np
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from backend.api.vr_ligation import Catalog, record, parse_event


def test_catalog_rotates_positions_and_tangents_with_reserved_zero_offsets():
    body = Catalog(version=4, ends=[dict(role=3, strand=2, identity='nuc%3As1',
        position=[1,2,3], tangent=[0,0,1], expanded_offset=[0,2,0])])
    lines = record(body, [[0,0,1],[0,1,0],[-1,0,0]]).splitlines()
    assert lines[0] == 'NADOC_LIGATION_1 4 ready 1'
    assert lines[1].split()[:3] == ['3', '2', 'nuc%3As1']
    assert list(map(float, lines[1].split()[3:])) == [3,2,-1,1,0,0,0,0,0]


def test_invalid_catalog_and_releases_are_rejected():
    with pytest.raises(ValidationError):
        Catalog(version=1, ends=[dict(role=4, strand=0, identity='a',position=[0,0,0],tangent=[0,0,1])])
    body = Catalog(version=1, ends=[dict(role=5, strand=0, identity='a',position=[float('nan'),0,0],tangent=[0,0,1])])
    with pytest.raises(HTTPException):
        record(body, np.eye(3))
    assert parse_event(dict(sequence=1, version=2, source=0, target=1)) == dict(sequence=1, version=2, source=0, target=1)
    for value in [None, {}, dict(sequence=True, version=1, source=0, target=1), dict(sequence=1, version=1, source=-1, target=2)]:
        assert parse_event(value) is None


def test_nick_bonds_rotate_and_wheel_actions_validate():
    body=Catalog(version=1,ends=[],bonds=[dict(a=[1,0,0],b=[2,0,0])])
    lines=record(body,[[0,-1,0],[1,0,0],[0,0,1]]).splitlines()
    assert lines[1]=='BONDS 1'
    assert list(map(float,lines[2].split()))[:6]==[0,1,0,0,2,0]
    for action in ('nick','undo','redo'):
        event=dict(sequence=3,version=2,source=0,target=0,action=action)
        assert parse_event(event)==event
    assert parse_event(dict(sequence=1,version=1,source=0,target=0,action='delete')) is None


@pytest.mark.parametrize('action', ['nick','undo','redo'])
def test_wheel_event_survives_the_full_native_event_envelope(tmp_path, action):
    import json
    from backend.api.routes_vr import _event_payload
    event=dict(sequence=1,version=2,source=3,target=0,action=action)
    path=tmp_path/'event.json'
    path.write_text(json.dumps(dict(sequence=5,level_sequence=1,selection_level='base',ligation=event)))
    payload=_event_payload({'event_path':str(path)})
    assert payload['sequence']==5
    assert payload['ligation']==event
