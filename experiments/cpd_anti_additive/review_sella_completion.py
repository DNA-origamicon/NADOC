"""Verify a completed Sella run against printed native gradients and trajectory."""

import argparse
import json
from pathlib import Path
import re
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from ase.io import read as read_atoms
from sella import Constraints
from experiments.cpd_anti_additive.sella_pilot import (
    BOHR, geometry_audit, now, projected_metrics, force_pass, save,
)
from experiments.cpd_anti_additive.validation_gate import checked, read, source


def review(root, service):
    output = root / 'completion_delivery_verified.json'
    if output.exists():
        raise FileExistsError('Preserve existing completion review')
    authorization = read(root / 'authorization.json')
    plan = read(checked(authorization['plan']))
    checked(authorization['worker'])
    checked(authorization['preflight'])
    for item in plan['sources'] + plan['runtime_sources']:
        checked(item)
    status = read(service / 'status.json')
    ack = read(service / 'completion_wake_ack.json')
    wake = read(service / 'completion_wake.json')
    assert status['state'] == 'complete' and status['returncode'] == 0
    assert ack['token'] == wake['token'] and ack['event'] == 'complete'
    assessment = read(root / 'assessment.json')
    rows = read(root / 'progress.json')['evaluations']
    assert len(rows) == assessment['evaluations'] == assessment['attempted_gradients'] == 20
    assert assessment['joint_optimizer_converged'] and assessment['minimum_certified'] is False
    graph = read(checked(plan['record']['model_graph']))
    trajectory = read_atoms(root / 'sella.traj', index=':')
    assert len(trajectory) == len(rows)
    verified = []
    for i, (row, frame) in enumerate(zip(rows, trajectory), 1):
        result = read(checked(row['result']))
        x = np.load(checked(result['geometry']))
        inputs = read(checked(result['input']))
        assert np.array_equal(x, inputs['geometry_bohr'])
        assert inputs['elements'] == plan['elements'] == frame.get_chemical_symbols()
        assert inputs['options'] == plan['options'] and inputs['method'] == plan['method']
        native_path = checked(result['native'])
        native = native_path.read_text()
        energies = [float(v) for v in re.findall(r'^\s*Total Energy\s*=\s*([-+\d.Ee]+)\s*\[Eh\]', native, re.M)]
        assert energies and abs(energies[-1]-result['energy']) < 1e-10
        table = native.rsplit('-Total Gradient:', 1)[1].split('*** tstop()', 1)[0]
        parsed = re.findall(r'^\s*(\d+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*$', table, re.M)
        assert [int(p[0]) for p in parsed] == list(range(1, len(x)+1))
        printed_gradient = np.array([[float(v) for v in p[1:]] for p in parsed])
        gradient = np.array(result['gradient'])
        gradient_difference = float(np.max(abs(gradient-printed_gradient)))
        assert gradient_difference < 6e-13
        response = [float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)', native)]
        assert response and max(response) <= 1e-10
        audit = geometry_audit(x, plan, graph)
        assert audit['chemistry_passed']
        trajectory_difference = float(np.max(abs(frame.positions/BOHR-x)))
        assert trajectory_difference < 1e-10
        verified.append(dict(evaluation=i, result=row['result'], native=source(native_path),
            native_gradient_max_rounding_difference=gradient_difference,
            response_max=max(response), torsion_error_deg=audit['torsion_error_deg'],
            trajectory_coordinate_difference_bohr=trajectory_difference))

    exported = read_atoms(root / 'optimized.xyz')
    assert exported.get_chemical_symbols() == plan['elements']
    export_difference = float(np.max(abs(exported.positions/BOHR-x)))
    assert export_difference < 1e-10
    projections = [projected_metrics(x, printed_gradient, plan['record']['torsion_indices'], h)
                   for h in (1e-4, 1e-5, 1e-6)]
    assert all(force_pass(m, plan['limits']) for m in projections) and audit['constraint_passed']
    constraint = Constraints(exported)
    constraint.fix_dihedral(tuple(plan['record']['torsion_indices']))
    normal = constraint.jacobian()[0].reshape(x.shape)
    projected = gradient-normal*np.sum(normal*gradient)/np.sum(normal**2)
    analytic_max = float(np.linalg.norm(projected, axis=1).max())
    assert abs(analytic_max-projections[1]['max_projected_atom_gradient']) < 1e-10
    convergence = read(root / 'convergence_checks.json')
    assert convergence[-1]['native_converged'] and convergence[-1]['independent_passed']
    assert not any(v['independent_passed'] for v in convergence[:-1])
    # Preserve the original reference frame and graph; never infer stereochemistry from a label.
    original = read(checked(plan['sources'][0]))
    reference = read_atoms(checked(original['seed_reference']))
    stereo_reference_plan = dict(plan, geometry_bohr=(reference.positions/BOHR).tolist())
    assert geometry_audit(x, stereo_reference_plan, graph)['chemistry_passed']
    report = dict(reviewed_at=now(), passed=True, token=ack['token'],
        event=ack['event'], claim='Constrained stationarity at the declared tolerances only',
        source=source(Path(__file__)), acknowledgement=source(service/'completion_wake_ack.json'),
        native_status=source(service/'status.json'), plan=source(root/'plan.json'),
        assessment=source(root/'assessment.json'), original_independent_review=source(root/'independent_review.json'),
        optimized=source(root/'optimized.xyz'), trajectory=source(root/'sella.traj'),
        convergence_checks=source(root/'convergence_checks.json'), evaluations=verified,
        elapsed_seconds=status['finished_at']-status['started_at'],
        energy_hartree=result['energy'], final_geometry_audit=audit,
        final_native_gradient_projection_checks=projections,
        sella_analytic_normal_max_gradient=analytic_max,
        export_coordinate_difference_bohr=export_difference,
        minimum_certified=False, simulation_ready=False, new_qm_evaluations=0,
        log_note='ASE logs before its convergence call; Sella caches the prior convergence tuple. The final printed fmax can lag one geometry. Current native gradient and convergence_checks determine this verdict.')
    save(output, report)
    save(service/'completion_delivery_verified.json', dict(acknowledgement=source(service/'completion_wake_ack.json'),
         scientific_review=source(output), received_event='complete', scientific_claim=report['claim'],
         minimum_certified=False, simulation_ready=False))
    print(json.dumps(dict(verified=len(verified), seconds=report['elapsed_seconds'],
        energy=report['energy_hartree'], projection=projections[1],
        torsion_error_deg=audit['torsion_error_deg'], minimum_certified=False), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('service', type=Path)
    args = parser.parse_args()
    review(args.root.resolve(), args.service.resolve())
