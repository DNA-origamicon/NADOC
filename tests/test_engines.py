"""Tests for the MD-engine status + install-planning model (backend/core/engines.py).

The plan builders are pure functions of (gpu, toolchain) so they verify the
GPU-awareness contract — a GPU-equipped machine is *never* planned a CPU build —
without any engine actually installed.  `engines_status()` is exercised with the
`find_*` probes + hardware monkeypatched so it is hermetic.
"""

from __future__ import annotations

import os

import backend.core.engines as engines


# ── parse_compute_cap (pure) ──────────────────────────────────────────────────


def test_parse_compute_cap_basic():
    assert engines.parse_compute_cap("7.5\n") == "75"


def test_parse_compute_cap_picks_first_and_ignores_junk():
    assert engines.parse_compute_cap("\nblah\n8.6\n7.5\n") == "86"


def test_parse_compute_cap_garbage_is_none():
    assert engines.parse_compute_cap("no GPU here") is None
    assert engines.parse_compute_cap("") is None


# ── source-build plan: GPU-awareness ──────────────────────────────────────────

_FULL_TOOLCHAIN = {
    "git": True,
    "cmake": True,
    "make": True,
    "cxx": True,
    "nvcc": True,
    "mpi": True,
    "conda": True,
    "apt": True,
}


def _gpu(present, toolkit=True, arch="75"):
    return {
        "present": present,
        "devices": ([{"name": "RTX 2080"}] if present else []),
        "names": (["RTX 2080"] if present else []),
        "toolkit": toolkit,
        "arch": arch,
    }


def test_gpu_machine_targets_cuda_never_cpu():
    """The core requirement: a GPU box is planned a CUDA build, not CPU."""
    plan = engines._source_build_plan(
        _gpu(True), _FULL_TOOLCHAIN, name="oxDNA", commands_fn=engines._managed_oxdna_commands
    )
    assert plan["target"] == "CUDA"
    assert plan["can_auto"] is True
    joined = "\n".join(plan["commands"])
    assert "OXDNA_CUDA_ARCH=75" in joined


def test_no_gpu_targets_cpu():
    plan = engines._source_build_plan(
        _gpu(False), _FULL_TOOLCHAIN, name="oxDNA", commands_fn=engines._managed_oxdna_commands
    )
    assert plan["target"] == "CPU"
    assert "-DCUDA=ON" not in "\n".join(plan["commands"])


def test_gpu_present_but_no_toolkit_blocks_auto_and_surfaces_nvcc():
    """GPU but no nvcc → still a CUDA target, NOT downgraded to CPU; auto blocked
    with the CUDA toolkit named as the missing prerequisite (the GPU-steer)."""
    tools = {**_FULL_TOOLCHAIN, "nvcc": False}
    plan = engines._source_build_plan(
        _gpu(True, toolkit=False),
        tools,
        name="oxDNA",
        commands_fn=engines._managed_oxdna_commands,
    )
    assert plan["target"] == "CUDA"
    assert plan["can_auto"] is False
    assert any("CUDA toolkit" in m for m in plan["missing_prereqs"])
    assert "CUDA toolkit" in plan["note"]


def test_missing_base_toolchain_blocks_auto():
    tools = {**_FULL_TOOLCHAIN, "cmake": False}
    plan = engines._source_build_plan(
        _gpu(False), tools, name="oxDNA", commands_fn=engines._managed_oxdna_commands
    )
    assert plan["can_auto"] is False
    assert "cmake" in plan["missing_prereqs"]


def test_arch_flows_into_cuda_command():
    plan = engines._source_build_plan(
        _gpu(True, arch="86"),
        _FULL_TOOLCHAIN,
        name="oxDNA",
        commands_fn=engines._managed_oxdna_commands,
    )
    assert "OXDNA_CUDA_ARCH=86" in "\n".join(plan["commands"])


def test_managed_oxdna_build_script_carries_arch_env_on_gpu():
    plan = engines._source_build_plan(
        _gpu(True, arch="89"),
        _FULL_TOOLCHAIN,
        name="oxDNA",
        commands_fn=engines._managed_oxdna_commands,
    )
    (cmd,) = plan["commands"]
    assert "OXDNA_CUDA_ARCH=89" in cmd
    assert cmd.endswith("bash scripts/build-oxdna.sh")


def test_oxdna_command_is_pasteable_from_any_dir():
    """The copy-paste command must cd into the project root by ABSOLUTE path —
    a bare relative `scripts/...` fails when pasted from the wrong directory."""
    (cmd,) = engines._managed_oxdna_commands("CPU", "75")
    assert cmd.startswith(f"cd {engines._PROJECT_ROOT} && ")
    assert os.path.isabs(engines._PROJECT_ROOT)
    assert "bash scripts/build-oxdna.sh" in cmd


def test_mrdna_command_cds_into_project_root():
    plan = engines._mrdna_plan(_gpu(False), {"git": True})
    (cmd,) = plan["commands"]
    assert cmd.startswith(f"cd {engines._PROJECT_ROOT} && ")
    assert "setup-mrdna.sh" in cmd


# ── terminal_guidance: where-to-paste, platform specific ──────────────────────


def test_terminal_guidance_wsl_names_distro_and_warns_off_windows():
    g = engines.terminal_guidance(wsl=True, distro="Ubuntu", platform="linux")
    assert "Ubuntu" in g["heading"]
    assert "Windows" in g["heading"]
    blob = " ".join([g["heading"], *g["steps"]])
    assert "PowerShell" in blob or "CMD" in blob
    assert g["check"]["cmd"] == "pwd"
    assert g["check"]["fail"]  # WSL gets an explicit wrong-shell message


def test_terminal_guidance_wsl_without_distro_has_fallback_name():
    g = engines.terminal_guidance(wsl=True, distro=None, platform="linux")
    assert "WSL" in g["heading"]


def test_terminal_guidance_macos_and_linux_variants():
    mac = engines.terminal_guidance(wsl=False, distro=None, platform="darwin")
    assert "Terminal" in mac["heading"]
    lin = engines.terminal_guidance(wsl=False, distro=None, platform="linux")
    assert "terminal" in lin["heading"].lower()
    assert lin["check"]["cmd"] == "pwd"


# ── gromacs plan: guided, conda line first when available ─────────────────────


def test_gromacs_is_guided_and_shows_conda_first_when_available():
    plan = engines._gromacs_plan(_gpu(False), {"conda": True})
    assert plan["method"] == "guided"
    assert plan["can_auto"] is False
    assert "conda" in plan["commands"][0]
    assert any("apt-get" in c for c in plan["commands"])


def test_gromacs_apt_only_without_conda():
    plan = engines._gromacs_plan(_gpu(False), {"conda": False})
    assert plan["method"] == "guided"
    assert all("conda" not in c for c in plan["commands"])
    assert any("apt-get" in c for c in plan["commands"])


# ── namd plan: download-only, GPU-aware build choice ──────────────────────────


def test_namd_is_download_only():
    plan = engines._namd_plan(_gpu(True), _FULL_TOOLCHAIN)
    assert plan["method"] == "download"
    assert plan["can_auto"] is False
    assert plan["downloads"] and plan["downloads"][0]["url"].startswith("https://")


def test_namd_steers_to_cuda_build_on_gpu_box():
    assert "multicore-CUDA" in "\n".join(engines._namd_plan(_gpu(True), {})["commands"])
    assert "multicore-CUDA" not in "\n".join(
        engines._namd_plan(_gpu(False), {})["commands"]
    )


# ── engines_status() aggregation + section readiness ──────────────────────────


def _patch_all(
    monkeypatch, *, oxdna, anm, namd, gmx, psfgen, dnanalysis, gpu_present=False
):
    monkeypatch.setattr(engines, "find_oxdna", lambda: oxdna)
    monkeypatch.setattr(engines, "find_dnanalysis", lambda: dnanalysis)
    monkeypatch.setattr(
        engines, "find_namd", lambda: namd or (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr(
        engines, "find_gmx", lambda: gmx or (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr(
        engines, "find_psfgen", lambda: psfgen or (_ for _ in ()).throw(RuntimeError())
    )
    monkeypatch.setattr(
        engines.hardware,
        "enumerate_cuda_devices",
        lambda: (
            [{"index": 0, "name": "RTX 2080", "uuid": "GPU-x"}] if gpu_present else []
        ),
    )
    monkeypatch.setattr(
        engines.shutil, "which", lambda c: "/usr/bin/" + c
    )  # toolchain all present


def test_status_all_installed_sections_ready(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
    )
    st = engines.engines_status()
    assert st["sections"]["oxdna"]["ready"] is True
    assert st["sections"]["md"]["ready"] is True
    assert st["engines"]["oxdna"]["installed"] is True
    assert st["engines"]["oxdna"]["install"] is None  # no plan when installed


def test_status_missing_oxdna_gates_oxdna_section(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna=None,
        anm=None,
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis=None,
        gpu_present=True,
    )
    st = engines.engines_status()
    assert st["sections"]["oxdna"]["ready"] is False
    assert st["sections"]["oxdna"]["missing"] == ["oxdna"]
    assert st["sections"]["md"]["ready"] is True
    # missing engine carries a GPU-aware CUDA plan
    plan = st["engines"]["oxdna"]["install"]
    assert plan["target"] == "CUDA"


def test_status_missing_namd_gates_md_section(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd=None,
        gmx="/g/gmx",
        psfgen=None,
        dnanalysis="/o/DNAnalysis",
    )
    st = engines.engines_status()
    assert st["sections"]["md"]["ready"] is False
    assert "namd" in st["sections"]["md"]["missing"]
    assert st["sections"]["oxdna"]["ready"] is True


# ── simulation switch (NADOC_ENGINES_FORCE_MISSING) ───────────────────────────


def test_forced_missing_parses_env(monkeypatch):
    monkeypatch.setenv("NADOC_ENGINES_FORCE_MISSING", " oxdna , namd ,")
    assert engines.forced_missing_engines() == {"oxdna", "namd"}
    assert engines.is_forced_missing("oxdna") is True
    assert engines.is_forced_missing("gromacs") is False


def test_forced_missing_unset_is_empty(monkeypatch):
    monkeypatch.delenv("NADOC_ENGINES_FORCE_MISSING", raising=False)
    assert engines.forced_missing_engines() == set()


def test_simulation_reports_installed_engine_as_missing(monkeypatch):
    # Everything truly present, but force oxdna missing → it reads as not installed,
    # carries a plan + simulated flag, and gates its section.
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
        gpu_present=True,
    )
    monkeypatch.setenv("NADOC_ENGINES_FORCE_MISSING", "oxdna")
    st = engines.engines_status()
    ox = st["engines"]["oxdna"]
    assert ox["installed"] is False
    assert ox["simulated"] is True
    assert ox["path"] is None
    assert ox["install"] is not None
    assert st["sections"]["oxdna"]["ready"] is False


# ── CUDA-degraded detection (installed but CPU-only while a GPU is present) ────


def test_oxdna_cuda_capable_not_degraded(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
        gpu_present=True,
    )
    monkeypatch.setattr(engines, "oxdna_supports_cuda", lambda p: True)
    ox = engines.engines_status()["engines"]["oxdna"]
    assert ox["installed"] is True
    assert ox["cuda_capable"] is True
    assert ox["degraded"] is False
    assert ox["install"] is None


def test_oxdna_cpu_only_with_gpu_is_degraded_with_rebuild_plan(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
        gpu_present=True,
    )
    monkeypatch.setattr(engines, "oxdna_supports_cuda", lambda p: False)
    ox = engines.engines_status()["engines"]["oxdna"]
    assert ox["installed"] is True  # CPU binary still runs — not "missing"
    assert ox["cuda_capable"] is False
    assert ox["degraded"] is True
    assert ox["install"]["target"] == "CUDA"  # the fix is re-attached
    assert "CUDA" in ox["degraded_note"] and "faster" in ox["degraded_note"]
    # section still reads ready (CPU works); degradation is a separate signal
    assert engines.engines_status()["sections"]["oxdna"]["ready"] is True


def test_oxdna_cpu_only_without_gpu_not_degraded(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
        gpu_present=False,
    )
    monkeypatch.setattr(engines, "oxdna_supports_cuda", lambda p: False)
    ox = engines.engines_status()["engines"]["oxdna"]
    assert ox["degraded"] is False  # no GPU → CPU-only is not a regression
    assert ox["install"] is None


def test_installable_keys_only_source_engines():
    keys = engines.installable_engine_keys()
    assert "namd" not in keys  # download-only
    assert "gromacs" not in keys  # guided (PATH/conda wrinkle)
    assert "psfgen" not in keys  # bundled with namd
    assert "dnanalysis" not in keys  # bundled with oxdna
    assert "arbd" not in keys  # downloaded source tarball, not a repo
    assert "cuda" not in keys  # guided (needs sudo)
    assert "oxdna" in keys and "oxdna_anm" not in keys
    assert "mrdna" in keys  # git clone via setup-mrdna.sh, no GPU


# ── mrDNA / ARBD / CUDA plans (the coarse-grained pipeline deps) ──────────────


def test_mrdna_plan_is_auto_gpu_independent():
    plan = engines._mrdna_plan(_gpu(True), _FULL_TOOLCHAIN)
    assert plan["method"] == "auto"
    assert plan["can_auto"] is True
    (cmd,) = plan["commands"]
    assert cmd.startswith(f"cd {engines._PROJECT_ROOT} && ") and "setup-mrdna.sh" in cmd
    assert plan["downloads"] == []  # nothing to download — pure git clone


def test_mrdna_plan_blocked_without_git():
    plan = engines._mrdna_plan(_gpu(False), {**_FULL_TOOLCHAIN, "git": False})
    assert plan["can_auto"] is False
    assert any("git" in m for m in plan["missing_prereqs"])


def test_arbd_plan_is_download_and_surfaces_cuda_prereq():
    plan = engines._arbd_plan(_gpu(True), {**_FULL_TOOLCHAIN, "nvcc": False})
    assert plan["method"] == "download"
    assert plan["can_auto"] is False
    assert (
        "ks.uiuc.edu" in plan["downloads"][0]["url"]
        and "ARBD" in plan["downloads"][0]["url"]
    )
    assert any("CUDA toolkit" in m for m in plan["missing_prereqs"])
    assert "sudo make install" in "\n".join(plan["commands"])


def test_arbd_plan_no_cuda_prereq_when_toolkit_present():
    plan = engines._arbd_plan(_gpu(True), _FULL_TOOLCHAIN)
    assert not any("CUDA toolkit" in m for m in plan["missing_prereqs"])


def test_cuda_plan_is_guided_with_link_and_apt():
    plan = engines._cuda_plan(_gpu(True), _FULL_TOOLCHAIN)
    assert plan["method"] == "guided"
    assert plan["can_auto"] is False
    assert plan["downloads"][0]["url"].startswith("https://developer.nvidia.com")
    assert any("apt-get" in c for c in plan["commands"])


def test_status_includes_mrdna_arbd_cuda_rows(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
        gpu_present=True,
    )
    monkeypatch.setattr(engines, "find_mrdna", lambda: None)
    monkeypatch.setattr(engines, "find_arbd", lambda: None)
    monkeypatch.setattr(engines, "find_arbd_build", lambda: None)
    # nvcc reported present via the toolchain which-stub → cuda row installed
    st = engines.engines_status()
    assert st["engines"]["mrdna"]["installed"] is False
    assert st["engines"]["mrdna"]["install"]["method"] == "auto"
    assert st["engines"]["arbd"]["installed"] is False
    assert st["engines"]["arbd"]["install"]["method"] == "download"
    assert st["engines"]["cuda"]["installed"] is True  # which("nvcc") stubbed truthy
    # the new rows don't disturb the existing sidebar sections
    assert set(st["sections"]) == {"oxdna", "md"}


def test_status_mrdna_installed_when_found(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
    )
    monkeypatch.setattr(engines, "find_mrdna", lambda: "/home/u/mrdna-tool")
    monkeypatch.setattr(engines, "find_arbd", lambda: "/usr/local/bin/arbd")
    st = engines.engines_status()
    assert st["engines"]["mrdna"]["installed"] is True
    assert st["engines"]["mrdna"]["install"] is None
    assert st["engines"]["arbd"]["installed"] is True


# ── WSL-awareness + ARBD "built but not installed" finish ──────────────────────


def test_arbd_plan_built_but_not_installed_offers_no_password_finish():
    plan = engines._arbd_plan(
        _gpu(True), _FULL_TOOLCHAIN, built_path="/home/u/arbd-src/build/arbd", wsl=True
    )
    assert plan["can_finish_built"] is True
    assert plan["built_path"].endswith("build/arbd")
    assert plan["wsl"] is True
    # both routes shown: sudo make install AND the no-password copy
    joined = "\n".join(plan["commands"])
    assert "sudo make install" in joined
    assert "~/.local/bin" in joined
    assert "not installed on PATH" in plan["note"]


def test_arbd_plan_wsl_note_when_not_built():
    plan = engines._arbd_plan(_gpu(True), _FULL_TOOLCHAIN, built_path=None, wsl=True)
    assert plan["can_finish_built"] is False
    assert "WSL" in plan["note"] and "Linux" in plan["note"]


def test_status_arbd_built_not_installed(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
        gpu_present=True,
    )
    monkeypatch.setattr(engines, "find_mrdna", lambda: None)
    monkeypatch.setattr(engines, "find_arbd", lambda: None)  # not on PATH
    monkeypatch.setattr(engines, "find_arbd_build", lambda: "/h/arbd-src/build/arbd")
    monkeypatch.setattr(engines, "is_wsl", lambda: True)
    arbd = engines.engines_status()["engines"]["arbd"]
    assert arbd["installed"] is False
    assert arbd["install"]["can_finish_built"] is True
    assert "not installed yet" in arbd["required_note"]


def test_is_wsl_reads_env(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert engines.is_wsl() is True


# ── LAMMPS (CG-DNA / oxDNA) — CPU-parallel oxDNA engine ───────────────────────


def test_lammps_plan_is_auto_cpu_never_cuda_even_on_gpu_box():
    """The parallel oxDNA scales via MPI on CPU cores, not a GPU — a GPU box must
    NOT flip this plan to CUDA (unlike the source-build plan for standalone oxDNA)."""
    plan = engines._lammps_plan(_gpu(True), _FULL_TOOLCHAIN)
    assert plan["method"] == "auto"
    assert plan["can_auto"] is True
    assert "CUDA" not in plan["target"]
    joined = "\n".join(plan["commands"])
    assert "-DCUDA=ON" not in joined and "-DCMAKE_CUDA_ARCHITECTURES" not in joined


def test_lammps_plan_carries_cgdna_cmake_flags():
    plan = engines._lammps_plan(_gpu(False), _FULL_TOOLCHAIN)
    joined = "\n".join(plan["commands"])
    assert "PKG_CG-DNA=on" in joined  # hyphen, not underscore
    assert "PKG_MOLECULE=on" in joined and "PKG_ASPHERE=on" in joined
    assert "../cmake" in joined  # LAMMPS's cmake source dir
    assert plan["doc"] == "docs/lammps_setup.md"


def test_lammps_plan_mpi_usable_builds_parallel_one_click():
    """MPI already build-usable → parallel one-click auto build, no apt line."""
    plan = engines._lammps_plan(_gpu(False), _FULL_TOOLCHAIN)
    assert plan["target"] == "CPU (MPI)"
    assert plan["can_auto"] is True  # no sudo step needed
    cmds = "\n".join(plan["commands"])
    assert "BUILD_MPI=on" in cmds
    assert "apt-get install" not in cmds  # headers already present


def test_lammps_serial_command_disables_mpi_find_package():
    """A serial build must actively disable cmake's MPI probe — otherwise a
    runtime-only MPI (mpicxx on PATH, no headers) aborts the whole configure."""
    cmds = "\n".join(engines._lammps_commands(parallel=False, install_mpi=False))
    assert "CMAKE_DISABLE_FIND_PACKAGE_MPI=ON" in cmds
    # and it wipes a stale (poisoned) build dir before re-configuring
    assert "rm -rf build" in cmds
    # the parallel command must NOT carry the disable flag
    assert "CMAKE_DISABLE_FIND_PACKAGE_MPI" not in "\n".join(
        engines._lammps_commands(parallel=True, install_mpi=False)
    )


def test_lammps_plan_missing_headers_folds_apt_install_and_stays_parallel():
    """Assume the user wants multi-core: when MPI headers are missing but apt is
    available, the `sudo apt install libopenmpi-dev` is baked into the commands and
    the build stays parallel (BUILD_MPI=on). Because it needs sudo, it's surfaced
    as copy-paste (can_auto False), and the 'why' lives in `details`, not `note`."""
    tools = {**_FULL_TOOLCHAIN, "mpi": False, "mpi_runtime": True, "apt": True}
    plan = engines._lammps_plan(_gpu(False), tools)
    assert plan["target"] == "CPU (MPI)"
    assert plan["can_auto"] is False
    cmds = plan["commands"]
    assert cmds[0] == "sudo apt-get install -y libopenmpi-dev"
    assert "BUILD_MPI=on" in "\n".join(cmds)
    assert "CMAKE_DISABLE_FIND_PACKAGE_MPI" not in "\n".join(cmds)
    # no judgement-call note; explanation is behind Details
    assert "libopenmpi-dev" not in plan["note"]
    assert "libopenmpi-dev" in plan["details"]


def test_lammps_plan_no_mpi_no_apt_builds_serial_auto():
    """No MPI and no apt to install it → serial build, still one-click (no sudo)."""
    tools = {**_FULL_TOOLCHAIN, "mpi": False, "mpi_runtime": False, "apt": False}
    plan = engines._lammps_plan(_gpu(False), tools)
    assert plan["target"] == "CPU"
    assert plan["can_auto"] is True
    assert "CMAKE_DISABLE_FIND_PACKAGE_MPI=ON" in "\n".join(plan["commands"])
    assert not any("apt-get" in c for c in plan["commands"])


def test_toolchain_mpi_means_build_usable_not_just_runtime(monkeypatch):
    """toolchain_info().mpi reflects header-usability; mpi_runtime keeps the raw
    wrapper-on-PATH signal."""
    monkeypatch.setattr(
        engines.shutil, "which", lambda c: "/usr/bin/" + c
    )  # everything present
    monkeypatch.setattr(
        engines, "_mpi_build_usable", lambda: False
    )  # but headers missing
    tools = engines.toolchain_info()
    assert tools["mpi"] is False
    assert tools["mpi_runtime"] is True


def test_lammps_plan_blocked_without_base_toolchain():
    plan = engines._lammps_plan(_gpu(False), {**_FULL_TOOLCHAIN, "cmake": False})
    assert plan["can_auto"] is False
    assert "cmake" in plan["missing_prereqs"]


def test_lammps_is_installable():
    assert "lammps_oxdna" in engines.installable_engine_keys()


def test_status_includes_lammps_row_not_capable(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
    )
    monkeypatch.setattr(engines, "find_lammps", lambda: None)
    st = engines.engines_status()
    lmp = st["engines"]["lammps_oxdna"]
    assert lmp["installed"] is False
    assert lmp["install"]["method"] == "auto"
    assert lmp["cgdna_capable"] is None  # nothing to probe
    assert lmp["degraded"] is False
    # a bare status row, not a gated sidebar section
    assert set(st["sections"]) == {"oxdna", "md"}


def test_status_lammps_installed_and_cgdna_capable(monkeypatch):
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
    )
    monkeypatch.setattr(engines, "find_lammps", lambda: "/home/u/lammps/build/lmp")
    monkeypatch.setattr(engines, "lammps_supports_cgdna", lambda p: True)
    lmp = engines.engines_status()["engines"]["lammps_oxdna"]
    assert lmp["installed"] is True
    assert lmp["cgdna_capable"] is True
    assert lmp["degraded"] is False
    assert lmp["install"] is None


def test_status_lammps_without_cgdna_is_degraded_with_rebuild_plan(monkeypatch):
    """A LAMMPS lacking CG-DNA is installed but can't run oxDNA — flagged degraded
    (no GPU condition) with the CG-DNA rebuild re-attached as the fix."""
    _patch_all(
        monkeypatch,
        oxdna="/o/oxDNA",
        anm="/a/oxDNA",
        namd="/n/namd3",
        gmx="/g/gmx",
        psfgen="/n/psfgen",
        dnanalysis="/o/DNAnalysis",
        gpu_present=False,
    )
    monkeypatch.setattr(engines, "find_lammps", lambda: "/usr/bin/lmp")
    monkeypatch.setattr(engines, "lammps_supports_cgdna", lambda p: False)
    lmp = engines.engines_status()["engines"]["lammps_oxdna"]
    assert lmp["installed"] is True  # the binary still runs
    assert lmp["cgdna_capable"] is False
    assert lmp["degraded"] is True
    assert lmp["install"]["method"] == "auto"
    assert "CG-DNA" in lmp["degraded_note"]
    assert lmp["install"]["degraded_action_label"] == "Rebuild with CG-DNA"
