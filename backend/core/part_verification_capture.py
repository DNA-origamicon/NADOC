"""Bounded proof input capture; strip recovery payloads and display/physics data."""
from copy import deepcopy
from time import monotonic

from pydantic import BaseModel

from backend.core.part_history_contract import FIELD_ROLES


class CaptureLimit(ValueError):
    pass


def capture(design, *, max_nodes=30_000, max_bytes=2_000_000, seconds=0.025):
    """Caller owns the state lock. Bound admission before expensive deep copies.

    Time is cooperative at object boundaries, not a hard real-time guarantee.
    Immutable strings are shared, but count toward the retained input budget.
    No snapshot blobs or physical results enter the captured proof input.
    """
    from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry
    deadline = monotonic() + seconds
    remaining = [max_nodes, max_bytes]

    def charge(value):
        pending = [value]
        seen = set()
        while pending:
            item = pending.pop()
            remaining[0] -= 1
            if remaining[0] < 0 or remaining[1] < 0 or monotonic() > deadline:
                raise CaptureLimit("Part verification capture budget exceeded")
            if isinstance(item, str):
                remaining[1] -= len(item) * 4  # conservative UTF-8 upper bound
            elif isinstance(item, (BaseModel, dict, list, tuple)):
                if id(item) in seen:
                    continue
                seen.add(id(item))
                if isinstance(item, BaseModel):
                    children = item.__dict__.values()
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

    fields = {}
    for name in type(design).model_fields:
        if FIELD_ROLES.get(name) not in {"presentation", "physical", "history"}:
            value = getattr(design, name)
            charge(value)
            fields[name] = deepcopy(value)
    charge(design.recipe_root)
    fields["recipe_root"] = design.recipe_root  # frozen root, immutable scalar fields
    fields["feature_log_cursor"] = design.feature_log_cursor
    fields["feature_log_sub_cursor"] = design.feature_log_sub_cursor

    def header(entry):
        # Copy only fields proof mode actually reads. Never visit a payload.
        data = {"id": entry.id, "op_subtype": getattr(entry, "op_kind", getattr(entry, "op_subtype", entry.feature_type)),
                "params": getattr(entry, "params", {})}
        charge(data)
        # model_construct intentionally preserves unsupported legacy kinds for
        # fail-closed coverage diagnostics without attempting a schema migration.
        return MinorMutationLogEntry.model_construct(**deepcopy(data))

    log = []
    for entry in design.feature_log:
        if entry.feature_type == "routing-cluster":
            charge(entry.id)
            log.append(RoutingClusterLogEntry.model_construct(id=entry.id, children=[header(c) for c in entry.children]))
        else:
            log.append(header(entry))
    fields["feature_log"] = log
    if monotonic() > deadline:
        raise CaptureLimit("Part verification capture time budget exceeded")
    return type(design).model_construct(**fields)
