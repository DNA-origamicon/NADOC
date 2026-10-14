"""Fail-closed accounting for final-swapchain recordings.

The layer samples the presentation boundary, not emitted photons. Completion
and refresh mapping are deliberately separate from successful image readback.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zlib

from .pixels import decode_frame


def percentile(values, percent):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * percent / 100
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def distribution(values):
    return {'count': len(values), 'median': percentile(values, 50),
            'p95': percentile(values, 95), 'max': max(values) if values else None}


def load_events(directory):
    rows, errors = [], []
    for source in sorted(directory.glob('events-*.jsonl')):
        with source.open() as stream:
            for number, text in enumerate(stream, 1):
                try:
                    row = json.loads(text)
                    row['_source'] = source.name
                    rows.append(row)
                except (ValueError, TypeError) as error:
                    errors.append(f'{source.name}:{number}: {error}')
    return rows, errors


def audit_directory(directory: Path, request: int | None = None, *, verify_pixels=True):
    directory = directory.resolve(strict=True)
    rows, errors = load_events(directory)
    event = lambda row: row.get('event', row.get('type'))
    starts = [r for r in rows if event(r) == 'capture_start']
    if request is None and starts:
        newest = max(starts, key=lambda r: r['start_ns'])
        request = newest['request']
        rows = [r for r in rows if r['_source'] == newest['_source']]
    starts = [r for r in starts if r.get('request') == request]
    result = {'schema': 1, 'directory': str(directory), 'request': request,
              'complete_present_capture': False, 'refresh_mapping_verified': False,
              'optical_output_verified': False, 'errors': errors,
              'capture_boundary': 'final_swapchain_before_queue_present',
              'refresh_mapping_limit': 'Present calls and sampled vblank counters alone do not identify the image scanned out at every refresh.'}
    if len(starts) != 1:
        errors.append(f'Expected one capture_start, found {len(starts)}')
        return result
    start = starts[0]
    own = [r for r in rows if r.get('_source') == start['_source']]
    in_request = [r for r in own if r.get('request') == request]
    presents = [r for r in in_request if event(r) == 'present'
                and r.get('armed', start['start_ns'] <= r['enter_ns'] < start['end_ns'])]
    ends = [r for r in in_request if event(r) == 'capture_interval_end']
    completions = [r for r in in_request if event(r) == 'capture_complete']
    saved = [r for r in in_request if event(r) == 'frame_saved']
    drops = [r for r in in_request if event(r) == 'pixel_drop']
    copies = [r for r in in_request if event(r) == 'copy_complete']
    present_keys = [(r['swapchain'], r['present']) for r in presents]
    saved_keys = [(r['swapchain'], r['present']) for r in saved]
    swaps = {r['swapchain']: r for r in own if event(r) == 'swapchain'}
    selected_ids = {r['swapchain'] for r in presents}
    selected_swaps = [swaps[k] for k in sorted(selected_ids) if k in swaps]
    if selected_ids - swaps.keys():
        errors.append('Missing surface metadata for captured presentations')
    for row in saved:
        surface = swaps.get(row['swapchain'], {})
        if any(row.get(k) != surface.get(k) for k in ('width', 'height', 'format')):
            errors.append(f"Frame {row['present']} dimensions/format disagree with swapchain")
    packed = {}
    for row in saved:
        if 'file_offset' in row:
            offset, size = row['file_offset'], row.get('compressed_bytes')
            if type(offset) is not int or type(size) is not int or offset < 0 or size <= 0:
                errors.append('Invalid packed-frame range')
                continue
            packed.setdefault(row['file'], []).append((offset, offset+size))
    for name, ranges in packed.items():
        ranges.sort()
        cursor = 0
        for begin, end in ranges:
            if begin != cursor:
                errors.append(f'{name}: packed frames overlap or leave an unexplained gap')
            cursor = end
        try:
            path = (directory/name).resolve(strict=True)
            if path.parent != directory or Path(name).name != name or path.stat().st_size != cursor:
                errors.append(f'{name}: packed file size/path disagrees with indexed frames')
        except OSError as error:
            errors.append(f'{name}: {error}')
    pixels = []
    if verify_pixels:
        for row in saved:
            name = row['file']
            try:
                raw = decode_frame(directory, row)
                # Alpha is not evidence of visible content.
                stride = max(1, row['width'] * row['height'] // 4096) * 4
                sample = [tuple(raw[i:i+3]) for i in range(0, len(raw), stride)]
                pixels.append({'present': row['present'], 'file': name,
                               'sha256': hashlib.sha256(raw).hexdigest(),
                               'nonblack_sample_fraction': sum(any(p) for p in sample) / len(sample),
                               'sample_unique_colors': len(set(sample))})
            except (OSError, ValueError, zlib.error, KeyError) as error:
                errors.append(f'{name}: {error}')
    successful = [r for r in presents if r.get('result') in (0, 1000001003)
                  and r.get('image_result', 0) in (0, 1000001003)]
    waits = [r for r in own if event(r) == 'wait_for_present'
             and r.get('driver_reports_present_complete') and r.get('result') == 0]
    wait_keys = {(r['swapchain'], r['present_id']) for r in waits}
    matched_waits = sum((r['swapchain'], r.get('present_id', 0)) in wait_keys
                        and r.get('present_id', 0) != 0 for r in presents)
    selected_present_ids = {(p['swapchain'], p.get('present_id')) for p in presents}
    selected_waits = [r for r in waits if (r['swapchain'], r['present_id']) in selected_present_ids]
    interval_waits = [r for r in own if event(r) == 'wait_for_present'
                      and start['start_ns'] <= r.get('begin_ns', -1) < start['end_ns']]
    counter_rows = sorted((r for r in selected_waits if r.get('vblank_sample_valid')),
                          key=lambda r: r.get('vblank_sample_begin_ns', r.get('return_ns', 0)))
    counter_steps = [b['vblank_sample']-a['vblank_sample'] for a, b in zip(counter_rows, counter_rows[1:])
                     if a['swapchain'] == b['swapchain']]
    direct_surfaces = {r['surface']: r for r in own if event(r) == 'direct_surface'}
    refresh_rates = {direct_surfaces.get(s.get('surface'), {}).get('refresh_millihz', 0)/1000 for s in selected_swaps}
    nominal_hz = next(iter(refresh_rates)) if len(refresh_rates) == 1 and 0 not in refresh_rates else None
    timestamps = sorted(r['enter_ns'] for r in presents)
    gaps = [(b-a)/1e6 for a, b in zip(timestamps, timestamps[1:])]
    counters_match = (len(completions) == 1 and completions[0].get('active_presents') == len(presents)
                      and completions[0].get('copied_frames') == len(presents)
                      and completions[0].get('saved') == len(saved)
                      and completions[0].get('pixel_drops') == 0
                      and completions[0].get('event_drops') == 0)
    deferred = any(r.get('deferred_pixel_writes') is True for r in own if event(r) == 'layer_start')
    writes_deferred = bool(saved) and all(r.get('write_begin_ns', -1) >= start['end_ns']
                                        and r.get('write_end_ns', -1) >= r['write_begin_ns'] for r in saved)
    if deferred and not writes_deferred:
        errors.append('Deferred pixel writes lack evidence that all writes began after recording ended')
    durable = any(r.get('durable_pixel_files') is True and r.get('pixel_mode', True)
                  for r in own if event(r) == 'layer_start')
    persistence_verified = bool(saved) and all(r.get('file_fdatasynced') is True
        and r.get('file_closed') is True for r in saved) and len(completions) == 1 \
        and completions[0].get('directory_synced') is True and completions[0].get('persistence_ok') is True
    if durable and not persistence_verified:
        errors.append('Durable capture lacks successful pixel-file and directory synchronization evidence')
    preparations = [r for r in in_request if event(r) == 'capture_preparing']
    drains = [r for r in in_request if event(r) == 'spool_drain_complete']
    storage_writes = list({r['file']: r for r in saved}.values())
    direct_io_advertised = any(r.get('archive_direct_io') is True for r in own if event(r) == 'layer_start')
    def direct_write_valid(row):
        memory, offset = row.get('direct_memory_alignment'), row.get('direct_offset_alignment')
        logical, physical, padding = (row.get(key) for key in ('written_bytes', 'physical_written_bytes', 'padding_bytes'))
        return (row.get('direct_io') is True and row.get('logical_truncate_succeeded') is True
                and all(type(v) is int and v > 0 for v in (memory, offset, logical, physical))
                and type(padding) is int and padding >= 0 and physical == logical+padding
                and physical % offset == 0 and logical == row.get('pack_bytes'))
    direct_io_verified = bool(saved) and all(direct_write_valid(r) for r in saved)
    if direct_io_advertised and not direct_io_verified:
        errors.append('Direct capture writes lack alignment, byte accounting or exact truncation evidence')
    result.update({
        'capture_interval_ended': len(ends) == 1,
        'capture_fully_drained': len(completions) == 1,
        'independent_counters_match': counters_match,
        'duration_seconds': (start['end_ns'] - start['start_ns']) / 1e9,
        'allocated_raw_bytes': start.get('allocated_raw_bytes'),
        'allocated_compressed_bytes': start.get('allocated_compressed_bytes'),
        'memory_reserve_bytes': preparations[0].get('memory_reserve_bytes') if len(preparations) == 1 else None,
        'deferred_pixel_writes_advertised': deferred,
        'bulk_writes_after_recording_verified': writes_deferred,
        'durable_pixel_files_advertised': durable,
        'pixel_file_persistence_verified': persistence_verified,
        'direct_disk_io_advertised': direct_io_advertised,
        'direct_disk_io_verified': direct_io_verified,
        'pixel_storage_file_count': len(storage_writes),
        'storage_write_timing_scope': 'one sample per storage file; packed frames share one write/sync',
        'preparation_seconds': (start['start_ns']-preparations[0]['begin_ns'])/1e9 if len(preparations) == 1 else None,
        'saving_seconds': (drains[0]['end_ns']-drains[0]['begin_ns'])/1e9 if len(drains) == 1 else None,
        'compressed_spool_bytes': completions[0].get('compressed_spool_bytes') if len(completions) == 1 else None,
        'present_count': len(presents), 'successful_present_count': len(successful),
        'saved_count': len(saved), 'drop_count': len(drops),
        'drop_reasons': dict(Counter(r.get('reason', 'unknown') for r in drops)),
        'missing_present_keys': sorted(set(present_keys) - set(saved_keys)),
        'unexpected_saved_keys': sorted(set(saved_keys) - set(present_keys)),
        'duplicate_saved_keys': [list(k) for k, n in Counter(saved_keys).items() if n > 1],
        'surfaces': selected_swaps,
        'direct_display_provenance': bool(selected_swaps) and len(selected_swaps) == len(selected_ids) and all(r.get('direct_display') and not r.get('test_surface') for r in selected_swaps),
        'headset_identity_verified': False,
        'matched_present_completion_waits': matched_waits,
        'sampled_vblank_increment_counts': dict(Counter(counter_steps)),
        'sampled_vblank_steps_all_one': bool(counter_steps) and all(step == 1 for step in counter_steps),
        'wait_metadata_skipped_in_interval': sum(bool(r.get('metadata_skipped')) for r in interval_waits),
        'nominal_refresh_rate_hz': nominal_hz,
        'nominal_refreshes_in_interval': nominal_hz * (start['end_ns']-start['start_ns'])/1e9 if nominal_hz else None,
        'present_gap_ms': distribution(gaps),
        'present_rate_hz': (len(timestamps)-1)*1e9/(timestamps[-1]-timestamps[0]) if len(timestamps)>1 and timestamps[-1]>timestamps[0] else None,
        'hook_before_driver_ms': distribution([r['hook_before_driver_ns']/1e6 for r in presents if 'hook_before_driver_ns' in r]),
        'copy_gpu_ms': distribution([r['copy_gpu_ns']/1e6 for r in copies if r.get('gpu_timestamp_valid')]),
        'copy_host_memcpy_ms': distribution([r['host_memcpy_ns']/1e6 for r in copies if 'host_memcpy_ns' in r]),
        'counter_query_after_wait_ms': distribution([(r['vblank_sample_end_ns'] - r['vblank_sample_begin_ns'])/1e6
            for r in selected_waits if r.get('vblank_sample_valid') and 'vblank_sample_begin_ns' in r]),
        'post_wait_observation_ms': distribution([(r['vblank_sample_end_ns'] - r['return_ns'])/1e6
            for r in selected_waits if 'vblank_sample_end_ns' in r and 'return_ns' in r]),
        'wait_hook_through_exit_sample_ms': distribution([r['layer_host_through_exit_sample_ns']/1e6
            for r in selected_waits if 'layer_host_through_exit_sample_ns' in r]),
        'wait_registry_lock_ms': distribution([r['registry_lock_wait_ns']/1e6
            for r in selected_waits if 'registry_lock_wait_ns' in r]),
        'counter_query_before_present_ms': distribution([r['counter_query_ns']/1e6 for r in presents if 'counter_query_ns' in r]),
        'compression_and_write_ms': distribution([r['compression_write_ns']/1e6 for r in saved if 'compression_write_ns' in r]),
        'compression_ms': distribution([r['compression_ns']/1e6 for r in saved if 'compression_ns' in r]),
        'disk_write_ms': distribution([r['disk_write_ns']/1e6 for r in storage_writes if 'disk_write_ns' in r]),
        'file_data_sync_ms': distribution([r['data_sync_ns']/1e6 for r in storage_writes if 'data_sync_ns' in r]),
        'storage_write_calls': sum(r.get('write_calls', 0) for r in storage_writes),
        'max_storage_write_request_bytes': max((r.get('write_max_requested_bytes', 0) for r in storage_writes), default=0),
        'physical_storage_bytes_written': sum(r.get('physical_written_bytes', 0) for r in storage_writes),
        'storage_padding_bytes_removed': sum(r.get('padding_bytes', 0) for r in storage_writes),
        'writer_pacing_seconds': sum(r.get('writer_pacing_ns', 0) for r in storage_writes)/1e9,
        'written_source_release_ms': sum(r.get('source_release_ns', 0) for r in storage_writes)/1e6,
        'discarded_copied_spool_bytes': sum(r.get('discarded_copied_spool_bytes', 0) for r in storage_writes),
        'compression_queue_ms': distribution([r['compression_queue_ns']/1e6 for r in saved if 'compression_queue_ns' in r]),
        'compressed_spool_memcpy_ms': distribution([r['spool_memcpy_ns']/1e6 for r in saved if 'spool_memcpy_ns' in r]),
        'compressed_bytes': sum(r.get('compressed_bytes', 0) for r in saved),
        'verified_pixels': len(pixels), 'pixel_evidence': pixels,
    })
    result['complete_present_capture'] = bool(
        presents and len(ends) == 1 and counters_match and not errors and not drops
        and len(present_keys) == len(set(present_keys))
        and len(saved_keys) == len(set(saved_keys))
        and len(successful) == len(presents)
        and Counter(present_keys) == Counter(saved_keys)
        and all(r.get('copied') for r in presents)
        and verify_pixels and len(pixels) == len(presents))
    return result


def compare_reports(baseline, capture):
    """Describe overhead; differing present modes/surfaces are not a valid A/B."""
    keys = ('width', 'height', 'format', 'mode', 'direct_display', 'test_surface')
    shape = lambda x: [{k: s.get(k) for k in keys} for s in x.get('surfaces', [])]
    same = bool(shape(baseline)) and shape(baseline) == shape(capture)
    a, b = baseline.get('present_rate_hz'), capture.get('present_rate_hz')
    return {'comparable_surface': same, 'baseline_present_rate_hz': a,
            'capture_present_rate_hz': b,
            'present_rate_change_percent': 100*(b-a)/a if same and a and b is not None else None,
            'capture_hook_before_driver_ms': capture.get('hook_before_driver_ms'),
            'capture_copy_gpu_ms': capture.get('copy_gpu_ms'),
            'negligible_overhead_verified': False,
            'limit': 'Requires paired same-workload runtime timing, repeated A/B windows, and resource-pressure checks; frame rate alone can hide lost GPU headroom.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--request', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit_directory(args.directory, args.request)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
