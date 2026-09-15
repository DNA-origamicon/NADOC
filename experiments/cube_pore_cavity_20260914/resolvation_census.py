"""Compare available solvent sites before/after DNA relaxation at unchanged cell."""
from pathlib import Path
import json,numpy as np,subprocess
from backend.core.namd_solvate import _parse_gro,_exclude_waters_near_graphene
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated';g=json.loads((p/'graphene_nanopore.json').read_text());box=np.array(g['periodic_box_nm']);n=1679987
stages=['original','relaxed'];result={}
for stage in stages:
 d=root/f'resolvate_{stage}';d.mkdir(exist_ok=True)
 coords=None if stage=='original' else np.memmap(p/'output/cube_pore_04_300K_NPT_MGHH_only_p10.coor',dtype='<f8',offset=4,shape=(n,3))
 lines=[];idx=0
 with (p/'cube_pore.pdb').open() as f:
  for line in f:
   if not line.startswith(('ATOM  ','HETATM')):continue
   if line[17:21].strip() not in ['TIP3','SOD','CLA']:
    if coords is not None:
     xyz=coords[idx].copy();xyz[:2]%=box[:2]*10
     # Do not individually wrap the DNA normal direction across a molecule.
     line=line[:30]+''.join(f'{v:8.3f}' for v in xyz)+line[54:]
    lines.append(line.rstrip())
   idx+=1
 dry='\n'.join(lines+['END','']);(d/'dry.pdb').write_text(dry)
 for cmd in [['gmx','editconf','-f','dry.pdb','-o','dry.gro','-noc','-box',*[str(x) for x in box],'-nobackup'],['gmx','solvate','-cp','dry.gro','-cs','spc216.gro','-o','solvated.gro','-nobackup']]:
  with (d/(cmd[1]+'.log')).open('w') as f:subprocess.run(cmd,cwd=d,stdout=f,stderr=subprocess.STDOUT,check=True)
 waters,_=_parse_gro((d/'solvated.gro').read_text());before=len(waters);waters,removed=_exclude_waters_near_graphene(waters,dry,clearance_nm=.3,box_nm=box)
 result[stage]={'gmx_waters':before,'wall_removed':removed,'water_sites_after_wall_exclusion':len(waters),'expected_waters_after_replacing_6619_ions':len(waters)-6619}
 (root/'resolvation_census.json').write_text(json.dumps(result,indent=2)+'\n');print(stage,result[stage],flush=True)
