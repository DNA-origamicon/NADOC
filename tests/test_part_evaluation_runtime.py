"""Spawned evaluation enforces its thread policy after entry-point imports."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_preloaded_spawn_entrypoint_pools_are_limited_only_inside_child(tmp_path):
    # A fresh script is essential: multiprocessing spawn re-executes its module
    # before _evaluate can set environment variables. Merely patching the pytest
    # process or setting OPENBLAS_NUM_THREADS at the target misses that failure.
    script = tmp_path / "preloaded_evaluation.py"
    script.write_text(textwrap.dedent('''
        from importlib import import_module
        import json
        import os

        for module in ("numpy", "scipy.linalg", "scipy.optimize", "scipy.spatial.transform",
                       "scipy.spatial.distance", "scipy.interpolate"):
            import_module(module)
        from threadpoolctl import threadpool_info, threadpool_limits

        # Run at module scope so __mp_main__ reproduces the preloaded-pool seam,
        # even when inherited environment variables already specify one thread.
        preloaded_policy = threadpool_limits(limits=2)

        def pools():
            return sorted((item["filepath"], item["num_threads"])
                          for item in threadpool_info()
                          if item["user_api"] in {"blas", "openmp"})

        before_target_pools = pools()
        from backend.api import part_evaluation
        from backend.api.part_evaluation_worker import EvaluationWorker
        from backend.core.part_history_contract import create_empty_part
        from backend.core.part_numerical_runtime import runtime_fingerprint

        def probe_runtime(source, operation):
            # Exercise the real pinned-engine runtime validator, without atom
            # construction or a solver. The old worker fails here after spawn.
            fingerprint = runtime_fingerprint()
            return {"status": "verified", "issues": [], "fingerprint": fingerprint,
                    "before_target_pools": before_target_pools,
                    "inside_pools": pools()}

        part_evaluation.evaluate = probe_runtime

        if __name__ == "__main__":
            environment = {name: os.environ.get(name) for name in (
                "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")}
            parent_before = pools()
            worker = EvaluationWorker(create_empty_part("Runtime policy", "HONEYCOMB"),
                {"request": {"operation": "verify"}, "header": {}})
            try:
                worker.start()
                if not worker.wait(15):
                    raise RuntimeError("Small runtime probe exceeded its child allowance")
                result = worker.result()
            finally:
                worker.close()
            print(json.dumps({"result": result, "parent_before": parent_before,
                "parent_after": pools(), "environment_before": environment,
                "environment_after": {name: os.environ.get(name) for name in environment}}))
    '''))
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root) + os.pathsep + environment.get("PYTHONPATH", "")
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        environment[name] = "2"
    completed = subprocess.run([sys.executable, str(script)], cwd=root, env=environment,
                               capture_output=True, text=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    result = evidence["result"]
    assert result["status"] == "verified", result
    assert result["before_target_pools"]
    assert any(count > 1 for _path, count in result["before_target_pools"])
    assert all(count == 1 for _path, count in result["inside_pools"])
    assert result["fingerprint"]["native_threads"] == 1
    assert evidence["parent_before"] == evidence["parent_after"]
    assert any(count > 1 for _path, count in evidence["parent_after"])
    assert evidence["environment_before"] == evidence["environment_after"]
