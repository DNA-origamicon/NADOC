"""Fail-closed CPD qualification contract over independently reviewed evidence.

This aggregates reviewed native evidence; it is not a substitute for native audits.
Missing records, changed hashes, nonfinite metrics and unmatched basins cannot pass.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
POLICY = Path(__file__).with_name('validation_policy_v1.json')
STATE = REPO / '.development-artifacts/cpd-anti-validation-v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(path):
    return dict(path=str(Path(path).resolve()), sha256=digest(path))


def checked(ref):
    p = Path(ref['path'])
    if digest(p) != ref['sha256']:
        raise ValueError(f'Changed evidence: {p}')
    return p


def read(path):
    return json.loads(Path(path).read_text())


def geometry_match(qm, mm, elements, torsions):
    """Atom-order-fixed heavy RMSD and all supplied heavy proper torsions.

    Caller must independently verify exact graph, stereo and torsion-list coverage.
    No atom permutation/reflection: endpoint order is chemically meaningful here.
    """
    import numpy as np
    from backend.parameterization.photoproduct_qm import _dihedral_degrees
    q, m = np.asarray(qm, float), np.asarray(mm, float)
    if q.shape != (len(elements), 3) or m.shape != q.shape or not np.isfinite([q, m]).all():
        raise ValueError('Invalid coordinates')
    heavy = [i for i, e in enumerate(elements) if e != 'H']
    if len(heavy) < 3 or not torsions:
        raise ValueError('Missing basin descriptors')
    x, y = q[heavy] - q[heavy].mean(0), m[heavy] - m[heavy].mean(0)
    u, _, vt = np.linalg.svd(x.T @ y)
    rot = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
    rmsd = float(np.sqrt(np.mean(np.sum((x @ rot - y)**2, axis=1))))
    errors = [abs((_dihedral_degrees(*q[t]) - _dihedral_degrees(*m[t]) + 180) % 360 - 180) for t in torsions]
    if not all(math.isfinite(e) for e in errors):
        raise ValueError('Undefined torsion')
    return dict(basin_rmsd_A=rmsd, basin_max_torsion_deg=max(errors))


def evaluate(policy_path=POLICY, packet_path=None, stage='acquisition'):
    policy = read(policy_path)
    packet = read(packet_path) if packet_path and Path(packet_path).exists() else {}
    limits = policy['thresholds']
    reasons, records, errors = [], [], {}
    if packet.get('policy_sha256') != digest(policy_path):
        reasons.append('Missing or mismatched policy hash')
    incoming = packet.get('records', [])
    ids = [r['case_id'] for r in incoming]
    if len(ids) != len(set(ids)):
        reasons.append('Duplicate case IDs')
    if set(ids) - {c['id'] for c in policy['cases']}:
        reasons.append('Unknown case IDs')
    rows = {r['case_id']: r for r in incoming}
    candidate = packet.get('candidate', {})
    references = packet.get('references', {})
    for endpoint in {str(c['endpoint']) for c in policy['cases'] if c['kind'] == 'profile'}:
        try:
            ref = references[endpoint]
            if not ref['id'] or type(ref['qm_energy']) not in (int, float) or not math.isfinite(ref['qm_energy']):
                raise ValueError('Invalid reference energy/identity')
            checked(ref['qm_geometry'])
        except (KeyError, ValueError, OSError, TypeError) as exc:
            reasons.append(f'Frozen reference {endpoint}: {exc}')
    if stage == 'candidate':
        try:
            bundle = read(checked(candidate['parameters']))
            if not bundle.get('artifacts'):
                raise ValueError('Missing parameter bundle artifacts')
            for ref in bundle['artifacts']:
                checked(ref)
            if candidate['frozen_before_holdout'] is not True or candidate['holdout_used_for_fit'] is not False:
                raise ValueError('Holdout contaminated or candidate not preregistered')
            if type(candidate['fit_round']) is not int or candidate['fit_round'] not in (1, 2):
                raise ValueError('Same-model fit budget exceeded')
            if not candidate['training_case_ids'] or set(candidate['training_case_ids']) - {c['id'] for c in policy['cases'] if c['role'] in ('development', 'regression')}:
                raise ValueError('Invalid training split')
            receipt = read(checked(candidate['freeze_receipt']))
            if receipt['policy_sha256'] != digest(policy_path) or receipt['parameters'] != candidate['parameters']:
                raise ValueError('Candidate lock mismatch')
            lock = read(checked(receipt['dataset_lock']))
            checked(lock['policy'])
            if lock['policy']['sha256'] != digest(policy_path):
                raise ValueError('Dataset lock policy mismatch')
            acquisition_path = checked(lock['packet'])
            if not evaluate(policy_path, acquisition_path, 'acquisition')['passed']:
                raise ValueError('Locked acquisition evidence no longer passes')
            frozen_refs = read(acquisition_path)['references']
            for endpoint, ref in frozen_refs.items():
                if any(references[endpoint][key] != ref[key] for key in ('id','qm_energy','qm_geometry')):
                    raise ValueError('Candidate changed frozen QM reference')
        except (KeyError, OSError, ValueError) as exc:
            reasons.append(f'Candidate provenance: {exc}')
    for case in policy['cases']:
        if stage == 'acquisition' and (case['role'] == 'holdout' or case['kind'] == 'export'):
            continue
        failures = []
        row = rows.get(case['id'])
        if row is None:
            records.append(dict(case_id=case['id'], passed=False, failures=['Missing reviewed evidence']))
            continue
        try:
            evidence = read(checked(row['review']))
            if evidence['case_id'] != case['id']:
                raise ValueError('Review case mismatch')
            if stage == 'candidate' and evidence['candidate_sha256'] != candidate['parameters']['sha256']:
                raise ValueError('Review is for a different candidate')
            if not evidence['artifacts']:
                raise ValueError('Missing native artifacts')
            for ref in evidence['artifacts']:
                checked(ref)
            metrics, checks = evidence['metrics'], evidence['checks']
            if stage == 'candidate' and case['role'] == 'holdout':
                if checks.get('target_generated_after_registration') is not True or checks.get('used_for_fit') is not False:
                    raise ValueError('Holdout exposure invalid')
            def flag(name):
                if checks.get(name) is not True:
                    failures.append(name)
            def maximum(name, bound):
                value = metrics.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > bound:
                    failures.append(name)
            flag('native_audit_passed')
            flag('method_and_atom_map_match')
            kind = case['kind']
            if kind in ('profile', 'minimum'):
                flag('stereo_preserved')
                maximum('qm_max_gradient_au', limits['qm_max_gradient_au'])
                maximum('qm_rms_gradient_au', limits['qm_rms_gradient_au'])
                if kind == 'profile':
                    flag('all_seed_families_checked')
                    flag('bidirectional_closure_passed')
                    flag('no_unresolved_branches')
                    maximum('closure_energy_kcal', limits['closure_energy_kcal'])
                    maximum('torsion_constraint_deg', limits['torsion_constraint_deg'])
                else:
                    flag('unconstrained')
                    flag('positive_projected_hessian_two_steps')
                    flag('soft_mode_uncertainty_resolved')
                if stage == 'candidate':
                    flag('all_heavy_torsions_checked')
                    flag('same_reference_identity')
                    flag('mm_multistart_complete')
                    for name in ('mm_max_gradient_au','mm_rms_gradient_au','basin_rmsd_A','basin_max_torsion_deg','bond_error_A','angle_error_deg'):
                        maximum(name, limits[name])
                    if kind == 'minimum':
                        flag('mm_positive_projected_hessian_two_steps')
                    else:
                        ref = references[str(case['endpoint'])]
                        if evidence['reference_id'] != ref['id'] or metrics['mm_reference_energy'] != ref['mm_energy'] or metrics['qm_reference_energy'] != ref['qm_energy']:
                            raise ValueError('Energy zero/reference identity mismatch')
                        # Recompute ddE: four energies in kcal/mol, same frozen identity.
                        vals = [metrics[n] for n in ('mm_energy','mm_reference_energy','qm_energy','qm_reference_energy')]
                        if not all(type(v) in (int,float) and math.isfinite(v) for v in vals):
                            raise ValueError('Nonfinite energy')
                        error = (vals[0]-vals[1]) - (vals[2]-vals[3])
                        if abs(error) > limits['energy_max_abs_kcal']:
                            failures.append('energy_max_abs_kcal')
                        errors.setdefault((case['endpoint'],case['role']), []).append(error)
            elif kind == 'water':
                flag('qm_minimum_bracketed')
                flag('single_site_contact')
                flag('orientation_preregistered')
                maximum('df_direct_error_kcal', .02)
                if stage == 'candidate':
                    flag('mm_minimum_bracketed')
                    flag('charmm_scaling_applied')
                    maximum('water_abs_energy_error_kcal', limits['water_max_abs_energy_kcal'])
                    maximum('water_abs_distance_error_A', limits['water_max_abs_distance_A'])
            elif kind == 'electrostatics':
                flag('finite_esp_grid_and_dipole')
                if stage == 'candidate':
                    flag('fixed_caps_sugar_lj_and_neutrality')
                    maximum('esp_relative_rmse_increase', limits['esp_relative_rmse_regression'])
                    ratio = metrics.get('dipole_ratio', float('nan'))
                    if not limits['dipole_ratio_min'] <= ratio <= limits['dipole_ratio_max']:
                        failures.append('dipole_ratio')
                    maximum('dipole_angle_deg', limits['dipole_angle_deg'])
            elif kind == 'export':
                flag('complete_parameter_coverage')
                maximum('export_energy_kcal', limits['export_energy_kcal'])
                maximum('export_force_kcal_A', limits['export_force_kcal_A'])
        except (KeyError, OSError, ValueError, TypeError) as exc:
            failures.append(str(exc))
        records.append(dict(case_id=case['id'], passed=not failures, failures=failures))
    for group, values in errors.items():
        if math.sqrt(sum(v*v for v in values)/len(values)) > limits['energy_rmse_kcal']:
            reasons.append(f'Energy RMSE exceeds limit for {group}')
    passed = not reasons and bool(records) and all(r['passed'] for r in records)
    return dict(policy=source(policy_path), stage=stage, passed=passed, reasons=reasons,
                records=records, passed_cases=sum(r['passed'] for r in records), required_cases=len(records),
                simulation_ready=False, product_promotion_authorized=False,
                scope='Fragment contract only; successful acquisition is not candidate acceptance or DNA validation')


def require_fit_ready():
    """All parameter fitting entry points call this before creating outputs."""
    if (STATE / 'candidate_lock.json').exists():
        raise RuntimeError('CPD fitting blocked: candidate locked for holdout; a new preregistered validation version is required to resume fitting')
    path = STATE / 'dataset_lock.json'
    if not path.exists():
        raise RuntimeError('CPD fitting blocked: basin-checked dataset not frozen. See docs/cpd_validation_protocol.md')
    lock = read(path)
    checked(lock['policy'])
    if lock['policy']['sha256'] != digest(POLICY):
        raise RuntimeError('CPD policy changed; renew dataset lock')
    packet = checked(lock['packet'])
    if not evaluate(POLICY, packet)['passed']:
        raise RuntimeError('CPD fitting blocked: reference acquisition gate failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'check', 'freeze', 'register'])
    parser.add_argument('--packet', type=Path, default=STATE/'evidence_packet.json')
    parser.add_argument('--stage', choices=['acquisition','candidate'], default='acquisition')
    parser.add_argument('--output', type=Path, default=STATE/'status.json')
    parser.add_argument('--parameters', type=Path)
    args = parser.parse_args()
    if args.action == 'register':
        require_fit_ready()
        if not args.parameters:
            parser.error('--parameters must name an immutable parameter bundle manifest')
        from datetime import datetime, timezone
        bundle = read(args.parameters)
        if not bundle.get('artifacts'):
            parser.error('Parameter bundle must hash all PSF/RTF/PRM/XML files in artifacts')
        for ref in bundle['artifacts']:
            checked(ref)
        with (STATE/'candidate_lock.json').open('x') as f:
            json.dump(dict(policy_sha256=digest(POLICY), parameters=source(args.parameters), dataset_lock=source(STATE/'dataset_lock.json'), registered_at=datetime.now(timezone.utc).isoformat()), f, indent=2)
        print('Candidate locked; further fitting blocked and holdout acquisition may begin')
        return
    result = evaluate(POLICY, args.packet, args.stage)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    if args.action == 'freeze':
        if args.stage != 'acquisition' or not result['passed']:
            raise SystemExit('Cannot freeze: acquisition incomplete')
        with (STATE/'dataset_lock.json').open('x') as f:
            json.dump(dict(policy=source(POLICY), packet=source(args.packet)), f, indent=2)
    print(f"{args.stage}: {'PASS' if result['passed'] else 'BLOCKED'}; {result['passed_cases']}/{result['required_cases']} reviewed cases")
    if args.action == 'check' and not result['passed']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
