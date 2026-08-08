"""Build a CUDA / GPU-resident NAMD on the cluster, as a batch job.

Alpine ships only ``namd/2.14`` and ``namd/3.0.1_cpu`` — there is **no CUDA NAMD
module at all** — and a locally-built binary cannot be uploaded because Alpine is
RHEL 8.10 (glibc 2.28) while a modern desktop build wants glibc 2.38. So the only
way to run NAMD 3 GPU-resident there is to compile it on the cluster. CURC
documents this as the supported path ("begin a compile job by using the ``acompile``
command"), and requires that the runtime module set match the build's.

**This is deliberately NOT a remote shell.** The submitted script is generated here
from a template plus *validated* parameters; nothing the caller sends is ever
interpolated into a command unchecked. Writes are confined to
``<project_base>/nadoc_builds/<name>``. The one broad power it does take is
"submit a batch job", which is the whole point.

Layout mirrors the rest of the cluster code: pure, unit-tested builders first, then
one async orchestrator that talks to the connection.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tarfile
import time
from pathlib import Path

from backend.core.cluster_config import ClusterProfile, _sub_user

logger = logging.getLogger(__name__)

# Paths/modules/flags are matched against these before reaching a command line.
_MODULE_RE = re.compile(r"^[A-Za-z0-9_.+/-]{1,64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_GENCODE_RE = re.compile(r"^arch=compute_\d{2,3},code=(sm_\d{2,3}|compute_\d{2,3})$")
# Build-arch names carry `+` (Linux-x86_64-g++); it has no shell meaning.
_ARCH_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,40}$")

# Alpine's newest CUDA module is 12.1.1, whose nvcc rejects GCC newer than 12.2 —
# gcc/13 and gcc/14 fail with "unsupported GNU version". The profile's default
# gcc/14.2.0 is therefore unusable for a CUDA build.
# cmake is REQUIRED, not optional: without it charm falls back to ./buildold,
# whose argument grammar differs and which rejects the version string
# (live-confirmed, SLURM 30949599). 3.27.7 not 4.x — CMake 4 drops support for
# cmake_minimum_required < 3.5 and breaks projects of charm 8.0's vintage.
DEFAULT_MODULES = (
    "gcc/11.2.0",
    "cuda/12.1.1",
    "cmake/3.27.7",
    "fftw/3.3.10",
    "tcltk/8.6.11",
)

# EMPTY ON PURPOSE: NAMD's own arch/Linux-x86_64.cuda12 curates the gencode set
# (sm_70/80/90 + compute_70/90 PTX) and warns "Limit CUDADLINKOPTS to architectures
# available in libcufft_static" — NAMD device-links against the STATIC cuFFT, so an
# invented arch list can fail the device link even when nvcc accepts it. The local
# working build overrides nothing and gets that curated set. It covers aa100 (sm_80)
# and ah200 (sm_90) natively and al40 (Ada sm_89) via PTX JIT.
#
# artxpro6000 is unreachable regardless: Blackwell is sm_120 and needs CUDA >= 12.8,
# while Alpine's newest toolkit is 12.1.1.
DEFAULT_GENCODES: tuple[str, ...] = ()

# Local paths never shipped, matched by POSITION not by bare name.
#
# `multicore-linux-x86_64` names TWO different things in a charm tree: the build
# output at `charm-*/multicore-linux-x86_64/` (local objects + a CMakeCache full of
# absolute Ubuntu paths — must not travel) and the architecture DEFINITION at
# `charm-*/src/arch/multicore-linux-x86_64/` (must travel, or charm reports
# "triplet 'multicore-linux-x86_64' is not supported" — live-confirmed, SLURM
# 30949634). A by-name filter cannot tell them apart, so depth matters.
TAR_EXCLUDE_TOP = ("Linux-x86_64-g++", ".git")  # directly under the source root
TAR_EXCLUDE_SUFFIXES = (".o", ".a")
# Directly under a charm-* root only — never under src/arch/.
CHARM_BUILD_DIR_RE = re.compile(r"^[a-z]+(?:-[a-z0-9_]+){1,3}$")
CHARM_KEEP = {
    "src",
    "contrib",
    "doc",
    "docs",
    "examples",
    "tests",
    "benchmarks",
    "tools",
    "util",
    "bin",
    "include",
    "lib",
    "cmake",
    "buildold",
}


def _check(value: str, pattern: re.Pattern, what: str) -> str:
    v = (value or "").strip()
    if not pattern.match(v):
        raise ValueError(f"invalid {what}: {value!r}")
    return v


def validated_modules(modules) -> list[str]:
    return [_check(m, _MODULE_RE, "module name") for m in (modules or DEFAULT_MODULES)]


def validated_gencodes(gencodes) -> list[str]:
    """Each `-gencode` must be a literal arch/code pair — never free text.

    An empty result means "pass no --cuda-gencode at all", leaving NAMD's curated,
    cuFFT-static-compatible set in place.
    """
    return [
        _check(g, _GENCODE_RE, "cuda gencode")
        for g in (DEFAULT_GENCODES if gencodes is None else gencodes)
    ]


def build_dir_for(profile: ClusterProfile, user: str, name: str) -> str:
    """``<project_base>/nadoc_builds/<name>`` — the only place this writes."""
    base = _sub_user(profile.project_base, user).rstrip("/")
    return f"{base}/nadoc_builds/{_check(name, _NAME_RE, 'build name')}"


def build_sbatch(
    *,
    build_dir: str,
    src_dir_name: str,
    tar_name: str,
    modules=None,
    gencodes=None,
    charm_arch: str = "multicore-linux-x86_64",
    namd_arch: str = "Linux-x86_64-g++",
    cores: int = 8,
    partition: str = "acpu",
    qos: str = "cpu-normal",
    walltime: str = "06:00:00",
    job_name: str = "nadoc_namd_build",
) -> str:
    """The batch script that unpacks, builds charm++, configures and builds NAMD.

    Runs as a normal CPU batch job rather than an interactive ``acompile`` session:
    a 30–90 minute build should not depend on a terminal staying open, and CURC's
    rule is only that compiling must not happen on a *login* node.

    No GPU is requested — ``nvcc`` cross-compiles for the target architectures and
    never needs a device present.
    """
    mods = validated_modules(modules)
    gens = validated_gencodes(gencodes)
    src = _check(src_dir_name, _NAME_RE, "source dir name")
    tar = _check(tar_name, _NAME_RE, "tarball name")
    charm = _check(charm_arch, _ARCH_RE, "charm arch")
    arch = _check(namd_arch, _ARCH_RE, "namd arch")
    gencode_args = (
        ("".join(f' \\\n    --cuda-gencode "{g}"' for g in gens)) if gens else ""
    )

    return "\n".join(
        [
            "#!/bin/bash",
            f"#SBATCH --job-name={job_name}",
            f"#SBATCH --output={build_dir}/build_%j.out",
            f"#SBATCH --error={build_dir}/build_%j.out",
            f"#SBATCH --partition={partition}",
            f"#SBATCH --qos={qos}",
            "#SBATCH --nodes=1",
            f"#SBATCH --ntasks={cores}",
            f"#SBATCH --time={walltime}",
            "",
            "source /etc/profile",
            # No `-u`: Alpine's /etc/profile references unbound vars and would abort.
            "set -eo pipefail",
            "module purge",
            f"module load {' '.join(mods)}",
            "echo \"[nadoc] modules: $(module -t list 2>&1 | tr '\\n' ' ')\"",
            'echo "[nadoc] nvcc: $(nvcc --version 2>&1 | tail -1)"',
            'echo "[nadoc] gcc:  $(gcc --version 2>&1 | head -1)"',
            "",
            f"cd '{build_dir}'",
            f"rm -rf '{src}'",
            f"tar xf '{tar}'",
            f"cd '{src}'",
            "",
            "echo '[nadoc] ===== charm++ ====='",
            # The charm tree ships inside the NAMD source; build the multicore (non-MPI)
            # layer, which is what NAMD 3 GPU-resident requires.
            'CHARM_DIR=$(cd "$(ls -d charm-* | head -1)" && pwd)',
            'cd "$CHARM_DIR"',
            f"./build charm++ {charm} gcc --with-production -j{cores}",
            "cd ..",
            "",
            "echo '[nadoc] ===== namd config ====='",
            f"rm -rf '{arch}'",
            # Discover charm's built directory rather than assuming its name.  The CMake
            # path produces `multicore-linux-x86_64`; the legacy ./buildold path appends
            # the compiler (`-gcc`).  Passing the wrong one makes ./config reject the
            # argument and print its usage — live-confirmed, SLURM 30949706.  The local
            # working build records `CHARMARCH = multicore-linux-x86_64` (no suffix).
            f'CHARM_BUILT=$(ls -d "$CHARM_DIR"/{charm}* 2>/dev/null | head -1)',
            '[ -n "$CHARM_BUILT" ] || { echo "[nadoc] ERROR: no charm build dir"; exit 1; }',
            'CHARM_ARCH_NAME=$(basename "$CHARM_BUILT")',
            'echo "[nadoc] charm arch: $CHARM_ARCH_NAME"',
            # Locate the CUDA toolkit WITHOUT assuming a variable name.  Alpine's
            # cuda/12.1.1 does not export CUDA_HOME, so `--cuda-prefix "$CUDA_HOME"`
            # expanded to nothing and config died with a bare "ERROR: No such directory"
            # (live-confirmed, SLURM 30949866).  nvcc always lives at <prefix>/bin/nvcc,
            # so deriving the prefix from it works whatever the site calls the variable.
            'CUDA_PREFIX="${CUDA_HOME:-${CUDA_ROOT:-${CUDAROOT:-}}}"',
            '[ -n "$CUDA_PREFIX" ] || CUDA_PREFIX="$(dirname "$(dirname "$(command -v nvcc)")")"',
            '[ -d "$CUDA_PREFIX" ] || { echo "[nadoc] ERROR: cannot locate the CUDA toolkit"; exit 1; }',
            'echo "[nadoc] cuda prefix: $CUDA_PREFIX"',
            # Same story for FFTW.  NAMD's DEFAULT is the FFTW *2* API, which wants
            # sfftw.h under /Projects/namd2/fftw — a UIUC-internal path that exists on no
            # other machine, so the build died with "fatal error: sfftw.h: No such file"
            # (live-confirmed, SLURM 30950063).  The local working build uses
            # arch/Linux-x86_64.fftw3, i.e. --with-fftw3, so mirror that.
            'FFTW_PREFIX="${FFTW_ROOT:-${FFTW_DIR:-${FFTWROOT:-${FFTW_HOME:-}}}}"',
            'if [ -z "$FFTW_PREFIX" ]; then',
            '  for d in $(echo "${CPATH}:${C_INCLUDE_PATH}" | tr ":" " "); do',
            '    [ -f "$d/fftw3.h" ] && FFTW_PREFIX=$(dirname "$d") && break',
            "  done",
            "fi",
            'if [ -z "$FFTW_PREFIX" ]; then',
            '  for d in $(echo "${LD_LIBRARY_PATH}" | tr ":" " "); do',
            '    ls "$d"/libfftw3* >/dev/null 2>&1 && FFTW_PREFIX=$(dirname "$d") && break',
            "  done",
            "fi",
            '[ -d "$FFTW_PREFIX" ] || { echo "[nadoc] ERROR: cannot locate FFTW3"; exit 1; }',
            # NAMD's fftw3 arch links -lfftw3f — the SINGLE-precision build. Sites often
            # ship only the double-precision libfftw3, which would link-fail an hour into
            # the build. Check now, at zero cost.
            'ls "$FFTW_PREFIX"/lib*/libfftw3f.* >/dev/null 2>&1 || '
            '{ echo "[nadoc] ERROR: $FFTW_PREFIX has no single-precision libfftw3f "'
            '"(NAMD links -lfftw3f); load an fftw module built with --enable-float"; exit 1; }',
            'echo "[nadoc] fftw prefix: $FFTW_PREFIX"',
            # Same derivation for Tcl, and assert 8.6 specifically.
            'TCL_PREFIX="${TCL_ROOT:-${TCLTK_ROOT:-${TCL_HOME:-${TCLROOT:-}}}}"',
            'if [ -z "$TCL_PREFIX" ]; then',
            '  for d in $(echo "${CPATH}:${C_INCLUDE_PATH}" | tr ":" " "); do',
            '    [ -f "$d/tcl.h" ] && TCL_PREFIX=$(dirname "$d") && break',
            "  done",
            "fi",
            'if [ -z "$TCL_PREFIX" ]; then',
            '  for d in $(echo "${LD_LIBRARY_PATH}" | tr ":" " "); do',
            '    ls "$d"/libtcl8.6* >/dev/null 2>&1 && TCL_PREFIX=$(dirname "$d") && break',
            "  done",
            "fi",
            '[ -d "$TCL_PREFIX" ] || { echo "[nadoc] ERROR: cannot locate Tcl"; exit 1; }',
            'ls "$TCL_PREFIX"/lib*/libtcl8.6* >/dev/null 2>&1 || '
            '{ echo "[nadoc] ERROR: $TCL_PREFIX has no libtcl8.6 (NAMD links -ltcl8.6; '
            'tcltk/9.x will not do)"; exit 1; }',
            'echo "[nadoc] tcl prefix: $TCL_PREFIX"',
            "./config " + arch + " \\",
            '    --charm-arch "$CHARM_ARCH_NAME" \\',
            # THE flag that makes this a GPU-RESIDENT build.  It sets
            # -DNODEGROUP_FORCE_REGISTER, which the local working binary carries.  Without
            # it you get a CUDA *offload* build that compiles and links fine and then
            # FATALs on the first `GPUresident on` conf with "not supported on regular
            # multicore builds" — the exact failure NADOC already guards against.
            "    --with-single-node-cuda \\",
            # TCL IS REQUIRED — I got this wrong once and it cost a GPU job.
            #
            # NADOC's confs contain no Tcl *syntax* (no set/proc/if), which is why
            # --without-tcl looked safe.  But `run` and `reinitvels` are Tcl COMMANDS
            # registered by NAMD's embedded interpreter, not native config parameters, and
            # every conf ends in `run N`.  A non-Tcl build rejects them outright:
            #   ERROR: The following variables were set ... but are NOT VALID
            #   ERROR:    run
            #   ERROR:    reinitvels
            # (live-confirmed, SLURM 30954462).
            #
            # arch/Linux-x86_64.tcl hardcodes a UIUC-internal TCLDIR; the local build only
            # survived because Ubuntu supplies tcl.h/libtcl8.6 on system paths.  RHEL 8 has
            # no tcl-devel, so point at Alpine's tcltk module explicitly.  It must be 8.6.x:
            # NAMD links -ltcl8.6, so tcltk/9.0.1 would not satisfy it.
            '    --with-tcl --tcl-prefix "$TCL_PREFIX" \\',
            '    --with-fftw3 --fftw-prefix "$FFTW_PREFIX" \\',
            '    --with-cuda --cuda-prefix "$CUDA_PREFIX" \\',
            f"    {gencode_args}",
            "",
            # Alpine ships Tcl STATIC (libtcl8.6.a).  tclZlib.c inside it needs zlib, which
            # a SHARED libtcl8.6.so pulls in transitively — as it does on the local Ubuntu
            # box, whose `ldd namd3` shows libz.so.1.  With a .a it must be explicit or every
            # Tcl-linking target dies on undefined adler32/deflateInit2_/... (live-confirmed,
            # SLURM 30954671).  A later assignment in Make.config wins over the arch file.
            'echo "TCLLIB = -L$TCL_PREFIX/lib -ltcl8.6 -lz -ldl -lpthread" >> Make.config',
            'grep -n "^TCLLIB" Make.config',
            "",
            "echo '[nadoc] ===== namd build ====='",
            f"cd '{arch}'",
            # Only the binary: psfgen and the other plugins are never used on the cluster
            # (NADOC runs psfgen locally during prep) and only add link surface.
            f"make -j{cores} namd3",
            "",
            # Validate the ARTIFACT, not by running it: this is a CPU node with no GPU,
            # and a -DNAMD_CUDA binary can segfault during CUDA init when no device
            # exists.  Attempt 6 did exactly that and the old `|| true` printed BUILD OK
            # over the top of a core dump — a build script must never claim success after
            # a crash.  Existence + executability + linkage is what a CPU node can honestly
            # check; whether it RUNS is the GPU acceptance test's job.
            'echo "[nadoc] ===== result ====="',
            f"BIN='{build_dir}/{src}/{arch}/namd3'",
            '[ -x "$BIN" ] || { echo "[nadoc] ERROR: no executable produced at $BIN"; exit 1; }',
            'ls -l "$BIN"',
            'echo "[nadoc] linkage:"; ldd "$BIN" 2>&1 | head -15',
            # Confirm from the binary itself that this is the GPU-RESIDENT build.
            # NOTE: plain `grep`, never `grep -q`, in a pipeline under `set -o pipefail`.
            # `grep -q` exits at the first match, `strings` then dies of SIGPIPE (141), and
            # pipefail reports the pipeline as FAILED — which condemned a perfectly good
            # binary as "not a CUDA build" (live-confirmed, SLURM 30954674).
            'strings "$BIN" | grep "Linux-x86_64-multicore-CUDA" >/dev/null || '
            '{ echo "[nadoc] ERROR: binary does not report a multicore-CUDA platform"; exit 1; }',
            'echo "[nadoc] platform: Linux-x86_64-multicore-CUDA (confirmed)"',
            'strings "$BIN" | grep "Tcl_CreateInterp" >/dev/null || '
            '{ echo "[nadoc] ERROR: no Tcl in binary (run/reinitvels would be rejected)"; exit 1; }',
            'echo "[nadoc] tcl: linked (confirmed)"',
            'echo "[nadoc] BUILD OK: $BIN"',
        ]
    )


def namd_bin_path(
    build_dir: str, src_dir_name: str, namd_arch: str = "Linux-x86_64-g++"
) -> str:
    """Where the finished binary lands — what goes into ``gpu_namd_bin``."""
    return f"{build_dir}/{src_dir_name}/{namd_arch}/namd3"


def make_source_tarball(source_dir: Path, out_path: Path) -> Path:
    """Pack the NAMD source, dropping the local build tree and git history.

    The desktop ``Linux-x86_64-g++`` directory in particular must not travel: it is
    the glibc-2.38 binary that cannot run on Alpine, and shipping it would quadruple
    the upload for something we immediately delete.
    """
    source_dir = Path(source_dir)
    if not (source_dir / "config").is_file():
        raise ValueError(
            f"{source_dir} does not look like a NAMD source tree (no ./config)"
        )

    def _skip(info: tarfile.TarInfo):
        # parts[0] is the source-root name added by `arcname`; match relative to it.
        rel = Path(info.name).parts[1:]
        if not rel:
            return info
        if info.name.endswith(TAR_EXCLUDE_SUFFIXES):
            return None
        if rel[0] in TAR_EXCLUDE_TOP:
            return None
        # charm build output: charm-*/<triplet>/..., but NOT charm-*/src/arch/<triplet>
        if (
            len(rel) >= 2
            and rel[0].startswith("charm-")
            and rel[1] not in CHARM_KEEP
            and CHARM_BUILD_DIR_RE.match(rel[1])
        ):
            return None
        return info

    out_path = Path(out_path)
    with tarfile.open(out_path, "w") as tf:
        tf.add(source_dir, arcname=source_dir.name, filter=_skip)
    return out_path


# ── Orchestration ─────────────────────────────────────────────────────────────

# In-process record of the running/last build, so the UI can poll without a job record.
_state: dict = {"phase": "idle"}


def build_state() -> dict:
    return dict(_state)


async def run_namd_build(
    conn,
    profile: ClusterProfile,
    *,
    source_dir: Path,
    name: str = "namd-git",
    modules=None,
    gencodes=None,
    cores: int = 8,
    partition: str = "acpu",
    qos: str = "cpu-normal",
    walltime: str = "06:00:00",
    scratch: Path | None = None,
) -> dict:
    """Pack → upload → submit the NAMD build. Returns once SLURM has the job.

    The build itself then runs unattended; poll with :func:`build_state` or the usual
    ``squeue``/``sacct`` path.
    """
    user = getattr(conn, "user", "") or ""
    if not user:
        raise RuntimeError("not connected to the cluster")

    build_dir = build_dir_for(profile, user, name)
    src_name = Path(source_dir).name
    tar_name = f"{_check(name, _NAME_RE, 'build name')}.tar"

    _state.clear()
    _state.update(
        {"phase": "packing", "build_dir": build_dir, "started_at": time.time()}
    )
    tar_dir = Path(scratch) if scratch else Path(source_dir).parent
    tar_path = tar_dir / tar_name
    await asyncio.get_running_loop().run_in_executor(
        None, make_source_tarball, Path(source_dir), tar_path
    )
    _state.update({"phase": "uploading", "tar_bytes": tar_path.stat().st_size})
    logger.info(
        "namd build: packed %s (%.0f MB)", tar_path, tar_path.stat().st_size / 1e6
    )

    await conn.mkdir_p(build_dir)
    await conn.sftp_put(str(tar_path), f"{build_dir}/{tar_name}")

    script = build_sbatch(
        build_dir=build_dir,
        src_dir_name=src_name,
        tar_name=tar_name,
        modules=modules,
        gencodes=gencodes,
        cores=cores,
        partition=partition,
        qos=qos,
        walltime=walltime,
    )
    _state.update({"phase": "submitting", "script": script})
    remote_sbatch = f"{build_dir}/build.sbatch"
    await conn.sftp_put_text(script, remote_sbatch) if hasattr(
        conn, "sftp_put_text"
    ) else await _put_text(conn, script, remote_sbatch)

    res = await conn.run(f"cd '{build_dir}' && sbatch build.sbatch")
    m = re.search(r"Submitted batch job (\d+)", res.stdout or "")
    if not m:
        _state.update(
            {"phase": "failed", "error": (res.stderr or res.stdout or "")[:500]}
        )
        raise RuntimeError(
            f"build sbatch failed: {(res.stderr or res.stdout or '').strip()[:400]}"
        )

    slurm_id = m.group(1)
    _state.update(
        {
            "phase": "queued",
            "slurm_job_id": slurm_id,
            "log": f"{build_dir}/build_{slurm_id}.out",
            "namd_bin": namd_bin_path(build_dir, src_name),
        }
    )
    logger.info("namd build submitted as SLURM %s → %s", slurm_id, build_dir)
    return build_state()


async def _put_text(conn, text: str, remote: str) -> None:
    """Write a small text file remotely without a local temp file."""
    import tempfile  # noqa: PLC0415

    with tempfile.NamedTemporaryFile("w", suffix=".sbatch", delete=False) as fh:
        fh.write(text)
        tmp = fh.name
    try:
        await conn.sftp_put(tmp, remote)
    finally:
        Path(tmp).unlink(missing_ok=True)
