"""Private feature-stage transforms using unchanged native execution.

No host, lease, recovery decoder or publication authority lives here. Prepare
rebuilds a bounded prefix once; Evaluate owns a fresh copy and executes only the
selected command. Full source equivalence and downstream replay remain Apply's
separate responsibility. Organization metadata is never a placement selector.
"""

from dataclasses import dataclass

from backend.api.part_deformation_preview import (
    _admit, _checkpoint, _identity, _prefix_rows, _replay_prefix, _run,
)
from backend.api.part_transform_inputs import KINDS, edit_transform_entry, normalize
from backend.core.models import ClusterOpLogEntry, Design, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_overlay_commands import command_input
from backend.core.validator import ValidationReport, validate_design


@dataclass(frozen=True, slots=True)
class PreparedTransform:
    feature_id: str
    design_id: str
    kind: str
    _prefix: Design
    _entry: ClusterOpLogEntry | SnapshotLogEntry

    def copy_prefix(self):
        return self._prefix.model_copy(deep=True)

    def display_prefix(self):
        """Read-only display input; native evaluation still owns a deep copy."""
        return self._prefix


@dataclass(frozen=True, slots=True)
class EvaluatedTransform:
    design: Design
    entry: ClusterOpLogEntry | SnapshotLogEntry
    params: dict
    validation: ValidationReport
    stage: str = "feature"
    source_equivalence_checked: bool = False
    downstream_evaluated: bool = False


def select_from_capture(captured, feature_id, check):
    """Bind the exact typed selection before either bounded execution lane."""
    feature_id = _identity(feature_id)
    rows, entries = _prefix_rows(captured, check)
    selected = entries.get(feature_id)
    if selected is None:
        raise ReferenceResolutionError("Selected transform feature no longer exists", references=[
            {"kind": "feature", "identity": feature_id, "parameter_path": ["feature_id"]}])
    if type(selected) is not ClusterOpLogEntry and not (
            type(selected) is SnapshotLogEntry and selected.op_kind in KINDS - {"cluster_op"}):
        raise CommandContractError("Select an ordinary top-level transform history row",
                                   code="unsupported_transform_scope")
    kind, params = command_input(selected)
    normalize(kind, params, {})
    return feature_id, rows, selected, kind


def bind_prepared(captured, feature_id, kind, selected, current, check):
    """Resolve original inputs on an owned prefix, with no replay authority."""
    _admit(current, check)
    entry = edit_transform_entry(selected, {}, current)
    check()
    return PreparedTransform(feature_id, captured.id, kind, current, entry)


def prepare_from_capture(captured, feature_id):
    check = _checkpoint()
    feature_id, rows, selected, kind = select_from_capture(captured, feature_id, check)
    current = _replay_prefix(captured, rows, check, stop=feature_id)
    # Resolve the original definition without executing it or retaining aliases
    # from the caller's captured history graph.
    return bind_prepared(captured, feature_id, kind, selected, current, check)


def evaluate(prepared, patch):
    if type(prepared) is not PreparedTransform:
        raise CommandContractError("Transform evaluation requires its owned prepared prefix",
                                   code="invalid_transform_input")
    check = _checkpoint()
    prefix = prepared.copy_prefix()
    entry = edit_transform_entry(prepared._entry, patch, prefix)
    kind, params = command_input(entry)
    candidate = _run(kind, prefix, params, check)
    validation = validate_design(candidate)
    check()
    return EvaluatedTransform(candidate, entry, params, validation)
