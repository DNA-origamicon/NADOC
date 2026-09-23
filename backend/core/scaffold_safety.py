"""Transactional scaffold routing and identity-based sequence preservation."""
from functools import wraps

from backend.core.sequences import _build_loop_skip_map, domain_bp_range, strand_sequence_length
from backend.core.topology_integrity import domain_order_errors, forced_edge, occupancy_errors, slot


class RoutingIntegrityError(ValueError):
    pass


def sequence_keys(design, strand):
    mods = _build_loop_skip_map(design)
    for dm in strand.domains:
        for bp in domain_bp_range(dm):
            count = 1 if dm.overhang_id or dm.binds_overhang_id else max(0, 1 + mods.get((dm.helix_id, bp), 0))
            for copy in range(count):
                yield (*slot(dm.helix_id, bp, dm.direction), copy)


def preserve_scaffold_sequences(before, after):
    assigned = {}
    for s in before.strands:
        if not s.is_scaffold or s.is_reference or s.sequence is None:
            continue
        if len(s.sequence) != strand_sequence_length(before, s):
            raise RoutingIntegrityError(f"Scaffold {s.id!r} has an inconsistent sequence length; repair it before routing.")
        assigned.update(zip(sequence_keys(before, s), s.sequence))
    if not assigned:
        return after
    strands = []
    for s in after.strands:
        if s.is_scaffold and not s.is_reference:
            keys = list(sequence_keys(after, s))
            if any(k in assigned for k in keys):
                s = s.model_copy(update={"sequence": "".join(assigned.get(k, "N") for k in keys)})
        strands.append(s)
    return after.copy_with(strands=strands)


def _has_backbone_edge(design, edge):
    a, b = edge
    for s in design.strands:
        if s.is_reference:
            continue
        for first, second in zip(s.domains, s.domains[1:]):
            if (slot(first.helix_id, first.end_bp, first.direction),
                    slot(second.helix_id, second.start_bp, second.direction)) == edge:
                return True
        # A same-helix ligation can have merged the adjacent domains.
        if a[0] == b[0] and a[2] == b[2] and b[1] == a[1] + (1 if a[2] == "FORWARD" else -1):
            for dm in s.domains:
                if dm.helix_id == a[0] and dm.direction.value == a[2] and min(dm.start_bp, dm.end_bp) <= min(a[1], b[1]) <= max(a[1], b[1]) <= max(dm.start_bp, dm.end_bp):
                    return True
    return False


def safe_scaffold_route(result_type):
    """Reject an unsafe candidate as a whole, preserving the caller's design."""
    def decorate(fn):
        @wraps(fn)
        def run(design, *args, **kwargs):
            try:
                problems = domain_order_errors(design) or occupancy_errors(design)
                if problems:
                    raise RoutingIntegrityError(problems[0])
                out, result = fn(design.model_copy(deep=True), *args, **kwargs)
                if not result.valid:
                    raise RoutingIntegrityError("; ".join(result.errors))
                problems = domain_order_errors(out) or occupancy_errors(out)
                if problems:
                    raise RoutingIntegrityError(problems[0])
                # Deliberate connections are protected even through hinge-specific
                # routes that temporarily rebuild their own ligation records.
                protected = {forced_edge(fl): fl for fl in design.forced_ligations}
                for edge, fl in protected.items():
                    if not _has_backbone_edge(out, edge):
                        raise RoutingIntegrityError(f"Routing would change forced ligation {fl.id!r}; original design retained.")
                if protected:
                    out = out.copy_with(forced_ligations=[*protected.values(), *[
                        fl for fl in out.forced_ligations if forced_edge(fl) not in protected]])
                out = preserve_scaffold_sequences(design, out)
                return out, result
            except RoutingIntegrityError as exc:
                message = f"Routing rejected; original design retained: {exc}"
                return design, result_type(valid=False, errors=[message], warnings=[message])
        return run
    return decorate


def require_clear_extension(design, strand, domain_index, new_domain):
    """Preflight the complete proposed domain, including other scaffold domains."""
    old = strand.domains[domain_index]
    lo, hi = sorted((new_domain.start_bp, new_domain.end_bp))
    for other in design.strands:
        if other.is_reference:
            continue
        for di, dm in enumerate(other.domains):
            if other.id == strand.id and di == domain_index:
                continue
            if dm.helix_id != old.helix_id or dm.direction != old.direction:
                continue
            if max(lo, min(dm.start_bp, dm.end_bp)) <= min(hi, max(dm.start_bp, dm.end_bp)):
                raise RoutingIntegrityError(f"Scaffold extension on {old.helix_id!r} would overlap {other.id!r} ({dm.start_bp}→{dm.end_bp}, {dm.direction.value}).")
