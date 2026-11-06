"""Cluster crossover thinning and length-based temperature ordering.

This optimizes estimated cluster medians, not cooperative folding kinetics.
The complete deterministic policy is executed inside recorded full-autostaple.
"""
from statistics import median

from backend.core.cluster_reconcile import _build_coverage_map
from backend.core.models import StrandType
from backend.core.sequences import assign_staple_sequences
from backend.core.staple_length_limit import enforce_staple_maximum, staple_lengths
from backend.core.staple_thermodynamics import estimate_staple_temperatures


class ClusterCrossoverPolicy:
    """Marras 2016 mechanism: remove selected crossovers in the early component.

    Our HC adaptation retains alternate 21-bp repeats (42 bp) in the earliest
    stage, and every repeat (21 bp) in later stages. Undefined/interface sites
    use the caller's baseline. This is not an assertion that the paper prescribes
    a universal 42-bp interval. Temperature verification follows actual routing.
    """
    def __init__(self, source, policy, *, regional=False):
        clusters, stages, coverage = folding_scope(source, regional=regional)
        self.clusters, self.coverage = clusters, coverage
        self.first_stage, self.default = stages[0], policy
        self.early = policy.model_copy(update={'crossover_repeat_bp': 42})
        self.late = policy.model_copy(update={'crossover_repeat_bp': 21})

    def for_boundary(self, lower_bp, helix_ids):
        if not helix_ids:
            return self.default
        for cluster in self.clusters:
            coverage = self.coverage[cluster.id]
            if all(_covers_interval(coverage.get(hid, []), lower_bp, lower_bp+1) for hid in helix_ids):
                return self.early if cluster.folding_order == self.first_stage else self.late
        return self.default


def _contains(coverage, domain):
    claim = coverage.get(domain.helix_id, [])
    return _covers_interval(claim, *sorted((domain.start_bp, domain.end_bp)))


def _covers_interval(claim, lo, hi):
    if claim == 'whole':
        return True
    cursor = lo
    for a, b in sorted(claim):
        if a > cursor:
            break
        cursor = max(cursor, b+1)
    return cursor > hi


def _members(design, coverage, clusters):
    members = {c.id: set() for c in clusters}
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or strand.is_reference or not strand.domains:
            continue
        owners = [c for c in clusters if all(_contains(coverage[c.id], d) for d in strand.domains)]
        if len({c.folding_order for c in owners}) > 1:
            raise ValueError('Folding-order clusters overlap with different stages. Resolve their membership first.')
        # A staple must be entirely inside a cluster to contribute to its
        # temperature objective; connectors are reported separately.
        for cluster in owners:
            members[cluster.id].add(strand.id)
    return members


def _statistics(design, coverage, clusters):
    members = _members(design, coverage, clusters)
    temperatures = estimate_staple_temperatures(design)
    rows = []
    for c in clusters:
        ids = members[c.id]
        if not ids:
            raise ValueError(f'Cluster {c.name or c.id} has no wholly contained staples to score.')
        unknown = [sid for sid in ids if temperatures.get(sid) is None]
        if unknown:
            raise ValueError(f'Cluster {c.name or c.id} has {len(unknown)} staples without a supported Tfold estimate. '
                             'Check scaffold sequences, ambiguous pairing and unsupported junctions.')
        values = [temperatures[sid] for sid in sorted(ids)]
        rows.append({'cluster_id': c.id, 'name': c.name or c.id, 'stage': c.folding_order,
                     'count': len(values), 'median_c': median(values), 'min_c': min(values), 'max_c': max(values)})
    return rows, members


def folding_scope(source, *, regional=False):
    if regional:
        raise ValueError('Folding-order routing requires the entire part so every assigned cluster can be evaluated.')
    clusters = [c for c in source.cluster_transforms if c.folding_order is not None]
    stages = sorted({c.folding_order for c in clusters})
    if len(stages) < 2:
        raise ValueError('Assign at least two distinct folding stages before routing by folding order.')
    coverage = _build_coverage_map(source)
    # Partial overlaps between different stages are also ambiguous, even when
    # no single staple happens to fit entirely inside both clusters.
    for c in clusters:
        for other in source.cluster_transforms:
            if c.id == other.id or c.folding_order == other.folding_order:
                continue
            for hid in coverage[c.id].keys() & coverage[other.id].keys():
                a, b = coverage[c.id][hid], coverage[other.id][hid]
                if a == 'whole' or b == 'whole' or any(x <= v and u <= y for x, y in a for u, v in b):
                    raise ValueError('Folding-order clusters overlap with different stages or Undefined. Resolve their membership first.')
    return clusters, stages, coverage


def route_folding_order(source, design, policy, *, regional=False):
    """Verify routed medians, adding native nicks to later stages when needed.

    The incoming topology already uses cluster-specific crossover thinning.
    Its connectors are excluded from length optimization; manual/protected
    strands remain protected by the existing native nick policy.
    """
    from backend.api.generation_progress import report as progress

    clusters, stages, coverage = folding_scope(source, regional=regional)
    before, _ = _statistics(design, coverage, clusters)
    result, previous_floor, plans = design, None, []
    for stage in stages:
        group = [c for c in clusters if c.folding_order == stage]
        rows, members = _statistics(result, coverage, group)
        ceiling = None if previous_floor is None else previous_floor-policy.temperature_gap_c
        selected_cap, added_nicks = None, 0
        if ceiling is not None and max(r['median_c'] for r in rows) > ceiling:
            target = set().union(*members.values())
            lengths, _ = staple_lengths(result)
            keep = frozenset(lengths.keys()-target)
            longest = max(lengths[sid] for sid in target)
            # Seven-base increments respect the existing nick safety margins;
            # 21 nt is the lowest length cap supported by the autostaple UI.
            caps = sorted({21, *range(28, min(longest, 300), 7)}, reverse=True)
            last_error = ''
            for cap in caps:
                progress('Route folding order', f'Stage {stage}: testing {cap} nt cap', 0.47)
                try:
                    candidate, report = enforce_staple_maximum(result, cap, kept_ids=keep,
                                                               minimum=min(policy.min_length, cap))
                    assigned = assign_staple_sequences(candidate)
                    originals = {s.id: s for s in result.strands if s.id in keep}
                    candidate = assigned.copy_with(strands=[originals.get(s.id, s) for s in assigned.strands])
                    candidate_rows, _ = _statistics(candidate, coverage, group)
                except ValueError as exc:
                    last_error = str(exc)
                    continue
                if max(r['median_c'] for r in candidate_rows) <= ceiling:
                    result, rows = candidate, candidate_rows
                    selected_cap, added_nicks = cap, report['added_nicks']
                    break
            else:
                detail = f' {last_error}' if last_error else ''
                raise ValueError(f'Cannot achieve the requested {policy.temperature_gap_c:g} °C median Tfold gap '
                                 f'for stage {stage} using supported staple lengths (21–300 nt). '
                                 f'Target median ≤ {ceiling:.2f} °C. Routing was not applied.{detail}')
        previous_floor = min(r['median_c'] for r in rows)
        plans.append({'stage': stage, 'crossover_repeat_bp': 42 if stage == stages[0] else 21,
                      'length_cap_nt': selected_cap, 'added_nicks': added_nicks})
    after, members = _statistics(result, coverage, clusters)
    all_ids = set(staple_lengths(result)[0])
    assigned_ids = set().union(*members.values())
    return result, {'metric': 'cluster_median_tfold', 'gap_c': policy.temperature_gap_c,
                    'magnesium_m': 0.010, 'staple_m': 200e-9, 'before': before, 'clusters': after,
                    'stages': plans, 'default_routed_staples': len(all_ids-assigned_ids)}
