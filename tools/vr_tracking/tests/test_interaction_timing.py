import copy
import hashlib
import json
import struct
import zlib

import pytest

from tools.vr_tracking import interaction_timing as it

BASE = 1_000_000_000
MS = 1_000_000


def packet(eye, frame):
    body = struct.pack('>2sBBIQQ', b'NF', 2, int(eye == 'right'), 123, 456, frame)
    crc = zlib.crc32(body)
    return body + struct.pack('>I', crc) + bytes.fromhex('a55ac33c'), crc


def evidence(tmp_path):
    header = dict(event='pose_journal_start', schema=1, source='application_projection', session='123-456',
                  request=77, space='OpenXR_LOCAL', units='meters', clock='CLOCK_MONOTONIC',
                  clock_mapping='XR_KHR_convert_timespec_time', capture_start_monotonic_ns=BASE+5*MS,
                  capture_end_monotonic_ns=BASE+125*MS, capacity_frames=8192,
                  frame_identity=dict(enabled=True, protocol='nadoc-frame-v2'))
    rows = []
    for i, duration in enumerate((10, 20, 10, 10, 10)):
        start = BASE+i*30*MS
        end = start+duration*MS
        row = dict(event='application_frame', source='application_projection', frame=100+i,
                   predicted_display_time_ns=BASE+(i*30+15)*MS,
                   predicted_display_monotonic_ns=BASE+(i*30+15)*MS,
                   predicted_display_period_ns=10*MS, clock_mapping=header['clock_mapping'],
                   host_frame_start_ns=start, host_frame_end_ns=end,
                   host_actions_start_ns=start+MS, host_actions_end_ns=start+3*MS,
                   host_locate_views_start_ns=start+3*MS, host_locate_views_end_ns=start+4*MS,
                   host_end_frame_start_ns=end-2*MS, host_end_frame_end_ns=end-MS,
                   submitted=True, xr_end_frame_succeeded=True, menu_open=[i == 1, False],
                   view_state_flags=15, hands=[dict(valid=True, grip=False, input_source='physical',
                     runtime_location_flags=15, runtime_pose_queried=True, runtime_pose_action_active=True)]*2,
                   eyes=[dict(eye=eye, rendered=True, frame_identity=dict(rendered=True, frame=100+i,
                         packet_crc32=packet(eye, 100+i)[1])) for eye in ('left', 'right')])
        row['host_window_relation'] = 'capture' if end < header['capture_end_monotonic_ns'] else 'tail'
        row['predicted_window_relation'] = 'capture' if row['predicted_display_monotonic_ns'] < header['capture_end_monotonic_ns'] else 'tail'
        rows.append(row)
    trailer = dict(event='pose_journal_complete', frames=len(rows), overflow_frames=0, mapping_failures=0, complete=True)
    path = tmp_path/'journal.jsonl'
    def save():
        path.write_text(''.join(json.dumps(r)+'\n' for r in [header, *rows, trailer]))
    save()
    return path, header, rows, trailer, save


def diagnostics(row, *, haptic=False, hover=False):
    event = dict(hand=0, callsite_line=20, amplitude=.4, request_ns=row['host_frame_start_ns']+MS,
                 dispatch_begin_ns=row['host_frame_start_ns']+MS, dispatch_end_ns=row['host_frame_start_ns']+2*MS,
                 dispatched=True, xr_result=0)
    return dict(version=1, enabled=True, clock='CLOCK_MONOTONIC', clock_errors=0, clock_queries=5,
                gpu_timing_available=False, onscreen_visibility_available=False,
                haptics=dict(requested=[int(haptic),0], dispatched=[int(haptic),0], failed=[0,0],
                    host_total_ns=[MS if haptic else 0,0], host_max_ns=[MS if haptic else 0,0],
                    events=[event] if haptic else [], events_overflow=0),
                sidebars=[dict(hand=h, open=h == 0, hover_id='Tools' if h == 0 else '', hover_truncated=False,
                    hover_previous_known=True, hover_change_valid=True, hover_changed=hover and h == 0,
                    texture_updates=1, texture_cache_hits=0, texture_update_host_ns=100, draw_calls=1, draw_host_ns=200)
                    for h in range(2)],
                eyes=[dict(eye=e, menu_draw_calls=1, menu_host_ns=300, backdrop_copy_calls=1, backdrop_host_ns=100)
                      for e in ('left', 'right')])


def identities(path, header, rows, indices=(0, 0, None, 1, 2)):
    frames = []
    for i, index in enumerate(indices):
        host = BASE+(i*10+20)*MS
        source = dict(coordinate_space='final_swapchain_distorted', provenance=dict(request=77, index=i, present=200+i,
                      host_present_enter_ns=host))
        item = dict(capture_index=i, present=200+i, host_present_enter_ns=host, source=source, eyes={})
        for eye in ('left', 'right'):
            if index is None:
                item['eyes'][eye] = dict(status='unknown', reason='no_marker')
                continue
            row = rows[index]
            wire, crc = packet(eye, row['frame'])
            item['eyes'][eye] = dict(status='joined', identity=dict(session=header['session'], eye=eye, frame=row['frame'],
                packet_crc32=crc, packet_hex=wire.hex()), journal={k: row[k] for k in
                ('frame', 'predicted_display_time_ns', 'predicted_display_monotonic_ns', 'host_frame_start_ns', 'host_frame_end_ns', 'clock_mapping')})
            item['eyes'][eye]['journal']['eye'] = eye
        frames.append(item)
    report = dict(schema=1, protocol='nadoc-frame-v2', session=header['session'], request=77,
                  coordinate_space='final_swapchain_distorted', journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), frames=frames)
    output = path.parent/'identities.json'
    output.write_text(json.dumps(report))
    return output, report


def test_legacy_available_timing_and_exact_window_boundaries(tmp_path):
    path, _, _, _, _ = evidence(tmp_path)
    result = it.summarize_interactions(path)
    first = result['frames'][0]
    assert first['host_window_relation'] == 'capture'  # Native uses END, not start.
    assert first['host_start_window_relation'] == 'preroll'
    assert first['frame_ms'] == 10 and first['actions_ms'] == 2 and first['xr_end_frame_ms'] == 1
    assert result['summary']['all_retained']['interaction_telemetry_frames'] == 0
    assert result['summary']['all_retained']['haptics'] is None
    assert result['summary']['host_start_in_capture']['frames'] == 4
    assert not result['causality_verified'] and not result['optical_output_verified']


def test_menu_haptic_hover_association_does_not_claim_cause(tmp_path):
    path, _, rows, _, save = evidence(tmp_path)
    for i, row in enumerate(rows):
        row['capture_ui_diagnostics'] = diagnostics(row, haptic=i == 1, hover=i == 1)
    save()
    result = it.summarize_interactions(path)
    summary = result['summary']['all_retained']
    assert summary['associations']['haptic_dispatched']['true']['frame_ms']['median'] == 20
    assert summary['associations']['hover_changed']['true']['frames'] == 1
    assert summary['haptics']['dispatched'] == [1, 0]
    assert result['causality_verified'] is False
    rows[1]['capture_ui_diagnostics'] = diagnostics(rows[1])
    save()
    negative = it.summarize_interactions(path)['summary']['all_retained']
    assert negative['timing_ms']['frame_ms']['max'] == 20
    assert negative['associations']['haptic_dispatched']['true']['frames'] == 0


@pytest.mark.parametrize('change', ['frame_inverted', 'frame_overlap', 'actions_inverted', 'actions_outside', 'end_partial',
                                    'predicted_reverse', 'window_lie', 'trailer_count', 'trailer_overflow', 'schema_bool'])
def test_invalid_timing_and_completion_fail_closed(tmp_path, change):
    path, header, rows, trailer, save = evidence(tmp_path)
    if change == 'frame_inverted': rows[0]['host_frame_end_ns'] = BASE-1
    if change == 'frame_overlap': rows[1]['host_frame_start_ns'] = BASE+1
    if change == 'actions_inverted': rows[0]['host_actions_end_ns'] = BASE
    if change == 'actions_outside': rows[0]['host_actions_start_ns'] = BASE-1
    if change == 'end_partial': del rows[0]['host_end_frame_start_ns']
    if change == 'predicted_reverse': rows[1]['predicted_display_time_ns'] = 1
    if change == 'window_lie': rows[0]['host_window_relation'] = 'preroll'
    if change == 'trailer_count': trailer['frames'] = 9
    if change == 'trailer_overflow': trailer['overflow_frames'] = 1
    if change == 'schema_bool': header['schema'] = True
    save()
    with pytest.raises(ValueError): it.summarize_interactions(path)


def test_unmapped_clock_null_not_invented_and_missing_interval_unavailable(tmp_path):
    path, _, rows, trailer, save = evidence(tmp_path)
    rows[0].update(clock_mapping='unavailable', predicted_display_monotonic_ns=None, predicted_window_relation=None)
    rows[0]['host_actions_start_ns'] = rows[0]['host_actions_end_ns'] = 0
    trailer['mapping_failures'] = 1
    save()
    r = it.summarize_interactions(path)['frames'][0]
    assert r['predicted_display_monotonic_ns'] is None and r['actions_ms'] is None
    rows[0]['predicted_display_monotonic_ns'] = BASE
    save()
    with pytest.raises(ValueError): it.summarize_interactions(path)


def test_first_hover_unknown_and_nonrendered_sidebar_observation(tmp_path):
    path, _, rows, _, save = evidence(tmp_path)
    rows[0]['eyes'] = []
    rows[0]['submitted'] = False
    save()
    assert it.summarize_interactions(path)['frames'][0]['menu_open'] is None
    d = diagnostics(rows[0])
    d['sidebars'][0].update(hover_previous_known=False, hover_change_valid=False)
    rows[0]['capture_ui_diagnostics'] = d
    save()
    r = it.summarize_interactions(path)['frames'][0]
    assert r['menu_open'] == [True, False] and it._hover_changed(r) is None


@pytest.mark.parametrize('result,failed', [(0,0), (1,0), (-1,1)])
def test_haptic_result_success_includes_positive_codes(tmp_path, result, failed):
    path, _, rows, _, save = evidence(tmp_path)
    d = diagnostics(rows[0], haptic=True)
    d['haptics']['events'][0]['xr_result'] = result
    d['haptics']['failed'][0] = failed
    rows[0]['capture_ui_diagnostics'] = d
    save()
    assert it.summarize_interactions(path)['summary']['all_retained']['haptics']['failed'] == [failed, 0]


@pytest.mark.parametrize('change', ['counters', 'overflow', 'inverted', 'outside', 'hover_invalid', 'long_hover', 'suppressed_time'])
def test_malformed_diagnostics_rejected(tmp_path, change):
    path, _, rows, _, save = evidence(tmp_path)
    d = diagnostics(rows[0], haptic=True)
    if change == 'counters': d['haptics']['dispatched'][0] = 0
    if change == 'overflow': d['haptics']['events_overflow'] = 1
    if change == 'inverted': d['haptics']['events'][0]['dispatch_end_ns'] = BASE
    if change == 'outside': d['haptics']['events'][0]['request_ns'] = BASE-1
    if change == 'hover_invalid': d['sidebars'][0].update(hover_changed=True, hover_change_valid=False)
    if change == 'long_hover': d['sidebars'][0]['hover_id'] = 'é'*49
    if change == 'suppressed_time': d['haptics']['events'][0]['dispatched'] = False
    rows[0]['capture_ui_diagnostics'] = d
    save()
    with pytest.raises(ValueError): it.summarize_interactions(path)


def test_haptic_overflow_preserves_aggregate_and_clock_error_is_unavailable(tmp_path):
    path, _, rows, _, save = evidence(tmp_path)
    d = diagnostics(rows[0], haptic=True)
    d['haptics']['requested'][0] = 2
    d['haptics']['events_overflow'] = 1
    rows[0]['capture_ui_diagnostics'] = d
    save()
    r = it.summarize_interactions(path)
    assert r['summary']['all_retained']['haptics']['events_overflow'] == 1
    d['clock_errors'] = 1
    save()
    assert not it.summarize_interactions(path)['frames'][0]['interaction']['available']


def test_exact_id_holds_unknown_breaks_and_pin_hash(tmp_path):
    path, h, rows, _, _ = evidence(tmp_path)
    ids, _ = identities(path, h, rows)
    result = it.summarize_interactions(path, ids)['identities']
    assert result['sha256'] == hashlib.sha256(ids.read_bytes()).hexdigest()
    assert [r['eyes']['left']['image_transition'] for r in result['frames']] == ['unavailable', 'held', 'unavailable', 'unavailable', 'advanced']
    assert result['frames'][2]['stereo_app_ids_match'] is None


@pytest.mark.parametrize('change', ['hash', 'session', 'request', 'bool_request', 'eye', 'crc', 'packet', 'frame',
                                    'claimed_time', 'source_request', 'source_bool_index', 'protocol', 'schema', 'disabled'])
def test_identity_mismatch_rejected(tmp_path, change):
    path, h, rows, _, save = evidence(tmp_path)
    if change == 'disabled': h['frame_identity']['enabled'] = False; save()
    ids, report = identities(path, h, rows)
    eye = report['frames'][0]['eyes']['left']
    if change == 'hash': report['journal_sha256'] = '0'*64
    if change == 'session': report['session'] = '123-999'
    if change == 'request': report['request'] = 78
    if change == 'bool_request': report['request'] = True
    if change == 'eye': eye['identity']['eye'] = 'right'
    if change == 'crc': eye['identity']['packet_crc32'] ^= 1
    if change == 'packet': eye['identity']['packet_hex'] = '00'*32
    if change == 'frame': eye['identity']['frame'] = 9999
    if change == 'claimed_time': eye['journal']['host_frame_start_ns'] += 1
    if change == 'source_request': report['frames'][0]['source']['provenance']['request'] = 78
    if change == 'source_bool_index': report['frames'][0]['source']['provenance']['index'] = False
    if change == 'protocol': report['protocol'] = None
    if change == 'schema': report['schema'] = True
    ids.write_text(json.dumps(report))
    with pytest.raises(ValueError): it.summarize_interactions(path, ids)


def test_unknown_payload_is_not_rescued_and_nonadjacent_indices_break(tmp_path):
    path, h, rows, _, _ = evidence(tmp_path)
    ids, report = identities(path, h, rows)
    report['frames'][2]['eyes']['left']['identity'] = copy.deepcopy(report['frames'][0]['eyes']['left']['identity'])
    report['frames'] = report['frames'][::4]
    ids.write_text(json.dumps(report))
    assert it.summarize_interactions(path, ids)['identities']['frames'][-1]['eyes']['left']['image_transition'] == 'unavailable'


def test_html_safe_exact_uint64_and_cli(tmp_path, monkeypatch, capsys):
    path, _, rows, _, save = evidence(tmp_path)
    rows[-1]['frame'] = (1 << 63)+101
    d = diagnostics(rows[0])
    d['sidebars'][0]['hover_id'] = '</script><img src=x onerror=evil()>'
    rows[0]['capture_ui_diagnostics'] = d
    save()
    from tools.vr_tracking.__main__ import main
    out = tmp_path/'report'
    monkeypatch.setattr('sys.argv', ['vr_tracking', 'summarize-interactions', '--journal', str(path), '--output', str(out)])
    main()
    page = (out/'index.html').read_text()
    assert '\\u003c/script>' in page and '</script><img' not in page
    assert '"frame": "9223372036854775909"' in page
    assert json.loads(capsys.readouterr().out)['journal_frames'] == 5
    with pytest.raises(FileExistsError): it.write_interaction_report(it.summarize_interactions(path), out)


def test_suppressed_haptic_request_not_dispatch_and_inactive_runtime_not_invalid_query(tmp_path):
    path, _, rows, _, save = evidence(tmp_path)
    d = diagnostics(rows[0], haptic=True)
    event = d['haptics']['events'][0]
    event.update(dispatched=False, dispatch_begin_ns=0, dispatch_end_ns=0, xr_result=None)
    for key in ('dispatched', 'host_total_ns', 'host_max_ns'): d['haptics'][key] = [0, 0]
    rows[0]['capture_ui_diagnostics'] = d
    rows[0]['hands'] = [dict(valid=False, grip=False, input_source='physical', runtime_location_flags=0,
                            runtime_pose_queried=False, runtime_pose_action_active=False)]*2
    save()
    summary = it.summarize_interactions(path)['summary']['all_retained']
    assert summary['haptics']['requested'] == [1, 0] and summary['haptics']['dispatched'] == [0, 0]
    assert summary['hands'][0]['applied_invalid_frames'] == 1
    assert summary['hands'][0]['queried_runtime_invalid_frames'] == 0
    assert summary['ui']['clock_queries'] == 5
    assert summary['ui']['eyes'][0]['menu_host_ms']['median'] == .0003


def test_unknown_identity_ignores_plausible_payload_and_size_bound(tmp_path, monkeypatch):
    path, h, rows, _, _ = evidence(tmp_path)
    ids, report = identities(path, h, rows)
    report['frames'][2]['eyes']['left']['identity'] = copy.deepcopy(report['frames'][0]['eyes']['left']['identity'])
    ids.write_text(json.dumps(report))
    result = it.summarize_interactions(path, ids)
    assert result['identities']['frames'][2]['eyes']['left']['app_frame'] is None
    monkeypatch.setattr(it, 'MAX_BYTES', 20)
    with pytest.raises(ValueError, match='bounded'): it.summarize_interactions(path, ids)


def test_nonrendered_default_state_not_counted_as_tracking_failure(tmp_path):
    path, _, rows, _, save = evidence(tmp_path)
    row = rows[0]
    row['eyes'] = []
    row['submitted'] = False
    row['view_state_flags'] = 0
    row['host_locate_views_start_ns'] = row['host_locate_views_end_ns'] = 0
    row['hands'] = [dict(valid=False, grip=False, input_source='physical', runtime_location_flags=0,
                        runtime_pose_queried=False, runtime_pose_action_active=False)]*2
    save()
    result = it.summarize_interactions(path)
    assert result['frames'][0]['tracking']['view']['valid'] is None
    assert result['summary']['all_retained']['view_invalid_frames'] == 0
    assert result['summary']['all_retained']['view_unobserved_frames'] == 1
    assert result['summary']['all_retained']['hands'][0]['applied_invalid_frames'] == 0
    assert result['summary']['all_retained']['hands'][0]['applied_state_unavailable_frames'] == 1
