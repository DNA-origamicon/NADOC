from pathlib import Path
import subprocess,json,time
root=Path(__file__).resolve().parent
exe='/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3'
status={}
for name in ['fill_100','fill_96','fill_92']:
 p=root/'open_pore'/name
 status[name]={'started':time.time()};(root/'control_status.json').write_text(json.dumps(status,indent=2))
 with (p/'run.log').open('w') as f:
  code=subprocess.run([exe,'+p1','+devices','0',str(p/'run.conf')],cwd=p,stdout=f,stderr=subprocess.STDOUT).returncode
 status[name].update(returncode=code,finished=time.time());(root/'control_status.json').write_text(json.dumps(status,indent=2))
 if code:break
