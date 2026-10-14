"""Four bounded energy probes of the qualified corrected-core reference gradient."""
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
    checked, geometry_audit, now, pin, read, save,
)
from backend.parameterization.photoproduct_qm import parse_psi4_output

CAMPAIGN = (REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT = CAMPAIGN/'conditioned-directional-check-v1'
PYTHON = Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def directional_verdict(analytic, energies, limits):
    """Check both centered slopes and step halving without selecting a favorite."""
    if not np.isfinite(analytic) or abs(analytic) < 1e-5:
        raise ValueError('Reference slope too small for this relative-error diagnostic')
    slopes = [(p-m)/(2*h) for h, p, m in energies]
    if len(slopes) != 2 or not np.isfinite(slopes).all():
        raise ValueError('Two finite centered slopes are required')
    error_limit = max(limits['absolute_slope_error_au'],
                      limits['relative_slope_error']*abs(analytic))
    halving_limit = max(limits['absolute_slope_error_au'],
                        limits['relative_step_halving_difference']*abs(analytic))
    return dict(analytic_slope_au=analytic, centered_slopes_au=slopes,
                slope_errors_au=[abs(s-analytic) for s in slopes],
                slope_error_limit_au=error_limit,
                step_halving_difference_au=abs(slopes[0]-slopes[1]),
                step_halving_limit_au=halving_limit,
                passed=bool(all(abs(s-analytic) <= error_limit for s in slopes)
                            and abs(slopes[0]-slopes[1]) <= halving_limit))


def context(root):
    plan = read(root/'plan.json')
    receipt = read(root/'launch_receipt.json')
    execution = read(checked(receipt['execution_plan']))
    if checked(execution['plan']) != root/'plan.json':
        raise ValueError('Launched plan identity changed')
    for ref in plan['sources']:
        checked(ref)
    if checked(plan['worker']) != Path(__file__).resolve():
        raise ValueError('Frozen worker changed')
    qualification = read(checked(plan['qualification']))
    auth = read(checked(plan['authorization']))
    if (not qualification['passed'] or not auth['user_authorized'] or
            auth['compute_policy']['cloud_spending_usd'] != 0):
        raise ValueError('Qualification or campaign authorization missing')
    base = read(checked(plan['source_options']))
    if plan['options'] != {**base['options'], 'df_fitting_condition': 1e-7}:
        raise ValueError('Unreviewed numerical options')
    if plan['hard_seconds'] != 900 or len(plan['cases']) != 4:
        raise ValueError('Finite allocation changed')
    pause = CAMPAIGN/'pause.json'
    if pause.exists() and read(pause).get('paused'):
        raise RuntimeError('User paused campaign')
    return plan, base


def prepare():
    qualified = CAMPAIGN/'reference-conditioning-diagnostic-v2'
    review = read(qualified/'independent_review.json')
    if not review['passed']:
        raise ValueError('Gradient reproducibility did not qualify')
    base_ref = read(qualified/'plan.json')['source_options']
    base = read(checked(base_ref))
    reference_ref = next(row['result'] for row in review['rows'] if row['case'] == 'schema-2')
    ref = read(checked(reference_ref)); x = np.array(ref['returned_geometry_bohr'])
    gradient = np.array(ref['gradient']); direction = gradient/np.linalg.norm(gradient)
    ROOT.mkdir(exist_ok=False); (ROOT/'tmp').mkdir()
    shutil.copy2(Path(__file__), ROOT/'executed_source.py')
    cases = []
    for label, step in [('plus-full', .005), ('minus-full', -.005),
                        ('plus-half', .0025), ('minus-half', -.0025)]:
        folder = ROOT/label; folder.mkdir(); (folder/'scratch').mkdir()
        pos = x+step*direction
        audit = geometry_audit(pos, base)
        if not audit['passed']:
            raise ValueError('Displaced chemistry failed before QM')
        save(folder/'input.json', dict(elements=base['elements'], geometry_bohr=pos.tolist(),
                                      step_bohr=step, geometry_audit=audit))
        cases.append(dict(label=label, input=pin(folder/'input.json')))
    sources = [*base['sources'], pin(qualified/'independent_review.json'), reference_ref,
               pin(REPO/'experiments/cpd_anti_additive/corrected_core_stage1.py'),
               pin(REPO/'backend/parameterization/photoproduct_qm.py')]
    save(ROOT/'plan.json', dict(at=now(), worker=pin(ROOT/'executed_source.py'), sources=sources,
         authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),
         qualification=pin(qualified/'independent_review.json'), source_options=base_ref,
         reference_result=reference_ref, options=ref['options'], direction=direction.tolist(),
         analytic_slope_au=float(np.sum(gradient*direction)), cases=cases,
         limits=dict(absolute_slope_error_au=1e-6, relative_slope_error=.05,
                     relative_step_halving_difference=.02),
         hard_seconds=900, maximum_new_energies=4, maximum_new_gradients=0,
         task_timeout_seconds=180, threads=4, memory_gib=4, psi4_version=base['psi4_version'],
         scope='Local directional derivative consistency at one geometry and two fixed steps; not a global derivative proof, stationary point, Hessian, or minimum certificate.',
         reason='Changed auxiliary fitting numerics passed repeatability. Check energy/gradient agreement before investing in a fresh optimizer or Hessian. Reuse the existing reference gradient.',
         expected_seconds=4*review['wall_seconds']/3,
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
        raise ValueError('Psi4 changed')
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
    energy, wfn = psi4.energy('mp2', molecule=molecule, return_wfn=True)
    elapsed = time.monotonic()-start
    actual = np.asarray(wfn.molecule().geometry())
    if not np.isfinite(energy) or np.max(abs(actual-x)) > 1e-14:
        raise ValueError('Energy or coordinate-frame failure')
    if not geometry_audit(actual, base)['passed']:
        raise ValueError('Returned geometry changed chemistry')
    psi4.core.clean(); psi4.core.flush_outfile(); psi4.core.close_outfile()
    native = (folder/'output.dat').read_text()
    parsed = parse_psi4_output(native, 'single_point')['final_energy_hartree']
    if parsed is None or abs(parsed-energy) > 1e-9:
        raise ValueError('Native MP2 energy differs from returned value')
    if 'Energy and wave function converged.' not in native or 'Fitting Condition:        1E-07' not in native:
        raise ValueError('Native convergence/options evidence missing')
    save(folder/'result.json', dict(at=now(), input=case['input'], native=pin(folder/'output.dat'),
         energy_hartree=float(energy), native_energy_hartree=parsed,
         returned_geometry_bohr=actual.tolist(), wall_seconds=elapsed,
         psi4_version=psi4.__version__, scf_converged=True,
         mp2_response='Not applicable: energy-only evaluation', minimum_certified=False))


def review(root):
    plan, _ = context(root); records = {}; pins = []
    for c in plan['cases']:
        path = root/c['label']/'result.json'; result = read(path)
        if result['input'] != c['input']:
            raise ValueError('Input/result mismatch')
        checked(c['input']); native = checked(result['native']).read_text()
        parsed = parse_psi4_output(native, 'single_point')['final_energy_hartree']
        if parsed is None or abs(parsed-result['energy_hartree']) > 1e-9:
            raise ValueError('Native energy verification failed')
        records[c['label']] = result; pins.append(pin(path))
    energies = [(h, records['plus-'+suffix]['energy_hartree'], records['minus-'+suffix]['energy_hartree'])
                for suffix, h in [('full', .005), ('half', .0025)]]
    verdict = directional_verdict(plan['analytic_slope_au'], energies, plan['limits'])
    report = dict(at=now(), native_calculations_completed=4, new_gradients=0,
                  plan=pin(root/'plan.json'), results=pins, **verdict,
                  wall_seconds=sum(v['wall_seconds'] for v in records.values()),
                  minimum_certified=False, simulation_ready=False, scope=plan['scope'])
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
    completed = []; error = None; verdict = None
    try:
        for case in plan['cases']:
            context(root)
            if deadline-time.time() < plan['task_timeout_seconds']+30:
                raise RuntimeError('Insufficient time for another bounded energy task')
            folder = root/case['label']
            env = {**os.environ, 'PSI_SCRATCH':str(folder/'scratch'), 'TMPDIR':str(folder/'scratch')}
            with (folder/'runner.log').open('x') as log:
                result = subprocess.run([sys.executable, str(checked(plan['worker'])),
                    'worker', str(root), '--label', case['label']], stdout=log,
                    stderr=subprocess.STDOUT, env=env, cwd=folder,
                    timeout=plan['task_timeout_seconds'])
            if result.returncode:
                raise RuntimeError(f"Native task {case['label']} failed: {result.returncode}")
            completed.append(pin(folder/'result.json'))
            save(root/'progress.json', dict(completed=completed, at=now()))
        verdict = review(root)
    except Exception as exc:
        error = repr(exc)
        (root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json', dict(at=now(), error=error, completed=len(completed),
         native_completed=len(completed)==4, derivative_consistency_pass=False if verdict is None else verdict['passed'],
         review=None if verdict is None else pin(root/'independent_review.json'), minimum_certified=False))
    return 1 if error or verdict is None or not verdict['passed'] else 0


def launch():
    root = ROOT; plan = read(root/'plan.json')
    for ref in plan['sources']:
        checked(ref)
    checked(plan['worker'])
    pause = CAMPAIGN/'pause.json'
    if pause.exists() and read(pause).get('paused'):
        raise RuntimeError('Campaign paused')
    units = subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'], text=True)
    if any('cpd-' in line for line in units.splitlines()):
        raise RuntimeError('A CPD service is still active')
    if subprocess.run(['pgrep','-x','namd3'], capture_output=True).returncode == 0:
        raise RuntimeError('NAMD is active')
    mem = {line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()
           if line.startswith(('MemAvailable:', 'SwapFree:'))}
    if mem['MemAvailable'] < 12*1024**3 or shutil.disk_usage(root).free < 30*1024**3:
        raise RuntimeError('Insufficient RAM or Archive headroom')
    service = CAMPAIGN/(root.name+'-service'); service.mkdir(exist_ok=False)
    for old, new in [('launch.py','supervisor.py'), ('watch.py','watcher.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/old, service/new)
    unit = 'cpd-corrected-anti1-conditioned-directional-v1'; start = time.time()
    save(service/'watcher_config.json', dict(codex_executable=str(Path(shutil.which('codex')).resolve()),
         expected_seconds=plan['expected_seconds'], review_deadline_epoch=start+540,
         review_deadline_id='conditioned-directional-terminal-audit', self_test=False))
    save(service/'execution_plan.json', dict(unit=unit, thread=os.environ['CODEX_THREAD_ID'],
         command=[str(PYTHON), str(root/'executed_source.py'), 'run', str(root)], cwd=str(root),
         runtime_hours=.25, memory_gib=8, omp_threads=4, plan=pin(root/'plan.json'),
         completion_semantics='Four energy probes only. Review fixed derivative criteria before any optimization. No minimum certification or cloud spending.'))
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
        print(review(root)['passed'])
    else:
        globals()[args.action]()
