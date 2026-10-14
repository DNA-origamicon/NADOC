"""Fresh corrected-graph MM baseline; no legacy anti model, fitting or new QM."""
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
import warnings
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,geometry_audit
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_published_comparator.reconstruct import key as publication_key

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'bonded-baseline-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')
PUBLICATION=(REPO/'.development-artifacts/cpd-published-comparator-v1').resolve()
FF=Path('/media/jojo/Archive/NADOC_archive/photoproduct_evidence/alpine-qm-primary-syn-anti-fit-v1/local-run-v1/bundle/inputs/forcefield')
BOHR=.52917721067
EH=627.5094740631


def proper_rmsd(reference,coordinates,elements):
    ids=np.array([i for i,e in enumerate(elements) if e!='H'])
    a=np.asarray(reference)[ids];b=np.asarray(coordinates)[ids]
    a=a-a.mean(axis=0);b=b-b.mean(axis=0)
    left,_,right=np.linalg.svd(b.T@a)
    rotation=left@np.diag([1.,1.,np.linalg.det(left@right)])@right
    return float(np.sqrt(np.mean(np.sum((b@rotation-a)**2,axis=1))))


def angle_degrees(x,ids):
    a,b,c=np.asarray(x)[list(ids)];u=a-b;v=c-b
    denominator=np.linalg.norm(u)*np.linalg.norm(v)
    if denominator<=0:raise ValueError('Degenerate bond angle')
    return float(np.degrees(np.arccos(np.clip(u@v/denominator,-1,1))))


def geometry_differences(reference,x,fixture):
    keys=fixture['atom_keys'];bonds=[];angles=[]
    for a,b in fixture['bonds']:
        bonds.append(dict(atoms=[keys[a],keys[b]],error_angstrom=float(np.linalg.norm(x[a]-x[b])-np.linalg.norm(reference[a]-reference[b]))))
    for ids in fixture['angles']:
        angles.append(dict(atoms=[keys[i] for i in ids],error_degrees=angle_degrees(x,ids)-angle_degrees(reference,ids)))
    return dict(bonds=bonds,angles=angles,max_bond_error_angstrom=max(abs(v['error_angstrom']) for v in bonds),
                max_angle_error_degrees=max(abs(v['error_degrees']) for v in angles),
                heavy_atom_proper_alignment_rmsd_angstrom=proper_rmsd(reference,x,fixture['elements']))


class Evaluator:
    def __init__(self,system_path):
        import openmm as mm
        from openmm import unit
        self.unit=unit;self.system=mm.XmlSerializer.deserialize(Path(system_path).read_text())
        self.integrator=mm.VerletIntegrator(.001)
        self.context=mm.Context(self.system,self.integrator,mm.Platform.getPlatformByName('Reference'))

    def evaluate(self,x,components=False):
        u=self.unit;self.context.setPositions(np.asarray(x)*u.angstrom)
        state=self.context.getState(getEnergy=True,getForces=True)
        energy=float(state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole))
        gradient=-np.asarray(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
        if not np.isfinite(energy) or not np.isfinite(gradient).all():raise ValueError('Nonfinite MM result')
        parts={}
        if components:
            for index,force in enumerate(self.system.getForces()):
                st=self.context.getState(getEnergy=True,groups=1<<index)
                parts[f'{index}:{force.__class__.__name__}']=float(st.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole))
            if abs(sum(parts.values())-energy)>1e-7:raise ValueError('Force-group energy mismatch')
        return energy,gradient,parts

    def close(self):
        del self.context,self.integrator


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Frozen worker changed')
    for v in p['sources']:checked(v)
    auth=read(checked(p['authorization']))
    if not auth['user_authorized'] or auth['compute_policy']['cloud_spending_usd']!=0:raise ValueError('Missing local authority')
    if (p['hard_seconds'],p['variant_timeout_seconds'],p['variants'])!=(900,360,['first','last']):raise ValueError('Allocation changed')
    for name,version in p['versions'].items():
        if metadata.version(name)!=version:raise ValueError(f'Runtime changed: {name}')
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan'])!=root/'plan.json':raise ValueError('Launched plan changed')
    return p


def prepare():
    import openmm as mm
    from openmm import app
    from rdkit import Chem
    require_archive(CAMPAIGN)
    transfer=CAMPAIGN/'electrostatic-endpoint-transfer-v1/completion_audit.json'
    assert read(transfer)['passed'] and read(transfer)['bonded_baseline_admitted']
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    save(ROOT/'design.json',dict(at=now(),scope='Two published duplicate-row hypotheses on fresh corrected core/endpoint topology; unchanged candidate charges, LJ and sugar terms. Static MM energy/force evaluation on ten acquired training geometries per hypothesis and one core relaxation per hypothesis.',
        rationale='Measure bonded-model deficiencies before selecting or fitting terms; retain published-source ambiguity as first/last hypotheses. Neither is a published corrected-anti force field.',
        topology='Exact corrected SDF/graph bonds; four carbonyl planar impropers only (C2 and C4 each base). No planar C5 improper on the saturated stereocenter.',
        static_profile='Same-coordinate vertical energy and force comparisons; not independently relaxed glycosidic profiles. No basin closure inference.',
        minimization='L-BFGS-B, max1000iterations/max1500evaluations/300seconds per core, ftol1e-15,gtol1e-7,maxls40. Preserve evaluated trials and accepted checkpoints. Independently report max atom gradient <=0.001kcal/mol/Angstrom and chemistry, distinct from optimizer status. No MM Hessian or minimum certification.',
        no_new_qm=True,no_fit=True,heldout_accessed=False,simulation_ready=False))
    certpath=CAMPAIGN/'core_local_minimum_assessment.json';cert=read(certpath);assert cert['minimum_certified']
    corepath=CAMPAIGN/'optimization/plan.json';core=read(corepath)
    endpointpath=CAMPAIGN/'endpoint-seeds-v2/endpoint-1/model_manifest.json';endpoint=read(endpointpath)
    chargepath=CAMPAIGN/'charge-core-fit-v1/candidate_charges.json';charge=read(chargepath)
    chargepolicy=read(checked(charge['policy']));base_assign={v['atom']:(v['atom_type'],charge['charges_e'][v['atom']]) for v in chargepolicy['baseline_assignments']}
    endpointchargespath=CAMPAIGN/'electrostatic-endpoint-transfer-v1/charge_assignment.json';endpointcharges=read(endpointchargespath)
    transcriptpath=PUBLICATION/'source_transcription.json';transcript=read(transcriptpath);checked(transcript['source'])
    # Recreate both source-transcription hypotheses locally, without borrowing a
    # legacy anti stream. Other parent Fourier multiplicities remain inherited.
    grouped=defaultdict(list)
    for row in transcript['rows']:
        if not row['commented']:grouped[publication_key(row)].append(row)
    for variant in ['first','last']:
        selected=[rows[0 if variant=='first' else -1] for rows in grouped.values()]
        lines=[f'* Published source duplicate-row hypothesis: {variant}','*','']
        for section in ['BONDS','ANGLES','DIHEDRALS','IMPROPERS']:
            lines.append(section)
            for row in selected:
                if row['section']!=section:continue
                values=row['values']
                if section=='IMPROPERS':values=[values[0],0,values[1]]
                lines.append(' '.join(row['types'])+' '+' '.join(f'{v:g}' for v in values))
        lines.append('END');(ROOT/f'published_{variant}.prm').write_text('\n'.join(lines)+'\n')
    parent=[REPO/'backend/data/forcefield/top_all36_na.rtf',REPO/'backend/data/forcefield/par_all36_na.prm',FF/'top_all36_cgenff.rtf',FF/'par_all36_cgenff.prm']
    with warnings.catch_warnings():
        warnings.simplefilter('ignore');params=app.CharmmParameterSet(*map(str,parent))
    executable=Path(shutil.which('psfgen')).resolve()
    sources=[pin(p) for p in parent]+[pin(executable),pin(transcriptpath),transcript['source'],pin(transfer),pin(certpath),cert['geometry'],cert['stationarity_audit'],pin(corepath),core['sdf'],core['definition'],pin(endpointpath),endpoint['sdf'],endpoint['graph'],endpoint['definition'],pin(chargepath),charge['policy'],pin(endpointchargespath),pin(ROOT/'design.json')]
    fixtures={}
    for label,model in [('core',core),('endpoint',endpoint)]:
        folder=ROOT/label;folder.mkdir();keys=model['atom_keys']
        mol=Chem.MolFromMolFile(str(checked(model['sdf'])),removeHs=False)
        pairs=sorted(tuple(sorted((b.GetBeginAtomIdx(),b.GetEndAtomIdx()))) for b in mol.GetBonds())
        assert len(keys)==mol.GetNumAtoms() and len(pairs)==(38 if label=='core' else 52)
        cross=sorted(tuple(sorted((keys[a],keys[b]))) for a,b in pairs if keys[a][0]!=keys[b][0])
        assert cross==[('1:C5','2:C6'),('1:C6','2:C5')]
        if label=='endpoint':
            graph=read(checked(model['graph']))
            assert [v['key'] for v in graph['atoms']]==keys
            assert pairs==sorted(tuple(sorted(v['indices'])) for v in graph['bonds'])
        assignments=[]
        for k in keys:
            if k in base_assign:assignments.append(base_assign[k])
            else:
                sugar=endpointcharges['sugar'][k.split(':')[1]]
                assignments.append((sugar['atom_type'],sugar['charge_e']))
        assert abs(sum(q for _,q in assignments))<1e-12
        pdbnames=[f'A{i:03d}' for i in range(len(keys))]
        masses=[f'MASS -1 {t} {params.atom_types_str[t].mass}' for t in sorted({t for t,_ in assignments})]
        lines=['* Isolated corrected cis-anti-I development fixture','*','36 1',*masses,'AUTO ANGLES DIHE','RESI CPDX 0.0','GROUP']
        lines += [f'ATOM {name} {typ} {q:.16g}' for name,(typ,q) in zip(pdbnames,assignments)]
        lines += [f'BOND {pdbnames[a]} {pdbnames[b]}' for a,b in pairs]
        for residue in (1,2):
            for seq in [('C2','N1','N3','O2'),('C4','N3','C5','O4')]:
                lines.append('IMPR '+' '.join(pdbnames[keys.index(f'{residue}:{n}')] for n in seq))
        lines.append('END');(folder/'fragment.rtf').write_text('\n'.join(lines)+'\n')
        tcl=f'''package require psfgen
resetpsf
topology {folder}/fragment.rtf
segment B {{
 first NONE
 last NONE
 residue 1 CPDX
}}
regenerate angles dihedrals
writepsf {folder}/fragment.psf
exit
'''
        (folder/'build.tcl').write_text(tcl)
        proc=subprocess.run([str(executable),str(folder/'build.tcl')],cwd=folder,capture_output=True,text=True,timeout=30)
        (folder/'build.log').write_text(proc.stdout+proc.stderr);proc.check_returncode()
        psf=app.CharmmPsfFile(str(folder/'fragment.psf'))
        assert [a.name for a in psf.atom_list]==pdbnames
        assert sorted(tuple(sorted((b.atom1.idx,b.atom2.idx))) for b in psf.bond_list)==pairs
        # PSF decimal formatting can round charges; restore full-precision values
        # explicitly in the serialized engine systems and record the PSF error.
        rounding=max(abs(a.charge-q) for a,(_,q) in zip(psf.atom_list,assignments))
        for atom,(_,q) in zip(psf.atom_list,assignments):atom.charge=float(q)
        assert len(psf.improper_list)==4
        systems={};inventories={}
        for variant in ['first','last']:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                pars=app.CharmmParameterSet(*map(str,parent),str(ROOT/f'published_{variant}.prm'))
                system=psf.createSystem(pars,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False,removeCMMotion=False)
            inventory=[]
            for index,force in enumerate(system.getForces()):
                force.setForceGroup(index)
                inventory.append(dict(index=index,type=force.__class__.__name__))
                if isinstance(force,mm.NonbondedForce):
                    assert max(abs(float(force.getParticleParameters(i)[0]._value)-assignments[i][1]) for i in range(len(keys)))<1e-14
            path=folder/f'{variant}_system.xml';path.write_text(mm.XmlSerializer.serialize(system));systems[variant]=pin(path)
            inventories[variant]=dict(forces=inventory,parameter_load_warnings=[str(w.message) for w in caught])
        fixtures[label]=dict(atom_keys=keys,elements=model['elements'],assignments=[dict(atom=k,atom_type=t,charge_e=q) for k,(t,q) in zip(keys,assignments)],
                             model=pin(corepath if label=='core' else endpointpath),psf=pin(folder/'fragment.psf'),rtf=pin(folder/'fragment.rtf'),
                             systems=systems,bonds=pairs,angles=[(a.atom1.idx,a.atom2.idx,a.atom3.idx) for a in psf.angle_list],
                             improper_count=4,psf_charge_max_rounding_e=rounding,full_precision_engine_charges=True,
                             full_precision_psf_export_pending=True,engine_inventories=inventories)
        save(folder/'fixture.json',fixtures[label]);sources.extend([pin(folder/'fixture.json'),pin(folder/'fragment.psf'),pin(folder/'fragment.rtf'),pin(folder/'build.tcl'),pin(folder/'build.log'),*systems.values()])
    core_result=CAMPAIGN/'optimization/evaluation-030/result.json';cr=read(core_result)
    assert cr['geometry']==cert['geometry']
    points=[dict(label='core',fixture='core',geometry=cert['geometry'],qm_result=pin(core_result))]
    ringpath=CAMPAIGN/'coupled-ring-training-v1/plan.json';ring=read(ringpath)
    sources.extend([pin(ringpath),pin(CAMPAIGN/'coupled-ring-training-v1/completion_audit.json')])
    for case in ring['cases']:
        points.append(dict(label=case['label'],fixture='core',geometry=case['geometry'],qm_result=pin(ringpath.parent/case['label']/'result.json'),mode_rank=case['mode_rank'],step_bohr=case['step_bohr']))
    profilepath=CAMPAIGN/'glycosidic-branch-profile-v1/completed_profile_review.json';profile=read(profilepath);sources.append(pin(profilepath))
    for point in profile['points']:
        offset=point['offset_degrees']
        points.append(dict(label=f'endpoint-{offset:+d}',fixture='endpoint',geometry=point['geometry'],qm_result=point['result'],offset_degrees=offset,prior_audit=point['audit']))
        sources.append(point['audit'])
    assert len(points)==10
    for point in points:
        value=read(checked(point['qm_result']));assert value['geometry']==point['geometry']
        model=core if point['fixture']=='core' else endpoint;x=np.load(checked(point['geometry']))
        assert (geometry_audit(x,model) if point['fixture']=='core' else audit_endpoint(x,model))['passed']
        sources.extend([point['geometry'],point['qm_result'],value['native']])
    for name in ['corrected_core_stage1.py','corrected_coupled_ring.py','prepare_corrected_endpoints.py']:
        sources.append(pin(REPO/'experiments/cpd_anti_additive'/name))
    sources.append(pin(REPO/'experiments/cpd_published_comparator/reconstruct.py'))
    for variant in ['first','last']:sources.append(pin(ROOT/f'published_{variant}.prm'))
    plan=dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),
              fixtures=fixtures,points=points,variants=['first','last'],hard_seconds=900,variant_timeout_seconds=360,
              expected_seconds=180,threads=1,service_memory_gib=4,versions={n:metadata.version(n) for n in ['numpy','scipy','openmm','rdkit']},
              per_core_limits=dict(maxiter=1000,max_evaluations=1500,wall_seconds=300,gtol=1e-7,ftol=1e-15,maxls=40),
              stationarity_max_atom_gradient_kcal_mol_angstrom=.001,
              completion_semantics='Twenty native fixed-geometry MM evaluations plus two bounded core relaxations. Completion is diagnostic acquisition, not a fitted force field, basin closure or minimum certification.',
              source_ambiguity='Published SI conflicting duplicate rows retained as first/last hypotheses; additional parent Fourier multiplicities retained. Neither interpretation is asserted to reproduce the authors unprovided stream.',
              parameter_rounds_used=0,new_qm=0,heldout_accessed=False,charge_transfer_validated=False,minimum_certified=False,simulation_ready=False,cloud_spending_usd=0)
    save(ROOT/'plan.json',plan)
    # Verify coordinate/gradient units against independent energy differences.
    checks=[]
    for label,fixture in fixtures.items():
        point=next(v for v in points if v['fixture']==label);x=np.load(checked(point['geometry']))*BOHR
        for variant in plan['variants']:
            ev=Evaluator(checked(fixture['systems'][variant]));energy,g,_=ev.evaluate(x,True)
            errors=[]
            for atom,axis in [(fixture['atom_keys'].index('1:C5'),0),(fixture['atom_keys'].index('2:O4'),1),(len(x)-1,2)]:
                d=np.zeros_like(x);d[atom,axis]=1e-5
                numerical=(ev.evaluate(x+d)[0]-ev.evaluate(x-d)[0])/2e-5
                errors.append(abs(numerical-g[atom,axis]))
            assert max(errors)<1e-3
            checks.append(dict(fixture=label,variant=variant,maximum_gradient_error_kcal_mol_angstrom=max(errors)))
            ev.close()
    save(ROOT/'preflight.json',dict(at=now(),passed=True,plan=pin(ROOT/'plan.json'),gradient_checks=checks,
                                    fresh_graphs_verified=True,parameter_coverage_complete=True,core_atoms=36,endpoint_atoms=49,
                                    full_precision_engine_charges=True,full_precision_psf_export_pending=True,new_qm_evaluations=0))
    print(ROOT)


def variant_worker(root,variant):
    from scipy.optimize import minimize
    p=context(root);assert variant in p['variants']
    folder=root/f'evaluation-{variant}';folder.mkdir()
    with (folder/'started.json').open('x') as f:f.write(now()+'\n')
    engines={label:Evaluator(checked(f['systems'][variant])) for label,f in p['fixtures'].items()}
    records=[]
    for point in p['points']:
        x=np.load(checked(point['geometry']))*BOHR;qm=read(checked(point['qm_result']))
        energy,g,parts=engines[point['fixture']].evaluate(x,True)
        target=np.array(qm['gradient_hartree_bohr'])*EH/BOHR
        np.save(folder/(point['label']+'_gradient_kcal_A.npy'),g)
        records.append(dict(label=point['label'],fixture=point['fixture'],energy_kcal_mol=energy,force_group_energies=parts,
                            gradient=pin(folder/(point['label']+'_gradient_kcal_A.npy')),
                            max_atom_gradient_kcal_mol_angstrom=float(np.linalg.norm(g,axis=1).max()),
                            qm_gradient_component_rmse_kcal_mol_angstrom=float(np.sqrt(np.mean((g-target)**2))),
                            qm_energy_hartree=qm['energy_hartree'],geometry=point['geometry'],qm_result=point['qm_result']))
    save(folder/'static_results.json',dict(at=now(),plan=pin(root/'plan.json'),variant=variant,records=records,
        scope='Native OpenMM Reference at exact QM coordinates; raw full gradients, not projected constrained forces. Endpoint energies form an unrelaxed vertical profile.'))
    core=p['fixtures']['core'];model=read(checked(core['model']));x0=np.load(checked(p['points'][0]['geometry']))*BOHR
    ev=engines['core'];history=[];start=time.monotonic();last_accepted=x0.copy();accepted=[];error=None;solution=None
    def objective(flat):
        if len(history)>=p['per_core_limits']['max_evaluations'] or time.monotonic()-start>p['per_core_limits']['wall_seconds']:
            raise RuntimeError('Bounded core relaxation reached allocation limit')
        x=np.asarray(flat).reshape(-1,3);e,g,_=ev.evaluate(x)
        history.append((x.copy(),e,g.copy()))
        return e,g.ravel()
    def callback(flat):
        nonlocal last_accepted
        last_accepted=np.asarray(flat).reshape(-1,3).copy()
        accepted.append(last_accepted.copy());np.save(folder/'last_accepted_angstrom.npy',last_accepted)
        save(folder/'progress.json',dict(at=now(),accepted_steps=len(accepted),evaluations=len(history)))
    try:
        solution=minimize(objective,x0.ravel(),jac=True,method='L-BFGS-B',callback=callback,
                          options=dict(maxiter=1000,maxfun=1500,gtol=1e-7,ftol=1e-15,maxls=40))
        final=solution.x.reshape(-1,3)
    except Exception as exc:
        error=repr(exc);(folder/'failure_traceback.txt').write_text(traceback.format_exc());final=last_accepted
    finally:
        np.savez_compressed(folder/'evaluations.npz',coordinates_angstrom=np.array([v[0] for v in history]),
                            energies_kcal_mol=np.array([v[1] for v in history]),gradients_kcal_A=np.array([v[2] for v in history]))
        np.save(folder/'accepted_coordinates_angstrom.npy',np.array([x0,*accepted]))
    e,g,parts=ev.evaluate(final,True);np.save(folder/'final_angstrom.npy',final);np.save(folder/'final_gradient_kcal_A.npy',g)
    identity=geometry_audit(final/BOHR,model);force=float(np.linalg.norm(g,axis=1).max())
    result=dict(at=now(),plan=pin(root/'plan.json'),variant=variant,static_results=pin(folder/'static_results.json'),
                final_geometry=pin(folder/'final_angstrom.npy'),final_gradient=pin(folder/'final_gradient_kcal_A.npy'),
                raw_evaluations=pin(folder/'evaluations.npz'),accepted_coordinates=pin(folder/'accepted_coordinates_angstrom.npy'),
                error=error,optimizer_success=bool(solution.success) if solution is not None else False,
                optimizer_message=str(solution.message) if solution is not None else error,
                evaluations=len(history),wall_seconds=time.monotonic()-start,energy_kcal_mol=e,force_group_energies=parts,
                max_atom_gradient_kcal_mol_angstrom=force,stationary=force<=p['stationarity_max_atom_gradient_kcal_mol_angstrom'],
                identity=identity,geometry_differences=geometry_differences(x0,final,core),
                minimum_certified=False,fit_target_accepted=False,simulation_ready=False)
    save(folder/'assessment.json',result)
    for engine in engines.values():engine.close()
    print(dict(variant=variant,optimizer_success=result['optimizer_success'],stationary=result['stationary'],identity_passed=identity['passed'],evaluations=len(history)),flush=True)
    return 1 if error else 0


def run(root):
    p=context(root);deadline=read(root/'launch_receipt.json')['deadline_epoch'];completed=[];error=None
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    try:
        for variant in p['variants']:
            context(root)
            if deadline-time.time()<p['variant_timeout_seconds']+30:raise RuntimeError('Insufficient allocation for next hypothesis')
            with (root/f'{variant}_runner.log').open('x') as log:
                child=subprocess.run([str(PYTHON),str(checked(p['worker'])),'worker',str(root),'--variant',variant],
                    cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=p['variant_timeout_seconds'])
            if child.returncode:raise RuntimeError(f'Baseline hypothesis {variant} failed with code {child.returncode}')
            completed.append(pin(root/f'evaluation-{variant}/assessment.json'));save(root/'progress.json',dict(at=now(),completed=completed))
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),completed=completed,error=error,requires_completion_audit=True,
                                    minimum_certified=False,fit_target_accepted=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    p=context(root);assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Another CPD job active')
    available=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024
    if available<6*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient resource headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-bonded-baseline-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=p['expected_seconds'],review_deadline_epoch=start+720,review_deadline_id='bonded-baseline-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.25,memory_gib=4,omp_threads=1,plan=pin(root/'plan.json'),completion_semantics=p['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+900,unit=unit,available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=4G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=100%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=1',f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','launch','run','worker'])
    parser.add_argument('root',nargs='?',type=Path,default=ROOT);parser.add_argument('--variant',choices=['first','last'])
    args=parser.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='worker':sys.exit(variant_worker(root,args.variant))
    elif args.action=='run':sys.exit(run(root))
    else:launch(root)
