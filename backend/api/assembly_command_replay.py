"""Versioned assembly commands replay through their user-facing operations.

Inputs are captured when the user invokes the operation, never recovered from
post-state geometry. Output identities bind subsequent selections to the same
objects. Legacy summary-only rows do not acquire a replay contract here.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from importlib import import_module
from uuid import uuid4
import math
import time

from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import assembly_state


# module, operation, request model, path parameter, generated output slot
COMMANDS = {
    "assembly-instance-history-change": ("assembly_instance_history", "record_change", "InstanceHistoryChange", "instance_id", None),
    "assembly-instance-overhang-extrude": ("assembly", "extrude_instance_overhang", "InstanceOverhangExtrudeRequest", "instance_id", "part_feature_id"),
    "assembly-instance-overhang-patch": ("assembly", "patch_instance_overhang", "InstanceOverhangPatchRequest", ("instance_id", "overhang_id"), "part_feature_id"),
    "assembly-delete-instance": ("assembly", "delete_instance", None, "instance_id", None),
    "assembly-propagate-fk": ("assembly", "propagate_fk", "PropagateFKRequest", None, None),
    "assembly-patch-instance": ("assembly", "patch_instance", "PatchInstanceRequest", "instance_id", None),
    "assembly-transform-instance": ("assembly", "patch_instance", "PatchInstanceRequest", "instance_id", None),
    "assembly-transform-instance-cluster": ("assembly", "patch_instance_cluster_transform", "PatchInstanceClusterTransformRequest", "instance_id", None),
    "assembly-duplicate-instance": ("assembly", "duplicate_instance", "DuplicateInstanceRequest", "source_instance_id", "new_instance_id"),
    "assembly-add-instance": ("assembly", "add_instance", "AddInstanceRequest", None, "instance_id"),
    "assembly-replace-instance-source": ("assembly", "patch_instance_design", "PatchInstanceDesignRequest", "instance_id", None),
    "assembly-overhang-bind": ("routes_assembly_overhangs", "create_assembly_overhang_binding", "CreateAssemblyOverhangBindingRequest", None, "binding_id"),
    "assembly-overhang-bind-patch": ("routes_assembly_overhangs", "patch_assembly_overhang_binding", "PatchAssemblyOverhangBindingRequest", "binding_id", None),
    "assembly-overhang-unbind": ("routes_assembly_overhangs", "delete_assembly_overhang_binding", None, "binding_id", None),
    "assembly-overhang-connection-add": ("routes_assembly_overhangs", "create_assembly_overhang_connection", "CreateAssemblyOverhangConnectionRequest", None, "connection_id"),
    "assembly-overhang-connection-patch": ("routes_assembly_overhangs", "patch_assembly_overhang_connection", "PatchAssemblyOverhangConnectionRequest", "connection_id", None),
    "assembly-overhang-connection-delete": ("routes_assembly_overhangs", "delete_assembly_overhang_connection", None, "connection_id", None),
    "assembly-overhang-connection-relax": ("routes_assembly_overhangs", "relax_assembly_overhang_connection", "RelaxAssemblyLinkerRequest", "connection_id", None),
    "assembly-duplex-add": ("routes_assembly_overhangs", "create_assembly_duplex", "CreateAssemblyDuplexBody", None, "duplex_id"),
    "assembly-duplex-connect": ("routes_assembly_overhangs", "connect_assembly_duplex", "ConnectAssemblyDuplexBody", None, "duplex_id"),
    "assembly-duplex-sync": ("routes_assembly_overhangs", "sync_assembly_duplexes", None, None, "outputs"),
    "assembly-duplex-patch": ("routes_assembly_overhangs", "patch_assembly_duplex", "PatchAssemblyDuplexBody", "duplex_id", None),
    "assembly-duplex-delete": ("routes_assembly_overhangs", "delete_assembly_duplex", None, "duplex_id", None),
    "assembly-add-connector": ("routes_assembly_connectors", "add_connector", "AddConnectorRequest", "instance_id", "label"),
    "assembly-delete-connector": ("routes_assembly_connectors", "delete_connector", None, ("instance_id", "label"), None),
    "assembly-create-belt": ("routes_assembly_belts", "create_belt_path", "CreateBeltPathRequest", None, "belt_id"),
    "assembly-patch-belt": ("routes_assembly_belts", "patch_belt_path", "PatchBeltPathRequest", "belt_id", None),
    "assembly-delete-belt": ("routes_assembly_belts", "delete_belt_path", None, "belt_id", None),
    "assembly-create-belt-rider": ("routes_assembly_belts", "create_belt_rider", "CreateBeltRiderRequest", None, "rider_id"),
    "assembly-delete-belt-rider": ("routes_assembly_belts", "delete_belt_rider", None, "rider_id", None),
    "assembly-polymerize-belt": ("routes_assembly_belts", "polymerize_belt", "PolymerizeBeltRequest", None, "outputs"),
    "assembly-patch-joint": ("routes_assembly_joints", "patch_joint", "PatchJointRequest", "joint_id", None),
    "assembly-refresh-mate": ("routes_assembly_joints", "refresh_mate", None, "joint_id", None),
    "assembly-delete-joint": ("routes_assembly_joints", "delete_joint", None, "joint_id", None),
    "assembly-polymerize": ("routes_assembly_polymerize", "polymerize_assembly", "PolymerizeAssemblyRequest", None, "outputs"),
    "assembly-polymerize-periodic": ("routes_assembly_polymerize", "polymerize_periodic_assembly", "PolymerizePeriodicRequest", None, "outputs"),
    "assembly-transform-group": ("routes_assembly_groups", "transform_group", "TransformGroupRequest", "group_id", None),
    "assembly-create-group": ("routes_assembly_groups", "create_group", "CreateGroupRequest", None, "group_id"),
    "assembly-patch-group": ("routes_assembly_groups", "patch_group", "PatchGroupRequest", "group_id", None),
    "assembly-ungroup": ("routes_assembly_groups", "ungroup", None, "group_id", None),
    "assembly-delete-group": ("routes_assembly_groups", "cascade_delete_group", None, "group_id", None),
    "assembly-duplicate-group": ("routes_assembly_groups", "duplicate_group", "DuplicateGroupRequest", "source_group_id", "outputs"),
    "assembly-create-gear": ("routes_assembly_gears", "create_gear_relation", "CreateGearRelationRequest", None, "relation_id"),
    "assembly-patch-gear": ("routes_assembly_gears", "patch_gear_relation", "PatchGearRelationRequest", "relation_id", None),
    "assembly-delete-gear": ("routes_assembly_gears", "delete_gear_relation", None, "relation_id", None),
    "assembly-resolve-gear": ("routes_assembly_gears", "resolve_gear_relation", None, "relation_id", None),
    "assembly-add-joint": ("routes_assembly_joints", "add_joint", "AddJointRequest", None, "joint_id"),
    "assembly-create-mate": ("routes_assembly_joints", "create_mate", "CreateMateRequest", None, "joint_id"),
}

TIMED_COMMANDS = {"assembly-overhang-bind", "assembly-overhang-connection-add", "assembly-duplex-add", "assembly-duplex-connect",
                  "assembly-instance-overhang-extrude", "assembly-instance-overhang-patch"}
_creation_time: ContextVar[float | None] = ContextVar("assembly_creation_time", default=None)


def output_created_at():
    value = _creation_time.get()
    return time.time() if value is None else value


_editing_outputs: ContextVar[bool] = ContextVar("assembly_editing_outputs", default=False)
_outputs: ContextVar[dict | None] = ContextVar("assembly_command_outputs", default=None)


def output_id(slot):
    """Allocate an ordinary operation output, or consume its recorded identity."""
    outputs = _outputs.get()
    if outputs is None:
        return str(uuid4())
    value = outputs.pop(slot, None)
    if value is None and _editing_outputs.get():
        return str(uuid4())
    if not isinstance(value, str) or not value:
        raise HTTPException(422, detail=f"AGENT_PROCESS_REQUIRED: missing output identity {slot}.")
    return value


def output_label(slot, suggested, *, explicit=False):
    """Preserve an automatically chosen connector label during replay."""
    if _outputs.get() is None:
        return suggested
    recorded = output_id(slot)
    return suggested if explicit and _editing_outputs.get() else recorded


@contextmanager
def recorded_outputs(outputs, *, editing=False, created_at=None):
    pending = dict(outputs)
    time_token = _creation_time.set(created_at)
    token = _outputs.set(pending)
    edit_token = _editing_outputs.set(editing)
    try:
        yield
        if pending and not editing:
            raise HTTPException(422, detail="Recorded assembly outputs were not produced by the command.")
    finally:
        _outputs.reset(token)
        _editing_outputs.reset(edit_token)
        _creation_time.reset(time_token)


def command_params(body=None, **identities):
    return {
        **identities,
        "command_version": 1,
        "input_fields_set": sorted(body.model_fields_set) if body is not None else [],
        "inputs": body.model_dump(mode="json") if body is not None else {},
    }


def replay(assembly, kind, params):
    return _execute(assembly, kind, params)


def replay_edited(assembly, kind, params):
    """Execute an explicit input edit and capture its actual output contract.

    Surviving semantic slots retain their IDs; new slots receive new IDs from
    the ordinary command allocator. Removed outputs vanish only from this
    edited command. Downstream commands still replay strictly and reject any
    selections that no longer exist.
    """
    return _execute(assembly, kind, params, editing=True)


def validate_definition(kind, params):
    """Validate a recorded definition without executing it or resolving references."""
    if kind not in COMMANDS or type(params.get("command_version")) is not int or params["command_version"] != 1 or not isinstance(params.get("inputs"), dict):
        raise HTTPException(422, detail=f"AGENT_PROCESS_REQUIRED: {kind} lacks supported recorded command inputs.")
    module_name, function_name, model_name, path_key, output_key = COMMANDS[kind]
    module = import_module(f"backend.api.{module_name}")
    args = []
    if path_key:
        for key in path_key if isinstance(path_key, tuple) else (path_key,):
            value = params.get(key)
            if not isinstance(value, str) or not value:
                raise HTTPException(422, detail=f"Missing recorded {key}.")
            args.append(value)
    if model_name:
        model = getattr(module, model_name)
        if set(params["inputs"]) != model.model_fields.keys():
            raise HTTPException(422, detail="Incomplete or unknown recorded assembly command inputs.")
        try:
            inputs = params["inputs"]
            fields_set = params.get("input_fields_set")
            if fields_set is not None:
                if (not isinstance(fields_set, list) or any(not isinstance(key, str) for key in fields_set)
                        or len(set(fields_set)) != len(fields_set) or set(fields_set) - model.model_fields.keys()):
                    raise HTTPException(422, detail="Invalid recorded input field presence.")
                parsed = model.model_validate({key: inputs[key] for key in fields_set})
                if parsed.model_dump(mode="json") != inputs:
                    raise HTTPException(422, detail="Recorded defaults disagree with input field presence.")
            else:
                if kind == "assembly-patch-joint":
                    raise HTTPException(422, detail="Joint patch requires recorded input field presence.")
                parsed = model.model_validate(inputs)
            if kind == "assembly-patch-joint" and (parsed.silent or parsed.expected_revision is not None or parsed.expected_assembly_id is not None):
                raise HTTPException(422, detail="Playback transport is not an authored joint command.")
            args.append(parsed)
        except ValidationError as error:
            raise HTTPException(422, detail=str(error)) from error
    elif params["inputs"]:
        raise HTTPException(422, detail="This assembly command has no body inputs.")
    outputs = params.get("outputs") if output_key == "outputs" else ({output_key: params.get(output_key)} if output_key else {})
    if not isinstance(outputs, dict) or any(not isinstance(value, str) or not value for value in outputs.values()):
        raise HTTPException(422, detail="Missing recorded assembly output identities.")
    if len(set(outputs.values())) != len(outputs):
        raise HTTPException(422, detail="Recorded assembly output identities are not unique.")
    created_at = params.get("created_at") if kind in TIMED_COMMANDS else None
    if kind in TIMED_COMMANDS and (isinstance(created_at, bool) or not isinstance(created_at, (int, float)) or not math.isfinite(created_at)):
        raise HTTPException(422, detail="Missing or invalid recorded creation time.")
    return module, function_name, args, outputs, output_key, created_at


def _execute(assembly, kind, params, *, editing=False):
    module, function_name, args, outputs, output_key, created_at = validate_definition(kind, params)
    existing = {obj.id for field in ("instances", "joints", "gear_relations", "groups", "overhang_bindings", "belt_paths", "belt_riders", "overhang_connections", "duplexes") for obj in getattr(assembly, field)}
    if output_key != "label" and any(value in existing for value in outputs.values()):
        raise HTTPException(422, detail="Recorded output identity already exists in this assembly prefix.")
    with assembly_state.isolated_evaluation(assembly), recorded_outputs(outputs, editing=editing and output_key in ("outputs", "label"), created_at=created_at):
        getattr(module, function_name)(*args)
        result = assembly_state.get_or_404()
        # Capture the real command's updated inputs/outputs, never infer an
        # authoring operation from its resulting geometry.
        captured = result.feature_log[-1].params if len(result.feature_log) > len(assembly.feature_log) else None
        candidate = result.model_copy(update={"feature_log": list(assembly.feature_log), "feature_log_cursor": -1})
        if editing:
            if captured is None:
                raise HTTPException(422, detail="Edited command produced no recorded operation; delete the feature instead.")
            return candidate, captured
        return candidate
