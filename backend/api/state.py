"""
API layer — active design state singleton.

Holds a single in-memory Design instance shared across all request handlers.
All mutations are protected by a threading.Lock.

Also maintains undo/redo history stacks (up to MAX_UNDO_STEPS deep each).
Every call to set_design() or mutate_and_validate() pushes the previous state
onto the undo stack and clears the redo stack.  undo() pops from the undo stack
and pushes the displaced state onto the redo stack.  redo() reverses that.

Usage
-----
    from backend.api import state

    # Read
    design = state.get_or_404()

    # Mutate + validate atomically
    design, report = state.mutate_and_validate(lambda d: d.helices.append(h))

    # Undo last mutation (returns (design, report) or raises 404 if nothing to undo)
    design, report = state.undo()

    # Redo last undone mutation (returns (design, report) or raises 404 if nothing to redo)
    design, report = state.redo()
"""

from __future__ import annotations

import base64
import datetime as _dt
import gzip
import threading
from collections import deque
from typing import Callable

from fastapi import HTTPException

from backend.core.cluster_reconcile import (
    MutationReport,
    reconcile_cluster_membership,
)
from backend.core.models import (
    Design,
    MinorMutationLogEntry,
    MinorOpSubtype,
    RoutingClusterLogEntry,
    SnapshotLogEntry,
    SnapshotOpKind,
)
from backend.core.lattice import retry_pending_ligations as _retry_pending_ligations
from backend.core.validator import ValidationReport, validate_design

MAX_UNDO_STEPS = 50

# Maximum compressed bytes across all SnapshotLogEntry payloads in a design's
# feature_log. When exceeded after appending a new snapshot entry, the OLDEST
# snapshot bodies are evicted (zeroed out, evicted=True) until under budget.
# Entries themselves remain in the log so historical labels stay visible.
MAX_SNAPSHOT_BUDGET_BYTES = 5_000_000

_lock = threading.Lock()
_active_design: Design | None = None
_history: deque[Design] = deque(maxlen=MAX_UNDO_STEPS)
_redo:    deque[Design] = deque(maxlen=MAX_UNDO_STEPS)

# Optional pre-built atomistic model from PDB import.
# When set, GET /design/atomistic returns this instead of computing from templates.
_pdb_atomistic: object | None = None


def get_design() -> Design | None:
    with _lock:
        return _active_design


def set_design(d: Design) -> None:
    global _active_design
    with _lock:
        if _active_design is not None:
            _history.append(_active_design.model_copy(deep=True))
        _redo.clear()
        _active_design = d


def get_or_404() -> Design:
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        return _active_design


def mutate_and_validate(
    fn: Callable[[Design], None],
) -> tuple[Design, ValidationReport]:
    """Apply *fn* to the active design in-place under the lock, then validate.

    Pushes the pre-mutation snapshot onto the undo stack and clears redo.
    Returns (design, report).  Raises HTTP 404 if no active design.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        _history.append(_active_design.model_copy(deep=True))
        _redo.clear()
        fn(_active_design)
        report = validate_design(_active_design)
    return _active_design, report


def mutate_with_reconcile(
    fn: Callable[[Design], MutationReport | None],
) -> tuple[Design, ValidationReport]:
    """Apply *fn* to the active design in-place, then reconcile cluster membership.

    The mutation function may return a ``MutationReport`` to hint at strand
    renames, new-helix parents, etc.  Returning ``None`` is fine — the
    reconciler falls back to bp-range overlap and lattice-neighbor heuristics.

    Pushes the pre-mutation snapshot onto the undo stack and clears redo,
    same as :func:`mutate_and_validate`.  Returns ``(design, report)``.
    Raises HTTP 404 if no active design.

    Use this for any topology mutation that may affect cluster scope:
    crossover/nick/ligation, autostaple/autobreak, end-extend, slice-plane
    extrude, overhang/linker creation, helix CRUD.

    Do NOT use this for routes that explicitly edit ``cluster_transforms``
    (cluster CRUD, feature-log replay, ``relax_overhang_connection``,
    importers).  Those keep :func:`mutate_and_validate`.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        before = _active_design.model_copy(deep=True)
        _history.append(before)
        _redo.clear()
        report = fn(_active_design)
        reconciled = reconcile_cluster_membership(before, _active_design, report)
        _active_design = _retry_pending_ligations(before, reconciled)
        validation = validate_design(_active_design)
    return _active_design, validation


def replace_with_reconcile(
    new_design: Design,
    report: MutationReport | None = None,
) -> tuple[Design, ValidationReport]:
    """Replace the active design with ``new_design``, snapshot for undo, then reconcile.

    Use this for routes that build the post-mutation design immutably (via
    pure functions in ``backend.core.lattice``) and would otherwise call
    :func:`set_design` directly.

    Same cluster-reconciler semantics as :func:`mutate_with_reconcile`.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        before = _active_design.model_copy(deep=True)
        _history.append(before)
        _redo.clear()
        reconciled = reconcile_cluster_membership(before, new_design, report)
        _active_design = _retry_pending_ligations(before, reconciled)
        validation = validate_design(_active_design)
    return _active_design, validation


def encode_design_snapshot(design: Design) -> tuple[str, int]:
    """Serialize ``design`` to a gzip+base64 payload for a SnapshotLogEntry.

    The design's own ``feature_log`` and ``feature_log_cursor`` are stripped
    before encoding to prevent recursive nesting (a snapshot must never embed
    other snapshots).

    Returns ``(payload_b64, uncompressed_byte_length)``.
    """
    stripped = design.model_copy(update={"feature_log": [], "feature_log_cursor": -1})
    raw = stripped.model_dump_json().encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)
    return base64.b64encode(gz).decode("ascii"), len(raw)


def decode_design_snapshot(payload_b64: str) -> Design:
    """Inverse of :func:`encode_design_snapshot`.  Raises ``ValueError`` on bad input."""
    if not payload_b64:
        raise ValueError("empty snapshot payload")
    raw = gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))
    return Design.model_validate_json(raw)


def _payload_total_bytes(entry: SnapshotLogEntry | RoutingClusterLogEntry) -> int:
    """Combined compressed payload size (pre + post) for a payload-bearing entry."""
    if isinstance(entry, SnapshotLogEntry):
        return len(entry.design_snapshot_gz_b64) + len(entry.post_state_gz_b64)
    # RoutingClusterLogEntry
    return len(entry.pre_state_gz_b64) + len(entry.post_state_gz_b64)


def _clear_payload(entry: SnapshotLogEntry | RoutingClusterLogEntry) -> None:
    """Drop both pre+post bytes from a snapshot OR cluster entry; flip evicted=True.
    Entry + (cluster) children remain visible historically."""
    if isinstance(entry, SnapshotLogEntry):
        entry.design_snapshot_gz_b64 = ""
        entry.post_state_gz_b64 = ""
    else:
        entry.pre_state_gz_b64 = ""
        entry.post_state_gz_b64 = ""
    entry.evicted = True


def _evict_oldest_payloads_if_over_budget(design: Design) -> None:
    """Evict the OLDEST payload-bearing entries (snapshots + routing clusters)
    in-place until the total compressed byte count is under
    :data:`MAX_SNAPSHOT_BUDGET_BYTES`.

    Entries remain in ``feature_log`` so historical labels (and cluster
    children) are still shown; only the topology snapshot bytes are dropped
    (``evicted=True``).

    The MOST RECENT payload-bearing entry is never evicted — the user has just
    run the operation and must always be able to revert it, even if its
    payload alone exceeds the budget.
    """
    payload_entries = [
        e for e in design.feature_log
        if isinstance(e, (SnapshotLogEntry, RoutingClusterLogEntry))
    ]
    total = sum(_payload_total_bytes(e) for e in payload_entries if not e.evicted)
    if total <= MAX_SNAPSHOT_BUDGET_BYTES:
        return
    # Iterate oldest → second-newest; never touch payload_entries[-1].
    for entry in payload_entries[:-1]:
        if entry.evicted:
            continue
        total -= _payload_total_bytes(entry)
        _clear_payload(entry)
        if total <= MAX_SNAPSHOT_BUDGET_BYTES:
            return


# Backward-compat alias; old call site name. Prefer the new name in new code.
_evict_oldest_snapshots_if_over_budget = _evict_oldest_payloads_if_over_budget


def mutate_with_feature_log(
    op_kind: SnapshotOpKind,
    label: str,
    params: dict,
    fn: Callable[[Design], Design | MutationReport | None],
) -> tuple[Design, ValidationReport, SnapshotLogEntry]:
    """Capture a pre-state snapshot, apply ``fn``, append a SnapshotLogEntry,
    reconcile cluster membership, validate, and push undo.

    ``fn`` is called with the active design.  It may either:
    - Return a new ``Design`` (immutable style — preferred for routes that
      build the post-mutation design via pure functions in ``backend.core``),
      OR
    - Mutate the design in-place and return ``None`` or a ``MutationReport``.

    The pre-state snapshot stored in the log entry is the design state BEFORE
    ``fn`` runs.  This is the revert target for
    ``POST /design/features/{index}/revert``.

    Snapshot byte budget is enforced via
    :func:`_evict_oldest_payloads_if_over_budget` after the new entry is
    appended.

    Returns ``(design, validation_report, snapshot_entry)``.  Raises HTTP 404
    if no active design.

    Use this for the eight major auto-op routes (auto-scaffold variants,
    auto-break, auto-merge, auto-crossover, create-near/far-ends) and bulk
    overhang manager operations.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        before = _active_design.model_copy(deep=True)
        _history.append(before)
        _redo.clear()

        payload_b64, uncompressed_size = encode_design_snapshot(before)

        result = fn(_active_design)
        # Three return shapes supported:
        #   - Design                      : pure-functional, no custom report.
        #   - (Design, MutationReport)    : pure-functional + custom reconcile hint.
        #   - MutationReport / None       : in-place mutation; report optional.
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], Design):
            _active_design = result[0]
            report = result[1] if isinstance(result[1], MutationReport) else None
        elif isinstance(result, Design):
            _active_design = result
            report: MutationReport | None = None
        else:
            report = result if isinstance(result, MutationReport) else None

        reconciled = reconcile_cluster_membership(before, _active_design, report)
        _active_design = _retry_pending_ligations(before, reconciled)

        # Capture POST-state AFTER reconcile + retry so back-and-forth seeking
        # can restore the live topology even after the slider has been scrubbed
        # back through this entry.
        post_b64, post_size = encode_design_snapshot(_active_design)

        snap_entry = SnapshotLogEntry(
            op_kind=op_kind,
            label=label,
            timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            params=params,
            design_snapshot_gz_b64=payload_b64,
            snapshot_size_bytes=uncompressed_size,
            post_state_gz_b64=post_b64,
            post_state_size_bytes=post_size,
        )
        _active_design.feature_log.append(snap_entry)
        _evict_oldest_payloads_if_over_budget(_active_design)

        validation = validate_design(_active_design)
    return _active_design, validation, snap_entry


def mutate_with_minor_log(
    op_subtype: MinorOpSubtype,
    label: str,
    params: dict,
    fn: Callable[[Design], Design | MutationReport | None],
) -> tuple[Design, ValidationReport, MinorMutationLogEntry]:
    """Wrap a minor user-driven mutation: append it to the open RoutingClusterLogEntry,
    or open a new cluster if the last log entry isn't a non-evicted cluster.

    A "Fine Routing" cluster groups consecutive minor ops; any
    snapshot-emitting endpoint (``mutate_with_feature_log``) implicitly closes
    the current cluster because it appends a SnapshotLogEntry, after which
    the next ``mutate_with_minor_log`` call finds the last entry isn't a
    cluster and starts a fresh one.

    For NEW cluster: pre-state is encoded BEFORE ``fn`` runs and stored as
    ``cluster.pre_state_gz_b64`` (the revert target). For both NEW and APPEND:
    after ``fn`` runs and clusters are reconciled, ``cluster.post_state_gz_b64``
    is re-encoded so the cluster always has a current post-state for forward
    seek / latest-state queries.

    Each call pushes one undo entry — every minor op is individually
    Ctrl-Z-undoable just like before.

    ``fn`` may either return a new ``Design`` (immutable style) OR mutate the
    active design in-place and return ``None`` or a ``MutationReport``.

    Returns ``(design, validation_report, minor_entry)``.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        before = _active_design.model_copy(deep=True)
        _history.append(before)
        _redo.clear()

        # Detect open cluster: last entry must be a non-evicted RoutingClusterLogEntry.
        last_entry = _active_design.feature_log[-1] if _active_design.feature_log else None
        is_append = (
            isinstance(last_entry, RoutingClusterLogEntry)
            and not last_entry.evicted
            and last_entry.pre_state_gz_b64 != ""
        )

        # Capture pre-state ONLY for new clusters; append mode reuses the
        # cluster's existing pre-state.
        if not is_append:
            pre_b64, pre_size = encode_design_snapshot(before)

        # Run the user's mutation.
        result = fn(_active_design)
        if isinstance(result, Design):
            _active_design = result
            report: MutationReport | None = None
        else:
            report = result if isinstance(result, MutationReport) else None

        reconciled = reconcile_cluster_membership(before, _active_design, report)
        _active_design = _retry_pending_ligations(before, reconciled)

        # Re-encode post-state after reconcile + retry so back-and-forth
        # seeking restores the live topology even after the slider has been
        # scrubbed back through the cluster.
        post_b64, post_size = encode_design_snapshot(_active_design)

        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
        minor_entry = MinorMutationLogEntry(
            op_subtype=op_subtype,
            label=label,
            timestamp=now_iso,
            params=params,
        )

        if is_append:
            cluster = _active_design.feature_log[-1]
            cluster.children.append(minor_entry)
            cluster.post_state_gz_b64 = post_b64
            cluster.post_state_size_bytes = post_size
        else:
            cluster = RoutingClusterLogEntry(
                label='Fine Routing',
                timestamp=now_iso,
                children=[minor_entry],
                pre_state_gz_b64=pre_b64,
                pre_state_size_bytes=pre_size,
                post_state_gz_b64=post_b64,
                post_state_size_bytes=post_size,
            )
            _active_design.feature_log.append(cluster)

        _evict_oldest_payloads_if_over_budget(_active_design)

        validation = validate_design(_active_design)
    return _active_design, validation, minor_entry


def undo() -> tuple[Design, ValidationReport]:
    """Restore the previous design state.

    Returns (design, report).  Raises HTTP 404 if nothing to undo.
    """
    global _active_design
    with _lock:
        if not _history:
            raise HTTPException(status_code=404, detail="Nothing to undo.")
        _redo.append(_active_design.model_copy(deep=True))
        _active_design = _history.pop()
        report = validate_design(_active_design)
    return _active_design, report


def redo() -> tuple[Design, ValidationReport]:
    """Re-apply the last undone mutation.

    Returns (design, report).  Raises HTTP 404 if nothing to redo.
    """
    global _active_design
    with _lock:
        if not _redo:
            raise HTTPException(status_code=404, detail="Nothing to redo.")
        _history.append(_active_design.model_copy(deep=True))
        _active_design = _redo.pop()
        report = validate_design(_active_design)
    return _active_design, report


def clear_history() -> None:
    """Discard both undo and redo history (e.g. after loading a new design from disk)."""
    global _pdb_atomistic
    with _lock:
        _history.clear()
        _redo.clear()
        _pdb_atomistic = None


def close_session() -> None:
    """Erase the active design and all history (used when the user closes the session)."""
    global _active_design, _pdb_atomistic
    with _lock:
        _active_design = None
        _history.clear()
        _redo.clear()
        _pdb_atomistic = None


def snapshot() -> None:
    """Push the current design onto the undo stack without changing it.

    Use this before starting a multi-step operation (e.g., step-by-step autostaple)
    so the entire operation is undoable as a single Ctrl-Z.
    """
    global _active_design
    with _lock:
        if _active_design is not None:
            _history.append(_active_design.model_copy(deep=True))
        _redo.clear()


def get_pdb_atomistic() -> object | None:
    """Return the stored PDB atomistic model, or None."""
    with _lock:
        return _pdb_atomistic


def set_pdb_atomistic(model: object | None) -> None:
    """Store a pre-built atomistic model from PDB import."""
    global _pdb_atomistic
    with _lock:
        _pdb_atomistic = model


def set_design_silent(d: Design) -> None:
    """Update the active design without pushing to the undo stack.

    Use for intermediate steps in a multi-step operation where snapshot()
    was already called before the first step.
    """
    global _active_design
    with _lock:
        _active_design = d


def set_design_silent_reconciled(
    new_design: Design,
    before: Design,
    report: MutationReport | None = None,
) -> tuple[Design, ValidationReport]:
    """Reconcile cluster membership against ``before``, then silent-set + validate.

    Pair with :func:`snapshot` for multi-step operations that build up the new
    design across several steps (e.g. ``place_crossover``, ``forced_ligation``,
    ``add_nick_batch``).  Caller is responsible for capturing ``before`` from
    :func:`get_or_404` *before* :func:`snapshot` and passing it here.
    """
    global _active_design
    with _lock:
        reconciled = reconcile_cluster_membership(before, new_design, report)
        _active_design = reconciled
        validation = validate_design(_active_design)
    return _active_design, validation
