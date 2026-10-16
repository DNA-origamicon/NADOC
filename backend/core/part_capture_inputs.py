"""Shared authoring projection and resource accounting for capture/admission.

Admission checks an already-private candidate; capture additionally isolates a
live input while its host owns the lock. Neither path validates or normalizes
models. Their field/header/node/byte selection must remain identical.
"""
from copy import deepcopy
from time import monotonic

from pydantic import BaseModel

from backend.core.part_history_contract import FIELD_ROLES


class CaptureLimit(ValueError):
    pass


def visit_inputs(design, *, max_nodes, max_bytes, seconds, preserve_entry_types,
                 copy_inputs, retain_owned=False):
    """One accounting path for copying, admission or private ownership transfer.

    A missing deadline is allowed only for resource admission of private input.
    This remains count/byte bounded, not a latency guarantee. Temporary walking
    stacks, identity sets and small header dictionaries still allocate.
    ``retain_owned`` is internal to immutable-source materialization: its caller
    must own and discard that entire decoded model. Ordinary capture never sets
    it. It removes a second deep copy, not any accounting or history projection.
    """
    from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry
    from backend.core.part_capture_copy import scalar_atom_charge, seed_scalar_atom_copy
    if copy_inputs and retain_owned:
        raise TypeError("Input projection cannot both copy and transfer ownership")
    build_inputs = copy_inputs or retain_owned
    if build_inputs and seconds is None:
        raise TypeError("Source capture requires a cooperative time allowance")
    deadline = monotonic() + seconds if seconds is not None else None
    remaining = [max_nodes, max_bytes]

    def charge(value, copy_memo=None, *, scalar_atoms=False):
        pending = [value]
        seen = set()
        while pending:
            item = pending.pop()
            remaining[0] -= 1
            if remaining[0] < 0 or remaining[1] < 0 or (deadline is not None and monotonic() > deadline):
                raise CaptureLimit("Part verification capture budget exceeded")
            if isinstance(item, str):
                remaining[1] -= len(item) * 4  # conservative UTF-8 upper bound
            elif isinstance(item, (BaseModel, dict, list, tuple)):
                if id(item) in seen:
                    continue
                seen.add(id(item))
                if isinstance(item, BaseModel):
                    children = item.__dict__.values()
                    if scalar_atoms:
                        scalar_charge = (seed_scalar_atom_copy(item, copy_memo) if copy_inputs
                                         else scalar_atom_charge(item))
                        if scalar_charge is not None:
                            nodes, size = scalar_charge
                            if nodes + len(pending) > remaining[0]:
                                raise CaptureLimit("Part verification capture node budget exceeded")
                            remaining[0] -= nodes
                            remaining[1] -= size
                            if remaining[1] < 0 or (deadline is not None and monotonic() > deadline):
                                raise CaptureLimit("Part verification capture budget exceeded")
                            continue
                elif isinstance(item, dict):
                    if len(item) * 2 > remaining[0]:
                        raise CaptureLimit("Part verification capture node budget exceeded")
                    children = (*item.keys(), *item.values())
                else:
                    children = item
                if len(children) + len(pending) > remaining[0]:
                    raise CaptureLimit("Part verification capture node budget exceeded")
                pending.extend(children)
        if remaining[1] < 0:
            raise CaptureLimit("Part verification capture byte budget exceeded")

    def retain(value, memo=None):
        return deepcopy(value, memo) if copy_inputs else value

    fields = {} if build_inputs else None
    for name in type(design).model_fields:
        if FIELD_ROLES.get(name) not in {"presentation", "physical", "history", "repair_draft"}:
            value = getattr(design, name)
            # Specialize the same reviewed scalar atoms in protein assets and
            # nanoparticle authoring; never bypass field/node/byte accounting.
            # Keep traversal/budgets identical; memo preserves atom aliases
            # within the captured field without sharing atoms with the source.
            scalar_atoms = name in {"nanoparticles", "protein_assets"}
            copy_memo = {} if copy_inputs and scalar_atoms else None
            charge(value, copy_memo, scalar_atoms=scalar_atoms)
            if build_inputs:
                fields[name] = retain(value, copy_memo)
    charge(design.recipe_root)
    if build_inputs:
        fields["recipe_root"] = design.recipe_root  # frozen root, immutable scalar fields
        fields["feature_log_cursor"] = design.feature_log_cursor
        fields["feature_log_sub_cursor"] = design.feature_log_sub_cursor

    def header(entry):
        # Copy only fields proof mode actually reads. Never visit a payload.
        from backend.core.part_overlay_commands import KINDS as OVERLAY_KINDS, command_input
        if entry.feature_type in OVERLAY_KINDS:
            charge(entry)
        if preserve_entry_types:
            if entry.feature_type in OVERLAY_KINDS:
                # These native overlay definitions are already input-only.
                return retain(entry) if build_inputs else None
            names = {"id", "feature_type", "op_kind", "op_subtype", "label", "params",
                     "timestamp", "autogenerated_group_id"}
            data = {name: getattr(entry, name) for name in names if name in type(entry).model_fields}
            charge(data)
            return type(entry).model_construct(**retain(data)) if build_inputs else None
        kind, params = command_input(entry)
        data = {"id": entry.id, "op_subtype": kind, "params": params}
        charge(data)
        # model_construct intentionally preserves unsupported legacy kinds for
        # fail-closed coverage diagnostics without attempting a schema migration.
        return MinorMutationLogEntry.model_construct(**retain(data)) if build_inputs else None

    log = [] if build_inputs else None
    for entry in design.feature_log:
        if entry.feature_type == "routing-cluster":
            data = {"id": entry.id}
            if preserve_entry_types:
                data.update({name: getattr(entry, name) for name in (
                    "label", "timestamp", "autogenerated_group_id")})
            charge(data)
            if build_inputs:
                log.append(RoutingClusterLogEntry.model_construct(**data, children=[header(c) for c in entry.children]))
            else:
                for child in entry.children:
                    header(child)
        else:
            copied = header(entry)
            if build_inputs:
                log.append(copied)
    if deadline is not None and monotonic() > deadline:
        raise CaptureLimit("Part verification capture time budget exceeded")
    if build_inputs:
        fields["feature_log"] = log
        return type(design).model_construct(**fields)
