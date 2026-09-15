from pathlib import Path
import subprocess,json,time
root=Path(__file__).resolve().parent
exe='/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3'
for name in ['npt','nvt']:
 p=root/'bulk'/name
 with (p/'run.log').open('w') as f:
  code=subprocess.run([exe,'+p1','+devices','0',str(p/'run.conf')],cwd=p,stdout=f,stderr=subprocess.STDOUT).returncode
 print(name,code,flush=True)
 if code:break
