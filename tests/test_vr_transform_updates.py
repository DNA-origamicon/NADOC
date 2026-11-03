"""Exact display-transform transport, including hostile/truncated packets."""
import struct
import numpy as np
import pytest
from fastapi import HTTPException
from backend.api.vr_view_tools import validate_and_rotate


def packet(columns=3, values=None):
    values = values if values is not None else [1, 2, 3] * (columns//3)
    return (b'NADOCVT1' + struct.pack('<11I', 7, 12, 2048, 0, 0, 0, 0, 0, 1, 0, 10)
            + struct.pack('<2I', 1, columns) + np.array(values, dtype='<f4').tobytes())


@pytest.mark.parametrize('columns', [3, 12])
def test_absolute_transforms_rotate_exactly_like_full_instance_columns(columns):
    rotation = np.array([[.6, 0, .8], [0, 1, 0], [-.8, 0, .6]])
    values = np.arange(columns, dtype='<f4') + .125
    out = validate_and_rotate(packet(columns, values), rotation)
    expected = (values.reshape(1, -1, 3) @ rotation.T).astype('<f4')
    assert out[:60] == packet(columns, values)[:60]
    assert out[60:] == expected.tobytes()
    matrix = np.eye(4, dtype='<f4').T.copy()
    matrix[(3 if columns==3 else 0):, :3] = values.reshape(-1,3)
    instance = np.r_[matrix.reshape(-1), [1,1,1,1]].astype('<f4')
    vertices = np.zeros((3,12),dtype='<f4')
    full = (b'NADOCVT1'+struct.pack('<10I',6,12,2048,0,0,0,0,0,1,0)
            +struct.pack('<2I',3,1)+vertices.tobytes()+instance.tobytes())
    rotated = np.frombuffer(validate_and_rotate(full,rotation),dtype='<f4',offset=56+vertices.nbytes,count=16).reshape(4,4)
    assert out[60:] == rotated[(3 if columns==3 else 0):,:3].tobytes()


@pytest.mark.parametrize('change', [
    lambda p: p[:-1], lambda p: p+b'x',
    lambda p: p[:48]+struct.pack('<I', 0)+p[52:],
    lambda p: p[:48]+struct.pack('<I', 12)+p[52:],
    lambda p: p[:56]+struct.pack('<I', 4)+p[60:],
    lambda p: p[:52]+struct.pack('<I', 1000001)+p[56:],
    lambda p: p[:60]+struct.pack('<f', float('nan'))+p[64:],
])
def test_malformed_update_is_rejected(change):
    with pytest.raises(HTTPException): validate_and_rotate(change(packet()), np.eye(3))


@pytest.mark.parametrize('available,enabled', [(False, True), (True, True), (True, False)])
def test_transform_delivery_requires_ipc_and_reports_negotiation(tmp_path, monkeypatch, available, enabled):
    import asyncio
    from types import SimpleNamespace
    from backend.api import routes_vr, doc_context, vr_view_transport
    from backend.api.vr_view_tools import publish
    state = {'doc_id':'transform-test', 'event_path':str(tmp_path/'event'), 'view_rotation':np.eye(3).tolist()}
    monkeypatch.setattr(routes_vr, '_require_local', lambda _: None)
    monkeypatch.setattr(routes_vr, '_read_state', lambda: state)
    monkeypatch.setattr(doc_context, 'get_current_doc', lambda: 'transform-test')
    monkeypatch.setenv('NADOC_VR_TRANSFORM_UPDATES', '1' if enabled else '0')
    def send(path, data, *, capabilities):
        capabilities['transform_updates'] = True
        return available
    monkeypatch.setattr(vr_view_transport, 'send_snapshot', send)
    async def stream():
        yield b'NADOCVT1' + struct.pack('<11I', 7, 2, 2048, 0, 0, 0, 0, 0, 0, 0, 1)
    if available:
        assert asyncio.run(publish(SimpleNamespace(stream=stream)))['transform_updates'] is enabled
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(publish(SimpleNamespace(stream=stream)))
        assert error.value.status_code == 409
    assert not (tmp_path/'event.viewtools').exists()
