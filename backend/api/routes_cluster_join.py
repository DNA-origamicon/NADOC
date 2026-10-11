"""Atomic native cluster attachment previews and directed scaffold joins."""

from fastapi import APIRouter, HTTPException
from backend.api import state
from backend.core.cluster_join import (
    ClusterJoinRequest,
    cluster_join_candidates,
    propose_cluster_join,
    join_preview_token,
)
from backend.core.cluster_reconcile import MutationReport

router = APIRouter()


def _guard(design, revision, body):
    if design.id != body.expected_design_id:
        raise HTTPException(
            409, detail="Active design changed; select attachment sites again."
        )
    if revision != body.expected_revision:
        raise HTTPException(409, detail="Design changed; preview the join again.")


@router.get("/design/cluster-join/candidates")
def candidates(cluster_id: str | None = None):
    design, revision = state.copy_for_persist()
    if design is None:
        raise HTTPException(404, detail="No active design.")
    return {**cluster_join_candidates(design, cluster_id), "revision": revision}


@router.post("/design/cluster-join/preview")
def preview(body: ClusterJoinRequest):
    design, revision = state.copy_for_persist()
    if design is None:
        raise HTTPException(404, detail="No active design.")
    _guard(design, revision, body)
    try:
        _, report = propose_cluster_join(design, body)
        return report
    except ValueError as exc:
        return dict(
            valid=False,
            errors=[str(exc)],
            warnings=[],
            design_id=design.id,
            revision=revision,
        )


@router.post("/design/cluster-join/apply")
def apply(body: ClusterJoinRequest):
    from backend.api.crud import _design_response_with_geometry

    report = None

    def build(design):
        nonlocal report
        _guard(design, body.expected_revision, body)
        if not body.preview_token or body.preview_token != join_preview_token(
            design, body
        ):
            raise HTTPException(
                409, detail="Join preview is stale or missing; preview again."
            )
        try:
            result, report = propose_cluster_join(design, body)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return result, MutationReport(
            new_helix_origins={b["helix_id"]: None for b in report["bridges"]}
        )

    updated, validation, entry = state.mutate_with_feature_log(
        op_kind="cluster-join",
        label="Join clusters",
        params=body.model_dump(mode="json"),
        fn=build,
        expected_revision=body.expected_revision,
    )
    payload = _design_response_with_geometry(
        updated, validation, preserve_feature_log_id=entry.id
    )
    payload["join"] = report
    return payload
