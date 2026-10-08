"""Launching VR must not rebuild the test suite with unbounded compiler jobs."""
from types import SimpleNamespace
import os
from backend.api import routes_vr


def test_automatic_build_is_serial_and_viewer_only(tmp_path, monkeypatch):
    root = tmp_path / 'viewer'
    (root / 'src').mkdir(parents=True)
    (root / 'CMakeLists.txt').write_text('')
    (root / 'src' / 'main.cpp').write_text('')
    build = root / 'build'
    viewer = build / 'nadoc-vr-viewer'
    monkeypatch.setattr(routes_vr, '_VIEWER_DIR', root)
    monkeypatch.setattr(routes_vr, '_BUILD_DIR', build)
    monkeypatch.setattr(routes_vr, '_VIEWER', viewer)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if '--build' in command:
            assert command[-4:] == ['--target', 'nadoc-vr-viewer', '--parallel', '1']
            viewer.write_text('built')
        return SimpleNamespace(returncode=0, stderr='')

    monkeypatch.setattr(routes_vr.subprocess, 'run', run)
    routes_vr._ensure_viewer_built()
    assert len(calls) == 2
    routes_vr._ensure_viewer_built()
    assert len(calls) == 2  # A waiting caller reuses the completed build.
    # Sweep's runtime implementation is an included source fragment. Changing it
    # must rebuild the viewer just like changing main.cpp or a header.
    fragment = root / 'src' / 'sweep_runtime.inc'
    fragment.write_text('// revised gesture handling')
    newer = viewer.stat().st_mtime + 1
    os.utime(fragment, (newer, newer))
    routes_vr._ensure_viewer_built()
    assert len(calls) == 4
