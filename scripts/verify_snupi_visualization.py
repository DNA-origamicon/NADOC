"""Opt-in SNUPI display checks using immutable result copies, never a new solve.

BigO CanDo static FEM data exercises the shared display protocol at 424k scale;
the native smallO SNUPI dynamics result exercises actual trajectory playback.
"""

from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from verify_assembly_fem import _stop_owned_processes


def main():
    root = Path(__file__).resolve().parents[1]
    import sys

    sys.path.insert(0, str(root))
    from backend.core.snupi_job import SnupiJob

    workspace = Path(tempfile.mkdtemp(prefix="nadoc-snupi-viz-"))
    print(f"Isolated workspace: {workspace}", flush=True)
    try:
        for engine, source_id, test_id in [
            ("cando", "8ed8754fac18", "bigo-viz-stress"),
            ("snupi", "436657acd6f1", "native-snupi-dynamics"),
        ]:
            source = root / "workspace" / f"{engine}_jobs" / source_id
            target = workspace / "snupi_jobs" / test_id
            target.mkdir(parents=True)
            for name in (
                "job.json",
                "design.json",
                "display.json",
                "display.bin",
                "rmsf.json",
                "trajectory.json",
            ):
                if (source / name).exists():
                    shutil.copy2(source / name, target / name)
            job_path = target / "job.json"
            job = json.loads(job_path.read_text())
            job.update(
                job_id=test_id,
                doc_id="__e2e__snupi_visualization",
                project_id="flat___e2e__snupi_visualization",
                design_source_path=None,
            )
            job = {
                k: v for k, v in job.items() if k in {f.name for f in fields(SnupiJob)}
            }
            job_path.write_text(json.dumps(job))
        result = subprocess.run(
            [
                "npx",
                "playwright",
                "test",
                "e2e/assembly_snupi_visualization.spec.js",
                "--workers=1",
                *sys.argv[1:],
            ],
            cwd=root / "frontend",
            env=dict(
                os.environ,
                NADOC_WORKSPACE=str(workspace),
                NADOC_E2E_SNUPI_VISUALIZATION="1",
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
            ),
            timeout=600,
        )
        return result.returncode
    finally:
        _stop_owned_processes(workspace)
        shutil.rmtree(workspace)
        digest = hashlib.sha256(str(root / "frontend").encode()).hexdigest()[:12]
        (Path(tempfile.gettempdir()) / f"nadoc-viewer-test-{digest}-5175.json").unlink(
            missing_ok=True
        )
        assert not workspace.exists()
        print(
            "Disposable inputs, derived caches, revisions, logs and bridge credentials removed.",
            flush=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
