from pathlib import Path
import json,numpy as np,re,time
root=Path(__file__).resolve().parents[1];d=root/'openmm_full';p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated'
for _ in range(240):
 if 'probe complete' in (root/'openmm_validation/full_probe.log').read_text():break
 if 'Traceback' in (root/'openmm_validation/full_probe.log').read_text():raise RuntimeError('Probe failed')
 time.sleep(2)
else:raise RuntimeError('System serialization did not complete')
xyz=np.memmap(p/'output/cube_pore_04_300K_NPT_MGHH_only_p10.coor',dtype='<f8',offset=4,shape=(1679987,3))/10
lj=0.;count=0
with (d/'system.xml').open() as f:
 for l in f:
  if '<Exception ' not in l:continue
  a=dict(re.findall(r'(\w+)="([^"]+)"',l));eps=float(a['eps'])
  if eps==0:continue
  r=np.linalg.norm(xyz[int(a['p1'])]-xyz[int(a['p2'])]);r6=(float(a['sig'])/r)**6;lj+=4*eps*(r6*r6-r6)/4.184;count+=1
res=json.loads((d/'energy_validation.json').read_text());res['exception_LJ_kcal']=lj;res['nonzero_LJ_exceptions']=count
ref={'bond':41874.0944,'angle_including_urey':101711.8300,'dihedral':135318.5789,'improper':2170.6578,'vdw':520539.0316,'electrostatics':-6985332.5469}
calc={'bond':res['0_HarmonicBondForce'],'angle_including_urey':res['1_HarmonicAngleForce']+res['2_HarmonicBondForce'],'dihedral':res['3_PeriodicTorsionForce'],'improper':res['4_CustomTorsionForce'],'vdw':res['7_CustomNonbondedForce']+lj,'electrostatics':res['6_NonbondedForce']-lj}
res['component_comparison']={k:{'NAMD_kcal':ref[k],'OpenMM_kcal':v,'difference_kcal':v-ref[k]} for k,v in calc.items()}
masses=np.load(d/'masses.npy');ok=bool(np.isfinite(masses).all() and (masses>0).all())
with (p/'cube_pore_hmr.psf').open() as f:
 for l in f:
  if '!NATOM' in l:
   for i in range(len(masses)):
    if abs(float(next(f).split()[7])-masses[i])>1e-8:ok=False
   break
res['all_source_masses_match']=ok
# A tight bonded/LJ agreement and a <0.05% electrostatic difference are required.
res['component_gate_passed']=ok and all(abs(calc[k]-ref[k])<2 for k in ['bond','angle_including_urey','dihedral','improper','vdw']) and abs((calc['electrostatics']-ref['electrostatics'])/ref['electrostatics'])<.0005
res['component_gate_passed']=bool(res['component_gate_passed'])
(d/'energy_validation.json').write_text(json.dumps(res,indent=2)+'\n');print(json.dumps(res,indent=2));assert res['component_gate_passed']
