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
    routes_runpod._SESSION.api_key = None  # noqa: SLF001 — else /balance hits GraphQL for real


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
        """The estimate must quote the SECURE price we actually pay ($0.69 for a 4090).

        It used to quote $0.34 — the COMMUNITY price — while Community cloud is excluded
        in code (no card in EU-RO-1). Every cost this endpoint reported was therefore
        ~2.2x low, which is how an $11 overnight ladder is mistaken for a $5 one.
        """
        r = client.post("/api/runpod/estimate", json={"n_atoms": 225_504})
        assert r.status_code == 200
        body = r.json()
        assert body["feasible"] is True
        assert body["gpu"]["label"] == "RTX 4090"
        assert body["gpu"]["usd_per_hour"] == 0.69
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


class TestSetupWizard:
    """The first-time-setup wizard connects the key BEFORE a volume is chosen (that is
    what unlocks the balance + volume-list lookups), then reconnects with the volume."""

    def test_connect_without_a_volume_is_allowed(self, client, monkeypatch):
        """Key-first: the wizard verifies the key before the user has picked a volume."""
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[]))
        r = client.post("/api/runpod/connect", json={"api_key": "rp_abcdefgh"})
        assert r.status_code == 200
        body = r.json()
        assert body["connected"] is True
        assert body["network_volume_id"] is None

    def test_a_key_only_reverify_keeps_the_chosen_volume(self, client, monkeypatch):
        """Reconnecting to refresh status must not wipe a volume the user already set."""
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[]))
        client.post("/api/runpod/connect",
                    json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME})
        r = client.post("/api/runpod/connect", json={"api_key": "rp_abcdefgh"})
        assert r.json()["network_volume_id"] == VOLUME

    def test_volumes_list_needs_a_key(self, client):
        assert client.get("/api/runpod/volumes").status_code == 400

    def test_volumes_are_listed_for_the_dropdown(self, client, monkeypatch):
        def handler(req):
            if req.url.path.endswith("/networkvolumes"):
                return httpx.Response(200, json=[
                    {"id": VOLUME, "name": "namd", "size": 60, "dataCenterId": "EU-RO-1"},
                ])
            return httpx.Response(200, json=[])

        _mock_runpod(monkeypatch, handler)
        client.post("/api/runpod/connect", json={"api_key": "rp_abcdefgh"})
        vols = client.get("/api/runpod/volumes").json()["volumes"]
        assert vols[0]["id"] == VOLUME
        assert vols[0]["size_gb"] == 60

    def test_balance_is_unavailable_without_a_key(self, client):
        body = client.get("/api/runpod/balance").json()
        assert body["available"] is False
        assert "API key" in body["reason"]

    def test_balance_is_shown_once_connected(self, client, monkeypatch):
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[]))
        client.post("/api/runpod/connect", json={"api_key": "rp_abcdefgh"})

        async def fake_balance(api_key, **kw):
            return {"available": True, "balance": 207.0, "spend_per_hr": 0.0}

        monkeypatch.setattr(routes_runpod.runpod_preflight, "fetch_balance", fake_balance)
        body = client.get("/api/runpod/balance").json()
        assert body["available"] is True
        assert body["balance"] == 207.0

    def test_ssh_public_key_reports_present_when_it_exists(self, client, monkeypatch, tmp_path):
        home = tmp_path
        (home / ".ssh").mkdir()
        (home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAAC3Nz user@host\n")
        monkeypatch.setattr(routes_runpod.Path, "home", staticmethod(lambda: home))
        body = client.get("/api/runpod/ssh-public-key").json()
        assert body["present"] is True
        assert body["public_key"].startswith("ssh-ed25519")

    def test_ssh_public_key_absent_is_not_an_error(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(routes_runpod.Path, "home", staticmethod(lambda: tmp_path))
        body = client.get("/api/runpod/ssh-public-key").json()
        assert body["present"] is False
        assert body["public_key"] is None


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


class TestGpuOptions:
    """The cluster-card GPU picker feed: ranked cards with price, relax time, and cost."""

    def test_lists_cards_with_price_time_cost(self, client):
        r = client.post("/api/runpod/gpu-options", json={"n_atoms": 1_310_154})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] and d["gpus"], d
        assert d["n_atoms"] == 1_310_154 and d["relax_ns"] == 19.2
        row = d["gpus"][0]
        for k in ("label", "usd_per_hour", "vram_gb", "available", "ns_day",
                  "relax_hours", "est_cost"):
            assert k in row, f"missing {k}"
        assert row["relax_hours"] > 0 and row["est_cost"] > 0

    def test_not_connected_prices_are_indicative(self, client):
        # no session -> stock unknown -> available None + an indicative-price note
        d = client.post("/api/runpod/gpu-options", json={"n_atoms": 1_000_000}).json()
        assert d["connected"] is False
        assert d["note"] and "indicative" in d["note"].lower()
        assert all(row["available"] is None for row in d["gpus"])

    def test_no_size_returns_200_shape(self, client):
        # no n_atoms: sizes the active design if any, else soft-fails — never 500
        r = client.post("/api/runpod/gpu-options", json={})
        assert r.status_code == 200
        assert "gpus" in r.json()
