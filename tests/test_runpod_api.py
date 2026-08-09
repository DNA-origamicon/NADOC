"""Tests for the RunPod REST client — no network, httpx MockTransport throughout.

The load-bearing property here is not "does it parse JSON". It is **does every path
that creates a pod also destroy one**. A pod bills from creation to termination; a
leaked pod is an unbounded, silent cost. Most of these tests exist to prove the
termination paths.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re

import httpx
import pytest

from backend.core import runpod_api

from backend.core import runpod_api as rp
from backend.core.runpod_api import (
    DEFAULT_IMAGE,
    VOLUME_MOUNT_PATH,
    RunpodClient,
    RunpodError,
    build_create_payload,
    parse_network_volume,
    parse_pod,
    pod_is_ready,
    ssh_endpoint,
    termination_deadline,
)

VOLUME = "77pnhye88p"  # the real volume: patched NAMD + packages + checkpoints


def _pod_json(pod_id="p1", status="RUNNING", ip="1.2.3.4", port=10341, cost=0.34):
    d = {"id": pod_id, "desiredStatus": status, "costPerHr": cost}
    if ip:
        d["publicIp"] = ip
    if port:
        d["portMappings"] = {"22": port}
    return d


class TestCreatePayload:
    def payload(self, **kw):
        return build_create_payload(
            name="nadoc-job-abc",
            gpu_type_ids=["NVIDIA GeForce RTX 4090"],
            network_volume_id=VOLUME,
            **kw,
        )

    def test_attaches_the_network_volume_at_the_right_mount(self):
        """The volume MUST be attached at creation — it cannot be added to a running
        pod. It carries the patched NAMD and every checkpoint; without it the pod is
        an empty box that has to rebuild NAMD from source."""
        p = self.payload()
        assert p["networkVolumeId"] == VOLUME
        assert p["volumeMountPath"] == VOLUME_MOUNT_PATH

    def test_exposes_tcp_22_because_the_ssh_proxy_cannot_rsync(self):
        """RunPod's SSH *proxy* (ssh.runpod.io) does not reliably carry rsync/scp, and
        we stage ~2 GB packages. Direct TCP on 22 is mandatory."""
        assert "22/tcp" in self.payload()["ports"]

    def test_defaults_to_on_demand_because_reclaims_lose_segment_work(self):
        assert self.payload()["interruptible"] is False
        assert self.payload(interruptible=True)["interruptible"] is True

    def test_does_not_override_the_images_start_command(self):
        """REGRESSION. Setting `dockerStartCmd` replaces RunPod's own start script — and
        THAT script is what launches sshd. A pod created with `sleep infinity` boots,
        reports RUNNING, exposes port 22, and then refuses every SSH connection, because
        no sshd was ever started. Cost an entire pod launch to learn."""
        assert "dockerStartCmd" not in self.payload()

    def test_does_not_pin_a_datacenter(self):
        """networkVolumeId already pins the pod to the volume's datacenter. Passing
        dataCenterIds as well can make the request unsatisfiable."""
        assert "dataCenterIds" not in self.payload()

    def test_provider_deadline_is_absolute_utc(self):
        now = datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)
        assert termination_deadline(3600, now=now) == "2026-08-09T01:00:00Z"

    def test_provider_deadline_is_carried_separately_from_the_container(self):
        p = self.payload(terminate_after="2026-08-10T00:00:00Z")
        assert p["terminateAfter"] == "2026-08-10T00:00:00Z"
        assert "dockerStartCmd" not in p

    def test_gpu_priority_order_is_preserved(self):
        p = build_create_payload(
            name="x", gpu_type_ids=["A", "B"], network_volume_id=VOLUME
        )
        assert p["gpuTypeIds"] == ["A", "B"]

    def test_image_is_a_plain_cuda_base(self):
        """NAMD is statically linked and lives on the volume, so the image only has to
        supply the driver stack — it never needs rebuilding."""
        assert self.payload()["imageName"] == DEFAULT_IMAGE
        assert (
            "runpod/" in DEFAULT_IMAGE
        )  # a bogus tag 500s at pod-create with no way to discover valid ones


class TestParsePod:
    def test_parses_ssh_endpoint(self):
        pod = parse_pod(_pod_json())
        assert ssh_endpoint(pod) == ("1.2.3.4", 10341)
        assert pod_is_ready(pod)

    def test_running_but_no_ip_yet_is_not_ready(self):
        """A pod reports RUNNING before publicIp/portMappings are populated. Treating
        RUNNING as connectable is the classic race."""
        pod = parse_pod(_pod_json(ip=None))
        assert pod.is_running
        assert ssh_endpoint(pod) is None
        assert not pod_is_ready(pod)

    def test_missing_port_mapping_is_not_ready(self):
        assert not pod_is_ready(parse_pod(_pod_json(port=None)))

    def test_terminated_pod(self):
        assert parse_pod(_pod_json(status="TERMINATED")).is_terminated

    def test_garbage_fields_do_not_raise(self):
        pod = parse_pod(
            {
                "id": "x",
                "desiredStatus": "RUNNING",
                "portMappings": {"22": "not-a-port"},
                "costPerHr": "free",
            }
        )
        assert pod.ssh_port is None
        assert pod.cost_per_hr is None


class TestNetworkVolumes:
    """Listing volumes is read-only — it creates no pod and bills nothing. It exists so
    the setup wizard can offer the account's volumes as a dropdown instead of an opaque
    id the user has to paste."""

    def test_parses_a_volume_object(self):
        v = parse_network_volume(
            {
                "id": "77pnhye88p",
                "name": "namd-vol",
                "size": 60,
                "dataCenterId": "EU-RO-1",
            }
        )
        assert v == {
            "id": "77pnhye88p",
            "name": "namd-vol",
            "size_gb": 60,
            "data_center_id": "EU-RO-1",
        }

    def test_tolerates_garbage_size(self):
        v = parse_network_volume({"id": "x", "size": "huge"})
        assert v["size_gb"] is None
        assert v["name"] == ""

    def test_lists_volumes(self):
        def handler(req):
            assert req.url.path.endswith("/networkvolumes")
            return httpx.Response(
                200,
                json=[
                    {"id": "v1", "name": "a", "size": 60, "dataCenterId": "EU-RO-1"},
                    {"id": "v2", "name": "b", "size": 100, "dataCenterId": "US-KS-2"},
                ],
            )

        async def go():
            c = _client(handler)
            vols = await c.list_network_volumes()
            await c.aclose()
            return vols

        vols = _run(go())
        assert [v["id"] for v in vols] == ["v1", "v2"]
        assert vols[1]["size_gb"] == 100

    def test_unwraps_a_wrapped_response(self):
        """Some deployments wrap the list in {"networkVolumes": [...]}."""

        def handler(req):
            return httpx.Response(200, json={"networkVolumes": [{"id": "v1"}]})

        async def go():
            c = _client(handler)
            vols = await c.list_network_volumes()
            await c.aclose()
            return vols

        assert [v["id"] for v in _run(go())] == ["v1"]


def _client(handler):
    return RunpodClient("key", transport=httpx.MockTransport(handler))


def _run(coro):
    """This repo drives async tests with asyncio.run (see tests/test_md_executor.py) —
    there is no pytest-asyncio plugin, and a bare @pytest.mark.asyncio silently does
    NOTHING (the coroutine is never awaited and the test 'passes' vacuously)."""
    return asyncio.run(coro)


PAYLOAD = build_create_payload(name="n", gpu_type_ids=["g"], network_volume_id=VOLUME)


class TestClient:
    def test_rejects_empty_api_key(self):
        with pytest.raises(RunpodError):
            RunpodClient("")

    def test_create_and_get(self):
        def handler(req):
            if req.method == "POST":
                return httpx.Response(201, json=_pod_json())
            return httpx.Response(200, json=_pod_json())

        async def go():
            c = _client(handler)
            pod = await c.create_pod(PAYLOAD)
            got = await c.get_pod("p1")
            await c.aclose()
            return pod, got

        pod, got = _run(go())
        assert pod.id == "p1"
        assert got.cost_per_hr == 0.34

    def test_expiring_gpu_creation_uses_graphql_wire_format(self):
        seen = {}

        def handler(req):
            seen["url"] = str(req.url)
            seen["body"] = json.loads(req.content)
            return httpx.Response(
                200,
                json={
                    "data": {"podFindAndDeployOnDemand": _pod_json(pod_id="guarded")}
                },
            )

        async def go():
            c = _client(handler)
            payload = build_create_payload(
                name="n",
                gpu_type_ids=["g"],
                network_volume_id=VOLUME,
                terminate_after="2026-08-10T00:00:00Z",
            )
            try:
                return await c.create_pod(payload)
            finally:
                await c.aclose()

        assert _run(go()).id == "guarded"
        gql_input = seen["body"]["variables"]["input"]
        assert gql_input["terminateAfter"] == "2026-08-10T00:00:00Z"
        assert gql_input["gpuTypeId"] == "g"
        assert gql_input["minCudaVersion"] == rp.DEFAULT_ALLOWED_CUDA[0]
        assert "api_key=key" in seen["url"]

    def test_401_is_a_clear_message_not_a_stack_trace(self):
        async def go():
            c = _client(lambda req: httpx.Response(401, text="nope"))
            try:
                await c.get_pod("p1")
            finally:
                await c.aclose()

        with pytest.raises(RunpodError, match="API key"):
            _run(go())

    def test_terminate_is_idempotent(self):
        """Terminating an already-gone pod must NOT raise — it is called from cleanup
        paths, and an exception there leaks the very pod we were trying to kill."""

        async def go():
            c = _client(lambda req: httpx.Response(404, text="gone"))
            await c.terminate_pod("p1")  # must not raise
            await c.aclose()

        _run(go())

    def test_lifecycle_audit_survives_pod_deletion(self, tmp_path):
        requests = []

        async def go():
            c = RunpodClient(
                "key",
                transport=httpx.MockTransport(
                    lambda req: requests.append(req) or httpx.Response(200)
                ),
                audit_dir=tmp_path,
            )
            c.record_lifecycle("pod_created", pod_id="p1", job_id="j1")
            await c.terminate_pod("p1", reason="job_completed", job_id="j1")
            events = c.lifecycle_events("p1")
            await c.aclose()
            return events

        events = _run(go())
        assert [e["event"] for e in events] == [
            "pod_created",
            "terminate_requested",
            "terminate_succeeded",
        ]
        assert events[1]["reason"] == "job_completed"
        assert events[1]["job_id"] == "j1"
        assert (tmp_path / ".runpod_lifecycle.jsonl").stat().st_mode & 0o777 == 0o600

    def test_failed_delete_is_durably_distinct_from_provider_loss(self, tmp_path):
        async def go():
            c = RunpodClient(
                "key",
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(400, text="bad")
                ),
                audit_dir=tmp_path,
            )
            with pytest.raises(RunpodError):
                await c.terminate_pod("p1", reason="explicit_job_stop", job_id="j1")
            events = c.lifecycle_events("p1")
            await c.aclose()
            return events

        assert [e["event"] for e in _run(go())] == [
            "terminate_requested",
            "terminate_failed",
        ]

    def test_wait_for_ssh_polls_until_the_ip_appears(self):
        calls = {"n": 0}

        def handler(req):
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(200, json=_pod_json(ip=None, port=None))
            return httpx.Response(200, json=_pod_json())

        async def go():
            c = _client(handler)
            pod = await c.wait_for_ssh("p1", poll_s=0, sleep=_nosleep)
            await c.aclose()
            return pod

        pod = _run(go())
        assert ssh_endpoint(pod) == ("1.2.3.4", 10341)
        assert calls["n"] == 3

    def test_wait_for_ssh_terminates_the_pod_on_timeout(self):
        """A half-booted pod that nobody holds a handle to bills forever. On timeout we
        kill it before raising."""
        deleted = []

        def handler(req):
            if req.method == "DELETE":
                deleted.append(req.url.path)
                return httpx.Response(200)
            return httpx.Response(200, json=_pod_json(ip=None, port=None))

        t = {"v": 0.0}

        def clock():
            t["v"] += 1.0
            return t["v"]

        async def go():
            c = _client(handler)
            try:
                await c.wait_for_ssh(
                    "p1", timeout_s=3, poll_s=0, sleep=_nosleep, now=clock
                )
            finally:
                await c.aclose()

        with pytest.raises(RunpodError, match="did not expose SSH"):
            _run(go())
        assert deleted, "timed-out pod must be terminated"

    def test_wait_for_ssh_fails_fast_if_the_pod_dies(self):
        async def go():
            c = _client(
                lambda req: httpx.Response(200, json=_pod_json(status="TERMINATED"))
            )
            try:
                await c.wait_for_ssh("p1", poll_s=0, sleep=_nosleep)
            finally:
                await c.aclose()

        with pytest.raises(RunpodError, match="before exposing SSH"):
            _run(go())

    def test_pod_context_manager_terminates_on_success(self):
        deleted = []

        async def go():
            c = _client(_recording_handler(deleted))
            async with c.pod(PAYLOAD) as pod:
                assert pod.id == "p1"
            await c.aclose()

        _run(go())
        assert deleted == ["/v1/pods/p1"], "pod must be terminated on the happy path"

    def test_pod_context_manager_terminates_when_the_body_raises(self):
        """THE test. If the job blows up mid-run, the pod still dies. Without this a
        crashed NADOC leaves a GPU billing indefinitely."""
        deleted = []

        async def go():
            c = _client(_recording_handler(deleted))
            try:
                async with c.pod(PAYLOAD):
                    raise ZeroDivisionError("job exploded")
            finally:
                await c.aclose()

        with pytest.raises(ZeroDivisionError):
            _run(go())
        assert deleted == ["/v1/pods/p1"], (
            "pod must be terminated even when the body raises"
        )


async def _nosleep(_):
    return None


def _recording_handler(deleted: list):
    def handler(req):
        if req.method == "DELETE":
            deleted.append(req.url.path)
            return httpx.Response(200)
        if req.method == "POST":
            return httpx.Response(201, json=_pod_json())
        return httpx.Response(200, json=_pod_json())

    return handler


class TestTransientFailuresDoNotKillTheRun:
    """A single DNS blip must not kill a 10-hour run. It did.

    A routine status poll hit `[Errno -3] Temporary failure in name resolution`.
    `_request` turned it into a fatal RunpodError, that propagated out of the poll loop
    and killed the launcher — and the launcher's `finally` is the ONLY thing that
    destroys the pod. The pod then billed on with NAMD still happily running and nothing
    alive to reap it. (The on-pod kill-switch has no API key: it can stop NAMD, never the
    billing.)
    """

    def _client(self, handler):
        return RunpodClient("k", transport=httpx.MockTransport(handler))

    def test_a_transient_dns_failure_is_retried_not_fatal(self, monkeypatch):
        monkeypatch.setattr(rp.asyncio, "sleep", _no_sleep)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError(
                    "[Errno -3] Temporary failure in name resolution"
                )
            return httpx.Response(200, json={"id": "p1", "desiredStatus": "RUNNING"})

        pod = asyncio.run(self._client(handler).get_pod("p1"))
        assert pod.id == "p1"
        assert calls["n"] == 3, "must retry through the blip, not die on it"

    def test_a_5xx_is_retried(self, monkeypatch):
        monkeypatch.setattr(rp.asyncio, "sleep", _no_sleep)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] < 2:
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(200, json={"id": "p1", "desiredStatus": "RUNNING"})

        assert asyncio.run(self._client(handler).get_pod("p1")).id == "p1"

    def test_a_4xx_fails_FAST_and_is_never_retried(self, monkeypatch):
        """A bad payload or rejected key fails identically forever; retrying it just
        burns pod-time while the meter runs."""
        monkeypatch.setattr(rp.asyncio, "sleep", _no_sleep)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(400, text="malformed")

        with pytest.raises(RunpodError):
            asyncio.run(self._client(handler).get_pod("p1"))
        assert calls["n"] == 1, "a 4xx must not be retried"

    def test_a_401_still_fails_immediately(self, monkeypatch):
        monkeypatch.setattr(rp.asyncio, "sleep", _no_sleep)

        def handler(request):
            return httpx.Response(401, text="nope")

        with pytest.raises(RunpodError, match="401"):
            asyncio.run(self._client(handler).get_pod("p1"))

    def test_gives_up_eventually_rather_than_hanging_forever(self, monkeypatch):
        monkeypatch.setattr(rp.asyncio, "sleep", _no_sleep)

        def handler(request):
            raise httpx.ConnectError("down")

        with pytest.raises(RunpodError, match="unreachable after"):
            asyncio.run(self._client(handler).get_pod("p1"))


async def _no_sleep(_):
    return None


class TestAPodThatNeverProvisionsSTILLBILLS:
    """`client.pod()` creates the pod, THEN waits for SSH, THEN yields. Billing starts at
    CREATE — not at the yield.

    A host whose driver is too old for the image's CUDA does not fail at create: RunPod
    rents it, the pod boots, reports RUNNING, and never starts sshd ("minimum cuda version
    requirement not met"). It bills for the entire wait_for_ssh timeout (10 min) and is then
    destroyed. Callers registered the pod id at the YIELD, so that spend reached no ledger
    at all and the budget guard was wrong by however many pods failed to provision.
    Measured on an EU-RO-1 RTX 4090.
    """

    def test_on_created_fires_even_when_the_pod_never_exposes_ssh(self, monkeypatch):
        monkeypatch.setattr(rp.asyncio, "sleep", _no_sleep)
        booked: list[str] = []
        terminated: list[str] = []

        def handler(request):
            if request.method == "POST" and request.url.path.endswith("/pods"):
                return httpx.Response(
                    200,
                    json={"id": "DEAD1", "desiredStatus": "RUNNING", "costPerHr": 0.69},
                )
            if request.method == "DELETE":
                terminated.append(request.url.path)
                return httpx.Response(200, json={})
            # GET: RUNNING forever, but NEVER an ssh endpoint.
            return httpx.Response(
                200, json={"id": "DEAD1", "desiredStatus": "RUNNING", "costPerHr": 0.69}
            )

        client = RunpodClient("k", transport=httpx.MockTransport(handler))

        async def go():
            async with client.pod(
                {"x": 1}, wait_timeout_s=0.0, on_created=lambda p: booked.append(p.id)
            ):
                pass  # pragma: no cover — wait_for_ssh must raise before we get here

        with pytest.raises(Exception):
            asyncio.run(go())

        assert booked == ["DEAD1"], "the pod BILLED — it must reach the ledger"
        assert terminated, "and it must still be destroyed"

    def test_on_created_reports_the_live_rate(self, monkeypatch):
        monkeypatch.setattr(rp.asyncio, "sleep", _no_sleep)
        seen = {}

        def handler(request):
            body = {
                "id": "P1",
                "desiredStatus": "RUNNING",
                "costPerHr": 0.74,
                "publicIp": "1.2.3.4",
                "portMappings": {"22": 1234},
            }
            return httpx.Response(200, json=body)

        client = RunpodClient("k", transport=httpx.MockTransport(handler))

        async def go():
            async with client.pod(
                {"x": 1}, on_created=lambda p: seen.update(id=p.id, rate=p.cost_per_hr)
            ):
                pass

        asyncio.run(go())
        assert seen == {"id": "P1", "rate": 0.74}


class TestNeverRentAHostThatCannotRunTheImage:
    def test_the_payload_pins_the_cuda_version(self):
        """The image is a cu128 build. A host with an older driver rents FINE, boots, and
        never starts sshd — billing for the whole timeout. allowedCudaVersions moves that
        failure to CREATE time, where it is free and instant."""
        p = rp.build_create_payload(name="n", gpu_type_ids=["g"], network_volume_id="v")
        assert p["allowedCudaVersions"] == rp.DEFAULT_ALLOWED_CUDA
        assert p["allowedCudaVersions"], "an empty list would allow ANY host"

    def test_the_pin_matches_the_image_tag(self):
        """If DEFAULT_IMAGE moves to a different cuXXX, this pin must move with it — else
        we go straight back to renting hosts that boot and never start sshd.

        `cu1281` = CUDA 12.8.1 -> major 12, minor 8.
        """
        m = re.search(r"cu(\d{2})(\d)", rp.DEFAULT_IMAGE)
        assert m, f"cannot read a CUDA version out of {rp.DEFAULT_IMAGE!r}"
        want = f"{m.group(1)}.{m.group(2)}"  # "12.8"
        assert want in rp.DEFAULT_ALLOWED_CUDA, (
            f"image needs CUDA {want} but allowedCudaVersions is "
            f"{rp.DEFAULT_ALLOWED_CUDA} — hosts too old for the image would be rented, "
            f"boot, never start sshd, and bill for the whole wait_for_ssh timeout"
        )


class TestHandoffAcrossAReload:
    """A pod survives a dev-server reload only if the UNWIND spares it.

    The teardown is structural: at process exit every in-flight task is cancelled, the
    CancelledError unwinds through ``pod()``'s finally, and the pod dies. Skipping the
    explicit shutdown hook does nothing about that — which is how a live 200 ns run was
    lost twice, once to the hook and once to the unwind.
    """

    def _client(self, deleted):
        def handler(req):
            if req.method == "DELETE":
                deleted.append(req.url.path)
                return httpx.Response(200)
            if req.method == "POST":
                return httpx.Response(201, json=_pod_json())
            return httpx.Response(200, json=_pod_json())

        return RunpodClient("k", transport=httpx.MockTransport(handler))

    def teardown_method(self):
        runpod_api.set_handoff(False)  # never leak the flag between tests

    def test_a_cancelled_run_normally_destroys_the_pod(self):
        deleted: list[str] = []
        client = self._client(deleted)

        async def go():
            async with client.pod({"name": "nadoc-x"}):
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(go())
        assert deleted == ["/v1/pods/p1"], "the default MUST stay destroy-on-unwind"

    def test_handoff_spares_the_pod_on_the_unwind(self):
        deleted: list[str] = []
        client = self._client(deleted)
        runpod_api.set_handoff(True)

        async def go():
            async with client.pod({"name": "nadoc-x"}):
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(go())
        assert deleted == [], (
            "a handed-off pod must survive for the next process to adopt"
        )

    def test_handoff_spares_an_adopted_pod_too(self):
        deleted: list[str] = []
        client = self._client(deleted)
        runpod_api.set_handoff(True)

        async def go():
            async with client.adopt("p1"):
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(go())
        assert deleted == []

    def test_the_flag_is_off_by_default(self):
        """Fail toward destroying pods: the expensive mistake is the one that bills."""
        assert runpod_api._handing_off() is False  # noqa: SLF001


class TestResolveApiKey:
    """Where the key comes from. Same order as experiments/exp43_runpod_bench/*, so the
    app, the launchers and the watchdogs all read ONE credential."""

    def test_env_var_wins_over_the_file(self, tmp_path):
        f = tmp_path / "key"
        f.write_text("rpa_fromfile")
        resolved = rp.resolve_api_key(env={"RUNPOD_API_KEY": "rpa_fromenv"}, key_file=f)
        assert (resolved.value, resolved.source) == ("rpa_fromenv", "env")

    def test_falls_back_to_the_key_file(self, tmp_path):
        f = tmp_path / "key"
        f.write_text("rpa_fromfile")
        assert rp.resolve_api_key(env={}, key_file=f) == rp.ResolvedApiKey(
            "rpa_fromfile", "file"
        )

    def test_a_trailing_newline_is_stripped(self, tmp_path):
        """`echo key > ~/.runpod_key` adds one; an unstripped key 401s every request."""
        f = tmp_path / "key"
        f.write_text("rpa_fromfile\n")
        assert rp.resolve_api_key(env={}, key_file=f).value == "rpa_fromfile"

    def test_an_empty_env_var_is_not_a_key(self, tmp_path):
        f = tmp_path / "key"
        f.write_text("rpa_fromfile")
        assert rp.resolve_api_key(env={"RUNPOD_API_KEY": "  "}, key_file=f) == (
            rp.ResolvedApiKey("rpa_fromfile", "file")
        )

    def test_no_key_anywhere_is_none_not_an_error(self, tmp_path):
        assert rp.resolve_api_key(
            env={}, key_file=tmp_path / "absent"
        ) == rp.ResolvedApiKey(None, "none")

    def test_an_empty_key_file_is_none(self, tmp_path):
        f = tmp_path / "key"
        f.write_text("\n")
        assert rp.resolve_api_key(env={}, key_file=f) == rp.ResolvedApiKey(None, "none")

    def test_an_unreadable_key_file_is_none_not_a_crash(self, tmp_path):
        """A key file we cannot read must degrade to "paste one in the wizard"."""
        f = tmp_path / "key"
        f.write_text("rpa_fromfile")
        f.chmod(0o000)
        try:
            assert rp.resolve_api_key(env={}, key_file=f) == rp.ResolvedApiKey(
                None, "none"
            )
        finally:
            f.chmod(0o600)
