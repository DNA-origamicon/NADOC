#!/usr/bin/env python3
"""Scope and prepare the first frequency cohort from passed campaign geometries."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.parameterization.photoproduct_qm import generate_psi4_job
from continue_campaign import assessment
from reassess import DEFAULT, ROOT, atomic, digest, inventory, preflight, read, valid


def prepare(root: Path) -> dict:
    target = root / 'frequency_scope_v1.json'
    if target.exists() or (root / 'review_extensions.json').exists():
        raise FileExistsError('frequency scope/registration already exists; preserve prior cohort')
    preparation, items = inventory(root)
    geometry = [item for item in items if item['stage'] in {'A', 'B'}]
    # Benchmark the main release target and largest size first; subsequent jobs are
    # serialized until this finite-difference frequency benchmark is favorable.
    geometry.sort(key=lambda item: (item['id'] != 'syn-primary-endpoint-1', item['stage'] != 'B', item['id']))
    reports = [assessment(root, item, root / 'continuation_policy.json') for item in geometry]
    if not geometry or any(report['decision'] != 'continue' for report in reports):
        raise ValueError('frequency preparation requires favorable A/B candidate assessments')
    jobs = []
    for item in geometry:
        original = preflight(item)
        parent = Path(item['job_dir']) / 'optimized_model_audit.json'
        audit = read(parent)
        if not valid(audit['optimized_xyz']):
            raise ValueError('optimized geometry no longer matches its parent audit')
        case_id = f"frequency-{item['id']}"
        directory = root / 'frequency-cases' / case_id / 'job'
        generate_psi4_job(
            product_id=original['product_id'], model_id=original['model_id'],
            xyz_path=Path(audit['optimized_xyz']['path']), output_dir=directory,
            job_kind='frequency', charge=original['charge'], multiplicity=original['multiplicity'],
            atom_map=original['atom_map'], parent_manifest_path=parent,
            memory_gib=12, threads=12,
            protocol_path=ROOT / 'backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json',
        )
        jobs.append({'id': case_id, 'stage': 'D', 'job_dir': str(directory),
                     'job_manifest': {'path': str(directory / 'job_manifest.json'),
                                      'sha256': digest(directory / 'job_manifest.json')},
                     'parent_case': item['id'], 'wall_hours': 24})
    scope = {'schema': 'nadoc.local-qm-frequency-scope.v1', 'status': 'scoped_for_execution',
             'gate_effect': 'none', 'simulation_ready': False,
             'objective': 'Confirm harmonic minima and collect Cartesian Hessians for the seven newly optimized A/B fragments',
             'source_campaign': preparation['campaign'],
             'jobs': jobs, 'benchmark': jobs[0]['id'], 'maximum_parallel_jobs': 1,
             'acceptance': {'complete_projected_modes': '3N-6', 'imaginary_mode_count': 0,
                            'cartesian_hessian': 'hash-valid, finite, symmetric; existing frequency audit tolerance 1e-8 hartree/bohr^2',
                            'failure_action': 'hold dependent progression; no automatic imaginary-mode dismissal or geometry change'},
             'resources': {'psi4_memory_gib': 12, 'threads': 12, 'systemd_memory_max_gib': 16,
                           'wall_review_hours_per_job': 24, 'timing': 'provisional upper review budget; benchmark first job'},
             'coverage_limits': ['five reused core geometries need separate matching frequency-evidence inventory',
                                 'no held-out C structures used', 'charges, nonbonded targets and acyclic scans need a separate identified scope',
                                 'no force-field fit/release authorized by frequency success']}
    atomic(target, scope)
    atomic(root / 'review_extensions.json', {'schema': 'nadoc.local-qm-review-extensions.v1', 'jobs': jobs})
    return scope


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-root', type=Path, default=DEFAULT)
    print(json.dumps(prepare(parser.parse_args().campaign_root.resolve()), indent=2))
