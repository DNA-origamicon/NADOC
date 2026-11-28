"""Regenerate a versioned assembly feature and its downstream commands."""

from importlib import import_module

from fastapi import HTTPException

from backend.api import assembly_state
from backend.api.assembly_command_replay import COMMANDS
from backend.api.assembly_history_regeneration import regenerate


def edit_recorded_feature(index, overrides):
    # Local import: assembly.py is the legacy host, not a command dependency.
    from backend.api.assembly import _decode_entry_pre_state

    source = assembly_state.get_or_404()
    if source.feature_log_cursor != -1:
        raise HTTPException(409, detail="Return to the latest assembly history position before editing.")
    entry = source.feature_log[index]
    params = edited_inputs(entry, overrides)
    current = _decode_entry_pre_state(source.feature_log, index).model_copy(
        update={"feature_log": list(source.feature_log[:index]), "feature_log_cursor": -1}
    )
    return regenerate(current, source.feature_log[index:], edited_id=entry.id, edited_params=params)


def edited_inputs(entry, overrides):
    spec = COMMANDS.get(entry.op_kind)
    if not spec or not spec[2] or entry.params.get("command_version") != 1:
        raise HTTPException(422, detail="This entry has no supported recorded input editor.")
    model = getattr(import_module(f"backend.api.{spec[0]}"), spec[2])
    updates = overrides
    if "inputs" in overrides:
        if set(overrides) != {"inputs"}:
            raise HTTPException(422, detail="Edit command inputs without changing output identities.")
        updates = overrides["inputs"]
    if not isinstance(updates, dict) or set(updates) - model.model_fields.keys():
        raise HTTPException(422, detail="Unknown assembly command input fields.")
    params = {**entry.params, "inputs": {**entry.params.get("inputs", {}), **updates}}
    if "input_fields_set" in params:
        params["input_fields_set"] = sorted(set(params["input_fields_set"]) | set(updates))
    return params
