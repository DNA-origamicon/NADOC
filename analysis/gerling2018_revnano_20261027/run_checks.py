from pathlib import Path
import subprocess,time,json,shutil
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent;W=R/'.development-artifacts/revnano-gerling2018/REVNANO'
rows=[]
for name in ['caps_raw','caps_annotated','42hb14_raw']:
 t=time.monotonic()
 with (O/(name+'.log')).open('w') as log:
  try:
   r=subprocess.run([str(R/'.venv/bin/python'),'-u','revnano.py',name],cwd=W,stdout=log,stderr=subprocess.STDOUT,timeout=300)
   status=r.returncode
  except subprocess.TimeoutExpired:status='timeout300s'
 for p in (W/'_assets').glob(name+'*'):
  if p.suffix in ('.csv','.rev'):shutil.copy2(p,O/p.name)
 row={'name':name,'exit_status':status,'seconds':round(time.monotonic()-t,2),'contact_map_exists':(O/(name+'.csv')).exists()};rows.append(row);print(row,flush=True)
 (O/'runs.json').write_text(json.dumps(rows,indent=2)+'\n')
