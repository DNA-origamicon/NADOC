"""Physical trigger editing; read-only native targets guide noisy controller paths."""
import json,sys,os,time
from pathlib import Path
from urllib.parse import unquote
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.model import multiply
from tools.vr_workflows.extrude_sidebar import SidebarControls
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.demo_view import reveal,hold
socket,output,kind,before_path,mode=sys.argv[1:6]
out=Path(output);out.mkdir(parents=True,exist_ok=True)
bridge=Bridge(socket)
deadline=time.monotonic()+30
while True:
 try:
  state=bridge.call('scrywrite_observe',{})
  if state.get('focused'):break
 except OSError:pass
 if time.monotonic()>deadline:raise RuntimeError('Viewer did not become focused')
 time.sleep(.1)
live=LiveSession(bridge,physical=True,allow_transactions=True)
preset=os.environ.get('NADOC_VR_PROFILE','steady_fast')
controls=SidebarControls(live,out,preset);trials=[]
def wait(predicate):
 deadline=time.monotonic()+90
 while not predicate(live.state):
  if time.monotonic()>deadline:raise RuntimeError('Timed out: '+str(live.state))
  try:live.frame()
  except TimeoutError:continue # read-only observation during authoritative snapshot upload
  time.sleep(.05)
def reach(position,orientation=None,acquired=None):
 trials.append(reach_target(live,position,preset,3000+len(trials),target_position=position,target_orientation=orientation or [0,0,0,1],acquired=acquired))
 (out/'reaches.json').write_text(json.dumps(trials,indent=2))
def park():
 p=np.array(live.state['head_position'])+[0,-1,0]
 for h in (0,1):live.send('pose',hand=h,position=p.tolist(),orientation=[0,0,0,1])
 live.frame()
try:
 reveal(live)
 if mode=='undo':
  if not live.state['sidebars'][1]['open']:live.button('menu',hand=1);live.frame()
  controls.click('move:undo');wait(lambda s:s['status']=='UNDONE')
  park();live.capture_to(out/'undone',discard_source=True)
 else:
  if not live.state['sidebars'][1]['open']:live.button('menu',hand=1);live.frame()
  controls.click('tab:tools');controls.click('tool-move')
  controls.click('move:recenter')
  live.frame()
  # With Move / Rotate open, grips still move the part rather than editing it.
  park()
  p=(np.array(live.state['head_position'])+[0,-.65,0]).tolist()
  reach(p);presentation=live.state['presentation']['model_to_tracking_rows']
  sequence=live.state['tool_sequence']
  live.send('button',hand=1,button='grip',pressed=True);live.frame()
  reach((np.array(p)+[.06,0,0]).tolist())
  live.send('button',hand=1,button='grip',pressed=False);live.frame()
  assert live.state['presentation']['model_to_tracking_rows']!=presentation
  assert live.state['tool_sequence']==sequence and not live.state['move_grabbing']
  controls.click('move:recenter');live.frame()
  controls.click('move:'+kind)
  before=json.loads(Path(before_path).read_text())
  cluster=next(c for c in before['design']['cluster_transforms'] if c['name']=='Movable helix')
  geom=before['geometry']
  allowed=[n for n in geom if (n.get('overhang_id') if kind=='overhang' else n['helix_id'] in cluster['helix_ids'] if kind=='cluster' else not n.get('overhang_id'))]
  live.button('menu',hand=1);live.frame()
  park();live.capture_to(out/'before-framing',discard_source=True)
  from tools.vr_workflows.review_view import improve_review
  improve_review(live,out/'before-framing',out/'review-view')
  park()
  targets=live.state['move_targets']
  matches=[p for p in targets if any(f":{n['helix_id']}:{n['bp_index']}:{n['direction']}:" in unquote(p['identity']) for n in allowed)]
  assert matches,'no rendered target candidates'
  # Approach actual backbone points, then click. Selection is browser-authoritative.
  target=min(matches,key=lambda p:np.linalg.norm(np.array(p['world'])-live.state['head_position']))
  reach((np.array(target['world'])+[0,0,.12]).tolist())
  live.button('trigger',hand=1)
  wait(lambda s:s['selection_kind']==kind and s['move_handle'] is not None)
  park();live.capture_to(out/'selected',discard_source=True);hold(live,'Selected '+kind)
  center=live.state['move_handle']
  reach(center,acquired=lambda s:s['move_nearby'])
  assert live.state['move_nearby'],'centroid not highlighted'
  live.send('button',hand=1,button='trigger',pressed=True);live.frame()
  assert live.state['move_grabbing'],'trigger did not acquire target'
  start=np.array(live.state['hands'][1]['position']);q=live.state['hands'][1]['orientation_xyzw']
  rotation=[0,0,np.sin(np.pi/12),np.cos(np.pi/12)]
  from tools.vr_motion.metrics import rotate
  shift=rotate(json.loads((out/'selected/evidence.json').read_text())['eyes'][0]['orientation_xyzw'],[.10,.055,.04])
  reach((start+shift).tolist(),multiply(rotation,q))
  end=np.array(live.state['hands'][1]['position'])
  expected_center=np.array(center)+end-start
  live.capture_to(out/'preview',discard_source=True)
  commit_revision=live.state['scene_revision']
  commit_started=time.monotonic()
  live.send('button',hand=1,button='trigger',pressed=False)
  wait(lambda s:s['status']=='COMMITTED')
  commit_seconds=time.monotonic()-commit_started
  (out/'commit-timing.json').write_text(json.dumps({'release_to_ack_seconds':commit_seconds,'scene_rebuilt':live.state['scene_revision']!=commit_revision,'maximum_seconds':5}))
  assert live.state['scene_revision']==commit_revision,'rigid edit rebuilt all representations'
  assert commit_seconds<5,'rigid edit acknowledgment too slow'
  center_error=float(np.linalg.norm(np.array(live.state['move_handle'])-expected_center))
  (out/'pose-check.json').write_text(json.dumps({'expected_center':expected_center.tolist(),'saved_center':live.state['move_handle'],'error_m':center_error}))
  assert center_error<.002,center_error
  park();live.capture_to(out/'committed',discard_source=True);hold(live,'Saved '+kind+' move and rotation')
  (out/'result.json').write_text(json.dumps(live.state,indent=2))
  from tools.vr_workflows.move_pixels import compare
  pixels=compare(out/'selected',out/'committed',live.state['owner_tokens'][0])
  (out/'pixels.json').write_text(json.dumps(pixels,indent=2))
  assert pixels['passed'],pixels
except Exception:
 (out/'failure-state.json').write_text(json.dumps(live.state,indent=2));raise
