"""Live 24HB idle/grip audit in Full, Stick, Ball & Stick and Quick Surface.

Private snapshot and owned viewer; unchanged rendering quality and motion presets.
This stage does not claim coverage of selected-part edits or authoring commits.
"""
import argparse
import json
import hashlib
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
from backend.api import routes_vr as vr
from backend.api.routes_vr_tours import _viewer_active
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.representation_tour import ROOT
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.models import Design
from tools.vr_workflows.representation_motion import check as grip_check
from tools.vr_workflows.frame_audit import report, distribution


def compositor_report(path, intervals):
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    cases = []
    for interval in intervals:
        selected = [r for r in rows if interval['start_ms'] <= r['sample_wall_time_ms'] <= interval['end_ms']]
        cases.append(dict(**interval, samples=len(selected),
            gpu_ms=distribution([r['m_flPreSubmitGpuMs'] for r in selected]),
            repeated=sum(max(0,r['m_nNumFramePresents']-1) for r in selected),
            dropped=sum(r['m_nNumDroppedFrames'] for r in selected),
            mispresented=sum(r['m_nNumMisPresented'] for r in selected)))
    return dict(note='Polling wall timestamps have approximately 100 ms boundary uncertainty. GPU duration is not total CPU+GPU time; repeated/dropped are compositor counters.',cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, default=ROOT/'workspace/24hb_0xT.nadoc')
    parser.add_argument('--output', type=Path, default=ROOT/'.development-artifacts/vr-frame-audit'/uuid.uuid4().hex[:10])
    parser.add_argument('--snapshot', type=Path, help='Reuse an immutable selective export')
    parser.add_argument('--viewer-binary', type=Path, help='Explicit saved native binary for labeled A/B verification')
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--representations', nargs='+', choices=['full','stick','ballstick','surface'], default=['full','stick','ballstick','surface'])
    parser.add_argument('--mirror-diagnostics', action='store_true', help='Retain asynchronous diagnostic source/completion metadata')
    parser.add_argument('--idle-seconds', type=float, default=10)
    args = parser.parse_args()
    if not 1 <= args.idle_seconds <= 120: parser.error('--idle-seconds must be 1..120')
    if _viewer_active(): raise RuntimeError('An existing viewer must be closed before this isolated tour.')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=False)
    if args.snapshot:
        snapshot=args.snapshot.resolve()
        export=dict(snapshot=str(snapshot),reused=True)
    else:
        raw=args.design.read_bytes()
        doc='__test_vr_frame_audit_'+uuid.uuid4().hex
        token=set_current_doc(doc)
        try:
            state.set_design(Design.from_json(raw.decode()))
            with (args.output/'scene.nadocvr').open('w',buffering=1024*1024) as stream:
                vr._snapshot(vr.VRLaunchRequest(),line_writer=lambda line:stream.write(line+'\n'),representations={'full','stick','ballstick','surface'})
        finally:
            state.drop_doc(doc)
            reset_current_doc(token)
        export=dict(source=str(args.design),sha256=hashlib.sha256(raw).hexdigest(),representations=['full','stick','ballstick','surface'])
        snapshot=args.output/'scene.nadocvr'
    (args.output/'export.json').write_text(json.dumps(export,indent=2))
    if args.viewer_binary:
        args.viewer_binary=args.viewer_binary.resolve()
        if not args.viewer_binary.is_file():parser.error('Saved viewer binary does not exist')
    else:
        vr._ensure_viewer_built()
    vr._start_steamvr()
    intervals, errors = [], []
    viewer = sampler = live = None
    with tempfile.TemporaryDirectory(prefix='nadoc-frame-audit-') as temporary:
        runtime=Path(temporary)
        visual=runtime/'visualization.txt'
        socket=runtime/'viewer.sock'
        env={**vr._build_environment(),'NADOC_VR_FRAME_AUDIT':'1'}
        sequence=0
        def publish(rep):
            nonlocal sequence
            sequence+=1
            pending=visual.with_suffix('.tmp')
            pending.write_text(vr._visualization_snapshot_record([],sequence=sequence,mode='design',view_rotation=np.eye(3),representation=rep,coloring='strand'))
            pending.replace(visual)
        publish(args.representations[0])
        command=[str(args.viewer_binary or ROOT/'native/vr_viewer/build/nadoc-vr-viewer'),str(snapshot),
                 '--visualization',str(visual),'--events',str(runtime/'events.json'),
                 '--scrywrite-live',str(socket),'--scrywrite-live-mode','transactions',
                 '--mirror-eye','left','--place-scene-in-view','on','--scene-view','mirror',
                 '--scene-orientation','isometric','--scene-distance','1.30','--scene-scale','3.0']
        if args.mirror_diagnostics:
            command += ['--mirror-diagnostics', str(args.output/'mirror-diagnostics.jsonl')]
        try:
            if _viewer_active(): raise RuntimeError('A viewer started while preparing the audit.')
            with (args.output/'compositor.log').open('w') as log:
                sampler=subprocess.Popen([shutil.which('uv') or 'uv','run','--with','openvr','python','-m','tools.vr_workflows.compositor_timing','--output',str(args.output/'compositor.jsonl'),'--seconds','1800'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            with (args.output/'viewer.log').open('w') as log:
                viewer=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT)
            (args.output/'launch.json').write_text(json.dumps(dict(pid=viewer.pid,command=command,quality='production defaults',setup='representation changes via production visualization feed; no browser editing bridge'),indent=2))
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                if viewer.poll() is not None: raise RuntimeError('Viewer exited; see viewer.log')
                try:
                    live=LiveSession(Bridge(str(socket)),physical=True,allow_transactions=True)
                    if not live.state.get('startup',{}).get('active',False): break
                except (ValueError,RuntimeError,OSError): pass
                time.sleep(.2)
            else: raise RuntimeError('No focused physical session')
            for menu in (0,1):
                if live.state['sidebars'][menu]['open']: live.button('menu',hand=menu)
            for rep in args.representations:
                publish(rep)
                deadline=time.monotonic()+120
                while time.monotonic()<deadline:
                    live.frame()
                    if live.state['representation']==rep and not live.state.get('representation_loading',{}).get('pending',False): break
                else: raise RuntimeError('Representation did not become ready: '+rep)
                time.sleep(2)  # Explicit warmup, outside measured intervals.
                for preset in PRESETS if args.validate else ['steady_fast']:
                    name=rep+'-'+preset
                    print('AUDIT '+name,flush=True)
                    # Drain previous capture/IPC and the compositor polling window.
                    # This is outside measurement; retain the original matrix as evidence.
                    time.sleep(1)
                    start=time.time()*1000
                    time.sleep(args.idle_seconds)
                    intervals.append(dict(name=name+'-idle',start_ms=start,end_ms=time.time()*1000))
                    destination=args.output/name
                    try:
                        grip_check(live,destination,preset)
                    except Exception as error:
                        errors.append(dict(case=name,error=str(error)))
                    if (destination/'motion.json').exists():
                        motion=json.loads((destination/'motion.json').read_text())
                        for i,trial in enumerate(motion['motions']):
                            if 'end_ms' in trial: intervals.append(dict(name=name+f'-grip-{i}',start_ms=trial['start_ms'],end_ms=trial['end_ms']))
                    (args.output/'intervals.json').write_text(json.dumps(intervals,indent=2))
                    if errors: break
                if errors: break
        except Exception as error:
            errors.append(dict(case='session',error=str(error)))
        finally:
            if live:
                try: live.release()
                except (RuntimeError,OSError): pass
            for process in (viewer,sampler):
                if process and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            result=report((args.output/'viewer.log').read_text() if (args.output/'viewer.log').exists() else '',intervals,target_budget_ms=1000/90)
            result['errors']=errors
            result['coverage']='idle and whole-model grips only'
            result['passed']=result['valid'] and not errors and not result['missing_intervals'] and len(intervals)==len(args.representations)*3*(len(PRESETS) if args.validate else 1)
            (args.output/'frame-audit.json').write_text(json.dumps(result,indent=2))
            comp=compositor_report(args.output/'compositor.jsonl',intervals)
            (args.output/'compositor-summary.json').write_text(json.dumps(comp,indent=2))
    print(args.output,flush=True)
    if not result['passed'] or any(not c['samples'] for c in comp['cases']): raise SystemExit(1)


if __name__=='__main__': main()
