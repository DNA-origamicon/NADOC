"""Bounded entity correspondence around the unchanged crossover move builder.

Native moves preserve strand IDs and domain order until ordinary reconciliation
and retry. Validate that contract against scalar endpoint edits, then transport
whole source entities atomically to the observed output intervals. No geometry,
lattice-site formula, numerical placement or saved recovery payload is used.
"""

from dataclasses import dataclass

from backend.core.models import Crossover, Direction, HalfCrossover
from backend.core.part_group_lineage import _Budget, _fail, _identity, _inventory, _list


@dataclass(frozen=True, slots=True)
class _Transport:
    domains: tuple
    crossovers: tuple


def _output_error(message):
    _fail(message, "unsupported_group_lineage_output")


def _optional_identity(value, budget):
    return None if value is None else _identity(value, budget)


def _integer(value, budget):
    if type(value) is not int or value.bit_length() > 64:
        _fail("Crossover lineage requires bounded integer endpoints.")
    budget.charge(value)
    return value


def _domains(design, budget):
    # The caller inventories typed strands/domains before this additional pass.
    result = []
    for strand in design.strands:
        records = []
        for domain in strand.domains:
            record = (domain.helix_id, domain.direction, domain.start_bp, domain.end_bp,
                      _optional_identity(domain.overhang_id, budget),
                      _optional_identity(domain.binds_overhang_id, budget))
            budget.charge(record)
            records.append(record)
        result.append((strand.id, tuple(records)))
    return tuple(result)


def _crossovers(design, budget):
    result, identities = [], set()
    for crossover in _list(design.crossovers):
        if type(crossover) is not Crossover:
            _fail("Crossover lineage requires typed crossovers.")
        identity = _identity(crossover.id, budget)
        if identity in identities:
            _fail("Crossover lineage requires unique crossover identities.")
        identities.add(identity)
        halves = []
        for half in (crossover.half_a, crossover.half_b):
            if type(half) is not HalfCrossover or type(half.strand) is not Direction:
                _fail("Crossover lineage requires typed directional endpoints.")
            halves.append((_identity(half.helix_id, budget), half.strand, _integer(half.index, budget)))
        # Preserve the rest of this small model without invoking serialization.
        metadata = (crossover.extra_bases, crossover.process_id)
        if any(value is not None and type(value) is not str for value in metadata):
            _fail("Crossover lineage requires scalar crossover metadata.")
        budget.charge(metadata)
        result.append((identity, *halves, *metadata))
    return tuple(result)


def _check_growth_metadata(design, originals, records, changed):
    helices = {helix.id: helix for helix in design.helices}
    original_by_id = dict(originals)
    for sid, domains in records:
        for ordinal, domain in enumerate(domains):
            if (sid, ordinal) not in changed:
                continue
            hid, _, start, end, *_ = domain
            old = original_by_id[sid][ordinal]
            helix = helices[hid]
            if (type(helix.bp_start) is not int or type(helix.length_bp) is not int
                    or helix.bp_start.bit_length() > 64 or helix.length_bp.bit_length() > 64):
                _fail("Crossover lineage requires bounded helix extents.")
            # Batch native growth evaluates each edited endpoint against its
            # original opposite endpoint, even if both ends move. The source
            # and final envelope also bounds those intermediate native spans.
            if (min(start, end, old[2], old[3]) >= helix.bp_start
                    and max(start, end, old[2], old[3]) < helix.bp_start + helix.length_bp):
                continue
            # Existing native growth reconstructs Helix without these fields.
            # Keep that legacy numerical path untouched and do not claim this
            # new consumer preserves an authored frame/source it would erase.
            if (helix.lattice_frame_id is not None or helix.label is not None
                    or helix.direction is not None or helix.native_source is not None
                    or helix.native_residues):
                _output_error("Crossover growth cannot yet preserve this helix's frame/source metadata.")


def prepare_crossover_transport(before, kind, params, budget):
    """Index once, resolve exact requested adjacent pairs, retain scalar receipts."""
    domains = _domains(before, budget)
    crossovers = _crossovers(before, budget)
    by_id = {record[0]: record for record in crossovers}
    adjacent = {}
    for sid, records in domains:
        for ordinal, (left, right) in enumerate(zip(records, records[1:])):
            key = (left[0], left[1], left[3]), (right[0], right[1], right[2])
            budget.charge(key)
            adjacent.setdefault(key, []).append((sid, ordinal))
    requests = _list(params.get("moves")) if kind == "crossover-move-batch" else [params]
    moves, endpoints = {}, {}
    for request in requests:
        if type(request) is not dict:
            _fail("Crossover lineage requires typed move inputs.")
        identity = _identity(request.get("crossover_id"), budget)
        index = _integer(request.get("new_index"), budget)
        if identity not in by_id or identity in moves:
            _fail("Crossover lineage requires existing unique move selectors.")
        moves[identity] = index
        _, half_a, half_b, *_ = by_id[identity]
        if half_a[2] != half_b[2]:
            _fail("Crossover lineage requires matching source junction indices.")
        if index == half_a[2]:
            continue
        candidates = set(adjacent.get((half_a, half_b), ())) | set(adjacent.get((half_b, half_a), ()))
        if len(candidates) != 1:
            _fail("Crossover lineage requires one unambiguous adjacent domain pair.",
                  "ambiguous_group_lineage")
        sid, ordinal = candidates.pop()
        for ref, endpoint in [((sid, ordinal), 3), ((sid, ordinal + 1), 2)]:
            edits = endpoints.setdefault(ref, {})
            if endpoint in edits:
                _fail("Two crossover moves cannot claim the same domain endpoint.", "ambiguous_group_lineage")
            edits[endpoint] = index
    expected_domains = []
    for sid, records in domains:
        expected = []
        for ordinal, record in enumerate(records):
            edits = endpoints.get((sid, ordinal), {})
            updated = tuple(edits.get(i, value) for i, value in enumerate(record))
            if edits:
                _, direction, start, end, *_ = updated
                if ((direction == Direction.FORWARD and start > end)
                        or (direction == Direction.REVERSE and start < end)):
                    _output_error("Crossover move would invert a domain's directional endpoints.")
            expected.append(updated)
        expected_domains.append((sid, tuple(expected)))
    _check_growth_metadata(before, domains, expected_domains, endpoints)
    expected_crossovers = tuple((identity,
        (a[0], a[1], moves.get(identity, a[2])),
        (b[0], b[1], moves.get(identity, b[2])), *metadata)
        for identity, a, b, *metadata in crossovers)
    return _Transport(tuple(expected_domains), expected_crossovers)


def finish_crossover_transport(plan, raw_after, source_helices):
    """Bind the native output to its admitted original→final correspondence."""
    if type(plan) is not _Transport:
        _output_error("Crossover transport requires its prepared scalar receipt.")
    budget = _Budget()
    helices, _, intervals, _ = _inventory(raw_after, budget)
    if (helices != source_helices or _domains(raw_after, budget) != plan.domains
            or _crossovers(raw_after, budget) != plan.crossovers):
        _output_error("Native crossover output does not match its admitted domain correspondence.")
    # The refs still identify the source entities here. Reconciliation/retry may
    # now rename/split/merge them; the common final-output interval join handles it.
    return tuple((key, tuple(records)) for key, records in intervals.items())
