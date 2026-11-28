"""Cold Corner display benchmark; reads an existing part, writes no structures.

Run in a fresh process, under `just validate-safe`, to include cold geometry,
projection and fit caches. Report import time separately. Numba's installed
machine-code cache is allowed; a first-ever compilation is included if needed.
Optional iteration studies evaluate numerical vectors only; the ordinary result
is always returned to the unchanged production geometry path.
"""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--iteration-study", action="store_true")
    parser.add_argument("--parallel", action="store_true", help="Use file-load paired projection workers")
    args = parser.parse_args()
    if args.parallel and args.iteration_study:
        parser.error("Iteration studies run in the local solver, not disposable workers")
    started = perf_counter()
    import numpy as np
    from backend.core.models import Design
    from backend.core.design_geometry import _positions_for_design
    from backend.core import corner_seam_closure as closure

    imports = perf_counter() - started
    raw = args.path.read_bytes()
    design = Design.from_json(raw.decode())
    before = design.model_dump_json()
    report = {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "imports_seconds": imports,
        "cold": "fresh process; no geometry, projection, fit or dependency results",
        "stages": {},
        "iteration_study": [],
    }
    original_minimize = closure.minimize
    sampled = set()

    def study(fun, x0, *positional, **kwargs):
        result = original_minimize(fun, x0, *positional, **kwargs)
        problem = fun.__self__
        # First example of each insert count, from each posed/straight stage.
        key = (stage, len(problem.bodies))
        if args.iteration_study and key not in sampled:
            sampled.add(key)
            reference = problem.coordinates(result.x)[0]
            for cap in (25, 50, 100):
                options = {**kwargs["options"], "maxiter": cap}
                t = perf_counter()
                trial = original_minimize(
                    fun, x0, *positional, **{**kwargs, "options": options}
                )
                elapsed = perf_counter() - t
                points = problem.coordinates(trial.x)[0]
                edges = problem.bridges[:, 1:3]
                ref_lengths = np.linalg.norm(
                    reference[edges[:, 0]] - reference[edges[:, 1]], axis=1
                )
                lengths = np.linalg.norm(
                    points[edges[:, 0]] - points[edges[:, 1]], axis=1
                )
                report["iteration_study"].append(
                    {
                        "stage": stage,
                        "insert_bases": len(problem.bodies),
                        "cap": cap,
                        "seconds": elapsed,
                        "iterations": trial.nit,
                        "converged": bool(trial.success),
                        "reference_iterations": result.nit,
                        "reference_objective": float(result.fun),
                        "objective": float(trial.fun),
                        "max_atom_displacement_nm": float(
                            np.linalg.norm(points - reference, axis=1).max()
                        ),
                        "max_o3_p_length_delta_nm": float(
                            np.abs(lengths - ref_lengths).max()
                        ),
                    }
                )
        return result

    if args.iteration_study:
        closure.minimize = study
    try:
        if args.parallel:
            from backend.api.corner_projection_worker import prepare_corner_display_pair
            t = perf_counter()
            prepare_corner_display_pair(design)
            report["stages"]["parallel_projections"] = perf_counter() - t
        for stage, source in [
            ("posed", design),
            (
                "straight",
                design.model_copy(
                    update={"deformations": [], "cluster_transforms": []}
                ),
            ),
        ]:
            t = perf_counter()
            positions, axes = _positions_for_design(source)
            report["stages"][stage] = perf_counter() - t
            print(
                json.dumps({"stage": stage, "seconds": report["stages"][stage]}),
                flush=True,
            )
        assert design.model_dump_json() == before
        assert args.path.read_bytes() == raw, (
            "Source changed while benchmarking; timings are not a stable comparison"
        )
    finally:
        closure.minimize = original_minimize
    report["geometry_seconds"] = sum(report["stages"].values())
    report["process_seconds"] = perf_counter() - started
    report["includes_iteration_study_overhead"] = args.iteration_study
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
