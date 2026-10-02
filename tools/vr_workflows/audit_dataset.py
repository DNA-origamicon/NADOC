"""Export recorded VR audit campaigns as reviewable CSV tables and a JSON index.

Never turn a failed workflow into a pass because some frames were recorded.
Missing measurements remain empty; setup, stationary, reaches and commits retain
their own interval labels. Run after live measurement to avoid competing work.
"""
import argparse
import csv
import hashlib
import json
import re
import math
import shutil
from pathlib import Path


LATENCY_DEFINITIONS={
    'move-commit':'Trigger release through observed commit acknowledgement',
    'ligation-commit':'Trigger release through observed scene and ligation revision update',
    'end_resize-commit':'Trigger release through observed scene and end-resize revision update',
    'bend-commit':'Confirm-control acquisition/click and subsequent acknowledgement wait; includes nested reach',
    'twist-commit':'Confirm-control acquisition/click and subsequent acknowledgement wait; includes nested reach',
    'nick-feedback':'Acknowledgement wait after trigger input and its initial frame observation',
    'stationary-after-representation':'Deliberate stationary observation interval without continuous observer requests',
    'stationary-observed':'Deliberate stationary interval with continuous frame observation requests',
}


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def table(path, rows):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def flatten_distribution(row, prefix, value):
    for key in ('samples','p50','p95','p99','maximum'):
        row[prefix+'_'+key]=value.get(key) if value else None


def exit_record_in_tail(path):
    if not path.exists():return None
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-65536))
        return b'VR_METRIC event=process_end mode=openxr_viewer' in stream.read()


def failure_details(path, fallback):
    if not path.exists():return fallback
    lines=[re.sub(r'\x1b\[[0-9;]*m','',line).strip() for line in path.read_text(errors='replace').splitlines()]
    failures=[]
    for i,line in enumerate(lines):
        if re.match(r'^(?:[\w.]*Error|[\w.]*Exception|StopIteration)\b',line):
            if line=='AssertionError':
                assertion=next((previous for previous in reversed(lines[max(0,i-4):i]) if previous.startswith('assert ')),None)
                if assertion:line+=': '+assertion
            if line.startswith('Error: expect('):
                values=[following for following in lines[i+1:i+12]
                        if following.startswith(('Expected:','Received:'))]
                if values:line+='; '+'; '.join(values)
            failures.append(line)
    return failures[-5:] or fallback


def add_target_budget(reports, log, bounds, budget_ms):
    """Count fixed-budget misses from raw frames without replacing old reports.

    OpenXR's predicted period can be throttled to 22/44 ms on a 90 Hz headset.
    Keep that adaptive period, but never use it as the fixed benchmark budget.
    """
    if budget_ms is None:return
    if not math.isfinite(budget_ms) or budget_ms<=0:raise ValueError('Invalid target budget')
    targets={}
    windows={b['name']:(b['start_ms'],b['end_ms']) for b in bounds}
    windows['whole-run']=(-math.inf,math.inf)
    for report in reports:
        for case in report.get('cases',[]):
            if (case.get('target_budget_ms')==budget_ms and
                    case.get('non_runtime_wait_over_target_budget_frames') is not None and
                    'submission_gaps_over_1_5_target_budget' in case):
                continue  # The controlled runner already computed this target.
            case.update(target_budget_ms=budget_ms,non_runtime_wait_over_target_budget_frames=None,
                        submission_gaps_over_1_5_target_budget=None)
            if case['interval'] in windows:
                targets[(case['interval'],case['representation'],case['tool'])]=dict(case=case,count=0,over=0,gaps=0,previous=None,continuous=True)
    if not targets or not log.exists():return
    needed=re.compile(r'\b(epoch_ms|frame|representation|tool|total_ms|submitted|focused|xr_wait_ms|xr_sync_ms|xr_end_ms|swapchain_wait_ms)=(\S+)')
    with log.open(errors='replace') as stream:
        for line in stream:
            if not line.startswith('VR_FRAME_AUDIT '):continue
            raw=dict(needed.findall(line))
            try:
                r={k:v if k in ('representation','tool') else float(v) for k,v in raw.items()}
                start=r['epoch_ms'];end=start+r['total_ms'];frame=r['frame']
                rep=r['representation'];tool=r['tool'];eligible=r['submitted'] and r['focused']
                work=max(0,r['total_ms']-sum(r.get(k,0) for k in ('xr_wait_ms','xr_sync_ms','xr_end_ms','swapchain_wait_ms')))
            except (ValueError,KeyError):continue
            for name,(low,high) in windows.items():
                counter=targets.get((name,rep,tool))
                if counter is None or not low<=start or not end<=high:continue
                counter['count']+=1;counter['over']+=work>budget_ms
                if eligible:
                    previous=counter['previous']
                    if previous:
                        if frame!=previous[0]+1:counter['continuous']=False
                        counter['gaps']+=start-previous[1]>1.5*budget_ms
                    counter['previous']=(frame,start)
    for counter in targets.values():
        case=counter['case']
        if counter['count']==case['frames']:
            case['non_runtime_wait_over_target_budget_frames']=counter['over']
            case['submission_gaps_over_1_5_target_budget']=counter['gaps'] if counter['continuous'] else None


def collect(campaigns, baseline=None, inventory=(), target_budget_ms=None):
    runs=[];intervals=[];calculations=[];phases=[];operations=[]
    sessions=[];session_calculations=[];session_phases=[]
    for campaign in campaigns:
        matrix=read(campaign/'matrix.json',{})
        for result in matrix.get('results',[]):
            suffix='-'+result['profile'] if matrix.get('validation') and result.get('profile') else ''
            directory=campaign/(result['tool']+'-'+result['representation']+suffix)
            audit=read(directory/'frame-audit.json',{})
            proof_paths=list(directory.rglob('audit-design.json'))
            proofs=[read(p) for p in proof_paths]
            base=dict(campaign=str(campaign),case=directory.name,tool=result['tool'],
                      profile=result.get('profile','steady_fast'),requested_representation=result['representation'],
                      workflow_passed=result.get('tour_exit_code')==0 if result.get('tour_exit_code') is not None else result['passed'],
                      audit_passed=result['passed'],trace_valid=audit.get('valid'))
            source=matrix.get('source') or {}
            host=read(directory/'host-resources.json',{})
            host_fields={f'host_{boundary}_{key}':value for boundary in ('before','after','delta')
                         for key,value in host.get(boundary,{}).items()}
            bounds=[json.loads(line) for line in (directory/'reaches.jsonl').read_text().splitlines()] if (directory/'reaches.jsonl').exists() else []
            session=read(directory/'session-frame-audit.json',{})
            add_target_budget([audit,session],directory/'viewer.log',bounds,target_budget_ms)
            runs.append(dict(**base,**host_fields,source_sha256=source.get('sha256') or next((p.get('sha256') for p in proofs if p.get('sha256')),None),
                tour_exit_code=result.get('tour_exit_code'),
                native_exit_record_in_log_tail=exit_record_in_tail(directory/'viewer.log'),
                source_proofs=json.dumps([str(p) for p in proof_paths]),
                loaded_helices=next((p.get('helices') for p in proofs if p.get('helices')),None),
                loaded_nucleotides=next((p.get('nucleotides') for p in proofs if p.get('nucleotides')),None),
                requested_representation_frame_rows=sum(c['frames'] for c in audit.get('cases',[]) if c['representation']==result['representation']),
                recorded_kinds=json.dumps(sorted({b.get('kind','reach') for b in bounds})),
                reached_commit_intervals=sum(b.get('kind','').endswith('-commit') for b in bounds),
                recorded_intervals=result.get('reach_intervals'),missing_intervals=json.dumps(audit.get('missing_intervals',[])),
                failure=json.dumps(failure_details(directory/'tour.log',result.get('failure_excerpt',[]))),error=result.get('error'),
                tour_log=str(directory/'tour.log'),frame_log=str(directory/'viewer.log')))
            bound_by_name={b['name']:b for b in bounds}
            comp={c['name']:c for c in read(directory/'compositor-summary.json',{}).get('cases',[])}
            for b in bounds:
                if 'operation_latency_ms' in b:
                    operations.append(dict(**base,interval=b['name'],kind=b['kind'],observed_representation=b.get('representation'),latency_ms=b['operation_latency_ms'],
                                           latency_definition=LATENCY_DEFINITIONS.get(b['kind'],'See named operation in probe source'),error=b.get('error')))
            append_cases(audit,base,bound_by_name,comp,intervals,calculations,phases,inventory)
            session_base={**base,'trace_valid':session.get('valid'),'workload':'whole owned session INCLUDING captures, setup, waits and commits'}
            append_cases(session,session_base,{}, {},sessions,session_calculations,session_phases,inventory)
    if baseline:
        audit=read(baseline/'frame-audit.json',{})
        bounds={b['name']:b for b in read(baseline/'intervals.json',[])}
        add_target_budget([audit],baseline/'viewer.log',list(bounds.values()),target_budget_ms)
        comp={c['name']:c for c in read(baseline/'compositor-summary.json',{}).get('cases',[])}
        base=dict(campaign=str(baseline),case='baseline',tool='idle/whole-model-grip',profile='encoded in interval',
                  requested_representation='encoded in interval',workflow_passed=audit.get('passed'),audit_passed=audit.get('passed'),trace_valid=audit.get('valid'))
        append_cases(audit,base,bounds,comp,intervals,calculations,phases,inventory)
    # Campaigns are supplied chronologically. Select the latest attempt, never
    # silently select the passing attempt, while retaining all attempts above.
    grouped={}
    for run in runs:
        key=(run['tool'],run['requested_representation'],run['profile'])
        grouped.setdefault(key,[]).append(run)
    coverage=[dict(tool=key[0],representation=key[1],profile=key[2],attempts=len(attempts),
                   latest_campaign=attempts[-1]['campaign'],latest_case=attempts[-1]['case'],
                   latest_workflow_passed=attempts[-1]['workflow_passed'],
                   latest_audit_passed=attempts[-1]['audit_passed'],
                   any_attempt_passed=any(r['workflow_passed'] for r in attempts),
                   latest_trace_valid=attempts[-1]['trace_valid'],
                   latest_requested_representation_frame_rows=attempts[-1]['requested_representation_frame_rows'],
                   latest_reached_commit_intervals=attempts[-1]['reached_commit_intervals'],
                   latest_failure=attempts[-1]['failure']) for key,attempts in sorted(grouped.items())]
    return dict(runs=runs,coverage=coverage,intervals=intervals,calculations=calculations,phases=phases,operations=operations,
                sessions=sessions,session_calculations=session_calculations,session_phases=session_phases)


def append_cases(audit,base,bounds,compositor,intervals,calculations,phases,inventory=()):
    for case in audit.get('cases',[]):
        name=case['interval'];bound=bounds.get(name,{})
        shared=dict(**base,interval=name,representation=case['representation'],native_tool=case['tool'])
        row=dict(**shared,interval_kind=bound.get('kind','reach' if name.startswith('reach-') else 'baseline/setup'),
                 interval_error=bound.get('error'),start_ms=bound.get('start_ms'),end_ms=bound.get('end_ms'))
        for boundary in ('start','end'):
            for key in ('scene_override','view_tools_version','view_tools_flags','observed_frame'):
                row[key+'_'+boundary]=bound.get('display_'+boundary,{}).get(key)
        for key in ('frames','submitted_focused_frames','fallback_or_unfocused_frames','application_submission_fps',
                    'continuous_frames',
                    'target_budget_ms','non_runtime_wait_over_target_budget_frames','submission_gaps_over_1_5_target_budget'):
            row[key]=case.get(key)
        row['non_runtime_wait_over_reported_runtime_period_frames']=case.get('non_runtime_wait_over_budget_frames')
        row['submission_gaps_over_1_5_reported_runtime_period']=case.get('submission_gaps_over_1_5_period')
        for key in ('non_runtime_wait_wall_ms','outer_wall_ms','runtime_period_ms','submission_gap_ms'):
            flatten_distribution(row,key,case.get(key))
        comp=compositor.get(name,{})
        row['compositor_scope']='whole named interval; not split by native representation/tool'
        flatten_distribution(row,'gpu_ms',comp.get('gpu_ms'))
        row['compositor_samples']=comp.get('samples')
        for key in ('repeated','dropped','mispresented'):
            row['compositor_'+key]=comp.get(key) if comp.get('samples',0)>0 else None
        intervals.append(row)
        active=case.get('calculation_active_frame_wall_ms',{})
        for scope in sorted(set(active)|set(inventory)):
            stats=active.get(scope)
            # Native records are sparse: known instrumented scopes only emit
            # fields when entered. Zero requires a valid trace AND the supplied
            # source inventory; an unknown/missing counter remains unmeasured.
            absent=0 if base['trace_valid'] and scope in inventory else None
            calculation=dict(**shared,calculation=scope,calls=case.get('phase_calls',{}).get(scope.removesuffix('_ms')+'_calls',absent))
            flatten_distribution(calculation,'active_frame_inclusive_ms',stats)
            calculations.append(calculation)
        for phase,stats in case.get('phase_wall_ms',{}).items():
            value=dict(**shared,phase=phase)
            flatten_distribution(value,'wall_ms',stats)
            phases.append(value)


def calculation_inventory(source_directory):
    """Include modularized calculations and all local scope-variable names."""
    files = {}
    names = set()
    for path in sorted(source_directory.iterdir()):
        if path.suffix not in {'.cpp', '.hpp', '.inc'} or not path.is_file():
            continue
        content = path.read_text()
        scopes = re.findall(r'CalculationScope\s+\w+\(\s*"([^"\n]+)"', content)
        if scopes:
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            names.update(scopes)
    return ['calc_' + name + '_ms' for name in sorted(names)], files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaigns',nargs='+',type=Path,required=True)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--design',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--target-hz',type=float,default=90,help='Fixed benchmark target, independent of adaptive OpenXR pacing (default 90 Hz)')
    args=parser.parse_args()
    if not math.isfinite(args.target_hz) or args.target_hz<=0:parser.error('Target Hz must be finite and positive')
    args.output.mkdir(parents=True,exist_ok=False)
    native_source=Path(__file__).resolve().parents[2]/'native/vr_viewer/src/main.cpp'
    inventory, inventory_files = calculation_inventory(native_source.parent)
    (args.output/'calculation-inventory.json').write_text(json.dumps({'source':str(native_source),'sha256':hashlib.sha256(native_source.read_bytes()).hexdigest(),'files':inventory_files,'scopes':inventory,'note':'Zero calls means the instrumented scope was not entered in a valid measured interval. It does not prove all internal calculations are absent; consult the source inventory for uninstrumented subroutines.'},indent=2))
    data=collect([p.resolve() for p in args.campaigns],args.baseline.resolve() if args.baseline else None,inventory,1000/args.target_hz)
    for name,rows in data.items():table(args.output/(name+'.csv'),rows)
    captures=[]
    if args.baseline:
        for rep in ('full','stick','ballstick','surface'):
            original=args.baseline/(rep+'-steady_fast')/'stereo/mirror.png'
            if original.exists():
                filename='baseline-'+rep+'.png'
                shutil.copyfile(original,args.output/filename)
                captures.append(dict(representation=rep,file=filename,source=str(original.resolve()),
                                     sha256=hashlib.sha256(original.read_bytes()).hexdigest()))
    (args.output/'captures.json').write_text(json.dumps(captures,indent=2))
    from tools.vr_workflows.audit_review import write_review
    write_review(args.output/'review.html',data,args.target_hz,captures)
    source=args.design.read_bytes()
    index=dict(source=str(args.design.resolve()),sha256=hashlib.sha256(source).hexdigest(),
        target_hz=args.target_hz,target_budget_ms=1000/args.target_hz,
        gpu_metric='OpenVR Compositor_FrameTiming.m_flPreSubmitGpuMs',
        gpu_metric_limits='Compositor-reported scene-rendering span, not isolated shader execution or GPU utilization; scheduling can include other processes. Do not add to CPU wall time.',
        campaigns=[str(p.resolve()) for p in args.campaigns],baseline=str(args.baseline.resolve()) if args.baseline else None,
        rows={key:len(value) for key,value in data.items()},passed_workflows=sum(r['workflow_passed'] for r in data['runs']),
        passed_audits=sum(r['audit_passed'] for r in data['runs']),
        limits='Instrumented physical OpenXR sessions with synthetic controller profiles; not human wearer trials. FPS is application submission cadence, not scanout. CPU wall time includes waits. Inclusive calculation scopes overlap phases. Compositor sampling has approximately 100 ms boundary uncertainty. Failed workflows and absent measurements remain failures/gaps. Interval frames and compositor totals must not be summed across overlapping intervals or representation splits. Whole sessions include captures; interval CSV uses complete contained frames only. Coverage selects the latest attempt in the supplied chronological campaign order, not the best result.')
    (args.output/'index.json').write_text(json.dumps(index,indent=2))
    print(json.dumps(index,indent=2))


if __name__=='__main__':main()
