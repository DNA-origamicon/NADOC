"""Validate the original Hamiltonian in an independent GPU engine before dynamics.
No production files are written. Wait for the CPU experiment to release memory.
"""
from pathlib import Path
import time,json,resource
root=Path(__file__).resolve().parents[1];out=root/'openmm_full';out.mkdir(exist_ok=True)
for _ in range(1440):
 log=(root/'full_npzat/run.log').read_text(errors='replace')
 if 'FATAL ERROR' in log:raise RuntimeError('CPU experiment failed; inspect it first')
 if 'End of program' in log:break
 time.sleep(5)
else:raise RuntimeError('CPU experiment still running after 2 hours')
# Keep this optional probe below the RAM used by the application plus main controls.
resource.setrlimit(resource.RLIMIT_DATA,(11*1024**3,11*1024**3))
print('CPU experiment finished; loading independent GPU probe',flush=True)
import openmm as mm
from openmm import app,unit as u
import numpy as np,gc
p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';ff=p/'forcefield'
pars=app.CharmmParameterSet(str(ff/'top_all36_na.rtf'))
for _ in range(2):
 for name in ['par_all36_na.prm','par_all36m_prot.prm','par_np_thiol.prm']:pars.readParameterFile(str(ff/name),permissive=True)
 pars.readStreamFile(str(ff/'toppar_water_ions_cufix.str'))
 pars.readParameterFile(str(ff/'par_stub_ions_nbfix.str'),permissive=True)
assert pars.atom_types_str['NGRC'].nbfix['NGRC'][1]==0
s=(p/'cube_pore_hmr.psf').read_text();(out/'parser_compatible.psf').write_text(s);del s
print('load PSF',flush=True)
psf=app.CharmmPsfFile(str(out/'parser_compatible.psf'));g=json.loads((p/'graphene_nanopore.json').read_text());box=np.array(g['periodic_box_nm']);center=np.array(g['pore_center_nm']);psf.setBox(*(box*u.nanometer))
print('create System',len(psf.atom_list),flush=True)
sys=psf.createSystem(pars,nonbondedMethod=app.PME,nonbondedCutoff=1*u.nanometer,constraints=app.HBonds,rigidWater=True,removeCMMotion=False,flexibleConstraints=True)
for i,f in enumerate(sys.getForces()):
 f.setForceGroup(i)
 if isinstance(f,mm.NonbondedForce):
  f.setUseDispersionCorrection(False);f.setPMEParameters(3.12341,180,180,162)
 if isinstance(f,mm.CustomNonbondedForce):
  head,sep,tail=f.getEnergyFunction().partition(';');f.setEnergyFunction('('+head+')*sw;sw=select(step(r-0.8),(1-r*r)^2*(1+2*r*r-3*0.8^2)/(1-0.8^2)^3,1);'+tail);f.setUseSwitchingFunction(False);f.setUseLongRangeCorrection(False)
 print(i,type(f).__name__,flush=True)
# Preserve the exact source masses before freeing the high-level topology objects.
masses=np.array([sys.getParticleMass(i).value_in_unit(u.dalton) for i in range(sys.getNumParticles())]);np.save(out/'masses.npy',masses)
del psf,pars;gc.collect()
n=sys.getNumParticles();xyz=np.memmap(p/'output/cube_pore_04_300K_NPT_MGHH_only_p10.coor',dtype='<f8',offset=4,shape=(n,3))/10-center
print('CUDA context',flush=True)
integ=mm.LangevinMiddleIntegrator(300*u.kelvin,5/u.picosecond,.002*u.picosecond);integ.setConstraintTolerance(1e-8);integ.setRandomNumberSeed(9142026)
ctx=mm.Context(sys,integ,mm.Platform.getPlatformByName('CUDA'),{'DeviceIndex':'0','Precision':'mixed'});ctx.setPositions(xyz*u.nanometer)
res={}
for i,f in enumerate(sys.getForces()):
 e=ctx.getState(getEnergy=True,groups={i}).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole);res[str(i)+'_'+type(f).__name__]=e;print(i,type(f).__name__,e,flush=True)
res['total_kcal']=ctx.getState(getEnergy=True).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
ref=-6183718.3541;res['namd_reference_kcal']=ref;res['fractional_total_difference']=(res['total_kcal']-ref)/abs(ref)
(out/'energy_validation.json').write_text(json.dumps(res,indent=2)+'\n');print(res,flush=True)
# Do not begin dynamics without reviewing component agreement.
(out/'system.xml').write_text(mm.XmlSerializer.serialize(sys));print('probe complete',flush=True)
