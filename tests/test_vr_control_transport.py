import pytest
from fastapi import HTTPException
from backend.api import vr_control_transport as transport
from backend.api import routes_vr


@pytest.mark.parametrize('suffix',['.share','.simulations'])
@pytest.mark.parametrize('ipc',[False,True])
def test_exact_control_bytes_and_legacy_fallback(tmp_path,monkeypatch,suffix,ipc):
    state={'doc_id':'mine','event_path':str(tmp_path/'event')}
    monkeypatch.setattr(routes_vr,'_read_state',lambda:state)
    sent=[]
    def send(path,data,*,display):
        sent.append((path,data,display))
        return ipc
    monkeypatch.setattr(transport,'send_snapshot',send)
    transport.deliver_control('mine',suffix,'exact μ state\n')
    assert sent==[(str(tmp_path/('event'+suffix)),'exact μ state\n'.encode(),False)]
    path=tmp_path/('event'+suffix)
    if ipc:assert not path.exists()
    else:assert path.read_text()=='exact μ state\n'
    with pytest.raises(HTTPException) as error:transport.deliver_control('other',suffix,'bad')
    assert error.value.status_code==409
    assert len(sent)==1


def test_transport_failure_never_falls_back_to_disk(tmp_path,monkeypatch):
    monkeypatch.setattr(routes_vr,'_read_state',lambda:{'doc_id':'mine','event_path':str(tmp_path/'event')})
    def send(*args,**kwargs):raise TimeoutError('stalled receiver')
    monkeypatch.setattr(transport,'send_snapshot',send)
    with pytest.raises(HTTPException) as error:transport.deliver_control('mine','.share','state')
    assert error.value.status_code==503
    assert not list(tmp_path.iterdir())
