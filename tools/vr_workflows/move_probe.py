"""Physical trigger editing; read-only native targets guide noisy controller paths."""
import json,sys,os,time
from pathlib import Path
from urllib.parse import unquote
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.model import multiply
from tools.vr_workflows.extrude_sidebar import SidebarControls
from tools.vr_workflows.profile_input import reach_target, aim_orientation
from tools.vr_workflows.demo_view import reveal,hold
from tools.vr_workflows.audit_intervals import operation
socket,output,kind,before_path,mode=sys.argv[1:6]
out=Path(output);out.mkdir(parents=True,exist_ok=True)
bridge=Bridge(socket)
deadline=time.monotonic()+30
while True:
 try:
  state=bridge.call('scrywrite_observe',{})
  if state.get('focused') and not state.get('startup',{}).get('active',False):break
 except OSError:pass
 if time.monotonic()>deadline:raise RuntimeError('Viewer did not become focused with initial geometry ready')
 time.sleep(.1)
live=LiveSession(bridge,physical=True,allow_transactions=True)
from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation
if mode != 'edit': prepare_audit_representation(live)
preset=os.environ.get('NADOC_VR_PROFILE','steady_fast')
controls=SidebarControls(live,out,preset);trials=[]
def wait(predicate):
 deadline=time.monotonic()+90
 while not predicate(live.state):
  if live.state.get('status','').endswith(('FAILED','REFUSED')):raise RuntimeError('Authoring operation failed: '+live.state['status'])
  if time.monotonic()>deadline:raise RuntimeError('Timed out: '+str(live.state))
  try:live.frame()
  except TimeoutError:continue # read-only observation during authoritative snapshot upload
  time.sleep(.05)
def reach(position,orientation=None,acquired=None,hand=1):
 trials.append(reach_target(live,position,preset,3000+len(trials),target_position=position,target_orientation=orientation or [0,0,0,1],acquired=acquired,hand=hand))
 (out/'reaches.json').write_text(json.dumps(trials,indent=2))
def park():
 p=np.array(live.state['head_position'])+[0,-1,0]
 for h in (0,1):live.send('pose',hand=h,position=p.tolist(),orientation=[0,0,0,1])
 live.frame()
try:
 reveal(live)
 # Physical controllers can be asleep at launch. Establish the owned synthetic
 # poses before the first menu button; invalid hands cannot open a sidebar.
 for hand,offset in ((0,-.3),(1,.3)):
  live.send('pose',hand=hand,position=(np.array(live.state['head_position'])+[offset,-.25,-.4]).tolist(),orientation=[0,0,0,1])
 live.frame()
 assert all(h['valid'] for h in live.state['hands']), 'Synthetic hand poses were not applied'
 if mode=='undo':
  if not live.state['sidebars'][1]['open']:live.button('menu',hand=1);live.frame()
  controls.click('move:undo');wait(lambda s:s['status']=='UNDONE')
  park();live.capture_to(out/'undone',discard_source=True)
 else:
  if not live.state['sidebars'][1]['open']:live.button('menu',hand=1);live.frame()
  if os.environ.get('NADOC_VR_MOVE_DIRECT_ACTIVATION')=='1':
   live.send('activate',tool='move_rotate');live.frame()
   (out/'activation.json').write_text(json.dumps({'method':'semantic setup','menu_acquisition_validated':False}))
  else:controls.click('tab:tools');controls.click('tool-move')
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
  controls.click('move:'+('domain' if kind=='overhang' else kind))
  live.capture_to(out/'selection-options',discard_source=True)
  before=json.loads(Path(before_path).read_text())
  cluster=(max(before['design']['cluster_transforms'],key=lambda c:len(c['helix_ids'])) if os.environ.get('NADOC_VR_AUDIT_DESIGN') else next((c for c in before['design']['cluster_transforms'] if c['name']=='Movable helix'),None))
  geom=before['geometry']
  allowed=[n for n in geom if (n.get('overhang_id') if kind=='overhang' else n['helix_id'] in cluster['helix_ids'] if kind=='cluster' else not n.get('overhang_id'))]
  prior={(t['helix_id'],t['bp_index'],t['direction']) for t in before['design'].get('nucleotide_transforms',[])}
  if kind=='base':allowed=[n for n in allowed if (n['helix_id'],n['bp_index'],n['direction']) not in prior]
  live.button('menu',hand=1);live.frame()
  park();live.capture_to(out/'before-framing',discard_source=True)
  from tools.vr_workflows.review_view import improve_review
  review=improve_review(live,out/'before-framing',out/'review-view')
  if os.environ.get('NADOC_VR_MOVE_DESIGN') or os.environ.get('NADOC_VR_AUDIT_DESIGN'):
   from tools.vr_workflows.profile_input import zoom_scene
   center=review['orientation']['target']
   zoom_scene(live,[center[0],center[1]+.25,center[2]],2)
   (out/'selection-view.json').write_text(json.dumps({'additional_zoom':2,'reason':'Expose individual bases in the dense origami'}))
  park();live.capture_to(out/'acquisition-view',discard_source=True)
  objects=json.loads((out/'acquisition-view/objects.json').read_text())
  counts=[np.bincount(np.fromfile(out/f'acquisition-view/{eye}.ids.u32',dtype=np.uint32)) for eye in ('left','right')]
  visible_owners=[]
  for count in counts:
   visible_owners.append({t for o in objects if o['id']<len(count) and count[o['id']]>=4 for t in o['owner_tokens'] if unquote(t).startswith('["base",')})
  exposed=visible_owners[0]&visible_owners[1]
  owners={o['identity']:set(o['owner_tokens']) for o in objects}

  targets=live.state['move_targets']
  matches=[p for p in targets if any(f":{n['helix_id']}:{n['bp_index']}:{n['direction']}:" in unquote(p['identity']) for n in allowed)]
  assert matches,'no rendered target candidates'
  # Approach actual backbone points, then click. Selection is browser-authoritative.
  if kind=='base':matches=[p for p in matches if owners.get(p['identity'],set())&exposed]
  assert matches,'No candidate base visible in both eyes'
  candidates=sorted(matches,key=lambda p:np.linalg.norm(np.array(p['world'])-live.state['head_position']))
  acquisitions=[]
  for target in candidates[:24]:
   reach((np.array(target['world'])+[0,0,.12]).tolist(),hand=0)
   live.send('trigger_value',hand=0,value=.5);live.frame()
   acquisitions.append({'target':target,'hover':live.state.get('scene_hover')})
   (out/'acquisition.json').write_text(json.dumps(acquisitions,indent=2))
   if (live.state.get('scene_hover') or '').startswith('nuc:') and (kind!='base' or owners.get(live.state['scene_hover'],set())&exposed):break
   live.send('trigger_value',hand=0,value=0);live.frame()
  else:raise RuntimeError('No nucleotide hover acquired without selecting a crossover')
  live.button('trigger',hand=0)
  live.send('trigger_value',hand=0,value=0);live.frame()
  wait(lambda s:s['selection_kind']==kind and s['move_handle'] is not None)
  if os.environ.get('NADOC_VR_AUDIT_REPRESENTATION'):
   prepare_audit_representation(live)
   (out/'representation-setup.json').write_text(json.dumps({'selection_representation':'full','edit_representation':live.state['representation'],'native_atomistic_selection_validated':False}))
  park();live.capture_to(out/'selected',discard_source=True);hold(live,'Selected '+kind)
  center=live.state['move_handle']
  # Point at a selected molecular point, not the potentially empty group centroid.
  aim=next((p['world'] for p in live.state['move_targets'] if p['identity']==acquisitions[-1]['hover']),center)
  if live.state['representation'] != 'full':
   from tools.vr_workflows.move_pixels import centers
   a,selected=centers(out/'selected','left',live.state['owner_tokens'][0])
   b,_=centers(out/'selected','right',live.state['owner_tokens'][0])
   common=a.keys() & b.keys() & selected
   assert common,'Selected molecular geometry is not visible in both eyes'
   aim=a[min(common,key=lambda i:np.linalg.norm(a[i]-center))].tolist()
  # Put the pointing hand on the observer's side of the model, with a
  # lateral offset so the beam is visible rather than hidden behind geometry.
  from tools.vr_motion.metrics import rotate
  eye=json.loads((out/'selected/evidence.json').read_text())['eyes'][0]
  toward=np.array(live.state['head_position'])-np.array(aim);toward/=np.linalg.norm(toward)
  toward+=np.array(rotate(eye['orientation_xyzw'],[.4,-.15,0]));toward/=np.linalg.norm(toward)
  pointing=(np.array(aim)+toward*.45).tolist()
  (out/'pointing-approach.json').write_text(json.dumps({'target':aim,'position':pointing,'distance_m':.45,'reason':'Observer-side hand with lateral beam visibility'}))
  reach(pointing,aim_orientation(pointing,aim),acquired=lambda s:s['move_nearby'])
  assert live.state['move_nearby'] and live.state['move_beam_end'] is not None,'selected geometry was not pointed at'
  assert np.linalg.norm(np.array(live.state['hands'][1]['position'])-live.state['move_beam_end'])>.15,'grab was not remote'
  live.capture_to(out/'pointed',discard_source=True)
  live.send('button',hand=1,button='trigger',pressed=True);live.frame()
  assert live.state['move_grabbing'],'trigger did not acquire target'
  start=np.array(live.state['hands'][1]['position']);q=live.state['hands'][1]['orientation_xyzw']
  rotation=[0,0,np.sin(np.pi/12),np.cos(np.pi/12)]
  from tools.vr_motion.metrics import rotate
  shift=rotate(json.loads((out/'selected/evidence.json').read_text())['eyes'][0]['orientation_xyzw'],[.10,.055,.04])
  preview_start=time.time()*1000
  preview_first_frame=live.state['frame']
  preview_completed=False
  try:
   reach((start+shift).tolist(),multiply(rotation,q))
   preview_completed=True
  finally:
   (out/'preview-interval.json').write_text(json.dumps({'start_ms':preview_start,'end_ms':time.time()*1000,
    'first_frame':preview_first_frame,'last_frame':live.state['frame'],'preset':preset,'representation':live.state['representation'],
    'completed':preview_completed}))
  end=np.array(live.state['hands'][1]['position'])
  expected_center=np.array(center)+end-start
  live.capture_to(out/'preview',discard_source=True)
  commit_revision=live.state['scene_revision']
  commit_started=time.monotonic()
  with operation(live,'move-commit'):
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
  pixels=compare(out/'selected',out/'committed',live.state['owner_tokens'][0],
      entire_scene=kind=='cluster' and all(n['helix_id'] in cluster['helix_ids'] for n in geom))
  (out/'pixels.json').write_text(json.dumps(pixels,indent=2))
  assert pixels['passed'],pixels
except Exception:
 (out/'failure-state.json').write_text(json.dumps(live.state,indent=2));raise
