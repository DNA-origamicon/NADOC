"""Independent-engine paired ensemble intervention after component energy validation.
Usage: ... run_full_dynamics.py nvt|npzat duration_ps
Writes only experiment outputs. NAMD source checkpoints are read-only.
"""
from pathlib import Path
import sys,time,json,resource,struct
resource.setrlimit(resource.RLIMIT_DATA,(11*1024**3,11*1024**3))
import openmm as mm
from openmm import unit as u
import numpy as np
from scipy.spatial import cKDTree
root=Path(__file__).resolve().parents[1];mode=sys.argv[1];duration=float(sys.argv[2]);assert mode in ['nvt','npzat']
src=root/'openmm_full';out=src/mode;out.mkdir(exist_ok=True)
if (out/'metrics.jsonl').exists():raise RuntimeError('Do not overwrite an existing dynamics branch')
val=json.loads((src/'energy_validation.json').read_text());assert abs(val['fractional_total_difference'])<.0005 and val.get('component_gate_passed')
p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';g=json.loads((p/'graphene_nanopore.json').read_text());center=np.array(g['pore_center_nm']);box0=np.array(g['periodic_box_nm'])
system=mm.XmlSerializer.deserialize((src/'system.xml').read_text());n=system.getNumParticles();assert n==1679987
# References and spring energy match NAMD: K*d^2, K=50 kcal/mol/A^2.
wall=mm.CustomExternalForce('k*periodicdistance(x,y,z,x0,y0,z0)^2');wall.addGlobalParameter('k',50*4.184*100)
for name in ['x0','y0','z0']:wall.addPerParticleParameter(name)
idx=0
with (p/'cube_pore.pdb').open() as f:
 for l in f:
  if not l.startswith(('ATOM  ','HETATM')):continue
  if 123167<=idx<148711:
   ref=np.array([float(l[a:a+8]) for a in [30,38,46]])/10-center;wall.addParticle(idx,ref.tolist())
  idx+=1
  if idx==148711:break
assert wall.getNumParticles()==25544;wall.setForceGroup(8);system.addForce(wall)
baro=mm.MonteCarloAnisotropicBarostat(mm.Vec3(1.01325,1.01325,1.01325)*u.bar,300*u.kelvin,False,False,True,25 if mode=='npzat' else 0);baro.setRandomNumberSeed(9142027);system.addForce(baro)
integ=mm.LangevinMiddleIntegrator(300*u.kelvin,5/u.picosecond,.002*u.picosecond);integ.setConstraintTolerance(1e-8);integ.setRandomNumberSeed(9142026)
print('creating CUDA context',mode,flush=True)
ctx=mm.Context(system,integ,mm.Platform.getPlatformByName('CUDA'),{'DeviceIndex':'0','Precision':'mixed'})
xyz=np.memmap(p/'output/cube_pore_04_300K_NPT_MGHH_only_p10.coor',dtype='<f8',offset=4,shape=(n,3))/10-center
vel=np.memmap(p/'output/cube_pore_04_300K_NPT_MGHH_only_p10.vel',dtype='<f8',offset=4,shape=(n,3))*(20.45482706/10)
ctx.setPositions(xyz*u.nanometer);ctx.setVelocities(vel*u.nanometer/u.picosecond)
boundary=ctx.getState(getEnergy=True,groups={8}).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
print('boundary kcal',boundary,flush=True);assert abs(boundary-23038.8966)<5,'wall energy mismatch'
meta={'engine':'OpenMM '+mm.version.full_version+' CUDA mixed precision','mode':mode,'duration_ps':duration,'dt_fs':2,'source_job':'60e854232e8c','source_stage':'04_300K_NPT_MGHH_only_p10','same_initial_coordinates_and_velocities':True,'source_velocity_to_nm_ps':20.45482706/10,'same_force_field_and_masses':True,'differences_from_NAMD':['LangevinMiddle integrator; thermostat also acts on hydrogen','2 fs single-rate PME instead of 4 fs/8 fs MTS','PME interpolation implementation','Monte Carlo z-only pressure control in NPzAT branch'],'energy_validation':val,'initial_wall_energy_kcal':boundary,'pressure_target_bar':1.01325 if mode=='npzat' else None}
(out/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
water=148711+np.arange(508219)*3;grid=np.stack(np.meshgrid(np.arange(-5.8,6,.4),np.arange(-5.8,6,.4),np.arange(-6.8,2,.4),indexing='ij'),axis=-1).reshape(-1,3)
ndof=3*n-system.getNumConstraints();start=time.time();steps=int(round(duration/.002));report=500
with (out/'metrics.jsonl').open('w') as f:
 for step in range(0,steps+1,report):
  if step:integ.step(min(report,steps-step+report))
  state=ctx.getState(getPositions=True,getEnergy=True);pos=state.getPositions(asNumpy=True).value_in_unit(u.nanometer);box=np.diag(state.getPeriodicBoxVectors(asNumpy=True).value_in_unit(u.nanometer));rel=pos-box*np.round(pos/box);rad=np.linalg.norm(rel[water,:2],axis=1)
  assert np.all(np.isfinite(pos)) and np.max(abs(box[:2]-box0[:2]))<1e-6
  dist=cKDTree(pos[water]%box,boxsize=box).query(grid%box,workers=2)[0]
  rec={'time_ps':step*.002,'wall_seconds':time.time()-start,'box_nm':box.tolist(),'temperature_K':2*state.getKineticEnergy().value_in_unit(u.kilojoule_per_mole)/(ndof*.008314462618),'potential_kcal':state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),'pore_region_water_void_nm3':float(np.sum(dist>.4)*.4**3),'slice_counts':{str(z):int(np.sum((rad<4)&(abs(rel[water,2]-z)<.25))) for z in [-3,-2,-1,0,1]},'graphene_z_range_nm':np.quantile(rel[123167:148711,2],[0,.5,1]).tolist(),'dna_atoms_in_aperture_plane':int(np.sum((np.linalg.norm(rel[:123167,:2],axis=1)<4)&(abs(rel[:123167,2])<.5)))}
  if step%2500==0:rec['instantaneous_molecular_pressure_bar']=list(baro.computeCurrentPressure(ctx).value_in_unit(u.bar))
  f.write(json.dumps(rec)+'\n');f.flush();print(json.dumps(rec),flush=True)
  if step%2500==0:np.save(out/f'positions_{step:07d}.npy',np.asarray(pos,dtype=np.float32))
  if step and step%5000==0:(out/'restart.chk').write_bytes(ctx.createCheckpoint())
(out/'final.chk').write_bytes(ctx.createCheckpoint());print('completed',flush=True)
