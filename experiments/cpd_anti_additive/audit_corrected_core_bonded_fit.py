"""Audit the bounded fit, actual native states and local MM curvature separately."""
from pathlib import Path
import importlib.util
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now


def audit(root):
    import openmm as mm
    from openmm import unit as u
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service');status=read(service/'status.json');ack=read(service/'completion_wake_ack.json')
    assert ack['token']==read(service/'completion_wake.json')['token'] and ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('core_fit_frozen',root/'executed_source.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);p=m.context(root)
    assert read(root/'assessment.json')['error'] is None
    arrays=dict(np.load(checked(p['response_arrays'])));fit=read(root/'fit_result.json');candidate=read(root/'candidate_parameters.json')
    checked(candidate['plan']);checked(candidate['fit']);z=np.load(root/'scaled_parameters.npy')
    assert np.array_equal(z,np.array(fit['scaled_parameters'])) and np.max(abs(z))<=2+1e-12
    engines={};systems=[]
    for label,fixture,groups in [('core',p['fixture'],p['groups']),('endpoint',p['endpoint_fixture'],p['endpoint_groups'])]:
        original=mm.XmlSerializer.deserialize(checked(fixture['systems']['last']).read_text())
        engine=m.Evaluator(checked(candidate[label]));engines[label]=engine
        modified=engine.system
        assert original.getNumParticles()==modified.getNumParticles() and original.getNumForces()==modified.getNumForces()
        for i in range(original.getNumParticles()):assert original.getParticleMass(i)==modified.getParticleMass(i)
        shifts={}
        for gr,value in zip(groups,z,strict=True):
            for term in gr['terms']:shifts[(term['force_index'],term['index'])]=value*gr['scale']
        for fi,(before,after) in enumerate(zip(original.getForces(),modified.getForces(),strict=True)):
            if fi not in (0,1):assert mm.XmlSerializer.serialize(before)==mm.XmlSerializer.serialize(after);continue
            count=before.getNumBonds() if fi==0 else before.getNumAngles()
            assert count==(after.getNumBonds() if fi==0 else after.getNumAngles())
            for i in range(count):
                a=before.getBondParameters(i) if fi==0 else before.getAngleParameters(i)
                b=after.getBondParameters(i) if fi==0 else after.getAngleParameters(i)
                assert a[:-2]==b[:-2] and a[-1]==b[-1]
                unit=u.angstrom if fi==0 else u.radian
                assert abs((b[-2]-a[-2]).value_in_unit(unit)-shifts.get((fi,i),0.))<1e-12
        systems.append(dict(fixture=label,candidate=candidate[label],changed_equilibria=len(shifts),
                            all_other_parameters_and_force_constants_identical=True))
    baseline=m.Evaluator(checked(p['fixture']['systems']['last']));static=read(root/'static_core.json')['records']
    bg=[];be=[];qmg=[];qme=[];observed=[];candidate_g=[];max_replay=0.
    constant=sum(.5*t['k']*((t['equilibrium']+v*g['scale'])**2-t['equilibrium']**2)
                 for g,v in zip(p['groups'],z,strict=True) for t in g['terms'])
    for i,(point,row) in enumerate(zip(p['points'],static,strict=True)):
        assert row['point']==point
        x=np.load(checked(point['geometry']))*m.BOHR;qm=read(checked(point['qm_result']))
        e0,g0,_=baseline.evaluate(x);e,g,parts=engines['core'].evaluate(x,True);bv,gg=m.basis(x,p['groups'])
        assert np.max(abs(gg-arrays['basis_gradients'][i]))<1e-12
        assert abs(e-(e0+bv@z+constant))<1e-9 and np.max(abs(g.ravel()-(g0.ravel()+gg@z)))<1e-9
        assert abs(e-row['energy_kcal_mol'])<1e-9 and np.max(abs(g-np.load(checked(row['gradient']))))<1e-9
        assert all(abs(parts[k]-v)<1e-9 for k,v in row['force_groups'].items())
        bg.append(g0.ravel());be.append(e0);qmg.append(np.array(qm['gradient_hartree_bohr']).ravel()*m.EH/m.BOHR)
        qme.append(qm['energy_hartree']*m.EH);observed.append(e);candidate_g.append(g.ravel())
    bg=np.array(bg);qmg=np.array(qmg);cg=np.array(candidate_g);x0=arrays['core_geometry'];q=m.internal_basis(x0)
    for key,value in [('baseline_gradients',bg),('baseline_energies',be),('qm_gradients',qmg),('qm_energies',qme)]:
        assert np.max(abs(arrays[key]-value))<1e-9
    h0,_=m.finite_hessian(lambda x:baseline.evaluate(x)[1].ravel(),x0,5e-5)
    hc,_=m.finite_hessian(lambda x:engines['core'].evaluate(x)[1].ravel(),x0,5e-5)
    htarget=arrays['qm_hessian'];hlinear=arrays['baseline_hessian']+np.einsum('ijp,p->ij',arrays['basis_hessian'],z)
    assert np.max(abs(hc-hlinear))<1e-3
    native_blocks=[(bg[0]-qmg[0],cg[0]-qmg[0],1.),
                   (q.T@(h0-htarget)@q,q.T@(hc-htarget)@q,10.),
                   ((bg[1:]-bg[0])-(qmg[1:]-qmg[0]),(cg[1:]-cg[0])-(qmg[1:]-qmg[0]),1.)]
    blocks=[];start=0
    for block,(before,after,scale) in zip(p['blocks'],native_blocks,strict=True):
        end=start+block['rows'];a=arrays['design'][start:end];b=arrays['target'][start:end]
        before_score=float(b@b);after_score=float(np.sum((a@z-b)**2))
        assert abs(before_score-np.mean((before/scale)**2))<1e-5
        assert abs(after_score-np.mean((after/scale)**2))<1e-5
        blocks.append(dict(name=block['name'],before_score=before_score,after_score=after_score,
            before_rms=float(np.sqrt(np.mean(before**2))),after_rms=float(np.sqrt(np.mean(after**2))),scale=scale));start=end
    assert start==len(arrays['target'])
    prior=p['ridge_mean_weight']*np.mean(z*z)
    assert abs(prior-fit['prior_objective'])<1e-12
    assert abs(sum(b['after_score'] for b in blocks)-fit['data_objective_after'])<1e-10
    gradient=arrays['design'].T@(arrays['design']@z-arrays['target'])+p['ridge_mean_weight']/len(z)*z
    active=np.where(z<=-2+1e-8,-1,np.where(z>=2-1e-8,1,0))
    assert np.array_equal(active,fit['active_mask'])
    kkt=np.where(active==-1,np.minimum(gradient,0),np.where(active==1,np.maximum(gradient,0),gradient))
    assert np.max(abs(kkt))<1e-9
    bounds=[dict(roles=g['ordered_roles'],category=g['category'],scaled_value=float(v),
                 shift_degrees=float(np.degrees(v*g['scale']))) for g,v,a in zip(p['groups'],z,active,strict=True) if a]
    history=dict(np.load(root/'evaluations.npz'));accepted=np.load(root/'accepted_angstrom.npy');final=np.load(root/'final_angstrom.npy')
    assert np.array_equal(final,accepted[-1]) and np.array_equal(final,np.load(root/'last_accepted_angstrom.npy'))
    history_ids={frame.tobytes() for frame in history['coordinates_angstrom']}
    assert all(frame.tobytes() in history_ids for frame in accepted)
    for x,e,g in zip(history['coordinates_angstrom'],history['energies_kcal_mol'],history['gradients_kcal_A'],strict=True):
        re,rg,_=engines['core'].evaluate(x);max_replay=max(max_replay,abs(re-e),float(np.max(abs(rg-g))))
    assert max_replay<1e-9
    core=read(root/'core_relaxation.json');e,g,_=engines['core'].evaluate(final)
    assert len(accepted)==core['accepted_states'] and len(history_ids)==len(history['coordinates_angstrom'])==core['evaluations']
    assert abs(e-core['energy_kcal_mol'])<1e-9 and np.max(abs(g-np.load(root/'final_gradient.npy')))<1e-9
    force=float(np.linalg.norm(g,axis=1).max());identity=m.geometry_audit(final/m.BOHR,read(checked(p['fixture']['model'])))
    assert force<.001 and identity['passed']
    h,asym=m.finite_hessian(lambda x:engines['core'].evaluate(x)[1].ravel(),final)
    hh,half_asym=m.finite_hessian(lambda x:engines['core'].evaluate(x)[1].ravel(),final,5e-5)
    assert np.max(abs(h-np.load(root/'final_hessian_kcal_A2.npy')))<1e-9
    qf=m.internal_basis(final);eig=np.linalg.eigvalsh(qf.T@h@qf);eig_half=np.linalg.eigvalsh(qf.T@hh@qf)
    stepnorm=float(np.linalg.norm(qf.T@(h-hh)@qf,2))
    assert len(eig)==102 and min(eig[0],eig_half[0])>100*stepnorm
    assert np.max(abs(eig-np.array(core['internal_hessian_eigenvalues_kcal_mol_A2'])))<1e-9
    geometry=m.geometry_differences(x0,final,p['fixture']);assert geometry==core['geometry']
    modes=[]
    for rank in (1,2):
        ids=[next(i for i,v in enumerate(p['points']) if v['label']==f'mode-{rank}-{s}') for s in ('minus','plus')]
        def even(es):return (es[ids[0]]+es[ids[1]]-2*es[0])/2
        qm_even=even(qme);modes.append(dict(rank=rank,qm_even_kcal_mol=qm_even,mm_even_kcal_mol=even(observed),
            relative_error=even(observed)/qm_even-1,interpretation='Acquired training displacement response at QM reference; not Hessian curvature at the relaxed MM geometry.'))
    transfer=[]
    for row in read(root/'vertical_endpoint_transfer.json')['records']:
        point=row['point'];x=np.load(checked(point['geometry']))*m.BOHR;qm=read(checked(point['qm_result']))
        e,g,_=engines['endpoint'].evaluate(x)
        assert abs(e-row['energy_kcal_mol'])<1e-9 and np.max(abs(g-np.load(checked(row['gradient']))))<1e-9
        transfer.append(dict(offset_degrees=point['offset_degrees'],energy_kcal_mol=e,qm_energy_hartree=qm['energy_hartree'],
            gradient_rmse_kcal_mol_A=float(np.sqrt(np.mean((g-np.array(qm['gradient_hartree_bohr'])*m.EH/m.BOHR)**2)))))
    zero=next(v for v in transfer if v['offset_degrees']==0)
    for row in transfer:
        row['relative_vertical_error_kcal_mol']=row['energy_kcal_mol']-zero['energy_kcal_mol']-(row['qm_energy_hartree']-zero['qm_energy_hartree'])*m.EH
    for engine in [baseline,*engines.values()]:engine.close()
    save(out,dict(at=now(),source=pin(Path(__file__)),plan=pin(root/'plan.json'),acknowledgement=pin(service/'completion_wake_ack.json'),
        status=pin(service/'status.json'),candidate=pin(root/'candidate_parameters.json'),passed=True,native_evidence_passed=True,
        objective_blocks=blocks,prior_objective=float(prior),bound_terms=bounds,kkt_max_violation=float(np.max(abs(kkt))),
        systems=systems,evaluated_states_verified=len(history_ids),accepted_states_verified=len(accepted),replay_max_error=max_replay,
        core_geometry=geometry,core_identity=identity,core_max_atom_gradient_kcal_mol_A=force,
        local_mm_minimum=dict(numerically_certified=True,scope='Exact candidate_core.xml at saved final geometry; finite-difference resolution tested at1e-4 and5e-5Angstrom. Local MM curvature only, not QM agreement, basin closure or transfer validation.',
            geometry=pin(root/'final_angstrom.npy'),gradient=pin(root/'final_gradient.npy'),hessian=pin(root/'final_hessian_kcal_A2.npy'),
            positive_internal_eigenvalues=len(eig),lowest_eigenvalue_kcal_mol_A2=float(eig[0]),half_step_lowest=float(eig_half[0]),
            step_difference_operator_norm=stepnorm,hessian_antisymmetry=asym,half_step_antisymmetry=half_asym),
        ring_training_response=modes,vertical_endpoint_transfer=transfer,fit_rounds_consumed=1,fit_rounds_max=2,
        candidate_qualified=False,full_candidate_hash_lock=False,minimum_certified=False,
        minimum_certified_scope_note='Top-level flag refers to full endpoint/campaign qualification; isolated MM local minimum evidence is explicitly scoped above.',
        decision='Preserve partial core correction, but do not fit again yet. Run two fixed-QM-core sugar diagnostics at offset0 and+30 under the same chi constraints. All32 base/methyl atoms fixed;17 sugar/cap atoms free. Changes to base-only equilibria cannot affect this free-atom objective except a constant, verified natively before launch. This tests whether the endpoint branch drift persists without core-shape error.',
        fixed_core_boundary_diagnostic_admitted=True,second_fit_admitted=False,new_qm_admitted=False,
        method_deviation='Completed historical core relaxations used L-BFGS-B despite the preferred Sella default. Evidence is preserved and independently audited; no repeat solely to change optimizer. New molecular relaxations use Sella order0/internal coordinates.',
        heldout_accessed=False,charge_transfer_validated=False,basin_closure_certified=False,simulation_ready=False,cloud_spending_usd=0))
    print(dict(blocks=blocks,bound_count=len(bounds),force=force,lowest_internal_mm_eigenvalue=float(eig[0]),step_operator_norm=stepnorm,
               ring_relative_errors=[v['relative_error'] for v in modes],vertical_errors=[v['relative_vertical_error_kcal_mol'] for v in transfer]))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
