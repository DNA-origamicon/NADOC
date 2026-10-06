"""Bounded GPU-resident ensemble diagnostic; never promotes production readiness."""
import os,sys,time,subprocess,itertools,traceback
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.gpu_longbox_startup_v3 import ROOT as SOURCE,ART,NAMD,config,dimensions,geometry,geometry_passed
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from backend.core.dcd_fast import read_layout,read_frame,cell_to_dimensions
OUT=ART/'cpd-anti-gpu-force-switch-qualification-v3'
PRIOR=ART/'cpd-anti-gpu-ensemble-diagnostic-v3-r1'
N,NW=dimensions()[1:]

def box_from_xsc(path):
 r=np.loadtxt(path);assert r.ndim==1 and r.size>=13 and np.isfinite(r).all()
 basis=r[1:10].reshape(3,3);box=np.diag(basis)
 assert np.all(box>28) and np.max(abs(basis-np.diag(box)))<1e-8
 return box,r

def make_config(case,cp,first,seed,npt,resident=True):
 text=config(case,Path(str(cp)+'.coor'),first,seed,cp,resident)
 drop={'cellBasisVector1','cellBasisVector2','cellBasisVector3','cellOrigin','PMEGridSpacing'}
 lines=[l for l in text.splitlines() if l.split()[0] not in drop]
 text='\n'.join(lines)+'\n'
 for k,v in [('DCDfreq','1000'),('restartfreq','50000'),('outputEnergies','1000')]:text=text.replace(k+' 500\n',k+' '+v+'\n')
 text+='PMEGridSizeX 72\nPMEGridSizeY 88\nPMEGridSizeZ 144\nDCDunitcell yes\nXSTfreq 1000\nuseGroupPressure yes\nuseFlexibleCell no\nuseConstantArea no\nvdwForceSwitching on\n'
 text+='LangevinPiston '+('on' if npt else 'off')+'\n'
 if npt:text+='LangevinPistonTarget 1.01325\nLangevinPistonPeriod 200\nLangevinPistonDecay 100\nLangevinPistonTemp 300\n'
 return text

def physical(case,x,box,quantized):
 x=np.asarray(x,dtype=float);assert x.shape==(N,3) and np.isfinite(x).all()
 g=geometry(SOURCE/case,x);sol=x[:3043];tree=cKDTree(sol)
 gap=min(float(tree.query(sol+np.array(t)*box)[0].min()) for t in itertools.product([-1,0,1],repeat=3) if any(t))
 w=x[3043:3043+3*NW].reshape(-1,3,3);d=w[:,1:]-w[:,:1];d-=np.rint(d/box)*box
 err=abs(np.linalg.norm(d,axis=2)-.9572);half=.5*abs(np.spacing(w.astype(np.float32)).astype(float)) if quantized else np.zeros_like(w)
 excess=float(np.maximum(0,err-np.linalg.norm(half[:,1:]+half[:,:1],axis=2)).max())
 oo=float(cKDTree(w[:,0]%box,boxsize=box).query(w[:,0]%box,k=2)[0][:,1].min())
 return dict(geometry=g,image_clearance_A=gap,min_water_OO_A=oo,max_OH_error_beyond_storage_A=excess,passed=bool(geometry_passed(g) and gap>12 and oo>2 and excess<1e-5))

def void_witness(x,box):
 axes=[np.arange(0,v,2.) for v in box];points=np.array(np.meshgrid(*axes,indexing='ij')).reshape(3,-1).T
 distances=cKDTree(x%box,boxsize=box).query(points)[0];i=int(distances.argmax())
 return dict(sampled_max_nearest_atom_A=float(distances[i]),point_A=points[i].tolist(),grid_max_spacing_A=2.,caution='Witness radius only; no continuum maximum or universal physical acceptance cutoff')

def verify_checkpoint(out,step):
 for ext in ['coor','vel']:assert np.array_equal(read_binary(out/f'result.{ext}',N),read_binary(out/f'result.restart.{ext}',N))
 box,r=box_from_xsc(out/'result.restart.xsc');assert r[0]==step and np.array_equal(r,np.loadtxt(out/'result.xsc'))
 return box,[source(out/f'result.restart.{ext}') for ext in ['coor','vel','xsc']]

def summarize(rows,window_samples,block_samples,mass):
 # Use instantaneous2ps samples; this GPU build AVG fields are overlapping rolling averages.
 rows=rows[-window_samples:];blocks=[]
 for i in range(0,len(rows),block_samples):
  part=rows[i:i+block_samples]
  if len(part)!=block_samples:continue
  blocks.append(dict(first_step=part[0]['TS'],last_step=part[-1]['TS'],temperature_K=float(np.mean([r['TEMP'] for r in part])),group_pressure_bar=float(np.mean([r['GPRESSURE'] for r in part])),volume_A3=float(np.mean([r['VOLUME'] for r in part])),total_density_g_cm3=float(np.mean([mass*1.66053906660/r['VOLUME'] for r in part]))))
 return dict(blocks=blocks,window_samples=len(rows),block_samples=block_samples,interpretation='Nonoverlapping blocks of instantaneous2ps samples report drift/spread; GPUresident AVG rolling buffers are not interval averages. No equilibrium certification from duration or pressure control; correlation may persist between blocks.')

def run():
 plan=read(OUT/'plan.json')
 admission=read(OUT/'prior_audit_admission.json');checked(admission['plan'])
 assert read(checked(admission['native_audit']))['native_and_geometry_replay_passed']
 for pin in plan['inputs']:checked(pin)
 assert read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused'],'Production hold must stay active'
 deadline=min(time.time()+plan['hard_seconds'],plan['context_deadline_epoch'],plan['diagnostic_deadline_epoch']);reports=[]
 def native(out,cfg,resident=True):
  # NAMD emits ETITLE only each10 energy outputs; all static counters are multiples5000.
  # The500step static cadence guarantees an explicit native header without advancing MD.
  if any(line.strip()=='run 0' for line in cfg.splitlines()):cfg=cfg.replace('outputEnergies 1000\n','outputEnergies 500\n')
  out.mkdir(parents=True,exist_ok=False);(out/'run.conf').write_text(cfg)
  with (out/'run.log').open('w') as f:
   p=subprocess.run([str(NAMD),'+p4','+devices','0','run.conf'],cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=max(.01,deadline-time.time()))
  save(out/'native_exit.json',dict(at=now(),returncode=p.returncode));assert p.returncode==0
  native_text=(out/'run.log').read_text()
  assert ('Running with GPU-resident mode' in native_text)==resident
  assert ('LANGEVIN PISTON PRESSURE CONTROL ACTIVE' in native_text)==('LangevinPiston on\n' in cfg)
  assert ('VDW FORCE SWITCHING ACTIVE' in native_text)==('vdwForceSwitching on\n' in cfg)
  return parse_log(out/'run.log')
 for case in ['anti','control']:
  cp=SOURCE/case/'replica-1/restart/result.restart';first=55000;previous=parse_log(PRIOR/case/'static-on-resident/run.log')[-1]['POTENTIAL'];seed=77117
  # Frozen same-coordinate force-switch static comparisons were already completed.
  assert all(r['passed'] for r in read(PRIOR/case/'static_assessment.json'))
  for stage,steps,npt in [('npt',500000,True),('npt-restart',5000,True)]:
   assert read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
   out=OUT/case/stage;rows=native(out,make_config(case,cp,first,seed,npt)+f'run {steps}\noutput result.restart\noutput result\n')
   assert [r['TS'] for r in rows]==list(range(first,first+steps+1,1000)),'Energy cadence mismatch'
   delta=abs(rows[0]['POTENTIAL']-previous);limit=max(.01,1e-6*abs(previous));assert delta<=limit
   final_box,pins=verify_checkpoint(out,first+steps);layout=read_layout(out/'result.dcd');frames=steps//1000
   assert (layout.n_atoms,layout.n_frames,layout.nsavc,layout.istart)==(N,frames,1000,first+1000)
   xst=np.atleast_2d(np.loadtxt(out/'result.xst'));cells={int(r[0]):r[1:10].reshape(3,3) for r in xst};energies={int(r['TS']):r for r in rows};record=[];voids=[]
   initial_box,_=box_from_xsc(Path(str(cp)+'.xsc'))
   assert np.isfinite(xst).all()
   for basis in cells.values():assert np.all(np.diag(basis)>28) and np.max(abs(basis-np.diag(np.diag(basis))))<1e-8
   for i in range(frames+1):
    assert time.time()<deadline
    if i<frames:
     x,cell=read_frame(out/'result.dcd',layout,i);dims=cell_to_dimensions(cell);assert dims is not None and np.allclose(dims[3:],90,atol=1e-5)
     box=np.array(dims[:3],dtype=float);step=first+(i+1)*1000;assert np.allclose(np.diag(cells[step]),box,rtol=0,atol=1e-3)
    else:
     x=read_binary(out/'result.coor',N);box=final_box;step=first+steps
     last_x,last_cell=read_frame(out/'result.dcd',layout,frames-1)
     assert np.allclose(cell_to_dimensions(last_cell)[:3],box,rtol=0,atol=1e-3)
     storage=.5*abs(np.spacing(last_x).astype(float))+1e-10
     assert np.all(abs(x-last_x.astype(float))<=storage),'Final DCD/binary coordinate mismatch'
    assert np.allclose(box/box[0],initial_box/initial_box[0],rtol=0,atol=1e-5),'Nonisotropic cell change'
    if i<frames:assert abs(float(np.prod(box))-energies[step]['VOLUME'])<1.0,'DCD/native volume mismatch'
    r=physical(case,x,box,i<frames);r.update(frame=i,step=step,box_A=box.tolist(),final=i==frames);record.append(r)
    if i==frames or (i+1)%25==0:voids.append(dict(step=step,**void_witness(np.asarray(x,dtype=float),box)))
    if not r['passed']:save(out/'failed_frame_review.json',record);raise RuntimeError(f'Physical gate failed: {case}/{stage}/frame{i}')
   save(out/'frames_review.json',record);save(out/'void_diagnostics.json',voids)
   ref=out/'endpoint-reference';refrows=native(ref,make_config(case,out/'result.restart',first+steps,seed,False,False)+'run 0\n',False)
   edelta=abs(refrows[-1]['POTENTIAL']-rows[-1]['POTENTIAL']);elimit=max(.01,1e-6*abs(rows[-1]['POTENTIAL']));assert edelta<=elimit
   summary=summarize(rows[1:],250 if stage=='npt' else frames,25 if stage!='npt-restart' else 5,plan['mass_Da'])
   report=dict(case=case,stage=stage,first_step=first,last_step=first+steps,native_and_chemistry_passed=True,checkpoints=pins,restart_error_kcal=delta,endpoint_error_kcal=edelta,endpoint_limit_kcal=elimit,statistics=summary,maximum_void_witness_A=max(v['sampled_max_nearest_atom_A'] for v in voids),final_box_A=final_box.tolist())
   save(out/'assessment.json',report);reports.append(report);save(OUT/'progress.json',dict(at=now(),completed=reports))
   cp=out/'result.restart';first+=steps;previous=rows[-1]['POTENTIAL'];seed+=100
 save(OUT/'assessment.json',dict(at=now(),diagnostic_complete=True,native_and_chemistry_passed=True,results=reports,physical_interpretation_pending=True,force_switch_method_selected_before_acquisition=True,force_switch_dynamic_review_pending=True,production_hold_remains=True,simulation_ready=False,minimum_certified=False))

if __name__=='__main__':
 try:run()
 except BaseException:
  (OUT/'failure_traceback.txt').write_text(traceback.format_exc());save(OUT/'assessment.json',dict(at=now(),diagnostic_complete=False,simulation_ready=False,minimum_certified=False,production_hold_remains=True));raise
