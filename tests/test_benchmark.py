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

import pytest
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


def test_namd_grid_cpu_build_is_cpu_only():
    # A CPU (non-CUDA) NAMD build cannot use the GPU → only CPU-thread configs.
    devs = [{"index": 0, "name": "A"}]
    grid = bench.namd_config_grid([4, 8], devs, cuda_build=False)
    assert {c.label for c in grid} == {"+p4 CPU", "+p8 CPU"}
    assert all(c.devices == "" for c in grid)


def test_namd_grid_cuda_build_single_gpu_has_no_fake_cpu_arm():
    # On a CUDA build a "CPU-only" trial still runs on the GPU, so it must NOT appear;
    # a single-GPU box just sweeps thread counts on that GPU.
    devs = [{"index": 0, "name": "A"}]
    grid = bench.namd_config_grid([4, 8], devs, cuda_build=True)
    assert {c.label for c in grid} == {"+p4 GPU:0", "+p8 GPU:0"}
    assert all(c.devices == "0" for c in grid)


def test_namd_grid_cuda_build_multi_gpu_adds_all_gpus_target():
    # Multi-GPU: per-device configs PLUS a genuine "use all GPUs" config (devices="").
    devs = [{"index": 0, "name": "A"}, {"index": 1, "name": "B"}]
    grid = bench.namd_config_grid([8], devs, cuda_build=True)
    assert {c.label for c in grid} == {"+p8 GPU:0", "+p8 GPU:1", "+p8 GPU:all"}
    all_gpu = [c for c in grid if c.label.endswith("GPU:all")]
    assert len(all_gpu) == 1 and all_gpu[0].devices == ""


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

    # A CPU MC pre-relax settles the proxy first, then the two timed trials run.
    assert order[0].endswith("prerelax")  # proxy settled before any timing
    trials = order[1:]
    assert len(trials) == 2  # both trials ran
    assert trials == sorted(trials)  # sequential, in config order
    assert state.state == "completed"
    assert state.trials_done == 2  # pre-relax is not counted as a trial
    assert state.recommendation is not None
    assert not workdir.exists()  # temp dir cleaned up


def test_run_oxdna_trials_prerelaxes_and_suppresses_trajectory(tmp_path, monkeypatch):
    # The proxy is written from raw ideal geometry (clashing, ~1e15 energy); a CPU MC
    # pre-relax settles it once, and the timed trials start from THAT conf with
    # trajectory output off so the wall-time reflects compute, not frame I/O.
    monkeypatch.setenv("OXDNA_BIN", "/usr/bin/true")
    design, plan = br.build_synthetic_design(300, max_nt=50_000)
    from backend.core.design_geometry import _geometry_for_design

    geometry = _geometry_for_design(design)
    configs = [bench.OxdnaTrialConfig("CUDA:0", "CUDA", "0")]
    inputs: dict[str, str] = {}

    async def fake_runner(oxdna_bin, input_path, stage_dir, log, job_id):
        if job_id.endswith("prerelax"):
            (stage_dir / "last_conf.dat").write_text("settled\n")  # produce a settled conf
        inputs[job_id] = input_path.read_text()
        return 0, None

    state = br.BenchmarkState(benchmark_id="t3", engine="oxdna", trials_total=1,
                              proxy_nucleotides=plan["proxy_nucleotides"])
    asyncio.run(br.run_oxdna_trials(state, design, geometry, configs, tmp_path / "r",
                                    steps=2000, runner=fake_runner))

    pre = next(v for k, v in inputs.items() if k.endswith("prerelax"))
    assert "sim_type = MC" in pre and "backend = CPU" in pre   # CPU MC pre-relax
    trial = next(v for k, v in inputs.items() if k.endswith("-0"))
    assert "../prerelax/last_conf.dat" in trial                # starts from the settled conf
    assert "print_conf_interval = 2001" in trial               # no intermediate trajectory frames
    assert state.recommendation is not None


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


# ── Live command + log capture (in-card details view) ──────────────────────────────


def test_log_block_lifecycle_live_then_snapshot(tmp_path):
    """A running block live-tails its file; finish_block snapshots before cleanup."""
    st = br.BenchmarkState(benchmark_id="lg", engine="oxdna", trials_total=1)
    log = tmp_path / "oxdna.log"
    log.write_text("step 1\nstep 2\n")
    st.start_block("CPU", "/usr/bin/oxDNA input.txt", log)

    d = st.to_dict()
    assert d["commands"] == [{"label": "CPU", "cmd": "/usr/bin/oxDNA input.txt"}]
    assert "$ /usr/bin/oxDNA input.txt" in d["log"]
    assert "step 2" in d["log"]  # live tail while running

    log.write_text("step 1\nstep 2\nstep 3\n")  # more output arrives
    assert "step 3" in st.to_dict()["log"]  # picked up live

    st.finish_block()
    log.unlink()  # temp dir cleaned — snapshot must survive
    assert "step 3" in st.to_dict()["log"]


def test_run_oxdna_trials_captures_commands_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("OXDNA_BIN", "/usr/bin/true")
    design, _ = br.build_synthetic_design(300, max_nt=50_000)
    from backend.core.design_geometry import _geometry_for_design

    geometry = _geometry_for_design(design)
    configs = [bench.OxdnaTrialConfig("CPU", "CPU", "0")]

    async def fake_runner(oxdna_bin, input_path, stage_dir, log, job_id):
        log.write_text(f"running {job_id}\nT = 0.1\n")  # emit a log line per launch
        return 0, None

    st = br.BenchmarkState(benchmark_id="lc", engine="oxdna", trials_total=1)
    asyncio.run(
        br.run_oxdna_trials(
            st, design, geometry, configs, tmp_path / "r", steps=10, runner=fake_runner
        )
    )
    d = st.to_dict()
    labels = [c["label"] for c in d["commands"]]
    assert labels == ["settle proxy (MC pre-relax)", "CPU"]  # pre-relax + the trial
    assert "/usr/bin/true" in d["log"]  # the engine call surfaced
    assert "running bench-lc" in d["log"]  # snapshotted log content survives cleanup


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


# ── Real-engine end-to-end (slow; needs a real NAMD binary) ─────────────────────────
#
# Regression guard for the NAMD benchmark having NEVER run end-to-end against a real
# binary (it was unit-mocked only).  Two FATALs hid here until exercised: minimize/run
# step counts that weren't multiples of stepsPerCycle, and a `reinitvels` line that made
# NAMD mis-report a missing `langevinTemp`.  This test builds a simple 6hb FROM SCRATCH,
# presses the Benchmark button (the real route + background runner + frontend-style
# poll), and asserts the sweep actually COMPLETES with a throughput number.  The runner
# solvates/minimises/runs in a temp workdir it rmtrees in a finally — nothing persists.


@pytest.mark.slow
def test_namd_benchmark_completes_end_to_end_on_a_6hb(monkeypatch):
    from backend.api import routes_benchmark
    from backend.api.headless_build import build_bundle
    from backend.core.hardware import cpu_count
    from backend.core.models import LatticeType
    from backend.core.namd_runner import find_namd

    try:
        find_namd()
    except RuntimeError:
        pytest.skip("NAMD not installed on this machine")

    # Build a small honeycomb 6hb the same way the user would, from an empty design.
    design = build_bundle(
        list(bench.SIX_HB_CELLS), 32, lattice=LatticeType.HONEYCOMB, name="bench6hb"
    )
    design_state.set_design(design)

    # Keep the sweep to a single CPU trial so the real solvate→minimize→MD→parse path
    # runs in ~a minute (the point is "does it complete", not "which config wins").
    # Cap the trial at 2 threads — NOT cpu_count(). Under `just test` (-n auto = one
    # worker per core), a `+p{all-cores}` NAMD run with core-pinning seizes every core
    # mid-suite and starves the ~11 concurrent workers running real oxDNA sims, blowing
    # their wall-clock deadlines (the historical "flaky under parallel xdist" failures).
    # A 32-bp proxy completes fine on 2 threads and stays a good citizen under load.
    trial_threads = min(2, cpu_count())
    monkeypatch.setattr(
        bench,
        "namd_config_grid",
        lambda *a, **k: [bench.NamdTrialConfig(f"+p{trial_threads} CPU", trial_threads, "")],
    )

    # Press the button: the real route counts the design's nucleotides, builds the
    # synthetic proxy, picks the grid, and starts the background sweep.
    resp = asyncio.run(
        routes_benchmark.start_namd_benchmark(routes_benchmark.StartBenchmarkRequest())
    )
    bid = resp["benchmark_id"]

    # Poll exactly like the frontend until the run leaves the "running" state.
    # 600s (not 300): under `just test` this real NAMD run competes with ~11 other
    # workers for cores, so its wall time balloons well past the isolated ~1 min. The
    # generous ceiling absorbs that contention; a genuine hang still fails, just later.
    deadline = time.monotonic() + 600
    state = None
    while time.monotonic() < deadline:
        state = br.get_state(bid)
        assert state is not None
        if state.state != "running":
            break
        time.sleep(1.0)

    assert state is not None and state.state == "completed", (
        f"benchmark did not complete: state={state and state.state} "
        f"error={state and state.error}\n--- log ---\n{state and state.render_log()[-2000:]}"
    )
    assert state.recommendation is not None
    assert (state.recommendation.get("ns_per_day") or 0) > 0
    # The single trial succeeded (no per-config error surfaced).
    assert all(r.get("error") is None for r in state.results)
