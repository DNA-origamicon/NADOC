"""Explicit sidebar actions recording a complete presentation configuration."""
from fastapi import APIRouter, HTTPException

from backend.api import state, assembly_state
from backend.core.presentation_checkpoints import SaveCheckpoint, capture, apply

router = APIRouter()


def _check(document, body):
    if document.id != body.document_id:
        raise HTTPException(409, detail='The active document changed; save the state again.')
    if document.feature_log_cursor != -1 or getattr(document, 'feature_log_sub_cursor', None) is not None:
        raise HTTPException(409, detail='Return to the latest feature before saving a presentation state.')


def _label(body):
    return body.label.strip() or ('Annotations state' if body.kind == 'annotations-state' else 'View volumes state')


@router.post('/design/features/presentation-state')
def save_part_checkpoint(body: SaveCheckpoint):
    from backend.api.feature_recording import record_feature
    with state._lock:
        session = state._session()
        if session.design is None:
            raise HTTPException(404, detail='No active part')
        document = session.design
        _check(document, body)
        state._assert_active_loadout_editable(document)
        params = capture(document, body.kind)
        updated, _, _ = record_feature(session, body.kind, _label(body), params,
            lambda source: apply(source, body.kind, params))
        return {'document_id': updated.id, 'revision': session.revision,
                'feature_log': [entry.model_dump(mode='json') for entry in updated.feature_log]}


@router.post('/assembly/features/presentation-state')
def save_assembly_checkpoint(body: SaveCheckpoint):
    from datetime import datetime, timezone
    from backend.core.models import SnapshotLogEntry
    with assembly_state._lock:
        session = assembly_state._session()
        document = session.assembly
        if document is None:
            raise HTTPException(404, detail='No active assembly')
        _check(document, body)
        params = capture(document, body.kind)
        candidate = apply(document, body.kind, params)
        pre, pre_size = assembly_state.encode_assembly_snapshot(document)
        post, post_size = assembly_state.encode_assembly_snapshot(candidate)
        entry = SnapshotLogEntry(op_kind=body.kind, label=_label(body), params=params,
            timestamp=datetime.now(timezone.utc).isoformat(),
            design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
            post_state_gz_b64=post, post_state_size_bytes=post_size)
        updated = candidate.model_copy(update={'feature_log': [*document.feature_log, entry]})
        # All validation/encoding precedes the single publication and undo step.
        session.history.append(document.model_copy(deep=True))
        assembly_state._trim_to(session.history, assembly_state._undo_cap_for(document))
        session.redo.clear()
        session.assembly = updated
        session.revision += 1
        return {'document_id': updated.id, 'revision': session.revision,
                'feature_log': [row.model_dump(mode='json') for row in updated.feature_log]}
