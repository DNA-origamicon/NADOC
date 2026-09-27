"""Recompute fitted water minima from native probe geometries, without fit matrices."""

import json
from pathlib import Path
import sys
import warnings

import numpy as np
from openmm import app
from scipy.optimize import minimize_scalar

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require, STATE
from experiments.cpd_anti_additive.validation_gate import checked, read, source
from experiments.cpd_published_comparator.reconstruct import BASE, FF
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_nonbonded_fit import _interaction_row

ART = REPO / '.development-artifacts'


def review():
    require('electrostatics')
    receipt = read(STATE/'electrostatics_inputs.json')
    dataset = read(checked(receipt['dataset']))
    fitpath = ART/'cpd-anti-charge-minima-fit-v2/assessment.json'
    fit = read(fitpath)
    assert fit['dataset'] == receipt['dataset'] and fit['optimizer_success']
    output = fitpath.parent/'independent_review.json'
    if output.exists():
        raise FileExistsError(output)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params = app.CharmmParameterSet(str(BASE/'top_all36_na.rtf'), str(BASE/'par_all36_na.prm'),
            str(FF/'top_all36_cgenff.rtf'), str(FF/'par_all36_cgenff.prm'),
            str(ART/'cpd-published-comparator-v1/comparator_last.prm'))
    nb = {k: dict(epsilon_kcal_mol=v.epsilon, rmin_half_angstrom=v.rmin)
          for k, v in params.atom_types_str.items()}
    jobs = [read(checked(s)) for s in dataset['sources'] if Path(s['path']).name == 'job_manifest.json']
    records = []
    for case, result in zip(dataset['cases'], fit['records']):
        assert case['id'] == result['id'] and case['names'] == result['names']
        xyz = np.array(case['xyz_A'])
        q = np.array(result['charges_e'])
        shifts = np.array([fit['charge_shifts_e'].get(n, 0) for n in case['names']])
        assert np.max(abs(q-np.array(case['charges'])-shifts)) < 1e-12
        assert abs(q.sum()) < 1e-8 and np.max(abs(shifts)) <= .15000001
        baseline = 'cpd-anti-additive-boundary-baseline-v1' if case['endpoint'] == 1 else 'cpd-anti-additive-boundary-endpoint2-v1'
        psf = app.CharmmPsfFile(str(ART/baseline/f"endpoint-{case['endpoint']}/fragment.psf"))
        lj = [nb[a.attype] for a in psf.atom_list]
        for curve, fitted in zip(case['curves'], result['water']):
            probe_id = curve['id'].split('/')[-1]
            matches = []
            for job in jobs:
                if 'water_xyz' not in job or job['atom_map'] != case['names']:
                    continue
                if job.get('probe_id') != probe_id:
                    continue
                atoms, _ = parse_xyz(checked(job['source_xyz']).read_text())
                if np.max(abs(np.array([a[1:] for a in atoms])-xyz)) < 1e-9:
                    matches.append(job)
            assert len(matches) == 7, (curve['id'], len(matches))
            job = matches[-1]
            water, _ = parse_xyz(checked(job['water_xyz']).read_text())
            water = np.array([a[1:] for a in water])
            center = xyz[case['names'].index(job['target_atom'])]
            probe = {'O': 0, 'H1': 1, 'H2': 2}[job['probe_atom']]
            vec = water[probe]-center
            old = np.linalg.norm(vec)
            direction = vec/old

            def energy(distance):
                row, lj_energy = _interaction_row(xyz, lj, water+(distance-old)*direction, nb)
                return float(row@q+lj_energy)

            seed = fitted['mm_distance_A']
            minimum = minimize_scalar(energy, bounds=(seed-.04, seed+.04), method='bounded',
                                      options={'xatol': 1e-12})
            de = float(minimum.fun-curve['target_energy_kcal'])
            dr = float(minimum.x-curve['target_distance_A'])
            interpolation_energy = abs(float(minimum.fun-fitted['mm_energy_kcal']))
            interpolation_distance = abs(float(minimum.x-seed))
            records.append(dict(id=curve['id'], energy_error_kcal=de, distance_error_A=dr,
                interpolation_energy_error_kcal=interpolation_energy,
                interpolation_distance_error_A=interpolation_distance,
                passed=bool(minimum.success and abs(de)<=.5 and abs(dr)<=.2
                            and interpolation_energy<.002 and interpolation_distance<.002)))
    report = dict(charge_fit=source(fitpath), dataset=receipt['dataset'], reviewer=source(Path(__file__)),
        all_water_passed=len(records)==17 and all(r['passed'] for r in records), records=records,
        exposure='Independent implementation check on exposed development targets; no blind claim',
        limitations=['Geometry/energy transfer remains unvalidated', 'Three charge shifts reach bounds',
                     'Dipole vector errors 0.44-0.99 D remain reported; no post-hoc ratio gate'],
        simulation_ready=False)
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(all_water_passed=report['all_water_passed'],
        max_energy_error_kcal=max(abs(r['energy_error_kcal']) for r in records),
        max_distance_error_A=max(abs(r['distance_error_A']) for r in records)), indent=2))


if __name__ == '__main__':
    review()
