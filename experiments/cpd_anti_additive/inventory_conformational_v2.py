"""Assemble the already declared 19 exposed QM cases; no fitting or new QM."""

import argparse
import copy
from pathlib import Path
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from backend.parameterization.photoproduct_qm import parse_xyz, _dihedral_degrees
from experiments.cpd_anti_additive.sella_pilot import BOHR, now, save, projected_metrics
from experiments.cpd_anti_additive.validation_gate import checked, read, source, geometry_match

ART = REPO / '.development-artifacts'
EH = 627.5094740631


def heavy_torsions(graph):
    neighbors = {i: [] for i in range(graph['atom_count'])}
    for b in graph['bonds']:
        i, j = b['indices']
        if graph['atoms'][i]['element'] != 'H' and graph['atoms'][j]['element'] != 'H':
            neighbors[i].append(j)
            neighbors[j].append(i)
    torsions = set()
    for j, n in neighbors.items():
        for k in n:
            for i in neighbors[j]:
                for l in neighbors[k]:
                    if len({i, j, k, l}) == 4:
                        t = (i, j, k, l)
                        torsions.add(min(t, t[::-1]))
    return [list(t) for t in sorted(torsions)]


def main(root):
    root.mkdir(parents=True, exist_ok=False)
    original_path = ART / 'cpd-anti-remote-profile-mm-v1/plan.json'
    original = read(original_path)
    points = copy.deepcopy(original['points'])
    assert len(points) == 15
    for relative in (
        'cpd-anti-refined-basin-qm-v2/endpoint-2-reference-lower-mm-basin',
        'cpd-anti-refined-basin-qm-v1/endpoint-2--30-lower-mm-basin',
        'cpd-anti-lower-basin-profile-v1/endpoint-2--15-lower-qm-basin',
        'cpd-anti-sella-fresh-v1',
    ):
        folder = ART / relative
        plan = read(folder/'plan.json')
        assessment = read(folder/'assessment.json')
        rows = read(folder/'progress.json')['evaluations']
        result = read(checked(rows[-1]['result']))
        checked(result['native'])
        x = np.load(checked(result['geometry']))
        optimized = folder/'optimized.xyz'
        atoms, _ = parse_xyz(optimized.read_text())
        assert [a[0] for a in atoms] == plan['elements']
        assert np.max(abs(np.array([a[1:] for a in atoms])/BOHR-x)) < 2e-8
        if folder.name == 'cpd-anti-sella-fresh-v1':
            review_path = folder/'completion_delivery_verified.json'
            assert read(review_path)['passed']
        else:
            review_path = folder.parent/'independent_review.json'
            reviewed = next(r for r in read(review_path)['records'] if r['point'] == folder.name)
            assert reviewed['converged']
            checked(reviewed['assessment'])
        points.append(dict(label=plan['record']['label'], endpoint=2, record=plan['record'],
            elements=plan['elements'], geometry_bohr=x.tolist(), qm_energy=result['energy'],
            qm_source=source(folder/'assessment.json'), geometry_source=source(optimized),
            final_result=rows[-1]['result'], independent_review=source(review_path),
            acquisition_plan=source(folder/'plan.json')))

    records = []
    for point in points:
        evidence_path = checked(point['qm_source'])
        evidence = read(evidence_path)
        geometry_path = checked(point['geometry_source'])
        graph = read(checked(point['record']['model_graph']))
        scan = read(checked(point['record']['scan_plan']))
        names = [a['key'] for a in graph['atoms']]
        assert [a['element'] for a in graph['atoms']] == point['elements']
        assert scan['atom_map'] == names
        x = np.array(point['geometry_bohr'])
        if geometry_path.suffix == '.xyz':
            atoms, _ = parse_xyz(geometry_path.read_text())
            assert [a[0] for a in atoms] == point['elements']
            loaded = np.array([a[1:] for a in atoms])/BOHR
        else:
            inputs = read(geometry_path)
            assert inputs['elements'] == point['elements']
            loaded = np.array(inputs['geometry_bohr'])
        assert np.max(abs(loaded-x)) < 2e-8
        result_source = point.get('final_result')
        if result_source is None and (evidence_path.parent/'progress.json').exists():
            result_source = read(evidence_path.parent/'progress.json')['evaluations'][-1]['result']
        gradient_metrics = None
        if result_source:
            result = read(checked(result_source))
            native = checked(result['native'])
            assert abs(point['qm_energy']-result['energy']) < 1e-10
            gx = np.load(checked(result['geometry']))
            assert np.max(abs(gx-x)) < 2e-8
            g = np.array(result['gradient'])
            freeze = read(evidence_path.parent/'plan.json').get('freeze_torsion', True)
        elif 'gradient_au' in evidence:
            native = checked(evidence['native'])
            g = np.array(evidence['gradient_au']).reshape(x.shape)
            freeze = False
        else:
            native = checked(evidence['native'])
            g = None
            freeze = True
        if g is not None:
            if freeze:
                gradient_metrics = projected_metrics(x, g, point['record']['torsion_indices'])
            else:
                norms = np.linalg.norm(g, axis=1)
                gradient_metrics = dict(max_projected_atom_gradient=float(norms.max()),
                    rms_projected_atom_gradient=float(np.sqrt(np.mean(norms**2))))
        torsions = heavy_torsions(graph)
        torsion_values = [_dihedral_degrees(*x[list(t)]) for t in torsions]
        label = point['label']
        branch = ('lower-basin' if 'lower-' in label else
                  'remote-unconstrained' if 'remote-minimum' in label else 'historical-original')
        records.append(dict(case_id=label, endpoint=point['endpoint'], branch=branch,
            exposure='Previously inspected development/regression data; not blind',
            qm_energy_hartree=point['qm_energy'], geometry_bohr=point['geometry_bohr'],
            elements=point['elements'], atom_map=names, record=point['record'],
            qm_source=point['qm_source'], geometry_source=point['geometry_source'],
            native=source(native), final_result=result_source,
            acquisition_plan=point.get('acquisition_plan'), independent_review=point.get('independent_review'),
            constrained=freeze, actual_dihedral_deg=_dihedral_degrees(*x[point['record']['torsion_indices']]),
            cached_gradient_metrics=gradient_metrics,
            heavy_torsion_indices=torsions, heavy_torsion_degrees=torsion_values))
    assert len(records) == len({r['case_id'] for r in records}) == 19
    references = {'1': 'endpoint-1-reference', '2': 'endpoint-2-reference-lower-mm-basin'}
    for record in records:
        reference = next(r for r in records if r['case_id'] == references[str(record['endpoint'])])
        record['reference_case_id'] = reference['case_id']
        record['qm_relative_kcal_mol'] = (record['qm_energy_hartree']-reference['qm_energy_hartree'])*EH
    old = next(r for r in records if r['case_id'] == 'endpoint-2-+15')
    new = next(r for r in records if r['case_id'] == 'endpoint-2-+15-lower-qm-basin')
    correspondence = geometry_match(np.array(old['geometry_bohr'])*BOHR,
        np.array(new['geometry_bohr'])*BOHR, new['elements'], new['heavy_torsion_indices'])
    correspondence.update(old_case=old['case_id'], new_case=new['case_id'],
                          lower_minus_old_energy_kcal=(new['qm_energy_hartree']-old['qm_energy_hartree'])*EH,
                          interpretation='Distinct retained conformers at the same scanned angle; do not collapse branch labels.')
    packet = dict(schema='nadoc.cpd-anti-conformational-inventory.v2.1', created_at=now(),
        policy=source(REPO/'experiments/cpd_anti_additive/preliminary_policy_v2.json'),
        original_membership=source(original_path), case_count=19, records=records,
        common_reference_proposal=references, same_angle_branch_comparison=correspondence,
        all_declared_qm_geometries_present=True, new_qm_evaluations=0, fitted_parameters=0,
        stage='conformational', ready=False,
        remaining_before_fit=['Freeze minimal changed torsion identities and phase/periodicity/bounds.',
            'Specify branch correspondence, candidate MM evaluations and common references in the fitting manifest.',
            'Resolve any reference-quality issues recorded by this inventory without silently excluding targets; then lock stage inputs.'],
        caveats=['Historical endpoint-1 -15 uses earlier electronic tolerances; retained unchanged.',
                 'Cached gradient metrics are reported, not a retrospective claim that every historical case meets the newer optimizer pilot limits.',
                 'Constrained stationarity is not positive-curvature or global-minimum certification.'],
        minimum_certified=False, simulation_ready=False, source=source(Path(__file__)))
    save(root/'inventory.json', packet)
    print('19 declared cases inventoried; fitting not started; stage not yet locked.')
    print(correspondence)
    print('New +15 relative to lower reference',new['qm_relative_kcal_mol'])
    print('Cached force maxima',[(r['case_id'], None if r['cached_gradient_metrics'] is None else r['cached_gradient_metrics']['max_projected_atom_gradient']) for r in records])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    main(parser.parse_args().root.resolve())
