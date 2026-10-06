"""Preserve/replay failed validation and assess virtual cells; no new dynamics."""
import os,sys,time,itertools,subprocess,traceback
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
REPO=Path(os.environ['NADOC_REPO_ROOT']);sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.gpu_largebox_startup_v3 import *
from experiments.cpd_anti_additive.gpu_largebox_validation_v3 import observables
OUT=ART/'cpd-anti-gpu-largebox-failure-audit-v3'

def run():
 plan=read(OUT/'plan.json')
 for pin in plan['inputs']:checked(pin)
 for pin in read(ROOT/'validation_plan.json')['inputs']:checked(pin)
 deadline=min(time.time()+3600,plan['context_deadline_epoch'])
 box,n,nw=dimensions();spec=read(ROOT/'observables_registration.json');reports=[]
 cells=[box+np.array([0,0,20]),box+np.array([0,0,40]),box+20]
 for entry in plan['segments']:
  case=entry['case'];path=Path(entry['path']);rows=parse_log(path/'run.log');first=entry['first'];last=first+500000
  assert rows[0]['TS']==first and rows[-1]['TS']==last
  assert 'Running with GPU-resident mode' in (path/'run.log').read_text()
  cp=checkpoint(path,last);layout=read_layout(path/'result.dcd')
  assert (layout.n_atoms,layout.n_frames,layout.nsavc,layout.istart)==(n,100,5000,first+5000)
  records=[]
  for i in range(101):
   assert time.time()<deadline
   x=read_frame(path/'result.dcd',layout,i)[0].astype(float) if i<100 else read_binary(path/'result.coor',n)
   physical=evaluate(case,x,i<100);spans=np.ptp(x[:3043],axis=0);tree=cKDTree(x[:3043]);virtual=[]
   for cell in cells:
    lower=float(np.min(cell-spans))
    # Axis-span lower bound is conservative; otherwise use explicit 26 images.
    gap=lower if lower>12 else min(float(tree.query(x[:3043]+np.array(t)*cell)[0].min()) for t in itertools.product([-1,0,1],repeat=3) if any(t))
    virtual.append(dict(box_A=cell.tolist(),clearance_bound_or_exact_A=gap,conservative_bound=lower>12,passed=gap>12))
   records.append(dict(frame=i,final=i==100,step=first+min(i+1,100)*5000,physical=physical,spans_A=spans.tolist(),virtual_cells=virtual,observables=observables(x,spec,case)))
  target=OUT/f"{case}-r{entry['replica']}-s{entry['segment']}";target.mkdir(exist_ok=False)
  save(target/'frames.json',records)
  ref=path/'endpoint-reference'
  if not ref.exists():
   ref=target/'endpoint-reference';ref.mkdir()
   (ref/'run.conf').write_text(config(case,path/'result.restart.coor',last,41017,path/'result.restart',False)+'run 0\n')
   with (ref/'run.log').open('w') as log:
    proc=subprocess.run([str(NAMD),'+p4','+devices','0','run.conf'],cwd=ref,stdout=log,stderr=subprocess.STDOUT,timeout=max(.01,deadline-time.time()))
   save(ref/'native_exit.json',dict(returncode=proc.returncode));assert proc.returncode==0
  refrows=parse_log(ref/'run.log');de=abs(refrows[-1]['POTENTIAL']-rows[-1]['POTENTIAL']);limit=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
  previous=path.parent.parent/'restart' if entry['segment']==1 else path.parent/f"segment-{entry['segment']-1:02d}"
  prev=parse_log(previous/'run.log');restart_error=abs(rows[0]['POTENTIAL']-prev[-1]['POTENTIAL']);restart_limit=max(.01,1e-6*abs(prev[-1]['POTENTIAL']))
  failures=[dict(frame=r['frame'],step=r['step'],physical=r['physical']) for r in records if not r['physical']['passed']]
  reports.append(dict(**entry,frames=source(target/'frames.json'),checkpoints=cp,failed_geometries=failures,minimum_clearance_A=min(r['physical']['image_clearance_A'] for r in records),water_passed=all(r['physical']['min_water_OO_A']>2 and r['physical']['max_OH_error_beyond_storage_A']<1e-5 for r in records),solute_passed=all(geometry_passed(r['physical']['geometry']) for r in records),endpoint_energy_error=de,endpoint_energy_limit=limit,endpoint_energy_passed=de<=limit,restart_energy_error=restart_error,restart_energy_passed=restart_error<=restart_limit,virtual_cells_passed=[all(r['virtual_cells'][j]['passed'] for r in records) for j in range(3)]))
  save(OUT/'progress.json',dict(at=now(),completed=reports))
 save(OUT/'assessment.json',dict(at=now(),audit_complete=True,results=reports,virtual_cells_A=[c.tolist() for c in cells],virtual_cells_all_frames_passed=[all(r['virtual_cells_passed'][j] for r in reports) for j in range(3)],limitations='Virtual cell clearance only; no new packing, dynamics or future-clearance guarantee. Original failed trajectories remain failed. No minimum or readiness certification.',simulation_ready=False,minimum_certified=False))
if __name__=='__main__':
 try:run()
 except BaseException:
  (OUT/'failure_traceback.txt').write_text(traceback.format_exc());raise
