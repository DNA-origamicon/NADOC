"""MD-engine status + install planning — the model behind the "MD Engines" panel.

NADOC's heavy simulation back-ends (oxDNA, NAMD,
GROMACS) are installed by the user, once per machine.  This module answers two
questions for the UI:

1. **What is installed?** — `engines_status()` probes each engine (reusing the
   `find_*` discovery functions) plus the local GPU + build toolchain, and reports
   per-engine availability and per-sidebar-section readiness.

2. **How do I install what's missing?** — each engine carries an *install plan*:
   whether it can be auto-built here (`method="auto"`), needs a license-gated
   download (`method="download"`), or needs a guided package install
   (`method="guided"`); the exact GPU-aware shell commands; missing prerequisites;
   and doc links.

**GPU-awareness is deliberate:** when a CUDA GPU is present the install plan
targets the **CUDA** build, never a silent CPU build — so a user with capable
hardware is never steered into a slow CPU-only engine without knowing.  If the
GPU is present but the CUDA toolkit (`nvcc`) is missing, that is surfaced as a
prerequisite rather than downgrading the target to CPU.

Pure/​side-effect-light: the only impurities are the `find_*` PATH probes and the
toolchain `shutil.which` checks.  The command/plan builders are pure functions of
(gpu, toolchain) so they unit-test without any engine installed.  Actually
*running* an install lives in `engine_install.py`, not here.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# NADOC project root (this file is backend/core/engines.py → up 3).  The from-source
# engine scripts live under ``scripts/`` here; the copy-paste commands must reference
# them by ABSOLUTE path (with a ``cd`` into the root) so a user pasting into any
# terminal — not just one already sitting at the project root — actually runs them.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])

from backend.core import hardware
from backend.core.oxdna_runner import (
    find_dnanalysis,
    find_lammps,
    find_oxdna,
    lammps_supports_cgdna,
    oxdna_supports_cuda,
)
from backend.core.namd_runner import find_gmx, find_namd
from backend.core.namd_topology import find_psfgen
from backend.core.mrdna_bridge import find_arbd, find_arbd_build, find_mrdna
from backend.core.blade_runner import find_blade_python


# ── simulation switch ─────────────────────────────────────────────────────────
# `NADOC_ENGINES_FORCE_MISSING=oxdna,namd` makes those engines REPORT as not
# installed even when they are, so the whole install UX (sidebar gates, status
# panel, popups, auto-build progress + fall-back) can be exercised on a normal
# machine — no fresh VM, no uninstalling.  Under simulation the auto-build streams
# fake progress and then declines (engine_install._simulate_install), so nothing
# is actually cloned/compiled.  Unset to return to real detection.
def forced_missing_engines() -> set[str]:
    raw = os.environ.get("NADOC_ENGINES_FORCE_MISSING", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def is_forced_missing(key: str) -> bool:
    return key in forced_missing_engines()


# Upstream sources (kept here so the doc, the plan, and engine_install.py agree).
OXDNA_REPO = "https://github.com/lorenzo-rovigatti/oxDNA.git"
OXDNA_REV = "8028cf33b3cba12992b771156085fa54879f50cd"
LAMMPS_REPO = "https://github.com/lammps/lammps.git"
OXDNA_BUILD_SCRIPT = "scripts/build-oxdna.sh"
NAMD_DOWNLOAD_URL = "https://www.ks.uiuc.edu/Research/namd/"
MRDNA_SETUP_SCRIPT = "./scripts/setup-mrdna.sh"
# ARBD ships from the UIUC KS group's download portal (register + accept the license,
# like NAMD) — not a public one-click repo.
ARBD_DOWNLOAD_URL = (
    "https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=ARBD"
)
CUDA_DOWNLOAD_URL = "https://developer.nvidia.com/cuda-downloads"

# Build tools we probe for.  `cxx` resolves either g++ or clang++.
_TOOLCHAIN_PROBES = {
    "git": ["git"],
    "cmake": ["cmake"],
    "make": ["make"],
    "cxx": ["g++", "c++", "clang++"],
    "nvcc": ["nvcc"],
    "mpi": ["mpirun", "mpiexec", "mpicxx", "mpic++"],
    "conda": ["conda", "mamba", "micromamba"],
    "apt": ["apt-get"],
}


# ── hardware / toolchain probes ───────────────────────────────────────────────


def _try_find(fn) -> str | None:
    """Call a ``find_*`` helper that may either return None or raise, → path|None."""
    try:
        return fn()
    except Exception:
        return None


def gpu_info() -> dict:
    """Local CUDA-GPU summary.

    ``present`` is true when at least one CUDA device is visible (``nvidia-smi``).
    ``toolkit`` is true when ``nvcc`` (the CUDA compiler, needed to *build* GPU
    binaries) is on PATH — distinct from merely having a driver/GPU.
    """
    devices = hardware.enumerate_cuda_devices()
    return {
        "present": bool(devices),
        "devices": devices,
        "names": [d.get("name", "GPU") for d in devices],
        "toolkit": shutil.which("nvcc") is not None,
        "arch": _gpu_arch(),
    }


def _gpu_arch() -> str | None:
    """Best-effort CUDA compute architecture of GPU 0 (e.g. ``"75"``), or None.

    Parsed from ``nvidia-smi --query-gpu=compute_cap`` (``"7.5"`` → ``"75"``).
    Used to target the CUDA build at the actual card; callers default to ``75``
    when this is None.
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    import subprocess

    try:
        out = subprocess.run(
            [exe, "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return parse_compute_cap(out.stdout)


def parse_compute_cap(text: str) -> str | None:
    """PURE: first ``"7.5"``-style line → ``"75"``; junk → None."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        digits = s.replace(".", "")
        if digits.isdigit():
            return digits
    return None


def _mpi_build_usable() -> bool:
    """True when MPI can actually be *compiled* against — not merely runtime wrappers on PATH.

    OpenMPI's ``openmpi-bin`` puts ``mpicxx``/``mpirun`` on PATH, but ``mpi.h`` (the
    include dir) ships only in ``libopenmpi-dev``.  Without the headers LAMMPS's
    ``find_package(MPI)`` doesn't skip MPI gracefully — it hard-errors the *entire*
    cmake configure (the wrapper advertises an include path that doesn't exist), so
    no Makefile is generated and the build fails with a cryptic "No rule to make
    target 'Makefile'".  The only reliable signal is whether the MPI compiler
    wrapper can preprocess ``#include <mpi.h>`` — works for OpenMPI and MPICH alike.
    """
    wrapper = shutil.which("mpicxx") or shutil.which("mpic++") or shutil.which("mpiCC")
    if not wrapper:
        return False
    import subprocess

    try:
        r = subprocess.run(
            [wrapper, "-E", "-x", "c++", "-"],
            input="#include <mpi.h>\n",
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def toolchain_info() -> dict:
    """Which build tools are on PATH → ``{"git": bool, "cmake": bool, ...}``.

    ``mpi`` means **build-usable** MPI — dev headers present, verified by actually
    preprocessing ``mpi.h`` — NOT just a runtime wrapper on PATH, because a
    runtime-only OpenMPI (``openmpi-bin`` without ``libopenmpi-dev``) makes LAMMPS's
    cmake configure fail outright.  ``mpi_runtime`` keeps the raw wrapper-on-PATH
    signal so the UI can tell the user to install the ``-dev`` package.
    """
    tools = {
        name: any(shutil.which(c) for c in cmds)
        for name, cmds in _TOOLCHAIN_PROBES.items()
    }
    tools["mpi_runtime"] = tools["mpi"]
    tools["mpi"] = _mpi_build_usable()
    return tools


def is_wsl() -> bool:
    """True when NADOC is running inside WSL (Windows Subsystem for Linux).

    Matters for engine installs: NADOC's backend runs on the *Linux* side, so
    engines must be Linux builds installed on the Linux side — a Windows-side
    download (under ``/mnt/c/...``) can't be run.  Detected via the ``microsoft``
    marker the WSL kernel puts in ``/proc/version``.
    """
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def terminal_guidance(*, wsl: bool, distro: str | None, platform: str) -> dict:
    """Explicit *where do I paste these commands?* help for the install popup.  PURE.

    The most common install failure isn't a bad command — it's the right command
    pasted into the WRONG shell: Windows PowerShell/CMD instead of the WSL Linux
    shell, or a VS Code integrated terminal running the Windows profile.  NADOC's
    backend runs on the Linux side, so the build has to happen there too.  We hand
    the UI a plain-language, platform-specific block plus a one-line self-check
    (``pwd``) so the user can confirm they're in the right place before pasting.

    Shape: ``{heading, steps:[...], check:{cmd, pass, fail}}``.
    """
    if wsl:
        name = distro or "your Linux (WSL) distro"
        return {
            "heading": f"Paste these in a WSL (Linux) terminal for “{name}” — NOT Windows PowerShell or CMD",
            "steps": [
                "NADOC's engine build must run on the Linux side (where the backend runs), "
                "never in Windows PowerShell/CMD and never from a C:\\ or /mnt/c/ location.",
                f"Easiest: open Windows Terminal, click the ⌄ tab dropdown, and choose “{name}” "
                f"(or open the Start menu and launch “{name}”). The window title shows your Linux user@host.",
                "Prefer VS Code? Its terminal must be the WSL one. If the prompt reads "
                "`PS C:\\>` or `C:\\Users\\…>`, that's Windows — open the terminal ⌄ dropdown → "
                "“Select Default Profile” → pick your WSL/Ubuntu profile, then Terminal → New Terminal "
                "(or just type `wsl` and press Enter in the current one).",
            ],
            "check": {
                "cmd": "pwd",
                "pass": "Prints a path starting with /home/ → you're in the right (Linux) terminal; paste away.",
                "fail": "Prints C:\\… or errors out → that's a Windows shell. Switch to the WSL one first.",
            },
        }
    if platform == "darwin":
        return {
            "heading": "Paste these in the Terminal app",
            "steps": [
                "Open Terminal (press ⌘-Space, type “Terminal”, Enter) — or iTerm if you use it.",
                "VS Code's integrated terminal (Terminal → New Terminal) also works; on macOS it's a normal shell.",
            ],
            "check": {
                "cmd": "pwd",
                "pass": "Prints a /Users/… path → you're good.",
                "fail": "",
            },
        }
    return {  # plain Linux
        "heading": "Paste these in a terminal",
        "steps": [
            "Open your terminal app (on Ubuntu/GNOME: press Ctrl+Alt+T).",
            "VS Code's integrated terminal (Terminal → New Terminal) also works — on Linux it's a normal shell.",
        ],
        "check": {
            "cmd": "pwd",
            "pass": "Prints a /home/… path → you're good.",
            "fail": "",
        },
    }


# ── per-engine install-plan builders (pure: (gpu, toolchain) → dict) ───────────


def _missing(tools: dict, needed: list[str]) -> list[str]:
    return [t for t in needed if not tools.get(t)]


def _source_build_plan(gpu: dict, tools: dict, *, name: str, commands_fn) -> dict:
    """Install plan for an engine we build from source (oxDNA + the ANM fork).

    Targets CUDA whenever a GPU is present.  Auto-buildable only when the base
    toolchain is present *and* — for a CUDA target — ``nvcc`` is too; otherwise
    the missing piece (commonly the CUDA toolkit) is reported as a prerequisite
    and the UI falls back to showing copy-paste commands.
    """
    target = "CUDA" if gpu["present"] else "CPU"
    base_needed = ["git", "cmake", "make", "cxx"]
    needed = base_needed + (["nvcc"] if target == "CUDA" else [])
    missing = _missing(tools, needed)
    arch = gpu.get("arch") or "75"
    return {
        "method": "auto",
        "target": target,
        "can_auto": not missing,
        "missing_prereqs": [_pretty_tool(m) for m in missing],
        "commands": commands_fn(target, arch),
        "downloads": [],
        "doc": "docs/oxdna_setup.md",
        "note": _gpu_note(gpu, tools, target),
    }


def _managed_oxdna_commands(target: str, arch: str) -> list[str]:
    """Commands for NADOC's pinned upstream build (DNA, RNA, and DNANM)."""
    env = f"OXDNA_CUDA_ARCH={arch} " if target == "CUDA" else ""
    return [f"cd {_PROJECT_ROOT} && {env}bash {OXDNA_BUILD_SCRIPT}"]


def _lammps_commands(*, parallel: bool, install_mpi: bool) -> list[str]:
    # LAMMPS's CMake source dir is the ``cmake`` subfolder, not the repo root.
    # CG-DNA carries the oxDNA/oxDNA2 styles; it *requires* MOLECULE + ASPHERE.
    # BUILD_MPI=on is what makes it the CPU-*parallel* oxDNA (the whole point).
    # A shallow clone avoids LAMMPS's very large full history.  Binary: ~/lammps/build/lmp.
    cmake = "cmake -D PKG_CG-DNA=on -D PKG_MOLECULE=on -D PKG_ASPHERE=on"
    if parallel:
        cmake += " -D BUILD_MPI=on"
    else:
        # Serial build.  Simply omitting BUILD_MPI is NOT enough: LAMMPS calls
        # find_package(MPI) unconditionally, and a runtime-only MPI (mpicxx on PATH
        # but no dev headers) poisons that probe and aborts the whole configure.
        # This flag makes cmake skip the MPI search entirely for a clean build.
        cmake += " -D CMAKE_DISABLE_FIND_PACKAGE_MPI=ON"
    cmake += " ../cmake"
    steps = []
    if install_mpi:
        # The MPI dev headers needed for the parallel build.  We assume the user
        # wants multi-core (the whole point of this engine), so this is folded into
        # the copy-paste block rather than left as a "you might want to…" note.
        steps.append("sudo apt-get install -y libopenmpi-dev")
    steps += [
        f"git clone --depth 1 {LAMMPS_REPO} ~/lammps",
        # Wipe build/ so a poisoned CMakeCache from a previous failed attempt can't
        # linger (re-running cmake reuses a stale cache and fails the same way).
        "cd ~/lammps && rm -rf build && mkdir build && cd build",
        cmake,
        "cmake --build . -j$(nproc)",
    ]
    return steps


def _lammps_plan(gpu: dict, tools: dict) -> dict:
    """LAMMPS + CG-DNA: the CPU-*parallel* oxDNA — source-built here.

    Unlike standalone oxDNA (whose accelerator is a single GPU), the value of the
    LAMMPS CG-DNA build is **MPI domain decomposition** across CPU cores, which is
    how the oxDNA force field scales to very large assemblies.  So the target is
    always CPU, never CUDA.

    We **assume the user wants the parallel build** (it's the point of the engine).
    When MPI isn't build-usable but the dev headers can be apt-installed, the
    ``sudo apt-get install -y libopenmpi-dev`` line is folded straight into the
    copy-paste commands and the build stays parallel — no judgement-call note.
    That case needs a sudo step the background service can't run, so it's surfaced
    as copy-paste (``can_auto=False``) rather than one-click.  Only when MPI can't
    be obtained at all (no apt) does it fall back to a serial build.
    """
    base_needed = ["git", "cmake", "make", "cxx"]
    missing = _missing(tools, base_needed)
    mpi = bool(tools.get("mpi"))  # build-usable (headers present) right now
    apt = bool(tools.get("apt"))
    install_mpi = (not mpi) and apt  # get parallel via a one-line sudo apt install
    parallel = mpi or install_mpi
    target = "CPU (MPI)" if parallel else "CPU"
    # One-click auto only when no sudo step is needed (the service can't run sudo).
    can_auto = (not missing) and not install_mpi

    if mpi:
        details = "MPI is already available, so this builds the multi-core (parallel) engine directly."
    elif install_mpi:
        details = (
            "The parallel build needs MPI. The first command installs the MPI "
            "development headers (libopenmpi-dev); the rest clone and compile LAMMPS "
            "with the CG-DNA package across all your CPU cores. Parallel MPI is the "
            "only oxDNA that scales to very large assemblies."
        )
    else:
        details = (
            "No MPI toolchain is available and it can't be auto-installed here, so "
            "this builds a single-core LAMMPS. Install an MPI implementation "
            "(e.g. libopenmpi-dev) and rebuild for the multi-core speedup."
        )
    return {
        "method": "auto",
        "target": target,
        "can_auto": can_auto,
        "missing_prereqs": [_pretty_tool(m) for m in missing],
        "commands": _lammps_commands(parallel=parallel, install_mpi=install_mpi),
        "downloads": [],
        "doc": "docs/lammps_setup.md",
        # Frontend degraded-rebuild label overrides (this rebuild is about the
        # CG-DNA package, not a GPU — see md_engines_logic.actionLabel).
        "degraded_action_label": "Rebuild with CG-DNA",
        "degraded_guided_label": "Add CG-DNA…",
        # Short, factual top line — no judgement calls.  The "why" lives in `details`,
        # rendered behind an expandable section in the popup.
        "note": "LAMMPS with the CG-DNA package — the CPU-parallel oxDNA, for assemblies too large for single-GPU oxDNA.",
        "details": details,
    }


def _gromacs_plan(gpu: dict, tools: dict) -> dict:
    """GROMACS: guided install (paste commands).

    Not auto-run: a conda-installed ``gmx`` lands on the conda env's PATH, which
    the NADOC backend (running under its own ``uv`` venv) won't see without extra
    PATH wiring — so a "successful" auto-build could still read as not-installed.
    We show the no-sudo conda command first and the system ``apt`` command as the
    alternative, and let the user run whichever fits their setup.
    """
    conda_cmd = "conda install -y -c conda-forge gromacs"
    apt_cmds = ["sudo apt-get update", "sudo apt-get install -y gromacs"]
    commands = ([conda_cmd] if tools.get("conda") else []) + apt_cmds
    note = (
        "Run the conda line (no admin rights) if you use conda, or the apt lines "
        "(needs your password). Make sure `gmx` ends up on the PATH the NADOC "
        "backend sees, then restart it."
        if tools.get("conda")
        else "Needs administrator rights (the sudo password). Paste these in a terminal."
    )
    return {
        "method": "guided",
        "target": "CPU",
        "can_auto": False,
        "missing_prereqs": [],
        "commands": commands,
        "downloads": [],
        "doc": "docs/external_tools.md",
        "note": note,
    }


def _namd_plan(gpu: dict, tools: dict) -> dict:
    """NAMD: license-gated download — cannot be auto-installed.

    The user must register + accept the license on the NAMD site, then NADOC can
    extract+detect the tarball.  GPU-aware *guidance*: steer to the CUDA build
    when a GPU is present.
    """
    build = (
        "Linux-x86_64-multicore-CUDA" if gpu["present"] else "Linux-x86_64-multicore"
    )
    extract = "tar xf NAMD_*_%s.tar.gz -C ~/Applications/" % build
    return {
        "method": "download",
        "target": "CUDA" if gpu["present"] else "CPU",
        "can_auto": False,
        "missing_prereqs": [],
        "commands": ["mkdir -p ~/Applications", extract],
        "downloads": [
            {
                "label": "NAMD 3 download (register + accept license)",
                "url": NAMD_DOWNLOAD_URL,
            },
        ],
        "doc": "docs/namd_setup.md",
        "note": _namd_note(gpu, build),
    }


def _mrdna_plan(gpu: dict, tools: dict) -> dict:
    """mrdna Python package: one-click auto-install (git clone, no download, no sudo).

    ``scripts/setup-mrdna.sh`` clones the checkout, applies the NumPy-2.x patches,
    and editable-installs it into NADOC's venv — GPU-independent (mrdna builds the
    model; ARBD does the GPU work).  Auto-buildable whenever ``git`` is present.
    """
    missing = _missing(tools, ["git"])
    return {
        "method": "auto",
        "target": "CPU",
        "can_auto": not missing,
        "missing_prereqs": [_pretty_tool(m) for m in missing],
        # Absolute `cd` into the project root — the setup script is referenced
        # relatively, so a paste from elsewhere would not find it.
        "commands": [f"cd {_PROJECT_ROOT} && bash {MRDNA_SETUP_SCRIPT}"],
        "downloads": [],
        "doc": "docs/mrdna_setup.md",
        "note": (
            "Installs the mrdna Python package (no download needed). It converts a "
            "design into a coarse-grained model; the GPU simulation itself needs ARBD "
            "(below). Click Install to run the setup script here."
        ),
    }


def _arbd_plan(
    gpu: dict, tools: dict, *, built_path: str | None = None, wsl: bool = False
) -> dict:
    """ARBD GPU engine: download the source tarball, build it here, then install.

    Not a public one-click repo — the user downloads the tarball from the KS/UIUC
    portal, picks it with the folder navigator, and NADOC verifies + builds it.
    Building needs the CUDA toolkit + a C++ build chain (surfaced as prereqs).

    **WSL-aware:** NADOC runs on the Linux side, so ARBD must be the *Linux* build
    installed on the Linux side.  When a Linux binary is already built but not yet
    on PATH (``built_path`` — the common "sudo make install wasn't finished" snag),
    the plan flips to a **finish-install** shape: a one-click no-password copy onto
    PATH (``can_finish_built``), plus the standard ``sudo make install`` line.
    """
    missing = _missing(tools, ["nvcc", "cmake", "make", "cxx"])
    plan = {
        "method": "download",
        "target": "CUDA" if gpu["present"] else "CPU",
        "can_auto": False,
        "wsl": wsl,
        "built_path": built_path,
        "can_finish_built": bool(built_path),
        "missing_prereqs": [_pretty_tool(m) for m in missing],
        "downloads": [
            {
                "label": "ARBD download (register + accept license)",
                "url": ARBD_DOWNLOAD_URL,
            },
        ],
        "doc": "docs/mrdna_setup.md",
    }
    if built_path:
        # Already built on the Linux side — just needs to land on PATH.
        plan["commands"] = [
            f"cd {os.path.dirname(built_path)}",
            "sudo make install            # → /usr/local/bin/arbd (needs your password)",
            f"# …or with no password:  cp {built_path} ~/.local/bin/",
        ]
        plan["note"] = (
            f"ARBD is already **built** (Linux binary at {built_path}) but not installed "
            "on PATH yet, so NADOC can't find it. Click **Finish install** below to copy it "
            "onto PATH (no password) — or run the sudo line to install it system-wide."
        )
    else:
        plan["commands"] = [
            "mkdir -p ~/arbd-src && tar xf ~/Downloads/arbd*.tar.* -C ~/arbd-src --strip-components=1",
            "cd ~/arbd-src && mkdir -p build && cd build",
            "cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local",
            "make -j$(nproc)",
            "sudo make install   # installs /usr/local/bin/arbd (needs your password)",
        ]
        plan["note"] = _arbd_note(gpu, tools, wsl)
    return plan


def _blade_plan() -> dict:
    """Install plan for BLADE's compute env.  Deliberately NOT auto-installable: OpenMM ships
    as a conda/micromamba package, and creating an env is a machine-level decision (CUDA build
    variant, disk, an existing env the user may already curate) — not something a CAD app should
    do behind the user's back.  So this is instructions only."""
    return {
        "auto": False,
        "name": "BLADE (OpenMM)",
        "note": (
            "BLADE runs OpenMM, which is not in the NADOC Python environment. Create a "
            "conda/micromamba env with openmm + parmed, or point $BLADE_OPENMM_ENV at one "
            "you already have."
        ),
        "commands": [
            "micromamba create -n gpu -c conda-forge python=3.12 openmm parmed cudatoolkit",
            "# then either name it 'gpu' (auto-detected) or export BLADE_OPENMM_ENV=<prefix>",
        ],
    }


def _cuda_plan(gpu: dict, tools: dict) -> dict:
    """CUDA toolkit (nvcc): guided install — needs the admin password, can't auto-run.

    The toolkit provides ``nvcc``, required to *build* ARBD (and the GPU oxDNA/NAMD
    builds). On this WSL/Ubuntu setup it installs via apt (sudo) or the NVIDIA
    runfile; either way it needs the password, so NADOC shows the link + commands
    rather than running them.
    """
    return {
        "method": "guided",
        "target": "CUDA",
        "can_auto": False,
        "missing_prereqs": [],
        "commands": [
            "sudo apt-get update",
            "sudo apt-get install -y nvidia-cuda-toolkit",
        ],
        "downloads": [
            {"label": "CUDA Toolkit (NVIDIA)", "url": CUDA_DOWNLOAD_URL},
        ],
        "doc": "docs/mrdna_setup.md",
        "note": (
            "The CUDA toolkit gives you `nvcc`, needed to build the GPU engine ARBD. "
            "Installing it needs your computer's admin password, so paste the lines "
            "below in a terminal (or use the NVIDIA link), then click Re-check."
        ),
    }


def _arbd_note(gpu: dict, tools: dict, wsl: bool = False) -> str:
    wsl_hint = (
        " You're running NADOC inside WSL, so ARBD must be the **Linux** build "
        "installed on the Linux side — a Windows download (under /mnt/c/…) won't run. "
        "NADOC builds the Linux binary for you."
        if wsl
        else ""
    )
    if not tools.get("nvcc"):
        return (
            "First install the CUDA toolkit (below) — ARBD needs it to build. Then "
            "download the ARBD source (link) and use **Browse…** to pick the file. "
            "NADOC builds it; one `sudo make install` line finishes it." + wsl_hint
        )
    return (
        "Download the ARBD source (link), then use **Browse…** to pick the file. "
        "NADOC builds it; one `sudo make install` line (needs your password) finishes "
        "the install to /usr/local/bin/arbd." + wsl_hint
    )


def _pretty_tool(tool: str) -> str:
    return {
        "nvcc": "CUDA toolkit (nvcc)",
        "cxx": "C++ compiler (g++)",
        "git": "git",
        "cmake": "cmake",
        "make": "make",
    }.get(tool, tool)


def _gpu_note(gpu: dict, tools: dict, target: str) -> str:
    if not gpu["present"]:
        return "No CUDA GPU detected — building the CPU engine."
    names = ", ".join(gpu["names"]) or "CUDA GPU"
    if target == "CUDA" and not tools.get("nvcc"):
        return (
            f"GPU detected ({names}) but the CUDA toolkit (nvcc) is missing — "
            "install it to build the much faster GPU engine. See the doc for the link."
        )
    return f"GPU detected ({names}) — building the CUDA (GPU-accelerated) engine."


def _namd_note(gpu: dict, build: str) -> str:
    if gpu["present"]:
        names = ", ".join(gpu["names"]) or "CUDA GPU"
        return (
            f"GPU detected ({names}). Download the **{build}** build for GPU speed. "
            "NAMD requires a free registration + license acceptance before download."
        )
    return (
        f"No GPU detected. Download the **{build}** (CPU) build. "
        "NAMD requires a free registration + license acceptance before download."
    )


# ── per-engine status ─────────────────────────────────────────────────────────


def _engine(key, name, purpose, path, plan, *, required_note="", forced=False) -> dict:
    installed = (path is not None) and not forced
    return {
        "key": key,
        "name": name,
        "purpose": purpose,
        "installed": installed,
        "path": None if forced else path,
        "required_note": required_note,
        "simulated": forced,
        "install": None if installed else plan,
    }


def engines_status() -> dict:
    """Full MD-engine report for the panel + the sidebar gates.

    Shape::

        {
          "gpu": {present, devices, names, toolkit, arch},
          "toolchain": {git, cmake, make, cxx, nvcc, conda, apt},
          "engines": {oxdna, namd, gromacs, psfgen, dnanalysis},
          "sections": {
             "oxdna": {required:[...], ready:bool, missing:[...]},
             "md":    {required:[...], ready:bool, missing:[...]},
          }
        }

    ``sections`` tells each sidebar panel whether to show its real controls
    (``ready``) or the status+install gate (the ``missing`` engine keys).
    """
    gpu = gpu_info()
    tools = toolchain_info()

    ox_path = find_oxdna()
    lammps_path = _try_find(find_lammps)
    namd_path = _try_find(find_namd)
    gmx_path = _try_find(find_gmx)
    psfgen_path = _try_find(find_psfgen)
    dnanalysis_path = find_dnanalysis()
    mrdna_path = _try_find(find_mrdna)
    blade_python = _try_find(find_blade_python)
    arbd_path = _try_find(find_arbd)
    arbd_built = None if arbd_path else _try_find(find_arbd_build)
    wsl = is_wsl()
    nvcc_path = shutil.which("nvcc")
    forced = forced_missing_engines()
    _f = lambda k: k in forced

    engines = {
        "oxdna": _engine(
            "oxdna",
            "oxDNA",
            "GPU molecular dynamics for DNA/RNA and DNANM protein-DNA hybrids.",
            ox_path,
            _source_build_plan(gpu, tools, name="oxDNA", commands_fn=_managed_oxdna_commands),
            forced=_f("oxdna"),
        ),
        "lammps_oxdna": _engine(
            "lammps_oxdna",
            "LAMMPS (CG-DNA / oxDNA)",
            "CPU-parallel oxDNA (MPI) — the only oxDNA that scales to very large assemblies.",
            lammps_path,
            _lammps_plan(gpu, tools),
            required_note="Optional — for assemblies too large for single-GPU oxDNA.",
            forced=_f("lammps_oxdna"),
        ),
        "namd": _engine(
            "namd",
            "NAMD 3",
            "All-atom molecular dynamics engine.",
            namd_path,
            _namd_plan(gpu, tools),
            forced=_f("namd"),
        ),
        "gromacs": _engine(
            "gromacs",
            "GROMACS",
            "Solvation + energy minimisation for the all-atom MD pipeline.",
            gmx_path,
            _gromacs_plan(gpu, tools),
            forced=_f("gromacs"),
        ),
        "blade": _engine(
            "blade",
            "BLADE (OpenMM)",
            "Box-free implicit-solvent atomistic relax — no explicit water, no periodic cell.",
            blade_python,
            _blade_plan(),
            required_note="Only needed for the BLADE tab; ships as a conda/micromamba env, "
            "not a NADOC build.",
            forced=_f("blade"),
        ),
        # These ship *inside* another engine's install — reported, never installed
        # on their own.
        "psfgen": _engine(
            "psfgen",
            "psfgen",
            "CHARMM topology builder — ships inside the NAMD download.",
            psfgen_path,
            _namd_plan(gpu, tools),
            required_note="Bundled with NAMD; installing NAMD provides it.",
            forced=_f("psfgen"),
        ),
        "dnanalysis": _engine(
            "dnanalysis",
            "DNAnalysis",
            "oxDNA H-bond health oracle — builds alongside oxDNA.",
            dnanalysis_path,
            _source_build_plan(gpu, tools, name="oxDNA", commands_fn=_managed_oxdna_commands),
            required_note="Bundled with oxDNA; building oxDNA provides it.",
            forced=_f("dnanalysis"),
        ),
        # ── mrDNA coarse-grained pipeline (mrdna Python + ARBD GPU engine + CUDA) ──
        "mrdna": _engine(
            "mrdna",
            "mrDNA",
            "Coarse-grained multi-resolution relaxation — converts a design to a bead model.",
            mrdna_path,
            _mrdna_plan(gpu, tools),
            forced=_f("mrdna"),
        ),
        "arbd": _engine(
            "arbd",
            "ARBD",
            "GPU Brownian-dynamics engine that runs the mrDNA coarse-grained simulation.",
            arbd_path,
            _arbd_plan(gpu, tools, built_path=arbd_built, wsl=wsl),
            required_note=(
                "Built on the Linux side but not installed yet — finish below."
                if arbd_built
                else "Needs the CUDA toolkit to build; drives mrDNA."
            ),
            forced=_f("arbd"),
        ),
        "cuda": _engine(
            "cuda",
            "CUDA toolkit",
            "GPU compiler toolkit (nvcc) — needed to build ARBD and the GPU oxDNA/NAMD engines.",
            nvcc_path,
            _cuda_plan(gpu, tools),
            forced=_f("cuda"),
        ),
    }

    # ── CUDA-degraded detection ─────────────────────────────────────────────
    # A source-built engine can be *installed* yet CPU-only (the classic broken
    # state: a conda/apt `oxDNA` on PATH with no GPU support).  When a GPU is
    # present that is "installed but not full-speed": flag it and re-attach the
    # CUDA build plan as the fix, without marking the engine missing (the CPU
    # binary still runs — just slowly).
    for key in ("oxdna",):
        eng = engines[key]
        path = eng["path"]
        cuda_capable = oxdna_supports_cuda(path) if path else None
        eng["cuda_capable"] = cuda_capable
        degraded = bool(eng["installed"] and gpu["present"] and cuda_capable is False)
        eng["degraded"] = degraded
        if degraded:
            eng["install"] = _source_build_plan(
                gpu,
                tools,
                name=eng["name"],
                commands_fn=_managed_oxdna_commands,
            )
            names = ", ".join(gpu["names"]) or "a CUDA GPU"
            eng["degraded_note"] = (
                f"{eng['name']} is installed but the binary NADOC resolved is CPU-only, while "
                f"{names} is available. GPU (CUDA) runs are ~1–2 orders of magnitude "
                f"faster. Rebuild with CUDA (commands below), or set OXDNA_BIN to an "
                f"existing CUDA build."
            )

    # ── LAMMPS CG-DNA-capability (present but built without CG-DNA = degraded) ──
    # Directly analogous to the oxDNA CUDA-degraded case: a LAMMPS that lacks the
    # CG-DNA package is installed and runnable but cannot run the oxDNA force
    # field, so it's flagged "installed but not capable" with the rebuild as the
    # fix — no GPU condition here (CG-DNA is a CPU package).
    lmp = engines["lammps_oxdna"]
    lmp_path = lmp["path"]
    cgdna_capable = lammps_supports_cgdna(lmp_path) if lmp_path else None
    lmp["cgdna_capable"] = cgdna_capable
    lmp_degraded = bool(lmp["installed"] and cgdna_capable is False)
    lmp["degraded"] = lmp_degraded
    if lmp_degraded:
        lmp["install"] = _lammps_plan(gpu, tools)
        lmp["degraded_note"] = (
            "LAMMPS is installed but this binary was built without the CG-DNA "
            "package, so it can't run the oxDNA force field. Rebuild with "
            "-D PKG_CG-DNA=on (commands below), or point LAMMPS_BIN at a CG-DNA build."
        )

    def _section(required: list[str]) -> dict:
        missing = [k for k in required if not engines[k]["installed"]]
        return {"required": required, "ready": not missing, "missing": missing}

    return {
        "gpu": gpu,
        "toolchain": tools,
        "wsl": wsl,
        "terminal_help": terminal_guidance(
            wsl=wsl, distro=os.environ.get("WSL_DISTRO_NAME"), platform=sys.platform
        ),
        "engines": engines,
        "sections": {
            "oxdna": _section(["oxdna"]),
            "md": _section(["namd", "gromacs"]),
        },
    }


def installable_engine_keys() -> list[str]:
    """Engine keys that ``engine_install.py`` knows how to auto-build here.

    Only the from-source engines, which build into conventional paths that
    ``find_*`` then auto-detect.  GROMACS is guided (PATH/conda wrinkle), NAMD is
    download-only (license), psfgen/dnanalysis are bundled — none auto-buildable.
    mrdna is auto-installable via its setup script (git clone, no GPU); ARBD is a
    downloaded source tarball (handled via the archive path), CUDA is guided.
    LAMMPS (CG-DNA) is source-built (git clone + cmake), no license/download.
    """
    return ["oxdna", "mrdna", "lammps_oxdna"]
