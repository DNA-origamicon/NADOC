"""Independently replay native tables and all checkpoints after stage one."""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path
import re
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    BOHR, checked, metrics, now, pin, read, save, stationary,
)


def parse_native_table(native, count):
    if '-Total Gradient:' not in native:
        raise ValueError('Native total gradient table absent')
    section = native.rsplit('-Total Gradient:', 1)[1]
    rows = re.findall(r'^\s*(\d+)\s+([-\d.E+]+)\s+([-\d.E+]+)\s+([-\d.E+]+)\s*$', section, re.M)
    if [int(row[0]) for row in rows] != list(range(1, count+1)):
        raise ValueError('Native gradient atom rows incomplete or out of order')
    energies = re.findall(r'(?m)^\s*Total Energy\s*=\s*([-\d.]+)\s*\[Eh\]', native)
    if len(energies) != 1:
        raise ValueError('Native MP2 energy missing or ambiguous')
    gradient = np.array([[float(v) for v in row[1:]] for row in rows])
    if not np.isfinite(gradient).all():
        raise ValueError('Nonfinite native gradient')
    return float(energies[0]), gradient


def load_xyz(path, expected_elements):
    lines = path.read_text().splitlines()
    rows = [line.split() for line in lines[2:] if line.strip()]
    if int(lines[0]) != len(expected_elements) or [r[0] for r in rows] != expected_elements:
        raise ValueError('XYZ atom count/order changed')
    return np.array([[float(v) for v in row[1:]] for row in rows])/BOHR


def audit(root, output):
    if output.exists():
        raise FileExistsError('Refuse to overwrite completion evidence')
    opt = root/'optimization'
    service = root/'optimization-service'
    auth = read(opt/'authorization.json')
    worker = checked(auth['worker'])
    spec = importlib.util.spec_from_file_location('frozen_worker', worker)
    frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    plan = frozen.validate(opt)
    status = read(service/'status.json')
    outcome = read(opt/'assessment.json')
    if (status['state'] != 'complete' or status['returncode'] != 0 or
            outcome['error'] is not None or not outcome['optimizer_converged']):
        raise ValueError('Native optimizer did not complete successfully')
    service_seconds = status['finished_at'] - status['started_at']
    if service_seconds >= 14400 or outcome['new_gradients'] > 60:
        raise ValueError('Approved optimization allocation exceeded')
    progress = read(opt/'progress.json')
    if sum(not r.get('reused',False) for r in progress['evaluations']) != outcome['new_gradients']:
        raise ValueError('Gradient accounting mismatch')
    evaluations, geometries = [], []
    for row in progress['evaluations']:
        result = read(checked(row['result']))
        inp = read(checked(result['input']))
        x = np.load(checked(result['geometry']))
        if not np.array_equal(x, np.asarray(inp['geometry_bohr'])):
            raise ValueError('Saved input/evaluated coordinate mismatch')
        if (inp['options'] != plan['options'] or inp['method'] != 'mp2' or
                inp['charge'] != 0 or inp['multiplicity'] != 1):
            raise ValueError('QM method or state changed')
        native = checked(result['native']).read_text()
        convergence = frozen.native_audit(native,result['energy_hartree'],result['gradient_hartree_bohr'])
        energy, gradient = parse_native_table(native,len(x))
        error = float(np.max(abs(gradient-np.array(result['gradient_hartree_bohr']))))
        if error > 1e-11 or abs(energy-result['energy_hartree']) > 1e-9:
            raise ValueError('Saved energy/gradient differs from native output')
        identity = frozen.geometry_audit(x,plan)
        if not identity['passed']:
            raise ValueError('Corrected product geometry failed')
        if not Path(result['scratch_path']).resolve().is_relative_to(root):
            raise ValueError('Native scratch escaped campaign Archive root')
        geometries.append(x)
        evaluations.append(dict(result=row['result'],native=result['native'],input=result['input'],
             geometry=result['geometry'],reused=row.get('reused',False),energy_hartree=energy,
             native_gradient_max_difference_au=error,native_convergence=convergence,
             identity=identity,wall_seconds=result['wall_seconds'],peak_rss_bytes=result['peak_rss_bytes']))
    checkpoints=[]
    for path in sorted(opt.glob('accepted-*.xyz')):
        x=load_xyz(path,plan['elements'])
        matches=[i for i,g in enumerate(geometries) if np.allclose(x,g,atol=1e-11,rtol=0)]
        if not matches or not frozen.geometry_audit(x,plan)['passed']:
            raise ValueError('Accepted checkpoint has no audited native evaluation')
        checkpoints.append(dict(geometry=pin(path),evaluated_source=evaluations[matches[-1]]['result']))
    from ase.io import read as ase_read
    frames=ase_read(opt/'sella.traj',index=':')
    for frame in frames:
        if frame.get_chemical_symbols() != plan['elements']:
            raise ValueError('Optimizer trajectory element order changed')
        x=frame.positions/BOHR
        if (not frozen.geometry_audit(x,plan)['passed'] or
                not any(np.allclose(x,g,atol=1e-10,rtol=0) for g in geometries)):
            raise ValueError('Optimizer trajectory contains unverified geometry')
    final=load_xyz(opt/'optimized.xyz',plan['elements'])
    if not np.allclose(final,geometries[-1],atol=1e-11,rtol=0):
        raise ValueError('Final geometry is not final evaluated geometry')
    restart=read(opt/'restart_checkpoint.json')
    if (restart['evaluated_source'] != evaluations[-1]['result'] or
            not np.allclose(load_xyz(checked(restart['geometry']),plan['elements']),final,atol=1e-11,rtol=0)):
        raise ValueError('Final restart checkpoint differs from optimized geometry')
    final_metrics=metrics(np.array(read(checked(evaluations[-1]['result']))['gradient_hartree_bohr']))
    if not stationary(final_metrics) or not read(opt/'latest_convergence.json')['native_converged']:
        raise ValueError('Native or independently recomputed stationarity failed')
    initial_failure=read(root/'pilot_startup_failure_audit.json')
    checked(initial_failure['status_source']);checked(initial_failure['traceback'])
    durations=[r['wall_seconds'] for r in evaluations if not r['reused']]
    report=dict(schema='nadoc.corrected-core-stage1-completion.v1',at=now(),passed=True,
         status='passed_corrected_identity_and_unconstrained_stationarity',gate_effect='none',
         audit_script=pin(Path(__file__)),frozen_worker=pin(worker),authorization=pin(opt/'authorization.json'),
         plan=pin(opt/'plan.json'),native_status=pin(service/'status.json'),assessment=pin(opt/'assessment.json'),
         source_independent_review=pin(opt/'independent_review.json'),
         new_gradients=len(durations),total_evaluations_including_reused_pilot=len(evaluations),
         native_table_components_verified=sum(np.array(g).size for g in geometries),
         evaluations=evaluations,accepted_checkpoints=checkpoints,ase_trajectory_frames=len(frames),
         ase_trajectory=pin(opt/'sella.traj'),optimizer_log=pin(opt/'sella.log'),
         optimizer_service_seconds=service_seconds,optimizer_process_seconds=outcome['wall_seconds'],
         all_native_gradient_seconds=sum(r['wall_seconds'] for r in evaluations),
         peak_process_rss_bytes=outcome['peak_rss_bytes'],
         gradient_seconds=dict(minimum=min(durations),median=float(np.median(durations)),
                               maximum=max(durations),mean=float(np.mean(durations))),
         optimized_xyz=pin(opt/'optimized.xyz'),final_binary_geometry=evaluations[-1]['geometry'],
         final_result=evaluations[-1]['result'],final_metrics=final_metrics,
         restart=pin(opt/'restart_checkpoint.json'),
         preserved_startup_failure=pin(root/'pilot_startup_failure_audit.json'),
         minimum_certified=False,simulation_ready=False,
         claim='Corrected stationary candidate at the specified MP2 method. No Hessian or harmonic-minimum certification.',
         next_action='Prepare finite Hessian schedule for approval; no later compute launched.')
    save(output,report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=audit(args.root.resolve(),args.output.resolve())
    print({k:report[k] for k in ['passed','new_gradients','native_table_components_verified',
                               'ase_trajectory_frames','optimizer_service_seconds','final_metrics']})
