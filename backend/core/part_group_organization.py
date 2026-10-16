"""Native organization inputs that leave every numerical placement untouched."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_dependencies import Dependencies, Resource
from backend.core.part_group_model import GroupDomainRef, GroupId, GroupOrganization, PartGroup
from backend.core.part_operation_input import validate_operation_input


KINDS = frozenset({"group-organize", "group-create", "group-update", "group-dissolve"})
MEMBERSHIP_FIELDS = frozenset({"helix_ids", "domain_ids"})
EDIT_FIELDS = MEMBERSHIP_FIELDS | {"name", "color", "opacity"}
GROUP_FIELDS = frozenset(PartGroup.model_fields)
ORGANIZATION = Resource("part", "group_organization")
TOPOLOGY = Resource("part", "topology")


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Literal[1] = Field(alias="_proof_version")


class Organize(_Command):
    expected_placement_ids: list[GroupId] = Field(max_length=2_000)


class Create(_Command):
    group: PartGroup


class Update(_Command):
    group_id: GroupId
    fields: dict


class Dissolve(_Command):
    group_ids: list[GroupId] = Field(min_length=1, max_length=128)


_COMMANDS = {"group-organize": Organize, "group-create": Create,
             "group-update": Update, "group-dissolve": Dissolve}


def _invalid(detail, code="invalid_group_organization_input"):
    raise CommandContractError(detail, code=code)


def _reference(kind, identity, path, *, invalid=False):
    raise ReferenceResolutionError(
        "Organizational group reference is ambiguous or repeated." if invalid
        else "Organizational group reference is missing.",
        code="invalid_selection" if invalid else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )


def parse_command(kind, params):
    try:
        validate_operation_input(params)
        if (kind not in KINDS or type(params) is not dict
                or type(params.get("_proof_version")) is not int or params["_proof_version"] != 1):
            _invalid("Organization commands require their closed version 1 inputs.")
        command = _COMMANDS[kind].model_validate(params)
        if isinstance(command, Update):
            if not command.fields or set(command.fields) - EDIT_FIELDS:
                _invalid("Group updates require membership, name or style fields only.")
            # Validate supplied values without a source model or any geometry.
            PartGroup.model_validate({"id": command.group_id, **command.fields})
        ids = (command.expected_placement_ids if isinstance(command, Organize)
               else command.group_ids if isinstance(command, Dissolve) else ())
        if len(set(ids)) != len(ids):
            _invalid("Select unique organizational group or placement identities.")
        return command
    except ValidationError as error:
        _invalid(str(error))
    except ValueError as error:
        if isinstance(error, CommandContractError):
            raise
        _invalid(str(error))


def dependencies(kind, params):
    try:
        command = parse_command(kind, params)
    except (ValueError, TypeError):
        return Dependencies(known=False)
    reads, writes = {ORGANIZATION, TOPOLOGY}, {ORGANIZATION}
    if isinstance(command, Organize):
        reads.update(Resource("cluster", identity) for identity in command.expected_placement_ids)
        writes.update(Resource("part_group", identity) for identity in command.expected_placement_ids)
    elif isinstance(command, Dissolve):
        selected = {Resource("part_group", identity) for identity in command.group_ids}
        reads.update(selected)
        writes.update(selected)
    else:
        if isinstance(command, Create):
            group, identity = command.group, command.group.id
        else:
            identity = command.group_id
            reads.add(Resource("part_group", identity))
            group = PartGroup.model_validate({"id": identity, **command.fields})
        writes.add(Resource("part_group", identity))
        reads.update(Resource("helix", identity) for identity in group.helix_ids)
        reads.update(Resource("strand", ref.strand_id) for ref in group.domain_ids)
    # Domain ordinals and a conversion's complete placement inventory need the
    # existing conservative topology boundary until finer invalidation is proven.
    return Dependencies(frozenset(reads), frozenset(writes), barrier=True)


def _index(items, kind):
    if len(items) > 30_000:
        _invalid("Group source exceeds its metadata item allowance.", "group_organization_limit")
    index = {}
    for item in items:
        if type(item.id) is not str or not 1 <= len(item.id) <= 512:
            _invalid("Group source identities must be bounded nonempty strings.")
        if item.id in index:
            _reference(kind, item.id, ["source", kind], invalid=True)
        index[item.id] = item
    return index


def _members(group, helices, strands, path):
    seen = set()
    for index, identity in enumerate(group.helix_ids):
        if identity not in helices or identity in seen:
            _reference("helix", identity, [*path, "helix_ids", index], invalid=identity in seen)
        seen.add(identity)
    seen.clear()
    for index, ref in enumerate(group.domain_ids):
        key = ref.strand_id, ref.domain_index
        strand = strands.get(ref.strand_id)
        if strand is None or ref.domain_index >= len(strand.domains) or key in seen:
            _reference("strand", ref.strand_id, [*path, "domain_ids", index], invalid=key in seen)
        seen.add(key)


def _bounded_groups(value, *, budget=None):
    from backend.core.part_capture_graph import CaptureLimit, GraphBudget
    from backend.core.models import ClusterRigidTransform, DomainRef

    if type(value) is GroupOrganization:
        if type(value.version) is not int or value.version != 1:
            _invalid("Unsupported group organization version.", "unsupported_group_organization_source")
        groups = value.groups
    else:
        groups = value
    if type(groups) is not list or len(groups) > 2_000:
        _invalid("Group source requires a bounded typed list.", "group_organization_limit")
    if budget is None:
        budget = GraphBudget(max_nodes=30_000, max_bytes=2_000_000, seconds=None, clock=lambda: 0)
    try:
        budget.charge(None)  # Outer collection/wrapper.
        for group in groups:
            if (type(group) not in {PartGroup, ClusterRigidTransform}
                    or set(vars(group)) != set(type(group).model_fields)
                    or type(group.domain_ids) is not list or len(group.domain_ids) > 30_000):
                _invalid("Group source has unsupported metadata.", "unsupported_group_organization_source")
            # Each charge has its own alias memo but shares the cumulative
            # allowance. JSON expands a shared membership list once per group,
            # and expands every repeated DomainRef occurrence too. Charge those
            # occurrences before model_dump, rather than only the unique graph.
            budget.charge({**vars(group), "domain_ids": []})
            member_type = GroupDomainRef if type(group) is PartGroup else DomainRef
            for member in group.domain_ids:
                if type(member) is not member_type or set(vars(member)) != set(member_type.model_fields):
                    _invalid("Group source has unsupported domain metadata.", "unsupported_group_organization_source")
                budget.charge(member)
    except CaptureLimit as error:
        _invalid(str(error), "group_organization_limit")


def build(kind, design, params):
    """Return only a new organization wrapper; never reconcile or place DNA."""
    command = parse_command(kind, params)
    helices = _index(design.helices, "helix")
    strands = _index(design.strands, "strand")
    if isinstance(command, Organize):
        if design.group_organization is not None:
            _invalid("Group organization is already active.", "group_organization_active")
        placements = _index(design.cluster_transforms, "cluster")
        expected, actual = command.expected_placement_ids, list(placements)
        if expected != actual:
            missing = next((identity for identity in expected if identity not in placements), None)
            if missing is not None:
                _reference("cluster", missing, ["expected_placement_ids", expected.index(missing)])
            _invalid("The complete ordered placement selection changed.", "group_placement_selection_changed")
        _bounded_groups(design.cluster_transforms)
        try:
            groups = [PartGroup.model_validate(group.model_dump(include=GROUP_FIELDS))
                      for group in design.cluster_transforms]
        except ValidationError as error:
            _invalid(str(error), "unsupported_group_organization_source")
        for index, group in enumerate(groups):
            _members(group, helices, strands, ["expected_placement_ids", index])
    else:
        organization = design.group_organization
        if organization is None:
            _invalid("Convert grouping before editing organizational groups.", "group_organization_required")
        _bounded_groups(organization)
        try:
            organization = GroupOrganization.model_validate(organization.model_dump())
        except (ValidationError, AttributeError) as error:
            _invalid(str(error), "unsupported_group_organization_source")
        index = _index(organization.groups, "part_group")
        groups = list(organization.groups)
        if isinstance(command, Create):
            if command.group.id in index:
                _reference("part_group", command.group.id, ["group", "id"], invalid=True)
            _members(command.group, helices, strands, ["group"])
            groups.append(command.group)
        elif isinstance(command, Update):
            if command.group_id not in index:
                _reference("part_group", command.group_id, ["group_id"])
            previous = index[command.group_id]
            group = PartGroup.model_validate({**previous.model_dump(), **command.fields})
            _members(group, helices, strands, ["fields"])
            groups = [group if item.id == group.id else item for item in groups]
        else:
            for position, identity in enumerate(command.group_ids):
                if identity not in index:
                    _reference("part_group", identity, ["group_ids", position])
            selected = set(command.group_ids)
            from backend.core.part_group_consumers import require_no_incoming_groups
            require_no_incoming_groups(design, selected)
            groups = [group for group in groups if group.id not in selected]
    _bounded_groups(groups)
    try:
        organization = GroupOrganization(groups=groups)
    except ValidationError as error:
        _invalid(str(error), "group_organization_limit")
    return design.copy_with(group_organization=organization)
