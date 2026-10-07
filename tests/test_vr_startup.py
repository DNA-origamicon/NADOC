"""Startup publication, cancellation and failure checks without a VR runtime."""
import pytest
from pathlib import Path
from types import SimpleNamespace

from backend.api import vr_startup, routes_vr


@pytest.fixture(autouse=True)
def private_design(monkeypatch, tmp_path):
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path / "placement-reports"))
    from backend.core.models import Design
    monkeypatch.setattr(routes_vr.design_state, 'get_or_404', lambda: Design())


def test_progress_is_atomic_private_and_single_line(tmp_path):
    path = tmp_path/'startup'
    vr_startup.publish(path, 'loading', 15, 'Building\natoms')
    assert path.read_text() == 'loading 15\nBuilding atoms\n'
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_suffix('.next').exists()


def test_scene_is_published_before_ready_and_timing(monkeypatch, tmp_path):
    scene, progress = tmp_path/'scene', tmp_path/'progress'
    current = {'pid': 123}
    monkeypatch.setattr(routes_vr, '_read_state', lambda: current)
    monkeypatch.setattr(routes_vr, '_write_state', lambda value: current.update(value))
    monkeypatch.setattr(routes_vr, '_snapshot', lambda body, line_writer, progress, design_snapshot, representations: (progress(50, 'Exporting'), line_writer('SCENE')))
    def write(*, producer):
        candidate = tmp_path/'candidate'
        lines = []
        producer(lines.append)
        candidate.write_text('\n'.join(lines))
        assert progress.read_text().startswith('loading 50')
        return candidate
    monkeypatch.setattr(routes_vr, '_write_scene_snapshot', write)
    vr_startup.prepare_scene(None, scene, progress, SimpleNamespace(pid=123, poll=lambda: None))
    assert scene.read_text() == 'SCENE'
    assert progress.read_text().startswith('ready 85')
    assert current['snapshot_ready_at'] >= current['snapshot_started_at']
    assert not (tmp_path/'candidate').exists()


def test_failure_is_visible_and_does_not_publish_scene(monkeypatch, tmp_path):
    def fail(**kwargs):
        raise ValueError('Invalid scene')
    monkeypatch.setattr(routes_vr, '_write_scene_snapshot', fail)
    scene, progress = tmp_path/'scene', tmp_path/'progress'
    vr_startup.prepare_scene(None, scene, progress, SimpleNamespace(pid=123, poll=lambda: None))
    assert progress.read_text() == 'error 0\nInvalid scene\n'
    assert not scene.exists()


def test_closed_viewer_discards_finished_export(monkeypatch, tmp_path):
    candidate, scene, progress = (tmp_path/name for name in ('candidate','scene','progress'))
    candidate.write_text('scene')
    progress.write_text('loading')
    monkeypatch.setattr(routes_vr, '_write_scene_snapshot', lambda **kw: candidate)
    vr_startup.prepare_scene(None, scene, progress, SimpleNamespace(pid=123, poll=lambda: 0))
    assert not any(p.exists() for p in (candidate, scene, progress))


def test_launch_starts_viewer_before_scheduling_export(monkeypatch, tmp_path):
    from starlette.requests import Request
    from backend.api import vr_dimensions, vr_view_volumes
    import tempfile

    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(routes_vr, '_LOG_PATH', tmp_path/'viewer.log')
    monkeypatch.setattr(routes_vr, '_start_steamvr', lambda: None)
    monkeypatch.setattr(routes_vr, '_ensure_viewer_built', lambda: None)
    monkeypatch.setattr(routes_vr, '_read_state', lambda: None)
    monkeypatch.setattr(routes_vr, '_write_state', lambda state: None)
    monkeypatch.setattr(routes_vr, '_status_payload', lambda: {'running': True})
    calls = []
    def popen(command, **kwargs):
        assert '--loading-status' in command
        assert Path(command[1]).exists()
        calls.append('viewer')
        return SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(routes_vr.subprocess, 'Popen', popen)
    monkeypatch.setattr('backend.api.vr_lifecycle.track', lambda *args: None)
    monkeypatch.setattr(routes_vr, '_snapshot', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Export must not block launch')))
    class DeferredThread:
        def __init__(self, *, target, args, daemon, name):
            self.name = name
            if name == "nadoc-vr-startup":
                assert args[1].representation == "full"
        def start(self):
            calls.append(self.name)
    monkeypatch.setattr(routes_vr.threading, 'Thread', DeferredThread)
    for module in (vr_dimensions, vr_view_volumes):
        monkeypatch.setattr(module, 'prepare', lambda *args: None)
        monkeypatch.setattr(module, 'start', lambda *args: None)
    request = Request({'type':'http','client':('127.0.0.1',1234),'headers':[]})
    assert routes_vr.launch_vr(routes_vr.VRLaunchRequest(representation="vdw"), request)['running']
    assert calls == ['viewer','nadoc-vr-startup','nadoc-vr-cleanup']
