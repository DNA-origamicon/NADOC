"""Admit group timeline recovery before any snapshot decode or publication.

This compatibility reader deliberately requires all dissolution and organization
recovery bodies. Native input regeneration is separate and has no such requirement.
"""

from fastapi import HTTPException

from backend.core.feature_history_clusters import group_pose_windows, has_group_dissolution
from backend.core.part_capture_graph import GraphBudget
from backend.core.part_recovery_storage import MAX_RECOVERY_BYTES, retained_recovery_bytes


MAX_ORGANIZATION_HISTORY_ENTRIES = 2_000
MAX_ORGANIZATION_ITEMS = 30_000
MAX_ORGANIZATION_METADATA_BYTES = 2_000_000
MAX_ORGANIZATION_RECOVERY_BYTES = MAX_RECOVERY_BYTES
MAX_ORGANIZATION_ID_CHARS = 512


def _organization_kind(entry):
    for field in ("op_kind", "op_subtype"):
        kind = getattr(entry, field, None)
        if type(kind) is str and kind.startswith("group-"):
            return kind
    return None


def _has_organization(entries):
    # Only new organization histories acquire this admission contract. The
    # marker scan does not impose new size/shape limits on legacy histories.
    for entry in entries:
        if _organization_kind(entry) is not None:
            return True
        children = getattr(entry, "children", ())
        if type(children) in (list, tuple) and any(_organization_kind(child) is not None for child in children):
            return True
    return False


def _organization_error(detail, entry=None, *, unavailable=False):
    issue = {"code": "group_recovery_unavailable" if unavailable else "group_recovery_invalid",
             "detail": detail}
    identity, kind = getattr(entry, "id", None), _organization_kind(entry)
    if type(identity) is str and len(identity) <= MAX_ORGANIZATION_ID_CHARS:
        issue["feature_id"] = identity
    if kind is not None and len(kind) <= 64:
        issue["op_kind"] = kind
    raise HTTPException(410 if unavailable else 409, detail=issue)


def _charge_metadata(budget, value):
    # Native input parsing expands each occurrence of an aliased JSON list or
    # mapping. Charge occurrences too, instead of a unique-object graph. The
    # shared budget owns node/string accounting; no serialization is needed.
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError("Group recovery metadata exceeds its nesting allowance")
        if type(item) in (dict, list):
            budget.charge(None)
            count = len(item) * (2 if type(item) is dict else 1)
            if count + len(pending) > budget.remaining[0]:
                raise ValueError("Group recovery metadata exceeds its item allowance")
            if type(item) is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError("Group recovery input keys must be strings")
                    pending.extend(((key, depth + 1), (child, depth + 1)))
            else:
                pending.extend((child, depth + 1) for child in item)
        else:
            if item is not None and type(item) not in (str, bool, int, float):
                raise ValueError("Group recovery metadata requires JSON values")
            budget.charge(item)


def _admit_organization_recovery(entries):
    if not _has_organization(entries):
        return
    from backend.core.models import SnapshotLogEntry
    from backend.core.part_group_organization import KINDS, parse_command

    if type(entries) is not list or len(entries) > MAX_ORGANIZATION_HISTORY_ENTRIES:
        _organization_error("Organization history exceeds its recovery row allowance")
    budget = GraphBudget(max_nodes=MAX_ORGANIZATION_ITEMS, max_bytes=MAX_ORGANIZATION_METADATA_BYTES,
                         seconds=None, clock=lambda: 0)
    identities, count, current = set(), len(entries), None
    try:
        for entry in entries:
            current = entry
            children = getattr(entry, "children", [])
            if type(children) is not list:
                raise ValueError("Group recovery requires a bounded routing child list")
            count += len(children)
            if count > MAX_ORGANIZATION_HISTORY_ENTRIES:
                raise ValueError("Organization history exceeds its recovery row allowance")
            for row in (entry, *children):
                current = row
                identity = row.id
                if type(identity) is not str or not 1 <= len(identity) <= MAX_ORGANIZATION_ID_CHARS:
                    raise ValueError("Group recovery requires bounded feature identities")
                if identity in identities:
                    raise ValueError("Group recovery feature identities are ambiguous")
                identities.add(identity)
                _charge_metadata(budget, identity)
                kind = _organization_kind(row)
                if kind is None:
                    continue
                if (row is not entry or type(row) is not SnapshotLogEntry
                        or row.feature_type != "snapshot" or len(kind) > 64 or kind not in KINDS):
                    raise ValueError("Organization recovery requires recognized top-level snapshot commands")
                _charge_metadata(budget, row.params)
                if type(row.params) is not dict:
                    raise ValueError("Organization recovery requires named command inputs")
                # Attribution is not an input. Do not strip generated scope or
                # arbitrary unknown fields from the closed native contract.
                params = {key: value for key, value in row.params.items() if key != "_generator"}
                parse_command(kind, params)
                if (type(row.evicted) is not bool
                        or type(row.design_snapshot_gz_b64) is not str
                        or type(row.post_state_gz_b64) is not str
                        or any(type(size) is not int or size < 0 or size.bit_length() > 64
                               for size in (row.snapshot_size_bytes, row.post_state_size_bytes))):
                    raise ValueError("Organization recovery body metadata is malformed")
                if (row.diff_added_b64 or row.diff_removed_ids or row.diff_modified_b64
                        or row.pre_state_from_previous is not False):
                    raise ValueError("Organization recovery requires complete full-snapshot bodies")
                if row.evicted or not row.design_snapshot_gz_b64 or not row.post_state_gz_b64:
                    _organization_error("Organization recovery data is unavailable. Timeline seeking is disabled "
                        "for this history; restore a complete saved copy or use input regeneration when supported.",
                        row, unavailable=True)
        # Charge actual retained encoded strings, never caller-provided decoded
        # size claims. This checks storage only; payload validity belongs to the
        # existing decoder after all metadata admission has succeeded.
        current = None
        retained_recovery_bytes(entries, max_rows=MAX_ORGANIZATION_HISTORY_ENTRIES,
                                limit=MAX_ORGANIZATION_RECOVERY_BYTES)
    except (ValueError, TypeError, AttributeError) as exc:
        _organization_error(str(exc), current)


def prepare_group_seek(design, position):
    _admit_organization_recovery(design.feature_log)
    if not has_group_dissolution(design.feature_log):
        return {}
    try:
        windows = group_pose_windows(design, position)
    except ValueError as exc:
        raise HTTPException(409, detail={
            "code": "group_recovery_invalid", "detail": str(exc),
        }) from exc
    for entry in design.feature_log:
        if (entry.feature_type == "snapshot" and entry.op_kind == "cluster-dissolve"
                and (entry.evicted or not entry.design_snapshot_gz_b64 or not entry.post_state_gz_b64)):
            # Another surviving snapshot may describe a different incarnation
            # of the same ID. Do not infer a valid baseline from its presence.
            raise HTTPException(410, detail={
                "code": "group_recovery_unavailable",
                "feature_id": entry.id,
                "detail": "Group dissolution recovery data is unavailable. Timeline seeking is disabled "
                    "for this history; restore a complete saved copy or use input regeneration when supported.",
            })
    return windows


def restore_group_patterns(design, decode_snapshot, pose_windows):
    from backend.core.circular_pattern import pattern_history_overlays
    from backend.core.part_command_errors import CommandContractError

    try:
        return pattern_history_overlays(design, decode_snapshot, pose_windows=pose_windows)
    except CommandContractError as exc:
        raise HTTPException(409, detail=exc.as_issue()) from exc
