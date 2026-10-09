"""CPU export worker owns no live document or renderer state."""
import gzip
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import routes_vr as vr, vr_scene_export as exporter
from backend.core.native_full_placement import NativePlacementError
from tests.conftest import make_minimal_design


def test_spawned_worker_matches_inline_snapshot_and_shuts_down():
    design = make_minimal_design(helix_length_bp=8)
    body = vr.VRLaunchRequest()
    expected = vr._snapshot(body, design_snapshot=design, representations={'full'})
    path = None
    try:
        exporter.warm()
        path = exporter.export_scene(body, design, {'full'})
        assert gzip.open(path, 'rt').read() == expected
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        exporter.shutdown()
    assert exporter._pool is None


def test_authority_failure_keeps_site_details_across_worker_boundary(monkeypatch):
    details = {'identity': {'helix_id': 'h', 'bp_index': 7}, 'actual': [1, 2, 3]}
    def fail(*args, **kwargs):
        raise NativePlacementError('invalid placement', details=details)
    monkeypatch.setattr(vr, '_snapshot', fail)
    result = exporter._render(vr.VRLaunchRequest(), make_minimal_design(), {'full'})
    monkeypatch.setattr(exporter, '_executor', lambda: SimpleNamespace(
        submit=lambda *args: SimpleNamespace(result=lambda: result)))
    with pytest.raises(NativePlacementError) as error:
        exporter.export_scene(None, None)
    assert str(error.value) == 'invalid placement'
    assert error.value.details == details


def test_http_error_is_transported_without_pickling_exception(monkeypatch):
    def fail(*args, **kwargs):
        raise HTTPException(409, detail='changed input')
    monkeypatch.setattr(vr, '_snapshot', fail)
    result = exporter._render(vr.VRLaunchRequest(), make_minimal_design(), {'full'})
    monkeypatch.setattr(exporter, '_executor', lambda: SimpleNamespace(
        submit=lambda *args: SimpleNamespace(result=lambda: result)))
    with pytest.raises(HTTPException) as error:
        exporter.export_scene(None, None)
    assert error.value.status_code == 409
    assert error.value.detail == 'changed input'
