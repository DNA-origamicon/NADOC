"""Owned, revision-checked organization edits using the existing publication host.

Prepare bounded authoring inputs outside the document lock, then merge only the
owned fields into the unchanged source. Recovery is authoring recovery; live
physical and presentation state stays on the source. No historical replay or
derived geometry is required by an organizational edit.
"""

import hashlib
import json
import math
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_permit as permits
from backend.api import part_publication_policy as policy
from backend.api.part_model_serialization import admit_model_serialization
from backend.api.part_recovery_budget import RecoveryBudget
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import ClusterOpLogEntry, SnapshotLogEntry, VisibilityState
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_group_model import PartGroup
from backend.core.part_group_organization import EDIT_FIELDS, KINDS, build as build_organization
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import build as build_overlay
from backend.core.part_recovery_storage import MAX_RECOVERY_BYTES, retained_recovery_bytes
from backend.core.part_structure_gate import PartStructureError, require_valid_structure


POSE_FIELDS = {"translation": 3, "rotation": 4, "pivot": 3}
MAX_HISTORY_ROWS = 2_000
PLACEMENT_KINDS = frozenset({"placement-update", "placements-update"})
MAX_PLACEMENTS_PER_EDIT = 64


def _invalid(message):
    raise HTTPException(422, detail={"code": "invalid_group_input", "message": message})


def _request(kind, inputs, expected_revision):
    if type(expected_revision) is not int or expected_revision < 0:
        _invalid("An exact nonnegative document revision is required.")
    if type(kind) is not str or kind not in KINDS | PLACEMENT_KINDS | {"visibility-update"} or type(inputs) is not dict:
        _invalid("Select a supported group or explicit placement command.")
    try:
        validate_operation_input(inputs)
        # Isolate the bounded request before preparing it or hashing its values.
        encoded = json.dumps({"kind": kind, "inputs": inputs, "expected_revision": expected_revision},
            sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as error:
        _invalid(str(error))
    return json.loads(encoded)["inputs"], hashlib.sha256(encoded.encode()).hexdigest()


def _editable(source, *, display=False):
    state._assert_active_loadout_editable(source)
    if not display and (source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None):
        raise HTTPException(409, detail={"code": "historical_cursor",
            "message": "Return to the latest history position before editing a group."})


def _current(context, session):
    gate.require_group_edit_enabled()
    if policy.resolve(context.doc_id).generation != context.policy_generation:
        raise HTTPException(409, detail={"code": "policy_changed",
            "message": "Construction policy changed while the group edit was being prepared."})
    if (doc_context.get_current_doc() != context.doc_id
            or state._sessions.get(context.doc_id) is not session
            or not permits.context_matches(context, context.doc_id, session)):
        raise HTTPException(409, detail={"code": "source_changed",
            "message": "The document changed while the group edit was being prepared."})
    policy.require_compatibility(context.doc_id, "owned_group_edit")
    _editable(session.design, display=context.operation == "visibility-update")


def _placement(source, inputs):
    if (set(inputs) != {"placement_id", "fields"} or type(inputs["placement_id"]) is not str
            or not 1 <= len(inputs["placement_id"]) <= 512 or type(inputs["fields"]) is not dict
            or not inputs["fields"] or set(inputs["fields"]) - POSE_FIELDS.keys()):
        _invalid("Placement updates require one explicit placement identity and pose fields only.")
    if source.group_organization is None:
        _invalid("Convert grouping before using the separate placement editor.")
    matches = [item for item in source.cluster_transforms if item.id == inputs["placement_id"]]
    if len(matches) != 1:
        raise ReferenceResolutionError("The explicit placement is missing or ambiguous.",
            code="invalid_selection" if matches else "missing_reference",
            references=[{"kind": "cluster", "identity": inputs["placement_id"],
                "parameter_path": ["placement_id"]}])
    pose = {name: inputs["fields"].get(name, getattr(matches[0], name)) for name in POSE_FIELDS}
    for name, length in POSE_FIELDS.items():
        values = pose[name]
        if (type(values) is not list or len(values) != length
                or any(type(value) not in {int, float} or not math.isfinite(value) for value in values)):
            _invalid("Placement poses require finite numerical vectors of the declared lengths.")
    if not any(pose["rotation"]):
        _invalid("Placement rotation must be a nonzero quaternion.")
    params = {"_proof_version": 1, "cluster_id": inputs["placement_id"], **pose}
    result = build_overlay("cluster_op", source, params)
    entry = ClusterOpLogEntry(proof_version=1, cluster_id=inputs["placement_id"], **pose)
    return result, entry


def _prepare(kind, source, inputs):
    if kind == "placement-update":
        return _placement(source, inputs)
    if kind == "placements-update":
        if (set(inputs) != {"placements"} or type(inputs["placements"]) is not list
                or not 1 <= len(inputs["placements"]) <= MAX_PLACEMENTS_PER_EDIT):
            _invalid("Select between one and 64 explicit placements for one move.")
        identities = set()
        result, entries = source, []
        for item in inputs["placements"]:
            if type(item) is not dict or type(item.get("placement_id")) is not str:
                _invalid("Each move requires an explicit placement identity and pose fields.")
            if item["placement_id"] in identities:
                _invalid("A move cannot repeat a placement identity.")
            identities.add(item["placement_id"])
            updated, entry = _placement(result, item)
            if updated.cluster_transforms != result.cluster_transforms:
                entries.append(entry)
            result = updated
        return result, entries
    if kind == "visibility-update":
        value = inputs.get("visibility_state")
        fields = set(VisibilityState.model_fields)
        if (set(inputs) != {"visibility_state"} or type(value) is not dict
                or set(value) not in (fields, fields - {"hidden_part_group_ids"})
                or any(type(items) is not list or any(type(item) is not str for item in items)
                       for items in value.values())):
            _invalid("Visibility requires exact nucleotide/placement lists and an optional named-group identity list.")
        # Validate the original count before deduplicating; never infer members
        # or reinterpret dormant group IDs as numerical placement owners.
        validated = VisibilityState.model_validate(value)
        visibility = validated.model_copy(update={
            key: list(dict.fromkeys(getattr(validated, key))) for key in fields})
        return source.copy_with(visibility_state=visibility), None
    if kind == "group-create":
        if set(inputs) - EDIT_FIELDS:
            _invalid("New groups accept membership, name and style only; identities are allocated by the host.")
        params = {"_proof_version": 1,
            "group": PartGroup(id=str(uuid4()), **inputs).model_dump(mode="json")}
    else:
        if "_proof_version" in inputs:
            _invalid("The host owns the native command version.")
        params = {**inputs, "_proof_version": 1}
    result = build_organization(kind, source, params)
    entry = SnapshotLogEntry(op_kind=kind, label={"group-organize": "Separate groups and placements",
        "group-create": "Create group", "group-update": "Edit group", "group-dissolve": "Dissolve groups"}[kind],
        timestamp=datetime.now(timezone.utc).isoformat(), params=params)
    return result, entry


def apply(kind, inputs, *, expected_revision):
    """Publish an owned edit atomically; visibility has no native feature row."""
    from backend.core.part_verification_capture import CaptureLimit, admit, capture

    gate.require_group_edit_enabled()
    policy.require_compatibility(doc_context.get_current_doc(), "owned_group_edit")
    inputs, digest = _request(kind, inputs, expected_revision)
    try:
        with state._lock:
            gate.require_group_edit_enabled()
            policy.require_compatibility(doc_context.get_current_doc(), "owned_group_edit")
            session = state._sessions.get(doc_context.get_current_doc())
            if session is None or session.design is None:
                raise HTTPException(404, detail="No active design.")
            if session.revision != expected_revision:
                raise HTTPException(409, detail={"code": "source_changed",
                    "message": "Refresh the design before editing its groups."})
            source = session.design
            _editable(source, display=kind == "visibility-update")
            admission = permits.admit_group_edit(doc_context.get_current_doc(), session,
                operation="cluster_op" if kind in PLACEMENT_KINDS else kind, request_sha256=digest)
            context = permits.admission_context(admission)
            retained = retained_recovery_bytes(source.feature_log, max_rows=MAX_HISTORY_ROWS)
            captured = capture(source, preserve_entry_types=True)

        admit_model_serialization(captured, max_nodes=30_000, max_bytes=2_000_000,
                                  label="Group authoring serialization")
        prepared, entry = _prepare(kind, captured, inputs)
        entries = entry if type(entry) is list else ([] if entry is None else [entry])
        owned_field = ("cluster_transforms" if kind in PLACEMENT_KINDS else
                       "visibility_state" if kind == "visibility-update" else "group_organization")
        changed = getattr(prepared, owned_field) != getattr(source, owned_field)
        # Validate the bounded private input, without serializing live physical
        # state or repeating a whole recipe replay on an ordinary group gesture.
        if changed:
            # Charge actual appended rows against the same aggregate inventory,
            # including Fine Routing children. The captured definition is owned;
            # its stripped recovery bodies are not used as storage evidence.
            retained_recovery_bytes(captured.feature_log, max_rows=MAX_HISTORY_ROWS - len(entries))
            admitted = prepared.copy_with(feature_log=[*prepared.feature_log, *entries])
            admit(admitted, preserve_entry_types=True)
            admit_model_serialization(admitted, max_nodes=30_000, max_bytes=2_000_000,
                                      label="Group authoring serialization")
        require_valid_structure(prepared)
        state._assert_photoproduct_dependencies(prepared)
        report = state.validate_design(prepared)
        if changed and kind in KINDS:
            budget = RecoveryBudget(MAX_RECOVERY_BYTES - retained)
            pre, pre_size = state.encode_design_snapshot(captured)
            budget.charge(pre)
            post, post_size = state.encode_design_snapshot(prepared)
            budget.charge(post)
            entry = entry.model_copy(update={"design_snapshot_gz_b64": pre, "snapshot_size_bytes": pre_size,
                "post_state_gz_b64": post, "post_state_size_bytes": post_size})
            entries = [entry]

        with state._lock:
            _current(context, session)
            if not changed:
                doc_context.set_request_revision(context.source_revision)
                return source, report, None
            candidate = source.copy_with(**{owned_field: getattr(prepared, owned_field)},
                feature_log=[*source.feature_log, *entries] if entries else source.feature_log)
            state._assert_active_loadout_editable(source, candidate)
            permit = permits.issue_group_edit_permit(admission, candidate,
                request_sha256=digest, expires=monotonic() + 60)
            publish_replacement(session, candidate, publication_permit=permit)
            last_entry = entries[-1] if entries else None
            doc_context.set_request_feature_log_entry_id(last_entry.id if last_entry else None)
            return candidate, report, last_entry
    except (CaptureLimit, ProofBudgetExceeded) as error:
        raise HTTPException(409, detail={"code": "group_capture_limit", "message": str(error)}) from error
    except (CommandContractError, PartStructureError) as error:
        raise HTTPException(409, detail=error.as_issue()) from error
    except ValueError as error:
        _invalid(str(error))
