"""Isolated native launch -> save journal -> document file -> native reload proof."""
import argparse
import os
import json
import time
import uuid
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.routes import _demo_design
from backend.api import routes_vr
from tools.vr_workflows.audit_design import load as audit_design
from backend.core.models import Design
from backend.core.dimensions import Dimension
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.menu_tour import enlarge_mirror
from tools.vr_workflows.dimensions_check import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('.development-artifacts/vr-dimensions')/('persistence-'+uuid.uuid4().hex[:12]))
    parser.add_argument('--validate',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    if routes_vr._read_state():
        raise RuntimeError('Another native viewer is active; refusing to replace it.')
    doc='__test_vr_dimension_persistence__'
    token=set_current_doc(doc)
    design=audit_design(_demo_design);design.metadata.name='__e2e__native-dimensions'
    design.dimensions=[Dimension(id='desktop_seed',name='Desktop seed',a=(1,2,3),b=(4,6,3))]
    state.set_design(design)
    client=TestClient(app,client=('127.0.0.1',50000),headers={'X-NADOC-Doc':doc})
    launched=False;live=None;owned_event=None
    def start():
        nonlocal launched,live,owned_event
        response=client.post('/api/vr/launch',json={'scrywrite_live':'transactions'})
        assert response.status_code==200,response.text
        launched=True
        saved=routes_vr._read_state()
        owned_event=Path(saved['event_path'])
        (args.output/'launch.json').write_text(json.dumps(saved,indent=2))
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:
                live=LiveSession(Bridge(saved['scrywrite_socket']),physical=True,allow_transactions=True)
                break
            except (RuntimeError,OSError,ValueError):time.sleep(.2)
        assert live is not None
        expected=os.environ.get('NADOC_VR_AUDIT_REPRESENTATION')
        if expected:
            deadline=time.monotonic()+180
            while live.state.get('startup',{}).get('active'):
                if time.monotonic()>deadline:raise RuntimeError('Audit startup timed out')
                live.frame();time.sleep(.05)
            # Production launches intentionally start in Full. Use the normal
            # display-feedback route to request the audit representation.
            response=client.post('/api/vr/visualization-feedback',json={'representation':expected})
            assert response.status_code==200,response.text
            deadline=time.monotonic()+180
            while live.state['representation']!=expected or live.state['representation_loading']['pending'] or live.state.get('startup',{}).get('active'):
                if time.monotonic()>deadline:raise RuntimeError('Audit launch representation not ready: '+expected)
                live.frame();time.sleep(.05)
        enlarge_mirror(live)
        return saved
    def check_positions(records, launch):
        presentation=live.state['presentation']
        transform=np.asarray(presentation['model_to_tracking_rows'])
        rotation=np.asarray(launch['view_rotation'])
        center=np.asarray(presentation['source_center_nm'])
        offset=np.asarray(presentation['normalized_offset_model'])
        scale=presentation['normalization_model_per_nm']
        entries=live.state['dimensions']['entries']
        assert len(entries)==len(records)
        for record,entry in zip(records,entries):
            for point,endpoint in zip((record.a,record.b),entry['endpoints']):
                local=(rotation@point-center)*scale+offset
                expected=(transform@np.r_[local,1])[:3]
                assert np.allclose(expected,endpoint['world'],atol=1e-5), (expected,endpoint)

    def stop():
        nonlocal launched,live
        if live:
            live.release();live=None
        if launched:
            assert client.post('/api/vr/stop').status_code==200
            launched=False
            # /vr/stop acknowledges SIGTERM, not completed journal cleanup.
            # The owned event file is removed after the persistence bindings
            # have drained. This wait is outside all measured motion intervals.
            deadline=time.monotonic()+20
            while owned_event.exists() and time.monotonic()<deadline:time.sleep(.05)
            assert not owned_event.exists(), 'Owned viewer cleanup did not finish'
    try:
        initial=start()
        assert len(live.state['dimensions']['entries'])==1
        assert abs(live.state['dimensions']['entries'][0]['length_nm']-5)<.001
        check_positions(design.dimensions,initial)
        head=live.state['head_position']
        for h in (0,1):
            live.send('pose',hand=h,position=[head[0]+(-.3 if h==0 else .3),head[1]-.3,head[2]-.3],orientation=[0,0,0,1])
            live.button('menu',hand=h)
        results=[]
        for preset in ([os.environ['NADOC_VR_AUDIT_PROFILE']] if os.environ.get('NADOC_VR_AUDIT_PROFILE') else PRESETS if args.validate else ['steady_fast']):
            directory=args.output/preset;directory.mkdir()
            results.append({'preset':preset,**run(live,None,directory,preset)})
        expected=live.state['dimensions']['entries']
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            saved=state.get_or_404().dimensions
            if len(saved)==len(expected) and all(abs(np.linalg.norm(np.array(a.a)-a.b)-b['length_nm'])<.002 for a,b in zip(saved,expected)):
                break
            live.frame();time.sleep(.05)
        assert len(saved)==len(expected)
        assert all(abs(np.linalg.norm(np.array(a.a)-a.b)-b['length_nm'])<.002 for a,b in zip(saved,expected))
        check_positions(saved,initial)
        content=state.get_or_404().to_json()
        (args.output/'saved.nadoc').write_text(content)
        stop()
        pending=Path(initial['event_path']+'.dimensions-pending')
        if pending.exists():
            (args.output/'pending-at-stop.json').write_bytes(pending.read_bytes())
        assert not pending.exists(), 'Dimensions journal remains pending after owned viewer stop'
        state.set_design(Design.from_json(content))
        reopened=start()
        check_positions(saved,reopened)
        reloaded=live.state['dimensions']['entries']
        assert len(reloaded)==len(saved)
        assert all(abs(a['length_nm']-np.linalg.norm(np.array(b.a)-b.b))<.002 for a,b in zip(reloaded,saved))
        (args.output/'result.json').write_text(json.dumps({'passed':True,'profiles':results,'saved':len(saved),'native_reload':True},indent=2))
        print('Native dimensions saved and reloaded:',len(saved))
    finally:
        stop()
        state.drop_doc(doc)
        reset_current_doc(token)


if __name__=='__main__':main()
