"""Measured work units, request/thread isolation, and bounded progress lifecycle."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api.doc_context import DocContextMiddleware
from backend.api.surface_progress import SurfaceProgressMiddleware, router
from backend.core.surface_progress import report, reporting, strand_scope


def test_core_reports_actual_tile_and_strand_units_without_leaking_context():
    events = []
    with reporting(events.append):
        with strand_scope(2, 5):
            report("Extracting surface tiles", 3, 7)
        report("Packing surface")
    report("not tracked")
    assert events == [
        {
            "stage": "Extracting surface tiles",
            "done": 3,
            "total": 7,
            "strand": {"index": 2, "total": 5},
        },
        {"stage": "Packing surface", "done": None, "total": None, "strand": None},
    ]


def test_live_progress_is_doc_scoped_and_visible_while_worker_is_computing():
    app = FastAPI()
    app.add_middleware(SurfaceProgressMiddleware)
    app.add_middleware(DocContextMiddleware)
    app.include_router(router)
    started, release = Event(), Event()

    @app.get("/test-surface")
    def build():
        report("Extracting surface tiles", 2, 9)
        started.set()
        assert release.wait(3)
        return {"ok": True}

    headers = {
        "X-NADOC-Doc": "surface-progress-test",
        "X-NADOC-Surface-Progress": "request-12345678",
    }
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        pending = pool.submit(client.get, "/test-surface", headers=headers)
        try:
            assert started.wait(3)
            value = client.get(
                "/surface-progress/request-12345678",
                headers={"X-NADOC-Doc": "surface-progress-test"},
            ).json()
            assert value["state"] == "running"
            assert (value["done"], value["total"]) == (2, 9)
            assert (
                client.get(
                    "/surface-progress/request-12345678",
                    headers={"X-NADOC-Doc": "other-doc"},
                ).status_code
                == 404
            )
            assert client.get("/test-surface", headers=headers).status_code == 409
        finally:
            release.set()
        assert pending.result().status_code == 200
        value = client.get(
            "/surface-progress/request-12345678",
            headers={"X-NADOC-Doc": "surface-progress-test"},
        ).json()
        assert value["state"] == "complete"


def test_error_and_expiry_are_not_reported_as_success(monkeypatch):
    from backend.api import surface_progress as p

    app = FastAPI()
    app.add_middleware(SurfaceProgressMiddleware)
    app.add_middleware(DocContextMiddleware)
    app.include_router(router)

    @app.get("/error-surface")
    def fail():
        raise RuntimeError("test failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert (
            client.get(
                "/error-surface",
                headers={"X-NADOC-Surface-Progress": "failure-12345678"},
            ).status_code
            == 500
        )
        assert (
            client.get("/surface-progress/failure-12345678").json()["state"] == "error"
        )
        now = p.monotonic()
        monkeypatch.setattr(p, "monotonic", lambda: now + p._TTL + 1)
        assert client.get("/surface-progress/failure-12345678").status_code == 404
