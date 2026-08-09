"""Owns the in-flight RunPod jobs: one asyncio task per job, and the pod it must kill.

``runpod_executor.run_job_on_pod`` is a single long-lived coroutine (provision → stage →
run → fetch → destroy). Something has to hold it, let the API return immediately, and be
able to cancel it. That is this module — the RunPod analogue of ``namd_runner``'s
``_RUNNING`` registry, and of ``md_executor.poll_remote_jobs`` for Alpine (whose loop
filters ``!= "alpine"`` and therefore ignores RunPod jobs entirely).

⚠️ **Cancellation must still destroy the pod.** ``run_job_on_pod`` terminates inside a
``finally``, so cancelling the task unwinds through it — but only if the cancellation is
awaited. ``stop_job`` therefore awaits the task, and belt-and-braces terminates the pod
id directly afterwards. A cancelled task whose pod survives is a GPU billing forever with
nothing watching it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from pathlib import Path
from typing import Optional

from backend.core.md_job import MdJob, MdStatus
from backend.core.runpod_api import RunpodClient
from backend.core.runpod_api import RunpodError
from backend.core.runpod_conn import RunpodSSHError
from backend.core.runpod_executor import reattach_job_on_pod, run_job_on_pod
from backend.core.runpod_script import DEFAULT_BUDGET_USD

log = logging.getLogger(__name__)

_RUNNING: dict[str, asyncio.Task] = {}
_PODS: dict[str, str] = {}  # job_id -> pod_id, so a cancel can kill a pod mid-provision

_NATOM_RE = re.compile(r"^\s*(\d+)\s*!NATOM", re.MULTILINE)

# A spot pod can be reclaimed repeatedly. Resume is cheap (completed steps live on the
# network volume and are skipped), but an interrupted SEGMENT restarts from its top, so
# a pathologically unlucky run could thrash. Cap it, and say so.
MAX_AUTO_RESUMES = 20
RESUME_BACKOFF_S = 30.0  # let the region breathe before asking for another card


def _should_auto_resume(job: MdJob) -> bool:
    """True only for an unintended, checkpoint-safe interruption.

    User Stop and the dollar lifetime are authority boundaries.  Everything else that
    the executor classified paused+resumable is infrastructure loss and should recover
    without waiting for a person to notice it.
    """
    if job.user_stopped or job.status != MdStatus.paused or not job.resumable:
        return False
    return not (job.error and "maximum lifetime" in job.error.lower())


# ── Package introspection (what the sizing + chain need) ─────────────────────


def n_atoms_for(job: MdJob, workspace_dir: Path) -> int:
    """Atom count from the package PSF's ``!NATOM`` header.

    Drives GPU sizing via the measured VRAM model, so it must be the REAL solvated
    count (6hb 225,504 / flat 1,442,735 / VoltronCore 5,656,632), not the DNA-only count.

    ⚠️ **Do NOT "optimise" this into a fixed-size head read.** psfgen emits ONE `REMARKS`
    line per applied patch, so the `!NTITLE` block scales with the residue count and
    `!NATOM` can sit far into the file:

        6hb          604 title lines  → !NATOM at byte  18,729
        flat_1x50  7,342 title lines  → !NATOM beyond   64 KB
        VoltronCore  larger still

    A 4 KB (or even 64 KB) read finds it in none of them. We stream lines instead and
    stop at the header — cheap even on a 700 MB PSF, because `!NATOM` precedes the atom
    records. The cap only guards against a truncated/garbage file.
    """
    pkg = job.package_dir(workspace_dir)
    psf = next((p for p in pkg.glob("*.psf") if not p.stem.endswith("_hmr")), None)
    if psf is None:
        raise RuntimeError(f"no PSF in {pkg} — cannot size a pod for this job")

    with psf.open("r", errors="ignore") as fh:
        for i, line in enumerate(fh):
            if "!NATOM" in line:
                m = _NATOM_RE.search(line)
                if m:
                    return int(m.group(1))
            if i > 2_000_000:  # far past any real !NTITLE block
                break
    raise RuntimeError(f"no !NATOM header found in {psf.name}")


def min_name_for(job: MdJob, workspace_dir: Path) -> str:
    """The minimisation step's name, from the package manifest."""
    manifest = job.package_dir(workspace_dir) / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        name = (data.get("minimization") or {}).get("name")
        if name:
            return str(name)
    conf = next(job.package_dir(workspace_dir).glob("*_00_min_*.conf"), None)
    if conf is None:
        raise RuntimeError("cannot determine the minimisation step name for this job")
    return conf.stem


# ── Registry ─────────────────────────────────────────────────────────────────


def is_running(job_id: str) -> bool:
    task = _RUNNING.get(job_id)
    return task is not None and not task.done()


def running_job_ids() -> list[str]:
    return [jid for jid, t in _RUNNING.items() if not t.done()]


def pod_id_for(job_id: str) -> Optional[str]:
    return _PODS.get(job_id)


# ── Start / stop ─────────────────────────────────────────────────────────────


def start_job(
    job: MdJob,
    workspace_dir: Path,
    *,
    client: RunpodClient,
    network_volume_id: str,
    client_keys: Optional[list[str]] = None,
    interruptible: bool = False,
    budget_usd: Optional[float] = None,
) -> None:
    """Launch the job on a pod in the background. Returns immediately.

    ``budget_usd`` (and ``job.runpod_budget_usd``, which wins) is the spend cap the user set
    in the Job Wizard. It was previously a module constant no one could see or change.
    ⚠️ It caps ONE pod: the auto-resume loop below relaunches with a FRESH budget on every
    reclaim, so N resumes can cost up to N x the cap. Cumulative spend is not tracked.
    """
    if is_running(job.job_id):
        return

    # ``0`` used to fall through this ``or`` chain and silently authorize the full
    # default cap.  Routes reject non-positive caps now, but keep the core boundary
    # explicit too: callers outside FastAPI must never turn "$0" into "$15".
    configured_budget = (
        job.runpod_budget_usd if job.runpod_budget_usd is not None else budget_usd
    )
    budget = (
        DEFAULT_BUDGET_USD if configured_budget is None else float(configured_budget)
    )
    if budget <= 0:
        raise ValueError("RunPod budget must be greater than $0.")

    n_atoms = n_atoms_for(job, workspace_dir)
    min_name = min_name_for(job, workspace_dir)

    async def _main() -> None:
        """Run the ladder, AUTO-RESUMING on every spot reclaim until it finishes.

        An interruptible pod WILL be taken away mid-run — that is the deal, and it is
        why it costs half price. What makes that survivable is that the chain script is
        idempotent: every completed step's ``.coor`` sits on the NETWORK VOLUME, which
        outlives the pod, so relaunching simply skips them. So a reclaim is not a
        failure, it is a **resume**, and resuming is just calling run_job_on_pod again
        on a fresh pod.

        Without this loop a long run stops dead at the first reclaim and waits for a
        human — which, for an overnight run, means it does nothing all night.

        ⚠️ **Coarse-grained.** Resume restarts the INTERRUPTED SEGMENT from the top (a
        segment has no ``.coor`` until it finishes). Real relax segments are 240,000
        steps, so a reclaim can cost hours of that segment's work. It cannot loop
        forever, but it can thrash: hence the cap, and hence on-demand
        (``interruptible=False``) being the right choice for a very long run.
        """
        attempt = 0
        try:
            while True:
                await run_job_on_pod(
                    job,
                    workspace_dir,
                    client=client,
                    network_volume_id=network_volume_id,
                    min_name=min_name,
                    n_atoms=n_atoms,
                    client_keys=client_keys,
                    interruptible=interruptible,
                    budget_usd=budget,
                    on_pod=lambda pid: _PODS.__setitem__(job.job_id, pid),
                )
                _PODS.pop(job.job_id, None)

                resumable = _should_auto_resume(job)
                # A lifetime stop means the user-authorised spend cap was consumed.  It
                # is technically resumable, but doing so automatically with a fresh cap
                # made the cap "$N per retry" and could spend 20x what the wizard showed.
                # Leave the checkpoint paused; a deliberate Start is the next authority.
                budget_exhausted = bool(
                    resumable and job.error and "maximum lifetime" in job.error.lower()
                )
                if budget_exhausted:
                    break
                if not resumable or job.user_stopped:
                    break

                attempt += 1
                if attempt > MAX_AUTO_RESUMES:
                    job.status = MdStatus.paused
                    job.error = (
                        f"Pod was reclaimed {attempt} times; giving up automatic resume. "
                        f"Progress is safe on the network volume — press Start to continue, "
                        f"or use an on-demand pod for a run this long."
                    )
                    break

                log.warning(
                    "runpod job %s: pod reclaimed, auto-resuming (%d/%d) — completed "
                    "steps are on the volume and will be skipped",
                    job.job_id,
                    attempt,
                    MAX_AUTO_RESUMES,
                )
                job.resubmit_count = attempt
                job.status = MdStatus.running
                job.error = None
                job.resumable = False
                with contextlib.suppress(Exception):
                    job.save(workspace_dir)
                await asyncio.sleep(RESUME_BACKOFF_S)

        except asyncio.CancelledError:
            # run_job_on_pod's `finally` already terminated the pod on the way out.
            # EXCEPT during a dev-reload handoff: runpod_api's context manager deliberately
            # leaves the pod alive for the replacement server.  Marking the record stopped
            # here removed its durable claim, so startup's orphan reaper immediately killed
            # the supposedly handed-off pod.  Preserve RUNNING + pod id for adoption.
            from backend.core import runpod_api

            if not runpod_api._handing_off():  # noqa: SLF001 — shared lifecycle flag
                job.status = MdStatus.stopped
                job.user_stopped = True
                job.error = None
            raise
        except (RunpodError, RunpodSSHError, OSError, asyncio.TimeoutError) as exc:
            # Provisioning/API/transport loss is no more a scientific failure than a
            # spot reclaim.  The pod context has already torn down anything billable and
            # the volume holds completed checkpoints, so feed it through the same bounded
            # automatic-resume policy on the next supervisor pass.
            log.warning(
                "runpod job %s infrastructure interruption: %s", job.job_id, exc
            )
            job.status = MdStatus.paused
            job.resumable = True
            job.resubmit_count += 1
            retry = job.resubmit_count <= MAX_AUTO_RESUMES
            job.error = (
                f"RunPod infrastructure interruption ({exc}); automatically retrying."
                if retry
                else f"RunPod infrastructure failed {job.resubmit_count} times; "
                "automatic retry limit reached. Resume manually to try again."
            )
            with contextlib.suppress(Exception):
                job.save(workspace_dir)
            # This exception can occur outside run_job_on_pod's normal paused return.
            # Relaunch via a fresh task after this one releases the registry.
            if retry:
                asyncio.get_running_loop().call_later(
                    RESUME_BACKOFF_S,
                    lambda: (
                        start_job(
                            job,
                            workspace_dir,
                            client=client,
                            network_volume_id=network_volume_id,
                            client_keys=client_keys,
                            interruptible=interruptible,
                            budget_usd=budget,
                        )
                        if _should_auto_resume(job) and not is_running(job.job_id)
                        else None
                    ),
                )
        except Exception as exc:  # noqa: BLE001 — a crash must not strand a pod
            log.exception("runpod job %s failed", job.job_id)
            job.status = MdStatus.failed
            job.error = str(exc)
        finally:
            _PODS.pop(job.job_id, None)
            with contextlib.suppress(Exception):
                job.save(workspace_dir)

    task = asyncio.create_task(_main(), name=f"runpod:{job.job_id}")
    _RUNNING[job.job_id] = task
    task.add_done_callback(lambda _t: _RUNNING.pop(job.job_id, None))


async def stop_job(job_id: str, *, client: Optional[RunpodClient] = None) -> bool:
    """Cancel the job AND make certain its pod is destroyed.

    Cancelling the task unwinds ``run_job_on_pod``'s ``finally``, which terminates the
    pod — but only if we AWAIT the cancellation. We then terminate the recorded pod id
    directly as well: a pod that outlives its task has nothing left watching it and bills
    until a human notices.
    """
    task = _RUNNING.get(job_id)
    pod_id = _PODS.get(job_id)

    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    if pod_id and client is not None:
        with contextlib.suppress(Exception):
            await client.terminate_pod(
                pod_id, reason="explicit_job_stop", job_id=job_id
            )
        log.info("runpod: stop_job terminated pod %s for job %s", pod_id, job_id)

    _RUNNING.pop(job_id, None)
    _PODS.pop(job_id, None)
    return task is not None or pod_id is not None


def _claimed_pods(workspace_dir: Path) -> dict[str, MdJob]:
    """``{pod_id: job}`` for every job whose record says it is still on a pod.

    A pod is only an ORPHAN if nothing claims it. After a dev-server reload the in-memory
    registry is empty but the job records on disk are not — and those records are the whole
    reason the pod id is persisted the instant a pod exists.
    """
    out: dict[str, MdJob] = {}
    try:
        jobs = MdJob.list_jobs(workspace_dir)
    except Exception:  # noqa: BLE001 — an unreadable workspace must not block a reap
        return out
    for j in jobs:
        if (
            j.execution_target == "runpod"
            and j.runpod_pod_id
            and j.status in (MdStatus.running, MdStatus.preparing, MdStatus.queued)
        ):
            out[j.runpod_pod_id] = j
    return out


async def reap_orphan_pods(
    client: RunpodClient, workspace_dir: Optional[Path] = None
) -> tuple[list[str], list[MdJob]]:
    """Terminate every live pod nothing claims; return the ones that ARE claimed.

    Returns ``(killed_pod_ids, adoptable_jobs)``.

    Called on reconnect. A crash or a lost job.json orphans a pod — it keeps running, keeps
    billing, and nothing watches it. Only pods whose name carries our prefix are touched, so
    a pod the user started by hand is left alone.

    ⚠️ **A pod a running job still claims is NOT an orphan.** Reaping by "absent from the
    in-memory registry" alone killed exactly the pods a reload was meant to preserve: the
    registry is empty in a fresh process, so the first reconnect destroyed the live run it
    was supposed to rescue. Those come back as ``adoptable_jobs`` for the caller to
    re-attach instead.
    """
    killed: list[str] = []
    adoptable: list[MdJob] = []
    tracked = set(_PODS.values())
    claimed = _claimed_pods(workspace_dir) if workspace_dir else {}
    for pod in await client.list_pods():
        name = str(pod.raw.get("name") or "")
        if not name.startswith("nadoc-"):
            continue
        # is_DESTROYED, not is_terminated: an EXITED pod is a stopped container that is
        # still on the account and still billing for its disk. Skipping those is what
        # orphaned pod 2tnfzwx9j3mvhm — it sat EXITED and every reap walked past it.
        if pod.id in tracked or pod.is_destroyed:
            continue
        job = claimed.get(pod.id)
        if job is not None:
            adoptable.append(job)
            log.info(
                "runpod: pod %s (%s) is claimed by job %s (%s) — adopting, not reaping",
                pod.id,
                name,
                job.job_id,
                job.status.value,
            )
            continue
        with contextlib.suppress(Exception):
            await client.terminate_pod(pod.id, reason="unclaimed_nadoc_orphan")
            killed.append(pod.id)
            log.warning("runpod: reaped orphaned pod %s (%s)", pod.id, name)
    return killed, adoptable


def reattach_job(
    job: MdJob,
    workspace_dir: Path,
    *,
    client: RunpodClient,
    client_keys: Optional[list[str]] = None,
    network_volume_id: Optional[str] = None,
) -> None:
    """Resume supervision of a run already going on its pod. Returns immediately.

    Same registry and task shape as :func:`start_job`, so a re-attached run is stopped,
    polled and torn down by exactly the same code paths as one this process launched —
    including the guarantee that the pod dies when the run does.
    """
    if is_running(job.job_id):
        return

    async def _main() -> None:
        restart = False
        try:
            await reattach_job_on_pod(
                job,
                workspace_dir,
                client=client,
                client_keys=client_keys,
                on_pod=lambda pid: _PODS.__setitem__(job.job_id, pid),
            )
            restart = _should_auto_resume(job)
        except Exception as exc:  # noqa: BLE001
            # An adopt that fails must not leave the job claiming a pod forever: the next
            # reconnect would try again and never reap it.
            log.exception("runpod: could not adopt pod for job %s", job.job_id)
            job.status = MdStatus.paused
            job.resumable = True
            job.error = (
                f"Lost the pod supervising this run ({exc}); resume to continue."
            )
            job.runpod_pod_id = None
            job.save(workspace_dir)
            restart = _should_auto_resume(job)
        finally:
            _PODS.pop(job.job_id, None)
            _RUNNING.pop(job.job_id, None)
        volume_id = job.runpod_volume_id or network_volume_id
        if restart and volume_id:
            start_job(
                job,
                workspace_dir,
                client=client,
                network_volume_id=volume_id,
                client_keys=client_keys,
            )

    _RUNNING[job.job_id] = asyncio.create_task(
        _main(), name=f"runpod-adopt:{job.job_id}"
    )
