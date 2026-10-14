"""Recompute the first corrected-core charge fit without another optimization."""
from pathlib import Path
import importlib.util
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now


def audit(root):
    output = root / 'completion_audit.json'
    if output.exists():
        raise FileExistsError(output)
    service = root.parent / (root.name + '-service')
    status = read(service / 'status.json')
    ack = read(service / 'completion_wake_ack.json')
    assert ack['token'] == read(service / 'completion_wake.json')['token']
    assert ack['event'] == status['state'] == 'complete' and status['returncode'] == 0
    spec = importlib.util.spec_from_file_location('frozen_fit', root / 'executed_source.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = module.context(root)
    metadata, arrays = module.load_data(root)
    result = read(root / 'assessment.json')
    candidate = read(checked(result['candidate']))
    assert checked(result['plan']) == root / 'plan.json'
    policy = read(checked(candidate['policy']))
    assert checked(candidate['dataset']) == root / 'dataset.json'
    keys = metadata['atom_keys']
    charge = np.array([candidate['charges_e'][key] for key in keys])
    initial = np.array([row['charge_e'] for row in policy['baseline_assignments']])
    assert [row['atom'] for row in policy['baseline_assignments']] == keys
    assert np.array_equal(initial, arrays['q0'])
    shifts = np.array([candidate['variable_group_shifts_e'][group[0][2:]]
                       for group in metadata['variable_groups']])
    assert np.max(abs(charge - initial - arrays['mapping'] @ shifts)) < 1e-14
    assert abs(shifts.sum()) < 1e-12 and np.max(abs(shifts)) <= .15 + 1e-12
    assert abs(charge.sum()) < 1e-12
    for residue in (1, 2):
        caps = [i for i, k in enumerate(keys) if k.startswith(f'{residue}:')
                and k.split(':')[1] in ('CM', 'HCM1', 'HCM2', 'HCM3')]
        base = [i for i, k in enumerate(keys) if k.startswith(f'{residue}:') and i not in caps]
        assert len(caps) == 4 and len(base) == 14
        assert abs(charge[caps].sum()) < 1e-12 and abs(charge[base].sum()) < 1e-12
        assert np.array_equal(charge[caps], initial[caps])
    fixed = np.where(~arrays['mapping'].any(axis=1))[0]
    assert len(fixed) == 16 and np.array_equal(charge[fixed], initial[fixed])
    assert all(charge[keys.index(a)] == charge[keys.index(b)]
               for a, b in metadata['variable_groups'])
    assert np.max(abs(arrays['xyz'] - np.load(checked(metadata['source_geometry']))
                      * .52917721067)) < 1e-14

    # Reconstruct all interactions directly from geometry, charges and LJ,
    # independently of the saved linear rows and the fit's minimum helper.
    water_charge = np.array([-.834, .417, .417])
    curves = []
    reconstructed_grids = []
    for index, target in enumerate(metadata['curves']):
        energies = []
        for water in arrays['waters'][index]:
            total = 0.
            for i, position in enumerate(arrays['xyz']):
                for j, water_position in enumerate(water):
                    distance = np.linalg.norm(position - water_position)
                    epsilon = np.sqrt(abs(arrays['model_lj'][i, 0] * arrays['water_lj'][j, 0]))
                    radius = arrays['model_lj'][i, 1] + arrays['water_lj'][j, 1]
                    sixth = (radius / distance) ** 6
                    total += 332.063713299 * charge[i] * water_charge[j] / distance
                    total += epsilon * (sixth ** 2 - 2 * sixth)
            energies.append(total)
        energies = np.array(energies)
        assert np.max(abs(energies - (arrays['rows'][index] @ charge
                                     + arrays['lj_energy'][index]))) < 1e-8
        reconstructed_grids.append(energies)
        k = int(np.argmin(energies))
        assert 0 < k < len(energies) - 1
        h = arrays['mm_distances'][k + 1] - arrays['mm_distances'][k]
        curvature = (energies[k - 1] + energies[k + 1] - 2 * energies[k]) / h**2
        slope = (energies[k + 1] - energies[k - 1]) / (2 * h)
        assert curvature > 0
        offset = -slope / curvature
        assert abs(offset) < h
        distance = arrays['mm_distances'][k] + offset
        energy = energies[k] + slope * offset + .5 * curvature * offset**2
        de = float(energy - target['target_energy_kcal_mol'])
        dr = float(distance - target['target_distance_angstrom'])
        stored = result['metrics']['water'][index]
        assert abs(de - stored['energy_error_kcal_mol']) < 1e-9
        assert abs(dr - stored['distance_error_angstrom']) < 1e-9
        assert abs(de) <= .5 and abs(dr) <= .2 and stored['bracketed']
        curves.append(dict(site=target['site'],energy_error_kcal_mol=de,
                           distance_error_angstrom=dr,bracketed=True))
    dipole = charge @ arrays['xyz'] * (2.541746473 / .52917721067)
    dipole_error = dipole - arrays['dipole_target']
    esp_error = arrays['esp_matrix'] @ charge - arrays['esp_values']
    objective_blocks = dict(
        water_energy=float(np.mean([(r['energy_error_kcal_mol'] / .2)**2 for r in curves])),
        water_distance=float(np.mean([(r['distance_error_angstrom'] / .1)**2 for r in curves])),
        dipole=float(np.mean((dipole_error / .5)**2)),
        charge_restraint=float(.2 * np.mean((shifts / .1)**2)))
    assert abs(sum(objective_blocks.values()) - result['objective']) < 1e-9
    native = read(root / 'fitted_openmm_check.json')
    assert native['passed'] and native['platform'] == 'Reference' and len(native['records']) == 6
    errors = []
    for index, record in enumerate(native['records']):
        target = metadata['curves'][index]
        assert record['site'] == target['site'] and record['charge_case'] == 'fitted'
        k = np.argmin(abs(arrays['mm_distances'] - target['target_distance_angstrom']))
        error = abs(record['native_kcal_mol'] - reconstructed_grids[index][k])
        assert error < 1e-5
        errors.append(float(error))
    identity = module.identifiability(shifts, metadata, arrays)
    assert np.allclose(identity['weighted_data_jacobian_singular_values'],
                       result['identifiability']['weighted_data_jacobian_singular_values'])
    assert result['optimizer_success'] and result['constraints_passed']
    assert result['water_development_limits_passed']
    data = dict(at=now(), source=pin(Path(__file__)), passed=True,
                status=pin(service/'status.json'), acknowledgement=pin(service/'completion_wake_ack.json'),
                plan=pin(root/'plan.json'), candidate=pin(root/'candidate_charges.json'),
                assessment=pin(root/'assessment.json'), native_check=pin(root/'fitted_openmm_check.json'),
                source_pins_verified=True, independent_grid_points=6*196,
                constraints_passed=True, core_water_development_limits_passed=True,
                curves=curves, objective_blocks=objective_blocks,
                dipole_vector_error_debye=float(np.linalg.norm(dipole_error)),
                esp_relative_rmse=float(np.linalg.norm(esp_error)/np.linalg.norm(arrays['esp_values'])),
                maximum_native_reconstruction_error_kcal_mol=max(errors),
                native_check_scope='Saved OpenMM Reference cross-fragment energies at target-nearest grid points; these are not minimum energies or bonded/NAMD checks.',
                identifiability=identity,
                active_bounds=[group[0][2:] for group, d in zip(metadata['variable_groups'], shifts) if abs(d) >= .15-1e-8],
                optimizer_success=True, service_seconds=status['finished_at']-status['started_at'],
                decision='Stop core charge fitting after round one; retain this bounded candidate for development. Check unchanged charge transfer at two existing sugar endpoint conformers before considering a second fit or bonded-model completion.',
                limitations='O4 is at the +0.15e bound; charge information is poorly conditioned and ESP relative RMSE remains substantial. No uniqueness, transfer, full parameter-set acceptance or minimum certification follows from the fit.',
                second_fit_admitted=False, transfer_diagnostic_admitted=True,
                core_charge_candidate_admitted_for_development=True,
                charge_transfer_validated=False, full_parameter_hash_lock=False,
                heldout_accessed=False, minimum_certified=False, simulation_ready=False,
                cloud_spending_usd=0)
    save(output, data)
    print({k:data[k] for k in ('passed','objective_blocks','dipole_vector_error_debye','esp_relative_rmse','active_bounds')})


if __name__ == '__main__':
    audit(Path(sys.argv[1]).resolve())
