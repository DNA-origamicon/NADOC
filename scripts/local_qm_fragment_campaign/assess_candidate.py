#!/usr/bin/env python3
"""Conservative continuation QC for a completed, isolated QM candidate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.parameterization.photoproduct_qm import audit_optimized_model, audit_frequency_result, parse_xyz
from reassess import preflight, read, digest, valid


def geometry_screen(job: dict, policy: dict) -> dict:
    model = read(Path(job['model_manifest']['path']))
    sdf = model['outputs']['sdf']
    if not valid(sdf):
        raise ValueError('model SDF changed or unavailable')
    mol = Chem.SDMolSupplier(sdf['path'], removeHs=False)[0]
    if mol is None or mol.GetNumAtoms() != job['atom_count']:
        raise ValueError('invalid source molecular graph')
    atom_map = job['atom_map']
    before, _ = parse_xyz(Path(job['source_xyz']['path']).read_text())
    after, _ = parse_xyz(Path(job['input']['path']).parent.joinpath('optimized.xyz').read_text())
    elements = [a.GetSymbol() for a in mol.GetAtoms()]
    if [a[0] for a in before] != elements or [a[0] for a in after] != elements:
        raise ValueError('element or atom order changed')
    first = np.array([a[1:] for a in before])
    final = np.array([a[1:] for a in after])
    if not np.isfinite(final).all():
        raise ValueError('nonfinite coordinates')
    issues, bonds, centers = [], [], []
    for bond in mol.GetBonds():
        i, j = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        d0, d1 = float(np.linalg.norm(first[i]-first[j])), float(np.linalg.norm(final[i]-final[j]))
        fraction = abs(d1/d0 - 1)
        bonds.append({'atoms': [atom_map[i], atom_map[j]], 'before': d0, 'after': d1, 'fractional_change': fraction})
        if fraction > policy['maximum_bond_fractional_change']:
            issues.append(f'bond change: {atom_map[i]}--{atom_map[j]}')
    for atom in mol.GetAtoms():
        neighbors = sorted(n.GetIdx() for n in atom.GetNeighbors())
        if len(neighbors) != 4:
            continue
        def volume(coords):
            points = coords[neighbors]
            return float(np.linalg.det(points[:3]-points[3]))
        v0, v1 = volume(first), volume(final)
        passed = v0*v1 > 0 and abs(v1) >= policy['minimum_tetrahedral_volume_fraction']*abs(v0)
        centers.append({'atom': atom_map[atom.GetIdx()], 'before_volume': v0, 'after_volume': v1, 'passed': passed})
        if not passed:
            issues.append(f'tetrahedral inversion/flattening: {atom_map[atom.GetIdx()]}')
    topology_distance = Chem.GetDistanceMatrix(mol)
    table = Chem.GetPeriodicTable()
    cap_contacts = []
    for i in range(len(elements)):
        for j in range(i):
            if topology_distance[i, j] <= 2:
                continue
            distance = float(np.linalg.norm(final[i]-final[j]))
            radii = table.GetRcovalent(elements[i]) + table.GetRcovalent(elements[j])
            if distance < policy['nonbonded_covalent_radius_fraction'] * radii:
                issues.append(f'nonbonded overlap: {atom_map[i]}--{atom_map[j]}')
            for h, acceptor in ((i, j), (j, i)):
                key = atom_map[h].split(':')[-1]
                if elements[h] == 'H' and elements[acceptor] in {'N', 'O'} and (key.startswith('HCM') or key in {"HO3'", "HO5'"}):
                    if distance < policy['cap_h_acceptor_review_angstrom']:
                        cap_contacts.append({'atoms': [atom_map[h], atom_map[acceptor]], 'distance': distance})
    if cap_contacts:
        issues.append('short cap-to-acceptor contact requires conformer review')
    return {'passed': not issues, 'issues': issues, 'bonds': bonds,
            'tetrahedral_centers': centers, 'cap_contacts': cap_contacts,
            'source_sdf_sha256': sdf['sha256'],
            'scope': 'candidate continuity and gross-geometry QC only; no minimum/transfer/force-field release'}


def assess(item: dict, policy: dict) -> dict:
    directory = Path(item['job_dir'])
    job = preflight(item)
    run = read(directory / 'run_manifest.json')
    if run.get('status') != 'completed_unreviewed' or run.get('returncode') != 0 or not run.get('parsed', {}).get('passed_execution_checks'):
        raise ValueError('QM execution did not pass')
    if run['job_manifest_sha256'] != digest(directory / 'job_manifest.json'):
        raise ValueError('run/job hash mismatch')
    for name, record in run['outputs'].items():
        if Path(name).name != name or digest(directory / name) != record['sha256']:
            raise ValueError('run/output hash mismatch')
    finish = read(directory / 'campaign_finish.json')
    issues = []
    if finish['returncode'] != 0 or finish['elapsed_seconds'] > item['wall_hours']*3600:
        issues.append('execution failed or exceeded registered wall budget')
    if finish['peak_child_rss_kib']/1024**2 > job['memory_gib'] + policy['peak_memory_headroom_gib']:
        issues.append('peak memory exceeded continuation headroom')
    if job['job_kind'] == 'frequency':
        path = directory / 'frequency_audit.json'
        audit = read(path) if path.exists() else audit_frequency_result(directory)
        if audit['status'] not in {'passed_harmonic_minimum', 'passed_candidate_harmonic_minimum'}:
            issues.append('frequency/minimum audit failed')
        geometry = None
    else:
        path = directory / 'optimized_model_audit.json'
        audit = read(path) if path.exists() else audit_optimized_model(directory)
        if audit['status'] not in {'passed_identity_and_chirality', 'passed_candidate_identity_and_chirality'}:
            issues.append('product identity/chirality audit failed')
        geometry = geometry_screen(job, policy)
        issues += geometry['issues']
    for key in ('effective_run_record', 'optimized_xyz', 'output', 'parent_optimized_model_audit'):
        if key in audit and not valid(audit[key]):
            raise ValueError(f'audit provenance mismatch: {key}')
    return {'schema': 'nadoc.local-qm-continuation-assessment.v1',
            'id': item['id'], 'stage': item['stage'], 'decision': 'hold' if issues else 'continue',
            'issues': issues, 'domain_audit': {'path': str(path), 'sha256': digest(path)},
            'run_sha256': digest(directory / 'run_manifest.json'),
            'job_manifest': item['job_manifest'], 'geometry_screen': geometry, 'resources': finish,
            'gate_effect': 'none', 'simulation_ready': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--item', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(assess(read(args.item), read(args.policy)), indent=2))
