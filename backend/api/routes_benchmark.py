"""API layer — simulation hardware Benchmark endpoints.

The Dynamics-panel "Benchmark" button auto-tunes oxDNA / NAMD hardware settings for
the current machine: it builds a synthetic system sized like the open design, runs a
short trial on each candidate config (sequentially), keeps the fastest, and stores it
in ``Design.metadata.hardware_defaults`` keyed by hostname so the panel pre-fills it.

Routes
------
  GET  /benchmark/hardware        — this machine's CPUs / CUDA devices + the sweep grids
  POST /benchmark/oxdna           — start an oxDNA sweep → {benchmark_id}
  POST /benchmark/namd            — start a NAMD sweep → {benchmark_id}
  GET  /benchmark/{id}            — poll progress + results + recommendation
  POST /benchmark/{id}/apply      — write the recommendation into the design (+ save)

Thin wiring only — the decision logic lives in ``backend/core/benchmark.py`` and the
trial orchestration in ``backend/core/benchmark_runner.py``.  Mounted in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core import benchmark as bench
from backend.core import benchmark_runner as runner
from backend.core import hardware
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import (
    NamdHardwareDefault,
    OxdnaHardwareDefault,
)
from backend.physics.oxdna_interface import _strand_nucleotide_order

router = APIRouter()


def _workdir(benchmark_id: str) -> Path:
    return _WORKSPACE_DIR / "benchmark_runs" / benchmark_id


def _hardware() -> dict:
    devices = hardware.enumerate_cuda_devices()
    ladder = hardware.cpu_thread_ladder()
    return {
        "hostname": hardware.hostname(),
        "cpu_count": hardware.cpu_count(),
        "thread_ladder": ladder,
        "cuda_devices": devices,
    }


@router.get("/benchmark/hardware")
async def benchmark_hardware() -> dict:
    """Report local hardware and the config grids the sweeps would run."""
    hw = _hardware()
    oxdna_grid = [c.label for c in bench.oxdna_config_grid(hw["cuda_devices"])]
    namd_grid = [
        c.label for c in bench.namd_config_grid(hw["thread_ladder"], hw["cuda_devices"])
    ]
    return {**hw, "oxdna_grid": oxdna_grid, "namd_grid": namd_grid}


class StartBenchmarkRequest(BaseModel):
    steps: Optional[int] = None
    design_source_path: Optional[str] = None


@router.post("/benchmark/oxdna")
async def start_oxdna_benchmark(body: StartBenchmarkRequest) -> dict:
    if runner.is_any_running():
        raise HTTPException(409, "A benchmark is already running.")
    design = design_state.get_or_404()
    n_target = len(_strand_nucleotide_order(design))
    syn, plan = runner.build_synthetic_design(n_target, max_nt=bench.OXDNA_MAX_NT)
    geometry = _geometry_for_design(syn)

    configs = bench.oxdna_config_grid(_hardware()["cuda_devices"])
    bid = runner.new_benchmark_id()
    runner.start_oxdna_benchmark(bid, syn, geometry, configs, _workdir(bid), plan)
    return {"benchmark_id": bid, "trials_total": len(configs)}


@router.post("/benchmark/namd")
async def start_namd_benchmark(body: StartBenchmarkRequest) -> dict:
    if runner.is_any_running():
        raise HTTPException(409, "A benchmark is already running.")
    design = design_state.get_or_404()
    n_target = len(_strand_nucleotide_order(design))
    syn, plan = runner.build_synthetic_design(n_target, max_nt=bench.NAMD_MAX_NT)

    hw = _hardware()
    configs = bench.namd_config_grid(hw["thread_ladder"], hw["cuda_devices"])
    bid = runner.new_benchmark_id()
    runner.start_namd_benchmark(bid, syn, configs, _workdir(bid), plan)
    return {"benchmark_id": bid, "trials_total": len(configs)}


@router.get("/benchmark/{benchmark_id}")
async def get_benchmark(benchmark_id: str) -> dict:
    state = runner.get_state(benchmark_id)
    if state is None:
        raise HTTPException(404, "Unknown benchmark id.")
    return state.to_dict()


@router.post("/benchmark/{benchmark_id}/cancel")
def cancel_benchmark(benchmark_id: str) -> dict:
    """Kill a running benchmark; existing defaults are kept (Apply never ran).

    Sync (threadpooled) route — ``runner.cancel_benchmark`` may block ≤1 s waiting
    for the worker's task to exist, which must not run on the event loop.
    """
    cancelled = runner.cancel_benchmark(benchmark_id)
    return {"cancelled": cancelled}


class ApplyBenchmarkRequest(BaseModel):
    design_source_path: Optional[str] = None


@router.post("/benchmark/{benchmark_id}/apply")
async def apply_benchmark(benchmark_id: str, body: ApplyBenchmarkRequest) -> dict:
    """Write the discovered config into the design's per-machine defaults (+ save)."""
    state = runner.get_state(benchmark_id)
    if state is None:
        raise HTTPException(404, "Unknown benchmark id.")
    if state.state != "completed" or state.recommendation is None:
        raise HTTPException(409, "Benchmark has not completed with a recommendation.")

    host = hardware.hostname()
    rec = state.recommendation
    engine = state.engine

    def _apply(d) -> None:
        slot = d.metadata.hardware_defaults.get(host)
        if slot is None:
            from backend.core.models import HardwareBenchmark

            slot = HardwareBenchmark()
            d.metadata.hardware_defaults[host] = slot
        ts = state.benchmark_id  # opaque tag; the field is informational
        if engine == "oxdna":
            slot.oxdna = OxdnaHardwareDefault(
                backend=rec["backend"],
                device=rec["device"],
                steps_per_s=rec.get("steps_per_s"),
                benchmarked_at=ts,
                proxy_nucleotides=rec.get("proxy_nucleotides"),
            )
        else:
            slot.namd = NamdHardwareDefault(
                threads=rec["threads"],
                devices=rec["devices"],
                ns_per_day=rec.get("ns_per_day"),
                benchmarked_at=ts,
                proxy_nucleotides=rec.get("proxy_nucleotides"),
            )

    design_state.mutate_and_validate(_apply)

    saved_to = None
    if body.design_source_path:
        path = Path(body.design_source_path).resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(design_state.get_or_404().to_json(), encoding="utf-8")
            saved_to = str(path)
        except OSError as exc:
            raise HTTPException(500, f"Failed to save design: {exc}") from exc

    return {
        "hostname": host,
        "engine": engine,
        "recommendation": rec,
        "saved_to": saved_to,
    }
