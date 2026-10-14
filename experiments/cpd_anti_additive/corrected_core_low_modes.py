"""Sixteen gradients to assess four numerically sensitive vibrational modes.

No percentage pass gate, optimizer, full Hessian, or automatic certification.
Native success means acquisition completed; a completion-triggered audit decides
the next allocation from absolute noise, step dependence, and curvature evidence.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    checked, geometry_audit, native_audit, now, pin, read, save, stationary,
)
from experiments.cpd_anti_additive.audit_corrected_core_stage1 import parse_native_table

CAMPAIGN = (REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT = CAMPAIGN/'low-mode-check-v1'
PYTHON = Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


from experiments.cpd_anti_additive.corrected_core_curvature_pilot import summarize


def coupled_subspace(directions, cartesian_norms, hessian_vectors, frequency_factor):
    """Convert unit Cartesian directional derivatives to a common MW mode basis."""
    q=np.asarray(directions,float); norms=np.asarray(cartesian_norms,float)
    hv=np.asarray(hessian_vectors,float)
    if (q.ndim!=2 or hv.shape!=(2,*q.shape) or norms.shape!=(len(q),)
            or not np.isfinite(q).all() or not np.isfinite(hv).all()
            or not np.isfinite(norms).all() or np.any(norms<=0)
            or not np.allclose(np.linalg.norm(q,axis=1),1,atol=1e-10,rtol=0)):
        raise ValueError('Invalid Cartesian directions or two-scale derivatives')
    d=q.T*norms
    blocks=[d.T@scale.T*norms for scale in hv]
    extrap=(4*blocks[1]-blocks[0])/3
    reports=[]
    for name,block in [('full',blocks[0]),('half',blocks[1]),('richardson',extrap)]:
        symmetric=(block+block.T)/2
        values=np.linalg.eigvalsh(symmetric)
        reports.append(dict(scale=name,raw_mass_weighted_block=block.tolist(),
            antisymmetry_spectral_norm=float(np.linalg.norm(block-block.T,2)),
            eigenvalues_mass_weighted=values.tolist(),
            signed_frequencies_cm_inverse=(np.sign(values)*np.sqrt(abs(values))*frequency_factor).tolist()))
    return dict(scales=reports,step_difference_spectral_norm=float(np.linalg.norm(blocks[0]-blocks[1],2)),
        richardson_correction_spectral_norm=float(np.linalg.norm(extrap-blocks[1],2)),
        scope='Four-mode subspace only. Check coupling, step dependence, energies and noise in completion review; no automatic minimum certificate.',minimum_certified=False)


def context(root, launched=True):
    plan = read(root/'plan.json')
    if launched:
        execution = read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan']) != root/'plan.json':
            raise ValueError('Launched plan changed')
    if checked(plan['worker']) != Path(__file__).resolve():
        raise ValueError('Frozen worker identity changed')
    for ref in plan['sources']:
        checked(ref)
    decision = read(checked(plan['decision']))
    auth = read(checked(plan['authorization']))
    base = read(checked(plan['source_options']))
    if not decision['passed_reconstruction_and_native_audit'] or not auth['user_authorized']:
        raise ValueError('Missing admission')
    if auth['compute_policy']['cloud_spending_usd'] != 0 or plan['options'] != base['options']:
        raise ValueError('Unreviewed resource or method change')
    if plan['hard_seconds'] != 1800 or len(plan['cases']) != 16 or len(plan['modes']) != 4:
        raise ValueError('Finite allocation changed')
    pause = CAMPAIGN/'pause.json'
    if pause.exists() and read(pause).get('paused'):
        raise RuntimeError('Campaign paused')
    return plan, base


def prepare():
    stage=read(CAMPAIGN/'stage1_completion_audit.json')
    base_ref=stage['plan']; base=read(checked(base_ref))
    decision_path=CAMPAIGN/'hessian-stage2-v3/assembly/independent_completion_audit.json'
    audit=read(decision_path)
    if not audit['passed_reconstruction_and_native_audit'] or not stage['passed']:
        raise ValueError('Hessian or stationarity audit missing')
    x=np.load(checked(stage['final_binary_geometry']))
    weights=np.repeat(np.sqrt(read(checked(audit['mode_labels']))['masses']),3)
    modes_mw=np.load(checked(audit['mass_weighted_modes']))
    refs=read(CAMPAIGN/'threshold_reassessment_20261010.json')['original_method_references']
    reference_gradients=[]
    for row in refs:
        result=read(checked(row['result']));checked(row['native'])
        gradient=result.get('gradient_hartree_bohr',result.get('gradient',result.get('return_result')))
        reference_gradients.append(np.asarray(gradient).reshape(36,3))
    ROOT.mkdir(exist_ok=False);(ROOT/'tmp').mkdir()
    shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    cases=[];modes=[]
    for i,mode in enumerate(audit['selected_low_mode_checks']):
        d=modes_mw[:,mode['mode_column']]/weights
        norm=float(np.linalg.norm(d));q=(d/norm).reshape(36,3);label=f'mode-{i+1}'
        modes.append(dict(**mode,label=label,direction=q.tolist(),
            cartesian_norm=norm,reference_slopes_au=[float(np.sum(g*q)) for g in reference_gradients]))
        for suffix,h in [('plus-full',.04),('minus-full',-.04),('plus-half',.02),('minus-half',-.02)]:
            case_label=label+'-'+suffix;folder=ROOT/case_label;folder.mkdir();(folder/'scratch').mkdir()
            pos=x+h*q;identity=geometry_audit(pos,base)
            if not identity['passed']:raise ValueError('Low-mode displaced identity failed')
            save(folder/'input.json',dict(elements=base['elements'],geometry_bohr=pos.tolist(),
                step_bohr=h,mode_label=label,geometry_audit=identity))
            cases.append(dict(label=case_label,input=pin(folder/'input.json')))
    sources=[*base['sources'],pin(CAMPAIGN/'stage1_completion_audit.json'),stage['final_binary_geometry'],
        audit['hessian'],audit['mass_weighted_modes'],audit['mode_labels'],
        *[item for row in refs for item in (row['result'],row['native'])],
        pin(REPO/'experiments/cpd_anti_additive/corrected_core_stage1.py'),
        pin(REPO/'experiments/cpd_anti_additive/audit_corrected_core_stage1.py'),
        pin(REPO/'experiments/cpd_anti_additive/corrected_core_curvature_pilot.py')]
    save(ROOT/'plan.json',dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,
        decision=pin(decision_path),authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),
        source_options=base_ref,options=base['options'],modes=modes,cases=cases,
        source_hessian=audit['hessian'],source_mode_basis=audit['mass_weighted_modes'],
        frequency_conversion_factor=audit['frequency_conversion_factor'],
        reference_energy_spread_hartree=float(np.ptp([r['energy_hartree'] for r in refs])),
        selection_reason=audit['selection_reason'],steps_cartesian_unit_direction_bohr=[.04,.02],
        hard_seconds=1800,task_timeout_seconds=180,maximum_new_gradients=16,
        threads=4,memory_gib=4,psi4_version=base['psi4_version'],expected_seconds=audit['next_attempt']['expected_seconds'],
        completion_semantics='Native acquisition and numerical summaries only. Review evidence before minimum certification; no automatic subsequent job.',
        review_policy='Assess signs, absolute step corrections, coupled four-mode eigenvalues, energy-derived curvature and empirical noise. Compare with existing Hessian and remaining-mode coupling using retained full Hessian-vector products. No universal 5% gate or automatic certificate; do not extend absent a specific unresolved question.',
        minimum_certified=False,gate_effect='none'))
    print(ROOT)


def worker(root, label):
    plan, base = context(root)
    case = next(c for c in plan['cases'] if c['label'] == label)
    inp = read(checked(case['input'])); folder = root/label
    with (folder/'started.json').open('x') as f:
        f.write(now()+'\n')
    import psi4
    if psi4.__version__ != plan['psi4_version']:
        raise ValueError('Engine changed')
    os.chdir(folder)
    psi4.set_output_file(str(folder/'output.dat'), False)
    psi4.set_memory('4 GiB'); psi4.set_num_threads(4)
    psi4.core.IOManager.shared_object().set_default_path(str(folder/'scratch'))
    psi4.set_options(plan['options'])
    x = np.array(inp['geometry_bohr'])
    text = '\n'.join(el+' '+' '.join(f'{v:.17g}' for v in xyz)
                     for el, xyz in zip(inp['elements'], x))
    molecule = psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    start = time.monotonic()
    grad, wfn = psi4.gradient('mp2', molecule=molecule, return_wfn=True)
    elapsed = time.monotonic()-start
    g = np.asarray(grad).copy(); energy = float(wfn.energy())
    actual = np.asarray(wfn.molecule().geometry()).copy()
    if np.max(abs(actual-x)) > 1e-14 or not geometry_audit(actual, base)['passed']:
        raise ValueError('Coordinate or chemistry failure')
    psi4.core.clean(); psi4.core.flush_outfile(); psi4.core.close_outfile()
    native = (folder/'output.dat').read_text()
    electronic = native_audit(native, energy, g)
    en, gn = parse_native_table(native, len(x))
    if abs(en-energy) > 1e-9 or np.max(abs(gn-g)) > 1e-11:
        raise ValueError('Native table disagrees')
    if 'Fitting Condition:        1E-10' not in native:
        raise ValueError('Original fitting condition missing')
    save(folder/'result.json', dict(at=now(), input=case['input'], native=pin(folder/'output.dat'),
        energy_hartree=energy, gradient_hartree_bohr=g.tolist(), native_audit=electronic,
        returned_geometry_bohr=actual.tolist(), wall_seconds=elapsed,
        psi4_version=psi4.__version__, minimum_certified=False))


def review(root):
    plan, base = context(root); records = {}; pins = []
    for case in plan['cases']:
        path = root/case['label']/'result.json'; result = read(path)
        if result['input'] != case['input']:
            raise ValueError('Input/result mismatch')
        inp = read(checked(case['input'])); native = checked(result['native']).read_text()
        en, gn = parse_native_table(native, len(base['elements']))
        g = np.array(result['gradient_hartree_bohr'])
        if abs(en-result['energy_hartree']) > 1e-9 or np.max(abs(gn-g)) > 1e-11:
            raise ValueError('Native verification failed')
        native_audit(native, en, gn)
        x = np.array(result['returned_geometry_bohr'])
        if np.max(abs(x-np.array(inp['geometry_bohr']))) > 1e-14 or not geometry_audit(x, base)['passed']:
            raise ValueError('Returned geometry failed')
        records[case['label']] = result; pins.append(pin(path))
    per_mode=[];hv_full=[];hv_half=[]
    for mode in plan['modes']:
        samples=[]
        for suffix,h in [('full',.04),('half',.02)]:
            p,m=records[mode['label']+'-plus-'+suffix],records[mode['label']+'-minus-'+suffix]
            samples.append((h,p['energy_hartree'],m['energy_hartree'],p['gradient_hartree_bohr'],m['gradient_hartree_bohr']))
        summary=summarize(mode['direction'],samples,mode['reference_slopes_au'],plan['reference_energy_spread_hartree'])
        hv_full.append(np.asarray(summary['scales'][0]['hessian_vector_au']).ravel())
        hv_half.append(np.asarray(summary['scales'][1]['hessian_vector_au']).ravel())
        per_mode.append(dict(mode_label=mode['label'],original_hessian_mode=mode,**summary))
    hv=np.array([hv_full,hv_half])
    coupled=coupled_subspace([np.asarray(m['direction']).ravel() for m in plan['modes']],
        [m['cartesian_norm'] for m in plan['modes']],hv,plan['frequency_conversion_factor'])
    hv_path=root/'low_mode_hessian_vectors.npy'
    if hv_path.exists():
        if not np.array_equal(np.load(hv_path),hv):raise ValueError('Previously saved Hessian vectors changed')
    else:np.save(hv_path,hv)
    report=dict(at=now(),plan=pin(root/'plan.json'),results=pins,
        native_calculations_completed=16,native_evidence_verified=True,
        wall_seconds=sum(v['wall_seconds'] for v in records.values()),
        per_mode=per_mode,coupled_subspace=coupled,hessian_vectors=pin(hv_path),
        minimum_certified=False,simulation_ready=False,requires_completion_audit=True)
    path = root/'independent_review.json'
    if path.exists():
        old = read(path)
        if old['results'] != pins:
            raise ValueError('Previously audited evidence changed')
        return old
    save(path, report)
    return report


def run(root):
    plan, _ = context(root)
    with (root/'started.json').open('x') as f:
        f.write(now()+'\n')
    deadline = read(root/'launch_receipt.json')['deadline_epoch']
    completed = []; error = None; report = None
    try:
        for case_index,case in enumerate(plan['cases']):
            context(root)
            if deadline-time.time() < (2 if case_index%2==0 else 1)*plan['task_timeout_seconds']+30:
                raise RuntimeError('Insufficient boundary time')
            folder = root/case['label']
            env = {**os.environ, 'PSI_SCRATCH':str(folder/'scratch'), 'TMPDIR':str(folder/'scratch')}
            with (folder/'runner.log').open('x') as log:
                result = subprocess.run([sys.executable, str(checked(plan['worker'])),
                    'worker', str(root), '--label', case['label']], stdout=log,
                    stderr=subprocess.STDOUT, env=env, cwd=folder, timeout=plan['task_timeout_seconds'])
            if result.returncode:
                raise RuntimeError(f"Native task {case['label']} failed: {result.returncode}")
            completed.append(pin(folder/'result.json'))
            save(root/'progress.json', dict(completed=completed, at=now()))
        report = review(root)
    except Exception as exc:
        error = repr(exc)
        (root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json', dict(at=now(), error=error, completed=len(completed),
        native_completed=len(completed)==16, numerical_adequacy='pending_completion_audit',
        review=None if report is None else pin(root/'independent_review.json'), minimum_certified=False))
    return 1 if error or report is None else 0


def launch():
    root = ROOT; plan, _ = context(root, launched=False)
    units = subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'], text=True)
    if any('cpd-' in line for line in units.splitlines()):
        raise RuntimeError('Another CPD service is active')
    processes = subprocess.check_output(['ps','-eo','args='], text=True).splitlines()
    if any(line.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for line in processes):
        raise RuntimeError('Another native simulation process is active')
    mem = {line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()
           if line.startswith(('MemAvailable:', 'SwapFree:'))}
    if mem['MemAvailable'] < 12*1024**3 or shutil.disk_usage(root).free < 30*1024**3:
        raise RuntimeError('Insufficient RAM or Archive headroom')
    service = CAMPAIGN/(root.name+'-service'); service.mkdir(exist_ok=False)
    for old, new in [('launch.py','supervisor.py'), ('watch.py','watcher.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/old, service/new)
    unit = 'cpd-corrected-anti1-low-modes-v1'; start = time.time()
    save(service/'watcher_config.json', dict(codex_executable=str(Path(shutil.which('codex')).resolve()),
        expected_seconds=plan['expected_seconds'], review_deadline_epoch=start+1500,
        review_deadline_id='low-modes-terminal-audit', self_test=False))
    save(service/'execution_plan.json', dict(unit=unit, thread=os.environ['CODEX_THREAD_ID'],
        command=[str(PYTHON), str(root/'executed_source.py'), 'run', str(root)], cwd=str(root),
        runtime_hours=.5, memory_gib=8, omp_threads=4, plan=pin(root/'plan.json'),
        completion_semantics=plan['completion_semantics']))
    save(root/'launch_receipt.json', dict(at=now(), deadline_epoch=start+1800, unit=unit,
        prelaunch_memory=mem, execution_plan=pin(service/'execution_plan.json'),
        supervisor=pin(service/'supervisor.py'), watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G',
        '--property=MemorySwapMax=0','--property=RuntimeMaxSec=1785s','--property=TimeoutStopSec=15s',
        '--property=KillMode=control-group','--property=CPUQuota=400%',
        f'--setenv=PYTHONPATH={REPO}', f'--setenv=NADOC_REPO_ROOT={REPO}',
        '--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1',
        '--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',
        f'--setenv=PSI_SCRATCH={root}/tmp', f'--setenv=TMPDIR={root}/tmp',
        '/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)], check=True)
    print(service)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare','launch','run','worker','review'))
    p.add_argument('root', nargs='?', type=Path, default=ROOT)
    p.add_argument('--label')
    args = p.parse_args(); root = args.root.resolve()
    if args.action == 'worker':
        worker(root, args.label)
    elif args.action == 'run':
        sys.exit(run(root))
    elif args.action == 'review':
        print(review(root))
    else:
        globals()[args.action]()
