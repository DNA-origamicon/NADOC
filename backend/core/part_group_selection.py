"""Typed organizational selectors around the unchanged native scope resolver.

Named group targets remain authoring inputs. Each owned replay resolves their
current membership and stores native ranges on the resulting operation. Neither
the group name nor equal identity text selects a numerical placement owner.
Legacy target-only calls retain the original native resolution behavior.
"""

from backend.core import models as m
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_group_model import GroupOrganization, PartGroup
from backend.core.part_operation_input import MAX_OPERATION_NODES, validate_operation_input


MAX_ITEMS = 30_000
MAX_BYTES = 2_000_000
MAX_ID_CHARS = 512


def _invalid(detail, code="invalid_deformation_selection"):
    raise CommandContractError(detail, code=code)


def _identity(value):
    if type(value) is not str or not 1 <= len(value) <= MAX_ID_CHARS:
        _invalid("Deformation selectors require bounded nonempty identities")
    return value


def has_part_group_targets(targets):
    """Bound detection without reinterpreting existing native target grammar."""
    if type(targets) is not list:
        return False
    if len(targets) > MAX_OPERATION_NODES:
        _invalid("Deformation target count exceeds its input allowance", "group_selection_limit")
    return any(type(target) is dict and target.get("kind") == "part_group" for target in targets)


def _parse(targets):
    try:
        validate_operation_input(targets)
    except ValueError as error:
        _invalid(str(error))
    if type(targets) is not list or not targets:
        _invalid("Select at least one organizational group, placement, strand, or domain")
    parsed, group_ids = [], set()
    for target in targets:
        if type(target) is not dict or type(target.get("kind")) is not str:
            _invalid("Deformation targets require a closed typed selector")
        kind = target["kind"]
        if kind in {"part_group", "cluster", "strand"} and set(target) == {"kind", "id"}:
            identity = _identity(target["id"])
            if kind == "part_group":
                if identity in group_ids:
                    _invalid("Select each organizational group once")
                group_ids.add(identity)
            parsed.append({"kind": kind, "id": identity})
        elif kind == "domain" and set(target) in (
                {"kind", "strand_id", "domain_index"}, {"kind", "strandId", "domainIndex"}):
            identity = _identity(target.get("strand_id", target.get("strandId")))
            index = target.get("domain_index", target.get("domainIndex"))
            if type(index) is not int or index < 0 or index.bit_length() > 64:
                _invalid("Deformation domain selectors require a nonnegative integer ordinal")
            parsed.append({"kind": kind, "strand_id": identity, "domain_index": index})
        else:
            _invalid("Deformation target fields or kind are unsupported")
    return parsed


def target_references(targets):
    """Bounded command-only references; no Design, geometry or source traversal."""
    if targets is None:
        return frozenset()
    return frozenset(("strand", target["strand_id"]) if target["kind"] == "domain"
                     else (target["kind"], target["id"]) for target in _parse(targets))


def _reference(kind, identity, path, *, invalid=False, detail=None):
    raise ReferenceResolutionError(
        detail or ("Deformation selection is ambiguous or empty" if invalid else
                   "Deformation selection refers to a missing object"),
        code="invalid_selection" if invalid else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )


def resolve_deformation_targets(design, targets, *, checkpoint=lambda: None):
    """Resolve an owned source into independently owned native range records.

    Whole-helix groups use the existing cluster resolver's two full-span range
    records, including currently unoccupied strand directions. Domain-backed
    groups retain domain precedence and delegate their primitive intervals to
    the native resolver. No axes, atoms, history, or placement matrices are read.
    """
    from backend.core.deformation_scope import resolve_deformation_targets as native
    from backend.core.part_group_organization import _bounded_groups

    checkpoint()
    if not has_part_group_targets(targets):
        if targets == []:
            _invalid("Select at least one deformation target")
        return native(design, targets)
    parsed = _parse(targets)
    organization = design.group_organization
    if (type(organization) is not GroupOrganization or type(organization.version) is not int
            or organization.version != 1):
        _invalid("Organizational selection requires explicit group organization version 1")
    budget = GraphBudget(max_nodes=MAX_ITEMS, max_bytes=MAX_BYTES, seconds=None, clock=lambda: 0)
    try:
        collections = ((design.helices, "helix", m.Helix),
                       (design.strands, "strand", m.Strand),
                       (design.cluster_transforms, "cluster", m.ClusterRigidTransform))
        if (any(not isinstance(items, list) for items, _, _ in collections)
                or type(organization.groups) is not list
                or sum(len(items) for items, _, _ in collections) + len(organization.groups) > MAX_ITEMS):
            _invalid("Deformation source exceeds its metadata item allowance", "group_selection_limit")
        _bounded_groups(organization, budget=budget)

        def index(items, kind, model):
            result = {}
            for item in items:
                checkpoint()
                if type(item) is not model:
                    _invalid("Deformation source contains unsupported typed metadata")
                identity = _identity(item.id)
                budget.charge(identity)
                if identity in result:
                    _reference(kind, identity, ["source", kind], invalid=True)
                result[identity] = item
            return result

        helices, strands, placements = (index(*values) for values in collections)
        groups = index(organization.groups, "part_group", PartGroup)
        order, full_ranges, primitive = {}, {}, {}

        def helix(identity, path):
            checkpoint()
            identity = _identity(identity)
            record = helices.get(identity)
            if record is None:
                _reference("helix", identity, path)
            if (type(record.bp_start) is not int or type(record.length_bp) is not int
                    or record.length_bp <= 0 or record.bp_start.bit_length() > 64
                    or record.length_bp.bit_length() > 64):
                _invalid("Selected helix requires a positive bounded native span")
            for direction in (m.Direction.FORWARD, m.Direction.REVERSE):
                values = {"helix_id": identity, "start_bp": record.bp_start,
                    "end_bp": record.bp_start + record.length_bp - 1, "direction": direction,
                    "strand_id": None, "domain_index": None}
                budget.charge(values)
                key = identity, direction
                order.setdefault(key, None)
                full_ranges.setdefault(key, m.DeformationRange(**values))

        def domain(identity, ordinal, path):
            checkpoint()
            identity = _identity(identity)
            record = strands.get(identity)
            if record is None:
                _reference("strand", identity, path)
            if (type(record.domains) is not list or len(record.domains) > MAX_ITEMS
                    or type(ordinal) is not int or not 0 <= ordinal < len(record.domains)):
                _reference("strand", identity, path, detail="Selected domain no longer exists")
            member = record.domains[ordinal]
            if type(member) is not m.Domain:
                _invalid("Selected domain requires reviewed native metadata")
            helix_id = _identity(member.helix_id)
            if helix_id not in helices:
                _reference("helix", helix_id, path)
            if (type(member.start_bp) is not int or type(member.end_bp) is not int
                    or member.start_bp.bit_length() > 64 or member.end_bp.bit_length() > 64
                    or type(member.direction) is not m.Direction):
                _invalid("Selected domain requires bounded native interval metadata")
            values = {"kind": "domain", "strand_id": identity, "domain_index": ordinal}
            budget.charge(values)
            budget.charge((member.helix_id, member.start_bp, member.end_bp, member.direction))
            key = identity, ordinal
            order.setdefault(key, None)
            primitive.setdefault(key, values)

        for position, target in enumerate(parsed):
            checkpoint()
            path = ["targets", position]
            kind = target["kind"]
            if kind == "domain":
                domain(target["strand_id"], target["domain_index"], path)
                continue
            identity = target["id"]
            if kind == "strand":
                strand = strands.get(identity)
                if strand is None:
                    _reference("strand", identity, path)
                if type(strand.domains) is not list or len(strand.domains) > MAX_ITEMS:
                    _invalid("Selected strand exceeds its domain allowance", "group_selection_limit")
                if not strand.domains:
                    _reference("strand", identity, path, invalid=True)
                for ordinal in range(len(strand.domains)):
                    domain(identity, ordinal, path)
                continue
            selected = (groups if kind == "part_group" else placements).get(identity)
            if selected is None:
                _reference(kind, identity, path)
            if kind == "cluster":
                _bounded_groups([selected], budget=budget)
            if not selected.domain_ids and not selected.helix_ids:
                _reference(kind, identity, path, invalid=True)
            if selected.domain_ids:
                for ordinal, member in enumerate(selected.domain_ids):
                    domain(member.strand_id, member.domain_index, [*path, "domain_ids", ordinal])
            else:
                for ordinal, identity in enumerate(selected.helix_ids):
                    helix(identity, [*path, "helix_ids", ordinal])
        checkpoint()
        resolved = native(design, list(primitive.values())) if primitive else []
        for item in resolved:
            full_ranges[item.strand_id, item.domain_index] = item
        checkpoint()
        return [full_ranges[key] for key in order]
    except CaptureLimit as error:
        _invalid(str(error), "group_selection_limit")
