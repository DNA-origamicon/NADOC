"""Record existing isolated authoring tours across the requested representations.

Failures remain failures. Original fixtures, seeds and controller deadlines are
unchanged. Reach intervals exclude captures, but include setup/menu reaches;
native tool mode and representation identify each reported case.
"""
import argparse
import hashlib
import math
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

from tools.vr_workflows.tour_catalog import ROOT
from tools.vr_workflows.frame_audit import report
from tools.vr_workflows.frame_audit_tour import compositor_report

TOOLS={'move':['move_tour','--target','base','--direct-activation'],
       'move_cluster':['move_tour','--target','cluster','--direct-activation'],
       'bend':['bend_tour'],'twist':['twist_tour'],'sweep':['sweep_tour'],'extrude':['extrude_tour','--lattice','honeycomb'],
       'nick':['nick_tour'],'ligation':['ligation_tour'],'end_resize':['end_resize_tour'],
       'view_tools':['view_tools_tour'],'simulation':['simulation_tour'],
       'dimensions':['dimensions_persistence_check'],'view_volumes':['view_volumes_check']}


def stop(process):
    if process and process.poll() is None:
        os.killpg(process.pid,signal.SIGINT)
        try: process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL);process.wait()


def retain_owned_volume_journals(case):
    """Retain journals named by this stopped private backend, then clean /tmp.

    Changing/reopening the fixture can leave its volume binding behind. Never
    glob shared runtime files: only exact paths reported by this case are owned.
    The caller must have stopped the tour and verified that its viewer exited.
    """
    log=case/'tour.log'
    manifest=case/'volume-journal-cleanup.json'
    records=json.loads(manifest.read_text()) if manifest.exists() else []
    if log.exists():
        paths=set(re.findall(r'Retaining unsaved view-volume journal at (/tmp/nadoc-vr-event-[a-zA-Z0-9_-]+\.json)',log.read_text(errors='replace')))
        for base in sorted(paths):
            for suffix in ('state','state.tmp','pending','pending.tmp'):
                path=Path(base+'.volumes-'+suffix)
                if not path.is_file() or path.is_symlink():continue
                retained=case/'retained-volume-journals'/path.name
                retained.parent.mkdir(exist_ok=True)
                data=path.read_bytes();retained.write_bytes(data)
                if retained.read_bytes()!=data:raise RuntimeError('Journal evidence copy failed')
                path.unlink()
                records.append(dict(path=str(path),retained=str(retained),sha256=hashlib.sha256(data).hexdigest(),removed=not path.exists()))
    manifest.write_text(json.dumps(records,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools',nargs='+',choices=TOOLS,default=list(TOOLS))
    parser.add_argument('--representations',nargs='+',choices=['full','stick','ballstick','surface'],default=['full','stick','ballstick','surface'])
    parser.add_argument('--design',type=Path,help='Full-size authored design imported into private tool fixtures')
    parser.add_argument('--validate',action='store_true')
    parser.add_argument('--settled-drag',action='store_true',help='Measure a long settled Move/Rotate drag and stationary control.')
    parser.add_argument('--profiles',nargs='+',choices=['steady_fast','steady_deliberate','variable_fast','variable_deliberate'],
                        help='Explicit subset for a documented retry; use --validate for profile-named case directories')
    parser.add_argument('--desktop-rendering',choices=['off','on'],default='off',
                        help='Browser desktop viewport during VR; off by default for feature benchmarks')
    parser.add_argument('--target-hz',type=float,default=90,help='Fixed benchmark target, independent of adaptive OpenXR pacing')
    parser.add_argument('--restart-runtime-between-representations',action='store_true',
                        help='Exclusive audit only: gracefully restart the owned Steam/SteamVR client stack before each representation batch')
    parser.add_argument('--min-available-gib',type=float,default=0,help='Stop before a case when host MemAvailable is below this floor')
    parser.add_argument('--output',type=Path,default=ROOT/'.development-artifacts/vr-tool-frame-audit'/uuid.uuid4().hex[:10])
    args=parser.parse_args()
    if args.settled_drag and any(t not in ('move','move_cluster') for t in args.tools):parser.error('--settled-drag requires Move/Rotate tools only')
    if args.profiles and not args.validate:parser.error('--profiles requires --validate')
    if not math.isfinite(args.target_hz) or args.target_hz<=0:parser.error('Target Hz must be finite and positive')
    if not math.isfinite(args.min_available_gib) or args.min_available_gib<0:parser.error('Memory floor must be finite and nonnegative')
    if args.design:
        args.design=args.design.resolve()
        if not args.design.is_file():parser.error('Design does not exist')
    from backend.api import routes_vr as vr
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active(): raise RuntimeError('Close the active viewer before this isolated audit.')
    # Build outside browser readiness deadlines and measured VR work.
    vr._ensure_viewer_built()
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    results=[]
    source=None
    if args.design:
        source={'path':str(args.design),'sha256':hashlib.sha256(args.design.read_bytes()).hexdigest()}
    profiles=args.profiles or (['steady_fast','steady_deliberate','variable_fast','variable_deliberate'] if args.validate else ['steady_fast'])
    (args.output/'campaign.json').write_text(json.dumps({'source':source,'tools':args.tools,'representations':args.representations,'validation':args.validate,'profiles':profiles,'target_hz':args.target_hz,'desktop_rendering':args.desktop_rendering,
        'restart_runtime_between_representations':args.restart_runtime_between_representations,'min_available_gib':args.min_available_gib,'settled_drag':args.settled_drag},indent=2))
    uv=shutil.which('uv') or 'uv'
    from tools.vr_workflows.audit_runtime import resources,pressure,restart
    current_rep=None
    for rep,tool,profile in ((r,t,p) for r in args.representations for t in args.tools for p in profiles):
        if args.restart_runtime_between_representations and rep!=current_rep:
            print('RUNTIME_RESET '+rep,flush=True)
            restart(args.output/('runtime-reset-'+rep+'.json'))
        current_rep=rep
        host_before=resources()
        if host_before['mem_available_kib']<args.min_available_gib*1024**2:
            (args.output/'campaign-halt.json').write_text(json.dumps({'reason':'Host available memory below floor','tool':tool,'representation':rep,'profile':profile,'resources':host_before},indent=2))
            raise RuntimeError('Host available memory below audit floor')
        case=args.output/(tool+'-'+rep+('-'+profile if args.validate else ''));case.mkdir()
        env={**os.environ,'NADOC_VR_FRAME_AUDIT':'1','NADOC_VR_AUDIT_REPRESENTATION':rep,
             'NADOC_VR_AUDIT_DESKTOP_DRAW':'preference-off' if args.desktop_rendering=='off' else 'on',
             'NADOC_VR_AUDIT_BROWSER_TRACE':'1',
             'NADOC_VR_AUDIT_INTERVALS':str(case/'reaches.jsonl'),'NADOC_VR_AUDIT_PROFILE':profile}
        if args.design:env['NADOC_VR_AUDIT_DESIGN']=str(args.design)
        module,*options=TOOLS[tool]
        command=[uv,'run','python','-m','tools.vr_workflows.'+module,*options,'--output',str(case/'tour')]
        if args.settled_drag:command.append('--settled-drag')
        if args.validate: command.append('--validate')
        sampler=process=None
        code=None;error=None;started=time.time()*1000
        log_offset=vr._LOG_PATH.stat().st_size if vr._LOG_PATH.exists() else 0
        print('TOOL_AUDIT '+tool+' '+rep+' '+profile,flush=True)
        try:
            with (case/'compositor.log').open('w') as log:
                sampler=subprocess.Popen([uv,'run','--with','openvr','python','-m','tools.vr_workflows.compositor_timing','--output',str(case/'compositor.jsonl'),'--seconds','1800'],cwd=ROOT,env=vr._build_environment(),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            with (case/'tour.log').open('w') as log:
                process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                code=process.wait(timeout=1200)
        except Exception as failure: error=str(failure)
        finally:
            stop(process)
            # /vr/stop can acknowledge before the native process flushes its
            # final frame. Preserve that tail before copying or summarizing.
            cleanup_deadline=time.monotonic()+20
            while _viewer_active() and time.monotonic()<cleanup_deadline:time.sleep(.2)
            stop(sampler)
            if not _viewer_active():retain_owned_volume_journals(case)
            host_after=resources()
            (case/'host-resources.json').write_text(json.dumps({'before':host_before,'after':host_after,
                'delta':pressure(host_before,host_after),'limits':'Boundary host-wide counters include setup and cleanup; not per-frame or process-specific CPU/memory attribution.'},indent=2))
            text=''
            if vr._LOG_PATH.exists():
                with vr._LOG_PATH.open('rb') as native_log:
                    if vr._LOG_PATH.stat().st_size>=log_offset: native_log.seek(log_offset)
                    text=native_log.read().decode(errors='replace')
            # Native logs may contain earlier launches; interval filtering below
            # prevents an old successful frame from masking a failed setup.
            (case/'viewer.log').write_text(text)
            intervals=[json.loads(line) for line in (case/'reaches.jsonl').read_text().splitlines()] if (case/'reaches.jsonl').exists() else []
            audit=report(text,intervals or [dict(name='setup',start_ms=started,end_ms=time.time()*1000)],target_budget_ms=1000/args.target_hz)
            failure_lines=[re.sub(r'\x1b\[[0-9;]*m','',line).strip() for line in (case/'tour.log').read_text(errors='replace').splitlines() if '[WebServer]' not in line and re.search(r'(?:Error|Exception):|\bStopIteration\b',line)] if (case/'tour.log').exists() else []
            audit.update(failure_excerpt=failure_lines[-5:], tool=tool,profile=profile,requested_representation=rep,tour_exit_code=code,error=error,
                         reach_intervals=len(intervals),passed=code==0 and bool(intervals) and audit['valid'] and not audit['missing_intervals'] and any(c['representation']==rep for c in audit['cases']))
            (case/'frame-audit.json').write_text(json.dumps(audit,indent=2))
            # Keep asynchronous commit/playback work too. This inclusive session
            # summary deliberately contains captures and is not a clean FPS gate.
            session=report(text,target_budget_ms=1000/args.target_hz)
            session['workload']='Whole owned session including setup, captures, waits, commits and playback; use reach report for measured motion.'
            (case/'session-frame-audit.json').write_text(json.dumps(session,indent=2))
            (case/'compositor-summary.json').write_text(json.dumps(compositor_report(case/'compositor.jsonl',intervals),indent=2))
            results.append(dict(tool=tool,profile=profile,representation=rep,passed=audit['passed'],tour_exit_code=code,error=error,failure_excerpt=failure_lines[-5:],reach_intervals=len(intervals)))
            (args.output/'matrix.json').write_text(json.dumps(dict(validation=args.validate,source=source,results=results),indent=2))
        if _viewer_active(): raise RuntimeError('An active viewer remains; refusing to start another case.')
    print(args.output,flush=True)
    if any(not r['passed'] for r in results): raise SystemExit(1)


if __name__=='__main__': main()
