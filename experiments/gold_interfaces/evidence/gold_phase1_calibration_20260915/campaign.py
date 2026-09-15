"""Isolated bulk NPT / gold NVT calibration, retaining every run and input."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import numpy as np
from backend.core import namd_gold_package as gp, namd_solvate as sv, gold_model
from backend.core.md_charge import parse_psf_atoms, audit_psf
from experiments.gold_interfaces.native import read_binary, checkpoint_step

ROOT=Path(__file__).resolve().parents[4]/'workspace/gold_phase1_calibration_20260915'
BIN=Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')
SEEDS=(317,719)

def save(p,m):
    m['asset_sha256']={str(x.relative_to(p)):gp.sha(x) for x in p.rglob('*')
       if x.is_file() and x.name!='manifest.json' and 'output' not in x.parts and x.suffix not in ('.log','.conf')}
    (p/'manifest.json').write_text(json.dumps(m,indent=2))

def template(cell, seed):
    with tempfile.TemporaryDirectory() as t:
        proc=subprocess.run([sv._find_gmx(),'solvate','-cs','spc216.gro','-box',*map(str,cell),'-o','water.gro','-nobackup'],cwd=t,capture_output=True,text=True)
        if proc.returncode: raise RuntimeError(proc.stderr)
        waters,_=sv._parse_gro((Path(t)/'water.gro').read_text())
    offset=np.random.default_rng(seed).uniform(size=3)*cell
    result=[]
    for w in waters:
        q=np.array(list(asdict(w).values())).reshape(3,3)
        q+=np.mod(q[0]+offset,cell)-q[0]
        result.append(sv._Water(*q.ravel()))
    return result

def bulk(seed):
    p=ROOT/f'bulk_{seed}'; p.mkdir();(p/'output').mkdir();(p/'forcefield').mkdir()
    cell=np.array([4.7]*3)
    waters,na,cl,packing=gp.pack(template(cell,seed),np.empty((0,3)),cell,{'kind':'bulk'},150.,seed,6.)
    psf,pdb=gp.dry_pair(np.empty((0,3)))
    psf=sv._extend_psf(psf,waters,na,cl)
    pdb=sv._build_solvated_pdb(pdb,waters,na,cl,tuple(cell),0)
    (p/'system.psf').write_text(psf);(p/'system.pdb').write_text(pdb)
    for name in gp.FF_FILES: shutil.copy2(sv._FF_DIR/name,p/'forcefield'/name)
    (p/'forcefield/gold.prm').write_text(gold_model.parameter_text())
    m=dict(geometry={'kind':'bulk'},cell_nm=cell.tolist(),mobility='mobile',temperature_K=298.15,seed=seed,
           packing=packing,n_atoms=len(parse_psf_atoms(psf)),n_gold=0,qualification_only=True,
           preparation='Independent periodic translation, ion placement and thermostat seed; no gold cavity',
           validation=audit_psf(psf,require_neutral=True,require_dna_hydrogens=False,require_dna_residue_charge=False).to_dict())
    save(p,m);return p

def execute(p,name,steps,previous=None,npt=False,minimize=0):
    m=json.loads((p/'manifest.json').read_text())
    text=gp.config(m,steps=steps,minimize=minimize,prefix=name,restart=previous,
        first_step=checkpoint_step(p,previous) if previous else 0,timestep_fs=1.)
    text=text.replace('DCDfreq 100','DCDfreq 1000').replace('outputEnergies 100','outputEnergies 1000')
    text=text.replace('DCDfreq 1000',f'DCDfreq 1000\nvelDCDfile output/{name}.veldcd\nvelDCDfreq 1000')
    if npt:
        text=text.replace('langevinPiston off','langevinPiston on\nlangevinPistonTarget 1.01325\nlangevinPistonPeriod 200\nlangevinPistonDecay 100\nlangevinPistonTemp 298.15\nuseGroupPressure yes\nuseFlexibleCell no\nuseConstantArea no')
    conf=p/f'{name}.conf';log=p/f'{name}.log';record=p/f'{name}.run.json'
    if conf.exists(): raise FileExistsError(conf)
    spent=sum(json.loads(x.read_text()).get('wall_s',0) for x in ROOT.glob('*/*.run.json'))
    allowance=4*3600-60-spent
    if allowance<=0: raise RuntimeError('Four GPU-hour campaign budget exhausted')
    conf.write_text(text)
    rec=dict(engine_sha256=gp.sha(BIN),config_sha256=gp.sha(conf),steps=steps,previous=previous,npt=npt,
             input_hashes={str(x.relative_to(p)):gp.sha(x) for x in [p/'system.psf',p/'system.pdb']},status='running')
    if previous:
        rec['restart_input_sha256']={ext:gp.sha(p/'output'/f'{previous}.{ext}') for ext in ('coor','vel','xsc')}
    record.write_text(json.dumps(rec,indent=2));start=time.monotonic()
    try:
        with log.open('x') as out:
            r=subprocess.run([str(BIN),'+p2','+devices','0',conf.name],cwd=p,stdout=out,stderr=subprocess.STDOUT,timeout=min(1800,allowance))
        rec['returncode']=r.returncode
        if r.returncode or 'End of program' not in log.read_text(): raise RuntimeError(str(log))
        rec['final_step']=checkpoint_step(p,name)
        expected=(checkpoint_step(p,previous) if previous else 0)+steps+minimize
        if rec['final_step']!=expected:raise RuntimeError('Checkpoint step mismatch')
        if 'Running with GPU-resident mode' not in log.read_text(): raise RuntimeError('Resident mode missing')
        rec['status']='complete'
    except BaseException as exc:
        rec.update(status='failed',error=str(exc))
        raise
    finally:
        rec['wall_s']=time.monotonic()-start;record.write_text(json.dumps(rec,indent=2))
    print(p.name,name,rec['wall_s'],flush=True)

def bulk_waters(p,prefix='npt'):
    atoms=parse_psf_atoms((p/'system.psf').read_text())
    xyz=read_binary(p/'output'/f'{prefix}.coor')/10
    row=next(r for r in (p/'output'/f'{prefix}.xsc').read_text().splitlines() if not r.startswith('#')).split()
    cell=np.array([float(row[i]) for i in (1,5,9)])/10
    ox=[i for i,a in enumerate(atoms) if a.atomtype=='OT']
    q=xyz[np.array(ox)[:,None]+np.arange(3)]
    q+= (np.mod(q[:,0],cell)-q[:,0])[:,None,:]
    return q,cell

def gold(kind,seed,scale=1.,suffix='initial',target_water=None,ion_pairs=None):
    bulkp=ROOT/f'bulk_{seed}'
    q,bcell=bulk_waters(bulkp)
    geom=({'kind':'slab','facet':'111','repeats':[16,9],'layers':5,'gap_nm':3.}
        if kind=='slab' else {'kind':'nanoparticle','radius_nm':.85,'solvent_padding_nm':1.5})
    p=ROOT/f'{kind}_{seed}_{suffix}'
    m=gp.build_package(p,geom,seed=seed)
    xyz,cell,g=gp.layout(geom);cell=np.array(cell)
    linear=scale**(1/3);extent=cell*linear
    tiles=[]
    for ix in np.ndindex(tuple(np.ceil(extent/bcell).astype(int))):
        v=q+np.array(ix)*bcell
        v=v[np.all(v[:,0]<extent,axis=1)]
        v+= (v[:,0]/linear-v[:,0])[:,None,:]
        tiles.extend(sv._Water(*w.ravel()) for w in v)
    oversupply=None
    if target_water is not None:
        candidates,_,_,_=gp.pack(tiles,xyz,cell,g,0.,seed,6.)
        pairs=ion_pairs if ion_pairs is not None else int(np.floor(target_water*150./(55500.-300.)+.5))
        count=target_water+2*pairs;oversupply=len(candidates)
        if count>len(candidates):raise ValueError('Insufficient whole-water inventory for target')
        chosen=np.random.default_rng(seed+991).choice(len(candidates),count,replace=False)
        tiles=[candidates[i] for i in sorted(chosen)]
    salt=150. if ion_pairs is None else ion_pairs*55500./len(tiles)
    waters,na,cl,packing=gp.pack(tiles,xyz,cell,g,salt,seed,6.)
    if ion_pairs is not None:
        packing.update(requested_nominal_salt_mM=150.,ion_count_policy='Fixed to prior revised control to isolate water inventory')
    if target_water is not None and len(waters)!=target_water:raise ValueError('Target water accounting mismatch')
    psf,pdb=gp.dry_pair(xyz);psf=sv._extend_psf(psf,waters,na,cl)
    pdb=sv._build_solvated_pdb(pdb,waters,na,cl,tuple(cell),len(xyz))
    (p/'system.psf').write_text(psf);(p/'system.pdb').write_text(pdb)
    rows=[];ordinal=0
    for row in pdb.splitlines():
        if row.startswith(('ATOM  ','HETATM')):
            ordinal+=1;row=row[:60]+f'{10. if ordinal<=len(xyz) else 0.:6.2f}'+row[66:]
        rows.append(row)
    (p/'gold_reference.pdb').write_text('\n'.join(rows)+'\n')
    atoms=parse_psf_atoms(psf)
    if kind=='slab':
        from backend.core.namd_electrode_gpu import parameter_text
        params=np.zeros((len(atoms),6));params[:,0]=[a.charge for a in atoms]
        c=2*np.pi*gp.COULOMB/np.prod(cell*10)
        (p/'electrode_gpu.params').write_text(parameter_text(params,[2,c,0,cell[2]*10,0]))
    m.update(packing=packing,n_atoms=len(atoms),bulk_reference=str(bulkp),bulk_checkpoint_sha256=gp.sha(bulkp/'output/npt.coor'),
             inventory_scale=scale,bulk_cell_nm=bcell.tolist(),preparation='Tiled independent bulk NPT water snapshot; whole-water center scaling; new ions')
    m.update(target_water=target_water,oversupply_waters=oversupply,fixed_ion_pairs=ion_pairs)
    m['validation']={'charge_audit':audit_psf(psf,require_neutral=True,require_dna_hydrogens=False,require_dna_residue_charge=False).to_dict(),'physical':'pending'}
    save(p,m);return p

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['bulk','gold']);a=ap.parse_args()
    if a.mode=='bulk':
        for seed in SEEDS:
            p=ROOT/f'bulk_{seed}'
            if not p.exists(): p=bulk(seed)
            execute(p,'minimize_v2',0,minimize=500)
            execute(p,'npt',200000,'minimize_v2',npt=True)
    else:
        for kind in ('slab','nanoparticle'):
            for seed in SEEDS:
                p=gold(kind,seed);execute(p,'minimize',0,minimize=500)
                execute(p,'pilot',100000,'minimize')
