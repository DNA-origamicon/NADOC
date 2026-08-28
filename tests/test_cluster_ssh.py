"""Unit tests for backend/core/cluster_ssh.py using an injected fake connector.

No real network — the asyncssh handshake is replaced by a fake connection object so
we can assert the state machine, credential hygiene, and run/error mapping.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.core import alpine_operations, cluster_ssh, resume_transfer
from backend.core.cluster_ssh import ClusterConnection, ClusterSSHError, ConnState
from tests.test_resume_transfer import build_dcd, frame_size, header_size


class _FakeRunResult:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.exit_status = rc
        self.stdout = stdout
        self.stderr = stderr


class _FakeConn:
    def __init__(self):
        self.closed = False
        self.commands = []
        self.next_result = _FakeRunResult(0, "ok", "")
        self.raise_on_run = None

    async def run(self, cmd, check=False):
        self.commands.append(cmd)
        if self.raise_on_run is not None:
            raise self.raise_on_run
        return self.next_result

    def close(self):
        self.closed = True


def _connector_returning(conn, *, captured=None):
    async def _connect(host, user, password, duo_method):
        if captured is not None:
            captured.update(host=host, user=user, password=password, duo=duo_method)
        return conn

    return _connect


def _run(coro):
    return asyncio.run(coro)


class _FakeRemoteFile:
    def __init__(self, data: bytes, fail_after: int | None = None):
        self.data = data
        self.pos = 0
        self.fail_after = fail_after

    async def __aenter__(self): return self
    async def __aexit__(self, *_): return None
    async def seek(self, pos): self.pos = pos

    async def read(self, size):
        if self.fail_after is not None and self.pos >= self.fail_after:
            raise BrokenPipeError("interrupted")
        chunk = self.data[self.pos : self.pos + min(size, 4)]
        self.pos += len(chunk)
        return chunk


class _FakeSftp:
    def __init__(self, data: bytes, fail_after: int | None = None):
        self.data = data
        self.fail_after = fail_after
        self.open_offsets = []

    async def __aenter__(self): return self
    async def __aexit__(self, *_): return None

    async def stat(self, _):
        return type("Stat", (), {"size": len(self.data)})()

    def open(self, *_):
        f = _FakeRemoteFile(self.data, self.fail_after)
        original_seek = f.seek
        async def seek(pos):
            self.open_offsets.append(pos)
            await original_seek(pos)
        f.seek = seek
        return f


def test_stream_get_resumes_partial_atomically(tmp_path):
    data = b"abcdefghijklmnop"
    target = tmp_path / "large.bin"
    broken = _FakeSftp(data, fail_after=8)
    with pytest.raises(BrokenPipeError):
        _run(cluster_ssh._stream_get(broken, "/remote/large.bin", str(target)))
    assert not target.exists()  # an incomplete file never masquerades as final
    assert (tmp_path / "large.bin.part").read_bytes() == data[:8]

    resumed = _FakeSftp(data)
    _run(cluster_ssh._stream_get(resumed, "/remote/large.bin", str(target)))
    # Two opens now: the first re-reads the partial's tail (the whole 8 bytes here,
    # being far under the verify window) to prove it really is a prefix of this remote
    # file; the second is the append itself.
    assert resumed.open_offsets == [0, 8]
    assert target.read_bytes() == data
    assert not (tmp_path / "large.bin.part").exists()


def test_stream_get_writes_a_resume_sidecar(tmp_path):
    data = b"abcdefghijklmnop"
    target = tmp_path / "large.bin"
    broken = _FakeSftp(data, fail_after=8)
    with pytest.raises(BrokenPipeError):
        _run(cluster_ssh._stream_get(broken, "/remote/large.bin", str(target)))

    side = resume_transfer.read_sidecar(str(target) + ".part")
    assert side["remote_path"] == "/remote/large.bin"
    assert side["remote_size"] == len(data)


def test_stream_get_clears_the_sidecar_once_complete(tmp_path):
    data = b"abcdefghijklmnop"
    target = tmp_path / "large.bin"
    _run(cluster_ssh._stream_get(_FakeSftp(data), "/remote/large.bin", str(target)))
    assert resume_transfer.read_sidecar(str(target) + ".part") is None


def test_stream_get_quarantines_a_partial_whose_tail_is_not_the_remote(tmp_path):
    """A partial built from some other file must never be appended to."""
    data = b"abcdefghijklmnop"
    target = tmp_path / "large.bin"
    part = tmp_path / "large.bin.part"
    part.write_bytes(b"ZZZZZZZZ")  # right length, wrong bytes

    _run(cluster_ssh._stream_get(_FakeSftp(data), "/remote/large.bin", str(target)))

    assert target.read_bytes() == data  # restarted from zero and got it right
    assert (tmp_path / "large.bin.part.rejected").read_bytes() == b"ZZZZZZZZ"


def test_stream_get_quarantines_a_dcd_partial_with_a_foreign_head(tmp_path):
    """The production failure: a stand-in one-frame DCD, then real remote bytes.

    The tail matches the remote perfectly, so only the structural check can refuse it.
    Quarantine, never delete — a corrupt head is often repairable and the partial can
    represent many hours of transfer.
    """
    real = build_dcd(6, 5)
    stand_in = build_dcd(6, 1, n_titles=3, fill=500)
    poisoned = stand_in + real[len(stand_in) : len(stand_in) + 2 * frame_size(6)]

    target = tmp_path / "traj.dcd"
    part = tmp_path / "traj.dcd.part"
    part.write_bytes(poisoned)

    _run(cluster_ssh._stream_get(_FakeSftp(real), "/remote/traj.dcd", str(target)))

    assert target.read_bytes() == real
    assert (tmp_path / "traj.dcd.part.rejected").read_bytes() == poisoned


def test_stream_get_resumes_a_structurally_sound_dcd_partial(tmp_path):
    """The whole point: a genuine prefix is appended to, not re-downloaded."""
    real = build_dcd(6, 5)
    cut = header_size() + 2 * frame_size(6)
    target = tmp_path / "traj.dcd"
    (tmp_path / "traj.dcd.part").write_bytes(real[:cut])

    sftp = _FakeSftp(real)
    _run(cluster_ssh._stream_get(sftp, "/remote/traj.dcd", str(target)))

    assert target.read_bytes() == real
    assert not (tmp_path / "traj.dcd.part.rejected").exists()
    assert cut in sftp.open_offsets  # it really resumed rather than restarting


def test_stream_get_refuses_a_complete_but_corrupt_download(tmp_path):
    """Right size, wrong bytes — the state that used to be reported as verified."""
    real = build_dcd(6, 5)
    stand_in = build_dcd(6, 1, n_titles=3, fill=500)
    poisoned = stand_in + real[len(stand_in) :]
    assert len(poisoned) == len(real)

    target = tmp_path / "traj.dcd"
    with pytest.raises(OSError, match="corrupt download"):
        _run(cluster_ssh._stream_get(_FakeSftp(poisoned), "/remote/traj.dcd", str(target)))

    assert not target.exists()
    assert (tmp_path / "traj.dcd.part.rejected").exists()


def test_stream_get_yields_between_chunks_for_api_fairness(tmp_path, monkeypatch):
    yields = []

    async def fair_yield(delay):
        yields.append(delay)

    monkeypatch.setattr(cluster_ssh.asyncio, "sleep", fair_yield)
    data = b"abcdefghijklmnop"
    target = tmp_path / "fair.bin"
    _run(cluster_ssh._stream_get(_FakeSftp(data), "/remote/fair.bin", str(target)))

    assert target.read_bytes() == data
    assert yields == [0, 0, 0, 0]


def test_initial_state_disconnected():
    c = ClusterConnection()
    assert c.state == ConnState.DISCONNECTED
    assert not c.is_connected()
    assert c.status() == {
        "state": "disconnected",
        "who": None,
        "host": None,
        "last_error": None,
        "error_kind": None,
    }


def test_connect_success_sets_state_and_identity():
    c = ClusterConnection()
    fake = _FakeConn()
    captured = {}
    _run(
        c.connect(
            "login.rc.colorado.edu",
            "jojo",
            "secret",
            "push",
            connector=_connector_returning(fake, captured=captured),
        )
    )
    assert c.is_connected()
    assert c.state == ConnState.CONNECTED
    assert c.status()["who"] == "jojo@login.rc.colorado.edu"
    # The connector actually received the password (auth happened)...
    assert captured["password"] == "secret"
    assert captured["duo"] == "push"


def test_connect_does_not_retain_password_attribute():
    c = ClusterConnection()
    _run(c.connect("h", "u", "topsecret", connector=_connector_returning(_FakeConn())))
    # No attribute anywhere on the object holds the plaintext password.
    assert "topsecret" not in repr(vars(c))


def test_connect_failure_returns_to_disconnected():
    c = ClusterConnection()

    async def _boom(host, user, password, duo_method):
        raise OSError("auth denied")

    with pytest.raises(ClusterSSHError):
        _run(c.connect("h", "u", "pw", connector=_boom))
    assert c.state == ConnState.DISCONNECTED
    assert not c.is_connected()


def test_connect_requires_host_and_user():
    c = ClusterConnection()
    with pytest.raises(ClusterSSHError):
        _run(c.connect("", "u", "pw", connector=_connector_returning(_FakeConn())))
    with pytest.raises(ClusterSSHError):
        _run(c.connect("h", "", "pw", connector=_connector_returning(_FakeConn())))


def test_run_requires_connection():
    c = ClusterConnection()
    with pytest.raises(ClusterSSHError):
        _run(c.run("whoami"))


def test_download_filesystem_error_does_not_expire_connection(tmp_path, monkeypatch):
    c = ClusterConnection()
    _run(c.connect("h", "u", "pw", connector=_connector_returning(_FakeConn())))

    async def missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", str(tmp_path / "x.part"))

    monkeypatch.setattr("backend.core.cluster_ssh._stream_get", missing)
    with pytest.raises(ClusterSSHError) as caught:
        _run(c.sftp_get("/remote/x", str(tmp_path / "x")))
    assert caught.value.kind == "filesystem"
    assert c.is_connected()


def test_download_incomplete_local_write_does_not_expire_connection(tmp_path, monkeypatch):
    c = ClusterConnection()
    fake = _FakeConn()
    fake.start_sftp_client = lambda: _FakeSftp(b"")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))

    async def incomplete(*args, **kwargs):
        raise OSError("incomplete download for /remote/x: 4/8 bytes")

    monkeypatch.setattr("backend.core.cluster_ssh._stream_get", incomplete)
    with pytest.raises(ClusterSSHError) as caught:
        _run(c.sftp_get("/remote/x", str(tmp_path / "x")))
    assert caught.value.kind == "unknown"
    assert c.is_connected()


def test_download_transport_error_expires_connection(tmp_path, monkeypatch):
    c = ClusterConnection()
    fake = _FakeConn()
    fake.start_sftp_client = lambda: _FakeSftp(b"")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))

    async def broken(*args, **kwargs):
        raise BrokenPipeError("Broken pipe")

    monkeypatch.setattr("backend.core.cluster_ssh._stream_get", broken)
    with pytest.raises(ClusterSSHError) as caught:
        _run(c.sftp_get("/remote/x", str(tmp_path / "x")))
    assert caught.value.kind == "network"
    assert c.state == ConnState.EXPIRED


def test_upload_generic_sftp_failure_does_not_expire_connection(tmp_path, monkeypatch):
    c = ClusterConnection()
    fake = _FakeConn()
    fake.start_sftp_client = lambda: _FakeSftp(b"")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    source = tmp_path / "source"
    source.write_text("payload")

    class SFTPFailure(Exception):
        pass

    async def rejected(*args, **kwargs):
        raise SFTPFailure("Failure")

    monkeypatch.setattr("backend.core.cluster_ssh._stream_put", rejected)
    with pytest.raises(ClusterSSHError) as caught:
        _run(c.sftp_put(str(source), "/projects/u/source"))
    assert caught.value.kind == "filesystem"
    assert c.is_connected()


def test_upload_transport_error_expires_connection(tmp_path, monkeypatch):
    c = ClusterConnection()
    fake = _FakeConn()
    fake.start_sftp_client = lambda: _FakeSftp(b"")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    source = tmp_path / "source"
    source.write_text("payload")

    async def broken(*args, **kwargs):
        raise BrokenPipeError("Broken pipe")

    monkeypatch.setattr("backend.core.cluster_ssh._stream_put", broken)
    with pytest.raises(ClusterSSHError) as caught:
        _run(c.sftp_put(str(source), "/scratch/u/source"))
    assert caught.value.kind == "network"
    assert c.state == ConnState.EXPIRED


def test_run_returns_result():
    c = ClusterConnection()
    fake = _FakeConn()
    fake.next_result = _FakeRunResult(0, "jojo\n", "")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    res = _run(c.run("whoami"))
    assert res.rc == 0
    assert res.stdout == "jojo\n"
    assert "whoami" in fake.commands


def test_run_transport_error_marks_expired():
    c = ClusterConnection()
    fake = _FakeConn()
    fake.raise_on_run = BrokenPipeError("pipe gone")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    with pytest.raises(ClusterSSHError):
        _run(c.run("whoami"))
    assert c.state == ConnState.EXPIRED
    assert not c.is_connected()


def test_run_transport_error_records_classified_status():
    c = ClusterConnection()
    fake = _FakeConn()
    fake.raise_on_run = BrokenPipeError("Broken pipe")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    with pytest.raises(ClusterSSHError) as ei:
        _run(c.run("whoami"))
    assert ei.value.kind == "network"
    st = c.status()
    assert st["state"] == "expired"
    assert st["error_kind"] == "network"
    assert "Broken pipe" in st["last_error"]


def test_timeout_records_timeout_kind():
    c = ClusterConnection()

    class _HangConn(_FakeConn):
        async def run(self, cmd, check=False):
            await asyncio.sleep(10)

    fake = _HangConn()
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    with pytest.raises(ClusterSSHError) as ei:
        _run(c.run("whoami", timeout=0.01))
    assert ei.value.kind == "timeout"
    assert c.status()["error_kind"] == "timeout"


def test_connect_failure_records_error_and_kind():
    c = ClusterConnection()

    async def _boom(host, user, password, duo_method):
        raise OSError("Permission denied (keyboard-interactive)")

    with pytest.raises(ClusterSSHError) as ei:
        _run(c.connect("h", "u", "pw", connector=_boom))
    assert ei.value.kind == "auth"
    st = c.status()
    assert st["state"] == "disconnected"
    assert st["error_kind"] == "auth"


def test_reconnect_clears_prior_error():
    c = ClusterConnection()

    async def _boom(host, user, password, duo_method):
        raise OSError("connection refused")

    with pytest.raises(ClusterSSHError):
        _run(c.connect("h", "u", "pw", connector=_boom))
    assert c.status()["error_kind"] == "network"
    # A successful reconnect wipes the stale error.
    _run(c.connect("h", "u", "pw", connector=_connector_returning(_FakeConn())))
    st = c.status()
    assert st["state"] == "connected"
    assert st["last_error"] is None and st["error_kind"] is None


@pytest.mark.parametrize(
    "text,kind",
    [
        ("command timed out after 60s: whoami", "timeout"),
        ("Broken pipe", "network"),
        ("Connection refused", "network"),
        ("connection reset by peer", "network"),
        ("Permission denied (keyboard-interactive)", "auth"),
        ("Authentication failed for user jojo", "auth"),
        ("Duo push denied", "auth"),
        ("No such file or directory", "filesystem"),
        ("sftp: disk quota exceeded", "filesystem"),
        ("Operation not permitted", "permission"),
        ("something totally unexpected", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify_ssh_error(text, kind):
    assert cluster_ssh.classify_ssh_error(text) == kind


def test_cluster_ssh_error_derives_kind_from_message():
    err = ClusterSSHError("upload failed: No such file or directory")
    assert err.kind == "filesystem"
    # explicit kind wins over classification
    assert ClusterSSHError("anything", kind="timeout").kind == "timeout"


def test_disconnect_clears_and_closes():
    c = ClusterConnection()
    fake = _FakeConn()
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    _run(c.disconnect())
    assert fake.closed
    assert c.state == ConnState.DISCONNECTED
    assert c.status()["who"] is None


def test_mkdir_p_and_mirror_issue_expected_commands():
    c = ClusterConnection()
    fake = _FakeConn()
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    _run(c.mkdir_p("/scratch/alpine/u/nadoc_jobs/md_1"))
    _run(c.mirror("/projects/u/nadoc_jobs/md_1", "/scratch/alpine/u/nadoc_jobs/md_1"))
    joined = "\n".join(fake.commands)
    assert "mkdir -p" in joined
    assert "rsync -a" in joined
    # trailing slashes present so rsync mirrors contents, not the dir itself
    assert "nadoc_jobs/md_1/'" in joined


def test_remote_mkdir_failure_is_filesystem_error_without_expiring_connection():
    c = ClusterConnection()
    fake = _FakeConn()
    fake.next_result = _FakeRunResult(1, "", "Disk quota exceeded")
    _run(c.connect("h", "u", "pw", connector=_connector_returning(fake)))
    with pytest.raises(ClusterSSHError) as caught:
        _run(c.mkdir_p("/scratch/alpine/u/nadoc_jobs/md_1"))
    assert caught.value.kind == "filesystem"
    assert c.is_connected()


def test_get_manager_is_singleton():
    a = cluster_ssh.get_manager()
    b = cluster_ssh.get_manager()
    assert a is b


def test_kbdint_answers_password_then_duo():
    prompts = [("Password:", False), ("Duo two-factor (push/passcode):", False)]
    assert cluster_ssh._kbdint_answers("pw", "push", prompts) == ["pw", "push"]


def test_kbdint_answers_passcode():
    prompts = [("Password: ", False), ("Passcode or option (1-3):", False)]
    assert cluster_ssh._kbdint_answers("pw", "123456", prompts) == ["pw", "123456"]


def test_kbdint_answers_unknown_prompt_defaults_password_first():
    prompts = [("Verification:", False), ("Second:", False)]
    assert cluster_ssh._kbdint_answers("pw", "push", prompts) == ["pw", "push"]


def test_kbdint_answers_empty_prompts():
    assert cluster_ssh._kbdint_answers("pw", "push", []) == []


def test_asyncssh_connect_kwargs_are_valid():
    """Guard against a repeat of the bad-kwarg bug: the options asyncssh builds from
    our connect kwargs must construct without error (no network is attempted)."""

    import asyncssh

    asyncssh.SSHClientConnectionOptions(
        username="u",
        password="pw",
        known_hosts=None,
    )


def test_alpine_operations_log_correlates_start_and_finish_without_secrets(tmp_path):
    log_file = alpine_operations.configure(tmp_path)
    c = ClusterConnection()
    fake = _FakeConn()
    _run(c.connect("alpine.example", "jojo", "topsecret", "654321",
                   connector=_connector_returning(fake)))
    _run(c.run("squeue -j 42"))
    _run(c.disconnect())

    records = [json.loads(line) for line in log_file.read_text().splitlines()]
    for operation in ("connect", "command", "disconnect"):
        start = next(r for r in records if r["event"] == f"{operation}_start")
        finish = next(r for r in records if r["event"] == f"{operation}_finish")
        assert finish["operation_id"] == start["operation_id"]
        assert finish["duration_ms"] >= 0
        assert finish["outcome"] == "success"
    text = log_file.read_text()
    assert "squeue -j 42" in text
    assert "topsecret" not in text
    assert "654321" not in text


def test_remote_command_error_log_keeps_bounded_diagnostic_preview(tmp_path):
    log_file = alpine_operations.configure(tmp_path)
    c = ClusterConnection()
    fake = _FakeConn()
    fake.next_result = _FakeRunResult(11, "", "rsync: Disk quota exceeded")
    _run(c.connect("alpine.example", "jojo", "pw", connector=_connector_returning(fake)))
    result = _run(c.run("rsync source/ destination/"))

    assert result.rc == 11
    records = [json.loads(line) for line in log_file.read_text().splitlines()]
    finish = next(
        r for r in records
        if r["event"] == "command_finish" and r["outcome"] == "remote_error"
    )
    assert finish["error_preview"] == "rsync: Disk quota exceeded"
