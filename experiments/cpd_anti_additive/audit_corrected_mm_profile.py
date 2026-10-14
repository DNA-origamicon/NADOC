"""Replay constrained MM evidence and diagnose conformer drift without new QM."""
from pathlib import Path
import importlib.util
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now


def audit(root):
    from ase import Atoms
    from ase.io.trajectory import Trajectory
    out = root / 'completion_audit.json'
    if out.exists():
        raise FileExistsError(out)
    service = root.parent / (root.name + '-service')
    status = read(service / 'status.json')
    ack = read(service / 'completion_wake_ack.json')
    assert ack['token'] == read(service / 'completion_wake.json')['token']
    assert ack['event'] == status['state'] == 'complete' and status['returncode'] == 0
    spec = importlib.util.spec_from_file_location('profile_frozen', root / 'executed_source.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    plan, model = m.context(root)
    top = read(root / 'assessment.json')
    assert top['error'] is None and len(top['completed']) == 5
    profile_path = root.parent / 'glycosidic-branch-profile-v1/completed_profile_review.json'
    definitions = read(profile_path)['torsion_definitions']
    keys = plan['fixture']['atom_keys']
    definitions = {name: [keys.index(k) for k in atoms] for name, atoms in definitions.items()}
    engine = m.Evaluator(checked(plan['system']))
    rows = []
    for point, ref in zip(plan['points'], top['completed'], strict=True):
        result = read(checked(ref))
        assert result['point'] == point and result['error'] is None and result['optimizer_converged']
        assert checked(result['plan']) == root / 'plan.json'
        x0 = np.load(checked(point['geometry'])) * m.BOHR
        x = np.load(checked(result['final_geometry']))
        history = dict(np.load(checked(result['evaluations'])))
        accepted = dict(np.load(checked(result['accepted'])))
        xyz = accepted['coordinates_angstrom']
        ids = accepted['evaluated_indices']
        assert len(xyz) == result['accepted_states'] and len(history['coordinates_angstrom']) == result['evaluated_states']
        assert np.array_equal(x, xyz[-1]) and np.array_equal(x0, xyz[0])
        assert np.array_equal(xyz, history['coordinates_angstrom'][ids])
        replay_error = 0.0
        for q, e, g in zip(history['coordinates_angstrom'], history['energies_kcal_mol'], history['gradients_kcal_A'], strict=True):
            re, rg, _ = engine.evaluate(q)
            replay_error = max(replay_error, abs(re-e), float(np.max(abs(rg-g))))
        assert replay_error < 1e-9
        trajectory = Trajectory(str(checked(result['native_trajectory'])))
        assert len(trajectory) == len(xyz)
        native_error = 0.0
        for frame, q, idx in zip(trajectory, xyz, ids, strict=True):
            assert np.array_equal(frame.positions, q)
            native_error = max(native_error,
                abs(frame.get_potential_energy()*m.EV_KCAL-history['energies_kcal_mol'][idx]),
                float(np.max(abs(-frame.get_forces(apply_constraint=False)*m.EV_KCAL-history['gradients_kcal_A'][idx]))))
        trajectory.close()
        assert native_error < 1e-9
        logrows = [line.split() for line in checked(result['native_log']).read_text().splitlines() if line.startswith('AuditedSella')]
        assert len(logrows) == len(xyz)
        assert all(abs(float(row[3])*m.EV_KCAL-history['energies_kcal_mol'][idx]) < 2e-5 for row, idx in zip(logrows, ids, strict=True))
        e, g, parts = engine.evaluate(x, True)
        e0, _, parts0 = engine.evaluate(x0, True)
        assert abs(e-result['energy_kcal_mol']) < 1e-9
        assert np.max(abs(g-np.load(checked(result['final_gradient'])))) < 1e-9
        assert all(abs(parts[k]-v) < 1e-9 for k, v in result['force_group_energies'].items())
        identity = m.audit_endpoint(x/m.BOHR, model)
        projection = m.projected_metrics(x, g, point['constraint']['indices'])
        constraints, _ = m.make_scan_constraints(Atoms(model['elements'], positions=x), point['constraint'], accepted_restart=True)
        analytic = np.asarray(constraints.jacobian()).reshape(x.shape)
        numeric = m.torsion_jacobian(x, point['constraint']['indices'])
        jacobian_error = float(np.max(abs(analytic-numeric)))
        assert jacobian_error < 1e-7
        tangent = g-analytic*np.sum(analytic*g)/np.sum(analytic*analytic)
        force = float(np.linalg.norm(tangent, axis=1).max())
        assert abs(force-projection['max_projected_atom_gradient_kcal_mol_angstrom']) < 1e-7
        assert identity['passed'] and force < .001
        angle_error = abs(m.wrapped(m.torsion(x, point['constraint']['indices'])-point['constraint']['target_degrees']))
        assert angle_error < .01
        match = m.descriptors(x0, x, plan['fixture'], plan['heavy_torsions'])
        assert match == result['conformer_descriptors']
        geometry = m.geometry_differences(x0, x, plan['fixture'])
        assert geometry == result['geometry_differences']
        named = {name: dict(reference_degrees=m.torsion(x0, atoms), final_degrees=m.torsion(x, atoms),
                 change_degrees=m.wrapped(m.torsion(x, atoms)-m.torsion(x0, atoms))) for name, atoms in definitions.items()}
        # Save actual accepted branch evolution; a 60-degree departure is a descriptive
        # marker for the large rotamer movement, not a new acceptance criterion.
        evolution = []
        for index, q in enumerate(xyz):
            evolution.append(dict(accepted_index=index, evaluated_index=int(ids[index]),
                energy_kcal_mol=float(history['energies_kcal_mol'][ids[index]]),
                torsions_degrees={name: m.torsion(q, atoms) for name, atoms in definitions.items()}))
        evpath = root / point['label'] / 'audited_branch_evolution.json'
        save(evpath, dict(at=now(),accepted_evolution=evolution))
        # Geometric contacts only; distances alone do not establish hydrogen bonding.
        contacts = []
        for donor in ["1:HO5'", "1:HO3'"]:
            for acceptor in ['1:O2', '1:O4', '2:O2', '2:O4']:
                a, b = keys.index(donor), keys.index(acceptor)
                contacts.append(dict(atoms=[donor,acceptor],reference_angstrom=float(np.linalg.norm(x0[a]-x0[b])),
                                     final_angstrom=float(np.linalg.norm(x[a]-x[b]))))
        rows.append(dict(offset_degrees=point['offset_degrees'],assessment=ref,
            evaluated_states_verified=len(history['energies_kcal_mol']), accepted_states_verified=len(xyz),
            replay_max_error=replay_error,native_trajectory_max_error=native_error,
            analytic_numeric_constraint_jacobian_max_error=jacobian_error,
            independently_constrained_stationary=True,identity=identity,projection=projection,angle_error_degrees=angle_error,
            geometry=geometry,conformer_descriptors=match,named_torsion_changes=named,
            energy_kcal_mol=e,qm_energy_hartree=point['qm_energy_hartree'],
            relaxation_energy_kcal_mol=e-e0,relaxation_force_group_changes={k:parts[k]-parts0[k] for k in parts},
            cap_oxygen_distances=contacts,accepted_evolution=pin(evpath)))
    engine.close()
    zero=next(row for row in rows if row['offset_degrees']==0)
    for row in rows:
        row['mixed_conformer_relative_mm_kcal_mol']=row['energy_kcal_mol']-zero['energy_kcal_mol']
        row['qm_relative_kcal_mol']=(row['qm_energy_hartree']-zero['qm_energy_hartree'])*m.EH
    save(out,dict(at=now(),source=pin(Path(__file__)),plan=pin(root/'plan.json'),
        status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),qm_profile=pin(profile_path),
        passed=True,native_evidence_passed=True,all_constrained_stationarity_passed=True,records=rows,
        matched_profile_accepted=False,minimum_certified=False,basin_closure_certified=False,
        decision='Reject mixed-conformer relaxed energies as a glycosidic fitting target. Stop this unchanged-parent scan. Advance a bounded core-only bonded response correction using the certified core and acquired ring training; preserve endpoint observations as transfer diagnostics. Recheck endpoint branches only after changing the deficient parent model.',
        rationale='All five historical descriptor checks fail. The middle three exhibit large exocyclic sugar rotations, with additional sugar-pucker/base changes. Geometry and force errors already exist in the isolated core. Fitting a glycosidic term to these mixed states would confound core and sugar/cap errors.',
        core_bonded_fit_design_admitted=True,relaxed_endpoint_fit_admitted=False,new_qm_admitted=False,
        parameter_fit_round_consumed=False,heldout_accessed=False,charge_transfer_validated=False,
        simulation_ready=False,cloud_spending_usd=0))
    print([dict(offset=r['offset_degrees'],force=r['projection']['max_projected_atom_gradient_kcal_mol_angstrom'],
                exocyclic_change=r['named_torsion_changes']['sugar_exocyclic']['change_degrees'],
                relaxation_components=r['relaxation_force_group_changes']) for r in rows])


if __name__ == '__main__':
    audit(Path(sys.argv[1]).resolve())
