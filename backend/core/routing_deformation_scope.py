"""Inherit endpoint deformation membership during recorded scaffold routing.

This is a routing state transition, not a new deformation formula or a live
selection expansion. Existing ranges and unselected strands remain unchanged.
"""
from backend.core.models import DeformationRange

VERSION = 1
PARAM = 'inherit_scaffold_end_deformations'


def _intervals(design):
    grouped = {}
    for strand in design.scaffolds():
        if strand.is_reference:
            continue
        for domain in strand.domains:
            key = domain.helix_id, domain.direction
            grouped.setdefault(key, []).append(tuple(sorted((domain.start_bp, domain.end_bp))))
    for key, spans in grouped.items():
        merged = []
        for lo, hi in sorted(spans):
            if merged and lo <= merged[-1][1] + 1:
                merged[-1] = merged[-1][0], max(hi, merged[-1][1])
            else:
                merged.append((lo, hi))
        grouped[key] = merged
    return grouped


def inherit_scaffold_ends(before, after):
    """Only new terminal scaffold runs inherit their existing root's membership."""
    from backend.core.deformation_scope import membership_classifier

    if not any(op.target_ranges is not None for op in before.deformations):
        return after
    old, new = _intervals(before), _intervals(after)
    classify = membership_classifier(before)
    additions = {}
    for (hid, direction), spans in old.items():
        # Interior gaps are deliberate selections/topology, not terminal growth.
        first, last = spans[0][0], spans[-1][1]
        for lo, hi in new.get((hid, direction), []):
            growth = []
            if lo < first <= hi:
                growth.append((lo, first - 1, first))
            if lo <= last < hi:
                growth.append((last + 1, hi, last))
            for start, end, root in growth:
                for index in classify(hid, root, direction):
                    if before.deformations[index].target_ranges is not None:
                        additions.setdefault(before.deformations[index].id, []).append(
                            DeformationRange(helix_id=hid, direction=direction,
                                             start_bp=start, end_bp=end))
    return after.copy_with(deformations=[
        op.model_copy(update={'target_ranges': [*op.target_ranges, *additions[op.id]]})
        if op.id in additions else op for op in after.deformations
    ])


def has_inherited_routing(log):
    return any(getattr(entry, 'params', {}).get(PARAM) == VERSION for entry in log)


def recover_scopes(operations, snapshot_operations):
    """Routing snapshots own later scope additions; Bend rows own parameters."""
    saved = {op.id: op for op in snapshot_operations}
    return [op.model_copy(update={'target_ranges': saved[op.id].target_ranges})
            if op.id in saved else op for op in operations]
