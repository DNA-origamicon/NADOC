"""Run a NADOC NAMD segment chain on a rented RunPod GPU pod.

The RunPod counterpart of :mod:`backend.core.md_executor` (Alpine/SLURM). The two are
deliberately NOT parallel implementations — everything that is not scheduler-shaped is
**reused** from ``md_executor``:

    staging       md_executor.stage_plan          (unchanged)
    result fetch  md_executor.fetch_outputs       (unchanged)
    live progress md_executor.poll_remote_progress(unchanged)

...because those functions take an explicit ``conn`` duck-type and a pod is an SSH box.
Only the scheduler-shaped parts are new, and they are new because RunPod has no
scheduler at all:

    Alpine   sbatch  → squeue/sacct → scancel
    RunPod   rent a machine → run a script → track a PID → DESTROY the machine

⚠️ **The pod is the meter.** It bills from creation to termination. RunPod now owns the
hard ``terminateAfter`` deadline; NADOC tears down terminal/pre-submit cases immediately
but preserves a submitted chain across supervisor or SSH loss for later adoption.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from backend.core import md_executor
from backend.core.md_job import (
    MdJob, MdStatus, finish_runpod_billing, start_runpod_billing,
)
from backend.core.runpod_api import (
    RunpodClient,
    RunpodError,
    build_create_payload,
    ssh_endpoint,
    termination_deadline,
)
from backend.core.runpod_conn import RunpodConnection, RunpodSSHError
from backend.core.runpod_identity import installation_id, pod_name
from backend.core.slurm_script import LIVE_METRICS_NAME
from backend.core.runpod_script import (
    DEFAULT_BUDGET_USD,
    RESUME_CONF_NAME,
    SETTLE_RETARGET_NAME,
    ChainStep,
    completed_steps,
    heartbeat_is_stale,
    lifetime_for_budget,
    namd_threads,
    parse_status_file,
    plan_execution,
    render_chain_script,
)

log = logging.getLogger(__name__)

# The single-pod kill-switch is BUDGET-DERIVED, not a hardcoded ceiling: the launcher
# computes it from the rate of the pod it actually got (lifetime_for_budget) and passes
# it to submit_job. The stall watchdog kills a HUNG NAMD (no log output for 30 min); the
# lifetime guard caps a run that is merely slower than predicted from billing all night.

REMOTE_ROOT = "/workspace/nadoc_jobs"
CHAIN_SCRIPT = "nadoc_chain.sh"
STATUS_FILE = "nadoc_status"
HEARTBEAT_FILE = "nadoc_heartbeat"
# The post-run fetch must NEVER be able to keep a pod billing.  ``fetch_outputs`` has no
# internal timeout; an SFTP channel that hangs (a real, observed failure — see the runbook's
# "stuck fetch bills an idle pod indefinitely") would otherwise wedge run_job_on_pod BEFORE the
# pod's finally-teardown, billing until a human intervenes.  The volume keeps every output, so
# abandoning a slow fetch is cheap; a live pod is not.  Generous enough for a ~140 MB checkpoint.
FETCH_TIMEOUT_S = 900.0
# How many CONSECUTIVE poll SSH failures to tolerate before pausing the run. The chain runs
# detached (setsid) so the job keeps going on the pod during a network blip; conn.run already
# reconnects+retries per-call, this is the belt-and-suspenders so a longer wobble pauses
# (resumable) rather than crashes the whole run. Reset to 0 on any successful poll.
MAX_POLL_SSH_FAILURES = 5
S3_STAGE_ARCHIVE = ".nadoc_stage/package.tar.gz"


def _volume_file_reusable(rel: str, remote_size: Optional[int], local_size: int) -> bool:
    """Whether a persistent-volume input is safely reusable from size alone.

    Large topology/coordinate payloads dominate upload time and are immutable after prep,
    so a size match is the deliberate cheap identity check.  NAMD configs are tiny and
    may be repaired between attempts without changing byte count (for example margin 30
    to margin 10); always refresh them or a resume can silently execute stale settings.
    """
    return not rel.endswith(".conf") and remote_size == local_size

# The patched NAMD lives on the NETWORK VOLUME, built once per GPU architecture.
# Pods are disposable; the toolchain is not.
#
# MULTI-ARCH: sm_80 (Ampere/A100) + sm_89 (Ada) + sm_90 (Hopper/H100) + sm_120 (Blackwell
# workstation), plus a compute_120 PTX fallback. Built 2026-07-14 by
# experiments/exp43_runpod_bench/build_namd_multiarch.py.
#
# ⚠️ A card outside these archs rents FINE and dies at step 0: "no kernel image is
# available for execution on the device". And ⚠️ `cuobjdump --list-elf` CANNOT tell you the
# coverage — it reports sm_50..sm_120 for BOTH the old 2-arch binary and this one, because
# it shows the union with the bundled NVIDIA libs (cuFFT etc.). The only proof is running
# the card. (The old sm_89+sm_120 binary was PROVEN to fail on an A100 this way, for $0.12.)
NAMD_ON_VOLUME = "/workspace/namd/3.0.2p1-cuda-a80/namd3"


def remote_dir_for(job: MdJob) -> str:
    return f"{REMOTE_ROOT}/{job.job_id}"


def chain_steps_for(job: MdJob, min_name: str) -> list[ChainStep]:
    """The ladder: minimisation, then every segment, in order.

    ``steps`` is carried through because a cell-shrink resume has to run
    ``total - restart_step``, and the pod cannot know the total from the conf alone once
    the conf has been rewritten.
    """
    min_steps = int(getattr(getattr(job, "minimization", None), "steps", 0) or 0)
    steps = [ChainStep(min_name, is_minimization=True, steps=min_steps)]
    steps += [ChainStep(seg.name, steps=int(seg.steps or 0)) for seg in job.segments]
    return steps


# ── Submit ───────────────────────────────────────────────────────────────────


class MdAnalysisMissing(RuntimeError):
    """Tier-A early-stop was requested but the pod cannot import MDAnalysis."""


async def _remote_file_sizes(conn: RunpodConnection, remote: str) -> dict[str, int]:
    """``{path-relative-to-remote: size}`` for everything already on the volume.

    One `find` rather than a stat per file: the package is ~35 files but a round-trip per
    file over SSH to EU-RO-1 is ~150 ms, and we are paying for the pod while we ask.
    Returns {} on any failure — the safe direction is to re-upload, never to skip.
    """
    res = await conn.run(
        f"cd {remote} 2>/dev/null && find . -type f -printf '%s %P\\n'"
    )
    if res.rc != 0:
        return {}
    sizes: dict[str, int] = {}
    for line in res.stdout.splitlines():
        size, _, rel = line.partition(" ")
        if rel and size.isdigit():
            sizes[rel] = int(size)
    return sizes


async def _prestage_package_s3(
    job: MdJob,
    workspace_dir: Path,
    *,
    credentials,
    volume_id: str,
    data_center_id: str,
) -> Optional[str]:
    """Compress and upload missing package inputs before any billing pod exists.

    Returns the pod-visible archive path to extract, or ``None`` when every file is
    already present with the expected size.
    """
    import asyncio
    from backend.core import runpod_s3

    pkg = job.package_dir(workspace_dir)
    plan = list(md_executor.stage_plan(pkg))
    remote = remote_dir_for(job)
    conn = runpod_s3.RunpodS3Connection(
        credentials, volume_id=volume_id, data_center_id=data_center_id,
        remote_root=remote,
    )
    remote_sizes = await conn.file_sizes()
    missing = [
        (path, rel) for path, rel in plan
        if not _volume_file_reusable(rel, remote_sizes.get(rel), path.stat().st_size)
    ]
    total_raw = sum(path.stat().st_size for path, _ in missing)
    if not missing:
        job.remote_submit_progress = None
        job.save(workspace_dir)
        return None

    job.remote_submit_progress = {
        "target": "runpod", "phase": "compress",
        "label": f"Compressing {len(missing)} files before upload (no pod rented)…",
        "fraction": 0.0, "bytes_done": 0, "bytes_total": total_raw,
        "files_done": len(plan) - len(missing), "files_total": len(plan),
        "updated_at": time.time(),
    }
    job.save(workspace_dir)

    # A level-1 gzip archive is a major win for PSF/PDB/ENM text while keeping local CPU
    # time small. It also turns 47 latency-sensitive SFTP streams into one multipart S3
    # object. NamedTemporaryFile supplies an explicit narrow target and is always cleaned.
    fd, archive_name = tempfile.mkstemp(prefix=f"nadoc-{job.job_id}-", suffix=".tar.gz")
    import os
    os.close(fd)
    archive = Path(archive_name)
    try:
        def build_archive() -> None:
            with tarfile.open(archive, "w:gz", compresslevel=1) as tf:
                for path, rel in missing:
                    tf.add(path, arcname=rel, recursive=False)

        await asyncio.to_thread(build_archive)
        compressed = archive.stat().st_size
        last_save = 0.0

        def progress(done: int, _total: int) -> None:
            nonlocal last_save
            now = time.time()
            job.remote_submit_progress = {
                "target": "runpod", "phase": "upload",
                "label": "Uploading compressed package directly to the RunPod volume (no pod rented)…",
                "fraction": done / compressed if compressed else 1.0,
                "bytes_done": done, "bytes_total": compressed,
                "raw_bytes_total": total_raw,
                "files_done": len(plan) - len(missing), "files_total": len(plan),
                "updated_at": now,
            }
            if now - last_save >= 0.5 or done >= compressed:
                job.save(workspace_dir)
                last_save = now

        remote_archive = f"{remote}/{S3_STAGE_ARCHIVE}"
        await conn.sftp_put(str(archive), remote_archive, on_progress=progress)
        return remote_archive
    finally:
        archive.unlink(missing_ok=True)


async def _extract_s3_stage(conn: RunpodConnection, remote: str, archive_path: str) -> None:
    """Expand the pre-uploaded package on the mounted volume, then remove its archive."""
    import shlex

    result = await conn.run(
        f"mkdir -p {shlex.quote(remote)} && "
        # RunPod's network volume may root-squash chown.  Tar archives created by the
        # desktop carry the desktop uid/gid; restoring those owners is unnecessary and
        # can make an otherwise successful extraction exit nonzero after writing files.
        f"tar --no-same-owner -xzf {shlex.quote(archive_path)} "
        f"-C {shlex.quote(remote)} && "
        f"rm -f {shlex.quote(archive_path)}"
    )
    if result.rc != 0:
        raise RunpodError(f"Could not unpack the S3-staged package: {result.stderr.strip()}")


async def _seed_from_parent(conn, job: MdJob, remote: str, plan: list) -> None:
    """Copy the parent's identical staged files into the child's remote dir, on the pod.

    Safe by construction: only names the child's own ``stage_plan`` asks for, and only
    when the parent's copy is byte-for-byte the same SIZE. Nothing from ``output/`` and
    none of the chain sentinels can come across, so the child cannot inherit a checkpoint
    that would make the skip-guard declare its segments already done.
    """
    parent_remote = f"{REMOTE_ROOT}/{job.parent_job_id}"
    parent_sizes = await _remote_file_sizes(conn, parent_remote)
    if not parent_sizes:
        return

    reusable = [
        rel
        for local_path, rel in plan
        if parent_sizes.get(rel) == local_path.stat().st_size
    ]
    if not reusable:
        return

    cmds = " ; ".join(
        f"cp -n {parent_remote}/{rel} {remote}/{rel} 2>/dev/null" for rel in reusable
    )
    # mkdir the subdirs (forcefield/) first, else cp has nowhere to land.
    dirs = sorted({rel.rsplit("/", 1)[0] for rel in reusable if "/" in rel})
    mk = " ; ".join(f"mkdir -p {remote}/{d}" for d in dirs)
    await conn.run(f"{mk} ; {cmds} ; true", timeout=300.0)
    log.info(
        "runpod: seeded %d file(s) from parent %s on the volume (no re-upload)",
        len(reusable),
        job.parent_job_id,
    )


async def _ensure_mdanalysis(conn: RunpodConnection) -> None:
    """Make ``import MDAnalysis`` work on the pod, or raise.

    Tier A's whole job is to make the ladder affordable, and it does that by SKIPPING
    chunks. Its fail-safe is to NOT skip — which is right for the science and ruinous
    for the wallet: the un-accelerated ladder is ~55 h / ~$41, so a missing MDAnalysis
    turns a $8 night into a pod that bills until the kill-switch guillotines it
    mid-ladder, leaving neither a finished relaxation nor the money to retry.

    So this is a hard gate, not a best-effort ``|| true``. The pytorch image ships
    numpy+scipy but not MDAnalysis; installing it is a ~30 s pip on an already-rented
    pod, and if that fails we want to know before the ladder starts.
    """
    # retries: setup runs over a freshly-booted pod whose SSH sometimes drops a channel
    # (EU-RO-1 flake); a transient drop here once aborted the whole run. probe + pip are
    # idempotent, so reconnect-and-retry rather than crash.
    probe = (
        'python3 -c "import MDAnalysis, numpy, scipy; print(MDAnalysis.__version__)"'
    )
    res = await conn.run(probe, retries=3)
    if res.rc == 0:
        log.info("runpod: MDAnalysis %s already present", res.stdout.strip())
        return

    log.info("runpod: MDAnalysis absent — installing (Tier-A early-stop needs it)")
    # The pytorch image's python is PEP 668 "externally managed" and a plain pip install
    # dies with `error: externally-managed-environment`. --break-system-packages is the
    # documented override and is entirely safe HERE: the pod is a disposable container we
    # destroy within hours, so there is no OS install to preserve. Try the polite form
    # first anyway, in case a future image isn't marked externally-managed.
    attempts = (
        "python3 -m pip install --no-input --quiet MDAnalysis",
        "python3 -m pip install --no-input --quiet --break-system-packages MDAnalysis",
    )
    last = ""
    for cmd in attempts:
        res = await conn.run(cmd, timeout=900.0, retries=2)
        if res.rc == 0:
            break
        last = (res.stderr or res.stdout).strip()
        log.warning("runpod: `%s` failed: %s", cmd.split("--")[0].strip(), last[:200])
    else:
        raise MdAnalysisMissing(f"could not install MDAnalysis on the pod: {last}")

    res = await conn.run(probe, retries=3)
    if res.rc != 0:
        raise MdAnalysisMissing(
            f"MDAnalysis still not importable after install: {res.stderr or res.stdout}"
        )
    log.info("runpod: MDAnalysis %s installed", res.stdout.strip())


async def submit_job(
    job: MdJob,
    workspace_dir: Path,
    *,
    conn: RunpodConnection,
    min_name: str,
    n_atoms: int,
    vcpus: int,
    gpu_resident: bool = True,
    max_lifetime_s: Optional[int] = None,
) -> int:
    """Stage the package, write the chain script, launch it detached. Returns its PID.

    Idempotent by construction: the chain script skips any step whose
    ``output/<name>.coor`` already exists on the network volume. So calling this again
    after a spot-pod reclaim IS the resume path — no separate resume codepath, unlike
    Alpine (which needs one because SLURM walltimes cut MID-segment).
    """
    remote = remote_dir_for(job)
    pkg = job.package_dir(workspace_dir)

    # Prepared packages can predate adaptive minimisation. Upgrade the tiny config
    # before stage_plan computes file sizes, so a stopped job (including the current
    # expensive 3.24M-atom run) gets the controller on its next submission and only
    # this changed file is re-uploaded to the persistent volume.
    from backend.core.md_protocols import upgrade_minimization_conf_adaptive

    manifest_path = pkg / "manifest.json"
    prepared_manifest = json.loads(manifest_path.read_text())
    prepared_min = prepared_manifest.get("minimization") or {}
    prepared_min_name = str(prepared_min.get("name") or min_name)
    if prepared_min.get("adaptive", True):
        upgrade_minimization_conf_adaptive(
            pkg / f"{prepared_min_name}.conf",
            min_name=prepared_min_name,
            n_atoms=n_atoms,
            max_steps=int(prepared_min.get("steps") or 0),
        )

    last_progress_save = 0.0
    last_progress_fraction = -1.0

    def submit_progress(
        label: str,
        fraction: float,
        *,
        force: bool = False,
        **detail,
    ) -> None:
        """Expose byte-accurate RunPod staging instead of simulated NAMD steps."""
        nonlocal last_progress_save, last_progress_fraction
        now = time.time()
        fraction = max(0.0, min(1.0, float(fraction)))
        # A multi-GB package produces thousands of SFTP chunks. Keep the UI fluid while
        # avoiding thousands of atomic job.json replacements per minute.
        if not force and now - last_progress_save < 0.5 and fraction - last_progress_fraction < 0.002:
            return
        job.remote_submit_progress = {
            "target": "runpod",
            "phase": "upload",
            "label": label,
            "fraction": fraction,
            "updated_at": now,
            **detail,
        }
        job.save(workspace_dir)
        last_progress_save = now
        last_progress_fraction = fraction

    await conn.mkdir_p(remote)

    # REUSED from the Alpine executor — this is the whole point of the conn duck-type.
    #
    # But SKIP what is already there. The staging target is the NETWORK VOLUME
    # (REMOTE_ROOT=/workspace/nadoc_jobs, volumeMountPath=/workspace), so it OUTLIVES the
    # pod: a relaunch after any failure — or the production child of the same job — finds
    # the package already uploaded. Re-sending it is not free: the 1.9M-atom 3x6x400
    # package is 1.21 GB, which is ~15 min of BILLABLE pod time at domestic upstream
    # speed, before NAMD runs a single step. Compare by size, which is enough to catch a
    # truncated transfer and costs one `find` instead of hashing 1.21 GB over SSH.
    plan = list(md_executor.stage_plan(pkg))
    # A production child shares its parent's structure files (build_replica_package
    # HARDLINKS the PSF/PDB/forcefield rather than copying them). The parent's copies are
    # already on the volume, so hand them across server-side — a local `cp` on the volume
    # instead of a 1.21 GB re-upload over domestic ADSL, which is 15 min of pod time on
    # the very run where wall-clock is nanoseconds.
    #
    # Copies ONLY files in the child's own stage_plan, and only when the size matches.
    # A blanket `cp -r` of the parent's directory would drag across output/*.coor and the
    # chain sentinels — and the skip-guard would then declare the child's segments already
    # complete and run NOTHING.
    if job.parent_job_id:
        await _seed_from_parent(conn, job, remote, plan)

    remote_sizes = await _remote_file_sizes(conn, remote)
    file_sizes = [local_path.stat().st_size for local_path, _ in plan]
    bytes_total = sum(file_sizes)
    bytes_done = sum(
        size
        for (local_path, rel), size in zip(plan, file_sizes)
        if _volume_file_reusable(rel, remote_sizes.get(rel), size)
    )
    skipped = sum(
        _volume_file_reusable(rel, remote_sizes.get(rel), size)
        for (_, rel), size in zip(plan, file_sizes)
    )
    sent = 0
    submit_progress(
        "Checking files already on the RunPod volume…",
        bytes_done / bytes_total if bytes_total else 1.0,
        force=True,
        bytes_done=bytes_done,
        bytes_total=bytes_total,
        files_done=skipped,
        files_total=len(plan),
    )
    files_done = skipped
    supports_progress = "on_progress" in inspect.signature(conn.sftp_put).parameters
    for (local_path, rel), file_size in zip(plan, file_sizes):
        if _volume_file_reusable(rel, remote_sizes.get(rel), file_size):
            continue
        base_bytes = bytes_done

        def on_file_progress(current: int, _total: int) -> None:
            current_done = min(file_size, max(0, current))
            submit_progress(
                f"Uploading {local_path.name} to the RunPod volume…",
                (base_bytes + current_done) / bytes_total if bytes_total else 1.0,
                bytes_done=base_bytes + current_done,
                bytes_total=bytes_total,
                files_done=files_done,
                files_total=len(plan),
            )

        if supports_progress:
            await conn.sftp_put(
                str(local_path), f"{remote}/{rel}", on_progress=on_file_progress
            )
        else:  # Preserve the executor's duck-type contract for test/custom connections.
            await conn.sftp_put(str(local_path), f"{remote}/{rel}")
        sent += 1
        files_done += 1
        bytes_done += file_size
        submit_progress(
            f"Uploaded {files_done} of {len(plan)} package files",
            bytes_done / bytes_total if bytes_total else 1.0,
            force=True,
            bytes_done=bytes_done,
            bytes_total=bytes_total,
            files_done=files_done,
            files_total=len(plan),
        )
    log.info(
        "runpod: staged %d file(s), reused %d already on the volume", sent, skipped
    )

    # The cell-shrink resume writer. Staged ALWAYS — an NPT box crossing its patch grid
    # has nothing to do with early-stop, and without this the chain script's "bounded
    # retry" just re-runs the identical failing conf four times.
    from backend.core import remote_resume_conf

    await md_executor._put_text(
        conn,
        Path(remote_resume_conf.__file__).read_text(),
        f"{remote}/{RESUME_CONF_NAME}",
        workspace_dir,
        job,
    )

    # The canonical settle-restraint coordinate rewrite.  The local runner imports this
    # exact module; staging it makes the pod path byte-for-byte equivalent.
    from backend.core import remote_settle_retarget

    await md_executor._put_text(
        conn,
        Path(remote_settle_retarget.__file__).read_text(),
        f"{remote}/{SETTLE_RETARGET_NAME}",
        workspace_dir,
        job,
    )

    manifest = json.loads((pkg / "manifest.json").read_text())
    early_stop = md_executor._early_stop_on(job, manifest)
    tier = md_executor._early_stop_tier(job)

    # The node live-metrics collector — the SAME script the Alpine path stages, and the
    # only thing that makes a rented run's progress bar move mid-segment. Without it,
    # progress advances only when a whole segment lands its .coor, so a single-segment
    # 200 ns production reads 0% for its entire life.
    #
    # `poll_job` already `cat`s the blob this writes (it delegates to the shared
    # `md_executor.poll_remote_progress`), so staging it costs the poll nothing extra —
    # the endpoint was there all along with nothing writing to it.
    from backend.core import remote_live_metrics  # noqa: PLC0415

    await md_executor._put_text(
        conn,
        Path(remote_live_metrics.__file__).read_text(),
        f"{remote}/{LIVE_METRICS_NAME}",
        workspace_dir,
        job,
    )

    # Full health stays on the pod: stage the canonical implementation plus a tiny
    # periodic wrapper. The output is metadata-sized and is collected by the same poll
    # as live speed/progress. Install/prove dependencies before NAMD starts so the Health
    # card cannot silently remain empty for an entire paid run.
    from backend.core import md_health, remote_live_health  # noqa: PLC0415
    from backend.core.slurm_script import LIVE_HEALTH_NAME, STAGED_MD_HEALTH_NAME

    await md_executor._put_text(
        conn,
        Path(md_health.__file__).read_text(),
        f"{remote}/{STAGED_MD_HEALTH_NAME}",
        workspace_dir,
        job,
    )
    await md_executor._put_text(
        conn,
        Path(remote_live_health.__file__).read_text(),
        f"{remote}/{LIVE_HEALTH_NAME}",
        workspace_dir,
        job,
    )
    await _ensure_mdanalysis(conn)

    if early_stop:
        # Same three scripts the sbatch stages, uploaded through the same helper — the
        # conn duck-type means the Alpine stager works verbatim over an SSH'd pod.
        await md_executor._stage_early_stop_evaluator(
            conn, remote, workspace_dir, job, tier=tier
        )
        if tier == "A":
            # Tier A fails SAFE to HOLD, and "hold" on a rented pod means running the
            # FULL 9.6M-step ladder at ~$41. A silent import failure here is therefore
            # a budget event, not a degraded-quality event: prove MDAnalysis is
            # importable NOW, while we have spent cents, not at chunk 1 of stage 4.
            # Already proven above for the continuous health collector.
            pass

    script = render_chain_script(
        steps=chain_steps_for(job, min_name),
        remote_dir=remote,
        namd_bin=NAMD_ON_VOLUME,
        threads=namd_threads(vcpus),
        devices="0",
        max_lifetime_s=max_lifetime_s,
        manifest=manifest,
        early_stop_relax=early_stop,
        early_stop_tier=tier,
        name_stem=job.name_stem,
    )
    # job_dir(), never workspace/md_jobs/<id> — this job is ARCHIVED onto an external
    # drive and the hardcoded path would quietly resurrect a folder on the system disk.
    tmp = job.job_dir(workspace_dir) / CHAIN_SCRIPT
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(script)
    await conn.sftp_put(str(tmp), f"{remote}/{CHAIN_SCRIPT}")
    await conn.run(f"chmod +x {remote}/{CHAIN_SCRIPT}")

    pid = await conn.launch_detached(f"{remote}/{CHAIN_SCRIPT}", remote)
    job.runpod_pid = pid
    job.remote_submit_progress = None
    job.remote_scratch_dir = remote
    job.remote_project_dir = remote  # one filesystem: no project/scratch split
    job.status = MdStatus.running
    job.error = None

    # PERSIST. Nothing here used to be written to disk, so a launcher that died left NO
    # record of which pod, which pid, or which remote dir — and the launcher's `finally`
    # is the only thing that destroys the pod. A crash therefore produced an orphaned,
    # billing pod that nothing could even identify, let alone reap or resume. NAMD itself
    # is detached (setsid, output on the network volume) and carries on regardless, so
    # this record is the ONLY link back to a run that is still very much alive.
    job.save(workspace_dir)

    log.info(
        "runpod: job %s launched on pod %s as pid %s",
        job.job_id,
        job.runpod_pod_id,
        pid,
    )
    return pid


# ── Poll ─────────────────────────────────────────────────────────────────────


async def poll_job(
    job: MdJob, *, conn: RunpodConnection, now: Optional[int] = None
) -> dict:
    """One poll pass: chain status + heartbeat + live segment progress.

    Returns ``{state, segment, alive, stale, advanced}``. ``state`` is the chain
    script's own sentinel, which is authoritative — the PID being alive only tells you
    bash is running, not that NAMD is healthy.
    """
    now = now or int(time.time())

    status = parse_status_file(
        await conn.read_file(f"{job.remote_scratch_dir}/{STATUS_FILE}")
    )
    hb_raw = (
        await conn.read_file(f"{job.remote_scratch_dir}/{HEARTBEAT_FILE}")
    ).strip()
    heartbeat = int(hb_raw) if hb_raw.isdigit() else None
    job.runpod_heartbeat = heartbeat

    alive = await conn.pid_alive(job.runpod_pid) if job.runpod_pid else False
    stale = heartbeat_is_stale(heartbeat, now)

    # REUSED: the same ls-based progress scan Alpine uses.
    advanced = await md_executor.poll_remote_progress(job, conn=conn)

    return {
        "state": status["state"],
        "segment": status["segment"],
        "alive": alive,
        "stale": stale,
        "advanced": advanced,
    }


async def remote_completed_steps(job: MdJob, *, conn: RunpodConnection) -> set[str]:
    """Which ladder steps already have final coords on the volume."""
    res = await conn.run(
        f"ls -1 {job.remote_scratch_dir}/output/*.coor 2>/dev/null || true"
    )
    return completed_steps(res.stdout)


# ── Cancel ───────────────────────────────────────────────────────────────────


async def cancel_job(job: MdJob, *, conn: RunpodConnection) -> None:
    """Kill the chain script and everything it spawned.

    Kills the process GROUP (``launch_detached`` used ``setsid``, so the chain script is
    a session leader). Killing only the bash PID would orphan a running NAMD, which then
    keeps the GPU busy and the pod billing while the UI cheerfully reads "stopped" —
    exactly the local stop-kill bug, but with a meter attached.
    """
    if job.runpod_pid:
        await conn.run(f"kill -TERM -{int(job.runpod_pid)} 2>/dev/null || true")
        await conn.run(f"kill -KILL -{int(job.runpod_pid)} 2>/dev/null || true")
    job.runpod_pid = None


# ── Fetch ────────────────────────────────────────────────────────────────────


async def fetch_results(
    job: MdJob, workspace_dir: Path, *, conn: RunpodConnection
) -> bool:
    """Pull outputs back, refusing to call a partial download successful."""
    for attempt in range(3):
        if await md_executor.fetch_outputs(job, workspace_dir, conn=conn):
            return True
        log.warning(
            "runpod job %s: output fetch incomplete (%d/3) — retrying before teardown",
            job.job_id,
            attempt + 1,
        )
    raise RuntimeError(
        "RunPod job finished, but its outputs could not be downloaded completely after "
        "three attempts. They remain safe on the RunPod network volume."
    )


# ── Whole-job orchestration ──────────────────────────────────────────────────


def pod_payloads_for(
    job: MdJob,
    n_atoms: int,
    *,
    network_volume_id: str,
    interruptible: bool = False,
    budget_usd: float = DEFAULT_BUDGET_USD,
) -> list[dict]:
    """Size the pod from the system (MEASURED VRAM model), cheapest tier first.

    Returns MULTIPLE payloads because the network volume PINS the pod to its datacenter,
    and a tier is often unavailable there: RunPod answers 500 "There are no instances
    currently available". Community 4090s in particular are frequently absent from the
    volume's region — which is why a hand-made pod silently lands on SECURE at ~2x the
    price ($0.69/hr vs $0.34). We try cheapest-first and walk down rather than fail.
    """
    if interruptible:
        raise RunpodError(
            "Interruptible RunPod launches are disabled: provider-enforced "
            "terminateAfter is available only on the on-demand creation path."
        )
    plan = plan_execution(n_atoms)
    if plan["gpu"] is None:
        raise RunpodError(plan["reason"])
    # Launch is an explicit local action, so a copied job record changes ownership to
    # this installation for the new pod rather than inheriting another machine's claim.
    job.runpod_owner_id = installation_id()
    name = pod_name(job.design_name, job.job_id)
    # gpuTypeIds is a PRIORITY LIST — hand RunPod every card that fits, cheapest first,
    # and let it pick whatever is actually free in the volume's datacenter.
    gpu_ids = [g.key for g in plan["gpus"]]

    # The card the user CHOSE in the Job Wizard goes to the front.
    #
    # Without this the wizard shows one card and rents another: the wizard's table comes from
    # `runpod_select` (live stock, live prices, arch-vs-build gate, $/ns AND ns/day ranking)
    # while this list comes from `plan_execution` — VRAM fit against the pinned price table,
    # cheapest first, none of the other three. They routinely disagree.
    #
    # It is a PREFERENCE, not a replacement: the network volume pins the datacenter, so a
    # single named card frequently comes back 500 "no instances currently available". Keeping
    # the rest as fallbacks is what makes a launch survive that. A card that does not fit this
    # system is ignored rather than honoured — it is not in `plan["gpus"]`, and renting a card
    # too small for the box just OOMs at step 0.
    chosen = getattr(job, "runpod_gpu_key", None)
    if chosen and chosen in gpu_ids:
        gpu_ids = [chosen] + [g for g in gpu_ids if g != chosen]

    # SECURE ONLY (user decision, 2026-07-14). Community Cloud is a pool of third-party
    # hosts: cheaper, but variable reliability, and in EU-RO-1 (where the network volume
    # pins us) it frequently has NO card at all — every COMMUNITY attempt so far returned
    # 500 "There are no instances currently available". For an unattended overnight run
    # the halved price is not worth the variance.
    from backend.core.runpod_script import DEFAULT_MAX_USD_PER_HOUR, GPU_TYPES

    # ``terminateAfter`` is a GraphQL creation field and that mutation accepts one GPU
    # type. Try the ranked cards individually. Each gets a conservative provider-owned
    # deadline; the on-pod timer is retained as a second, actual-rate-derived guard.
    prices = {g.key: float(g.usd_per_hour) for g in GPU_TYPES}
    payloads = []
    for gpu_id in gpu_ids:
        price_ceiling = max(DEFAULT_MAX_USD_PER_HOUR, prices.get(gpu_id, 0.0))
        payloads.append(
            build_create_payload(
                name=name,
                gpu_type_ids=[gpu_id],
                network_volume_id=network_volume_id,
                interruptible=interruptible,
                cloud_type="SECURE",
                terminate_after=termination_deadline(
                    lifetime_for_budget(budget_usd, price_ceiling)
                ),
            )
        )
    return payloads


def pod_payload_for(
    job: MdJob, n_atoms: int, *, network_volume_id: str, interruptible: bool = False
) -> dict:
    """The preferred (cheapest) payload. See :func:`pod_payloads_for` for the fallbacks."""
    return pod_payloads_for(
        job, n_atoms, network_volume_id=network_volume_id, interruptible=interruptible
    )[0]


async def run_job_on_pod(
    job: MdJob,
    workspace_dir: Path,
    *,
    client: RunpodClient,
    network_volume_id: str,
    min_name: str,
    n_atoms: int,
    client_keys: Optional[list[str]] = None,
    poll_s: float = 30.0,
    sleep=None,
    interruptible: bool = False,
    on_pod: Optional[Callable[[str], None]] = None,
    budget_usd: float = DEFAULT_BUDGET_USD,
) -> MdStatus:
    """Provision → stage → run, with provider-owned expiry and explicit teardown.

    The provider deadline is installed before the pod exists. Once the chain has been
    submitted, controller/SSH failures leave it running for later adoption; terminal
    outcomes and failures before submission still trigger immediate teardown.
    """
    import asyncio

    sleep = sleep or asyncio.sleep
    from backend.core import runpod_s3

    s3_credentials = runpod_s3.resolve_credentials()
    s3_data_center = None
    s3_stage_archive = None
    if s3_credentials:
        with contextlib.suppress(Exception):
            volumes = await client.list_network_volumes()
            selected = next((v for v in volumes if v.get("id") == network_volume_id), None)
            s3_data_center = selected and selected.get("data_center_id")
    # Transfer BEFORE provisioning. The previous SFTP path rented a $0.74/hr GPU and
    # then left it idle for ~40 minutes while a 1.9 GiB package crossed Colorado→Romania.
    # S3 is podless; compression + multipart parallelism make it faster and cost $0 GPU.
    if s3_credentials and s3_data_center:
        s3_stage_archive = await _prestage_package_s3(
            job, workspace_dir, credentials=s3_credentials,
            volume_id=network_volume_id, data_center_id=s3_data_center,
        )
    payloads = pod_payloads_for(
        job,
        n_atoms,
        network_volume_id=network_volume_id,
        interruptible=interruptible,
        budget_usd=budget_usd,
    )
    job.runpod_terminate_after = min(p["terminateAfter"] for p in payloads)
    job.save(workspace_dir)

    # cheapest tier first; fall back when the volume's datacenter has no instances
    def _created(info):
        # The pod is BILLING from this instant — before wait_for_ssh, before the yield.
        # A host too old for the image's CUDA boots, never starts sshd, and bills for the
        # whole timeout. Registering only at the yield made that spend invisible.
        job.runpod_pod_id = info.id
        start_runpod_billing(job, info.id, info.cost_per_hr)
        job.save(workspace_dir)
        client.record_lifecycle(
            "pod_claimed",
            pod_id=info.id,
            job_id=job.job_id,
            terminate_after=job.runpod_terminate_after,
        )
        if on_pod is not None:
            on_pod(info.id)

    submitted = False
    try:
        async with client.pod(
            payloads[0],
            fallbacks=payloads[1:],
            on_created=_created,
            terminate_on_exit=False,
        ) as pod:
            job.runpod_pod_id = pod.id
            # ...and PERSIST it the instant it exists, for exactly the same reason: a crash
            # between here and the first save would leave a billing pod that no later process
            # could even name, let alone reap.
            job.save(workspace_dir)
            if on_pod is not None:
                # Register the pod id the INSTANT it exists. A caller that cannot name the
                # pod cannot kill it, and an unkillable pod bills until a human notices.
                on_pod(pod.id)
            endpoint = ssh_endpoint(pod)
            if endpoint is None:  # wait_for_ssh guarantees this, belt+braces
                raise RunpodError(f"pod {pod.id} exposed no SSH endpoint")
            host, port = endpoint

            conn = RunpodConnection(
                host=host, port=port, pod_id=pod.id, client_keys=client_keys
            )
            await conn.connect()
            try:
                if s3_stage_archive:
                    await _extract_s3_stage(
                        conn, remote_dir_for(job), s3_stage_archive
                    )
                vcpus = await _remote_vcpus(conn)
                # Derive the kill-switch from the rate of the pod we ACTUALLY got — not a
                # hardcoded duration. The fallback list means we may be on the $0.34 card or
                # the $0.82 one, and the same budget buys very different wall-clocks.
                lifetime_s = lifetime_for_budget(budget_usd, pod.cost_per_hr)
                log.info(
                    "runpod: pod %s at $%s/hr, $%.2f budget -> kill-switch at %.1f h",
                    pod.id,
                    pod.cost_per_hr,
                    budget_usd,
                    lifetime_s / 3600,
                )
                await submit_job(
                    job,
                    workspace_dir,
                    conn=conn,
                    min_name=min_name,
                    n_atoms=n_atoms,
                    vcpus=vcpus,
                    max_lifetime_s=lifetime_s,
                )
                submitted = True

                await _supervise_run(
                    job,
                    workspace_dir,
                    conn=conn,
                    pod_id=pod.id,
                    poll_s=poll_s,
                    sleep=sleep,
                    fetch=not bool(s3_credentials and s3_data_center),
                )
            finally:
                await conn.close()
    except BaseException:
        # A pod that never received the detached chain has nothing useful to preserve.
        # Once submitted, however, SSH/NADOC loss must not kill healthy computation;
        # RunPod's terminateAfter remains the hard bill boundary.
        if job.runpod_pod_id and not submitted:
            job.remote_submit_progress = None
            with contextlib.suppress(Exception):
                await client.terminate_pod(
                    job.runpod_pod_id,
                    reason="failure_before_chain_submission",
                    job_id=job.job_id,
                )
            finish_runpod_billing(job, job.runpod_pod_id)
            with contextlib.suppress(Exception):
                job.save(workspace_dir)
        raise

    if job.runpod_pod_id and (
        job.status in (MdStatus.completed, MdStatus.failed) or job.user_stopped
    ):
        await client.terminate_pod(
            job.runpod_pod_id,
            reason=("user_stop" if job.user_stopped else f"job_{job.status.value}"),
            job_id=job.job_id,
        )
        finish_runpod_billing(job, job.runpod_pod_id)

    # The expensive GPU is now destroyed and its meter is closed. Download from the
    # persistent volume directly; this can take hours without adding compute charges.
    if (
        s3_credentials and s3_data_center
        and job.status in (MdStatus.completed, MdStatus.failed)
        and not job.user_stopped
    ):
        try:
            s3_conn = runpod_s3.RunpodS3Connection(
                s3_credentials, volume_id=network_volume_id,
                data_center_id=s3_data_center, remote_root=remote_dir_for(job),
            )
            await fetch_results(job, workspace_dir, conn=s3_conn)
        except Exception as exc:  # noqa: BLE001 — results remain safe on the volume
            job.status = MdStatus.paused
            job.resumable = True
            job.error = f"Podless result download failed: {exc}"
            job.save(workspace_dir)

    job.runpod_pid = None
    # Returning from supervision means this attempt's pod is terminal or was explicitly
    # destroyed. Close the meter for completed, failed, stopped, and reclaimed attempts.
    finish_runpod_billing(job, job.runpod_pod_id)
    return job.status


async def _supervise_run(
    job: MdJob,
    workspace_dir: Path,
    *,
    conn: RunpodConnection,
    pod_id: str,
    poll_s: float = 30.0,
    sleep=None,
    fetch: bool = True,
) -> MdStatus:
    """Watch an ALREADY-LAUNCHED chain to a terminal state, then fetch what exists.

    Split out of ``run_job_on_pod`` so a re-attach can reuse it verbatim: the difference
    between starting a run and inheriting one is entirely in how the pod and the chain
    script come to exist, not in how they are watched. Sharing this is what stops the two
    paths drifting on the things that decide whether a pod keeps billing — the SSH-wobble
    tolerance, the resumable/paused classification, and the bounded fetch.

    Does NOT terminate the pod: that belongs to the caller's context manager.
    """
    import asyncio

    sleep = sleep or asyncio.sleep

    ssh_failures = 0
    while True:
        try:
            st = await poll_job(job, conn=conn)
            ssh_failures = 0
        except RunpodSSHError as exc:
            # A transient SSH drop must not abort a live run — the chain is detached
            # and the volume keeps every completed step. conn.run already reconnects
            # per-call; tolerate a longer wobble here, then pause (resumable).
            ssh_failures += 1
            if ssh_failures > MAX_POLL_SSH_FAILURES:
                log.error(
                    "lost SSH to pod %s for %d consecutive polls — pausing "
                    "(resumable; the volume holds all progress): %s",
                    pod_id,
                    ssh_failures,
                    exc,
                )
                job.status = MdStatus.paused
                job.resumable = True
                job.error = (
                    "Lost SSH to the pod; resume to continue from the checkpoint."
                )
                break
            log.warning(
                "poll SSH error %d/%d — reconnecting and retrying: %s",
                ssh_failures,
                MAX_POLL_SSH_FAILURES,
                exc,
            )
            await conn._reconnect()
            await sleep(poll_s)
            continue
        if st["state"] == "completed":
            job.status = MdStatus.completed
            break
        if st["state"] == "failed":
            job.status = MdStatus.failed
            job.error = f"NAMD failed at segment {st['segment']}"
            break
        if st["state"] == "lifetime":
            job.status = MdStatus.paused
            job.resumable = True
            job.error = "Pod hit its maximum lifetime; resume to continue."
            break
        if not st["alive"] and st["stale"]:
            # The pod was reclaimed (interruptible) or the script died. Both are
            # resumable: the volume holds every completed step.
            job.status = MdStatus.paused
            job.resumable = True
            job.error = "Pod stopped mid-run; resume to continue from the checkpoint."
            break
        # Persist every pass: progress and health advanced by poll_job are what the UI
        # reads, and a supervisor that dies between terminal states must not take the
        # last known step count with it.
        job.save(workspace_dir)
        await sleep(poll_s)

    # Always fetch what exists — even a failed/paused run has useful output.
    # BOUNDED: a hung fetch must not keep the pod billing.  On timeout, abandon the
    # fetch and fall through to teardown — the outputs remain on the volume.
    if not fetch:
        job.save(workspace_dir)
        return job.status
    try:
        await asyncio.wait_for(
            fetch_results(job, workspace_dir, conn=conn),
            timeout=FETCH_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        log.error(
            "fetch_outputs exceeded %.0fs — ABANDONING the fetch so the pod is destroyed "
            "(outputs persist on the volume; pull them later). This is the stuck-fetch "
            "billing guard.",
            FETCH_TIMEOUT_S,
        )
        job.status = MdStatus.paused
        job.resumable = True
        job.error = (
            "RunPod finished, but downloading its outputs timed out. The results remain "
            "safe on the network volume; resume to retry the download."
        )
    except Exception as exc:  # noqa: BLE001 — preserve the finished remote result
        log.error("runpod output fetch failed: %s", exc)
        job.status = MdStatus.paused
        job.resumable = True
        job.error = str(exc)
    job.save(workspace_dir)
    return job.status


async def reattach_job_on_pod(
    job: MdJob,
    workspace_dir: Path,
    *,
    client: RunpodClient,
    client_keys: Optional[list[str]] = None,
    poll_s: float = 30.0,
    sleep=None,
    on_pod: Optional[Callable[[str], None]] = None,
) -> MdStatus:
    """Inherit a run already going on a pod this process did not start → fetch → **destroy**.

    The counterpart to ``run_job_on_pod`` for a pod that outlived its supervisor — the
    ordinary case after a dev-server reload, and the recovery case after a crash. NAMD is
    detached (``setsid``, output on the network volume), so it carries on regardless; what
    it loses is the thing that was watching it, which is also the only thing that would
    have destroyed the pod. Adopting restores both.

    **Never relaunches a live chain.** If the recorded PID is still alive we only resume
    watching it; starting a second chain would put two NAMDs on one GPU, each corrupting
    the other's restart files. A chain that has died is left to the ordinary resume path
    rather than being restarted from here, because a fresh launch needs the staging and
    budget decisions that ``run_job_on_pod`` makes.
    """
    if not job.runpod_pod_id:
        raise RunpodError(f"job {job.job_id} has no pod to adopt")

    from backend.core import runpod_s3

    s3_credentials = runpod_s3.resolve_credentials()
    s3_data_center = None
    volume_id = job.runpod_volume_id
    if s3_credentials and volume_id:
        with contextlib.suppress(Exception):
            volumes = await client.list_network_volumes()
            selected = next((v for v in volumes if v.get("id") == volume_id), None)
            s3_data_center = selected and selected.get("data_center_id")

    async with client.adopt(
        job.runpod_pod_id,
        terminate_on_exit=not bool(job.runpod_terminate_after),
    ) as pod:
        if on_pod is not None:
            on_pod(pod.id)  # registered = killable; do this before anything can fail
        endpoint = ssh_endpoint(pod)
        if endpoint is None:
            raise RunpodError(f"pod {pod.id} exposed no SSH endpoint")
        host, port = endpoint
        conn = RunpodConnection(
            host=host, port=port, pod_id=pod.id, client_keys=client_keys
        )
        await conn.connect()
        try:
            alive = await conn.pid_alive(job.runpod_pid) if job.runpod_pid else False
            log.info(
                "runpod: adopted pod %s for job %s (chain pid %s %s)",
                pod.id,
                job.job_id,
                job.runpod_pid,
                "alive" if alive else "GONE — will fetch and tear down",
            )
            if alive:
                job.status = MdStatus.running
                job.error = None
                job.save(workspace_dir)
            await _supervise_run(
                job, workspace_dir, conn=conn, pod_id=pod.id, poll_s=poll_s, sleep=sleep,
                fetch=not bool(s3_credentials and s3_data_center),
            )
        finally:
            await conn.close()

    if (
        job.runpod_terminate_after
        and job.runpod_pod_id
        and (job.status in (MdStatus.completed, MdStatus.failed) or job.user_stopped)
    ):
        await client.terminate_pod(
            job.runpod_pod_id,
            reason=("user_stop" if job.user_stopped else f"job_{job.status.value}"),
            job_id=job.job_id,
        )

    if (
        s3_credentials and s3_data_center and volume_id
        and job.status in (MdStatus.completed, MdStatus.failed)
        and not job.user_stopped
    ):
        try:
            await fetch_results(
                job, workspace_dir,
                conn=runpod_s3.RunpodS3Connection(
                    s3_credentials, volume_id=volume_id,
                    data_center_id=s3_data_center, remote_root=remote_dir_for(job),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            job.status = MdStatus.paused
            job.resumable = True
            job.error = f"Podless result download failed: {exc}"

    job.runpod_pid = None
    job.save(workspace_dir)
    return job.status


async def _remote_vcpus(conn: RunpodConnection) -> int:
    res = await conn.run("nproc")
    out = res.stdout.strip()
    return int(out) if out.isdigit() else 8


async def open_pod_connection(
    job: MdJob,
    *,
    client: RunpodClient,
    client_keys: Optional[list[str]] = None,
    timeout: float = 60.0,
) -> RunpodConnection:
    """An SSH connection to a job's LIVE pod, for a read-only errand beside the run.

    ⚠️ **Deliberately not ``client.pod()`` or ``client.adopt()``.** Both are context
    managers that DESTROY the pod in their ``finally`` — correct when you own the run,
    catastrophic for a peek at one: fetching a display frame would kill the paid job it
    was fetching from. ``get_pod`` is a plain read.

    The caller owns the connection and MUST ``await conn.close()``. Runs alongside the
    supervisor's own connection rather than sharing it: a second SSH channel to the same
    box is free, whereas interleaving an ad-hoc SFTP with the poll loop's traffic on one
    connection is a race for no gain.
    """
    if not job.runpod_pod_id:
        raise RunpodError(f"job {job.job_id} has no pod")
    try:
        pod = await client.get_pod(job.runpod_pod_id)
    except RunpodError as exc:
        # A destroyed pod 404s here. That is the ORDINARY end of every run, so it must
        # read as one — the raw "GET /pods/xxx failed (404)" surfaced verbatim in the UI.
        if "404" in str(exc):
            raise RunpodError(
                "That pod no longer exists — it was destroyed when the run ended."
            ) from exc
        raise
    if not pod.is_running:
        raise RunpodError(f"pod {pod.id} is {pod.desired_status}, not running")
    endpoint = ssh_endpoint(pod)
    if endpoint is None:
        raise RunpodError(f"pod {pod.id} exposed no SSH endpoint")
    host, port = endpoint
    conn = RunpodConnection(
        host=host, port=port, pod_id=pod.id, client_keys=client_keys
    )
    await conn.connect(timeout=timeout, retries=1)
    return conn
