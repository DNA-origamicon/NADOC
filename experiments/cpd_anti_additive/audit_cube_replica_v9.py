"""Audit an uninterrupted final-cube ten-nanosecond replica."""
import json,os,sys
from pathlib import Path
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.gpu_cube_preparation_v6 import load_engine
from experiments.cpd_anti_additive.sella_pilot import save,now


def audit(output,case,rep):
 root=REPO/'.development-artifacts/cpd-anti-gpu-cube-context-v5';art=REPO/'.development-artifacts'
 service=art/f'cpd-anti-cube-validation-{case}-{rep}-service-v6';plan=read(root/f'validation_{case}_{rep}_v6.json');m=load_engine(plan)
 for pin in plan['inputs']:checked(pin)
 state=read(service/'status.json');assert state['returncode']==0 and state['state']=='complete'
 series=[]
 pins=plan['inputs']+[source(service/'status.json'),source(Path(__file__))];reports=[];allblocks=[]
 for segment in range(1,11):
  f=root/case/f'replica-{rep}'/'validation'/f'segment-{segment:02d}';firststep=530000+(segment-1)*500000;last=firststep+500000
  a=read(f/'assessment.json');assert a['native_and_registered_geometry_passed']
  rows=m.parse_log(f/'run.log');assert sorted(set(r['TS'] for r in rows))==list(range(firststep,last+1,1000))
  for folder in [f,f/'endpoint-reference']:
   assert read(folder/'native_exit.json')['returncode']==0
   cfg=(folder/'run.conf').read_text();log=(folder/'run.log').read_text()
   assert ('Running with GPU-resident mode' in log)==('GPUresident on\n' in cfg)
   assert 'VDW FORCE SWITCHING ACTIVE' in log
   assert ('LANGEVIN PISTON PRESSURE CONTROL ACTIVE' in log)==('LangevinPiston on\n' in cfg)
   for axis in 'XYZ':assert f'PMEGridSize{axis} 144\n' in cfg
   pins += [source(folder/n) for n in ['run.conf','run.log','native_exit.json']]
  cfg=dict((l.split()[0],' '.join(l.split()[1:])) for l in (f/'run.conf').read_text().splitlines())
  previous=m.parse_log(Path(cfg['binCoordinates']).parent/'run.log')[-1]['POTENTIAL']
  assert abs(rows[0]['POTENTIAL']-previous)<=max(.01,1e-6*abs(previous))
  ref=m.parse_log(f/'endpoint-reference/run.log')[-1];assert ref['TS']==last
  assert abs(ref['POTENTIAL']-rows[-1]['POTENTIAL'])<=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
  layout=m.read_layout(f/'result.dcd');assert (layout.n_atoms,layout.n_frames,layout.istart,layout.nsavc)==(m.N,100,firststep+5000,5000)
  cells={int(r[0]):r[1:10].reshape(3,3) for r in np.atleast_2d(np.loadtxt(f/'result.xst'))};energies={int(r['TS']):r for r in rows};samples=[]
  for i in range(100):
   x,cell=m.read_frame(f/'result.dcd',layout,i);dims=m.cell_to_dimensions(cell);step=firststep+(i+1)*5000;box=np.array(dims[:3])
   assert np.allclose(dims[3:],90) and np.allclose(cells[step],np.diag(box),rtol=0,atol=1e-3)
   assert abs(np.prod(box)-energies[step]['VOLUME'])<1
   if step%50000==0:
    cp=f/f'checkpoint.{step}';b,r=m.box_from_xsc(Path(str(cp)+'.xsc'));assert r[0]==step and np.allclose(b,box,atol=1e-3)
    coor=m.read_binary(Path(str(cp)+'.coor'),m.N);vel=m.read_binary(Path(str(cp)+'.vel'),m.N);assert np.isfinite(vel).all()
    assert np.all(abs(coor-x.astype(float))<=.5*abs(np.spacing(x).astype(float))+1e-10)
   if i in {0,50,99}:
    g=m.physical(case,x,box,True);assert g['passed'];samples.append(dict(frame=i,geometry=g))
  b,p=m.checkpoint(f,last);end=m.read_binary(f/'result.coor',m.N);g=m.physical(case,end,b);assert g['passed']
  assert np.allclose(b,box,rtol=0,atol=1e-3) and np.all(abs(end-x.astype(float))<=.5*abs(np.spacing(x).astype(float))+1e-10)
  for pin in a['checkpoints']:checked(pin);pins.append(pin)
  assert len(a['regular_checkpoints'])==10
  for record in a['regular_checkpoints']:
   for pin in record['files']:checked(pin);pins.append(pin)
  worker=read(f/'frames_review.json');assert len(worker)==101 and all(v['passed'] for v in worker)
  series += [dict(step=v['step'],observables=v['observables']) for v in worker if not v['final']]
  blocks=m.statistics(rows,1000)['blocks'];allblocks+=blocks
  reports.append(dict(segment=segment,minimum_image_A=a['minimum_image_A'],endpoint_geometry=g,endpoint_void=m.void_witness(end,b),samples=samples,performance=m.performance((f/'run.log').read_text(),500000),statistics=blocks))
  pins += [source(f/n) for n in ['assessment.json','frames_review.json','result.dcd','result.xst','result.coor','result.vel','result.xsc']]
 assert [v['step'] for v in series]==list(range(535000,5530001,5000));json.dumps(series,allow_nan=False)
 summaries=[]
 for ns in range(1,11):
  part=series[(ns-1)*100:ns*100];contacts=[v['observables']['source_contact_fraction'] for v in part]
  summaries.append(dict(ns=ns,contact_mean=float(np.mean(contacts)),contact_min=min(contacts),contact_max=max(contacts),contact_last=contacts[-1],lesion_cross_mean_A=np.mean([v['observables']['lesion_cross_distances_A'] for v in part],axis=0).tolist()))
 late=allblocks[-100:];keys=['temperature_K','group_pressure_bar','total_density_g_cm3','added_NaCl_molar']
 physical={k:float(np.mean([r[k] for r in late])) for k in keys}
 physical['density_half_difference_g_cm3']=float(np.mean([r['total_density_g_cm3'] for r in late[50:]])-np.mean([r['total_density_g_cm3'] for r in late[:50]]))
 native=sum(r['performance']['native_wall_seconds'] for r in reports)
 report=dict(at=now(),passed=True,case=case,replica=rep,scope='1000 DCD cells,100 periodic restart triples,30 stratified geometry frames and10 binary endpoints checked using frozen chemistry. All1010 worker geometry records pass; not independent all-frame chemistry.',stages=reports,late5ns_physical=physical,structural_by_ns=summaries,series=series,inputs=pins,performance=dict(ns=10,native_seconds=native,native_ns_per_day=10*86400/native,service_elapsed_seconds=state['finished_at']-state['started_at']),simulation_ready=False,minimum_certified=False)
 save(output,report)
 print(json.dumps(dict(passed=True,late5ns=physical,structural_by_ns=summaries,minimum_new_image_A=min(r['minimum_image_A'] for r in reports),max_endpoint_void_A=max(r['endpoint_void']['sampled_max_nearest_atom_A'] for r in reports),performance=report['performance']),indent=2))

if __name__=='__main__':audit(Path(sys.argv[1]),sys.argv[2],int(sys.argv[3]))
