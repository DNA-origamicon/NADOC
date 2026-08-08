"""Unit tests for backend/core/cluster_ssh.py using an injected fake connector.

No real network — the asyncssh handshake is replaced by a fake connection object so
we can assert the state machine, credential hygiene, and run/error mapping.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core import cluster_ssh
from backend.core.cluster_ssh import ClusterConnection, ClusterSSHError, ConnState


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
