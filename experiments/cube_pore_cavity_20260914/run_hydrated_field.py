"""Hold an equilibrated open pore at fixed volume with the user's 300 mV bias."""
from pathlib import Path
import time,subprocess,json,shutil
root=Path(__file__).resolve().parent;src=root/'open_pore/fill_100_npzat';dst=root/'open_pore/hydrated_300mv';dst.mkdir(exist_ok=True)
for _ in range(720):
 log=(src/'run.log').read_text(errors='replace')
 if 'FATAL ERROR' in log:raise RuntimeError('Source equilibration failed')
 if 'End of program' in log and (src/'run.coor').exists():break
 time.sleep(5)
else:raise RuntimeError('Source equilibration did not complete within 1 hour')
for ext in ['coor','vel','xsc']:shutil.copyfile(src/f'run.{ext}',dst/f'start.{ext}')
s=(src/'run.conf').read_text();lines=[]
for l in s.splitlines():
 a=l.split();k=a[0] if a else ''
 if k in ['run','useFlexibleCell','useConstantArea','langevinPistonTarget','langevinPistonPeriod','langevinPistonDecay','langevinPistonTemp']:continue
 if k=='langevinPiston':l='langevinPiston off'
 elif k in ['outputName','dcdFile']:l=l.replace(str(src),str(dst))
 elif k in ['binCoordinates','binVelocities','extendedSystem']:ext={'binCoordinates':'coor','binVelocities':'vel','extendedSystem':'xsc'}[k];l=f'{k} {dst/f"start.{ext}"}'
 elif k=='dcdFreq':l='dcdFreq 500'
 lines.append(l)
lines+=['eFieldOn on','eField 0 0 6.918164349','eFieldNormalized yes','outputPressure 1000','run 250000']
(dst/'run.conf').write_text('\n'.join(lines)+'\n');meta=json.loads((src/'meta.json').read_text());meta.update(ensemble='NVT',voltage_mV=300,parent='fill_100_npzat',change='Freeze equilibrated volume; apply 300 mV +z; 1 ps DCD cadence.');(dst/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
with (dst/'run.log').open('w') as f:
 code=subprocess.run(['/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3','+p1','+devices','0',str(dst/'run.conf')],cwd=dst,stdout=f,stderr=subprocess.STDOUT).returncode
print('returncode',code,flush=True)
