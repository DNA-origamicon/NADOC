from pathlib import Path
import numpy as np,subprocess,json
from backend.core.namd_solvate import _parse_gro,_extend_psf,_build_solvated_pdb
from backend.core.namd_package import complete_psf
from backend.core.models import Design
root=Path(__file__).resolve().parent;base=root/'bulk';base.mkdir(exist_ok=True)
with (base/'solvate.log').open('w') as f:subprocess.run(['gmx','solvate','-cs','spc216.gro','-box','6','6','6','-o','solvated.gro','-nobackup'],cwd=base,stdout=f,stderr=subprocess.STDOUT,check=True)
waters,_=_parse_gro((base/'solvated.gro').read_text());rng=np.random.default_rng(6142026);idx=rng.choice(len(waters),40,replace=False);ions=[(waters[i].ox,waters[i].oy,waters[i].oz) for i in idx];ix=set(idx);waters=[w for i,w in enumerate(waters) if i not in ix]
for ensemble in ['nvt','npt']:
 p=base/ensemble;p.mkdir(exist_ok=True)
 (p/'system.psf').write_text(_extend_psf(complete_psf(Design()),waters,ions[:20],ions[20:]))
 (p/'system.pdb').write_text(_build_solvated_pdb('END\n',waters,ions[:20],ions[20:],(6,6,6),0))
 conf=(root/'open_pore/fill_100/run.conf').read_text().replace(str(root/'open_pore/fill_100'),str(p))
 lines=[]
 for l in conf.splitlines():
  a=l.split();k=a[0] if a else ''
  if k.startswith('cellBasisVector'):ax=int(k[-1])-1;v=[0.,0.,0.];v[ax]=60.;l=k+' '+' '.join(map(str,v))
  elif k=='cellOrigin':l='cellOrigin 30 30 30'
  elif k=='constraints':l='constraints off'
  elif k in ['consref','conskfile','conskcol','consexp']:continue
  elif k=='minimize':l='minimize 500'
  elif k=='run':l='run 100000'
  lines.append(l)
 # Enable barostat only after minimization and velocity initialization.
 if ensemble=='npt':
  j=next(i for i,l in enumerate(lines) if l.startswith('run '));lines[j:j]=['langevinPiston on','langevinPistonTarget 1.01325','langevinPistonPeriod 200','langevinPistonDecay 100','langevinPistonTemp 300','useGroupPressure yes']
 (p/'run.conf').write_text('\n'.join(lines)+'\n');(p/'meta.json').write_text(json.dumps({'box_nm':[6,6,6],'water_count':len(waters),'salt_pairs':20,'ensemble':ensemble},indent=2))
print(len(waters))
