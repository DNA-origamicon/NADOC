"""Explicit organizational copies around the unchanged placement pattern kernel.

The extraction receipt supplies current domain ancestry. Frozen deformation
strand/ordinal selectors are historical provenance; only their geometric helix
ownership and live named-group roles change for a new pattern instance.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.core import models as m
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_group_model import GroupDomainRef, GroupId, GroupOrganization, PartGroup
from backend.core.part_group_organization import _bounded_groups, _members
from backend.core.part_group_selection import target_references
from backend.core.part_operation_input import validate_operation_input
from backend.core.sweep_model import SweepParams


MAX_GROUPS = 2_000
MAX_ITEMS = 30_000
MAX_BYTES = 2_000_000
_UUID = "00000000-0000-0000-0000-000000000000"


class OrganizationCopy(BaseModel):
    """Versioned explicit group selection; absence remains the legacy contract."""

    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    group_ids: list[GroupId] = Field(max_length=MAX_GROUPS)

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Organization copy requires integer version 1")
        return value

    @field_validator("group_ids")
    @classmethod
    def unique_groups(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Select each organizational group once")
        return value


def _invalid(detail, code="invalid_pattern_organization"):
    raise CommandContractError(detail, code=code)


def _reference(kind, identity, path, *, invalid=False):
    raise ReferenceResolutionError(
        "Pattern organization selection is ambiguous or was not explicitly declared."
        if invalid else "Pattern organization refers to a missing source object.",
        code="invalid_selection" if invalid else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )


def parse_organization_copy(value):
    if value is None:
        return None
    try:
        if type(value) is OrganizationCopy:
            value = vars(value)
        validate_operation_input(value)
        return OrganizationCopy.model_validate(value)
    except (ValidationError, ValueError, TypeError) as error:
        _invalid(str(error))


def _budget():
    return GraphBudget(max_nodes=MAX_ITEMS, max_bytes=MAX_BYTES,
                       seconds=None, clock=lambda: 0)


def _identity(value):
    if type(value) is not str or not 1 <= len(value) <= 512:
        _invalid("Pattern source identities must be bounded nonempty strings.")
    return value


def _list(value):
    if type(value) is not list or len(value) > MAX_ITEMS:
        _invalid("Pattern source exceeds its metadata allowance.", "pattern_organization_limit")
    return value


def _index(items, model, kind, budget):
    result = {}
    for item in _list(items):
        if type(item) is not model:
            _invalid("Pattern source contains unsupported typed metadata.")
        identity = _identity(item.id)
        budget.charge(identity)
        if identity in result:
            _reference(kind, identity, ["source", kind], invalid=True)
        result[identity] = item
    return result


def require_linear_metadata_bounds(design, cluster_ids):
    """Count-only guard before the legacy overlap/reference selection scans.

    Domain objects and helix-member strings are not traversed here. Complete
    source/projection validation remains the one shared copy preflight.
    """
    if type(cluster_ids) is not list or len(cluster_ids) > 128:
        _invalid("Pattern placement count exceeds its allowance.", "pattern_organization_limit")
    for identity in cluster_ids:
        _identity(identity)
    strands, placements = _list(design.strands), _list(design.cluster_transforms)
    if len(strands) + len(placements) > MAX_ITEMS:
        _invalid("Pattern source exceeds its metadata allowance.", "pattern_organization_limit")
    total = 0
    placement_ids = set()
    for records, model, field in ((strands, m.Strand, "domains"),
                                  (placements, m.ClusterRigidTransform, "helix_ids")):
        for record in records:
            if type(record) is not model:
                _invalid("Pattern source contains unsupported typed metadata.")
            if model is m.ClusterRigidTransform:
                placement_ids.add(_identity(record.id))
            total += len(_list(getattr(record, field)))
            if total > MAX_ITEMS:
                _invalid("Pattern source exceeds its member allowance.", "pattern_organization_limit")
    for position, identity in enumerate(cluster_ids):
        if identity not in placement_ids:
            _reference("cluster", identity, ["cluster_ids", position])


def _cost(value):
    budget = _budget()
    budget.charge(value)
    return MAX_ITEMS - budget.remaining[0], MAX_BYTES - budget.remaining[1]


def _reserve(budget, cost, count=1):
    for index, used in enumerate(cost):
        budget.remaining[index] -= used * count
    if min(budget.remaining) < 0:
        raise CaptureLimit("Expanded pattern metadata exceeds its allowance")


def _parameter_cost(params):
    """Count the closed native parameter schemas, including aliased vector rows.

    These three schemas contain scalars, vectors and lists of vectors only.
    Charge each occurrence separately without dumping models or introducing a
    generic recursive walker or any per-nucleotide work.
    """
    if (type(params) not in {m.BendParams, m.TwistParams, SweepParams}
            or len(vars(params)) != len(type(params).model_fields)
            or set(vars(params)) != set(type(params).model_fields)):
        _invalid("Pattern deformation has unsupported parameter metadata.")
    budget = _budget()
    budget.charge(tuple(type(params).model_fields))

    def scalar(value):
        if (value is not None and type(value) not in {str, int, float, bool}
                or type(value) is int and value.bit_length() > 64
                or type(value) is float and not isfinite(value)):
            _invalid("Pattern deformation parameter shape is unsupported.")
        budget.charge(value)

    for value in vars(params).values():
        if type(value) not in {list, tuple}:
            scalar(value)
            continue
        if len(value) > budget.remaining[0]:
            raise CaptureLimit("Expanded pattern parameters exceed their allowance")
        budget.charge([])
        for row in value:
            if type(row) not in {list, tuple}:
                scalar(row)
                continue
            if len(row) > budget.remaining[0]:
                raise CaptureLimit("Expanded pattern parameter vectors exceed their allowance")
            budget.charge([])
            for item in row:
                scalar(item)
    if type(params) is SweepParams:
        for identity in _list(params.preceding_op_ids):
            _identity(identity)
    return MAX_ITEMS - budget.remaining[0], MAX_BYTES - budget.remaining[1]


def _operation_cost(op):
    """Per-occurrence scoped metadata accounting, independent of Python aliases."""
    if (len(vars(op)) != len(m.DeformationOp.model_fields)
            or set(vars(op)) != set(m.DeformationOp.model_fields)):
        _invalid("Pattern deformation has unsupported metadata fields.")
    budget = _budget()
    budget.charge({**vars(op), "targets": None, "target_ranges": None, "params": None,
                   "affected_helix_ids": [], "cluster_ids": []})
    # Distinct fields are separate serialized occurrences even if a local
    # caller reused the same list for numerical and geometric namespaces.
    budget.charge(_list(op.affected_helix_ids))
    budget.charge(_list(op.cluster_ids))
    if op.targets is not None:
        for target in _list(op.targets):
            # Closed source selectors are checked separately for copied ops;
            # this bounded JSON admission also rejects opaque/cyclic metadata.
            validate_operation_input(target)
            budget.charge(target)
    if op.target_ranges is not None:
        for item in _list(op.target_ranges):
            if (type(item) is not m.DeformationRange
                    or len(vars(item)) != len(m.DeformationRange.model_fields)
                    or set(vars(item)) != set(m.DeformationRange.model_fields)):
                _invalid("Pattern deformation requires typed frozen native ranges.")
            # JSON emits the six field names for every range occurrence.
            # Model graph accounting visits values only; charge the already
            # validated storage mapping to include those repeated keys without
            # serializing or copying the range.
            budget.charge(vars(item))
    _reserve(budget, _parameter_cost(op.params))
    return MAX_ITEMS - budget.remaining[0], MAX_BYTES - budget.remaining[1]


@dataclass(frozen=True)
class _GroupProjection:
    source: PartGroup
    helices: tuple[str, ...]
    domains: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class OrganizationPlan:
    groups: tuple[_GroupProjection, ...]
    copied_helices: frozenset[str]
    copied_operation_ids: frozenset[str]


def prepare_organization_copy(design, value, cluster_ids, instance_keys, *, seed,
                              single_cluster=False):
    """Bound source and complete expansion before extraction or native copying.

    No geometry, recovery rows or physical data are traversed. The plan stores
    only source metadata; actual new domain identities come from the one native
    extraction and the corresponding instance maps.
    """
    if type(design.group_organization) is not GroupOrganization:
        _invalid("Explicit pattern organization requires active version 1 organization.")
    command = parse_organization_copy(value)
    if command is None:
        _invalid("Active organization requires an explicit organization-copy contract.")
    _identity(seed)
    if (type(cluster_ids) is not list or not cluster_ids or len(cluster_ids) > 128
            or type(instance_keys) is not list or len(instance_keys) > 127):
        _invalid("Pattern selection or copy count exceeds its allowance.", "pattern_organization_limit")
    for identity in [*cluster_ids, *instance_keys]:
        _identity(identity)
    if len(set(cluster_ids)) != len(cluster_ids) or len(set(instance_keys)) != len(instance_keys):
        _invalid("Pattern placement and instance identities must be unique.")
    try:
        budget = _budget()
        _bounded_groups(design.group_organization, budget=budget)
        helices = _index(design.helices, m.Helix, "helix", budget)
        strands = _index(design.strands, m.Strand, "strand", budget)
        placements = _index(design.cluster_transforms, m.ClusterRigidTransform, "cluster", budget)
        operations = _index(design.deformations, m.DeformationOp, "deformation", budget)
        source_groups = _index(design.group_organization.groups, PartGroup, "part_group", budget)
        for strand in strands.values():
            if type(strand.is_reference) is not bool:
                _invalid("Pattern source requires typed reference-strand metadata.")
            for domain in _list(strand.domains):
                if type(domain) is not m.Domain:
                    _invalid("Pattern source requires typed domains.")
                identity = _identity(domain.helix_id)
                budget.charge(identity)
                if identity not in helices:
                    _reference("helix", identity, ["source", "strands", strand.id])
        # The unchanged native copier examines all overlapping placement owners.
        for placement in placements.values():
            budget.charge(_list(placement.helix_ids))
            _list(placement.domain_ids)
            for identity in placement.helix_ids:
                _identity(identity)
        copied = set()
        for position, identity in enumerate(cluster_ids):
            placement = placements.get(identity)
            if placement is None:
                path = ["cluster_id"] if single_cluster else ["cluster_ids", position]
                _reference("cluster", identity, path)
            copied.update(placement.helix_ids)
        copied -= design.reference_helix_ids()
        if copied - helices.keys():
            _reference("helix", next(iter(copied - helices.keys())), ["cluster_ids"])
        for group in source_groups.values():
            # Validate after bounded accounting, including mutated internal
            # scalar values which Pydantic instance validation would trust.
            PartGroup.model_validate(vars(group))
            for member in group.domain_ids:
                GroupDomainRef.model_validate(vars(member))
            _members(group, helices, strands, ["source", "part_group", group.id])
        selected = []
        for position, identity in enumerate(command.group_ids):
            group = source_groups.get(identity)
            if group is None:
                _reference("part_group", identity, ["_organization_copy", "group_ids", position])
            domain_keys = tuple((ref.strand_id, ref.domain_index) for ref in group.domain_ids
                if strands[ref.strand_id].domains[ref.domain_index].helix_id in copied)
            helix_ids = tuple(identity for identity in group.helix_ids if identity in copied)
            if group.domain_ids and not domain_keys:
                helix_ids = ()  # An empty domain projection must never become whole-helix membership.
            selected.append(_GroupProjection(group, helix_ids, domain_keys))
        copies = len(instance_keys)
        if len(source_groups) + len(selected) * copies > MAX_GROUPS:
            _invalid("Pattern copies exceed the organizational group count.", "pattern_organization_limit")
        output = _budget()
        _bounded_groups(design.group_organization, budget=output)
        ref_cost = _cost(GroupDomainRef(strand_id=_UUID, domain_index=0))
        for projection in selected:
            header = {**vars(projection.source), "id": _UUID,
                      "helix_ids": [_UUID] * len(projection.helices), "domain_ids": [],
                      "is_default": False, "auto_created": False}
            _reserve(output, _cost(header), copies)
            _reserve(output, ref_cost, len(projection.domains) * copies)
        declared = set(command.group_ids)
        copied_operation_ids = set()
        for op in operations.values():
            operation_cost = _operation_cost(op)
            _reserve(budget, operation_cost)
            for identity in _list(op.affected_helix_ids):
                _identity(identity)
            if not copied.intersection(op.affected_helix_ids):
                continue
            copied_operation_ids.add(op.id)
            if op.targets is not None and op.target_ranges is None:
                _invalid("Scoped pattern deformation requires its frozen native ranges.",
                         "unsupported_pattern_organization_source")
            references = target_references(op.targets)
            for kind, identity in references:
                if kind == "part_group" and identity not in declared:
                    _reference(kind, identity, ["_organization_copy", "group_ids"],
                               invalid=identity in source_groups)
            if op.target_ranges is not None:
                for item in _list(op.target_ranges):
                    if type(item) is not m.DeformationRange:
                        _invalid("Pattern deformation requires typed frozen native ranges.")
                    _identity(item.helix_id)
                    if (type(item.start_bp) is not int or type(item.end_bp) is not int
                            or max(item.start_bp.bit_length(), item.end_bp.bit_length()) > 64
                            or type(item.direction) is not m.Direction
                            or (item.domain_index is not None and
                                (type(item.domain_index) is not int or item.domain_index < 0
                                 or item.domain_index.bit_length() > 64))):
                        _invalid("Pattern deformation range metadata is malformed.")
                    if item.strand_id is not None:
                        _identity(item.strand_id)
            # Include repeated operation provenance in the pre-allocation work
            # allowance. UUID remapping can lengthen short source identities.
            _reserve(output, operation_cost, copies)
            growth = max(0, len(_UUID) - len(op.id))
            growth += sum(max(0, len(_UUID) - len(identity)) for identity in op.affected_helix_ids)
            if op.target_ranges is not None:
                growth += sum(max(0, len(_UUID) - len(item.helix_id)) for item in op.target_ranges)
            growth += sum(max(0, len(_UUID) - len(identity)) for kind, identity in references if kind == "part_group")
            if type(op.params) is SweepParams:
                growth += sum(max(0, len(_UUID) - len(identity)) for identity in op.params.preceding_op_ids)
            # The copied numerical placement context is one root UUID.
            _reserve(output, (1, 4 * (growth + len(_UUID))), copies)
        occupied = set(source_groups)
        namespace = "/".join(cluster_ids)
        for instance in instance_keys:
            for projection in selected:
                identity = str(uuid5(NAMESPACE_URL,
                    f"{seed}/{namespace}/{instance}/part_group/{projection.source.id}"))
                if identity in occupied:
                    _reference("part_group", identity, ["_organization_copy", "group_ids"], invalid=True)
                occupied.add(identity)
        return OrganizationPlan(tuple(selected), frozenset(copied), frozenset(copied_operation_ids))
    except CaptureLimit as error:
        _invalid(str(error), "pattern_organization_limit")
    except ValidationError as error:
        _invalid(str(error), "unsupported_pattern_organization_source")


def copy_groups(plan, split_map, hmap, smap, new_id):
    """Project through actual extraction descendants, never domain coincidence."""
    if split_map is None or set(hmap) != plan.copied_helices:
        _invalid("Native extraction changed the admitted copy scope.", "pattern_extraction_mismatch")
    result, group_ids = [], {}
    for projection in plan.groups:
        identity = new_id("part_group", projection.source.id)
        group_ids[projection.source.id] = identity
        references = []
        for key in projection.domains:
            mapped = split_map.get(key)
            if mapped is None or mapped[0] not in smap:
                _invalid("Native extraction omitted a declared copied domain.", "pattern_extraction_mismatch")
            references.append(GroupDomainRef(strand_id=smap[mapped[0]], domain_index=mapped[1]))
        result.append(projection.source.model_copy(deep=True, update={
            "id": identity, "helix_ids": [hmap[identity] for identity in projection.helices],
            "domain_ids": references, "is_default": False, "auto_created": False}))
    return result, group_ids


def copy_deformation(plan, op, hmap, root_id, new_id, group_ids):
    """Keep primitive provenance exact; relocate only live geometric/group roles."""
    owned = op.model_copy(deep=True)
    if owned.targets is not None:
        owned.targets = [{**target, "id": group_ids[target["id"]]}
                         if target["kind"] == "part_group" else target
                         for target in owned.targets]
    if owned.target_ranges is not None:
        owned.target_ranges = [item.model_copy(update={"helix_id": hmap[item.helix_id]})
                               for item in owned.target_ranges if item.helix_id in hmap]
    if type(owned.params) is SweepParams:
        owned.params = owned.params.model_copy(update={"preceding_op_ids": [
            new_id("deformation", identity) if identity in plan.copied_operation_ids else identity
            for identity in owned.params.preceding_op_ids]})
    return owned.model_copy(update={"id": new_id("deformation", op.id),
        "affected_helix_ids": [hmap[identity] for identity in sorted(set(op.affected_helix_ids) & hmap.keys())],
        "cluster_ids": [root_id]})
