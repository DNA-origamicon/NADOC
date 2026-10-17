"""Bounded extension-only preparation and one source-bound publication.

This validates a new command, not the whole historical recipe. Only extensions
and one feature row merge back; topology, placements and physical/display data
remain the exact live source fields. No native geometry runs under the lock.
"""

import hashlib
import json
from threading import Event
from time import monotonic

from fastapi import HTTPException

from backend.api import doc_context, state, part_extension_publication as authority
from backend.api import part_publication_permit as permits
from backend.api.part_extension_commands import UPSERT_VERSION, build
from backend.api.part_extension_inputs import resolve
from backend.api.part_group_geometry_budget import require_group_geometry_budget
from backend.api.part_model_serialization import admit_model_serialization
from backend.api.part_recovery_budget import RecoveryBudget
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_recovery_storage import MAX_RECOVERY_BYTES, retained_recovery_bytes
from backend.core.part_structure_gate import PartStructureError, require_valid_structure

SECONDS = 5.0


def _refuse(code, message, status=409):
    raise HTTPException(status, detail={"code": code, "message": message})


def _editable(source):
    state._assert_active_loadout_editable(source)
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        _refuse("historical_cursor", "Return to the latest history position before editing extensions.")


def apply(action, values, *, extension_id=None, expected_revision, cancelled=None):
    from backend.core.part_verification_capture import CaptureLimit, admit, capture
    from backend.api.part_extension_transport import require_current

    authority.require_policy(doc_id=doc_context.get_current_doc())
    if type(expected_revision) is not int or expected_revision < 0:
        _refuse("invalid_extension_input", "An exact nonnegative document revision is required.", 422)
    if cancelled is not None and not isinstance(cancelled, Event):
        _refuse("invalid_extension_input", "Cancellation must be owned by the host.", 422)
    deadline = monotonic() + SECONDS

    def check():
        if cancelled is not None and cancelled.is_set():
            _refuse("cancelled", "Extension edit cancelled.")
        if monotonic() >= deadline:
            _refuse("extension_capture_limit", "Extension preparation exceeded its cooperative time allowance.")

    check()
    try:
        request = {"action": action, "values": values, "extension_id": extension_id, "expected_revision": expected_revision}
        validate_operation_input(request)
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
        owned = json.loads(encoded)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        kind = "extension-delete" if action == "delete" else "extension-upsert"
        with state._lock:
            check()
            require_current()
            authority.require_policy(doc_id=doc_context.get_current_doc())
            session = state._sessions.get(doc_context.get_current_doc())
            if session is None or session.design is None:
                raise HTTPException(404, detail="No active design.")
            if session.revision != expected_revision:
                _refuse("source_changed", "Refresh the design before editing extensions.")
            source = session.design
            _editable(source)
            admission = authority.admit(doc_context.get_current_doc(), session, operation=kind, request_sha256=digest)
            context = permits.admission_context(admission)
            retained = retained_recovery_bytes(source.feature_log, max_rows=authority.MAX_HISTORY_ROWS)
            captured = capture(source, preserve_entry_types=True)
        check()
        admit_model_serialization(captured, max_nodes=30_000, max_bytes=2_000_000, label="Extension authoring serialization")
        operation, params, ids = resolve(captured, owned["action"], owned["values"],
            extension_id=owned["extension_id"], version=UPSERT_VERSION if action != "delete" else 1)
        prepared = build(operation, captured, params) if operation is not None else captured
        changed = prepared.extensions != captured.extensions
        require_valid_structure(prepared)
        state._assert_photoproduct_dependencies(prepared)
        report = state.validate_design(prepared)
        if kind == "extension-upsert":
            require_group_geometry_budget(prepared)
        if changed:
            entry = SnapshotLogEntry(op_kind=operation, label=("Remove terminal extensions" if action == "delete" else "Edit terminal extensions"), params=params)
            retained_recovery_bytes(captured.feature_log, max_rows=authority.MAX_HISTORY_ROWS - 1)
            admitted = prepared.copy_with(feature_log=[*prepared.feature_log, entry])
            admit(admitted, preserve_entry_types=True)
            admit_model_serialization(admitted, max_nodes=30_000, max_bytes=2_000_000, label="Extension authoring serialization")
            check()
            budget = RecoveryBudget(MAX_RECOVERY_BYTES - retained)
            pre, pre_size = state.encode_design_snapshot(captured)
            budget.charge(pre)
            check()
            post, post_size = state.encode_design_snapshot(prepared)
            budget.charge(post)
            entry = entry.model_copy(update={"design_snapshot_gz_b64": pre, "snapshot_size_bytes": pre_size,
                "post_state_gz_b64": post, "post_state_size_bytes": post_size})
        with state._lock:
            check()
            authority.require_policy(context)
            if (doc_context.get_current_doc() != context.doc_id
                    or state._sessions.get(context.doc_id) is not session
                    or not permits.context_matches(context, context.doc_id, session)):
                _refuse("source_changed", "The document changed while the extension edit was prepared.")
            _editable(session.design)
            if not changed:
                doc_context.set_request_revision(context.source_revision)
                return source, report, ids
            candidate = source.copy_with(extensions=prepared.extensions, feature_log=[*source.feature_log, entry])
            state._assert_active_loadout_editable(source, candidate)
            permit = authority.issue(admission, candidate, request_sha256=digest, expires=deadline, cancelled=cancelled)
            publish_replacement(session, candidate, publication_permit=permit)
            doc_context.set_request_feature_log_entry_id(entry.id)
            return candidate, report, ids
    except (CaptureLimit, ProofBudgetExceeded) as error:
        _refuse("extension_capture_limit", str(error))
    except (CommandContractError, PartStructureError) as error:
        raise HTTPException(409, detail=error.as_issue()) from error
    except ValueError as error:
        _refuse("invalid_extension_input", str(error), 422)
