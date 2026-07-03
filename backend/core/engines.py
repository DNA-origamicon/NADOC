"""MD-engine status + install planning — the model behind the "MD Engines" panel.

NADOC's heavy simulation back-ends (oxDNA, the ANM-oxDNA protein fork, NAMD,
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

from backend.core import hardware
from backend.core.oxdna_runner import (
    find_dnanalysis,
    find_oxdna,
    find_oxdna_anm,
    oxdna_supports_cuda,
)
from backend.core.namd_runner import find_gmx, find_namd
from backend.core.namd_topology import find_psfgen
from backend.core.mrdna_bridge import find_arbd, find_arbd_build, find_mrdna

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
ANM_OXDNA_BUILD_SCRIPT = "scripts/build-anm-oxdna.sh"
NAMD_DOWNLOAD_URL = "https://www.ks.uiuc.edu/Research/namd/"
MRDNA_SETUP_SCRIPT = "./scripts/setup-mrdna.sh"
# ARBD ships from the UIUC KS group's download portal (register + accept the license,
# like NAMD) — not a public one-click repo.
ARBD_DOWNLOAD_URL = "https://www.ks.uiuc.edu/Development/Download/download.cgi?PackageName=ARBD"
CUDA_DOWNLOAD_URL = "https://developer.nvidia.com/cuda-downloads"

# Build tools we probe for.  `cxx` resolves either g++ or clang++.
_TOOLCHAIN_PROBES = {
    "git": ["git"],
    "cmake": ["cmake"],
    "make": ["make"],
    "cxx": ["g++", "c++", "clang++"],
    "nvcc": ["nvcc"],
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
            capture_output=True, text=True, timeout=10, check=False,
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


def toolchain_info() -> dict:
    """Which build tools are on PATH → ``{"git": bool, "cmake": bool, ...}``."""
    return {
        name: any(shutil.which(c) for c in cmds)
        for name, cmds in _TOOLCHAIN_PROBES.items()
    }


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


def _oxdna_commands(target: str, arch: str) -> list[str]:
    # Build into the conventional ~/oxDNA/build/ — the path find_oxdna() auto-detects,
    # so no OXDNA_BIN env var is needed afterward.  -DCUDA=ON makes one binary that
    # runs on GPU *or* CPU (oxDNA picks the backend from the input file).
    cmake = "cmake .." if target == "CPU" else f"cmake .. -DCUDA=ON -DCMAKE_CUDA_ARCHITECTURES={arch}"
    return [
        f"git clone {OXDNA_REPO} ~/oxDNA",
        "cd ~/oxDNA && mkdir -p build && cd build",
        cmake,
        "make -j$(nproc) oxDNA DNAnalysis",
    ]


def _oxdna_anm_commands(target: str, arch: str) -> list[str]:
    # The build script self-detects CPU/CUDA; arch via OXDNA_CUDA_ARCH.
    env = f"OXDNA_CUDA_ARCH={arch} " if target == "CUDA" else ""
    return [f"{env}{ANM_OXDNA_BUILD_SCRIPT}"]


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
        "Linux-x86_64-multicore-CUDA" if gpu["present"]
        else "Linux-x86_64-multicore"
    )
    extract = "tar xf NAMD_*_%s.tar.gz -C ~/Applications/" % build
    return {
        "method": "download",
        "target": "CUDA" if gpu["present"] else "CPU",
        "can_auto": False,
        "missing_prereqs": [],
        "commands": ["mkdir -p ~/Applications", extract],
        "downloads": [
            {"label": "NAMD 3 download (register + accept license)", "url": NAMD_DOWNLOAD_URL},
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
        "commands": [MRDNA_SETUP_SCRIPT],
        "downloads": [],
        "doc": "docs/mrdna_setup.md",
        "note": (
            "Installs the mrdna Python package (no download needed). It converts a "
            "design into a coarse-grained model; the GPU simulation itself needs ARBD "
            "(below). Click Install to run the setup script here."
        ),
    }


def _arbd_plan(gpu: dict, tools: dict, *, built_path: str | None = None, wsl: bool = False) -> dict:
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
            {"label": "ARBD download (register + accept license)", "url": ARBD_DOWNLOAD_URL},
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
        if wsl else ""
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
          "engines": {oxdna, oxdna_anm, namd, gromacs, psfgen, dnanalysis},
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
    anm_path = find_oxdna_anm()
    namd_path = _try_find(find_namd)
    gmx_path = _try_find(find_gmx)
    psfgen_path = _try_find(find_psfgen)
    dnanalysis_path = find_dnanalysis()
    mrdna_path = _try_find(find_mrdna)
    arbd_path = _try_find(find_arbd)
    arbd_built = None if arbd_path else _try_find(find_arbd_build)
    wsl = is_wsl()
    nvcc_path = shutil.which("nvcc")
    forced = forced_missing_engines()
    _f = lambda k: k in forced

    engines = {
        "oxdna": _engine(
            "oxdna", "oxDNA",
            "Coarse-grained DNA molecular dynamics — relax, E-field, health.",
            ox_path,
            _source_build_plan(gpu, tools, name="oxDNA", commands_fn=_oxdna_commands),
            forced=_f("oxdna"),
        ),
        "oxdna_anm": _engine(
            "oxdna_anm", "ANM-oxDNA (protein fork)",
            "oxDNA's DNANM hybrid — required only for designs that include proteins.",
            anm_path,
            _source_build_plan(gpu, tools, name="ANM-oxDNA", commands_fn=_oxdna_anm_commands),
            required_note="Only needed for protein-bearing designs.",
            forced=_f("oxdna_anm"),
        ),
        "namd": _engine(
            "namd", "NAMD 3",
            "All-atom molecular dynamics engine.",
            namd_path,
            _namd_plan(gpu, tools),
            forced=_f("namd"),
        ),
        "gromacs": _engine(
            "gromacs", "GROMACS",
            "Solvation + energy minimisation for the all-atom MD pipeline.",
            gmx_path,
            _gromacs_plan(gpu, tools),
            forced=_f("gromacs"),
        ),
        # These ship *inside* another engine's install — reported, never installed
        # on their own.
        "psfgen": _engine(
            "psfgen", "psfgen",
            "CHARMM topology builder — ships inside the NAMD download.",
            psfgen_path,
            _namd_plan(gpu, tools),
            required_note="Bundled with NAMD; installing NAMD provides it.",
            forced=_f("psfgen"),
        ),
        "dnanalysis": _engine(
            "dnanalysis", "DNAnalysis",
            "oxDNA H-bond health oracle — builds alongside oxDNA.",
            dnanalysis_path,
            _source_build_plan(gpu, tools, name="oxDNA", commands_fn=_oxdna_commands),
            required_note="Bundled with oxDNA; building oxDNA provides it.",
            forced=_f("dnanalysis"),
        ),
        # ── mrDNA coarse-grained pipeline (mrdna Python + ARBD GPU engine + CUDA) ──
        "mrdna": _engine(
            "mrdna", "mrDNA",
            "Coarse-grained multi-resolution relaxation — converts a design to a bead model.",
            mrdna_path,
            _mrdna_plan(gpu, tools),
            forced=_f("mrdna"),
        ),
        "arbd": _engine(
            "arbd", "ARBD",
            "GPU Brownian-dynamics engine that runs the mrDNA coarse-grained simulation.",
            arbd_path,
            _arbd_plan(gpu, tools, built_path=arbd_built, wsl=wsl),
            required_note=(
                "Built on the Linux side but not installed yet — finish below."
                if arbd_built else "Needs the CUDA toolkit to build; drives mrDNA."
            ),
            forced=_f("arbd"),
        ),
        "cuda": _engine(
            "cuda", "CUDA toolkit",
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
    for key in ("oxdna", "oxdna_anm"):
        eng = engines[key]
        path = eng["path"]
        cuda_capable = oxdna_supports_cuda(path) if path else None
        eng["cuda_capable"] = cuda_capable
        degraded = bool(eng["installed"] and gpu["present"] and cuda_capable is False)
        eng["degraded"] = degraded
        if degraded:
            eng["install"] = _source_build_plan(
                gpu, tools, name=eng["name"],
                commands_fn=_oxdna_commands if key == "oxdna" else _oxdna_anm_commands,
            )
            names = ", ".join(gpu["names"]) or "a CUDA GPU"
            eng["degraded_note"] = (
                f"oxDNA is installed but the binary NADOC resolved is CPU-only, while "
                f"{names} is available. GPU (CUDA) runs are ~1–2 orders of magnitude "
                f"faster. Rebuild with CUDA (commands below), or set OXDNA_BIN to an "
                f"existing CUDA build."
            )

    def _section(required: list[str]) -> dict:
        missing = [k for k in required if not engines[k]["installed"]]
        return {"required": required, "ready": not missing, "missing": missing}

    return {
        "gpu": gpu,
        "toolchain": tools,
        "wsl": wsl,
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
    """
    return ["oxdna", "oxdna_anm", "mrdna"]
