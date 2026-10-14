import json
import os
import zlib

import pytest

from tools.vr_capture.audit import audit_directory, compare_reports
from tools.vr_capture.session import arm


def make_capture(tmp_path, *, remove=None, duplicate=False, corrupt=False, test_surface=False):
    raw = bytes([15, 35, 100, 255]) * 4
    (tmp_path / 'frame-1.bgra.z').write_bytes(zlib.compress(raw if not corrupt else raw[:-1]))
    rows = [
        {'event': 'swapchain', 'swapchain': 1, 'width': 2, 'height': 2, 'format': 44,
         'mode': 2, 'direct_display': not test_surface, 'test_surface': test_surface},
        {'event': 'capture_start', 'request': 7, 'start_ns': 100, 'end_ns': 200},
        {'event': 'present', 'request': 7, 'enter_ns': 150, 'swapchain': 1, 'present': 4,
         'present_id': 12, 'copied': True, 'result': 0, 'image_result': 0},
        {'event': 'frame_saved', 'request': 7, 'swapchain': 1, 'present': 4,
         'width': 2, 'height': 2, 'format': 44, 'file': 'frame-1.bgra.z'},
        {'event': 'capture_interval_end', 'request': 7},
        {'event': 'capture_complete', 'request': 7, 'active_presents': 1,
         'copied_frames': 1, 'saved': 1, 'pixel_drops': 0, 'event_drops': 0},
        {'event': 'wait_for_present', 'swapchain': 1, 'present_id': 12, 'result': 0,
         'driver_reports_present_complete': True},
    ]
    if duplicate:
        rows.append(dict(rows[3]))
    rows = [r for r in rows if r['event'] != remove]
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return rows


def test_byte_exact_present_accounting_does_not_claim_scanout(tmp_path):
    make_capture(tmp_path)
    result = audit_directory(tmp_path)
    assert result['complete_present_capture']
    assert result['direct_display_provenance']
    assert not result['headset_identity_verified']
    assert result['matched_present_completion_waits'] == 1
    assert result['verified_pixels'] == 1
    assert not result['refresh_mapping_verified']
    assert not result['optical_output_verified']


@pytest.mark.parametrize('missing', ['capture_start', 'capture_interval_end', 'capture_complete', 'frame_saved', 'present'])
def test_missing_evidence_cannot_pass(tmp_path, missing):
    make_capture(tmp_path, remove=missing)
    assert not audit_directory(tmp_path)['complete_present_capture']


@pytest.mark.parametrize('write_begin,passed', [(199, False), (200, True), (None, False)])
def test_deferred_writer_must_prove_it_waited_for_recording_end(tmp_path, write_begin, passed):
    rows = make_capture(tmp_path)
    rows.insert(0, {'event': 'layer_start', 'deferred_pixel_writes': True})
    saved = next(r for r in rows if r['event'] == 'frame_saved')
    if write_begin is not None:
        saved.update(write_begin_ns=write_begin, write_end_ns=250)
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    result = audit_directory(tmp_path)
    assert result['complete_present_capture'] is passed
    assert result['bulk_writes_after_recording_verified'] is passed


@pytest.mark.parametrize('missing', [None, 'file_fdatasynced', 'file_closed', 'directory_synced', 'persistence_ok'])
def test_durable_capture_requires_sync_and_close_evidence(tmp_path, missing):
    rows = make_capture(tmp_path)
    rows.insert(0, {'event': 'layer_start', 'durable_pixel_files': True})
    next(r for r in rows if r['event'] == 'frame_saved').update(file_fdatasynced=True, file_closed=True)
    next(r for r in rows if r['event'] == 'capture_complete').update(directory_synced=True, persistence_ok=True)
    for row in rows:
        row.pop(missing, None)
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    report = audit_directory(tmp_path)
    assert report['complete_present_capture'] is (missing is None)
    assert report['pixel_file_persistence_verified'] is (missing is None)


@pytest.mark.parametrize('kwargs', [{'duplicate': True}, {'corrupt': True}])
def test_duplicate_or_corrupt_image_rejected(tmp_path, kwargs):
    make_capture(tmp_path, **kwargs)
    assert not audit_directory(tmp_path)['complete_present_capture']


@pytest.mark.parametrize('invalid', [None, 'direct_io', 'logical_truncate_succeeded',
                                  'physical_written_bytes', 'direct_offset_alignment'])
def test_direct_disk_writes_require_accounting_and_exact_truncation(tmp_path, invalid):
    rows = make_capture(tmp_path)
    rows.insert(0, {'event': 'layer_start', 'archive_direct_io': True})
    saved = next(r for r in rows if r['event'] == 'frame_saved')
    size = (tmp_path/saved['file']).stat().st_size
    saved.update(direct_io=True, logical_truncate_succeeded=True, direct_memory_alignment=512,
                 direct_offset_alignment=512, written_bytes=size, physical_written_bytes=512,
                 padding_bytes=512-size, pack_bytes=size)
    if invalid:
        saved[invalid] = False
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    report = audit_directory(tmp_path)
    assert report['complete_present_capture'] is (invalid is None)
    assert report['direct_disk_io_verified'] is (invalid is None)


def test_synthetic_surface_not_headset_evidence(tmp_path):
    make_capture(tmp_path, test_surface=True)
    result = audit_directory(tmp_path)
    assert result['complete_present_capture']
    assert not result['direct_display_provenance']


def test_truncated_metadata_is_a_failure(tmp_path):
    make_capture(tmp_path)
    with (tmp_path / 'events-1.jsonl').open('a') as stream:
        stream.write('{"event":')
    result = audit_directory(tmp_path)
    assert result['errors']
    assert not result['complete_present_capture']


def test_file_escape_rejected(tmp_path):
    rows = make_capture(tmp_path)
    next(r for r in rows if r['event'] == 'frame_saved')['file'] = '../elsewhere.z'
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    assert not audit_directory(tmp_path)['complete_present_capture']


def test_same_rate_does_not_prove_negligible_overhead(tmp_path):
    make_capture(tmp_path)
    report = audit_directory(tmp_path)
    result = compare_reports(report, report)
    assert result['comparable_surface']
    assert not result['negligible_overhead_verified']


@pytest.mark.parametrize('seconds', [-1, 0, 11, float('inf'), float('nan')])
def test_record_duration_bounded(tmp_path, seconds):
    with pytest.raises(ValueError):
        arm(tmp_path, seconds, delay=0)
    assert not list(tmp_path.iterdir())


def test_arm_requires_layer_evidence(tmp_path):
    with pytest.raises(RuntimeError):
        arm(tmp_path, 5, delay=0)


def test_arm_writes_a_single_atomic_request(tmp_path):
    (tmp_path / 'events-1.jsonl').write_text(json.dumps({'event': 'layer_start', 'pid': os.getpid()}) + '\n')
    request = arm(tmp_path, 5, delay=0)
    assert (tmp_path / 'control.txt').read_text() == f"{request['token']} 5.000000000\n"
    assert not list(tmp_path.glob('*.tmp'))


def test_arm_rejects_stale_layer_files(tmp_path):
    path = tmp_path / 'events-1.jsonl'
    path.write_text(json.dumps({'event': 'layer_start', 'pid': os.getpid()}) + '\n')
    os.utime(path, (1, 1))
    with pytest.raises(RuntimeError):
        arm(tmp_path, 5, delay=0)


def test_lost_events_cannot_pass_even_if_remaining_files_match(tmp_path):
    rows = make_capture(tmp_path)
    next(r for r in rows if r['event'] == 'capture_complete')['event_drops'] = 1
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    assert not audit_directory(tmp_path)['complete_present_capture']


def test_review_png_preserves_panel_row_order_and_converts_bgra():
    import struct
    from tools.vr_capture.review import png_bytes
    raw = bytes([0, 0, 255, 255, 0, 255, 0, 255,
                 255, 0, 0, 255, 0, 255, 255, 255])
    png = png_bytes(raw, 2, 2, 44)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    cursor, payload = 8, b''
    while cursor < len(png):
        size = struct.unpack('>I', png[cursor:cursor+4])[0]
        kind = png[cursor+4:cursor+8]
        if kind == b'IDAT':
            payload += png[cursor+8:cursor+8+size]
        cursor += size + 12
    assert zlib.decompress(payload) == bytes([0, 255, 0, 0, 0, 255, 0,
                                            0, 0, 0, 255, 255, 255, 0])


def test_metadata_only_audit_does_not_claim_complete_pixels(tmp_path):
    make_capture(tmp_path)
    assert not audit_directory(tmp_path, verify_pixels=False)['complete_present_capture']


def test_missing_swapchain_metadata_prevents_headset_claim(tmp_path):
    make_capture(tmp_path, remove='swapchain')
    report = audit_directory(tmp_path)
    assert not report['complete_present_capture']
    assert not report['direct_display_provenance']


def test_saved_format_must_match_actual_swapchain(tmp_path):
    rows = make_capture(tmp_path)
    next(r for r in rows if r['event'] == 'frame_saved')['format'] = 37
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    assert not audit_directory(tmp_path)['complete_present_capture']


@pytest.mark.parametrize('trailing', [False, True])
def test_zstd_exact_decode_and_trailing_payload_rejected(tmp_path, trailing):
    import ctypes
    from tools.vr_capture.pixels import decode_frame, zstd_library
    try:
        library = zstd_library()
    except OSError:
        pytest.skip('System Zstandard runtime unavailable')
    library.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                     ctypes.c_size_t, ctypes.c_int]
    library.ZSTD_compress.restype = ctypes.c_size_t
    raw = bytes(range(16))
    output = ctypes.create_string_buffer(1024)
    size = library.ZSTD_compress(output, len(output), raw, len(raw), 1)
    assert not library.ZSTD_isError(size)
    (tmp_path/'panel.bgra.zst').write_bytes(output.raw[:size] + (b'garbage' if trailing else b''))
    row = {'file': 'panel.bgra.zst', 'codec': 'zstd', 'width': 2, 'height': 2, 'raw_bytes': 16}
    if trailing:
        with pytest.raises(ValueError):
            decode_frame(tmp_path, row)
    else:
        assert decode_frame(tmp_path, row) == raw


@pytest.mark.parametrize('bad_offset', [None, 0, -1])
def test_packed_capture_requires_disjoint_complete_frame_ranges(tmp_path, bad_offset):
    rows = make_capture(tmp_path)
    first = (tmp_path/'frame-1.bgra.z').read_bytes()
    second = zlib.compress(bytes([50, 20, 5, 255]) * 4)
    (tmp_path/'capture.frames.z').write_bytes(first+second)
    saved = next(r for r in rows if r['event'] == 'frame_saved')
    saved.update(file='capture.frames.z', file_offset=0, compressed_bytes=len(first))
    present = next(r for r in rows if r['event'] == 'present')
    rows.append(dict(present, present=5, present_id=13, enter_ns=160))
    rows.append(dict(saved, present=5, file_offset=len(first) if bad_offset is None else bad_offset,
                     compressed_bytes=len(second)))
    next(r for r in rows if r['event'] == 'capture_complete').update(active_presents=2, copied_frames=2, saved=2)
    (tmp_path / 'events-1.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    report = audit_directory(tmp_path)
    assert report['complete_present_capture'] is (bad_offset is None)
    if bad_offset is None:
        assert report['pixel_storage_file_count'] == 1
        assert len({p['sha256'] for p in report['pixel_evidence']}) == 2


def test_random_access_to_large_pack_reads_only_one_compressed_frame(tmp_path):
    from tools.vr_capture.pixels import decode_frame
    raw = bytes(range(16))
    payload = zlib.compress(raw)
    offset = 2*1024*1024*1024-len(payload)
    with (tmp_path/'sparse.frames.z').open('wb') as stream:
        stream.seek(offset)
        stream.write(payload)
    row = {'file': 'sparse.frames.z', 'file_offset': offset, 'compressed_bytes': len(payload),
           'width': 2, 'height': 2, 'codec': 'zlib'}
    assert decode_frame(tmp_path, row) == raw
    for key, value in [('file_offset', -1), ('file_offset', True), ('file_offset', offset+1),
                       ('compressed_bytes', None), ('compressed_bytes', 9999999)]:
        with pytest.raises(ValueError):
            decode_frame(tmp_path, dict(row, **{key: value}))
    with (tmp_path/'sparse.frames.z').open('ab') as stream:
        stream.write(b'\0')
    with pytest.raises(ValueError, match='excessive packed-frame range'):
        decode_frame(tmp_path, row)


def test_capture_environment_is_scoped_and_diagnostic_is_explicit(monkeypatch, tmp_path):
    from tools.vr_capture.launch_compositor import make_environment
    monkeypatch.setenv('NADOC_VR_CAPTURE_TEST_SURFACES', '1')
    monkeypatch.setenv('NADOC_VR_CAPTURE_DIAGNOSTIC_FDS', '1')
    monkeypatch.setenv('LD_PRELOAD', '/unrelated/library.so')
    ordinary = make_environment()
    assert 'VK_INSTANCE_LAYERS' not in ordinary
    assert 'NADOC_VR_CAPTURE_TEST_SURFACES' not in ordinary
    assert 'NADOC_VR_CAPTURE_DIAGNOSTIC_FDS' not in ordinary
    assert 'LD_PRELOAD' not in ordinary
    prepared = make_environment(tmp_path, tmp_path, diagnostic_fds=True)
    assert prepared['NADOC_VR_CAPTURE_DIAGNOSTIC_FDS'] == '1'
    assert 'NADOC_VR_CAPTURE_TEST_SURFACES' not in prepared
    assert int(prepared['NADOC_VR_CAPTURE_COMPRESSED_BYTES']) == 1280*1024*1024


def test_archive_mount_failure_does_not_create_capture_directory(monkeypatch, tmp_path):
    from tools.vr_capture.launch_compositor import prepare_output
    monkeypatch.setattr(os.path, 'ismount', lambda path: False)
    destination = tmp_path/'new'
    with pytest.raises(RuntimeError):
        prepare_output(destination)
    assert not destination.exists()
