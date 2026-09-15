"""Branch the depleted-pore control from a consistent, immutable restart snapshot."""
from pathlib import Path
import json,time,shutil,subprocess,hashlib
root=Path(__file__).resolve().parent;src=root/'open_pore/fill_92';dst=root/'open_pore/fill_92_npzat';dst.mkdir(exist_ok=True)
assert not (dst/'run.log').exists(),'Do not overwrite an existing branch'
files=[src/f'run.restart.{e}' for e in ['coor','vel','xsc']]
def stamps():return [(p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns) for p in files]
for _ in range(120):
 before=stamps();time.sleep(.5)
 if before!=stamps():continue
 for p,e in zip(files,['coor','vel','xsc']):shutil.copyfile(p,dst/f'start.{e}')
 if before==stamps():break
 time.sleep(.2)
else:raise RuntimeError('Could not capture a stable checkpoint')
meta=json.loads((src/'meta.json').read_text());n=meta['graphene_atoms']+3*meta['water_count']+2*meta['salt_pairs']
assert all((dst/f'start.{e}').stat().st_size==4+24*n for e in ['coor','vel'])
xs=(dst/'start.xsc').read_text().splitlines();parent_step=int(xs[-1].split()[0]);shutil.copyfile(dst/'start.xsc',dst/'parent_start.xsc');a=xs[-1].split();a[0]='0';xs[-1]=' '.join(a);(dst/'start.xsc').write_text('\n'.join(xs)+'\n')
lines=[]
for l in (src/'run.conf').read_text().splitlines():
 a=l.split();k=a[0] if a else ''
 if k in ['temperature','minimize','reinitvels','run']:continue
 if k=='langevinPiston':l='langevinPiston on'
 elif k in ['outputName','dcdFile','xstFile']:l=l.replace(str(src),str(dst))
 lines.append(l)
lines += [f'binCoordinates {dst/"start.coor"}',f'binVelocities {dst/"start.vel"}',f'extendedSystem {dst/"start.xsc"}','useGroupPressure yes','useFlexibleCell yes','useConstantArea yes','langevinPistonTarget 1.01325','langevinPistonPeriod 1000','langevinPistonDecay 500','langevinPistonTemp 300','margin 4','outputPressure 1000','run 100000']
(dst/'run.conf').write_text('\n'.join(lines)+'\n');meta.update(parent='fill_92',parent_restart_step=parent_step,parent_time_ps=(parent_step-2000)*.002,ensemble='NPzAT',requested_ps=200,change='Only pressure control, outputs and restart initialization; same coordinates, velocities, cell, masses, ions and restraints. Independent stochastic continuation.');meta['snapshot_sha256']={e:hashlib.sha256((dst/f'start.{e}').read_bytes()).hexdigest() for e in ['coor','vel','xsc']};(dst/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
print('parent step',parent_step,'parent ps',meta['parent_time_ps'],flush=True)
with (dst/'run.log').open('w') as f:
 code=subprocess.run(['/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3','+p1','+devices','0',str(dst/'run.conf')],cwd=dst,stdout=f,stderr=subprocess.STDOUT).returncode
print('returncode',code,flush=True)
