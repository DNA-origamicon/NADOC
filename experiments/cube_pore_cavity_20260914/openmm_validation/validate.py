"""Independent-engine energy check; no dynamics or application modifications."""
from pathlib import Path
import openmm as mm
from openmm import app,unit as u
import numpy as np,json,time,resource
root=Path(__file__).resolve().parents[1];src=root/'open_pore/fill_100';out=Path(__file__).resolve().parent
ff=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated/forcefield'
print('load params',flush=True)
pars=app.CharmmParameterSet(str(ff/'top_all36_na.rtf'))
for name in ['par_all36_na.prm','par_all36m_prot.prm','par_np_thiol.prm']:
 pars.readParameterFile(str(ff/name),permissive=True)
pars.readStreamFile(str(ff/'toppar_water_ions_cufix.str'))
pars.readParameterFile(str(ff/'par_stub_ions_nbfix.str'),permissive=True)
# Repeat after all atom types exist: permissive parsing otherwise skips NBFIX
# records whose types are first introduced later in the same file.
for name in ['par_all36_na.prm','par_all36m_prot.prm','par_np_thiol.prm']:
 pars.readParameterFile(str(ff/name),permissive=True)
pars.readStreamFile(str(ff/'toppar_water_ions_cufix.str'))
pars.readParameterFile(str(ff/'par_stub_ions_nbfix.str'),permissive=True)
assert pars.atom_types_str['NGRC'].nbfix['NGRC'][1] == 0
print('load psf',flush=True)
(out/'parser_compatible.psf').write_text((src/'system.psf').read_text().replace('!NNB\n\n','!NNB\n\n\n'));psf=app.CharmmPsfFile(str(out/'parser_compatible.psf'));meta=json.loads((src/'meta.json').read_text());box=np.array(meta['box_nm']);psf.setBox(*(box*u.nanometer))
print('create system',len(psf.atom_list),flush=True)
sys=psf.createSystem(pars,nonbondedMethod=app.PME,nonbondedCutoff=1*u.nanometer,constraints=app.HBonds,rigidWater=True,removeCMMotion=False,flexibleConstraints=True)
for i,f in enumerate(sys.getForces()):
 f.setForceGroup(i)
 if isinstance(f,mm.NonbondedForce):
  f.setUseDispersionCorrection(False)
  # NAMD explicit values printed for the same control.
  f.setPMEParameters(3.12341,84,84,80)
 if isinstance(f,mm.CustomNonbondedForce):
  e=f.getEnergyFunction();head,sep,tail=e.partition(';')
  f.setEnergyFunction('('+head+')*sw;sw=select(step(r-0.8),(1-r*r)^2*(1+2*r*r-3*0.8^2)/(1-0.8^2)^3,1);'+tail)
  f.setUseSwitchingFunction(False);f.setUseLongRangeCorrection(False)
 print(i,type(f).__name__,flush=True)
(out/'system.xml').write_text(mm.XmlSerializer.serialize(sys))
xyz=np.memmap(src/'run.coor',dtype='<f8',offset=4,shape=(sys.getNumParticles(),3))/10
print('create CPU context',flush=True)
integ=mm.VerletIntegrator(.002);ctx=mm.Context(sys,integ,mm.Platform.getPlatformByName('CPU'),{'Threads':'2'});ctx.setPositions(xyz*u.nanometer)
res={}
for i,f in enumerate(sys.getForces()):
 e=ctx.getState(getEnergy=True,groups={i}).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole);res[str(i)+'_'+type(f).__name__]=e;print(i,type(f).__name__,e,flush=True)
res['total_kcal']=ctx.getState(getEnergy=True).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
(out/'energies.json').write_text(json.dumps(res,indent=2)+'\n');print(res,flush=True)
