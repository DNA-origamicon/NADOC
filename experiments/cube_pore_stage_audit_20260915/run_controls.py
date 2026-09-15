"""Exercise every managed stage's settings with a small hydrated graphene control.

Molecular inputs, box geometry, and run lengths are substituted. This checks NAMD
startup and handoffs, not the stability of the full DNA system or ENM forces.
"""
from pathlib import Path
import json, re, subprocess
from backend.core.namd_graphene import graphene_pressure_conf
root=Path(__file__).resolve().parent
repo=root.parents[1]
package=repo/'workspace/md_jobs/d49d12f98a47/package/cube_pore_namd_solvated'
control=repo/'experiments/cube_pore_cavity_20260914/open_pore/fill_100'
z=repo/'experiments/graphene_pressure_implementation_20260914/z'
m=json.loads((package/'manifest.json').read_text())
directory=root/'controls';directory.mkdir(exist_ok=True);(directory/'output').mkdir(exist_ok=True)
base=(z/'production.conf').read_text()
box={a[0]:' '.join(a[1:]) for l in base.splitlines() if (a:=l.split()) and a[0].startswith('cellBasisVector')}
wall=dict(m['graphene_nanopore'],plane_point_nm=[6.177,6.148780367,1.2])
records=[]
for index,name in enumerate([m['minimization']['name']]+[s['name'] for s in m['segments']]):
    original=(package/(name+'.conf')).read_text()
    text=graphene_pressure_conf(original,enabled=True,wall=wall)
    lines=[]
    for line in text.splitlines():
        a=line.split();key=a[0] if a else ''
        if key in {'extraBonds','extraBondsFile'}:continue
        if key=='structure':line=f'structure {control}/system.psf'
        elif key in {'coordinates','consref'}:line=f'{key} {z}/system.pdb'
        elif key=='conskfile':line=f'conskfile {control}/wall.pdb'
        elif key=='parameters':line=f'parameters {package/a[1]}'
        elif key in box:line=f'{key} {box[key]}'
        elif key in {'outputEnergies','xstFreq','restartfreq'}:line=f'{key} 20'
        elif key=='dcdFreq':line='dcdFreq 0'
        elif key=='run':line='run 20'
        lines.append(line)
    text='\n'.join(lines)+'\n'
    if index==0:
        text=f'binCoordinates {z}/resume.coor\n'+text
        for key,value in [('max',40),('min',40),('chunk',20)]:text=re.sub(r'^set nadoc_min_'+key+r' \d+',f'set nadoc_min_{key} {value}',text,flags=re.M)
    path=directory/(name+'.conf');path.write_text(text)
    with (directory/(name+'.log')).open('w') as log:
        proc=subprocess.run(['/home/joshua/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3','+p1','+devices','0',path.name],cwd=directory,stdout=log,stderr=subprocess.STDOUT)
    output=(directory/(name+'.log')).read_text()
    record={'stage':name,'exit_code':proc.returncode,'completed':proc.returncode==0 and 'End of program' in output,'fatal':[l for l in output.splitlines() if 'FATAL ERROR' in l]}
    records.append(record);(root/'runtime.json').write_text(json.dumps(records,indent=2)+'\n');print(record,flush=True)
    if not record['completed']:raise RuntimeError(record)
