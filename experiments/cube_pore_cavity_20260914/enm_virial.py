"""Explicit elastic-network energy/virial contribution in original snapshots."""
from pathlib import Path
import numpy as np,json,mmap
from backend.core.md_trajectory import _DcdPrefixFile
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';g=json.loads((p/'graphene_nanopore.json').read_text());volume=np.prod(np.array(g['periodic_box_nm'])*10)
a=np.loadtxt(p/'cube_pore_k0.5.enm.extra',usecols=(1,2,3,4));i=a[:,0].astype(int);j=a[:,1].astype(int);k0=a[:,2];r0=a[:,3];conversion=4184/6.02214076e23/1e-30/1e5
records=[]
for stage,coef,offset,dt in [('01_300K_NPT_ENM_k0p5_p10',.5,0,2),('02_300K_NPT_ENM_k0p1_p10',.1,240,4),('03_300K_NPT_ENM_k0p01_p10',.01,720,4)]:
 r=_DcdPrefixFile(p/'output'/f'cube_pore_{stage}.dcd',0)
 with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
  for frame in range(r.n_frames):
   base=r.frame_start+frame*r.frame_bytes
   pos=np.stack([np.frombuffer(m,'<f4',123167,base+r.cell_record_bytes+c*r.coord_record_bytes+4).copy() for c in range(3)],axis=1).astype(float)
   dr=pos[i]-pos[j];dist=np.linalg.norm(dr,axis=1);delta=dist-r0;k=k0*(coef/.5)
   energy=float(np.sum(k*delta**2));tensor=-np.einsum('n,ni,nj->ij',2*k*delta/dist,dr,dr)/volume*conversion
   rec={'stage':stage,'time_ps':offset+(frame+1)*4000*dt/1000,'enm_k':coef,'enm_energy_kcal':energy,'enm_pressure_tensor_bar':tensor.tolist(),'enm_isotropic_pressure_bar':float(np.trace(tensor)/3)};records.append(rec)
 r.close()
first=records[0];assert abs(first['enm_energy_kcal']-(51339.3859-36498.5007))<.1
# Direct extra-bond virial agrees within 0.3% with the NAMD force-toggle
# comparison; that comparison also includes force/constraint coupling.
assert abs(first['enm_isotropic_pressure_bar']-(-986.7815+380.8999))<3
(root/'enm_virial.json').write_text(json.dumps(records,indent=2)+'\n')
for stage in sorted(set(r['stage'] for r in records)):
 s=[r for r in records if r['stage']==stage];print(stage,'first/last/mean ENM pressure',s[0]['enm_isotropic_pressure_bar'],s[-1]['enm_isotropic_pressure_bar'],np.mean([r['enm_isotropic_pressure_bar'] for r in s]),flush=True)
