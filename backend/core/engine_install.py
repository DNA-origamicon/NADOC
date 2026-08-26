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
import re
from pathlib import Path

from backend.core import engines
from backend.core.mrdna_bridge import find_mrdna
from backend.core.oxdna_runner import find_lammps, find_oxdna

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OXDNA_DIR = os.path.expanduser("~/oxDNA")
_LAMMPS_DIR = os.path.expanduser("~/lammps")


class InstallError(RuntimeError):
    """A build step exited non-zero, or the binary wasn't detected afterward."""


# cmake/make emit ``[ 35%] Building CXX object …``; git emits ``Receiving objects:
# 35% (…)`` / ``Resolving deltas: 12% (…)``.  We scrape either family so the
# progress bar advances *during* the long compile instead of freezing at a step
# boundary (the "is it working or looping?" problem).
_MAKE_PCT_RE = re.compile(r"\[\s*(\d{1,3})%\]")
_GIT_PCT_RE = re.compile(
    r"(?:Receiving objects|Resolving deltas|Updating files|Compressing objects|Counting objects)"
    r":\s*(\d{1,3})%"
)


def parse_build_progress(line: str) -> int | None:
    """Extract a 0–100 progress percent from one line of build output.  PURE.

    Recognizes cmake/make's ``[ 35%]`` and git-clone's ``Receiving objects: 35%``
    family.  Returns ``None`` for the vast majority of lines (no percent token),
    so the caller only emits a progress tick when there's real news.
    """
    m = _MAKE_PCT_RE.search(line) or _GIT_PCT_RE.search(line)
    if not m:
        return None
    pct = int(m.group(1))
    return pct if 0 <= pct <= 100 else None


def install_steps(engine_key: str, gpu: dict, tools: dict) -> list[dict]:
    """Ordered build steps for an auto-installable engine.  PURE.

    Each step: ``{"label", "cwd", "argv", "env"?, "skip_if_dir"?}``.  A
    ``skip_if_dir`` that already exists turns the step into a no-op (idempotent
    re-clone).  Raises ValueError for engines that aren't auto-buildable.
    """
    arch = gpu.get("arch") or "75"
    cuda = gpu.get("present")

    if engine_key == "oxdna":
        env = {"OXDNA_CUDA_ARCH": str(arch)} if cuda else {"NADOC_OXDNA_CPU_ONLY": "1"}
        return [
            {
                "label": "Building pinned upstream oxDNA — several minutes",
                "cwd": str(_PROJECT_ROOT),
                "argv": ["bash", engines.OXDNA_BUILD_SCRIPT],
                "env": env,
            },
        ]

    if engine_key == "lammps_oxdna":
        # CPU-parallel oxDNA. CMake source is the ``cmake`` subfolder; CG-DNA needs
        # MOLECULE + ASPHERE; BUILD_MPI (when an MPI toolchain is present) makes it
        # the parallel engine.  Shallow clone — LAMMPS's full history is huge.
        src = _LAMMPS_DIR
        build = os.path.join(src, "build")
        cmake = [
            "cmake",
            "-D",
            "PKG_CG-DNA=on",
            "-D",
            "PKG_MOLECULE=on",
            "-D",
            "PKG_ASPHERE=on",
        ]
        if tools.get("mpi"):
            cmake += ["-D", "BUILD_MPI=on"]
        else:
            # Serial: actively disable cmake's MPI search — a runtime-only MPI
            # (mpicxx on PATH, no dev headers) otherwise aborts the whole configure.
            cmake += ["-D", "CMAKE_DISABLE_FIND_PACKAGE_MPI=ON"]
        cmake += [os.path.join(src, "cmake")]
        return [
            {
                "label": "Downloading LAMMPS (git clone)",
                "cwd": os.path.expanduser("~"),
                "argv": [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    engines.LAMMPS_REPO,
                    _LAMMPS_DIR,
                ],
                "skip_if_dir": _LAMMPS_DIR,
            },
            {
                "label": "Configuring (cmake — CG-DNA + MOLECULE + ASPHERE)",
                "cwd": build,
                "argv": cmake,
            },
            {
                "label": "Compiling (make) — this can take several minutes",
                "cwd": build,
                "argv": ["cmake", "--build", ".", f"-j{os.cpu_count() or 2}"],
            },
        ]

    if engine_key == "mrdna":
        # Pure Python (git clone + patch + editable install) — no GPU, no compile.
        return [
            {
                "label": "Installing mrDNA (download + patch + install) — about a minute",
                "cwd": str(_PROJECT_ROOT),
                "argv": ["bash", "scripts/setup-mrdna.sh"],
            },
        ]

    raise ValueError(
        f"{engine_key!r} is not auto-installable (see installable_engine_keys())"
    )


def _verify(engine_key: str) -> str | None:
    return {
        "oxdna": find_oxdna,
        "mrdna": find_mrdna,
        "lammps_oxdna": find_lammps,
    }[engine_key]()


async def _simulate_install(engine_key: str, send) -> str:
    """Dry-run for the `NADOC_ENGINES_FORCE_MISSING` simulation switch.

    Streams a few fake stages so the progress UI can be exercised, then declines
    (raises) without cloning/compiling anything — which makes the frontend fall
    back to its copy-paste command popup.  Lets the whole install UX be tested on
    a machine that already has the engine, with zero side effects.
    """
    stages = [
        "Downloading (simulated)",
        "Configuring (simulated)",
        "Compiling (simulated)",
    ]
    for i, stage in enumerate(stages):
        await send(
            {"type": "progress", "stage": stage, "pct": round(i / len(stages) * 100)}
        )
        await send(
            {"type": "log", "line": f"[simulation] {stage} — no real build is running."}
        )
    raise InstallError(
        "Simulation mode (NADOC_ENGINES_FORCE_MISSING): no real build ran. "
        "Showing the manual commands instead."
    )


async def _stream(
    argv: list[str],
    cwd: str,
    env: dict | None,
    send,
    *,
    stage: str = "",
    base: float = 0.0,
    span: float = 0.0,
) -> int:
    """Run ``argv`` in ``cwd``, forwarding each output line to ``send`` as a log.

    Returns the exit code.  stderr is merged into stdout so warnings/errors stream
    in order.  When a line carries a build percent (see ``parse_build_progress``),
    emits a ``progress`` tick mapping that 0–100 onto this step's slice of the
    overall bar — ``[base, base+span]`` — so the bar visibly climbs while the
    compile runs.
    """
    full_env = {**os.environ, **(env or {})}
    os.makedirs(cwd, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=full_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    last = -1
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if not line:
            continue
        await send({"type": "log", "line": line})
        inner = parse_build_progress(line)
        if inner is not None and span:
            overall = round(base + span * inner / 100)
            if overall != last:
                last = overall
                await send({"type": "progress", "stage": stage, "pct": overall})
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
        base = i / n * 100
        span = 100 / n
        await send({"type": "progress", "stage": step["label"], "pct": round(base)})
        skip = step.get("skip_if_dir")
        if skip and os.path.isdir(skip):
            await send(
                {
                    "type": "log",
                    "line": f"(already present: {skip} — skipping download)",
                }
            )
            continue
        rc = await _stream(
            step["argv"],
            step["cwd"],
            step.get("env"),
            send,
            stage=step["label"],
            base=base,
            span=span,
        )
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
