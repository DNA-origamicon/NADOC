"""Summarize complete loading intervals, including work outside renderFrame."""
import argparse
import json
import re
from pathlib import Path


def summarize(run, compositor=None):
    results = json.loads((run / 'native/results.json').read_text())
    traces = []
    log = (run / 'native-viewer.log').read_text()
    # The backend log appends across launches. Scope cadence to this viewer,
    # not a previous headset/session that may have had a faster refresh rate.
    log = log.rsplit('NADOC VR viewer ready.', 1)[-1]
    periods = re.findall(r'runtime_period_ms=([0-9.]+)', log)
    # Predicted periods may lengthen under reprojection; that must not turn a
    # half-rate application into a passing 45 Hz result on a 90 Hz runtime.
    period = min((float(value) for value in periods if float(value)>0), default=1000/90)
    for line in log.splitlines():
        if not line.startswith(('VR_LOAD_TRACE ', 'VR_RENDER_TRACE ', 'VR_UPLOAD_TRACE ', 'VR_GPU_TRACE ', 'VR_TRACE_DROPPED ')):
            continue
        row = dict(re.findall(r'(\w+)=([^\s]+)', line))
        try:
            row['epoch_ms'] = float(row['epoch_ms'])
            for key in ('cpu_wall_ms', 'frame_gap_ms', 'percent', 'gpu_ms', 'ids_ms', 'driver_ms'):
                if key in row:
                    row[key] = float(row[key])
        except (KeyError, ValueError):
            continue  # A worker log may interleave; never fabricate a timing sample.
        row['kind'] = line.split()[0]
        traces.append(row)
    compositor_rows = []
    if compositor and compositor.exists():
        compositor_rows = [json.loads(line) for line in compositor.read_text().splitlines()]
    reports = []
    for result in results:
        samples = result['samples']
        first, last = samples[0]['wall_time_ms'], samples[-1]['wall_time_ms']
        selected = [row for row in traces if first <= row['epoch_ms'] <= last]
        frames = [row for row in selected if row['kind'] == 'VR_LOAD_TRACE' and row.get('stage') == 'frame']
        bands = {}
        for name, low, high in [('whole_load', 0, 100), ('40_to_50', 40, 50), ('activation', 96, 100)]:
            gaps = sorted(row['frame_gap_ms'] for row in frames if low <= row.get('percent', -1) <= high)
            bands[name] = dict(samples=len(gaps), max_ms=max(gaps, default=None),
                               p99_ms=gaps[min(len(gaps)-1, int(len(gaps)*.99))] if gaps else None,
                               over_22ms=sum(value > period*2 for value in gaps))
        cpu = {}
        for row in selected:
            if 'cpu_wall_ms' in row and row.get('stage') != 'frame':
                key = row['kind'] + ':' + row['stage']
                cpu[key] = max(cpu.get(key, 0), row['cpu_wall_ms'])
        comp = [row for row in compositor_rows if first <= row['sample_wall_time_ms'] <= last]
        reports.append(dict(target=result['target'], preset=result['preset'], start_ms=first, end_ms=last,
                            bands=bands, cpu_phase_max_ms=cpu,
                            trace_dropped=sum(int(row.get('count', 0)) for row in selected if row['kind'] == 'VR_TRACE_DROPPED'),
                            slow_frames=[row for row in frames if row['frame_gap_ms'] > period*2],
                            compositor=dict(samples=len(comp), dropped=sum(row['m_nNumDroppedFrames'] for row in comp),
                                            mispresented=sum(row['m_nNumMisPresented'] for row in comp),
                                            reprojection_flagged=sum(bool(row['m_nReprojectionFlags']) for row in comp))))
    return dict(runtime_hz=1000/period, note='CPU wall times; compositor interval membership uses polling timestamps (up to 100 ms boundary uncertainty). No captures inside loading intervals. Warm immediate switches may have too few frames for timing acceptance.', reports=reports)


def acceptance_failures(report):
    """Engineering regression limits, not a guarantee of physical comfort.

    p99 allows 20% cadence jitter; maximum allows three runtime intervals. At
    most 0.1% compositor drops. Immediate warm switches use functional assertions
    because a handful of samples cannot estimate a meaningful percentile.
    """
    failures = []
    period = 1000/report['runtime_hz']
    for item in report['reports']:
        band = item['bands']['whole_load']
        label = item['target']+'/'+item['preset']
        if item.get('trace_dropped', 0):
            failures.append(label+' trace samples lost')
        if band['samples'] < 30:
            if item.get('end_ms', 0)-item.get('start_ms', 0) > period*30:
                failures.append(label+' insufficient frame timing for measured loading duration')
            continue
        if band['p99_ms'] > period*1.2:
            failures.append(label+' p99 exceeds 1.2 frame periods')
        if band['max_ms'] > period*3:
            failures.append(label+' maximum exceeds 3 frame periods')
        compositor = item['compositor']
        if not compositor['samples']:
            failures.append(label+' missing compositor timing')
        elif compositor['dropped']/compositor['samples'] > .001:
            failures.append(label+' compositor drops exceed 0.1%')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--compositor', type=Path)
    args = parser.parse_args()
    report = summarize(args.run, args.compositor)
    (args.run / 'loading-profile.json').write_text(json.dumps(report, indent=2))
    for item in report['reports']:
        print(item['target'], item['preset'], json.dumps(item['bands']), json.dumps(item['compositor']))


if __name__ == '__main__':
    main()
