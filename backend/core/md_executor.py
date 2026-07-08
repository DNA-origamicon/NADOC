"""Remote executor — run a prepared NADOC MD job on Alpine (SLURM) via SSH.

Phase 3 of the alpine-cluster-submission plan.  Wires together Phase 1
(``cluster_ssh`` live transport) and Phase 2 (``slurm_script`` / ``cluster_resources``)
into the job lifecycle: **stage → submit → poll → fetch → cancel**.

The whole ladder runs as ONE ``sbatch`` on the compute node (plan decision #1), so
this module never orchestrates segment-by-segment — it uploads the prepared package,
submits, polls ``squeue``/``sacct`` for status, and on completion mirrors the results
back to the login node and pulls them down locally so the existing job detail view
(and the locally-recomputed health/metrics) keep working.

Design for testability, exactly like ``cluster_ssh``: every async orchestration
function takes an explicit ``conn`` (a ``ClusterConnection`` or any object exposing
``run`` / ``sftp_put`` / ``sftp_get`` / ``mkdir_p`` / ``mirror`` / ``user``).  Tests
pass a fake conn returning canned ``sbatch``/``squeue``/``sacct`` output — no network.
The pure parsers below are unit-tested directly.

All asyncssh ops must run on the event loop the connection was created on (the main
uvicorn loop), so the only callers are the async cluster endpoints and the async MD
supervisor — never a worker thread.  The sync ``namd_runner`` seam (start/stop/
reconcile) treats ``execution_target != "local"`` jobs as hands-off.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path, PurePosixPath

from backend.core.cluster_config import ClusterProfile, resolve_paths
from backend.core.md_job import MdJob, MdStatus
from backend.core import md_protocols
from backend.core.md_protocols import strip_gpu_resident
from backend.core.slurm_script import (
    EARLY_STOP_EVAL_NAME,
    EARLY_STOP_HEALTH_NAME,
    STAGED_MD_HEALTH_NAME,
    generate_sbatch,
    is_gpu_target,
)

logger = logging.getLogger(__name__)

_SBATCH_NAME = "nadoc_job.sbatch"

# Local package artifacts NOT uploaded: a fresh remote run creates its own output/
# and logs.  (Directory names checked against any path component; suffixes against
# the file name.)
_SKIP_DIRS = {"output"}
_SKIP_SUFFIXES = {".log"}


# ── Pure parsers (unit-tested directly) ───────────────────────────────────────

def parse_sbatch_job_id(stdout: str) -> str | None:
    """Extract the numeric job id from ``Submitted batch job <id>``."""
    m = re.search(r"Submitted batch job (\d+)", stdout or "")
    return m.group(1) if m else None


def parse_namd_modules(text: str) -> list[str]:
    """NAMD module strings from ``module -t avail namd`` terse output.

    Terse output is one entry per line, with ``/path/to/modulefiles:`` section
    headers interleaved; keep only ``namd/...`` (and a bare ``namd``) tokens.  Used
    to confirm/pick the exact GPU vs CPU NAMD module name live (the one thing the
    embedded profile can only guess).
    """
    mods: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().rstrip(":")
        low = line.lower()
        if low == "namd" or low.startswith("namd/"):
            mods.append(line)
    return sorted(set(mods))


def parse_state_lines(text: str) -> dict[str, str]:
    """Parse ``squeue``/``sacct`` ``<jobid>|<STATE>`` lines → ``{jobid: STATE}``.

    Handles ``sacct`` sub-step rows (``12345.batch``) by keeping only the base id,
    and ``CANCELLED by 12345`` by taking the first token of the state.  A later row
    for the same base id wins only if the existing one is not already terminal —
    but since we normalise to base ids and callers pass one id set, first-write is
    fine; we simply keep the first non-empty state seen per base id.
    """
    states: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        job_field, _, state_field = line.partition("|")
        base = job_field.strip().split(".")[0]
        state = state_field.strip().split()[0] if state_field.strip() else ""
        if base and state and base not in states:
            states[base] = state.upper()
    return states


# SLURM state code → NADOC lifecycle bucket.  Mirrors the Appendix status-code map.
_STATE_MAP = {
    "PD": "pending", "PENDING": "pending", "CF": "pending", "CONFIGURING": "pending",
    "R": "running", "RUNNING": "running", "CG": "running", "COMPLETING": "running",
    "S": "running", "SUSPENDED": "running", "RQ": "running", "REQUEUED": "pending",
    "CD": "completed", "COMPLETED": "completed",
    "CA": "cancelled", "CANCELLED": "cancelled",
    "F": "failed", "FAILED": "failed",
    "TO": "failed", "TIMEOUT": "failed",
    "NF": "failed", "NODE_FAIL": "failed",
    "PR": "failed", "PREEMPTED": "failed",
    "OOM": "failed", "OUT_OF_MEMORY": "failed",
    "BF": "failed", "BOOT_FAIL": "failed",
    "DL": "failed", "DEADLINE": "failed",
}


def map_slurm_state(code: str) -> str:
    """Map a raw SLURM state code to ``pending``/``running``/``completed``/
    ``cancelled``/``failed`` (unknown → ``running`` so we keep polling rather than
    prematurely declaring a terminal state)."""
    return _STATE_MAP.get((code or "").strip().upper(), "running")


_TIMEOUT_STATES = {"TO", "TIMEOUT", "DL", "DEADLINE"}


def is_timeout_state(raw: str) -> bool:
    """True for a SLURM state that means "ran out of walltime" (resumable), as opposed
    to a real error (FAILED/OOM/NODE_FAIL — those are not offered a resume)."""
    return (raw or "").strip().upper() in _TIMEOUT_STATES


def bucket_to_md_status(bucket: str) -> MdStatus:
    """Map a lifecycle bucket to the persisted MdStatus."""
    return {
        "pending": MdStatus.queued,
        "running": MdStatus.running,
        "completed": MdStatus.completed,
        "cancelled": MdStatus.stopped,
        "failed": MdStatus.failed,
    }.get(bucket, MdStatus.running)


def is_remote_active(status: MdStatus) -> bool:
    """A remote job still worth polling (submitted, not yet terminal)."""
    return status in (MdStatus.queued, MdStatus.running)


def parse_progress_listing(text: str) -> tuple[set[str], set[str]]:
    """From a remote ``ls output/*.coor; ls *.log`` dump → ``(finished, started)``
    segment-name sets.

    A segment with a final ``output/<name>.coor`` has finished; a segment with a
    top-level ``<name>.log`` has at least started.  Restart coords
    (``<name>.restart.coor``) and the minimization step yield names that don't match
    any real segment, so they are harmlessly ignored by the caller (which intersects
    against ``job.segments``).
    """
    finished: set[str] = set()
    started: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        name = PurePosixPath(line).name
        if name.endswith(".coor"):
            finished.add(name[: -len(".coor")])
        elif name.endswith(".log"):
            started.add(name[: -len(".log")])
    return finished, started


def apply_remote_progress(job: MdJob, finished: set[str], started: set[str]) -> bool:
    """Update segment statuses + ``current_segment_idx`` from a remote listing so a
    RUNNING remote job shows live p10→p50→… progress instead of sitting at segment 0
    until the whole ladder finishes.  Returns True if anything changed.

    A segment is ``done`` once its ``.coor`` exists, ``running`` once its log exists
    (but no ``.coor`` yet), else ``pending``.  A ``done`` segment is never regressed
    (a lingering ``.log`` after the ``.coor`` lands must not flip it back).
    ``current_segment_idx`` tracks the first running segment (else the done count) so
    the detail timeline points at the live stage.
    """
    changed = False
    running_idx: int | None = None
    for idx, seg in enumerate(job.segments):
        if seg.name in finished:
            new = "done"
        elif seg.name in started:
            new = "running"
            if running_idx is None:
                running_idx = idx
        else:
            new = "pending"
        if seg.status == "done":
            new = "done"  # never regress a completed segment
        if seg.status != new:
            seg.status = new
            changed = True
    n_done = sum(1 for s in job.segments if s.status == "done")
    new_idx = running_idx if running_idx is not None else min(n_done, max(len(job.segments) - 1, 0))
    if job.current_segment_idx != new_idx:
        job.current_segment_idx = new_idx
        changed = True
    return changed


def stage_plan(package_dir: Path) -> list[tuple[Path, str]]:
    """Files to upload for a remote run: every package file EXCEPT the local
    ``output/`` tree and ``*.log`` run artifacts.  Returns ``(abs_local, relpath)``
    pairs with POSIX-style relative paths (for the remote layout)."""
    plan: list[tuple[Path, str]] = []
    package_dir = Path(package_dir)
    for p in sorted(package_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(package_dir)
        parts = set(rel.parts[:-1])
        if parts & _SKIP_DIRS:
            continue
        if p.suffix in _SKIP_SUFFIXES:
            continue
        plan.append((p, rel.as_posix()))
    return plan


# ── Async orchestration (drive from the main-loop async endpoints/supervisor) ──

def _default_conn():
    from backend.core import cluster_ssh
    return cluster_ssh.get_manager()


def _early_stop_on(job: MdJob, manifest: dict) -> bool:
    """Whether to emit + stage the in-sbatch early-stop accelerator for this run.

    On only when the job opted in AND the package is not a declash design (a declash
    manifest is rejected by ``generate_sbatch`` anyway — its mid-chain reference
    rebuild can't run in a bare sbatch, so early-stop is moot there).  Production-only
    replica packages carry no eligible relaxation chunks, so this is a harmless no-op
    even if a replica ever inherited the flag.
    """
    return bool(getattr(job, "early_stop_relax", False)) and not manifest.get("declash")


def _early_stop_tier(job: MdJob) -> str:
    t = str(getattr(job, "early_stop_tier", "B") or "B").upper()
    return t if t in ("A", "B") else "B"


async def _stage_early_stop_evaluator(conn, remote_dir: str, workspace_dir: Path,
                                      job: MdJob, *, tier: str) -> None:
    """Upload the node early-stop scripts next to the confs.

    Tier B: just the stdlib ``nadoc_cutoff_eval.py`` (the sbatch runs
    ``python3 nadoc_cutoff_eval.py`` from the run cwd).  Tier A additionally ships
    ``nadoc_health_eval.py`` + a verbatim ``md_health.py`` (the WC step needs the
    real ``run_health_check``; it imports numpy/scipy/MDAnalysis on the node).  We
    ship the exact module sources the tests pin, so the node runs byte-for-byte what
    was validated offline.
    """
    from backend.core import md_health, remote_cutoff_eval, remote_health_eval

    async def _stage(module, remote_name):
        await _put_text(conn, Path(module.__file__).read_text(),
                        f"{remote_dir}/{remote_name}", workspace_dir, job)

    await _stage(remote_cutoff_eval, EARLY_STOP_EVAL_NAME)
    if tier == "A":
        await _stage(remote_health_eval, EARLY_STOP_HEALTH_NAME)
        await _stage(md_health, STAGED_MD_HEALTH_NAME)


async def submit_job(
    job: MdJob,
    workspace_dir: Path,
    *,
    profile: ClusterProfile,
    resources: dict,
    conn=None,
) -> MdJob:
    """Stage the prepared package to Alpine and submit the whole-ladder sbatch.

    Idempotent guard: a job that already has a ``slurm_job_id`` is not re-submitted.
    Populates ``execution_target``/``cluster_name``/``slurm_job_id``/remote dirs/
    ``resources`` and leaves the job ``queued`` (SLURM will move it to running).
    """
    conn = conn or _default_conn()
    if job.slurm_job_id:
        logger.info("[%s] already submitted as SLURM %s; skipping re-submit",
                    job.job_id, job.slurm_job_id)
        return job

    user = getattr(conn, "user", "") or ""
    if not user:
        raise RuntimeError("not connected to the cluster (no user on the session)")

    paths = resolve_paths(profile, user, job.job_id)
    project_dir = paths["project_dir"]
    scratch_dir = paths["scratch_dir"]

    package_dir = job.package_dir(workspace_dir)
    if not (package_dir / "manifest.json").exists():
        raise RuntimeError(f"prepared package not found at {package_dir}")
    manifest = _read_manifest(package_dir)

    # Build the sbatch first — a declash / bad-partition manifest raises here,
    # before we touch the network.
    early_stop = _early_stop_on(job, manifest)
    es_tier = _early_stop_tier(job)
    if early_stop:
        manifest["early_stop_tier"] = es_tier          # generate_sbatch reads this
    sbatch = generate_sbatch(manifest, profile, resources, scratch_dir,
                             job_name=job.name_stem or job.design_name,
                             early_stop_relax=early_stop)

    # 1) stage package → project (persistent), skipping local output/logs.
    #    NADOC's confs bake ``GPUresident on`` into the fast (HMR/4 fs) segments —
    #    the local pipeline is GPU-resident.  A CPU/multicore Alpine target FATALs on
    #    that, so amend EVERY staged .conf to strip it, matching the sbatch's CPU exec
    #    path (same is_gpu_target decision).  Only the p10 warmup confs lack it; this
    #    makes all of them consistent with the chosen partition.
    gpu = is_gpu_target(profile, resources)
    plan = stage_plan(package_dir)
    logger.info("[%s] staging %d files → %s (gpu=%s)", job.job_id, len(plan), project_dir, gpu)
    await conn.mkdir_p(project_dir)
    for local_path, rel in plan:
        remote = f"{project_dir}/{rel}"
        if not gpu and local_path.suffix == ".conf":
            amended = strip_gpu_resident(local_path.read_text())
            await _put_text(conn, amended, remote, workspace_dir, job)
        else:
            await conn.sftp_put(str(local_path), remote)

    # 1b) stage the node early-stop scripts into project (mirrored to scratch next).
    if early_stop:
        await _stage_early_stop_evaluator(conn, project_dir, workspace_dir, job, tier=es_tier)

    # 2) mirror project → scratch (two-filesystem model — jobs MUST run on scratch).
    await conn.mirror(project_dir, scratch_dir)

    # 3) upload the sbatch into scratch and submit from there.
    remote_sbatch = f"{scratch_dir}/{_SBATCH_NAME}"
    await _put_text(conn, sbatch, remote_sbatch, workspace_dir, job)
    res = await conn.run(f"cd {_shq(scratch_dir)} && sbatch {_SBATCH_NAME}")
    if res.rc != 0:
        raise RuntimeError(f"sbatch failed (rc={res.rc}): {res.stderr or res.stdout}")
    slurm_id = parse_sbatch_job_id(res.stdout)
    if not slurm_id:
        raise RuntimeError(f"could not parse SLURM job id from: {res.stdout!r}")

    job.execution_target = "alpine"
    job.cluster_name = profile.name
    job.slurm_job_id = slurm_id
    job.slurm_state = "PENDING"
    job.remote_project_dir = project_dir
    job.remote_scratch_dir = scratch_dir
    job.resources = resources
    job.status = MdStatus.queued
    job.queued_at = time.time()
    job.error = None
    job.failure_kind = None
    job.user_stopped = False
    job.save(workspace_dir)
    logger.info("[%s] submitted to %s as SLURM %s", job.job_id, profile.name, slurm_id)
    return job


async def list_namd_modules(conn=None) -> list[str]:
    """Live-discover the NAMD modules available on the cluster (``module avail namd``).

    Lets the user confirm the exact GPU (CUDA) vs CPU NAMD module name — the embedded
    Alpine profile can only guess the GPU one (``namd/3.0.1_gpu``).  Combines stdout +
    stderr because LMOD writes ``module avail`` to stderr.
    """
    conn = conn or _default_conn()
    res = await conn.run("source /etc/profile >/dev/null 2>&1; module -t avail namd 2>&1")
    return parse_namd_modules(f"{res.stdout}\n{res.stderr}")


async def poll_status(job: MdJob, *, conn=None) -> tuple[str, str]:
    """Poll SLURM for one job → ``(raw_state, bucket)``.

    Tries ``squeue`` first (active jobs); a job missing from squeue has finished, so
    fall back to ``sacct``.  A job absent from both (e.g. purged accounting) is
    treated as ``completed`` — the outputs, if any, are fetched and health recomputed.
    """
    conn = conn or _default_conn()
    jid = job.slurm_job_id
    if not jid:
        return ("", "running")

    sq = await conn.run(f"squeue -j {jid} --format='%i|%T' --noheader")
    states = parse_state_lines(sq.stdout)
    raw = states.get(jid)
    if raw is None:
        sa = await conn.run(
            f"sacct -j {jid} --format=JobID,State --parsable2 --noheader"
        )
        raw = parse_state_lines(sa.stdout).get(jid)
    if raw is None:
        return ("", "completed")
    return (raw, map_slurm_state(raw))


async def poll_remote_progress(job: MdJob, *, conn=None) -> bool:
    """Cheap remote scan of which segments have finished on the cluster so a RUNNING
    remote job shows live segment progress.  Lists ``output/*.coor`` (finished) and
    top-level ``*.log`` (started) in one ``ls`` — no file transfer.  Updates segment
    statuses + ``current_segment_idx`` in place; returns True if progress advanced.
    """
    conn = conn or _default_conn()
    scratch = job.remote_scratch_dir
    if not scratch or not job.segments:
        return False
    res = await conn.run(
        f"cd {_shq(scratch)} && ls -1 output/*.coor 2>/dev/null; ls -1 *.log 2>/dev/null"
    )
    finished, started = parse_progress_listing(res.stdout)
    return apply_remote_progress(job, finished, started)


async def resume_job(
    job: MdJob, workspace_dir: Path, *, profile: ClusterProfile,
    resources: dict | None = None, conn=None,
) -> MdJob:
    """Resume a timed-out remote job from its latest checkpoint (user-triggered).

    ``resources`` overrides the SLURM resources for the resumed run (e.g. a longer
    walltime after a promising short run) — the user reviews/edits them in the same
    card used to submit.  ``None`` keeps the job's existing resources.

    Resume is NEVER automatic — Duo 2FA needs the user present — so this runs only on
    an explicit ``/resume-remote`` after the user reconnects.  Because the backend is
    present, we can be smart (unlike a bare node):

    1. Scan scratch for which segments already finished (``output/<name>.coor``).
    2. Find the first UNfinished segment (the interrupted one).
    3. If it wrote a mid-segment NAMD checkpoint (``output/<name>.restart.xsc`` with a
       usable step), generate a resume conf (continue from the restart, run only the
       remaining steps) and upload it; otherwise it simply re-runs fresh (the
       idempotent sbatch handles that — it timed out before the first checkpoint).
    4. Regenerate + upload the sbatch (completed segments skip; the interrupted one
       runs its resume conf) and submit.  New SLURM id, ``resubmit_count`` bumped.
    """
    conn = conn or _default_conn()
    scratch = job.remote_scratch_dir
    if not scratch:
        raise RuntimeError("no remote scratch dir to resume into")
    if resources:
        # Reviewed/edited resources for the resumed run (e.g. a longer walltime).
        job.resources = resources
    package_dir = job.package_dir(workspace_dir)
    manifest = _read_manifest(package_dir)

    # 1) which segments finished on the cluster.
    ls = await conn.run(
        f"cd {_shq(scratch)} && ls -1 output/*.coor 2>/dev/null; ls -1 *.log 2>/dev/null"
    )
    finished, _ = parse_progress_listing(ls.stdout)

    # 2) first unfinished segment.
    interrupted = next((s for s in job.segments if s.name not in finished), None)
    resume_conf_for: dict[str, str] = {}
    if interrupted is not None:
        # 3) mid-segment checkpoint? read its restart step.
        total_steps = _segment_total_steps(manifest, interrupted.name)
        step = await _remote_restart_step(conn, scratch, interrupted.name, workspace_dir, job)
        if step and total_steps and 0 < step < total_steps:
            conf_path = package_dir / f"{interrupted.name}.conf"
            resume_text = md_protocols.build_remote_resume_conf(
                conf_path.read_text(), segment_name=interrupted.name,
                restart_step=step, total_steps=total_steps,
                cont_index=(job.resubmit_count or 0) + 1,
            )
            if not is_gpu_target(profile, job.resources or {}):
                resume_text = strip_gpu_resident(resume_text)
            resume_base = f"{interrupted.name}.resume"
            await _put_text(conn, resume_text, f"{scratch}/{resume_base}.conf", workspace_dir, job)
            resume_conf_for[interrupted.name] = resume_base
            logger.info("[%s] resume seg %s from step %d/%d",
                        job.job_id, interrupted.name, step, total_steps)

    # 4) regenerate the sbatch (skip done; resume the interrupted one) and submit.
    early_stop = _early_stop_on(job, manifest)
    es_tier = _early_stop_tier(job)
    if early_stop:
        manifest["early_stop_tier"] = es_tier
    sbatch = generate_sbatch(
        manifest, profile, job.resources or {}, scratch,
        job_name=job.name_stem or job.design_name,
        resume_conf_for=resume_conf_for or None,
        early_stop_relax=early_stop,
    )
    # Re-stage the evaluator(s) straight into scratch (resume uploads only the sbatch/
    # resume conf; the original copy is normally still there, but this keeps a resumed
    # run self-consistent even if scratch was partially purged).
    if early_stop:
        await _stage_early_stop_evaluator(conn, scratch, workspace_dir, job, tier=es_tier)
    await _put_text(conn, sbatch, f"{scratch}/{_SBATCH_NAME}", workspace_dir, job)
    res = await conn.run(f"cd {_shq(scratch)} && sbatch {_SBATCH_NAME}")
    if res.rc != 0:
        raise RuntimeError(f"resume sbatch failed (rc={res.rc}): {res.stderr or res.stdout}")
    slurm_id = parse_sbatch_job_id(res.stdout)
    if not slurm_id:
        raise RuntimeError(f"could not parse SLURM job id from resume: {res.stdout!r}")

    job.slurm_job_id = slurm_id
    job.slurm_state = "PENDING"
    job.status = MdStatus.queued
    job.queued_at = time.time()
    job.resubmit_count = (job.resubmit_count or 0) + 1
    job.resumable = False
    job.error = None
    job.failure_kind = None
    job.user_stopped = False
    job.save(workspace_dir)
    logger.info("[%s] resumed as SLURM %s (resume #%d)",
                job.job_id, slurm_id, job.resubmit_count)
    return job


async def _remote_restart_step(conn, scratch, seg_name, workspace_dir, job) -> int | None:
    """Fetch the interrupted segment's ``.restart.xsc`` and read its checkpoint step,
    or None if there is no usable mid-segment checkpoint."""
    from backend.core.namd_runner import _read_xsc_step
    remote = f"{scratch}/output/{seg_name}.restart.xsc"
    local = job.job_dir(workspace_dir) / "_resume.xsc"
    try:
        await conn.sftp_get(remote, str(local))
    except Exception:  # noqa: BLE001 — no restart file → resume from segment start
        return None
    try:
        return _read_xsc_step(local)
    finally:
        try:
            local.unlink()
        except OSError:
            pass


def _segment_total_steps(manifest: dict, seg_name: str) -> int:
    for seg in manifest.get("segments", []):
        if seg.get("name") == seg_name:
            return int(seg.get("steps", 0))
    return 0


async def fetch_outputs(job: MdJob, workspace_dir: Path, *, conn=None) -> None:
    """Bring a finished remote run's results back to the login node and locally.

    Mirrors scratch → project (persist before scratch is purged), then downloads the
    remote ``output/`` tree and top-level ``*.log`` files into the local package dir
    so the existing detail view + local health/metrics recompute work.
    """
    conn = conn or _default_conn()
    scratch = job.remote_scratch_dir
    project = job.remote_project_dir
    if not scratch:
        return
    if project:
        try:
            await conn.mirror(scratch, project)
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            logger.warning("[%s] scratch→project mirror failed: %s", job.job_id, exc)

    package_dir = job.package_dir(workspace_dir)
    # List the remote files to pull: output/ tree + top-level logs + sbatch out/err.
    rels = await _remote_relpaths(conn, scratch)
    for rel in rels:
        local = package_dir / rel
        try:
            await conn.sftp_get(f"{scratch}/{rel}", str(local))
        except Exception as exc:  # noqa: BLE001 — one bad file must not abort fetch
            logger.warning("[%s] fetch %s failed: %s", job.job_id, rel, exc)


async def cancel_job(job: MdJob, *, conn=None) -> bool:
    """``scancel`` the remote job.  Returns True if a cancel was issued."""
    conn = conn or _default_conn()
    if not job.slurm_job_id:
        return False
    res = await conn.run(f"scancel {job.slurm_job_id}")
    return res.rc == 0


async def reconcile_remote_job(job: MdJob, workspace_dir: Path, *, conn=None) -> MdJob:
    """Poll one remote job and advance its persisted state.

    - pending/running  → update ``slurm_state`` + status (queued/running), save.
    - completed        → fetch outputs, recompute local health/metrics, mark completed.
    - cancelled        → mark stopped.
    - failed           → fetch what exists (for logs), mark failed.
    """
    conn = conn or _default_conn()
    raw, bucket = await poll_status(job, conn=conn)
    prev_state = job.slurm_state
    job.slurm_state = raw or job.slurm_state
    new_status = bucket_to_md_status(bucket)

    if bucket in ("pending", "running"):
        changed = job.slurm_state != prev_state
        if job.status != new_status:
            job.status = new_status
            changed = True
        # Live segment progress: cheap remote scan so the panel shows p10→p50→…
        # instead of sitting at segment 0 for the whole run.
        if bucket == "running":
            try:
                if await poll_remote_progress(job, conn=conn):
                    changed = True
            except Exception as exc:  # noqa: BLE001 — progress is advisory
                logger.warning("[%s] remote progress poll failed: %s", job.job_id, exc)
        if changed:
            job.save(workspace_dir)
        return job

    # Terminal — pull results back (restart files for a resume; logs to diagnose).
    try:
        await fetch_outputs(job, workspace_dir, conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] output fetch failed: %s", job.job_id, exc)

    # Record this finished submission so the panel's expand chevron can show the
    # full resumption chain (original + each resume).
    _append_history(job, raw or "unknown")

    if bucket == "completed":
        _finalize_local_bookkeeping(job, workspace_dir)
        _record_learned_throughput(job, workspace_dir)
        job.status = MdStatus.completed
        job.error = None
        job.resumable = False
    elif bucket == "cancelled":
        job.status = MdStatus.stopped
        job.user_stopped = True
    elif is_timeout_state(raw):
        # A walltime TIMEOUT is expected for the short-job strategy — NOT a failure.
        # Mark it resumable-from-checkpoint and wait for a one-click Resume (resume is
        # never automatic: Duo 2FA needs the user present).  status=paused (accent, not
        # red) reads as "paused at checkpoint, resume me".
        n = len(job.segments)
        job.status = MdStatus.paused
        job.resumable = True
        job.failure_kind = "cluster_timeout"
        job.error = (
            f"Timed out (SLURM {raw}) at segment {min(job.current_segment_idx + 1, n)}/{n} "
            "— reconnect and click Resume to continue from the last checkpoint."
        )
    else:  # genuine failure (FAILED/OOM/NODE_FAIL/…) — do not offer resume.
        job.status = MdStatus.failed
        job.resumable = False
        base = f"Remote job {job.slurm_job_id} ended in SLURM state {raw or 'unknown'}."
        excerpt, src, kind = _scan_logs_for_error(job.package_dir(workspace_dir))
        if excerpt:
            job.error = f"{base} {excerpt}" + (f" (see {src})" if src else "")
            job.failure_kind = kind
        else:
            job.error = base
    job.save(workspace_dir)
    logger.info("[%s] remote job %s → %s", job.job_id, job.slurm_job_id, job.status.value)
    return job


async def poll_remote_jobs(workspace_dir: Path, *, conn=None) -> list[str]:
    """Supervisor pass: reconcile every active (queued/running) Alpine job.

    Only runs when the session is connected — a disconnected/expired session leaves
    remote jobs as-is (viewable offline from job.json).  Returns reconciled ids.
    """
    conn = conn or _default_conn()
    if not getattr(conn, "is_connected", lambda: False)():
        return []
    touched: list[str] = []
    for job in MdJob.list_jobs(workspace_dir):
        if job.execution_target != "alpine" or not is_remote_active(job.status):
            continue
        if not job.slurm_job_id:
            continue
        try:
            await reconcile_remote_job(job, workspace_dir, conn=conn)
            touched.append(job.job_id)
        except Exception:  # noqa: BLE001 — one job must not kill the pass
            logger.exception("[%s] remote reconcile failed", job.job_id)
    return touched


# ── local helpers ─────────────────────────────────────────────────────────────

def _scan_logs_for_error(package_dir: Path) -> tuple[str | None, str | None, str | None]:
    """Best ``(excerpt, source_filename, failure_kind)`` from a failed remote run's
    fetched logs — the human-meaningful cause behind a bare SLURM ``FAILED``.

    Scans NAMD per-segment ``*.log`` newest-first (the failing segment runs last and
    its log is freshest), then the SLURM ``*.err`` / ``*.out`` (shell/scheduler-level
    errors like the ``set -u`` abort).  Returns ``(None, None, None)`` if nothing
    matches.  Best-effort; never raises.
    """
    from backend.core.md_vram import (
        _read_log_tail,
        classify_failure_log,
        extract_error_line,
    )

    def _by_mtime(paths) -> list[Path]:
        try:
            return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return list(paths)

    package_dir = Path(package_dir)
    ordered: list[Path] = []
    ordered += _by_mtime(package_dir.rglob("*.log"))
    ordered += _by_mtime(package_dir.glob("*.err"))
    ordered += _by_mtime(package_dir.glob("*.out"))
    for path in ordered:
        try:
            tail = _read_log_tail(path)
        except OSError:
            continue
        excerpt = extract_error_line(tail)
        if excerpt:
            return excerpt, path.name, classify_failure_log(tail)
    return None, None, None


def _record_learned_throughput(job: MdJob, workspace_dir: Path) -> None:
    """Fold this completed remote run's measured Alpine throughput into the learned
    ns/day store, keyed by (cluster, partition, size-bucket), so future estimates for
    similar systems tighten toward reality.  Best-effort; never raises."""
    from backend.core import cluster_resources, cluster_throughput
    try:
        pkg = job.package_dir(workspace_dir)
        nsday = cluster_resources.latest_ns_per_day(pkg / "output" / "metrics.jsonl")
        if not nsday:
            return
        manifest = _read_manifest(pkg) if (pkg / "manifest.json").exists() else {}
        n_atoms = cluster_resources.n_atoms_from_manifest(manifest)
        partition = (job.resources or {}).get("partition", "")
        cluster_throughput.record_throughput(
            workspace_dir, cluster=job.cluster_name or "", partition=partition,
            n_atoms=n_atoms, ns_per_day=nsday,
        )
    except Exception:  # noqa: BLE001 — learning must not break job completion
        logger.warning("[%s] learned-throughput record failed", job.job_id, exc_info=True)


def _append_history(job: MdJob, state: str) -> None:
    """Record a finished remote submission on the job so the panel's expand chevron can
    show the full resumption chain (original + each resume)."""
    import time
    n = len(job.segments)
    job.resume_history = list(job.resume_history or [])
    job.resume_history.append({
        "slurm_job_id": job.slurm_job_id,
        "state": state,
        "segment_reached": min(job.current_segment_idx + 1, n) if n else 0,
        "segments_total": n,
        "walltime": (job.resources or {}).get("walltime"),
        "at": time.time(),
    })


def _read_manifest(package_dir: Path) -> dict:
    import json
    return json.loads((Path(package_dir) / "manifest.json").read_text())


def _shq(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


async def _put_text(conn, text: str, remote_path: str, workspace_dir: Path, job: MdJob) -> None:
    """Upload an in-memory string as a remote file via a scratch tempfile."""
    tmp = job.job_dir(workspace_dir) / "_upload.tmp"
    tmp.write_text(text)
    try:
        await conn.sftp_put(str(tmp), remote_path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


async def _remote_relpaths(conn, scratch: str) -> list[str]:
    """Relative paths under the remote scratch dir worth fetching: the output/ tree
    plus top-level logs and the sbatch .out/.err."""
    listing = await conn.run(
        f"cd {_shq(scratch)} && "
        "find output -type f 2>/dev/null; "
        "ls -1 *.log *.out *.err 2>/dev/null"
    )
    rels: list[str] = []
    for line in (listing.stdout or "").splitlines():
        rel = line.strip()
        if rel and not rel.startswith("/") and ".." not in PurePosixPath(rel).parts:
            rels.append(rel)
    return rels


def _finalize_local_bookkeeping(job: MdJob, workspace_dir: Path) -> None:
    """Recompute metrics + health for each completed segment from the fetched
    logs/coords — the between-segment bookkeeping the local runner does inline, which
    a bare remote sbatch skips (plan decision #1: health is advisory, computed locally
    post-fetch).  Best-effort; never raises."""
    import time
    from backend.core.md_health import append_health_jsonl, run_health_check
    from backend.core.md_job import MdHealthSample
    from backend.core.namd_runner import (
        _append_metrics_jsonl,
        _jsonl_has_segment,
        _latest_segment_log,
        _segment_outputs_complete,
        segments_from_manifest,
    )

    package_dir = job.package_dir(workspace_dir)
    output_dir = package_dir / "output"
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        return
    output_dir.mkdir(exist_ok=True)
    try:
        _, specs = segments_from_manifest(manifest_path)
    except Exception:  # noqa: BLE001
        return
    metrics_path = output_dir / "metrics.jsonl"
    health_path = output_dir / "health.jsonl"

    for seg, spec in zip(job.segments, specs):
        if not _segment_outputs_complete(output_dir, seg.name):
            continue
        seg.status = "done"
        log_path = _latest_segment_log(package_dir, seg.name)
        try:
            if not _jsonl_has_segment(metrics_path, seg.name):
                _append_metrics_jsonl(output_dir, seg.name, seg.stage, log_path)
        except Exception:  # noqa: BLE001
            pass
        try:
            if not _jsonl_has_segment(health_path, seg.name):
                hres = run_health_check(
                    package_dir, seg.name, job.name_stem,
                    min_c1_paired=spec.min_c1_paired,
                    min_wc_ref_relative=spec.min_wc_ref_relative,
                )
                append_health_jsonl(output_dir, seg.name, seg.stage, hres)
                job.health_samples.append(MdHealthSample(
                    wall_time=time.time(), stage=seg.stage, segment=seg.name,
                    c1_paired_fraction=hres.c1_paired_fraction,
                    c1_mean_ang=hres.c1_mean_ang, c1_p90_ang=hres.c1_p90_ang,
                    wc_ref_relative_fraction=hres.wc_ref_relative_fraction,
                    wc_mean_hbond_ang=hres.wc_mean_hbond_ang,
                    passed=hres.passed, blocking=hres.blocking,
                    reason=hres.reason or (hres.error or ""),
                ))
        except Exception:  # noqa: BLE001
            pass
    job.current_segment_idx = max(0, len(job.segments) - 1)
