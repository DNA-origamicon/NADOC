"""Closed named-group reference repair for typed bend/twist definitions.

Only targets[i].id is an editable input here. Native replay resolves the patched
selector on its feature prefix; derived ranges and placement context are never
copied from a replacement group or authored through this adapter.
"""

import json

from backend.core import models as m
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_deformation_edit import can_edit_named_groups


def _reject(detail, code="unsupported_repair_target"):
    raise CommandContractError(detail, code=code)


def _recognized_operation(operation):
    return (type(operation) is m.DeformationOp and type(operation.id) is str
        and 1 <= len(operation.id) <= 256
        and ((operation.type == "bend" and type(operation.params) is m.BendParams)
             or (operation.type == "twist" and type(operation.params) is m.TwistParams))
        and operation.params.kind == operation.type and can_edit_named_groups(operation))


def require_named_entry(entry):
    """Typed/schema-only recognition, safe during bounded source discovery."""
    if (type(entry) is not m.DeformationLogEntry or entry.feature_type != "deformation"
            or type(entry.proof_version) is not int or entry.proof_version != 1
            or not _recognized_operation(entry.op_snapshot)
            or entry.deformation_id != entry.op_snapshot.id
            or type(entry.deformation_id) is not str):
        _reject("Select a coherent native bend/twist with only named organizational group targets")
    return entry.op_snapshot


def reference_index(operation, path):
    if (not can_edit_named_groups(operation) or operation.type not in {"bend", "twist"}
            or type(path) is not list or len(path) != 3 or path[0] != "targets"
            or type(path[1]) is not int or not 0 <= path[1] < len(operation.targets)
            or path[2] != "id"):
        _reject("Only an existing named group target identity can be repaired",
                "protected_recipe_identity")
    return path[1]


def operation_from_params(params):
    """Outside-lock command recognition for the explicit reference catalog."""
    from backend.core.part_operation_input import validate_operation_input

    try:
        validate_operation_input(params)
        if (type(params) is not dict or type(params.get("_proof_version")) is not int
                or params["_proof_version"] != 1 or "id" not in params):
            _reject("Named deformation repair requires its explicit version 1 inputs")
        # command_input is JSON: native Direction enums are serialized as
        # strings. Strict JSON validation accepts that declared wire form
        # while retaining strict integer/bool and extra-field checks.
        operation = m.DeformationOp.model_validate_json(json.dumps(
            {key: value for key, value in params.items() if key != "_proof_version"}, allow_nan=False),
            strict=True, extra="forbid")
        if not _recognized_operation(operation):
            _reject("Named deformation repair requires pure organizational group selectors")
        return operation
    except ValueError as error:
        if isinstance(error, CommandContractError):
            raise
        _reject(str(error))


def replace_reference(entry, index, value, *, copy_value):
    """Update a private accumulated row after checking its original input path.

    Duplicate-selector validation belongs after all actions: two independent
    ID slots may intentionally exchange their references in one proposal.
    """
    if type(value) is not str or not 1 <= len(value) <= 256:
        _reject("Replacement groups require bounded nonempty identities", "invalid_repaired_contract")
    replacement = copy_value(entry)
    replacement.op_snapshot.targets[index]["id"] = value
    return replacement


def group_candidates(design, params, request, checkpoint):
    """One bounded metadata index; no per-candidate native resolver or geometry."""
    from backend.core.part_capture_graph import CaptureLimit, GraphBudget
    from backend.core.part_group_model import GroupOrganization
    from backend.core.part_group_organization import _bounded_groups, _index, _members

    operation = operation_from_params(params)
    selected = reference_index(operation, request.parameter_path)
    excluded = {target["id"] for index, target in enumerate(operation.targets) if index != selected}
    organization = design.group_organization
    if type(organization) is not GroupOrganization:
        _reject("The rebuilt prefix has no organizational group namespace", "invalid_deformation_selection")
    budget = GraphBudget(max_nodes=30_000, max_bytes=2_000_000, seconds=None, clock=lambda: 0)
    try:
        if len(design.helices) + len(design.strands) + len(organization.groups) > 30_000:
            _reject("Group selection exceeds its metadata allowance", "group_selection_limit")
        _bounded_groups(organization, budget=budget)
        helices = _index(design.helices, "helix")
        strands = _index(design.strands, "strand")
        groups = _index(organization.groups, "part_group")
        invalid_helices, invalid_domains = set(), set()
        for helix in helices.values():
            checkpoint()
            if type(helix) is not m.Helix:
                _reject("Replacement groups require typed native topology")
            budget.charge((helix.id, helix.bp_start, helix.length_bp))
            if (type(helix.bp_start) is not int or type(helix.length_bp) is not int
                    or helix.length_bp <= 0 or helix.bp_start.bit_length() > 64
                    or helix.length_bp.bit_length() > 64):
                invalid_helices.add(helix.id)
        for strand in strands.values():
            checkpoint()
            if type(strand) is not m.Strand or type(strand.domains) is not list or len(strand.domains) > 30_000:
                _reject("Replacement groups require bounded native domain metadata", "group_selection_limit")
            budget.charge(strand.id)
            for ordinal, domain in enumerate(strand.domains):
                checkpoint()
                if type(domain) is not m.Domain:
                    _reject("Replacement groups require typed native domains")
                budget.charge((domain.helix_id, domain.start_bp, domain.end_bp, domain.direction))
                if (type(domain.helix_id) is not str or domain.helix_id not in helices
                        or type(domain.start_bp) is not int or type(domain.end_bp) is not int
                        or domain.start_bp.bit_length() > 64 or domain.end_bp.bit_length() > 64
                        or type(domain.direction) is not m.Direction):
                    invalid_domains.add((strand.id, ordinal))
        candidates, count = [], 0
        for group in groups.values():
            checkpoint()
            if len(group.id) > 256 or group.id in excluded or not (group.domain_ids or group.helix_ids):
                continue
            if group.domain_ids:
                if any(type(member.strand_id) is not str or type(member.domain_index) is not int
                       or member.domain_index < 0 or (member.strand_id, member.domain_index) in invalid_domains
                       for member in group.domain_ids):
                    continue
            elif any(type(identity) is not str or identity in invalid_helices for identity in group.helix_ids):
                continue
            try:
                # Domain selection takes precedence; unused helix selectors
                # cannot broaden it or rule out an otherwise valid domain set.
                selected_group = group.model_copy(update={"helix_ids": []}) if group.domain_ids else group
                _members(selected_group, helices, strands, request.parameter_path)
            except ReferenceResolutionError:
                continue
            count += 1
            if len(candidates) < request.limit:
                candidates.append({"kind": "part_group", "identity": group.id,
                                   "label": (group.name or group.id)[:256]})
        return candidates, count
    except CaptureLimit as error:
        _reject(str(error), "group_selection_limit")
