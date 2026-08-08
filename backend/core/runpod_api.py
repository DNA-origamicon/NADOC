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

The API key is resolved by ``resolve_api_key`` — ``$RUNPOD_API_KEY`` first, then
``~/.runpod_key`` — which is the same order every script in
``experiments/exp43_runpod_bench/`` already uses.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

# ── Hand-off (dev-server reload) ──────────────────────────────────────────────
# A pod is destroyed in ``pod()``/``adopt()``'s ``finally``, and that is STRUCTURAL: at
# process exit the supervisor task is cancelled, the CancelledError unwinds through the
# context manager, and the pod dies. So skipping the explicit shutdown hook does NOT save a
# pod across a dev-server reload — the cancellation destroys it anyway. That is exactly how
# a live 200 ns run was lost twice: once to the hook, once to the unwind.
#
# This flag is the only way to suppress that, and it is deliberately global + explicit:
# `main.lifespan` sets it when ``dev_reload.under_reloader()`` says another process is
# starting immediately and will adopt the pod on ``/runpod/connect``.
#
# ⚠️ Setting this when nothing adopts the pod leaks a billing GPU. It is never set on a real
# shutdown, and never outside a reload.
_HANDOFF = False


def set_handoff(on: bool) -> None:
    """Suppress pod destruction on unwind, because another process is taking over."""
    global _HANDOFF
    _HANDOFF = bool(on)


def _handing_off() -> bool:
    return _HANDOFF


# A transient network failure must not kill a 10-hour run. Retry the network layer and
# 5xx/429; never a 4xx (it will fail identically forever and just burns pod-time).
_MAX_API_RETRIES = 5
_RETRY_BASE_S = 2.0

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

# ⚠️ The image is a **cu128** build: it needs a host driver new enough for CUDA 12.8. Not
# every host has one. A host that is too old does NOT fail at create — RunPod rents it, the
# pod boots, reports RUNNING, and **never starts sshd** ("minimum cuda version requirement
# not met"). It then bills for the entire wait_for_ssh timeout (10 min) before we give up
# and destroy it. Measured on an EU-RO-1 RTX 4090.
#
# `allowedCudaVersions` moves that failure to CREATE time, where it is FREE and INSTANT:
# RunPod simply reports no matching instances instead of handing us a pod that cannot run.
#
# ⚠️ It is a list of ACCEPTABLE versions, NOT a minimum — so it must name 12.8 AND
# EVERYTHING ABOVE IT. A newer driver runs an older image perfectly well: the live PRO 4500
# host reports **CUDA 13.0** (driver 580.159.04). Listing only "12.8" excluded it and every
# other modern host, and the entire GPU sweep came back "no instances available" — a filter
# so tight it rented nothing at all. Keep the FLOOR in step with DEFAULT_IMAGE's cuXXX tag,
# and keep the CEILING open.
DEFAULT_ALLOWED_CUDA = ["12.8", "12.9", "13.0"]

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
    allowed_cuda_versions: Optional[list[str]] = None,
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
        # Never rent a host whose driver cannot run the image (see DEFAULT_ALLOWED_CUDA).
        "allowedCudaVersions": list(
            allowed_cuda_versions
            if allowed_cuda_versions is not None
            else DEFAULT_ALLOWED_CUDA
        ),
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


def parse_network_volume(data: dict[str, Any]) -> dict[str, Any]:
    """Normalise one network-volume object from ``GET /networkvolumes``.

    The volume is where everything durable lives (the patched multi-arch NAMD, the
    packages, every checkpoint) and it PINS the pod to its datacenter. The setup wizard
    lists these so the user picks the finished volume instead of pasting an opaque id.
    """
    size = data.get("size")
    try:
        size_gb = int(size) if size is not None else None
    except (TypeError, ValueError):
        size_gb = None
    return {
        "id": str(data.get("id", "")),
        "name": data.get("name") or "",
        "size_gb": size_gb,
        "data_center_id": data.get("dataCenterId") or None,
    }


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


# ── Where the key comes from ─────────────────────────────────────────────────
# Resolution order — env var, then key file — is IDENTICAL to every script in
# experiments/exp43_runpod_bench/ (balance.py:43, pod_watchdog.py:104,
# launch_voltron_compact.py:272). One source of truth: rotate the key in one place and the
# app, the launchers and the watchdogs all pick up the new one.
#
# The key lives on disk deliberately. A RunPod API key is a MACHINE credential — scoped to
# one account, revocable in one click — not a human password, and holding it in memory only
# had a concrete cost: after any backend restart NADOC had no key and literally could not
# terminate a pod it had left billing. What must never happen is the key entering the REPO;
# KEY_FILE is under $HOME, never under the working tree.
#
# NOT to be confused with ~/.runpod_key_kill, the second key shipped INTO a pod so the
# deadman switch can DELETE the pod from inside (the pod's auto-injected key 403s that).
# It is separate so it can be revoked on its own — it lives on a machine we do not control.
ENV_VAR = "RUNPOD_API_KEY"
KEY_FILE = Path.home() / ".runpod_key"


@dataclass(frozen=True)
class ResolvedApiKey:
    """A credential plus non-secret provenance.

    This deliberately is not a tuple.  Passing the old ``(key, source)`` result directly
    to ``RunpodClient`` produced an Authorization header containing the tuple repr and a
    misleading 401, even though the key itself was valid.
    """

    value: Optional[str]
    source: str


def resolve_api_key(
    *,
    env: Optional[Mapping[str, str]] = None,
    key_file: Optional[Path] = None,
) -> ResolvedApiKey:
    """The stored key and its origin, without exposing it in logs or status payloads.

    Never raises. A missing or unreadable key file is not an error — the setup wizard can
    always ask the user to paste one, which is exactly what happened before this existed.
    """
    environ = os.environ if env is None else env
    from_env = (environ.get(ENV_VAR) or "").strip()
    if from_env:
        return ResolvedApiKey(from_env, "env")

    path = KEY_FILE if key_file is None else key_file
    try:
        if not path.exists():
            return ResolvedApiKey(None, "none")
        raw = path.read_text().strip()
    except OSError as exc:
        log.warning("runpod: could not read %s: %s", path, exc)
        return ResolvedApiKey(None, "none")
    if not raw:
        return ResolvedApiKey(None, "none")
    _warn_if_group_or_world_readable(path)
    return ResolvedApiKey(raw, "file")


def _warn_if_group_or_world_readable(path: Path) -> None:
    """A key file other accounts can read is the one genuine risk of storing it at all."""
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        log.warning(
            "runpod: %s is readable by other users (mode %o) — run: chmod 600 %s",
            path,
            mode,
            path,
        )


# ── Client ───────────────────────────────────────────────────────────────────


class RunpodClient:
    """Thin async REST client. Takes the key from ``resolve_api_key`` or the setup wizard."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = API_BASE,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout: float = 30.0,
    ):
        if not isinstance(api_key, str):
            raise TypeError(
                "RunpodClient requires the credential string. Pass "
                "resolve_api_key().value, not the resolution object."
            )
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
        """One API call, retrying TRANSIENT failures.

        A single DNS blip must not kill a 10-hour run. It did: a routine status poll hit
        ``[Errno -3] Temporary failure in name resolution``, ``_request`` turned it into a
        fatal ``RunpodError``, that propagated out of the poll loop and killed the
        launcher — and the launcher's ``finally`` is the ONLY thing that destroys the pod.
        The pod then billed on, with NAMD still happily running and nothing left alive to
        reap it. (The on-pod kill-switch cannot help: it has no API key, so it can stop
        NAMD but never the billing.)

        Retries the network layer and 5xx/429 — i.e. "the request did not land, or the
        far end is having a moment". A 4xx is NOT retried: a bad payload or a rejected key
        will fail identically forever, and hammering it just costs pod-time.

        NOTE this makes a create_pod retry possible. That is safe here because every
        create is followed by a list/reconcile in `pod()`'s finally, and an orphan from a
        double-create would be caught by the reaper — whereas the failure it prevents
        (a leaked, billing pod nobody owns) is unbounded.
        """
        last: Exception | None = None
        for attempt in range(_MAX_API_RETRIES):
            try:
                resp = await self._client.request(method, path, **kw)
            except httpx.HTTPError as exc:
                last = exc
                await self._backoff(attempt, f"{method} {path}: {exc}")
                continue

            if resp.status_code == 401:
                raise RunpodError("RunPod rejected the API key (401).")
            if resp.status_code == 429 or resp.status_code >= 500:
                last = RunpodError(
                    f"RunPod API {method} {path} -> {resp.status_code}: {resp.text[:200]}"
                )
                await self._backoff(attempt, str(last))
                continue
            if resp.status_code >= 400:
                raise RunpodError(
                    f"RunPod API {method} {path} failed ({resp.status_code}): "
                    f"{resp.text[:300]}"
                )
            if not resp.content:
                return None
            return resp.json()

        raise RunpodError(
            f"RunPod API unreachable after {_MAX_API_RETRIES} tries: {last}"
        )

    async def _backoff(self, attempt: int, why: str) -> None:
        if attempt >= _MAX_API_RETRIES - 1:
            return
        delay = _RETRY_BASE_S * (2**attempt)
        log.warning(
            "runpod: %s — retrying in %.0fs (%d/%d)",
            why,
            delay,
            attempt + 1,
            _MAX_API_RETRIES,
        )
        await asyncio.sleep(delay)

    async def create_pod(self, payload: dict[str, Any]) -> PodInfo:
        return parse_pod(await self._request("POST", "/pods", json=payload) or {})

    async def get_pod(self, pod_id: str) -> PodInfo:
        return parse_pod(await self._request("GET", f"/pods/{pod_id}") or {})

    async def list_pods(self) -> list[PodInfo]:
        data = await self._request("GET", "/pods") or []
        if isinstance(data, dict):  # some deployments wrap it
            data = data.get("pods") or data.get("data") or []
        return [parse_pod(p) for p in data]

    async def list_network_volumes(self) -> list[dict[str, Any]]:
        """Every network volume on the account (``GET /networkvolumes``).

        Read-only — creates nothing, bills nothing. Used by the setup wizard to offer the
        volume as a dropdown. Same wrapping tolerance as ``list_pods``.
        """
        data = await self._request("GET", "/networkvolumes") or []
        if isinstance(data, dict):  # some deployments wrap it
            data = data.get("networkVolumes") or data.get("data") or []
        return [parse_network_volume(v) for v in data]

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

    async def create_pod_first_available(
        self, payloads: list[dict[str, Any]]
    ) -> PodInfo:
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
        on_created=None,
    ):
        """Create a pod, yield it ready-for-SSH, and ALWAYS terminate it.

        The `finally` is the cost model. Do not create pods any other way.

        ``on_created(PodInfo)`` fires the INSTANT the pod exists — before ``wait_for_ssh``.
        **This is not a nicety: billing starts at creation, not at the yield.** A pod that
        boots but never exposes SSH (e.g. the host's driver is too old for the image's CUDA
        — RunPod reports "minimum cuda version requirement not met") bills for the whole
        ``wait_timeout_s`` and is then destroyed here. If the caller only learns the pod id
        at the yield, that spend is **invisible**: it never reaches the ledger, and the
        budget guard is wrong by however many pods failed to provision. Measured: a 4090
        bench pod billed ~10 min this way and appeared in no ledger at all.
        """
        info = await self.create_pod_first_available([payload, *(fallbacks or [])])
        if on_created is not None:
            on_created(info)  # it is BILLING from this moment
        try:
            yield await self.wait_for_ssh(info.id, timeout_s=wait_timeout_s)
        finally:
            if _handing_off():
                log.warning(
                    "runpod: HANDING OFF pod %s instead of destroying it (dev-server "
                    "reload). The next process adopts it on /runpod/connect; if it does "
                    "not, this pod bills until it is reaped.",
                    info.id,
                )
            else:
                with contextlib.suppress(Exception):
                    await self.terminate_pod(info.id)

    @contextlib.asynccontextmanager
    async def adopt(self, pod_id: str, *, wait_timeout_s: float = 300.0):
        """Take ownership of an EXISTING pod, yield it ready-for-SSH, and ALWAYS terminate it.

        The counterpart to :meth:`pod` for a run this process did not start — a pod left up
        by a dev-server reload, or one whose supervisor died. It carries the same `finally`,
        so the rule "a pod dies exactly one way" still holds: adopting is how a second
        process inherits that obligation instead of orphaning it.

        Raises ``RunpodError`` if the pod is gone or already destroyed, so a caller cannot
        mistake a vanished pod for an adopted one and sit polling nothing.
        """
        info = await self.get_pod(pod_id)
        if info.is_destroyed:
            raise RunpodError(f"pod {pod_id} is already destroyed; nothing to adopt")
        try:
            yield await self.wait_for_ssh(pod_id, timeout_s=wait_timeout_s)
        finally:
            if _handing_off():
                log.warning(
                    "runpod: HANDING OFF adopted pod %s instead of destroying it "
                    "(dev-server reload).",
                    pod_id,
                )
            else:
                with contextlib.suppress(Exception):
                    await self.terminate_pod(pod_id)
