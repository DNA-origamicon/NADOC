"""Full SNUPI benchmark on an existing prepared job snapshot (never authors a part).

Run serialized with just validate-safe. --baseline-ref loads the specified committed
physics implementation in this process only. Transient result files are removed even
on failure; metrics and per-node RMSF are retained for numerical comparisons.
"""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--backend", choices=["cpu", "cuda", "auto"], default="cuda")
    parser.add_argument("--baseline-ref")
    parser.add_argument(
        "--matched-noise",
        action="store_true",
        help="CUDA arithmetic control using NumPy impulses",
    )
    parser.add_argument("--steps", type=int, default=60000)
    args = parser.parse_args()
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import numpy as np
    from backend.core.models import Design
    from backend.core.snupi_job import SnupiJob, SnupiStatus
    from backend.core.snupi_runner import _cache_fem_analysis
    from threadpoolctl import threadpool_limits

    if args.baseline_ref:
        for module_name in ("snupi_dynamics", "fem_solver"):
            module = importlib.import_module("backend.physics." + module_name)
            path = f"backend/physics/{module_name}.py"
            source = subprocess.check_output(
                ["git", "show", f"{args.baseline_ref}:{path}"], cwd=root
            )
            exec(
                compile(source, f"{args.baseline_ref}:{path}", "exec"), module.__dict__
            )
    if args.matched_noise:
        if args.baseline_ref or args.backend != "cuda":
            parser.error("--matched-noise requires the current CUDA backend")
        from backend.physics import snupi_cuda

        integrate = snupi_cuda.LinearGJF.integrate
        select = snupi_cuda.select_backend

        def matched_integrate(self, q0, **kwargs):
            kwargs["rng"] = np.random.default_rng(kwargs.get("seed", 0))
            return integrate(self, q0, **kwargs)

        def matched_select(*pos, **kwargs):
            solver, execution = select(*pos, **kwargs)
            execution["rng"] = "numpy-matched-oracle"
            return solver, execution

        snupi_cuda.LinearGJF.integrate = matched_integrate
        snupi_cuda.select_backend = matched_select
    from backend.physics.fem_solver import predict_shape

    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.snapshot.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    design = Design.from_json(raw.decode())
    del raw
    phases = []
    start = time.perf_counter()

    def progress(fraction, phase, info=None):
        if isinstance(fraction, str):
            phase, info = fraction, {"message": info}
        row = {"seconds": time.perf_counter() - start, "phase": phase, **(info or {})}
        phases.append(row)
        if phase != "trajectory" or row.get("step", 0) % 5000 in (0, 1):
            print(json.dumps(row), flush=True)

    kwargs = {} if args.baseline_ref else {"dynamics_backend": args.backend}
    with threadpool_limits(limits=1):
        result = predict_shape(
            design,
            nonlinear=False,
            dynamics=True,
            material="snupi",
            mgcl2_M=0.02,
            hydrodynamics=False,
            tails=False,
            dynamics_steps=args.steps,
            progress_cb=progress,
            **kwargs,
        )
    solve_seconds = time.perf_counter() - start
    job = SnupiJob(
        job_id="benchmark",
        design_name="benchmark",
        status=SnupiStatus.running,
        created_at=time.time(),
    )
    with tempfile.TemporaryDirectory(
        prefix="result-files-", dir=args.output
    ) as scratch:
        _cache_fem_analysis(job, Path(scratch), result)
        total_bytes = sum(p.stat().st_size for p in Path(scratch).iterdir())
        wall_seconds = time.perf_counter() - start
        files = {p.name: p.stat().st_size for p in Path(scratch).iterdir()}
    values = np.array([r["rmsf_nm"] for r in result["rmsf"]])
    np.save(args.output / "rmsf.npy", values)
    finite = all(
        np.isfinite(np.asarray(frame)).all() for frame in result["trajectory"]["frames"]
    )
    assert finite and np.isfinite(values).all() and (values >= 0).all()
    assert hashlib.sha256(args.snapshot.read_bytes()).hexdigest() == checksum
    data = {
        "snapshot_sha256": checksum,
        "baseline_ref": args.baseline_ref,
        "requested_backend": args.backend,
        "matched_noise": args.matched_noise,
        "execution": result.get("execution", {"backend": "cpu", "rng": "numpy"}),
        "steps": args.steps,
        "dt_ns": result["dt_ns"],
        "sample_count": result["n_frame"],
        "output_frames": result["trajectory"]["n_frames"],
        "nodes": len(values),
        "nucleotides": len(result["positions"]),
        "solver_seconds": solve_seconds,
        "total_seconds": wall_seconds,
        "cache_seconds": wall_seconds - solve_seconds,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "result_bytes": total_bytes,
        "files": files,
        "finite": finite,
        "rmsf_mean_nm": float(values.mean()),
        "rmsf_range_nm": [float(values.min()), float(values.max())],
        "phases": phases,
        "temporary_results_removed": not Path(scratch).exists(),
    }
    if data["execution"]["backend"] == "cuda":
        import torch

        data["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
        data["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
    data["source_hashes"] = (
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "backend/physics/snupi_cuda.py",
                "backend/physics/snupi_analysis.py",
                "backend/physics/snupi_dynamics.py",
                "backend/physics/fem_solver.py",
                "backend/physics/fem_thermal_reconstruction.py",
            )
        }
        if not args.baseline_ref
        else {"git_ref": args.baseline_ref}
    )
    # Record guard pressure so a memory-throttled baseline cannot masquerade as
    # a hardware-only speedup. This is observation, never a limit override.
    cgroup_file = Path("/proc/self/cgroup")
    if cgroup_file.exists():
        for line in cgroup_file.read_text().splitlines():
            if line.startswith("0::"):
                cg = Path("/sys/fs/cgroup") / line[3:].lstrip("/")
                data["memory_guard"] = {
                    name: (cg / name).read_text().strip()
                    for name in ("memory.high", "memory.max", "memory.events")
                    if (cg / name).is_file()
                }
    data["cpu_threads"] = 1
    data["python"] = sys.version
    (args.output / "metrics.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({k: v for k, v in data.items() if k != "phases"}), flush=True)


if __name__ == "__main__":
    main()
