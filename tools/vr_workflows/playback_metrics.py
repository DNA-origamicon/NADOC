"""Summarize exact-frame delivery separately from submitted headset cadence."""
import argparse
import json
import math
from pathlib import Path
import re


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return {'count': len(values), 'p50': values[len(values)//2],
            'p95': values[min(len(values)-1, int(len(values)*.95))],
            'max': values[-1]}


def records(text, prefix):
    return [dict(re.findall(r'(\w+)=([^ ]+)', line))
            for original in text.splitlines() if (offset := original.find(prefix+' ')) >= 0
            for line in [original[offset:]]]


def numeric_records(text, prefix, fields):
    rows = records(text, prefix)
    valid, bad = [], []
    for index, row in enumerate(rows):
        try:
            if not all(math.isfinite(float(row[key])) for key in fields): raise ValueError('nonfinite')
        except (KeyError, ValueError): bad.append(index)
        else: valid.append((index, row))
    intervals = []
    if 'epoch_ms' in fields:
        for index in bad:
            before = [float(r['epoch_ms']) for i,r in valid if i<index]
            after = [float(r['epoch_ms']) for i,r in valid if i>index]
            intervals.append((before[-1] if before else -math.inf, after[0] if after else math.inf))
    return [r for _,r in valid], len(bad), intervals


def summarize(directory):
    directory = Path(directory)
    text = (directory/'viewer.log').read_text() if (directory/'viewer.log').exists() else ''
    frames, bad_frames, intervals = numeric_records(text, 'VR_FRAME_AUDIT', ('frame','epoch_ms','total_ms'))
    gpu_rows, bad_gpu, _ = numeric_records(text, 'VR_GPU_PASS', ('frame','total_ns','view_tools_version'))
    gpu = {r['frame']: r for r in gpu_rows if r.get('valid') == '1'}
    native, bad_native, _ = numeric_records(text, 'VR_VIEW_PIPELINE_NATIVE', ('epoch_ms','read_parse_ms','upload_ms'))
    result = []
    for window in json.loads((directory/'windows.json').read_text()):
        if window['name'] != 'play':
            continue
        selected = [r for r in frames if window['start'] <= float(r['epoch_ms']) <= window['end'] and r.get('submitted') == '1']
        firsts = []; previous = None
        for frame in selected:
            version = gpu.get(frame['frame'], {}).get('view_tools_version')
            if version is not None and version != previous:
                firsts.append(float(frame['epoch_ms'])); previous = version
        gaps = [b-a for a, b in zip(firsts, firsts[1:])]
        rows = [r for r in native if window['start'] <= float(r['epoch_ms']) <= window['end']]
        pipeline = directory/f"{window['representation']}-{str(window['smooth']).lower()}-pipeline.json"
        events = json.loads(pipeline.read_text())['events'] if pipeline.exists() else []
        stages = {}
        for name in ('capture', 'encode', 'upload', 'apply'):
            spans = []; start = None
            for event in events:
                if event['stage'] == name+'_start':
                    start = event['epoch_ms']
                elif event['stage'] == name+'_end' and start is not None:
                    spans.append(event['epoch_ms']-start); start = None
            stages[name+'_ms'] = distribution(spans)
        malformed_in_window = sum(start <= window['end'] and end >= window['start'] for start,end in intervals)
        missing = sum(r['frame'] not in gpu for r in selected)
        boundary_gaps = ([firsts[0] - window['start'], window['end'] - firsts[-1]] if firsts else [window['end'] - window['start']])
        result.append({**window, 'submitted_scene_gap_ms': distribution(gaps),
                       'scene_gaps_over_125ms': sum(g > 125 for g in gaps),
                       'scene_window_max_gap_ms': max(gaps + boundary_gaps),
                       'malformed_records': {'frames':bad_frames,'gpu':bad_gpu,'native':bad_native},
                       'malformed_frames_in_window': malformed_in_window,
                       'scene_cadence_pass': bool(gaps) and malformed_in_window == 0 and missing == 0 and max(gaps + boundary_gaps) <= 125,
                       'gpu_missing_frames': missing,
                       'native_frame_ms': distribution([float(r['total_ms']) for r in selected]),
                       'native_frames_over_16_67ms': sum(float(r['total_ms']) > 1000/60 for r in selected),
                       'gpu_ms': distribution([float(gpu[r['frame']]['total_ns'])/1e6 for r in selected if r['frame'] in gpu]),
                       'native_transform_packets': sum(r.get('transforms')=='1' for r in rows),
                       'wire_bytes': distribution([e['bytes'] for e in events if e['stage']=='upload_start']),
                       'browser_transform_packets': sum(e.get('transforms',False) for e in events if e['stage']=='upload_start'),
                       'parse_ms': distribution([float(r['read_parse_ms']) for r in rows]),
                       'upload_gl_ms': distribution([float(r['upload_ms']) for r in rows]),
                       'long_tasks_ms': [e['duration_ms'] for e in events if e['stage'] == 'longtask'], **stages})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    results = {str(p.parent.relative_to(args.directory)): summarize(p.parent)
               for p in args.directory.rglob('windows.json')}
    (args.directory/'metrics.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
