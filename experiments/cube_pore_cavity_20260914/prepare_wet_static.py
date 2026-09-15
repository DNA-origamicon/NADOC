from pathlib import Path
import mmap,numpy as np,struct,shutil,json
from backend.core.md_trajectory import _DcdPrefixFile
root=Path(__file__).resolve().parent;d=root/'full_wet_static';d.mkdir(exist_ok=True);p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';stage='cube_pore_01_300K_NPT_ENM_k0p5_p10';r=_DcdPrefixFile(p/'output'/f'{stage}.dcd',0)
with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
 xyz=np.stack([np.frombuffer(m,'<f4',r.n_atoms,r.frame_start+r.cell_record_bytes+a*r.coord_record_bytes+4).copy() for a in range(3)],axis=1).astype('<f8')
with (d/'wet_8ps.coor').open('wb') as f:f.write(struct.pack('<i',r.n_atoms));xyz.tofile(f)
r.close();lines=[]
for line in (p/f'{stage}.conf').read_text().splitlines():
 a=line.split();k=a[0] if a else ''
 if k in ['run','binVelocities']:continue
 if k in ['structure','coordinates','consref','conskfile','parameters','extraBondsFile','extendedSystem']:line=k+' '+str(p/a[1])
 elif k=='binCoordinates':line=k+' '+str(d/'wet_8ps.coor')
 elif k=='GPUresident':line='GPUresident off'
 elif k in ['outputName','dcdFile','xstFile']:line=k+' '+str(d/({'outputName':'run','dcdFile':'run.dcd','xstFile':'run.xst'}[k]))
 lines.append(line)
lines+=['temperature 300','outputPressure 1','run 0'];(d/'run.conf').write_text('\n'.join(lines)+'\n')
shutil.copyfile(root/'full_static_01/FFTW_NAMD_3.0.2_Linux-x86_64-multicore.txt',d/'FFTW_NAMD_3.0.2_Linux-x86_64-multicore.txt')
(d/'meta.json').write_text(json.dumps({'purpose':'Check virial before a large cavity develops','source_stage':stage,'source_frame':0,'source_time_ps':8,'same_stage_forces_including_ENM_and_graphene_restraints':True,'velocities':'Original frame velocities unavailable; thermal velocities initialized at 300 K. Static virial diagnostic, not archived runtime pressure or new dynamics.'},indent=2)+'\n')
