"""Record ordinary group authoring under the document's state lock.

Grouping owns cluster membership directly, so it uses the shared pure overlay
builder and replacement transaction rather than topology reconciliation. This
does not infer a recipe root or validate an entire historical recipe.
"""

import math
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import doc_context, state
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry, ClusterRigidTransform, DomainRef, SnapshotLogEntry
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import GROUP_CREATE_VERSION, build
from backend.core.part_structure import MAX_ID_CHARS, MAX_ITEMS
from backend.core.part_structure_gate import PartStructureError, require_valid_structure


AUTHORED_FIELDS = frozenset({"name", "helix_ids", "domain_ids", "color", "opacity"})


def _start(action):
    """Called with the non-reentrant state lock already held."""
    state._require_compatibility_write(action)
    session = state._session()
    source, revision, identity = session.design, session.revision, session.identity
    if source is None:
        raise HTTPException(404, detail="No active design.")
    state._assert_active_loadout_editable(source)
    # Historical branching requires its own input/history policy. Do not
    # truncate only outer entries and retain unapplied children or an F0 future.
    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise HTTPException(409, detail={
            "code": "historical_cursor",
            "message": "Return to the latest history position before editing a group.",
        })
    return session, source, revision, identity


def _publish(session, source, revision, identity, candidate):
    """Validate once before the one failure-atomic publication."""
    try:
        require_valid_structure(candidate)
    except PartStructureError as exc:
        raise HTTPException(409, detail=exc.as_issue()) from exc
    report = state.validate_design(candidate)
    current = state._sessions.get(doc_context.get_current_doc())
    if (current is not session or current.identity != identity
            or current.design is not source or current.revision != revision):
        raise HTTPException(409, detail={
            "code": "source_changed",
            "message": "The document changed before the group edit could be published.",
        })
    state._assert_active_loadout_editable(source, candidate)
    state._assert_photoproduct_dependencies(candidate)
    publish_replacement(session, candidate)
    return candidate, report


def create_group(body):
    """Publish one group, authored row and undo step; ``log`` cannot bypass it."""
    with state._lock:
        session, source, revision, identity = _start("group_creation")

        group = ClusterRigidTransform(
            name=body.name,
            helix_ids=list(body.helix_ids),
            domain_ids=[DomainRef.model_validate(item) for item in body.domain_ids],
        )
        grouped = build("cluster_create", source, {
            "cluster": group.model_dump(mode="json"), "_proof_version": GROUP_CREATE_VERSION})
        entry = ClusterCreateLogEntry(
            proof_version=GROUP_CREATE_VERSION,
            cluster_snapshot=group,
            cluster_id=group.id,
            name=group.name,
            helix_ids=list(group.helix_ids),
            domain_ids=list(group.domain_ids),
        )
        candidate = grouped.copy_with(feature_log=[*source.feature_log, entry])
        return _publish(session, source, revision, identity, candidate)


def _reference_error(kind, identity, path, *, ambiguous=False, status=409):
    error = ReferenceResolutionError(
        "Group edit target is ambiguous or repeated." if ambiguous else "Group edit target is missing.",
        code="invalid_selection" if ambiguous else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )
    raise HTTPException(status, detail=error.as_issue())


def _limit():
    raise HTTPException(409, detail={
        "code": "group_input_limit",
        "message": "Group references exceed the bounded edit allowance.",
        "maximum_items": MAX_ITEMS, "maximum_identity_chars": MAX_ID_CHARS,
    })


def _identity(value):
    if not isinstance(value, str) or not value:
        raise HTTPException(422, detail={
            "code": "invalid_group_input", "message": "Group references must use nonempty string identities.",
        })
    if len(value) > MAX_ID_CHARS:
        _limit()
    return value


def _check_members(source, group):
    """Bounded typed selectors, not a scan of geometry or historical snapshots."""
    helices, strands = {}, {}
    for helix in source.helices:
        key = helix.id
        helices[key] = helices.get(key, 0) + 1
    for strand in source.strands:
        key = strand.id
        strands.setdefault(key, []).append(strand)
    seen = set()
    for index, identity in enumerate(group.helix_ids):
        _identity(identity)
        count = helices.get(identity, 0)
        if count != 1 or identity in seen:
            _reference_error("helix", identity, ["helix_ids", index],
                             ambiguous=count > 1 or identity in seen)
        seen.add(identity)
    seen.clear()
    for index, ref in enumerate(group.domain_ids):
        _identity(ref.strand_id)
        matches = strands.get(ref.strand_id, [])
        key = (ref.strand_id, ref.domain_index)
        if (len(matches) != 1 or key in seen or not
                0 <= ref.domain_index < len(matches[0].domains)):
            _reference_error("strand", ref.strand_id, ["domain_ids", index],
                             ambiguous=len(matches) > 1 or key in seen)
        seen.add(key)


def _check_input_bounds(source, group, fields):
    # Check collection lengths before serializing or constructing the group.
    helices = fields.get("helix_ids", group.helix_ids)
    domains = fields.get("domain_ids", group.domain_ids)
    if len(source.helices) + len(source.strands) + len(helices) + len(domains) > MAX_ITEMS:
        _limit()
    for collection in (source.helices, source.strands):
        for item in collection:
            _identity(item.id)
    for identity in helices:
        _identity(identity)
    for ref in domains:
        _identity(ref.strand_id if isinstance(ref, DomainRef) else ref.get("strand_id"))
    _check_operation(fields)


def _check_operation(params):
    try:
        validate_operation_input(params)
    except ValueError as exc:
        raise HTTPException(422, detail={
            "code": "invalid_group_input", "message": str(exc),
        }) from exc


def update_group(cluster_id, fields):
    """Publish one complete v1 pose/membership input and one undo step.

    The existing overlay semantics remain exact, including overlapping groups.
    Membership edits intentionally change which members receive this transform;
    no coordinates are baked or automatic pose rebasing inferred here.
    """
    with state._lock:
        session, source, revision, identity = _start("group_edit")
        if len(source.cluster_transforms) > MAX_ITEMS:
            _limit()
        _identity(cluster_id)
        matches = [c for c in source.cluster_transforms if c.id == cluster_id]
        if len(matches) != 1:
            _reference_error("cluster", cluster_id, ["cluster_id"],
                             ambiguous=bool(matches), status=409 if matches else 404)
        _check_input_bounds(source, matches[0], fields)
        try:
            group = ClusterRigidTransform.model_validate({**matches[0].model_dump(), **fields})
        except ValidationError as exc:
            raise HTTPException(422, detail={"code": "invalid_group_input", "message": str(exc)}) from exc
        for key, size in (("translation", 3), ("rotation", 4), ("pivot", 3)):
            values = getattr(group, key)
            if len(values) != size or not all(math.isfinite(value) for value in values):
                raise HTTPException(422, detail={"code": "invalid_group_pose", "field": key})
        if not any(group.rotation) or not math.isfinite(group.opacity):
            raise HTTPException(422, detail={"code": "invalid_group_pose"})
        _check_members(source, group)
        entry = ClusterOpLogEntry(
            proof_version=1, cluster_id=cluster_id,
            authored_fields=group.model_dump(mode="json", include=AUTHORED_FIELDS),
            translation=list(group.translation), rotation=list(group.rotation), pivot=list(group.pivot),
        )
        from backend.core.part_overlay_commands import command_input
        kind, params = command_input(entry)
        # The exact emitted input must fit the same metadata envelope used by
        # dependency admission, including unchanged legacy membership/name data.
        _check_operation(params)
        grouped = build(kind, source, params)
        candidate = grouped.copy_with(feature_log=[*source.feature_log, entry])
        return _publish(session, source, revision, identity, candidate)


def dissolve_groups(cluster_ids):
    """Record one atomic keep-members operation, with recovery kept separate.

    The native command proves its own finite reference/placement admission.
    Whole-design recovery uses the established snapshot format only for seek
    and undo; replay depends solely on the versioned selected identities.
    """
    from backend.api.part_recovery_budget import RecoveryBudget
    from backend.core.part_capture_graph import CaptureLimit
    from backend.core.part_command_errors import CommandContractError
    from backend.core.part_group_dissolve import KIND, build as dissolve
    from backend.core.part_history_proof import ProofBudgetExceeded
    from backend.core.part_recovery_storage import MAX_RECOVERY_BYTES, retained_recovery_bytes

    with state._lock:
        session, source, revision, identity = _start("group_dissolve")
        params = {"_proof_version": 1, "cluster_ids": cluster_ids}
        try:
            grouped = dissolve(source, params)
        except CommandContractError as exc:
            raise HTTPException(404 if exc.code == "missing_reference" else 409, detail=exc.as_issue()) from exc
        try:
            retained = retained_recovery_bytes(source.feature_log, max_rows=1999)
            budget = RecoveryBudget(MAX_RECOVERY_BYTES - retained)
            pre, pre_size = state.encode_design_snapshot(source)
            budget.charge(pre)
            post, post_size = state.encode_design_snapshot(grouped)
            budget.charge(post)
        except (CaptureLimit, ProofBudgetExceeded) as exc:
            raise HTTPException(409, detail={"code": "group_recovery_limit", "message": str(exc)}) from exc
        entry = SnapshotLogEntry(
            op_kind=KIND, label="Dissolve group" if len(cluster_ids) == 1 else f"Dissolve {len(cluster_ids)} groups",
            timestamp=datetime.now(timezone.utc).isoformat(),
            params=params, design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
            post_state_gz_b64=post, post_state_size_bytes=post_size,
        )
        candidate = grouped.copy_with(feature_log=[*source.feature_log, entry])
        return _publish(session, source, revision, identity, candidate)
