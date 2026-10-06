"""Preserve and diagnose the first v4 image-clearance failure; no new dynamics."""
import os,sys,time,itertools
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree,ConvexHull,distance
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,checked,source
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.gpu_npt_context_v4 import ROOT,ART,N,physical,box_from_xsc,checkpoint,regular_checkpoints,performance,endpoint_reference,statistics,void_witness
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from backend.core.dcd_fast import read_layout,read_frame,cell_to_dimensions
OUT=ART/'cpd-anti-gpu-npt-anti-1-failure-audit-v4'

def gap(x,box):
 tree=cKDTree(x);best=None
 for t in itertools.product([-1,0,1],repeat=3):
  if not any(t):continue
  ds,js=tree.query(x+np.array(t)*box);i=int(ds.argmin())
  if best is None or ds[i]<best['distance_A']:best=dict(distance_A=float(ds[i]),source_atom=i,image_atom=int(js[i]),translation=list(t))
 return best

def run():
 plan=read(OUT/'plan.json');deadline=plan['deadline_epoch']
 for p in plan['inputs']:checked(p)
 records=[];segments=[];previous=ROOT/'anti/replica-1/restart'
 for number in range(1,10):
  f=ROOT/'anti/replica-1/validation'/f'segment-{number:02d}';first=530000+(number-1)*500000
  rows=parse_log(f/'run.log');assert read(f/'native_exit.json')['returncode']==0
  cfg=(f/'run.conf').read_text();log=(f/'run.log').read_text()
  assert 'Running with GPU-resident mode' in log and 'VDW FORCE SWITCHING ACTIVE' in log and 'LANGEVIN PISTON PRESSURE CONTROL ACTIVE' in log
  assert [r['TS'] for r in rows]==list(range(first,first+500001,1000))
  old=parse_log(previous/'run.log')[-1]['POTENTIAL'];restart_error=abs(old-rows[0]['POTENTIAL']);assert restart_error<=max(.01,1e-6*abs(old))
  box,cp=checkpoint(f,first+500000);regular=regular_checkpoints(f,first,first+500000);assert len(regular)==10
  if not (f/'endpoint-reference').exists():
   assert number==9
   endpoint_reference('anti',f,first+500000,44917,rows,deadline,4)
  ref=parse_log(f/'endpoint-reference/run.log')[-1];ed=abs(ref['POTENTIAL']-rows[-1]['POTENTIAL']);assert ed<=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
  layout=read_layout(f/'result.dcd');assert (layout.n_atoms,layout.n_frames,layout.nsavc,layout.istart)==(N,100,5000,first+5000)
  xst={int(r[0]):r[1:10].reshape(3,3) for r in np.atleast_2d(np.loadtxt(f/'result.xst'))};energies={int(r['TS']):r for r in rows}
  chunk=[]
  for i in range(101):
   assert time.time()<deadline
   if i<100:
    x,cell=read_frame(f/'result.dcd',layout,i);dims=cell_to_dimensions(cell);b=np.array(dims[:3]);step=first+(i+1)*5000
    assert np.allclose(dims[3:],90,atol=1e-5) and np.allclose(xst[step],np.diag(b),rtol=0,atol=1e-3)
    assert abs(np.prod(b)-energies[step]['VOLUME'])<1
   else:x=read_binary(f/'result.coor',N);b=box;step=first+500000
   p=physical('anti',x,b,i<100);sol=np.asarray(x[:3043],dtype=float)
   hull=ConvexHull(sol);diameter=float(distance.pdist(sol[hull.vertices]).max())
   witness=gap(sol,b)
   assert abs(witness['distance_A']-p['image_clearance_A'])<1e-8
   variants={}
   for label,delta in [('y+20',[0,20,0]),('xy+20',[20,20,0])]:variants[label]=gap(sol,b+delta)['distance_A']
   r=dict(segment=number,frame=i,step=step,final=i==100,box_A=b.tolist(),physical=p,witness=witness,solute_spans_A=np.ptp(sol,axis=0).tolist(),solute_diameter_A=diameter,virtual_image_clearance_A=variants)
   chunk.append(r)
  save(OUT/f'segment-{number:02d}-frames.json',chunk);records.extend(chunk)
  segments.append(dict(segment=number,native_complete=True,restart_error_kcal=restart_error,endpoint_error_kcal=ed,checkpoints=cp,regular_checkpoint_sets=len(regular),performance=performance(log,500000),late500ps=statistics(rows,1000,250),endpoint_void=void_witness(read_binary(f/'result.coor',N),box)))
  save(OUT/'progress.json',dict(at=now(),segments=segments,geometries=len(records)))
  previous=f
 failures=[r for r in records if not r['physical']['passed']]
 chemistry=[r for r in failures if not r['physical']['geometry']['stereo_passed'] or not r['physical']['geometry']['bond_integrity_passed'] or r['physical']['geometry']['contacts']['severe_clash_count'] or r['physical']['geometry']['contacts']['all_piercing_count'] or r['physical']['min_water_OO_A']<=2 or r['physical']['max_OH_error_beyond_storage_A']>=1e-5]
 assert len(records)==909 and failures
 D=max(r['solute_diameter_A'] for r in records)
 summary=dict(at=now(),audit_complete=True,original_validation_passed=False,all_native_completed=True,geometries=len(records),failed_geometries=len(failures),non_image_failures=len(chemistry),failures=failures,segments=segments,maximum_observed_solute_diameter_A=D,
  rotation_independent_cell_bound=dict(minimum_shortest_lattice_vector_A=D+12,interpretation='For recorded conformations, |lattice vector| minus solute diameter bounds pair-image distances under any rigid rotation. This is not a bound on future conformational expansion or NPT contraction.'),
  virtual_minima_A={label:min(r['virtual_image_clearance_A'][label] for r in records) for label in ['y+20','xy+20']},
  caution='Virtual larger boxes do not establish new solvent states, adequate future sampling, or final readiness. Do not count failed-cell trajectories toward fresh corrected validation.',
  context_deadline_epoch=plan['context_deadline_epoch'],simulation_ready=False,minimum_certified=False)
 save(OUT/'assessment.json',summary)
 service=ART/'cpd-anti-gpu-npt-anti-1-service-v4'
 save(service/'completion_delivery_verified.json',dict(at=now(),token='40f05a7b-05ac-4150-a569-9fd1bd25fa85',event='failed',ack=source(service/'completion_wake_ack.json'),audit=source(OUT/'assessment.json'),original_validation_passed=False,simulation_ready=False,minimum_certified=False))
 print(dict(geometries=len(records),failures=len(failures),non_image_failures=len(chemistry),maximum_diameter_A=D))

if __name__=='__main__':run()
