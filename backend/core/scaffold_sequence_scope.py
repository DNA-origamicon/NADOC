"""Whole-scaffold assignment scopes shared by authoring and independent replay."""
from backend.core.cluster_reconcile import _build_coverage_map
from backend.core.models import StrandType
from backend.core.sequences import (
    SCAFFOLD_LIBRARY, _resolve_scaffold_strand,
    assign_custom_scaffold_sequence, assign_scaffold_sequence,
)


def resolve_targets(design, *, strand_id=None, cluster_id=None):
    if strand_id is not None and cluster_id is not None:
        raise ValueError('Choose a scaffold strand or a cluster, not both.')
    if cluster_id is None:
        return [_resolve_scaffold_strand(design, strand_id)]
    coverage = _build_coverage_map(design).get(cluster_id)
    if coverage is None:
        raise ValueError('Selected cluster no longer exists.')
    targets = []
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD or strand.is_reference:
            continue
        contained, touches = bool(strand.domains), False
        for domain in strand.domains:
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            claim = coverage.get(domain.helix_id, [])
            if claim == 'whole':
                touches = True
                continue
            touches |= any(a <= hi and lo <= b for a, b in claim)
            cursor = lo
            for a, b in sorted(claim):
                if a > cursor:
                    break
                cursor = max(cursor, b + 1)
            contained &= cursor > hi
        if touches and not contained:
            raise ValueError('A scaffold crosses the selected cluster boundary. Select that scaffold strand explicitly to assign its whole sequence.')
        if contained:
            targets.append(strand)
    if not targets:
        raise ValueError('Selected cluster contains no editable scaffold strands.')
    return targets


def assign_scoped_sequence(design, params):
    targets = resolve_targets(design, strand_id=params.get('strand_id'), cluster_id=params.get('cluster_id'))
    sequence, name = params.get('custom_sequence'), params.get('scaffold_name', 'M13mp18')
    use_custom = bool(sequence and sequence.strip())
    rows = []
    for strand in targets:
        if use_custom:
            design, total, padded = assign_custom_scaffold_sequence(design, sequence, strand_id=strand.id)
        else:
            design, total, padded = assign_scaffold_sequence(design, name, strand_id=strand.id)
        rows.append({'strand_id': strand.id, 'total_nt': total, 'padded_nt': padded})
    length = len(''.join(sequence.split())) if use_custom else next((n for label, n, _ in SCAFFOLD_LIBRARY if label == name), 0)
    return design, {'total_nt': sum(r['total_nt'] for r in rows), 'padded_nt': sum(r['padded_nt'] for r in rows),
                    'scaffold_len': length, 'assigned_strands': rows}
