"""Private generated 6HB or copied design → trigger move/rotate and persistence checks.

Never uses or publishes to the user's workspace. Browser, backend, files and
native viewer are owned by this run; evidence alone is retained.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
import socket
from tools.vr_workflows.tour_catalog import ROOT

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate',action='store_true')
    parser.add_argument('--profile',choices=['steady_fast','steady_deliberate','variable_fast','variable_deliberate'],help='Run one motion profile without repeating a completed matrix.')
    parser.add_argument('--direct-activation',action='store_true',help='Performance setup: activate Move/Rotate directly; subsequent interactions remain profile-driven.')
    parser.add_argument('--keep-going',action='store_true',help='Retain independent profile results after a failure; still exit nonzero.')
    parser.add_argument('--target',choices=['cluster','overhang','base'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--design',type=Path,help='Copy an existing design into the private test workspace (base target only).')
    args=parser.parse_args()
    if args.profile and args.validate: parser.error('--profile and --validate are mutually exclusive')
    if args.design and args.target!='base': parser.error('--design currently requires --target base')
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active(): raise RuntimeError('Close the active viewer before starting an isolated move/rotate tour.')
    output=(args.output or ROOT/'.development-artifacts/vr-move'/uuid.uuid4().hex[:10]).resolve()
    output.mkdir(parents=True,exist_ok=True)
    profiles=['steady_fast','steady_deliberate','variable_fast','variable_deliberate'] if args.validate else [args.profile or 'steady_fast']
    targets=[args.target] if args.target else ['cluster','overhang','base']
    results=[]
    with tempfile.TemporaryDirectory(prefix='nadoc-move-tour-') as temporary:
        fixture=None
        if args.design:
            design=json.loads(args.design.read_text())
            if design.get('nucleotide_transforms'): raise ValueError('Imported test design must have no existing nucleotide transforms')
            # Branch heads belong to the source workspace's revision store.
            # This private copy starts a new store, retaining embedded history.
            for loadout in design.get('loadouts',[]):
                if not loadout.get('design_snapshot_gz_b64'): raise ValueError('Use a complete .nadoc file, not an API loadout summary')
                loadout['head_revision_id']=None
                loadout['base_revision_id']=None
            design['metadata']['name']='__e2e__VR Move imported'
            design['metadata']['identity_last_known_path']='move-fixture.nadoc'
            fixture=Path(temporary)/'move-fixture.nadoc'
            fixture.write_text(json.dumps(design))
        for target,profile in ((l,p) for l in targets for p in profiles):
            case_workspace=Path(temporary)/target/profile
            case_workspace.mkdir(parents=True)
            if fixture:
                fixture=case_workspace/'move-fixture.nadoc'
                fixture.write_text(json.dumps(design))
            with socket.socket() as backend, socket.socket() as frontend:
                backend.bind(('127.0.0.1',0));frontend.bind(('127.0.0.1',0))
                backend_port=str(backend.getsockname()[1]);frontend_port=str(frontend.getsockname()[1])
            env={**os.environ,'NADOC_VR_MOVE_TARGET':target,'NADOC_SMOKE_BACKEND_PORT':backend_port,
                 'NADOC_SMOKE_FRONTEND_PORT':frontend_port,'NADOC_E2E_API_BASE':'http://127.0.0.1:'+backend_port,'NADOC_WORKSPACE':str(case_workspace),'NADOC_PHYSICAL_VR_TEST':'1',
                 'NADOC_VR_PROFILE':profile,
                 'NADOC_VR_DEMO':'0' if args.validate else '1','NADOC_VR_DEMO_HOLD':'3'}
            if fixture: env['NADOC_VR_MOVE_DESIGN']=str(fixture)
            if args.direct_activation: env['NADOC_VR_MOVE_DIRECT_ACTIVATION']='1'
            command=['npx','playwright','test','--config','playwright.smoke.config.js',
                     'vr_move_rotate.spec.js','--workers=1','--output',str(output/target/profile)]
            # Physical VR validation needs real window focus so the desktop
            # renderer yields the GPU when the native viewer takes focus.
            command.append('--headed')
            result=subprocess.run(command,cwd=ROOT/'frontend',env=env)
            results.append({'target':target,'profile':profile,'passed':result.returncode==0})
            (output/'result.json').write_text(json.dumps({'results':results,'workspace':'temporary, removed on exit','design':str(args.design.resolve()) if args.design else 'generated 6HB','direct_activation':args.direct_activation},indent=2))
            if result.returncode and not args.keep_going: raise SystemExit(result.returncode)
    print(output,flush=True)
    if any(not r['passed'] for r in results): raise SystemExit(1)

if __name__=='__main__':main()
