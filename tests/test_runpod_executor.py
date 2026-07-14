"""RunPod executor — provision → stage → run → fetch → DESTROY.

Two properties carry the whole feature and both are tested by execution, not assertion:

1. **The pod always dies.** Success, failure, exception, reclaim — every path terminates
   it. A leaked pod is a silent, unbounded bill.
2. **A reclaimed pod resumes, it does not restart.** The chain script is idempotent, so
   completed steps on the network volume are skipped. This is what makes cheap
   interruptible GPUs usable.

No network anywhere: httpx MockTransport + a stubbed asyncssh connection.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.core import runpod_executor as rx
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.runpod_api import RunpodClient, RunpodError
from backend.core.runpod_conn import RunpodConnection

VOLUME = "77pnhye88p"


def _run(coro):
    return asyncio.run(coro)


def _job(tmp_path, n_segs=2) -> MdJob:
    job = new_job("d", "equilibrium_aware_namd", "d", "package/d_namd_solvated")
    job.segments = [
        MdSegmentStatus(name=f"d_{i:02d}", stage="relax", percent=10.0, steps=100)
        for i in range(1, n_segs + 1)
    ]
    pkg = job.package_dir(tmp_path)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "d.psf").write_text("psf")
    (pkg / "d.pdb").write_text("pdb")
    return job


class FakeSSH:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.commands: list[str] = []

    async def run(self, cmd, check=False):
        self.commands.append(cmd)
        for needle, (rc, out, err) in self.responses.items():
            if needle in cmd:
                return _Res(rc, out, err)
        return _Res(0, "", "")

    def start_sftp_client(self):
        return _FakeSFTPCtx()


class _Res:
    def __init__(self, rc, out, err):
        self.exit_status, self.stdout, self.stderr = rc, out, err


class _FakeSFTPCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def open(self, path, mode):
        return _FakeFile()


class _FakeFile:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def write(self, data):
        return len(data)

    async def read(self, n=-1):
        return b""


def _conn(responses=None) -> RunpodConnection:
    c = RunpodConnection(host="h", port=1, pod_id="p1")
    c._conn = FakeSSH(responses)  # noqa: SLF001
    return c


# ── Sizing ───────────────────────────────────────────────────────────────────


class TestPodSizing:
    def test_sizes_from_the_measured_vram_model(self, tmp_path):
        job = _job(tmp_path)
        payload = rx.pod_payload_for(job, 225_504, network_volume_id=VOLUME)
        # gpuTypeIds is a PRIORITY LIST: cheapest first, then every other card that fits.
        # Naming a single GPU is what made RunPod answer 500 "There are no instances
        # currently available" — a network volume pins the datacenter (EU-RO-1), and the
        # one card we asked for simply was not free there.
        assert payload["gpuTypeIds"][0] == "NVIDIA GeForce RTX 4090"
        assert len(payload["gpuTypeIds"]) > 1, "must offer fallbacks, not one card"
        assert payload["networkVolumeId"] == VOLUME
        assert payload["interruptible"] is True

    def test_falls_back_across_cloud_tiers_as_well_as_cards(self, tmp_path):
        """COMMUNITY 4090s are frequently absent from the volume's region, which is why a
        hand-made pod silently lands on SECURE at ~2x the price ($0.69 vs $0.34/hr)."""
        payloads = rx.pod_payloads_for(_job(tmp_path), 225_504, network_volume_id=VOLUME)
        tiers = [(p["cloudType"], p["interruptible"]) for p in payloads]
        assert tiers[0] == ("COMMUNITY", True), "try the cheap tier first"
        assert ("SECURE", False) in tiers, "on-demand secure is the last resort"

    def test_refuses_a_system_no_gpu_can_hold(self, tmp_path):
        with pytest.raises(RunpodError, match="carve|GBIS"):
            rx.pod_payload_for(_job(tmp_path), 200_000_000, network_volume_id=VOLUME)

    def test_pod_name_is_within_runpods_191_char_limit(self, tmp_path):
        job = _job(tmp_path)
        job.design_name = "x" * 400
        assert len(rx.pod_payload_for(job, 225_504, network_volume_id=VOLUME)["name"]) <= 191


# ── Chain ────────────────────────────────────────────────────────────────────


class TestChainSteps:
    def test_minimisation_runs_first_then_every_segment_in_order(self, tmp_path):
        job = _job(tmp_path, n_segs=3)
        steps = rx.chain_steps_for(job, "d_00_min")
        assert steps[0].name == "d_00_min"
        assert steps[0].is_minimization
        assert [s.name for s in steps[1:]] == ["d_01", "d_02", "d_03"]


# ── Submit ───────────────────────────────────────────────────────────────────


class TestSubmit:
    def test_stages_the_package_and_launches_detached(self, tmp_path):
        job = _job(tmp_path)
        conn = _conn({"setsid": (0, "4242\n", "")})
        pid = _run(rx.submit_job(
            job, tmp_path, conn=conn, min_name="d_00_min", n_atoms=225_504, vcpus=32,
        ))
        assert pid == 4242
        assert job.runpod_pid == 4242
        assert job.status == MdStatus.running
        assert job.remote_scratch_dir == rx.remote_dir_for(job)

    def test_uses_physical_cores_not_vcpus(self, tmp_path):
        """MEASURED: +p32 on a 16-physical-core pod ran 18.85 ns/day vs +p16's 41.38.
        Oversubscribing SMT HALVES throughput. The chain script must ask for vcpus//2."""
        job = _job(tmp_path)
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(rx.submit_job(
            job, tmp_path, conn=conn, min_name="m", n_atoms=225_504, vcpus=32,
        ))
        script = (tmp_path / "md_jobs" / job.job_id / rx.CHAIN_SCRIPT).read_text()
        assert "+p16" in script
        assert "+p32" not in script

    def test_runs_namd_from_the_network_volume(self, tmp_path):
        """The patched sm_89 binary is built once and lives on the volume. Pods are
        disposable; a pod that had to rebuild NAMD would cost more than the run."""
        job = _job(tmp_path)
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(rx.submit_job(job, tmp_path, conn=conn, min_name="m",
                           n_atoms=225_504, vcpus=8))
        script = (tmp_path / "md_jobs" / job.job_id / rx.CHAIN_SCRIPT).read_text()
        assert rx.NAMD_ON_VOLUME in script


# ── Poll ─────────────────────────────────────────────────────────────────────


class TestPoll:
    def test_reports_completed(self, tmp_path):
        job = _job(tmp_path)
        job.remote_scratch_dir = "/workspace/nadoc_jobs/x"
        job.runpod_pid = 5
        conn = _conn({
            "nadoc_status": (0, "completed\n", ""),
            "nadoc_heartbeat": (0, "1000\n", ""),
            "kill -0": (0, "dead\n", ""),
        })
        st = _run(rx.poll_job(job, conn=conn, now=1010))
        assert st["state"] == "completed"

    def test_reports_the_failing_segment(self, tmp_path):
        job = _job(tmp_path)
        job.remote_scratch_dir = "/w/x"
        job.runpod_pid = 5
        conn = _conn({
            "nadoc_status": (0, "failed:d_02\n", ""),
            "nadoc_heartbeat": (0, "1000\n", ""),
            "kill -0": (0, "dead\n", ""),
        })
        st = _run(rx.poll_job(job, conn=conn, now=1010))
        assert st["state"] == "failed"
        assert st["segment"] == "d_02"

    def test_a_reclaimed_pod_looks_stale_and_dead_not_failed(self, tmp_path):
        """On an interruptible pod this is the NORMAL end state, not an error. The chain
        status still says 'running' because nothing got to write a failure — the machine
        simply vanished."""
        job = _job(tmp_path)
        job.remote_scratch_dir = "/w/x"
        job.runpod_pid = 5
        conn = _conn({
            "nadoc_status": (0, "running\n", ""),
            "nadoc_heartbeat": (0, "1000\n", ""),
            "kill -0": (0, "dead\n", ""),
        })
        st = _run(rx.poll_job(job, conn=conn, now=99999))
        assert st["state"] == "running"
        assert st["alive"] is False
        assert st["stale"] is True


# ── Cancel ───────────────────────────────────────────────────────────────────


class TestCancel:
    def test_kills_the_process_group_not_just_the_bash_pid(self, tmp_path):
        """Killing only the script orphans a running NAMD, which keeps the GPU busy and
        the pod BILLING while the UI reads 'stopped'. The script is a session leader
        (setsid), so kill the group: `kill -TERM -<pid>`."""
        job = _job(tmp_path)
        job.runpod_pid = 777
        conn = _conn()
        _run(rx.cancel_job(job, conn=conn))
        cmds = " ".join(conn._conn.commands)  # noqa: SLF001
        assert "-TERM -777" in cmds
        assert "-KILL -777" in cmds
        assert job.runpod_pid is None


# ── Whole-job orchestration: THE POD MUST ALWAYS DIE ─────────────────────────


def _pod_json(status="RUNNING"):
    return {"id": "pod1", "desiredStatus": status, "publicIp": "1.2.3.4",
            "portMappings": {"22": 10341}, "costPerHr": 0.34}


def _client_recording(deleted):
    def handler(req):
        if req.method == "DELETE":
            deleted.append(req.url.path)
            return httpx.Response(200)
        if req.method == "POST":
            return httpx.Response(201, json=_pod_json())
        return httpx.Response(200, json=_pod_json())

    return RunpodClient("k", transport=httpx.MockTransport(handler))


class TestRunJobOnPodAlwaysTerminates:
    def _patch_conn(self, monkeypatch, responses):
        async def fake_connect(self, **kw):
            self._conn = FakeSSH(responses)

        async def fake_close(self):
            self._conn = None

        monkeypatch.setattr(RunpodConnection, "connect", fake_connect)
        monkeypatch.setattr(RunpodConnection, "close", fake_close)

    def test_terminates_the_pod_after_a_successful_run(self, tmp_path, monkeypatch):
        self._patch_conn(monkeypatch, {
            "setsid": (0, "9\n", ""),
            "nadoc_status": (0, "completed\n", ""),
            "nadoc_heartbeat": (0, "1000\n", ""),
            "kill -0": (0, "dead\n", ""),
            "nproc": (0, "32\n", ""),
        })
        deleted: list[str] = []
        client = _client_recording(deleted)
        job = _job(tmp_path)

        status = _run(rx.run_job_on_pod(
            job, tmp_path, client=client, network_volume_id=VOLUME,
            min_name="d_00_min", n_atoms=225_504, poll_s=0, sleep=_nosleep,
        ))
        assert status == MdStatus.completed
        assert deleted == ["/v1/pods/pod1"], "the pod MUST be destroyed"

    def test_terminates_the_pod_when_the_run_fails(self, tmp_path, monkeypatch):
        self._patch_conn(monkeypatch, {
            "setsid": (0, "9\n", ""),
            "nadoc_status": (0, "failed:d_01\n", ""),
            "nadoc_heartbeat": (0, "1000\n", ""),
            "kill -0": (0, "dead\n", ""),
            "nproc": (0, "8\n", ""),
        })
        deleted: list[str] = []
        job = _job(tmp_path)
        status = _run(rx.run_job_on_pod(
            job, tmp_path, client=_client_recording(deleted), network_volume_id=VOLUME,
            min_name="m", n_atoms=225_504, poll_s=0, sleep=_nosleep,
        ))
        assert status == MdStatus.failed
        assert "d_01" in (job.error or "")
        assert deleted == ["/v1/pods/pod1"]

    def test_terminates_the_pod_when_something_raises_mid_run(self, tmp_path, monkeypatch):
        """The one that keeps you solvent. If NADOC crashes mid-job, the GPU still dies."""
        async def boom(self, **kw):
            raise RuntimeError("ssh exploded")

        monkeypatch.setattr(RunpodConnection, "connect", boom)
        deleted: list[str] = []
        job = _job(tmp_path)
        with pytest.raises(RuntimeError, match="ssh exploded"):
            _run(rx.run_job_on_pod(
                job, tmp_path, client=_client_recording(deleted),
                network_volume_id=VOLUME, min_name="m", n_atoms=225_504,
                poll_s=0, sleep=_nosleep,
            ))
        assert deleted == ["/v1/pods/pod1"], "a crash must not leak a billing GPU"

    def test_a_reclaimed_pod_becomes_resumable_not_failed(self, tmp_path, monkeypatch):
        """An interruptible pod vanishing is the EXPECTED case. The volume holds every
        completed step, so this is 'paused, resume me' — not 'failed, start over'."""
        self._patch_conn(monkeypatch, {
            "setsid": (0, "9\n", ""),
            "nadoc_status": (0, "running\n", ""),
            "nadoc_heartbeat": (0, "1\n", ""),   # ancient => stale
            "kill -0": (0, "dead\n", ""),
            "nproc": (0, "8\n", ""),
        })
        deleted: list[str] = []
        job = _job(tmp_path)
        status = _run(rx.run_job_on_pod(
            job, tmp_path, client=_client_recording(deleted), network_volume_id=VOLUME,
            min_name="m", n_atoms=225_504, poll_s=0, sleep=_nosleep,
        ))
        assert status == MdStatus.paused
        assert job.resumable is True
        assert deleted == ["/v1/pods/pod1"]


async def _nosleep(_):
    return None
