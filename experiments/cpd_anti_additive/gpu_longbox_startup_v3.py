"""Qualify expanded solvent cell and matched six-replica GPU-resident startup."""
import os,sys,time,subprocess,json,re,traceback,itertools
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry,NAMD
from experiments.cpd_anti_additive.solvated_engine_v3 import geometry_passed
from backend.core.dcd_fast import read_layout,read_frame
ART=REPO/'.development-artifacts';ROOT=ART/'cpd-anti-gpu-longbox-v3'

def dimensions():
 a=read(ROOT/'assembly.json');return np.array(a['box_A']),a['cases'][0]['atoms'],a['waters']

def evaluate(case,x,quantized=False):
 box,n,nw=dimensions();x=np.asarray(x,dtype=float);g=geometry(ROOT/case,x)
 sol=x[:3043];tree=cKDTree(sol);gap=min(float(tree.query(sol+np.array(t)*box)[0].min()) for t in itertools.product([-1,0,1],repeat=3) if any(t))
 w=x[3043:3043+3*nw].reshape(-1,3,3);d=w[:,1:]-w[:,:1];d-=np.rint(d/box)*box;errors=abs(np.linalg.norm(d,axis=2)-.9572)
 half=.5*abs(np.spacing(w.astype(np.float32)).astype(float)) if quantized else np.zeros_like(w)
 bound=np.linalg.norm(half[:,1:]+half[:,:1],axis=2);excess=float(np.maximum(0,errors-bound).max())
 oxygen=w[:,0]%box;dist,_=cKDTree(oxygen,boxsize=box).query(oxygen,k=2);minimum=float(dist[:,1].min())
 return dict(geometry=g,image_clearance_A=gap,min_water_OO_A=minimum,max_OH_error_beyond_storage_A=excess,passed=bool(geometry_passed(g) and gap>12 and minimum>2 and excess<1e-5))

def config(case,coordinates,first=0,seed=41017,checkpoint=None,resident=True):
 box,n,nw=dimensions();folder=ROOT/case
 lines=[f'structure {(folder/"system.psf").resolve()}',f'coordinates {(folder/"system.pdb").resolve()}',f'binCoordinates {coordinates.resolve()}','paraTypeCharmm on']
 names=['par_all36_na.prm','par_all36_cgenff.prm']+(['anti_dna_overlay.prm'] if case=='anti' else [])+['water_ions.prm']
 lines += [f'parameters {(ROOT/"forcefield"/name).resolve()}' for name in names]
 lines += ['exclude scaled1-4','oneFourScaling 1','cutoff 12','switching on','switchdist 10','pairlistdist 14','margin 2','PME yes','PMETolerance 0.000001','PMEGridSpacing 1.0',f'cellBasisVector1 {box[0]} 0 0',f'cellBasisVector2 0 {box[1]} 0',f'cellBasisVector3 0 0 {box[2]}','cellOrigin '+' '.join(str(v/2) for v in box),'wrapAll off','rigidBonds all','useSettle on','rigidTolerance 0.00000001','rigidIterations 200','timestep 2','nonbondedFreq 1','fullElectFrequency 1','stepspercycle 10','GPUresident on' if resident else 'bondedGPU 0','outputName result','DCDfreq 500','restartfreq 500','outputEnergies 500','binaryoutput yes','binaryrestart yes',f'firsttimestep {first}',f'seed {seed}','langevin on','langevinTemp 300','langevinDamping 1','langevinHydrogen off']
 if checkpoint:
  lines += ['binVelocities '+str(Path(str(checkpoint)+'.vel').resolve()),'extendedSystem '+str(Path(str(checkpoint)+'.xsc').resolve())]
 else:lines+=['temperature 0']
 return '\n'.join(lines)+'\n'

def checkpoint(out,step):
 box,n,nw=dimensions();pins=[]
 for ext in ['coor','vel']:
  a=read_binary(out/f'result.{ext}',n);b=read_binary(out/f'result.restart.{ext}',n);assert np.array_equal(a,b);pins.append(source(out/f'result.restart.{ext}'))
 xsc=np.loadtxt(out/'result.restart.xsc');assert xsc[0]==step and np.array_equal(xsc,np.loadtxt(out/'result.xsc')) and np.allclose(xsc[[1,5,9]],box,rtol=0,atol=1e-10)
 return pins+[source(out/'result.restart.xsc')]

def review(case,out,first,frames):
 box,n,nw=dimensions();layout=read_layout(out/'result.dcd');assert layout.n_atoms==n and layout.n_frames==frames and layout.nsavc==500 and layout.istart==first+500
 records=[]
 for i in range(frames+1):
  x=read_frame(out/'result.dcd',layout,i)[0] if i<frames else read_binary(out/'result.coor',n)
  r=evaluate(case,x,i<frames);r.update(frame=i,final=i==frames);records.append(r)
  if not r['passed']:
   save(out/'failed_frame_review.json',records);raise RuntimeError(f'Geometry/water/image failure at {out} frame{i}')
 save(out/'frames_review.json',records);cp=checkpoint(out,first+500*frames)
 return dict(passed=True,frames=frames,checkpoints=cp,log=source(out/'run.log'),trajectory=source(out/'result.dcd'),review=source(out/'frames_review.json'),minimum_clearance_A=min(r['image_clearance_A'] for r in records),minimum_water_OO_A=min(r['min_water_OO_A'] for r in records))

def run():
 plan=read(ROOT/'startup_plan.json')
 for p in plan['inputs']:checked(p)
 assert read(checked(plan['gpu_native_audit']))['passed']
 assert not read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
 start=time.time();deadline=min(start+7200,plan['context_deadline_epoch']);box,n,nw=dimensions()
 with (ROOT/'startup_started.json').open('x') as f:json.dump(dict(at=now(),deadline_epoch=deadline,plan=source(ROOT/'startup_plan.json')),f)
 def native(out,cfg,resident=True):
  assert time.time()<deadline;out.mkdir(parents=True,exist_ok=False);(out/'run.conf').write_text(cfg)
  with (out/'run.log').open('w') as log:
   proc=subprocess.run([str(NAMD),'+p4','+devices','0','run.conf'],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=deadline-time.time())
  save(out/'native_exit.json',dict(at=now(),returncode=proc.returncode));assert proc.returncode==0
  assert ('Running with GPU-resident mode' in (out/'run.log').read_text())==resident
  return parse_log(out/'run.log')
 reports=[]
 try:
  for case in ['anti','control']:
   initial=evaluate(case,read_binary(ROOT/case/'start.coor',n));save(ROOT/case/'initial_check.json',initial)
   assert geometry_passed(initial['geometry']) and initial['image_clearance_A']>12 and initial['min_water_OO_A']>1.5 and initial['max_OH_error_beyond_storage_A']<1e-5
   energies=[];forces=[]
   for mode in ['reference','resident']:
    out=ROOT/case/f'static-{mode}';rows=native(out,config(case,ROOT/case/'start.coor',resident=mode=='resident')+'run 0\noutput onlyforces result\n',mode=='resident');energies.append(rows[-1]['POTENTIAL']);forces.append(read_binary(out/'result.force',n))
   de=abs(energies[0]-energies[1]);df=float(abs(forces[0]-forces[1]).max());el=max(.001,1e-4*abs(energies[0]));fl=max(.001,1e-4*float(abs(forces[0]).max()))
   save(ROOT/case/'static_assessment.json',dict(energy_error_kcal=de,force_error_kcal_A=df,energy_limit_kcal=el,force_limit_kcal_A=fl,passed=bool(de<=el and df<=fl)));assert de<=el and df<=fl
   out=ROOT/case/'minimize';native(out,config(case,ROOT/case/'start.coor')+'minimize 1000\noutput result.restart\noutput result\n')
   result=evaluate(case,read_binary(out/'result.coor',n));save(out/'geometry.json',result);assert result['passed']
  for rep,seed in enumerate(plan['paired_seeds'],1):
   for case in ['anti','control']:
    folder=ROOT/case/f'replica-{rep}';out=folder/'startup';cfg=config(case,ROOT/case/'minimize/result.coor',seed=seed)+'reinitvels 50\n'
    for target in range(75,301,25):cfg+=f'langevinTemp {target}\nrun 2500\n'
    rows=native(out,cfg+'run 25000\noutput result.restart\noutput result\n');report=review(case,out,0,100)
    restart=folder/'restart';rr=native(restart,config(case,out/'result.restart.coor',50000,seed+1000,out/'result.restart')+'run 5000\noutput result.restart\noutput result\n');rreview=review(case,restart,50000,10)
    delta=abs(rr[0]['POTENTIAL']-rows[-1]['POTENTIAL']);limit=max(.01,1e-6*abs(rows[-1]['POTENTIAL']));assert delta<=limit
    # Independent endpoint replay catches resident saved-state corruption early.
    ref=folder/'endpoint-reference';refrows=native(ref,config(case,restart/'result.restart.coor',55000,seed+1000,restart/'result.restart',False)+'run 0\n',False)
    edelta=abs(refrows[-1]['POTENTIAL']-rr[-1]['POTENTIAL']);elimit=max(.01,1e-6*abs(rr[-1]['POTENTIAL']));assert edelta<=elimit
    sec=float(re.findall(r'WallClock:\s*([\d.]+)',(out/'run.log').read_text())[-1]);reports.append(dict(case=case,replica=rep,seed=seed,native_100ps_seconds=sec,startup=report,restart=rreview,restart_energy_error_kcal=delta,endpoint_reference_error_kcal=edelta))
    save(ROOT/'progress.json',dict(at=now(),completed=reports))
  save(ROOT/'startup_assessment.json',dict(at=now(),passed=True,results=reports,elapsed_seconds=time.time()-start,simulation_ready=False,minimum_certified=False,context_validation_pending=True))
 except BaseException:
  (ROOT/'failure_traceback.txt').write_text(traceback.format_exc());save(ROOT/'startup_assessment.json',dict(at=now(),passed=False,results=reports,simulation_ready=False));raise

if __name__=='__main__':run()
