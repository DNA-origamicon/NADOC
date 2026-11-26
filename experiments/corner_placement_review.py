"""Prepare read-only Corner A/B evidence with complete native source history.

No .nadoc is published, candidate poses are not inserted into a Design, and no
atomistic reference substitutes for authoring history. The only candidate is
the explicitly named diagnostic evaluation of the unchanged authored topology.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.api.part_proof_commands import dependencies, execute
from backend.core.atomistic import atomistic_to_json
from backend.core.atomistic_validation import CLASH_NM
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design, LatticeType
from backend.core.molecular_placement_audit import _bond_metrics, _defect_serials
from backend.core.part_history_contract import assess_part_history
from experiments.corner_review_projection import full_model
from experiments.corner_seam_context import PROVIDER, PROCESS
from experiments.corner_tool_audit import audit


def pack(design, current, candidate, report, label):
    reopened = Design.model_validate_json(design.model_dump_json())
    proof = assess_part_history(reopened, execute=execute, dependencies=dependencies)
    if proof['status'] != 'verified':
        raise ValueError(f'AGENT_PROCESS_REQUIRED: {proof}')
    labels = {h.id: h.label if h.label is not None else i for i, h in enumerate(design.helices)}
    raw = {side: np.array([[a.x, a.y, a.z] for a in model.atoms])
           for side, model in [('current', current), ('candidate', candidate)]}
    if not all(np.isfinite(xyz).all() for xyz in raw.values()):
        raise ValueError('Select a finite representative for the 3D artifact; retain invalid phases in engineering evidence.')
    displacement = np.linalg.norm(raw['candidate']-raw['current'], axis=1)
    affected = np.flatnonzero(displacement > 1e-9).tolist()
    geometry = _geometry_for_design(design)
    source = reopened.model_dump(mode='json')
    bundle = {'schema': 'nadoc.corner-placement-review.v1', 'label': label, 'read_only': True,
        'current_design': source, 'candidate_design': source,
        'source_sha256': report['design_sha256'], 'source_proof': proof,
        'recorded_commands': report['recorded_commands'], 'nucleotides': geometry,
        'candidate_process': PROCESS,
        'provider': {'id': PROVIDER, 'label': 'Corner joint seam closure — isolated candidate',
                     'not_authorized_for_production': True},
        'affected_atom_serials': affected, 'defect_atom_serials': {},
        'displacement': {'n_displaced': len(affected), 'max_nm': float(displacement.max()),
            'vectors': [{'serial': i, 'from': raw['current'][i].tolist(),
                         'to': raw['candidate'][i].tolist()} for i in affected]},
        'construction': [], 'junctions': [],
        'limitations': [
            'Current is the exact native atomistic reconstruction; Candidate changes only diagnostic atom coordinates.',
            'The authored topology, insertion counts, sequences and all rigid duplex atoms are identical.',
            'Insert sugar/base bodies move rigidly; seam phosphate atoms are fitted jointly. Native terminal gamma is not preserved.',
            'Full-style panels project O5′ beads and base slabs from these actual atom models, not canonical production Full placement.',
            'These are geometric checks, not a relaxation, stability result or simulation-ready certificate.',
            'Approval would cover this demonstrated Corner seam provider, not unrelated crossover placements or locked phase constants.',
        ]}
    for index, entry in enumerate(design.feature_log, 1):
        kind = getattr(entry, 'op_kind', entry.feature_type)
        if kind == 'bundle-create':
            text = f'F{index}: Extrude 1 — {len(entry.params["cells"])} helices, {entry.params["length_bp"]} bp, {design.lattice_type.value}'
        elif entry.feature_type == 'cluster_create':
            selected = ', '.join(str(labels[hid]) for hid in entry.cluster_snapshot.helix_ids)
            text = f'F{index}: Make Cluster 1 — helices {selected}'
        elif kind == 'corner':
            p = entry.params
            text = f'F{index}: Corner 1 — plane {p["position_bp"]} bp, angle {p["angle_deg"]:g}°, direction {p["direction_deg"]:g}°; count policy v{p["_proof_version"]}'
        else:
            raise ValueError(f'No truthful review label for source operation {kind}.')
        bundle['construction'].append(text)
    for side, model in [('current', current), ('candidate', candidate)]:
        metrics = report if side == 'current' else report['candidate']
        diagnostics = {'piercing': metrics['ring_piercing'], 'bonds': _bond_metrics(model, raw[side]),
            'clashes': metrics['heavy_atom_clashes'], 'n_clashes': len(metrics['heavy_atom_clashes']),
            'clash_threshold_nm': CLASH_NM,
            'max_junction_covalent_nm': max(r['length_nm'] for r in metrics['junction_flexible_edges'])}
        data = atomistic_to_json(model)
        for row, xyz in zip(data['atoms'], raw[side]):
            row.update(zip(('x', 'y', 'z'), map(float, xyz)))
        bundle[side] = {**data, 'diagnostics': diagnostics, 'nucleotides': geometry,
                        'full_model': full_model(model)}
        bundle['defect_atom_serials'][side] = _defect_serials(diagnostics)
    for link in design.forced_ligations:
        endpoints = {(getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
                      getattr(link, end+'_direction').value) for end in ('three_prime', 'five_prime')}
        ids = {a.serial for a in current.atoms if a.crossover_id == link.id or
               (not a.crossover_id and (a.helix_id, a.bp_index, a.direction) in endpoints)}
        row = {'label': f'Helix {labels[link.three_prime_helix_id]}:{link.three_prime_bp} → '
                       f'helix {labels[link.five_prime_helix_id]}:{link.five_prime_bp}',
               'insert_bases': len(link.extra_bases), 'atom_serials': sorted(ids),
               'max_displacement_nm': float(displacement[list(ids)].max())}
        for side, model in [('current', current), ('candidate', candidate)]:
            diag = bundle[side]['diagnostics']
            lengths = [float(np.linalg.norm(raw[side][i]-raw[side][j])) for i, j in model.bonds
                       if (i in ids or j in ids) and {model.atoms[i].name, model.atoms[j].name}
                       & {"O3'", 'P', 'OP1', 'OP2', "O5'"}]
            row[side] = {'max_covalent_nm': max(lengths),
                'clashes': sum(bool(ids.intersection(hit['serials'])) for hit in diag['clashes']),
                'piercings': sum(bool(ids.intersection([*hit['bond_serials'], *hit['ring_serials']]))
                                 for hit in diag['piercing']['pierced'])}
        bundle['junctions'].append(row)
    return bundle


def build(output, phase_path):
    phases = json.loads(phase_path.read_text())
    if not phases.get('complete') or len(phases['cases']) != phases['expected_cases'] or phases['expected_cases'] != 53:
        raise ValueError('The full 21 HC / 32 SQ phase sweep must complete before preparing the review.')
    cases = {}
    for key, lattice, shape, position, label in [
        ('six', LatticeType.HONEYCOMB, 'bundle', 84, 'Corner — 6HB'),
        ('square', LatticeType.SQUARE, 'bundle', 84, 'Corner — flat 1×8 square'),
        ('hc2', LatticeType.HONEYCOMB, '2hb', 84, 'Corner — 2HB honeycomb'),
        ('sq2', LatticeType.SQUARE, '2hb', 85, 'Corner — 2HB square')]:
        audit(lattice, close=True, cross_section=shape, position_bp=position,
              evidence_sink=lambda d, a, b, r: cases.update({key: pack(d, a, b, r, label)}))
        print(f'Prepared {label}', flush=True)
    bundle = cases.pop('six')
    bundle['controls'] = cases
    phase_summary = {'sha256': hashlib.sha256(phase_path.read_bytes()).hexdigest(), 'cases': []}
    for row in phases['cases']:
        c = row['candidate']
        phase_summary['cases'].append({'lattice': row['lattice'], 'position_bp': row['position_bp'],
            'current_invalid_atoms': len(row['invalid_atoms']),
            'candidate_invalid_atoms': len(c['invalid_atoms']), 'candidate_clashes': len(c['heavy_atom_clashes']),
            'candidate_piercings': c['ring_piercing']['n_pierced'],
            'candidate_max_covalent_nm': max(x['length_nm'] for x in c['junction_flexible_edges'])})
    for case in [bundle, *cases.values()]:
        case['phase_sweep'] = phase_summary
    root = Path(__file__).resolve().parents[1]
    bundle['implementation_sha256'] = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in [
        'experiments/corner_seam_context.py', 'experiments/corner_seam_closure.py',
        'experiments/corner_seam_candidate.py', 'experiments/corner_review_projection.py',
        'backend/api/corner_build.py', 'backend/core/corner_tip_support.py']}
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, 'wt') as stream:
        json.dump(bundle, stream, allow_nan=False, separators=(',', ':'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phases', type=Path, required=True)
    args = parser.parse_args()
    build(args.output, args.phases)
