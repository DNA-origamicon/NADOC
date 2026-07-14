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

⚠️ **The pod is the meter.** It bills from creation to termination regardless of whether
it is computing. Every path here that creates a pod must destroy it; ``run_job_on_pod``
does so in a ``finally`` via ``RunpodClient.pod``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from backend.core import md_executor
from backend.core.md_job import MdJob, MdStatus
from backend.core.runpod_api import (
    RunpodClient,
    RunpodError,
    build_create_payload,
    ssh_endpoint,
)
from backend.core.runpod_conn import RunpodConnection
from backend.core.runpod_script import (
    ChainStep,
    completed_steps,
    heartbeat_is_stale,
    namd_threads,
    parse_status_file,
    plan_execution,
    render_chain_script,
)

log = logging.getLogger(__name__)

# Hard ceiling on a single pod's life. The stall watchdog kills a HUNG NAMD (no log
# output for 30 min), but a run that is merely slower than expected would keep billing
# all night unattended. 20 h covers a full early-stopped relax ladder on a ~2M-atom
# system (~11-12 h predicted) with real headroom, and caps the damage of a bad estimate.
MAX_POD_LIFETIME_S = 20 * 3600

REMOTE_ROOT = "/workspace/nadoc_jobs"
CHAIN_SCRIPT = "nadoc_chain.sh"
STATUS_FILE = "nadoc_status"
HEARTBEAT_FILE = "nadoc_heartbeat"

# The patched NAMD lives on the NETWORK VOLUME, built once per GPU architecture.
# Pods are disposable; the toolchain is not. (4090 = sm_89, 3080 Ti = sm_86.)
# MULTI-ARCH build (sm_89 Ada + sm_120 Blackwell, + PTX fallback). The old sm_89-only
# binary rents a Blackwell card happily and then dies at step 0 with
# "no kernel image is available for execution on the device".
NAMD_ON_VOLUME = "/workspace/namd/3.0.2p1-cuda-multi/namd3"


def remote_dir_for(job: MdJob) -> str:
    return f"{REMOTE_ROOT}/{job.job_id}"


def chain_steps_for(job: MdJob, min_name: str) -> list[ChainStep]:
    """The ladder: minimisation, then every segment, in order."""
    steps = [ChainStep(min_name, is_minimization=True)]
    steps += [ChainStep(seg.name) for seg in job.segments]
    return steps


# ── Submit ───────────────────────────────────────────────────────────────────


async def submit_job(
    job: MdJob,
    workspace_dir: Path,
    *,
    conn: RunpodConnection,
    min_name: str,
    n_atoms: int,
    vcpus: int,
    gpu_resident: bool = True,
    max_lifetime_s: int = MAX_POD_LIFETIME_S,
) -> int:
    """Stage the package, write the chain script, launch it detached. Returns its PID.

    Idempotent by construction: the chain script skips any step whose
    ``output/<name>.coor`` already exists on the network volume. So calling this again
    after a spot-pod reclaim IS the resume path — no separate resume codepath, unlike
    Alpine (which needs one because SLURM walltimes cut MID-segment).
    """
    remote = remote_dir_for(job)
    pkg = job.package_dir(workspace_dir)

    await conn.mkdir_p(remote)

    # REUSED from the Alpine executor — this is the whole point of the conn duck-type.
    for local_path, rel in md_executor.stage_plan(pkg):
        await conn.sftp_put(str(local_path), f"{remote}/{rel}")

    script = render_chain_script(
        steps=chain_steps_for(job, min_name),
        remote_dir=remote,
        namd_bin=NAMD_ON_VOLUME,
        threads=namd_threads(vcpus),
        devices="0",
        max_lifetime_s=max_lifetime_s,
    )
    tmp = Path(workspace_dir) / "md_jobs" / job.job_id / CHAIN_SCRIPT
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(script)
    await conn.sftp_put(str(tmp), f"{remote}/{CHAIN_SCRIPT}")
    await conn.run(f"chmod +x {remote}/{CHAIN_SCRIPT}")

    pid = await conn.launch_detached(f"{remote}/{CHAIN_SCRIPT}", remote)
    job.runpod_pid = pid
    job.remote_scratch_dir = remote
    job.remote_project_dir = remote  # one filesystem: no project/scratch split
    job.status = MdStatus.running
    job.error = None
    log.info("runpod: job %s launched on pod %s as pid %s", job.job_id, job.runpod_pod_id, pid)
    return pid


# ── Poll ─────────────────────────────────────────────────────────────────────


async def poll_job(job: MdJob, *, conn: RunpodConnection, now: Optional[int] = None) -> dict:
    """One poll pass: chain status + heartbeat + live segment progress.

    Returns ``{state, segment, alive, stale, advanced}``. ``state`` is the chain
    script's own sentinel, which is authoritative — the PID being alive only tells you
    bash is running, not that NAMD is healthy.
    """
    now = now or int(time.time())

    status = parse_status_file(await conn.read_file(f"{job.remote_scratch_dir}/{STATUS_FILE}"))
    hb_raw = (await conn.read_file(f"{job.remote_scratch_dir}/{HEARTBEAT_FILE}")).strip()
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


async def fetch_results(job: MdJob, workspace_dir: Path, *, conn: RunpodConnection) -> bool:
    """Pull outputs back. REUSED verbatim from the Alpine executor."""
    return await md_executor.fetch_outputs(job, workspace_dir, conn=conn)


# ── Whole-job orchestration ──────────────────────────────────────────────────


def pod_payloads_for(job: MdJob, n_atoms: int, *, network_volume_id: str,
                     interruptible: bool = True) -> list[dict]:
    """Size the pod from the system (MEASURED VRAM model), cheapest tier first.

    Returns MULTIPLE payloads because the network volume PINS the pod to its datacenter,
    and a tier is often unavailable there: RunPod answers 500 "There are no instances
    currently available". Community 4090s in particular are frequently absent from the
    volume's region — which is why a hand-made pod silently lands on SECURE at ~2x the
    price ($0.69/hr vs $0.34). We try cheapest-first and walk down rather than fail.
    """
    plan = plan_execution(n_atoms)
    if plan["gpu"] is None:
        raise RunpodError(plan["reason"])
    name = f"nadoc-{job.design_name}-{job.job_id}"[:191]
    # gpuTypeIds is a PRIORITY LIST — hand RunPod every card that fits, cheapest first,
    # and let it pick whatever is actually free in the volume's datacenter.
    gpu_ids = [g.key for g in plan["gpus"]]

    payloads = []
    for cloud_type, spot in (("COMMUNITY", interruptible), ("SECURE", interruptible),
                             ("SECURE", False)):
        payloads.append(build_create_payload(
            name=name,
            gpu_type_ids=gpu_ids,
            network_volume_id=network_volume_id,
            interruptible=spot,
            cloud_type=cloud_type,
        ))
    return payloads


def pod_payload_for(job: MdJob, n_atoms: int, *, network_volume_id: str,
                    interruptible: bool = True) -> dict:
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
    interruptible: bool = True,
    on_pod: Optional[Callable[[str], None]] = None,
) -> MdStatus:
    """Provision → stage → run → fetch → **destroy**. The pod cannot outlive this call.

    A reclaimed interruptible pod is NOT a failure: the chain script is idempotent, so
    the caller simply calls this again and every completed step is skipped. That is the
    whole reason interruptible pods are the default.
    """
    import asyncio

    sleep = sleep or asyncio.sleep
    payloads = pod_payloads_for(
        job, n_atoms, network_volume_id=network_volume_id, interruptible=interruptible
    )

    # cheapest tier first; fall back when the volume's datacenter has no instances
    async with client.pod(payloads[0], fallbacks=payloads[1:]) as pod:  # terminates in a finally
        job.runpod_pod_id = pod.id
        if on_pod is not None:
            # Register the pod id the INSTANT it exists. A caller that cannot name the
            # pod cannot kill it, and an unkillable pod bills until a human notices.
            on_pod(pod.id)
        endpoint = ssh_endpoint(pod)
        if endpoint is None:                          # wait_for_ssh guarantees this, belt+braces
            raise RunpodError(f"pod {pod.id} exposed no SSH endpoint")
        host, port = endpoint

        conn = RunpodConnection(
            host=host, port=port, pod_id=pod.id, client_keys=client_keys
        )
        await conn.connect()
        try:
            vcpus = await _remote_vcpus(conn)
            await submit_job(
                job, workspace_dir, conn=conn, min_name=min_name,
                n_atoms=n_atoms, vcpus=vcpus,
            )

            while True:
                st = await poll_job(job, conn=conn)
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
                await sleep(poll_s)

            # Always fetch what exists — even a failed/paused run has useful output.
            await fetch_results(job, workspace_dir, conn=conn)
        finally:
            await conn.close()

    job.runpod_pid = None
    return job.status


async def _remote_vcpus(conn: RunpodConnection) -> int:
    res = await conn.run("nproc")
    out = res.stdout.strip()
    return int(out) if out.isdigit() else 8
