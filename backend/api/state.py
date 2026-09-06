"""
API layer — active design state, keyed by document (multi-document, Phase 2).

Holds a registry of in-memory Design "sessions", one per ``doc_id``.  The active
document for a request is resolved from :mod:`backend.api.doc_context` (set by
the DocContextMiddleware from the ``X-NADOC-Doc`` header / ``?doc=`` query).
Requests that name no document resolve to ``DEFAULT_DOC_ID`` — so single-document
clients, internal callers, and the entire test suite behave exactly as before.

Each session has its own Design, undo/redo stacks (up to MAX_UNDO_STEPS deep),
optional PDB atomistic model, and a monotonic revision counter.  The protein
library is intentionally PROCESS-GLOBAL (shared across documents) so an imported
PDB can be attached across designs.  All access is protected by a single lock.

Usage
-----
    from backend.api import state

    design = state.get_or_404()
    design, report = state.mutate_and_validate(lambda d: d.helices.append(h))
    design, report = state.undo()
    design, report = state.redo()
"""

from __future__ import annotations

import base64
import datetime as _dt
import gzip
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from fastapi import HTTPException

from backend.api.doc_context import (
    current_request_revision as _doc_current_request_revision,
    current_request_feature_log_entry_id as _doc_current_request_feature_log_entry_id,
    get_current_doc,
    set_request_revision,
    set_request_feature_log_entry_id,
)
from backend.core.cluster_reconcile import (
    MutationReport,
    reconcile_cluster_membership,
)
from backend.core.models import (
    Design,
    MinorMutationLogEntry,
    MinorOpSubtype,
    ProteinAsset,
    RoutingClusterLogEntry,
    SnapshotLogEntry,
    SnapshotOpKind,
)
from backend.core.lattice import retry_pending_ligations as _retry_pending_ligations
from backend.core.validator import ValidationReport, validate_design

MAX_UNDO_STEPS = 50

# Retained for API/test compatibility. Feature history is intentionally no
# longer evicted: every visible feature-log entry must remain revertable. Wire
# responses are slimmed separately in ``backend.api.crud`` so keeping canonical
# recovery snapshots does not put them back on the click-to-render hot path.
MAX_SNAPSHOT_BUDGET_BYTES = 5_000_000


def current_request_revision() -> int | None:
    """Current request revision, re-exported for backend.api.crud."""

    return _doc_current_request_revision()


def current_request_feature_log_entry_id() -> str | None:
    """Id of the feature-log entry the current request's mutation just
    created, or None. Re-exported for backend.api.crud."""

    return _doc_current_request_feature_log_entry_id()


@dataclass
class _DesignSession:
    """Per-document design state: the active design + its undo/redo + extras."""

    design: Design | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=MAX_UNDO_STEPS))
    redo: deque = field(default_factory=lambda: deque(maxlen=MAX_UNDO_STEPS))
    # Optional pre-built atomistic model from PDB import (per document).
    pdb_atomistic: object | None = None
    # Monotonic counter bumped on every reassignment of this doc's design. The
    # session-cache flush thread reads it to skip serializing unchanged docs.
    revision: int = 0
    # Persistence cursors belong to the document session, not undoable content.
    workspace_heads: dict[tuple[str, str], set[str]] = field(default_factory=dict)


_lock = threading.Lock()
_sessions: dict[str, _DesignSession] = {}


def _bump_revision(s: "_DesignSession") -> None:
    """Increment a session's revision and record it for the current request.

    The per-request value (read by ``_design_response`` via
    ``current_request_revision``) is captured ATOMICALLY here under the lock, so
    a concurrent mutation moving ``s.revision`` on can't make the response stamp
    the wrong revision. The contextvar lives in :mod:`doc_context` and is reset
    to None per request by its middleware, so a read-only request never inherits
    a prior mutation's value. Lets the client drop out-of-order/stale design
    responses (rapid edits where freshly-added nicks "disappear" a moment later).
    """
    s.revision += 1
    set_request_revision(s.revision)


# Session-level protein library, keyed by asset id.  PROCESS-GLOBAL (shared
# across documents) — an imported PDB can be attached across designs.  Persisted
# copies live on the Design/Assembly that reference them.
_protein_library: dict[str, ProteinAsset] = {}


def _session() -> _DesignSession:
    """Return the current request's document session, creating it lazily.

    MUST be called while holding ``_lock``.
    """
    doc = get_current_doc()
    s = _sessions.get(doc)
    if s is None:
        s = _DesignSession()
        _sessions[doc] = s
    return s


# ── Document registry helpers (multi-document) ───────────────────────────────


def list_doc_ids() -> list[str]:
    """Doc ids that currently hold a design."""
    with _lock:
        return [doc for doc, s in _sessions.items() if s.design is not None]


def peek_design(doc_id: str) -> Design | None:
    """The design for a specific doc id without touching the ContextVar."""
    with _lock:
        s = _sessions.get(doc_id)
        return s.design if s else None


def drop_doc(doc_id: str) -> bool:
    """Forget a document's design session entirely. Returns True if it existed.

    Does NOT touch the shared protein library (other open docs may use it).
    """
    with _lock:
        return _sessions.pop(doc_id, None) is not None


def restore_doc_design(doc_id: str, design: Design) -> None:
    """Load a design into a specific doc's session (startup recovery).

    No undo history is created — the cached design was already a live, fully
    post-processed design.
    """
    with _lock:
        s = _sessions.get(doc_id)
        if s is None:
            s = _DesignSession()
            _sessions[doc_id] = s
        s.history.clear()
        s.redo.clear()
        s.workspace_heads.clear()
        s.pdb_atomistic = None
        s.design = design
        _bump_revision(s)


def revision_map() -> dict[str, int]:
    """``{doc_id: revision}`` for every design session (cheap; for the cache)."""
    with _lock:
        return {doc: s.revision for doc, s in _sessions.items()}


def copy_doc_for_persist(doc_id: str) -> tuple[Design | None, int]:
    """``(deep_copy_of_doc_design_or_None, revision)`` for one doc, under lock.

    Lets the session-cache flush thread serialize a stable snapshot OUTSIDE the
    lock without racing an in-place mutation.
    """
    with _lock:
        s = _sessions.get(doc_id)
        if s is None:
            return None, 0
        snap = s.design.model_copy(deep=True) if s.design is not None else None
        return snap, s.revision


# ── Current-document accessors ───────────────────────────────────────────────


def get_design() -> Design | None:
    with _lock:
        return _session().design


def get_design_with_revision() -> tuple[Design | None, int]:
    """Current design reference and revision captured under the same lock.

    Read-only caches may do expensive derived work outside the state lock, then compare
    this pair again before publishing it.  The object identity distinguishes a newly
    opened session whose revision counter happens to match the previous session's.
    """
    with _lock:
        s = _session()
        return s.design, s.revision


def has_design_unlocked() -> bool:
    """Whether the current doc holds a design, WITHOUT taking ``_lock``.

    For the liveness probe (``GET /health``) only: it must never block behind a
    long mutation holding ``_lock``, nor lazily create a session. Reads are
    GIL-atomic, so a benign race (seeing the pre/post-swap state) is acceptable
    for a status beacon.
    """
    s = _sessions.get(get_current_doc())
    return s is not None and s.design is not None


def revision() -> int:
    """Current document's change-counter."""
    with _lock:
        return _session().revision


def copy_for_persist() -> tuple[Design | None, int]:
    """``(deep copy of current doc's design or None, revision)`` under the lock."""
    with _lock:
        s = _session()
        snap = s.design.model_copy(deep=True) if s.design is not None else None
        return snap, s.revision


def copy_for_workspace_save() -> tuple[Design, int, dict[str, set[str]]]:
    """Snapshot edits and the branch heads this document has already observed."""
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(404, detail="No active design.")
        design = s.design.model_copy(deep=True)
        known: dict[str, set[str]] = {}
        # Include history for sessions opened before persistence cursors were
        # tracked separately. Undo/redo may restore an older embedded head.
        for candidate in (s.design, *s.history, *s.redo):
            if candidate.id != design.id:
                continue
            for loadout in candidate.loadouts:
                if loadout.head_revision_id:
                    known.setdefault(loadout.id, set()).add(loadout.head_revision_id)
        for (project_id, loadout_id), heads in s.workspace_heads.items():
            if project_id == design.id:
                known.setdefault(loadout_id, set()).update(heads)
        return design, s.revision, known


def acknowledge_workspace_save(before: Design, saved: Design, revision: int) -> None:
    """Advance save cursors without overwriting edits made during disk I/O."""
    with _lock:
        s = _session()
        for loadout in saved.loadouts:
            if loadout.head_revision_id:
                s.workspace_heads.setdefault((saved.id, loadout.id), set()).add(loadout.head_revision_id)
        if s.design is None or s.design.id != before.id:
            return  # The user navigated to another document during the save.
        if saved.id != before.id:
            # Save As forks a project. Its undo stack must not carry snapshots
            # with the source file's identity and workspace path.
            s.history.clear()
            s.redo.clear()
        if s.revision == revision:
            s.design = saved
        else:
            heads = {item.id: item.head_revision_id for item in saved.loadouts}
            loadouts = [item.model_copy(update={"head_revision_id": heads[item.id]})
                        if item.id in heads else item for item in s.design.loadouts]
            updates = {"loadouts": loadouts or saved.loadouts}
            if not s.design.active_loadout_id:
                updates["active_loadout_id"] = saved.active_loadout_id
            if saved.id != before.id or saved.metadata != before.metadata:
                updates["id"] = saved.id
                updates["metadata"] = s.design.metadata.model_copy(update={
                    "identity_last_known_path": saved.metadata.identity_last_known_path,
                    "identity_confirmed_at": saved.metadata.identity_confirmed_at,
                })
            s.design = s.design.model_copy(update=updates)
        _bump_revision(s)


def workspace_heads_for_doc(doc_id: str) -> dict[str, dict[str, list[str]]]:
    """Portable recovery metadata, kept outside undoable design snapshots."""
    with _lock:
        session = _sessions.get(doc_id)
        result: dict[str, dict[str, list[str]]] = {}
        if session is not None:
            for (project_id, loadout_id), heads in session.workspace_heads.items():
                result.setdefault(project_id, {})[loadout_id] = sorted(heads)
        return result


def restore_workspace_heads(doc_id: str, heads: dict[str, dict[str, list[str]]]) -> None:
    with _lock:
        session = _sessions.get(doc_id)
        if session is not None:
            session.workspace_heads = {
                (project_id, loadout_id): set(revisions)
                for project_id, branches in heads.items()
                for loadout_id, revisions in branches.items()
            }


def _assert_active_loadout_editable(
    current: Design | None, replacement: Design | None = None
) -> None:
    """Reject edits to a protected simulation loadout.

    The client responds to this machine-readable conflict by restoring the last
    editable loadout and retrying the original request. A different design id is
    file navigation rather than an edit and remains allowed.
    """
    if current is None or (replacement is not None and replacement.id != current.id):
        return
    active = next(
        (item for item in current.loadouts if item.id == current.active_loadout_id),
        None,
    )
    if active is not None and active.protected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "protected_simulation_loadout",
                "message": "Simulation loadouts are read-only.",
            },
        )


def load_design(d: Design) -> None:
    """Establish a file/new-design baseline without making navigation undoable."""
    with _lock:
        s = _session()
        s.history.clear()
        s.redo.clear()
        s.workspace_heads.clear()
        s.pdb_atomistic = None
        s.design = d
        _bump_revision(s)


def set_design(d: Design) -> None:
    with _lock:
        s = _session()
        _assert_active_loadout_editable(s.design, d)
        if s.design is not None:
            s.history.append(s.design.model_copy(deep=True))
        s.redo.clear()
        s.design = d
        _bump_revision(s)


def set_design_branch(d: Design) -> None:
    """Navigate to a branch without undoing back into a different branch."""
    with _lock:
        s = _session()
        if s.design is None or s.design.id != d.id:
            s.workspace_heads.clear()
        s.history.clear()
        s.redo.clear()
        s.pdb_atomistic = None
        s.design = d
        _bump_revision(s)


def get_or_404() -> Design:
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        return s.design


def undo_depth() -> int:
    """Current document's undo stack depth."""
    with _lock:
        return len(_session().history)


def redo_depth() -> int:
    """Current document's redo stack depth."""
    with _lock:
        return len(_session().redo)


def mutate_and_validate(
    fn: Callable[[Design], None],
) -> tuple[Design, ValidationReport]:
    """Apply *fn* to the active design in-place under the lock, then validate.

    Pushes the pre-mutation snapshot onto the undo stack and clears redo.
    Returns (design, report).  Raises HTTP 404 if no active design.
    """
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        _assert_active_loadout_editable(s.design)
        s.history.append(s.design.model_copy(deep=True))
        s.redo.clear()
        fn(s.design)
        report = validate_design(s.design)
        _bump_revision(s)
        return s.design, report


def mutate_display_metadata(fn: Callable[[Design], None]) -> tuple[Design, int]:
    """Apply a display-only mutation atomically without topology validation.

    Display metadata cannot invalidate the design, but it still has to advance
    the session revision. Otherwise an older in-flight design response can land
    after this mutation and erase the metadata in the browser.
    """
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        _assert_active_loadout_editable(s.design)
        fn(s.design)
        _bump_revision(s)
        return s.design, s.revision


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
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        _assert_active_loadout_editable(s.design)
        before = s.design.model_copy(deep=True)
        s.history.append(before)
        s.redo.clear()
        report = fn(s.design)
        reconciled = reconcile_cluster_membership(before, s.design, report)
        s.design = _retry_pending_ligations(before, reconciled)
        validation = validate_design(s.design)
        _bump_revision(s)
        return s.design, validation


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
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        _assert_active_loadout_editable(s.design, new_design)
        before = s.design.model_copy(deep=True)
        s.history.append(before)
        s.redo.clear()
        reconciled = reconcile_cluster_membership(before, new_design, report)
        s.design = _retry_pending_ligations(before, reconciled)
        validation = validate_design(s.design)
        _bump_revision(s)
        return s.design, validation


def encode_design_snapshot(design: Design) -> tuple[str, int]:
    """Serialize ``design`` to a gzip+base64 payload for a SnapshotLogEntry.

    The design's own ``feature_log`` and ``feature_log_cursor`` are stripped
    before encoding to prevent recursive nesting (a snapshot must never embed
    other snapshots).

    Returns ``(payload_b64, uncompressed_byte_length)``.
    """
    stripped = design.model_copy(
        update={
            "feature_log": [],
            "feature_log_cursor": -1,
            "feature_log_sub_cursor": None,
            "loadouts": [],
            "active_loadout_id": None,
        }
    )
    raw = stripped.model_dump_json().encode("utf-8")
    # Interactive edits write both pre- and post-state snapshots. Level 3 keeps
    # nearly all of gzip's size reduction while taking roughly one third of the
    # CPU time of level 6 on Voltron-scale designs; eviction is governed by the
    # uncompressed byte budget, so this does not weaken history limits.
    gz = gzip.compress(raw, compresslevel=3)
    return base64.b64encode(gz).decode("ascii"), len(raw)


def decode_design_snapshot(payload_b64: str) -> Design:
    """Inverse of :func:`encode_design_snapshot`.  Raises ``ValueError`` on bad input."""
    if not payload_b64:
        raise ValueError("empty snapshot payload")
    raw = gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))
    return Design.model_validate_json(raw)


def _payload_total_bytes(entry: SnapshotLogEntry | RoutingClusterLogEntry) -> int:
    """Combined compressed payload size (pre + post, plus per-child diffs for a
    cluster) for a payload-bearing entry."""
    if isinstance(entry, SnapshotLogEntry):
        return len(entry.design_snapshot_gz_b64) + len(entry.post_state_gz_b64)
    # RoutingClusterLogEntry — pre/post plus the per-child diff payloads.
    total = len(entry.pre_state_gz_b64) + len(entry.post_state_gz_b64)
    if not entry.diffs_evicted:
        for c in entry.children:
            total += (
                len(c.diff_added_b64)
                + len(c.diff_removed_b64)
                + len(c.diff_modified_b64)
            )
    return total


def _clear_payload(entry: SnapshotLogEntry | RoutingClusterLogEntry) -> None:
    """Drop both pre+post bytes from a snapshot OR cluster entry; flip evicted=True.
    For a cluster, also drop the per-child diff payloads (diffs_evicted=True) —
    once pre/post are gone the cluster is non-revertable anyway, so its diffs
    are useless. Entry + (cluster) children remain visible historically."""
    if isinstance(entry, SnapshotLogEntry):
        entry.design_snapshot_gz_b64 = ""
        entry.post_state_gz_b64 = ""
    else:
        entry.pre_state_gz_b64 = ""
        entry.post_state_gz_b64 = ""
        for c in entry.children:
            c.diff_added_b64 = ""
            c.diff_removed_b64 = ""
            c.diff_modified_b64 = ""
        entry.diffs_evicted = True
    entry.evicted = True


def _evict_oldest_payloads_if_over_budget(design: Design) -> None:
    """Compatibility no-op: canonical feature snapshots are never discarded.

    This hook used to clear the oldest payloads after 5 MB, leaving visible
    feature rows whose Revert action returned HTTP 410. That violates the UI's
    history contract. Response-size control now happens only on serialized
    mutation responses; the server and saved ``.nadoc`` document keep every
    recovery payload.
    """
    return None


# Backward-compat alias; old call site name. Prefer the new name in new code.
_evict_oldest_snapshots_if_over_budget = _evict_oldest_payloads_if_over_budget


def mutate_with_feature_log(
    op_kind: SnapshotOpKind,
    label: str,
    params: dict,
    fn: Callable[[Design], Design | MutationReport | None],
    *,
    expected_revision: int | None = None,
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

    Snapshot bodies remain in canonical state so every entry stays revertable.
    Mutation responses may omit older bodies on the wire, but the browser
    merges its cached copies before persistence.

    Returns ``(design, validation_report, snapshot_entry)``.  Raises HTTP 404
    if no active design.

    Use this for the eight major auto-op routes (auto-scaffold variants,
    auto-break, auto-merge, auto-crossover, create-near/far-ends) and bulk
    overhang manager operations.
    """
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        if expected_revision is not None and s.revision != expected_revision:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Design changed while this operation was being prepared.",
                    "expected_revision": expected_revision,
                    "current_revision": s.revision,
                },
            )
        _assert_active_loadout_editable(s.design)
        before = s.design.model_copy(deep=True)
        history_before = deque(s.history, maxlen=s.history.maxlen)
        redo_before = deque(s.redo, maxlen=s.redo.maxlen)
        s.history.append(before)
        s.redo.clear()

        payload_b64, uncompressed_size = encode_design_snapshot(before)
        try:
            result = fn(s.design)
        except Exception:
            # A callback may mutate in place before discovering an invalid or
            # duplicate operation. Restore all transaction-owned state so a
            # rejected request changes neither the design nor undo/redo.
            s.design = before
            s.history.clear()
            s.history.extend(history_before)
            s.redo.extend(redo_before)
            raise
        # Three return shapes supported:
        #   - Design                      : pure-functional, no custom report.
        #   - (Design, MutationReport)    : pure-functional + custom reconcile hint.
        #   - MutationReport / None       : in-place mutation; report optional.
        if (
            isinstance(result, tuple)
            and len(result) == 2
            and isinstance(result[0], Design)
        ):
            s.design = result[0]
            report = result[1] if isinstance(result[1], MutationReport) else None
        elif isinstance(result, Design):
            s.design = result
            report: MutationReport | None = None
        else:
            report = result if isinstance(result, MutationReport) else None

        reconciled = reconcile_cluster_membership(before, s.design, report)
        if op_kind in ("auto-break", "full-autostaple"):
            # Autobreak / full-autostaple deliberately leave crossovers unligated
            # so staples stay at or below the length cap.  Retrying pre-existing
            # unligated crossovers here would re-ligate across those breaks,
            # busting the 56-nt cap and undoing the routed topology.
            s.design = reconciled
        else:
            s.design = _retry_pending_ligations(before, reconciled)

        # Capture POST-state AFTER reconcile + retry so back-and-forth seeking
        # can restore the live topology even after the slider has been scrubbed
        # back through this entry.
        post_b64, post_size = encode_design_snapshot(s.design)

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
        s.design.feature_log.append(snap_entry)
        _evict_oldest_payloads_if_over_budget(s.design)

        validation = validate_design(s.design)
        _bump_revision(s)
        # So _design_response's default blob-stripping preserves THIS entry's
        # body even when the calling route forgets to pass
        # preserve_feature_log_id explicitly — the client has never seen this
        # id before, so its cache-merge can't backfill a missing body the way
        # it can for an existing (already-cached) entry.
        set_request_feature_log_entry_id(snap_entry.id)
        return s.design, validation, snap_entry


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
    with _lock:
        s = _session()
        if s.design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        _assert_active_loadout_editable(s.design)
        before = s.design.model_copy(deep=True)
        s.history.append(before)
        s.redo.clear()

        # Detect open cluster: last entry must be a non-evicted RoutingClusterLogEntry.
        last_entry = s.design.feature_log[-1] if s.design.feature_log else None
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
        result = fn(s.design)
        if isinstance(result, Design):
            s.design = result
            report: MutationReport | None = None
        else:
            report = result if isinstance(result, MutationReport) else None

        reconciled = reconcile_cluster_membership(before, s.design, report)
        s.design = _retry_pending_ligations(before, reconciled)

        # Re-encode post-state after reconcile + retry so back-and-forth
        # seeking restores the live topology even after the slider has been
        # scrubbed back through the cluster.
        post_b64, post_size = encode_design_snapshot(s.design)

        # Per-child topology diff (pre-child boundary → post-reconcile state).
        # `before` is ALWAYS the pre-child boundary: for a new cluster it equals
        # the cluster pre_state; for an append it equals the previous child's
        # resulting state (the live design before this fn ran). Captured AFTER
        # reconcile + ligation retry, so the diff already includes those effects
        # and reconstruction never re-reconciles. See backend.core.design_diff.
        from backend.core.design_diff import encode_child_diff

        d_added, d_removed, d_modified, d_size = encode_child_diff(before, s.design)

        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
        minor_entry = MinorMutationLogEntry(
            op_subtype=op_subtype,
            label=label,
            timestamp=now_iso,
            params=params,
            diff_added_b64=d_added,
            diff_removed_b64=d_removed,
            diff_modified_b64=d_modified,
            diff_size_bytes=d_size,
        )

        if is_append:
            cluster = s.design.feature_log[-1]
            cluster.children.append(minor_entry)
            cluster.post_state_gz_b64 = post_b64
            cluster.post_state_size_bytes = post_size
        else:
            cluster = RoutingClusterLogEntry(
                label="Fine Routing",
                timestamp=now_iso,
                children=[minor_entry],
                pre_state_gz_b64=pre_b64,
                pre_state_size_bytes=pre_size,
                post_state_gz_b64=post_b64,
                post_state_size_bytes=post_size,
            )
            s.design.feature_log.append(cluster)

        _evict_oldest_payloads_if_over_budget(s.design)

        validation = validate_design(s.design)
        _bump_revision(s)
        # Preserve the PARENT cluster entry, not the child: _strip_feature_log_payloads
        # only matches preserve_entry_ids against top-level entry ids, and a
        # preserved parent keeps all its children's diff blobs too (see its
        # docstring). Matters most for a brand-new cluster (is_append is
        # False) — its id has never reached the client before.
        set_request_feature_log_entry_id(cluster.id)
        return s.design, validation, minor_entry


def _restore_edit_snapshot(snapshot: Design, current: Design) -> Design:
    """File location/signoff are persistence metadata, not editable content."""
    if snapshot.id != current.id:
        return snapshot
    return snapshot.model_copy(update={
        "metadata": snapshot.metadata.model_copy(update={
            "identity_last_known_path": current.metadata.identity_last_known_path,
            "identity_confirmed_at": current.metadata.identity_confirmed_at,
        }),
    })


def undo() -> tuple[Design, ValidationReport]:
    """Restore the previous design state.

    Returns (design, report).  Raises HTTP 404 if nothing to undo.
    """
    with _lock:
        s = _session()
        _assert_active_loadout_editable(s.design)
        if not s.history:
            raise HTTPException(status_code=404, detail="Nothing to undo.")
        s.redo.append(s.design.model_copy(deep=True))
        s.design = _restore_edit_snapshot(s.history.pop(), s.design)
        report = validate_design(s.design)
        _bump_revision(s)
        return s.design, report


def redo() -> tuple[Design, ValidationReport]:
    """Re-apply the last undone mutation.

    Returns (design, report).  Raises HTTP 404 if nothing to redo.
    """
    with _lock:
        s = _session()
        _assert_active_loadout_editable(s.design)
        if not s.redo:
            raise HTTPException(status_code=404, detail="Nothing to redo.")
        s.history.append(s.design.model_copy(deep=True))
        s.design = _restore_edit_snapshot(s.redo.pop(), s.design)
        report = validate_design(s.design)
        _bump_revision(s)
        return s.design, report


def clear_history() -> None:
    """Discard both undo and redo history for the current doc (e.g. after loading
    a new design from disk)."""
    with _lock:
        s = _session()
        s.history.clear()
        s.redo.clear()
        s.workspace_heads.clear()
        s.pdb_atomistic = None


def close_session() -> None:
    """Erase the current document's design and history.

    Also clears the shared protein library (preserves the historical
    single-document "Close Session" semantics).  The multi-document close path
    (:func:`drop_doc`, used by ``DELETE /documents/{id}``) leaves the library
    intact so other open documents keep their assets.
    """
    with _lock:
        s = _session()
        s.design = None
        s.history.clear()
        s.redo.clear()
        s.workspace_heads.clear()
        s.pdb_atomistic = None
        _bump_revision(s)
        _protein_library.clear()
        from backend.core.conjugation import clear_conjugation_candidate_cache
        from backend.core.protein_metrics import clear_protein_process_metrics

        clear_conjugation_candidate_cache()
        clear_protein_process_metrics()


def snapshot() -> None:
    """Push the current design onto the undo stack without changing it.

    Use this before starting a multi-step operation (e.g., step-by-step autostaple)
    so the entire operation is undoable as a single Ctrl-Z.
    """
    with _lock:
        s = _session()
        _assert_active_loadout_editable(s.design)
        if s.design is not None:
            s.history.append(s.design.model_copy(deep=True))
        s.redo.clear()


def get_pdb_atomistic() -> object | None:
    """Return the stored PDB atomistic model for the current doc, or None."""
    with _lock:
        return _session().pdb_atomistic


def set_pdb_atomistic(model: object | None) -> None:
    """Store a pre-built atomistic model from PDB import for the current doc."""
    with _lock:
        _session().pdb_atomistic = model


def add_protein_asset(asset: ProteinAsset) -> None:
    """Add (or replace) a protein asset in the shared session library."""
    with _lock:
        _protein_library[asset.id] = asset


def get_protein_asset(asset_id: str) -> ProteinAsset | None:
    """Return a library protein asset by id, or None."""
    with _lock:
        return _protein_library.get(asset_id)


def list_protein_assets() -> list[ProteinAsset]:
    """Return all protein assets in the shared session library."""
    with _lock:
        return list(_protein_library.values())


def remove_protein_asset(asset_id: str) -> bool:
    """Remove a protein asset from the library.  Returns True if it existed."""
    with _lock:
        return _protein_library.pop(asset_id, None) is not None


def set_design_silent(d: Design) -> None:
    """Update the active design without pushing to the undo stack.

    Use for intermediate steps in a multi-step operation where snapshot()
    was already called before the first step.
    """
    with _lock:
        s = _session()
        _assert_active_loadout_editable(s.design, d)
        s.design = d
        _bump_revision(s)


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
    with _lock:
        s = _session()
        _assert_active_loadout_editable(s.design, new_design)
        reconciled = reconcile_cluster_membership(before, new_design, report)
        s.design = reconciled
        validation = validate_design(s.design)
        _bump_revision(s)
        return s.design, validation
