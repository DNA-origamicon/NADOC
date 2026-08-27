import json

import pytest

from backend.core.oxdna_protocol import build_relaxation_stages
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus, new_oxdna_job
from backend.core.runpod_oxdna import (
    CampaignLedger,
    GPU_TARGETS,
    OXDNA_REV,
    REMOTE_ROOT,
    RunpodOxdnaError,
    manifest,
    render_build_script,
    render_chain_script,
    stage_inputs,
    target_for_gpu,
    validate_fetched_result,
)


def test_gpu_targets_match_alpine_architectures():
    assert {(t.label, t.cuda_arch) for t in GPU_TARGETS} == {
        ("H200", "90"),
        ("RTX PRO 6000", "120"),
    }
    with pytest.raises(RunpodOxdnaError, match="unsupported GPU"):
        target_for_gpu("NVIDIA A40")


def test_build_script_is_pinned_adaptive_and_persistent():
    script = render_build_script("90", "/workspace/adaptive.patch")
    assert OXDNA_REV in script
    assert "CMAKE_CUDA_ARCHITECTURES=90" in script
    assert "/usr/local/cuda-12.8/bin" in script
    assert "git -C \"$source_dir\" apply /workspace/adaptive.patch" in script
    assert f"{REMOTE_ROOT}/engines/" in script
    assert "build-flavor" in script and "adaptive-memory" in script
    assert 'mkdir -p "$install/bin" "$install/lib"\ninstall -m' in script


def test_build_script_rejects_unplanned_architecture():
    with pytest.raises(RunpodOxdnaError, match="sm_89"):
        render_build_script("89", "/tmp/p.patch")


def test_stage_inputs_chain_previous_checkpoint(tmp_path):
    specs = build_relaxation_stages(mc_steps=10, md_relax_steps=20, equil_steps=30)
    inputs = stage_inputs(tmp_path, specs, "/workspace/nadoc_oxdna/jobs/j1")
    assert "conf_file = /workspace/nadoc_oxdna/jobs/j1/conf.dat" in inputs[
        "1_mc_relax/input.txt"
    ]
    assert (
        "conf_file = /workspace/nadoc_oxdna/jobs/j1/1_mc_relax/last_conf.dat"
        in inputs["2_md_relax/input.txt"]
    )
    assert "adaptive_neighbor_list = true" in inputs["2_md_relax/input.txt"]
    assert "adaptive_compact_cells = true" in inputs["2_md_relax/input.txt"]


def test_chain_is_restartable_and_reports_terminal_state():
    specs = build_relaxation_stages(mc_steps=10, md_relax_steps=20, equil_steps=30)
    script = render_chain_script("j1", specs, "120")
    assert "adaptive-sm120/bin/oxDNA" in script
    assert "if [ ! -s 1_mc_relax/last_conf.dat ]; then" in script
    assert "failed:2_md_relax:$rc" in script
    assert "echo completed > nadoc_status" in script
    assert "nadoc_heartbeat" in script


def test_manifest_records_reproducible_engine_and_target():
    specs = build_relaxation_stages(mc_steps=1, md_relax_steps=2, equil_steps=3)
    result = manifest("j1", specs, GPU_TARGETS[0])
    assert result["source_revision"] == OXDNA_REV
    assert result["engine"] == "oxdna-adaptive-memory"
    assert result["cuda_arch"] == "90"
    assert [s["steps"] for s in result["stages"]] == [1, 2, 3]


def test_campaign_ledger_caps_cumulative_attempts(tmp_path):
    ledger = CampaignLedger(tmp_path / "spend.json", cap_usd=5.0)
    ledger.authorize(2.0, 3600)
    ledger.open_pod("p1", 2.0, now=100.0)
    ledger.close_pod("p1", now=1900.0)  # $1
    ledger.open_pod("p2", 4.0, now=2000.0)
    assert ledger.spent_usd(now=3800.0) == pytest.approx(3.0)
    with pytest.raises(RunpodOxdnaError, match="campaign remainder"):
        ledger.authorize(4.0, 1801)
    ledger.close_pod("p2", now=3800.0)
    assert json.loads((tmp_path / "spend.json").read_text())[1]["ended_at"] == 3800.0


def test_campaign_ledger_corruption_fails_closed(tmp_path):
    path = tmp_path / "spend.json"
    path.write_text("not json")
    with pytest.raises(RunpodOxdnaError, match="cannot trust"):
        CampaignLedger(path).remaining_usd()


def test_budgeted_lifetime_uses_campaign_remainder(tmp_path):
    from backend.core.runpod_oxdna import budgeted_lifetime_s

    ledger = CampaignLedger(tmp_path / "spend.json", cap_usd=5.0)
    ledger.open_pod("old", 2.0, now=0.0)
    ledger.close_pod("old", now=1800.0)  # $1 already spent
    assert budgeted_lifetime_s(ledger, 4.0, requested_s=5000) == 3600


def test_fetched_result_oracle_requires_adaptive_cuda_evidence(tmp_path):
    specs = build_relaxation_stages(mc_steps=1, md_relax_steps=2, equil_steps=3)[1:2]
    (tmp_path / "nadoc_status").write_text("completed\n")
    stage = tmp_path / specs[0].name
    stage.mkdir()
    (stage / "last_conf.dat").write_text("t = 0\nb = 1 1 1\nE = 0 0 0\nparticle\n")
    (stage / "stderr.log").write_text(
        "CUDA adaptive neighbour telemetry: 10 observed max, 64 capacity\n"
        "Total Running Time: 0.1 s, per step: 1 ms\n"
    )
    result = validate_fetched_result(tmp_path, specs)
    assert result["stages"][0]["particles"] == 1
    (stage / "stderr.log").write_text("Total Running Time: 0.1 s\n")
    with pytest.raises(RunpodOxdnaError, match="lacks adaptive CUDA telemetry"):
        validate_fetched_result(tmp_path, specs)


def test_oxdna_job_loads_old_schema_with_local_execution_default(tmp_path):
    specs = build_relaxation_stages(mc_steps=1, md_relax_steps=2, equil_steps=3)
    job = new_oxdna_job("old", [spec.to_status() for spec in specs])
    job.save(tmp_path)
    path = job.job_dir(tmp_path) / "job.json"
    raw = json.loads(path.read_text())
    for key in (
        "execution_target", "runpod_pod_id", "runpod_gpu_key",
        "runpod_budget_usd", "runpod_final_cost_usd",
    ):
        raw.pop(key)
    path.write_text(json.dumps(raw))
    loaded = OxdnaJob.load(job.job_id, tmp_path)
    assert loaded.status is OxdnaStatus.queued
    assert loaded.execution_target == "local"
    assert loaded.runpod_pod_id is None
