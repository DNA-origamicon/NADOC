"""SSH connection to a RunPod pod, satisfying md_executor's ``conn`` contract.

``md_executor`` was written against an informal duck-type (documented at
``md_executor.py:13-16``): any object exposing ``run`` / ``sftp_put`` / ``sftp_get`` /
``mkdir_p`` / ``mirror`` / ``user`` / ``is_connected``. It exists so tests can inject a
fake — but **a pod is just an SSH box, so it satisfies the same contract**, which is why
``stage_plan``, ``fetch_outputs`` and ``poll_remote_progress`` work here UNCHANGED.

Differences from :class:`~backend.core.cluster_ssh.ClusterConnection`:

* **No Duo, no password.** Key-based auth only. Consequence: unlike Alpine, RunPod
  resume can be fully AUTOMATIC — nothing needs a human present. That is what makes
  interruptible (spot) pods viable.
* **One filesystem.** Alpine has a project/scratch split and must ``mirror`` between
  them. A pod has one network volume, so ``mirror`` is a local ``rsync`` (kept only to
  satisfy the contract; on a pod the src and dst are usually the same tree).
* **Pods are ephemeral.** The connection is bound to a pod id and dies with it. A
  dropped connection to a spot pod means "reclaimed" — a resume, not a failure.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

import asyncssh

from backend.core.cluster_ssh import RunResult

log = logging.getLogger(__name__)

_CHUNK = 256 * 1024


class RunpodSSHError(RuntimeError):
    pass


class RunpodConnection:
    """An SSH session to one pod. Satisfies md_executor's ``conn`` contract."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        pod_id: str,
        username: str = "root",
        client_keys: Optional[list[str]] = None,
    ):
        self.host = host
        self.port = int(port)
        self.pod_id = pod_id
        self.user = username
        self._client_keys = client_keys
        self._conn: Optional[asyncssh.SSHClientConnection] = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def connect(self, *, timeout: float = 120.0, retries: int = 12) -> None:
        """Open the session, retrying while the pod's sshd finishes booting.

        A pod exposes its IP/port BEFORE sshd is accepting connections, so the first
        few attempts legitimately fail with ConnectionRefused. Treat that as "not yet",
        not as an error — otherwise every launch races and fails intermittently.
        """
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._conn = await asyncio.wait_for(
                    asyncssh.connect(
                        self.host,
                        port=self.port,
                        username=self.user,
                        client_keys=self._client_keys,
                        known_hosts=None,  # a fresh pod has a fresh host key, every time
                    ),
                    timeout=timeout,
                )
                return
            except (OSError, asyncssh.Error, asyncio.TimeoutError) as exc:
                last = exc
                await asyncio.sleep(min(5.0 * (attempt + 1), 20.0))
        raise RunpodSSHError(
            f"could not SSH to pod {self.pod_id} at {self.host}:{self.port} "
            f"after {retries} attempts: {last}"
        )

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            with_wait = getattr(self._conn, "wait_closed", None)
            if with_wait:
                await with_wait()
            self._conn = None

    def is_connected(self) -> bool:
        return self._conn is not None

    def status(self) -> dict:
        return {
            "connected": self.is_connected(),
            "pod_id": self.pod_id,
            "host": self.host,
            "port": self.port,
            "user": self.user,
        }

    def _require(self) -> asyncssh.SSHClientConnection:
        if self._conn is None:
            raise RunpodSSHError(f"not connected to pod {self.pod_id}")
        return self._conn

    # ── the conn contract ────────────────────────────────────────────────────

    async def run(self, cmd: str, timeout: float = 60.0, retries: int = 0) -> RunResult:
        """Run ``cmd`` on the pod.

        ``retries`` > 0 tolerates a TRANSIENT SSH drop (EU-RO-1 SSH flakes; a single dropped
        channel once aborted a whole multi-hour run): on a transport failure it RECONNECTS and
        retries, up to ``retries`` times.  Use it ONLY for IDEMPOTENT / read-only commands
        (status reads, `kill -0`, `pip install`) — NEVER for a side-effecting launch, where a
        reconnect-retry could double-execute (``launch_detached`` keeps the default 0).  A
        timeout is NOT retried (the command may still be running remotely)."""
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                conn = self._require()
            except RunpodSSHError as exc:  # not connected — try to (re)establish
                last = exc
                if attempt < retries and await self._reconnect():
                    continue
                raise
            try:
                res = await asyncio.wait_for(
                    conn.run(cmd, check=False), timeout=timeout
                )
                rc = getattr(res, "exit_status", 0) or 0
                return RunResult(
                    rc=int(rc), stdout=_s(res.stdout), stderr=_s(res.stderr)
                )
            except asyncio.TimeoutError as exc:
                raise RunpodSSHError(
                    f"command timed out after {timeout}s: {cmd}"
                ) from exc
            except Exception as exc:  # noqa: BLE001 — broken pipe / pod reclaimed / SSH drop
                last = exc
                if attempt < retries:
                    log.warning(
                        "runpod ssh: transport drop (try %d/%d), reconnecting: %s",
                        attempt + 1,
                        retries,
                        exc,
                    )
                    await self._reconnect()
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                raise RunpodSSHError(
                    f"command failed on transport after {attempt + 1} tr{'y' if attempt == 0 else 'ies'}: {exc}"
                ) from exc
        raise RunpodSSHError(f"command failed on transport: {last}")

    async def _reconnect(self) -> bool:
        """Drop the dead connection and re-establish it. Returns True on success."""
        try:
            await self.close()
        except Exception:  # noqa: BLE001
            self._conn = None
        try:
            await self.connect()
            return True
        except RunpodSSHError as exc:
            log.warning("runpod ssh: reconnect failed: %s", exc)
            return False

    async def mkdir_p(self, remote_dir: str) -> None:
        await self.run(f"mkdir -p {shlex.quote(remote_dir)}")

    async def sftp_put(
        self,
        local_path: str,
        remote_path: str,
        *,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        conn = self._require()
        await self.mkdir_p(str(PurePosixPath(remote_path).parent))
        total = Path(local_path).stat().st_size
        transferred = 0
        try:
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(remote_path, "wb") as dst:
                    with Path(local_path).open("rb") as src:
                        while chunk := src.read(_CHUNK):
                            await dst.write(chunk)
                            transferred += len(chunk)
                            if on_progress is not None:
                                on_progress(transferred, total)
        except Exception as exc:  # noqa: BLE001
            raise RunpodSSHError(f"upload failed ({local_path}): {exc}") from exc

    async def sftp_get(
        self, remote_path: str, local_path: str, *,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        conn = self._require()
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        total = 0
        transferred = 0
        try:
            async with conn.start_sftp_client() as sftp:
                total = int((await sftp.stat(remote_path)).size)
                async with sftp.open(remote_path, "rb") as src:
                    with Path(local_path).open("wb") as dst:
                        while chunk := await src.read(_CHUNK):
                            dst.write(chunk)
                            transferred += len(chunk)
                            if on_progress is not None:
                                on_progress(transferred, total)
        except Exception as exc:  # noqa: BLE001
            raise RunpodSSHError(f"download failed ({remote_path}): {exc}") from exc

    async def mirror(self, src: str, dst: str) -> RunResult:
        """rsync one remote tree to another, ON the pod.

        Alpine needs this for its project↔scratch two-filesystem model. A pod has a
        single network volume, so this is usually a no-op — kept because md_executor's
        contract calls it and a no-op rsync is cheaper than branching the executor.
        """
        await self.mkdir_p(dst)
        return await self.run(
            f"rsync -a {shlex.quote(src.rstrip('/') + '/')} "
            f"{shlex.quote(dst.rstrip('/') + '/')}",
            timeout=1800,
        )

    # ── pod-specific helpers the chain script needs ──────────────────────────

    async def launch_detached(self, script_path: str, workdir: str) -> int:
        """Start the chain script detached and return its PID.

        Three things here are load-bearing and were each learned by breaking them:

        * ``setsid`` — otherwise the script dies with the SSH channel, and the chain is
          a session leader so a later ``kill -TERM -<pid>`` can take the whole group.
        * ``> out 2>&1 < /dev/null`` — an inherited pipe keeps the SSH channel open, so
          ``conn.run`` never returns.
        * **``;`` NOT ``&&``.** ``cd D && CMD &`` backgrounds the whole COMPOUND in a
          subshell, and *that subshell's* stdout is still the SSH channel — so the channel
          stays open until the chain finishes (hours) and the launch call times out. With
          ``;`` the ``&`` binds to the redirected ``setsid`` alone. This exact bug hung the
          first real launch.
        """
        cmd = (
            f"cd {shlex.quote(workdir)} || exit 90; "
            f"setsid nohup bash {shlex.quote(script_path)} "
            f"> nadoc_chain.out 2>&1 < /dev/null & echo $!"
        )
        res = await self.run(cmd)
        pid = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
        if not pid.isdigit():
            raise RunpodSSHError(
                f"could not launch chain script (rc={res.rc}): {res.stderr[:200]}"
            )
        return int(pid)

    async def pid_alive(self, pid: int) -> bool:
        """Is that PID still running?

        ⚠️ **Never `pgrep namd3`.** NAMD renames its process to "NAMD masterPe", so
        matching by process NAME finds nothing and reports a live job as dead. The PID
        we spawned is the only reliable handle — this cost an hour of debugging and a
        contaminated benchmark.
        """
        res = await self.run(
            f"kill -0 {int(pid)} 2>/dev/null && echo alive || echo dead", retries=3
        )
        return "alive" in res.stdout

    async def read_file(self, remote_path: str) -> str:
        # retries: read_file backs the poll loop's status/heartbeat reads; a transient SSH
        # drop there must not abort a live run (the chain runs detached and keeps going).
        res = await self.run(
            f"cat {shlex.quote(remote_path)} 2>/dev/null || true", retries=3
        )
        return res.stdout


def _s(v) -> str:
    if v is None:
        return ""
    return v.decode() if isinstance(v, bytes) else str(v)
