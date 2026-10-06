"""Fresh browser part → VR-painted honeycomb/square extrusion → local volume.

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
    parser.add_argument('--lattice',choices=['honeycomb','square'])
    parser.add_argument('--slice-reference',action='store_true',
                        help='Start with a square 1x8 platform and paint adjacent cells')
    parser.add_argument('--paint-grid-zoom',type=float,default=1,
                        help='Explicit diagnostic two-grip zoom before painting (default: unchanged auto-fit)')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.slice_reference and args.lattice == 'honeycomb':
        parser.error('--slice-reference requires the square lattice')
    if not .25 <= args.paint_grid_zoom <= 4:
        parser.error('--paint-grid-zoom must be .25..4')
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active(): raise RuntimeError('Close the active viewer before starting an isolated extrusion tour.')
    # Compilation is preparation, outside the browser's measured launch gate.
    # A changed main.cpp can otherwise consume that gate before VR even starts.
    from backend.api.routes_vr import _ensure_viewer_built
    _ensure_viewer_built()
    output=(args.output or ROOT/'.development-artifacts/vr-extrude'/uuid.uuid4().hex[:10]).resolve()
    output.mkdir(parents=True,exist_ok=True)
    profiles=['steady_fast','steady_deliberate','variable_fast','variable_deliberate'] if args.validate else ['steady_fast']
    if os.environ.get('NADOC_VR_AUDIT_PROFILE'): profiles=[os.environ['NADOC_VR_AUDIT_PROFILE']]
    lattices=['square'] if args.slice_reference else [args.lattice] if args.lattice else ['honeycomb','square'] if args.validate else ['honeycomb']
    results=[]
    with tempfile.TemporaryDirectory(prefix='nadoc-extrude-tour-') as temporary:
        for lattice,profile in ((l,p) for l in lattices for p in profiles):
            with socket.socket() as backend, socket.socket() as frontend:
                backend.bind(('127.0.0.1',0));frontend.bind(('127.0.0.1',0))
                backend_port=str(backend.getsockname()[1]);frontend_port=str(frontend.getsockname()[1])
            env={**os.environ,'NADOC_VR_LATTICE':lattice.upper(),'NADOC_SMOKE_BACKEND_PORT':backend_port,
                 'NADOC_SMOKE_FRONTEND_PORT':frontend_port,'NADOC_E2E_API_BASE':'http://127.0.0.1:'+backend_port,'NADOC_WORKSPACE':temporary,'NADOC_PHYSICAL_VR_TEST':'1',
                 'NADOC_VR_PROFILE':profile,'NADOC_VR_MENU_ACTIVATION':'1',
                 'NADOC_VR_PROFILE_CONTROLS':'1','NADOC_VR_FEEDBACK_ACQUISITION':'1',
                 'NADOC_VR_APPROACH_CONTROLS':'1','NADOC_VR_APPROACH_CELLS':'1',
                 'NADOC_VR_PAINT_ZOOM':'fit','NADOC_VR_REVIEW_VIEW':'1',
                 'NADOC_VR_FREEFORM':'0','NADOC_VR_PROFILE_WHEEL':os.environ.get('NADOC_VR_PROFILE_WHEEL','1'),
                 'NADOC_VR_SLICE_REFERENCE':'1' if args.slice_reference else '0',
                 'NADOC_VR_PAINT_GRID_ZOOM':str(args.paint_grid_zoom),
                 'NADOC_VR_DEMO':'0' if args.validate else '1','NADOC_VR_DEMO_HOLD':'3'}
            command=['npx','playwright','test','--config','playwright.smoke.config.js',
                     'vr_extrude_volume.spec.js','--workers=1','--output',str(output/lattice/profile)]
            if not args.validate or os.environ.get('NADOC_VR_FRAME_AUDIT') == '1': command.append('--headed')
            result=subprocess.run(command,cwd=ROOT/'frontend',env=env)
            results.append({'lattice':lattice,'profile':profile,'passed':result.returncode==0})
            (output/'result.json').write_text(json.dumps({'results':results,'workspace':'temporary, removed on exit'},indent=2))
            if result.returncode: raise SystemExit(result.returncode)
    print(output,flush=True)

if __name__=='__main__':main()
