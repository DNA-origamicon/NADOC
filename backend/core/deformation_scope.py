"""Exact, persisted selection membership around the existing deformation evaluator.

A scope is a union of strand-direction intervals, never a helix-level hint.
Geometry partitions by the ordered operations affecting each nucleotide and uses
unchanged frame mathematics for each partition. Old operations have scope=None.
"""
from collections import defaultdict

import numpy as np

from backend.core.models import DeformationRange, Direction


def resolve_deformation_targets(design, targets):
    if not targets:
        raise ValueError('Select at least one cluster, strand, or domain')
    strands = {s.id: s for s in design.strands}
    helices = {h.id: h for h in design.helices}
    clusters = {c.id: c for c in design.cluster_transforms}
    ranges = {}

    def domain(sid, index):
        s = strands.get(sid)
        if s is None or not isinstance(index, int) or index < 0 or index >= len(s.domains):
            raise ValueError('Selected domain no longer exists')
        d = s.domains[index]
        if d.helix_id not in helices:
            raise ValueError('Selected domain has no helix geometry')
        r = DeformationRange(helix_id=d.helix_id, start_bp=min(d.start_bp, d.end_bp),
                             end_bp=max(d.start_bp, d.end_bp), direction=d.direction,
                             strand_id=sid, domain_index=index)
        ranges[(sid, index)] = r

    for ref in targets:
        kind = ref.get('kind')
        if kind == 'domain':
            domain(ref.get('strandId', ref.get('strand_id')), ref.get('domainIndex', ref.get('domain_index')))
        elif kind == 'strand':
            s = strands.get(ref.get('id'))
            if s is None:
                raise ValueError('Selected strand no longer exists')
            for i in range(len(s.domains)):
                domain(s.id, i)
        elif kind == 'cluster':
            c = clusters.get(ref.get('id'))
            if c is None:
                raise ValueError('Selected cluster no longer exists')
            if c.domain_ids:
                for d in c.domain_ids:
                    domain(d.strand_id, d.domain_index)
            else:
                for hid in c.helix_ids:
                    h = helices.get(hid)
                    if h is None:
                        raise ValueError('Selected cluster helix no longer exists')
                    for direction in (Direction.FORWARD, Direction.REVERSE):
                        ranges[(hid, direction)] = DeformationRange(
                            helix_id=hid, start_bp=h.bp_start, end_bp=h.bp_start + h.length_bp - 1,
                            direction=direction)
        else:
            raise ValueError('Bend and Twist support clusters, strands, and domains')
    if not ranges:
        raise ValueError('Selection contains no deformable nucleotides')
    return list(ranges.values())


def scoped(design):
    return any(op.target_ranges is not None for op in design.deformations)


def membership_classifier(design):
    """Index and merge intervals once per evaluation, rather than scan per atom."""
    from bisect import bisect_right

    scopes = []
    for op in design.deformations:
        grouped = defaultdict(list)
        if op.target_ranges is not None:
            for r in op.target_ranges:
                grouped[(r.helix_id, r.direction)].append((r.start_bp, r.end_bp))
        indexed = {}
        for key, intervals in grouped.items():
            merged = []
            for lo, hi in sorted(intervals):
                if merged and lo <= merged[-1][1] + 1:
                    merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
                else:
                    merged.append((lo, hi))
            indexed[key] = ([lo for lo, _ in merged], [hi for _, hi in merged])
        scopes.append((set(op.affected_helix_ids), op.target_ranges is None, indexed))

    def classify(hid, bp, direction):
        result = []
        for i, (helices, legacy, indexed) in enumerate(scopes):
            if helices and hid not in helices:
                continue
            if legacy:
                result.append(i)
            elif (hid, direction) in indexed:
                starts, ends = indexed[(hid, direction)]
                j = bisect_right(starts, bp) - 1
                if j >= 0 and bp <= ends[j]:
                    result.append(i)
        return tuple(result)
    return classify


def partition_design(design, key):
    # Remove scopes only inside this private evaluation view; no topology mutation.
    selected = set(key)
    return design.copy_with(deformations=[op.model_copy(update={'target_ranges': None})
        for i, op in enumerate(design.deformations)
        if i in selected or op.target_ranges is None])


def selected_arrays(helix, design, evaluate):
    classify = membership_classifier(design)
    baseline = evaluate(partition_design(design, ()))
    groups = defaultdict(list)
    for j, (bp, direction) in enumerate(zip(baseline['bp_indices'], baseline['directions'])):
        key = classify(helix.id, int(bp), Direction.FORWARD if direction == 0 else Direction.REVERSE)
        if key:
            groups[key].append(j)
    result = {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in baseline.items()}
    for key, indices in groups.items():
        candidate = evaluate(partition_design(design, key))
        for name, value in candidate.items():
            if isinstance(value, np.ndarray) and value.shape == result[name].shape:
                result[name][indices] = value[indices]
    return result


def selected_atoms(atoms, design, evaluate):
    classify = membership_classifier(design)
    groups = defaultdict(list)
    for atom in atoms:
        direction = Direction.FORWARD if atom.direction == 'FORWARD' else Direction.REVERSE
        groups[classify(atom.helix_id, atom.bp_index, direction)].append(atom)
    for key, group in groups.items():
        evaluate(group, partition_design(design, key))


def selected_axes(design, evaluate):
    """Separate axis owners when the two strands have different deformation scopes."""
    cache = {}
    classify = membership_classifier(design)

    def axes(key):
        if key not in cache:
            cache[key] = {a['helix_id']: a for a in evaluate(partition_design(design, key))}
        return cache[key]

    baseline = axes(())
    strands = {s.id: s for s in design.strands}
    result = []
    for hid, entry in baseline.items():
        segments = []
        for seg in entry.get('segments', []):
            owners = seg.get('domain_ids') or [{'strand_id': seg['strand_id'], 'domain_index': seg['domain_index']}]
            grouped = defaultdict(list)
            for owner in owners:
                s = strands.get(owner['strand_id'])
                d = s.domains[owner['domain_index']] if s else None
                direction = d.direction if d else Direction.FORWARD
                key = classify(hid, seg['bp_lo'], direction)
                grouped[key].append(owner)
            for key, members in grouped.items():
                source = axes(key)[hid]
                candidate = next((x for x in source['segments'] if x['bp_lo'] == seg['bp_lo'] and x['bp_hi'] == seg['bp_hi']), seg)
                segments.append({**candidate, **members[0], 'domain_ids': members, 'samples': source['samples']})
        # Overall helix axis remains a reference; per-domain segments are authoritative.
        representative = max((value[hid] for value in cache.values()), key=lambda a: len(a['samples']), default=entry)
        result.append({**representative, 'segments': segments})
    return result


def selection_boundary_warning(design, ranges):
    """Report authored selection boundaries without extending movement to neighbors."""
    if ranges is None:
        return None
    # A temporary operation is enough to reuse the exact membership classifier.
    from backend.core.models import DeformationOp, TwistParams
    view = design.copy_with(deformations=[DeformationOp(type='twist', plane_a_bp=0,
        plane_b_bp=1, params=TwistParams(total_degrees=0), target_ranges=ranges)])
    selected = membership_classifier(view)
    boundaries = 0
    for strand in design.strands:
        for left, right in zip(strand.domains, strand.domains[1:]):
            left_bp = max(left.start_bp, left.end_bp) if left.direction == Direction.FORWARD else min(left.start_bp, left.end_bp)
            right_bp = min(right.start_bp, right.end_bp) if right.direction == Direction.FORWARD else max(right.start_bp, right.end_bp)
            if bool(selected(left.helix_id, left_bp, left.direction)) != bool(selected(right.helix_id, right_bp, right.direction)):
                boundaries += 1
    if not boundaries:
        return None
    return {'status': 'warn', 'message': f'{boundaries} strand connection(s) cross the selection boundary. '
            'Bending or twisting may strain these connections; unselected nucleotides stay fixed.'}


def measured_arrays(helix, design, compact_skips, phase_roll_rad, axis_cache=None):
    """Keep existing display placement independent for each operation partition.

    The measured-placement guard tests both strands against an axis. Feeding it
    strands with different transforms would change placement even on the stationary
    partner. Evaluate the existing guard in each coherent frame, then select rows.
    No measured landmarks or molecular placement constants change.
    """
    from backend.core.constants import HELIX_RADIUS
    from backend.core.deformation import deformed_nucleotide_arrays, deformed_helix_axes, effective_helix_for_geometry
    from backend.core.measured_positioning import apply_measured_positioning

    if axis_cache is None:
        axis_cache = {}

    def evaluate(view):
        arrs = deformed_nucleotide_arrays(helix, view, compact_skips=compact_skips, phase_roll_rad=phase_roll_rad)
        if effective_helix_for_geometry(helix, view).native_residues:
            return arrs
        key = tuple(op.id for op in view.deformations)
        if key not in axis_cache:
            axis_cache[key] = {a['helix_id']: a for a in deformed_helix_axes(view)}
        axis = axis_cache[key].get(helix.id)
        if axis is None:
            return arrs
        start = np.asarray(axis['start'])
        tangent = np.asarray(axis['end']) - start
        length = np.linalg.norm(tangent)
        if length <= 1e-12:
            return arrs
        return apply_measured_positioning(arrs, axis_origin=start, axis_hat=tangent / length, legacy_radius=HELIX_RADIUS)
    return selected_arrays(helix, design, evaluate)
