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

import json
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
    DEFAULT_BUDGET_USD,
    RESUME_CONF_NAME,
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

REMOTE_ROOT = "/workspace/nadoc_jobs"
CHAIN_SCRIPT = "nadoc_chain.sh"
STATUS_FILE = "nadoc_status"
HEARTBEAT_FILE = "nadoc_heartbeat"

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
    steps = [ChainStep(min_name, is_minimization=True)]
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
    res = await conn.run(f"cd {remote} 2>/dev/null && find . -type f -printf '%s %P\\n'")
    if res.rc != 0:
        return {}
    sizes: dict[str, int] = {}
    for line in res.stdout.splitlines():
        size, _, rel = line.partition(" ")
        if rel and size.isdigit():
            sizes[rel] = int(size)
    return sizes


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
        rel for local_path, rel in plan
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
        len(reusable), job.parent_job_id,
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
    probe = 'python3 -c "import MDAnalysis; print(MDAnalysis.__version__)"'
    res = await conn.run(probe)
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
        res = await conn.run(cmd, timeout=900.0)
        if res.rc == 0:
            break
        last = (res.stderr or res.stdout).strip()
        log.warning("runpod: `%s` failed: %s", cmd.split("--")[0].strip(), last[:200])
    else:
        raise MdAnalysisMissing(f"could not install MDAnalysis on the pod: {last}")

    res = await conn.run(probe)
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
    skipped = sent = 0
    for local_path, rel in plan:
        if remote_sizes.get(rel) == local_path.stat().st_size:
            skipped += 1
            continue
        await conn.sftp_put(str(local_path), f"{remote}/{rel}")
        sent += 1
    log.info("runpod: staged %d file(s), reused %d already on the volume", sent, skipped)

    # The cell-shrink resume writer. Staged ALWAYS — an NPT box crossing its patch grid
    # has nothing to do with early-stop, and without this the chain script's "bounded
    # retry" just re-runs the identical failing conf four times.
    from backend.core import remote_resume_conf

    await md_executor._put_text(
        conn, Path(remote_resume_conf.__file__).read_text(),
        f"{remote}/{RESUME_CONF_NAME}", workspace_dir, job,
    )

    manifest = json.loads((pkg / "manifest.json").read_text())
    early_stop = md_executor._early_stop_on(job, manifest)
    tier = md_executor._early_stop_tier(job)

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
            await _ensure_mdanalysis(conn)

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
    budget_usd: float = DEFAULT_BUDGET_USD,
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
    def _created(info):
        # The pod is BILLING from this instant — before wait_for_ssh, before the yield.
        # A host too old for the image's CUDA boots, never starts sshd, and bills for the
        # whole timeout. Registering only at the yield made that spend invisible.
        job.runpod_pod_id = info.id
        job.save(workspace_dir)
        if on_pod is not None:
            on_pod(info.id)

    async with client.pod(payloads[0], fallbacks=payloads[1:],
                          on_created=_created) as pod:  # terminates in a finally
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
        if endpoint is None:                          # wait_for_ssh guarantees this, belt+braces
            raise RunpodError(f"pod {pod.id} exposed no SSH endpoint")
        host, port = endpoint

        conn = RunpodConnection(
            host=host, port=port, pod_id=pod.id, client_keys=client_keys
        )
        await conn.connect()
        try:
            vcpus = await _remote_vcpus(conn)
            # Derive the kill-switch from the rate of the pod we ACTUALLY got — not a
            # hardcoded duration. The fallback list means we may be on the $0.34 card or
            # the $0.82 one, and the same budget buys very different wall-clocks.
            lifetime_s = lifetime_for_budget(budget_usd, pod.cost_per_hr)
            log.info(
                "runpod: pod %s at $%s/hr, $%.2f budget -> kill-switch at %.1f h",
                pod.id, pod.cost_per_hr, budget_usd, lifetime_s / 3600,
            )
            await submit_job(
                job, workspace_dir, conn=conn, min_name=min_name,
                n_atoms=n_atoms, vcpus=vcpus, max_lifetime_s=lifetime_s,
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
