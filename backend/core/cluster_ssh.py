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
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Awaitable, Callable, Optional

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

        if not host or not user:
            raise ClusterSSHError("host and user are required")
        connect_fn = connector or _asyncssh_connect
        async with self._lock:
            self.state = ConnState.CONNECTING
            self.host, self.user = host, user
            try:
                self._conn = await connect_fn(host, user, password, duo_method)
            except Exception as exc:  # noqa: BLE001 — surface any handshake failure
                self._conn = None
                self.state = ConnState.DISCONNECTED
                msg = f"connection failed: {exc}"
                self._record_error(msg)
                raise ClusterSSHError(msg) from exc
            finally:
                # Drop the password reference regardless of outcome.
                password = ""  # noqa: F841
            self.state = ConnState.CONNECTED
            self.last_error = self.last_error_kind = ""  # clear on success

    async def disconnect(self) -> None:
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
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass

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

        conn = self._require()
        try:
            result = await asyncio.wait_for(conn.run(cmd, check=False), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise self._fail_transport(
                f"command timed out after {timeout}s: {cmd}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — broken pipe / channel loss
            raise self._fail_transport(f"command failed on transport: {exc}") from exc
        rc = getattr(result, "exit_status", getattr(result, "returncode", 0)) or 0
        return RunResult(
            rc=int(rc), stdout=_as_str(result.stdout), stderr=_as_str(result.stderr)
        )

    async def mkdir_p(self, remote_dir: str) -> None:
        """Recursive remote mkdir (Appendix: recursive mkdir for job dirs)."""

        await self.run(f"mkdir -p {_shquote(remote_dir)}")

    async def sftp_put(self, local_path: str, remote_path: str) -> None:
        """Upload one file, chunked (256 KB, per-chunk flush)."""

        conn = self._require()
        await self.mkdir_p(str(PurePosixPath(remote_path).parent))
        try:
            async with conn.start_sftp_client() as sftp:
                await _stream_put(sftp, local_path, remote_path)
        except ClusterSSHError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._fail_transport(f"upload failed: {exc}") from exc

    async def sftp_get(self, remote_path: str, local_path: str, on_progress=None) -> None:
        """Download one file, chunked."""

        conn = self._require()
        try:
            async with conn.start_sftp_client() as sftp:
                await _stream_get(sftp, remote_path, local_path, on_progress=on_progress)
        except ClusterSSHError:
            raise
        except Exception as exc:  # noqa: BLE001
            message = f"download failed: {exc}"
            kind = classify_ssh_error(message)
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


async def _stream_get(sftp, remote_path: str, local_path: str, on_progress=None) -> None:
    import os

    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    remote_size = int((await sftp.stat(remote_path)).size)
    part_path = local_path + ".part"
    # Older NADOC downloads wrote directly to the final path. Adopt a short file as the
    # resumable partial instead of throwing away gigabytes already transferred.
    if os.path.exists(local_path):
        local_size = os.path.getsize(local_path)
        if local_size == remote_size:
            return
        if local_size < remote_size and not os.path.exists(part_path):
            os.replace(local_path, part_path)
    offset = os.path.getsize(part_path) if os.path.exists(part_path) else 0
    if offset > remote_size:
        os.unlink(part_path)
        offset = 0
    if on_progress:
        on_progress(offset, remote_size)
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
                # AsyncSSH may satisfy sequential reads immediately from its buffered
                # packet queue. An explicit yield prevents a multi-GB transfer from
                # monopolising uvloop and freezing unrelated API requests.
                await asyncio.sleep(0)
            fh.flush()
            os.fsync(fh.fileno())
    if os.path.getsize(part_path) != remote_size:
        raise OSError(
            f"incomplete download for {remote_path}: "
            f"{os.path.getsize(part_path)}/{remote_size} bytes"
        )
    os.replace(part_path, local_path)


# ── module singleton (one live connection per backend session) ─────────────────────

_MANAGER: ClusterConnection | None = None


def get_manager() -> ClusterConnection:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = ClusterConnection()
    return _MANAGER
