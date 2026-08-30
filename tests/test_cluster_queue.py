"""Unit tests for backend/core/cluster_queue.py — pure parsers, offline.

Fixture text mirrors real SLURM output shapes (``scontrol -o show node`` flat
key=value lines, pipe-delimited ``squeue``/``sacct``).  Nothing here touches SSH.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.core import cluster_config as cc
from backend.core import cluster_queue as cq


# ── fixtures ──────────────────────────────────────────────────────────────────

# Two ah200 nodes (4 H200 each): one idle, one with 1 of 4 GPUs allocated.
# One aa100 node fully allocated, one aa100 node drained (must not count).
SCONTROL_OUT = """\
NodeName=c3gpu-c2-u17 Arch=x86_64 CoresPerSocket=64 CPUAlloc=0 CPUTot=128 \
Gres=gpu:h200:4(S:0-1) Partitions=ah200 State=IDLE ThreadsPerCore=1 \
CfgTRES=cpu=128,mem=1546000M,billing=1616,gres/gpu=4 AllocTRES= CapWatts=n/a
NodeName=c3gpu-c2-u18 Arch=x86_64 CoresPerSocket=64 CPUAlloc=32 CPUTot=128 \
Gres=gpu:h200:4(S:0-1) Partitions=ah200 State=MIXED ThreadsPerCore=1 \
CfgTRES=cpu=128,mem=1546000M,billing=1616,gres/gpu=4 AllocTRES=cpu=32,mem=128G,gres/gpu=1
NodeName=c3gpu-c2-u19 Arch=x86_64 CoresPerSocket=64 CPUAlloc=0 CPUTot=128 \
Gres=gpu:h200:2(S:0-1),gpu:h200_3g.71gb:6(S:0-1) Partitions=ah200 State=IDLE ThreadsPerCore=1 \
CfgTRES=cpu=128,mem=1546000M,billing=1616,gres/gpu=8 AllocTRES= CapWatts=n/a
NodeName=c3gpu-a1-u1 Arch=x86_64 CoresPerSocket=32 CPUAlloc=64 CPUTot=64 \
Gres=gpu:a100-40gb:3(S:0-1) Partitions=aa100 State=ALLOCATED ThreadsPerCore=1 \
CfgTRES=cpu=64,mem=243000M,billing=392,gres/gpu=3 AllocTRES=cpu=64,mem=200G,gres/gpu=3
NodeName=c3gpu-a1-u2 Arch=x86_64 CoresPerSocket=32 CPUAlloc=0 CPUTot=64 \
Gres=gpu:a100-40gb:3(S:0-1) Partitions=aa100 State=IDLE+DRAIN ThreadsPerCore=1 \
CfgTRES=cpu=64,mem=243000M,billing=392,gres/gpu=3 AllocTRES= CapWatts=n/a
NodeName=c3cpu-c11-u1 Arch=x86_64 CPUAlloc=64 CPUTot=64 Gres=(null) \
Partitions=acpu,dtn State=ALLOCATED CfgTRES=cpu=64,mem=239400M,billing=64 AllocTRES=cpu=64
"""

SQUEUE_PENDING_OUT = """\
ah200|4210001|gres:gpu:h200:1|Priority|2026-08-06T09:12:00|2026-08-06T18:00:00|alice
ah200|4210002|gres:gpu:h200:2|Resources|2026-08-06T09:40:00|Unknown|bob
aa100|4210003|gres:gpu:a100-40gb:1|Priority|2026-08-06T08:00:00|2026-08-06T12:30:00|carol
aa100|4210004|gres:gpu:a100-40gb:1|QOSMaxGRESPerUser|2026-08-06T08:05:00|N/A|carol
"""

SACCT_OUT = """\
ah200|2026-08-01T10:00:00|2026-08-01T10:30:00|COMPLETED
ah200|2026-08-02T10:00:00|2026-08-02T11:00:00|COMPLETED
ah200|2026-08-03T10:00:00|2026-08-03T12:00:00|COMPLETED
ah200|2026-08-04T10:00:00|2026-08-04T14:00:00|FAILED
aa100|2026-08-01T10:00:00|2026-08-01T18:00:00|COMPLETED
aa100|2026-08-02T10:00:00|Unknown|CANCELLED
"""

RESERVATIONS_OUT = """\
ReservationName=alpine-maint StartTime=2026-08-31T06:00:00 EndTime=2026-09-03T06:30:00 Duration=3-00:30:00 Nodes=ALL NodeCnt=480 Flags=MAINT,ALL_NODES State=INACTIVE
ReservationName=classroom StartTime=2026-08-07T08:00:00 EndTime=2026-08-07T12:00:00 Duration=04:00:00 Nodes=c3gpu-c2-u17 NodeCnt=1 Flags=SPEC_NODES State=INACTIVE
ReservationName=old-maint StartTime=2026-08-01T00:00:00 EndTime=2026-08-02T00:00:00 Duration=1-00:00:00 Nodes=ALL NodeCnt=480 Flags=MAINT,ALL_NODES State=INACTIVE
"""


@pytest.fixture
def alpine():
    return cc.alpine_profile()


NOW = datetime(2026, 8, 6, 12, 0, 0)


# ── parse_scontrol_nodes ──────────────────────────────────────────────────────


def test_parse_scontrol_nodes_reads_gpu_occupancy():
    nodes = cq.parse_scontrol_nodes(SCONTROL_OUT)
    assert len(nodes) == 6
    by_name = {n["node"]: n for n in nodes}

    idle = by_name["c3gpu-c2-u17"]
    assert idle["partitions"] == ["ah200"]
    assert idle["gpus_total"] == 4
    assert idle["gpus_alloc"] == 0
    assert idle["gpu_model"] == "h200"

    mixed = by_name["c3gpu-c2-u18"]
    assert mixed["gpus_total"] == 4
    assert mixed["gpus_alloc"] == 1
    assert mixed["cpus_alloc"] == 32 and mixed["cpus_total"] == 128


def test_parse_scontrol_nodes_handles_cpu_only_and_multi_partition():
    nodes = {n["node"]: n for n in cq.parse_scontrol_nodes(SCONTROL_OUT)}
    cpu = nodes["c3cpu-c11-u1"]
    assert cpu["gpus_total"] == 0
    assert cpu["gpus_alloc"] == 0
    assert cpu["partitions"] == ["acpu", "dtn"]


def test_parse_scontrol_nodes_ignores_noise():
    assert cq.parse_scontrol_nodes("") == []
    assert cq.parse_scontrol_nodes("some banner\nNodeName=\n") == []


def test_mig_slices_are_not_counted_as_whole_gpus():
    """Live 2026-08-06: 8 four-GPU H200 nodes reported 56 "GPUs" because MIG slices
    were summed in.  NADOC asks for `--gres=gpu:h200:1` — a whole card — so a free
    MIG slice is capacity a NAMD job can never get."""
    node = {n["node"]: n for n in cq.parse_scontrol_nodes(SCONTROL_OUT)}["c3gpu-c2-u19"]
    assert node["gpus_total"] == 2  # whole H200s
    assert node["mig_total"] == 6  # 6 x h200_3g.71gb slices, counted apart
    assert node["gpu_model"] == "h200"  # the model name, not the slice profile


def test_is_mig_type_recognises_every_alpine_slice_profile():
    for mig in (
        "h200_3g.71gb",
        "h200_2g.35gb",
        "a100_3g.20gb",
        "rtx_pro_6000_2g.48gb",
        "rtx_pro_6000_1g.24gb",
    ):
        assert cq.is_mig_type(mig), mig
    for whole in ("h200", "a100-40gb", "a100_80gb", "mi100", "l40", "rtx_pro_6000"):
        assert not cq.is_mig_type(whole), whole


def test_gres_by_type_splits_a_mixed_node():
    assert cq.gres_by_type("gpu:h200:2(S:0-1),gpu:h200_3g.71gb:6(S:0-1)") == {
        "h200": 2,
        "h200_3g.71gb": 6,
    }
    assert cq.gres_by_type("(null)") == {}


def test_untyped_alloc_charges_whole_cards_first():
    """With an untyped AllocTRES we cannot tell which card was taken; charging the
    whole cards first under-reports free capacity, which is the safe direction."""
    line = (
        "NodeName=n1 CPUTot=128 CPUAlloc=0 Gres=gpu:h200:2,gpu:h200_2g.35gb:4 "
        "Partitions=ah200 State=MIXED CfgTRES=cpu=128,gres/gpu=6 AllocTRES=cpu=8,gres/gpu=3"
    )
    node = cq.parse_scontrol_nodes(line)[0]
    assert node["gpus_total"] == 2 and node["gpus_alloc"] == 2  # both whole cards
    assert node["mig_total"] == 4 and node["mig_alloc"] == 1


def test_typed_alloc_is_used_when_slurm_provides_it():
    line = (
        "NodeName=n1 CPUTot=128 CPUAlloc=0 Gres=gpu:h200:2,gpu:h200_2g.35gb:4 "
        "Partitions=ah200 State=MIXED CfgTRES=cpu=128,gres/gpu=6 "
        "AllocTRES=cpu=8,gres/gpu=3,gres/gpu:h200=1,gres/gpu:h200_2g.35gb=2"
    )
    node = cq.parse_scontrol_nodes(line)[0]
    assert node["gpus_alloc"] == 1
    assert node["mig_alloc"] == 2


def test_observed_partitions_and_gres_report_ground_truth():
    nodes = cq.parse_scontrol_nodes(SCONTROL_OUT)
    assert cq.observed_partitions(nodes) == ["aa100", "acpu", "ah200", "dtn"]
    gres = cq.observed_gres(nodes, "ah200")
    assert any("h200_3g.71gb" in g for g in gres)


def test_gpu_count_from_typed_tres():
    # Some sites emit only the typed key; the count must still be found.
    assert cq._gpu_count_from_tres("cpu=128,gres/gpu:h200=4") == 4
    # When both forms are present the plain key is the total and wins.
    assert cq._gpu_count_from_tres("gres/gpu=4,gres/gpu:h200=4") == 4
    assert cq._gpu_count_from_tres("cpu=64,mem=200G") == 0


# ── aggregate_nodes_by_partition ──────────────────────────────────────────────


def test_aggregate_counts_free_gpus_per_partition():
    nodes = cq.parse_scontrol_nodes(SCONTROL_OUT)
    rows = cq.aggregate_nodes_by_partition(nodes, ["ah200", "aa100"])

    ah200 = rows["ah200"]
    assert ah200["nodes_total"] == 3
    assert ah200["nodes_idle"] == 2 and ah200["nodes_mixed"] == 1
    assert ah200["gpus_total"] == 10  # 4 + 4 + 2 whole cards (not the 6 MIG slices)
    assert ah200["gpus_alloc"] == 1
    assert ah200["gpus_free"] == 9
    assert ah200["mig_total"] == 6 and ah200["mig_free"] == 6
    assert ah200["gpu_free_by_type"] == {"h200": 9, "h200_3g.71gb": 6}


def test_summary_exposes_each_mig_profile_as_a_schedulable_resource(alpine):
    rows = {r["partition"]: r for r in _summary(alpine)}
    choices = {
        c["gres_type"]: c for c in rows["ah200"]["gpu_resources"]
    }
    assert choices["h200"]["gpus_free"] == 9
    assert choices["h200_3g.71gb"]["gpus_free"] == 6
    assert choices["h200_3g.71gb"]["mig"] is True
    assert choices["h200_3g.71gb"]["vram_gb"] == 71


def test_aggregate_excludes_drained_node_capacity():
    """A drained node's GPUs cannot be scheduled — advertising them is a lie."""
    nodes = cq.parse_scontrol_nodes(SCONTROL_OUT)
    rows = cq.aggregate_nodes_by_partition(nodes, ["aa100"])
    aa100 = rows["aa100"]
    assert aa100["nodes_total"] == 2
    assert aa100["nodes_down"] == 1  # the IDLE+DRAIN one
    assert aa100["gpus_total"] == 3  # only the healthy node's 3 GPUs
    assert aa100["gpus_free"] == 0  # and those 3 are all allocated


def test_aggregate_returns_zero_row_for_unknown_partition():
    rows = cq.aggregate_nodes_by_partition([], ["ah200"])
    assert rows["ah200"]["gpus_free"] == 0
    assert rows["ah200"]["nodes_total"] == 0


# ── parse_squeue_pending ──────────────────────────────────────────────────────


def test_parse_squeue_pending_counts_jobs_gpus_and_reasons():
    pending = cq.parse_squeue_pending(SQUEUE_PENDING_OUT)
    assert pending["ah200"]["pending_jobs"] == 2
    assert pending["ah200"]["pending_gpus"] == 3  # 1 + 2
    assert pending["ah200"]["reasons"] == {"Priority": 1, "Resources": 1}
    assert pending["aa100"]["reasons"]["QOSMaxGRESPerUser"] == 1


def test_parse_squeue_pending_keeps_earliest_known_start():
    pending = cq.parse_squeue_pending(SQUEUE_PENDING_OUT)
    assert pending["ah200"]["earliest_start"] == datetime(2026, 8, 6, 18, 0, 0)
    # "Unknown"/"N/A" must not be read as a start time.
    assert pending["aa100"]["earliest_start"] == datetime(2026, 8, 6, 12, 30, 0)


def test_parse_squeue_pending_ignores_malformed_rows():
    assert cq.parse_squeue_pending("") == {}
    assert cq.parse_squeue_pending("garbage without pipes\n") == {}


def test_parse_maintenance_reservations_is_explicit_and_drops_expired():
    reservations = cq.parse_maintenance_reservations(RESERVATIONS_OUT, now=NOW)
    assert reservations == [
        {
            "name": "alpine-maint",
            "start": "2026-08-31T06:00:00",
            "end": "2026-09-03T06:30:00",
            "active": False,
            "state": "INACTIVE",
            "node_count": 480,
            "all_nodes": True,
        }
    ]


def test_parse_maintenance_reservations_marks_active_window():
    now = datetime(2026, 9, 1, 12, 0, 0)
    assert cq.parse_maintenance_reservations(RESERVATIONS_OUT, now=now)[0]["active"] is True


# ── parse_sacct_waits ─────────────────────────────────────────────────────────


def test_parse_sacct_waits_medians_only_started_jobs():
    hist = cq.parse_sacct_waits(SACCT_OUT)
    # ah200 waits: 30, 60, 120, 240 min → nearest-rank median = 120
    assert hist["ah200"]["n_samples"] == 4
    assert hist["ah200"]["median_wait_min"] == pytest.approx(120.0)


def test_parse_sacct_waits_suppresses_thin_samples():
    """One data point is not a median — report the count, not a fake number."""
    hist = cq.parse_sacct_waits(SACCT_OUT)
    assert hist["aa100"]["n_samples"] == 1  # the CANCELLED row has no Start
    assert hist["aa100"]["median_wait_min"] is None


# ── parse_test_only ───────────────────────────────────────────────────────────


def test_parse_test_only_reads_predicted_start():
    err = (
        "sbatch: Job 4210999 to start at 2026-08-06T18:22:11 using 8 processors "
        "on nodes c3gpu-c2-u18 in partition ah200"
    )
    assert cq.parse_test_only(err) == datetime(2026, 8, 6, 18, 22, 11)


def test_parse_test_only_none_when_slurm_cannot_place():
    assert cq.parse_test_only("sbatch: error: Batch job submission failed") is None
    assert cq.parse_test_only("") is None


def test_build_test_only_cmd_never_submits():
    cmd = cq.build_test_only_cmd(
        "ah200",
        gres="h200",
        gpus=1,
        cores=8,
        mem_gb=32,
        walltime="24:00:00",
        qos="gpu-normal",
    )
    assert "--test-only" in cmd
    assert "--gres=gpu:h200:1" in cmd
    assert "--partition=ah200" in cmd and "--qos=gpu-normal" in cmd


# ── summarize_availability ────────────────────────────────────────────────────


def _summary(alpine, **over):
    nodes = cq.parse_scontrol_nodes(SCONTROL_OUT)
    gpu_parts = [p.name for p in alpine.partitions if p.kind == "gpu"]
    kwargs = {
        "node_rows": cq.aggregate_nodes_by_partition(nodes, gpu_parts),
        "pending": cq.parse_squeue_pending(SQUEUE_PENDING_OUT),
        "history": cq.parse_sacct_waits(SACCT_OUT),
        "now": NOW,
        "history_scope": "cluster-wide",
    }
    kwargs.update(over)
    return cq.summarize_availability(alpine, **kwargs)


def test_summary_covers_every_gpu_partition_plus_gh200(alpine):
    rows = _summary(alpine)
    names = {r["partition"] for r in rows}
    assert {"aa100", "ami100", "al40", "ah200", "artxpro6000"} <= names
    gh = next(r for r in rows if r["partition"] == "gh200")
    assert gh["request_only"] is True


def test_free_gpus_with_a_hardware_blocked_job_ahead_do_not_start_now(alpine):
    """ah200's fixture queue contains a job pending on `Resources` — i.e. genuinely
    waiting for hardware — so the free GPUs are already spoken for."""
    rows = {r["partition"]: r for r in _summary(alpine)}
    ah200 = rows["ah200"]
    assert ah200["gpus_free"] == 9
    assert ah200["blocked_on_hardware"] == 1
    assert ah200["wait_basis"] != "free now"


def test_policy_blocked_queue_does_not_mask_free_gpus(alpine):
    """The bug found live 2026-08-06: gating on TOTAL pending was too strict.  A job
    held by its owner's QoS cap (or by Priority) is blocked by policy, not by a GPU
    shortage, and must not make an idle partition look busy."""
    rows = {
        r["partition"]: r
        for r in _summary(
            alpine,
            pending={
                "ah200": {
                    "pending_jobs": 30,
                    "pending_gpus": 30,
                    "blocked_on_hardware": 0,
                    "reasons": {"QOSMaxGRESPerUser": 30},
                    "earliest_start": None,
                },
            },
        )
    }
    ah200 = rows["ah200"]
    assert ah200["pending_gpus"] == 30
    assert ah200["wait_basis"] == "free now"


def test_starts_now_when_free_and_no_backlog(alpine):
    rows = {r["partition"]: r for r in _summary(alpine, pending={})}
    ah200 = rows["ah200"]
    assert ah200["wait_min"] == 0.0
    assert ah200["wait_basis"] == "free now"
    assert ah200["wait_label"] == "~0 min"


def test_another_users_pending_start_is_never_used_as_our_wait(alpine):
    """Found live 2026-08-06: artxpro6000 reported a 13 h 39 m "SLURM estimate" that
    was really a stranger's queued job's start time, while 39 GPUs sat idle.  Only
    `sbatch --test-only` for OUR shape may drive the SLURM signal."""
    rows = {
        r["partition"]: r
        for r in _summary(
            alpine,
            pending={
                "al40": {
                    "pending_jobs": 1,
                    "pending_gpus": 1,
                    "blocked_on_hardware": 1,
                    "reasons": {"Resources": 1},
                    "earliest_start": datetime(2026, 8, 7, 2, 0, 0),
                },  # 14 h away
            },
            history={},
        )
    }
    al40 = rows["al40"]
    assert al40["wait_basis"] != "SLURM backfill estimate"
    assert al40["slurm_start"] is None


def test_slurm_estimate_beats_history(alpine):
    rows = {
        r["partition"]: r
        for r in _summary(
            alpine,
            slurm_starts={"ah200": datetime(2026, 8, 6, 14, 0, 0)},
        )
    }
    ah200 = rows["ah200"]
    assert ah200["wait_min"] == pytest.approx(120.0)  # 12:00 → 14:00
    assert ah200["wait_basis"] == "SLURM backfill estimate"


def test_future_slurm_start_beats_physically_free_gpus(alpine):
    """Idle MIGs are not 'ready' when the requested walltime overlaps maintenance."""
    rows = {
        r["partition"]: r
        for r in _summary(
            alpine,
            pending={},
            slurm_starts={
                "ah200": datetime(2026, 9, 3, 6, 30, 0),
                "ah200|h200_3g.71gb": datetime(2026, 9, 3, 6, 30, 0),
            },
        )
    }
    ah200 = rows["ah200"]
    assert ah200["gpus_free"] == 9
    assert ah200["wait_basis"] == "SLURM backfill estimate"
    assert ah200["wait_min"] > 0
    mig = next(g for g in ah200["gpu_resources"] if g["gres_type"] == "h200_3g.71gb")
    assert mig["wait_basis"] == "SLURM backfill estimate"
    assert mig["slurm_start"] == "2026-09-03T06:30:00"


def test_unknown_wait_stays_unknown_not_zero(alpine):
    """No free GPUs, no SLURM estimate, no history → must not claim 'now'."""
    rows = {
        r["partition"]: r
        for r in _summary(
            alpine,
            history={},
            pending={
                "artxpro6000": {
                    "pending_jobs": 5,
                    "pending_gpus": 5,
                    "reasons": {},
                    "earliest_start": None,
                },
            },
        )
    }
    row = rows["artxpro6000"]
    assert row["wait_min"] is None
    assert row["wait_label"] == "unknown"


def test_history_used_when_no_live_signal(alpine):
    """Genuinely full (jobs pending on Resources) and no --test-only answer → the
    only signal left is what recent jobs actually waited."""
    rows = {
        r["partition"]: r
        for r in _summary(
            alpine,
            pending={
                "ah200": {
                    "pending_jobs": 9,
                    "pending_gpus": 99,
                    "blocked_on_hardware": 9,
                    "reasons": {"Resources": 9},
                    "earliest_start": None,
                },
            },
        )
    }
    ah200 = rows["ah200"]
    assert ah200["wait_min"] == pytest.approx(120.0)
    assert "median of 4 recent jobs (cluster-wide)" == ah200["wait_basis"]


def test_top_reason_is_the_commonest(alpine):
    rows = {r["partition"]: r for r in _summary(alpine)}
    assert rows["aa100"]["top_reason"] in {"Priority (1)", "QOSMaxGRESPerUser (1)"}


def test_job_shape_projects_cost_and_time_per_partition(alpine):
    """The same job must be costed and timed against EACH partition's own GPU."""
    shape = {
        "n_atoms": 180_000,
        "total_ns": 100.0,
        "gpus": 1,
        "cores": 8,
        "mem_gb": 32,
        "walltime": "24:00:00",
        "qos": "gpu-normal",
    }
    rows = {r["partition"]: r for r in _summary(alpine, job_shape=shape)}
    ah200, aa100 = rows["ah200"], rows["aa100"]

    # H200 is modelled ~2.5x an A100 → more ns/day, less walltime.
    assert ah200["job_ns_per_day"] > aa100["job_ns_per_day"]
    assert ah200["job_walltime_h"] < aa100["job_walltime_h"]
    # ...but it bills far more per GPU-hour, so it is not automatically cheaper.
    assert ah200["su_per_gpu_hour"] > aa100["su_per_gpu_hour"]


def test_rows_sort_by_time_to_result_not_by_wait(alpine):
    """A faster GPU that starts later can still finish first — that must win."""
    shape = {
        "n_atoms": 180_000,
        "total_ns": 100.0,
        "gpus": 1,
        "cores": 8,
        "mem_gb": 32,
        "walltime": "24:00:00",
        "qos": "gpu-normal",
    }
    rows = _summary(
        alpine,
        job_shape=shape,
        slurm_starts={
            "ah200": datetime(2026, 8, 6, 14, 0, 0),  # waits 2 h, then runs fast
            "aa100": datetime(2026, 8, 6, 12, 0, 0),  # starts now, but slow
        },
        pending={},
        history={},
    )
    ordered = [r["partition"] for r in rows if r.get("time_to_result_h") is not None]
    assert ordered.index("ah200") < ordered.index("aa100")
    # request-only hardware always sorts last
    assert rows[-1]["partition"] == "gh200"


def test_fmt_minutes_reads_naturally():
    assert cq._fmt_minutes(0) == "~0 min"
    assert cq._fmt_minutes(45) == "~45 min"
    assert cq._fmt_minutes(200) == "~3 h 20 m"
    assert cq._fmt_minutes(2880) == "~2 d"
    assert cq._fmt_minutes(None) is None


# ── read-only probe registry ─────────────────────────────────────────────────


def test_probe_registry_is_named_not_freeform():
    """No caller string may become a command — unknown names are rejected outright."""
    with pytest.raises(ValueError, match="unknown probe"):
        cq.probe_command("rm -rf /")
    with pytest.raises(ValueError, match="unknown probe"):
        cq.probe_command("")
    assert cq.probe_command("reservations") == "scontrol -o show reservation 2>&1"


def test_probe_argument_is_strictly_validated():
    # A shell metacharacter must never survive into the command.
    for bad in ("cuda; rm -rf /", "$(whoami)", "a b", "`id`", "x" * 80, ""):
        with pytest.raises(ValueError, match="needs an argument"):
            cq.probe_command("modules", bad)


def test_probe_argument_is_interpolated_when_valid():
    assert "spider cuda" in cq.probe_command("modules", "cuda")
    assert "scontrol show job 30948828" in cq.probe_command("job", "30948828")
    # Module names carry a slash; it has no shell meaning, so it is allowed.
    assert "spider namd/3.0.1_cpu" in cq.probe_command("modules", "namd/3.0.1_cpu")


def test_argless_probes_ignore_a_supplied_argument():
    assert cq.probe_command("os") == cq.probe_command("os", "ignored")


def test_storage_probe_uses_curc_read_only_quota_report():
    assert cq.probe_command("storage") == "curc-quota 2>&1"


def test_every_probe_is_read_only():
    """Guard the registry itself: a future probe must not mutate cluster state."""
    import re as _re

    # Word-bounded: `ldd --version` must not trip a naive "dd " substring check.
    forbidden = (
        "rm",
        "sbatch",
        "scancel",
        "mv",
        "cp",
        "chmod",
        "chown",
        "mkdir",
        "touch",
        "dd",
        "kill",
        "tee",
        "sed",
    )
    for name, tmpl in cq._PROBES.items():
        for bad in forbidden:
            assert not _re.search(rf"(?<![\w/.-]){bad}\b", tmpl), (
                f"probe {name} looks mutating: {bad!r} in {tmpl!r}"
            )
        assert ">" not in tmpl.replace("2>&1", "").replace(">/dev/null", ""), (
            f"probe {name} redirects output somewhere"
        )
