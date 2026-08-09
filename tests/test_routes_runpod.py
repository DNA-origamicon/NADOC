"""RunPod API routes — connect / status / pods / estimate.

The endpoint that earns its keep is ``GET /runpod/pods``: **anything it returns is
billing right now.** It is the leak check, and the UI surfaces it with a terminate
button for exactly that reason.
"""

from __future__ import annotations

import asyncio

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
    routes_runpod._SESSION.key_source = "none"  # noqa: SLF001
    routes_runpod._SESSION.connection_error = None  # noqa: SLF001


def _pod(pid="p1", status="RUNNING"):
    return {
        "id": pid,
        "desiredStatus": status,
        "publicIp": "1.2.3.4",
        "portMappings": {"22": 10341},
        "costPerHr": 0.34,
    }


def _mock_runpod(monkeypatch, handler):
    """Make RunpodClient talk to a MockTransport instead of the internet."""
    real_init = routes_runpod.RunpodClient.__init__

    def patched(self, api_key, **kw):
        # Route tests use fake pod ids; never write them into the real workspace audit.
        kw.pop("audit_dir", None)
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
        assert (
            client.post("/api/runpod/estimate", json={"n_atoms": 0}).status_code == 422
        )

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
        r = client.post(
            "/api/runpod/connect",
            json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["connected"] is True
        assert body["network_volume_id"] == VOLUME
        assert body["live_pods"] == 1

    def test_a_bad_key_is_a_400_not_a_500(self, client, monkeypatch):
        _mock_runpod(monkeypatch, lambda req: httpx.Response(401, text="nope"))
        r = client.post(
            "/api/runpod/connect",
            json={"api_key": "rp_bogus1234", "network_volume_id": VOLUME},
        )
        assert r.status_code == 400
        assert "API key" in r.json()["detail"]

    def test_endpoints_that_need_a_key_refuse_without_one(self, client):
        assert client.get("/api/runpod/pods").status_code == 400
        assert client.post("/api/runpod/pods/p1/terminate").status_code == 400

    def test_disconnect_clears_the_key(self, client, monkeypatch):
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[]))
        client.post(
            "/api/runpod/connect",
            json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME},
        )
        assert client.post("/api/runpod/disconnect").json()["connected"] is False
        assert client.get("/api/runpod/pods").status_code == 400

    def test_disconnect_does_not_close_a_client_used_by_a_running_job(
        self, monkeypatch
    ):
        class Client:
            closed = False

            async def aclose(self):
                self.closed = True

        old = Client()
        routes_runpod._SESSION.client = old  # noqa: SLF001
        from backend.core import runpod_supervisor

        monkeypatch.setattr(runpod_supervisor, "running_job_ids", lambda: ["job1"])
        asyncio.run(routes_runpod._SESSION.disconnect())  # noqa: SLF001
        assert old.closed is False
        assert routes_runpod._SESSION.client is None  # noqa: SLF001


class TestVanishedPodReconciliation:
    def _job(self, tmp_path):
        from backend.core.md_job import MdStatus, new_job

        job = new_job("d", "equilibrium_aware_namd", "d", "package/d")
        job.execution_target = "runpod"
        job.status = MdStatus.running
        job.runpod_pod_id = "gone-pod"
        job.save(tmp_path)
        return job

    def test_audited_external_disappearance_pauses_without_spending_again(
        self, tmp_path, monkeypatch
    ):
        from backend.api import routes_md
        from backend.core.md_job import MdJob, MdStatus
        from backend.core.runpod_api import RunpodClient

        monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
        job = self._job(tmp_path)
        client = RunpodClient(
            "key",
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[])),
            audit_dir=tmp_path,
        )
        client.record_lifecycle("pod_created", pod_id="gone-pod", job_id=job.job_id)

        assert routes_runpod._reconcile_vanished_jobs(client, []) == [job.job_id]  # noqa: SLF001
        saved = MdJob.load(job.job_id, tmp_path)
        assert saved.status == MdStatus.paused
        assert saved.resumable is True
        assert saved.runpod_pod_id is None
        assert saved.runpod_last_pod_id == "gone-pod"
        assert "No NADOC termination was recorded" in (saved.error or "")
        assert not any(
            e["event"] == "terminate_requested"
            for e in client.lifecycle_events("gone-pod")
        )
        asyncio.run(client.aclose())

    def test_local_delete_is_attributed_to_its_recorded_reason(
        self, tmp_path, monkeypatch
    ):
        from backend.api import routes_md
        from backend.core.md_job import MdJob
        from backend.core.runpod_api import RunpodClient

        monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
        job = self._job(tmp_path)
        client = RunpodClient(
            "key",
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[])),
            audit_dir=tmp_path,
        )
        client.record_lifecycle("pod_created", pod_id="gone-pod", job_id=job.job_id)
        client.record_lifecycle(
            "terminate_requested",
            pod_id="gone-pod",
            job_id=job.job_id,
            reason="explicit_job_stop",
        )

        routes_runpod._reconcile_vanished_jobs(client, [])  # noqa: SLF001
        assert "explicit_job_stop" in (MdJob.load(job.job_id, tmp_path).error or "")
        asyncio.run(client.aclose())


class TestAutoconnect:
    """Startup resolves the stored key itself.

    The point is not convenience. Holding the key in memory only meant that after any
    restart NADOC could not terminate a pod it was still being billed for — connecting
    on boot is what lets the orphan reaper run without a human re-pasting a key.
    """

    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        # conftest sets this to "0" so the rest of the suite never touches the network.
        monkeypatch.setenv("NADOC_RUNPOD_AUTOCONNECT", "1")
        monkeypatch.delenv("RUNPOD_NETWORK_VOLUME_ID", raising=False)

    def _key_file(self, monkeypatch, tmp_path, text="rpa_stored1234"):
        p = tmp_path / ".runpod_key"
        p.write_text(text)
        monkeypatch.setattr(routes_runpod.runpod_api, "KEY_FILE", p)
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
        return p

    def test_connects_from_the_key_file_with_no_human(
        self, client, monkeypatch, tmp_path
    ):
        self._key_file(monkeypatch, tmp_path)
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[_pod()]))

        body = asyncio.run(routes_runpod.autoconnect())
        assert body["connected"] is True
        assert body["key_source"] == "file"
        assert client.get("/api/runpod/status").json()["connected"] is True

    def test_the_env_var_wins_over_the_file(self, client, monkeypatch, tmp_path):
        self._key_file(monkeypatch, tmp_path)
        monkeypatch.setenv("RUNPOD_API_KEY", "rpa_fromenv1234")
        seen: list[str] = []

        def handler(req):
            seen.append(req.headers.get("authorization", ""))
            return httpx.Response(200, json=[])

        _mock_runpod(monkeypatch, handler)
        body = asyncio.run(routes_runpod.autoconnect())
        assert body["key_source"] == "env"
        assert any("rpa_fromenv1234" in h for h in seen)

    def test_no_stored_key_is_silence_not_a_crash(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(
            routes_runpod.runpod_api, "KEY_FILE", tmp_path / "nothing-here"
        )
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        assert asyncio.run(routes_runpod.autoconnect()) is None
        assert client.get("/api/runpod/status").json()["connected"] is False

    def test_a_rejected_key_leaves_the_server_usable(
        self, client, monkeypatch, tmp_path
    ):
        """A revoked key must not take the whole backend down on boot."""
        self._key_file(monkeypatch, tmp_path)
        _mock_runpod(monkeypatch, lambda req: httpx.Response(401, text="nope"))

        assert asyncio.run(routes_runpod.autoconnect()) is None
        assert client.get("/api/runpod/status").json()["connected"] is False

    def test_the_opt_out_env_var_is_honoured(self, client, monkeypatch, tmp_path):
        self._key_file(monkeypatch, tmp_path)
        monkeypatch.setenv("NADOC_RUNPOD_AUTOCONNECT", "0")

        assert asyncio.run(routes_runpod.autoconnect()) is None

    def test_adopts_the_volume_when_the_account_has_exactly_one(
        self, client, monkeypatch, tmp_path
    ):
        """Otherwise a self-connected session still fails the pre-flight volume gate."""
        self._key_file(monkeypatch, tmp_path)

        def handler(req):
            if req.url.path.endswith("/networkvolumes"):
                return httpx.Response(
                    200, json=[{"id": VOLUME, "name": "namd", "size": 60}]
                )
            return httpx.Response(200, json=[])

        _mock_runpod(monkeypatch, handler)
        body = asyncio.run(routes_runpod.autoconnect())
        assert body["network_volume_id"] == VOLUME

    def test_two_volumes_are_left_for_the_user_to_pick(
        self, client, monkeypatch, tmp_path
    ):
        """Guessing between disks could stage a job onto the wrong one."""
        self._key_file(monkeypatch, tmp_path)

        def handler(req):
            if req.url.path.endswith("/networkvolumes"):
                return httpx.Response(
                    200,
                    json=[
                        {"id": VOLUME, "name": "namd", "size": 60},
                        {"id": "other99", "name": "scratch", "size": 20},
                    ],
                )
            return httpx.Response(200, json=[])

        _mock_runpod(monkeypatch, handler)
        body = asyncio.run(routes_runpod.autoconnect())
        assert body["network_volume_id"] is None

    def test_a_pinned_volume_env_var_wins(self, client, monkeypatch, tmp_path):
        self._key_file(monkeypatch, tmp_path)
        monkeypatch.setenv("RUNPOD_NETWORK_VOLUME_ID", "pinned42")
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[]))

        body = asyncio.run(routes_runpod.autoconnect())
        assert body["network_volume_id"] == "pinned42"

    def test_a_pasted_key_overrides_the_stored_one(self, client, monkeypatch, tmp_path):
        """Using a second account must not require editing files."""
        self._key_file(monkeypatch, tmp_path)
        _mock_runpod(monkeypatch, lambda req: httpx.Response(200, json=[]))
        asyncio.run(routes_runpod.autoconnect())

        r = client.post("/api/runpod/connect", json={"api_key": "rp_pasted1234"})
        assert r.json()["key_source"] == "manual"
        assert routes_runpod._SESSION.api_key == "rp_pasted1234"  # noqa: SLF001


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
        client.post(
            "/api/runpod/connect",
            json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME},
        )
        r = client.post("/api/runpod/connect", json={"api_key": "rp_abcdefgh"})
        assert r.json()["network_volume_id"] == VOLUME

    def test_volumes_list_needs_a_key(self, client):
        assert client.get("/api/runpod/volumes").status_code == 400

    def test_volumes_are_listed_for_the_dropdown(self, client, monkeypatch):
        def handler(req):
            if req.url.path.endswith("/networkvolumes"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": VOLUME,
                            "name": "namd",
                            "size": 60,
                            "dataCenterId": "EU-RO-1",
                        },
                    ],
                )
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

        monkeypatch.setattr(
            routes_runpod.runpod_preflight, "fetch_balance", fake_balance
        )
        body = client.get("/api/runpod/balance").json()
        assert body["available"] is True
        assert body["balance"] == 207.0

    def test_ssh_public_key_reports_present_when_it_exists(
        self, client, monkeypatch, tmp_path
    ):
        home = tmp_path
        (home / ".ssh").mkdir()
        (home / ".ssh" / "id_ed25519.pub").write_text(
            "ssh-ed25519 AAAAC3Nz user@host\n"
        )
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
        _mock_runpod(
            monkeypatch, lambda req: httpx.Response(200, json=[_pod("p1"), _pod("p2")])
        )
        client.post(
            "/api/runpod/connect",
            json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME},
        )
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
        client.post(
            "/api/runpod/connect",
            json={"api_key": "rp_abcdefgh", "network_volume_id": VOLUME},
        )
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
        for k in (
            "label",
            "usd_per_hour",
            "vram_gb",
            "available",
            "ns_day",
            "relax_hours",
            "est_cost",
        ):
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


class TestSetVolume:
    """The wizard's volume picker.

    It cannot re-POST ``/connect`` the way the setup modal does: the modal still holds the API
    key in its own closure, and the wizard must never hold it at all.
    """

    def test_sets_the_session_volume_without_an_api_key(self, client, monkeypatch):
        _mock_runpod(monkeypatch, lambda r: httpx.Response(200, json=[]))
        client.post("/api/runpod/connect", json={"api_key": "k" * 12})
        r = client.post("/api/runpod/volume", json={"network_volume_id": "abc123"})
        assert r.status_code == 200
        assert r.json()["network_volume_id"] == "abc123"
        assert routes_runpod._SESSION.network_volume_id == "abc123"  # noqa: SLF001

    def test_refuses_when_not_connected(self, client):
        r = client.post("/api/runpod/volume", json={"network_volume_id": "abc123"})
        assert r.status_code == 400


class TestJobPreview:
    """The Job Wizard's feed: a WHOLE plan costed — relax + production + storage + budget.

    Distinct from ``/gpu-options`` in the one way that matters to the wizard: the numbers move
    when the run being designed moves.
    """

    BODY = {
        "n_atoms": 1_310_154,
        "relax_ns": 19.2,
        "production_ns": 50.0,
        "relax_timestep_fs": 2.0,
        "production_timestep_fs": 4.0,
    }

    def test_costs_relax_and_production_separately(self, client):
        d = client.post("/api/runpod/job-preview", json=self.BODY).json()
        assert d["sized"] is True and d["gpus"]
        row = d["gpus"][0]
        for k in (
            "relax_hours",
            "relax_cost",
            "production_hours",
            "production_cost",
            "total_hours",
            "total_cost",
            "ns_day",
            "ns_day_relax",
        ):
            assert k in row, f"missing {k}"
        assert (
            abs(row["total_cost"] - (row["relax_cost"] + row["production_cost"])) < 0.02
        )

    def test_a_longer_production_moves_the_total_but_not_the_ladder(self, client):
        """The reactivity the wizard exists to provide: change the run length on a later tab
        and the cost follows, while the fixed relaxation cost stays put."""
        short = client.post(
            "/api/runpod/job-preview", json={**self.BODY, "production_ns": 10.0}
        ).json()["gpus"][0]
        long = client.post(
            "/api/runpod/job-preview", json={**self.BODY, "production_ns": 100.0}
        ).json()["gpus"][0]
        assert long["relax_cost"] == short["relax_cost"]
        assert long["total_cost"] > short["total_cost"]

    def test_storage_forecast_from_the_stage_table(self, client):
        d = client.post(
            "/api/runpod/job-preview",
            json={
                **self.BODY,
                "stages": [{"steps": 240_000, "dcd_freq": 5_000}] * 4,
                "package_bytes": 1_300_000_000,
            },
        ).json()
        st = d["storage"]
        assert st["output_bytes"] > 0
        assert st["needed_bytes"] > st["output_bytes"]  # the staged package counts too
        assert st["staging"]["minutes"] > 0
        assert st["used_known"] is False  # no live pod => usage unknowable

    def test_budget_gate_includes_the_staging_upload(self, client):
        """Staging bills before NAMD runs a step, so leaving it out of the comparison is how a
        'just under budget' run goes over."""
        d = client.post(
            "/api/runpod/job-preview",
            json={
                **self.BODY,
                "budget_usd": 0.01,
                "package_bytes": 1_300_000_000,
            },
        ).json()
        assert d["budget"]["over_budget"] is True
        assert d["budget"]["estimated_usd"] >= d["gpus"][0]["total_cost"]

    def test_generous_budget_is_not_flagged(self, client):
        d = client.post(
            "/api/runpod/job-preview", json={**self.BODY, "budget_usd": 100_000.0}
        ).json()
        assert d["budget"]["over_budget"] is False

    def test_git_build_drops_sm120(self, client):
        """A card outside the build's arch set rents fine and dies at step 0."""
        d = client.post(
            "/api/runpod/job-preview", json={**self.BODY, "build": "git"}
        ).json()
        assert d["gpus"] and all(g["sm"] != "sm_120" for g in d["gpus"])

    def test_unknown_build_is_a_400_not_a_500(self, client):
        r = client.post("/api/runpod/job-preview", json={**self.BODY, "build": "nope"})
        assert r.status_code == 400

    def test_not_connected_still_answers_with_indicative_prices(self, client):
        d = client.post("/api/runpod/job-preview", json=self.BODY).json()
        assert d["connected"] is False
        assert d["note"] and "indicative" in d["note"].lower()
        assert all(g["available"] is None for g in d["gpus"])
        assert d["balance"]["available"] is False
        assert d["live_pods"] == []

    def test_no_design_and_no_size_says_so(self, client):
        """No size, no honest cost — and no 500 either."""
        r = client.post("/api/runpod/job-preview", json={})
        assert r.status_code == 200
        d = r.json()
        if d["sized"] is False:
            assert d["reason"]
        else:  # a design happened to be loaded in the session
            assert d["n_atoms"] > 0 and d["n_atoms_source"] == "estimated"

    def test_stock_failure_degrades_instead_of_500ing(self, client, monkeypatch):
        """A Cloudflare hiccup on the GraphQL stock query must not take the panel down."""

        async def boom(*a, **kw):
            raise RuntimeError("cloudflare 1010")

        monkeypatch.setattr(routes_runpod.runpod_preflight, "fetch_gpu_stock", boom)
        routes_runpod._SESSION.api_key = "k" * 12  # noqa: SLF001
        r = client.post("/api/runpod/job-preview", json=self.BODY)
        assert r.status_code == 200
        assert r.json()["gpus"]

    def test_live_pods_surface_as_a_billing_warning(self, client, monkeypatch):
        """Anything in `live_pods` is billing right now — the wizard shows it in red."""

        def handler(request):
            if request.url.path.endswith("/pods"):
                return httpx.Response(200, json=[_pod()])
            return httpx.Response(200, json=[])

        _mock_runpod(monkeypatch, handler)
        client.post(
            "/api/runpod/connect",
            json={"api_key": "k" * 12, "network_volume_id": VOLUME},
        )
        d = client.post("/api/runpod/job-preview", json=self.BODY).json()
        assert d["connected"] is True
        assert [p["id"] for p in d["live_pods"]] == ["p1"]
