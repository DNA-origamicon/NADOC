"""Private native feature-stage display and controls from independently owned inputs.

No live source, session, publication, renderer or cache is read here. The host
supplies a copy of the fixed prefix and an isolated EvaluatedPreview. These DTOs
are display values, never authoring inputs or proof/physical-validity receipts.
The display retains historical interval provenance without re-resolving prior
operations against current topology. No comparison or live host gate is enabled.
"""

from math import isfinite
from time import monotonic

from backend.api import part_deformation_preview as _limits
from backend.api.part_deformation_preview import EvaluatedPreview, PreparedCreation, _work, creation_scope
from backend.core.models import Design
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison_contract import DNA_FIELDS, check_scope
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_verification_capture import admit


PROJECTION_VERSION = 2
# Sized for ordinary origami parts (an 18-helix x 504-bp part is ~16 MB).
MAX_OUTPUT_NODES = 50_000_000
MAX_OUTPUT_BYTES = 256_000_000
_NON_GEOMETRY = frozenset({"dimensions", "lattice_type", "metadata", "tm_settings", "group_organization"})
_CONTROL_FIELDS = {
    "helices": {"id", "bp_start", "length_bp", "axis_start", "axis_end"},
    "strands": {"id", "strand_type", "domains", "notes", "is_reference"},
    "cluster_transforms": {"id", "name", "is_default", "helix_ids", "domain_ids",
                           "parent_cluster_id", "translation", "rotation", "pivot"},
}
_ENVELOPE_STRINGS = {
    "preview_id": 256, "expected_design_id": 256, "feature_id": 256,
    "lease_id": 256, "doc_id": 1024, "deformation_id": 256,
}
_ENVELOPE_INTEGERS = frozenset({"expected_revision", "request_sequence"})
_ENVELOPE_FIELDS = frozenset(_ENVELOPE_STRINGS) | _ENVELOPE_INTEGERS | {"remaining_seconds"}


def _reject(detail, code="unsupported_preview_scope"):
    raise CommandContractError(detail, code=code)


def _native(call, *args, **kwargs):
    """Keep actionable preview codes without masking unexpected native defects."""
    try:
        return call(*args, **kwargs)
    except CommandContractError as error:
        code = {"comparison_limit": "preview_limit",
                "unsupported_comparison_scope": "unsupported_preview_scope",
                "invalid_comparison_reference": "invalid_preview_reference",
                "invalid_comparison_geometry": "invalid_preview_geometry"}.get(error.code)
        if code is None:
            raise
        _reject(str(error), code)


def _admit(design):
    if type(design) is not Design or set(Design.model_fields) != set(FIELD_ROLES):
        _reject("Preview display requires the reviewed standard-part schema")
    # Whole-model closure precedes any geometry: companion assets may not simply
    # disappear because the reused DNA component handles only DNA itself.
    for name, role in FIELD_ROLES.items():
        if role == "authoring" and name not in DNA_FIELDS | _NON_GEOMETRY and getattr(design, name):
            _reject(f"Deformation preview does not yet display {name}")
    try:
        admit(design, max_nodes=_limits.MAX_CAPTURE_NODES, max_bytes=_limits.MAX_CAPTURE_BYTES,
              preserve_entry_types=True)
    except CaptureLimit as error:
        _reject(str(error), "preview_limit")
    _work(design, lambda: None)
    _native(check_scope, design)


def _inputs(prefix, evaluated):
    if type(evaluated) is not EvaluatedPreview or type(prefix) is not Design:
        _reject("Preview display requires owned prefix and evaluation values", "invalid_preview_definition")
    _admit(prefix)
    _admit(evaluated.design)
    op = evaluated.entry.op_snapshot
    if (op is None or op.id != evaluated.entry.deformation_id
            or not evaluated.design.deformations
            or evaluated.design.deformations[-1] != op
            or prefix.id != evaluated.design.id
            or any(previous.id == op.id for previous in prefix.deformations)):
        _reject("Preview operation does not match its owned feature-stage inputs", "invalid_preview_definition")
    if evaluated.stage != "feature" or evaluated.source_equivalence_checked or evaluated.downstream_evaluated:
        _reject("Preview values cannot assert source or downstream proof", "invalid_preview_definition")
    return op


def _feasibility(prefix, op):
    """Same native classification and selection warning as the ordinary editor."""
    from backend.core.deformation import helices_crossing_planes, resolve_cluster_scope
    from backend.core.deformation_scope import selection_boundary_warning
    from backend.core.part_group_selection import resolve_deformation_targets
    from backend.core.loop_skip_calculator import classify_deformation

    identities = op.affected_helix_ids or helices_crossing_planes(prefix, op.plane_a_bp, op.plane_b_bp)
    identities = resolve_cluster_scope(prefix, op.cluster_ids, identities)["helix_ids"]
    ranges = None
    if op.targets is not None:
        # The selected operation was built on this exact owned prefix. Reuse
        # its resolved intervals; prior retained operations are never retargeted.
        ranges = op.target_ranges if op.target_ranges is not None else resolve_deformation_targets(prefix, op.targets)
        identities = sorted({item.helix_id for item in ranges})
        if not any(item.start_bp < op.plane_b_bp and item.end_bp > op.plane_a_bp for item in ranges):
            _reject("Selection does not intersect the deformation window", "invalid_preview_reference")
    wanted = set(identities)
    result = classify_deformation([helix for helix in prefix.helices if helix.id in wanted],
                                  op.plane_a_bp, op.plane_b_bp, op.type, op.params, design=prefix)
    boundary = selection_boundary_warning(prefix, ranges)
    if boundary:
        result = {**result, "status": result["status"] if result["status"] != "ok" else "warn",
                  "message": " ".join(filter(None, [result.get("message"), boundary["message"]]))}
    return result


def _control_inputs(prefix):
    # The caller has charged the complete owned prefix before serialization.
    result = {name: [item.model_dump(mode="json", include=fields) for item in getattr(prefix, name)]
              for name, fields in _CONTROL_FIELDS.items()}
    result.update(
        group_organization=(prefix.group_organization.model_dump(mode="json")
                            if prefix.group_organization is not None else None),
        deformations=[item.model_dump(mode="json") for item in prefix.deformations],
        forced_ligations=[item.model_dump(mode="json") for item in prefix.forced_ligations],
    )
    return result


def _controls(prefix, op):
    from backend.core.part_deformation_edit import can_edit_groups, can_edit_named_groups

    result = _control_inputs(prefix)
    result.update(selected_operation=op.model_dump(mode="json"),
        capabilities={"change_targets": can_edit_named_groups(op), "change_clusters": can_edit_groups(op),
                      "native_feasibility": True, "polymer_circle_inputs": True},
    )
    return result


def _encoded_size(result, trusted=()):
    """Compact UTF-8 JSON size, refusing NaN/inf like ``json.dumps(allow_nan=False)``.

    orjson (the response encoder) is much faster on multi-MB native displays but
    writes NaN/inf as null, so non-finite floats are refused by an explicit walk.
    ``trusted`` subtrees (native nucleotide rows and helix axes) were already
    coordinate-checked by the DNA projection and are not walked again. Sizes
    equal the compact stdlib encoding up to float spelling.
    """
    import orjson

    skip = {id(item) for item in trusted}

    def finite(value):
        if id(value) in skip:
            return
        kind = type(value)
        if isinstance(value, float):  # includes numpy.float64
            if not isfinite(value):
                raise ValueError("Out of range float values are not JSON compliant")
        elif kind is dict:
            for item in value.values():
                finite(item)
        elif kind is list or kind is tuple:
            for item in value:
                finite(item)

    finite(result)
    # Same options as the ORJSONResponse that sends this payload.
    return len(orjson.dumps(result, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY))


def _validated_panes(result):
    """Projection-checked coordinate subtrees of the before/candidate panes."""
    panes = [result.get(name) for name in ("before", "candidate")]
    return [pane[key] for pane in panes if type(pane) is dict for key in ("nucleotides", "helix_axes") if key in pane]


def _bounded(result, *, max_nodes=None, max_bytes=None, trusted=()):
    # Count the entire response, not each pane separately. One finite JSON
    # encoding enforces actual wire bytes and refuses NaN/inf (the orjson response
    # would otherwise emit null). json.dumps uses the C encoder; the former chunked
    # iterencode ran the pure-Python encoder and dominated evaluation on real parts.
    # Every JSON node occupies at least one byte, so when the encoded size is
    # within the node allowance the structural walk cannot refuse and is skipped.
    # Other strict reads reuse this contract with their own (smaller) allowances.
    max_nodes = MAX_OUTPUT_NODES if max_nodes is None else max_nodes
    max_bytes = MAX_OUTPUT_BYTES if max_bytes is None else max_bytes
    try:
        size = _encoded_size(result, trusted)
        if size > max_bytes:
            raise CaptureLimit("Deformation preview exceeds its combined display byte allowance")
        if size > max_nodes:
            GraphBudget(max_nodes=max_nodes, max_bytes=max_bytes,
                        seconds=None, clock=monotonic).charge(result)
    except CaptureLimit as error:
        _reject(str(error), "preview_limit")
    except (TypeError, ValueError) as error:
        _reject(f"Invalid preview display transport: {error}", "invalid_preview_geometry")
    return result


def _base(feasibility, operation):
    return {"projection_version": PROJECTION_VERSION, "stage": "feature",
            "source_equivalence_checked": False, "downstream_evaluated": False,
            "physical_validity": False, "feasibility": feasibility,
            # Explicit selected-stage intervals keep private plane guides in
            # sync even when native visual projection is switched off.
            "selected_scope": operation.model_dump(mode="json", include={
                "id", "affected_helix_ids", "target_ranges"})}


def _envelope(value):
    """Own a small host identity mapping; it cannot replace display/proof fields."""
    if value is None:
        return {}
    if type(value) is not dict or len(value) > len(_ENVELOPE_FIELDS):
        _reject("Preview host envelope must be a bounded scalar object", "invalid_preview_definition")
    for key, item in value.items():
        if type(key) is not str or key not in _ENVELOPE_FIELDS:
            _reject("Preview host envelope contains an unsupported or colliding field", "invalid_preview_definition")
        if key in _ENVELOPE_STRINGS:
            valid = type(item) is str and 0 < len(item) <= _ENVELOPE_STRINGS[key]
        elif key in _ENVELOPE_INTEGERS:
            valid = type(item) is int and item >= 0 and item.bit_length() <= 64
        else:
            valid = ((type(item) is int and item >= 0 and item.bit_length() <= 64)
                     or (type(item) is float and item >= 0 and isfinite(item)))
        if not valid:
            _reject(f"Invalid preview host envelope field: {key}", "invalid_preview_definition")
    return dict(value)


def _remember_rows(result, cache, prefix):
    # Only the owning session retains this small topology-only portion. Never
    # retain coordinates, a live design, or publication authority here.
    if cache is not None and result.get("lease_id"):
        from copy import deepcopy
        from backend.core.part_dna_comparison_contract import inventory
        cache.clear()
        cache.update(lease_id=result["lease_id"], rows=deepcopy(result["before"]["nucleotides"]["rows"]))
        cache["inventory"] = _native(inventory, prefix.model_copy(deep=True))
    return result


def prepare_display(prefix, original, *, envelope=None, display_cache=None):
    """Before/original display plus controls from the fixed historical prefix."""
    from backend.core.part_dna_comparison import project_for_deformation_preview

    envelope = _envelope(envelope)
    op = _inputs(prefix, original)
    result = {**_base(_feasibility(prefix, op), op), "control_context": _controls(prefix, op),
              "before": _native(project_for_deformation_preview, prefix),
              "candidate": _native(project_for_deformation_preview, original.design)}
    result = {**result, **envelope}
    return _remember_rows(_bounded(result, trusted=_validated_panes(result)), display_cache, prefix)


def prepare_creation_display(prefix, prepared, *, envelope=None, display_cache=None):
    """Owned latest-stage controls before the user has authored two planes."""
    from backend.core.part_dna_comparison import project_for_deformation_preview

    if type(prepared) is not PreparedCreation or type(prefix) is not Design or prefix.id != prepared.design_id:
        _reject("Creation controls require their owned prefix", "invalid_preview_definition")
    _admit(prefix)
    envelope = _envelope(envelope)
    creation = prepared.creation_inputs()
    identities, ranges = creation_scope(prefix, creation["targets"], creation["cluster_ids"])
    controls = {**_control_inputs(prefix), "creation": creation, "selected_operation": None,
                "capabilities": {"change_targets": False, "change_clusters": creation["targets"] is None,
                                 "native_feasibility": True, "polymer_circle_inputs": True}}
    result = {"projection_version": PROJECTION_VERSION, "mode": "create", "awaiting_parameters": True,
              "stage": "feature", "source_equivalence_checked": False, "downstream_evaluated": False,
              "physical_validity": False, "feasibility": None,
              "selected_scope": {"id": prepared.deformation_id, "affected_helix_ids": identities,
                                 "target_ranges": None if ranges is None else [r.model_dump(mode="json") for r in ranges]},
              "control_context": controls, "before": _native(project_for_deformation_preview, prefix),
              "candidate": None}
    result = {**result, **envelope}
    return _remember_rows(_bounded(result, trusted=_validated_panes(result)), display_cache, prefix)


def evaluate_display(prefix, evaluated, *, include_geometry=True, envelope=None, creation=False, display_cache=None):
    """One local candidate; feedback remains available with visual preview off."""
    from backend.core.part_dna_comparison import project_for_deformation_preview

    if type(include_geometry) is not bool or type(creation) is not bool:
        _reject("Preview geometry choice must be a boolean", "invalid_preview_definition")
    envelope = _envelope(envelope)
    op = _inputs(prefix, evaluated)
    cached_inventory = (display_cache.get("inventory") if display_cache
                        and envelope.get("lease_id") == display_cache.get("lease_id") else None)
    result = {**_base(_feasibility(prefix, op), op),
              "candidate": _native(project_for_deformation_preview, evaluated.design,
                                   inventory_cache=cached_inventory) if include_geometry else None}
    if creation:
        result.update(mode="create", awaiting_parameters=False)
    result = {**result, **envelope}
    if (include_geometry and display_cache and envelope.get("lease_id") == display_cache.get("lease_id")):
        packed = result["candidate"]["nucleotides"]
        # Compare every scalar, in order: any changed ownership/flag receives a
        # full packet. Coordinates and their native guards always run above.
        if packed["rows"] == display_cache["rows"]:
            packed.pop("rows")
            packed["rows_ref"] = envelope["lease_id"]
    return _bounded(result, trusted=_validated_panes(result))
