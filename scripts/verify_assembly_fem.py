"""Opt-in native BigO browser check with failure-safe disposable job storage.

Run with ``uv run python scripts/verify_assembly_fem.py``. Requires the local
workspace/BigO-poly.nass fixture and its sources. Original inputs are read-only.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def _owned_processes(workspace: Path) -> list[int]:
    """Identify surviving test processes by the unique workspace environment tag."""
    marker = f"NADOC_WORKSPACE={workspace}".encode()
    owned = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if marker in (proc / "environ").read_bytes().split(b"\0"):
                owned.append(int(proc.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    return owned


def _stop_owned_processes(workspace: Path) -> None:
    # Also covers an interrupted Playwright driver before its own teardown ran.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        owned = _owned_processes(workspace)
        for pid in owned:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        if owned:
            deadline = time.monotonic() + 2
            while _owned_processes(workspace) and time.monotonic() < deadline:
                time.sleep(0.05)
    if _owned_processes(workspace):
        raise RuntimeError(f"Test workers still own {workspace}; retained for cleanup")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    workspace = Path(tempfile.mkdtemp(prefix="nadoc-bigo-fem-"))
    env = dict(
        os.environ,
        NADOC_WORKSPACE=str(workspace),
        NADOC_E2E_FEM_ISOLATED="1",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
    )
    print(f"Isolated workspace: {workspace}", flush=True)
    try:
        args = sys.argv[1:]
        spec = "e2e/assembly_fem_execution.spec.js"
        if "--visualization" in args:
            index = args.index("--visualization")
            source = Path(args[index + 1]).resolve()
            del args[index : index + 2]
            spec = "e2e/assembly_cando_visualization.spec.js"
            target = workspace / "cando_jobs" / source.name
            target.mkdir(parents=True)
            # Copy inputs, never hardlink writable result caches to the user's job.
            for name in (
                "job.json",
                "design.json",
                "display.json",
                "rmsf.json",
                "thermal_representative.bin",
            ):
                shutil.copy2(source / name, target / name)
            job_file = target / "job.json"
            job = json.loads(job_file.read_text())
            job.update(
                doc_id="__e2e__cando_visualization",
                project_id="flat___e2e__cando_visualization",
                design_source_path=None,
            )
            job_file.write_text(json.dumps(job))
            env["NADOC_E2E_VISUALIZATION_JOB"] = source.name
        if "--thermal" in args:
            args.remove("--thermal")
            spec = "e2e/assembly_thermal_progress.spec.js"
            env["NADOC_E2E_THERMAL_FIXTURE"] = str(workspace / "__e2e__thermal.nass")
            subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    "-c",
                    """
import json, os
from pathlib import Path
from tests.periodic_assembly_fixture import periodic_assembly
part, assembly = periodic_assembly()
workspace = Path(os.environ['NADOC_WORKSPACE'])
source = workspace / '__e2e__thermal_part.nadoc'
source.write_text(part.to_json())
data = json.loads(assembly.to_json())
for key in data['sources']:
    data['sources'][key] = {'type': 'file', 'path': str(source)}
(workspace / '__e2e__thermal.nass').write_text(json.dumps(data))
""",
                ],
                cwd=root,
                env=env,
                check=True,
            )
        result = subprocess.run(
            ["npx", "playwright", "test", spec, "--workers=1", *args],
            cwd=root / "frontend",
            env=env,
            check=False,
        )
        return result.returncode
    finally:
        # Playwright has shut down its owned API/browser/Vite processes. SNUPI
        # workers are detached: kill only PIDs proven to belong to this workspace.
        for file in workspace.glob("snupi_jobs/*/job.json"):
            pid = json.loads(file.read_text()).get("pid")
            if not pid:
                continue
            try:
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
                if b"snupi" in command and str(workspace).encode() in command:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, FileNotFoundError):
                pass
        _stop_owned_processes(workspace)
        shutil.rmtree(workspace)
        # Bridge credentials are the only artifact outside the workspace/reports.
        digest = hashlib.sha256(str(root / "frontend").encode()).hexdigest()[:12]
        port = env.get("NADOC_E2E_FRONTEND_PORT", "5175")
        if port != "5173":
            (
                Path(tempfile.gettempdir()) / f"nadoc-viewer-test-{digest}-{port}.json"
            ).unlink(missing_ok=True)
        assert not workspace.exists()
        print(
            "Disposable jobs, revisions, logs, autosaves and bridge credentials removed.",
            flush=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
