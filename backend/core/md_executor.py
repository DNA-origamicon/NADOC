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

import asyncio
import fcntl
import json
import logging
import re
import time
from pathlib import Path, PurePosixPath

from backend.core.cluster_config import ClusterProfile, resolve_paths
from backend.core.md_job import MdJob, MdStatus
from backend.core import md_protocols, resume_transfer
from backend.core.md_protocols import strip_gpu_resident
from backend.core.slurm_script import (
    EARLY_STOP_EVAL_NAME,
    LIVE_METRICS_FILE,
    LIVE_METRICS_NAME,
    LIVE_HEALTH_FILE,
    SETTLE_RETARGET_NAME,
    EARLY_STOP_HEALTH_NAME,
    STAGED_MD_HEALTH_NAME,
    ALPINE_WC_EVAL_NAME,
    ALPINE_WC_PLAN_NAME,
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
        state_text = state_field.partition("|")[0].strip()
        state = state_text.split()[0] if state_text else ""
        if base and state and base not in states:
            states[base] = state.upper()
    return states


def parse_sacct_diagnostics(text: str, job_id: str) -> dict | None:
    """Persistable accounting evidence from a parsable2 sacct row.

    Expected columns are JobIDRaw,State,ExitCode,DerivedExitCode,Elapsed,NodeList.
    Older/injected outputs with only JobID|State remain valid and simply yield the
    available fields.  The allocation row wins over .batch/.extern steps.
    """
    for raw in (text or "").splitlines():
        cols = raw.strip().split("|")
        if len(cols) < 2 or cols[0].strip() != str(job_id):
            continue
        keys = (
            "job_id", "state", "exit_code", "derived_exit_code", "elapsed", "node_list"
        )
        out = {key: value.strip() for key, value in zip(keys, cols) if value.strip()}
        if "state" in out:
            out["state"] = out["state"].split()[0].upper()
        out["captured_at"] = time.time()
        return out
    return None


# SLURM state code → NADOC lifecycle bucket.  Mirrors the Appendix status-code map.
_STATE_MAP = {
    "PD": "pending",
    "PENDING": "pending",
    "CF": "pending",
    "CONFIGURING": "pending",
    "R": "running",
    "RUNNING": "running",
    "CG": "running",
    "COMPLETING": "running",
    "S": "running",
    "SUSPENDED": "running",
    "RQ": "running",
    "REQUEUED": "pending",
    "CD": "completed",
    "COMPLETED": "completed",
    "CA": "cancelled",
    "CANCELLED": "cancelled",
    "F": "failed",
    "FAILED": "failed",
    "TO": "failed",
    "TIMEOUT": "failed",
    "NF": "failed",
    "NODE_FAIL": "failed",
    "PR": "failed",
    "PREEMPTED": "failed",
    "OOM": "failed",
    "OUT_OF_MEMORY": "failed",
    "BF": "failed",
    "BOOT_FAIL": "failed",
    "DL": "failed",
    "DEADLINE": "failed",
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


# A SLURM job can report COMPLETED while its checkpoint restart files fail to
# download (transient SFTP/network drop).  Rather than lie ``completed`` (which ends
# polling and strands the missing files — see ISSUE-15), we keep the job re-pollable
# and let the supervisor re-fetch on subsequent passes.  This bounds those retries so
# a genuinely-never-produced file can't spin forever before we surface a failure.
_MAX_FETCH_ATTEMPTS = 3


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
    new_idx = (
        running_idx
        if running_idx is not None
        else min(n_done, max(len(job.segments) - 1, 0))
    )
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
        if resume_transfer.is_transfer_artifact(p.name):
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


async def _stage_early_stop_evaluator(
    conn, remote_dir: str, workspace_dir: Path, job: MdJob
) -> None:
    """Upload RunPod's MDAnalysis-backed early-stop scripts next to the confs.

    RunPod ships all three: the stdlib ``nadoc_cutoff_eval.py`` cutoff evaluator,
    ``nadoc_health_eval.py``, and a verbatim ``md_health.py`` (the WC step needs the
    real ``run_health_check``; it imports numpy/scipy/MDAnalysis on the pod) — no
    energy-only mode, so the node always makes the same energy-AND-WC decision the
    local runner does.  We ship the exact module sources the tests pin, so the node
    runs byte-for-byte what was validated offline.
    """
    from backend.core import md_health, remote_cutoff_eval, remote_health_eval

    async def _stage(module, remote_name):
        await _put_text(
            conn,
            Path(module.__file__).read_text(),
            f"{remote_dir}/{remote_name}",
            workspace_dir,
            job,
        )

    await _stage(remote_cutoff_eval, EARLY_STOP_EVAL_NAME)
    await _stage(remote_health_eval, EARLY_STOP_HEALTH_NAME)
    await _stage(md_health, STAGED_MD_HEALTH_NAME)


async def _prepare_alpine_wc_plan(package_dir: Path, name_stem: str) -> Path:
    """Build/cache the dependency-free Alpine WC plan off the event loop."""
    from backend.core import remote_wc_eval  # noqa: PLC0415

    try:
        return await asyncio.to_thread(
            remote_wc_eval.ensure_plan,
            package_dir,
            name_stem,
            ALPINE_WC_PLAN_NAME,
        )
    except Exception as exc:  # noqa: BLE001 — turn a hidden no-skip into a hard preflight
        raise RuntimeError(
            "Could not prepare Alpine relaxation skip acceleration: the local "
            f"Watson-Crick pair plan failed ({exc})."
        ) from exc


async def _stage_alpine_early_stop_evaluator(
    conn,
    remote_dir: str,
    workspace_dir: Path,
    job: MdJob,
    plan_path: Path,
) -> None:
    """Stage the stdlib-only Alpine cutoff + WC evaluator and precomputed plan."""
    from backend.core import remote_cutoff_eval, remote_wc_eval  # noqa: PLC0415

    for module, remote_name in (
        (remote_cutoff_eval, EARLY_STOP_EVAL_NAME),
        (remote_wc_eval, ALPINE_WC_EVAL_NAME),
    ):
        await _put_text(
            conn,
            Path(module.__file__).read_text(),
            f"{remote_dir}/{remote_name}",
            workspace_dir,
            job,
        )
    await conn.sftp_put(str(plan_path), f"{remote_dir}/{ALPINE_WC_PLAN_NAME}")


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
        logger.info(
            "[%s] already submitted as SLURM %s; skipping re-submit",
            job.job_id,
            job.slurm_job_id,
        )
        return job

    user = getattr(conn, "user", "") or ""
    if not user:
        raise RuntimeError("not connected to the cluster (no user on the session)")

    def submit_progress(phase: str, label: str, fraction: float, **detail) -> None:
        """Persist the cluster hand-off while this long request is still running."""
        job.remote_submit_progress = {
            "phase": phase,
            "label": label,
            "fraction": max(0.0, min(1.0, float(fraction))),
            "updated_at": time.time(),
            **detail,
        }
        job.save(workspace_dir)

    submit_progress("preflight", "Checking cluster launch requirements…", 0.03)

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
    alpine_wc_plan = (
        await _prepare_alpine_wc_plan(package_dir, job.name_stem or job.design_name)
        if early_stop
        else None
    )
    sbatch = generate_sbatch(
        manifest,
        profile,
        resources,
        scratch_dir,
        job_name=job.name_stem or job.design_name,
        early_stop_relax=early_stop,
    )

    # 1) stage package → project (persistent), skipping local output/logs.
    #    NADOC's confs bake ``GPUresident on`` into the fast (HMR/4 fs) segments —
    #    the local pipeline is GPU-resident.  A CPU/multicore Alpine target FATALs on
    #    that, so amend EVERY staged .conf to strip it, matching the sbatch's CPU exec
    #    path (same is_gpu_target decision).  Only the p10 warmup confs lack it; this
    #    makes all of them consistent with the chosen partition.
    gpu = is_gpu_target(profile, resources)

    # Pre-flight the module set on the LOGIN node before staging anything.  The
    # `module load` line is the first thing the compute node runs, and if a name is
    # wrong the job dies instantly — after we have already pushed the whole package
    # (hundreds of MB) and burned a queue slot.  Live-confirmed 2026-08-06: SLURM
    # 30948986 died on `namd/3.0.1_gpu`, which does not exist on Alpine, having
    # uploaded an 814 MB package and waited in the queue first.  Two seconds here
    # turns that into an immediate, readable error.
    mods = profile.modules_for(gpu)
    namd_cmd = profile.namd_command(gpu)
    if mods or namd_cmd:
        # Verify with `module spider` and a filesystem test — NOT `module load`.
        #
        # The login node's module environment is not the compute node's: `module load
        # gcc/11.2.0` is refused on the login node ("exist but cannot be loaded as
        # requested") while the same load succeeds inside an acpu job, so loading here
        # produces FALSE NEGATIVES that block submissions which would have run fine
        # (live-confirmed 2026-08-07).  `spider` searches the whole tree and answers
        # the question we actually care about — does this module EXIST — which is what
        # caught `namd/3.0.1_gpu` (SLURM 30948986).  A private binary is an absolute
        # path, identical from either node, so `test -x` settles it outright.
        # A private NAMD executable was built under a compute allocation.  Alpine's
        # login node has repeatedly rejected both gcc/11.2.0 and gcc/14.2.0 queries
        # even though those modules exist and load in batch jobs.  In that case the
        # only invariant we can establish here is that the shared-filesystem binary
        # exists and is executable.  Do not turn a login-node Lmod policy/warning into
        # a false "MISSING MODULE" that prevents every submission.
        checks = [] if namd_cmd.startswith("/") else [
            f"module spider {_shq(m)} >/dev/null 2>&1 || "
            f'{{ echo "MISSING MODULE: {m}"; exit 1; }}'
            for m in mods
        ]
        if namd_cmd.startswith("/"):
            checks.append(
                f"test -x {_shq(namd_cmd)} || "
                f'{{ echo "NOT EXECUTABLE: {namd_cmd}"; exit 1; }}'
            )
        check = await conn.run(
            "source /etc/profile >/dev/null 2>&1; "
            + "; ".join(checks)
            + "; echo PREFLIGHT_OK"
        )
        # Each guard ends in `exit 1`, so a failure propagates as the command's exit
        # code; the echoed marker is for the log, not the decision.
        blob = f"{check.stdout}\n{check.stderr}".strip()
        if check.rc != 0:
            raise RuntimeError(
                f"Pre-flight failed on {profile.name}: the job would die immediately on "
                f"the compute node instead of after the upload. Fix module_loads / "
                f"gpu_module_loads / gpu_namd_bin in workspace/clusters.json (GET "
                f"/api/cluster/namd-modules lists the NAMD modules that exist).\n"
                f"{blob[:600]}"
            )

    plan = stage_plan(package_dir)
    total_bytes = sum(p.stat().st_size for p, _ in plan)
    uploaded_bytes = 0
    submit_progress(
        "upload", "Uploading prepared package to Alpine…", 0.08,
        files_done=0, files_total=len(plan), bytes_done=0, bytes_total=total_bytes,
    )
    logger.info(
        "[%s] staging %d files → %s (gpu=%s)", job.job_id, len(plan), project_dir, gpu
    )
    await conn.mkdir_p(project_dir)
    for index, (local_path, rel) in enumerate(plan, 1):
        remote = f"{project_dir}/{rel}"
        if not gpu and local_path.suffix == ".conf":
            amended = strip_gpu_resident(local_path.read_text())
            await _put_text(conn, amended, remote, workspace_dir, job)
        else:
            await conn.sftp_put(str(local_path), remote)
        uploaded_bytes += local_path.stat().st_size
        byte_fraction = uploaded_bytes / total_bytes if total_bytes else index / max(1, len(plan))
        submit_progress(
            "upload", f"Uploading package file {index} of {len(plan)}…",
            0.08 + 0.67 * byte_fraction,
            files_done=index, files_total=len(plan),
            bytes_done=uploaded_bytes, bytes_total=total_bytes,
        )

    # 1b) the node live-metrics collector — ALWAYS staged, independent of early-stop.
    #     Without it a remote run shows no speed/temp/pressure at all while it runs.
    from backend.core import remote_live_metrics  # noqa: PLC0415

    await _put_text(
        conn,
        Path(remote_live_metrics.__file__).read_text(),
        f"{project_dir}/{LIVE_METRICS_NAME}",
        workspace_dir,
        job,
    )

    # Same implementation imported by the local runner and staged by RunPod. Keeping
    # this outside the prepared package prevents target choice from changing physics.
    from backend.core import remote_settle_retarget  # noqa: PLC0415

    await _put_text(
        conn,
        Path(remote_settle_retarget.__file__).read_text(),
        f"{project_dir}/{SETTLE_RETARGET_NAME}",
        workspace_dir,
        job,
    )

    # 1c) stage the node early-stop scripts into project (mirrored to scratch next).
    if early_stop:
        await _stage_alpine_early_stop_evaluator(
            conn, project_dir, workspace_dir, job, alpine_wc_plan
        )

    # 2) mirror project → scratch (two-filesystem model — jobs MUST run on scratch).
    submit_progress("mirror", "Copying package to Alpine scratch storage…", 0.82)
    await conn.mirror(project_dir, scratch_dir)

    # 3) upload the sbatch into scratch and submit from there.
    submit_progress("sbatch", "Sending the job to the Slurm scheduler…", 0.95)
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
    job.remote_submit_progress = None
    job.status = MdStatus.queued
    job.queued_at = time.time()
    job.slurm_started_at = None
    job.error = None
    job.failure_kind = None
    job.user_stopped = False
    job.save(workspace_dir)
    logger.info("[%s] submitted to %s as SLURM %s", job.job_id, profile.name, slurm_id)
    return job


async def list_namd_modules(conn=None, *, compilers=("gcc/14.2.0",)) -> list[str]:
    """Live-discover the NAMD modules available on the cluster.

    Lets the user confirm the exact GPU (CUDA) vs CPU NAMD module name — the embedded
    Alpine profile can only guess the GPU one.  Combines stdout + stderr because LMOD
    writes ``module avail`` to stderr.

    **Alpine's Lmod is HIERARCHICAL**: ``namd`` is invisible to a bare
    ``module avail namd`` until a compiler is loaded, so the plain form returned an
    empty list precisely when it was needed — after a job died on an unknown module
    (live-confirmed 2026-08-06, ``namd/3.0.1_gpu`` unknown while avail showed nothing).
    So: try under each compiler, then fall back to ``module spider``, which searches
    the whole tree regardless of what is loaded.
    """
    conn = conn or _default_conn()
    found: list[str] = []
    for comp in compilers:
        res = await conn.run(
            f"source /etc/profile >/dev/null 2>&1; module load {comp} >/dev/null 2>&1; "
            "module -t avail namd 2>&1"
        )
        found += parse_namd_modules(f"{res.stdout}\n{res.stderr}")
    if not found:
        # `spider` walks every hierarchy branch; its output is prose, but the module
        # tokens still match the same `namd/...` shape the parser looks for.
        res = await conn.run(
            "source /etc/profile >/dev/null 2>&1; module -t spider namd 2>&1"
        )
        found += parse_namd_modules(f"{res.stdout}\n{res.stderr}")
    return sorted(set(found))


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
            f"sacct -j {jid} --format=JobIDRaw,State,ExitCode,DerivedExitCode,Elapsed,NodeList "
            "--parsable2 --noheader"
        )
        diagnostics = parse_sacct_diagnostics(sa.stdout, jid)
        if diagnostics:
            job.slurm_diagnostics = diagnostics
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
    # One command: the file listing AND the node-computed metrics blob.  The blob is
    # a couple of hundred bytes written by nadoc_live_metrics.py on the node, so this
    # stays a metadata-sized poll rather than a log transfer.
    res = await conn.run(
        f"cd {_shq(scratch)} && ls -1 output/*.coor 2>/dev/null; ls -1 *.log 2>/dev/null; "
        f"echo '---NADOC-METRICS---'; cat {LIVE_METRICS_FILE} 2>/dev/null; "
        f"echo '---NADOC-HEALTH---'; cat {LIVE_HEALTH_FILE} 2>/dev/null; "
        # Measure the files directly on every poll as well as asking the staged
        # collector. Existing Alpine jobs are already running an older collector and
        # cannot gain new Python code mid-allocation; this makes their growing DCDs
        # visible immediately and proves the bytes exist in a real remote file.
        "echo '---NADOC-SIZES---'; "
        "find output -type f -name '*.dcd' -printf '%s\\n' 2>/dev/null "
        "| awk '{s+=$1} END {print s+0}'; "
        "find . -type f -printf '%s\\n' 2>/dev/null "
        "| awk '{s+=$1} END {print s+0}'"
    )
    listing, _, tail = (res.stdout or "").partition("---NADOC-METRICS---")
    metrics_blob, _, health_and_sizes = tail.partition("---NADOC-HEALTH---")
    health_blob, _, sizes_blob = health_and_sizes.partition("---NADOC-SIZES---")
    dcd_bytes, total_bytes = parse_remote_sizes(sizes_blob)
    if dcd_bytes is not None and total_bytes is not None:
        try:
            metrics = json.loads(metrics_blob.strip()) if metrics_blob.strip() else {}
        except (ValueError, TypeError):
            metrics = {}
        if not isinstance(metrics, dict):
            metrics = {}
        metrics["dcd_size_bytes"] = dcd_bytes
        metrics["total_size_bytes"] = total_bytes
        metrics_blob = json.dumps(metrics)
    finished, started = parse_progress_listing(listing)
    advanced = apply_remote_progress(job, finished, started)
    health_changed = apply_live_health(job, health_blob)
    return apply_live_metrics(job, metrics_blob) or health_changed or advanced


def parse_remote_sizes(blob: str) -> tuple[int | None, int | None]:
    """Parse the two newline-delimited byte totals emitted by the remote poll."""
    lines = [line.strip() for line in (blob or "").splitlines() if line.strip()]
    if len(lines) < 2 or not lines[0].isdigit() or not lines[1].isdigit():
        return None, None
    return int(lines[0]), int(lines[1])


def apply_live_metrics(job: MdJob, blob: str) -> bool:
    """Store the node-computed metrics on the job; True if anything changed.

    A missing/half-written blob is simply ignored — the panel treats absent values
    as "not known yet", which is the honest state early in a stage before NAMD has
    printed its first ENERGY line.
    """
    text = (blob or "").strip()
    if not text:
        return False
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict) or not data:
        return False
    # `collected_at` inside the blob is the COMPUTE NODE's clock.  Progress is
    # extrapolated from this reading between sign-ins, so it needs an anchor on
    # NADOC's own clock — otherwise any host/node skew becomes fake progress.
    old = job.live_metrics or {}
    prior = {k: v for k, v in old.items() if k != "retrieved_at"}
    if data == prior:
        # Identical blob = the collector has not rewritten it, so the run HAS advanced
        # since we first saw this step.  Re-anchoring now would throw that away.
        return False
    # Minimisation logs do not emit NAMD's Benchmark/TIMING records, so the node
    # parser cannot obtain ``s_per_step`` from a single snapshot.  Successive ENERGY
    # snapshots are still a real stopwatch: carry their observed rate into the same
    # field used by the progress/ETA code.  Require the same segment and increasing
    # node time/step so a restart or clock discontinuity cannot manufacture a rate.
    if not data.get("s_per_step") and old.get("segment") == data.get("segment"):
        try:
            ds = int(data.get("step")) - int(old.get("step"))
            dt = float(data.get("collected_at")) - float(old.get("collected_at"))
            if ds > 0 and dt > 0:
                data["s_per_step"] = dt / ds
        except (TypeError, ValueError):
            pass
    data["retrieved_at"] = time.time()
    job.live_metrics = data
    return True


def apply_live_health(job: MdJob, blob: str) -> bool:
    """Merge the pod-computed compact health bundle into the job.

    Samples are advisory while NAMD is running. The raw scalar bundle is retained under
    ``health_probe.latest`` so newer metrics need no schema migration to remain visible.
    """
    text = (blob or "").strip()
    if not text:
        return False
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict) or not data:
        return False
    probe = dict(job.health_probe or {})
    if data.get("collected_at") == probe.get("node_collected_at"):
        return False
    probe.update(
        enabled=True,
        interval_s=300.0,
        last_tick_at=time.time(),
        node_collected_at=data.get("collected_at"),
        reason=data.get("reason"),
        last_error=None if data.get("ready") else data.get("reason"),
        latest=data.get("health") or {},
    )
    if data.get("ready"):
        health = data.get("health") or {}
        from types import SimpleNamespace
        from backend.core.md_job import MdHealthSample

        result = SimpleNamespace(**health)
        segment = str(data.get("segment") or "")
        stage = str(data.get("stage") or segment)
        sample = MdHealthSample.from_result(
            result,
            stage,
            segment,
            blocking=False,
            wall_time=float(data.get("collected_at") or time.time()),
        )
        job.health_samples.append(sample)
        probe["last_at"] = time.time()
    job.health_probe = probe
    return True


async def resume_job(
    job: MdJob,
    workspace_dir: Path,
    *,
    profile: ClusterProfile,
    resources: dict | None = None,
    conn=None,
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
        step = await _remote_restart_step(
            conn, scratch, interrupted.name, workspace_dir, job
        )
        if step and total_steps and 0 < step < total_steps:
            conf_path = package_dir / f"{interrupted.name}.conf"
            resume_text = md_protocols.build_remote_resume_conf(
                conf_path.read_text(),
                segment_name=interrupted.name,
                restart_step=step,
                total_steps=total_steps,
                cont_index=(job.resubmit_count or 0) + 1,
            )
            if not is_gpu_target(profile, job.resources or {}):
                resume_text = strip_gpu_resident(resume_text)
            resume_base = f"{interrupted.name}.resume"
            await _put_text(
                conn, resume_text, f"{scratch}/{resume_base}.conf", workspace_dir, job
            )
            resume_conf_for[interrupted.name] = resume_base
            logger.info(
                "[%s] resume seg %s from step %d/%d",
                job.job_id,
                interrupted.name,
                step,
                total_steps,
            )

    # 4) regenerate the sbatch (skip done; resume the interrupted one) and submit.
    early_stop = _early_stop_on(job, manifest)
    alpine_wc_plan = (
        await _prepare_alpine_wc_plan(package_dir, job.name_stem or job.design_name)
        if early_stop
        else None
    )
    sbatch = generate_sbatch(
        manifest,
        profile,
        job.resources or {},
        scratch,
        job_name=job.name_stem or job.design_name,
        resume_conf_for=resume_conf_for or None,
        early_stop_relax=early_stop,
    )
    # Re-stage transition helpers straight into scratch. A recovery must not depend on
    # the original helper surviving scratch cleanup or on the exact source version
    # uploaded by the failed attempt.
    from backend.core import remote_settle_retarget  # noqa: PLC0415

    await _put_text(
        conn,
        Path(remote_settle_retarget.__file__).read_text(),
        f"{scratch}/{SETTLE_RETARGET_NAME}",
        workspace_dir,
        job,
    )
    # Re-stage the evaluator(s) too (resume otherwise uploads only the sbatch/resume
    # conf; the original copies are normally still there, but may have been purged).
    if early_stop:
        await _stage_alpine_early_stop_evaluator(
            conn, scratch, workspace_dir, job, alpine_wc_plan
        )
    await _put_text(conn, sbatch, f"{scratch}/{_SBATCH_NAME}", workspace_dir, job)
    res = await conn.run(f"cd {_shq(scratch)} && sbatch {_SBATCH_NAME}")
    if res.rc != 0:
        raise RuntimeError(
            f"resume sbatch failed (rc={res.rc}): {res.stderr or res.stdout}"
        )
    slurm_id = parse_sbatch_job_id(res.stdout)
    if not slurm_id:
        raise RuntimeError(f"could not parse SLURM job id from resume: {res.stdout!r}")

    job.slurm_job_id = slurm_id
    job.slurm_state = "PENDING"
    job.status = MdStatus.queued
    job.queued_at = time.time()
    job.slurm_started_at = None
    job.resubmit_count = (job.resubmit_count or 0) + 1
    job.resumable = False
    job.error = None
    job.failure_kind = None
    # Attempt-scoped UI state from the finished allocation must not leak into the
    # new one. Live metrics will repopulate on the next poll, while download status
    # must remain empty until this allocation actually reaches result transfer.
    job.live_metrics = None
    job.live_frame = None
    job.download_status = None
    job.fetch_attempts = 0
    job.user_stopped = False
    job.save(workspace_dir)
    logger.info(
        "[%s] resumed as SLURM %s (resume #%d)",
        job.job_id,
        slurm_id,
        job.resubmit_count,
    )
    return job


async def _remote_restart_step(
    conn, scratch, seg_name, workspace_dir, job
) -> int | None:
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


_FETCH_LOCKS: dict[str, asyncio.Lock] = {}


async def fetch_outputs(job: MdJob, workspace_dir: Path, *, conn=None) -> bool:
    """Serialize every result fetch for a job, including across backend processes.

    Completion reconciliation, Stop, Fetch remote, and End-and-download can all reach
    this function.  Without a shared lock two SFTP readers opened the same ``.part`` in
    append mode and interleaved a remote DCD twice, producing a partial larger than the
    entire remote inventory.  The asyncio lock handles concurrent routes in this
    process; flock also covers a dev-server reload or a second server process.
    """
    key = str(job.job_dir(workspace_dir).resolve())
    lock = _FETCH_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        lock_path = job.job_dir(workspace_dir) / ".download.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+b")
        try:
            await asyncio.to_thread(fcntl.flock, lock_file.fileno(), fcntl.LOCK_EX)
            return await _fetch_outputs_locked(job, workspace_dir, conn=conn)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()


async def _fetch_outputs_locked(job: MdJob, workspace_dir: Path, *, conn=None) -> bool:
    """Bring a finished remote run's results back to the login node and locally.

    Mirrors scratch → project (persist before scratch is purged), then downloads the
    remote ``output/`` tree and top-level ``*.log`` files into the local package dir
    so the existing detail view + local health/metrics recompute work.
    """
    conn = conn or _default_conn()
    scratch = job.remote_scratch_dir
    project = job.remote_project_dir
    if not scratch:
        return True
    if project:
        try:
            await conn.mirror(scratch, project)
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            logger.warning("[%s] scratch→project mirror failed: %s", job.job_id, exc)

    package_dir = job.package_dir(workspace_dir)
    # List the remote files to pull: output/ tree + top-level logs + sbatch out/err.
    inventory = await remote_output_inventory(job, conn=conn)
    # Failure evidence is tiny and irreplaceable once sacct/scratch age out. Fetch it
    # before multi-GB trajectories and 100+ MB checkpoints so a transport drop still
    # leaves the reason locally.
    def _fetch_priority(rel: str) -> tuple[int, str]:
        name = PurePosixPath(rel).name
        if name == "nadoc_failure.log":
            return (0, rel)
        if name.endswith((".log", ".err", ".out")):
            return (1, rel)
        return (2, rel)

    rels = sorted(inventory, key=_fetch_priority)
    total_bytes = sum(inventory.values())
    job.download_status = {
        "state": "downloading", "total_bytes": total_bytes, "verified_bytes": 0,
        "dcd_bytes": sum(size for rel, size in inventory.items() if rel.endswith(".dcd")),
        "inventory": inventory,
        "files_total": len(rels), "files_verified": 0, "current_file": None,
    }
    job.save(workspace_dir)
    if not inventory:
        job.download_status.update(
            state="interrupted", current_file=None,
            failed_files=["Remote output inventory was empty or unavailable"],
        )
        job.save(workspace_dir)
        return False
    failed: list[str] = []
    verified_bytes = 0
    def _transport_alive() -> bool:
        check = getattr(conn, "is_connected", None)
        return True if not callable(check) else bool(check())

    for rel_index, rel in enumerate(rels):
        # A dropped/restarted SSH session invalidates every remaining path. Abort the
        # inventory as one interrupted transfer; retrying every one of thousands of
        # files three times in a tight loop pinned the event loop at 100% CPU and even
        # prevented uvicorn from shutting down.
        if not _transport_alive():
            failed.extend(rels[rel_index:])
            break
        local = package_dir / rel
        job.download_status["current_file"] = rel
        job.save(workspace_dir)
        last_saved = {"bytes": -1}

        def _progress(current: int, _file_total: int) -> None:
            # Persist at ~16 MiB intervals: smooth enough for the UI without rewriting
            # job.json on every 256 KiB SFTP chunk.
            # ``current`` is the absolute size of the resumable partial. Clamp it to
            # the inventory size defensively: progress can never truthfully exceed
            # 100 %, even if an old corrupt partial is encountered and reset.
            current = min(max(0, current), max(0, _file_total))
            transferred = min(total_bytes, verified_bytes + current)
            job.download_status["transferred_bytes"] = transferred
            job.download_status["current_file_bytes"] = current
            if current == _file_total or transferred - last_saved["bytes"] >= 16 * 1024**2:
                job.save(workspace_dir)
                last_saved["bytes"] = transferred
        fetched = False
        transport_lost = False
        for attempt in range(3):
            try:
                import inspect

                if "on_progress" in inspect.signature(conn.sftp_get).parameters:
                    await conn.sftp_get(
                        f"{scratch}/{rel}", str(local), on_progress=_progress
                    )
                else:  # legacy/injected connection implementations
                    await conn.sftp_get(f"{scratch}/{rel}", str(local))
                fetched = True
                break
            except Exception as exc:  # noqa: BLE001 — retry transient SSH/SFTP failures
                logger.warning(
                    "[%s] fetch %s failed (%d/3): %s",
                    job.job_id,
                    rel,
                    attempt + 1,
                    exc,
                )
                if not _transport_alive():
                    failed.extend(rels[rel_index:])
                    transport_lost = True
                    break
        if transport_lost:
            break
        if not fetched:
            failed.append(rel)
            continue
        expected = inventory[rel]
        if not local.exists() or local.stat().st_size != expected:
            failed.append(rel)
            continue
        verified_bytes += expected
        job.download_status.update(
            verified_bytes=verified_bytes,
            transferred_bytes=verified_bytes,
            files_verified=job.download_status["files_verified"] + 1,
        )
        job.save(workspace_dir)

    # Real trajectories have landed on top of any one-frame stand-in, so the marker
    # is void.  Leaving it set would let `remote_live_frame` overwrite real results
    # with a single frame on the next connect.
    from backend.core import remote_live_frame  # noqa: PLC0415 — cycle

    remote_live_frame.clear_live_frame(job, package_dir=package_dir)
    job.download_status.update(
        state="verified" if not failed else "interrupted",
        verified_bytes=verified_bytes,
        current_file=None,
        failed_files=failed,
    )
    job.save(workspace_dir)
    from backend.core.design_disk_usage import invalidate_dir_size

    invalidate_dir_size(job.job_dir(workspace_dir))
    return not failed


def verify_local_download(job: MdJob, workspace_dir: Path) -> bool:
    """Prove a remote result inventory is complete using local files only.

    New downloads persist the exact ``relative path -> byte size`` inventory. Older
    records retain only the exact aggregate byte count and file count, which still form
    a conservative offline proof when both match. This never contacts Alpine and never
    upgrades an incomplete or ambiguous directory.
    """
    status = job.download_status or {}
    # Never inspect/promote a .part owned by the active downloader. At exact size it
    # has not necessarily fsync'd or performed its own atomic rename yet; stealing it
    # here makes the downloader raise ENOENT and used to disconnect Alpine.
    if status.get("state") == "downloading":
        return False
    total = status.get("total_bytes")
    files_total = status.get("files_total")
    if not isinstance(total, int) or total < 0 or not isinstance(files_total, int):
        return False
    package_dir = job.package_dir(workspace_dir)
    inventory = status.get("inventory")
    local: dict[str, int] = {}
    if isinstance(inventory, dict) and inventory:
        try:
            expected = {str(rel): int(size) for rel, size in inventory.items()}
        except (TypeError, ValueError):
            return False
        for rel, size in expected.items():
            path = package_dir / rel
            try:
                part = Path(str(path) + ".part")
                # A transport can drop after fsync and before the final atomic rename.
                # Exact inventory size finishes that rename offline — but only alongside
                # a structural check: byte count alone once promoted a trajectory whose
                # head was a foreign one-frame DCD, and it read as "verified".
                if not path.exists() and part.is_file() and part.stat().st_size == size:
                    intact, detail = resume_transfer.validate_partial(part)
                    if not intact:
                        status["local_verification_error"] = (
                            f"Local result {rel} is the right size but not intact: {detail}"
                        )
                        job.download_status = status
                        job.save(workspace_dir)
                        return False
                    part.replace(path)
                if not path.is_file() or path.stat().st_size != size:
                    actual = path.stat().st_size if path.is_file() else None
                    status["local_verification_error"] = (
                        f"Local result {rel} is missing"
                        if actual is None
                        else f"Local result {rel} is {actual} bytes; expected {size}"
                    )
                    job.download_status = status
                    job.save(workspace_dir)
                    return False
            except OSError:
                return False
        local = expected
    else:
        # Legacy metadata: mirror remote_output_inventory's selection exactly.
        try:
            output = package_dir / "output"
            for path in output.rglob("*") if output.is_dir() else ():
                if path.is_file() and not resume_transfer.is_transfer_artifact(
                    path.name
                ):
                    local[path.relative_to(package_dir).as_posix()] = path.stat().st_size
            for pattern in ("*.log", "*.out", "*.err"):
                for path in package_dir.glob(pattern):
                    if path.is_file():
                        local[path.name] = path.stat().st_size
        except OSError:
            return False
        if len(local) != files_total or sum(local.values()) != total:
            status["local_verification_error"] = (
                f"Local results contain {len(local)} of {files_total} files and "
                f"{sum(local.values())} of {total} bytes"
            )
            job.download_status = status
            job.save(workspace_dir)
            return False

    # Exact inventories also defend their own persisted aggregate/count metadata.
    if len(local) != files_total or sum(local.values()) != total:
        status["local_verification_error"] = "Persisted result inventory is inconsistent"
        job.download_status = status
        job.save(workspace_dir)
        return False
    dcd_bytes = sum(size for rel, size in local.items() if rel.endswith(".dcd"))
    status.update(
        state="verified",
        verified_bytes=total,
        transferred_bytes=total,
        files_verified=files_total,
        current_file=None,
        current_file_bytes=0,
        failed_files=[],
        dcd_bytes=dcd_bytes,
        verified_offline=True,
        verified_at=time.time(),
        local_verification_error=None,
    )
    job.download_status = status
    job.save(workspace_dir)
    from backend.core.design_disk_usage import invalidate_dir_size

    invalidate_dir_size(job.job_dir(workspace_dir))
    return True


async def remote_output_inventory(job: MdJob, *, conn=None) -> dict[str, int]:
    """Remote result files and exact byte sizes; empty is never a verified download."""
    conn = conn or _default_conn()
    scratch = job.remote_scratch_dir
    if not scratch:
        return {}
    listing = await conn.run(
        f"cd {_shq(scratch)} && "
        "find output -type f -printf '%s\\t%p\\n' 2>/dev/null; "
        "for f in *.log *.out *.err; do [ -f \"$f\" ] && stat -c '%s\\t%n' \"$f\"; done"
    )
    out: dict[str, int] = {}
    for line in (listing.stdout or "").splitlines():
        try:
            size_text, rel = line.split("\t", 1)
            rel = rel.strip()
            if rel and not rel.startswith("/") and ".." not in PurePosixPath(rel).parts:
                out[rel] = int(size_text)
        except (ValueError, TypeError):
            continue
    return out


async def cancel_job(job: MdJob, *, conn=None) -> bool:
    """``scancel`` the remote job.  Returns True if a cancel was issued."""
    conn = conn or _default_conn()
    if not job.slurm_job_id:
        return False
    res = await conn.run(f"scancel {job.slurm_job_id}")
    return res.rc == 0


class _SkipHealth(Exception):
    """Internal: this segment's health is already recorded and final."""


def _segment_has_trajectory(
    output_dir: Path, segment_name: str, job: MdJob | None = None
) -> bool:
    """True if a segment wrote a non-trivial DCD, finished or not.

    ``run_health_check`` reads ``output/<segment>.dcd``, so a partial trajectory is
    enough to compute C1'/WC health for a segment still in flight or interrupted
    mid-way.  The size floor skips a freshly-created, header-only file.

    A single-frame stand-in fetched by ``remote_live_frame`` sits at that same path
    and sails past the size floor (tens of MB for a solvated system), so it must be
    excluded explicitly: RMSF over one frame is identically zero, which would read as
    a real — and reassuring — measurement.  Pass ``job`` to get that check.
    """
    if job is not None:
        from backend.core import remote_live_frame  # noqa: PLC0415 — cycle

        # output_dir is `<package>/output`, so its parent is the package dir the marker
        # is keyed on.
        if remote_live_frame.is_live_stand_in(job, segment_name, output_dir.parent):
            return False
    dcd = output_dir / f"{segment_name}.dcd"
    try:
        return dcd.is_file() and dcd.stat().st_size > 4096
    except OSError:
        return False


def _completion_checkpoint_present(job: MdJob, workspace_dir: Path) -> bool:
    """True if a SLURM-completed remote job's checkpoint actually landed locally.

    A genuinely-finished NAMD run leaves at least one segment's restart set
    (``.coor``/``.vel``/``.xsc``) in ``output/``; the resume + downstream chain-seed
    paths restart from it.  If the completion fetch dropped every restart file (a
    partial/failed SFTP download) none are present — that is the ISSUE-15 signal that
    the job must NOT be reported ``completed`` yet.  Conservative by design: a job
    with no segments (nothing to checkpoint) or any surviving checkpoint passes, so a
    good fetch is never falsely flagged.
    """
    if not job.segments:
        return True
    from backend.core.namd_runner import _segment_outputs_complete

    output_dir = job.package_dir(workspace_dir) / "output"
    return any(_segment_outputs_complete(output_dir, seg.name) for seg in job.segments)


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
    # poll_status deliberately treats a job absent from both squeue and aged-out sacct
    # as completed. Publish that inferred terminal state rather than retaining a stale
    # RUNNING badge through the entire result download.
    job.slurm_state = raw or ("COMPLETED" if bucket == "completed" else job.slurm_state)
    new_status = bucket_to_md_status(bucket)

    if bucket in ("pending", "running"):
        changed = job.slurm_state != prev_state
        if bucket == "running" and job.slurm_started_at is None:
            job.slurm_started_at = time.time()
            changed = True
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

    # Terminal — publish scheduler + final stage progress *before* the potentially
    # multi-hour mirror/download. A user reconnecting after completion must immediately
    # see that Alpine is done, every remotely-finished relax stage filled in, and the
    # progress bar repurposed for result transfer instead of the last pre-logout step.
    try:
        await poll_remote_progress(job, conn=conn)
    except Exception as exc:  # noqa: BLE001 — final listing is advisory
        logger.warning("[%s] terminal remote progress poll failed: %s", job.job_id, exc)
    job.download_status = {
        "state": "downloading",
        "total_bytes": None,
        "verified_bytes": 0,
        "transferred_bytes": 0,
        "files_total": None,
        "files_verified": 0,
        "current_file": None,
    }
    job.save(workspace_dir)

    # Pull results back (restart files for a resume; logs to diagnose).
    try:
        await fetch_outputs(job, workspace_dir, conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] output fetch failed: %s", job.job_id, exc)

    # A SLURM-completed job whose checkpoint restart files did not (fully) download
    # must NOT be reported ``completed`` — a completed job leaves the poll set
    # (is_remote_active), so the missing files would never be re-fetched and any
    # downstream chain-stage seed (spawn_md_production) 400s on the absent checkpoint.
    # Keep it re-pollable so the next supervisor pass re-fetches; only give up (→
    # failed) once the bounded retries exhaust.  (ISSUE-15)
    if bucket == "completed" and not _completion_checkpoint_present(job, workspace_dir):
        job.fetch_attempts += 1
        if job.fetch_attempts < _MAX_FETCH_ATTEMPTS:
            logger.warning(
                "[%s] remote job %s COMPLETED but no checkpoint restart files "
                "downloaded — keeping re-pollable, retry %d/%d on next poll",
                job.job_id,
                job.slurm_job_id,
                job.fetch_attempts,
                _MAX_FETCH_ATTEMPTS,
            )
            job.status = (
                MdStatus.running
            )  # stays is_remote_active → re-polled + re-fetched
            job.error = (
                "Completed remotely but the checkpoint restart files failed to "
                f"download (attempt {job.fetch_attempts}/{_MAX_FETCH_ATTEMPTS}) — retrying."
            )
            job.save(workspace_dir)
            return job
        # Retries exhausted — surface a genuine failure naming the missing checkpoint.
        _append_history(job, raw or "unknown")
        job.status = MdStatus.failed
        job.resumable = False
        job.failure_kind = "fetch_incomplete"
        job.error = (
            f"Remote job {job.slurm_job_id} finished but its checkpoint restart files "
            f"(.coor/.vel/.xsc) failed to download after {_MAX_FETCH_ATTEMPTS} attempts. "
            "Check the SSH connection and re-run."
        )
        job.save(workspace_dir)
        logger.info(
            "[%s] remote job %s → failed (fetch incomplete)",
            job.job_id,
            job.slurm_job_id,
        )
        return job

    # Record this finished submission so the panel's expand chevron can show the
    # full resumption chain (original + each resume).
    _append_history(job, raw or "unknown")

    if bucket == "completed":
        # The result bytes are present, but final health/metrics extraction can spend
        # minutes reading a multi-GB trajectory.  Persist that distinct phase before
        # entering the synchronous bookkeeping pass so the UI never looks frozen in
        # the synthetic retry/running state left by an interrupted fetch.
        if job.download_status and job.download_status.get("state") == "verified":
            job.download_status["state"] = "processing"
            job.download_status["processing_started_at"] = time.time()
            job.save(workspace_dir)
        await _finish_local_processing(job, workspace_dir)
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
        diag = job.slurm_diagnostics or {}
        detail = ", ".join(
            f"{label} {diag[key]}"
            for key, label in (
                ("exit_code", "exit"), ("derived_exit_code", "derived exit"),
                ("elapsed", "elapsed"), ("node_list", "node"),
            )
            if diag.get(key)
        )
        base = f"Remote job {job.slurm_job_id} ended in SLURM state {raw or 'unknown'}"
        base += f" ({detail})." if detail else "."
        excerpt, src, kind = _scan_logs_for_error(job.package_dir(workspace_dir))
        if excerpt:
            job.error = f"{base} {excerpt}" + (f" (see {src})" if src else "")
            job.failure_kind = kind
        else:
            job.error = base
    job.save(workspace_dir)
    logger.info(
        "[%s] remote job %s → %s", job.job_id, job.slurm_job_id, job.status.value
    )
    return job


async def _finish_local_processing(job: MdJob, workspace_dir: Path) -> None:
    """Index an already-downloaded remote result without blocking the API loop."""
    # Health/metrics extraction opens every large trajectory and is synchronous.
    # Running it on uvicorn's event loop made /health and every jobs endpoint time out
    # for minutes exactly when a remote download reached 100%. Keep SSH on the main
    # loop, but move this purely local CPU/disk phase to a worker thread.
    await asyncio.to_thread(_finalize_local_bookkeeping, job, workspace_dir)
    _record_learned_throughput(job, workspace_dir)
    if job.download_status and job.download_status.get("state") == "processing":
        job.download_status["state"] = "verified"
        job.download_status["processing_finished_at"] = time.time()
    job.status = MdStatus.completed
    job.error = None
    job.resumable = False
    job.fetch_attempts = 0


async def resume_local_processing_jobs(workspace_dir: Path) -> list[str]:
    """Finish verified Alpine results after a restart, without an SSH connection.

    ``processing`` is persisted only after the complete remote inventory has been
    downloaded and verified, so this phase is entirely local and safe to resume.
    """
    finished: list[str] = []
    for job in MdJob.list_jobs(workspace_dir):
        if (
            job.execution_target == "alpine"
            and job.slurm_state == "COMPLETED"
            and (job.download_status or {}).get("state") == "processing"
        ):
            await _finish_local_processing(job, workspace_dir)
            job.save(workspace_dir)
            finished.append(job.job_id)
    return finished


_REMOTE_RECONCILE_LOCKS: dict[str, asyncio.Lock] = {}


def _needs_remote_reconcile(job: MdJob, *, recover_incomplete: bool = False) -> bool:
    """Whether a connected supervisor/login pass should inspect this Alpine job.

    Ordinary periodic passes follow only scheduler-owned queued/running jobs. A fresh
    login additionally gets one recovery attempt for a job already marked completed
    (or a resumable timeout) whose persisted transfer was interrupted. This covers a
    backend/browser restart during download without turning a permanently bad remote
    file into an unbounded 30-second retry loop.
    """
    if not job.slurm_job_id:
        return False
    transfer_state = (job.download_status or {}).get("state")
    if transfer_state in {"verified", "processing"}:
        return False
    if is_remote_active(job.status):
        return True
    if not recover_incomplete or transfer_state not in {"downloading", "interrupted"}:
        return False
    if job.status == MdStatus.completed:
        return True
    return (
        job.status == MdStatus.paused
        and job.resumable
        and is_timeout_state(job.slurm_state or "")
    )


async def poll_remote_jobs(
    workspace_dir: Path, *, conn=None, recover_incomplete: bool = False
) -> list[str]:
    """Supervisor pass: reconcile every active (queued/running) Alpine job.

    Only runs when the session is connected — a disconnected/expired session leaves
    remote jobs as-is (viewable offline from job.json).  Returns reconciled ids.
    """
    conn = conn or _default_conn()
    if not getattr(conn, "is_connected", lambda: False)():
        return []
    touched: list[str] = []
    for job in MdJob.list_jobs(workspace_dir):
        if job.execution_target != "alpine":
            continue
        # Drain a DEFERRED cancel first: a Stop issued while the session was down set
        # pending_scancel (the job is already stopped locally).  Now that we're connected,
        # scancel it so it doesn't keep running on the cluster, then clear the flag.  This
        # runs even though the job is no longer "active" (it was marked stopped).
        if getattr(job, "pending_scancel", False):
            if job.slurm_job_id:
                try:
                    await cancel_job(job, conn=conn)
                    logger.info(
                        "[%s] drained deferred scancel (SLURM %s)",
                        job.job_id,
                        job.slurm_job_id,
                    )
                except Exception:  # noqa: BLE001 — one job must not kill the pass
                    logger.exception("[%s] deferred scancel failed", job.job_id)
                    continue  # keep the flag; retry next pass
            job.pending_scancel = False
            job.save(workspace_dir)
            touched.append(job.job_id)
            continue  # already stopped locally — nothing else to reconcile
        if not _needs_remote_reconcile(job, recover_incomplete=recover_incomplete):
            continue
        # cluster/connect starts a pass immediately while the 30 s supervisor may
        # already be in one. Never queue a second multi-GB fetch/finalization behind the
        # first: once the first releases, the waiting caller's in-memory job is stale and
        # can reset verified progress or overwrite completed bookkeeping.
        lock_key = str(job.job_dir(workspace_dir).resolve())
        reconcile_lock = _REMOTE_RECONCILE_LOCKS.setdefault(
            lock_key, asyncio.Lock()
        )
        if reconcile_lock.locked():
            continue
        try:
            async with reconcile_lock:
                # Reload after taking ownership. Another request may have updated the
                # record between list_jobs() and this point.
                latest = MdJob.load(job.job_id, workspace_dir)
                if not _needs_remote_reconcile(
                    latest, recover_incomplete=recover_incomplete
                ):
                    continue
                await reconcile_remote_job(latest, workspace_dir, conn=conn)
                touched.append(job.job_id)
        except Exception:  # noqa: BLE001 — one job must not kill the pass
            logger.exception("[%s] remote reconcile failed", job.job_id)
    return touched


# ── local helpers ─────────────────────────────────────────────────────────────


def _scan_logs_for_error(
    package_dir: Path,
) -> tuple[str | None, str | None, str | None]:
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
    diagnostic = package_dir / "output" / "nadoc_failure.log"
    if diagnostic.is_file():
        ordered.append(diagnostic)
    ordered += [p for p in _by_mtime(package_dir.rglob("*.log")) if p != diagnostic]
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
            workspace_dir,
            cluster=job.cluster_name or "",
            partition=partition,
            n_atoms=n_atoms,
            ns_per_day=nsday,
        )
    except Exception:  # noqa: BLE001 — learning must not break job completion
        logger.warning(
            "[%s] learned-throughput record failed", job.job_id, exc_info=True
        )


def _append_history(job: MdJob, state: str) -> None:
    """Record a finished remote submission on the job so the panel's expand chevron can
    show the full resumption chain (original + each resume)."""
    import time

    n = len(job.segments)
    job.resume_history = list(job.resume_history or [])
    job.resume_history.append(
        {
            "slurm_job_id": job.slurm_job_id,
            "state": state,
            "segment_reached": min(job.current_segment_idx + 1, n) if n else 0,
            "segments_total": n,
            "walltime": (job.resources or {}).get("walltime"),
            "slurm_diagnostics": dict(job.slurm_diagnostics or {}),
            "at": time.time(),
        }
    )


def _read_manifest(package_dir: Path) -> dict:
    import json

    return json.loads((Path(package_dir) / "manifest.json").read_text())


def _shq(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


async def _put_text(
    conn, text: str, remote_path: str, workspace_dir: Path, job: MdJob
) -> None:
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
    """Recompute cheap log metrics from fetched outputs.

    Structural health parsing is deliberately not part of remote-job completion: even
    one solvated DCD can exceed a gigabyte and monopolise Python for minutes. Trajectory
    health remains an explicit/on-demand concern; completing a transfer must promptly
    release active-job UI state. Best-effort; never raises.
    """
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

    for seg, spec in zip(job.segments, specs):
        complete = _segment_outputs_complete(output_dir, seg.name)
        # An INTERRUPTED segment still has a usable trajectory.  The gate used to be
        # `complete` alone — all three of .coor/.vel/.xsc, which NAMD writes only when
        # a segment FINISHES.  Under the short-walltime + resume workflow no segment
        # finishes inside a block, so a stopped or timed-out Alpine run produced no
        # health samples and no metrics at all, and the health card stayed empty
        # forever (reported 2026-08-07).  A partial DCD is enough for both.
        if not complete and not _segment_has_trajectory(output_dir, seg.name, job):
            continue
        if complete:
            seg.status = "done"
        log_path = _latest_segment_log(package_dir, seg.name)
        try:
            # A partial segment's numbers change as it runs, so only skip a segment
            # that is genuinely finished.
            if complete and not _jsonl_has_segment(metrics_path, seg.name):
                _append_metrics_jsonl(output_dir, seg.name, seg.stage, log_path)
            elif not complete:
                _append_metrics_jsonl(output_dir, seg.name, seg.stage, log_path)
        except Exception:  # noqa: BLE001
            pass
    job.current_segment_idx = max(0, len(job.segments) - 1)
