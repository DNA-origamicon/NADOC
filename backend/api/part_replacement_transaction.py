"""Failure-atomic publication of an already prepared part replacement.

The host owns the state lock. Unlike callback recording, this transaction never
mutates the source Design, so rollback preserves its object identity as well as
the complete bounded undo/redo stacks. There is still only one undo snapshot.
"""

from backend.api import doc_context


def publish_replacement(session, candidate, *, publication_permit=None):
    from backend.api import state
    from backend.api import part_publication_permit as permits
    from backend.api.part_group_organization_gate import require_live_design
    from backend.api.part_immutable_storage import is_immutable, retained_history

    checked = None
    if publication_permit is None:
        state._require_compatibility_write("publish_replacement")
    require_live_design(candidate)
    require_live_design(session.design)
    if publication_permit is not None:
        if state._sessions.get(doc_context.get_current_doc()) is not session:
            from fastapi import HTTPException
            raise HTTPException(409, detail={"code": "source_changed", "detail": "The publication session is no longer current"})
        checked = permits.check_publication(publication_permit, doc_id=doc_context.get_current_doc(),
            session=session, candidate=candidate)

    before = session.design
    immutable = is_immutable(before) or is_immutable(candidate)
    if immutable and checked is None:
        from fastapi import HTTPException
        raise HTTPException(409, detail={"code": "immutable_publication_scope", "detail": "Immutable content requires a registered publication permit"})
    next_history = retained_history(session, candidate, max_steps=state.MAX_UNDO_STEPS) if immutable else None
    snapshot = state._snapshot_copy(before) if before is not None and not immutable else None
    history, redo = list(session.history), list(session.redo)
    revision = session.revision
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()
    try:
        if checked is not None:
            permits.check_liveness(checked)
        if immutable:
            session.history.clear()
            session.history.extend(next_history)
        elif snapshot is not None:
            session.history.append(snapshot)
        session.redo.clear()
        session.design = candidate
        state._bump_revision(session)
        if checked is not None:
            if session.revision != revision + 1 or doc_context.current_request_revision() != session.revision:
                raise RuntimeError("Registered publication did not assign exactly one revision")
            permits.consume_publication(publication_permit, checked)
        return session.revision
    except BaseException:
        session.design = before
        session.history.clear()
        session.history.extend(history)
        session.redo.clear()
        session.redo.extend(redo)
        session.revision = revision
        doc_context.set_request_revision(request_revision)
        doc_context.set_request_feature_log_entry_id(request_entry)
        raise
