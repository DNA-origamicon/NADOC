"""Isolated fixed-charge gold screening controls; not a production gold model."""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
from backend.core import namd_gold_package as gp, namd_solvate as sv
from backend.core.md_charge import parse_psf_atoms, audit_psf
from backend.core.namd_electrode_gpu import parameter_text
from experiments.gold_interfaces.evidence.gold_phase1_calibration_20260915 import campaign as previous

REPO=Path(__file__).resolve().parents[3]
ROOT=REPO/'.development-artifacts/gold_screening_20260915'
PRIOR=REPO/'.development-artifacts/gold_phase1_calibration_20260915'
SEEDS=(317,719)

def save(p,m):
    previous.save(p,m)

def prepare(seed):
    spec=dict(kind='slab',facet='111',repeats=[28,16],layers=5,gap_nm=6.)
    p=ROOT/f'neutral_{seed}'
    m=gp.build_package(p,spec,seed=seed,temperature_K=300.,salt_mM=0.)
    xyz,cell,geom=gp.layout(spec);cell=np.array(cell);area=np.prod(cell[:2])
    old=json.loads((PRIOR/f'slab_{seed}_calibrated_fixed_ions/manifest.json').read_text())
    density=33.76000592463737
    # Transfer measured surface excess, add bulk water for the increased gap.
    surface_excess=2017/np.prod(old['cell_nm'][:2])-density*3
    target=round(area*(density*6+surface_excess));ions=64
    q,bcell=previous.bulk_waters(PRIOR/f'bulk_{seed}')
    linear=1.22**(1/3);extent=cell*linear;tiles=[]
    for index in np.ndindex(tuple(np.ceil(extent/bcell).astype(int))):
        v=q+np.array(index)*bcell
        v=v[np.all(v[:,0]<extent,axis=1)]
        v+=(v[:,0]/linear-v[:,0])[:,None,:]
        low,high=geom['liquid_bounds_nm']
        v=v[np.all((v[:,:,2]>low)&(v[:,:,2]<high),axis=1)]
        tiles.extend(sv._Water(*w.ravel()) for w in v)
    candidates,_,_,_=gp.pack(tiles,xyz,cell,geom,0.,seed,6.)
    if len(candidates)<target+2*ions:raise ValueError('Insufficient water candidates')
    selected=np.random.default_rng(seed+991).choice(len(candidates),target+2*ions,replace=False)
    waters,na,cl,packing=gp.pack([candidates[i] for i in sorted(selected)],xyz,cell,geom,ions*55500/(target+2*ions),seed,6.)
    assert len(waters)==target and len(na)==len(cl)==64
    psf,pdb=gp.dry_pair(xyz)
    psf=sv._extend_psf(psf,waters,na,cl)
    pdb=sv._build_solvated_pdb(pdb,waters,na,cl,tuple(cell),len(xyz))
    (p/'system.psf').write_text(psf);(p/'system.pdb').write_text(pdb)
    rows=[];i=0
    for row in pdb.splitlines():
        if row.startswith(('ATOM  ','HETATM')):
            i+=1;row=row[:60]+f'{10. if i<=len(xyz) else 0.:6.2f}'+row[66:]
        rows.append(row)
    (p/'gold_reference.pdb').write_text('\n'.join(rows)+'\n')
    m.update(schema='nadoc.gold_screening_experiment.v1',n_atoms=len(parse_psf_atoms(psf)),packing=packing,
        experimental_only=True,qualified=False,
        preparation=dict(bulk_snapshot=str(PRIOR/f'bulk_{seed}'),bulk_sha256=gp.sha(PRIOR/f'bulk_{seed}/output/npt.coor'),
            pilot_bulk_density_nm3=density,source_temperature_K=298.15,run_temperature_K=300.,
            surface_excess_water_per_nm2=surface_excess,target_waters=target,
            limitation='Transferred inventory from 3 nm/150 mM pilot; density at 6 nm and new salt must be measured.'),
        screening=dict(surface_charge_e_nm2=0.,surface_charge_C_m2=0.,constant_potential=False,
            interpretation='Neutral INTERFACE Au contact baseline',area_nm2=float(area),gap_nm=6.,ions_per_species=64))
    update_params(p,m)
    charged=ROOT/f'charged_{seed}';shutil.copytree(p,charged)
    cm=json.loads((charged/'manifest.json').read_text())
    qau=np.zeros(len(xyz));lo,hi=geom['liquid_bounds_nm']
    negative=np.isclose(xyz[:,2],lo);positive=np.isclose(xyz[:,2],hi)
    total=.25*area;qau[negative]=-total/negative.sum();qau[positive]=total/positive.sum()
    lines=psf.splitlines();start=next(i for i,s in enumerate(lines) if '!NATOM' in s)+1
    for i,value in enumerate(qau):
        parts=lines[start+i].split();parts[6]=f'{value:.10f}';lines[start+i]=' '.join(parts)
    (charged/'system.psf').write_text('\n'.join(lines)+'\n')
    cm['screening'].update(surface_charge_e_nm2=.25,surface_charge_C_m2=.25*.1602176634,
        interpretation='Experimental prescribed charges on inner Au layers plus neutral-IFF LJ; no induced/image response',
        prescribed_charge_per_surface_atom_e=float(total/negative.sum()),surface_atoms_per_side=int(negative.sum()),
        electrode_charge_magnitude_e=float(total))
    # Explicitly distinguish this experiment from the registered neutral force field.
    cm['gold_model']['experimental_charge_override']='See screening; neutral IFF LJ retained, charges changed only in this isolated package'
    update_params(charged,cm)
    print('prepared',seed,'waters',target,'area',area,'atoms',cm['n_atoms'],flush=True)

def update_params(p,m):
    atoms=parse_psf_atoms((p/'system.psf').read_text());q=np.array([a.charge for a in atoms])
    audit=audit_psf((p/'system.psf').read_text(),require_neutral=True,require_dna_hydrogens=False,require_dna_residue_charge=False)
    assert audit.passed,audit.errors
    params=np.zeros((len(q),6));params[:,0]=q
    cell=np.array(m['cell_nm']);coefficient=2*np.pi*gp.COULOMB/np.prod(cell*10)
    (p/'electrode_gpu.params').write_text(parameter_text(params,[2,coefficient,0,cell[2]*10,0]))
    m['validation']={'charge_audit':audit.to_dict(),'physical':'unqualified'}
    save(p,m)

def execute(p,name,steps,previous_name=None,minimize=0):
    prior_cost=60+sum(json.loads(x.read_text()).get('wall_s',0) for x in PRIOR.glob('*/*.run.json'))
    current=sum(json.loads(x.read_text()).get('wall_s',0) for x in ROOT.glob('*/*.run.json'))
    if prior_cost+current>3.5*3600:raise RuntimeError('Reserve remaining time within four-hour total budget')
    previous.ROOT=ROOT
    previous.execute(p,name,steps,previous=previous_name,minimize=minimize)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','run']);args=ap.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    if args.mode=='prepare':
        for seed in SEEDS:prepare(seed)
    else:
        for seed in SEEDS:
            for kind in ('neutral','charged'):
                p=ROOT/f'{kind}_{seed}'
                execute(p,'minimize',0,minimize=1000)
                execute(p,'pilot',300000,'minimize')
