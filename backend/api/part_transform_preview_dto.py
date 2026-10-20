"""Private transform controls and native display, with one whole-packet bound.

Inputs are independently owned by the caller. No state/session, recovery, proof,
publication or canonical renderer is accessed. Geometry-off still derives the
native rest-frame pivot choices for duplex controls; cumulative helper work is
admitted and cooperative deadlines are checked between native calls.
"""

from copy import deepcopy
import json
from math import isfinite

from backend.api.part_transform_inputs import KINDS, normalize
from backend.api.part_transform_preview import EvaluatedTransform
from backend.core.models import Design
from backend.core.part_overlay_commands import command_input
from backend.api.part_transform_display_contract import (
    MAX_CONTROL_WORK, MAX_OUTPUT_BYTES as MAX_OUTPUT_BYTES, MAX_OUTPUT_NODES as MAX_OUTPUT_NODES,
    bounded, checkpoint, inventory, limit, reject,
)


_STRINGS = {"preview_id": 256, "expected_design_id": 256, "feature_id": 256, "lease_id": 256,
            "doc_id": 1024, "family": 32, "command_kind": 64}
_INTEGERS = frozenset({"expected_revision", "request_sequence"})
_FIELDS = _STRINGS.keys() | _INTEGERS | {"remaining_seconds"}
_CONTROL_FIELDS = ("lattice_frames", "helices", "strands", "cluster_transforms", "cluster_joints",
    "cluster_join_constraints", "flexible_segment_marks", "flexible_connections", "crossovers",
    "forced_ligations", "extensions", "nucleotide_transforms")


def _bounded(value):
    return bounded(value, max_nodes=MAX_OUTPUT_NODES, max_bytes=MAX_OUTPUT_BYTES)


def _envelope(value, prefix, evaluated, kind):
    if value is None:
        return {}
    if type(value) is not dict or len(value) > len(_FIELDS):
        reject("Transform envelope must be a bounded scalar object", "invalid_preview_definition")
    for key, item in value.items():
        if type(key) is not str or key not in _FIELDS:
            reject("Unsupported or colliding transform envelope field", "invalid_preview_definition")
        if key in _STRINGS:
            valid = type(item) is str and 0 < len(item) <= _STRINGS[key]
        elif key in _INTEGERS:
            valid = type(item) is int and 0 <= item < 2**64
        else:
            valid = type(item) in (float, int) and 0 <= item < 2**64 and isfinite(item)
        if not valid:
            reject(f"Invalid transform envelope {key}", "invalid_preview_definition")
    for field, expected in (("family", "transform"), ("command_kind", kind),
                            ("feature_id", evaluated.entry.id), ("expected_design_id", prefix.id)):
        if field in value and value[field] != expected:
            reject(f"Transform envelope {field} does not match the owned result", "invalid_preview_definition")
    return dict(value)


def _inputs(prefix, evaluated):
    if type(prefix) is not Design or type(evaluated) is not EvaluatedTransform:
        reject("Transform display requires owned prefix and evaluation values", "invalid_preview_definition")
    kind, params = command_input(evaluated.entry)
    if (kind not in KINDS or params != evaluated.params or prefix.id != evaluated.design.id
            or evaluated.stage != "feature" or evaluated.source_equivalence_checked is not False
            or evaluated.downstream_evaluated is not False):
        reject("Transform evaluation identity or stage is inconsistent", "invalid_preview_definition")
    normalize(kind, evaluated.params, {})
    return kind


def _context(prefix, params):
    result = {field: [value.model_dump(mode="json", exclude={"routing_seed"} if field == "strands" else set())
                      for value in getattr(prefix, field)] for field in _CONTROL_FIELDS}
    result.update(inputs=deepcopy(params), lattice_type=prefix.lattice_type,
        group_organization=prefix.group_organization.model_dump(mode="json") if prefix.group_organization is not None else None,
        photoproduct_junctions=[value.model_dump(mode="json", include={"id", "base_key_1", "base_key_2", "product", "stereochemistry"})
                              for value in prefix.photoproduct_junctions])
    return result


def _control_cost(design, admitted):
    # Flexible gates build one graph, then visit it for each owner. Native
    # connection helpers revisit topology per owner/driver; each duplex pivot
    # helper independently derives rest geometry (no reusable geometry argument).
    owners = len(design.cluster_transforms)
    drivers = sum(bool(c.overhang_duplex_driver_id) for c in design.cluster_transforms)
    regular = owners - drivers
    domains = sum(len(strand.domains) for strand in design.strands)
    connections = len(design.overhang_connections)
    return (admitted.work * (1 + owners * (1 + drivers) + drivers)
            + regular * connections * 4 * (admitted.work + domains + owners + len(design.overhangs) + 1))


def _controls(design, params, check, gate_cache=None):
    from backend.core.connection_tethers import cluster_connection_tethers, cluster_movable_links
    from backend.core.duplex_cluster import duplex_cluster_rotation_points, duplex_cluster_tethers
    from backend.core.flexible_segments import all_cluster_gates
    from backend.core.models import _local_to_world_joint

    result = _context(design, params)
    owners = {owner.id: owner for owner in design.cluster_transforms}
    frames = {"joint_axes": {}, "rotation_points": {}, "placement_poses": {}}
    for owner in design.cluster_transforms:
        frames["placement_poses"][owner.id] = {"parent_cluster_id": owner.parent_cluster_id,
            "frame": "parent-rest" if owner.parent_cluster_id is not None else "native-design"}
    for joint in result["cluster_joints"]:
        owner = owners[joint["cluster_id"]].model_dump(mode="json")
        origin, direction = _local_to_world_joint(joint["local_axis_origin"], joint["local_axis_direction"], owner)
        joint.update(axis_origin=origin, axis_direction=direction)
        frames["joint_axes"][joint["id"]] = {"method": "native-owner-transform",
            "owner_id": joint["cluster_id"], "parent_cluster_id": owners[joint["cluster_id"]].parent_cluster_id,
            "parent_composed": False}
    check()
    # Native gates depend on ordered connectivity and ownership, not poses.
    # Retain complete collections rather than another hand-maintained schema.
    # Order matters for both domain lookup and equal-specificity owner ties.
    gate_key = None
    if gate_cache is not None:
        gate_key = json.dumps([
            *[result[field] for field in ("strands", "forced_ligations", "crossovers", "flexible_segment_marks")],
            [{key: value for key, value in owner.items() if key not in {"translation", "rotation", "pivot"}}
             for owner in result["cluster_transforms"]],
        ], allow_nan=False, separators=(",", ":"))
    if gate_cache is not None and gate_cache.get("key") == gate_key:
        result["flexible_gates"] = deepcopy(gate_cache["gates"])
    else:
        result["flexible_gates"] = all_cluster_gates(design)
        if gate_cache is not None:
            gate_cache.update(key=gate_key, gates=result["flexible_gates"])
    check()
    result["placement_constraints"] = []
    for owner in design.cluster_transforms:
        check()
        if owner.overhang_duplex_driver_id:
            points = duplex_cluster_rotation_points(design, owner)
            if not points:
                reject("Duplex placement has no native rotation-point context", "invalid_preview_reference")
            check()
            frames["rotation_points"][owner.id] = {"frame": "native-rest-with-placement-poses-removed"}
            tethers = duplex_cluster_tethers(design, owner)
            links = []
        else:
            points = []
            tethers = cluster_connection_tethers(design, owner)
            check()
            links = cluster_movable_links(design, owner)
        result["placement_constraints"].append({"cluster_id": owner.id, "rotation_points": points,
                                                "tethers": tethers, "movable_links": links})
    check()
    result["frame_provenance"] = frames
    return result


def _display(prefix, evaluated, *, prepare, include_geometry, envelope, source_entry=None, display_cache=None):
    from backend.api.part_transform_projection import project_admitted

    if type(include_geometry) is not bool:
        reject("Transform geometry choice must be boolean", "invalid_preview_definition")
    check = checkpoint()
    kind = _inputs(prefix, evaluated)
    # The host supplies its retained original row; envelope strings cannot
    # change the lease identity when an explicit upgrade changes row kind.
    source_entry = evaluated.entry if source_entry is None else source_entry
    source_kind, _ = command_input(source_entry)
    if (source_entry.id != evaluated.entry.id or source_kind not in KINDS
            or (source_kind != kind and (source_kind, kind) != ("cluster_op", "placement-poses"))):
        reject("Transform source and evaluated command roles differ", "invalid_preview_definition")
    envelope = _envelope(envelope, prefix, evaluated, source_kind)
    cache_owned = (display_cache is not None and bool(envelope.get("lease_id"))
                   and (prepare or display_cache.get("lease_id") == envelope["lease_id"]))
    gate_cache = dict(display_cache.get("gate_cache", {})) if cache_owned and not prepare else {}
    # Evaluation emits only the independently owned candidate. Admit the
    # historical prefix when it actually supplies a before pane at preparation.
    before = inventory(prefix, check) if prepare else None
    after = inventory(evaluated.design, check)
    native_work = _control_cost(evaluated.design, after) + (before.work * 2 if prepare else 0) + (after.work * 2 if include_geometry else 0)
    limit(native_work, MAX_CONTROL_WORK, "cumulative native display/control work")
    result = {"projection_version": 1, "family": "transform", "command_kind": source_kind,
        "evaluated_command_kind": kind,
        "feature_id": evaluated.entry.id, "stage": "feature", "source_equivalence_checked": False,
        "downstream_evaluated": False, "physical_validity": False,
        "control_state": _controls(evaluated.design, evaluated.params, check, gate_cache if cache_owned else None),
        "candidate": project_admitted(evaluated.design, after, check, compact=True) if include_geometry else None}
    if prepare:
        result.update(control_context=_context(prefix, evaluated.params), before=project_admitted(prefix, before, check, compact=True))
        from backend.api.part_placement_pose_commands import upgrade_descriptor
        result["control_context"]["placement_upgrade"] = (
            upgrade_descriptor(source_entry) if source_kind == "cluster_op" else None)
    elif (display_cache and envelope.get("lease_id") == display_cache.get("lease_id")
          and result["candidate"] is not None and result["candidate"]["component_version"] == 2):
        packed = result["candidate"]["nucleotides"]
        # The complete fresh native projection above still validates geometry
        # and ownership. Omit only scalar rows identical to this lease's before.
        if packed["rows"] == display_cache.get("rows"):
            packed.pop("rows")
            packed["rows_ref"] = envelope["lease_id"]
    check()
    result = _bounded({**result, **envelope})
    if prepare and display_cache is not None:
        display_cache.clear()
        if result.get("lease_id") and result["before"]["component_version"] == 2:
            display_cache.update(lease_id=result["lease_id"],
                                 rows=deepcopy(result["before"]["nucleotides"]["rows"]))
    if cache_owned and display_cache.get("lease_id") == envelope["lease_id"]:
        # Publish only after whole-response admission. The response and lease
        # never share mutable native gate values.
        display_cache["gate_cache"] = deepcopy(gate_cache)
    return result


def prepare_display(prefix, evaluated, *, envelope=None, source_entry=None, display_cache=None):
    return _display(prefix, evaluated, prepare=True, include_geometry=True, envelope=envelope,
                    source_entry=source_entry, display_cache=display_cache)


def evaluate_display(prefix, evaluated, *, include_geometry=True, envelope=None, source_entry=None, display_cache=None):
    return _display(prefix, evaluated, prepare=False, include_geometry=include_geometry, envelope=envelope,
                    source_entry=source_entry, display_cache=display_cache)
