"""Private native feature-stage display and controls from independently owned inputs.

No live source, session, publication, renderer or cache is read here. The host
supplies a copy of the fixed prefix and an isolated EvaluatedPreview. These DTOs
are display values, never authoring inputs or proof/physical-validity receipts.
The existing comparison host and its v2 wire contract remain unchanged.
"""

import json
from math import isfinite
from time import monotonic

from backend.api.part_deformation_preview import EvaluatedPreview, _work
from backend.core.models import Design
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison_contract import DNA_FIELDS, check_scope
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_verification_capture import admit


PROJECTION_VERSION = 1
MAX_OUTPUT_NODES = 200_000
MAX_OUTPUT_BYTES = 2_000_000
_NON_GEOMETRY = frozenset({"dimensions", "lattice_type", "metadata", "tm_settings"})
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
        admit(design, preserve_entry_types=True)
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
    from backend.core.deformation_scope import resolve_deformation_targets, selection_boundary_warning
    from backend.core.loop_skip_calculator import classify_deformation

    identities = op.affected_helix_ids or helices_crossing_planes(prefix, op.plane_a_bp, op.plane_b_bp)
    identities = resolve_cluster_scope(prefix, op.cluster_ids, identities)["helix_ids"]
    ranges = None
    if op.targets is not None:
        ranges = resolve_deformation_targets(prefix, op.targets)
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


def _controls(prefix, op):
    # _inputs has already charged the complete prefix and concrete operation
    # under the ordinary 30k/2MB admission, before these model_dump allocations.
    result = {name: [item.model_dump(mode="json", include=fields) for item in getattr(prefix, name)]
              for name, fields in _CONTROL_FIELDS.items()}
    result.update(
        deformations=[item.model_dump(mode="json") for item in prefix.deformations],
        forced_ligations=[item.model_dump(mode="json") for item in prefix.forced_ligations],
        selected_operation=op.model_dump(mode="json"),
        capabilities={"change_targets": False, "change_clusters": False,
                      "native_feasibility": True, "polymer_circle_inputs": True},
    )
    return result


def _bounded(result):
    # Count the entire response, not each pane separately. GraphBudget supplies
    # the shared structural/string accounting; finite JSON encoding additionally
    # enforces actual wire bytes without retaining another encoded copy.
    try:
        budget = GraphBudget(max_nodes=MAX_OUTPUT_NODES, max_bytes=MAX_OUTPUT_BYTES,
                             seconds=None, clock=monotonic)
        budget.charge(result)
        size = 0
        for chunk in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(result):
            size += len(chunk.encode("utf-8"))
            if size > MAX_OUTPUT_BYTES:
                raise CaptureLimit("Deformation preview exceeds its combined display byte allowance")
    except CaptureLimit as error:
        _reject(str(error), "preview_limit")
    except (TypeError, ValueError) as error:
        _reject(f"Invalid preview display transport: {error}", "invalid_preview_geometry")
    return result


def _base(feasibility):
    return {"projection_version": PROJECTION_VERSION, "stage": "feature",
            "source_equivalence_checked": False, "downstream_evaluated": False,
            "physical_validity": False, "feasibility": feasibility}


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


def prepare_display(prefix, original, *, envelope=None):
    """Before/original display plus controls from the fixed historical prefix."""
    from backend.core.part_dna_comparison import project_for_deformation_preview

    envelope = _envelope(envelope)
    op = _inputs(prefix, original)
    result = {**_base(_feasibility(prefix, op)), "control_context": _controls(prefix, op),
              "before": _native(project_for_deformation_preview, prefix),
              "candidate": _native(project_for_deformation_preview, original.design)}
    return _bounded({**result, **envelope})


def evaluate_display(prefix, evaluated, *, include_geometry=True, envelope=None):
    """One local candidate; feedback remains available with visual preview off."""
    from backend.core.part_dna_comparison import project_for_deformation_preview

    if type(include_geometry) is not bool:
        _reject("Preview geometry choice must be a boolean", "invalid_preview_definition")
    envelope = _envelope(envelope)
    op = _inputs(prefix, evaluated)
    result = {**_base(_feasibility(prefix, op)),
              "candidate": _native(project_for_deformation_preview, evaluated.design) if include_geometry else None}
    return _bounded({**result, **envelope})
