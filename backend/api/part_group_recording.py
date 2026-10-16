"""Record ordinary group creation from inputs under the document's state lock.

Grouping owns cluster membership directly, so it uses the shared pure overlay
builder and replacement transaction rather than topology reconciliation. This
does not infer a recipe root or validate an entire historical recipe.
"""

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api.part_replacement_transaction import publish_replacement
from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform, DomainRef
from backend.core.part_overlay_commands import build


def create_group(body):
    """Publish one group, authored row and undo step; ``log`` cannot bypass it."""
    with state._lock:
        state._require_compatibility_write("group_creation")
        session = state._session()
        source, revision, identity = session.design, session.revision, session.identity
        if source is None:
            raise HTTPException(404, detail="No active design.")
        state._assert_active_loadout_editable(source)
        # Earlier routes truncated only outer entries and could silently retain
        # unapplied children or an F0 future. Historical branching requires its
        # own input/history policy; ordinary creation must not guess that policy.
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise HTTPException(409, detail={
                "code": "historical_cursor",
                "message": "Return to the latest history position before creating a group.",
            })

        group = ClusterRigidTransform(
            name=body.name,
            helix_ids=list(body.helix_ids),
            domain_ids=[DomainRef.model_validate(item) for item in body.domain_ids],
        )
        grouped = build("cluster_create", source, {"cluster": group.model_dump(mode="json")})
        entry = ClusterCreateLogEntry(
            proof_version=1,
            cluster_snapshot=group,
            cluster_id=group.id,
            name=group.name,
            helix_ids=list(group.helix_ids),
            domain_ids=list(group.domain_ids),
        )
        candidate = grouped.copy_with(feature_log=[*source.feature_log, entry])
        report = state.validate_design(candidate)
        # This caller already owns the non-reentrant state lock. Reuse the
        # lock-owned transaction, with set_design's source/publication checks,
        # rather than reacquiring that lock through the public state facade.
        current = state._sessions.get(doc_context.get_current_doc())
        if (current is not session or current.identity != identity
                or current.design is not source or current.revision != revision):
            raise HTTPException(409, detail={
                "code": "source_changed",
                "message": "The document changed before group creation could be published.",
            })
        state._assert_active_loadout_editable(source, candidate)
        state._assert_photoproduct_dependencies(candidate)
        publish_replacement(session, candidate)
        return candidate, report
