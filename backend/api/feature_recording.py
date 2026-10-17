"""Failure-atomic standard-part history recording.

State owns the document lock. These functions run inside that lock and retain
the existing single design copy and snapshot/diff formats. This is a recording
transaction, not an isolated evaluator: legacy callbacks may mutate in place.
"""
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException

from backend.api import doc_context
from backend.core.cluster_reconcile import MutationReport
from backend.core.models import Design, MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry


@contextmanager
def _transaction(session, state):
    state._require_compatibility_write("feature_recording")
    before = state._snapshot_copy(session.design)
    history = list(session.history)
    redo = list(session.redo)
    revision = session.revision
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()
    try:
        yield before
    except BaseException:
        # Restore even cancellation, and even after the history append evicted
        # the oldest bounded-deque item or request publication partially ran.
        session.design = before
        session.history.clear()
        session.history.extend(history)
        session.redo.clear()
        session.redo.extend(redo)
        session.revision = revision
        doc_context.set_request_revision(request_revision)
        doc_context.set_request_feature_log_entry_id(request_entry)
        raise


def _run(session, before, fn, state, *, retry=True, command=None):
    state._require_compatibility_write("feature_recording_callback")
    from backend.api.part_connection_version_commands import metadata_policy
    metadata_only = command is not None and (
        metadata_policy(*command) or command[0] == "extension-delete")
    result = fn(session.design)
    report = None
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], Design):
        session.design = result[0]
        report = result[1] if isinstance(result[1], MutationReport) else None
    elif isinstance(result, Design):
        session.design = result
    elif isinstance(result, MutationReport):
        report = result
    if not metadata_only:
        reconciled = state.reconcile_cluster_membership(before, session.design, report)
        session.design = state._retry_pending_ligations(before, reconciled) if retry else reconciled
    from backend.core.part_repair_document import preserve_repair_draft
    session.design = preserve_repair_draft(before, session.design)
    # Preserve the established photoproduct gate and diagnostic exactly.
    from backend.core.photoproducts import stale_photoproduct_ids
    stale = stale_photoproduct_ids(session.design)
    if stale:
        raise HTTPException(409, detail={
            "code": "photoproduct_dependency",
            "message": "This edit would delete or change a formed TT-CPD endpoint. Remove the photoproduct first, then retry.",
            "photoproduct_ids": stale,
        })


def _publish(session, before, parent_id, state):
    state._require_compatibility_write("feature_recording_publication")
    # A validation report may contain warnings/errors on an editable draft;
    # preserve that contract. An exception, however, must never publish state.
    validation = state.validate_design(session.design)
    session.history.append(before)
    session.redo.clear()
    state._bump_revision(session)
    state.set_request_feature_log_entry_id(parent_id)
    return validation


def record_feature(session, op_kind, label, params, fn):
    # Local import keeps state the lock-owning composition root and preserves
    # its existing injected encode/reconcile/validation hooks.
    from backend.api import state

    with _transaction(session, state) as before:
        pre, pre_size = state.encode_design_snapshot(before)
        _run(session, before, fn, state,
             retry=op_kind not in {"auto-break", "full-autostaple", "cluster-join"},
             command=(op_kind, params))
        from backend.api.part_proof_commands import PROOF_SNAPSHOT_KINDS
        if op_kind in PROOF_SNAPSHOT_KINDS:
            from backend.api.part_proof_commands import PROOF_VERSION
            params = {**params, "_proof_version": PROOF_VERSION}
            if op_kind == "bundle-create":
                session.design.recipe_root = before.recipe_root
        post, post_size = state.encode_design_snapshot(session.design)
        entry = SnapshotLogEntry(
            op_kind=op_kind, label=label, params=params,
            timestamp=datetime.now(timezone.utc).isoformat(),
            design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
            post_state_gz_b64=post, post_state_size_bytes=post_size,
        )
        session.design.feature_log.append(entry)
        validation = _publish(session, before, entry.id, state)
        return session.design, validation, entry


def record_minor(session, op_subtype, label, params, fn):
    from backend.api import state
    from backend.core.design_diff import encode_child_diff
    from backend.api.part_proof_commands import PROOF_MINOR_KINDS, PROOF_VERSION

    if op_subtype in PROOF_MINOR_KINDS:
        params = {**params, "_proof_version": PROOF_VERSION}

    with _transaction(session, state) as before:
        last = session.design.feature_log[-1] if session.design.feature_log else None
        append = isinstance(last, RoutingClusterLogEntry) and not last.evicted and bool(last.pre_state_gz_b64)
        if not append:
            pre, pre_size = state.encode_design_snapshot(before)
        _run(session, before, fn, state)
        post, post_size = state.encode_design_snapshot(session.design)
        added, removed, modified, size = encode_child_diff(before, session.design)
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = MinorMutationLogEntry(
            op_subtype=op_subtype, label=label, params=params, timestamp=timestamp,
            diff_added_b64=added, diff_removed_b64=removed,
            diff_modified_b64=modified, diff_size_bytes=size,
        )
        if append:
            cluster = session.design.feature_log[-1]
            cluster.children.append(entry)
            cluster.post_state_gz_b64 = post
            cluster.post_state_size_bytes = post_size
        else:
            cluster = RoutingClusterLogEntry(
                label="Fine Routing", timestamp=timestamp, children=[entry],
                pre_state_gz_b64=pre, pre_state_size_bytes=pre_size,
                post_state_gz_b64=post, post_state_size_bytes=post_size,
            )
            session.design.feature_log.append(cluster)
        validation = _publish(session, before, cluster.id, state)
        return session.design, validation, entry
