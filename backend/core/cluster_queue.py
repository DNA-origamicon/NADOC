"""Fleet-level SLURM availability: which GPUs are free, and how long you'd wait.

Everything NADOC knew about Alpine's load until now was *per job* (``squeue -j <id>``
in :mod:`backend.core.md_executor`).  This module is the missing fleet view: it asks
the cluster what is idle right now, how deep the pending queue is, and — for a
specific job shape — when SLURM itself thinks the job would start.

Layout follows the house split (see ``md_executor.list_namd_modules`` /
``parse_namd_modules``): **pure parsers first**, unit-tested against captured
fixtures, then one thin async probe at the bottom that runs the remote commands.

Three independent wait signals, deliberately kept separate in the output so the UI
can show provenance rather than one falsely-confident number:

1. ``free_now``    — GPUs idle this second (``scontrol show node``).  Authoritative
   for "can it start immediately", useless for anything else.
2. ``slurm_start`` — SLURM's own backfill prediction, from ``sbatch --test-only``
   for the real job shape (and from pending jobs' ``%S``).  Absent whenever the
   backfill scheduler has not placed the job; ``None`` means UNKNOWN, never zero.
3. ``history``     — median/p90 of (Start - Submit) over recent ``sacct`` records.
   The only signal that reflects fair-share reality, but it is backward-looking.

Nothing here mutates anything on the cluster.  ``sbatch --test-only`` validates and
predicts without ever queuing a job.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime

from backend.core.cluster_config import ClusterProfile

logger = logging.getLogger(__name__)

# Login nodes are shared and `scontrol show node` is not free — never re-probe more
# often than this, however eagerly the UI polls.
CACHE_TTL_S = 60.0

# Per-command ceiling.  A wedged login node must not hold the single serialized
# ClusterConnection lock for minutes.
_CMD_TIMEOUT_S = 20.0

_UNKNOWN_TIMES = {"", "unknown", "n/a", "none", "invalid", "(null)"}


# ── Pure parsers ──────────────────────────────────────────────────────────────


def _parse_slurm_time(text: str) -> datetime | None:
    """SLURM timestamp (``2026-08-06T14:22:11``) → datetime, else ``None``.

    SLURM writes ``Unknown``/``N/A`` for a pending job the backfill scheduler has
    not placed yet.  Those must stay ``None`` — treating them as "now" is what turns
    an unknown wait into a confident lie.
    """
    s = (text or "").strip()
    if s.lower() in _UNKNOWN_TIMES:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _gpu_count_from_tres(tres: str) -> int:
    """GPU count out of a SLURM TRES string.

    Handles both the plain ``gres/gpu=4`` form and the typed ``gres/gpu:h200=4``
    form (clusters emit one, the other, or both — when both are present the plain
    key is the total, so it wins).
    """
    text = tres or ""
    m = re.search(r"gres/gpu=(\d+)", text)
    if m:
        return int(m.group(1))
    typed = re.findall(r"gres/gpu:[^=,]+=(\d+)", text)
    return sum(int(n) for n in typed)


def _gres_model(gres: str) -> str:
    """Model token out of a node ``Gres=`` field, e.g. ``gpu:h200:4(S:0-1)`` → ``h200``."""
    for gtype in gres_by_type(gres):
        if not is_mig_type(gtype):
            return gtype
    for gtype in gres_by_type(gres):
        return gtype
    return ""


# A MIG profile name carries its slice geometry: a100_3g.20gb, h200_2g.35gb,
# rtx_pro_6000_1g.24gb.  Whole-GPU types never match.
_MIG_RE = re.compile(r"\d+g\.\d+gb", re.IGNORECASE)


def is_mig_type(gres_type: str) -> bool:
    """True for a MIG slice profile, false for a whole GPU.

    Load-bearing: NADOC submits ``--gres=gpu:h200:1``, i.e. a **whole** GPU.  Free
    MIG slices cannot serve that request, so counting them as available GPUs
    advertises capacity a NAMD job can never get.  Alpine runs MIG on some ah200 /
    artxpro6000 / aa100 nodes, which is why 8 four-GPU H200 nodes reported 56 "GPUs".
    """
    return bool(_MIG_RE.search(gres_type or ""))


def gres_by_type(gres: str) -> dict[str, int]:
    """``Gres=gpu:h200:4(S:0-1),gpu:h200_3g.71gb:3`` → ``{'h200': 4, 'h200_3g.71gb': 3}``."""
    out: dict[str, int] = {}
    for m in re.finditer(r"gpu:([^:,()]+):(\d+)", gres or ""):
        out[m.group(1).strip()] = out.get(m.group(1).strip(), 0) + int(m.group(2))
    return out


def alloc_gpus_by_type(tres: str) -> dict[str, int]:
    """Typed allocated GPUs from AllocTRES (``gres/gpu:h200=1``) — may be empty.

    SLURM emits the typed keys only on some configurations; callers must cope with
    an empty result rather than assuming zero allocation.
    """
    out: dict[str, int] = {}
    for m in re.finditer(r"gres/gpu:([^=,]+)=(\d+)", tres or ""):
        out[m.group(1).strip()] = int(m.group(2))
    return out


def parse_scontrol_nodes(text: str) -> list[dict]:
    """``scontrol -o show node`` (one line per node) → per-node GPU occupancy.

    Each line is flat ``Key=Value`` pairs.  We keep only what the availability view
    needs: which partitions the node serves, its state, and configured vs allocated
    GPUs.  Nodes with no GPUs are kept (``gpus_total == 0``) so CPU partitions still
    report node states.
    """
    nodes: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("NodeName="):
            continue
        # Split on whitespace-separated key=value; values here never contain spaces
        # except CfgTRES/AllocTRES, which are comma-joined and space-free.
        fields: dict[str, str] = {}
        for tok in line.split():
            key, sep, val = tok.partition("=")
            if sep:
                fields.setdefault(key, val)
        name = fields.get("NodeName", "")
        if not name:
            continue
        partitions = [p for p in fields.get("Partitions", "").split(",") if p]
        state = fields.get("State", "").upper()
        cfg = fields.get("CfgTRES", "")
        alloc = fields.get("AllocTRES", "")
        gres = fields.get("Gres", "")

        # Split configured GPUs into whole cards vs MIG slices.  Only whole cards can
        # serve NADOC's `--gres=gpu:<model>:1` request.
        by_type = gres_by_type(gres)
        whole_total = sum(n for t, n in by_type.items() if not is_mig_type(t))
        mig_total = sum(n for t, n in by_type.items() if is_mig_type(t))
        total_from_tres = _gpu_count_from_tres(cfg)
        if not by_type and total_from_tres:
            # No parseable Gres= line: assume everything CfgTRES reports is a whole GPU.
            whole_total = total_from_tres

        alloc_typed = alloc_gpus_by_type(alloc)
        alloc_total = _gpu_count_from_tres(alloc)
        if alloc_typed:
            whole_alloc = sum(n for t, n in alloc_typed.items() if not is_mig_type(t))
            mig_alloc = sum(n for t, n in alloc_typed.items() if is_mig_type(t))
        else:
            # Untyped AllocTRES: charge allocation to whole cards first.  This
            # UNDER-reports free capacity, which is the safe direction — promising a
            # whole GPU that is actually carved into MIG slices wastes a queue slot.
            whole_alloc = min(alloc_total, whole_total)
            mig_alloc = min(max(0, alloc_total - whole_alloc), mig_total)

        nodes.append(
            {
                "node": name,
                "partitions": partitions,
                "state": state,
                "gpus_total": whole_total,
                "gpus_alloc": min(whole_alloc, whole_total),
                "mig_total": mig_total,
                "mig_alloc": min(mig_alloc, mig_total),
                "gpu_model": _gres_model(gres),
                "gres": gres,
                "cpus_total": int(fields.get("CPUTot", 0) or 0),
                "cpus_alloc": int(fields.get("CPUAlloc", 0) or 0),
            }
        )
    return nodes


def observed_partitions(nodes: list[dict]) -> list[str]:
    """Every partition name the cluster actually reports, sorted.

    The profile is a static guess; this is ground truth.  Used to warn when a
    configured partition no longer exists (CURC renames them — ``amilan`` → ``acpu``
    happened during the 2026 expansion) rather than letting submissions fail later.
    """
    seen: set[str] = set()
    for node in nodes:
        seen.update(node.get("partitions", []))
    return sorted(seen)


def observed_gres(nodes: list[dict], partition: str) -> list[str]:
    """Distinct ``Gres=`` strings on a partition's nodes — the live GRES tokens.

    Confirms the ``gres_type`` in the profile without a shell, and makes MIG slices
    visible (``gpu:h200_3g.71gb:3`` alongside ``gpu:h200:4``).
    """
    seen: set[str] = set()
    for node in nodes:
        if partition in node.get("partitions", []) and node.get("gres"):
            seen.add(node["gres"])
    return sorted(seen)


# Node states that cannot accept work.  SLURM appends flags (``IDLE+DRAIN``,
# ``MIXED+CLOUD``), so these are tested as substrings of the state field.
_UNAVAILABLE_STATE_FLAGS = ("DOWN", "DRAIN", "DRNG", "FAIL", "MAINT", "RESERVED", "UNK")


def aggregate_nodes_by_partition(
    nodes: list[dict], partitions: list[str]
) -> dict[str, dict]:
    """Roll per-node occupancy up to a per-partition availability row.

    GPUs on a drained/down node are excluded from ``gpus_total`` — counting them
    would advertise capacity that cannot actually be scheduled.
    """
    out: dict[str, dict] = {
        p: {
            "nodes_total": 0,
            "nodes_idle": 0,
            "nodes_mixed": 0,
            "nodes_alloc": 0,
            "nodes_down": 0,
            "gpus_total": 0,
            "gpus_alloc": 0,
            "gpus_free": 0,
            "mig_total": 0,
            "mig_free": 0,
            "gpu_model": "",
        }
        for p in partitions
    }
    wanted = set(partitions)
    for node in nodes:
        for part in node["partitions"]:
            if part not in wanted:
                continue
            row = out[part]
            row["nodes_total"] += 1
            state = node["state"]
            down = any(flag in state for flag in _UNAVAILABLE_STATE_FLAGS)
            if down:
                row["nodes_down"] += 1
            elif state.startswith("IDLE"):
                row["nodes_idle"] += 1
            elif state.startswith("MIX"):
                row["nodes_mixed"] += 1
            else:
                row["nodes_alloc"] += 1
            if not down:
                row["gpus_total"] += node["gpus_total"]
                row["gpus_alloc"] += node["gpus_alloc"]
                row["mig_total"] += node.get("mig_total", 0)
                row["mig_free"] += max(
                    0, node.get("mig_total", 0) - node.get("mig_alloc", 0)
                )
            if node["gpu_model"] and not row["gpu_model"]:
                row["gpu_model"] = node["gpu_model"]
    for row in out.values():
        row["gpus_free"] = max(0, row["gpus_total"] - row["gpus_alloc"])
    return out


def parse_squeue_pending(text: str) -> dict[str, dict]:
    """``squeue -t PD -o '%P|%i|%b|%r|%V|%S|%u'`` → per-partition pending demand.

    ``%b`` is the per-node GRES request (``gres:gpu:h200:1``), ``%r`` the pending
    REASON — which is the genuinely diagnostic field: ``Resources`` means you are
    next in line and waiting on hardware, ``Priority`` means other jobs are ahead of
    you, and a ``QOSMax…PerUser`` reason means *your own* limit is the blocker and
    no amount of waiting helps.
    """
    out: dict[str, dict] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        partition = parts[0].strip().rstrip("*")
        if not partition:
            continue
        row = out.setdefault(
            partition,
            {
                "pending_jobs": 0,
                "pending_gpus": 0,
                "reasons": {},
                "earliest_start": None,
                "blocked_on_hardware": 0,
            },
        )
        row["pending_jobs"] += 1
        gres = parts[2].strip()
        m = re.search(r"gpu:(?:[^:]+:)?(\d+)", gres)
        if m:
            row["pending_gpus"] += int(m.group(1))
        reason = parts[3].strip()
        if reason:
            row["reasons"][reason] = row["reasons"].get(reason, 0) + 1
            # "Resources" means the job is scheduled next and is waiting on hardware —
            # the only reason that proves the partition is genuinely full.  A job held
            # on Priority or a QOSMax*PerUser cap is blocked by policy, not by GPUs,
            # and says nothing about whether YOUR job could start.
            if reason == "Resources":
                row["blocked_on_hardware"] += 1
        start = _parse_slurm_time(parts[5])
        if start is not None:
            current = row["earliest_start"]
            if current is None or start < current:
                row["earliest_start"] = start
    return out


def parse_sacct_waits(text: str, *, min_samples: int = 3) -> dict[str, dict]:
    """``sacct -X -P -n -o Partition,Submit,Start,State`` → per-partition wait stats.

    Only rows that actually started contribute; a job cancelled while pending has no
    wait to measure and would bias the median toward zero.  Partitions with fewer
    than ``min_samples`` starts report ``None`` rather than a median of one job.
    """
    waits: dict[str, list[float]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        partition = parts[0].strip().rstrip("*")
        submit = _parse_slurm_time(parts[1])
        start = _parse_slurm_time(parts[2])
        if not partition or submit is None or start is None:
            continue
        minutes = (start - submit).total_seconds() / 60.0
        if minutes < 0:
            continue
        waits.setdefault(partition, []).append(minutes)

    out: dict[str, dict] = {}
    for partition, samples in waits.items():
        samples.sort()
        n = len(samples)
        if n < min_samples:
            out[partition] = {
                "median_wait_min": None,
                "p90_wait_min": None,
                "n_samples": n,
            }
            continue
        out[partition] = {
            "median_wait_min": round(_percentile(samples, 0.5), 1),
            "p90_wait_min": round(_percentile(samples, 0.9), 1),
            "n_samples": n,
        }
    return out


def _percentile(sorted_samples: list[float], q: float) -> float:
    """Nearest-rank percentile of an already-sorted list (non-empty)."""
    idx = max(
        0, min(len(sorted_samples) - 1, int(round(q * (len(sorted_samples) - 1))))
    )
    return sorted_samples[idx]


def parse_test_only(text: str) -> datetime | None:
    """Estimated start time out of ``sbatch --test-only`` output.

    SLURM writes ``sbatch: Job 12345 to start at 2026-08-06T18:22:11 using 8
    processors on nodes … in partition ah200`` — on **stderr**, and only when the
    backfill scheduler could place the job.  Anything else (including a rejection)
    yields ``None``.
    """
    m = re.search(r"to start at\s+(\S+)", text or "")
    return _parse_slurm_time(m.group(1)) if m else None


def _fmt_minutes(minutes: float | None) -> str | None:
    """Humanise a wait in minutes ("~3 h 20 m"); ``None`` passes through."""
    if minutes is None:
        return None
    m = max(0, int(round(minutes)))
    if m < 60:
        return f"~{m} min"
    hours, rem = divmod(m, 60)
    if hours < 24:
        return f"~{hours} h" if rem < 5 else f"~{hours} h {rem} m"
    days, rem_h = divmod(hours, 24)
    return f"~{days} d" if rem_h < 1 else f"~{days} d {rem_h} h"


def summarize_availability(
    profile: ClusterProfile,
    *,
    node_rows: dict[str, dict],
    pending: dict[str, dict],
    history: dict[str, dict],
    slurm_starts: dict[str, datetime | None] | None = None,
    job_shape: dict | None = None,
    throughput_for: "callable | None" = None,
    now: datetime,
    history_scope: str = "unknown",
) -> list[dict]:
    """Merge the three signals into one row per GPU partition.

    ``job_shape`` (optional) is a ``cluster_resources.recommend()`` result for the
    real job; when present each row also carries what *this* job would cost and how
    long it would take **on that partition** — recomputed per partition, because a
    walltime derived from A100 throughput is simply wrong for an H200.

    ``throughput_for(partition) -> ns/day | None`` supplies the *learned* throughput
    for that specific partition.  A single measured number must NOT be reused across
    partitions: doing so made every row report an identical ns/day (live 2026-08-06),
    which silently cancels the speed comparison the table exists to make.  Where no
    per-partition measurement exists we fall back to the size guess, which at least
    applies the right speed factor.

    Rows are sorted by estimated **time to result** (wait + runtime), not by wait
    alone: a faster GPU that starts later still finishes first surprisingly often,
    and finish time is the number that actually matters.  Rows with no wait estimate
    sort last rather than being optimistically treated as zero.
    """
    from backend.core import cluster_resources  # noqa: PLC0415  (avoids an import cycle)

    starts = slurm_starts or {}
    rows: list[dict] = []
    for part in profile.partitions:
        if part.kind != "gpu":
            continue
        occupancy = node_rows.get(part.name) or {}
        demand = pending.get(part.name) or {}
        past = history.get(part.name) or {}

        gpus_free = int(occupancy.get("gpus_free", 0) or 0)
        need = int((job_shape or {}).get("gpus", 1) or 1)
        pending_gpus = int(demand.get("pending_gpus", 0) or 0)

        # Signal 2: SLURM's prediction for OUR job shape (`sbatch --test-only`) only.
        # The earliest pending job's start time is deliberately NOT used as a proxy:
        # that job may be held by its owner's QoS cap for hours on a partition that is
        # wide open for us.  Live check 2026-08-06 showed exactly that — artxpro6000
        # read "13 h 39 m" from a stranger's queued job while 39 GPUs sat idle.
        predicted = starts.get(part.name)
        slurm_wait_min = None
        if predicted is not None:
            slurm_wait_min = max(0.0, (predicted - now).total_seconds() / 60.0)

        # Signal 1: free whole GPUs, with nothing waiting on hardware ahead of us.
        # Gating on total pending was too strict — most pending jobs are held by
        # policy, not by a shortage of GPUs.
        blocked = int(demand.get("blocked_on_hardware", 0) or 0)
        starts_now = gpus_free >= need and blocked == 0

        median = past.get("median_wait_min")
        if starts_now:
            wait_min, basis = 0.0, "free now"
        elif slurm_wait_min is not None:
            wait_min, basis = slurm_wait_min, "SLURM backfill estimate"
        elif median is not None:
            wait_min, basis = (
                float(median),
                f"median of {past.get('n_samples')} recent jobs ({history_scope})",
            )
        else:
            wait_min, basis = None, "unknown"

        row = {
            "partition": part.name,
            "gpu_model": part.gpu_model or occupancy.get("gpu_model", ""),
            "gres_type": part.gres_type,
            "gpus_per_node": part.gpus,
            "request_only": False,
            "nodes_total": occupancy.get("nodes_total", 0),
            "nodes_idle": occupancy.get("nodes_idle", 0),
            "nodes_mixed": occupancy.get("nodes_mixed", 0),
            "nodes_alloc": occupancy.get("nodes_alloc", 0),
            "nodes_down": occupancy.get("nodes_down", 0),
            "gpus_total": occupancy.get("gpus_total", 0),
            "gpus_free": gpus_free,
            "mig_total": occupancy.get("mig_total", 0),
            "mig_free": occupancy.get("mig_free", 0),
            "pending_jobs": demand.get("pending_jobs", 0),
            "pending_gpus": pending_gpus,
            "blocked_on_hardware": blocked,
            "top_reason": _top_reason(demand.get("reasons") or {}),
            "slurm_start": predicted.isoformat() if predicted is not None else None,
            "median_wait_min": median,
            "p90_wait_min": past.get("p90_wait_min"),
            "history_samples": past.get("n_samples", 0),
            "history_scope": history_scope,
            "wait_min": None if wait_min is None else round(wait_min, 1),
            "wait_basis": basis,
            "wait_label": _fmt_minutes(wait_min) or "unknown",
            "max_walltime_h": max(
                (q.max_walltime_h for q in profile.qos_tiers_for_partition(part.name)),
                default=None,
            ),
            "speed_factor": cluster_resources.gpu_speed_factor(part.name),
            "su_per_gpu_hour": part.su_per_gpu_hour or profile.su_per_gpu_hour,
        }

        # Per-partition job projection: re-run the recommender against THIS partition
        # so ns/day, walltime and SU cost reflect its GPU, not the default's.
        if job_shape and job_shape.get("n_atoms") and job_shape.get("total_ns"):
            # Learned ns/day for THIS partition only — never the job's single measured
            # value, which was recorded on one specific GPU.
            measured = throughput_for(part.name) if throughput_for else None
            try:
                rec = cluster_resources.recommend(
                    profile,
                    n_atoms=int(job_shape["n_atoms"]),
                    total_ns=float(job_shape["total_ns"]),
                    measured_ns_per_day=measured,
                    partition=part.name,
                )
            except ValueError:
                rec = None
            if rec is not None:
                row["job_ns_per_day"] = rec["expected_ns_per_day"]
                row["job_ns_per_day_measured"] = bool(measured)
                row["job_walltime_h"] = rec["walltime_h"]
                row["job_cost_su"] = rec["est_cost_su"]
                # SU per ns is what actually separates two equally-fast partitions.
                # Measured 2026-08-07: ah200 and artxpro6000 run the same speed, but
                # Blackwell bills 242 vs 334 SU/GPU-h — ~30% more science per SU.
                if job_shape.get("total_ns"):
                    row["job_su_per_ns"] = round(
                        rec["est_cost_su"] / float(job_shape["total_ns"]), 1
                    )
                row["job_qos"] = rec["qos"]
                if wait_min is not None:
                    row["time_to_result_h"] = round(
                        wait_min / 60.0 + rec["walltime_h"], 2
                    )
        rows.append(row)

    # gh200 is real hardware but needs a support request first — surface it so the
    # option is known to exist, never as something that can just be submitted to.
    if not any(r["partition"] == "gh200" for r in rows):
        rows.append(
            {
                "partition": "gh200",
                "gpu_model": "NVIDIA Grace-Hopper",
                "gres_type": "gh200",
                "gpus_per_node": 1,
                "request_only": True,
                "nodes_total": 2,
                "gpus_total": 2,
                "gpus_free": 0,
                "pending_jobs": 0,
                "pending_gpus": 0,
                "top_reason": "",
                "wait_min": None,
                "wait_basis": "request-only — needs a CURC support request",
                "wait_label": "request access",
                "max_walltime_h": 168,
            }
        )

    def _sort_key(r: dict) -> tuple:
        ttr = r.get("time_to_result_h")
        wait = r.get("wait_min")
        if r.get("request_only"):
            return (2, 0.0)
        if ttr is not None:
            return (0, ttr)
        return (1, wait if wait is not None else float("inf"))

    rows.sort(key=_sort_key)
    return rows


def _top_reason(reasons: dict[str, int]) -> str:
    if not reasons:
        return ""
    name, count = max(reasons.items(), key=lambda kv: kv[1])
    return f"{name} ({count})"


# ── Read-only cluster probes ──────────────────────────────────────────────────
#
# A NAMED REGISTRY, not an allowlist over free text: the caller picks a probe by
# name and may supply at most one sanitised argument, so there is no path by which a
# caller-supplied string becomes a command.  Everything here only reads state.

# `/` is included because module names legitimately contain it (namd/3.0.1_cpu);
# it carries no shell meaning. Everything with shell significance stays out.
_ARG_OK = re.compile(r"^[A-Za-z0-9_.+/-]{1,64}$")

_PROBES: dict[str, str] = {
    # What software exists.  `spider` searches every hierarchy branch, unlike `avail`,
    # which hides modules until their compiler is loaded.
    "modules": "source /etc/profile >/dev/null 2>&1; module -t spider {arg} 2>&1",
    # Runtime floor for any binary we might upload: a build made against a newer glibc
    # than the cluster's simply will not start.
    "os": "cat /etc/os-release 2>/dev/null; echo '--- glibc ---'; ldd --version 2>&1 | head -2",
    # Driver version bounds the CUDA toolkit that can run here, and the compute
    # capability bounds what a build must target (sm_90 Hopper, sm_120 Blackwell, ...).
    "gpu": "nvidia-smi --query-gpu=name,driver_version,compute_cap --format=csv 2>&1 | head -12",
    "cuda-compilers": "source /etc/profile >/dev/null 2>&1; module -t spider cuda 2>&1",
    # My own queue — the only way to see a job NADOC did not submit.
    "squeue-mine": "squeue -u $USER -o '%i|%P|%j|%T|%M|%L|%R' 2>&1",
    "job": "scontrol show job {arg} 2>&1",
    "sinfo": "sinfo -o '%P|%D|%T|%G' 2>&1",
}


def probe_command(name: str, arg: str | None = None) -> str:
    """Resolve a named read-only probe to its shell command.

    Raises ``ValueError`` for an unknown probe or a malformed argument.  ``{arg}``
    placeholders are filled only from a strictly-validated token.
    """
    template = _PROBES.get(name)
    if template is None:
        raise ValueError(
            f"unknown probe {name!r}; expected one of {', '.join(sorted(_PROBES))}"
        )
    if "{arg}" not in template:
        return template
    token = (arg or "").strip()
    if not _ARG_OK.match(token):
        raise ValueError(
            f"probe {name!r} needs an argument matching [A-Za-z0-9_.+/-]{{1,64}}"
        )
    return template.format(arg=token)


def build_test_only_cmd(
    partition: str,
    *,
    gres: str,
    gpus: int,
    cores: int,
    mem_gb: int,
    walltime: str,
    qos: str,
) -> str:
    """The read-only ``sbatch --test-only`` probe for one partition.

    ``--test-only`` makes SLURM validate the request and report when it *would*
    start, without ever queuing anything; ``--wrap='true'`` supplies a trivial
    payload so no script file has to be staged.
    """
    gres_flag = f"gpu:{gres}:{gpus}" if gres else f"gpu:{gpus}"
    return (
        f"sbatch --test-only --partition={partition} --qos={qos} --nodes=1 "
        f"--ntasks={cores} --gres={gres_flag} --time={walltime} --mem={mem_gb}GB "
        f"--wrap='true'"
    )


# ── Live probe ────────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, dict]] = {}


def _cache_key(profile_name: str, job_shape: dict | None, history_days: int) -> str:
    shape = (
        "generic"
        if not job_shape
        else f"{job_shape.get('n_atoms')}:{job_shape.get('total_ns')}"
    )
    return f"{profile_name}|{shape}|{history_days}"


def clear_cache() -> None:
    """Drop the probe cache (tests, and the 'Re-check' button's force path)."""
    _cache.clear()


async def probe_availability(
    conn,
    profile: ClusterProfile,
    *,
    job_shape: dict | None = None,
    throughput_for=None,
    history_days: int = 30,
    now: datetime | None = None,
    force: bool = False,
) -> dict:
    """Query the cluster for live GPU availability + wait estimates.

    Read-only: ``scontrol show node``, ``squeue``, ``sacct``, and ``sbatch
    --test-only``.  Nothing is submitted and nothing on the cluster changes.

    Commands run **sequentially** — ``ClusterConnection`` serializes on a single
    lock, and asyncssh ops must stay on the uvicorn loop the connection is bound to
    (see ``backend/api/main.py`` supervisor note).  Results are cached for
    ``CACHE_TTL_S`` so an auto-refreshing popup cannot hammer a shared login node.
    """
    key = _cache_key(profile.name, job_shape, history_days)
    if not force:
        hit = _cache.get(key)
        if hit and (time.monotonic() - hit[0]) < CACHE_TTL_S:
            cached = dict(hit[1])
            cached["cached"] = True
            return cached

    now = now or datetime.now()
    gpu_parts = [p.name for p in profile.partitions if p.kind == "gpu"]
    part_list = ",".join(gpu_parts)
    warnings: list[str] = []

    async def _run(cmd: str) -> tuple[int, str, str]:
        try:
            res = await conn.run(cmd, timeout=_CMD_TIMEOUT_S)
            return res.rc, res.stdout or "", res.stderr or ""
        except asyncio.TimeoutError:
            warnings.append(f"timed out: {cmd.split()[0]}")
            return 124, "", "timeout"
        except Exception as exc:  # noqa: BLE001 — one flaky probe must not kill the view
            logger.warning(
                "availability probe command failed: %s (%s)", cmd.split()[0], exc
            )
            warnings.append(f"failed: {cmd.split()[0]}")
            return 1, "", str(exc)

    # 1. Occupancy.  `scontrol -o show node` is flat Key=Value per node — far more
    #    robust than sinfo's fixed-width -O columns, which truncate long GRES strings.
    _, nodes_out, _ = await _run("scontrol -o show node")
    nodes = parse_scontrol_nodes(nodes_out)
    node_rows = aggregate_nodes_by_partition(nodes, gpu_parts)

    # 2. Pending demand + SLURM's predicted starts for queued work.
    _, squeue_out, _ = await _run(
        f"squeue -h -p {part_list} -t PD -o '%P|%i|%b|%r|%V|%S|%u'"
    )
    pending = parse_squeue_pending(squeue_out)

    # 3. Recent history.  `-a` (all users) gives a far better sample but many sites
    #    restrict it; fall back to the caller's own jobs and label the scope so the
    #    UI never presents one as the other.
    sacct_fmt = "-X -P -n -o Partition,Submit,Start,State"
    since = f"now-{max(1, int(history_days))}days"
    rc, sacct_out, _ = await _run(f"sacct -a {sacct_fmt} -S {since} -r {part_list}")
    history_scope = "cluster-wide"
    if rc != 0 or not sacct_out.strip():
        rc, sacct_out, _ = await _run(f"sacct {sacct_fmt} -S {since} -r {part_list}")
        history_scope = "your jobs only"
    history = parse_sacct_waits(sacct_out)

    # 4. SLURM's prediction for THIS job shape, one --test-only per partition.
    slurm_starts: dict[str, datetime | None] = {}
    if job_shape:
        for name in gpu_parts:
            part = profile.partition(name)
            if part is None:
                continue
            qos_options = [q.name for q in profile.qos_tiers_for_partition(name)]
            qos = job_shape.get("qos") if job_shape.get("qos") in qos_options else None
            qos = qos or (qos_options[0] if qos_options else "gpu-normal")
            cmd = build_test_only_cmd(
                name,
                gres=part.gres_type,
                gpus=int(job_shape.get("gpus", 1) or 1),
                cores=int(job_shape.get("cores", 8) or 8),
                mem_gb=int(job_shape.get("mem_gb", 32) or 32),
                walltime=str(job_shape.get("walltime", "24:00:00")),
                qos=qos,
            )
            _, out, err = await _run(cmd)
            slurm_starts[name] = parse_test_only(f"{err}\n{out}")

    rows = summarize_availability(
        profile,
        node_rows=node_rows,
        pending=pending,
        history=history,
        slurm_starts=slurm_starts,
        job_shape=job_shape,
        throughput_for=throughput_for,
        now=now,
        history_scope=history_scope,
    )
    # Profile drift: a configured partition the cluster does not report will fail at
    # sbatch time with an opaque error.  Say so here instead.
    live_partitions = observed_partitions(nodes)
    if live_partitions:
        missing = [p.name for p in profile.partitions if p.name not in live_partitions]
        if missing:
            warnings.append(
                f"profile partitions not present on {profile.name}: {', '.join(missing)}"
            )

    result = {
        "cluster": profile.name,
        "checked_at": now.isoformat(timespec="seconds"),
        "history_days": history_days,
        "history_scope": history_scope,
        "job_shape": job_shape,
        "partitions": rows,
        "observed_partitions": live_partitions,
        "observed_gres": {p: observed_gres(nodes, p) for p in gpu_parts},
        "warnings": warnings,
        "cached": False,
    }
    _cache[key] = (time.monotonic(), result)
    return result
