"""Read-only molecular audit of a natively recorded Corner operation.

Writes evidence only, never a structure or a geometry override. All source and
Corner construction runs through the public feature-recording commands. This
audit neither changes molecular placement nor grants publication approval.
"""

import argparse
import hashlib
import json
from pathlib import Path
from time import monotonic

import numpy as np

from backend.api import headless_build as hb, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_corner import CreateCornerRequest, create_corner
from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_validation import _find_clashes, CLASH_NM
from backend.core.design_bond_review import review_design_bonds
from backend.core.models import LatticeType
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import command_rows
from backend.core.ring_piercing import piercing_report
from experiments.corner_seam_candidate import candidate_atoms, PROCESS, PROVIDER


def audit(lattice, *, compare=False, tips=False, lengths=False, close=False,
          cross_section='bundle', position_bp=84, evidence_sink=None):
    cells = ([[0, 0], [0, 1]] if cross_section == '2hb' else
             [[0, i] for i in range(8)] if lattice == LatticeType.SQUARE
             else [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]])
    started = monotonic()
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, 168, lattice=lattice, separate_fresh_extrusions=False)
        hb.add_cluster('Corner audit', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        cluster = next(c for c in source.cluster_transforms if c.name == 'Corner audit')
        tip_report = None
        if tips:
            from backend.api.part_corner_commands import preflight
            from experiments.corner_tip_support import measure_support
            guide, _ = preflight(source, dict(cluster_id=cluster.id, position_bp=position_bp, angle_deg=90, direction_deg=15))
            tip_report = measure_support(source, guide)
        create_corner(CreateCornerRequest(cluster_id=cluster.id, position_bp=position_bp,
            angle_deg=90, direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        design = state.get_or_404()
        proof = assess_part_history(design, execute=execute, dependencies=dependencies)
        if proof['status'] != 'verified':
            raise ValueError(f'AGENT_PROCESS_REQUIRED: {proof}')
        full = review_design_bonds(design)
        model = build_atomistic_model(design)
        labels = {h.id: h.label if h.label is not None else i for i, h in enumerate(design.helices)}
        seams = {link.id for link in design.forced_ligations}
        endpoints = {(getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
                      getattr(link, end+'_direction').value)
                     for link in design.forced_ligations for end in ('three_prime', 'five_prime')}

        def site(atom):
            return {'helix_label': labels.get(atom.helix_id), 'bp': atom.bp_index,
                    'direction': atom.direction, 'atom': atom.name,
                    'connection_id': atom.crossover_id, 'insert_index': atom.extra_base_k}

        def metrics(atoms):
            edges = []
            flexible_edges = []
            unmeasured = []
            for i, j in atoms.bonds:
                a, b = atoms.atoms[i], atoms.atoms[j]
                distance = float(np.linalg.norm(np.array([a.x-b.x, a.y-b.y, a.z-b.z])))
                if not np.isfinite(distance):
                    unmeasured.append({'from': site(a), 'to': site(b), 'serials': [i, j]})
                    continue
                relevant = any(v.crossover_id in seams or (v.helix_id, v.bp_index, v.direction) in endpoints
                               for v in (a, b))
                if relevant and {a.name, b.name} & {"O3'", 'P', 'OP1', 'OP2', "O5'"}:
                    flexible_edges.append({'from': site(a), 'to': site(b), 'length_nm': distance})
                if not ({a.crossover_id, b.crossover_id} & seams):
                    continue
                if (a.crossover_id, a.extra_base_k) == (b.crossover_id, b.extra_base_k):
                    continue
                edges.append({'from': site(a), 'to': site(b), 'length_nm': distance})
            positions = np.array([[a.x, a.y, a.z] for a in atoms.atoms])
            finite = np.isfinite(positions).all(axis=1)
            invalid = [{'serial': int(i), **site(atoms.atoms[i])} for i in np.flatnonzero(~finite)]
            piercing = (piercing_report(design, model=atoms) if finite.all() else
                {'n_pierced': None, 'pierced': [], 'complete': False,
                 'reason': 'Nonfinite atoms prevent a complete ring-piercing measurement.'})
            return {'seam_covalent_edges': sorted(edges, key=lambda row: -row['length_nm']),
                    'junction_flexible_edges': sorted(flexible_edges, key=lambda row: -row['length_nm']),
                    'invalid_atoms': invalid, 'unmeasured_covalent_edges': unmeasured,
                    'ring_piercing': piercing,
                    'heavy_atom_clashes': _find_clashes(positions, finite, atoms.bonds, CLASH_NM, 10000)}

        report = {'lattice': lattice.value, 'cross_section': cross_section, 'position_bp': position_bp,
                'design_sha256': hashlib.sha256(design.model_dump_json().encode()).hexdigest(),
                'feature_kinds': [getattr(e, 'op_kind', type(e).__name__) for e in design.feature_log],
                'process': proof, 'full_backbone': full, 'atoms': len(model.atoms),
                'tip_support': tip_report,
                'recorded_commands': list(command_rows(design, 2000)), **metrics(model)}
        if compare or close:
            before = design.model_dump_json()
            if close:
                from experiments.corner_seam_context import closed_candidate_atoms, PROVIDER as provider, PROCESS as process
                candidate = closed_candidate_atoms(design)
            else:
                candidate = candidate_atoms(design)
                provider, process = PROVIDER, PROCESS
            assert design.model_dump_json() == before
            assert len(candidate.atoms) == len(model.atoms)
            assert candidate.bonds == model.bonds
            displaced = []
            restored = []
            for a, b in zip(model.atoms, candidate.atoms):
                assert site(a) == site(b) and a.strand_id == b.strand_id
                if not np.isfinite([a.x, a.y, a.z]).all():
                    if np.isfinite([b.x, b.y, b.z]).all():
                        restored.append({'serial': a.serial, **site(a)})
                    continue
                distance = float(np.linalg.norm([a.x-b.x, a.y-b.y, a.z-b.z]))
                if distance > 1e-9:
                    if not a.crossover_id and a.name not in {"O3'", 'P', 'OP1', 'OP2', "O5'"}:
                        raise ValueError('The isolated candidate moved a rigid duplex atom.')
                    displaced.append({**site(a), 'displacement_nm': distance})
            report['candidate'] = {'provider': provider, 'evaluation_process': process,
                'unapproved': True, 'displaced_atoms': displaced, 'restored_finite_atoms': restored,
                **metrics(candidate)}
        if lengths:
            from experiments.corner_seam_lengths import explore_lengths
            report['length_exploration'] = explore_lengths(design)
        report['elapsed_seconds'] = monotonic()-started
        if evidence_sink:
            if not (compare or close):
                raise ValueError('An A/B evidence sink requires an explicit candidate evaluation.')
            evidence_sink(design, model, candidate, report)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare', action='store_true')
    parser.add_argument('--tips', action='store_true')
    parser.add_argument('--lengths', action='store_true')
    parser.add_argument('--close', action='store_true')
    parser.add_argument('--phase-sweep', action='store_true',
                        help='Whole-model closed candidate on all 21 HC and 32 SQ bp phase classes in 2HB sources.')
    args = parser.parse_args()
    cases = ([(lattice, '2hb', 84+phase) for lattice, count in
              ((LatticeType.HONEYCOMB, 21), (LatticeType.SQUARE, 32)) for phase in range(count)]
             if args.phase_sweep else [(lattice, 'bundle', 84)
                 for lattice in (LatticeType.HONEYCOMB, LatticeType.SQUARE)])
    reports = []
    for lattice, cross_section, position_bp in cases:
        report = audit(lattice, compare=args.compare, tips=args.tips, lengths=args.lengths,
            close=args.close or args.phase_sweep, cross_section=cross_section, position_bp=position_bp)
        reports.append(report)
        if args.phase_sweep:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix('.tmp')
            temporary.write_text(json.dumps({'complete': len(reports) == len(cases),
                'expected_cases': len(cases), 'cases': reports}, indent=2, allow_nan=False))
            temporary.replace(args.output)
        print(json.dumps({'lattice': report['lattice'], 'atoms': report['atoms'],
            'case': len(reports), 'total': len(cases), 'position_bp': position_bp,
            'process': report['process']['status'], 'elapsed_seconds': report['elapsed_seconds'],
            'seam_edges': len(report['seam_covalent_edges']),
            'max_seam_bond_nm': max((r['length_nm'] for r in report['seam_covalent_edges']), default=0),
            'ring_piercings': report['ring_piercing']['n_pierced']}), flush=True)
        if 'candidate' in report:
            candidate = report['candidate']
            print(json.dumps({'candidate': candidate['provider'],
                'moved_atoms': len(candidate['displaced_atoms']),
                'max_seam_bond_nm': max((r['length_nm'] for r in candidate['seam_covalent_edges']), default=0),
                'ring_piercings': candidate['ring_piercing']['n_pierced'],
                'clashes': len(candidate['heavy_atom_clashes'])}), flush=True)
    if not args.phase_sweep:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(reports, indent=2, allow_nan=False))
