"""Join bridges retain identity independently of document/history payloads."""

from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from threading import Event
from backend.api import part_verification_jobs as jobs


def verify_job(monkeypatch):
    """Join proof belongs on the bounded worker, not the 0.5 s sync shortcut."""
    completed = Event()
    run = jobs._run

    def finish(*args):
        try:
            run(*args)
        finally:
            completed.set()

    with monkeypatch.context() as patch:
        patch.setattr(jobs, "_run", finish)
        job_id = jobs.start()["job_id"]
        try:
            assert completed.wait(10), "Join proof worker did not finish"
            return jobs.inspect(job_id)["result"]
        finally:
            jobs.inspect(job_id, cancel=True)
            assert completed.wait(10)
            with jobs._lock:
                jobs._jobs.pop(job_id, None)


def test_join_from_native_root_and_parameter_regeneration(monkeypatch):
    from backend.api.routes_scaffold_routing import auto_scaffold_seamed_endpoint
    from backend.api.routes_clusters import _create_pattern
    from backend.api.pattern_features import LinearPatternBody
    from backend.api.routes_cluster_join import candidates, preview, apply
    from backend.core.cluster_join import ClusterJoinRequest

    token = set_current_doc("native-join-proof-test")
    try:
        crud.create_bundle(
            crud.BundleRequest(
                cells=[[r, c] for r in range(3) for c in range(2)],
                length_bp=96,
                lattice_type="SQUARE",
            )
        )
        auto_scaffold_seamed_endpoint()
        cid = state.get_or_404().cluster_transforms[0].id
        _create_pattern(
            "linear-pattern",
            LinearPatternBody(cluster_ids=[cid], instances=2, spacing=40),
        )
        clusters = state.get_or_404().cluster_transforms
        sites = candidates()["sites"]
        first = next(
            s
            for s in sites
            if s["cluster_id"] == clusters[0].id and s["kind"] == "side"
        )
        second = next(
            s for s in sites if s["cluster_id"] == clusters[1].id and s["kind"] == "end"
        )
        body = ClusterJoinRequest(
            first=dict(cluster_id=first["cluster_id"], port_id=first["id"]),
            second=dict(cluster_id=second["cluster_id"], port_id=second["id"]),
            expected_design_id=state.get_or_404().id,
            expected_revision=state.revision(),
        )
        plan = preview(body)
        assert plan["valid"], plan
        apply(body.model_copy(update={"preview_token": plan["token"]}))
        result = verify_job(monkeypatch)
        assert result["status"] == "verified", result.get("issues", result)
        ids = [h.id for h in state.get_or_404().helices]
        crud.edit_feature(3, crud.EditFeatureBody(params={"gap_nm": 0.9}))
        assert [h.id for h in state.get_or_404().helices] == ids
        result = verify_job(monkeypatch)
        assert result["status"] == "verified", result.get("issues", result)
    finally:
        state.close_session()
        reset_current_doc(token)
