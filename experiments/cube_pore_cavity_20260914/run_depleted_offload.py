"""Continue the paired fixed-volume control using CPU integration/GPU force offload.
The GPU-resident source failed at step96012; preserve that failed segment.
Start from the same immutable156ps checkpoint used by the pressure branch.
"""
from pathlib import Path
import json,shutil,subprocess
root=Path(__file__).resolve().parent;src=root/'open_pore/fill_92_npzat';dst=root/'open_pore/fill_92_nvt_offload';dst.mkdir(exist_ok=True)
assert not (dst/'run.log').exists()
for e in ['coor','vel','xsc']:shutil.copyfile(src/f'start.{e}',dst/f'start.{e}')
lines=[]
for l in (src/'run.conf').read_text().splitlines():
 a=l.split();k=a[0] if a else ''
 if k in ['run','useFlexibleCell','useConstantArea','langevinPistonTarget','langevinPistonPeriod','langevinPistonDecay','langevinPistonTemp']:continue
 if k=='langevinPiston':l='langevinPiston off'
 elif k=='GPUresident':l='GPUresident off'
 elif k in ['outputName','dcdFile','xstFile','binCoordinates','binVelocities','extendedSystem']:l=l.replace(str(src),str(dst))
 lines.append(l)
lines+=['run 172000'];(dst/'run.conf').write_text('\n'.join(lines)+'\n')
meta=json.loads((src/'meta.json').read_text());meta.update(ensemble='NVT',requested_ps=344,execution_mode='GPU offload, CPU integration, +p4',reason='Original GPU-resident depleted control failed at step96012, atoms moving too fast. Restart the fixed-volume comparison from the SAME156ps checkpoint as the pressure branch; preserve all failed outputs.',change='Fixed volume and alternate execution mode; same source coordinates, velocities, cell, masses, ion counts, wall parameters and restraints.');(dst/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
with (dst/'run.log').open('w') as f:
 code=subprocess.run(['/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3','+p4','+devices','0',str(dst/'run.conf')],cwd=dst,stdout=f,stderr=subprocess.STDOUT).returncode
print('returncode',code,flush=True)
