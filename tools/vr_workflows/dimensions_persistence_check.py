"""Isolated native launch -> save journal -> document file -> native reload proof."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.routes import _demo_design
from backend.api import routes_vr
from backend.core.models import Design
from backend.core.dimensions import Dimension
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.menu_tour import enlarge_mirror
from tools.vr_workflows.dimensions_check import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--validate',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    if routes_vr._read_state():
        raise RuntimeError('Another native viewer is active; refusing to replace it.')
    doc='__test_vr_dimension_persistence__'
    token=set_current_doc(doc)
    design=_demo_design();design.metadata.name='__e2e__native-dimensions'
    design.dimensions=[Dimension(id='desktop_seed',name='Desktop seed',a=(1,2,3),b=(4,6,3))]
    state.set_design(design)
    client=TestClient(app,client=('127.0.0.1',50000),headers={'X-NADOC-Doc':doc})
    launched=False;live=None
    def start():
        nonlocal launched,live
        response=client.post('/api/vr/launch',json={'scrywrite_live':'transactions'})
        assert response.status_code==200,response.text
        launched=True
        saved=routes_vr._read_state()
        (args.output/'launch.json').write_text(json.dumps(saved,indent=2))
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:
                live=LiveSession(Bridge(saved['scrywrite_socket']),physical=True)
                break
            except (RuntimeError,OSError):time.sleep(.2)
        assert live is not None
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
            time.sleep(.3)
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
        for preset in PRESETS if args.validate else ['steady_fast']:
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
        assert not Path(initial['event_path']+'.dimensions-pending').exists()
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
