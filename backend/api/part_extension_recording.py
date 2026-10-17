"""Ordinary extension recording; organized edits use the owned transaction."""

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api.feature_recording import record_feature
from backend.api.part_extension_commands import build
from backend.api.part_extension_inputs import resolve
from backend.core.part_command_errors import CommandContractError


def record(action, values, *, extension_id=None, expected_revision=None, cancelled=None):
    from backend.api.part_extension_transport import require_current
    with state._lock:
        require_current()
        session = state._session()
        source = session.design
        if source is None:
            raise HTTPException(404, detail="No active design.")
        organized = source.group_organization is not None
        if not organized:
            state._require_compatibility_write("extension_authoring")
            state._assert_active_loadout_editable(source)
            if expected_revision is not None and (type(expected_revision) is not int or expected_revision != session.revision):
                raise HTTPException(409, detail={"code": "source_changed", "message": "Refresh the design before editing extensions."})
            if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
                raise HTTPException(409, detail="Return to the latest history position before editing extensions.")
            if cancelled is not None and cancelled.is_set():
                raise HTTPException(409, detail={"code": "cancelled"})
            try:
                kind, params, ids = resolve(source, action, values, extension_id=extension_id)
                if kind is None:
                    doc_context.set_request_revision(session.revision)
                    return source, state.validate_design(source), ids
                candidate = build(kind, source, params)
                result, report, _entry = record_feature(session, kind,
                    "Remove terminal extensions" if action == "delete" else "Edit terminal extensions",
                    params, lambda _source: candidate)
            except CommandContractError as error:
                raise HTTPException(404 if error.code == "missing_reference" else 400, detail=error.as_issue()) from error
            return result, report, ids
    from backend.api.part_extension_owned_recording import apply
    return apply(action, values, extension_id=extension_id,
                 expected_revision=expected_revision, cancelled=cancelled)
