"""Freeze corrected training torsions and prepare only the first relaxed scan."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,BOHR,xyz
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_scan_geometry import rotate_sugar,torsion,constraint_metrics,wrapped


def prepare():
    from ase import Atoms
    from sella import Constraints
    campaign=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    prior=campaign/'endpoint-1-optimization-v2';audit=read(prior/'completion_audit.json');old=read(prior/'plan.json')
    if not audit['passed'] or not audit['stationary'] or not audit['optimizer_converged']:raise ValueError('No stationary endpoint')
    result=read(checked(audit['last_accepted_result']));model=read(checked(old['model']))
    x=np.load(checked(result['geometry']));graph=read(checked(model['graph']));bonds=[v['indices'] for v in graph['bonds']]
    design=read(checked(old['reference_design']));membership=design['prospective_membership'];keys=model['atom_keys']
    indices=[keys.index(k) for k in membership['glycosidic_axis_atoms']];phi=torsion(x,indices)
    root=campaign/'glycosidic-training-v1';root.mkdir(exist_ok=False)
    shutil.copy2(Path(__file__),root/'preparation_source.py')
    tasks=[]
    for offset in [-15,15,-30,30]:
        label=('minus' if offset<0 else 'plus')+str(abs(offset));folder=root/label;folder.mkdir()
        y,moving=rotate_sugar(x,bonds,indices,offset)
        if len(moving)!=17:raise ValueError('Wrong glycosidic moving fragment')
        identity=audit_endpoint(y,model)
        np.save(folder/'starting_geometry_bohr.npy',y)
        (folder/'starting.xyz').write_text(xyz(model['elements'],y,f'Corrected training scan seed {offset:+d} deg; not optimized'))
        constraint=dict(indices=indices,atoms=membership['glycosidic_axis_atoms'],target_degrees=wrapped(phi+offset),
            offset_degrees=offset,tolerance_degrees=.01)
        atoms=Atoms(model['elements'],positions=y*BOHR);c=Constraints(atoms);c.fix_dihedral(tuple(indices))
        probe=np.cos(np.arange(y.size)).reshape(y.shape)*1e-3
        report,normal=constraint_metrics(y,probe,constraint)
        sella_normal=c.jacobian()[0].reshape(y.shape)
        projected=probe-sella_normal*np.sum(sella_normal*probe)/np.sum(sella_normal**2)
        max_projected=float(np.linalg.norm(projected,axis=1).max())
        assert abs(max_projected-report['max_atom_gradient_au'])<1e-12
        assert abs(wrapped(np.degrees(c.calc()[0])-constraint['target_degrees']))<1e-8
        passed=identity['passed'] and report['torsion_error_degrees']<1e-8
        save(folder/'seed_audit.json',dict(at=now(),passed=passed,identity=identity,moving_indices=moving,
            preserved_bond_lengths=True,sella_projection_agreement_au=abs(max_projected-report['max_atom_gradient_au']),
            independent_torsion_degrees=torsion(y,indices),sella_torsion_degrees=float(np.degrees(c.calc()[0])),new_qm_evaluations=0))
        tasks.append(dict(label=label,offset_degrees=offset,partition='training',geometry=pin(folder/'starting_geometry_bohr.npy'),
            constraint=constraint,seed_audit=pin(folder/'seed_audit.json'),seed_passed=passed))
    save(root/'design.json',dict(at=now(),reference_design=old['reference_design'],stationarity_audit=pin(prior/'completion_audit.json'),
        reference_result=audit['last_accepted_result'],reference_geometry=result['geometry'],reference_torsion_degrees=phi,
        model=old['model'],training_tasks=tasks,zero_offset='Reuse the audited unconstrained stationary reference.',
        heldout_offsets_degrees=membership['glycosidic_heldout_offsets_deg'],heldout_access='No heldout energies/geometries acquired; lock fitted parameters before generating targets.',
        constraints='Only O4\'-C1\'-N1-C2 torsion is fixed. Every other coordinate relaxes with seven stereocenter/graph screens. Matching QM/MM constraints and reference basin required.',
        branch_policy='Retain all results and failures. A branch change requires explicit comparison and fit-scope review, not silent lowest-energy substitution.',
        minimum_policy='Reference is independently stationary, not Hessian-certified. Scans supply constrained response targets and cannot certify full-dimensional minima.',
        endpoint_equivalence='Exact endpoint-exchanged map is the same data, not an independent sample.',
        deferred_full_endpoint_hessian=dict(estimated_new_gradients=288,estimated_hours=288*audit['mean_gradient_seconds']/3600,
            rationale='Core already certified separately. A full endpoint Hessian is not required to acquire preliminary constrained training response; retain uncertified endpoint status and revisit if branch behavior, curvature or fit residuals require it.'),
        sources=[pin(root/'preparation_source.py'),pin(REPO/'experiments/cpd_anti_additive/endpoint_scan_geometry.py')],simulation_ready=False))
    selected=tasks[0]
    if not selected['seed_passed']:raise ValueError('First training target seed failed; retain all preparation evidence')
    job=campaign/'endpoint-1-glyco-minus15-v1';job.mkdir();(job/'tmp').mkdir()
    shutil.copy2(REPO/'experiments/cpd_anti_additive/corrected_endpoint_optimization.py',job/'executed_source.py')
    plan={**old,'at':now(),'worker':pin(job/'executed_source.py'),'seed_result':None,
        'starting_geometry':selected['geometry'],'scan_design':pin(root/'design.json'),'scan_label':selected['label'],
        'constraint':selected['constraint'],'sources':[*old['sources'],pin(prior/'completion_audit.json'),result['input'],result['geometry'],result['native'],
            *[v['geometry'] for v in tasks],pin(root/'design.json'),pin(root/'preparation_source.py'),
            pin(REPO/'experiments/cpd_anti_additive/endpoint_scan_geometry.py'),pin(REPO/'backend/parameterization/photoproduct_qm.py')],
        'max_new_gradients':20,'hard_seconds':5400,'expected_seconds':20*audit['mean_gradient_seconds']+30,
        'unit':'cpd-corrected-anti1-glyco-minus15-v1','optimizer':{**old['optimizer'],'constraints_tol':1e-8},
        'seed_precision':'Full precision rotated geometry; no gradient reuse at displaced coordinates.',
        'stopping_policy':'Constrained convergence, 20 new gradients or 90-minute cap, 10-minute per-gradient timeout. Audit before continuation.',
        'completion_semantics':'Relaxed training acquisition only. Constrained stationarity is not unconstrained stationarity or minimum certification.'}
    plan.pop('continuation_audit',None)
    save(job/'plan.json',plan)
    spec=importlib.util.spec_from_file_location('frozen_scan',job/'executed_source.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.context(job)
    save(job/'preflight.json',dict(at=now(),passed=True,seed_audit=selected['seed_audit'],frozen_context_verified=True,
        exact_training_membership_verified=True,sella_torsion_and_projection_verified=True,new_qm_evaluations=0))
    save(job/'admission.json',dict(at=now(),proceed=True,plan=pin(job/'plan.json'),preflight=pin(job/'preflight.json'),
        preceding_audit=pin(prior/'completion_audit.json'),necessity='Acquire the first preregistered nonzero glycosidic training target for the corrected endpoint.',
        alternatives='Full endpoint Hessian deferred (~15.5 h), not replaced by a minimum claim. No further unconstrained optimization after audited force convergence. No redundant endpoint-exchanged QM.',
        expected_minutes=plan['expected_seconds']/60,maximum_minutes=90,minimum_certified=False,simulation_ready=False))
    print(job)


if __name__=='__main__':prepare()
