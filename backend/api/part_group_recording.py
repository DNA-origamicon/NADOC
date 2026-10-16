"""Record ordinary group authoring under the document's state lock.

Grouping owns cluster membership directly, so it uses the shared pure overlay
builder and replacement transaction rather than topology reconciliation. This
does not infer a recipe root or validate an entire historical recipe.
"""

import math
from dataclasses import dataclass
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
MAX_COMPONENT_GRAPH_WORK = 200_000
MAX_COMPONENT_GROUPS = 128


@dataclass(frozen=True)
class GroupSource:
    """Request-local admission; no global cache or retained candidate."""

    source: object
    captured: object
    session: object
    revision: int
    identity: str
    doc_id: str
    policy_generation: int


def capture_group_source(action):
    """Capture independent authoring input while the host owns its state lock."""
    from backend.api.part_publication_policy import resolve
    from backend.core.part_verification_capture import CaptureLimit, capture

    with state._lock:
        session, source, revision, identity = _start(action)
        doc_id = doc_context.get_current_doc()
        generation = resolve(doc_id).generation
        try:
            captured = capture(source, preserve_entry_types=True)
        except CaptureLimit as exc:
            raise HTTPException(409, detail={"code": "group_capture_limit", "message": str(exc)}) from exc
        return GroupSource(source, captured, session, revision, identity, doc_id, generation)


def require_group_source_current(admission):
    """Lock-owned origin check before allocating/publishing a final candidate."""
    from backend.api.part_publication_policy import resolve

    current = state._sessions.get(admission.doc_id)
    if (doc_context.get_current_doc() != admission.doc_id or current is not admission.session
            or current.identity != admission.identity or current.design is not admission.source
            or current.revision != admission.revision):
        raise HTTPException(409, detail={"code": "source_changed",
            "message": "The document changed while grouping was being prepared."})
    if resolve(admission.doc_id).generation != admission.policy_generation:
        raise HTTPException(409, detail={"code": "policy_changed",
            "message": "Construction policy changed while grouping was being prepared."})
    state._require_compatibility_write("prepared_group_edit")
    state._assert_active_loadout_editable(admission.source)


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


def _check_members(source, group, *, indexes=None):
    """Bounded typed selectors, not a scan of geometry or historical snapshots."""
    if indexes is None:
        helices, strands = {}, {}
        for helix in source.helices:
            key = helix.id
            helices[key] = helices.get(key, 0) + 1
        for strand in source.strands:
            key = strand.id
            strands.setdefault(key, []).append(strand)
    else:
        helices, strands = indexes
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
        candidate, _ = prepare_group_update(source, cluster_id, fields)
        return _publish(session, source, revision, identity, candidate)


def prepare_group_update(source, cluster_id, fields, *, entry_source=None):
    """Shared pure v1 pose/membership preparation for an owned source."""
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
        proof_version=1, cluster_id=cluster_id, source=entry_source,
        authored_fields=group.model_dump(mode="json", include=AUTHORED_FIELDS),
        translation=list(group.translation), rotation=list(group.rotation), pivot=list(group.pivot),
    )
    from backend.core.part_overlay_commands import command_input
    kind, params = command_input(entry)
    # The emitted input must fit dependency admission, including unchanged
    # legacy membership/name data. No source fields outside grouping change.
    _check_operation(params)
    grouped = build(kind, source, params)
    return grouped.copy_with(feature_log=[*source.feature_log, entry]), entry


def _component_input(source):
    """Admit the graph's typed identities/membership before graph allocation."""
    collections = (source.helices, source.strands, source.cluster_transforms,
                   source.crossovers, source.forced_ligations)
    items = sum(len(collection) for collection in collections)
    if items > MAX_ITEMS:
        _limit()
    for strand in source.strands:
        items += len(strand.domains)
        if items > MAX_ITEMS:
            _limit()
    for group in source.cluster_transforms:
        items += len(group.helix_ids) + len(group.domain_ids)
        if items > MAX_ITEMS:
            _limit()
    indexes = []
    for collection, kind in ((source.helices, "helix"), (source.strands, "strand"),
                             (source.cluster_transforms, "cluster")):
        index = {}
        for item in collection:
            identity = _identity(item.id)
            if identity in index:
                _reference_error(kind, identity, [kind + "_id"], ambiguous=True)
            index[identity] = item
        indexes.append(index)
    helices, strands, _ = indexes

    def helix_reference(identity, path):
        _identity(identity)
        if identity not in helices:
            _reference_error("helix", identity, path)

    for strand in source.strands:
        for index, domain in enumerate(strand.domains):
            helix_reference(domain.helix_id, ["strands", strand.id, "domains", index, "helix_id"])
    member_indexes = ({key: 1 for key in helices}, {key: [value] for key, value in strands.items()})
    for group in source.cluster_transforms:
        _check_members(source, group, indexes=member_indexes)
    for index, crossover in enumerate(source.crossovers):
        for name in ("half_a", "half_b"):
            helix_reference(getattr(crossover, name).helix_id, ["crossovers", index, name, "helix_id"])
    for index, ligation in enumerate(source.forced_ligations):
        for name in ("three_prime_helix_id", "five_prime_helix_id"):
            helix_reference(getattr(ligation, name), ["forced_ligations", index, name])
    try:
        require_valid_structure(source)
    except PartStructureError as exc:
        raise HTTPException(409, detail=exc.as_issue()) from exc


def repair_unassigned_groups():
    """Plan privately, then publish sequential native v2 inputs in one undo.

    Captured inputs exclude presentation, physical state and recovery payloads.
    Only the prepared grouping and new input rows are merged onto the original
    source after the exact origin check. Empty sources intentionally retain the
    empty default owner created by the existing v2 grouping contract.
    """
    from backend.core.cluster_components import ClusterComponentLimit, cluster_unassigned_components

    admission = capture_group_source("group_unassigned")
    captured = admission.captured
    _component_input(captured)
    try:
        planned = cluster_unassigned_components(captured, max_graph_work=MAX_COMPONENT_GRAPH_WORK)
    except ClusterComponentLimit as exc:
        raise HTTPException(409, detail={"code": "group_graph_limit", "message": str(exc),
            "maximum_graph_work": MAX_COMPONENT_GRAPH_WORK}) from exc
    groups = planned.cluster_transforms[len(captured.cluster_transforms):]
    if len(groups) > MAX_COMPONENT_GROUPS:
        raise HTTPException(409, detail={"code": "group_input_limit",
            "message": "Too many unassigned components for one group operation.",
            "maximum_groups": MAX_COMPONENT_GROUPS})
    prepared, entries = captured, []
    for group in groups:
        params = {"cluster": group.model_dump(mode="json"), "_proof_version": GROUP_CREATE_VERSION}
        _check_operation(params)
        try:
            prepared = build("cluster_create", prepared, params)
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "invalid_group_input", "message": str(exc)}) from exc
        entries.append(ClusterCreateLogEntry(
            proof_version=GROUP_CREATE_VERSION, cluster_snapshot=group,
            cluster_id=group.id, name=group.name, helix_ids=list(group.helix_ids),
            domain_ids=list(group.domain_ids),
        ))
    with state._lock:
        require_group_source_current(admission)
        if not entries:
            return admission.source, state.validate_design(admission.source)
        candidate = admission.source.copy_with(
            cluster_transforms=prepared.cluster_transforms,
            feature_log=[*admission.source.feature_log, *entries],
        )
        return _publish(admission.session, admission.source, admission.revision,
                        admission.identity, candidate)


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
