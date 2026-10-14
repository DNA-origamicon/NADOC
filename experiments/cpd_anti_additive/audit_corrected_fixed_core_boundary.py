"""Audit fixed-core trajectories and separate actual energy contributions."""
from pathlib import Path
import importlib.util
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now


def native_coulomb_constant():
    """Calibrate the installed engine's prefactor with two unit charges at1nm."""
    import openmm as mm
    from openmm import unit as u
    system=mm.System();force=mm.NonbondedForce()
    for _ in range(2):system.addParticle(1.);force.addParticle(1.,1.,0.)
    system.addForce(force);integrator=mm.VerletIntegrator(.001)
    context=mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
    context.setPositions(np.array([[0.,0.,0.],[1.,0.,0.]])*u.nanometer)
    constant=float(context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole))*10
    del context,integrator
    return constant


def decomposition(system,x,keys,fixed,torsion,coulomb):
    import openmm as mm
    from openmm import unit as u
    fixed=set(fixed);rows=[]
    def scope(ids):
        return 'core_only' if all(i in fixed for i in ids) else 'sugar_only' if all(i not in fixed for i in ids) else 'boundary'
    for fi,force in enumerate(system.getForces()):
        if isinstance(force,mm.PeriodicTorsionForce):
            for i in range(force.getNumTorsions()):
                a,b,c,d,n,phase,k=force.getTorsionParameters(i);ids=[a,b,c,d]
                phi=np.radians(torsion(x,ids));energy=k.value_in_unit(u.kilocalorie_per_mole)*(1+np.cos(n*phi-phase.value_in_unit(u.radian)))
                rows.append(dict(kind='proper',force_index=fi,index=i,atoms=[keys[j] for j in ids],scope=scope(ids),
                    periodicity=int(n),phase_degrees=float(phase.value_in_unit(u.degree)),energy_kcal_mol=float(energy)))
        if isinstance(force,mm.NonbondedForce):
            assert force.getNonbondedMethod()==mm.NonbondedForce.NoCutoff
            particles=[];exceptions={}
            for i in range(force.getNumParticles()):
                q,sigma,epsilon=force.getParticleParameters(i)
                particles.append((q.value_in_unit(u.elementary_charge),sigma.value_in_unit(u.angstrom),epsilon.value_in_unit(u.kilocalorie_per_mole)))
            for i in range(force.getNumExceptions()):
                a,b,qq,sigma,epsilon=force.getExceptionParameters(i)
                exceptions[tuple(sorted((a,b)))]=(qq.value_in_unit(u.elementary_charge**2),sigma.value_in_unit(u.angstrom),epsilon.value_in_unit(u.kilocalorie_per_mole))
            for a in range(len(x)):
                for b in range(a+1,len(x)):
                    qa,sa,ea=particles[a];qb,sb,eb=particles[b];exception=(a,b) in exceptions
                    qq,sigma,epsilon=exceptions.get((a,b),(qa*qb,(sa+sb)/2,np.sqrt(ea*eb)))
                    r=np.linalg.norm(x[a]-x[b]);power=(sigma/r)**6
                    ec=coulomb*qq/r;lj=4*epsilon*(power*power-power)
                    rows.append(dict(kind='nonbonded',force_index=fi,index=[a,b],atoms=[keys[a],keys[b]],scope=scope([a,b]),
                        exception=exception,distance_A=float(r),coulomb_kcal_mol=float(ec),lj_kcal_mol=float(lj),energy_kcal_mol=float(ec+lj)))
    return rows


def audit(root):
    from ase import Atoms
    from ase.io.trajectory import Trajectory
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service');status=read(service/'status.json');ack=read(service/'completion_wake_ack.json')
    assert ack['token']==read(service/'completion_wake.json')['token'] and ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('fixed_core_frozen',root/'executed_source.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);p,model=m.context(root)
    top=read(root/'assessment.json');assert top['error'] is None and len(top['completed'])==2
    engines=[m.Evaluator(checked(p[key])) for key in ['system','parent_system']];fixed=p['fixed_indices'];free=p['free_indices']
    constant=native_coulomb_constant();records=[]
    fit_plan=read(root.parent/'core-bonded-fit-v1/plan.json')
    fitted=np.load(root.parent/'core-bonded-fit-v1/scaled_parameters.npy')
    def core_energy_shift(x):
        total=0.
        for group,value in zip(fit_plan['endpoint_groups'],fitted,strict=True):
            for term in group['terms']:
                ids=term['indices']
                if len(ids)==2:coordinate=np.linalg.norm(x[ids[0]]-x[ids[1]])
                else:
                    a,b,c=x[ids];u=a-b;v=c-b
                    coordinate=np.arccos(np.clip(u@v/(np.linalg.norm(u)*np.linalg.norm(v)),-1.,1.))
                old=coordinate-term['equilibrium'];shift=value*group['scale']
                total+=.5*term['k']*((old-shift)**2-old**2)
        return float(total)
    for point,ref in zip(p['points'],top['completed'],strict=True):
        row=read(checked(ref));assert row['point']==point and row['error'] is None and row['optimizer_converged']
        x0=np.load(checked(point['geometry']))*m.BOHR;x=np.load(checked(row['final_geometry']))
        history=dict(np.load(checked(row['evaluations'])));accepted=dict(np.load(checked(row['accepted'])))
        ids=accepted['evaluated_indices'];xyz=accepted['coordinates_angstrom']
        assert np.array_equal(x,xyz[-1]) and np.array_equal(x0,xyz[0]) and np.array_equal(xyz,history['coordinates_angstrom'][ids])
        assert len(xyz)==row['accepted_states'] and len(history['coordinates_angstrom'])==row['evaluated_states']
        replay_error=0.;force_equivalence=0.;energy_constant_error=0.;reference_constant=None;shift_reconstruction_error=0.
        for q,e,g in zip(history['coordinates_angstrom'],history['energies_kcal_mol'],history['gradients_kcal_A'],strict=True):
            re,rg,_=engines[0].evaluate(q);pe,pg,_=engines[1].evaluate(q)
            replay_error=max(replay_error,abs(re-e),float(np.max(abs(rg-g))))
            force_equivalence=max(force_equivalence,float(np.max(abs(rg[free]-pg[free]))))
            if reference_constant is None:reference_constant=re-pe
            energy_constant_error=max(energy_constant_error,abs(re-pe-reference_constant))
            shift_reconstruction_error=max(shift_reconstruction_error,abs(re-pe-core_energy_shift(q)))
        final_constant_error=abs(re-pe-reference_constant)
        assert replay_error<1e-9 and force_equivalence<1e-10 and shift_reconstruction_error<1e-9 and final_constant_error<1e-9
        trajectory=Trajectory(str(checked(row['native_trajectory'])));assert len(trajectory)==len(xyz)
        for frame,q,index in zip(trajectory,xyz,ids,strict=True):
            assert np.array_equal(frame.positions,q)
            assert abs(frame.get_potential_energy()*m.EV_KCAL-history['energies_kcal_mol'][index])<1e-9
            assert np.max(abs(-frame.get_forces(apply_constraint=False)*m.EV_KCAL-history['gradients_kcal_A'][index]))<1e-9
        trajectory.close()
        native=[line.split() for line in checked(row['native_log']).read_text().splitlines() if line.startswith('AuditedSella')]
        assert len(native)==len(xyz)
        assert all(abs(float(v[3])*m.EV_KCAL-history['energies_kcal_mol'][idx])<2e-5 for v,idx in zip(native,ids,strict=True))
        e,g,parts=engines[0].evaluate(x,True);e0,g0,parts0=engines[0].evaluate(x0,True)
        assert abs(e-row['energy_kcal_mol'])<1e-9 and np.max(abs(g-np.load(checked(row['final_gradient']))))<1e-9
        identity=m.audit_endpoint(x/m.BOHR,model);assert identity['passed']
        constraints,configuration=m.constraints_for(Atoms(model['elements'],positions=x),point,fixed)
        jac=np.array(constraints.jacobian());_,s,v=np.linalg.svd(jac,full_matrices=True);q=v[len(s):].T
        analytic=(q@(q.T@g.ravel())).reshape(x.shape);independent=m.free_projection(x,g,fixed,point['constraint']['indices'])
        assert np.max(abs(analytic-independent))<1e-7
        force=float(np.linalg.norm(analytic,axis=1).max());drift=float(np.max(abs(xyz[:,fixed]-x0[fixed])))
        assert force<.001 and drift<1e-7
        chi_errors=[abs(m.wrapped(m.torsion(v,point['constraint']['indices'])-point['constraint']['target_degrees'])) for v in xyz]
        assert max(chi_errors)<.01
        descriptors=m.descriptors(x0,x,p['fixture'],p['heavy_torsions']);assert descriptors==row['conformer_descriptors']
        named={};evolution=[]
        for name,atoms in p['named_torsions'].items():
            indices=[p['fixture']['atom_keys'].index(a) for a in atoms]
            named[name]=dict(reference_degrees=m.torsion(x0,indices),final_degrees=m.torsion(x,indices),change_degrees=m.wrapped(m.torsion(x,indices)-m.torsion(x0,indices)))
        assert named==row['named_torsions']
        for frame,index in zip(xyz,ids,strict=True):
            evolution.append(dict(evaluated_index=int(index),energy_kcal_mol=float(history['energies_kcal_mol'][index]),
                torsions_degrees={name:m.torsion(frame,[p['fixture']['atom_keys'].index(k) for k in keys]) for name,keys in p['named_torsions'].items()}))
        before=decomposition(engines[0].system,x0,p['fixture']['atom_keys'],fixed,m.torsion,constant)
        after=decomposition(engines[0].system,x,p['fixture']['atom_keys'],fixed,m.torsion,constant);changes=[]
        for old,new in zip(before,after,strict=True):
            assert old['atoms']==new['atoms'] and old['kind']==new['kind'] and old['index']==new['index']
            changes.append(dict(**new,reference_energy_kcal_mol=old['energy_kcal_mol'],change_kcal_mol=new['energy_kcal_mol']-old['energy_kcal_mol']))
        for kind,group in [('proper','3:PeriodicTorsionForce'),('nonbonded','6:NonbondedForce')]:
            assert abs(sum(v['energy_kcal_mol'] for v in before if v['kind']==kind)-parts0[group])<1e-8
            assert abs(sum(v['energy_kcal_mol'] for v in after if v['kind']==kind)-parts[group])<1e-8
        folder=root/point['label'];save(folder/'audited_torsion_evolution.json',dict(at=now(),states=evolution))
        save(folder/'audited_energy_decomposition.json',dict(at=now(),native_coulomb_kcal_A_per_e2=constant,changes=changes,
            interpretation='Exact model energy accounting for proper terms and nonbonded pairs; does not uniquely identify physical error or validate component partitioning against QM.'))
        totals={}
        for kind in ['proper','nonbonded']:
            for scope in ['core_only','sugar_only','boundary']:
                totals[kind+':'+scope]=sum(v['change_kcal_mol'] for v in changes if v['kind']==kind and v['scope']==scope)
        records.append(dict(offset_degrees=point['offset_degrees'],assessment=ref,verified_evaluations=len(history['energies_kcal_mol']),
            accepted_states=len(xyz),replay_max_error=replay_error,free_force_parent_candidate_max_difference=force_equivalence,
            intermediate_parent_candidate_energy_offset_variation=energy_constant_error,
            final_parent_candidate_constant_energy_error=final_constant_error,
            actual_core_energy_shift_reconstruction_error=shift_reconstruction_error,identity=identity,configuration=configuration,
            independent_max_projected_atom_gradient_kcal_mol_A=force,maximum_accepted_fixed_drift_A=drift,maximum_accepted_chi_error_degrees=max(chi_errors),
            named_torsions=named,conformer_descriptors=descriptors,relaxation_energy_kcal_mol=e-e0,
            group_energy_changes={k:parts[k]-parts0[k] for k in parts},scope_energy_changes=totals,
            largest_proper_changes=sorted([v for v in changes if v['kind']=='proper'],key=lambda v:abs(v['change_kcal_mol']),reverse=True)[:12],
            largest_nonbonded_changes=sorted([v for v in changes if v['kind']=='nonbonded'],key=lambda v:abs(v['change_kcal_mol']),reverse=True)[:12],
            energy_decomposition=pin(folder/'audited_energy_decomposition.json'),torsion_evolution=pin(folder/'audited_torsion_evolution.json')))
    for engine in engines:engine.close()
    save(out,dict(at=now(),source=pin(Path(__file__)),plan=pin(root/'plan.json'),status=pin(service/'status.json'),
        acknowledgement=pin(service/'completion_wake_ack.json'),passed=True,native_evidence_passed=True,records=records,
        retained_initial_audit_failure=pin(root/'audit_initial_failure.json'),
        conclusion='At offset0, the large exocyclic/cap/pucker change persists with exact QM core positions. At+30, conformer descriptors remain close. Core-only equilibrium changes cannot affect the conditioned sugar forces; energy gains involve both internal sugar and boundary interactions. A changed MM conformer alone does not prove a force-field defect or establish the preferred QM basin.',
        decision='Acquire one original-method MP2 gradient at the audited offset0 MM alternative, retaining exact original QM fixed-core coordinates and chi. Compare energy and free projected forces against the existing QM conformer before any closure optimization or second fit. One bounded pilot, not a new scan or fit target acceptance.',
        alternate_qm_gradient_pilot_admitted=True,alternate_qm_optimization_admitted=False,new_fit_admitted=False,
        fit_rounds_consumed=1,fit_rounds_max=2,heldout_accessed=False,minimum_certified=False,basin_closure_certified=False,
        simulation_ready=False,cloud_spending_usd=0))
    print([dict(offset=v['offset_degrees'],force=v['independent_max_projected_atom_gradient_kcal_mol_A'],scope_energy_changes=v['scope_energy_changes'],largest_proper=v['largest_proper_changes'][:4]) for v in records])


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
