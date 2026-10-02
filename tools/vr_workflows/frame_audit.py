"""Summarize opt-in VR_FRAME_AUDIT records without conflating CPU wall time with GPU/FPS.

NADOC_VR_FRAME_AUDIT=1 enables the records for any existing VR tour or live viewer.
Use --intervals with [{name,start_ms,end_ms}] to exclude setup and captures.
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    def percentile(p):
        return values[max(0, math.ceil(len(values)*p)-1)]
    return dict(samples=len(values), p50=percentile(.5), p95=percentile(.95),
                p99=percentile(.99), maximum=values[-1])


def parse(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith('VR_FRAME_AUDIT '):
            continue
        try:
            fields = dict(item.split('=', 1) for item in line.split()[1:])
            row = {k: v if k in ('representation', 'tool') else float(v)
                   for k, v in fields.items()}
            required = ('epoch_ms','frame','representation','tool','period_ms','submitted','focused','total_ms','overflow')
            if any(k not in row for k in required) or any(not math.isfinite(v) for v in row.values() if isinstance(v,float)):
                continue
            rows.append(row)
        except (ValueError,TypeError):
            continue
    return rows


def summarize(rows, target_budget_ms=None):
    # Keep fallback/unfocused frames visible, but never count them as delivered FPS.
    eligible = [r for r in rows if r['submitted'] and r['focused']]
    phases = sorted({k for r in rows for k in r if k.endswith('_ms') and not k.startswith('calc_')}
                   - {'epoch_ms', 'period_ms', 'total_ms'})
    continuous = all(b['frame'] == a['frame']+1 for a,b in zip(eligible,eligible[1:]))
    gaps = [b['epoch_ms']-a['epoch_ms'] for a, b in zip(eligible, eligible[1:])] if continuous else []
    periods = [r['period_ms'] for r in eligible]
    runtime_waits=('xr_wait_ms','xr_sync_ms','xr_end_ms','swapchain_wait_ms')
    work=[max(0,r['total_ms']-sum(r.get(k,0) for k in runtime_waits)) for r in rows]
    return dict(continuous_frames=continuous, frames=len(rows), submitted_focused_frames=len(eligible),
                fallback_or_unfocused_frames=len(rows)-len(eligible),
                application_submission_fps=(1000*len(gaps)/sum(gaps)
                                            if gaps and sum(gaps)>0 else None),
                non_runtime_wait_wall_ms=distribution(work),
                non_runtime_wait_over_budget_frames=sum(w>r['period_ms'] for w,r in zip(work,rows)),
                target_budget_ms=target_budget_ms,
                non_runtime_wait_over_target_budget_frames=sum(w>target_budget_ms for w in work) if target_budget_ms is not None else None,
                submission_gaps_over_1_5_target_budget=sum(g>1.5*target_budget_ms for g in gaps) if target_budget_ms is not None and continuous else None,
                runtime_period_ms=distribution(periods), outer_wall_ms=distribution([r['total_ms'] for r in rows]),
                submission_gap_ms=distribution(gaps),
                submission_gaps_over_1_5_period=sum(g > 1.5*r['period_ms'] for g,r in zip(gaps,eligible[1:])),
                phase_wall_ms={k: distribution([r.get(k, 0) for r in rows]) for k in phases},
                calculation_inclusive_wall_ms={k: distribution([r.get(k, 0) for r in rows]) for k in sorted({k for r in rows for k in r if k.startswith('calc_') and k.endswith('_ms')})},
                calculation_active_frame_wall_ms={k: distribution([r[k] for r in rows if r.get(k.removesuffix('_ms')+'_calls',0)>0]) for k in sorted({k for r in rows for k in r if k.startswith('calc_') and k.endswith('_ms')})},
                phase_calls={k: sum(r.get(k, 0) for r in rows) for k in sorted({k for r in rows for k in r if k.endswith('_calls')})},
                phase_overflow=sum(r['overflow'] for r in rows))


def report(text, intervals=None, *, target_budget_ms=None):
    if target_budget_ms is not None and (not math.isfinite(target_budget_ms) or target_budget_ms<=0):
        raise ValueError('Target budget must be a finite positive number of milliseconds')
    rows = parse(text)
    malformed=sum(line.startswith('VR_FRAME_AUDIT ') for line in text.splitlines())-len(rows)
    groups = defaultdict(list)
    for row in rows:
        for interval in intervals or [dict(name='whole-run',start_ms=-math.inf,end_ms=math.inf)]:
            # Include only complete frames; captures at either boundary stay out.
            if interval['start_ms'] <= row['epoch_ms'] and row['epoch_ms']+row['total_ms'] <= interval['end_ms']:
                groups[(interval['name'],row['representation'],row['tool'])].append(row)
    return dict(malformed_records=malformed, valid=bool(rows) and not malformed and 'VR_TRACE_DROPPED ' not in text and not any(r['overflow'] for r in rows),
                trace_dropped='VR_TRACE_DROPPED ' in text,
                missing_intervals=[i['name'] for i in intervals or [] if not any(k[0]==i['name'] for k in groups)],
                limits='CPU wall phases include driver waits. Non-runtime-wait time subtracts only xrWaitFrame, xrSyncActions, xrEndFrame and swapchain acquisition/wait; it is not pure CPU execution or combined CPU+GPU cost. Calculation subscopes are inclusive and overlap phases; do not sum them. FPS estimates application cadence from outer-loop start timestamps of consecutive focused submitted frames, not headset scanout. Use compositor.jsonl for GPU/repeated/dropped evidence. Tool is frame-end mode; use explicit operation intervals. Clock/scope overhead is included. Final audit record formatting/enqueue is outside timed phases but affects submission cadence; these are instrumented-run results.',
                cases=[dict(interval=k[0], representation=k[1], tool=k[2], **summarize(v,target_budget_ms)) for k,v in groups.items()])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--intervals', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target-hz',type=float,help='Fixed refresh target, independent of adaptive OpenXR pacing')
    args = parser.parse_args()
    if args.target_hz is not None and (not math.isfinite(args.target_hz) or args.target_hz<=0):parser.error('Target Hz must be finite and positive')
    result = report(args.log.read_text(), json.loads(args.intervals.read_text()) if args.intervals else None,
                    target_budget_ms=1000/args.target_hz if args.target_hz else None)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    if not result['valid'] or result['missing_intervals']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
