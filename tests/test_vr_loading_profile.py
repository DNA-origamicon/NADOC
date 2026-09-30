"""Regression: green draw-only timers must not hide loading frame freezes."""
import json

from tools.vr_workflows.loading_profile import acceptance_failures, summarize
from tools.vr_workflows.tour_catalog import arguments, catalog


def test_whole_frame_stalls_outside_render_timer_fail(tmp_path):
    (tmp_path/'native').mkdir()
    (tmp_path/'native/results.json').write_text(json.dumps([
        dict(target='surface', preset='steady_fast', samples=[dict(wall_time_ms=100), dict(wall_time_ms=1000)])
    ]))
    lines = ['VR_METRIC phase=frame_timing runtime_period_ms=11.111111 scene_p95_within_budget=true']
    lines += [f'VR_LOAD_TRACE epoch_ms={110+i*12} stage=frame cpu_wall_ms=0.3 frame_gap_ms=11.2 requested=surface percent=45' for i in range(40)]
    lines += ['VR_LOAD_TRACE epoch_ms=700 stage=visualization cpu_wall_ms=225 frame_gap_ms=225 requested=surface percent=99',
              'VR_LOAD_TRACE epoch_ms=702 stage=frame cpu_wall_ms=0.3 frame_gap_ms=226 requested=surface percent=99',
              'VR_LOAD_TRACE epoch_ms=2000 stage=frame cpu_wall_ms=999 frame_gap_ms=999 requested=surface percent=99']
    lines += ['VR_METRIC runtime_period_ms=22.222222']
    (tmp_path/'native-viewer.log').write_text('\n'.join(lines))
    report = summarize(tmp_path)
    result = report['reports'][0]
    assert abs(report['runtime_hz']-90) < .001
    assert result['bands']['whole_load']['max_ms'] == 226
    assert result['cpu_phase_max_ms']['VR_LOAD_TRACE:visualization'] == 225
    assert any('maximum' in error for error in acceptance_failures(report))
    assert any('missing compositor' in error for error in acceptance_failures(report))


def test_compositor_drops_fail_even_when_application_cadence_passes():
    report = dict(runtime_hz=90, reports=[dict(target='stick', preset='steady_fast',
                  bands=dict(whole_load=dict(samples=100, p99_ms=11.4, max_ms=12)),
                  compositor=dict(samples=100, dropped=4))])
    assert acceptance_failures(report) == ['stick/steady_fast compositor drops exceed 0.1%']
    report['reports'][0]['compositor']['dropped'] = 0
    assert acceptance_failures(report) == []


def test_performance_tour_uses_browser_document_and_validation_dispatch():
    tour = next(item for item in catalog()['tours'] if item['id'] == 'loading-performance')
    assert tour['module'] == 'browser_representation_tour'
    assert '--profile' in arguments(tour, True)
    assert '--validate' in arguments(tour, True)


def test_trace_overflow_invalidates_even_short_intervals(tmp_path):
    (tmp_path/'native').mkdir()
    (tmp_path/'native/results.json').write_text(json.dumps([
        dict(target='surface', preset='steady_fast', samples=[dict(wall_time_ms=100), dict(wall_time_ms=1000)])
    ]))
    (tmp_path/'native-viewer.log').write_text('VR_TRACE_DROPPED epoch_ms=500 count=40\n')
    report = summarize(tmp_path)
    assert report['reports'][0]['trace_dropped'] == 40
    assert any('trace samples lost' in error for error in acceptance_failures(report))
    assert any('insufficient frame timing' in error for error in acceptance_failures(report))


def test_frame_polling_preserves_real_frame_barrier(monkeypatch):
    from frontend.scrywrite.mcp_bridge import Bridge
    sleeps = []
    monkeypatch.setattr('frontend.scrywrite.mcp_bridge.time.sleep', sleeps.append)
    class Frames(Bridge):
        frame = 0
        def request(self, command):
            assert command == 'observe'
            self.frame += 1
            return dict(session='1-2', frame=self.frame)
    result = Frames().call('scrywrite_wait', dict(session='1-2', field='frame', value=3, comparison='at_least'))
    assert result['frame'] == 3
    assert sleeps == [.001, .001]
