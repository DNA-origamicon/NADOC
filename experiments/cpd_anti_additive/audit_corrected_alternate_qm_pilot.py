"""Reopen native alternate-conformer evidence before admitting one QM chunk."""
from pathlib import Path
import importlib.util
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now


def audit(root):
    from ase import Atoms
    from experiments.cpd_anti_additive.corrected_fixed_core_boundary import constraints_for
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service');status=read(service/'status.json');ack=read(service/'completion_wake_ack.json')
    assert ack['token']==read(service/'completion_wake.json')['token'] and ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('alternate_pilot_frozen',root/'executed_source.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);p,model=m.context(root)
    assessment=read(root/'assessment.json');assert assessment['error'] is None and assessment['completed_gradients']==1
    result=read(root/'result.json');raw=read(root/'raw_result.json');inp=read(checked(result['input']))
    assert inp['options']==p['options'] and result['geometry']==p['geometry']
    x=np.load(checked(result['geometry']));g=np.load(checked(result['gradient_binary']));returned=np.load(checked(result['returned_geometry']))
    assert np.array_equal(x,np.array(inp['geometry_bohr'])) and np.array_equal(x,returned)
    assert np.array_equal(g,np.array(result['gradient_hartree_bohr'])) and raw['energy_hartree']==result['energy_hartree']
    assert np.array_equal(g,np.array(raw['gradient_hartree_bohr']))
    e,native_g,native=m.audit_native(checked(result['native']).read_text(),model['elements'],x)
    assert abs(e-result['energy_hartree'])<1e-9 and np.max(abs(native_g-g))<5.1e-13
    reference=read(checked(p['reference_result']));xr=np.load(checked(reference['geometry']))
    er,gr,reference_native=m.audit_native(checked(reference['native']).read_text(),model['elements'],xr)
    assert abs(er-reference['energy_hartree'])<1e-9 and np.max(abs(gr-np.array(reference['gradient_hartree_bohr'])))<1e-11
    assert np.array_equal(x[p['fixed_indices']],xr[p['fixed_indices']])
    identity=m.audit_endpoint(x,model);assert identity['passed']
    chi=abs(m.wrapped(m.torsion(x,p['constraint']['indices'])-p['constraint']['target_degrees']));assert chi<.01
    projected=m.free_projection(x*m.BOHR,g*m.EH/m.BOHR,p['fixed_indices'],p['constraint']['indices'])
    constraints,configuration=constraints_for(Atoms(model['elements'],positions=x*m.BOHR),dict(constraint=p['constraint']),p['fixed_indices'])
    jac=np.array(constraints.jacobian());_,s,v=np.linalg.svd(jac,full_matrices=True);q=v[len(s):].T
    analytic=(q@(q.T@(g*m.EH/m.BOHR).ravel())).reshape(x.shape)
    assert np.max(abs(analytic-projected))<1e-7
    norms=np.linalg.norm(projected,axis=1);maximum=float(norms.max());rms=float(np.sqrt(np.mean(norms[p['free_indices']]**2)))
    assert abs(maximum-result['free_projected_max_atom_gradient_kcal_mol_A'])<1e-10
    delta=(result['energy_hartree']-reference['energy_hartree'])*m.EH
    assert abs(delta-result['energy_relative_to_reference_kcal_mol'])<1e-12
    toward=m.free_projection(x*m.BOHR,(xr-x)*m.BOHR,p['fixed_indices'],p['constraint']['indices'])
    directional=float(np.sum(projected*toward)/np.linalg.norm(toward))
    largest=[dict(atom=model['atom_keys'][i],projected_gradient_norm_kcal_mol_A=float(norms[i])) for i in np.argsort(norms)[-10:][::-1]]
    save(out,dict(at=now(),source=pin(Path(__file__)),plan=pin(root/'plan.json'),result=pin(root/'result.json'),
        status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),passed=True,native_evidence_passed=True,
        native=native,reference_native=reference_native,identity=identity,configuration=configuration,
        fixed_core_exactly_equal_to_original_qm=True,chi_error_degrees=chi,energy_relative_to_reference_kcal_mol=delta,
        max_free_projected_atom_gradient_kcal_mol_A=maximum,rms_free_projected_atom_gradient_kcal_mol_A=rms,
        max_free_projected_atom_gradient_au=maximum*m.BOHR/m.EH,rms_free_projected_atom_gradient_au=rms*m.BOHR/m.EH,
        largest_free_gradient_atoms=largest,local_tangent_direction_toward_reference_derivative_kcal_mol_A=directional,
        direction_interpretation='Derivative along the normalized Cartesian chord projected into the local constraint tangent. This is not a reaction path, barrier or prediction that optimization returns to the reference basin.',
        native_seconds=result['wall_seconds'],service_seconds=status['finished_at']-status['started_at'],
        decision='Admit one Sella order0/internal fixed-core/chi optimization chunk from this alternate conformer, reusing the exact pilot gradient. At most12new gradients,600seconds per gradient,one-hour service; audit convergence, energy/force progress, conformer identity and necessity before continuation.',
        necessity='The alternate MM state is only1.18kcal/mol above the existing QM conformer but has a26.2kcal/mol/A tangent force. Its unrelaxed energy cannot rank local basins or justify fitting to either. A bounded relaxation resolves a concrete branch-correspondence question without a broader scan.',
        alternatives='No repeated pilot, new scan grid, relaxed-tolerance retry, blind second fit or immediate endpoint Hessian. Reuse194second pilot instead of recomputing it. Keep full coupled core frozen to isolate the observed sugar branch issue.',
        fixed_core_qm_chunk_admitted=True,new_fit_admitted=False,gradient_reuse=pin(root/'result.json'),
        maximum_new_gradients=12,hard_seconds=3600,task_timeout_seconds=600,
        constrained_stationary=False,minimum_certified=False,basin_closure_certified=False,heldout_accessed=False,
        simulation_ready=False,cloud_spending_usd=0))
    print(dict(delta_kcal_mol=delta,projected_max=maximum,projected_rms=rms,local_derivative_toward_reference=directional,
        native_seconds=result['wall_seconds'],next_new_gradient_limit=12))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
