"""Constrained Alpine batch builder for NADOC's adaptive-memory oxDNA."""

from __future__ import annotations

import asyncio
import re
import tarfile
import tempfile
import time
from pathlib import Path

from backend.core.cluster_config import ClusterProfile, _sub_user

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_MODULE_RE = re.compile(r"^[A-Za-z0-9_.+/-]{1,64}$")
_ARCH_RE = re.compile(r"^\d{2,3}$")
DEFAULT_MODULES = ("gcc/11.2.0", "cuda/12.1.1", "cmake/3.27.7")
_state: dict = {"phase": "idle"}


def _check(value: str, pattern: re.Pattern, what: str) -> str:
    value = (value or "").strip()
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def build_dir_for(profile: ClusterProfile, user: str, name: str) -> str:
    base = _sub_user(profile.project_base, user).rstrip("/")
    return f"{base}/nadoc_builds/{_check(name, _NAME_RE, 'build name')}"


def make_source_tarball(source_dir: Path, out_path: Path) -> Path:
    source_dir, out_path = Path(source_dir), Path(out_path)

    def skip(info: tarfile.TarInfo):
        rel = Path(info.name)
        if any(part == ".git" or part.startswith("build") for part in rel.parts):
            return None
        if rel.suffix in {".o", ".a", ".so", ".pyc"}:
            return None
        return info

    with tarfile.open(out_path, "w:gz") as archive:
        archive.add(source_dir, arcname=source_dir.name, filter=skip)
    return out_path


def build_sbatch(*, build_dir: str, source_name: str, tar_name: str,
                 modules=None, architectures=None, cores: int = 16,
                 partition: str = "acpu", qos: str = "cpu-normal",
                 walltime: str = "02:00:00") -> str:
    name = _check(source_name, _NAME_RE, "source name")
    tar = _check(tar_name, _NAME_RE, "tarball name")
    mods = [_check(m, _MODULE_RE, "module") for m in (modules or DEFAULT_MODULES)]
    arches = [_check(str(a), _ARCH_RE, "CUDA architecture") for a in (architectures or (80, 90))]
    if not 1 <= int(cores) <= 64:
        raise ValueError("cores must be between 1 and 64")
    arch_arg = ";".join(arches)
    install = f"{build_dir}/install"
    verify_oxdna = (
        f"(LD_LIBRARY_PATH='{install}/lib' '{install}/bin/oxDNA' --help 2>&1 || true) "
        "| grep -F \"Input file '--help' not found\""
    )
    verify_analysis = (
        f"(LD_LIBRARY_PATH='{install}/lib' '{install}/bin/DNAnalysis' --help 2>&1 || true) "
        "| grep -F \"Input file '--help' not found\""
    )
    return "\n".join([
        "#!/bin/bash",
        "#SBATCH --job-name=nadoc_oxdna_build",
        f"#SBATCH --output={build_dir}/build_%j.out",
        f"#SBATCH --error={build_dir}/build_%j.out",
        f"#SBATCH --partition={_check(partition, _NAME_RE, 'partition')}",
        f"#SBATCH --qos={_check(qos, _NAME_RE, 'qos')}",
        "#SBATCH --nodes=1",
        f"#SBATCH --ntasks={int(cores)}",
        f"#SBATCH --time={walltime}",
        "", "source /etc/profile", "set -eo pipefail", "module purge",
        f"module load {' '.join(mods)}",
        f"if test -x '{install}/bin/oxDNA' -a -x '{install}/bin/DNAnalysis' "
        f"-a \"$(cat '{install}/cuda-architectures' 2>/dev/null)\" = '{arch_arg}'; then",
        f"  {verify_oxdna}",
        f"  {verify_analysis}",
        "  echo '[nadoc] existing adaptive-memory oxDNA install verified'",
        "  exit 0",
        "fi",
        f"cd '{build_dir}'", f"rm -rf '{name}' build install", f"tar xzf '{tar}'",
        f"cmake -S '{name}' -B build -DCMAKE_BUILD_TYPE=Release -DCUDA=ON "
        f"-DCMAKE_CUDA_ARCHITECTURES='{arch_arg}' "
        "-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON "
        "-DCMAKE_INSTALL_RPATH='$ORIGIN/../lib'",
        f"cmake --build build -j{int(cores)} --target oxDNA DNAnalysis",
        f"mkdir -p '{install}/bin' '{install}/lib'",
        f"install -m 0755 build/bin/oxDNA build/bin/DNAnalysis '{install}/bin/'",
        f"install -m 0755 build/src/liboxdna_common.so '{install}/lib/'",
        f"cp -L \"$(g++ -print-file-name=libstdc++.so.6)\" '{install}/lib/'",
        f"cp -L \"$(gcc -print-file-name=libgcc_s.so.1)\" '{install}/lib/'",
        f"patchelf --set-rpath '$ORIGIN/../lib' '{install}/bin/oxDNA' "
        f"'{install}/bin/DNAnalysis' '{install}/lib/liboxdna_common.so' "
        "2>/dev/null || true",
        f"printf '%s\\n' adaptive-memory > '{install}/build-flavor'",
        f"printf '%s\\n' '{arch_arg}' > '{install}/cuda-architectures'",
        verify_oxdna,
        verify_analysis,
        "echo '[nadoc] adaptive-memory oxDNA build complete'",
    ]) + "\n"


def build_state() -> dict:
    return dict(_state)


async def run_build(conn, profile: ClusterProfile, *, source_dir: Path,
                    name: str = "oxdna-adaptive", modules=None, architectures=None,
                    cores: int = 16, partition: str = "acpu",
                    qos: str = "cpu-normal", walltime: str = "02:00:00") -> dict:
    user = getattr(conn, "user", "") or ""
    if not user:
        raise RuntimeError("not connected to the cluster")
    build_dir = build_dir_for(profile, user, name)
    source_dir = Path(source_dir)
    tar_name = f"{_check(name, _NAME_RE, 'build name')}.tar.gz"
    tar_path = source_dir.parent / tar_name
    _state.clear(); _state.update(phase="packing", build_dir=build_dir, started_at=time.time())
    await asyncio.get_running_loop().run_in_executor(None, make_source_tarball, source_dir, tar_path)
    _state.update(phase="uploading", tar_bytes=tar_path.stat().st_size)
    await conn.mkdir_p(build_dir)
    await conn.sftp_put(str(tar_path), f"{build_dir}/{tar_name}")
    script = build_sbatch(build_dir=build_dir, source_name=source_dir.name,
                          tar_name=tar_name, modules=modules,
                          architectures=architectures, cores=cores,
                          partition=partition, qos=qos, walltime=walltime)
    remote_script = f"{build_dir}/build.sbatch"
    if hasattr(conn, "sftp_put_text"):
        await conn.sftp_put_text(script, remote_script)
    else:
        await _put_text(conn, script, remote_script)
    result = await conn.run(f"cd '{build_dir}' && sbatch build.sbatch")
    match = re.search(r"Submitted batch job (\d+)", result.stdout or "")
    if not match:
        _state.update(phase="failed", error=(result.stderr or result.stdout or "")[:500])
        raise RuntimeError(f"oxDNA build submission failed: {(result.stderr or result.stdout or '').strip()[:400]}")
    job_id = match.group(1)
    _state.update(phase="queued", slurm_job_id=job_id,
                  log=f"{build_dir}/build_{job_id}.out",
                  oxdna_bin=f"{build_dir}/install/bin/oxDNA")
    return build_state()


async def _put_text(conn, content: str, remote_path: str) -> None:
    """Upload generated text through the base cluster connection interface."""
    with tempfile.NamedTemporaryFile("w", suffix=".sbatch", delete=False) as handle:
        handle.write(content)
        local_path = Path(handle.name)
    try:
        await conn.sftp_put(str(local_path), remote_path)
    finally:
        local_path.unlink(missing_ok=True)
