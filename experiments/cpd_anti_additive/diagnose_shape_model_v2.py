"""Inspect all exposed shapes and the locked torsion model; no fitting or energies."""
from pathlib import Path
import shutil
import sys
import warnings
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from ase import Atoms
from sella import Constraints
from openmm import app
from experiments.cpd_anti_additive.score_prospective_v2 import validate, ROOT as SCORES, FIT
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import BOHR, save, now
from experiments.cpd_anti_additive.diagnose_profile_geometry_v2 import examine
from backend.parameterization.photoproduct_qm import _dihedral_degrees

ART = REPO/'.development-artifacts'
OUT = ART/'cpd-anti-shape-model-diagnosis-v1c'


def projector(point, x):
    if point['branch'] == 'remote-unconstrained':
        return lambda g: g
    cons = Constraints(Atoms(point['elements'], positions=x))
    cons.fix_dihedral(tuple(point['record']['torsion_indices']))
    normal = cons.jacobian()[0].reshape(x.shape)
    return lambda g: g-normal*np.sum(normal*g)/np.sum(normal**2)


def feature_gradient(x, ids, n, step):
    result = np.zeros_like(x)
    for i in ids:
        for j in range(3):
            a = x.copy(); b = x.copy(); a[i,j] += step; b[i,j] -= step
            result[i,j] = (np.cos(n*np.radians(_dihedral_degrees(*a[ids])))-
                           np.cos(n*np.radians(_dihedral_degrees(*b[ids]))))/(2*step)
    return result


def main():
    plan, _ = validate()
    score = read(SCORES/'assessment.json'); assert score['all_four_scored']
    fit = read(FIT/'assessment.json'); checked(fit['candidate'])
    receipt = read(ART/'cpd-anti-conformational-inputs-v2/receipt.json')
    points = read(checked(receipt['inventory']))['records']
    candidates = read(checked(fit['profile_results']))
    baselines = read(FIT/'baseline_progress.json')
    assert len(points) == len(candidates) == len(baselines) == 19
    variables = read(checked(fit['fit']))['coefficients']
    selected_types = {tuple(v['types']) for v in variables}
    OUT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__), OUT/'worker.py')
    sources = [source(FIT/p) for p in ['assessment.json','baseline_progress.json','candidate_progress.json','fit.json']]
    sources += [source(SCORES/'assessment.json'), source(OUT/'worker.py'), receipt['inventory'], plan['candidate'], plan['candidate_lock']]
    sources += [source(REPO/'experiments/cpd_anti_additive'/p) for p in
                ['diagnose_profile_geometry_v2.py','score_prospective_v2.py','validation_gate.py']]
    for p in points:
        sources += [p['geometry_source'], p['qm_source'], p['native']]
    pairs = [(p,c,b) for p,c,b in zip(points,candidates,baselines)]
    for row in score['records']:
        assert row['state'] == 'scored'
        for ref in row['evidence']: checked(ref); sources.append(ref)
        folder = SCORES/row['case_id']
        pairs.append((read(folder/'point.json'), read(folder/'MM/assessment.json'), None))
    assert len(pairs) == 23
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params = app.CharmmParameterSet(str(checked(plan['candidate'])))
    systems = {}; inventories = []
    for e in (1,2):
        folder = Path(plan['parent'])/f'endpoint-{e}'
        psf = app.CharmmPsfFile(str(folder/'fragment.psf')); names = read(folder/'atom_map.json')
        psf.loadParameters(params)
        systems[e] = psf
        sources += [source(folder/'fragment.psf'), source(folder/'atom_map.json')]
        elements = next(p['elements'] for p in points if p['endpoint'] == e)
        propers = []
        for t in psf.dihedral_list:
            atoms = [t.atom1,t.atom2,t.atom3,t.atom4]; ids = [a.idx for a in atoms]
            if not any(names[i].endswith(':N1') for i in ids[1:3]) or any(elements[i]=='H' for i in ids): continue
            types = tuple(a.attype for a in atoms); canonical = min(types, types[::-1])
            propers.append(dict(names=[names[i] for i in ids], types=list(canonical),
                varied_in_round_one=canonical in selected_types,
                terms=[dict(k_kcal=float(v.phi_k), multiplicity=int(v.per), phase_deg=float(v.phase))
                       for v in params.dihedral_types[canonical]]))
        impropers = []
        for t in psf.improper_list:
            ids = [t.atom1.idx,t.atom2.idx,t.atom3.idx,t.atom4.idx]
            impropers.append(dict(names=[names[i] for i in ids], k_kcal=float(t.improper_type.k),
                                  equilibrium_deg=float(t.improper_type.phieq)))
        inventories.append(dict(endpoint=e, heavy_N1_central_propers=propers, all_impropers=impropers))
    save(OUT/'plan.json',dict(at=now(),sources=sources,case_ids=[p['case_id'] for p,_,_ in pairs],
        scope='Read saved coordinates/gradients; inspect existing topology/parameters and unit Fourier gradients only.',
        maximum_cases=23,no_new_QM_or_MM_energy=True,no_optimization_or_parameter_fit=True))
    rows=[]
    for p,c,b in pairs:
        assert p['case_id'] == c['case_id'] and (b is None or b['case_id'] == p['case_id'])
        psf = systems[p['endpoint']]; q=np.asarray(p['geometry_bohr'])*BOHR
        project=projector(p,q)
        row=examine(p,c,psf)
        raw=np.load(checked(c['raw_evaluations'])); sources.append(c['raw_evaluations'])
        assert np.max(abs(raw['coordinates_A'][0]-q))<1e-10
        g=project(raw['gradients_kcal_A'][0])
        row['candidate_projected_gradient_at_QM_max_kcal_A']=float(np.linalg.norm(g,axis=1).max())
        row['candidate_N1_projected_gradients_kcal_A']={n:g[i].tolist() for i,n in enumerate(p['atom_map']) if n.endswith(':N1')}
        if b is not None:
            row['baseline_shape']=examine(p,b,psf)
            original=np.load(checked(b['raw_evaluations'])); sources.append(b['raw_evaluations'])
            assert np.max(abs(original['coordinates_A'][0]-q))<1e-10
            gb=project(original['gradients_kcal_A'][0])
            row['baseline_projected_gradient_at_QM_max_kcal_A']=float(np.linalg.norm(gb,axis=1).max())
            row['baseline_N1_projected_gradients_kcal_A']={n:gb[i].tolist() for i,n in enumerate(p['atom_map']) if n.endswith(':N1')}
        features=[]
        for v in variables:
            if not all(n in p['atom_map'] for n in v['names']): continue
            ids=[p['atom_map'].index(n) for n in v['names']]
            checks=[]
            for h in (1e-4,1e-5):
                fg=feature_gradient(q,ids,v['periodicity'],h)
                checks.append(dict(step_A=h,cartesian_norm=float(np.linalg.norm(fg)),
                                   constraint_tangent_norm=float(np.linalg.norm(project(fg)))))
            constraint=list(p['record']['torsion_indices'])
            frozen=bool(p['branch']!='remote-unconstrained' and (ids==constraint or ids[::-1]==constraint))
            if frozen: assert checks[-1]['constraint_tangent_norm']<1e-7
            features.append(dict(names=v['names'],periodicity=v['periodicity'],same_as_frozen_coordinate=frozen,checks=checks))
        row['round_one_feature_sensitivity']=features
        rows.append(row)
    # Hash the complete read set after analysis; preserve every previous verdict.
    sources += [r['final_geometry'] for _,r,_ in pairs]
    sources += [b['final_geometry'] for _,_,b in pairs if b is not None]
    for ref in sources: checked(ref)
    failures=[r['case_id'] for r in rows if not r['branch_descriptor_match']]
    baseline_failures=[r['case_id'] for r in rows if r.get('baseline_shape') and not r['baseline_shape']['branch_descriptor_match']]
    result=dict(at=now(),plan=source(OUT/'plan.json'),sources=sources,cases=rows,parameter_inventory=inventories,
        baseline_failures=baseline_failures,candidate_failures=failures,
        conclusion='Two of four fitted proper families (six of twelve coefficients across both endpoints) are the scanned torsion itself: its three Fourier multiplicities per endpoint have zero tangent gradient when that coordinate is constrained. The other attachment proper can affect shape, but ring-centered terms and N1 out-of-plane balance were not directly fitted.',
        caveat='N1 signed heights are descriptors, not new stereochemical gates. Missing explicit N1 improper does not establish a missing physical force: proper, angle and nonbonded terms also control out-of-plane response.',
        no_new_QM_or_MM_energy=True,no_optimization_or_parameter_fit=True,old_verdicts_preserved=True,
        minimum_certified=False,simulation_ready=False)
    frozen_features=[f for r in rows for f in r['round_one_feature_sensitivity'] if f['same_as_frozen_coordinate']]
    assert len(failures)==8 and len(frozen_features)==66
    result['frozen_feature_checks']=len(frozen_features)
    result['maximum_frozen_feature_tangent_norm_A_inverse']=max(f['checks'][-1]['constraint_tangent_norm'] for f in frozen_features)
    save(OUT/'assessment.json',result)
    print(dict(cases=len(rows),baseline_failures=baseline_failures,candidate_failures=failures))


if __name__=='__main__':main()
