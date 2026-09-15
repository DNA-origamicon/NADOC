from pathlib import Path
import json,time,subprocess,shutil
root=Path(__file__).resolve().parent;src=root/'bulk/npt'
# Keep the number of competing GPU processes bounded by waiting for the first bulk pair.
for _ in range(1440):
 log=(root/'bulk_status.log').read_text(errors='replace')
 if 'nvt 0' in log:break
 if 'nvt ' in log:raise RuntimeError('Bulk NVT control did not succeed')
 time.sleep(5)
else:raise RuntimeError('Timed out waiting for original bulk controls')
for freq in [1,2]:
 dst=root/'bulk'/f'npt_4fs_pme{4*freq}fs';dst.mkdir(exist_ok=True)
 for ext in ['coor','vel','xsc']:shutil.copyfile(src/f'run.{ext}',dst/f'start.{ext}')
 lines=[]
 for l in (src/'run.conf').read_text().splitlines():
  a=l.split();k=a[0] if a else ''
  if k in ['temperature','minimize','reinitvels','run'] or (k=='langevinPiston' and a[1]=='off'):continue
  if k in ['outputName','dcdFile']:l=l.replace(str(src),str(dst))
  elif k=='timestep':l='timestep 4'
  elif k=='fullElectFrequency':l=f'fullElectFrequency {freq}'
  lines.append(l)
 lines += [f'binCoordinates {dst/"start.coor"}',f'binVelocities {dst/"start.vel"}',f'extendedSystem {dst/"start.xsc"}','run 50000']
 (dst/'run.conf').write_text('\n'.join(lines)+'\n');meta=json.loads((src/'meta.json').read_text());meta.update(timestep_fs=4,pme_interval_fs=4*freq,parent='bulk/npt 2fs');(dst/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
 with (dst/'run.log').open('w') as f:
  code=subprocess.run(['/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3','+p1','+devices','0',str(dst/'run.conf')],cwd=dst,stdout=f,stderr=subprocess.STDOUT).returncode
 print(dst.name,code,flush=True)
 if code:break
