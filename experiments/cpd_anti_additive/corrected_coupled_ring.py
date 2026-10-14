"""Four finite core-mode distortions for development reference acquisition.

The exact certified core and two modes are reused; this is neither a new Hessian
nor a ring-bond torsion scan. All decisions precede the four native gradients.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    BOHR,checked,geometry_audit,native_audit,now,pin,read,save,
)
from experiments.cpd_anti_additive.audit_corrected_core_stage1 import parse_native_table

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'coupled-ring-training-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def ranked_modes(mass_weighted,masses,labels,active,hessian):
    q=np.asarray(mass_weighted,float);mass=np.asarray(masses,float);h=np.asarray(hessian,float)
    n=3*len(mass)
    if (q.shape!=(n,n) or h.shape!=(n,n) or len(labels)!=n or
            not np.isfinite(q).all() or not np.isfinite(h).all() or
            not np.isfinite(mass).all() or np.any(mass<=0) or
            len(set(active))!=len(active) or not active or min(active)<0 or max(active)>=len(mass)):
        raise ValueError('Invalid mode inventory')
    rows=[]
    for column,kind in enumerate(labels):
        if kind!='V':continue
        d=q[:,column]/np.repeat(np.sqrt(mass),3)
        norm=np.linalg.norm(d)
        if norm<=0:raise ValueError('Empty vibrational mode')
        d=d/norm
        if d[np.argmax(abs(d))]<0:d=-d
        curvature=float(d@h@d)
        if curvature<=0:raise ValueError('Nonpositive reference mode; review certification')
        rows.append(dict(mode_column=column,ring_participation=float(np.sum(d.reshape(-1,3)[active]**2)),
            direction=d.reshape(-1,3).tolist(),curvature_hartree_bohr2=curvature,
            predicted_even_energy_kcal_mol_at_step=.5*.1**2*curvature*627.509474,
            maximum_atom_displacement_angstrom=float(np.linalg.norm(d.reshape(-1,3),axis=1).max()*.1*BOHR)))
    rows.sort(key=lambda v:(-v['ring_participation'],v['mode_column']))
    if len(rows)<3:raise ValueError('Insufficient internal modes')
    return rows


def require_archive(root):
    archive=Path('/media/jojo/Archive')
    if not archive.is_mount() or root.stat().st_dev!=archive.stat().st_dev or archive.stat().st_dev==Path('/').stat().st_dev:
        raise RuntimeError('Mounted Archive required; no fallback')


def context(root):
    require_archive(root)
    plan=read(root/'plan.json')
    if checked(plan['worker'])!=Path(__file__).resolve():raise ValueError('Frozen worker changed')
    for ref in plan['sources']:checked(ref)
    base=read(checked(plan['source_options']));auth=read(checked(plan['authorization']))
    cert=read(checked(plan['core_certification']))
    if not auth['user_authorized'] or auth['compute_policy']['cloud_spending_usd']!=0 or not cert['minimum_certified']:
        raise ValueError('Core reference or local authority missing')
    if plan['options']!=base['options'] or plan['psi4_version']!=base['psi4_version']:
        raise ValueError('Method changed')
    if (plan['hard_seconds'],plan['task_timeout_seconds'],len(plan['cases']),plan['maximum_new_gradients'])!=(900,180,4,4):
        raise ValueError('Finite allocation changed')
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):
        raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan'])!=root/'plan.json':raise ValueError('Launched plan changed')
    return plan,base


def prepare():
    require_archive(CAMPAIGN)
    cert_path=CAMPAIGN/'core_local_minimum_assessment.json';cert=read(cert_path)
    stage=read(checked(cert['stationarity_audit']));base=read(checked(stage['plan']))
    audit=read(checked(cert['hessian_audit']));labels=read(checked(audit['mode_labels']))
    profile=CAMPAIGN/'glycosidic-branch-profile-v1/completed_profile_review.json'
    if not cert['minimum_certified'] or not stage['passed'] or not read(profile)['completed_glycosidic_acquisition']:
        raise ValueError('Preceding reviews missing')
    x=np.load(checked(cert['geometry']));active=[base['atom_keys'].index(k) for k in ['1:C5','1:C6','2:C5','2:C6']]
    ranked=ranked_modes(np.load(checked(audit['mass_weighted_modes'])),labels['masses'],labels['TRV'],active,np.load(checked(audit['hessian'])))
    if len(ranked)!=102:raise ValueError('Unexpected vibrational inventory')
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    reference=read(checked(stage['final_result']));g=np.asarray(reference['gradient_hartree_bohr'])
    save(ROOT/'mode_selection.json',dict(at=now(),active_atoms=[base['atom_keys'][i] for i in active],
        rule='Rank the 102 internal modes by fraction of unit Cartesian displacement squared on the four cyclobutane carbons. Break ties by saved mode column. Convert mass-weighted vectors with inverse square-root masses and canonicalize sign by largest component.',
        ranked_modes=ranked,training_mode_columns=[v['mode_column'] for v in ranked[:2]],
        heldout_mode_column=ranked[2]['mode_column'],
        training_step_bohr=.1,heldout_step_bohr=.1,signs=[-1,1],
        step_reason='Finite response at 0.1 bohr in unit Cartesian direction; selected modes predict 0.42 and 0.93 kcal/mol even harmonic response with <0.020 A maximum atom displacement. Sampling design, not an accuracy acceptance threshold.',
        coverage='Two ring-enriched directions only. They do not span all coupled ring terms or certify fitted force constants.',
        heldout_policy='Third ranked direction, +/-0.1 bohr; no heldout coordinates or electronic targets acquired until candidate parameters are hash-locked. Development Hessian informed the direction: prospective finite-amplitude validation, not an independent structure or unseen Hessian test.'))
    cases=[]
    for rank,mode in enumerate(ranked[:2],1):
        q=np.asarray(mode['direction'])
        for sign in [-1,1]:
            label=f'mode-{rank}-'+('minus' if sign<0 else 'plus');folder=ROOT/label
            folder.mkdir();(folder/'scratch').mkdir()
            y=x+sign*.1*q;identity=geometry_audit(y,base)
            if not identity['passed']:raise ValueError('Displaced corrected identity failed')
            np.save(folder/'geometry_bohr.npy',y)
            save(folder/'input.json',dict(elements=base['elements'],geometry_bohr=y.tolist(),method='mp2',charge=0,multiplicity=1,
                options=base['options'],mode_column=mode['mode_column'],step_bohr=sign*.1,geometry_audit=identity))
            cases.append(dict(label=label,input=pin(folder/'input.json'),geometry=pin(folder/'geometry_bohr.npy'),
                mode_rank=rank,mode_column=mode['mode_column'],step_bohr=sign*.1,
                reference_slope_hartree_bohr=float(np.sum(g*q)),
                predicted_even_energy_kcal_mol=mode['predicted_even_energy_kcal_mol_at_step']))
    sources=[*base['sources'],pin(cert_path),cert['stationarity_audit'],cert['hessian_audit'],cert['low_mode_audit'],cert['geometry'],
        stage['final_result'],audit['mass_weighted_modes'],audit['mode_labels'],audit['hessian'],pin(profile),pin(ROOT/'mode_selection.json'),
        pin(REPO/'experiments/cpd_anti_additive/corrected_core_stage1.py'),pin(REPO/'experiments/cpd_anti_additive/audit_corrected_core_stage1.py')]
    save(ROOT/'plan.json',dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,
        authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),core_certification=pin(cert_path),
        reference_design=pin(CAMPAIGN/'endpoint_reference_design_v1.json'),source_options=stage['plan'],
        reference_result=stage['final_result'],reference_geometry=cert['geometry'],options=base['options'],psi4_version=base['psi4_version'],
        selection=pin(ROOT/'mode_selection.json'),cases=cases,maximum_new_gradients=4,hard_seconds=900,task_timeout_seconds=180,
        threads=4,psi4_memory_gib=4,service_memory_gib=8,expected_seconds=read(CAMPAIGN/'low-mode-check-v1/independent_review.json')['wall_seconds']/4+20,
        completion_semantics='Four fixed-geometry native responses acquired; no optimization or new minimum certification. Independent native and response audit required before fitting.',
        review_policy='Compare full native gradients/energies with exact inputs and core identity, then response versus development Hessian and both signs. Preserve discrepancies without clipping or an arbitrary percentage gate. Stop after the four tasks; no automatic extension.',
        membership='Four exposed development/training targets; heldout rank-three pair remains unacquired. Existing glycosidic heldouts remain untouched.',
        fit_target_accepted=False,minimum_certified=False,simulation_ready=False,cloud_spending_usd=0))
    # Verify the frozen source, method and every exact displaced identity without QM.
    import importlib.util
    spec=importlib.util.spec_from_file_location('ring_preflight',ROOT/'executed_source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.context(ROOT)
    save(ROOT/'preflight.json',dict(at=now(),passed=True,source_pins_verified=True,displaced_identities_verified=4,
        fresh_gradients_required=True,no_optimizer=True,new_qm_evaluations=0,archive_device=ROOT.stat().st_dev,
        output=str(ROOT),scratch=str(ROOT/'tmp'),system_disk_fallback=False))
    print(ROOT)


def worker(root,label):
    plan,base=context(root);case=next(v for v in plan['cases'] if v['label']==label)
    folder=root/label;inp=read(checked(case['input']));x=np.load(checked(case['geometry']))
    require_archive(folder/'scratch')
    if inp['options']!=plan['options'] or not np.array_equal(x,inp['geometry_bohr']) or not geometry_audit(x,base)['passed']:
        raise ValueError('Displaced input changed')
    with (folder/'started.json').open('x') as f:f.write(now()+'\n')
    import psi4
    if psi4.__version__!=plan['psi4_version']:raise ValueError('Engine changed')
    os.chdir(folder);psi4.set_output_file(str(folder/'output.dat'),False)
    psi4.set_memory('4 GiB');psi4.set_num_threads(4)
    psi4.core.IOManager.shared_object().set_default_path(str(folder/'scratch'));psi4.set_options(plan['options'])
    text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(inp['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    start=time.monotonic();gradient,wfn=psi4.gradient('mp2',molecule=molecule,return_wfn=True)
    elapsed=time.monotonic()-start;g=np.asarray(gradient).copy();energy=float(wfn.energy());actual=np.asarray(wfn.molecule().geometry()).copy()
    np.save(folder/'gradient_hartree_bohr.npy',g);np.save(folder/'returned_geometry_bohr.npy',actual)
    psi4.core.clean();psi4.core.flush_outfile();psi4.core.close_outfile()
    native=(folder/'output.dat').read_text();electronic=native_audit(native,energy,g)
    en,gn=parse_native_table(native,len(x))
    if abs(en-energy)>1e-9 or np.max(abs(gn-g))>1e-11 or np.max(abs(actual-x))>1e-14 or not geometry_audit(actual,base)['passed']:
        raise ValueError('Native or returned geometry verification failed')
    if 'Fitting Condition:        1E-10' not in native:raise ValueError('Original fitting condition missing')
    save(folder/'result.json',dict(at=now(),input=case['input'],geometry=case['geometry'],native=pin(folder/'output.dat'),
        energy_hartree=energy,gradient_hartree_bohr=g.tolist(),gradient_binary=pin(folder/'gradient_hartree_bohr.npy'),
        returned_geometry=pin(folder/'returned_geometry_bohr.npy'),native_audit=electronic,wall_seconds=elapsed,
        minimum_certified=False,simulation_ready=False))


def review(root):
    plan,base=context(root);reference=read(checked(plan['reference_result']));modes=read(checked(plan['selection']))['ranked_modes'];rows=[]
    for case in plan['cases']:
        p=root/case['label']/'result.json';v=read(p);inp=read(checked(case['input']));native=checked(v['native']).read_text()
        x=np.load(checked(v['geometry']));g=np.asarray(v['gradient_hartree_bohr']);en,gn=parse_native_table(native,len(x))
        if v['input']!=case['input'] or v['geometry']!=case['geometry'] or not np.array_equal(x,inp['geometry_bohr']) or inp['options']!=plan['options']:
            raise ValueError('Result/input mismatch')
        if abs(en-v['energy_hartree'])>1e-9 or np.max(abs(gn-g))>1e-11 or not np.array_equal(g,np.load(checked(v['gradient_binary']))):
            raise ValueError('Native gradient mismatch')
        if np.max(abs(np.load(checked(v['returned_geometry']))-x))>1e-14 or not geometry_audit(x,base)['passed']:
            raise ValueError('Returned geometry/identity mismatch')
        native_audit(native,en,gn)
        if 'Fitting Condition:        1E-10' not in native:raise ValueError('Original fitting condition missing')
        d=np.asarray(modes[case['mode_rank']-1]['direction'])
        rows.append(dict(label=case['label'],result=pin(p),native=v['native'],input=v['input'],
            energy_hartree=en,energy_relative_to_reference_kcal_mol=627.509474*(en-reference['energy_hartree']),
            directional_gradient_hartree_bohr=float(np.sum(g*d)),wall_seconds=v['wall_seconds']))
    pairs=[]
    for rank in (1,2):
        minus,plus=rows[2*(rank-1):2*rank]
        pairs.append(dict(mode_rank=rank,mode_column=modes[rank-1]['mode_column'],
            energy_curvature_hartree_bohr2=(plus['energy_hartree']+minus['energy_hartree']-2*reference['energy_hartree'])/.1**2,
            gradient_curvature_hartree_bohr2=(plus['directional_gradient_hartree_bohr']-minus['directional_gradient_hartree_bohr'])/.2,
            hessian_curvature_hartree_bohr2=modes[rank-1]['curvature_hartree_bohr2']))
    out=root/'independent_review.json'
    data=dict(at=now(),plan=pin(root/'plan.json'),native_evidence_passed=True,records=rows,response_pairs=pairs,
        native_gradient_components=432,returned_geometry_arrays_verified=4,requires_completion_audit=True,
        fit_target_accepted=False,minimum_certified=False,simulation_ready=False)
    if out.exists():
        old=read(out)
        if old['records']!=rows:raise ValueError('Previously reviewed evidence changed')
        return old
    save(out,data);return data


def run(root):
    plan,_=context(root)
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    deadline=read(root/'launch_receipt.json')['deadline_epoch'];completed=[];error=None
    try:
        for case in plan['cases']:
            context(root)
            if deadline-time.time()<plan['task_timeout_seconds']+30:raise RuntimeError('Insufficient boundary time')
            folder=root/case['label'];env={**os.environ,'TMPDIR':str(folder/'scratch'),'PSI_SCRATCH':str(folder/'scratch')}
            with (folder/'runner.log').open('x') as log:
                result=subprocess.run([str(PYTHON),str(checked(plan['worker'])),'worker',str(root),'--label',case['label']],
                    stdout=log,stderr=subprocess.STDOUT,env=env,cwd=folder,timeout=plan['task_timeout_seconds'])
            if result.returncode:raise RuntimeError(f"Native task {case['label']} failed: {result.returncode}")
            completed.append(pin(folder/'result.json'));save(root/'progress.json',dict(at=now(),completed=completed))
        review(root)
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),error=error,completed=len(completed),native_completed=len(completed)==4,
        requires_completion_audit=True,minimum_certified=False,fit_target_accepted=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    plan,_=context(root)
    if not read(root/'preflight.json')['passed']:raise ValueError('Preflight missing')
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Other CPD native job active')
    processes=subprocess.check_output(['ps','-eo','args='],text=True).splitlines()
    if any(line.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for line in processes):raise RuntimeError('Other native job active')
    mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','SwapFree:'))}
    if mem['MemAvailable']<12*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient resource headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-coupled-ring-training-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=plan['expected_seconds'],review_deadline_epoch=start+780,review_deadline_id='coupled-ring-completion-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(plan['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.25,memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=plan['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+900,unit=unit,prelaunch_memory=mem,
        execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',f'--setenv=PSI_SCRATCH={root}/tmp',f'--setenv=TMPDIR={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','launch','run','worker','review'));p.add_argument('root',nargs='?',type=Path,default=ROOT);p.add_argument('--label')
    args=p.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='worker':worker(root,args.label)
    elif args.action=='run':sys.exit(run(root))
    elif args.action=='review':print(review(root))
    else:launch(root)
