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
import json

import httpx
import pytest

from backend.core import md_executor
from backend.core import runpod_executor as rx
from backend.core.md_job import (
    MdJob,
    MdSegmentStatus,
    MdStatus,
    finish_runpod_billing,
    new_job,
    start_runpod_billing,
)
from backend.core.runpod_api import RunpodClient, RunpodError
from backend.core.runpod_conn import RunpodConnection

VOLUME = "77pnhye88p"


def test_runpod_billing_sessions_accumulate_and_freeze_final_cost(tmp_path):
    job = _job(tmp_path, 0)
    start_runpod_billing(job, "pod-a", 0.72, now=1_000)
    start_runpod_billing(job, "pod-a", 0.74, now=1_100)  # idempotent; refreshes rate
    assert len(job.runpod_billing_sessions) == 1
    assert finish_runpod_billing(job, "pod-a", now=4_600) == pytest.approx(0.74)

    start_runpod_billing(job, "pod-b", 1.0, now=5_000)
    job.status = MdStatus.completed
    assert finish_runpod_billing(job, "pod-b", now=6_800) == pytest.approx(1.24)
    assert job.runpod_final_cost_usd == pytest.approx(1.24)
    job.save(tmp_path)
    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.runpod_final_cost_usd == pytest.approx(1.24)


def test_s3_prestage_compresses_missing_files_before_pod_creation(tmp_path, monkeypatch):
    import tarfile
    from backend.core import runpod_s3

    job = _job(tmp_path)
    seen = {}

    class FakeS3:
        def __init__(self, *_args, **_kwargs):
            pass

        async def file_sizes(self):
            return {}

        async def sftp_put(self, local, remote, *, on_progress=None):
            with tarfile.open(local, "r:gz") as tf:
                seen["members"] = sorted(tf.getnames())
            seen["remote"] = remote
            size = __import__("pathlib").Path(local).stat().st_size
            on_progress(size, size)

    monkeypatch.setattr(runpod_s3, "RunpodS3Connection", FakeS3)
    remote = _run(rx._prestage_package_s3(
        job, tmp_path,
        credentials=runpod_s3.S3Credentials("a", "s", "test"),
        volume_id=VOLUME, data_center_id="EU-RO-1",
    ))
    assert remote == f"{rx.remote_dir_for(job)}/{rx.S3_STAGE_ARCHIVE}"
    assert "d.psf" in seen["members"]
    assert "d.pdb" in seen["members"]
    assert "manifest.json" in seen["members"]
    assert job.remote_submit_progress["fraction"] == 1.0


def test_s3_prestage_skips_when_volume_already_matches(tmp_path, monkeypatch):
    from backend.core import runpod_s3

    job = _job(tmp_path)
    pkg = job.package_dir(tmp_path)

    class FakeS3:
        def __init__(self, *_args, **_kwargs):
            pass

        async def file_sizes(self):
            return {p.name: p.stat().st_size for p in pkg.iterdir() if p.is_file()}

    monkeypatch.setattr(runpod_s3, "RunpodS3Connection", FakeS3)
    assert _run(rx._prestage_package_s3(
        job, tmp_path,
        credentials=runpod_s3.S3Credentials("a", "s", "test"),
        volume_id=VOLUME, data_center_id="EU-RO-1",
    )) is None


def test_s3_stage_extract_does_not_restore_desktop_ownership():
    seen = {}

    class Conn:
        async def run(self, command):
            seen["command"] = command
            return type("Result", (), {"rc": 0, "stderr": ""})()

    _run(rx._extract_s3_stage(Conn(), "/workspace/job", "/workspace/job/pkg.tgz"))
    assert "tar --no-same-owner -xzf" in seen["command"]


def test_equal_size_namd_conf_is_always_refreshed():
    assert not rx._volume_file_reusable("stage.conf", 100, 100)
    assert rx._volume_file_reusable("system.psf", 100, 100)
    assert not rx._volume_file_reusable("system.psf", 99, 100)


def _run(coro):
    return asyncio.run(coro)


def _job(tmp_path, n_segs=2) -> MdJob:
    job = new_job("d", "equilibrium_aware_namd", "d", "package/d_namd_solvated")
    # Early-stop is ON by default since 2026-07-29, which stages an extra evaluator
    # script.  These tests are about staging REUSE, so opt out to keep them focused;
    # test_md_executor.py covers the staging that early-stop itself triggers.
    job.early_stop_relax = False
    job.segments = [
        MdSegmentStatus(name=f"d_{i:02d}", stage="relax", percent=10.0, steps=100)
        for i in range(1, n_segs + 1)
    ]
    pkg = job.package_dir(tmp_path)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "d.psf").write_text("psf")
    (pkg / "d.pdb").write_text("pdb")
    # submit_job reads the manifest to get the per-chunk ENM scales that decide
    # early-stop eligibility. No manifest => no scales => nothing is skippable (the
    # fail-safe direction), so a package without one must still submit cleanly.
    (pkg / "manifest.json").write_text(
        json.dumps(
            {
                "minimization": {"name": "d_min"},
                "segments": [{"name": s.name, "scale": 0.5} for s in job.segments],
            }
        )
    )
    return job


class FakeSSH:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.commands: list[str] = []

    async def run(self, cmd, check=False, retries=0):
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


def test_sftp_put_reports_transferred_bytes(tmp_path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"x" * (300 * 1024))
    updates = []

    _run(_conn().sftp_put(str(source), "/workspace/payload.bin", on_progress=lambda done, total: updates.append((done, total))))

    assert updates[-1] == (300 * 1024, 300 * 1024)
    assert len(updates) == 2


# ── Sizing ───────────────────────────────────────────────────────────────────


class TestPodSizing:
    def test_spot_is_rejected_when_it_cannot_carry_provider_expiry(self, tmp_path):
        with pytest.raises(rx.RunpodError, match="Interruptible.*disabled"):
            rx.pod_payloads_for(
                _job(tmp_path),
                225_504,
                network_volume_id=VOLUME,
                interruptible=True,
            )

    def test_sizes_from_the_measured_vram_model(self, tmp_path):
        job = _job(tmp_path)
        payload = rx.pod_payload_for(job, 225_504, network_volume_id=VOLUME)
        # gpuTypeIds is a PRIORITY LIST: cheapest first, then every other card that fits.
        # Naming a single GPU is what made RunPod answer 500 "There are no instances
        # currently available" — a network volume pins the datacenter (EU-RO-1), and the
        # one card we asked for simply was not free there.
        assert payload["gpuTypeIds"][0] == "NVIDIA GeForce RTX 4090"
        assert len(payload["gpuTypeIds"]) == 1
        assert len(rx.pod_payloads_for(job, 225_504, network_volume_id=VOLUME)) > 1
        assert payload["networkVolumeId"] == VOLUME
        assert payload["interruptible"] is False
        assert payload["terminateAfter"].endswith("Z")

    def test_never_offers_community_cloud(self, tmp_path):
        """SECURE only (user decision). Community is a pool of third-party hosts — cheaper,
        but variable, and in EU-RO-1 (where the volume pins us) it frequently has NO card at
        all: every COMMUNITY attempt returned 500 "no instances currently available". For an
        unattended overnight run the halved price is not worth the variance."""
        payloads = rx.pod_payloads_for(
            _job(tmp_path), 225_504, network_volume_id=VOLUME
        )
        tiers = [(p["cloudType"], p["interruptible"]) for p in payloads]
        assert all(t == "SECURE" for t, _ in tiers), tiers
        assert ("SECURE", False) in tiers, "on-demand must be reachable for a long run"

    def test_the_wizards_chosen_card_goes_first(self, tmp_path):
        """Otherwise the wizard shows one card and rents another.

        The wizard's table comes from `runpod_select` (live stock, live prices, arch-vs-build
        gate, $/ns AND ns/day). This payload list comes from `plan_execution` — VRAM fit
        against the pinned table, cheapest first. They routinely disagree, and a user who
        deliberately picked a faster card would silently get the cheapest one.
        """
        job = _job(tmp_path)
        job.runpod_gpu_key = "NVIDIA RTX 6000 Ada Generation"
        payloads = rx.pod_payloads_for(job, 225_504, network_volume_id=VOLUME)
        ids = payloads[0]["gpuTypeIds"]
        assert ids[0] == "NVIDIA RTX 6000 Ada Generation"
        assert len(payloads) > 1, "the choice is a PREFERENCE — fallbacks must survive"
        assert len(set(ids)) == len(ids), "the promoted card must not also appear later"

    def test_no_choice_leaves_the_order_untouched(self, tmp_path):
        """The no-regression pin: a job without a chosen card behaves exactly as before."""
        job = _job(tmp_path)
        assert job.runpod_gpu_key is None
        ids = rx.pod_payloads_for(job, 225_504, network_volume_id=VOLUME)[0][
            "gpuTypeIds"
        ]
        assert ids[0] == "NVIDIA GeForce RTX 4090"

    def test_a_card_that_cannot_hold_the_system_is_ignored(self, tmp_path):
        """A stale or impossible choice must not be honoured — renting a card too small for
        the box just OOMs at step 0, having already billed."""
        job = _job(tmp_path)
        job.runpod_gpu_key = "NVIDIA GeForce RTX 4090"
        ids = rx.pod_payloads_for(job, 9_000_000, network_volume_id=VOLUME)[0][
            "gpuTypeIds"
        ]
        assert "NVIDIA GeForce RTX 4090" not in ids, (
            "24 GB cannot hold a 9M-atom system"
        )
        assert ids, "and the launch still has cards to try"

    def test_refuses_a_system_no_gpu_can_hold(self, tmp_path):
        with pytest.raises(RunpodError, match="carve|GBIS"):
            rx.pod_payload_for(_job(tmp_path), 200_000_000, network_volume_id=VOLUME)

    def test_pod_name_is_within_runpods_191_char_limit(self, tmp_path):
        job = _job(tmp_path)
        job.design_name = "x" * 400
        assert (
            len(rx.pod_payload_for(job, 225_504, network_volume_id=VOLUME)["name"])
            <= 191
        )


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
        pid = _run(
            rx.submit_job(
                job,
                tmp_path,
                conn=conn,
                min_name="d_00_min",
                n_atoms=225_504,
                vcpus=32,
            )
        )
        assert pid == 4242
        assert job.runpod_pid == 4242
        assert job.status == MdStatus.running
        assert job.remote_scratch_dir == rx.remote_dir_for(job)

    def test_uses_physical_cores_not_vcpus(self, tmp_path):
        """MEASURED: +p32 on a 16-physical-core pod ran 18.85 ns/day vs +p16's 41.38.
        Oversubscribing SMT HALVES throughput. The chain script must ask for vcpus//2."""
        job = _job(tmp_path)
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(
            rx.submit_job(
                job,
                tmp_path,
                conn=conn,
                min_name="m",
                n_atoms=225_504,
                vcpus=32,
            )
        )
        script = (tmp_path / "md_jobs" / job.job_id / rx.CHAIN_SCRIPT).read_text()
        assert "+p16" in script
        assert "+p32" not in script

    def test_runs_namd_from_the_network_volume(self, tmp_path):
        """The patched sm_89 binary is built once and lives on the volume. Pods are
        disposable; a pod that had to rebuild NAMD would cost more than the run."""
        job = _job(tmp_path)
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="m", n_atoms=225_504, vcpus=8
            )
        )
        script = (tmp_path / "md_jobs" / job.job_id / rx.CHAIN_SCRIPT).read_text()
        assert rx.NAMD_ON_VOLUME in script


# ── Poll ─────────────────────────────────────────────────────────────────────


class TestPoll:
    def test_reports_completed(self, tmp_path):
        job = _job(tmp_path)
        job.remote_scratch_dir = "/workspace/nadoc_jobs/x"
        job.runpod_pid = 5
        conn = _conn(
            {
                "nadoc_status": (0, "completed\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "dead\n", ""),
            }
        )
        st = _run(rx.poll_job(job, conn=conn, now=1010))
        assert st["state"] == "completed"

    def test_reports_the_failing_segment(self, tmp_path):
        job = _job(tmp_path)
        job.remote_scratch_dir = "/w/x"
        job.runpod_pid = 5
        conn = _conn(
            {
                "nadoc_status": (0, "failed:d_02\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "dead\n", ""),
            }
        )
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
        conn = _conn(
            {
                "nadoc_status": (0, "running\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "dead\n", ""),
            }
        )
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
    return {
        "id": "pod1",
        "desiredStatus": status,
        "publicIp": "1.2.3.4",
        "portMappings": {"22": 10341},
        "costPerHr": 0.34,
    }


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
        async def fake_fetch(*_args, **_kwargs):
            return None

        monkeypatch.setattr(rx, "fetch_results", fake_fetch)
        async def fake_connect(self, **kw):
            self._conn = FakeSSH(responses)

        async def fake_close(self):
            self._conn = None

        monkeypatch.setattr(RunpodConnection, "connect", fake_connect)
        monkeypatch.setattr(RunpodConnection, "close", fake_close)

        # These tests own the provision/run/DESTROY orchestration contract, not
        # result-transfer completeness. fetch_results now correctly pauses a job when
        # its strict manifest download is incomplete; isolate teardown here with a
        # successful fetch so FakeSSH does not need to emulate an entire output tree.
        async def fake_fetch_results(*args, **kwargs):
            return True

        monkeypatch.setattr(rx, "fetch_results", fake_fetch_results)

    def test_terminates_the_pod_after_a_successful_run(self, tmp_path, monkeypatch):
        self._patch_conn(
            monkeypatch,
            {
                "setsid": (0, "9\n", ""),
                "nadoc_status": (0, "completed\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "dead\n", ""),
                "nproc": (0, "32\n", ""),
            },
        )
        deleted: list[str] = []
        client = _client_recording(deleted)
        job = _job(tmp_path)

        status = _run(
            rx.run_job_on_pod(
                job,
                tmp_path,
                client=client,
                network_volume_id=VOLUME,
                min_name="d_00_min",
                n_atoms=225_504,
                poll_s=0,
                sleep=_nosleep,
            )
        )
        assert status == MdStatus.completed
        assert deleted == ["/v1/pods/pod1"], "the pod MUST be destroyed"

    def test_terminates_the_pod_when_the_run_fails(self, tmp_path, monkeypatch):
        self._patch_conn(
            monkeypatch,
            {
                "setsid": (0, "9\n", ""),
                "nadoc_status": (0, "failed:d_01\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "dead\n", ""),
                "nproc": (0, "8\n", ""),
            },
        )
        deleted: list[str] = []
        job = _job(tmp_path)
        status = _run(
            rx.run_job_on_pod(
                job,
                tmp_path,
                client=_client_recording(deleted),
                network_volume_id=VOLUME,
                min_name="m",
                n_atoms=225_504,
                poll_s=0,
                sleep=_nosleep,
            )
        )
        assert status == MdStatus.failed
        assert "d_01" in (job.error or "")
        assert deleted == ["/v1/pods/pod1"]

    def test_terminates_the_pod_when_something_raises_mid_run(
        self, tmp_path, monkeypatch
    ):
        """The one that keeps you solvent. If NADOC crashes mid-job, the GPU still dies."""

        async def boom(self, **kw):
            raise RuntimeError("ssh exploded")

        monkeypatch.setattr(RunpodConnection, "connect", boom)
        deleted: list[str] = []
        job = _job(tmp_path)
        with pytest.raises(RuntimeError, match="ssh exploded"):
            _run(
                rx.run_job_on_pod(
                    job,
                    tmp_path,
                    client=_client_recording(deleted),
                    network_volume_id=VOLUME,
                    min_name="m",
                    n_atoms=225_504,
                    poll_s=0,
                    sleep=_nosleep,
                )
            )
        assert deleted == ["/v1/pods/pod1"], "a crash must not leak a billing GPU"

    def test_controller_failure_after_submit_preserves_the_running_pod(
        self, tmp_path, monkeypatch
    ):
        """Once detached NAMD is running, loss of NADOC is not authority to kill it."""
        self._patch_conn(monkeypatch, {"nproc": (0, "8\n", "")})

        async def submitted(*args, **kwargs):
            args[0].runpod_pid = 9

        async def controller_lost(*args, **kwargs):
            raise RuntimeError("controller connection vanished")

        monkeypatch.setattr(rx, "submit_job", submitted)
        monkeypatch.setattr(rx, "_supervise_run", controller_lost)
        deleted: list[str] = []
        job = _job(tmp_path)
        with pytest.raises(RuntimeError, match="controller connection vanished"):
            _run(
                rx.run_job_on_pod(
                    job,
                    tmp_path,
                    client=_client_recording(deleted),
                    network_volume_id=VOLUME,
                    min_name="m",
                    n_atoms=225_504,
                    poll_s=0,
                    sleep=_nosleep,
                )
            )
        assert deleted == []
        assert job.runpod_terminate_after

    def test_a_reclaimed_pod_becomes_resumable_not_failed(self, tmp_path, monkeypatch):
        """An interruptible pod vanishing is the EXPECTED case. The volume holds every
        completed step, so this is 'paused, resume me' — not 'failed, start over'."""
        self._patch_conn(
            monkeypatch,
            {
                "setsid": (0, "9\n", ""),
                "nadoc_status": (0, "running\n", ""),
                "nadoc_heartbeat": (0, "1\n", ""),  # ancient => stale
                "kill -0": (0, "dead\n", ""),
                "nproc": (0, "8\n", ""),
            },
        )
        deleted: list[str] = []
        job = _job(tmp_path)
        status = _run(
            rx.run_job_on_pod(
                job,
                tmp_path,
                client=_client_recording(deleted),
                network_volume_id=VOLUME,
                min_name="m",
                n_atoms=225_504,
                poll_s=0,
                sleep=_nosleep,
            )
        )
        assert status == MdStatus.paused
        assert job.resumable is True
        assert deleted == [], "provider expiry preserves checkpoint-safe interruptions"
        assert job.runpod_terminate_after


async def _nosleep(_):
    return None


class TestTierAEarlyStopGate:
    """Tier-A early-stop is what makes a big ladder affordable — so its failure mode is
    a BUDGET failure, not a quality failure.

    The evaluator fails safe to HOLD (never skip) when it can't measure base-pairing.
    That is right for the science and ruinous for the wallet: HOLD means the full
    9.6M-step ladder, ~55 h, ~$41 on a secure pod. So a pod that cannot import
    MDAnalysis must REFUSE to start, not quietly run the expensive path.
    """

    def _tier_a_job(self, tmp_path):
        """A job with a real CHUNKED stage — the only shape early-stop can act on.

        A stage is a set of `_pNN` chunks sharing a base name. A single-chunk stage has
        nothing after it to bridge, so it is correctly never eligible; the plain `_job`
        fixture (d_01, d_02) is exactly that and would render no early-stop block at all.
        """
        job = _job(tmp_path)
        job.early_stop_relax = True
        job.early_stop_tier = "A"
        job.segments = [
            MdSegmentStatus(
                name=f"d_01_k0p5_p{p}", stage="relax", percent=float(p), steps=100
            )
            for p in (10, 50, 100)
        ]
        (job.package_dir(tmp_path) / "manifest.json").write_text(
            json.dumps(
                {
                    "minimization": {"name": "d_min"},
                    "segments": [{"name": s.name, "scale": 0.5} for s in job.segments],
                }
            )
        )
        return job

    def test_stages_the_evaluators_and_enables_early_stop_in_the_script(self, tmp_path):
        job = self._tier_a_job(tmp_path)
        conn = _conn(
            {"setsid": (0, "7\n", ""), "import MDAnalysis": (0, "2.7.0\n", "")}
        )
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )
        script = (job.job_dir(tmp_path) / rx.CHAIN_SCRIPT).read_text()
        assert "nadoc_cutoff_eval.py" in script
        assert "nadoc_health_eval.py" in script, "Tier A must run the WC health step"

    def test_refuses_to_launch_when_the_pod_cannot_import_mdanalysis(self, tmp_path):
        """The $33 test. A silent fallthrough here bills the full ladder."""
        job = self._tier_a_job(tmp_path)
        conn = _conn(
            {
                "import MDAnalysis": (
                    1,
                    "",
                    "ModuleNotFoundError: No module named 'MDAnalysis'",
                ),
                "pip install": (1, "", "network unreachable"),
            }
        )
        with pytest.raises(rx.MdAnalysisMissing):
            _run(
                rx.submit_job(
                    job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
                )
            )

    def test_installs_mdanalysis_when_the_image_lacks_it(self, tmp_path):
        """The pytorch image ships numpy+scipy but not MDAnalysis; a ~30 s pip fixes it."""
        job = self._tier_a_job(tmp_path)
        calls = {"n": 0}

        class _Conn(RunpodConnection):
            async def run(self, cmd, timeout=60.0, retries=0):
                if "import MDAnalysis" in cmd:
                    calls["n"] += 1
                    # Absent on the first probe, present once pip has run.
                    return (
                        _R(1, "", "ModuleNotFoundError")
                        if calls["n"] == 1
                        else _R(0, "2.7.0", "")
                    )
                if "setsid" in cmd:
                    return _R(0, "9\n", "")
                return _R(0, "", "")

        conn = _Conn(host="h", port=1, pod_id="p1")
        conn._conn = FakeSSH()  # noqa: SLF001
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )
        assert calls["n"] == 2, "must re-probe after installing, not assume pip worked"

    def test_health_is_staged_and_probed_even_when_early_stop_is_off(self, tmp_path):
        job = _job(tmp_path)  # early_stop_relax defaults False
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )
        script = (job.job_dir(tmp_path) / rx.CHAIN_SCRIPT).read_text()
        assert "nadoc_cutoff_eval.py" not in script
        assert any("MDAnalysis" in c for c in conn._conn.commands)  # noqa: SLF001
        assert "nadoc_live_health.py" in script


class _R:
    def __init__(self, rc, stdout, stderr):
        self.rc, self.stdout, self.stderr = rc, stdout, stderr


class TestStagingReusesTheVolume:
    """The staging target is the NETWORK VOLUME, so it OUTLIVES the pod.

    Re-uploading is not free: the 1.9M-atom 3x6x400 package is 1.21 GB, ~15 min of
    BILLABLE pod time at domestic upstream speed before NAMD runs a single step. A
    relaunch after a failed gate (or the production child of the same job) must reuse
    what is already there.
    """

    def test_skips_files_already_on_the_volume_at_the_same_size(self, tmp_path):
        job = _job(tmp_path)
        sent: list[str] = []

        class _Conn(RunpodConnection):
            async def run(self, cmd, timeout=60.0, retries=0):
                if "find . -type f" in cmd:
                    # Everything already present, at its true local size.
                    pkg = job.package_dir(tmp_path)
                    lines = [
                        f"{p.stat().st_size} {rel}"
                        for p, rel in __import__(
                            "backend.core.md_executor", fromlist=["x"]
                        ).stage_plan(pkg)
                    ]
                    return _R(0, "\n".join(lines), "")
                if "setsid" in cmd:
                    return _R(0, "3\n", "")
                return _R(0, "", "")

            async def sftp_put(self, local, remote):
                sent.append(remote)

        conn = _Conn(host="h", port=1, pod_id="p1")
        conn._conn = FakeSSH()  # noqa: SLF001
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )
        # The small generated/helper scripts are always re-sent — the chain script encodes
        # THIS run's kill-switch and early-stop wiring, the resume writer is a few KB, and
        # the live-metrics collector is refreshed so a stale copy on the volume can never
        # outlive a change to NADOC's own collector code.
        # The point of this test is that no PACKAGE file (the 1.21 GB) is re-uploaded.
        always = (
            rx.CHAIN_SCRIPT,
            rx.RESUME_CONF_NAME,
            rx.SETTLE_RETARGET_NAME,
            rx.LIVE_METRICS_NAME,
            "md_health.py",
            "nadoc_live_health.py",
        )
        package_files = [p for p in sent if not p.endswith(always)]
        assert package_files == [], package_files

    def test_reuploads_a_truncated_file(self, tmp_path):
        """Size mismatch => re-send. A partial transfer must not be mistaken for done."""
        job = _job(tmp_path)
        sent: list[str] = []

        class _Conn(RunpodConnection):
            async def run(self, cmd, timeout=60.0, retries=0):
                if "find . -type f" in cmd:
                    return _R(0, "1 d.psf", "")  # 1 byte — truncated
                if "setsid" in cmd:
                    return _R(0, "3\n", "")
                return _R(0, "", "")

            async def sftp_put(self, local, remote):
                sent.append(remote)

        conn = _Conn(host="h", port=1, pod_id="p1")
        conn._conn = FakeSSH()  # noqa: SLF001
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )
        assert any(p.endswith("d.psf") for p in sent), (
            "a truncated file must be re-sent"
        )

    def test_a_failed_listing_reuploads_everything(self, tmp_path):
        """Fail-safe: if we cannot tell what is there, send it. Wasting $0.19 beats
        running NAMD against a package with a missing file."""
        job = _job(tmp_path)
        sent: list[str] = []

        class _Conn(RunpodConnection):
            async def run(self, cmd, timeout=60.0, retries=0):
                if "find . -type f" in cmd:
                    return _R(1, "", "no such dir")
                if "setsid" in cmd:
                    return _R(0, "3\n", "")
                return _R(0, "", "")

            async def sftp_put(self, local, remote):
                sent.append(remote)

        conn = _Conn(host="h", port=1, pod_id="p1")
        conn._conn = FakeSSH()  # noqa: SLF001
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )
        assert any(p.endswith("d.psf") for p in sent)


class TestProductionChildSeedsFromParentOnTheVolume:
    """A production child shares its parent's structure files (build_replica_package
    HARDLINKS the PSF/PDB/forcefield). Those are already on the network volume under the
    parent's job_id, so hand them across with a `cp` on the volume instead of re-uploading
    1.21 GB over domestic ADSL — 15 min of pod time on the very run where wall-clock is
    nanoseconds.
    """

    def _child(self, tmp_path):
        job = _job(tmp_path)
        job.parent_job_id = "PARENT123456"
        job.run_kind = "production"
        return job

    def test_copies_the_parents_identical_files_instead_of_uploading_them(
        self, tmp_path
    ):
        job = self._child(tmp_path)
        sent: list[str] = []
        cmds: list[str] = []

        class _Conn(RunpodConnection):
            async def run(self, cmd, timeout=60.0, retries=0):
                cmds.append(cmd)
                if "find . -type f" in cmd and "PARENT123456" in cmd:
                    pkg = job.package_dir(tmp_path)
                    lines = [
                        f"{p.stat().st_size} {rel}"
                        for p, rel in md_executor.stage_plan(pkg)
                    ]
                    return _R(0, "\n".join(lines), "")
                if "find . -type f" in cmd:  # the child's own dir, post-copy
                    pkg = job.package_dir(tmp_path)
                    lines = [
                        f"{p.stat().st_size} {rel}"
                        for p, rel in md_executor.stage_plan(pkg)
                    ]
                    return _R(0, "\n".join(lines), "")
                if "setsid" in cmd:
                    return _R(0, "11\n", "")
                return _R(0, "", "")

            async def sftp_put(self, local, remote):
                sent.append(remote)

        conn = _Conn(host="h", port=1, pod_id="p1")
        conn._conn = FakeSSH()  # noqa: SLF001
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )

        assert any("cp -n" in c and "PARENT123456" in c for c in cmds), (
            "must copy from the parent's dir on the volume"
        )
        always = (
            rx.CHAIN_SCRIPT,
            rx.RESUME_CONF_NAME,
            rx.SETTLE_RETARGET_NAME,
            rx.LIVE_METRICS_NAME,
            "md_health.py",
            "nadoc_live_health.py",
        )
        assert [p for p in sent if not p.endswith(always)] == [], "no package re-upload"

    def test_never_drags_across_the_parents_output_or_sentinels(self, tmp_path):
        """THE hazard. A blanket `cp -r` of the parent's dir would bring its
        output/*.coor and chain sentinels — and the chain script's idempotent skip-guard
        would then declare the child's segments ALREADY COMPLETE and run NOTHING,
        producing an empty production run that reports success."""
        job = self._child(tmp_path)
        cmds: list[str] = []

        class _Conn(RunpodConnection):
            async def run(self, cmd, timeout=60.0, retries=0):
                cmds.append(cmd)
                if "find . -type f" in cmd and "PARENT123456" in cmd:
                    # The parent's dir ALSO holds completed outputs and sentinels.
                    pkg = job.package_dir(tmp_path)
                    lines = [
                        f"{p.stat().st_size} {rel}"
                        for p, rel in md_executor.stage_plan(pkg)
                    ]
                    lines += [
                        "999 output/d_01.coor",
                        "5 nadoc_status",
                        "12 nadoc_chain.out",
                    ]
                    return _R(0, "\n".join(lines), "")
                if "setsid" in cmd:
                    return _R(0, "11\n", "")
                return _R(0, "", "")

            async def sftp_put(self, local, remote):
                pass

        conn = _Conn(host="h", port=1, pod_id="p1")
        conn._conn = FakeSSH()  # noqa: SLF001
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )

        copies = " ".join(c for c in cmds if "cp -n" in c)
        assert "output/" not in copies, (
            "a copied .coor would make the child SKIP its work"
        )
        assert "nadoc_status" not in copies
        assert "nadoc_chain.out" not in copies

    def test_a_relaxation_job_never_seeds_from_anything(self, tmp_path):
        job = _job(tmp_path)  # no parent_job_id
        cmds: list[str] = []

        class _Conn(RunpodConnection):
            async def run(self, cmd, timeout=60.0, retries=0):
                cmds.append(cmd)
                return _R(0, "11\n", "") if "setsid" in cmd else _R(0, "", "")

            async def sftp_put(self, local, remote):
                pass

        conn = _Conn(host="h", port=1, pod_id="p1")
        conn._conn = FakeSSH()  # noqa: SLF001
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )
        assert not any("cp -n" in c for c in cmds)


class TestTheJobRecordSurvivesACrashedLauncher:
    """The launcher's `finally` is the ONLY thing that destroys a pod. If it dies, the
    pod bills on — NAMD is detached (setsid, output on the network volume) so the run
    itself carries on perfectly well, and nothing is left alive to turn the meter off.

    Recovery therefore depends entirely on the job record naming the pod. It didn't:
    runpod_executor never called job.save(), so a crashed launcher left an orphaned,
    billing pod that nothing could even NAME, let alone reap or resume. This happened
    for real (a transient DNS failure mid-poll).
    """

    def test_submit_persists_the_pod_id_pid_and_remote_dir(self, tmp_path):
        job = _job(tmp_path)
        job.runpod_pod_id = "POD123"
        conn = _conn({"setsid": (0, "4242\n", "")})
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="d_min", n_atoms=225_504, vcpus=8
            )
        )

        # Re-read from DISK — an in-memory field is worth nothing to a new process.
        reloaded = MdJob.load(job.job_id, tmp_path)
        assert reloaded.runpod_pod_id == "POD123", (
            "a pod nobody can name is a pod nobody can kill"
        )
        assert reloaded.runpod_pid == 4242
        assert reloaded.remote_scratch_dir == rx.remote_dir_for(job)
        assert reloaded.status == MdStatus.running


class TestOvernightSafety:
    def test_the_chain_script_carries_a_hard_kill_switch(self, tmp_path):
        """An UNATTENDED overnight run must not be able to bill until morning. The stall
        watchdog kills a HUNG NAMD (no log output for 30 min), but a run that is merely
        slower than predicted would keep going. The kill-switch is the backstop.

        The cap is now BUDGET-DERIVED (lifetime_for_budget), passed explicitly by the
        launcher from the rate of the pod we actually got — not a hardcoded default. So
        the guard renders whenever a lifetime is supplied."""
        job = _job(tmp_path)
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(
            rx.submit_job(
                job,
                tmp_path,
                conn=conn,
                min_name="m",
                n_atoms=225_504,
                vcpus=16,
                max_lifetime_s=16 * 3600,
            )
        )
        script = (tmp_path / "md_jobs" / job.job_id / rx.CHAIN_SCRIPT).read_text()
        assert "LIFETIME_GUARD" in script
        assert str(16 * 3600) in script

    def test_no_lifetime_means_no_guard(self, tmp_path):
        """The default is None, not a hardcoded ceiling: a caller that omits the cap gets
        no guard. Production never does — the launcher always derives one from the budget —
        so this only documents that the backstop is opt-in at the submit_job boundary."""
        job = _job(tmp_path)
        conn = _conn({"setsid": (0, "1\n", "")})
        _run(
            rx.submit_job(
                job, tmp_path, conn=conn, min_name="m", n_atoms=225_504, vcpus=16
            )
        )
        script = (tmp_path / "md_jobs" / job.job_id / rx.CHAIN_SCRIPT).read_text()
        assert "LIFETIME_GUARD" not in script


class TestAdoptAlsoAlwaysTerminates:
    """Inheriting a run must carry the SAME obligation as starting one.

    A pod left up by a dev-server reload is only safe to leave if the next process both
    picks up watching it AND destroys it at the end. If adopt could return with the pod
    alive, "don't tear down on reload" would just be a slower leak.
    """

    def _patch_conn(self, monkeypatch, responses):
        async def fake_fetch(*_args, **_kwargs):
            return None

        monkeypatch.setattr(rx, "fetch_results", fake_fetch)
        async def fake_connect(self, **kw):
            self._conn = FakeSSH(responses)

        async def fake_close(self):
            self._conn = None

        monkeypatch.setattr(RunpodConnection, "connect", fake_connect)
        monkeypatch.setattr(RunpodConnection, "close", fake_close)

        async def fake_fetch_results(*args, **kwargs):
            return True

        monkeypatch.setattr(rx, "fetch_results", fake_fetch_results)

    def _job_on_pod(self, tmp_path, pid=9):
        job = _job(tmp_path)
        job.execution_target = "runpod"
        job.runpod_pod_id = "pod1"
        job.runpod_pid = pid
        job.remote_scratch_dir = "/workspace/nadoc_jobs/x"
        return job

    def test_destroys_the_pod_when_the_adopted_run_finishes(
        self, tmp_path, monkeypatch
    ):
        self._patch_conn(
            monkeypatch,
            {
                "nadoc_status": (0, "completed\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "", ""),
            },
        )
        deleted: list[str] = []
        job = self._job_on_pod(tmp_path)
        status = _run(
            rx.reattach_job_on_pod(
                job,
                tmp_path,
                client=_client_recording(deleted),
                poll_s=0,
                sleep=_nosleep,
            )
        )
        assert status == MdStatus.completed
        assert deleted == ["/v1/pods/pod1"], "an adopted pod MUST still be destroyed"

    def test_destroys_the_pod_when_the_adopted_run_failed(self, tmp_path, monkeypatch):
        self._patch_conn(
            monkeypatch,
            {
                "nadoc_status": (0, "failed:d_01\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "", ""),
            },
        )
        deleted: list[str] = []
        job = self._job_on_pod(tmp_path)
        _run(
            rx.reattach_job_on_pod(
                job,
                tmp_path,
                client=_client_recording(deleted),
                poll_s=0,
                sleep=_nosleep,
            )
        )
        assert deleted == ["/v1/pods/pod1"]

    def test_never_relaunches_a_live_chain(self, tmp_path, monkeypatch):
        """Two chains on one GPU means two NAMDs writing the same restart files. Adopt
        RESUMES watching; it must never call submit_job."""
        self._patch_conn(
            monkeypatch,
            {
                "nadoc_status": (0, "completed\n", ""),
                "nadoc_heartbeat": (0, "1000\n", ""),
                "kill -0": (0, "", ""),
            },
        )
        called = {"n": 0}

        async def boom(*a, **kw):
            called["n"] += 1

        monkeypatch.setattr(rx, "submit_job", boom)
        job = self._job_on_pod(tmp_path)
        _run(
            rx.reattach_job_on_pod(
                job, tmp_path, client=_client_recording([]), poll_s=0, sleep=_nosleep
            )
        )
        assert called["n"] == 0

    def test_refuses_a_job_with_no_pod(self, tmp_path):
        job = _job(tmp_path)
        job.runpod_pod_id = None
        with pytest.raises(RunpodError, match="no pod"):
            _run(rx.reattach_job_on_pod(job, tmp_path, client=_client_recording([])))

    def test_refuses_an_already_destroyed_pod(self, tmp_path):
        """A vanished pod must raise, not be mistaken for an adopted one — otherwise the
        supervisor sits polling a machine that no longer exists."""

        def handler(req):
            return httpx.Response(
                200, json={**_pod_json(), "desiredStatus": "TERMINATED"}
            )

        client = RunpodClient("k", transport=httpx.MockTransport(handler))
        job = self._job_on_pod(tmp_path)
        with pytest.raises(RunpodError, match="destroyed"):
            _run(rx.reattach_job_on_pod(job, tmp_path, client=client))


class TestOpenPodConnection:
    """The read-only side-channel used to pull a display snapshot off a LIVE pod.

    The property that matters is a negative one: this must never destroy the pod. The
    obvious implementations — ``client.pod()`` or ``client.adopt()`` — both terminate in
    their ``finally``, so reaching for either would kill the paid run the caller was only
    trying to look at.
    """

    def _patch_conn(self, monkeypatch, opened):
        async def fake_connect(self, **kw):
            opened.append((self.host, self.port, self.pod_id))
            self._conn = FakeSSH()  # noqa: SLF001

        monkeypatch.setattr(RunpodConnection, "connect", fake_connect)

    def test_borrows_the_pod_without_destroying_it(self, tmp_path, monkeypatch):
        deleted, opened = [], []
        self._patch_conn(monkeypatch, opened)
        job = _job(tmp_path)
        job.runpod_pod_id = "p1"

        conn = _run(rx.open_pod_connection(job, client=_client_recording(deleted)))
        # Host/port/id all come from the API's answer, not from the job record — the
        # job only supplies which pod to ask about.
        assert opened == [("1.2.3.4", 10341, "pod1")]
        assert deleted == [], "a snapshot fetch must not terminate the running pod"
        # The caller owns it — nothing here closed it on their behalf.
        assert conn.pod_id == "pod1"

    def test_a_job_with_no_pod_is_refused(self, tmp_path):
        job = _job(tmp_path)
        job.runpod_pod_id = None
        with pytest.raises(RunpodError, match="no pod"):
            _run(rx.open_pod_connection(job, client=_client_recording([])))

    def test_a_pod_that_is_not_running_is_refused(self, tmp_path, monkeypatch):
        """Its filesystem is gone; SSH would hang rather than fail fast."""
        job = _job(tmp_path)
        job.runpod_pod_id = "p1"

        def handler(req):
            return httpx.Response(200, json={**_pod_json(), "desiredStatus": "EXITED"})

        client = RunpodClient("k", transport=httpx.MockTransport(handler))
        with pytest.raises(RunpodError, match="not running"):
            _run(rx.open_pod_connection(job, client=client))

    def test_a_destroyed_pod_reads_as_a_finished_run(self, tmp_path):
        """404 is the ORDINARY end of every run — it must not surface as raw API text."""
        job = _job(tmp_path)
        job.runpod_pod_id = "gone"
        client = RunpodClient(
            "k",
            transport=httpx.MockTransport(
                lambda req: httpx.Response(404, json={"error": "pod not found"})
            ),
        )
        with pytest.raises(RunpodError, match="no longer exists"):
            _run(rx.open_pod_connection(job, client=client))

@pytest.fixture(autouse=True)
def _isolate_saved_runpod_s3_credentials(monkeypatch):
    """Unit fakes must not change behavior because the developer has real S3 keys."""
    from backend.core import runpod_s3

    monkeypatch.setattr(runpod_s3, "resolve_credentials", lambda: None)
