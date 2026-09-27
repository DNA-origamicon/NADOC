"""Read saved coordinates/logs only; do not evaluate a force field or optimize."""
import json
from pathlib import Path
import sys

import numpy as np
from openmm import app

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now

ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-construction-method-review-v1'
FAILED=ART/'cpd-anti-fitted-conditioning-v2'
MODEL=ART/'cpd-anti-fitted-dna-v2-r1'


def aligned_rms(x,y):
    x=x-x.mean(0);y=y-y.mean(0)
    a,_,b=np.linalg.svd(x.T@y)
    rot=a@np.diag([1,1,np.linalg.det(a@b)])@b
    return float(np.sqrt(np.mean(np.sum((x@rot-y)**2,axis=1))))


def main():
    ROOT.mkdir(exist_ok=False)
    (ROOT/'executed_source.py').write_text(Path(__file__).read_text())
    result=read(FAILED/'assessment.json');plan=read(checked(result['plan']))
    for s in plan['sources']:checked(s)
    psf=app.CharmmPsfFile(str(MODEL/'anti.psf'))
    x=np.loadtxt(ART/'cpd-anti-placement-review-v2/current_A.txt')
    seed=np.loadtxt(FAILED/'starting_A.txt')
    final=np.loadtxt(checked(result['coordinates']))
    assert np.array_equal(seed,np.loadtxt(MODEL/'starting_A.txt'))
    mobile=plan['mobile_indices'];fixed=np.setdiff1d(np.arange(len(x)),mobile)
    topology=read(ART/'cpd-anti-dna-topology-v2b/assessment.json')
    endpoint_positions={(e['segid'],e['resid']) for e in topology['endpoints']}
    base=[a.idx for a in psf.atom_list if (a.system,a.residue.idx) in endpoint_positions
        and "'" not in a.name and a.name not in ('P','OP1','OP2')]
    heavybase=[i for i in base if psf.atom_list[i].mass.value_in_unit(__import__('openmm').unit.dalton)>2]
    sourcefiles=[FAILED/'plan.json',FAILED/'assessment.json',FAILED/'starting_A.txt',FAILED/'candidate_A.txt',
        FAILED/'final_reference_force.json',MODEL/'openmm_static.npz',MODEL/'run.log',MODEL/'anti.psf',
        ART/'cpd-anti-placement-review-v2/current_A.txt']
    frames=[(0,seed,FAILED/'starting_A.txt')]
    for folder in sorted(FAILED.glob('chirality_constrained-[0-9]*')):
        coord=folder/'coordinates_A.txt';frames.append((int(folder.name.rsplit('-',1)[1]),np.loadtxt(coord),coord))
    rows=[]
    for iteration,y,path in frames:
        assert np.array_equal(x[fixed],y[fixed])
        rows.append(dict(iteration=iteration,coordinates=source(path),
            maximum_lesion_base_displacement_A=float(np.linalg.norm(y[base]-x[base],axis=1).max()),
            maximum_lesion_heavy_base_displacement_A=float(np.linalg.norm(y[heavybase]-x[heavybase],axis=1).max()),
            heavy_base_center_shift_from_seed_A=float(np.linalg.norm(y[heavybase].mean(0)-seed[heavybase].mean(0))),
            aligned_heavy_base_rms_to_seed_A=aligned_rms(seed[heavybase],y[heavybase]),
            mobile_rms_displacement_from_source_A=float(np.sqrt(np.mean(np.sum((y[mobile]-x[mobile])**2,axis=1)))),
            fixed_atoms_unchanged=True))
    residues=[]
    for residue in psf.residue_list:
        ids=[a.idx for a in residue.atoms if a.idx in mobile and a.mass.value_in_unit(__import__('openmm').unit.dalton)>2]
        if not ids:continue
        residues.append(dict(residue=f'{residue.system}:{residue.idx}',
            max_heavy_atom_displacement_from_source_A=float(np.linalg.norm(final[ids]-x[ids],axis=1).max()),
            center_shift_from_seed_A=float(np.linalg.norm(final[ids].mean(0)-seed[ids].mean(0)))))
    residues.sort(key=lambda r:r['max_heavy_atom_displacement_from_source_A'],reverse=True)
    native_lines=(MODEL/'run.log').read_text().splitlines()
    titles=next(l.split()[1:] for l in native_lines if l.startswith('ETITLE:'))
    values=next([float(v) for v in l.split()[1:]] for l in native_lines if l.startswith('ENERGY:'))
    components=dict(zip(titles,values))
    initial=np.load(MODEL/'openmm_static.npz')['energy_kcal'].item()
    final_energy=read(FAILED/'final_reference_force.json')['energy_kcal']
    report=dict(schema='nadoc.cpd-anti-construction-method-review.v1',created_at=now(),
        sources=[source(p) for p in sourcefiles],author=source(Path(__file__)),
        no_new_QM_MM_energy_evaluations=True,no_optimization_or_dynamics=True,
        net_charge_e=float(sum(a.charge for a in psf.atom_list)),atom_count=len(psf.atom_list),
        environment='No solvent or ions; unswitched vacuum; 514 mobile and 2529 fixed DNA atoms',
        checkpoints=rows,largest_residue_displacements=residues,
        initial_native_components_kcal=components,component_scope='Initial geometry only; no trajectory component decomposition available',
        saved_reference_energy_change_kcal=float(final_energy-initial),
        displacement_screen_passed_at_any_saved_frame=any(r['maximum_lesion_base_displacement_A']<=3.5 for r in rows),
        final_aligned_heavy_base_rms_to_seed_A=rows[-1]['aligned_heavy_base_rms_to_seed_A'],
        interpretation='Energy reduction accompanies greater displacement; the existing seed already fails the product displacement screen. Optimizer completion would not by itself resolve that failure.',
        hypothesis='Unscreened charged DNA and the fixed boundary may favor displacement during vacuum conditioning. These observations do not establish causation; a solvent/context control is needed.',
        selected_next_method_review='Solvated, charge-neutralized, staged positional-restraint construction with unchanged CPD/parent parameters and a matched undamaged control. Freeze a separate versioned bounded engineering plan before launch; retain every existing verdict and threshold.',
        original_policy_changed=False,full_DNA_dynamics_ready=False,simulation_ready=False)
    save(ROOT/'assessment.json',report)
    print(json.dumps({k:report[k] for k in ('net_charge_e','saved_reference_energy_change_kcal',
        'displacement_screen_passed_at_any_saved_frame','final_aligned_heavy_base_rms_to_seed_A')},indent=2))
    print('Checkpoints',[(r['iteration'],round(r['maximum_lesion_base_displacement_A'],3),round(r['heavy_base_center_shift_from_seed_A'],3)) for r in rows])
    print('Largest residue displacements',residues[:4])


if __name__=='__main__':main()
