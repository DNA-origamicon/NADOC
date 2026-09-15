from pathlib import Path
import shutil,json
root=Path(__file__).resolve().parent;src=root/'open_pore/fill_100';dst=root/'open_pore/fill_100_npzat';dst.mkdir(exist_ok=True)
# Verify all three restart members remain unchanged across copying.
files=[src/f'run.restart.{ext}' for ext in ['coor','vel','xsc']]
before=[(p.stat().st_size,p.stat().st_mtime_ns) for p in files]
for p in files:shutil.copyfile(p,dst/p.name)
assert before==[(p.stat().st_size,p.stat().st_mtime_ns) for p in files], 'Restart changed during copy; retry preparation.'
step=int((dst/'run.restart.xsc').read_text().splitlines()[-1].split()[0]);s=(src/'run.conf').read_text();lines=[]
for l in s.splitlines():
 a=l.split();k=a[0] if a else ''
 if k in ['minimize','reinitvels','temperature','run']:continue
 if k in ['outputName','dcdFile']:l=l.replace(str(src),str(dst))
 if k=='langevinPiston':l='langevinPiston on'
 lines.append(l)
lines += [f'binCoordinates {dst/"run.restart.coor"}',f'binVelocities {dst/"run.restart.vel"}',f'extendedSystem {dst/"run.restart.xsc"}','useGroupPressure yes','useFlexibleCell yes','useConstantArea yes','langevinPistonTarget 1.01325','langevinPistonPeriod 1000','langevinPistonDecay 500','langevinPistonTemp 300','margin 4','run 100000']
(dst/'run.conf').write_text('\n'.join(lines)+'\n');meta=json.loads((src/'meta.json').read_text());meta.update(parent_restart_step=step,ensemble='NPzAT',change='Only normal pressure equilibration, fixed lateral dimensions, origin on membrane plane.');(dst/'meta.json').write_text(json.dumps(meta,indent=2)+'\n');print(step)
