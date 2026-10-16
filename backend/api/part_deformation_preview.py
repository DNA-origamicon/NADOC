"""Private, bounded feature-stage bend/twist evaluation from native inputs.

The caller supplies independently owned input captured under its source lock
with preserve_entry_types=True. This module has no live document access, cache,
session/revision lease, publication path, geometry DTO, or proof certificate.
Only the prefix is executed; source equivalence and the suffix remain unchecked.
The time allowance is cooperative between native calls, not a hard wall limit.
"""

from dataclasses import dataclass
from time import monotonic

from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import BendParams, DeformationLogEntry, DeformationOp, Design, TwistParams
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import command_rows, root_design
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import command_input, edit_entry
from backend.core.part_verification_capture import CaptureLimit, admit
from backend.core.validator import ValidationReport, validate_design


MAX_COMMANDS = 128
MAX_HELICES = 16
MAX_SLOTS = 1024
MAX_OPERATIONS = 64
MAX_BP_SPAN = 1024
SECONDS = 1.0
PREFIX_KINDS = frozenset({"bundle-create", "deformation", "cluster_create", "cluster_op"})
PATCH_FIELDS = frozenset({"type", "plane_a_bp", "plane_b_bp", "params", "cluster_ids"})


def _reject(detail, code="unsupported_preview_scope"):
    raise CommandContractError(detail, code=code)


def _checkpoint():
    deadline = monotonic() + SECONDS

    def check():
        if monotonic() > deadline:
            _reject("Deformation preview exceeded its cooperative time allowance", "preview_limit")

    return check


def _admit(design, check):
    check()
    try:
        admit(design, preserve_entry_types=True)
    except CaptureLimit as error:
        _reject(str(error), "preview_limit")
    check()


def _identity(value):
    if type(value) is not str or not value or len(value) > 256:
        _reject("Preview requires a bounded stable feature identity", "invalid_preview_definition")
    return value


def _json(value):
    try:
        validate_operation_input(value)
    except ValueError as error:
        _reject(str(error), "invalid_preview_definition")


def _bp(value):
    if type(value) is not int or abs(value) > 1_000_000:
        _reject("Preview requires bounded integer base-pair addresses", "preview_limit")
    return value


def _operation(op, design):
    if op.type not in {"bend", "twist"} or op.type != op.params.kind:
        _reject("This private preview supports ordinary bend and twist definitions only")
    a, b = _bp(op.plane_a_bp), _bp(op.plane_b_bp)
    if a >= b:
        _reject("The first deformation plane must precede the second", "invalid_preview_definition")
    # Native endpoint-fit evaluation may construct frame tables across gaps;
    # bounded site counts alone would not bound an outlying control plane.
    addresses = [a, b]
    for helix in design.helices:
        addresses.extend((_bp(helix.bp_start), _bp(helix.bp_start + helix.length_bp - 1)))
    if max(addresses) - min(addresses) + 1 > MAX_BP_SPAN:
        _reject("Deformation preview exceeds its frame-span allowance", "preview_limit")


def _work(design, check):
    check()
    if len(design.helices) > MAX_HELICES or len(design.deformations) + len(design.cluster_transforms) > MAX_OPERATIONS:
        _reject("Deformation preview exceeds its object allowance", "preview_limit")
    slots = 0
    for helix in design.helices:
        check()
        if type(helix.length_bp) is not int or helix.length_bp < 1:
            _reject("Deformation preview requires positive native helix spans", "invalid_preview_definition")
        slots += 2 * (helix.length_bp + sum(max(0, mark.delta) for mark in helix.loop_skips))
        if slots > MAX_SLOTS:
            _reject("Deformation preview exceeds its native site allowance", "preview_limit")
    walk = sum(abs(domain.end_bp - domain.start_bp) + 1
               for strand in design.strands for domain in strand.domains)
    if walk > MAX_SLOTS:
        _reject("Deformation preview exceeds its occupied-domain allowance", "preview_limit")
    for op in design.deformations:
        _operation(op, design)
    check()


def _before_command(kind, params, design):
    if kind not in PREFIX_KINDS or "_generated_scope" in params:
        _reject(f"Private deformation preview does not yet replay prefix command {kind!r}")
    if kind == "bundle-create":
        # The shared executor still enforces its own 512-cell/50k-bp guard.
        # This lower private-preview allowance bounds its first allocation.
        cells, length = params.get("cells"), params.get("length_bp")
        if (type(cells) is not list or type(length) is not int or length < 1
                or len(cells) > MAX_HELICES or 2 * len(cells) * length > MAX_SLOTS):
            _reject("Bundle exceeds the private preview site allowance", "preview_limit")
    elif kind == "deformation":
        try:
            op = DeformationOp.model_validate({k: v for k, v in params.items() if k != "_proof_version"})
        except ValueError as error:
            _reject(str(error), "invalid_preview_definition")
        _operation(op, design)


def _run(kind, design, params, check):
    check()
    _before_command(kind, params, design)
    try:
        updated = execute(kind, design, params)
    except CommandContractError:
        raise
    except (ValueError, TypeError, KeyError, NotImplementedError) as error:
        _reject(str(error), "preview_command_failed")
    check()
    _admit(updated, check)
    _work(updated, check)
    return updated


@dataclass(frozen=True, slots=True)
class PreparedPreview:
    """Internal retained inputs; callers receive copies, never the owned prefix.

    Its private models are not an immutable public API or a host lease. The
    future host must own this object exclusively and bind it to its session.
    """

    feature_id: str
    deformation_id: str
    design_id: str
    _prefix: Design
    _entry: DeformationLogEntry

    def copy_prefix(self):
        """Independent control-context input; contains no recovery/history rows."""
        return self._prefix.model_copy(deep=True)


@dataclass(frozen=True, slots=True)
class EvaluatedPreview:
    design: Design
    entry: DeformationLogEntry
    validation: ValidationReport
    stage: str = "feature"
    source_equivalence_checked: bool = False
    downstream_evaluated: bool = False


def prepare_from_capture(captured, feature_id):
    """Replay only the selected feature's prefix from an explicit empty root.

    Complete history coverage and identity uniqueness are checked cheaply, but
    suffix command references/output and source equivalence are not evaluated.
    Capture/resource admission is not schema validation or a proof certificate.
    """
    check = _checkpoint()
    check()
    if type(captured) is not Design or set(Design.model_fields) != set(FIELD_ROLES):
        _reject("Preview requires the reviewed standard-part schema")
    _admit(captured, check)
    feature_id = _identity(feature_id)
    if captured.recipe_root is None:
        _reject("Preview requires an explicit recipe root", "missing_recipe_root")
    if captured.recipe_root.version != 1 or captured.recipe_root.kind != "empty":
        _reject("This private preview supports version-one empty native roots only")
    if captured.feature_log_cursor != -1 or captured.feature_log_sub_cursor is not None:
        _reject("Return to the latest history position before previewing an edit", "historical_cursor")
    seen, selected, count = set(), None, 0
    for parent in captured.feature_log:
        entries = [parent, *parent.children] if parent.feature_type == "routing-cluster" else [parent]
        for entry in entries:
            check()
            count += 1
            if count > MAX_COMMANDS:
                _reject("Preview exceeds its command-count allowance", "preview_limit")
            identity = _identity(entry.id)
            if identity in seen:
                _reject(f"Duplicate feature identity {identity!r}", "ambiguous_feature")
            seen.add(identity)
            if identity == feature_id:
                selected = entry
    if selected is None:
        raise ReferenceResolutionError("The selected preview feature no longer exists", references=[
            {"kind": "feature", "identity": feature_id, "parameter_path": ["feature_id"]},
        ])
    if type(selected) is not DeformationLogEntry:
        _reject("Select a typed native deformation entry; capture must preserve entry types")
    if selected.proof_version != 1:
        _reject("Selected deformation lacks a native proof contract", "missing_proof_contract")
    if selected.op_snapshot is None or selected.deformation_id != selected.op_snapshot.id:
        _reject("Deformation feature and operation identities disagree", "invalid_preview_definition")
    _identity(selected.deformation_id)
    rows = []
    for identity, kind, params in command_rows(captured, MAX_COMMANDS):
        check()
        _json(params)
        try:
            known = dependencies(kind, params).known
        except (ValueError, KeyError, TypeError) as error:
            _reject(f"Invalid command {identity!r}: {error}", "invalid_preview_definition")
        if not known:
            _reject(f"Feature {identity!r} lacks a native proof contract", "missing_proof_contract")
        rows.append((identity, kind, params))
    try:
        current = root_design(captured.recipe_root).copy_with(id=captured.id)
    except (ValueError, TypeError) as error:
        _reject(str(error), "invalid_recipe_root")
    for identity, kind, params in rows:
        if identity == feature_id:
            break
        current = _run(kind, current, params, check).copy_with(
            id=captured.id, recipe_root=captured.recipe_root,
        )
    _operation(selected.op_snapshot, current)
    _admit(current, check)
    # Builders derive a fresh graph from empty inputs. The sole remaining
    # mutable alias into captured history is the selected native definition.
    entry = selected.model_copy(deep=True)
    check()
    return PreparedPreview(feature_id, entry.deformation_id, captured.id, current, entry)


def evaluate(prepared, patch):
    """Build one isolated edited overlay; never replay prefix/suffix or publish."""
    check = _checkpoint()
    check()
    if type(prepared) is not PreparedPreview or type(patch) is not dict:
        _reject("Preview requires prepared native inputs and an object patch", "invalid_preview_definition")
    _json(patch)
    if set(patch) - PATCH_FIELDS:
        _reject("This preview edits parameters/planes only; target membership is retained")
    original = prepared._entry.op_snapshot
    if patch.get("type", original.type) != original.type:
        _reject("A preview cannot change the recorded deformation family")
    if patch.get("cluster_ids", original.cluster_ids) != original.cluster_ids:
        _reject("Changing cluster scope requires a separately reviewed selection workflow")
    if "params" in patch:
        values = patch["params"]
        model = BendParams if original.type == "bend" else TwistParams
        if type(values) is not dict or set(values) - set(model.model_fields):
            _reject("Preview parameters do not match the native deformation schema", "invalid_preview_definition")
    _admit(prepared._prefix, check)
    # Each evaluation owns both the mutable native input and edited definition.
    # An exception or consumer mutation cannot affect the next slider result.
    prefix = prepared.copy_prefix()
    entry = prepared._entry.model_copy(deep=True)
    from copy import deepcopy
    try:
        entry = edit_entry(entry, deepcopy(patch))
    except ValueError as error:
        _reject(str(error), "invalid_preview_definition")
    kind, params = command_input(entry)
    candidate = _run(kind, prefix, params, check)
    report = validate_design(candidate)
    check()
    entry = entry.model_copy(update={"op_snapshot": candidate.deformations[-1].model_copy(deep=True)})
    return EvaluatedPreview(candidate, entry, report)
