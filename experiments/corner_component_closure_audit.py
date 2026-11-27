"""Bounded component-only Corner closure diagnostic; writes JSON evidence only."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from backend.api import headless_build as hb, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_corner import CreateCornerRequest, create_corner
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import LatticeType
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import command_rows
from experiments.corner_seam_candidate import deferred_duplex_atoms
from experiments.corner_seam_closure import close_component
from experiments.corner_seam_lengths import junction_component, local_metrics


def audit(lattice, *, cross_section='2hb', max_bases=8):
    if not 1 <= max_bases <= 8:
        raise ValueError('This diagnostic is bounded to 1–8 inserted bases.')
    cells = ([[0, 0], [0, 1]] if cross_section == '2hb' else
             [[0, i] for i in range(8)] if lattice == LatticeType.SQUARE else
             [[0, 1], [1, 1], [1, 2], [1, 3], [0, 3], [0, 2]])
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, 168, lattice=lattice, separate_fresh_extrusions=False)
        hb.add_cluster('Corner closure diagnostic', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        owner = next(c for c in source.cluster_transforms if c.name == 'Corner closure diagnostic')
        create_corner(CreateCornerRequest(cluster_id=owner.id, position_bp=84, angle_deg=90,
            direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        design = state.get_or_404()
        before = design.model_dump_json()
        proof = assess_part_history(design, execute=execute, dependencies=dependencies)
        if proof['status'] != 'verified':
            raise ValueError(f'AGENT_PROCESS_REQUIRED: {proof}')
        model = deferred_duplex_atoms(design)
        sites = {(r['helix_id'], r['bp_index'], r['direction']): r
                 for r in _geometry_for_design(design) if not r.get('copy_k')}
        labels = {h.id: h.label if h.label is not None else i for i, h in enumerate(design.helices)}
        junctions = []
        for link in design.forced_ligations:
            endpoints = {(getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
                          getattr(link, end+'_direction').value) for end in ('three_prime', 'five_prime')}
            environment = np.array([[a.x, a.y, a.z] for a in model.atoms
                if (a.helix_id, a.bp_index, a.direction) not in endpoints])
            tree = cKDTree(environment)
            options = []
            for count in range(1, max_bases+1):
                local = junction_component(model, link, sites, count)
                current = local_metrics(local)
                result = close_component(local, environment=environment)
                candidate = local_metrics(local)
                distances, _ = tree.query(np.array([[a.x, a.y, a.z] for a in local.atoms]))
                candidate['external_min_distance_nm'] = float(distances.min())
                candidate['external_clashes'] = int((distances < .08).sum())
                if not np.isfinite(candidate['max_flexible_covalent_nm']):
                    raise ValueError('Nonfinite closure candidate.')
                options.append({'count': count, 'current': current, 'candidate': candidate, 'solver': result})
            row = {'from_helix_label': labels[link.three_prime_helix_id], 'from_bp': link.three_prime_bp,
                   'to_helix_label': labels[link.five_prime_helix_id], 'to_bp': link.five_prime_bp,
                   'recorded_insert_count': len(link.extra_bases),
                   'options': options}
            junctions.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != 'options'}), flush=True)
        assert design.model_dump_json() == before
        return {'lattice': lattice.value, 'cross_section': cross_section,
            'design_sha256': hashlib.sha256(before.encode()).hexdigest(),
            'recorded_commands': list(command_rows(design, 2000)), 'proof': proof,
            'candidate_program': 'experiments.corner_seam_closure.ComponentClosure',
            'unapproved': True,
            'limitations': ['Component alternatives only; source insertion counts unchanged.',
                           'Native duplex atom contacts are screened; other insert seams and external ring piercings are not.',
                           'Terminal gamma is not preserved; production placement is unchanged.',
                           'No phase sweep, A/B visual artifact, or publication approval.'],
            'junctions': junctions}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--lattice', choices=['HONEYCOMB', 'SQUARE'], default='HONEYCOMB')
    parser.add_argument('--cross-section', choices=['2hb', 'bundle'], default='2hb')
    parser.add_argument('--max-bases', type=int, default=8)
    args = parser.parse_args()
    report = audit(LatticeType(args.lattice), cross_section=args.cross_section, max_bases=args.max_bases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
