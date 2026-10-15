"""Failure-atomic publication of an already prepared part replacement.

The host owns the state lock. Unlike callback recording, this transaction never
mutates the source Design, so rollback preserves its object identity as well as
the complete bounded undo/redo stacks. There is still only one undo snapshot.
"""

from backend.api import doc_context


def publish_replacement(session, candidate):
    from backend.api import state

    before = session.design
    snapshot = state._snapshot_copy(before) if before is not None else None
    history, redo = list(session.history), list(session.redo)
    revision = session.revision
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()
    try:
        if snapshot is not None:
            session.history.append(snapshot)
        session.redo.clear()
        session.design = candidate
        state._bump_revision(session)
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
