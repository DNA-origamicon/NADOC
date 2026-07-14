"""RunpodConnection — the piece that lets a RunPod pod reuse the Alpine executor.

The central claim of the whole design is: **md_executor was written against a `conn`
duck-type, and a pod is an SSH box, therefore stage_plan / fetch_outputs /
poll_remote_progress work UNCHANGED.** That claim is worth exactly nothing as prose, so
the headline test here drives a REAL md_executor function with a RunpodConnection and
asserts it works. If that ever breaks, the design is wrong and we would be maintaining
two remote backends instead of one.

No network: the asyncssh connection is stubbed.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from backend.core import md_executor
from backend.core.md_job import MdSegmentStatus, new_job
from backend.core.runpod_conn import RunpodConnection, RunpodSSHError


def _run(coro):
    return asyncio.run(coro)


class FakeSSH:
    """Stands in for asyncssh's SSHClientConnection."""

    def __init__(self, responses: dict[str, tuple[int, str, str]] | None = None):
        self.responses = responses or {}
        self.commands: list[str] = []

    async def run(self, cmd, check=False):
        self.commands.append(cmd)
        for needle, (rc, out, err) in self.responses.items():
            if needle in cmd:
                return _Res(rc, out, err)
        return _Res(0, "", "")


class _Res:
    def __init__(self, rc, out, err):
        self.exit_status = rc
        self.stdout = out
        self.stderr = err


def _conn(responses=None) -> RunpodConnection:
    c = RunpodConnection(host="1.2.3.4", port=10341, pod_id="p1")
    c._conn = FakeSSH(responses)  # noqa: SLF001 — deliberate injection, no network
    return c


# ── The claim ────────────────────────────────────────────────────────────────


class TestSatisfiesTheExecutorContract:
    CONTRACT = ("run", "sftp_put", "sftp_get", "mkdir_p", "mirror")

    def test_exposes_every_method_md_executor_calls(self):
        for name in self.CONTRACT:
            assert hasattr(RunpodConnection, name), name
            assert inspect.iscoroutinefunction(getattr(RunpodConnection, name)), name

    def test_has_user_and_is_connected(self):
        c = _conn()
        assert c.user == "root"
        assert c.is_connected() is True

    def test_md_executor_poll_remote_progress_works_over_a_runpod_connection(self):
        """THE test. A REAL md_executor function, driven by a RunpodConnection, with no
        RunPod-specific code path anywhere in it. This is what "reuse the Alpine
        executor" actually means — if it fails, we own two backends, not one."""
        job = new_job("d", "equilibrium_aware_namd", "d", "package/d_namd_solvated")
        job.remote_scratch_dir = "/workspace/jobs/abc"
        job.segments = [
            _seg("d_01_k0p5_p10"),
            _seg("d_01_k0p5_p50"),
            _seg("d_02_k0p1_p10"),
        ]
        listing = (
            "output/d_01_k0p5_p10.coor\n"
            "output/d_01_k0p5_p50.coor\n"
            "d_01_k0p5_p10.log\n"
            "d_01_k0p5_p50.log\n"
            "d_02_k0p1_p10.log\n"
        )
        conn = _conn({"ls -1 output/*.coor": (0, listing, "")})

        advanced = _run(md_executor.poll_remote_progress(job, conn=conn))

        assert advanced is True
        assert job.segments[0].status == "done"
        assert job.segments[1].status == "done"
        assert job.segments[2].status == "running"
        assert job.current_segment_idx == 2

    def test_md_executor_issues_the_listing_against_the_pod_scratch_dir(self):
        job = new_job("d", "equilibrium_aware_namd", "d", "package/d_namd_solvated")
        job.remote_scratch_dir = "/workspace/jobs/abc"
        job.segments = [_seg("s1")]
        conn = _conn()
        _run(md_executor.poll_remote_progress(job, conn=conn))
        assert any("/workspace/jobs/abc" in c for c in conn._conn.commands)  # noqa: SLF001


def _seg(name):
    return MdSegmentStatus(
        name=name, stage="relax", percent=10.0, steps=1000, status="pending"
    )


# ── Pod-specific helpers ─────────────────────────────────────────────────────


class TestLaunchDetached:
    def test_returns_the_pid_it_spawned(self):
        conn = _conn({"setsid": (0, "48213\n", "")})
        pid = _run(conn.launch_detached("/workspace/jobs/a/chain.sh", "/workspace/jobs/a"))
        assert pid == 48213

    def test_uses_setsid_and_detaches_all_stdio(self):
        """Without setsid the script dies when the SSH channel closes. Without full
        stdio redirection the inherited pipe keeps the SSH command from ever
        returning — the launch call itself hangs."""
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(conn.launch_detached("/w/chain.sh", "/w"))
        cmd = conn._conn.commands[-1]  # noqa: SLF001
        assert "setsid" in cmd
        assert "nohup" in cmd
        assert "< /dev/null" in cmd
        assert "> nadoc_chain.out 2>&1" in cmd

    def test_cd_is_separated_by_semicolon_not_ampersand_ampersand(self):
        """REGRESSION — this hung the first real pod launch.

        `cd D && CMD &` backgrounds the whole COMPOUND in a subshell whose stdout is
        still the SSH channel, so the channel stays open until the chain script finishes
        (hours) and conn.run times out after 60s. With `;` the `&` binds to the
        redirected `setsid` alone and the channel closes immediately."""
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(conn.launch_detached("/w/chain.sh", "/w"))
        cmd = conn._conn.commands[-1]  # noqa: SLF001
        assert "&&" not in cmd, "an && before the & re-subshells the launch and hangs it"
        assert "|| exit 90;" in cmd

    def test_raises_a_clear_error_when_no_pid_comes_back(self):
        conn = _conn({"setsid": (1, "", "bash: chain.sh: No such file")})
        with pytest.raises(RunpodSSHError, match="could not launch"):
            _run(conn.launch_detached("/w/nope.sh", "/w"))


class TestPidAlive:
    def test_alive(self):
        conn = _conn({"kill -0": (0, "alive\n", "")})
        assert _run(conn.pid_alive(123)) is True

    def test_dead(self):
        conn = _conn({"kill -0": (0, "dead\n", "")})
        assert _run(conn.pid_alive(123)) is False

    def test_never_greps_for_namd_by_process_name(self):
        """NAMD renames itself to "NAMD masterPe". `pgrep -x namd3` matches NOTHING and
        reports a running job as dead — that is how a runaway job survived a pkill, ate
        32 threads for an hour, and silently corrupted a whole benchmark run."""
        conn = _conn({"kill -0": (0, "alive\n", "")})
        _run(conn.pid_alive(123))
        cmd = conn._conn.commands[-1]  # noqa: SLF001
        assert "kill -0 123" in cmd
        assert "pgrep" not in cmd


class TestNotConnected:
    def test_every_op_fails_loudly_when_disconnected(self):
        c = RunpodConnection(host="h", port=1, pod_id="p")
        assert c.is_connected() is False
        with pytest.raises(RunpodSSHError, match="not connected"):
            _run(c.run("echo hi"))

    def test_status_is_reportable_without_a_connection(self):
        c = RunpodConnection(host="h", port=22, pod_id="p9")
        assert c.status() == {
            "connected": False, "pod_id": "p9", "host": "h", "port": 22, "user": "root",
        }
