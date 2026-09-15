"""Read-only audit of all packaged configs and managed restart handoffs."""
from pathlib import Path
from collections import defaultdict, Counter
import json, re, hashlib
from backend.core.remote_resume_conf import build_resume_conf
from backend.core.md_protocols import build_remote_resume_conf
from backend.core.namd_graphene import graphene_pressure_conf, validate_graphene_wall_package
root=Path(__file__).resolve().parent
package=root.parents[1]/'workspace/md_jobs/d49d12f98a47/package/cube_pore_namd_solvated'
m=json.loads((package/'manifest.json').read_text())
validate_graphene_wall_package(package)
def directives(text):
    d=defaultdict(list)
    for number,line in enumerate(text.splitlines(),1):
        a=line.split('#',1)[0].split(';',1)[0].split()
        if a:d[a[0].lower()].append((number,' '.join(a[1:])))
    return d
def val(d,k):return d[k.lower()][-1][1] if k.lower() in d else None
records=[]; errors=[]; files=set(); previous=m['minimization']['name']
filekeys=['structure','coordinates','parameters','extrabondsfile','consref','conskfile']
for f in sorted(package.glob('*.conf')):
    text=f.read_text();d=directives(text)
    duplicate={k:v for k,v in d.items() if len(v)>1 and k not in {'parameters','extrabondsfile','set','if','}','incr'}}
    record={'file':f.name,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'timestep':val(d,'timestep'),'piston':val(d,'langevinPiston'),'duplicates':duplicate,'inputs':{}}
    for key in filekeys:
        for _,name in d.get(key,[]):
            files.add(name);record['inputs'][name]=(package/name).is_file()
            if not (package/name).is_file():errors.append(f'{f.name}: missing {name}')
    # All managed dynamics are plain top-level commands; only minimization has a loop.
    if 'NADOC_ADAPTIVE_MIN_BEGIN' in text:
        before=text[:text.index('# NADOC_ADAPTIVE_MIN_BEGIN')]
        record['origin_before_adaptive_loop']='cellOrigin' in before
    else:
        first=next((i for i,l in enumerate(text.splitlines(),1) if re.match(r'^\s*(run|minimize)\s',l)),None)
        record['initialization_after_execution']=[k for k in ['cellorigin','langevinpiston','fixcelldimx','fixcelldimy','fixcelldimz','bincoordinates','binvelocities','extendedsystem','structure','constraints'] if first and any(n>first for n,_ in d.get(k,[]))]
        assert not record['initialization_after_execution']
    records.append(record)
for s in m['segments']:
    text=(package/(s['name']+'.conf')).read_text();d=directives(text)
    assert s['previous']==previous
    for key,ext in [('binCoordinates','coor'),('binVelocities','vel'),('extendedSystem','xsc')]:assert val(d,key)==f'output/{previous}.{ext}'
    assert int(val(d,'run'))==s['steps'] and s['steps']%int(val(d,'stepspercycle'))==0
    if s.get('timestep_fs'):assert float(val(d,'timestep'))==s['timestep_fs']
    assert val(d,'langevinPiston')=='on'
    assert [val(d,'fixCellDim'+a) for a in 'XYZ']==['yes','yes','no']
    assert val(d,'useConstantArea')=='yes' and val(d,'langevinPistonTarget')=='1.01325'
    assert val(d,'rigidBonds')=='all' and val(d,'structure')=='cube_pore_hmr.psf'
    for restart in [5000,s['steps']-20]:
        for kind in ['alpine','continuation']:
            resume=build_resume_conf(text,s['name'],restart,s['steps']) if kind=='alpine' else build_remote_resume_conf(text,segment_name=s['name'],restart_step=restart,total_steps=s['steps'])
            rd=directives(resume)
            assert int(val(rd,'run'))==s['steps']-restart and int(val(rd,'firsttimestep'))==restart
            for key,ext in [('binCoordinates','coor'),('binVelocities','vel'),('extendedSystem','xsc')]:assert val(rd,key)==f"output/{s['name']}.restart.{ext}"
            assert all(val(rd,k)==val(d,k) for k in ['cellOrigin','fixCellDimX','fixCellDimY','fixCellDimZ','timestep','structure','consref','conskfile'])
            assert max(rd[k.lower()][0][0] for k in ['cellOrigin','binCoordinates','binVelocities','extendedSystem','firsttimestep'])<rd['run'][0][0]
    previous=s['name']
# Every referenced PDB must preserve PSF-sized atom ordering, including combined restraints.
counts={};restraints={}
for name in sorted(files):
    if not name.endswith('.pdb'):continue
    count=0;active=Counter()
    with (package/name).open() as stream:
        for line in stream:
            if line.startswith(('ATOM','HETATM')):
                count+=1
                if name.startswith('restraints') and float(line[60:66])!=0:active[line[17:21].strip()]+=1
    counts[name]=count
    if active:restraints[name]=dict(active)
assert len(set(counts.values()))==1,counts
psfs={}
for name in ['cube_pore.psf','cube_pore_hmr.psf']:
    with (package/name).open() as stream:
        n=next(int(line.split()[0]) for line in stream if '!NATOM' in line)
        digest=hashlib.sha256();charge=mass=0.;minimum=1e9
        for _ in range(n):
            a=next(stream).split();digest.update(' '.join(a[:7]).encode());charge+=float(a[6]);mass+=float(a[7]);minimum=min(minimum,float(a[7]))
        psfs[name]={'atoms':n,'identity_charge_sha256':digest.hexdigest(),'charge':charge,'mass':mass,'minimum_mass':minimum}
assert len({v['identity_charge_sha256'] for v in psfs.values()})==1
assert all(v['atoms']==next(iter(counts.values())) and v['minimum_mass']>0 for v in psfs.values())
result={'job':'d49d12f98a47','managed_stages':len(m['segments'])+1,'auxiliary_configs':2,'resume_variants_checked':len(m['segments'])*4,'errors':errors,'configs':records,'pdb_atom_counts':counts,'nonzero_restraint_residues':restraints,'psfs':psfs}
(root/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['configs','pdb_atom_counts','nonzero_restraint_residues']},indent=2))
assert not errors
