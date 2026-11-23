import asyncio
import pytest
from fastapi import HTTPException
from backend.api import md_two_base_maps as api


def test_same_base_rejected_before_worker():
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.generate('job',api.TwoBaseRequest(bases=['a','a'],design_id='d'),None))
    assert error.value.status_code==422


def test_disconnect_cancels_own_request(monkeypatch,tmp_path):
    from backend.core import md_analysis_runner
    cancelled=[]
    monkeypatch.setattr(api,'inputs',lambda *a:(None,None,None,tmp_path,[]))
    async def run(*args,**kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(md_analysis_runner,'run_analysis',run)
    class Request:
        async def is_disconnected(self):
            await asyncio.sleep(.01)
            return True
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(api.generate('job',api.TwoBaseRequest(bases=['a','b'],design_id='d'),Request()))
    assert cancelled==[True]
    assert not list(tmp_path.rglob('*.json'))
    assert not list(tmp_path.rglob('*.tmp'))


def test_progress_request_id_cannot_escape_job_directory():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        api.TwoBaseRequest(bases=['a','b'],design_id='d',request_id='../other')
