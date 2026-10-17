"""Explicit absolute native owner poses; authoring controls are provenance only.

This command never reruns a constraint solver or infers linked history rows.
All selected and auxiliary owners are recorded, frame-bound and checked before
the unchanged single-owner overlay is applied in native placement-list order.
"""

from copy import deepcopy
from math import isfinite

from pydantic import BaseModel

from backend.core.models import ClusterOpLogEntry, SnapshotLogEntry
from backend.core.part_capture_graph import CaptureLimit, CaptureShapeError, GraphBudget
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dependencies import Dependencies, Resource
from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES, validate_operation_input


KIND = "placement-poses"
MAX_OWNERS = 64
UPGRADE = "placement-poses-v1"
_FIELDS = frozenset({"_proof_version", "primary_cluster_id", "selected_cluster_ids", "poses",
                     "authoring", "primary_authored_fields", "legacy_source"})
_POSE_FIELDS = frozenset({"cluster_id", "translation", "rotation", "pivot",
                          "parent_cluster_id", "overhang_duplex_driver_id"})
_HOST_FIELDS = frozenset({"primary_authored_fields", "legacy_source"})


def _reject(message, code="invalid_transform_input"):
    raise CommandContractError(message, code=code)


def _ids(value, name, *, nonempty=False):
    from backend.api.part_transform_inputs import _identity

    if type(value) is not list or not int(nonempty) <= len(value) <= MAX_OWNERS:
        _reject(f"{name} requires a bounded identity list")
    for item in value:
        _identity(item, name)
    if len(set(value)) != len(value):
        _reject(f"{name} contains duplicate identities")
    return set(value)


def parse_command(params):
    """Validate a closed bounded definition and return independent JSON values."""
    from backend.api.part_transform_inputs import AUTHORED_FIELDS, _bounded, _identity, _placement

    _bounded(params)
    if type(params) is not dict or set(params) != _FIELDS:
        _reject("Complete placement poses require the exact versioned fields")
    if type(params["_proof_version"]) is not int or params["_proof_version"] != 1:
        _reject("Complete placement poses require proof version 1", "missing_proof_contract")
    _identity(params["primary_cluster_id"], "primary_cluster_id")
    selected = _ids(params["selected_cluster_ids"], "selected_cluster_ids", nonempty=True)
    poses = params["poses"]
    if type(poses) is not list or not 1 <= len(poses) <= MAX_OWNERS:
        _reject("Complete placement poses require 1–64 owners")
    owners = set()
    for pose in poses:
        if type(pose) is not dict or set(pose) != _POSE_FIELDS:
            _reject("Each owner requires a complete pose and explicit native frame")
        _placement(pose)
        for key in ("parent_cluster_id", "overhang_duplex_driver_id"):
            if pose[key] is not None:
                _identity(pose[key], key)
        if pose["cluster_id"] in owners:
            _reject("Complete placement poses repeat an owner")
        owners.add(pose["cluster_id"])
    if params["primary_cluster_id"] not in selected or not selected <= owners:
        _reject("Primary and selected owners must be included in the complete pose list")
    authoring = params["authoring"]
    if type(authoring) is not dict or set(authoring) != {"mode", "joint_id", "fixed_cluster_ids", "pivot_id"}:
        _reject("Complete poses require closed authoring controls")
    mode, joint, pivot = authoring["mode"], authoring["joint_id"], authoring["pivot_id"]
    _identity(pivot, "pivot_id")
    if type(mode) is not str or mode not in {"free", "joint", "tethers"}:
        _reject("Unsupported placement authoring mode")
    if mode == "joint":
        _identity(joint, "joint_id")
        if pivot != joint:
            _reject("Joint pivot must identify the authored joint")
    elif joint is not None:
        _reject("Only joint mode may carry a joint identity")
    if mode == "free" and pivot != "centroid" and not pivot.startswith("dup:root:"):
        _reject("Free movement requires a native centroid or duplex-root pivot")
    if pivot.startswith("dup:root:"):
        _identity(pivot[len("dup:root:"):], "pivot overhang")
    if mode == "tethers" and pivot not in {"ssdna", "dup:taut"}:
        _reject("Tether mode requires its native tether control")
    fixed = _ids(authoring["fixed_cluster_ids"], "fixed_cluster_ids")
    if fixed & owners:
        _reject("Fixed owners cannot also receive an authored pose")
    authored = params["primary_authored_fields"]
    if type(authored) is not dict or set(authored) - AUTHORED_FIELDS:
        _reject("Primary authored fields must preserve ordinary placement metadata")
    primary = next(pose for pose in poses if pose["cluster_id"] == params["primary_cluster_id"])
    _placement({**primary, **authored})
    if params["legacy_source"] is not None and (
            type(params["legacy_source"]) is not str or len(params["legacy_source"]) > 512):
        _reject("Legacy source provenance requires bounded text or null")
    return deepcopy(params)


def validate_references(design, parsed):
    """Check complete ownership and exact native frames without deriving geometry."""
    from backend.api.part_transform_references import _References, _fail, _placement

    refs = _References(design)
    primary = None
    for index, pose in enumerate(parsed["poses"]):
        path = ["poses", index]
        owner = refs.resolve("cluster", pose["cluster_id"], [*path, "cluster_id"])
        for key in ("parent_cluster_id", "overhang_duplex_driver_id"):
            if pose[key] != getattr(owner, key):
                _fail("cluster", owner.id, [*path, key], ambiguous=True,
                      detail="The authored placement frame differs from its owned native prefix")
        fields = parsed["primary_authored_fields"] if owner.id == parsed["primary_cluster_id"] else {}
        _placement(refs, {**pose, **fields}, path_prefix=path,
                   authored_path=["primary_authored_fields"])
        if owner.id == parsed["primary_cluster_id"]:
            primary = owner
    authoring = parsed["authoring"]
    for index, identity in enumerate(authoring["fixed_cluster_ids"]):
        refs.resolve("cluster", identity, ["authoring", "fixed_cluster_ids", index])
    if authoring["joint_id"] is not None:
        joint = refs.resolve("joint", authoring["joint_id"], ["authoring", "joint_id"])
        if joint.cluster_id != primary.id:
            _fail("joint", joint.id, ["authoring", "joint_id"], ambiguous=True,
                  detail="The authored joint must belong to the primary placement")
    pivot = authoring["pivot_id"]
    if pivot.startswith("dup:root:") or pivot == "dup:taut":
        if primary.overhang_duplex_driver_id is None:
            _fail("cluster", primary.id, ["authoring", "pivot_id"], ambiguous=True,
                  detail="A duplex pivot requires a native duplex placement")
        if pivot.startswith("dup:root:"):
            from backend.core.duplex_cluster import _duplex_driven_overhang

            identity = pivot[len("dup:root:"):]
            refs.resolve("overhang", identity, ["authoring", "pivot_id"])
            if identity not in {primary.overhang_duplex_driver_id, _duplex_driven_overhang(design, primary)}:
                _fail("overhang", identity, ["authoring", "pivot_id"], ambiguous=True,
                      detail="The rotation root must belong to this native duplex")


def build(design, params):
    from backend.core.part_overlay_commands import build as overlay

    parsed = parse_command(params)
    validate_references(design, parsed)
    poses = {pose["cluster_id"]: pose for pose in parsed["poses"]}
    result = design
    for owner in design.cluster_transforms:
        if owner.id in poses:
            authored = parsed["primary_authored_fields"] if owner.id == parsed["primary_cluster_id"] else {}
            pose = poses[owner.id]
            result = overlay("cluster_op", result, {"_proof_version": 1,
                "cluster_id": owner.id, **authored,
                **{key: pose[key] for key in ("translation", "rotation", "pivot")}})
    return result


def dependencies(params):
    try:
        parsed = parse_command(params)
    except (ValueError, TypeError):
        return Dependencies(known=False)
    writes = frozenset(Resource("cluster", pose["cluster_id"]) for pose in parsed["poses"])
    reads = set(writes)
    for pose in parsed["poses"]:
        if pose["parent_cluster_id"] is not None:
            reads.add(Resource("cluster", pose["parent_cluster_id"]))
        if pose["overhang_duplex_driver_id"] is not None:
            reads.add(Resource("overhang", pose["overhang_duplex_driver_id"]))
    authored, controls = parsed["primary_authored_fields"], parsed["authoring"]
    reads.update(Resource("cluster", identity) for identity in controls["fixed_cluster_ids"])
    if controls["joint_id"] is not None:
        reads.add(Resource("joint", controls["joint_id"]))
    if controls["pivot_id"].startswith("dup:root:"):
        reads.add(Resource("overhang", controls["pivot_id"][len("dup:root:"):]))
    membership = "helix_ids" in authored or "domain_ids" in authored
    if membership:
        reads.add(Resource("part", "topology"))
        reads.update(Resource("helix", identity) for identity in authored.get("helix_ids", ()))
        reads.update(Resource("strand", ref["strand_id"]) for ref in authored.get("domain_ids", ()))
    return Dependencies(frozenset(reads), writes, barrier=membership)


def _definition(entry):
    from backend.api.part_transform_inputs import normalize
    from backend.core.part_overlay_commands import command_input

    def shape(value):
        if isinstance(value, BaseModel):
            if (type(value) is not ClusterOpLogEntry or type(value.__dict__) is not dict
                    or set(value.__dict__) != set(ClusterOpLogEntry.model_fields)
                    or value.__pydantic_extra__ or value.__pydantic_private__):
                _reject("Unsupported original placement definition")
        elif type(value) in {str, bool, list, dict} or value is None:
            return
        elif type(value) is int and value.bit_length() <= 64:
            return
        elif type(value) is float and isfinite(value):
            return
        else:
            _reject("Unsupported original placement definition")

    if type(entry) is not ClusterOpLogEntry or type(entry.proof_version) is not int or entry.proof_version != 1:
        _reject("Explicit upgrade requires an original typed placement v1 row")
    try:
        GraphBudget(max_nodes=MAX_OPERATION_NODES, max_bytes=MAX_OPERATION_BYTES,
                    seconds=None, clock=lambda: 0).charge(entry, validate=shape, reject_cycles=True)
    except (CaptureLimit, CaptureShapeError) as error:
        _reject(str(error))
    kind, params = command_input(entry)
    normalize(kind, params, {})
    value = entry.model_dump(mode="json")
    validate_operation_input(value)
    return value


def upgrade_descriptor(entry):
    from backend.core.part_history_proof import digest

    return {"upgrade_to": UPGRADE, "expected_definition_sha256": digest(_definition(entry))}


def upgrade_entry(entry, patch, prefix):
    from backend.api.part_transform_inputs import _bounded

    _bounded(patch)
    if type(patch) is not dict or set(patch) != {"upgrade_to", "expected_definition_sha256", "definition"}:
        _reject("Placement upgrade requires its exact closed request")
    expected = upgrade_descriptor(entry)
    if any(patch[key] != value or type(patch[key]) is not str for key, value in expected.items()):
        _reject("Original placement definition changed after preparation", "repair_conflict")
    definition = patch["definition"]
    if type(definition) is not dict or set(definition) != _FIELDS - _HOST_FIELDS:
        _reject("Upgrade cannot replace the original coauthored fields or provenance")
    if definition["primary_cluster_id"] != entry.cluster_id:
        _reject("Upgrade must retain the original primary owner")
    parsed = parse_command({**definition, "primary_authored_fields": entry.authored_fields,
                            "legacy_source": entry.source})
    validate_references(prefix, parsed)
    return SnapshotLogEntry(id=entry.id, op_kind=KIND, label="Move placements",
        params=parsed, autogenerated_group_id=entry.autogenerated_group_id)


def normalize(previous, patch):
    """Edit explicit inputs while retaining inherited single-row meaning."""
    from backend.api.part_transform_inputs import _bounded

    parsed = parse_command(previous)
    _bounded(patch)
    if type(patch) is not dict or set(patch) - _FIELDS:
        _reject("Complete placement editing requires known fields")
    for key in _HOST_FIELDS | {"_proof_version", "primary_cluster_id"}:
        if key in patch and (type(patch[key]) is not type(parsed[key]) or patch[key] != parsed[key]):
            _reject(f"Inherited placement definition cannot be replaced: {key}")
    return parse_command({**parsed, **patch})
