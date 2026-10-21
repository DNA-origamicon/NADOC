"""Playback timing must not confuse repeated headset frames with scene delivery."""
import json
from tools.vr_workflows.playback_metrics import distribution, summarize


def test_distribution_empty_and_tail():
    assert distribution([]) == {'count': 0}
    assert distribution([200, 80, 90]) == {'count': 3, 'p50': 90, 'p95': 200, 'max': 200}


def test_scene_versions_are_counted_once_and_missing_gpu_is_not_success(tmp_path):
    (tmp_path/'windows.json').write_text(json.dumps([{
        'name': 'play', 'representation': 'stick', 'smooth': False, 'start': 100, 'end': 500}]))
    (tmp_path/'viewer.log').write_text('\n'.join([
        'VR_FRAME_AUDIT frame=1 epoch_ms=100 total_ms=11 submitted=1',
        'VR_FRAME_AUDIT frame=2 epoch_ms=111 total_ms=11 submitted=1',
        'VR_FRAME_AUDIT frame=3 epoch_ms=250 total_ms=22 submitted=1',
        'VR_FRAME_AUDIT frame=4 epoch_ms=800 total_ms=99 submitted=1',
        'VR_GPU_PASS frame=1 valid=1 view_tools_version=8 total_ns=1000000',
        'VR_GPU_PASS frame=2 valid=1 view_tools_version=8 total_ns=2000000',
        'VR_GPU_PASS frame=3 valid=1 view_tools_version=9 total_ns=3000000',
    ]))
    row = summarize(tmp_path)[0]
    assert row['submitted_scene_gap_ms']['max'] == 150
    assert row['scene_gaps_over_125ms'] == 1
    assert row['scene_window_max_gap_ms'] == 250
    assert row['scene_cadence_pass'] is False
    assert row['native_frames_over_16_67ms'] == 1
    assert row['gpu_ms']['max'] == 3
    (tmp_path/'viewer.log').write_text('')
    assert summarize(tmp_path)[0]['submitted_scene_gap_ms'] == {'count': 0}
    assert summarize(tmp_path)[0]['scene_cadence_pass'] is False


def test_unobserved_gpu_frames_cannot_certify_smooth_delivery(tmp_path):
    (tmp_path/'windows.json').write_text(json.dumps([{
        'name': 'play', 'representation': 'vdw', 'smooth': False, 'start': 100, 'end': 200}]))
    (tmp_path/'viewer.log').write_text('\n'.join([
        'VR_FRAME_AUDIT frame=1 epoch_ms=100 total_ms=11 submitted=1',
        'VR_FRAME_AUDIT frame=2 epoch_ms=111 total_ms=11 submitted=1',
        'VR_FRAME_AUDIT frame=3 epoch_ms=180 total_ms=11 submitted=1',
        'VR_GPU_PASS frame=1 valid=1 view_tools_version=8 total_ns=1000000',
        'VR_GPU_PASS frame=3 valid=1 view_tools_version=9 total_ns=1000000',
    ]))
    row = summarize(tmp_path)[0]
    assert row['submitted_scene_gap_ms']['max'] == 80
    assert row['gpu_missing_frames'] == 1
    assert row['scene_cadence_pass'] is False


def test_interleaved_startup_logging_is_reported_without_crashing_metrics(tmp_path):
    from tools.vr_workflows.playback_metrics import numeric_records
    text = ('VR_FRAME_AUDIT epoch_ms=1792599704Using breakpad crash handler\n'
            'other output VR_FRAME_AUDIT frame=3 epoch_ms=200 total_ms=11 submitted=1\n')
    rows, bad, intervals = numeric_records(text,'VR_FRAME_AUDIT',('frame','epoch_ms','total_ms'))
    assert len(rows)==1 and rows[0]['frame']=='3'
    assert bad==1 and intervals==[(float('-inf'),200)]
    (tmp_path/'viewer.log').write_text(text)
    (tmp_path/'windows.json').write_text(json.dumps([{'name':'play','representation':'stick','smooth':False,'start':100,'end':300}]))
    result=summarize(tmp_path)[0]
    assert result['malformed_frames_in_window']==1
    assert result['scene_cadence_pass'] is False
