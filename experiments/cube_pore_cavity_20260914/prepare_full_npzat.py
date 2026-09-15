from pathlib import Path
import json,shutil
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';d=root/'full_npzat';d.mkdir(exist_ok=True)
stage='cube_pore_04_300K_NPT_MGHH_only_p10';s=(p/f'{stage}.conf').read_text();g=json.loads((p/'graphene_nanopore.json').read_text());c=g['pore_center_nm']
# Re-express the SAME periodic lattice with origin on the restrained membrane.
# Coordinates, velocities, lateral cell vectors, wall parameters, and topology are unchanged.
xsc=(p/'output'/f'{stage}.xsc').read_text().splitlines();a=xsc[-1].split();a[10:13]=[str(x*10) for x in c];a[0]='0';a[13:]=['0']*(len(a)-13);xsc[-1]=' '.join(a);(d/'start.xsc').write_text('\n'.join(xsc)+'\n')
inputs={'structure','coordinates','consref','conskfile','parameters'};lines=[]
for l in s.splitlines():
 a=l.split();k=a[0] if a else ''
 if k in inputs:l=f'{k} {p/a[1]}'
 elif k in ['binCoordinates','binVelocities']:ext='coor' if k=='binCoordinates' else 'vel';l=f'{k} {p/"output"/f"{stage}.{ext}"}'
 elif k=='extendedSystem':l=f'{k} {d/"start.xsc"}'
 elif k=='cellOrigin':l=k+' '+' '.join(str(x*10) for x in c)
 elif k=='GPUresident':l='GPUresident off'
 elif k in ['outputName','dcdFile','xstFile']:l=f'{k} {d/({"outputName":"run","dcdFile":"run.dcd","xstFile":"run.xst"}[k])}'
 elif k in ['outputEnergies','xstFreq','restartfreq','dcdFreq']:l=f'{k} 100'
 elif k=='langevinPiston':l='langevinPiston on'
 elif k=='run':continue
 lines.append(l)
lines+=['useGroupPressure yes','useFlexibleCell yes','useConstantArea yes','langevinPistonTarget 1.01325','langevinPistonPeriod 1000','langevinPistonDecay 500','langevinPistonTemp 300','margin 4','outputPressure 100','run 2500']
(d/'run.conf').write_text('\n'.join(lines)+'\n');shutil.copyfile(root/'full_baseline_probe/FFTW_NAMD_3.0.2_Linux-x86_64-multicore.txt',d/'FFTW_NAMD_3.0.2_Linux-x86_64-multicore.txt')
(d/'meta.json').write_text(json.dumps({'source_job':'60e854232e8c','source_checkpoint':stage,'changes':['GPUresident off (local memory limitation)','constant normal pressure, fixed lateral area','cell origin shifted to graphene plane (same periodic lattice)','output cadence increased'],'unchanged':['all atom coordinates','velocities','PSF','force field','wall restraint coefficients','timestep 4 fs','PME force interval 8 fs'],'requested_ps':10,'pore_center_nm':c},indent=2)+'\n')
