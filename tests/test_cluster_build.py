"""Unit tests for backend/core/cluster_build.py — pure builders, offline.

The point of these is that a caller can never turn a build request into arbitrary
remote commands, and that the generated script matches what the cluster actually
supports (CUDA 12.1.1 ceiling, gcc<=12.2 for nvcc, no Blackwell target).
"""

from __future__ import annotations

import pytest

from backend.core import cluster_build as cb
from backend.core import cluster_config as cc


@pytest.fixture
def alpine():
    return cc.alpine_profile()


# ── validation: no caller string reaches a command line ──────────────────────


def test_module_names_are_validated():
    for bad in ("gcc; rm -rf /", "$(id)", "a b", "`whoami`", "", "x" * 80):
        with pytest.raises(ValueError, match="invalid module name"):
            cb.validated_modules([bad])


def test_gencodes_must_be_literal_arch_code_pairs():
    for bad in ("arch=compute_90,code=sm_90; rm -rf /", "-O3", "arch=x,code=y", ""):
        with pytest.raises(ValueError, match="invalid cuda gencode"):
            cb.validated_gencodes([bad])
    assert cb.validated_gencodes(["arch=compute_90,code=sm_90"]) == [
        "arch=compute_90,code=sm_90"
    ]


def test_build_name_is_confined_to_a_safe_token(alpine):
    for bad in ("../../etc", "a/b", "x;y", ""):
        with pytest.raises(ValueError, match="invalid build name"):
            cb.build_dir_for(alpine, "me", bad)


def test_build_dir_stays_under_project_nadoc_builds(alpine):
    d = cb.build_dir_for(alpine, "me", "namd-git")
    assert d.startswith("/projects/me/")  # $USER bound, never someone else's tree
    assert d.endswith("/nadoc_builds/namd-git")
    assert ".." not in d


# ── the generated script ─────────────────────────────────────────────────────


def _script(**over):
    kw = dict(
        build_dir="/projects/me/nadoc_builds/namd-git",
        src_dir_name="NAMD_Git-2025-12-04_Source",
        tar_name="namd-git",
    )
    kw.update(over)
    return cb.build_sbatch(**kw)


def test_defaults_pair_a_gcc_that_nvcc_accepts():
    """CUDA 12.1's nvcc rejects gcc > 12.2, so the profile default gcc/14.2.0 —
    which the CPU path uses — cannot build CUDA."""
    assert cb.DEFAULT_MODULES[:2] == ("gcc/11.2.0", "cuda/12.1.1")
    assert "module load gcc/11.2.0 cuda/12.1.1" in _script()


def test_defers_gencodes_to_namds_curated_set():
    """NAMD's arch/Linux-x86_64.cuda12 curates sm_70/80/90 + PTX and warns that
    CUDADLINKOPTS must stay within what libcufft_static provides — NAMD device-links
    against the STATIC cuFFT. Inventing an arch list can fail that device link, and
    the local working build overrides nothing."""
    assert cb.DEFAULT_GENCODES == ()
    assert "--cuda-gencode" not in _script()


def test_an_explicit_gencode_override_still_works():
    s = _script(gencodes=["arch=compute_90,code=sm_90"])
    assert '--cuda-gencode "arch=compute_90,code=sm_90"' in s


def test_does_not_target_blackwell():
    """artxpro6000 is sm_120 and needs CUDA >= 12.8; Alpine's newest is 12.1.1."""
    assert "sm_120" not in _script()


def test_requests_no_gpu():
    # nvcc cross-compiles; acompile has no GPUs anyway.
    assert "--gres" not in _script()


def test_builds_multicore_charm_not_mpi():
    # NAMD 3 GPU-resident requires the multicore layer.
    assert "build charm++ multicore-linux-x86_64 gcc" in _script()


def test_script_verifies_the_artifact_before_claiming_success():
    s = _script()
    assert "namd3" in s and "BUILD OK" in s
    assert s.index("make -j") < s.index("BUILD OK")


def test_script_survives_alpine_profile_unbound_vars():
    # `set -u` would abort on /etc/profile's HISTCONTROL (live-confirmed 2026-07-03).
    assert "set -eo pipefail" in _script()
    assert "set -euo" not in _script()


def test_arch_names_with_plus_are_accepted_but_shell_metachars_are_not():
    # Linux-x86_64-g++ is a real NAMD arch name; `+` is inert in a shell word.
    assert "Linux-x86_64-g++" in _script(namd_arch="Linux-x86_64-g++")
    with pytest.raises(ValueError, match="invalid namd arch"):
        _script(namd_arch="Linux; rm -rf /")


def test_namd_bin_path_is_what_goes_into_the_profile():
    p = cb.namd_bin_path("/projects/me/nadoc_builds/namd-git", "NAMD_Src")
    assert p == "/projects/me/nadoc_builds/namd-git/NAMD_Src/Linux-x86_64-g++/namd3"


# ── tarball ──────────────────────────────────────────────────────────────────


def test_tarball_rejects_a_non_namd_tree(tmp_path):
    with pytest.raises(ValueError, match="does not look like a NAMD source"):
        cb.make_source_tarball(tmp_path, tmp_path / "out.tar")


def test_tarball_drops_the_local_build_and_git(tmp_path):
    """The desktop Linux-x86_64-g++ tree is the glibc-2.38 binary that cannot run on
    Alpine; shipping it would be a large upload of something we delete on arrival."""
    import tarfile

    src = tmp_path / "NAMD_Src"
    (src / "Linux-x86_64-g++").mkdir(parents=True)
    (src / ".git").mkdir()
    (src / "charm-8.0.0" / "multicore-linux-x86_64").mkdir(parents=True)
    (src / "config").write_text("#!/bin/sh\n")
    (src / "Makefile").write_text("all:\n")
    (src / "Linux-x86_64-g++" / "namd3").write_bytes(b"x" * 100)
    (src / ".git" / "HEAD").write_text("ref")
    (src / "charm-8.0.0" / "multicore-linux-x86_64" / "lib.a").write_bytes(b"y")
    (src / "charm-8.0.0" / "build").write_text("#!/bin/sh\n")

    out = cb.make_source_tarball(src, tmp_path / "out.tar")
    names = tarfile.open(out).getnames()
    assert any(n.endswith("NAMD_Src/config") for n in names)
    assert any("charm-8.0.0/build" in n for n in names)
    assert not any("Linux-x86_64-g++" in n for n in names)
    assert not any("/.git" in n for n in names)
    assert not any("multicore-linux-x86_64" in n for n in names)


def test_charm_arch_DEFINITION_survives_while_build_output_is_dropped(tmp_path):
    """SLURM 30949634 died with "triplet 'multicore-linux-x86_64' is not supported"
    because a by-name filter stripped charm-*/src/arch/<triplet> along with the
    identically-named build output. They are different things; depth tells them apart."""
    import tarfile

    src = tmp_path / "NAMD_Src"
    src.mkdir()
    (src / "config").write_text("#!/bin/sh\n")
    charm = src / "charm-8.0.0"
    (charm / "src" / "arch" / "multicore-linux-x86_64").mkdir(parents=True)
    (charm / "src" / "arch" / "multicore-linux-x86_64" / "conv-mach.h").write_text("x")
    (charm / "multicore-linux-x86_64" / "lib").mkdir(parents=True)
    (charm / "multicore-linux-x86_64" / "CMakeCache.txt").write_text("/home/jojo/...")
    (charm / "build").write_text("#!/bin/sh\n")

    names = tarfile.open(cb.make_source_tarball(src, tmp_path / "o.tar")).getnames()
    assert any("src/arch/multicore-linux-x86_64/conv-mach.h" in n for n in names), (
        "the arch DEFINITION must ship or charm cannot build that triplet"
    )
    assert not any(
        n.endswith("multicore-linux-x86_64/CMakeCache.txt") for n in names
    ), "the local build output must NOT ship (absolute Ubuntu paths)"
    assert any(n.endswith("charm-8.0.0/build") for n in names)


def test_cmake_is_a_default_module():
    """Without cmake, charm falls back to ./buildold and rejects the version string."""
    assert any(m.startswith("cmake/") for m in cb.DEFAULT_MODULES)
    assert not any(
        m.startswith("cmake/4") for m in cb.DEFAULT_MODULES
    )  # 4.x breaks charm 8


def test_config_enables_the_gpu_resident_integrator():
    """--with-single-node-cuda sets -DNODEGROUP_FORCE_REGISTER, which the local
    working binary carries. Without it the build is CUDA *offload*: it compiles,
    links and runs, then FATALs on the first `GPUresident on` conf."""
    assert "--with-single-node-cuda" in _script()


def test_config_discovers_charm_arch_instead_of_assuming_a_suffix():
    """./config printed its usage and died when handed `multicore-linux-x86_64-gcc`
    (SLURM 30949706): the CMake path names the dir without the compiler suffix, and
    the local build records CHARMARCH = multicore-linux-x86_64."""
    s = _script()
    assert '--charm-arch "$CHARM_ARCH_NAME"' in s
    assert "-gcc \\" not in s
    assert "CHARM_ARCH_NAME=$(basename" in s


def test_cuda_prefix_is_derived_not_assumed():
    """Alpine's cuda module does not export CUDA_HOME, so `--cuda-prefix "$CUDA_HOME"`
    expanded to nothing and config died with a bare "ERROR: No such directory"
    (SLURM 30949866). nvcc is always at <prefix>/bin/nvcc."""
    s = _script()
    assert '--cuda-prefix "$CUDA_PREFIX"' in s
    assert '--cuda-prefix "$CUDA_HOME"' not in s
    assert "command -v nvcc" in s  # the fallback derivation
    assert "CUDA_ROOT" in s and "CUDAROOT" in s  # the common alternatives first


def test_build_fails_loudly_if_cuda_cannot_be_located():
    s = _script()
    assert "cannot locate the CUDA toolkit" in s
    assert s.index("CUDA_PREFIX=") < s.index("./config")  # checked before configuring


def test_uses_the_fftw3_api_not_namds_fftw2_default():
    """NAMD defaults to the FFTW *2* API (sfftw.h) under /Projects/namd2/fftw, a
    UIUC-internal path — SLURM 30950063 died on it. The local working build uses
    arch/Linux-x86_64.fftw3."""
    s = _script()
    assert "--with-fftw3" in s
    assert '--fftw-prefix "$FFTW_PREFIX"' in s
    assert any(m.startswith("fftw/3") for m in cb.DEFAULT_MODULES)


def test_fftw_prefix_is_derived_and_checked():
    s = _script()
    assert "FFTW_ROOT" in s and "fftw3.h" in s and "libfftw3" in s
    assert "cannot locate FFTW3" in s
    assert s.index("FFTW_PREFIX=") < s.index("./config")


def test_builds_WITH_tcl_because_run_is_a_tcl_command():
    """`run` and `reinitvels` are Tcl COMMANDS registered by NAMD's interpreter, not
    native config parameters — every NADOC conf ends in `run N`. A --without-tcl build
    rejects them: "ERROR: ... NOT VALID / run / reinitvels" (SLURM 30954462).
    Must be 8.6.x: NAMD links -ltcl8.6, so tcltk/9.x will not satisfy it."""
    s = _script()
    assert "--without-tcl" not in s
    assert '--with-tcl --tcl-prefix "$TCL_PREFIX"' in s
    assert "libtcl8.6" in s
    assert any(m.startswith("tcltk/8.6") for m in cb.DEFAULT_MODULES)


def test_checks_for_single_precision_fftw():
    """NAMD links -lfftw3f. A double-only fftw module would link-fail an hour in."""
    s = _script()
    assert "libfftw3f" in s
    assert s.index("libfftw3f") < s.index("./config")


def test_build_validates_the_artifact_without_running_it():
    """acpu has no GPU and a -DNAMD_CUDA binary can segfault during CUDA init there.
    Attempt 6 did, and `|| true` printed BUILD OK over a core dump."""
    s = _script()
    assert '[ -x "$BIN" ]' in s
    assert "|| true" not in s
    assert "+idlepoll --version" not in s  # never RUN it on a CPU node
    assert 'grep "Linux-x86_64-multicore-CUDA"' in s  # prove it IS the CUDA build
    assert s.index('[ -x "$BIN" ]') < s.index("BUILD OK")


def test_links_zlib_for_static_tcl():
    """Alpine's libtcl8.6 is STATIC; its tclZlib.c needs zlib, which a shared
    libtcl8.6.so would have pulled in transitively (as on the local Ubuntu box).
    Without -lz every Tcl-linking target dies on undefined adler32 (SLURM 30954671)."""
    s = _script()
    assert "-ltcl8.6 -lz -ldl -lpthread" in s
    assert s.index("TCLLIB =") < s.index("make -j")  # appended before make runs


def test_builds_only_the_namd3_target():
    """psfgen links first under the default target and is never used on the cluster."""
    assert "make -j8 namd3" in _script(cores=8)


def test_verification_greps_are_sigpipe_safe():
    """`strings | grep -q` under `set -o pipefail` reports the pipeline as failed when
    grep exits early and strings takes SIGPIPE — it condemned a good binary
    (SLURM 30954674)."""
    s = _script()
    assert "grep -q" not in s
    assert 'grep "Linux-x86_64-multicore-CUDA" >/dev/null' in s
    assert 'grep "Tcl_CreateInterp" >/dev/null' in s
