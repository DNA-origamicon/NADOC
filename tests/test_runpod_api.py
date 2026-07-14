"""Tests for the RunPod REST client — no network, httpx MockTransport throughout.

The load-bearing property here is not "does it parse JSON". It is **does every path
that creates a pod also destroy one**. A pod bills from creation to termination; a
leaked pod is an unbounded, silent cost. Most of these tests exist to prove the
termination paths.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.core.runpod_api import (
    DEFAULT_IMAGE,
    VOLUME_MOUNT_PATH,
    RunpodClient,
    RunpodError,
    build_create_payload,
    parse_pod,
    pod_is_ready,
    ssh_endpoint,
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
            name="nadoc-job-abc", gpu_type_ids=["NVIDIA GeForce RTX 4090"],
            network_volume_id=VOLUME, **kw,
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

    def test_defaults_to_interruptible_because_resume_is_free(self):
        """The chain script skips completed steps, so a reclaim is a resume, not a
        failure — and interruptible is ~half price."""
        assert self.payload()["interruptible"] is True
        assert self.payload(interruptible=False)["interruptible"] is False

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

    def test_gpu_priority_order_is_preserved(self):
        p = build_create_payload(
            name="x", gpu_type_ids=["A", "B"], network_volume_id=VOLUME
        )
        assert p["gpuTypeIds"] == ["A", "B"]

    def test_image_is_a_plain_cuda_base(self):
        """NAMD is statically linked and lives on the volume, so the image only has to
        supply the driver stack — it never needs rebuilding."""
        assert self.payload()["imageName"] == DEFAULT_IMAGE
        assert "runpod/" in DEFAULT_IMAGE  # a bogus tag 500s at pod-create with no way to discover valid ones


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
        pod = parse_pod({"id": "x", "desiredStatus": "RUNNING",
                         "portMappings": {"22": "not-a-port"}, "costPerHr": "free"})
        assert pod.ssh_port is None
        assert pod.cost_per_hr is None


def _client(handler):
    return RunpodClient("key", transport=httpx.MockTransport(handler))


def _run(coro):
    """This repo drives async tests with asyncio.run (see tests/test_md_executor.py) —
    there is no pytest-asyncio plugin, and a bare @pytest.mark.asyncio silently does
    NOTHING (the coroutine is never awaited and the test 'passes' vacuously)."""
    return asyncio.run(coro)


PAYLOAD = build_create_payload(
    name="n", gpu_type_ids=["g"], network_volume_id=VOLUME
)


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
                await c.wait_for_ssh("p1", timeout_s=3, poll_s=0, sleep=_nosleep, now=clock)
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
        assert deleted == ["/v1/pods/p1"], "pod must be terminated even when the body raises"


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
