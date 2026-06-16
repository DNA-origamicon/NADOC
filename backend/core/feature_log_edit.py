"""Pure model-transform core for the feature-log ``edit_feature`` endpoint.

The api handler in ``crud.py`` validates a feature-log edit request, replays or
rewrites the target entry, and returns the standard fast-path response. The
*model transform* underneath — rewriting the target log entry and re-deriving
the affected overlay (cluster_transforms for a cluster_op edit, the deformation
set for a deformation edit) from the edited log — is pure topology/model logic
with no HTTP, no ``design_state``, no response formatting. That pure core lives
here, directly unit-testable.

The api layer keeps the thin shell: translate :class:`FeatureEditError` to the
right ``HTTPException`` status, run the api-bound deformed-continuation re-bake
(which needs ``design_state``-backed snapshot decode + live builders, so it
cannot move to core), commit via ``design_state.set_design``, validate, and
format the response.

``backend/core`` must not import ``backend/api`` (L4); this module imports only
core models + the core deformation helpers.
"""

from __future__ import annotations

from backend.core.deformation import (
    helices_crossing_planes,
    parse_deformation_params,
    resolve_cluster_scope,
)
from backend.core.models import (
    ClusterOpLogEntry,
    DeformationLogEntry,
    Design,
)


class FeatureEditError(ValueError):
    """Raised when a feature-log edit request is invalid.

    ``status`` carries the HTTP code the api layer should translate to
    (400 bad params, 404 missing target, 409 unreplayable). Keeping the code on
    the exception lets the pure core stay HTTP-free while the api shim preserves
    the exact status each branch returned before extraction.
    """

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def edit_cluster_op_entry(
    design: Design,
    index: int,
    entry: ClusterOpLogEntry,
    params: dict,
) -> Design:
    """Return a new ``Design`` with the cluster_op at ``feature_log[index]``
    re-posed to the absolute transform in ``params`` (``translation`` /
    ``rotation`` / ``pivot``).

    Updates the log entry's stored fields (so seek-replay reproduces the new
    pose at that step) and recomputes the live ``ClusterRigidTransform`` in
    ``design.cluster_transforms``.

    ANY cluster_op of a given cluster is editable, not just the latest. Each
    cluster_op records the cluster's absolute pose AFTER that step, and the
    cluster's live transform is the LAST op for that cluster — so editing an
    earlier op only rewrites that step's seek/scrub frame, while the latest op
    keeps defining the final pose. (manual_validation_debt MV-1 follow-on.)

    Raises :class:`FeatureEditError` (400) on a missing transform field, (404)
    if the cluster no longer exists.
    """
    p = params or {}
    for f in ('translation', 'rotation', 'pivot'):
        if f not in p:
            raise FeatureEditError(f"cluster_op edit requires '{f}'.", status=400)

    cts = list(design.cluster_transforms)
    ct_idx = next((i for i, c in enumerate(cts) if c.id == entry.cluster_id), None)
    if ct_idx is None:
        raise FeatureEditError(
            f"Cluster {entry.cluster_id!r} no longer exists.", status=404
        )

    new_log = list(design.feature_log)
    new_log[index] = entry.model_copy(update={
        'translation': list(p['translation']),
        'rotation':    list(p['rotation']),
        'pivot':       list(p['pivot']),
    })

    # Live pose = the LAST cluster_op for this cluster across the full (edited)
    # log. That's this op when it's the latest, else a later op that must keep
    # winning — so editing an earlier op leaves the final pose untouched.
    last_op = next(
        (e for e in reversed(new_log)
         if e.feature_type == 'cluster_op' and e.cluster_id == entry.cluster_id),
        None,
    )
    if last_op is not None:
        cts[ct_idx] = cts[ct_idx].model_copy(update={
            'translation': list(last_op.translation),
            'rotation':    list(last_op.rotation),
            'pivot':       list(last_op.pivot),
        })

    return design.copy_with(cluster_transforms=cts, feature_log=new_log)


def edit_deformation_entry(
    design: Design,
    index: int,
    entry: DeformationLogEntry,
    params: dict,
) -> Design:
    """Return a new ``Design`` with the deformation at ``feature_log[index]``
    updated to the params in ``params`` (same fields as ``AddDeformationBody``:
    ``type`` / ``plane_a_bp`` / ``plane_b_bp`` / ``params`` + optional
    ``affected_helix_ids`` / ``cluster_ids``).

    Refreshes the target entry's ``op_snapshot`` and rebuilds
    ``design.deformations`` from the LOG (the source of truth) rather than
    mutating the live list — which restores ops an edit-preview seek rolled out,
    drops any transient ``preview=true`` op, and is correct regardless of the
    current cursor. Deformations are geometric-only, so the live topology is
    unaffected.

    The caller is responsible for the api-bound deformed-continuation re-bake
    (``_rebuild_deformed_continuations``) AFTER this returns — it needs snapshot
    decode + live builders, which cannot live in core.

    Raises :class:`FeatureEditError` (400) on bad params, (409) if the entry has
    no stored op snapshot to edit.
    """
    p = params or {}
    op_type = p.get('type', entry.op_snapshot.type if entry.op_snapshot else None)
    if op_type not in ('twist', 'bend'):
        raise FeatureEditError(
            f"deformation 'type' must be 'twist' or 'bend' (got {op_type!r}).",
            status=400,
        )
    if 'plane_a_bp' not in p or 'plane_b_bp' not in p:
        raise FeatureEditError(
            "deformation edit requires plane_a_bp and plane_b_bp.", status=400
        )
    if 'params' not in p:
        raise FeatureEditError("deformation edit requires nested params.", status=400)
    if entry.op_snapshot is None:
        raise FeatureEditError(
            f"Deformation entry {index} has no stored op snapshot (evicted/broken); "
            "revert to this point and re-apply instead of editing.",
            status=409,
        )

    try:
        new_params = parse_deformation_params(op_type, p['params'])
    except ValueError as e:
        raise FeatureEditError(str(e), status=400) from e

    helix_ids = p.get('affected_helix_ids') or helices_crossing_planes(
        design, p['plane_a_bp'], p['plane_b_bp']
    )
    resolved = resolve_cluster_scope(design, p.get('cluster_ids') or [], helix_ids)
    helix_ids = resolved["helix_ids"]
    cluster_ids = resolved["cluster_ids"]

    # Build the edited op from the entry's stored snapshot (preserves the op id).
    new_op = entry.op_snapshot.model_copy(update={
        'type':               op_type,
        'plane_a_bp':         p['plane_a_bp'],
        'plane_b_bp':         p['plane_b_bp'],
        'affected_helix_ids': helix_ids,
        'cluster_ids':        cluster_ids,
        'params':             new_params,
    })

    # Refresh the entry's op_snapshot so seek replays match the new params.
    new_log = list(design.feature_log)
    new_log[index] = entry.model_copy(update={'op_snapshot': new_op})

    # Rebuild the full deformation set from the log (source of truth). Drops any
    # transient preview op and restores ops the edit-preview seek rolled out.
    rebuilt_ops = [
        e.op_snapshot for e in new_log
        if getattr(e, 'feature_type', None) == 'deformation' and e.op_snapshot is not None
    ]

    return design.copy_with(
        deformations=rebuilt_ops, feature_log=new_log, feature_log_cursor=-1,
    )
