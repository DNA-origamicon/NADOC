"""Tests for the simulation hardware Benchmark feature.

Covers the pure decision logic (grids, synthetic-size + cap, pick-best tie-breaks,
extrapolation note, hardware parse), the synthetic-design builder (no undefined
bases — both engines would 400 otherwise), the mocked-runner orchestration
(sequential order, metric extraction, temp-dir cleanup), and the routes
(hardware report + apply writes per-machine metadata).  None of this needs a GPU
or an installed oxDNA/NAMD binary.
"""

from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core import benchmark as bench
from backend.core import benchmark_runner as br
from backend.core import hardware
from backend.core.models import Design, HardwareBenchmark, OxdnaHardwareDefault

client = TestClient(app)


# ── Hardware enumeration (pure parse) ─────────────────────────────────────────────


def test_parse_nvidia_smi_l_multi_gpu():
    text = (
        "GPU 0: NVIDIA RTX A5000 (UUID: GPU-1d2c3b4a-1111-2222-3333-444455556666)\n"
        "GPU 1: NVIDIA GeForce RTX 3090 (UUID: GPU-aabbccdd-7777-8888-9999-000011112222)\n"
    )
    devs = hardware.parse_nvidia_smi_l(text)
    assert [d["index"] for d in devs] == [0, 1]
    assert devs[0]["name"] == "NVIDIA RTX A5000"
    assert devs[1]["uuid"].startswith("GPU-aabbccdd")


def test_parse_nvidia_smi_l_empty_and_garbage():
    assert hardware.parse_nvidia_smi_l("") == []
    assert hardware.parse_nvidia_smi_l("no devices were found\nsome junk line") == []


def test_cpu_thread_ladder_dedup(monkeypatch):
    monkeypatch.setattr("backend.core.hardware.os.cpu_count", lambda: 2)
    assert hardware.cpu_thread_ladder() == [1, 2]  # {2//4=0→1, 2//2=1, 2} → {1,2}
    monkeypatch.setattr("backend.core.hardware.os.cpu_count", lambda: 16)
    assert hardware.cpu_thread_ladder() == [4, 8, 16]


# ── Config grids ──────────────────────────────────────────────────────────────────


def test_oxdna_grid_cpu_plus_per_device():
    devs = [{"index": 0, "name": "A"}, {"index": 1, "name": "B"}]
    grid = bench.oxdna_config_grid(devs)
    assert grid[0].backend == "CPU"
    assert [c.backend for c in grid] == ["CPU", "CUDA", "CUDA"]
    assert [c.device for c in grid[1:]] == ["0", "1"]


def test_oxdna_grid_no_gpu_is_cpu_only():
    grid = bench.oxdna_config_grid([])
    assert len(grid) == 1 and grid[0].backend == "CPU"


def test_namd_grid_ladder_times_targets_with_cpu_only():
    devs = [{"index": 0, "name": "A"}]
    grid = bench.namd_config_grid([4, 8], devs)
    # 2 thread values × (CPU-only + 1 GPU) = 4 configs
    assert len(grid) == 4
    cpu_only = [c for c in grid if c.devices == ""]
    assert len(cpu_only) == 2  # one per thread value
    gpu = [c for c in grid if c.devices == "0"]
    assert {c.threads for c in gpu} == {4, 8}


# ── Synthetic size + cap ──────────────────────────────────────────────────────────


def test_synthetic_plan_hits_target():
    plan = bench.synthetic_bundle_plan(1200, max_nt=50_000)
    # 6 cells × 2 strands × length_bp ≈ 1200 → length_bp 100
    assert plan["length_bp"] == 100
    assert plan["proxy_nucleotides"] == 1200
    assert plan["capped"] is False


def test_synthetic_plan_applies_and_records_cap():
    plan = bench.synthetic_bundle_plan(1_000_000, max_nt=4_000)
    assert plan["capped"] is True
    assert plan["proxy_nucleotides"] <= 4_000 + 2 * len(bench.SIX_HB_CELLS)
    assert plan["requested_nucleotides"] == 1_000_000


def test_synthetic_plan_min_length():
    plan = bench.synthetic_bundle_plan(10, max_nt=50_000)
    assert plan["length_bp"] >= 8


# ── pick-best + tie-breaks ────────────────────────────────────────────────────────


def test_pick_best_oxdna_skips_errored_and_none():
    results = [
        {"backend": "CPU", "device": "0", "steps_per_s": 100.0, "error": None},
        {"backend": "CUDA", "device": "0", "steps_per_s": None, "error": "boom"},
        {"backend": "CUDA", "device": "1", "steps_per_s": 500.0, "error": None},
    ]
    best = bench.pick_best_oxdna(results)
    assert best["backend"] == "CUDA" and best["device"] == "1"


def test_pick_best_oxdna_tie_prefers_cuda():
    results = [
        {"backend": "CPU", "device": "0", "steps_per_s": 200.0, "error": None},
        {"backend": "CUDA", "device": "0", "steps_per_s": 200.0, "error": None},
    ]
    assert bench.pick_best_oxdna(results)["backend"] == "CUDA"


def test_pick_best_oxdna_all_invalid_returns_none():
    assert (
        bench.pick_best_oxdna([{"backend": "CPU", "steps_per_s": 0, "error": None}])
        is None
    )
    assert bench.pick_best_oxdna([]) is None


def test_pick_best_namd_tie_prefers_gpu_then_fewer_threads():
    results = [
        {"threads": 16, "devices": "", "ns_per_day": 5.0, "error": None},
        {"threads": 16, "devices": "0", "ns_per_day": 5.0, "error": None},
        {"threads": 8, "devices": "0", "ns_per_day": 5.0, "error": None},
    ]
    best = bench.pick_best_namd(results)
    assert best["devices"] == "0" and best["threads"] == 8


def test_pick_best_namd_max_throughput_wins_over_tiebreak():
    results = [
        {"threads": 4, "devices": "0", "ns_per_day": 12.0, "error": None},
        {"threads": 16, "devices": "", "ns_per_day": 9.0, "error": None},
    ]
    assert bench.pick_best_namd(results)["ns_per_day"] == 12.0


def test_extrapolate_note_flags_cap():
    capped = bench.extrapolate_note(4000, 40000, capped=True)
    assert "capped" in capped and "40000" in capped
    uncapped = bench.extrapolate_note(1200, 1200, capped=False)
    assert "capped" not in uncapped


# ── Metadata round-trip ───────────────────────────────────────────────────────────


def test_hardware_defaults_round_trip():
    d = Design()
    d.metadata.hardware_defaults["mybox"] = HardwareBenchmark(
        oxdna=OxdnaHardwareDefault(backend="CUDA", device="0", steps_per_s=4200.0),
    )
    restored = Design.from_json(d.to_json())
    slot = restored.metadata.hardware_defaults["mybox"]
    assert slot.oxdna.backend == "CUDA"
    assert slot.oxdna.steps_per_s == 4200.0
    assert slot.namd is None


def test_old_design_loads_without_hardware_defaults():
    d = Design()
    # Simulate a pre-feature file: metadata with no hardware_defaults key.
    js = d.to_json()
    assert Design.from_json(js).metadata.hardware_defaults == {}


# ── Synthetic design builder ──────────────────────────────────────────────────────


def test_build_synthetic_design_has_no_undefined_bases():
    from backend.physics.oxdna_interface import count_undefined_bases

    design, plan = br.build_synthetic_design(600, max_nt=50_000)
    undefined, total = count_undefined_bases(design)
    assert total > 0
    assert undefined == 0, f"{undefined}/{total} undefined bases would 400 both engines"
    # NAMD's gate: at least one A/C/G/T somewhere.
    seq_chars = sum(
        sum(1 for c in (s.sequence or "") if c in "ACGT") for s in design.strands
    )
    assert seq_chars > 0


# ── Mocked-runner orchestration ───────────────────────────────────────────────────


def test_run_oxdna_trials_sequential_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("OXDNA_BIN", "/usr/bin/true")  # find_oxdna returns a path

    design, plan = br.build_synthetic_design(300, max_nt=50_000)
    from backend.core.design_geometry import _geometry_for_design

    geometry = _geometry_for_design(design)
    configs = [
        bench.OxdnaTrialConfig("CPU", "CPU", "0"),
        bench.OxdnaTrialConfig("CUDA:0", "CUDA", "0"),
    ]

    order: list[str] = []

    async def fake_runner(oxdna_bin, input_path, stage_dir, log, job_id):
        order.append(job_id)
        # Faster on CUDA so it should win.
        await asyncio.sleep(
            0.02 if "bench-" in job_id and job_id.endswith("0") else 0.0
        )
        return 0, None

    state = br.BenchmarkState(
        benchmark_id="t1",
        engine="oxdna",
        trials_total=len(configs),
        proxy_nucleotides=plan["proxy_nucleotides"],
        requested_nucleotides=plan["requested_nucleotides"],
    )
    workdir = tmp_path / "run"
    asyncio.run(
        br.run_oxdna_trials(
            state, design, geometry, configs, workdir, steps=10, runner=fake_runner
        )
    )

    assert len(order) == 2  # both trials ran
    assert order == sorted(order)  # sequential, in config order
    assert state.state == "completed"
    assert state.trials_done == 2
    assert state.recommendation is not None
    assert not workdir.exists()  # temp dir cleaned up


def test_run_oxdna_trials_no_binary_fails_gracefully(tmp_path, monkeypatch):
    monkeypatch.delenv("OXDNA_BIN", raising=False)
    monkeypatch.setattr("backend.core.oxdna_runner.find_oxdna", lambda: None)

    design, plan = br.build_synthetic_design(120, max_nt=50_000)
    from backend.core.design_geometry import _geometry_for_design

    state = br.BenchmarkState(benchmark_id="t2", engine="oxdna", trials_total=1)
    asyncio.run(
        br.run_oxdna_trials(
            state,
            design,
            _geometry_for_design(design),
            [bench.OxdnaTrialConfig("CPU", "CPU", "0")],
            tmp_path / "r",
            steps=10,
        )
    )
    assert state.state == "failed"
    assert "oxDNA" in state.error


# ── Routes ────────────────────────────────────────────────────────────────────────


def test_benchmark_hardware_route(monkeypatch):
    monkeypatch.setattr(
        "backend.core.hardware.enumerate_cuda_devices",
        lambda: [{"index": 0, "name": "Fake GPU"}],
    )
    monkeypatch.setattr("backend.core.hardware.os.cpu_count", lambda: 8)
    r = client.get("/api/benchmark/hardware")
    assert r.status_code == 200
    body = r.json()
    assert body["thread_ladder"] == [2, 4, 8]
    assert any("CUDA:0" in g for g in body["oxdna_grid"])
    assert any("GPU:0" in g for g in body["namd_grid"])


def test_apply_writes_per_machine_metadata(monkeypatch):
    design_state.set_design(Design())
    monkeypatch.setattr("backend.core.hardware.hostname", lambda: "testhost")

    # Seed a completed oxDNA benchmark directly into the registry.
    state = br.BenchmarkState(
        benchmark_id="appl1",
        engine="oxdna",
        state="completed",
        trials_total=1,
        proxy_nucleotides=1200,
        recommendation={
            "backend": "CUDA",
            "device": "0",
            "steps_per_s": 4200.0,
            "proxy_nucleotides": 1200,
        },
    )
    br._BENCH["appl1"] = state

    r = client.post("/api/benchmark/appl1/apply", json={})
    assert r.status_code == 200, r.text
    assert r.json()["hostname"] == "testhost"

    slot = design_state.get_or_404().metadata.hardware_defaults["testhost"]
    assert slot.oxdna.backend == "CUDA"
    assert slot.oxdna.steps_per_s == 4200.0


def test_apply_before_completion_409():
    state = br.BenchmarkState(benchmark_id="pending1", engine="namd", state="running")
    br._BENCH["pending1"] = state
    r = client.post("/api/benchmark/pending1/apply", json={})
    assert r.status_code == 409


def test_get_unknown_benchmark_404():
    assert client.get("/api/benchmark/nope").status_code == 404


# ── ETA + fraction (pure) ─────────────────────────────────────────────────────────


def test_state_fraction_and_eta():
    st = br.BenchmarkState(
        benchmark_id="x", engine="oxdna", trials_total=4, trials_done=2
    )
    st.state = "running"
    st.trial_seconds = [2.0, 4.0]  # mean 3s × 2 remaining = 6s
    assert st.fraction() == 0.5
    assert st.eta_seconds() == 6.0
    d = st.to_dict()
    assert d["fraction"] == 0.5 and d["eta_seconds"] == 6.0


def test_eta_none_before_first_trial_and_when_done():
    st = br.BenchmarkState(benchmark_id="y", engine="oxdna", trials_total=2)
    st.state = "running"
    assert st.eta_seconds() is None  # nothing measured yet
    st.trial_seconds = [1.0, 1.0]
    st.trials_done = 2
    st.state = "completed"
    assert st.eta_seconds() is None  # not running → no estimate


# ── Cancellation ──────────────────────────────────────────────────────────────────


def test_cancel_running_benchmark_kills_and_keeps_state(tmp_path, monkeypatch):
    monkeypatch.setenv("OXDNA_BIN", "/usr/bin/true")

    design, plan = br.build_synthetic_design(120, max_nt=50_000)
    from backend.core.design_geometry import _geometry_for_design

    geometry = _geometry_for_design(design)
    configs = [
        bench.OxdnaTrialConfig("CPU", "CPU", "0"),
        bench.OxdnaTrialConfig("CUDA:0", "CUDA", "0"),
    ]

    async def slow_runner(*_a, **_k):
        await asyncio.sleep(30)  # block in-trial until cancelled
        return 0, None

    state = br.BenchmarkState(
        benchmark_id="cancelme",
        engine="oxdna",
        trials_total=len(configs),
        proxy_nucleotides=plan["proxy_nucleotides"],
        requested_nucleotides=plan["requested_nucleotides"],
    )
    workdir = tmp_path / "run"
    br._run_in_thread(
        state,
        lambda: br.run_oxdna_trials(
            state, design, geometry, configs, workdir, steps=10, runner=slow_runner
        ),
    )

    # Wait until the worker is actually in-flight.
    deadline = time.time() + 5
    while time.time() < deadline and not br.is_any_running():
        time.sleep(0.02)
    assert br.is_any_running()

    assert br.cancel_benchmark("cancelme") is True

    deadline = time.time() + 5
    while time.time() < deadline and br.is_any_running():
        time.sleep(0.02)
    assert not br.is_any_running()
    assert state.state == "cancelled"
    assert state.recommendation is None  # kept old defaults — nothing applied
    assert not workdir.exists()  # temp dir cleaned up on cancel


def test_cancel_unknown_benchmark_returns_false():
    assert br.cancel_benchmark("does-not-exist") is False


def test_cancel_route_unknown_ok():
    r = client.post("/api/benchmark/nope/cancel")
    assert r.status_code == 200 and r.json()["cancelled"] is False


def test_start_rejected_while_one_running(monkeypatch):
    design_state.set_design(Design())
    monkeypatch.setattr("backend.core.benchmark_runner.is_any_running", lambda: True)
    r = client.post("/api/benchmark/oxdna", json={})
    assert r.status_code == 409
    r2 = client.post("/api/benchmark/namd", json={})
    assert r2.status_code == 409
