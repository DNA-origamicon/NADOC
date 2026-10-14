"""One bounded core equilibrium correction; endpoint transfer remains diagnostic."""
from pathlib import Path
from collections import defaultdict
import argparse
import importlib.metadata as metadata
import os
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,geometry_audit
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from experiments.cpd_anti_additive.corrected_bonded_baseline import Evaluator,BOHR,EH,geometry_differences

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'core-bonded-fit-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def role_group(atoms):
    atoms=tuple(atoms)
    exchanged=tuple(('2:' if a.startswith('1:') else '1:')+a.split(':',1)[1] for a in atoms)
    return min(atoms,atoms[::-1],exchanged,exchanged[::-1])


def coordinate_gradient(x,indices):
    """Distance in Angstrom or angle in radians and its Cartesian derivative."""
    x=np.asarray(x,float);indices=list(indices);g=np.zeros_like(x)
    if len(indices)==2:
        a,b=indices;u=x[a]-x[b];r=np.linalg.norm(u)
        if r<1e-8:raise ValueError('Degenerate distance')
        g[a]=u/r;g[b]=-g[a]
        return float(r),g
    if len(indices)!=3:raise ValueError('Expected bond or angle')
    a,b,c=indices;u=x[a]-x[b];v=x[c]-x[b];ru=np.linalg.norm(u);rv=np.linalg.norm(v)
    if min(ru,rv)<1e-8:raise ValueError('Degenerate angle bond')
    uh=u/ru;vh=v/rv;co=np.clip(uh@vh,-1.,1.);si=np.sqrt(1-co*co)
    if si<1e-7:raise ValueError('Collinear angle')
    g[a]=(co*uh-vh)/(ru*si);g[c]=(co*vh-uh)/(rv*si);g[b]=-g[a]-g[c]
    return float(np.arccos(co)),g


def basis(x,groups):
    values=[];gradients=[]
    for group in groups:
        e=0.;g=np.zeros_like(x)
        for term in group['terms']:
            value,derivative=coordinate_gradient(x,term['indices'])
            weight=-term['k']*group['scale']
            e+=weight*value;g+=weight*derivative
        values.append(e);gradients.append(g.ravel())
    return np.asarray(values),np.stack(gradients,axis=1)


def internal_basis(x):
    centered=np.asarray(x)-np.mean(x,axis=0);columns=[]
    for axis in np.eye(3):
        columns.append(np.tile(axis,(len(x),1)).ravel())
        columns.append(np.cross(np.tile(axis,(len(x),1)),centered).ravel())
    u,s,_=np.linalg.svd(np.stack(columns,axis=1),full_matrices=True)
    if sum(s>s[0]*1e-10)!=6:raise ValueError('Rigid-body rank is not six')
    return u[:,6:]


def finite_hessian(gradient,x,step=1e-4):
    columns=[]
    for j in range(x.size):
        delta=np.zeros_like(x);delta.ravel()[j]=step
        columns.append((gradient(x+delta)-gradient(x-delta))/(2*step))
    raw=np.stack(columns,axis=1)
    return (raw+np.swapaxes(raw,0,1))/2,float(np.max(abs(raw-np.swapaxes(raw,0,1))))


def groups_for(system,fixture):
    from openmm import unit as u
    grouped=defaultdict(list);keys=fixture['atom_keys'];elements=fixture['elements']
    for force_index,category in [(0,'bond'),(1,'angle')]:
        force=system.getForce(force_index)
        count=force.getNumBonds() if category=='bond' else force.getNumAngles()
        for index in range(count):
            parameters=force.getBondParameters(index) if category=='bond' else force.getAngleParameters(index)
            ids=[int(i) for i in parameters[:-2]]
            if any(elements[i]=='H' or keys[i].split(':')[1]=='CM' or "'" in keys[i] for i in ids):continue
            eq,k=parameters[-2:]
            equilibrium=eq.value_in_unit(u.angstrom if category=='bond' else u.radian)
            coefficient=k.value_in_unit(u.kilocalorie_per_mole/(u.angstrom**2 if category=='bond' else u.radian**2))
            grouped[(category,role_group([keys[i] for i in ids]))].append(dict(force_index=force_index,index=index,
                indices=ids,atoms=[keys[i] for i in ids],equilibrium=float(equilibrium),k=float(coefficient)))
    groups=[]
    for (category,atoms),terms in sorted(grouped.items()):
        assert len(terms)==2 and np.ptp([t['k'] for t in terms])<1e-8 and np.ptp([t['equilibrium'] for t in terms])<1e-8
        groups.append(dict(category=category,ordered_roles=list(atoms),terms=terms,
            scale=.02 if category=='bond' else float(np.radians(4)),lower=-2.,upper=2.,
            units='angstrom' if category=='bond' else 'radian'))
    return groups


def changed_system(system,groups,z):
    import openmm as mm
    from openmm import unit as u
    result=mm.XmlSerializer.deserialize(mm.XmlSerializer.serialize(system))
    for group,value in zip(groups,z,strict=True):
        for term in group['terms']:
            force=result.getForce(term['force_index']);idx=term['index']
            if group['category']=='bond':
                a,b,eq,k=force.getBondParameters(idx)
                force.setBondParameters(idx,a,b,eq+value*group['scale']*u.angstrom,k)
            else:
                a,b,c,eq,k=force.getAngleParameters(idx)
                force.setAngleParameters(idx,a,b,c,eq+value*group['scale']*u.radian,k)
    return result


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Use frozen worker')
    for source in p['sources']:checked(source)
    auth=read(checked(p['authorization']))
    assert auth['user_authorized'] and auth['compute_policy']['cloud_spending_usd']==0
    assert p['hard_seconds']==900 and p['fit_round']==1 and len(p['points'])==5
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    for name,version in p['versions'].items():
        if metadata.version(name)!=version:raise ValueError(f'Runtime changed: {name}')
    if (root/'launch_receipt.json').exists():
        assert checked(read(checked(read(root/'launch_receipt.json')['execution_plan']))['plan'])==root/'plan.json'
    return p


def prepare():
    import openmm as mm
    require_archive(CAMPAIGN)
    auditpath=CAMPAIGN/'mm-endpoint-profile-v2/completion_audit.json';audit=read(auditpath)
    assert audit['native_evidence_passed'] and audit['core_bonded_fit_design_admitted'] and not audit['matched_profile_accepted']
    baselinepath=CAMPAIGN/'bonded-baseline-v1/plan.json';bp=read(baselinepath);fixture=bp['fixtures']['core']
    certpath=CAMPAIGN/'core_local_minimum_assessment.json';cert=read(certpath);assert cert['minimum_certified']
    ha=read(checked(cert['hessian_audit']));hessian=ha['hessian'];checked(hessian)
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    engine=Evaluator(checked(fixture['systems']['last']));groups=groups_for(engine.system,fixture)
    endpoint=Evaluator(checked(bp['fixtures']['endpoint']['systems']['last']))
    endpoint_groups=groups_for(endpoint.system,bp['fixtures']['endpoint'])
    assert [g['ordered_roles'] for g in groups]==[g['ordered_roles'] for g in endpoint_groups]
    for a,b in zip(groups,endpoint_groups,strict=True):
        assert a['category']==b['category'] and a['scale']==b['scale']
        assert all(abs(x['equilibrium']-y['equilibrium'])<1e-10 and abs(x['k']-y['k'])<1e-8
                   for x,y in zip(a['terms'],b['terms'],strict=True))
    endpoint.close()
    points=[v for v in bp['points'] if v['fixture']=='core'];x=np.load(checked(points[0]['geometry']))*BOHR
    energies=[];gradients=[];qmg=[];qmenergies=[];be=[];bg=[]
    for point in points:
        xyz=np.load(checked(point['geometry']))*BOHR;record=read(checked(point['qm_result']))
        e,g,_=engine.evaluate(xyz);a,b=basis(xyz,groups)
        energies.append(e);gradients.append(g.ravel());be.append(a);bg.append(b)
        qmg.append(np.asarray(record['gradient_hartree_bohr']).ravel()*EH/BOHR);qmenergies.append(record['energy_hartree']*EH)
    gradients=np.array(gradients);qmg=np.array(qmg);bg=np.array(bg)
    h,asym=finite_hessian(lambda q:engine.evaluate(q)[1].ravel(),x)
    hhalf,_=finite_hessian(lambda q:engine.evaluate(q)[1].ravel(),x,5e-5)
    bh,b_asym=finite_hessian(lambda q:basis(q,groups)[1],x)
    bhhalf,_=finite_hessian(lambda q:basis(q,groups)[1],x,5e-5)
    assert np.max(abs(h-hhalf))<1e-3 and np.max(abs(bh-bhhalf))<1e-4
    q=internal_basis(x);hq=np.load(checked(hessian))*EH/BOHR**2
    hp=np.einsum('ia,ijp,jb->abp',q,bh,q);residual_h=q.T@(h-hq)@q
    # Fixed equal-block RMS objective: core gradient /1 kcal/mol/A;
    # full internal Hessian /10 kcal/mol/A^2; four ring gradient differences /1.
    # These are declared development scales, not literature acceptance thresholds.
    blocks=[('core_gradient',bg[0]/np.sqrt(x.size),(qmg[0]-gradients[0])/np.sqrt(x.size)),
            ('internal_hessian',hp.reshape(-1,len(groups))/(10*np.sqrt(hp.shape[0]*hp.shape[1])),
             -residual_h.ravel()/(10*np.sqrt(residual_h.size))),
            ('ring_gradient_difference',(bg[1:]-bg[0]).reshape(-1,len(groups))/np.sqrt(4*x.size),
             ((qmg[1:]-qmg[0])-(gradients[1:]-gradients[0])).ravel()/np.sqrt(4*x.size))]
    design=np.vstack([a for _,a,_ in blocks]);target=np.concatenate([b for _,_,b in blocks]);singular=np.linalg.svd(design,compute_uv=False)
    rank=int(sum(singular>singular[0]*1e-8))
    np.savez_compressed(ROOT/'response_arrays.npz',design=design,target=target,core_geometry=x,
        baseline_energies=np.array(energies),baseline_gradients=gradients,qm_energies=np.array(qmenergies),qm_gradients=qmg,
        basis_energies=np.array(be),basis_gradients=bg,baseline_hessian=h,basis_hessian=bh,qm_hessian=hq,internal_basis=q)
    # Native combination check at all five points includes the exact quadratic
    # equilibrium constant omitted from the derivative-linear representation.
    z=.17*np.sin(np.arange(len(groups))+1)
    (ROOT/'preflight_combination.xml').write_text(mm.XmlSerializer.serialize(changed_system(engine.system,groups,z)))
    probe=Evaluator(ROOT/'preflight_combination.xml');gerror=0.;eerror=0.
    constant=sum(.5*t['k']*((t['equilibrium']+v*gr['scale'])**2-t['equilibrium']**2)
                 for gr,v in zip(groups,z,strict=True) for t in gr['terms'])
    for i,point in enumerate(points):
        xyz=np.load(checked(point['geometry']))*BOHR;en,gn,_=probe.evaluate(xyz)
        gerror=max(gerror,float(np.max(abs(gn.ravel()-(gradients[i]+bg[i]@z)))))
        eerror=max(eerror,abs(en-(energies[i]+be[i]@z+constant)))
    probe.close();engine.close();assert gerror<1e-9 and eerror<1e-9
    # Explicit ordered aliases are reserved for later CHARMM export. Fitting is
    # atom-role-specific in the native systems, never a mutation of shared parent types.
    aliases={key:'CA'+key.split(':')[0]+key.split(':')[1] for key,element in zip(fixture['atom_keys'],fixture['elements'],strict=True)
             if element!='H' and key.split(':')[1]!='CM'}
    sources=[pin(auditpath),pin(baselinepath),pin(certpath),cert['hessian_audit'],hessian,fixture['systems']['last'],fixture['model'],
             bp['fixtures']['endpoint']['systems']['last'],pin(CAMPAIGN/'endpoint_reference_design_v1.json')]
    for point in bp['points']:sources.extend([point['geometry'],point['qm_result']])
    for name in ['corrected_core_stage1.py','corrected_coupled_ring.py','corrected_bonded_baseline.py']:
        sources.append(pin(REPO/'experiments/cpd_anti_additive'/name))
    plan=dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,authorization=bp['authorization'],
        fixture=fixture,endpoint_fixture=bp['fixtures']['endpoint'],groups=groups,endpoint_groups=endpoint_groups,
        proposed_ordered_aliases=aliases,points=points,endpoint_points=[v for v in bp['points'] if v['fixture']=='endpoint'],
        response_arrays=pin(ROOT/'response_arrays.npz'),blocks=[dict(name=n,rows=len(b)) for n,a,b in blocks],
        objective='Sum of block mean-square residuals: core gradient/1 kcal/mol/A, internal Hessian/10 kcal/mol/A^2, four ring gradient differences/1 kcal/mol/A; plus0.1*mean(z^2). Scales are frozen modeling choices, not measured noise or acceptance standards.',
        variable_policy='Only base heavy-atom bond/angle equilibria; exact base-exchange ties and reversal. Bond scale0.02A and angle scale4deg, bounds +/-2 scaled units (0.04A/8deg). Fixed force constants, Urey-Bradley, Fourier terms, impropers, charges, LJ and every cap/sugar term.',
        rationale='Existing core shows0.03A/5.5deg geometry errors, while unchanged-parent endpoint relaxations change sugar branches. Correct core stationary-force bias conservatively before interpreting endpoint energy residuals. No glycosidic fit to mixed conformers.',
        ridge_mean_weight=.1,fit_round=1,fit_rounds_max=2,full_candidate_hash_lock=False,
        hard_seconds=900,expected_seconds=120,threads=1,service_memory_gib=4,
        limits=dict(lsq_max_iterations=500,relax_max_evaluations=1500,relax_max_iterations=1000,relax_seconds=300),
        validation='One core relaxation from the certified QM geometry; independently report actual stationarity/identity/geometry, finite-step Hessian diagnostic, ring response and vertical endpoint transfer. No endpoint optimization, new QM, prospective heldout acquisition or automatic promotion.',
        versions={n:metadata.version(n) for n in ['openmm','numpy','scipy','rdkit']},
        minimum_certified=False,charge_transfer_validated=False,simulation_ready=False,cloud_spending_usd=0)
    save(ROOT/'plan.json',plan)
    save(ROOT/'preflight.json',dict(at=now(),passed=rank==len(groups),plan=pin(ROOT/'plan.json'),
        parameter_count=len(groups),data_rank_relative_1e8=rank,scaled_singular_values=singular.tolist(),
        data_condition_number=float(singular[0]/singular[-1]),native_combination_energy_max_error=eerror,native_combination_gradient_max_error=gerror,
        hessian_step_difference=float(np.max(abs(h-hhalf))),basis_hessian_step_difference=float(np.max(abs(bh-bhhalf))),
        baseline_hessian_antisymmetry=asym,basis_hessian_antisymmetry=b_asym,
        untouched_standard_boundary_terms=True,endpoint_exact_role_transfer_verified=True,
        new_qm=0,fit_performed=False,heldout_accessed=False))
    print(dict(root=str(ROOT),parameters=len(groups),rank=rank,condition=float(singular[0]/singular[-1]),gradient_error=gerror))


def run(root):
    import openmm as mm
    from scipy.optimize import lsq_linear,minimize
    p=context(root);assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    start=time.monotonic();error=None;history=[];accepted=[]
    try:
        arrays=dict(np.load(checked(p['response_arrays'])));a=arrays['design'];b=arrays['target'];groups=p['groups'];n=len(groups)
        fit=lsq_linear(np.vstack([a,np.sqrt(p['ridge_mean_weight']/n)*np.eye(n)]),np.r_[b,np.zeros(n)],
                       bounds=(-2,2),tol=1e-12,max_iter=p['limits']['lsq_max_iterations'])
        z=fit.x;np.save(root/'scaled_parameters.npy',z)
        save(root/'fit_result.json',dict(at=now(),success=bool(fit.success),message=fit.message,status=int(fit.status),
            iterations=int(fit.nit),optimality=float(fit.optimality),active_mask=fit.active_mask.tolist(),
            scaled_parameters=z.tolist(),data_objective_before=float(b@b),data_objective_after=float(np.sum((a@z-b)**2)),
            prior_objective=float(p['ridge_mean_weight']*np.mean(z*z)),fit_round_consumed=True))
        if not fit.success:raise RuntimeError('Bounded linear fit did not converge')
        parent=mm.XmlSerializer.deserialize(checked(p['fixture']['systems']['last']).read_text())
        candidate=changed_system(parent,groups,z)
        (root/'candidate_core.xml').write_text(mm.XmlSerializer.serialize(candidate))
        ep=mm.XmlSerializer.deserialize(checked(p['endpoint_fixture']['systems']['last']).read_text())
        (root/'candidate_endpoint.xml').write_text(mm.XmlSerializer.serialize(changed_system(ep,p['endpoint_groups'],z)))
        save(root/'candidate_parameters.json',dict(at=now(),plan=pin(root/'plan.json'),fit=pin(root/'fit_result.json'),
            groups=[dict(**g,scaled_value=float(v),equilibrium_shift=float(v*g['scale'])) for g,v in zip(groups,z,strict=True)],
            core=pin(root/'candidate_core.xml'),endpoint=pin(root/'candidate_endpoint.xml'),
            full_candidate_hash_lock=False,full_precision_psf_export_pending=True,simulation_ready=False))
        engine=Evaluator(root/'candidate_core.xml');x0=arrays['core_geometry'];static=[]
        for point in p['points']:
            x=np.load(checked(point['geometry']))*BOHR;e,g,parts=engine.evaluate(x,True)
            file=root/(point['label']+'_gradient.npy');np.save(file,g)
            static.append(dict(point=point,energy_kcal_mol=e,gradient=pin(file),force_groups=parts))
        save(root/'static_core.json',dict(at=now(),records=static))
        relax_start=time.monotonic();last=x0.copy()
        def evaluate(flat):
            if len(history)>=p['limits']['relax_max_evaluations'] or time.monotonic()-relax_start>p['limits']['relax_seconds']:
                raise RuntimeError('Bounded core relaxation allocation exhausted')
            x=flat.reshape(x0.shape);e,g,_=engine.evaluate(x);history.append((x.copy(),e,g.copy()))
            return e,g.ravel()
        def callback(flat):
            nonlocal last
            last=flat.reshape(x0.shape).copy();accepted.append(last.copy());np.save(root/'last_accepted_angstrom.npy',last)
        try:
            opt=minimize(evaluate,x0.ravel(),jac=True,method='L-BFGS-B',callback=callback,
                         options=dict(maxiter=p['limits']['relax_max_iterations'],maxfun=p['limits']['relax_max_evaluations'],ftol=1e-15,gtol=1e-7,maxls=40))
        finally:
            np.savez_compressed(root/'evaluations.npz',coordinates_angstrom=np.array([v[0] for v in history]),
                energies_kcal_mol=np.array([v[1] for v in history]),gradients_kcal_A=np.array([v[2] for v in history]))
            np.save(root/'accepted_angstrom.npy',np.array(accepted))
        e,g,parts=engine.evaluate(last,True);np.save(root/'final_angstrom.npy',last);np.save(root/'final_gradient.npy',g)
        h,asym=finite_hessian(lambda q:engine.evaluate(q)[1].ravel(),last)
        hh,_=finite_hessian(lambda q:engine.evaluate(q)[1].ravel(),last,5e-5)
        np.save(root/'final_hessian_kcal_A2.npy',h);q=internal_basis(last);eig=np.linalg.eigvalsh(q.T@h@q)
        identity=geometry_audit(last/BOHR,read(checked(p['fixture']['model'])))
        save(root/'core_relaxation.json',dict(at=now(),optimizer_success=bool(opt.success),optimizer_message=str(opt.message),
            evaluations=len(history),accepted_states=len(accepted),energy_kcal_mol=e,force_groups=parts,
            maximum_atom_gradient_kcal_mol_angstrom=float(np.linalg.norm(g,axis=1).max()),identity=identity,
            geometry=geometry_differences(x0,last,p['fixture']),
            internal_hessian_eigenvalues_kcal_mol_A2=eig.tolist(),hessian_step_max_difference=float(np.max(abs(h-hh))),hessian_antisymmetry=asym,
            minimum_certified=False,requires_independent_audit=True))
        engine.close();epengine=Evaluator(root/'candidate_endpoint.xml');transfer=[]
        for point in p['endpoint_points']:
            x=np.load(checked(point['geometry']))*BOHR;e,g,parts=epengine.evaluate(x,True)
            file=root/(point['label']+'_gradient.npy');np.save(file,g)
            transfer.append(dict(point=point,energy_kcal_mol=e,gradient=pin(file),force_groups=parts))
        epengine.close();save(root/'vertical_endpoint_transfer.json',dict(at=now(),records=transfer,matched_relaxed_profile=False))
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),error=error,wall_seconds=time.monotonic()-start,requires_completion_audit=True,
        fit_round=1,minimum_certified=False,full_candidate_hash_lock=False,simulation_ready=False,heldout_accessed=False))
    return 1 if error else 0


def launch(root):
    p=context(root);assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Another CPD calculation active')
    available=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024
    if available<6*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-core-bonded-fit-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=p['expected_seconds'],review_deadline_epoch=start+720,review_deadline_id='core-bonded-fit-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.25,memory_gib=4,omp_threads=1,plan=pin(root/'plan.json'),completion_semantics='One bounded core bonded fit and native diagnostics; completion is not acceptance or minimum certification.'))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+900,unit=unit,available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=4G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=100%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=1',f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run','launch'])
    parser.add_argument('root',nargs='?',type=Path,default=ROOT);args=parser.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='run':sys.exit(run(args.root.resolve()))
    else:launch(args.root.resolve())
