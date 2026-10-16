"""Bounded definition admission for an explicit recipe-file recovery operation.

This is neither the ordinary Design loader nor a recovery certificate. Saved
geometry, physical state, presentation and draft metadata stay in the original
bytes only. The caller must check command coverage, source integrity and native
reconstruction before offering a recovered copy.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import math

from pydantic import TypeAdapter, ValidationError

from backend.core.models import Design, DesignMetadata, FeatureLogEntry
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import PartRecipeRoot
from backend.core.part_input_sources import Digest, EmbeddedInput, MAX_SOURCES


MAX_FILE_BYTES = 1_500_000
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 30_000
MAX_GRAPH_BYTES = 8_000_000
MAX_HISTORY_ROWS = 2_000
_ENVELOPE_FIELDS = frozenset({"id", "recipe_root", "feature_log", "input_sources",
                              "feature_log_cursor", "feature_log_sub_cursor"})
_RECOVERY_FIELDS = {
    "snapshot": frozenset({"design_snapshot_gz_b64", "snapshot_size_bytes", "post_state_gz_b64",
                           "post_state_size_bytes", "evicted", "diff_added_b64", "diff_removed_ids",
                           "diff_modified_b64", "pre_state_from_previous"}),
    "routing-cluster": frozenset({"pre_state_gz_b64", "pre_state_size_bytes", "post_state_gz_b64",
                                  "post_state_size_bytes", "evicted", "diffs_evicted"}),
    "minor": frozenset({"diff_added_b64", "diff_removed_b64", "diff_modified_b64", "diff_size_bytes"}),
}
_ROW_TYPES = frozenset({"snapshot", "routing-cluster", "deformation", "cluster_create",
                        "cluster_op", "overhang_rotation"})
_ROW_ADAPTER = TypeAdapter(FeatureLogEntry)
_ROOT_ADAPTER = TypeAdapter(PartRecipeRoot)
_SOURCES_ADAPTER = TypeAdapter(dict[Digest, EmbeddedInput])


class RecipeFileError(CommandContractError):
    """Admission failed; no editable Design or proof is implied."""


@dataclass(frozen=True)
class AdmittedRecipeFile:
    """Detached carrier plus immutable original evidence; not deep-frozen state."""

    original_bytes: bytes
    original_sha256: str
    source: Design
    excluded_fields: tuple[str, ...]
    stripped_recovery_fields: tuple[tuple[str | int, ...], ...]


def _reject(detail, *, limit=False):
    raise RecipeFileError(detail, code="recipe_file_limit" if limit else "recipe_file_invalid")


def _scan(text, check):
    """Bound valid JSON token starts/depth before allocating its decoded graph.

    This does not interpret values or accept syntax. stdlib JSON remains the
    syntax authority; escaped delimiters inside strings never count as nesting.
    """
    quoted = escaped = primitive = False
    depth = nodes = 0
    for offset, char in enumerate(text):
        if offset % 4096 == 0:
            check()
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char.isspace() or char in ",:":
            primitive = False
            continue
        if char in "]}":
            primitive = False
            depth -= 1
            continue
        if char == '"':
            quoted, primitive = True, False
        elif char in "[{":
            primitive = False
            depth += 1
            if depth > MAX_JSON_DEPTH:
                _reject("Recipe JSON nesting exceeds its admission limit", limit=True)
        elif primitive:
            continue
        else:
            primitive = True
        nodes += 1
        if nodes > MAX_JSON_NODES:
            _reject("Recipe JSON exceeds its node admission limit", limit=True)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject("Recipe JSON contains duplicate fields")
        result[key] = value
    return result


def _finite(value):
    number = float(value)
    if not math.isfinite(number):
        _reject("Recipe JSON requires finite numbers")
    return number


def _constant(_value):
    _reject("Recipe JSON requires finite numbers")


def _identity(value):
    if type(value) is not str or not 1 <= len(value) <= 256:
        _reject("Recipe definitions require explicit identities of 1–256 characters")
    return value


def _typed(adapter, value):
    # JSON-mode strict validation admits canonical JSON enum/tuple values while
    # refusing coercion and unknown fields recursively in typed definitions.
    try:
        return adapter.validate_json(json.dumps(value, separators=(",", ":"), allow_nan=False),
                                     strict=True, extra="forbid")
    except (ValidationError, ValueError, TypeError) as exc:
        _reject(f"Recipe definition schema is invalid: {str(exc)[:1024]}")


def _rows(raw_rows, check):
    if type(raw_rows) is not list or not raw_rows:
        _reject("Recipe recovery requires a nonempty feature log")
    identities, stripped = set(), []

    def header(raw, path, *, child=False):
        check()
        if type(raw) is not dict or type(raw.get("feature_type")) is not str:
            _reject("Every recipe row requires an explicit feature type")
        kind = raw["feature_type"]
        if kind not in ({"minor"} if child else _ROW_TYPES):
            _reject("Recipe contains an unsupported feature row type")
        identity = _identity(raw.get("id"))
        if identity in identities:
            _reject("Recipe feature and routing-child identities must be unique")
        identities.add(identity)
        if len(identities) > MAX_HISTORY_ROWS:
            _reject("Recipe exceeds its feature-row admission limit", limit=True)
        if "proof_version" in raw and raw["proof_version"] is not None and type(raw["proof_version"]) is not int:
            _reject("Recipe proof versions require exact integers")
        if kind in {"snapshot", "minor"}:
            if type(raw.get("params")) is not dict:
                _reject("Command rows require an explicit params object")
            if "_proof_version" in raw["params"] and type(raw["params"]["_proof_version"]) is not int:
                _reject("Recipe proof versions require exact integers")
        # These are the only nested typed identity-producing models in the
        # admitted FeatureLogEntry union. Check before Pydantic can mint an ID.
        nested = {"cluster_create": "cluster_snapshot", "deformation": "op_snapshot"}.get(kind)
        if nested and raw.get(nested) is not None:
            if type(raw[nested]) is not dict:
                _reject("Recipe overlay input must be an object")
            _identity(raw[nested].get("id"))
        removed = _RECOVERY_FIELDS.get(kind, ())
        stripped.extend((*path, name) for name in raw if name in removed)
        output = {name: value for name, value in raw.items() if name not in removed}
        if kind == "routing-cluster":
            children = raw.get("children")
            if type(children) is not list or not children:
                _reject("Recipe routing groups require explicit nonempty children")
            output["children"] = [header(item, (*path, "children", index), child=True)
                                  for index, item in enumerate(children)]
        return output

    rows = [_typed(_ROW_ADAPTER, header(raw, ("feature_log", index)))
            for index, raw in enumerate(raw_rows)]
    return rows, tuple(stripped)


def admit_recipe_file(raw: bytes, *, checkpoint=None) -> AdmittedRecipeFile:
    """Admit definitions only; never load, publish or regenerate saved geometry.

    The 1.5 MB transport bound is separate from the caller's ordinary proof
    capture/worker budgets. Named source bytes remain encoded and unverified
    here; explicit evaluation must resolve and verify them before replay.
    """
    check = checkpoint if checkpoint is not None else lambda: None
    check()
    if type(raw) is not bytes:
        _reject("Recipe recovery requires immutable original bytes")
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        _reject("Recipe file exceeds its 1.5 MB admission limit", limit=True)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        _reject(f"Recipe file is not UTF-8: {str(exc)[:256]}")
    # Caller cancellation remains its original exception, including ValueError.
    _scan(text, check)
    try:
        data = json.loads(text, object_pairs_hook=_unique, parse_constant=_constant, parse_float=_finite)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, RecipeFileError):
            raise
        _reject(f"Recipe file is not bounded UTF-8 JSON: {str(exc)[:256]}")

    def shape(value):
        check()
        if type(value) is str:
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeError:
                _reject("Recipe JSON contains an invalid Unicode string")

    try:
        GraphBudget(max_nodes=MAX_JSON_NODES, max_bytes=MAX_GRAPH_BYTES,
                    seconds=None, clock=lambda: 0).charge(data, validate=shape)
    except CaptureLimit as exc:
        raise RecipeFileError("Recipe JSON exceeds its graph admission limit", code="recipe_file_limit") from exc
    if type(data) is not dict or set(data) - Design.model_fields.keys():
        _reject("Recipe recovery accepts only known standard-part document fields")
    identity = _identity(data.get("id"))
    if (type(data.get("feature_log_cursor")) is not int or data["feature_log_cursor"] != -1
            or "feature_log_sub_cursor" not in data or data["feature_log_sub_cursor"] is not None):
        _reject("Recipe recovery requires an explicit latest history cursor")
    root_data = data.get("recipe_root")
    if (type(root_data) is not dict or not {"version", "kind", "lattice_type", "initial_name"} <= root_data.keys()
            or type(root_data["version"]) is not int or root_data["version"] != 1
            or root_data["kind"] != "empty" or root_data.get("source_json") is not None
            or root_data.get("source_sha256") is not None):
        _reject("Recipe recovery currently requires an explicit native empty root v1")
    root = _typed(_ROOT_ADAPTER, root_data)
    rows, stripped = _rows(data.get("feature_log"), check)
    sources = data.get("input_sources", {})
    if type(sources) is not dict or len(sources) > MAX_SOURCES:
        _reject("Recipe input source table exceeds its admission limit", limit=True)
    sources = _typed(_SOURCES_ADAPTER, sources)
    check()
    source = Design(id=identity, recipe_root=root, feature_log=rows, input_sources=sources,
                    lattice_type=root.lattice_type, metadata=DesignMetadata(name=root.initial_name))
    check()
    return AdmittedRecipeFile(raw, sha256(raw).hexdigest(), source,
                              tuple(sorted(set(data) - _ENVELOPE_FIELDS)), stripped)
