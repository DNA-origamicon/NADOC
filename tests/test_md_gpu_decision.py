"""Phase 2 — GPU-resident fallback decision: pause-and-ask instead of silent downgrade.

Covers the testable helpers wired into the runner: the decision payload builder, the
policy switch, the probe-failure handler (pause vs auto-downgrade), and resolve.
"""

from __future__ import annotations

from pathlib import Path

from backend.core import md_vram as V
from backend.core import namd_runner as R
from backend.core.md_job import MdJob, MdStatus

_TILELIST_LOG = (
    "TCL: Running for 2400 steps\n"
    "FATAL ERROR: CUDA error cudaStreamSynchronize(stream) in file "
    "src/CudaTileListKernel.cu, function buildTileLists, line 1141\n"
    " on Pe 8 device 0: an illegal memory access was encountered\n"
)


def _job(tmp: Path) -> MdJob:
    return MdJob(
        job_id="t1",
        design_name="d",
        protocol="mgh_slow_release",
        status=MdStatus.running,
        created_at=0.0,
        package_subdir="package/pkg",
        name_stem="d",
    )


# ── decision payload builder ──────────────────────────────────────────────────


def test_build_gpu_fallback_decision_payload():
    fux = V.describe_failure(_TILELIST_LOG)  # gpu_error, retry_other_binary True
    d = R.build_gpu_fallback_decision(fux)
    assert d["gate"] == "gpu_resident"
    assert d["severity"] == "decision"
    assert d["retry_hint"] is True  # newer build would fix it
    assert d["degrade_target"] == "offload"
    ids = [o["id"] for o in d["options"]]
    assert ids == ["offload", "cancel"]
    assert any(o["primary"] for o in d["options"])
    # jargon stays out of the headline, raw cause kept aside for logs
    assert "buildTileLists" not in d["message"] and "buildTileLists" not in d["title"]
    assert "buildTileLists" in d["technical_reason"]
    # the check-trail ends on the failed step
    assert d["checks"][-1]["ok"] is False


def test_build_decision_host_limit_no_retry_hint():
    fux = V.describe_failure(
        "FATAL ERROR: CUDA error cudaHostAlloc(...) reallocate_host_T: out of memory"
    )
    assert R.build_gpu_fallback_decision(fux)["retry_hint"] is False


# ── policy switch ─────────────────────────────────────────────────────────────


def test_gpu_fallback_policy_default_is_ask(monkeypatch):
    monkeypatch.delenv("NADOC_GPU_FALLBACK", raising=False)
    assert R.gpu_fallback_policy() == "ask"


def test_gpu_fallback_policy_auto_offload(monkeypatch):
    monkeypatch.setenv("NADOC_GPU_FALLBACK", "auto_offload")
    assert R.gpu_fallback_policy() == "auto_offload"


# ── probe-failure handler: pause vs auto ──────────────────────────────────────


def test_handle_probe_failure_ask_pauses_with_decision(tmp_path, monkeypatch):
    monkeypatch.delenv("NADOC_GPU_FALLBACK", raising=False)
    ws = tmp_path
    job = _job(ws)
    pkg = job.package_dir(ws)
    pkg.mkdir(parents=True)
    (pkg / "_gpures_probe.log").write_text(_TILELIST_LOG)

    proceed = R.handle_resident_probe_failure(job, pkg, ws)

    assert proceed is False  # caller must exit cleanly
    assert job.status == MdStatus.paused
    assert job.decision and job.decision["gate"] == "gpu_resident"
    assert job.decision["retry_hint"] is True
    # persisted, so the API/websocket can surface it
    assert MdJob.load("t1", ws).decision["gate"] == "gpu_resident"


def test_handle_probe_failure_per_job_policy_beats_env(tmp_path, monkeypatch):
    # A per-job "auto_offload" (from the launch toggle, stored in prep_params) proceeds
    # even when the env default is "ask" — the setting is a real per-run override.
    monkeypatch.delenv("NADOC_GPU_FALLBACK", raising=False)
    ws = tmp_path
    job = _job(ws)
    job.prep_params = {"gpu_fallback_policy": "auto_offload"}
    pkg = job.package_dir(ws)
    pkg.mkdir(parents=True)
    (pkg / "_gpures_probe.log").write_text(_TILELIST_LOG)
    assert R.handle_resident_probe_failure(job, pkg, ws) is True
    assert job.decision is None


def test_handle_probe_failure_per_job_ask_beats_env_auto(tmp_path, monkeypatch):
    # Conversely a per-job "ask" pauses even when the env default is auto_offload.
    monkeypatch.setenv("NADOC_GPU_FALLBACK", "auto_offload")
    ws = tmp_path
    job = _job(ws)
    job.prep_params = {"gpu_fallback_policy": "ask"}
    pkg = job.package_dir(ws)
    pkg.mkdir(parents=True)
    (pkg / "_gpures_probe.log").write_text(_TILELIST_LOG)
    assert R.handle_resident_probe_failure(job, pkg, ws) is False
    assert job.status == MdStatus.paused


def test_handle_probe_failure_auto_offload_proceeds(tmp_path, monkeypatch):
    monkeypatch.setenv("NADOC_GPU_FALLBACK", "auto_offload")
    ws = tmp_path
    job = _job(ws)
    pkg = job.package_dir(ws)
    pkg.mkdir(parents=True)
    (pkg / "_gpures_probe.log").write_text(_TILELIST_LOG)

    proceed = R.handle_resident_probe_failure(job, pkg, ws)

    assert proceed is True  # run continues (legacy behaviour)
    assert job.decision is None
    assert job.status == MdStatus.running


# ── resolve ───────────────────────────────────────────────────────────────────


def test_resolve_cancel_clean_stops(tmp_path):
    ws = tmp_path
    job = _job(ws)
    job.decision = {"gate": "gpu_resident"}
    job.package_dir(ws).mkdir(parents=True)

    R.resolve_gpu_decision(job, "cancel", ws)

    assert job.status == MdStatus.stopped
    assert job.user_stopped is True
    assert job.decision is None
    assert job.error is None  # clean stop, no error box


def test_resolve_offload_downgrades_and_requeues(tmp_path):
    ws = tmp_path
    job = _job(ws)
    job.decision = {"gate": "gpu_resident"}
    pkg = job.package_dir(ws)
    pkg.mkdir(parents=True)
    # a fast segment conf that asks for GPU-resident (what downgrade rewrites)
    (pkg / "s2.conf").write_text(
        "GPUresident on\nrigidBonds all\ntimestep 4\nstepspercycle 20\nrun 1000\n"
        "outputTiming 100\noutputName out/s2\n"
    )

    R.resolve_gpu_decision(job, "offload", ws)

    assert job.decision is None
    assert job.status == MdStatus.running
    # conf no longer requests GPU-resident -> resume will skip the probe entirely
    assert not R._has_gpu_resident(pkg / "s2.conf")


def test_resolve_rejects_unknown_choice(tmp_path):
    job = _job(tmp_path)
    job.decision = {"gate": "gpu_resident"}
    try:
        R.resolve_gpu_decision(job, "bogus", tmp_path)
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── data model round-trip ─────────────────────────────────────────────────────


def test_mdjob_decision_survives_save_load(tmp_path):
    job = _job(tmp_path)
    job.decision = {"gate": "gpu_resident", "severity": "decision", "options": []}
    job.save(tmp_path)
    assert MdJob.load("t1", tmp_path).decision == job.decision
    # default stays None for jobs created before the field existed
    job2 = _job(tmp_path)
    assert job2.decision is None
