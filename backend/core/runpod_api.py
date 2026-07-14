"""RunPod REST client — provision, poll and DESTROY a GPU pod.

Endpoint: ``https://rest.runpod.io/v1/pods`` (REST v1, not the legacy GraphQL API).

Split deliberately in two:

* **Pure functions** (``build_create_payload``, ``parse_pod``, ``ssh_endpoint``,
  ``pod_is_ready``) — no I/O, unit-tested directly.
* **``RunpodClient``** — a thin httpx wrapper. Its tests inject an httpx MockTransport,
  so the whole module is testable without renting anything.

⚠️ **The pod is the meter.** A pod bills from creation to termination, whether it is
computing or idle. Every code path that creates one MUST destroy it — see
``RunpodClient.pod`` (an async context manager that terminates in a ``finally``). An
orphaned pod costs $0.34–$2.39/hr until a human notices.

The API key lives in backend memory only (never on disk), mirroring the Alpine
credential rule in ``cluster_ssh``.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Optional

import httpx

API_BASE = "https://rest.runpod.io/v1"

# NAMD is statically linked against the CUDA runtime, so the container only has to supply
# the NVIDIA driver stack. The patched namd3 lives on the NETWORK VOLUME, not in the
# image, so the image NEVER needs rebuilding.
#
# ⚠️ Use a tag that actually exists on the registry. RunPod fails pod creation with a 500
# ("was not found on the registry") for a plausible-but-wrong tag, and there is no way to
# discover valid tags from the API — so this is pinned to the image the first working pod
# ran (verified: CUDA 12.8 toolchain, Ubuntu 24.04, gcc 13, which is what built the
# patched sm_89 NAMD on the volume).
DEFAULT_IMAGE = "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"

# Where the network volume mounts. Everything durable (patched NAMD, packages,
# checkpoints) lives here; anything outside it dies with the pod.
VOLUME_MOUNT_PATH = "/workspace"

# The container disk only holds the OS layer — the volume holds the data.
DEFAULT_CONTAINER_DISK_GB = 30


@dataclass(frozen=True)
class PodInfo:
    """A pod as RunPod reports it."""

    id: str
    desired_status: str  # RUNNING | EXITED | TERMINATED
    public_ip: Optional[str]
    ssh_port: Optional[int]
    cost_per_hr: Optional[float]
    raw: dict[str, Any]

    @property
    def is_running(self) -> bool:
        return self.desired_status == "RUNNING"

    @property
    def is_terminated(self) -> bool:
        """The pod is not going to run anything. NOT the same as 'it costs nothing'."""
        return self.desired_status in {"TERMINATED", "EXITED"}

    @property
    def is_destroyed(self) -> bool:
        """The pod is GONE — off the account, billing nothing.

        ``EXITED`` is deliberately NOT destroyed: the container stopped but the pod still
        exists and still holds (and bills for) its disk. Conflating the two is what let an
        orphaned EXITED pod sit on the account indefinitely — the reaper skipped it as
        'already dead'. Reap on this; poll on ``is_terminated``.
        """
        return self.desired_status == "TERMINATED"


# ── Pure ─────────────────────────────────────────────────────────────────────


def build_create_payload(
    *,
    name: str,
    gpu_type_ids: list[str],
    network_volume_id: str,
    interruptible: bool = True,
    gpu_count: int = 1,
    image: str = DEFAULT_IMAGE,
    container_disk_gb: int = DEFAULT_CONTAINER_DISK_GB,
    cloud_type: str = "COMMUNITY",
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Body for ``POST /v1/pods``.

    Notes that are easy to get wrong:

    * ``networkVolumeId`` must be set **at creation** — a volume cannot be attached to a
      running pod. It also pins the pod to the volume's datacenter, so we do NOT pass
      ``dataCenterIds`` and let RunPod resolve it.
    * ``ports`` must include ``22/tcp`` or there is no direct-TCP SSH, and the SSH
      *proxy* (``ssh.runpod.io``) does not reliably carry ``rsync``/``scp`` — which is
      how we stage a 2 GB package.
    * ``interruptible=True`` is the default because the chain script is idempotent: a
      reclaim is a resume, not a failure. It is roughly half price.
    """
    payload: dict[str, Any] = {
        "name": name,
        "imageName": image,
        "computeType": "GPU",
        "cloudType": cloud_type,
        "gpuTypeIds": list(gpu_type_ids),
        "gpuCount": gpu_count,
        "networkVolumeId": network_volume_id,
        "volumeMountPath": VOLUME_MOUNT_PATH,
        "containerDiskInGb": container_disk_gb,
        "ports": ["22/tcp"],
        "interruptible": interruptible,
        # ⚠️ Do NOT set `dockerStartCmd`. RunPod's images run their own start script,
        # and THAT is what launches sshd (plus keeps the container alive). Overriding it
        # with e.g. `sleep infinity` produces a pod that boots, reports RUNNING, exposes
        # a port — and refuses every SSH connection, because no sshd was ever started.
        # The image's default command already does the right thing.
    }
    if env:
        payload["env"] = dict(env)
    return payload


def parse_pod(data: dict[str, Any]) -> PodInfo:
    """Parse a pod object from any of the pod endpoints."""
    ports = data.get("portMappings") or {}
    raw_port = ports.get("22") if isinstance(ports, dict) else None
    try:
        ssh_port = int(raw_port) if raw_port is not None else None
    except (TypeError, ValueError):
        ssh_port = None

    ip = data.get("publicIp") or None
    cost = data.get("costPerHr")
    try:
        cost = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost = None

    return PodInfo(
        id=str(data.get("id", "")),
        desired_status=str(data.get("desiredStatus") or "UNKNOWN"),
        public_ip=ip,
        ssh_port=ssh_port,
        cost_per_hr=cost,
        raw=data,
    )


def ssh_endpoint(pod: PodInfo) -> Optional[tuple[str, int]]:
    """``(host, port)`` for direct-TCP SSH, or None while the pod is still booting.

    Both halves arrive asynchronously: a freshly created pod reports RUNNING with an
    empty ``publicIp`` for a while. Treat "no endpoint yet" as "keep waiting", never as
    an error.
    """
    if pod.public_ip and pod.ssh_port:
        return pod.public_ip, pod.ssh_port
    return None


def pod_is_ready(pod: PodInfo) -> bool:
    return pod.is_running and ssh_endpoint(pod) is not None


class RunpodError(RuntimeError):
    pass


# ── Client ───────────────────────────────────────────────────────────────────


class RunpodClient:
    """Thin async REST client. The api_key is held in memory only."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = API_BASE,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise RunpodError("A RunPod API key is required.")
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            transport=transport,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kw) -> Any:
        try:
            resp = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise RunpodError(f"RunPod API unreachable: {exc}") from exc
        if resp.status_code == 401:
            raise RunpodError("RunPod rejected the API key (401).")
        if resp.status_code >= 400:
            raise RunpodError(
                f"RunPod API {method} {path} failed ({resp.status_code}): {resp.text[:300]}"
            )
        if not resp.content:
            return None
        return resp.json()

    async def create_pod(self, payload: dict[str, Any]) -> PodInfo:
        return parse_pod(await self._request("POST", "/pods", json=payload) or {})

    async def get_pod(self, pod_id: str) -> PodInfo:
        return parse_pod(await self._request("GET", f"/pods/{pod_id}") or {})

    async def list_pods(self) -> list[PodInfo]:
        data = await self._request("GET", "/pods") or []
        if isinstance(data, dict):  # some deployments wrap it
            data = data.get("pods") or data.get("data") or []
        return [parse_pod(p) for p in data]

    async def terminate_pod(self, pod_id: str) -> None:
        """Destroy the pod. Idempotent: terminating an already-dead pod is not an error.

        This is the only thing standing between a bug and an unbounded bill, so it
        swallows 404 (already gone) rather than raising and skipping the cleanup.
        """
        try:
            await self._request("DELETE", f"/pods/{pod_id}")
        except RunpodError as exc:
            if "404" in str(exc):
                return
            raise

    async def wait_for_ssh(
        self,
        pod_id: str,
        *,
        timeout_s: float = 600.0,
        poll_s: float = 5.0,
        sleep=asyncio.sleep,
        now=None,
    ) -> PodInfo:
        """Block until the pod exposes a direct-TCP SSH endpoint.

        A pod reports RUNNING before ``publicIp``/``portMappings`` are populated, so
        "RUNNING" alone is NOT enough to connect. On timeout we TERMINATE the pod before
        raising — a half-booted pod nobody is holding a handle to is a silent bill.
        """
        loop_time = now or asyncio.get_event_loop().time
        deadline = loop_time() + timeout_s
        last: Optional[PodInfo] = None
        while loop_time() < deadline:
            last = await self.get_pod(pod_id)
            if pod_is_ready(last):
                return last
            if last.is_terminated:
                raise RunpodError(
                    f"Pod {pod_id} reached {last.desired_status} before exposing SSH."
                )
            await sleep(poll_s)

        with contextlib.suppress(Exception):
            await self.terminate_pod(pod_id)
        raise RunpodError(
            f"Pod {pod_id} did not expose SSH within {timeout_s:.0f}s "
            f"(last status {last.desired_status if last else 'unknown'}); terminated it."
        )

    async def create_pod_first_available(self, payloads: list[dict[str, Any]]) -> PodInfo:
        """Try each payload until one gets an instance.

        A network volume PINS the pod to its datacenter, and a given GPU/cloud-tier is
        often simply unavailable there — RunPod answers ``500 "There are no instances
        currently available"``. In particular there are frequently no COMMUNITY 4090s in
        the volume's region, which is why a hand-made pod ends up on SECURE at ~2x the
        price. So the caller passes cheapest-first and we walk down.

        Any error that is NOT an availability error is raised immediately — a bad image
        or a rejected key must not be retried against every tier.
        """
        last: Optional[RunpodError] = None
        for payload in payloads:
            try:
                return await self.create_pod(payload)
            except RunpodError as exc:
                if "no instances" not in str(exc).lower():
                    raise
                last = exc
        raise last or RunpodError("no pod payloads to try")

    @contextlib.asynccontextmanager
    async def pod(
        self,
        payload: dict[str, Any],
        *,
        fallbacks: Optional[list[dict[str, Any]]] = None,
        wait_timeout_s: float = 600.0,
    ):
        """Create a pod, yield it ready-for-SSH, and ALWAYS terminate it.

        The `finally` is the cost model. Do not create pods any other way.
        """
        info = await self.create_pod_first_available([payload, *(fallbacks or [])])
        try:
            yield await self.wait_for_ssh(info.id, timeout_s=wait_timeout_s)
        finally:
            with contextlib.suppress(Exception):
                await self.terminate_pod(info.id)
