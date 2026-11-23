"""Remote submission scripts cannot consume the local live-toggle API."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import routes_md


@pytest.mark.parametrize('target', ['alpine', 'runpod'])
def test_remote_live_toggle_refuses_without_writing_control(monkeypatch, target):
    monkeypatch.setattr(routes_md, '_load_job', lambda _: SimpleNamespace(execution_target=target))
    def forbidden(*args):
        raise AssertionError('remote toggle must not write a local override')
    monkeypatch.setattr(routes_md, 'set_early_stop', forbidden)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes_md.toggle_md_early_stop('remote', routes_md.EarlyStopRequest(enabled=True)))
    assert exc.value.status_code == 409
    assert 'set at submission' in exc.value.detail


def test_local_live_toggle_still_reaches_runner(monkeypatch):
    monkeypatch.setattr(routes_md, '_load_job', lambda _: SimpleNamespace(execution_target='local'))
    monkeypatch.setattr(routes_md, '_workspace', lambda: 'workspace')
    monkeypatch.setattr(routes_md, 'is_running', lambda _: True)
    calls = []
    def apply(*args):
        calls.append(args)
        return True
    monkeypatch.setattr(routes_md, 'set_early_stop', apply)
    result = asyncio.run(routes_md.toggle_md_early_stop('local', routes_md.EarlyStopRequest(enabled=True)))
    assert result['ok'] and result['running']
    assert calls == [('local', True, 'workspace')]
