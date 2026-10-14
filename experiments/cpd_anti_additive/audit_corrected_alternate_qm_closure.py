"""Replay native fixed-core QM closure evidence before admitting continuation."""
from pathlib import Path
import importlib.util
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now
from experiments.cpd_anti_additive.corrected_bonded_baseline import EH
from experiments.cpd_anti_additive.corrected_mm_endpoint_profile import descriptors, heavy_torsions
from experiments.cpd_anti_additive.endpoint_native import audit_native


def audit(root):
    from ase import Atoms
    from ase.io.trajectory import Trajectory
    out = root / 'completion_audit.json'
    if out.exists():
        raise FileExistsError(out)
    service = root.with_name(root.name + '-service')
    status = read(service / 'status.json')
    ack = read(service / 'completion_wake_ack.json')
    assert ack['token'] == read(service / 'completion_wake.json')['token']
    assert ack['event'] == status['state'] == 'complete' and status['returncode'] == 0
    spec = importlib.util.spec_from_file_location('closure_frozen', root / 'executed_source.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    p, model = m.context(root)
    assessment = read(root / 'assessment.json')
    history = read(root / 'progress.json')
    assert assessment['error'] is None
    rows = history['evaluations']
    assert rows[0]['reused'] and rows[0]['result'] == p['seed_result']
    assert all(row['state'] == 'complete' for row in rows)
    assert len(rows) - 1 == assessment['completed_new_gradients'] == history['attempts']
    assert assessment['attempts'] == history['attempts'] <= p['max_new_gradients']
    reference = read(checked(p['reference_result']))
    xr = np.load(checked(p['reference_geometry']))
    assert reference['geometry'] == p['reference_geometry']
    er, gr, refnative = audit_native(checked(reference['native']).read_text(), model['elements'], xr)
    assert abs(er - reference['energy_hartree']) < 1e-9
    assert np.max(abs(gr - np.array(reference['gradient_hartree_bohr']))) < 1e-11
    original = read(checked(p['native_template']))
    boundary = read(root.parent / 'fixed-core-boundary-v1/plan.json')
    fixture = boundary['fixture']
    assert fixture['model'] == p['model']
    torsion_defs = boundary['named_torsions']
    records = []
    cache = {}
    for row in rows:
        resultpath = checked(row['result'])
        result = read(resultpath)
        raw = read(resultpath.with_name('raw_result.json'))
        inp = read(checked(result['input']))
        assert inp['options'] == original['options']
        assert (inp['method'], inp['charge'], inp['multiplicity']) == ('mp2', 0, 1)
        assert inp['elements'] == model['elements']
        x = np.load(checked(result['geometry']))
        g = np.load(checked(result['gradient_binary']))
        assert np.array_equal(x, np.array(inp['geometry_bohr']))
        assert np.max(abs(x - np.load(checked(result['returned_geometry'])))) < 1e-14
        assert np.array_equal(g, np.array(result['gradient_hartree_bohr']))
        assert np.array_equal(g, np.array(raw['gradient_hartree_bohr']))
        assert result['energy_hartree'] == raw['energy_hartree']
        if not row.get('reused'):
            trial = read(checked(row['native_plan']))
            for source in trial['sources']:
                checked(source)
            assert trial['worker'] == p['native_worker'] and trial['options'] == original['options']
            assert trial['parent_optimization_plan'] == pin(root / 'plan.json')
            assert trial['geometry'] == result['geometry'] and trial['input'] == result['input']
            assert trial['model'] == p['model']
        e, ng, native = audit_native(checked(result['native']).read_text(), model['elements'], x)
        assert abs(e - result['energy_hartree']) < 1e-9 and np.max(abs(ng - g)) < 5.1e-13
        identity = m.audit_endpoint(x, model)
        assert identity['passed']
        checks = m.geometry_constraints(x, xr, p['fixed_indices'], p['constraint'])
        atoms = Atoms(model['elements'], positions=x * m.BOHR)
        constraints, configuration = m.constraints_for(atoms, xr, p['fixed_indices'], p['constraint'])
        jac = np.array(constraints.jacobian())
        _, singular, v = np.linalg.svd(jac, full_matrices=True)
        assert np.count_nonzero(singular > 1e-8) == 97
        q = v[97:].T
        analytic = (q @ (q.T @ g.ravel())).reshape(g.shape)
        projected = m.free_projection(x * m.BOHR, g, p['fixed_indices'], p['constraint']['indices'])
        projection_error = float(np.max(abs(analytic - projected)))
        assert projection_error < 1e-9
        norms = np.linalg.norm(analytic[p['free_indices']], axis=1)
        maximum = float(norms.max())
        rms = float(np.sqrt(np.mean(norms ** 2)))
        assert abs(maximum - row['stationarity']['max_free_projected_atom_gradient_au']) < 1e-9
        assert abs(rms - row['stationarity']['rms_free_projected_atom_gradient_au']) < 1e-9
        stationary = maximum < 1.5e-5 and rms < 1e-5
        assert stationary == row['stationarity']['passed']
        record = dict(source=row['result'], reused=bool(row.get('reused')), geometry=result['geometry'],
            gradient=result['gradient_binary'], native=result['native'], energy_hartree=result['energy_hartree'],
            relative_to_original_qm_kcal_mol=(result['energy_hartree'] - reference['energy_hartree']) * EH,
            max_free_projected_atom_gradient_au=maximum, rms_free_projected_atom_gradient_au=rms,
            max_free_projected_atom_gradient_kcal_mol_A=maximum * EH / m.BOHR,
            rms_free_projected_atom_gradient_kcal_mol_A=rms * EH / m.BOHR,
            independent_projection_error_au=projection_error, stationarity_passed=stationary,
            geometry_checks=checks, identity=identity, native_audit=native, native_seconds=result['wall_seconds'],
            torsions_degrees={name:m.torsion(x, [model['atom_keys'].index(k) for k in keys])
                             for name, keys in torsion_defs.items()})
        records.append(record)
        cache[str(resultpath)] = (record, x, g)
    accepted = history['accepted']
    assert len(accepted) == assessment['accepted_states']
    trajectory = Trajectory(str(root / 'sella.traj'))
    assert len(trajectory) == len(accepted)
    accepted_records = []
    for step, (saved, frame) in enumerate(zip(accepted, trajectory, strict=True)):
        resultpath = checked(saved['evaluated_source'])
        record, x, g = cache[str(resultpath)]
        assert saved['step'] == step
        assert saved['geometry'] == record['geometry'] and saved['gradient'] == record['gradient']
        assert np.max(abs(frame.positions / m.BOHR - x)) < 1e-12
        assert frame.get_chemical_symbols() == model['elements']
        assert abs(frame.get_potential_energy() / m.HARTREE_EV - record['energy_hartree']) < 1e-9
        assert np.max(abs(-frame.get_forces(apply_constraint=False) / m.FORCE_FACTOR - g)) < 1e-12
        accepted_records.append(record)
    trajectory.close()
    log = [line.split() for line in (root / 'sella.log').read_text().splitlines() if line.startswith('AuditedSella')]
    assert len(log) == len(accepted)
    for step, (line, record) in enumerate(zip(log, accepted_records, strict=True)):
        assert int(line[1]) == step
        assert abs(float(line[3]) - record['energy_hartree'] * m.HARTREE_EV) < 5.1e-7
    final = accepted_records[-1]
    assert accepted[-1] == assessment['last_accepted']
    checkpoint = read(root / 'restart_checkpoint.json')
    assert all(checkpoint[k] == value for k, value in accepted[-1].items())
    assert not checkpoint['optimizer_state_restorable']
    convergence = read(root / 'latest_convergence.json')
    assert convergence['stationarity']['passed'] == final['stationarity_passed']
    assert assessment['optimizer_converged'] == (convergence['native_converged'] and final['stationarity_passed'])
    xfinal = cache[str(checked(final['source']))][1]
    xseed = cache[str(checked(records[0]['source']))][1]
    first = accepted_records[0]
    recent = accepted_records[-5:]
    recent_reduction = 1 - final['max_free_projected_atom_gradient_au'] / recent[0]['max_free_projected_atom_gradient_au']
    progress = dict(force_reduction_factor=first['max_free_projected_atom_gradient_au'] / final['max_free_projected_atom_gradient_au'],
        energy_change_kcal_mol=(final['energy_hartree'] - first['energy_hartree']) * EH,
        last_five_force_reduction_fraction=recent_reduction,
        last_five_energy_change_kcal_mol=(final['energy_hartree'] - recent[0]['energy_hartree']) * EH,
        maximum_force_limit_ratio=final['max_free_projected_atom_gradient_au'] / 1.5e-5,
        rms_force_limit_ratio=final['rms_free_projected_atom_gradient_au'] / 1e-5,
        uphill_accepted_energy_changes_kcal_mol=[(b['energy_hartree']-a['energy_hartree'])*EH
            for a,b in zip(accepted_records,accepted_records[1:]) if b['energy_hartree']>a['energy_hartree']])
    seconds = [record['native_seconds'] for record in records if not record['reused']]
    continuation = bool(not final['stationarity_passed'] and recent_reduction > .5
                        and progress['energy_change_kcal_mol'] < 0 and max(seconds) < 600)
    report = dict(at=now(), source=pin(Path(__file__)), plan=pin(root/'plan.json'),
        status=pin(service/'status.json'), acknowledgement=pin(service/'completion_wake_ack.json'),
        progress_source=pin(root/'progress.json'), assessment=pin(root/'assessment.json'),
        native_trajectory=pin(root/'sella.traj'), native_log=pin(root/'sella.log'),
        passed=True, native_evidence_passed=True, evaluated_states=len(records), accepted_states=len(accepted),
        new_gradients=len(seconds), records=records, reference_native=refnative, torsion_definitions=torsion_defs,
        last_accepted_result=final['source'], final=final, progress=progress,
        final_descriptors_vs_original=descriptors(xr*m.BOHR,xfinal*m.BOHR,fixture,heavy_torsions(fixture)),
        final_descriptors_vs_alternate_seed=descriptors(xseed*m.BOHR,xfinal*m.BOHR,fixture,heavy_torsions(fixture)),
        mean_gradient_seconds=float(np.mean(seconds)), maximum_gradient_seconds=max(seconds),
        service_seconds=status['finished_at']-status['started_at'],
        maximum_evaluated_fixed_drift_A=max(record['geometry_checks']['maximum_fixed_drift_A'] for record in records),
        maximum_evaluated_chi_error_degrees=max(record['geometry_checks']['chi_error_degrees'] for record in records),
        planned_boundary=assessment['planned_boundary'], optimizer_converged=assessment['optimizer_converged'],
        constrained_stationary=final['stationarity_passed'], continuation_admitted=continuation,
        continuation_reason='Strong recent force reduction and stable native cost justify one more bounded chunk from the last accepted state. Reuse its full-precision gradient and exact original fixed/chi targets, with fresh optimizer history. Audit again at convergence or the allocation boundary.',
        alternatives='Do not repeat the seed gradient, lower electronic tolerances, fit to an unconverged point, expand the scan or compute an endpoint Hessian now. No optimizer Hessian restart was saved; retain exact native geometry/gradient and use the established Sella restart method.',
        continuation_max_new_gradients=12, continuation_hard_seconds=3600, task_timeout_seconds=600,
        interpretation='The alternate branch has an observed QM energy below the original reference under the same electronic model and fixed-core/chi conditions within recorded constraint tolerances. This is not a converged relative basin energy, a minimum certificate, a barrier, or proof of global basin closure.',
        new_fit_admitted=False, heldout_accessed=False, minimum_certified=False,
        basin_closure_certified=False, simulation_ready=False, cloud_spending_usd=0)
    save(out, report)
    print(dict(passed=True, new_gradients=len(seconds), accepted_states=len(accepted), progress=progress,
        final_energy_relative=final['relative_to_original_qm_kcal_mol'],
        projected_gradient_kcal_A=final['max_free_projected_atom_gradient_kcal_mol_A'],
        original_heavy_rmsd=report['final_descriptors_vs_original']['heavy_atom_rmsd_angstrom'],
        seed_heavy_rmsd=report['final_descriptors_vs_alternate_seed']['heavy_atom_rmsd_angstrom'],
        final_torsions=final['torsions_degrees'], continuation_admitted=continuation))


if __name__ == '__main__':
    audit(Path(sys.argv[1]).resolve())
