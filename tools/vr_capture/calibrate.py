"""Repeated quiet/recording windows with independent SteamVR timing.

Run with ``uv run --no-project --with openvr python -m tools.vr_capture.calibrate``.
Never changes the scene, tracking, runtime settings, or capture installation.
Quiet windows retain the loaded layer's telemetry cost. A --baseline-only run
without a loaded layer is needed to estimate that separate fixed cost.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import json
import os
from pathlib import Path
import queue
import threading
import time

from .audit import audit_directory, distribution
from .viewer_record import record, locate_layer, process_is_compositor
from tools.vr_workflows.audit_runtime import resources, pressure


METRICS = ('m_flTotalRenderGpuMs', 'm_flCompositorRenderGpuMs',
           'm_flCompositorRenderCpuMs', 'm_flPresentCallCpuMs',
           'm_flWaitForPresentCpuMs', 'm_flClientFrameIntervalMs')


def process_resources(pid):
    if pid is None:
        return None
    proc = Path('/proc')/str(pid)
    try:
        fields = (proc/'stat').read_text().rsplit(')', 1)[1].split()
        status = dict(line.split(':', 1) for line in (proc/'status').read_text().splitlines() if ':' in line)
        return {'pid': pid, 'sample_monotonic_ns': time.monotonic_ns(), 'start_ticks': fields[19],
                'cpu_seconds': (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'),
                'minor_faults': int(fields[7]), 'major_faults': int(fields[9]),
                'rss_kib': int(status['VmRSS'].split()[0]), 'high_water_rss_kib': int(status['VmHWM'].split()[0])}
    except (OSError, ValueError, KeyError, IndexError) as error:
        return {'pid': pid, 'error': str(error)}


def capture_resources():
    begin = time.monotonic_ns()
    result = resources()
    result['sample_monotonic_ns'] = time.monotonic_ns()
    vm = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
    result['vm_counters'] = {key: int(value) for key, value in vm.items()
                             if key.startswith(('allocstall_', 'pgscan_direct', 'pgsteal_direct', 'compact_stall', 'pgmajfault'))}
    result['pressure_total_us'] = {}
    for kind in ('cpu', 'io', 'memory'):
        for line in Path('/proc/pressure', kind).read_text().splitlines():
            fields = line.split()
            total = dict(field.split('=') for field in fields[1:])['total']
            result['pressure_total_us'][kind+'_'+fields[0]] = int(total)
    result.update(snapshot_begin_ns=begin, snapshot_end_ns=time.monotonic_ns())
    return result


def summarize(rows):
    rows = sorted(rows, key=lambda r: r['m_nFrameIndex'])
    duration = (rows[-1]['m_flSystemTimeInSeconds'] - rows[0]['m_flSystemTimeInSeconds']) if len(rows)>1 else 0
    return {'unique_application_frames': len(rows),
            'application_rate_hz': (len(rows)-1)/duration if duration>0 else None,
            'present_counts': dict(Counter(r['m_nNumFramePresents'] for r in rows)),
            'reprojection_flags': dict(Counter(r['m_nReprojectionFlags'] for r in rows)),
            'mis_presented': sum(r['m_nNumMisPresented'] for r in rows),
            'dropped': sum(r['m_nNumDroppedFrames'] for r in rows),
            **{key: distribution([r[key] for r in rows]) for key in METRICS}}


def run(output, directory=None, seconds=5, repetitions=2, compositor_pid=None):
    import openvr
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if directory:
        compositor_pid = locate_layer(Path(directory))[1]['pid']
    report = {'schema': 1, 'directory': str(directory) if directory else None,
              'phase_seconds': seconds, 'boundary_exclusion_seconds': .3,
              'quiet_includes_layer_telemetry': True if directory else None,
              'baseline_layer_absence_requires_launch_provenance': directory is None,
              'newest_application_frames_excluded': 3,
              'compositor_pid': compositor_pid,
              'physical_motion_reproduced': False, 'negligible_overhead_verified': False,
              'limitations': ['Stationary scene; does not reproduce upper-body rotation.',
                              'Timing membership uses poll timestamps; 0.3 s excluded at each boundary.',
                              'Resource intervals use their actual sample timestamps; active entry follows ACK and active exit may overlap initial saving.',
                              'Post-save quiet phases may include delayed kernel writeback; inspect their IO/reclaim counters before treating them as unaffected baselines.',
                              'Application and compositor GPU timing may exclude the injected readback; see layer GPU timestamps.',
                              'Quiet/capture comparison measures incremental recording cost, not all layer overhead.'],
              'phases': []}
    timing_rows = []
    openvr.init(openvr.VRApplication_Background)
    try:
        report['dashboard_visible'] = bool(openvr.VROverlay().isDashboardVisible())
        if report['dashboard_visible']:
            raise RuntimeError('SteamVR dashboard obscures scene; close it before calibration')
        compositor = openvr.VRCompositor()
        frames = (openvr.Compositor_FrameTiming * 128)()
        frames[0].m_nSize = ctypes.sizeof(openvr.Compositor_FrameTiming)
        count, values = compositor.getFrameTimings(frames)
        previous = max((f.m_nFrameIndex for f in values[:count]), default=-1)
        schedule = ['quiet'] if directory is None else ['quiet', 'pixels'] * repetitions + ['quiet']
        for index, kind in enumerate(schedule):
            if compositor_pid is not None and not process_is_compositor(compositor_pid):
                raise RuntimeError('Measured compositor exited; later timing is not comparable')
            phase = {'index': index, 'kind': kind}
            report['phases'].append(phase)
            phase['pre_request'] = {'resources': capture_resources(), 'process': process_resources(compositor_pid)}
            worker = None
            if kind == 'pixels':
                updates, outcome = queue.Queue(), {}
                def capture():
                    outcome.update(record(Path(directory), updates.put, seconds=seconds, delay=0))
                worker = threading.Thread(target=capture)
                worker.start()
                while True:
                    update = updates.get(timeout=20)
                    if update['phase'] == 'error':
                        worker.join()
                        raise RuntimeError(update['status'])
                    if update['phase'] == 'recording':
                        request = json.loads((Path(directory)/f"viewer-request-{update['request']}.json").read_text())
                        phase['request'] = {'token': update['request'], 'status': 'acknowledged'}
                        start = request['acknowledged_start']
                        begin, end = start['start_ns'], start['end_ns']
                        break
            else:
                begin = time.monotonic_ns()
                end = begin + int(seconds*1e9)
            phase.update(begin_ns=begin, end_ns=end, resources_before=capture_resources(),
                         process_before=process_resources(compositor_pid))
            rows = []
            while time.monotonic_ns() < end:
                if compositor_pid is not None and not process_is_compositor(compositor_pid):
                    raise RuntimeError('Measured compositor exited during timing window')
                count, values = compositor.getFrameTimings(frames)
                now = time.monotonic_ns()
                finalized = max((f.m_nFrameIndex for f in values[:count]), default=-1) - 3
                for f in values[:count]:
                    if f.m_nFrameIndex <= previous or f.m_nFrameIndex > finalized:
                        continue
                    previous = f.m_nFrameIndex
                    row = {k: getattr(f, k) for k, _ in f._fields_ if k != 'm_HmdPose'}
                    row.update(phase=index, kind=kind, sample_monotonic_ns=now)
                    timing_rows.append(row)
                    if begin+300_000_000 <= now <= end-300_000_000:
                        rows.append(row)
                time.sleep(.1)
            phase.update(resources_after=capture_resources(), process_after=process_resources(compositor_pid), timing=summarize(rows))
            phase['resource_pressure'] = pressure(phase['resources_before'], phase['resources_after'])
            for field in ('vm_counters', 'pressure_total_us'):
                phase['resource_pressure'][field] = {key: value-phase['resources_before'][field][key]
                    for key, value in phase['resources_after'][field].items()}
            print(json.dumps({'phase': index, 'kind': kind, 'rate': phase['timing']['application_rate_hz']}), flush=True)
            if worker:
                worker.join(timeout=65)
                if worker.is_alive():
                    raise RuntimeError('Recording helper failed to drain within its deadline')
                phase['recording_status'] = outcome['status']
                phase['acknowledged_and_drained'] = bool(outcome.get('acknowledged_start') and outcome.get('completion'))
                if outcome['status'] != 'saved' or not phase['acknowledged_and_drained']:
                    raise RuntimeError('Recording failed; stopping calibration: ' + outcome.get('error', outcome['status']))
                phase['post_drain'] = {'resources': capture_resources(), 'process': process_resources(compositor_pid)}
            # Saving has completed before the following quiet baseline transition.
            time.sleep(2)
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        openvr.shutdown()
        with (output/'timing.jsonl').open('x') as stream:
            for row in timing_rows:
                stream.write(json.dumps(row)+'\n')
        (output/'calibration.json').write_text(json.dumps(report, indent=2)+'\n')
    for phase in report['phases']:
        if 'request' in phase:
            capture = audit_directory(Path(directory), phase['request']['token'])
            name = f"capture-{phase['index']}.json"
            (output/name).write_text(json.dumps(capture, indent=2)+'\n')
            phase['capture_audit'] = name
            phase['complete_present_capture'] = capture['complete_present_capture']
    report['status'] = ('measured' if all(p.get('complete_present_capture', True)
                        and p.get('acknowledged_and_drained', True) for p in report['phases'])
                        else 'incomplete_capture')
    (output/'calibration.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--compositor-pid', type=int, help='Optional process-cost evidence for a baseline run')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--repetitions', type=int, default=2)
    args = parser.parse_args()
    if not 2 <= args.seconds <= 10 or not 1 <= args.repetitions <= 5:
        parser.error('seconds must be 2..10; repetitions must be 1..5')
    if args.baseline_only == bool(args.directory):
        parser.error('choose either --baseline-only or --directory')
    run(args.output, args.directory, args.seconds, args.repetitions, args.compositor_pid)


if __name__ == '__main__':
    main()
