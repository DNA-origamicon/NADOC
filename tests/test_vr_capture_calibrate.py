import ctypes
import json
import sys
from types import SimpleNamespace

import pytest

from tools.vr_capture import calibrate


@pytest.fixture
def fake_runtime(monkeypatch):
    class Timing(ctypes.Structure):
        _fields_ = [('m_nSize', ctypes.c_uint32)]

    stopped = []
    runtime = SimpleNamespace(VRApplication_Background=3, Compositor_FrameTiming=Timing,
        init=lambda _: None, shutdown=lambda: stopped.append(True),
        VROverlay=lambda: SimpleNamespace(isDashboardVisible=lambda: False),
        VRCompositor=lambda: SimpleNamespace(getFrameTimings=lambda _: (0, [])))
    monkeypatch.setitem(sys.modules, 'openvr', runtime)
    clock = iter(range(0, 100_000_000_000, 500_000_000))
    monkeypatch.setattr(calibrate, 'time', SimpleNamespace(monotonic_ns=lambda: next(clock), sleep=lambda _: None))
    monkeypatch.setattr(calibrate, 'capture_resources', lambda: {'vm_counters': {}, 'pressure_total_us': {}})
    monkeypatch.setattr(calibrate, 'process_resources', lambda _: {})
    monkeypatch.setattr(calibrate, 'pressure', lambda *_: {})
    monkeypatch.setattr(calibrate, 'process_is_compositor', lambda _: True)
    monkeypatch.setattr(calibrate, 'locate_layer', lambda _: (None, {'pid': 123}))
    return stopped


def test_dead_compositor_stops_before_a_misleading_timing_window(tmp_path, monkeypatch, fake_runtime):
    monkeypatch.setattr(calibrate, 'process_is_compositor', lambda _: False)
    output = tmp_path/'result'
    with pytest.raises(RuntimeError, match='compositor exited'):
        calibrate.run(output, seconds=2, compositor_pid=123)
    report = json.loads((output/'calibration.json').read_text())
    assert report['status'] == 'failed'
    assert report['phases'] == []
    assert fake_runtime == [True]


@pytest.mark.parametrize('acknowledged', [False, True])
def test_failed_recording_never_continues_to_a_post_save_baseline(tmp_path, monkeypatch, fake_runtime, acknowledged):
    directory = tmp_path/'capture'
    directory.mkdir()

    def record(directory, emit, **_):
        if not acknowledged:
            emit({'phase': 'error', 'status': 'forced preparation failure'})
            return {'status': 'error'}
        begin = calibrate.time.monotonic_ns()
        start = {'start_ns': begin, 'end_ns': begin+2_000_000_000}
        (directory/'viewer-request-7.json').write_text(json.dumps({'acknowledged_start': start}))
        emit({'phase': 'recording', 'request': 7})
        return {'status': 'error', 'error': 'forced saving failure', 'acknowledged_start': start}

    monkeypatch.setattr(calibrate, 'record', record)
    output = tmp_path/'result'
    with pytest.raises(RuntimeError, match='forced'):
        calibrate.run(output, directory, seconds=2, repetitions=2)
    report = json.loads((output/'calibration.json').read_text())
    assert report['status'] == 'failed'
    assert [p['kind'] for p in report['phases']] == ['quiet', 'pixels']
    assert 'post_drain' not in report['phases'][-1]
    assert (output/'timing.jsonl').exists()
    assert fake_runtime == [True]
