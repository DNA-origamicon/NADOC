"""Live SSH transport to a compute cluster — the *credentials + connection* half of
the Alpine remote-execution backend (config half is ``cluster_config.py``).

CURC Alpine allows **password + Duo 2FA only** (SSH keys disabled), via
keyboard-interactive.  So a connection is inherently ≥2-touch and cannot be fully
headless.  We hold one live connection per session in memory, keep the password only
long enough to authenticate, and **never** log or persist any secret.

Design for testability: the actual ``asyncssh`` handshake is isolated behind an
injectable ``connector`` coroutine.  Tests pass a fake connector returning a fake
connection object (with ``run`` / ``start_sftp_client`` / ``close``); the real one
is :func:`_asyncssh_connect`, lazy-imported so the backend/test-suite import even
when ``asyncssh`` is absent.

Nothing here does design/topology work — pure I/O plumbing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Awaitable, Callable, Optional

from backend.core import alpine_operations

# One connector coroutine signature: (host, user, password, duo_method) -> conn
Connector = Callable[[str, str, str, str], Awaitable[object]]

# AsyncSSH splits large reads into protocol packets internally. Asking for only 256 KiB
# here imposed hundreds of Python coroutine/round-trip cycles on an 80 MB NAMD checkpoint.
# Four MiB improved bulk throughput but a sustained 22.5 GB result download starved the
# server event loop badly enough that even /health and welcome-screen file imports hung.
# One MiB plus an explicit scheduler yield keeps most of the throughput while guaranteeing
# HTTP/WebSocket work gets a turn between SFTP chunks.
_SFTP_CHUNK = 1024 * 1024
_CHUNK_TIMEOUT_S = 300

logger = logging.getLogger(__name__)


class ConnState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    EXPIRED = "expired"


@dataclass
class RunResult:
    rc: int
    stdout: str
    stderr: str


# SSH/transport error buckets → actionable UI messages.  Order matters in
# ``classify_ssh_error`` (more specific keywords are tested first).
_ERROR_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("timeout", ("timed out", "timeout")),
    (
        "auth",
        (
            "permission denied (",
            "authentication failed",
            "auth failed",
            "password",
            "duo",
            "2fa",
            "kbdint",
            "keyboard-interactive",
            "no matching",
            "identikey",
            "too many authentication",
        ),
    ),
    (
        "network",
        (
            "connection refused",
            "connection reset",
            "connection lost",
            "connection closed",
            "broken pipe",
            "not connected",
            "unreachable",
            "name or service not known",
            "could not resolve",
            "host key",
            "channel",
            "econnrefused",
            "disconnected",
        ),
    ),
    ("permission", ("operation not permitted", "eacces", "not permitted")),
    (
        "filesystem",
        (
            "no such file",
            "not a directory",
            "disk quota",
            "no space",
            "enoent",
            "sftp",
        ),
    ),
]


def classify_ssh_error(text: str) -> str:
    """Pure: bucket an SSH/transport error message → an actionable kind.

    Returns one of ``"timeout"``, ``"auth"``, ``"network"``, ``"permission"``,
    ``"filesystem"``, or ``"unknown"``.  Turns opaque ``asyncssh`` exception text
    into something the UI can act on ("reconnect" vs "check your password" vs
    "check the remote path").  Heuristic + keyword-based — good enough to steer a
    message, not a precise diagnosis.
    """

    low = (text or "").lower()
    for kind, keywords in _ERROR_KEYWORDS:
        if any(k in low for k in keywords):
            return kind
    return "unknown"


def classify_transfer_error(exc: Exception, message: str) -> str:
    """Classify an SFTP operation without confusing file errors with auth errors.

    AsyncSSH's generic ``SFTPFailure`` is commonly returned for quota/capacity and
    other server-side file failures, with no detail beyond ``"Failure"``. That is
    not evidence that the authenticated SSH transport died. Conversely,
    ``SFTPConnectionLost`` really is a transport failure.
    """

    kind = classify_ssh_error(message)
    class_name = type(exc).__name__.lower()
    if class_name.startswith("sftp"):
        if "connectionlost" in class_name:
            return "network"
        if "permission" in class_name:
            return "permission"
        return "filesystem"
    return kind


class ClusterSSHError(RuntimeError):
    """Raised for transport-level failures (not-connected, auth, timeout).

    Carries a ``kind`` (see :func:`classify_ssh_error`) so callers/UI can react
    without re-parsing the message.
    """

    def __init__(self, message: str, kind: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind or classify_ssh_error(message)


def _kbdint_answers(password: str, duo_method: str, prompts) -> list[str]:
    """Pure: map an asyncssh keyboard-interactive challenge → response list.

    ``prompts`` is ``[(prompt_text, echo_bool), ...]``.  CURC sends the password
    prompt first, then a Duo second-factor prompt.  ``duo_method`` is ``"push"``
    (or ``"1"``) to trigger a phone push, or a 6-digit passcode.
    """

    answers: list[str] = []
    for prompt_text, _echo in prompts:
        low = (prompt_text or "").lower()
        if "password" in low:
            answers.append(password)
        elif any(k in low for k in ("duo", "passcode", "option", "push", "factor")):
            answers.append(duo_method)
        else:
            # Unknown extra prompt: password first, duo method thereafter.
            answers.append(password if not answers else duo_method)
    return answers


async def _asyncssh_connect(host: str, user: str, password: str, duo_method: str):
    """Real keyboard-interactive Duo handshake.  Lazy-imports ``asyncssh``.

    asyncssh drives keyboard-interactive via ``SSHClient`` callbacks, not a
    handler kwarg — so we hand ``connect`` a one-off client subclass bound to this
    call's password + Duo method via ``client_factory``.
    """

    import asyncssh  # lazy — optional dep

    class _DuoClient(asyncssh.SSHClient):
        def kbdint_auth_requested(self):
            return ""  # let the server choose the kbd-interactive submethod

        def kbdint_challenge_received(self, name, instructions, lang, prompts):
            if not prompts:
                return []  # info-only challenge (instructions) — no response
            return _kbdint_answers(password, duo_method, prompts)

    conn = await asyncssh.connect(
        host,
        username=user,
        password=password,  # also enables plain password_auth fallback
        client_factory=_DuoClient,
        known_hosts=None,  # CURC login nodes rotate host keys; TOFU-off
    )
    return conn


class ClusterConnection:
    """Singleton-per-session live connection holder.

    State machine: DISCONNECTED → CONNECTING → CONNECTED, and CONNECTED/… → EXPIRED
    on a detected transport error.  ``disconnect`` always returns to DISCONNECTED.
    """

    def __init__(self) -> None:
        self._conn: Optional[object] = None
        self.state: ConnState = ConnState.DISCONNECTED
        self.host: str = ""
        self.user: str = ""
        self.last_error: str = ""
        self.last_error_kind: str = ""
        self._lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────────
    async def connect(
        self,
        host: str,
        user: str,
        password: str,
        duo_method: str = "push",
        *,
        connector: Connector | None = None,
    ) -> None:
        """Authenticate and store the live connection.  Password is never retained."""

        op_id = alpine_operations.new_operation_id()
        started = time.monotonic()
        alpine_operations.event(
            "connect_start", operation_id=op_id, host=host, user=user,
            duo_mode="push" if duo_method == "push" else "passcode",
        )
        if not host or not user:
            alpine_operations.finish(
                "connect", op_id, started, outcome="error", error="host and user are required"
            )
            raise ClusterSSHError("host and user are required")
        connect_fn = connector or _asyncssh_connect
        async with self._lock:
            self.state = ConnState.CONNECTING
            self.host, self.user = host, user
            try:
                self._conn = await connect_fn(host, user, password, duo_method)
            except asyncio.CancelledError:
                self._conn = None
                self.state = ConnState.DISCONNECTED
                alpine_operations.finish("connect", op_id, started, outcome="cancelled")
                raise
            except Exception as exc:  # noqa: BLE001 — surface any handshake failure
                self._conn = None
                self.state = ConnState.DISCONNECTED
                msg = f"connection failed: {exc}"
                self._record_error(msg)
                alpine_operations.finish(
                    "connect", op_id, started, outcome="error",
                    error=msg, error_kind=self.last_error_kind,
                )
                raise ClusterSSHError(msg) from exc
            finally:
                # Drop the password reference regardless of outcome.
                password = ""  # noqa: F841
            self.state = ConnState.CONNECTED
            self.last_error = self.last_error_kind = ""  # clear on success
            alpine_operations.finish(
                "connect", op_id, started, outcome="success", host=host, user=user
            )

    async def disconnect(self) -> None:
        op_id = alpine_operations.new_operation_id()
        started = time.monotonic()
        alpine_operations.event(
            "disconnect_start", operation_id=op_id, host=self.host, user=self.user,
            prior_state=self.state.value,
        )
        async with self._lock:
            conn = self._conn
            self._conn = None
            self.state = ConnState.DISCONNECTED
            self.host = self.user = ""
            self.last_error = self.last_error_kind = ""
        if conn is not None:
            try:
                res = conn.close()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:  # noqa: BLE001 — best-effort teardown
                alpine_operations.finish(
                    "disconnect", op_id, started, outcome="error", error=str(exc)
                )
                return
        alpine_operations.finish("disconnect", op_id, started, outcome="success")

    def is_connected(self) -> bool:
        return self.state == ConnState.CONNECTED and self._conn is not None

    def status(self) -> dict:
        """Serializable snapshot for ``GET /api/cluster/status`` (no secrets)."""

        who = f"{self.user}@{self.host}" if self.user and self.host else None
        return {
            "state": self.state.value,
            "who": who,
            "host": self.host or None,
            "last_error": self.last_error or None,
            "error_kind": self.last_error_kind or None,
        }

    def _record_error(self, message: str) -> None:
        """Record a classified error for the status snapshot / UI."""
        self.last_error = message
        self.last_error_kind = classify_ssh_error(message)

    def _fail_transport(self, message: str) -> ClusterSSHError:
        """A transport-level failure that means the session is likely dead: record
        the classified error, flip to EXPIRED, and return the error to raise."""
        self._record_error(message)
        self.state = ConnState.EXPIRED
        return ClusterSSHError(message, kind=self.last_error_kind)

    # ── remote ops ───────────────────────────────────────────────────────────────
    def _require(self) -> object:
        if not self.is_connected():
            raise ClusterSSHError("not connected")
        return self._conn

    async def run(self, cmd: str, timeout: float = 60.0) -> RunResult:
        """Run a remote command → RunResult.  Marks EXPIRED on transport failure."""

        op_id = alpine_operations.new_operation_id()
        started = time.monotonic()
        alpine_operations.event(
            "command_start", operation_id=op_id, host=self.host, user=self.user,
            command=cmd, timeout_s=timeout,
        )
        try:
            conn = self._require()
        except Exception as exc:
            alpine_operations.finish(
                "command", op_id, started, outcome="error", command=cmd, error=str(exc)
            )
            raise
        try:
            result = await asyncio.wait_for(conn.run(cmd, check=False), timeout=timeout)
        except asyncio.CancelledError:
            alpine_operations.finish(
                "command", op_id, started, outcome="cancelled", command=cmd
            )
            raise
        except asyncio.TimeoutError as exc:
            alpine_operations.finish(
                "command", op_id, started, outcome="timeout", command=cmd, timeout_s=timeout
            )
            raise self._fail_transport(
                f"command timed out after {timeout}s: {cmd}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — broken pipe / channel loss
            alpine_operations.finish(
                "command", op_id, started, outcome="error", command=cmd, error=str(exc)
            )
            raise self._fail_transport(f"command failed on transport: {exc}") from exc
        rc = getattr(result, "exit_status", getattr(result, "returncode", 0)) or 0
        run_result = RunResult(
            rc=int(rc), stdout=_as_str(result.stdout), stderr=_as_str(result.stderr)
        )
        alpine_operations.finish(
            "command", op_id, started,
            outcome="success" if run_result.rc == 0 else "remote_error",
            command=cmd, rc=run_result.rc,
            stdout_bytes=len(run_result.stdout.encode("utf-8")),
            stderr_bytes=len(run_result.stderr.encode("utf-8")),
            # Byte counts alone hid the decisive rsync rc=11 diagnostic in the
            # incident log. Preserve a bounded error tail for post-reload triage;
            # successful command output remains count-only.
            error_preview=(
                (run_result.stderr or run_result.stdout).strip()[-2000:]
                if run_result.rc != 0
                else None
            ),
        )
        return run_result

    async def mkdir_p(self, remote_dir: str) -> None:
        """Recursive remote mkdir (Appendix: recursive mkdir for job dirs)."""

        result = await self.run(f"mkdir -p {_shquote(remote_dir)}")
        if result.rc != 0:
            detail = (result.stderr or result.stdout).strip()
            message = (
                f"remote directory creation failed for {remote_dir}: "
                f"{detail or f'rc={result.rc}'}"
            )
            kind = classify_ssh_error(message)
            raise ClusterSSHError(
                message, kind="filesystem" if kind == "unknown" else kind
            )

    async def sftp_put(self, local_path: str, remote_path: str) -> None:
        """Upload one file, chunked (256 KB, per-chunk flush)."""

        op_id = alpine_operations.new_operation_id()
        started = time.monotonic()
        size = os.path.getsize(local_path) if os.path.exists(local_path) else None
        alpine_operations.event(
            "upload_start", operation_id=op_id, local_path=local_path,
            remote_path=remote_path, bytes=size,
        )
        try:
            conn = self._require()
        except Exception as exc:
            alpine_operations.finish(
                "upload", op_id, started, outcome="error", local_path=local_path,
                remote_path=remote_path, bytes=size, error=str(exc),
            )
            raise
        try:
            await self.mkdir_p(str(PurePosixPath(remote_path).parent))
            async with conn.start_sftp_client() as sftp:
                await _stream_put(sftp, local_path, remote_path)
            alpine_operations.finish(
                "upload", op_id, started, outcome="success", local_path=local_path,
                remote_path=remote_path, bytes=size,
            )
        except asyncio.CancelledError:
            alpine_operations.finish(
                "upload", op_id, started, outcome="cancelled", local_path=local_path,
                remote_path=remote_path, bytes=size,
            )
            raise
        except ClusterSSHError:
            alpine_operations.finish(
                "upload", op_id, started, outcome="error", local_path=local_path,
                remote_path=remote_path, bytes=size,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            message = f"upload failed: {exc}"
            kind = classify_transfer_error(exc, message)
            alpine_operations.finish(
                "upload", op_id, started, outcome="error", local_path=local_path,
                remote_path=remote_path, bytes=size, error=message, error_kind=kind,
            )
            # A rejected remote write (quota, permissions, path, generic
            # SFTPFailure) fails this file, not the authenticated connection.
            if kind not in {"network", "timeout", "auth"}:
                raise ClusterSSHError(message, kind=kind) from exc
            raise self._fail_transport(message) from exc

    async def sftp_get(self, remote_path: str, local_path: str, on_progress=None) -> None:
        """Download one file, chunked."""

        op_id = alpine_operations.new_operation_id()
        started = time.monotonic()
        alpine_operations.event(
            "download_start", operation_id=op_id, remote_path=remote_path,
            local_path=local_path,
        )
        try:
            conn = self._require()
        except Exception as exc:
            alpine_operations.finish(
                "download", op_id, started, outcome="error", remote_path=remote_path,
                local_path=local_path, error=str(exc),
            )
            raise
        try:
            async with conn.start_sftp_client() as sftp:
                await _stream_get(sftp, remote_path, local_path, on_progress=on_progress)
            size = os.path.getsize(local_path) if os.path.exists(local_path) else None
            alpine_operations.finish(
                "download", op_id, started, outcome="success", remote_path=remote_path,
                local_path=local_path, bytes=size,
            )
        except asyncio.CancelledError:
            alpine_operations.finish(
                "download", op_id, started, outcome="cancelled", remote_path=remote_path,
                local_path=local_path,
            )
            raise
        except ClusterSSHError:
            alpine_operations.finish(
                "download", op_id, started, outcome="error", remote_path=remote_path,
                local_path=local_path,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            message = f"download failed: {exc}"
            kind = classify_transfer_error(exc, message)
            alpine_operations.finish(
                "download", op_id, started, outcome="error", remote_path=remote_path,
                local_path=local_path, error=message, error_kind=kind,
            )
            # A missing remote/local file, permissions problem, full disk, incomplete
            # local write, callback failure, etc. fails this transfer but says nothing
            # about the authenticated SSH transport. Unknown errors are deliberately
            # non-fatal too: a later remote operation can prove the transport dead, but
            # guessing here needlessly forces another Duo login.
            if kind not in {"network", "timeout", "auth"}:
                raise ClusterSSHError(message, kind=kind) from exc
            raise self._fail_transport(message) from exc

    async def mirror(self, src: str, dst: str) -> RunResult:
        """rsync one remote dir tree to another (project↔scratch two-filesystem model)."""

        cmd = f"rsync -a {_shquote(src.rstrip('/') + '/')} {_shquote(dst.rstrip('/') + '/')}"
        await self.mkdir_p(dst)
        return await self.run(cmd, timeout=1800)


# ── helpers ───────────────────────────────────────────────────────────────────────


def _as_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def _shquote(path: str) -> str:
    """Single-quote a remote path for the shell (defensive; job dirs are ours)."""

    return "'" + path.replace("'", "'\\''") + "'"


async def _stream_put(sftp, local_path: str, remote_path: str) -> None:
    with open(local_path, "rb") as fh:
        async with sftp.open(remote_path, "wb") as rf:
            while True:
                chunk = fh.read(_SFTP_CHUNK)
                if not chunk:
                    break
                await asyncio.wait_for(rf.write(chunk), timeout=_CHUNK_TIMEOUT_S)
                await asyncio.sleep(0)


async def _tail_matches(
    sftp, remote_path: str, part_path: str, start: int, end: int
) -> bool:
    """Does ``part_path[start:end]`` equal the same range of the remote file?

    The cheap proof that a partial really is a prefix of *this* remote file.  Costs one
    mebibyte against transfers measured in hundreds of gigabytes.
    """
    want = end - start
    if want <= 0:
        return True
    with open(part_path, "rb") as fh:
        fh.seek(start)
        local = fh.read(want)
    if len(local) != want:
        return False
    remote = bytearray()
    async with sftp.open(remote_path, "rb") as rf:
        await rf.seek(start)
        while len(remote) < want:
            chunk = await asyncio.wait_for(
                rf.read(min(_SFTP_CHUNK, want - len(remote))), timeout=_CHUNK_TIMEOUT_S
            )
            if not chunk:
                break
            remote.extend(chunk)
            await asyncio.sleep(0)
    return bytes(remote) == local


async def _stream_get(sftp, remote_path: str, local_path: str, on_progress=None) -> None:
    """Download one file to ``local_path``, resuming a verified ``.part`` if present.

    Appending to a partial is a trust decision, not a size comparison — see
    ``resume_transfer``.  A partial that fails either check is *quarantined*, never
    deleted: a corrupt head is often repairable, and silently discarding tens of
    gigabytes is the failure this whole path exists to prevent.
    """

    import os

    from backend.core import resume_transfer  # noqa: PLC0415 — keep transport importable

    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    attrs = await sftp.stat(remote_path)
    remote_size = int(attrs.size)
    remote_mtime = getattr(attrs, "mtime", None)
    part_path = local_path + ".part"
    if os.path.exists(local_path) and os.path.getsize(local_path) == remote_size:
        resume_transfer.clear_sidecar(part_path)
        return

    part_size = os.path.getsize(part_path) if os.path.exists(part_path) else 0
    plan = resume_transfer.plan_resume(
        part_size=part_size,
        remote_path=remote_path,
        remote_size=remote_size,
        remote_mtime=remote_mtime,
        sidecar=resume_transfer.read_sidecar(part_path),
    )
    offset, reject_reason = plan.offset, "" if plan.offset else plan.reason
    # Structural check FIRST: it is the only one that can see a corrupt *head*, which is
    # precisely how a stand-in writer sharing this path used to poison a download while
    # leaving the tail — and therefore the size and the tail check — perfectly plausible.
    if offset:
        ok, detail = resume_transfer.validate_partial(part_path)
        if not ok:
            offset, reject_reason = 0, f"structural check failed: {detail}"
    if offset and plan.verify_from < offset:
        if not await _tail_matches(
            sftp, remote_path, part_path, plan.verify_from, offset
        ):
            offset, reject_reason = 0, "last mebibyte does not match the remote file"

    if part_size and not offset:
        rejected = part_path + ".rejected"
        logger.error(
            "REFUSING to resume %s (%d bytes): %s — quarantined at %s",
            part_path,
            part_size,
            reject_reason,
            rejected,
        )
        os.replace(part_path, rejected)
        resume_transfer.clear_sidecar(part_path)
    if offset > remote_size:  # defensive; plan_resume already rules this out
        offset = 0

    if on_progress:
        on_progress(offset, remote_size)
    resume_transfer.write_sidecar(
        part_path,
        remote_path=remote_path,
        remote_size=remote_size,
        remote_mtime=remote_mtime,
        offset=offset,
    )
    checkpoint = offset
    async with sftp.open(remote_path, "rb") as rf:
        if offset:
            # AsyncSSH's SFTPClientFile.seek() is asynchronous.  Failing to await it
            # leaves the remote cursor at zero while we append to the partial file,
            # corrupting every resumed download and forcing another full retry.
            await rf.seek(offset)
        with open(part_path, "ab" if offset else "wb") as fh:
            while True:
                chunk = await asyncio.wait_for(
                    rf.read(_SFTP_CHUNK), timeout=_CHUNK_TIMEOUT_S
                )
                if not chunk:
                    break
                fh.write(chunk)
                offset += len(chunk)
                if on_progress:
                    on_progress(offset, remote_size)
                # Checkpoint on a fixed byte interval so an abrupt kill (uvicorn reload,
                # power loss) costs at most this much rather than the whole write buffer.
                if offset - checkpoint >= resume_transfer.CHECKPOINT_BYTES:
                    fh.flush()
                    os.fsync(fh.fileno())
                    resume_transfer.write_sidecar(
                        part_path,
                        remote_path=remote_path,
                        remote_size=remote_size,
                        remote_mtime=remote_mtime,
                        offset=offset,
                    )
                    checkpoint = offset
                # AsyncSSH may satisfy sequential reads immediately from its buffered
                # packet queue. An explicit yield prevents a multi-GB transfer from
                # monopolising uvloop and freezing unrelated API requests.
                await asyncio.sleep(0)
            fh.flush()
            os.fsync(fh.fileno())
    if os.path.getsize(part_path) != remote_size:
        resume_transfer.write_sidecar(
            part_path,
            remote_path=remote_path,
            remote_size=remote_size,
            remote_mtime=remote_mtime,
            offset=os.path.getsize(part_path),
        )
        raise OSError(
            f"incomplete download for {remote_path}: "
            f"{os.path.getsize(part_path)}/{remote_size} bytes"
        )
    complete, detail = resume_transfer.validate_partial(part_path)
    if not complete:
        # Right size, wrong bytes — the exact state that used to pass as "verified".
        rejected = part_path + ".rejected"
        os.replace(part_path, rejected)
        resume_transfer.clear_sidecar(part_path)
        raise OSError(
            f"corrupt download for {remote_path}: {detail} — quarantined at {rejected}"
        )
    os.replace(part_path, local_path)
    resume_transfer.clear_sidecar(part_path)


# ── module singleton (one live connection per backend session) ─────────────────────

_MANAGER: ClusterConnection | None = None


def get_manager() -> ClusterConnection:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = ClusterConnection()
    return _MANAGER
