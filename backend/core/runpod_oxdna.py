"""RunPod execution primitives for NADOC's adaptive-memory oxDNA build.

This is intentionally a headless first phase.  It reuses :mod:`runpod_api` for the
metered pod lifecycle and :mod:`runpod_conn` for SSH, while keeping the oxDNA-specific
build and stage-chain contract here.  Alpine can later reuse the same build manifest
and chain script behind a SLURM launcher.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from backend.core.runpod_api import (
    RunpodClient,
    build_create_payload,
    termination_deadline,
)
from backend.core.runpod_conn import RunpodConnection

OXDNA_URL = "https://github.com/lorenzo-rovigatti/oxDNA.git"
OXDNA_REV = "8028cf33b3cba12992b771156085fa54879f50cd"
REMOTE_ROOT = "/workspace/nadoc_oxdna"
STATUS_FILE = "nadoc_status"
HEARTBEAT_FILE = "nadoc_heartbeat"
PID_FILE = "nadoc_pid"
MAX_CAMPAIGN_USD = 5.0
DEFAULT_VALIDATION_LIFETIME_S = 6_000


class RunpodOxdnaError(RuntimeError):
    """A remote oxDNA build, launch, or budget invariant failed."""


@dataclass(frozen=True)
class OxdnaGpuTarget:
    gpu_id: str
    label: str
    cuda_arch: str


GPU_TARGETS: tuple[OxdnaGpuTarget, ...] = (
    OxdnaGpuTarget("NVIDIA H200", "H200", "90"),
    OxdnaGpuTarget(
        "NVIDIA RTX PRO 6000 Blackwell Server Edition", "RTX PRO 6000", "120"
    ),
)


def target_for_gpu(gpu_id: str) -> OxdnaGpuTarget:
    """Resolve only GPUs architecturally equivalent to Alpine's first targets."""
    for target in GPU_TARGETS:
        if target.gpu_id == gpu_id:
            return target
    supported = ", ".join(t.gpu_id for t in GPU_TARGETS)
    raise RunpodOxdnaError(f"unsupported GPU {gpu_id!r}; expected one of: {supported}")


class CampaignLedger:
    """Durable cumulative spend authorization shared by every attempt in a campaign.

    A provider-side ``terminateAfter`` bounds one pod.  This ledger bounds the sum of
    retries, failed boots, builds, and simulations, which is the user's actual $5 cap.
    Corrupt state fails closed.
    """

    def __init__(self, path: Path, *, cap_usd: float = MAX_CAMPAIGN_USD):
        self.path = Path(path)
        self.cap_usd = float(cap_usd)

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RunpodOxdnaError(f"cannot trust spend ledger {self.path}: {exc}") from exc
        if not isinstance(rows, list):
            raise RunpodOxdnaError(f"cannot trust spend ledger {self.path}: not a list")
        return rows

    def _write(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rows, indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def spent_usd(self, *, now: float | None = None) -> float:
        instant = time.time() if now is None else float(now)
        total = 0.0
        for row in self._rows():
            end = instant if row.get("ended_at") is None else float(row["ended_at"])
            total += max(0.0, end - float(row["started_at"])) / 3600.0 * float(
                row["usd_per_hour"]
            )
        return total

    def remaining_usd(self, *, now: float | None = None) -> float:
        return max(0.0, self.cap_usd - self.spent_usd(now=now))

    def authorize(self, rate_usd_per_hour: float, lifetime_s: int) -> None:
        projected = float(rate_usd_per_hour) * int(lifetime_s) / 3600.0
        remaining = self.remaining_usd()
        if projected > remaining + 1e-9:
            raise RunpodOxdnaError(
                f"pod authorization ${projected:.2f} exceeds campaign remainder "
                f"${remaining:.2f} (cap ${self.cap_usd:.2f})"
            )

    def open_pod(
        self, pod_id: str, rate_usd_per_hour: float, *, note: str = "", now: float | None = None
    ) -> None:
        rows = self._rows()
        if any(r.get("pod_id") == pod_id and r.get("ended_at") is None for r in rows):
            return
        rows.append(
            {
                "pod_id": pod_id,
                "usd_per_hour": float(rate_usd_per_hour),
                "started_at": time.time() if now is None else float(now),
                "ended_at": None,
                "note": note,
            }
        )
        self._write(rows)

    def close_pod(self, pod_id: str, *, now: float | None = None) -> None:
        rows = self._rows()
        ended = time.time() if now is None else float(now)
        for row in rows:
            if row.get("pod_id") == pod_id and row.get("ended_at") is None:
                row["ended_at"] = ended
        self._write(rows)


def engine_dir(cuda_arch: str) -> str:
    return f"{REMOTE_ROOT}/engines/{OXDNA_REV}-adaptive-sm{cuda_arch}"


def render_build_script(cuda_arch: str, patch_remote_path: str) -> str:
    """Idempotent remote build, persisted on the RunPod network volume."""
    if cuda_arch not in {"90", "120"}:
        raise RunpodOxdnaError(f"unsupported CUDA architecture sm_{cuda_arch}")
    install = engine_dir(cuda_arch)
    source = f"{REMOTE_ROOT}/source-{OXDNA_REV}"
    q = shlex.quote
    return f"""#!/usr/bin/env bash
set -euo pipefail
install={q(install)}
source_dir={q(source)}
if [ -x "$install/bin/oxDNA" ]; then
  "$install/bin/oxDNA" --help >/dev/null 2>&1 || true
  exit 0
fi
for cuda_bin in /usr/local/cuda/bin /usr/local/cuda-12.8/bin /usr/local/cuda-12.9/bin /usr/local/cuda-13.0/bin; do
  if [ -x "$cuda_bin/nvcc" ]; then export PATH="$cuda_bin:$PATH"; break; fi
done
command -v nvcc >/dev/null || {{ echo 'FATAL: nvcc missing' >&2; exit 20; }}
if [ ! -d "$source_dir/.git" ]; then git clone {q(OXDNA_URL)} "$source_dir"; fi
git -C "$source_dir" fetch --depth 1 origin {q(OXDNA_REV)}
git -C "$source_dir" checkout --detach {q(OXDNA_REV)}
git -C "$source_dir" reset --hard {q(OXDNA_REV)}
git -C "$source_dir" apply --check {q(patch_remote_path)}
git -C "$source_dir" apply {q(patch_remote_path)}
cmake -S "$source_dir" -B "$source_dir/build-sm{cuda_arch}" \
  -DCMAKE_BUILD_TYPE=Release -DCUDA=ON -DCMAKE_CUDA_ARCHITECTURES={cuda_arch}
cmake --build "$source_dir/build-sm{cuda_arch}" -j"$(nproc)" --target oxDNA DNAnalysis
mkdir -p "$install/bin" "$install/lib"
install -m 0755 "$source_dir/build-sm{cuda_arch}/bin/oxDNA" "$install/bin/oxDNA"
install -m 0755 "$source_dir/build-sm{cuda_arch}/bin/DNAnalysis" "$install/bin/DNAnalysis"
install -m 0755 "$source_dir/build-sm{cuda_arch}/src/liboxdna_common.so" "$install/lib/liboxdna_common.so"
printf '%s\n' {q(OXDNA_REV)} > "$install/source-revision"
printf '%s\n' adaptive-memory > "$install/build-flavor"
"""


def render_chain_script(job_id: str, specs: list[OxdnaStageSpec], cuda_arch: str) -> str:
    """Render a restartable stage chain for an already-uploaded job directory."""
    if not specs:
        raise RunpodOxdnaError("oxDNA job has no stages")
    root = f"{REMOTE_ROOT}/jobs/{job_id}"
    binary = f"{engine_dir(cuda_arch)}/bin/oxDNA"
    lines = [
        "#!/usr/bin/env bash", "set -euo pipefail", f"root={shlex.quote(root)}",
        f"oxdna={shlex.quote(binary)}", "cd \"$root\"",
        f"echo running > {STATUS_FILE}",
        f"(while true; do date +%s > {HEARTBEAT_FILE}; sleep 15; done) &", "hb=$!",
        "trap 'kill \"$hb\" 2>/dev/null || true' EXIT",
    ]
    for idx, spec in enumerate(specs):
        stage = shlex.quote(spec.name)
        prior = "conf.dat" if idx == 0 else f"{specs[idx - 1].name}/last_conf.dat"
        lines += [
            f"if [ ! -s {stage}/last_conf.dat ]; then",
            f"  test -s {shlex.quote(prior)} || {{ echo failed:{stage}:missing_seed > {STATUS_FILE}; exit 31; }}",
            f"  echo stage:{stage} > {STATUS_FILE}",
            f"  (cd {stage} && \"$oxdna\" input.txt) > {stage}/stdout.log 2> {stage}/stderr.log || "
            f"{{ rc=$?; echo failed:{stage}:$rc > {STATUS_FILE}; exit $rc; }}",
            "fi",
        ]
    lines += [f"echo completed > {STATUS_FILE}"]
    return "\n".join(lines) + "\n"


def stage_inputs(job_dir: Path, specs: list[OxdnaStageSpec], remote_job_dir: str) -> dict[str, str]:
    """Render remote-path inputs without mutating the prepared local job."""
    result: dict[str, str] = {}
    for idx, spec in enumerate(specs):
        conf = "conf.dat" if idx == 0 else f"{specs[idx - 1].name}/last_conf.dat"
        forces = (
            f"{remote_job_dir}/{spec.forces_file or 'forces.txt'}"
            if spec.external_forces else None
        )
        parfile = f"{remote_job_dir}/{spec.parfile}" if spec.parfile else None
        text = render_stage_input(
            spec,
            f"{remote_job_dir}/topology.top",
            f"{remote_job_dir}/{conf}",
            forces_name=forces,
            parfile_name=parfile,
        )
        if spec.backend == "CUDA" and "use_edge = true" in text:
            text = text.rstrip() + "\n" + "\n".join(
                (
                    "adaptive_neighbor_list = true",
                    "adaptive_neighbor_initial_capacity = 64",
                    "adaptive_compact_cells = true",
                    "configuration_print_energy = false",
                    "print_initial_energy = false",
                    "no_stdout_energy = true",
                    "verlet_skin = 0.40",
                )
            ) + "\n"
        result[f"{spec.name}/input.txt"] = text
    return result


def manifest(job_id: str, specs: list[OxdnaStageSpec], target: OxdnaGpuTarget) -> dict:
    return {
        "schema": 1,
        "job_id": job_id,
        "engine": "oxdna-adaptive-memory",
        "source_url": OXDNA_URL,
        "source_revision": OXDNA_REV,
        "cuda_arch": target.cuda_arch,
        "gpu_type_id": target.gpu_id,
        "stages": [asdict(spec) for spec in specs],
    }


def validate_fetched_result(result_dir: Path, specs: list[OxdnaStageSpec]) -> dict:
    """Strong completion oracle for a fetched adaptive-memory oxDNA chain."""
    status_path = result_dir / STATUS_FILE
    status = status_path.read_text().strip() if status_path.is_file() else "missing"
    if status != "completed":
        raise RunpodOxdnaError(f"fetched job status is {status!r}, not completed")
    stages: list[dict] = []
    for spec in specs:
        directory = result_dir / spec.name
        last_conf = directory / "last_conf.dat"
        stderr = directory / "stderr.log"
        if not last_conf.is_file() or last_conf.stat().st_size == 0:
            raise RunpodOxdnaError(f"{spec.name} has no fetched last_conf.dat")
        particle_lines = max(0, sum(1 for _ in last_conf.open(errors="replace")) - 3)
        log_text = stderr.read_text(errors="replace") if stderr.is_file() else ""
        adaptive = "CUDA adaptive neighbour telemetry:" in log_text
        runtime = "Total Running Time:" in log_text
        if spec.backend == "CUDA" and (not adaptive or not runtime):
            raise RunpodOxdnaError(
                f"{spec.name} lacks adaptive CUDA telemetry or completion timing"
            )
        stages.append(
            {
                "name": spec.name,
                "particles": particle_lines,
                "last_conf_bytes": last_conf.stat().st_size,
                "adaptive_cuda_telemetry": adaptive,
                "runtime_complete": runtime,
            }
        )
    return {"status": status, "stages": stages}


def budgeted_lifetime_s(
    ledger: CampaignLedger,
    rate_usd_per_hour: float,
    requested_s: int = DEFAULT_VALIDATION_LIFETIME_S,
) -> int:
    """Maximum provider-owned lifetime that cannot cross the cumulative cap."""
    if rate_usd_per_hour <= 0:
        raise RunpodOxdnaError("a positive quoted RunPod rate is required")
    affordable = int(ledger.remaining_usd() * 3600.0 / rate_usd_per_hour)
    lifetime = min(int(requested_s), affordable)
    if lifetime < 300:
        raise RunpodOxdnaError(
            f"only {ledger.remaining_usd():.2f} USD remains; less than five pod-minutes"
        )
    ledger.authorize(rate_usd_per_hour, lifetime)
    return lifetime


async def _upload_text(conn: RunpodConnection, text: str, remote: str) -> None:
    import tempfile

    fd, name = tempfile.mkstemp(prefix="nadoc-runpod-oxdna-")
    os.close(fd)
    local = Path(name)
    try:
        local.write_text(text)
        await conn.sftp_put(str(local), remote)
    finally:
        local.unlink(missing_ok=True)


async def stage_prepared_job(
    conn: RunpodConnection,
    *,
    job_id: str,
    job_dir: Path,
    specs: list[OxdnaStageSpec],
    target: OxdnaGpuTarget,
    patch_path: Path,
) -> str:
    """Upload a self-contained prepared job plus reproducible engine build inputs."""
    required = (job_dir / "topology.top", job_dir / "conf.dat")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RunpodOxdnaError(f"prepared oxDNA job is missing: {', '.join(missing)}")
    if not patch_path.is_file():
        raise RunpodOxdnaError(f"adaptive-memory patch is missing: {patch_path}")

    remote = f"{REMOTE_ROOT}/jobs/{job_id}"
    await conn.mkdir_p(remote)
    patch_remote = f"{REMOTE_ROOT}/adaptive-neighbor-lists.patch"
    await conn.sftp_put(str(patch_path), patch_remote)
    # One level-1 gzip stream avoids paying for many minutes of verbose coordinate
    # text over SFTP (the 451k-nt validation seed shrinks from 72 MB to ~20 MB).
    root_files = sorted(p for p in job_dir.iterdir() if p.is_file())
    fd, archive_name = tempfile.mkstemp(prefix="nadoc-oxdna-stage-", suffix=".tar.gz")
    os.close(fd)
    archive = Path(archive_name)
    try:
        with tarfile.open(archive, "w:gz", compresslevel=1) as bundle:
            for path in root_files:
                bundle.add(path, arcname=path.name, recursive=False)
        remote_archive = f"{remote}/prepared.tar.gz"
        await conn.sftp_put(str(archive), remote_archive)
        extracted = await conn.run(
            f"tar --no-same-owner -xzf {shlex.quote(remote_archive)} "
            f"-C {shlex.quote(remote)} && rm -f {shlex.quote(remote_archive)}",
            timeout=600,
        )
        if extracted.rc != 0:
            raise RunpodOxdnaError(
                f"could not unpack prepared job: {extracted.stderr[-1000:]}"
            )
    finally:
        archive.unlink(missing_ok=True)
    for relative, text_value in stage_inputs(job_dir, specs, remote).items():
        await _upload_text(conn, text_value, f"{remote}/{relative}")
    await _upload_text(
        conn, json.dumps(manifest(job_id, specs, target), indent=2) + "\n",
        f"{remote}/manifest.json",
    )
    await _upload_text(
        conn, render_chain_script(job_id, specs, target.cuda_arch),
        f"{remote}/nadoc_chain.sh",
    )
    await _upload_text(
        conn, render_build_script(target.cuda_arch, patch_remote),
        f"{remote}/build_engine.sh",
    )
    return remote


async def fetch_job_results(
    conn: RunpodConnection, remote: str, destination: Path, specs: list[OxdnaStageSpec]
) -> None:
    """Fetch the compact authoritative outputs; trajectories remain on the volume."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in (STATUS_FILE, HEARTBEAT_FILE, "manifest.json"):
        with contextlib.suppress(Exception):
            await conn.sftp_get(f"{remote}/{name}", str(destination / name))
    for spec in specs:
        local_stage = destination / spec.name
        local_stage.mkdir(parents=True, exist_ok=True)
        for name in ("last_conf.dat", "energy.dat", "stdout.log", "stderr.log"):
            with contextlib.suppress(Exception):
                await conn.sftp_get(
                    f"{remote}/{spec.name}/{name}", str(local_stage / name)
                )


async def run_prepared_job_on_pod(
    *,
    client: RunpodClient,
    network_volume_id: str,
    target: OxdnaGpuTarget,
    quoted_rate_usd_per_hour: float,
    ledger: CampaignLedger,
    job_id: str,
    job_dir: Path,
    specs: list[OxdnaStageSpec],
    patch_path: Path,
    result_dir: Path,
    lifetime_s: int = DEFAULT_VALIDATION_LIFETIME_S,
    poll_s: float = 5.0,
    client_keys: list[str] | None = None,
    on_pod_created: Callable[[str, float], None] | None = None,
    on_update: Callable[[str], None] | None = None,
) -> dict:
    """Provision, build/cache, submit, fetch, and destroy one remote oxDNA job.

    ``terminateAfter`` is provider-owned and the context manager also destroys the pod.
    The ledger is opened at pod creation (billing start), including failed SSH boots.
    """
    spent_before = ledger.spent_usd()
    allowed_lifetime = budgeted_lifetime_s(
        ledger, quoted_rate_usd_per_hour, lifetime_s
    )
    payload = build_create_payload(
        name=f"nadoc-oxdna-{job_id}",
        gpu_type_ids=[target.gpu_id],
        network_volume_id=network_volume_id,
        cloud_type="SECURE",
        terminate_after=termination_deadline(allowed_lifetime),
    )
    pod_id: str | None = None
    actual_rate = quoted_rate_usd_per_hour

    def created(info) -> None:
        nonlocal pod_id, actual_rate
        pod_id = info.id
        actual_rate = float(info.cost_per_hr or quoted_rate_usd_per_hour)
        ledger.open_pod(info.id, actual_rate, note=f"adaptive oxDNA {job_id}")
        if on_pod_created:
            on_pod_created(info.id, actual_rate)
        if on_update:
            on_update(f"pod {info.id} created at ${actual_rate:.2f}/hour")

    try:
        async with client.pod(payload, on_created=created, terminate_on_exit=True) as pod:
            # If the provider returned a rate above the quote, fail before doing costly work.
            projected = actual_rate * allowed_lifetime / 3600.0
            if spent_before + projected > ledger.cap_usd + 1e-6:
                raise RunpodOxdnaError(
                    f"live rate could spend ${projected:.2f}, above remaining campaign budget"
                )
            endpoint = (pod.public_ip, pod.ssh_port)
            if not endpoint[0] or not endpoint[1]:
                raise RunpodOxdnaError("RunPod returned no SSH endpoint")
            keys = client_keys
            if keys is None:
                default_key = Path.home() / ".ssh" / "id_ed25519"
                keys = [str(default_key)] if default_key.is_file() else None
            conn = RunpodConnection(
                host=endpoint[0], port=endpoint[1], pod_id=pod.id,
                client_keys=keys,
            )
            await conn.connect()
            remote = ""
            try:
                if on_update:
                    on_update("staging prepared job and adaptive-memory source patch")
                remote = await stage_prepared_job(
                    conn, job_id=job_id, job_dir=job_dir, specs=specs,
                    target=target, patch_path=patch_path,
                )
                if on_update:
                    on_update(f"building/checking cached sm_{target.cuda_arch} oxDNA")
                built = await conn.run(
                    f"bash {shlex.quote(remote + '/build_engine.sh')}", timeout=2400
                )
                if built.rc != 0:
                    raise RunpodOxdnaError(
                        f"remote oxDNA build failed ({built.rc}): "
                        f"{(built.stderr or built.stdout)[-2000:]}"
                    )
                probe = await conn.run(
                    "nvidia-smi --query-gpu=name,compute_cap,memory.total "
                    "--format=csv,noheader && "
                    f"cat {shlex.quote(engine_dir(target.cuda_arch) + '/build-flavor')}"
                )
                if probe.rc != 0 or "adaptive-memory" not in probe.stdout:
                    raise RunpodOxdnaError(f"remote engine probe failed: {probe.stderr}")
                if on_update:
                    on_update("launching restartable oxDNA stage chain")
                pid = await conn.launch_detached("nadoc_chain.sh", remote)
                await _upload_text(conn, str(pid) + "\n", f"{remote}/{PID_FILE}")
                deadline = time.monotonic() + allowed_lifetime
                status = ""
                while time.monotonic() < deadline:
                    status = (await conn.read_file(f"{remote}/{STATUS_FILE}")).strip()
                    if on_update and status:
                        on_update(status)
                    if status == "completed" or status.startswith("failed:"):
                        break
                    if not await conn.pid_alive(pid):
                        raise RunpodOxdnaError(
                            f"remote chain process exited without terminal status ({status})"
                        )
                    await asyncio.sleep(poll_s)
                else:
                    raise RunpodOxdnaError("remote oxDNA job reached its budget deadline")
                await fetch_job_results(conn, remote, result_dir, specs)
                if status != "completed":
                    raise RunpodOxdnaError(f"remote oxDNA job {status}")
                validation = validate_fetched_result(result_dir, specs)
                return {
                    "pod_id": pod.id, "status": status, "gpu_probe": probe.stdout.strip(),
                    "remote_dir": remote, "result_dir": str(result_dir),
                    "rate_usd_per_hour": actual_rate, "validation": validation,
                }
            finally:
                await conn.close()
    finally:
        if pod_id is not None:
            ledger.close_pod(pod_id)
