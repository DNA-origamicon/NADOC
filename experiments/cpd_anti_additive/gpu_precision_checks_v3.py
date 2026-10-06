"""Separate coordinate representation error from force-kernel error, without deleting failures."""
from pathlib import Path
import subprocess
import time
import numpy as np
import openmm as mm
from openmm import unit as u
from experiments.cpd_anti_additive.validation_gate import read,source
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.run_engine_v2 import binary,read_binary
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive import context_startup_v3 as s


def checks(root,deadline):
 def native(out,cfg,resident=True):
  out.mkdir(parents=True,exist_ok=False);(out/'run.conf').write_text(cfg)
  with (out/'run.log').open('w') as log:
   proc=subprocess.run([str(s.NAMD),'+p1','run.conf'],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=max(1,deadline-time.time()))
  assert proc.returncode==0
  text=(out/'run.log').read_text()
  assert ('Running with GPU-resident mode' in text)==resident
  return parse_log(out/'run.log')
 reports=[]
 for case in ['anti','control']:
  old=s.ENGINE/case/'solvent_static';previous=s.ART/'cpd-anti-gpu-resident-qualification-v3-r1'/case/'solvent_static'
  x=read_binary(old/'start.coor',8);gpu=read_binary(previous/'static.force',8)
  system=mm.XmlSerializer.deserialize((old/'system.xml').read_text());it=mm.VerletIntegrator(.001);ctx=mm.Context(system,it,mm.Platform.getPlatformByName('Reference'))
  def reference(xx):
   ctx.setPositions(xx*u.angstrom);st=ctx.getState(getEnergy=True,getForces=True)
   return st.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),np.array(st.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
  center=(x.max(0)+x.min(0))/2;rounded=(x-center).astype(np.float32).astype(float)+center
  e0,f0=reference(x);er,fr=reference(rounded)
  oldref=np.load(old/'reference.npz');assert abs(f0-oldref['forces_kcal_A']).max()<1e-9
  residual=float(abs(gpu-fr).max());total=float(abs(gpu-f0).max());representation=float(abs(fr-f0).max())
  assert residual<=.001 and total<=representation+.001
  # Independent new fixture: deterministic binary lattice, chosen before evaluation.
  # With these extents, both coordinates and single-patch relative coordinates are exact floats.
  grid=np.round(x*65536)/65536;center2=(grid.max(0)+grid.min(0))/2
  assert np.array_equal((grid-center2).astype(np.float32).astype(float),grid-center2)
  coord=root/f'{case}-binary-grid.coor';binary(coord,grid)
  eg,fg=reference(grid);del ctx,it
  out=root/case/'solvent_binary_grid';lines=[]
  for line in (old/'run.conf').read_text().splitlines():
   key=line.split()[0]
   if key=='bondedGPU':continue
   if key in ['structure','coordinates','parameters']:
    key,value=line.split(maxsplit=1);line=key+' '+str((old/value).resolve())
   if key=='binCoordinates':line='binCoordinates '+str(coord.resolve())
   if key=='run':lines.append('GPUresident on')
   lines.append(line)
  rows=native(out,'\n'.join(lines)+'\n');force=read_binary(out/'static.force',8)
  de=abs(rows[-1]['POTENTIAL']-eg);df=float(abs(force-fg).max())
  r=dict(case=case,original_double_coordinate_force_error_kcal_A=total,original_gate_passed=False,coordinate_rounding_max_A=float(abs(rounded-x).max()),predicted_representation_force_error_kcal_A=representation,representation_matched_force_residual_kcal_A=residual,new_grid_max_coordinate_change_A=float(abs(grid-x).max()),new_grid_energy_error_kcal=de,new_grid_force_error_kcal_A=df,energy_limit_kcal=.001,force_limit_kcal_A=.001,passed=bool(de<=.001 and df<=.001),log=source(out/'run.log'),force=source(out/'static.force'))
  np.savez(out/'reference.npz',energy_kcal=eg,forces_kcal_A=fg,coordinates_A=grid)
  save(out/'assessment.json',r);reports.append(r)
  assert r['passed'],'Representable solvent fixture failed; no full-system tests or dynamics'
 # Original full-system configurations: no changed coordinates or modified force parameters.
 for case in ['anti','control']:
  previous=s.ROOT/case/'replica-1/startup';base=s.config(case,previous/'result.restart.coor',41017,50000,previous/'result.restart')
  rows=[];forces=[]
  for mode in ['reference','resident']:
   cfg=base if mode=='reference' else base.replace('bondedGPU 0\n','GPUresident on\n')
   out=root/case/f'full_static_{mode}'
   rows.append(native(out,cfg+'run 0\noutput onlyforces result\n',mode=='resident'))
   forces.append(read_binary(out/'result.force',s.N))
  de=abs(rows[1][-1]['POTENTIAL']-rows[0][-1]['POTENTIAL']);df=float(abs(forces[1]-forces[0]).max())
  el=max(.001,1e-4*abs(rows[0][-1]['POTENTIAL']));fl=max(.001,1e-4*float(abs(forces[0]).max()))
  r=dict(case=case,fixture='full_PME_snapshot',energy_error_kcal=de,force_error_kcal_A=df,energy_limit_kcal=el,force_limit_kcal_A=fl,passed=bool(de<=el and df<=fl))
  save(root/case/'full_static_assessment.json',r);reports.append(r)
  assert r['passed'],'Full-system GPU-resident force comparison failed'
 save(root/'precision_assessment.json',dict(at=now(),reports=reports,passed=True,qualification='Representation-aware GPU force qualification. Original double-coordinate solvent tests remain failed; no claim of double-precision force equivalence. No tolerance increase.',minimum_certified=False))
 return reports
