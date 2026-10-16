"""Bounded organization ancestry for a closed native topology command set.

Prepare before invoking the admitted builder; apply to its completed output,
after ordinary placement reconciliation and pending-ligation retry. These kinds
conserve/delete directional material, except sweep's separate new helices. They
do not relocate old domains. Consequently disjoint directional intervals give
an exact old-entity ancestry relation without relying on strand IDs, ordinals,
Python object identity, placement proximity, or per-nucleotide expansion.

This is organization metadata only. The native builders, placement owners and
their numerical algorithms remain authoritative. Resize/shift, extrusion and
automatic route replacement require separately qualified lineage contracts.
"""

from bisect import bisect_right
from dataclasses import dataclass

from pydantic import ValidationError

from backend.core.models import Design, Direction, Domain, Helix, Strand
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
from backend.core.part_group_organization import _bounded_groups
from backend.core.part_operation_input import validate_operation_input


KINDS = frozenset({
    "nick", "nick-batch", "ligate", "forced-ligation-create",
    "forced-ligation-delete", "forced-ligation-delete-batch",
    "crossover-delete", "crossover-delete-batch", "strand-delete",
    "strand-delete-batch", "domain-delete", "sweep", "loop-skip-insert",
    "assign-staple-sequences",
})
_REMOVING = frozenset({"strand-delete", "strand-delete-batch", "domain-delete"})
MAX_ITEMS = 30_000
MAX_BYTES = 2_000_000
MAX_ID_CHARS = 512
MAX_RELATIONS = 30_000
MAX_EMITTED_REFS = 30_000


def _fail(detail, code="unsupported_group_lineage_source"):
    raise CommandContractError(detail, code=code)


def _limit():
    _fail("Organization lineage exceeds its metadata work allowance.", "group_lineage_limit")


def _reference(kind, identity, path, *, invalid=False):
    raise ReferenceResolutionError(
        "Organization lineage reference is ambiguous or repeated." if invalid
        else "Organization lineage reference is missing.",
        code="invalid_selection" if invalid else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )


class _Budget:
    def __init__(self):
        self.graph = GraphBudget(max_nodes=MAX_ITEMS, max_bytes=MAX_BYTES,
                                 seconds=None, clock=lambda: 0)
        self.relations = 0
        self.emitted = 0

    def charge(self, value):
        try:
            self.graph.charge(value)
        except CaptureLimit:
            _limit()

    def relation(self):
        self.relations += 1
        if self.relations > MAX_RELATIONS:
            _limit()

    def emit(self, ref):
        self.emitted += 1
        if self.emitted > MAX_EMITTED_REFS:
            _limit()
        self.charge(ref)


def _list(value):
    # Check length before iteration, including a poisoned list subclass.
    if not isinstance(value, list):
        _fail("Organization lineage requires typed lists.")
    if len(value) > MAX_ITEMS:
        _limit()
    if type(value) is not list:
        _fail("Organization lineage requires ordinary typed lists.")
    return value


def _identity(value, budget):
    if type(value) is not str or not 1 <= len(value) <= MAX_ID_CHARS:
        _fail("Organization lineage requires bounded nonempty identities.")
    budget.charge(value)  # Charge before hashing or inserting into an index.
    return value


@dataclass(frozen=True, slots=True)
class _Interval:
    lo: int
    hi: int
    ref: tuple[str, int]


@dataclass(frozen=True, slots=True)
class _Group:
    # Only immutable scalar values survive preparation, never model objects.
    style: tuple
    helices: tuple[str, ...]
    domains: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _Plan:
    kind: str
    helices: frozenset[str]
    intervals: tuple[tuple[tuple[str, Direction], tuple[_Interval, ...]], ...]
    groups: tuple[_Group, ...]


def _inventory(design, budget):
    """Index only scalar identities and directional address intervals."""
    if type(design) is not Design:
        _fail("Organization lineage requires an owned mutable Design.")
    helices = set()
    for index, helix in enumerate(_list(design.helices)):
        if type(helix) is not Helix:
            _fail("Organization lineage requires typed helices.")
        identity = _identity(helix.id, budget)
        if identity in helices:
            _reference("helix", identity, ["helices", index, "id"], invalid=True)
        helices.add(identity)
    strands, intervals, ordered = {}, {}, []
    for index, strand in enumerate(_list(design.strands)):
        if type(strand) is not Strand:
            _fail("Organization lineage requires typed strands.")
        identity = _identity(strand.id, budget)
        if identity in strands:
            _reference("strand", identity, ["strands", index, "id"], invalid=True)
        domains = _list(strand.domains)
        strands[identity] = len(domains)
        budget.charge(len(domains))
        for ordinal, domain in enumerate(domains):
            if type(domain) is not Domain:
                _fail("Organization lineage requires typed domains.")
            hid = _identity(domain.helix_id, budget)
            if hid not in helices:
                _reference("helix", hid, ["strands", index, "domains", ordinal, "helix_id"])
            if (type(domain.direction) is not Direction
                    or type(domain.start_bp) is not int or type(domain.end_bp) is not int
                    or domain.start_bp.bit_length() > 64 or domain.end_bp.bit_length() > 64):
                _fail("Organization lineage requires bounded integer directional addresses.")
            ref = identity, ordinal
            budget.charge((ordinal, domain.start_bp, domain.end_bp))
            record = _Interval(min(domain.start_bp, domain.end_bp),
                               max(domain.start_bp, domain.end_bp), ref)
            key = hid, domain.direction
            intervals.setdefault(key, []).append(record)
            ordered.append((key, record))
    for records in intervals.values():
        records.sort(key=lambda item: (item.lo, item.hi, item.ref))
        for left, right in zip(records, records[1:]):
            if right.lo <= left.hi:
                _fail("Overlapping domains on the same helix and direction have ambiguous ancestry.",
                      "ambiguous_group_lineage")
    return helices, strands, intervals, ordered


def _groups(organization, helices, strands, budget):
    if type(organization) is not GroupOrganization:
        _fail("Organization lineage requires the typed organization wrapper.")
    try:
        _bounded_groups(organization, budget=budget.graph)
    except CommandContractError as error:
        if error.code == "group_organization_limit":
            _limit()
        raise
    result, identities = [], set()
    for index, group in enumerate(organization.groups):
        if type(group) is not PartGroup:
            _fail("Organization lineage requires typed organizational groups.")
        path = ["group_organization", "groups", index]
        identity = _identity(group.id, budget)
        if identity in identities:
            _reference("part_group", identity, [*path, "id"], invalid=True)
        identities.add(identity)
        # Revalidate only bounded scalar style. No model serialization or
        # repeated parsing of the complete source/membership graph is needed.
        try:
            style = PartGroup(id=identity, name=group.name, color=group.color,
                              opacity=group.opacity, is_default=group.is_default,
                              auto_created=group.auto_created)
        except ValidationError as error:
            _fail(f"Invalid organizational group style: {error}")
        selected_helices, selected_domains = [], []
        seen = set()
        for member_index, hid in enumerate(_list(group.helix_ids)):
            _identity(hid, budget)
            if hid not in helices or hid in seen:
                _reference("helix", hid, [*path, "helix_ids", member_index], invalid=hid in seen)
            seen.add(hid)
            selected_helices.append(hid)
        seen.clear()
        for member_index, member in enumerate(_list(group.domain_ids)):
            if type(member) is not GroupDomainRef:
                _fail("Organization lineage requires typed domain selections.")
            sid = _identity(member.strand_id, budget)
            ordinal = member.domain_index
            if type(ordinal) is not int or ordinal < 0 or ordinal.bit_length() > 64:
                _fail("Organization lineage requires nonnegative domain ordinals.")
            ref = sid, ordinal
            if sid not in strands or ordinal >= strands[sid] or ref in seen:
                _reference("domain", f"{sid}:{ordinal}", [*path, "domain_ids", member_index],
                           invalid=ref in seen)
            seen.add(ref)
            selected_domains.append(ref)
        result.append(_Group((style.id, style.name, style.color, style.opacity,
                              style.is_default, style.auto_created),
                             tuple(selected_helices), tuple(selected_domains)))
    return tuple(result)


def prepare_lineage(before, kind, params):
    """Admit before native work and retain detached scalar ancestry metadata.

    Command schemas/reference checks remain the existing dispatcher's job. This
    helper admits only the qualified topology effects, not arbitrary callbacks.
    Legacy designs take the exact no-inventory path.
    """
    if before.group_organization is None:
        return None
    if type(kind) is not str or kind not in KINDS:
        _fail("This command requires a separately qualified organization lineage adapter.",
              "unsupported_group_lineage_command")
    try:
        validate_operation_input(params)
    except ValueError as error:
        _fail(str(error), "group_lineage_limit")
    budget = _Budget()
    helices, strands, intervals, _ = _inventory(before, budget)
    groups = _groups(before.group_organization, helices, strands, budget)
    return _Plan(kind, frozenset(helices),
                 tuple((key, tuple(records)) for key, records in intervals.items()), groups)


def _coverage(records):
    """Canonical union of disjoint intervals, without expanding base addresses."""
    result = []
    for record in records:
        if result and record.lo == result[-1][1] + 1:
            result[-1] = result[-1][0], record.hi
        else:
            result.append((record.lo, record.hi))
    return result


def apply_lineage(plan, final_after_retry):
    """Follow whole final entities independently for every overlapping group."""
    if plan is None:
        return final_after_retry
    if type(plan) is not _Plan:
        _fail("Organization lineage requires its prepared private scalar plan.")
    budget = _Budget()
    helices, _, intervals, ordered = _inventory(final_after_retry, budget)
    old = dict(plan.intervals)
    if plan.kind != "sweep" and helices - plan.helices:
        _fail("This command unexpectedly introduced new helix identities.",
              "unsupported_group_lineage_output")
    if plan.kind not in _REMOVING:
        if not plan.helices <= helices or any(
                _coverage(records) != _coverage(intervals.get(key, ()))
                for key, records in plan.intervals):
            _fail("The native output changed material outside the admitted ancestry contract.",
                  "unsupported_group_lineage_output")
    starts = {key: tuple(record.lo for record in records) for key, records in plan.intervals}
    selected_by = {}
    for group_index, group in enumerate(plan.groups):
        for ref in group.domains:
            budget.charge(ref)
            selected_by.setdefault(ref, []).append(group_index)
    output = [[] for _ in plan.groups]
    for key, final in ordered:
        records = old.get(key, ())
        if not records:
            if plan.kind == "sweep" and key[0] not in plan.helices:
                continue  # A separate new swept domain is not an old descendant.
            _fail("The native output introduced directional material without admitted ancestry.",
                  "unsupported_group_lineage_output")
        index = max(0, bisect_right(starts[key], final.lo) - 1)
        covered, selected = final.lo - 1, set()
        while index < len(records) and records[index].lo <= final.hi:
            ancestor = records[index]
            index += 1
            budget.relation()
            if ancestor.hi < final.lo:
                continue
            if ancestor.lo > covered + 1:
                break
            covered = max(covered, min(final.hi, ancestor.hi))
            for group_index in selected_by.get(ancestor.ref, ()):
                budget.relation()
                selected.add(group_index)
        if covered < final.hi:
            _fail("A final domain extends beyond its admitted directional ancestors.",
                  "unsupported_group_lineage_output")
        for group_index in sorted(selected):
            budget.emit(final.ref)
            output[group_index].append(final.ref)
    groups = []
    for group, domains in zip(plan.groups, output):
        identity, name, color, opacity, default, auto = group.style
        # Nonempty domain selectors have precedence. Losing the last selected
        # descendant must not turn retained helix labels into whole-helix scope.
        members = [] if group.domains and not domains else [hid for hid in group.helices if hid in helices]
        for hid in members:
            budget.emit(hid)
        groups.append(PartGroup(id=identity, name=name, color=color, opacity=opacity,
                                is_default=default, auto_created=auto, helix_ids=members,
                                domain_ids=[GroupDomainRef(strand_id=sid, domain_index=ordinal)
                                            for sid, ordinal in domains]))
    organization = GroupOrganization(groups=groups)
    try:
        _bounded_groups(organization, budget=budget.graph)
    except CommandContractError as error:
        if error.code == "group_organization_limit":
            _limit()
        raise
    return final_after_retry.copy_with(group_organization=organization)
