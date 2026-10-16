"""Closed editable native extrusion inputs, independent of publication authority.

Normalization owns JSON and validates the existing request schemas without
executing a builder. The private prefix binder runs only after source proof and
identity preservation, refreshing the edited continuation's derived source
receipt. Untouched saved commands keep their original inputs and semantics.
"""

from copy import deepcopy
from math import isfinite
from types import MappingProxyType
from uuid import UUID

from pydantic import ValidationError

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import validate_operation_input


_COMMON = frozenset({"cells", "length_bp", "plane", "separate_fresh_extrusions"})
_SEGMENT = _COMMON | {"offset_nm", "strand_filter", "ligate_adjacent"}
EDIT_FIELDS = MappingProxyType({
    "bundle-create": _COMMON | {"name", "strand_filter", "lattice_type", "ligate_adjacent"},
    "extrude-segment": _SEGMENT,
    "extrude-continuation": _SEGMENT | {"source_frame_id", "extend_inplace"},
    "extrude-deformed-continuation": _COMMON | {
        "grid_origin", "axis_dir", "frame_right", "frame_up", "ref_helix_id", "source_bp"},
    "extrude-frame": _COMMON | {
        "name", "translation_nm", "rotation_xyzw", "source_frame_id", "source_legacy_plane"},
    "circle-segment": (_SEGMENT - {"length_bp"}) | {"cell_lengths"},
    "overhang-extrude": frozenset({"helix_id", "bp_index", "direction", "is_five_prime",
                                  "neighbor_row", "neighbor_col", "length_bp", "reuse_existing_helix"}),
})
KINDS = frozenset(EDIT_FIELDS)
_TRANSPORT = frozenset({"expected_design_id", "expected_revision"})
_IDENTITY = frozenset({"history_seed", "_proof_version"})
_BOOLS = frozenset({"separate_fresh_extrusions", "ligate_adjacent", "extend_inplace",
                   "source_legacy_plane", "is_five_prime", "reuse_existing_helix"})
_INTS = frozenset({"length_bp", "bp_index", "neighbor_row", "neighbor_col", "source_bp", "expected_revision"})
_VECTORS = {"grid_origin": 3, "axis_dir": 3, "frame_right": 3, "frame_up": 3,
            "translation_nm": 3, "rotation_xyzw": 4}
MAX_CELLS = 512
MAX_WORK = 50_000
MAX_SOURCE_ITEMS = 30_000


def _invalid(detail, *, code="invalid_extrusion_input"):
    raise CommandContractError(detail, code=code)


def _json(value):
    try:
        validate_operation_input(value)
    except ValueError as error:
        _invalid(str(error))


def _schema(kind):
    from backend.api import crud
    from backend.api.routes_frame_extrusion import FrameExtrusionRequest

    return {"bundle-create": crud.BundleRequest,
            "extrude-segment": crud.BundleSegmentRequest,
            "extrude-continuation": crud.BundleContinuationRequest,
            "extrude-deformed-continuation": crud.BundleDeformedContinuationRequest,
            "extrude-frame": FrameExtrusionRequest,
            "circle-segment": crud.CircleSegmentRequest,
            "overhang-extrude": crud.OverhangExtrudeRequest}[kind]


def _protected(kind):
    return (_IDENTITY | (_TRANSPORT if kind in {"extrude-frame", "extrude-continuation"} else set())
            | ({"_source_helix_ids"} if kind == "extrude-continuation" else set()))


def _identity(value, *, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not str or not 1 <= len(value) <= 512:
        _invalid("Extrusion source identities must be bounded nonempty strings.")


def _validate_fields(kind, values):
    # Request models are intentionally legacy-compatible. Reject coercible
    # booleans/strings first at this new closed editing boundary.
    for key in _BOOLS & values.keys():
        if type(values[key]) is not bool:
            _invalid(f"{key} must be a boolean.")
    for key in _INTS & values.keys():
        value = values[key]
        if value is None and key in {"source_bp", "expected_revision"}:
            continue
        if type(value) is not int or value.bit_length() > 64:
            _invalid(f"{key} must be an exact bounded integer.")
    if values.get("expected_revision") is not None and values["expected_revision"] < 0:
        _invalid("expected_revision must be nonnegative.")
    for key in {"helix_id", "history_seed"} & values.keys():
        _identity(values[key])
    for key in {"source_frame_id", "ref_helix_id", "expected_design_id"} & values.keys():
        _identity(values[key], nullable=True)
    if "name" in values and type(values["name"]) is not str:
        _invalid("name must be a string.")
    for key, options in (("plane", {"XY", "XZ", "YZ"}),
                         ("strand_filter", {"both", "scaffold", "staples"}),
                         ("lattice_type", {"HONEYCOMB", "SQUARE"}),
                         ("direction", {"FORWARD", "REVERSE"})):
        if key in values and (type(values[key]) is not str or values[key] not in options):
            _invalid(f"Unsupported {key}.")
    if "offset_nm" in values and type(values["offset_nm"]) not in {int, float}:
        _invalid("offset_nm must be a finite number.")
    for key, length in _VECTORS.items():
        if key not in values:
            continue
        value = values[key]
        if (type(value) is not list or len(value) != length
                or any(type(item) not in {int, float} or not isfinite(item) for item in value)):
            _invalid(f"{key} requires {length} finite numerical components.")
    if "_source_helix_ids" in values:
        sources = values["_source_helix_ids"]
        if type(sources) is not list or len(sources) > MAX_SOURCE_ITEMS:
            _invalid("Continuation source receipt exceeds its allowance.")
        for identity in sources:
            _identity(identity)
        if len(set(sources)) != len(sources):
            _invalid("Continuation source receipt repeats an identity.")
    if "cells" in values:
        cells = values["cells"]
        if type(cells) is not list or not 1 <= len(cells) <= MAX_CELLS:
            _invalid("Extrusion requires between one and 512 cells.", code="extrusion_input_limit")
        seen = set()
        for cell in cells:
            if (type(cell) is not list or len(cell) != 2
                    or any(type(item) is not int or item.bit_length() > 64 for item in cell)):
                _invalid("Cells require two exact bounded integer coordinates.")
            key = tuple(cell)
            if key in seen:
                _invalid("Select each extrusion cell once.")
            seen.add(key)
    if kind == "circle-segment":
        lengths = values.get("cell_lengths")
        if (type(lengths) is not list or len(lengths) != len(values.get("cells", []))
                or any(type(item) is not int or item <= 0 or item.bit_length() > 64 for item in lengths)):
            _invalid("Circle cell lengths must be positive integers matching the cells.")
        work = sum(lengths)
    else:
        length = values.get("length_bp")
        if type(length) is not int or length == 0 or (kind == "overhang-extrude" and length < 1):
            _invalid("Extrusion requires a nonzero length; overhang lengths must be positive.")
        work = abs(length) * (1 if kind == "overhang-extrude" else len(values.get("cells", [])))
    if work > MAX_WORK:
        _invalid("Extrusion exceeds the existing 50000 base-pair-cell proof budget.", code="extrusion_input_limit")
    if kind == "extrude-frame":
        rotation = values.get("rotation_xyzw", [0, 0, 0, 1])
        if abs(sum(item * item for item in rotation) - 1) > 1e-6:
            _invalid("Frame placement requires a unit quaternion.")
        source_frame, legacy = values.get("source_frame_id"), values.get("source_legacy_plane", False)
        if (source_frame or legacy) and (values.get("translation_nm", [0, 0, 0]) != [0, 0, 0]
                                        or rotation != [0, 0, 0, 1]):
            _invalid("A source frame or legacy plane already supplies rigid placement.")
        if source_frame and legacy:
            _invalid("Select either a source frame or the legacy plane.")


def normalize(kind, previous, patch):
    """Return independent complete native parameters, retaining guarded metadata."""
    if type(kind) is not str or kind not in KINDS or type(previous) is not dict or type(patch) is not dict:
        _invalid("Choose an ordinary native extrusion definition.")
    _json(previous)
    _json(patch)
    if {"_generated_scope", "_generator"} & previous.keys():
        _invalid("Generated extrusion definitions use their own editor.", code="unsupported_extrusion_definition")
    protected = _protected(kind)
    if previous.keys() - EDIT_FIELDS[kind] - protected or patch.keys() - EDIT_FIELDS[kind] - protected:
        _invalid("Extrusion definition contains unsupported fields.", code="unsupported_extrusion_definition")
    if type(previous.get("_proof_version")) is not int or previous["_proof_version"] != 1:
        _invalid("Ordinary extrusion editing requires native proof version 1.", code="unsupported_extrusion_definition")
    seed = previous.get("history_seed")
    _identity(seed)
    try:
        UUID(seed)
    except ValueError as error:
        _invalid(f"Extrusion history identity is invalid: {error}")
    for key in protected & patch.keys():
        if (key not in previous or type(patch[key]) is not type(previous[key])
                or patch[key] != previous[key]):
            _invalid("Output identities, proof contracts, transport guards and source receipts cannot be edited.")
    values = {**previous, **{key: value for key, value in patch.items() if key in EDIT_FIELDS[kind]}}
    _json(values)
    _validate_fields(kind, values)
    schema = _schema(kind)
    native = {key: value for key, value in values.items() if key in schema.model_fields}
    # Native frame replay supplies current guards itself. Validate historical
    # rows without inventing absent transport fields in their recorded inputs.
    if kind == "extrude-frame":
        native.setdefault("expected_design_id", "owned-prefix")
        native.setdefault("expected_revision", 0)
    try:
        result = schema.model_validate(native).model_dump(mode="json")
    except ValidationError as error:
        _invalid(str(error))
    for key in protected:
        result.pop(key, None)
        if key in previous:
            result[key] = deepcopy(previous[key])
    _json(result)
    return result


def _source_reference(prefix, collection, identity, kind, path):
    items = getattr(prefix, collection)
    if type(items) is not list or len(items) > MAX_SOURCE_ITEMS:
        _invalid("Extrusion source inventory exceeds its allowance.", code="extrusion_input_limit")
    matches = []
    for item in items:
        _identity(item.id)
        if item.id == identity:
            matches.append(item)
    if len(matches) != 1:
        raise ReferenceResolutionError("Extrusion source is missing or ambiguous.",
            code="invalid_selection" if matches else "missing_reference",
            references=[{"kind": kind, "identity": identity, "parameter_path": [path]}])
    return matches[0]


def bind_prefix(kind, params, prefix):
    """Bind the selected edit to the independently proved pre-feature Design.

    This is a private evaluator callback, never a caller-supplied receipt. It
    performs bounded metadata work only; native execution still owns source
    geometry, occupancy, topology, endpoint and scientific validation.
    """
    if type(kind) is not str or kind not in KINDS or type(params) is not dict:
        _invalid("Choose an ordinary native extrusion definition.")
    _json(params)
    result = deepcopy(params)
    if kind in {"extrude-continuation", "extrude-frame"} and result.get("source_frame_id") is not None:
        identity = result["source_frame_id"]
        frame = _source_reference(prefix, "lattice_frames", identity, "lattice_frame", "source_frame_id")
        if frame.plane != result["plane"]:
            raise ReferenceResolutionError("The selected source frame uses a different plane.", code="invalid_selection",
                references=[{"kind": "lattice_frame", "identity": identity, "parameter_path": ["source_frame_id"]}])
    if kind == "extrude-deformed-continuation" and result.get("ref_helix_id") is not None:
        _source_reference(prefix, "helices", result["ref_helix_id"], "helix", "ref_helix_id")
    elif kind == "overhang-extrude":
        _source_reference(prefix, "helices", result["helix_id"], "helix", "helix_id")
    if kind == "extrude-continuation":
        from backend.api.crud import BundleContinuationRequest
        from backend.api.part_extrusion_commands import continuation_sources

        if type(prefix.helices) is not list or len(prefix.helices) > MAX_SOURCE_ITEMS:
            _invalid("Continuation source inventory exceeds its allowance.", code="extrusion_input_limit")
        for helix in prefix.helices:
            _identity(helix.id)
        result["_source_helix_ids"] = continuation_sources(prefix, BundleContinuationRequest.model_validate(result))
    _json(result)
    return result
