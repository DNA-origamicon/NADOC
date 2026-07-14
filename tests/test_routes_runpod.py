"""RunPod API routes — connect / status / pods / estimate.

The endpoint that earns its keep is ``GET /runpod/pods``: **anything it returns is
billing right now.** It is the leak check, and the UI surfaces it with a terminate
button for exactly that reason.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import routes_runpod
from backend.api.main import app

VOLUME = "77pnhye88p"


@pytest.fixture(scope="module")
def client():
    # Module-scoped: `with TestClient(app)` runs the app's whole lifespan (workspace
    # scan, session-cache restore, MD-supervisor task), ~0.45 s a go — paying that
    # once per test made this file 12 s.  Isolation never came from the fresh app
    # anyway: it comes from _reset_session below, which still runs per test.
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_session():
    """No RunPod key/volume leaks between tests — a stale key is a billing pod."""
    yield
    routes_runpod._SESSION.client = None  # noqa: SLF001
    routes_runpod._SESSION.network_volume_id = None  # noqa: SLF001


def _pod(pid="p1", status="RUNNING"):
    return {"id": pid, "desiredStatus": status, "publicIp": "1.2.3.4",
            "portMappings": {"22": 10341}, "costPerHr": 0.34}


def _mock_runpod(monkeypatch, handler):
    """Make RunpodClient talk to a MockTransport instead of the internet."""
    real_init = routes_runpod.RunpodClient.__init__

    def patched(self, api_key, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        real_init(self, api_key, **kw)

    monkeypatch.setattr(routes_runpod.RunpodClient, "__init__", patched)


class TestEstimate:
    """Pure sizing — no key, no network, no pod."""

    def test_small_system_gets_the_cheapest_card_resident(self, client):
        """RTX PRO 4500: 32 GB for the same $0.34/hr as a 24 GB 4090, and the only card in
        that tier RunPod reports as HIGH stock (the 4090 is perpetually "Low", which is
        what kept producing 500 "no instances currently available")."""
        r = client.post("/api/runpod/estimate", json={"n_atoms": 225_504})
        assert r.status_code == 200
        body = r.json()
        assert body["feasible"] is True
        assert body["gpu"]["label"] == "RTX PRO 4500"
        assert body["gpu"]["vram_mb"] > 24_564
        assert body["gpu"]["usd_per_hour"] == 0.34
        assert body["gpu_resident"] is True

    def test_voltroncore_sized_from_the_measured_model(self, client):
        """5.66M atoms measured 17,678 MB resident on a real 4090."""
        body = client.post("/api/runpod/estimate", json={"n_atoms": 5_656_632}).json()
        assert body["feasible"] is True
        assert body["required_vram_mb"] == pytest.approx(18_571, rel=0.10)

    def test_impossible_system_is_infeasible_and_says_why(self, client):
        body = client.post("/api/runpod/estimate", json={"n_atoms": 200_000_000}).json()
        assert body["feasible"] is False
        assert body["gpu"] is None
        assert "carve" in body["reason"].lower() or "gbis" in body["reason"].lower()

    def test_rejects_a_nonsense_atom_count(self, client):
        assert client.post("/api/runpod/estimate", json={"n_atoms": 0}).status_code == 422

    def test_gpu_types_are_listed_cheapest_first(self, client):
        gpus = client.get("/api/runpod/gpu-types").json()["gpus"]
        prices = [g["usd_per_hour"] for g in gpus]
        assert prices == sorted(prices)


class TestConnect:
    def test_status_is_disconnected_before_any_key(self, client):
        body = client.get("/api/runpod/status").json()
        assert body["connected"] is False
        assert body["live_pods"] == 0

    def test_connect_verifies_the_key_and_reports_live_pods(self, client, monkeypatch):
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[_pod()]))
        r = client.post("/api/runpod/connect",
                        json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME})
        assert r.status_code == 200
        body = r.json()
        assert body["connected"] is True
        assert body["network_volume_id"] == VOLUME
        assert body["live_pods"] == 1

    def test_a_bad_key_is_a_400_not_a_500(self, client, monkeypatch):
        _mock_runpod(monkeypatch, lambda req: httpx.Response(401, text="nope"))
        r = client.post("/api/runpod/connect",
                        json={"api_key": "rp_bogus1234", "network_volume_id": VOLUME})
        assert r.status_code == 400
        assert "API key" in r.json()["detail"]

    def test_endpoints_that_need_a_key_refuse_without_one(self, client):
        assert client.get("/api/runpod/pods").status_code == 400
        assert client.post("/api/runpod/pods/p1/terminate").status_code == 400

    def test_disconnect_clears_the_key(self, client, monkeypatch):
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[]))
        client.post("/api/runpod/connect",
                    json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME})
        assert client.post("/api/runpod/disconnect").json()["connected"] is False
        assert client.get("/api/runpod/pods").status_code == 400


class TestPodLeakCheck:
    def test_lists_live_pods_with_their_hourly_cost(self, client, monkeypatch):
        """Anything here is BILLING. The cost is shown so a forgotten pod is obvious."""
        _mock_runpod(monkeypatch, lambda req: httpx.Response(
            200, json=[_pod("p1"), _pod("p2")]))
        client.post("/api/runpod/connect",
                    json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME})
        pods = client.get("/api/runpod/pods").json()["pods"]
        assert [p["id"] for p in pods] == ["p1", "p2"]
        assert pods[0]["cost_per_hr"] == 0.34
        assert pods[0]["ssh"] == "1.2.3.4:10341"

    def test_terminate_is_idempotent(self, client, monkeypatch):
        """Called from cleanup paths — an exception here leaks the pod it was killing."""
        def handler(req):
            if req.method == "DELETE":
                return httpx.Response(404, text="gone")
            return httpx.Response(200, json=[])

        _mock_runpod(monkeypatch, handler)
        client.post("/api/runpod/connect",
                    json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME})
        r = client.post("/api/runpod/pods/p1/terminate")
        assert r.status_code == 200
        assert r.json()["ok"] is True
