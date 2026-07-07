"""Auto-build orchestration for the source-built MD engines (oxDNA + ANM fork).

The "MD Engines" panel's **try-auto** install path runs here: given an engine key,
`install_steps()` (pure) lays out the ordered build steps, and `run_install()`
executes them as subprocesses, streaming stage/log/progress dicts to a `send`
callback (the WebSocket).  On any failure it raises `InstallError`; the frontend
then falls back to showing the copy-paste commands from the engine's install plan.

Only the from-source engines live here — they build into conventional paths that
`find_*` re-detects, so "did it work?" is answerable.  NAMD (download) and GROMACS
(guided) are never auto-run; see `engines.installable_engine_keys()`.

Mirrors the mrdna clone-and-build pattern in `api/ws.py`, lifted into a module so
the WebSocket handler stays thin (FEATURE_DEVELOPMENT.md sprout rule).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from backend.core import engines
from backend.core.mrdna_bridge import find_mrdna
from backend.core.oxdna_runner import find_lammps, find_oxdna, find_oxdna_anm

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OXDNA_DIR = os.path.expanduser("~/oxDNA")
_LAMMPS_DIR = os.path.expanduser("~/lammps")


class InstallError(RuntimeError):
    """A build step exited non-zero, or the binary wasn't detected afterward."""


def install_steps(engine_key: str, gpu: dict, tools: dict) -> list[dict]:
    """Ordered build steps for an auto-installable engine.  PURE.

    Each step: ``{"label", "cwd", "argv", "env"?, "skip_if_dir"?}``.  A
    ``skip_if_dir`` that already exists turns the step into a no-op (idempotent
    re-clone).  Raises ValueError for engines that aren't auto-buildable.
    """
    arch = gpu.get("arch") or "75"
    cuda = gpu.get("present")

    if engine_key == "oxdna":
        build = os.path.join(_OXDNA_DIR, "build")
        cmake = ["cmake", ".."]
        if cuda:
            cmake += ["-DCUDA=ON", f"-DCMAKE_CUDA_ARCHITECTURES={arch}"]
        return [
            {"label": "Downloading oxDNA (git clone)", "cwd": os.path.expanduser("~"),
             "argv": ["git", "clone", engines.OXDNA_REPO, _OXDNA_DIR],
             "skip_if_dir": _OXDNA_DIR},
            {"label": "Configuring (cmake)", "cwd": build, "argv": cmake},
            {"label": "Compiling (make) — this can take several minutes",
             "cwd": build, "argv": ["make", f"-j{os.cpu_count() or 2}", "oxDNA", "DNAnalysis"]},
        ]

    if engine_key == "lammps_oxdna":
        # CPU-parallel oxDNA. CMake source is the ``cmake`` subfolder; CG-DNA needs
        # MOLECULE + ASPHERE; BUILD_MPI (when an MPI toolchain is present) makes it
        # the parallel engine.  Shallow clone — LAMMPS's full history is huge.
        src = _LAMMPS_DIR
        build = os.path.join(src, "build")
        cmake = ["cmake", "-D", "PKG_CG-DNA=on", "-D", "PKG_MOLECULE=on",
                 "-D", "PKG_ASPHERE=on"]
        if tools.get("mpi"):
            cmake += ["-D", "BUILD_MPI=on"]
        cmake += [os.path.join(src, "cmake")]
        return [
            {"label": "Downloading LAMMPS (git clone)", "cwd": os.path.expanduser("~"),
             "argv": ["git", "clone", "--depth", "1", engines.LAMMPS_REPO, _LAMMPS_DIR],
             "skip_if_dir": _LAMMPS_DIR},
            {"label": "Configuring (cmake — CG-DNA + MOLECULE + ASPHERE)",
             "cwd": build, "argv": cmake},
            {"label": "Compiling (make) — this can take several minutes",
             "cwd": build, "argv": ["cmake", "--build", ".", f"-j{os.cpu_count() or 2}"]},
        ]

    if engine_key == "oxdna_anm":
        env = {"OXDNA_CUDA_ARCH": str(arch)} if cuda else {}
        return [
            {"label": "Building ANM-oxDNA (clone + patch + compile) — several minutes",
             "cwd": str(_PROJECT_ROOT),
             "argv": ["bash", engines.ANM_OXDNA_BUILD_SCRIPT], "env": env},
        ]

    if engine_key == "mrdna":
        # Pure Python (git clone + patch + editable install) — no GPU, no compile.
        return [
            {"label": "Installing mrDNA (download + patch + install) — about a minute",
             "cwd": str(_PROJECT_ROOT),
             "argv": ["bash", "scripts/setup-mrdna.sh"]},
        ]

    raise ValueError(f"{engine_key!r} is not auto-installable (see installable_engine_keys())")


def _verify(engine_key: str) -> str | None:
    return {"oxdna": find_oxdna, "oxdna_anm": find_oxdna_anm, "mrdna": find_mrdna,
            "lammps_oxdna": find_lammps}[engine_key]()


async def _simulate_install(engine_key: str, send) -> str:
    """Dry-run for the `NADOC_ENGINES_FORCE_MISSING` simulation switch.

    Streams a few fake stages so the progress UI can be exercised, then declines
    (raises) without cloning/compiling anything — which makes the frontend fall
    back to its copy-paste command popup.  Lets the whole install UX be tested on
    a machine that already has the engine, with zero side effects.
    """
    stages = ["Downloading (simulated)", "Configuring (simulated)", "Compiling (simulated)"]
    for i, stage in enumerate(stages):
        await send({"type": "progress", "stage": stage, "pct": round(i / len(stages) * 100)})
        await send({"type": "log", "line": f"[simulation] {stage} — no real build is running."})
    raise InstallError(
        "Simulation mode (NADOC_ENGINES_FORCE_MISSING): no real build ran. "
        "Showing the manual commands instead."
    )


async def _stream(argv: list[str], cwd: str, env: dict | None, send) -> int:
    """Run ``argv`` in ``cwd``, forwarding each output line to ``send`` as a log.

    Returns the exit code.  stderr is merged into stdout so warnings/errors stream
    in order.
    """
    full_env = {**os.environ, **(env or {})}
    os.makedirs(cwd, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=full_env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            await send({"type": "log", "line": line})
    return await proc.wait()


async def run_install(engine_key: str, send) -> str:
    """Execute the build for ``engine_key``, streaming progress to ``send``.

    ``send(dict)`` is an async callback (the WebSocket's ``send_json``).  Emits
    ``{"type":"progress","stage","pct"}`` at each step boundary, ``{"type":"log",
    "line"}`` per output line, and finally ``{"type":"complete","engine","path"}``.
    Raises `InstallError` on any step failure or if the binary isn't detected after
    the build (the caller turns that into a fall-back-to-commands message).
    """
    if engines.is_forced_missing(engine_key):
        return await _simulate_install(engine_key, send)

    gpu = engines.gpu_info()
    tools = engines.toolchain_info()
    steps = install_steps(engine_key, gpu, tools)
    n = len(steps)

    for i, step in enumerate(steps):
        await send({"type": "progress", "stage": step["label"], "pct": round(i / n * 100)})
        skip = step.get("skip_if_dir")
        if skip and os.path.isdir(skip):
            await send({"type": "log", "line": f"(already present: {skip} — skipping download)"})
            continue
        rc = await _stream(step["argv"], step["cwd"], step.get("env"), send)
        if rc != 0:
            raise InstallError(f"Step failed: {step['label']} (exit code {rc}).")

    path = _verify(engine_key)
    if not path:
        raise InstallError(
            "Build finished but the binary wasn't found where NADOC looks. "
            "Try the manual commands."
        )
    await send({"type": "progress", "stage": "Done", "pct": 100})
    await send({"type": "complete", "engine": engine_key, "path": path})
    return path
