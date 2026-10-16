"""Passive scalar contributor tracking for native resize/shift replacements.

Temporary normalization is not an authored union: keep piecewise ancestry until
the final native domains are known. Observations never return geometry or decide
where a native edit happens. The legacy numerical path does not construct this
tracker. Source snapshots and sealed receipts contain only immutable scalars.
"""

from dataclasses import dataclass

from backend.core.models import Direction, Domain
from backend.core.part_group_lineage import _Budget, _Interval, _fail, _identity, _inventory


@dataclass(frozen=True, slots=True)
class _Tracked:
    address: tuple
    pieces: tuple[_Interval, ...]
    start_owner: tuple | None
    end_owner: tuple | None


@dataclass(frozen=True, slots=True)
class _Source:
    strands: tuple


def _error(message):
    _fail(message, "unsupported_group_lineage_output")


def _address(domain, budget):
    if type(domain) is not Domain or type(domain.direction) is not Direction:
        _error("Native domain observations require typed directional domains.")
    hid = _identity(domain.helix_id, budget)
    if any(type(value) is not int or value.bit_length() > 64
           for value in (domain.start_bp, domain.end_bp)):
        _error("Native domain observations require bounded integer endpoints.")
    result = (hid, domain.direction, domain.start_bp, domain.end_bp)
    budget.charge(result)
    return result


def _extent(address):
    _, direction, start, end = address
    if (direction == Direction.FORWARD and start > end
            or direction == Direction.REVERSE and start < end):
        return None  # Temporary inversion is empty, never min/max material.
    return min(start, end), max(start, end)


def prepare_domain_trace(before, budget):
    # Common preparation already bounds/indexes typed source topology/groups.
    strands = []
    for strand in before.strands:
        records = []
        for ordinal, domain in enumerate(strand.domains):
            address = _address(domain, budget)
            extent = _extent(address)
            if extent is None:
                _error("Domain tracing requires ordered source endpoints.")
            ref = (strand.id, ordinal)
            budget.charge(ref)
            records.append(_Tracked(address, (_Interval(*extent, ref),), ref, ref))
        strands.append((strand.id, tuple(records)))
    return _Source(tuple(strands))


def _tracked(address, pieces, budget, *, inverted_owners=(None, None)):
    extent = _extent(address)
    if extent is None:
        return _Tracked(address, (), *inverted_owners)
    lo, hi = extent
    clipped = []
    for piece in pieces:
        budget.relation()
        left, right = max(lo, piece.lo), min(hi, piece.hi)
        if left <= right:
            budget.charge((left, right, piece.ref))
            clipped.append(_Interval(left, right, piece.ref))
    clipped.sort(key=lambda p: (p.lo, p.hi, p.ref))
    joined = []
    for piece in clipped:
        if joined and piece.lo <= joined[-1].hi:
            _error("Observed contributor intervals overlap ambiguously.")
        if joined and piece.lo == joined[-1].hi + 1 and piece.ref == joined[-1].ref:
            joined[-1] = _Interval(joined[-1].lo, piece.hi, piece.ref)
        else:
            joined.append(piece)
    owners = []
    for endpoint in address[2:]:
        budget.relation(len(joined))
        owners.append(next((p.ref for p in joined if p.lo <= endpoint <= p.hi), None))
    return _Tracked(address, tuple(joined), *owners)


class DomainTrace:
    """One private native invocation; never retained on a design or in history."""

    def __init__(self, source):
        if type(source) is not _Source:
            _error("Domain tracing requires its prepared immutable source.")
        self.source = source
        self._strands = {sid: list(records) for sid, records in source.strands}
        self._budget = _Budget()
        self._finished = False

    def _current(self, sid, index, before):
        if self._finished:
            _error("A completed native domain trace cannot be reused.")
        self._budget.relation()
        _identity(sid, self._budget)
        if type(index) is not int or index < 0 or index.bit_length() > 64 or sid not in self._strands:
            _error("Native domain observation names an unknown source entity.")
        domains = self._strands[sid]
        if index + len(before) > len(domains):
            _error("Native domain observation is outside the current strand.")
        current = domains[index:index + len(before)]
        addresses = tuple(_address(domain, self._budget) for domain in before)
        if tuple(item.address for item in current) != addresses:
            _error("Native domain observation does not match its current contributors.")
        return domains, current

    def repartition(self, sid, index, before_domains, after_domains):
        if (type(before_domains) not in (list, tuple) or type(after_domains) not in (list, tuple)
                or (len(before_domains), len(after_domains)) not in {(1, 2), (2, 1)}):
            _error("Native normalization must report its actual merge or split.")
        domains, current = self._current(sid, index, before_domains)
        addresses = tuple(_address(domain, self._budget) for domain in after_domains)
        key = current[0].address[:2]
        if any(item.address[:2] != key for item in current) or any(a[:2] != key for a in addresses):
            _error("Native normalization cannot change contributor helix or direction.")
        self._budget.relation(len(domains))  # Bound cumulative list shifts/copies.
        pieces = tuple(piece for item in current for piece in item.pieces)
        replacements = [_tracked(address, pieces, self._budget) for address in addresses]
        domains[index:index + len(current)] = replacements

    def resize(self, sid, index, old_domain, new_domain, *, end):
        domains, (current,) = self._current(sid, index, [old_domain])
        address = _address(new_domain, self._budget)
        old = current.address
        if (end not in {"5p", "3p"} or address[:2] != old[:2]
                or address[3 if end == "5p" else 2] != old[3 if end == "5p" else 2]):
            _error("Native resize must edit only its declared terminal endpoint.")
        owner = current.start_owner if end == "5p" else current.end_owner
        old_extent, new_extent = _extent(old), _extent(address)
        pieces = list(current.pieces)
        if owner is not None and new_extent is not None:
            lo, hi = new_extent
            if old_extent is None:
                # The same native terminal still exists within this invocation.
                # A later resize can regrow it before normalization removes it.
                pieces.append(_Interval(lo, hi, owner))
            else:
                old_lo, old_hi = old_extent
                if lo < old_lo:
                    pieces.append(_Interval(lo, old_lo - 1, owner))
                if hi > old_hi:
                    pieces.append(_Interval(old_hi + 1, hi, owner))
        domains[index] = _tracked(address, pieces, self._budget,
                                  inverted_owners=(current.start_owner, current.end_owner))

    def translate(self, sid, index, old_domain, new_domain):
        domains, (current,) = self._current(sid, index, [old_domain])
        address = _address(new_domain, self._budget)
        old = current.address
        delta = address[2] - old[2]
        if address[:2] != old[:2] or address[3] - old[3] != delta:
            _error("Native shift must translate both endpoints by the same amount.")
        pieces = []
        for piece in current.pieces:
            self._budget.relation()
            pieces.append(_Interval(piece.lo + delta, piece.hi + delta, piece.ref))
        domains[index] = _tracked(address, pieces, self._budget)

    def finish(self, source, raw_after, source_helices):
        if self._finished or source is not self.source:
            _error("Native domain trace does not belong to this prepared invocation.")
        self._finished = True
        budget = _Budget()
        helices, _, intervals, _ = _inventory(raw_after, budget)
        if helices != source_helices or tuple(self._strands) != tuple(s.id for s in raw_after.strands):
            _error("Native resize/shift changed an undeclared source identity.")
        ancestors = {}
        for strand in raw_after.strands:
            records = self._strands[strand.id]
            if len(records) != len(strand.domains):
                _error("Native resize/shift omitted a domain replacement observation.")
            for domain, record in zip(strand.domains, records):
                address = _address(domain, budget)
                if address != record.address or _extent(address) is None:
                    _error("Native resize/shift output does not match its observed contributors.")
                for piece in record.pieces:
                    budget.relation()
                    budget.charge((piece.lo, piece.hi, piece.ref))
                    ancestors.setdefault(address[:2], []).append(piece)
        for records in ancestors.values():
            records.sort(key=lambda p: (p.lo, p.hi, p.ref))
        ancestry = tuple((key, tuple(records)) for key, records in ancestors.items())
        material = tuple((key, tuple(records)) for key, records in intervals.items())
        return ancestry, material
