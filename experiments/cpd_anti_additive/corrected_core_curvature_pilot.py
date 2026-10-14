"""Four original-method gradients to measure directional Hessian feasibility.

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
ROOT = CAMPAIGN/'original-method-curvature-pilot-v1'
PYTHON = Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def summarize(direction, samples, reference_slopes, energy_spread):
    """Central/Richardson estimates; empirical envelopes are not error bounds."""
    q = np.asarray(direction, float)
    if not np.isfinite(q).all() or abs(np.linalg.norm(q)-1) > 1e-10:
        raise ValueError('Direction must be finite and normalized')
    if len(samples) != 2 or samples[0][0] != 2*samples[1][0]:
        raise ValueError('Require two centered samples at h and h/2')
    if not np.isfinite(reference_slopes).all() or len(reference_slopes) < 2:
        raise ValueError('Require finite independent reference slopes')
    if not np.isfinite(energy_spread) or energy_spread < 0:
        raise ValueError('Invalid empirical energy spread')
    rows = []
    for h, ep, em, gp, gm in samples:
        gp, gm = np.asarray(gp), np.asarray(gm)
        if h <= 0 or gp.shape != q.shape or gm.shape != q.shape:
            raise ValueError('Invalid step or gradient shape')
        if not all(np.isfinite(v).all() for v in (ep, em, gp, gm)):
            raise ValueError('Nonfinite result')
        hvp = (gp-gm)/(2*h)
        rows.append(dict(step_bohr=h, energy_slope_au=float((ep-em)/(2*h)),
                         gradient_curvature_au=float(np.sum(q*hvp)),
                         hessian_vector_au=hvp.tolist(), energy_pair_sum=float(ep+em)))
    full, half = rows
    slope = (4*half['energy_slope_au']-full['energy_slope_au'])/3
    curvature = (4*half['gradient_curvature_au']-full['gradient_curvature_au'])/3
    # E(+h)+E(-h) = 2E0 + k*h^2 + O(h^4); E0 cancels here.
    energy_curvature = ((full['energy_pair_sum']-half['energy_pair_sum']) /
                        (full['step_bohr']**2-half['step_bohr']**2))
    projected_spread = float(np.ptp(reference_slopes))
    return dict(scales=rows, richardson_energy_slope_au=float(slope),
        richardson_gradient_curvature_au=float(curvature),
        energy_curvature_without_reference_energy_au=float(energy_curvature),
        slope_step_correction_au=float(abs(slope-half['energy_slope_au'])),
        curvature_step_correction_au=float(abs(curvature-half['gradient_curvature_au'])),
        reference_slopes_au=list(reference_slopes),
        absolute_slope_errors_au=[float(abs(slope-s)) for s in reference_slopes],
        empirical_reference_projected_gradient_spread_au=projected_spread,
        empirical_reference_energy_spread_hartree=energy_spread,
        empirical_slope_noise_scale_au=float(energy_spread/half['step_bohr']),
        empirical_gradient_curvature_noise_scale_au=float(projected_spread/half['step_bohr']),
        empirical_energy_curvature_noise_scale_au=float(
            2*energy_spread/(full['step_bohr']**2-half['step_bohr']**2)),
        evidence_scope='One direction, two steps. Reference spreads are empirical sensitivity scales, not statistical confidence intervals or guaranteed displaced-point error bounds.',
        minimum_certified=False, simulation_ready=False, requires_completion_audit=True)


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
    if not decision['admit_original_method_curvature_pilot'] or not auth['user_authorized']:
        raise ValueError('Missing admission')
    if auth['compute_policy']['cloud_spending_usd'] != 0 or plan['options'] != base['options']:
        raise ValueError('Unreviewed resource or method change')
    if plan['hard_seconds'] != 900 or len(plan['cases']) != 4:
        raise ValueError('Finite allocation changed')
    pause = CAMPAIGN/'pause.json'
    if pause.exists() and read(pause).get('paused'):
        raise RuntimeError('Campaign paused')
    return plan, base


def prepare():
    stage = read(CAMPAIGN/'stage1_completion_audit.json')
    base_ref = stage['plan']; base = read(checked(base_ref))
    decision_path = CAMPAIGN/'threshold_reassessment_20261010.json'
    decision = read(decision_path)
    if not stage['passed'] or not decision['admit_original_method_curvature_pilot']:
        raise ValueError('Stationarity or admission missing')
    x = np.load(checked(stage['final_binary_geometry']))
    q = np.array(read(CAMPAIGN/'conditioned-directional-check-v1/plan.json')['direction'])
    refs = decision['original_method_references']
    ROOT.mkdir(exist_ok=False); (ROOT/'tmp').mkdir()
    shutil.copy2(Path(__file__), ROOT/'executed_source.py')
    cases = []
    for label, h in [('plus-full', .02), ('minus-full', -.02),
                     ('plus-half', .01), ('minus-half', -.01)]:
        folder = ROOT/label; folder.mkdir(); (folder/'scratch').mkdir()
        pos = x+h*q; audit = geometry_audit(pos, base)
        if not audit['passed']:
            raise ValueError('Displaced chemistry failed')
        save(folder/'input.json', dict(elements=base['elements'], geometry_bohr=pos.tolist(),
                                      step_bohr=h, geometry_audit=audit))
        cases.append(dict(label=label, input=pin(folder/'input.json')))
    sources = [*base['sources'], pin(CAMPAIGN/'stage1_completion_audit.json'),
               stage['final_binary_geometry'], pin(CAMPAIGN/'conditioned-directional-check-v1/plan.json'),
               *[item for row in refs for item in (row['result'], row['native'])],
               pin(REPO/'experiments/cpd_anti_additive/corrected_core_stage1.py'),
               pin(REPO/'experiments/cpd_anti_additive/audit_corrected_core_stage1.py')]
    save(ROOT/'plan.json', dict(at=now(), worker=pin(ROOT/'executed_source.py'), sources=sources,
        decision=pin(decision_path), authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),
        source_options=base_ref, options=base['options'], direction=q.tolist(),
        direction_reason='Reuse the previous conditioned-gradient direction to probe the same numerically sensitive direction under the original method; it is not claimed to be the softest mode.',
        reference_slopes_au=[row['slope_au'] for row in refs],
        reference_energy_spread_hartree=float(np.ptp([row['energy_hartree'] for row in refs])),
        cases=cases, hard_seconds=900, task_timeout_seconds=180, maximum_new_gradients=4,
        threads=4, memory_gib=4, psi4_version=base['psi4_version'], expected_seconds=260,
        completion_semantics='Acquisition and native verification only; numerical adequacy requires completion-triggered review. No automatic subsequent job.',
        review_policy='Compare absolute energy/gradient consistency, gradient- and energy-based curvature, step dependence and observed noise. If credible, admit a diagnostic Hessian chunk; retain noisy soft modes for targeted checks. A resolved contradiction requires a concrete method change, not endless tolerance sweeps.',
        minimum_certified=False, gate_effect='none'))
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
    samples = []
    for suffix, h in [('full', .02), ('half', .01)]:
        p, m = records['plus-'+suffix], records['minus-'+suffix]
        samples.append((h, p['energy_hartree'], m['energy_hartree'],
                        p['gradient_hartree_bohr'], m['gradient_hartree_bohr']))
    report = dict(at=now(), plan=pin(root/'plan.json'), results=pins,
        native_calculations_completed=4, native_evidence_verified=True,
        wall_seconds=sum(v['wall_seconds'] for v in records.values()),
        **summarize(plan['direction'], samples, plan['reference_slopes_au'],
                    plan['reference_energy_spread_hartree']))
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
        for case in plan['cases']:
            context(root)
            if deadline-time.time() < plan['task_timeout_seconds']+30:
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
        native_completed=len(completed)==4, numerical_adequacy='pending_completion_audit',
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
    unit = 'cpd-corrected-anti1-original-curvature-v1'; start = time.time()
    save(service/'watcher_config.json', dict(codex_executable=str(Path(shutil.which('codex')).resolve()),
        expected_seconds=plan['expected_seconds'], review_deadline_epoch=start+540,
        review_deadline_id='original-curvature-terminal-audit', self_test=False))
    save(service/'execution_plan.json', dict(unit=unit, thread=os.environ['CODEX_THREAD_ID'],
        command=[str(PYTHON), str(root/'executed_source.py'), 'run', str(root)], cwd=str(root),
        runtime_hours=.25, memory_gib=8, omp_threads=4, plan=pin(root/'plan.json'),
        completion_semantics=plan['completion_semantics']))
    save(root/'launch_receipt.json', dict(at=now(), deadline_epoch=start+900, unit=unit,
        prelaunch_memory=mem, execution_plan=pin(service/'execution_plan.json'),
        supervisor=pin(service/'supervisor.py'), watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G',
        '--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s',
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
