"""Report exposed conformer energies after charge replacement; no parameter fitting."""

import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import app, unit as u

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive.validation_gate import checked, source, read
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from experiments.cpd_published_comparator.local_benchmarks import angle

ART = REPO/'.development-artifacts'


def main():
    _, receipt = require('engine')
    root = ART/'cpd-anti-charge-energy-diagnostic-v2'
    root.mkdir(exist_ok=False)
    (root/'executed_source.py').write_text(Path(__file__).read_text())
    candidate = Path(receipt['candidate'])
    planpath = ART/'cpd-anti-remote-profile-mm-v1/plan.json'
    plan = read(planpath)
    records = []
    for endpoint in (1, 2):
        folder = candidate/f'endpoint-{endpoint}'
        system = mm.XmlSerializer.deserialize((folder/'system.xml').read_text())
        labels = []
        for i, force in enumerate(system.getForces()):
            force.setForceGroup(i)
            labels.append(f'{type(force).__name__}:{i}')
        integrator = mm.VerletIntegrator(.001)
        ctx = mm.Context(system, integrator, mm.Platform.getPlatformByName('Reference'))
        for point in plan['points']:
            if point['endpoint'] != endpoint:
                continue
            checked(point['qm_source'])
            checked(point['geometry_source'])
            ctx.setPositions(np.array(point['geometry_bohr'])*.529177210903*u.angstrom)
            terms = {label: ctx.getState(getEnergy=True, groups=1<<i).getPotentialEnergy().value_in_unit(
                u.kilocalorie_per_mole) for i, label in enumerate(labels)}
            records.append(dict(label=point['label'], endpoint=endpoint,
                qm_energy_hartree=point['qm_energy'], mm_energy_kcal=sum(terms.values()), terms_kcal=terms,
                qm_source=point['qm_source'], geometry_source=point['geometry_source'],
                candidate=source(folder/'system.xml')))
        del ctx, integrator
    comparisons = []
    for record in records:
        # These identities are common to QM and MM; this is a diagnostic of the
        # original exposed set, not the pending lower-basin fit reference lock.
        reference_label = f"endpoint-{record['endpoint']}-reference"
        ref = next(r for r in records if r['label']==reference_label)
        qm_delta = (record['qm_energy_hartree']-ref['qm_energy_hartree'])*627.5094740631
        mm_delta = record['mm_energy_kcal']-ref['mm_energy_kcal']
        comparisons.append(dict(label=record['label'], reference=reference_label,
            qm_relative_kcal=qm_delta, mm_at_qm_relative_kcal=mm_delta,
            error_kcal=mm_delta-qm_delta))
    names = read(candidate/'endpoint-2/atom_map.json')
    original = np.loadtxt(candidate/'endpoint-2/starting_A.txt')
    original_min = np.loadtxt(candidate/'endpoint-2/minimum_A.txt')
    remote_min = np.loadtxt(candidate/'endpoint-2-remote/minimum_A.txt')
    p, q = original_min-original_min.mean(axis=0), remote_min-remote_min.mean(axis=0)
    left, _, right = np.linalg.svd(p.T@q)
    parity = np.eye(3)
    parity[2, 2] = np.linalg.det(left@right)
    rms = float(np.sqrt(np.mean(np.sum((p@left@parity@right-q)**2, axis=1))))
    psf = app.CharmmPsfFile(str(candidate/'endpoint-2/fragment.psf'))
    deviations = []
    for a in psf.angle_list:
        ids = [a.atom1.idx, a.atom2.idx, a.atom3.idx]
        deviations.append(dict(atoms=[names[i] for i in ids],
            error_deg=float(angle(original_min, ids)-angle(original, ids))))
    deviations.sort(key=lambda a: abs(a['error_deg']), reverse=True)
    save(root/'assessment.json', dict(records=records, comparisons=comparisons,
        original_endpoint2_relaxation=dict(rms_A_to_remote_minimum=rms, largest_angle_deviations=deviations[:10]),
        scope='Single-point MM on historical QM conformers. No MM relaxation, fitted torsions, energy gate or global minimum claim.',
        pending='Frozen lower-basin reference stage and branch-matched torsion validation',
        historical_plan=source(planpath), simulation_ready=False))
    print(json.dumps(dict(endpoint2_original_to_remote_minimum_rms_A=rms,
        largest_angle_deviations=deviations[:3], max_absolute_single_point_energy_error_kcal=
        max(abs(c['error_kcal']) for c in comparisons)), indent=2))


if __name__ == '__main__':
    main()
