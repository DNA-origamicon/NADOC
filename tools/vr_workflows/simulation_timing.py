"""Summarize real compositor and native timings over recorded simulation intervals.

Input/controller/capture intervals are retained separately from quiet playback.
This reports missed delivery honestly; it does not infer 90 Hz from CPU averages.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def distribution(values):
    if not values:
        return None
    return dict(zip(('p50', 'p95', 'p99', 'maximum'),
                    map(float, np.percentile(values, [50, 95, 99, 100]))))


def summarize(directory):
    compositor = [json.loads(line) for line in (directory / 'compositor.jsonl').read_text().splitlines()]
    intervals = [json.loads(line) for line in (directory / 'intervals.jsonl').read_text().splitlines()]
    start = min((i['start_ms'] for i in intervals), default=0)
    end = max((i['end_ms'] for i in intervals), default=0)
    frames = []
    with (directory / 'viewer.log').open() as stream:
        for line in stream:
            if line.startswith('VR_FRAME_AUDIT '):
                epoch = float(line.split('epoch_ms=', 1)[1].split()[0])
                if not start <= epoch <= end:
                    continue
                values = {}
                for item in line.split()[1:]:
                    if '=' not in item:
                        continue
                    key, value = item.split('=', 1)
                    try:
                        values[key] = float(value)
                    except ValueError:
                        pass
                frames.append(values)
    result = []
    for interval in intervals:
        start, end = interval['start_ms'], interval['end_ms']
        c = [r for r in compositor if start <= r['sample_wall_time_ms'] <= end]
        f = [r for r in frames if start <= r['epoch_ms'] <= end]
        result.append({**interval, 'seconds': (end-start)/1000,
            'compositor_frames': len(c), 'native_frames': len(f),
            'display_hz': sorted({r['hmd_display_hz'] for r in c}),
            'dropped_frames': sum(r['m_nNumDroppedFrames'] for r in c),
            'reprojected_frames': sum(bool(r['m_nReprojectionFlags']) for r in c),
            'gpu_ms': distribution([r['m_flTotalRenderGpuMs'] for r in c]),
            'cpu_without_runtime_wait_ms': distribution([max(0, r['total_ms']-r.get('xr_wait_ms',0)-r.get('xr_end_ms',0)) for r in f]),
            'scene_feed_ms': distribution([r.get('feeds_view_tools_ms',0) for r in f]),
            'frame_interval_ms': distribution([b['epoch_ms']-a['epoch_ms'] for a,b in zip(f,f[1:])]),
        })
    return {'timing_basis': 'Compositor sampling wall time (~100 ms bins); native frame start epoch. Capture/input intervals include diagnostic overhead.', 'intervals': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = summarize(args.directory)
    (args.directory / 'timing-summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
