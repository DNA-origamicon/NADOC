"""
API layer — active assembly state singleton.

Mirrors backend/api/state.py exactly, substituting Assembly for Design.
Holds a single in-memory Assembly instance shared across all request handlers.
All mutations are protected by a threading.Lock.

Also maintains undo/redo history stacks (up to MAX_UNDO_STEPS deep each).
Every call to set_assembly() pushes the previous state onto the undo stack
and clears the redo stack.  undo() pops from the undo stack and pushes the
displaced state onto the redo stack.  redo() reverses that.

The assembly undo stack is completely independent of the design undo stack —
Ctrl+Z in assembly mode only pops from this stack.

Usage
-----
    from backend.api import assembly_state

    # Read
    assembly = assembly_state.get_or_404()

    # Mutate (push old state onto undo stack)
    assembly_state.set_assembly(new_assembly)

    # Undo last mutation
    assembly = assembly_state.undo()

    # Get or auto-create (for GET /assembly)
    assembly = assembly_state.get_or_create()
"""

from __future__ import annotations

import base64
import gzip
import threading
from collections import deque
from dataclasses import dataclass, field

from fastapi import HTTPException

from backend.api.doc_context import get_current_doc
from backend.core.models import Assembly

# Baseline undo depth for small assemblies.  Effective cap is computed per
# push by ``_undo_cap_for`` and shrinks as instance count grows — each
# undo entry is a full deep-copy of the Assembly, so 50 entries of a
# 2000-instance assembly is a memory hog.  See
# memory/project_path_to_thousands.md (Phase 1d) for context.
MAX_UNDO_STEPS = 50


@dataclass
class _AssemblySession:
    """Per-document assembly state: active assembly + undo/redo + display state."""

    assembly: Assembly | None = None
    # maxlen is the baseline; ``_trim_to`` enforces the adaptive cap on every
    # push so the deque never holds more than the instance-count-aware limit.
    history: deque = field(default_factory=lambda: deque(maxlen=MAX_UNDO_STEPS))
    redo: deque = field(default_factory=lambda: deque(maxlen=MAX_UNDO_STEPS))
    # Per-instance display preferences kept OUTSIDE the assembly object so they
    # survive feature-log scrubbing (representation / visible).  Keyed by
    # PartInstance.id → {representation?, visible?}.
    display_state: dict = field(default_factory=dict)
    # Monotonic change-counter; read by the session-cache flush thread to skip
    # serializing an unchanged assembly.
    revision: int = 0


_lock = threading.Lock()
_sessions: dict[str, _AssemblySession] = {}


def _session() -> _AssemblySession:
    """Return the current request's document assembly session (lazily created).

    MUST be called while holding ``_lock``.
    """
    doc = get_current_doc()
    s = _sessions.get(doc)
    if s is None:
        s = _AssemblySession()
        _sessions[doc] = s
    return s


# ── Document registry helpers (multi-document) ───────────────────────────────


def list_doc_ids() -> list[str]:
    """Doc ids that currently hold an assembly."""
    with _lock:
        return [doc for doc, s in _sessions.items() if s.assembly is not None]


def peek_assembly(doc_id: str) -> Assembly | None:
    """The assembly for a specific doc id without touching the ContextVar."""
    with _lock:
        s = _sessions.get(doc_id)
        return s.assembly if s else None


def has_assembly_unlocked() -> bool:
    """Whether the current doc holds an assembly, WITHOUT taking ``_lock``.

    For the liveness probe (``GET /health``) only — see the matching note on
    ``state.has_design_unlocked``. Never blocks, never creates a session.
    """
    s = _sessions.get(get_current_doc())
    return s is not None and s.assembly is not None


def drop_doc(doc_id: str) -> bool:
    """Forget a document's assembly session entirely. Returns True if it existed."""
    with _lock:
        return _sessions.pop(doc_id, None) is not None


def restore_doc_assembly(doc_id: str, assembly: Assembly) -> None:
    """Load an assembly into a specific doc's session (startup recovery)."""
    with _lock:
        s = _sessions.get(doc_id)
        if s is None:
            s = _AssemblySession()
            _sessions[doc_id] = s
        s.assembly = assembly
        s.revision += 1


def revision_map() -> dict[str, int]:
    """``{doc_id: revision}`` for every assembly session (cheap; for the cache)."""
    with _lock:
        return {doc: s.revision for doc, s in _sessions.items()}


def copy_doc_for_persist(doc_id: str) -> tuple[Assembly | None, int]:
    """``(deep_copy_of_doc_assembly_or_None, revision)`` for one doc, under lock."""
    with _lock:
        s = _sessions.get(doc_id)
        if s is None:
            return None, 0
        snap = s.assembly.model_copy(deep=True) if s.assembly is not None else None
        return snap, s.revision


def _undo_cap_for(assembly: Assembly | None) -> int:
    """Adaptive undo cap based on assembly instance count.

    Small assemblies (≤100 instances) keep the full ``MAX_UNDO_STEPS``
    history.  Larger assemblies shave one slot for every 50 additional
    instances, floored at 5.  Each undo entry is a full Pydantic
    deep-copy, so this keeps RAM bounded for polymer/crystal-scale
    assemblies.
    """
    if assembly is None:
        return MAX_UNDO_STEPS
    n = len(assembly.instances)
    if n <= 100:
        return MAX_UNDO_STEPS
    return max(5, MAX_UNDO_STEPS - n // 50)


def _trim_to(dq: deque[Assembly], cap: int) -> None:
    """Drop oldest entries until ``len(dq) <= cap``."""
    while len(dq) > cap:
        dq.popleft()


def get_assembly() -> Assembly | None:
    with _lock:
        return _session().assembly


def revision() -> int:
    """Current document's assembly change-counter."""
    with _lock:
        return _session().revision


def copy_for_persist() -> tuple[Assembly | None, int]:
    """``(deep copy of current doc's assembly or None, revision)`` under the lock."""
    with _lock:
        s = _session()
        snap = s.assembly.model_copy(deep=True) if s.assembly is not None else None
        return snap, s.revision


def set_assembly(a: Assembly) -> None:
    with _lock:
        s = _session()
        if s.assembly is not None:
            s.history.append(s.assembly.model_copy(deep=True))
            _trim_to(s.history, _undo_cap_for(s.assembly))
        s.redo.clear()
        s.assembly = a
        s.revision += 1


def get_or_404() -> Assembly:
    with _lock:
        s = _session()
        if s.assembly is None:
            raise HTTPException(status_code=404, detail="No active assembly.")
        return s.assembly


def get_or_create() -> Assembly:
    """Return the active assembly, creating a new empty one if none exists."""
    with _lock:
        s = _session()
        if s.assembly is None:
            s.assembly = Assembly()
            s.revision += 1
        return s.assembly


def undo() -> Assembly:
    """Restore the previous assembly state.

    Returns the restored assembly.  Raises HTTP 404 if nothing to undo.
    """
    with _lock:
        s = _session()
        if not s.history:
            raise HTTPException(status_code=404, detail="Nothing to undo.")
        s.redo.append(s.assembly.model_copy(deep=True))
        _trim_to(s.redo, _undo_cap_for(s.assembly))
        s.assembly = s.history.pop()
        s.revision += 1
        return s.assembly


def redo() -> Assembly:
    """Re-apply the last undone mutation.

    Returns the restored assembly.  Raises HTTP 404 if nothing to redo.
    """
    with _lock:
        s = _session()
        if not s.redo:
            raise HTTPException(status_code=404, detail="Nothing to redo.")
        s.history.append(s.assembly.model_copy(deep=True))
        _trim_to(s.history, _undo_cap_for(s.assembly))
        s.assembly = s.redo.pop()
        s.revision += 1
        return s.assembly


def clear_history() -> None:
    """Discard both undo and redo history for the current doc (e.g. after loading
    a new assembly from disk)."""
    with _lock:
        s = _session()
        s.history.clear()
        s.redo.clear()


def close_session() -> None:
    """Erase the current document's assembly and all history."""
    with _lock:
        s = _session()
        s.assembly = None
        s.history.clear()
        s.redo.clear()
        s.display_state.clear()
        s.revision += 1


def remember_instance_display(
    instance_id: str, *, representation: str | None = None, visible: bool | None = None
) -> None:
    """Record a per-instance display preference that survives seek scrubbing.

    Called from any route that mutates ``representation`` or ``visible`` on
    a PartInstance (e.g. ``patch_instance``).  The values are NOT part of
    the assembly snapshot — encoded snapshots still carry whatever was
    current at the time — so seek uses these values to overlay the cheap
    rendering preference on top of the restored geometry.
    """
    with _lock:
        ds = _session().display_state
        entry = ds.get(instance_id, {})
        if representation is not None:
            entry["representation"] = representation
        if visible is not None:
            entry["visible"] = visible
        ds[instance_id] = entry


def get_display_overrides() -> dict[str, dict]:
    """Snapshot of the current per-instance display overrides."""
    with _lock:
        return {k: dict(v) for k, v in _session().display_state.items()}


def forget_instance_display(instance_id: str) -> None:
    """Drop overrides for an instance (e.g. when the instance is deleted)."""
    with _lock:
        _session().display_state.pop(instance_id, None)


def snapshot() -> None:
    """Push the current assembly onto the undo stack without changing it.

    Use before starting a multi-step operation so the entire operation is
    undoable as a single Ctrl-Z.
    """
    with _lock:
        s = _session()
        if s.assembly is not None:
            s.history.append(s.assembly.model_copy(deep=True))
            _trim_to(s.history, _undo_cap_for(s.assembly))
        s.redo.clear()


def set_assembly_silent(a: Assembly) -> None:
    """Update the active assembly without pushing to the undo stack.

    Use for intermediate steps in a multi-step operation where snapshot()
    was already called before the first step.
    """
    with _lock:
        s = _session()
        s.assembly = a
        s.revision += 1


def undo_depth() -> int:
    """Return the current undo stack depth."""
    with _lock:
        return len(_session().history)


def redo_depth() -> int:
    """Return the current redo stack depth."""
    with _lock:
        return len(_session().redo)


# ── Assembly snapshot encoder / decoder ──────────────────────────────────────
#
# Mirrors backend.api.state.encode_design_snapshot for embedding pre/post
# assembly states in SnapshotLogEntry payloads.  Required for the assembly
# feature log's per-entry Delete / Revert / Edit actions: without a payload
# the log entry can only carry params, not enough state to surgically remove
# or edit mid-history.


def encode_assembly_snapshot(assembly: Assembly) -> tuple[str, int]:
    """Serialize an Assembly to a gzip+base64 payload for a SnapshotLogEntry.

    The assembly's own ``feature_log`` and ``feature_log_cursor`` are
    stripped to prevent recursive nesting (snapshots embedded inside
    snapshots).  Returns ``(payload_b64, uncompressed_byte_length)``.

    Phase 5 contract step (path-to-thousands): the payload uses
    :meth:`Assembly.to_dict_v2` — v2-only (format_version + sources +
    instances_v2; no legacy ``instances`` list).  Frontend readers
    (commit ce34c8b) consume v2 and expand client-side.
    ``decode_assembly_snapshot`` falls back to v1 for legacy payloads
    via ``Assembly.from_json``'s detection logic.

    Bug fix: previously called ``to_dict_v2_dual`` which Wave B never
    actually defined — every polymerize / mutation crashed master.
    """
    import json as _json

    stripped = assembly.model_copy(
        update={
            "feature_log": [],
            "feature_log_cursor": -1,
        }
    )
    # v2-only dump (matches the wire-format _assembly_response now emits).
    raw = _json.dumps(stripped.to_dict_v2()).encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)
    return base64.b64encode(gz).decode("ascii"), len(raw)


def decode_assembly_snapshot(payload_b64: str) -> Assembly:
    """Inverse of :func:`encode_assembly_snapshot`.

    Auto-detects format_version: v2 payloads are expanded by
    ``Assembly.from_json`` (which prefers v2 fields when present); v1
    payloads pass through the same call path (no ``format_version`` key
    triggers the legacy branch).
    """
    if not payload_b64:
        raise ValueError("empty assembly snapshot payload")
    raw = gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))
    # Assembly.from_json handles both v1 (legacy) and v2 (current).
    return Assembly.from_json(raw.decode("utf-8"))


# ── Diff snapshot encoder / decoder (Phase 4b path-to-thousands) ─────────────
#
# Same encoding/wire format as the full snapshot (gzip+base64 JSON), but the
# payload is just the changed slices — added objects, ids of removed objects,
# and pre+post state of modified objects.  Used by
# ``_apply_assembly_mutation_with_feature_log`` for bulk ops like polymerize
# that touch a small fraction of total state; the navigation routes
# (seek/revert/delete) handle both formats transparently.


def _gzip_b64(raw: bytes) -> str:
    return base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")


def _ungzip_b64(payload_b64: str) -> bytes:
    return gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))


def _instance_dict(inst) -> dict:
    """JSON-safe dump of a PartInstance (pydantic v2 model)."""
    return inst.model_dump(mode="json")


def _joint_dict(jt) -> dict:
    """JSON-safe dump of an AssemblyJoint (pydantic v2 model)."""
    return jt.model_dump(mode="json")


def encode_diff_snapshot(pre: Assembly, post: Assembly) -> dict:
    """Build diff-snapshot payloads (added/removed_ids/modified) for the
    ``SnapshotLogEntry`` fields ``diff_added_b64`` / ``diff_removed_ids`` /
    ``diff_modified_b64``.

    Compares instances + joints by id.  Returns a dict ready to spread into
    ``SnapshotLogEntry(...)``::

        {
          "diff_added_b64":    "...",       # added items (full state, forward-apply)
          "diff_removed_ids":  ["id1",...], # ids dropped pre → post
          "diff_modified_b64": "...",       # pre + post of modified items, +
                                            #   full state of removed items
                                            #   (the inverse-apply payload)
        }
    """
    import json as _json

    pre_inst_by_id = {i.id: i for i in pre.instances}
    post_inst_by_id = {i.id: i for i in post.instances}
    pre_joint_by_id = {j.id: j for j in pre.joints}
    post_joint_by_id = {j.id: j for j in post.joints}

    # Pre-index maps so inverse-apply can restore removed items at their
    # original positions in the list (otherwise undo-delete shifts items).
    pre_inst_idx_by_id = {i.id: k for k, i in enumerate(pre.instances)}
    pre_joint_idx_by_id = {j.id: k for k, j in enumerate(pre.joints)}

    pre_inst_ids, post_inst_ids = set(pre_inst_by_id), set(post_inst_by_id)
    pre_joint_ids, post_joint_ids = set(pre_joint_by_id), set(post_joint_by_id)

    added_inst_ids = post_inst_ids - pre_inst_ids
    removed_inst_ids = pre_inst_ids - post_inst_ids
    added_joint_ids = post_joint_ids - pre_joint_ids
    removed_joint_ids = pre_joint_ids - post_joint_ids

    # Modified = present in both, but content differs.
    modified_inst_pre: list = []
    modified_inst_post: list = []
    for iid in pre_inst_ids & post_inst_ids:
        pre_i = pre_inst_by_id[iid]
        post_i = post_inst_by_id[iid]
        if pre_i != post_i:
            modified_inst_pre.append(_instance_dict(pre_i))
            modified_inst_post.append(_instance_dict(post_i))

    modified_joint_pre: list = []
    modified_joint_post: list = []
    for jid in pre_joint_ids & post_joint_ids:
        pre_j = pre_joint_by_id[jid]
        post_j = post_joint_by_id[jid]
        if pre_j != post_j:
            modified_joint_pre.append(_joint_dict(pre_j))
            modified_joint_post.append(_joint_dict(post_j))

    added_payload = {
        "instances": [_instance_dict(post_inst_by_id[i]) for i in added_inst_ids],
        "joints": [_joint_dict(post_joint_by_id[j]) for j in added_joint_ids],
    }
    # Sort removed items by their pre-index so inverse-apply can insert them
    # back at the original positions (ascending insertion is order-stable).
    removed_inst_sorted = sorted(removed_inst_ids, key=lambda i: pre_inst_idx_by_id[i])
    removed_joint_sorted = sorted(
        removed_joint_ids, key=lambda j: pre_joint_idx_by_id[j]
    )
    modified_payload = {
        "pre": {
            "instances": modified_inst_pre,
            "joints": modified_joint_pre,
        },
        "post": {
            "instances": modified_inst_post,
            "joints": modified_joint_post,
        },
        "removed": {
            "instances": [
                _instance_dict(pre_inst_by_id[i]) for i in removed_inst_sorted
            ],
            "joints": [_joint_dict(pre_joint_by_id[j]) for j in removed_joint_sorted],
            "inst_pre_idx": [pre_inst_idx_by_id[i] for i in removed_inst_sorted],
            "joint_pre_idx": [pre_joint_idx_by_id[j] for j in removed_joint_sorted],
        },
    }

    diff_added_b64 = _gzip_b64(_json.dumps(added_payload).encode("utf-8"))
    diff_modified_b64 = _gzip_b64(_json.dumps(modified_payload).encode("utf-8"))
    return {
        "diff_added_b64": diff_added_b64,
        "diff_removed_ids": sorted(removed_inst_ids | removed_joint_ids),
        "diff_modified_b64": diff_modified_b64,
    }


def _decode_diff_payloads(entry) -> tuple[dict, list[str], dict]:
    """Decode the three diff_* fields on a SnapshotLogEntry into raw dicts.

    Returns ``(added, removed_ids, modified)`` where ``added`` is
    ``{"instances": [...], "joints": [...]}``, ``removed_ids`` is the list of
    ids dropped pre → post, and ``modified`` is
    ``{"pre": {...}, "post": {...}, "removed": {...}}``.
    """
    import json as _json

    added: dict = {"instances": [], "joints": []}
    if entry.diff_added_b64:
        added = _json.loads(_ungzip_b64(entry.diff_added_b64).decode("utf-8"))
    modified: dict = {
        "pre": {"instances": [], "joints": []},
        "post": {"instances": [], "joints": []},
        "removed": {"instances": [], "joints": []},
    }
    if entry.diff_modified_b64:
        modified = _json.loads(_ungzip_b64(entry.diff_modified_b64).decode("utf-8"))
    return added, list(entry.diff_removed_ids or []), modified


def is_diff_entry(entry) -> bool:
    """True iff *entry* is a diff-snapshot variant (any diff_* field set).

    Legacy entries use ``design_snapshot_gz_b64`` / ``post_state_gz_b64``
    exclusively and have empty diff_* fields.
    """
    return bool(
        getattr(entry, "diff_added_b64", "")
        or getattr(entry, "diff_modified_b64", "")
        or getattr(entry, "diff_removed_ids", None)
    )


def apply_diff_forward(anchor: Assembly, entry) -> Assembly:
    """Apply the diff payload of *entry* to *anchor* (= pre-state of the op)
    to produce the post-state.

    Forward apply order: drop removed-ids, replace modified by their POST
    state, append added items.  Returns a new Assembly; ``anchor``'s
    feature_log + cursor pass through unchanged (callers patch those).
    """
    from backend.core.models import AssemblyJoint, PartInstance

    added, removed_ids, modified = _decode_diff_payloads(entry)
    removed_set = set(removed_ids)
    mod_post_inst = {d["id"]: d for d in modified.get("post", {}).get("instances", [])}
    mod_post_joint = {d["id"]: d for d in modified.get("post", {}).get("joints", [])}

    new_instances: list[PartInstance] = []
    for inst in anchor.instances:
        if inst.id in removed_set:
            continue
        if inst.id in mod_post_inst:
            new_instances.append(PartInstance.model_validate(mod_post_inst[inst.id]))
        else:
            new_instances.append(inst)
    for d in added.get("instances", []):
        new_instances.append(PartInstance.model_validate(d))

    new_joints: list[AssemblyJoint] = []
    for jt in anchor.joints:
        if jt.id in removed_set:
            continue
        if jt.id in mod_post_joint:
            new_joints.append(AssemblyJoint.model_validate(mod_post_joint[jt.id]))
        else:
            new_joints.append(jt)
    for d in added.get("joints", []):
        new_joints.append(AssemblyJoint.model_validate(d))

    return anchor.model_copy(
        update={
            "instances": new_instances,
            "joints": new_joints,
        }
    )


def is_skip_pre_entry(entry) -> bool:
    """True iff *entry* uses the Phase 1b skip-pre format.

    A skip-pre entry has no embedded pre-state snapshot and no diff_*
    fields; instead, its pre-state equals the previous feature_log entry's
    post-state (a free reference, since the feature log is append-only).
    """
    return bool(getattr(entry, "pre_state_from_previous", False))


def lookup_pre_state(feature_log, index: int) -> Assembly:
    """Return the pre-state Assembly for ``feature_log[index]``.

    Handles three storage modes plus the chain-walk:

    * Legacy full snapshot — entry carries ``design_snapshot_gz_b64``;
      decode and return.
    * Diff-snapshot entry (Phase 4b) — decode the entry's full post,
      then inverse-apply the diff.
    * Skip-pre entry (Phase 1b, ``pre_state_from_previous=True``) — return
      the previous feature_log entry's post-state.  If the previous entry
      is itself a skip-pre (or has an empty post payload for any reason),
      walk further back.  The walk terminates when an entry with a usable
      post is found, or when index 0 is reached with no pre to decode →
      raises HTTPException(422).

    Raises HTTPException on unrecoverable states (no payloads, decode
    failure, index 0 with skip-pre, etc.).  Callers route the 422s to
    the user as "this entry is too old to revert directly".
    """
    if index < 0 or index >= len(feature_log):
        raise HTTPException(404, detail=f"feature index {index} out of range.")

    entry = feature_log[index]

    # Case 1: legacy full pre-snapshot present → decode directly.
    if entry.design_snapshot_gz_b64:
        try:
            return decode_assembly_snapshot(entry.design_snapshot_gz_b64)
        except Exception as exc:
            raise HTTPException(
                500, detail=f"Failed to decode snapshot: {exc}"
            ) from exc

    # Case 2: diff-format entry → reconstruct pre from full post + inverse diff.
    if is_diff_entry(entry):
        if not entry.post_state_gz_b64:
            raise HTTPException(
                500,
                detail="Diff entry missing post_state_gz_b64; cannot reconstruct pre-state.",
            )
        try:
            post_state = decode_assembly_snapshot(entry.post_state_gz_b64)
        except Exception as exc:
            raise HTTPException(
                500, detail=f"Failed to decode snapshot: {exc}"
            ) from exc
        return apply_diff_inverse(post_state, entry)

    # Case 3: skip-pre → walk back to previous entry's post.  Chain-walk
    # past any preceding skip-pre or evicted entries until we find one with
    # a usable post payload.
    if is_skip_pre_entry(entry):
        j = index - 1
        while j >= 0:
            prev = feature_log[j]
            if prev.post_state_gz_b64:
                try:
                    return decode_assembly_snapshot(prev.post_state_gz_b64)
                except Exception as exc:
                    raise HTTPException(
                        500, detail=f"Failed to decode snapshot: {exc}"
                    ) from exc
            j -= 1
        # Walked off the front of the log with no usable post anywhere.
        raise HTTPException(
            422,
            detail="Skip-pre entry has no anchor: previous feature_log entries lack "
            "decodable post-state payloads.  Use Ctrl-Z to navigate around it.",
        )

    # Case 4: nothing usable.
    raise HTTPException(
        422,
        detail="This entry has no embedded pre-state snapshot — it was "
        "created before per-entry actions were supported. Use the "
        "slider / Ctrl-Z to navigate around it.",
    )


def apply_diff_inverse(anchor: Assembly, entry) -> Assembly:
    """Apply the inverse of *entry*'s diff to *anchor* (= post-state of the op)
    to recover the pre-state.

    Inverse apply order: drop added items, restore removed items (full state
    from modified.removed), replace modified by their PRE state.
    """
    from backend.core.models import AssemblyJoint, PartInstance

    added, _removed_ids, modified = _decode_diff_payloads(entry)
    added_inst_ids = {d["id"] for d in added.get("instances", [])}
    added_joint_ids = {d["id"] for d in added.get("joints", [])}
    mod_pre_inst = {d["id"]: d for d in modified.get("pre", {}).get("instances", [])}
    mod_pre_joint = {d["id"]: d for d in modified.get("pre", {}).get("joints", [])}

    removed_block = modified.get("removed", {})
    removed_inst_data = removed_block.get("instances", [])
    removed_joint_data = removed_block.get("joints", [])
    removed_inst_idx = removed_block.get("inst_pre_idx", None)
    removed_joint_idx = removed_block.get("joint_pre_idx", None)

    new_instances: list[PartInstance] = []
    for inst in anchor.instances:
        if inst.id in added_inst_ids:
            continue  # was added by this op — drop to get back to pre
        if inst.id in mod_pre_inst:
            new_instances.append(PartInstance.model_validate(mod_pre_inst[inst.id]))
        else:
            new_instances.append(inst)
    # Restore removed-by-this-op items.  When pre-index info is present
    # (encoder ≥ Phase 4a follow-up), insert at the original position so
    # undo-delete preserves list order.  Legacy payloads (no pre-idx)
    # fall back to append; they shipped before this format extension.
    if removed_inst_idx is not None and len(removed_inst_idx) == len(removed_inst_data):
        for idx, d in sorted(
            zip(removed_inst_idx, removed_inst_data), key=lambda t: t[0]
        ):
            new_instances.insert(
                min(idx, len(new_instances)), PartInstance.model_validate(d)
            )
    else:
        for d in removed_inst_data:
            new_instances.append(PartInstance.model_validate(d))

    new_joints: list[AssemblyJoint] = []
    for jt in anchor.joints:
        if jt.id in added_joint_ids:
            continue
        if jt.id in mod_pre_joint:
            new_joints.append(AssemblyJoint.model_validate(mod_pre_joint[jt.id]))
        else:
            new_joints.append(jt)
    if removed_joint_idx is not None and len(removed_joint_idx) == len(
        removed_joint_data
    ):
        for idx, d in sorted(
            zip(removed_joint_idx, removed_joint_data), key=lambda t: t[0]
        ):
            new_joints.insert(
                min(idx, len(new_joints)), AssemblyJoint.model_validate(d)
            )
    else:
        for d in removed_joint_data:
            new_joints.append(AssemblyJoint.model_validate(d))

    return anchor.model_copy(
        update={
            "instances": new_instances,
            "joints": new_joints,
        }
    )
