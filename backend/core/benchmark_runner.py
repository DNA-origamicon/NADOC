"""Sequential trial orchestration for the simulation Benchmark feature.

Runs a short oxDNA / NAMD simulation on each candidate hardware config, measures
throughput, and keeps the fastest.  Trials run **strictly sequentially** — two
simulations on the same GPU (or competing for the same cores) would corrupt each
other's timing.

Bypasses the full ``OxdnaJob`` / ``MdJob`` job machinery (health gates, multi-stage
staging, persistence, display): a throughput probe needs only the leaf launchers
``_run_oxdna_async`` (reused as-is) and a small NAMD launcher local to this module
(the shared ``_run_namd_async`` always appends ``+devices``, which breaks the
CPU-only trial).  The synthetic system is solvated / written ONCE and reused across
every config in a sweep.

Progress lives in an in-memory registry keyed by ``benchmark_id``; the REST poll
endpoint reads it.  The pure decision logic (which configs, which winner) lives in
``benchmark.py``.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from backend.core import benchmark as bench
from backend.core.models import Design

# oxDNA: a short MD stage long enough for a stable steps/s.  NAMD: a few hundred MD
# steps after a tiny minimize is enough for NAMD to emit its "days/ns" Benchmark line.
OXDNA_BENCH_STEPS = 2_000
NAMD_BENCH_STEPS = 2_000
NAMD_MIN_STEPS = 200


# ── In-memory progress registry ──────────────────────────────────────────────────


@dataclass
class BenchmarkState:
    benchmark_id: str
    engine: str  # "oxdna" | "namd"
    state: str = "running"  # "running" | "completed" | "failed" | "cancelled"
    trials_total: int = 0
    trials_done: int = 0
    current_label: str = ""
    results: list[dict] = field(default_factory=list)
    recommendation: dict | None = None
    proxy_nucleotides: int | None = None
    requested_nucleotides: int | None = None
    note: str = ""
    error: str | None = None
    started_at: float = 0.0
    # Wall-clock seconds each completed trial took — drives the ETA estimate.
    trial_seconds: list[float] = field(default_factory=list)

    def fraction(self) -> float:
        if self.trials_total <= 0:
            return 0.0
        return min(1.0, self.trials_done / self.trials_total)

    def eta_seconds(self) -> float | None:
        """Estimated seconds remaining: mean completed-trial time × trials left.

        ``None`` until the first trial finishes (nothing to extrapolate from).
        """
        if not self.trial_seconds or self.state != "running":
            return None
        remaining = max(0, self.trials_total - self.trials_done)
        if remaining == 0:
            return 0.0
        mean = sum(self.trial_seconds) / len(self.trial_seconds)
        return mean * remaining

    def to_dict(self) -> dict:
        return {
            "benchmark_id": self.benchmark_id,
            "engine": self.engine,
            "state": self.state,
            "trials_total": self.trials_total,
            "trials_done": self.trials_done,
            "current_label": self.current_label,
            "results": self.results,
            "recommendation": self.recommendation,
            "proxy_nucleotides": self.proxy_nucleotides,
            "requested_nucleotides": self.requested_nucleotides,
            "note": self.note,
            "error": self.error,
            "fraction": self.fraction(),
            "eta_seconds": self.eta_seconds(),
        }


_BENCH: dict[str, BenchmarkState] = {}


def new_benchmark_id() -> str:
    return uuid.uuid4().hex[:12]


def get_state(benchmark_id: str) -> BenchmarkState | None:
    return _BENCH.get(benchmark_id)


# ── Synthetic matched-size design ────────────────────────────────────────────────


def _sequence_synthetic(design: Design) -> Design:
    """Give every nucleotide a definite base (cyclic A/C/G/T).

    Both engines reject undefined ('N') bases.  Sequence *content* is irrelevant to
    a throughput probe (no mutual traps; we never check base-pair retention), so a
    deterministic cycle over the exact per-strand nucleotide count is the simplest
    thing that satisfies both gates without any topology reasoning.
    """

    def strand_nt(strand) -> int:
        n = 0
        for dm in strand.domains:
            lo, hi = min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)
            n += hi - lo + 1
        return n

    new_strands = []
    for s in design.strands:
        if s.is_reference:
            new_strands.append(s)
            continue
        length = strand_nt(s)
        seq = ("ACGT" * (length // 4 + 1))[:length]
        new_strands.append(s.model_copy(update={"sequence": seq}))
    return design.model_copy(update={"strands": new_strands})


def build_synthetic_design(n_target: int, *, max_nt: int) -> tuple[Design, dict]:
    """Build a sequenced synthetic 6hb bundle sized ≈ ``n_target`` (capped at ``max_nt``).

    Returns ``(design, plan)`` where ``plan`` records the realized proxy size and
    whether a cap was applied (no-silent-caps).
    """
    from backend.api.headless_build import build_bundle
    from backend.core.models import LatticeType

    plan = bench.synthetic_bundle_plan(n_target, max_nt=max_nt)
    design = build_bundle(
        plan["cells"],
        plan["length_bp"],
        lattice=LatticeType.HONEYCOMB,
        name="benchmark_proxy",
    )
    return _sequence_synthetic(design), plan


# ── NAMD launcher (CPU-only safe) ────────────────────────────────────────────────


async def _run_namd_bench(
    namd_bin: str,
    conf_name: str,
    package_dir: Path,
    log_path: Path,
    threads: int,
    devices: str,
) -> int:
    """Launch NAMD for one benchmark trial; return the return code.

    Mirrors ``namd_runner._run_namd_async`` but OMITS ``+devices`` when
    ``devices`` is empty (a CPU-only trial) — passing ``+devices ""`` confuses NAMD.
    """
    from backend.core.namd_runner import _core_binding_prefix, _kill_process_group

    cmd = [*_core_binding_prefix(threads), namd_bin, f"+p{threads}", "+setcpuaffinity"]
    if devices:
        cmd += ["+devices", devices]
    cmd += [f"{conf_name}.conf"]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log_fh:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(package_dir),
            stdout=log_fh,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return await proc.wait()
        except asyncio.CancelledError:
            _kill_process_group(proc.pid)
            raise


# ── oxDNA sweep ──────────────────────────────────────────────────────────────────


async def run_oxdna_trials(
    state: BenchmarkState,
    design: Design,
    geometry: list[dict],
    configs: list[bench.OxdnaTrialConfig],
    workdir: Path,
    *,
    steps: int = OXDNA_BENCH_STEPS,
    runner=None,
) -> None:
    """Write topology/conf ONCE, then run one short MD stage per config (sequential)."""
    from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
    from backend.core.oxdna_runner import _run_oxdna_async, find_oxdna
    from backend.physics.oxdna_interface import write_configuration, write_topology

    runner = runner or _run_oxdna_async
    oxdna_bin = find_oxdna()
    if oxdna_bin is None:
        state.state = "failed"
        state.error = (
            "oxDNA binary not found (set $OXDNA_BIN or build ~/oxDNA/build/bin/oxDNA)."
        )
        return

    workdir.mkdir(parents=True, exist_ok=True)
    try:
        topo = workdir / "topology.top"
        conf = workdir / "conf.dat"
        write_topology(design, topo)
        write_configuration(design, geometry, conf)

        for i, cfg in enumerate(configs):
            state.current_label = cfg.label
            stage_dir = workdir / f"trial_{i}"
            stage_dir.mkdir(parents=True, exist_ok=True)
            # Same modified-backbone force caps as the real MD-relax stage: a raw
            # bundle's ideal geometry has over-long backbone bonds at helix junctions
            # that stock FENE rejects at init.  The caps let the integrator start from
            # a stretched config (and match what a real relax run uses), so the
            # measured throughput is representative.
            spec = OxdnaStageSpec(
                name=f"bench_{i}",
                kind="md_relax",
                sim_type="MD",
                steps=steps,
                backend=cfg.backend,
                device=cfg.device,
                max_backbone_force=5.0,
                max_backbone_force_far=10.0,
                external_forces=False,
            )
            # topology/conf live in the parent workdir; oxDNA runs with cwd=stage_dir,
            # so reference them relatively. The input path itself must be absolute —
            # a repo-relative path wouldn't resolve from inside stage_dir.
            input_path = (stage_dir / "input.txt").resolve()
            input_path.write_text(
                render_stage_input(spec, f"../{topo.name}", f"../{conf.name}")
            )
            steps_per_s = None
            error = None
            t0 = time.time()
            try:
                rc, _ = await runner(
                    oxdna_bin,
                    input_path,
                    stage_dir,
                    stage_dir / "oxdna.log",
                    f"bench-{state.benchmark_id}-{i}",
                )
                elapsed = max(1e-6, time.time() - t0)
                if rc == 0:
                    steps_per_s = steps / elapsed
                else:
                    error = f"oxDNA exited with code {rc}"
            except Exception as exc:  # noqa: BLE001  (CancelledError is not Exception → propagates)
                error = str(exc)
            state.trial_seconds.append(max(1e-6, time.time() - t0))
            state.results.append(
                {
                    "label": cfg.label,
                    "backend": cfg.backend,
                    "device": cfg.device,
                    "steps_per_s": steps_per_s,
                    "error": error,
                }
            )
            state.trials_done += 1

        _finalize_oxdna(state)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _finalize_oxdna(state: BenchmarkState) -> None:
    best = bench.pick_best_oxdna(state.results)
    if best is None:
        state.state = "failed"
        state.error = state.error or "No oxDNA trial produced a valid timing."
        return
    state.recommendation = {
        "backend": best["backend"],
        "device": best["device"],
        "steps_per_s": best["steps_per_s"],
        "proxy_nucleotides": state.proxy_nucleotides,
    }
    state.state = "completed"
    state.current_label = ""


# ── NAMD sweep ───────────────────────────────────────────────────────────────────


def _write_namd_bench_confs(
    package_dir: Path, name_stem: str, box, *, steps: int
) -> None:
    """Write a tiny minimize conf + a short MD bench conf into the solvated package.

    The MD conf restarts from the minimize output so each per-config trial measures
    only MD throughput (ns/day) on an already-settled system.
    """
    from backend.core.md_protocols import _common_header

    (package_dir / "bench_min.conf").write_text(
        _common_header(name_stem, box, False, rigid_bonds="none")
        + "outputName         output/bench_min\n"
        + "dcdFreq            0\n"
        + "temperature        300\n"
        + "langevinTemp       300\n"
        + "langevinDamping    5\n"
        + "langevinPiston     off\n"
        + "constraints        off\n"
        + f"minimize           {NAMD_MIN_STEPS}\n"
    )
    (package_dir / "bench.conf").write_text(
        _common_header(name_stem, box, False)
        + "outputName         output/bench\n"
        + "dcdFreq            0\n"
        + "binCoordinates     output/bench_min.coor\n"
        + "extendedSystem     output/bench_min.xsc\n"
        + "temperature        300\n"
        + "reinitvels         300\n"
        + "langevinTemp       300\n"
        + "langevinDamping    5\n"
        + "langevinPiston     off\n"
        + "constraints        off\n"
        + f"run                {steps}\n"
    )


async def run_namd_trials(
    state: BenchmarkState,
    design: Design,
    configs: list[bench.NamdTrialConfig],
    workdir: Path,
    *,
    steps: int = NAMD_BENCH_STEPS,
    runner=None,
    solvate=None,
) -> None:
    """Solvate ONCE, minimize ONCE, then run a short MD per config (sequential)."""
    from backend.core.namd_metrics import parse_namd_log
    from backend.core.namd_runner import find_namd

    runner = runner or _run_namd_bench
    try:
        namd_bin = find_namd()
    except RuntimeError as exc:
        state.state = "failed"
        state.error = str(exc)
        return

    workdir.mkdir(parents=True, exist_ok=True)
    try:
        package_dir, name_stem, box = (solvate or _solvate_once)(design, workdir)
        _write_namd_bench_confs(package_dir, name_stem, box, steps=steps)

        # Minimize once (CPU, all-threads): produces the restart the trials reuse.
        from backend.core.hardware import cpu_count

        min_log = package_dir / "output" / "bench_min.log"
        await runner(namd_bin, "bench_min", package_dir, min_log, cpu_count(), "")

        for cfg in configs:
            state.current_label = cfg.label
            log = (
                package_dir
                / "output"
                / f"bench_{cfg.threads}_{cfg.devices or 'cpu'}.log"
            )
            ns_per_day = None
            error = None
            t0 = time.time()
            try:
                rc = await runner(
                    namd_bin, "bench", package_dir, log, cfg.threads, cfg.devices
                )
                if rc == 0:
                    ns_per_day = parse_namd_log(log).ns_per_day
                    if ns_per_day is None:
                        error = "NAMD produced no Benchmark line"
                else:
                    error = f"NAMD exited with code {rc}"
            except Exception as exc:  # noqa: BLE001  (CancelledError is not Exception → propagates)
                error = str(exc)
            state.trial_seconds.append(max(1e-6, time.time() - t0))
            state.results.append(
                {
                    "label": cfg.label,
                    "threads": cfg.threads,
                    "devices": cfg.devices,
                    "ns_per_day": ns_per_day,
                    "error": error,
                }
            )
            state.trials_done += 1

        _finalize_namd(state)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _solvate_once(design: Design, workdir: Path):
    """Solvate the synthetic design once; return (package_dir, name_stem, box)."""
    from backend.core.md_protocols import parse_box_from_namd_conf
    from backend.core.namd_solvate import build_namd_solvated_package

    zip_bytes = build_namd_solvated_package(design)
    pkg_root = workdir / "package"
    pkg_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(pkg_root)
    inner = [p for p in pkg_root.iterdir() if p.is_dir()]
    if not inner:
        raise RuntimeError("NAMD solvation produced no package directory.")
    package_dir = inner[0]
    psf = list(package_dir.glob("*.psf"))
    if not psf:
        raise RuntimeError(f"No .psf in {package_dir}")
    name_stem = psf[0].stem
    box = parse_box_from_namd_conf((package_dir / "namd.conf").read_text())
    (package_dir / "output").mkdir(exist_ok=True)
    return package_dir, name_stem, box


def _finalize_namd(state: BenchmarkState) -> None:
    best = bench.pick_best_namd(state.results)
    if best is None:
        state.state = "failed"
        state.error = state.error or "No NAMD trial produced a valid timing."
        return
    state.recommendation = {
        "threads": best["threads"],
        "devices": best["devices"],
        "ns_per_day": best["ns_per_day"],
        "proxy_nucleotides": state.proxy_nucleotides,
    }
    state.state = "completed"
    state.current_label = ""


# ── Background-thread launchers + cancellation ─────────────────────────────────────


@dataclass
class _RunningHandle:
    thread: threading.Thread
    loop: object = None
    task: object = None
    # Set once loop+task are assigned — cancel_benchmark waits on this to avoid a
    # start/cancel race (the worker thread may be alive a few ms before its task exists).
    ready: threading.Event = field(default_factory=threading.Event)


# Live benchmark threads, keyed by benchmark_id (mirrors oxdna_runner._RUNNING).
_RUNNING: dict[str, _RunningHandle] = {}


def is_any_running() -> bool:
    """True if a benchmark thread is currently alive (only one runs at a time)."""
    return any(h.thread.is_alive() for h in _RUNNING.values())


def cancel_benchmark(benchmark_id: str) -> bool:
    """Cancel a running benchmark; its in-flight subprocess is killed and the temp
    dir cleaned up (the runners catch CancelledError → kill process group → finally
    rmtree).  Existing stored defaults are untouched (we only ever write on Apply).
    Returns True if the running task was cancelled.

    Blocks briefly (≤1 s) for the worker's task to be assigned — handle this from a
    sync/threadpooled route, not directly on the event loop.
    """
    h = _RUNNING.get(benchmark_id)
    if not (h and h.thread.is_alive()):
        return False
    h.ready.wait(timeout=1.0)
    if h.loop is not None and h.task is not None:
        h.loop.call_soon_threadsafe(h.task.cancel)
        return True
    return False


def _run_in_thread(state: BenchmarkState, coro_factory) -> None:
    """Run an async sweep in a daemon thread (mirrors oxdna_runner.start_job)."""

    def _main() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        handle = _RUNNING.get(state.benchmark_id)
        task = loop.create_task(coro_factory())
        if handle is not None:
            handle.loop = loop
            handle.task = task
            handle.ready.set()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            # Cancel propagated from cancel_benchmark — the trial's finally already
            # killed the subprocess + removed the temp dir.  Keep old defaults.
            state.state = "cancelled"
            state.current_label = ""
        except Exception as exc:  # noqa: BLE001
            state.state = "failed"
            state.error = str(exc)
        finally:
            _RUNNING.pop(state.benchmark_id, None)
            loop.close()

    state.started_at = time.time()
    _BENCH[state.benchmark_id] = state
    handle = _RunningHandle(
        thread=threading.Thread(
            target=_main, name=f"benchmark-{state.benchmark_id}", daemon=True
        )
    )
    _RUNNING[state.benchmark_id] = handle
    handle.thread.start()


def start_oxdna_benchmark(
    benchmark_id: str,
    design: Design,
    geometry: list[dict],
    configs: list[bench.OxdnaTrialConfig],
    workdir: Path,
    plan: dict,
) -> BenchmarkState:
    state = BenchmarkState(
        benchmark_id=benchmark_id,
        engine="oxdna",
        trials_total=len(configs),
        proxy_nucleotides=plan["proxy_nucleotides"],
        requested_nucleotides=plan["requested_nucleotides"],
        note=bench.extrapolate_note(
            plan["proxy_nucleotides"],
            plan["requested_nucleotides"],
            capped=plan["capped"],
        ),
    )
    _run_in_thread(
        state, lambda: run_oxdna_trials(state, design, geometry, configs, workdir)
    )
    return state


def start_namd_benchmark(
    benchmark_id: str,
    design: Design,
    configs: list[bench.NamdTrialConfig],
    workdir: Path,
    plan: dict,
) -> BenchmarkState:
    state = BenchmarkState(
        benchmark_id=benchmark_id,
        engine="namd",
        trials_total=len(configs),
        proxy_nucleotides=plan["proxy_nucleotides"],
        requested_nucleotides=plan["requested_nucleotides"],
        note=bench.extrapolate_note(
            plan["proxy_nucleotides"],
            plan["requested_nucleotides"],
            capped=plan["capped"],
        ),
    )
    _run_in_thread(state, lambda: run_namd_trials(state, design, configs, workdir))
    return state
