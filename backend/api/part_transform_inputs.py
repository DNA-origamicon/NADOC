"""Closed ordinary transform-history inputs, independent of live state.

Placement poses remain absolute native owner poses. Residue poses retain their
native compose/replace semantics; this is not an organizational group mover.
The operation-input budget is shared with ordinary recipe requests. Smaller
private-preview work limits belong to the preview evaluator, not this module.
"""

from copy import deepcopy
from math import isfinite, sqrt
from uuid import UUID

from backend.core.models import ClusterOpLogEntry, Design, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import command_input


KINDS = frozenset({"cluster_op", "placement-poses", "nucleotide-transform", "nucleotide-transform-batch",
                   "nucleotide-transform-delete"})
POSE_FIELDS = frozenset({"translation", "rotation", "pivot"})
AUTHORED_FIELDS = frozenset({"name", "helix_ids", "domain_ids", "color", "opacity"})
_BODY_FIELDS = frozenset({"kind", "helix_id", "bp_index", "direction", "copy_k",
    "crossover_id", "extra_base_k", "compose"}) | POSE_FIELDS
_PROTECTED = frozenset({"_proof_version", "history_seed", "expected_design_id",
                        "expected_revision", "expected_feature_id"})


def _reject(message, code="invalid_transform_input"):
    raise CommandContractError(message, code=code)


def _bounded(value):
    try:
        validate_operation_input(value)
    except (ValueError, TypeError) as error:
        _reject(str(error))


def _identity(value, field):
    if type(value) is not str or not 1 <= len(value) <= 512:
        _reject(f"{field} requires a bounded nonempty identity")


def _integer(value, field, *, nonnegative=False):
    if type(value) is not int or (nonnegative and value < 0):
        _reject(f"{field} requires {'a nonnegative' if nonnegative else 'an'} integer")


def _pose(values):
    for key, size in (("translation", 3), ("rotation", 4), ("pivot", 3)):
        vector = values.get(key)
        if (type(vector) is not list or len(vector) != size
                or any(type(value) not in {int, float} or not isfinite(value) for value in vector)):
            _reject(f"{key} requires {size} finite numeric values")
    norm = sqrt(sum(value * value for value in values["rotation"]))
    if not isfinite(norm) or norm < 1e-12:
        _reject("rotation requires a finite nonzero quaternion")


def _body(values):
    if type(values) is not dict or set(values) - _BODY_FIELDS:
        _reject("Residue transform requires its closed native fields")
    _pose(values)
    kind = values.get("kind")
    if type(kind) is not str or kind not in {"base", "extra_base"}:
        _reject("Residue transform kind must be base or extra_base")
    if type(values.get("compose", False)) is not bool:
        _reject("compose requires a boolean")
    _integer(values.get("copy_k", 0), "copy_k", nonnegative=True)
    if kind == "base":
        _identity(values.get("helix_id"), "helix_id")
        _integer(values.get("bp_index"), "bp_index")
        if type(values.get("direction")) is not str or values["direction"] not in {"FORWARD", "REVERSE"}:
            _reject("direction must be FORWARD or REVERSE")
        if values.get("crossover_id") is not None or values.get("extra_base_k") is not None:
            _reject("A base target cannot also carry a junction target")
        return (kind, values["helix_id"], values["bp_index"], values["direction"], values.get("copy_k", 0))
    _identity(values.get("crossover_id"), "crossover_id")
    _integer(values.get("extra_base_k"), "extra_base_k", nonnegative=True)
    if any(values.get(key) is not None for key in ("helix_id", "bp_index", "direction")):
        _reject("An inserted-base target cannot also carry an ordinary base target")
    return (kind, values["crossover_id"], values["extra_base_k"])


def _target(value):
    if type(value) is not list or not value:
        _reject("Reset target must be a native target-key array")
    if value[0] == "base" and len(value) == 5:
        _identity(value[1], "target helix")
        _integer(value[2], "target bp_index")
        if type(value[3]) is not str or value[3] not in {"FORWARD", "REVERSE"}:
            _reject("Reset target direction must be FORWARD or REVERSE")
        _integer(value[4], "target copy_k", nonnegative=True)
    elif value[0] == "extra_base" and len(value) == 3:
        _identity(value[1], "target junction")
        _integer(value[2], "target extra_base_k", nonnegative=True)
    else:
        _reject("Reset target must have the exact native target-key shape")


def _placement(values):
    _identity(values.get("cluster_id"), "cluster_id")
    _pose(values)
    if "name" in values and (type(values["name"]) is not str or len(values["name"]) > 512):
        _reject("Placement name requires bounded text")
    if "color" in values and values["color"] is not None and (
            type(values["color"]) is not str or len(values["color"]) > 512):
        _reject("Placement color requires bounded text or null")
    if "opacity" in values and (type(values["opacity"]) not in {int, float} or not isfinite(values["opacity"])):
        _reject("Placement opacity requires a finite number")
    if "helix_ids" in values:
        if type(values["helix_ids"]) is not list:
            _reject("helix_ids requires an identity list")
        for identity in values["helix_ids"]:
            _identity(identity, "helix_ids")
    if "domain_ids" in values:
        if type(values["domain_ids"]) is not list:
            _reject("domain_ids requires a domain-reference list")
        for item in values["domain_ids"]:
            if type(item) is not dict or set(item) != {"strand_id", "domain_index"}:
                _reject("Placement domains require closed strand_id/domain_index references")
            _identity(item["strand_id"], "strand_id")
            _integer(item["domain_index"], "domain_index", nonnegative=True)


def normalize(kind, previous, patch):
    """Return owned complete inputs; preserve literals and protected metadata."""
    if kind == "placement-poses":
        from backend.api.part_placement_pose_commands import normalize as normalize_poses
        return normalize_poses(previous, patch)
    if type(kind) is not str or kind not in KINDS:
        _reject("Select an ordinary native transform", "unsupported_transform_scope")
    if type(previous) is not dict or type(patch) is not dict:
        _reject("Transform inputs and patch must be JSON objects")
    _bounded(previous)
    _bounded(patch)
    fields = (POSE_FIELDS | AUTHORED_FIELDS | {"cluster_id"} if kind == "cluster_op" else
              {"transforms"} if kind.endswith("-batch") else
              {"transform_id", "target"} if kind.endswith("-delete") else _BODY_FIELDS)
    protected = frozenset({"_proof_version"}) if kind == "cluster_op" else _PROTECTED
    if set(previous) - (fields | protected) or set(patch) - (fields | protected):
        _reject("Transform editing requires known ordinary, non-generated fields", "unsupported_transform_scope")
    if type(previous.get("_proof_version")) is not int or previous["_proof_version"] != 1:
        _reject("Transform editing requires native proof version 1", "missing_proof_contract")
    for key in _PROTECTED & patch.keys():
        if key not in previous or type(patch[key]) is not type(previous[key]) or patch[key] != previous[key]:
            _reject(f"Transform identity and transport cannot be edited: {key}")
    for key in ("expected_design_id", "expected_feature_id"):
        if key in previous:
            _identity(previous[key], key)
    if "expected_revision" in previous:
        _integer(previous["expected_revision"], "expected_revision", nonnegative=True)
    if kind in {"nucleotide-transform", "nucleotide-transform-batch"} or "history_seed" in previous:
        seed = previous.get("history_seed")
        try:
            if type(seed) is not str:
                raise ValueError("missing saved UUID")
            UUID(seed)
        except (ValueError, TypeError, AttributeError) as error:
            _reject(f"Transform history requires its stable UUID: {error}")
    values = {**previous, **patch}
    _bounded(values)
    authored = {key: value for key, value in values.items() if key not in _PROTECTED}
    if kind == "cluster_op":
        _placement(authored)
    elif kind.endswith("-delete"):
        _identity(authored.get("transform_id"), "transform_id")
        if "target" in authored:
            _target(authored["target"])
    elif kind.endswith("-batch"):
        bodies = authored.get("transforms")
        if type(bodies) is not list or not 1 <= len(bodies) <= 100_000:
            _reject("Transform batch requires 1–100000 native targets")
        keys = [_body(body) for body in bodies]
        if len(set(keys)) != len(keys):
            _reject("Duplicate nucleotide transform target")
    else:
        _body(authored)
    return deepcopy(values)


def bind_prefix(kind, params, prefix):
    """Resolve only against the owned pre-feature design, never latest state."""
    return _bind_normalized(kind, normalize(kind, params, {}), prefix)


def _bind_normalized(kind, values, prefix):
    """Bind the independently owned result of normalize without recopying it."""
    from backend.api.part_transform_references import validate_transform_references

    if type(prefix) is not Design:
        _reject("Transform binding requires an owned native prefix")
    validate_transform_references(kind, prefix, values)
    if kind == "nucleotide-transform-delete":
        target = next(item for item in prefix.nucleotide_transforms if item.id == values["transform_id"])
        values["target"] = list(target.target_key())
    return values


def edit_transform_entry(entry, patch, prefix):
    """Rebuild one typed row, retaining its feature identity and provenance."""
    if type(entry) is not ClusterOpLogEntry and not (
            type(entry) is SnapshotLogEntry and entry.op_kind in KINDS - {"cluster_op"}):
        _reject("Select an ordinary top-level transform history row", "unsupported_transform_scope")
    kind, previous = command_input(entry)
    if kind == "cluster_op" and type(patch) is dict and "upgrade_to" in patch:
        from backend.api.part_placement_pose_commands import upgrade_entry
        return upgrade_entry(entry, patch, prefix)
    values = _bind_normalized(kind, normalize(kind, previous, patch), prefix)
    if (kind == "nucleotide-transform-delete" and "target" in patch
            and patch["target"] != values["target"]):
        _reject("The explicit reset target does not match the selected prefix transform")
    if kind == "cluster_op":
        return entry.model_copy(deep=True, update={
            "cluster_id": values["cluster_id"],
            **{key: values[key] for key in POSE_FIELDS},
            "authored_fields": {key: values[key] for key in AUTHORED_FIELDS if key in values},
        })
    return entry.model_copy(deep=True, update={"params": values})
