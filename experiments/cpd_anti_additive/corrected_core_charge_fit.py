"""One preregistered, restrained charge fit on the corrected certified core."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback
import warnings
import numpy as np
from scipy.optimize import minimize
from scipy.linalg import null_space

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from experiments.cpd_anti_additive.corrected_core_water_curves import curve_diagnostics
from backend.parameterization.photoproduct_nonbonded_fit import _interaction_row

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'charge-core-fit-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')
FF=Path('/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-primary-syn-anti-fit-v1/local-run-v1/bundle/inputs/forcefield')
BOHR=0.52917721067
DEBYE=2.541746473/BOHR
COULOMB=332.063713299


def water_terms(xyz,lj,waters,water_lj):
    d=np.linalg.norm(waters[:,None,:,:]-xyz[None,:,None,:],axis=-1)
    if not np.isfinite(d).all() or np.any(d<=0):raise ValueError('Invalid model-water distances')
    rows=(COULOMB*np.array([-.834,.417,.417])/d).sum(axis=2)
    eps=np.sqrt(abs(lj[:,0,None]*water_lj[None,:,0]));rmin=lj[:,1,None]+water_lj[None,:,1]
    power=(rmin[None,:,:]/d)**6
    return rows,(eps[None,:,:]*(power**2-2*power)).sum(axis=(1,2))


def radial_minimum(r,e):
    i=int(np.argmin(e))
    if i==0 or i==len(r)-1:return float(r[i]),float(e[i]),False
    q=np.polyfit(r[i-1:i+2]-r[i],e[i-1:i+2],2)
    if q[0]<=0:return float(r[i]),float(e[i]),False
    x=-q[1]/(2*q[0]);bracketed=bool(r[i-1]<x+r[i]<r[i+1])
    return float(x+r[i]),float(np.polyval(q,x)),bracketed


def load_data(root):
    meta=read(root/'dataset.json')
    arrays=dict(np.load(checked(meta['arrays'])))
    return meta,arrays


def evaluate(delta,meta,a,regularize=True):
    q=a['q0']+a['mapping']@delta;water=[];energies=[];distances=[]
    for i,c in enumerate(meta['curves']):
        r,e,bracketed=radial_minimum(a['mm_distances'],a['rows'][i]@q+a['lj_energy'][i])
        de=e-c['target_energy_kcal_mol'];dr=r-c['target_distance_angstrom']
        energies.append(de/.2);distances.append(dr/.1)
        water.append(dict(site=c['site'],mm_energy_kcal_mol=e,mm_distance_angstrom=r,energy_error_kcal_mol=de,distance_error_angstrom=dr,bracketed=bracketed))
    dipole=q@a['xyz']*DEBYE;diff=dipole-a['dipole_target'];esp=a['esp_matrix']@q-a['esp_values']
    residual=np.r_[np.array(energies)/np.sqrt(6),np.array(distances)/np.sqrt(6),diff/.5/np.sqrt(3)]
    if regularize:residual=np.r_[residual,np.sqrt(.2)*np.asarray(delta)/.1/np.sqrt(10)]
    return residual,dict(charges_e=dict(zip(meta['atom_keys'],q.tolist())),net_charge_e=float(q.sum()),water=water,dipole_debye=dipole.tolist(),dipole_vector_error_debye=float(np.linalg.norm(diff)),esp_rmse_au=float(np.sqrt(np.mean(esp**2))),esp_relative_rmse=float(np.linalg.norm(esp)/np.linalg.norm(a['esp_values'])))


def identifiability(delta,meta,a):
    columns=[];step=1e-5
    for j in range(10):
        d=np.zeros(10);d[j]=step
        columns.append((evaluate(delta+d,meta,a,False)[0]-evaluate(delta-d,meta,a,False)[0])/(2*step))
    z=null_space(np.ones((1,10)));j=np.array(columns).T@z;s=np.linalg.svd(j,compute_uv=False)
    return dict(data_residuals=15,independent_charge_variables=9,weighted_data_jacobian_singular_values=s.tolist(),numerical_rank=int(np.linalg.matrix_rank(j)),rank_at_relative_1e_minus6=int(np.sum(s>s[0]*1e-6)),condition_number=float(s[0]/s[-1]),regularization_excluded_from_rank=True,finite_difference_step_e=step,interpretation='Equivalent base curves are near duplicates. Rank and conditioning describe local information only; restraint can choose a stable solution without unique physical charge determination.')


def native_energy_check(meta,a,charge_vectors):
    import openmm as mm
    from openmm import unit
    system=mm.System();force=mm.NonbondedForce();force.setNonbondedMethod(mm.NonbondedForce.NoCutoff);force.setUseDispersionCorrection(False)
    lj=np.vstack([a['model_lj'],a['water_lj']]);allq=np.r_[a['q0'],[-.834,.417,.417]]
    for q,(eps,rmin) in zip(allq,lj):
        system.addParticle(1);force.addParticle(float(q),float(2*rmin/2**(1/6)/10),float(abs(eps)*4.184))
    for i in range(39):
        for j in range(i):
            if (i<36)==(j<36):force.addException(i,j,0,1,0)
    system.addForce(force);integrator=mm.VerletIntegrator(.001);context=mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'));records=[]
    for label,q in charge_vectors:
        for i,value in enumerate(q):
            _,sigma,epsilon=force.getParticleParameters(i);force.setParticleParameters(i,float(value),sigma,epsilon)
        force.updateParametersInContext(context)
        for k,curve in enumerate(meta['curves']):
            index=int(np.argmin(abs(a['mm_distances']-curve['target_distance_angstrom'])))
            xyz=np.vstack([a['xyz'],a['waters'][k,index]])
            context.setPositions(xyz*.1*unit.nanometer)
            native=context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole)
            analytic=float(a['rows'][k,index]@q+a['lj_energy'][k,index]);error=abs(native-analytic)
            if not np.isfinite(error) or error>1e-5:raise ValueError(f'OpenMM interaction energy mismatch {label}/{curve["site"]}: {error}')
            records.append(dict(charge_case=label,site=curve['site'],native_kcal_mol=native,analytic_kcal_mol=analytic,absolute_error_kcal_mol=error))
    del context,integrator
    return dict(passed=True,platform='Reference',engine_version=mm.__version__,records=records,maximum_absolute_error_kcal_mol=max(v['absolute_error_kcal_mol'] for v in records),scope='Cross-fragment nonbonded interaction only; every intrafragment pair excluded. No bonded-system, MD or NAMD validation claim.')


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Frozen worker mismatch')
    for ref in p['sources']:checked(ref)
    if not read(checked(p['authorization']))['user_authorized']:raise ValueError('Missing authority')
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    if p['round']!=1 or p['maximum_rounds']!=2 or p['cloud_spending_usd']!=0:raise ValueError('Allocation changed')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan'])!=root/'plan.json':raise ValueError('Launched plan changed')
    return p


def prepare():
    from rdkit import Chem
    from openmm import app
    require_archive(CAMPAIGN);water=CAMPAIGN/'water-core-curves-v1';wp=read(water/'plan.json');wa=read(water/'completion_audit.json')
    if not wa['passed'] or not wa['charge_dataset_preparation_admitted']:raise ValueError('Water audit missing')
    for ref in wp['sources']:checked(ref)
    review=read(checked(wa['independent_review']));base=read(checked(wp['core_plan']));keys=base['atom_keys'];cert=read(checked(wp['core_certification']))
    m=Chem.MolFromMolFile(str(checked(base['sdf'])),removeHs=False);Chem.AssignStereochemistry(m,cleanIt=True,force=True)
    permutation=tuple(keys.index(('2' if k.startswith('1:') else '1')+k[1:]) for k in keys)
    matches=m.GetSubstructMatches(m,uniquify=False,useChirality=True,maxMatches=20000)
    if permutation not in matches:raise ValueError('Base exchange not a stereochemical automorphism')
    method=read(checked(wp['method_choice']));scope=read(checked(method['charge_scope']))
    names=sorted(k[2:] for k in method['variable_base_charge_keys'] if k.startswith('1:'))
    groups=[[f'1:{k}',f'2:{k}'] for k in names];assert len(groups)==10
    publication=REPO/'.development-artifacts/cpd-published-comparator-v1/source_transcription.json';published=read(publication);checked(published['source'])
    atoms=published['figure_s1_atoms'];caps={'CM':['CG331',-.27],**{h:['HGA3',.09] for h in ['HCM1','HCM2','HCM3']}}
    assignments=[caps[k[2:]] if k[2:] in caps else atoms[{'C7':'C5M'}.get(k[2:],k[2:])] for k in keys]
    q0=np.array([v[1] for v in assignments]);types=[v[0] for v in assignments];mapping=np.zeros((36,10))
    for j,g in enumerate(groups):
        for k in g:mapping[keys.index(k),j]=1
    assert abs(q0.sum())<1e-12 and all(abs(sum(q0[keys.index(f'{r}:{k}')] for k in caps))<1e-12 for r in [1,2])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore');params=app.CharmmParameterSet(str(FF/'top_all36_cgenff.rtf'),str(FF/'par_all36_cgenff.prm'))
    nb={k:dict(epsilon_kcal_mol=v.epsilon,rmin_half_angstrom=v.rmin) for k,v in params.atom_types_str.items()}
    wt=['OGTIP3','HGTIP3','HGTIP3'];assert all((t,w) not in params.nbfix_types and (w,t) not in params.nbfix_types for t in types for w in wt)
    lj=np.array([[nb[t]['epsilon_kcal_mol'],nb[t]['rmin_half_angstrom']] for t in types]);wlj=np.array([[nb[t]['epsilon_kcal_mol'],nb[t]['rmin_half_angstrom']] for t in wt])
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    save(ROOT/'policy.json',dict(at=now(),round=1,maximum_rounds=2,variable_atom_keys=method['variable_base_charge_keys'],charge_groups=groups,
        symmetry='Corresponding atoms on two identical bases share charge; exact chirality-aware graph automorphism verified; water curves differ by at most0.00023kcal/mol. Both ordered records retained without claiming independent replication.',
        baseline_assignments=[dict(atom=k,atom_type=t,charge_e=float(q)) for k,t,q in zip(keys,types,q0)],
        baseline_sources=[pin(publication),published['source'],pin(FF/'top_all36_cgenff.rtf'),pin(FF/'par_all36_cgenff.prm')],
        baseline_scope='Published cis-syn FigureS1 values used only as an initial charge/type hypothesis on the corrected core. No legacy anti fitted charges, topology or native geometry reused. Neutral N1-methyl caps use CG331 -0.27e plus three HGA3 +0.09e, an explicit local cap model.',
        constraints='Sum of ten independent charge shifts exactly zero; paired shifts equal. Both base totals remain zero, both methyl caps fixed neutral. Maximum absolute shift0.15e. AliphaticH6/H51/H52/H53, caps, LJ and all bonded/sugar/phosphate terms fixed.',
        objective='mean((water-min-energy-error/0.2kcal)^2)+mean((water-min-distance-error/0.1Angstrom)^2)+mean((HF-dipole-vector-error/0.5Debye)^2)+0.2*mean((independent-charge-shift/0.1e)^2). ESP diagnostic only.',
        weight_convention='0.2 is the squared-objective regularization coefficient, so residual multiplier is sqrt(0.2); explicit local choice, not a universal literature accuracy threshold.',
        water_energy_scale=1.16,water_distance_offset_angstrom=-.2,qm_dipole_scale=1.0,mm_grid_angstrom=[1.1,5.0,.02],
        solver='SLSQP, zero initial shifts, maxiter300, ftol1e-10; one fit, no strength sweep',
        water_development_limits=dict(maximum_energy_error_kcal_mol=.5,maximum_distance_error_angstrom=.2,all_mm_minima_bracketed=True),
        dipole_and_esp='Report vector and ESP errors; no hidden magnitude-ratio gate. Report data Jacobian singular spectrum without regularizer; numerical uniqueness is not physical identifiability.',
        all_data_exposed_development=True,heldout_accessed=False,minimum_certified=False,simulation_ready=False))
    xyz=np.load(checked(cert['geometry']))*BOHR;ds=np.arange(1.1,5.0+.01,.02);curves=[];rows=[];ljs=[];waters=[];sources=[pin(water/'completion_audit.json'),pin(water/'plan.json'),wa['independent_review'],wp['core_certification'],wp['core_plan'],base['sdf'],wp['method_choice'],wp['inventory'],method['charge_scope'],pin(publication),published['source'],pin(FF/'top_all36_cgenff.rtf'),pin(FF/'par_all36_cgenff.prm'),pin(REPO/'backend/parameterization/photoproduct_nonbonded_fit.py'),pin(REPO/'experiments/cpd_anti_additive/corrected_core_water_curves.py')]
    inventory=read(checked(wp['inventory']))
    for c in review['curves']:
        d=c['diagnostic'];assert d['bracketed'] and d['attractive'] and not d['needs_shape_review']
        target=d['quadratic_diagnostic'];assert target['inside_neighbor_interval']
        site=next(v for v in inventory['sites'] if v['id']==c['site']);point=next(v for v in site['selected']['points'] if v['distance_angstrom']==1.9)
        w=np.array([v[1:] for v in point['water_angstrom']]);ti=keys.index(site['target_atom']);wi=1 if site['role']=='acceptor' else 0;direction=(w[wi]-xyz[ti])/1.9
        ws=w[None,:,:]+(ds-1.9)[:,None,None]*direction;row,lennard=water_terms(xyz,lj,ws,wlj)
        for idx in [0,int(np.argmin(abs(ds-1.9))),len(ds)-1]:
            ir,il=_interaction_row(xyz,[nb[t] for t in types],ws[idx],nb)
            assert np.max(abs(row[idx]-ir))<1e-9 and abs(lennard[idx]-il)<1e-7
        rows.append(row);ljs.append(lennard);waters.append(ws)
        curves.append(dict(site=c['site'],target_atom=site['target_atom'],role=site['role'],qm_raw_minimum_distance_angstrom=target['raw_distance_angstrom'],qm_raw_minimum_energy_kcal_mol=target['raw_energy_kcal_mol'],target_distance_angstrom=target['raw_distance_angstrom']-.2,target_energy_kcal_mol=target['raw_energy_kcal_mol']*1.16))
        sources.extend(point['result'] for point in c['points'])
    cr=read(water/'core-df/result.json');grid=np.loadtxt(checked(cr['grid']));esp=np.loadtxt(checked(cr['potentials']));sources.extend([pin(water/'core-df/result.json'),cr['grid'],cr['potentials']])
    np.savez_compressed(ROOT/'arrays.npz',xyz=xyz,q0=q0,mapping=mapping,rows=np.array(rows),lj_energy=np.array(ljs),waters=np.array(waters),model_lj=lj,water_lj=wlj,mm_distances=ds,dipole_target=np.array(cr['dipole_au'])*2.541746473,esp_matrix=BOHR/np.linalg.norm(grid[:,None,:]-xyz[None,:,:],axis=-1),esp_values=esp)
    sources.append(cert['geometry'])
    save(ROOT/'dataset.json',dict(at=now(),arrays=pin(ROOT/'arrays.npz'),atom_keys=keys,atom_types=types,variable_groups=groups,curves=curves,source_geometry=cert['geometry'],chirality_aware_base_exchange_permutation=list(permutation),matched_automorphisms=len(matches),sources=sources,independent_validation=False))
    meta,a=load_data(ROOT);probe=np.zeros(10);probe[0]=.03;probe[1]=-.03
    save(ROOT/'baseline_openmm_check.json',native_energy_check(meta,a,[('baseline',q0),('neutral_test_perturbation',q0+mapping@probe)]))
    save(ROOT/'baseline_diagnostics.json',dict(at=now(),metrics=evaluate(np.zeros(10),meta,a)[1],identifiability=identifiability(np.zeros(10),meta,a),optimizer_started=False))
    save(ROOT/'plan.json',dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=[*sources,pin(ROOT/'policy.json'),pin(ROOT/'dataset.json'),pin(ROOT/'arrays.npz'),pin(ROOT/'baseline_openmm_check.json'),pin(ROOT/'baseline_diagnostics.json')],authorization=wp['authorization'],round=1,maximum_rounds=2,hard_seconds=900,expected_seconds=60,cloud_spending_usd=0))
    save(ROOT/'preflight.json',dict(at=now(),passed=True,policy_frozen_before_objective_evaluation=True,graph_symmetry_verified=True,neutral_caps_and_base_charge_verified=True,openmm_cross_energy_passed=True,no_pair_specific_nbfix=True,independent_scalar_formula_verified=True,heldout_accessed=False,new_qm=0))
    print(ROOT)


def run(root):
    p=context(root);meta,a=load_data(root)
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    start=time.monotonic();history=[]
    def objective(delta):
        if time.monotonic()-start>600:raise TimeoutError('Charge-fit optimizer time bound')
        r,_=evaluate(delta,meta,a);return float(r@r)
    def callback(delta):
        history.append(objective(delta));save(root/'progress.json',dict(at=now(),iterations=len(history),objective=history[-1]))
    try:
        fit=minimize(objective,np.zeros(10),method='SLSQP',bounds=[(-.15,.15)]*10,constraints=[dict(type='eq',fun=lambda x:float(x.sum()),jac=lambda x:np.ones(10))],callback=callback,options=dict(maxiter=300,ftol=1e-10))
        residual,metrics=evaluate(fit.x,meta,a);q=a['q0']+a['mapping']@fit.x
        constraints=bool(abs(fit.x.sum())<1e-8 and np.max(abs(fit.x))<=.15000001 and abs(q.sum())<1e-8)
        water_pass=all(v['bracketed'] and abs(v['energy_error_kcal_mol'])<=.5 and abs(v['distance_error_angstrom'])<=.2 for v in metrics['water'])
        native=native_energy_check(meta,a,[('fitted',q)]);save(root/'fitted_openmm_check.json',native)
        save(root/'candidate_charges.json',dict(at=now(),policy=pin(root/'policy.json'),dataset=pin(root/'dataset.json'),charges_e=metrics['charges_e'],variable_group_shifts_e=dict(zip([g[0][2:] for g in meta['variable_groups']],fit.x.tolist())),development_only=True,parameter_set_complete=False,simulation_ready=False))
        save(root/'assessment.json',dict(at=now(),plan=pin(root/'plan.json'),policy=pin(root/'policy.json'),candidate=pin(root/'candidate_charges.json'),optimizer_success=bool(fit.success),optimizer_message=str(fit.message),iterations=int(fit.nit),function_evaluations=int(fit.nfev),objective=float(residual@residual),history=history,constraints_passed=constraints,water_development_limits_passed=bool(water_pass),metrics=metrics,identifiability=identifiability(fit.x,meta,a),wall_seconds=time.monotonic()-start,requires_completion_audit=True,minimum_certified=False,charge_transfer_validated=False,fit_target_accepted=False,simulation_ready=False))
        return 0 if fit.success and constraints else 1
    except Exception as e:
        (root/'failure_traceback.txt').write_text(traceback.format_exc());save(root/'assessment.json',dict(at=now(),error=repr(e),wall_seconds=time.monotonic()-start,requires_completion_audit=True,minimum_certified=False,simulation_ready=False));return 1


def launch(root):
    p=context(root)
    if not read(root/'preflight.json')['passed']:raise ValueError('Preflight absent')
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Another CPD calculation active')
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    if available<6*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-charge-core-fit-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=60,review_deadline_epoch=start+720,review_deadline_id='charge-fit-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.25,memory_gib=4,omp_threads=1,plan=pin(root/'plan.json'),completion_semantics='One restrained charge fit; separate optimizer, native-energy, water-quality, identifiability and transfer verdicts.'))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+900,unit=unit,available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=4G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=100%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=1',f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run','launch']);parser.add_argument('root',nargs='?',type=Path,default=ROOT);args=parser.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='run':sys.exit(run(args.root.resolve()))
    else:launch(args.root.resolve())
