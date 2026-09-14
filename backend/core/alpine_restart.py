"""Reconcile Alpine execution generations without conflating sampling trajectories."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import shlex
import shutil
import time
import os
import tempfile

from backend.core.md_job import MdJob, MdStatus

logger = logging.getLogger(__name__)


def scheduler_evidence(text):
    fields = dict(re.findall(r"(\w+)=([^\s]+)", text))
    try:
        count = int(fields["Restarts"])
    except (KeyError, ValueError):
        return None
    return dict(
        slurm_job_id=fields.get("JobId"),
        restart_count=count,
        start_time=fields.get("StartTime"),
        state=fields.get("JobState"),
    )


def record_events(job, journal, scheduler):
    """Deduplicate by allocation/generation, retaining acknowledgments across polls."""
    existing = {e["id"]: e for e in job.restart_events}
    attempts = journal.get("attempts", []) if isinstance(journal, dict) else []
    changed = False
    for attempt in attempts:
        if not isinstance(attempt, dict) or not attempt.get("id"):
            continue
        if not attempt.get("restart_count") and not any(
            s.get("mode") in ("continued", "blocked")
            for s in attempt.get("segments", [])
        ):
            continue
        eid = "%s-r%s" % (attempt.get("slurm_job_id"), attempt.get("restart_count", 0))
        segments = [
            s
            for s in attempt.get("segments", [])
            if s.get("mode") in ("continued", "blocked")
        ]
        mode = (
            "blocked"
            if any(s.get("mode") == "blocked" for s in segments)
            else "continued"
            if any(s.get("mode") == "continued" for s in segments)
            else "checking"
        )
        update = dict(
            id=eid,
            mode=mode,
            slurm_job_id=attempt.get("slurm_job_id"),
            restart_count=attempt.get("restart_count", 0),
            started_at=attempt.get("started_at"),
            segments=segments,
            attempt_id=attempt["id"],
        )
        event = existing.get(eid)
        if event is None:
            event = dict(detected_at=time.time(), acknowledged_at=None)
            job.restart_events.append(event)
            existing[eid] = event
        if any(event.get(k) != v for k, v in update.items()):
            # New material evidence needs a new acknowledgment, even when the user
            # already acknowledged the initial "checking" incident.
            event.update(
                update, acknowledged_at=None, revision=event.get("revision", 0) + 1
            )
            changed = True
    if scheduler and scheduler["restart_count"] > 0:
        eid = "%s-r%d" % (scheduler["slurm_job_id"], scheduler["restart_count"])
        if eid not in existing:
            suspect = next(
                (
                    e
                    for e in job.restart_events
                    if e.get("source") == "progress_regression"
                    and e.get("slurm_job_id") == scheduler["slurm_job_id"]
                ),
                None,
            )
            if suspect:
                suspect.update(
                    id=eid,
                    scheduler=scheduler,
                    restart_count=scheduler["restart_count"],
                    revision=suspect.get("revision", 1) + 1,
                    acknowledged_at=None,
                )
                changed = True
                existing[eid] = suspect
        if eid not in existing:
            event = dict(
                id=eid,
                mode="unknown",
                detected_at=time.time(),
                acknowledged_at=None,
                revision=1,
                scheduler=scheduler,
                slurm_job_id=scheduler["slurm_job_id"],
                restart_count=scheduler["restart_count"],
                segments=[],
            )
            job.restart_events.append(event)
            changed = True
    if scheduler and scheduler != job.alpine_execution:
        job.alpine_execution = scheduler
        changed = True
    return changed


def snapshot_job(job, event, evidence, workspace):
    """Create a terminal linked entry owning only its preserved result directory."""
    sid = hashlib.sha256((job.job_id + ":" + event["id"]).encode()).hexdigest()[:12]
    if (workspace / "md_jobs" / sid / "job.json").exists():
        prior = MdJob.load(sid, workspace)
        if prior.remote_scratch_dir != evidence["remote_directory"]:
            prior.remote_scratch_dir = evidence["remote_directory"]
            prior.restart_snapshot_evidence = evidence
            for notice in prior.restart_events:
                notice["evidence"] = evidence
            prior.save(workspace)
        return sid
    prior = copy.deepcopy(job)
    prior.job_id = sid
    prior.archived = False
    prior.archive_path = None
    prior.parent_job_id = job.job_id
    prior.restart_of_job_id = job.job_id
    prior.ensemble_index = None
    prior.restart_snapshot = True
    prior.restart_events = [
        dict(event, mode="restarted", evidence=evidence, acknowledged_at=None)
    ]
    prior.alpine_execution = None
    prior.slurm_job_id = None
    prior.slurm_state = None
    prior.namd_pid = None
    prior.status = MdStatus.stopped
    prior.user_stopped = True
    prior.resumable = False
    prior.pending_scancel = False
    prior.remote_scratch_dir = evidence["remote_directory"]
    prior.remote_project_dir = None
    prior.download_status = None
    prior.live_frame = None
    prior.health_samples = []
    prior.resume_history = []
    prior.error = (
        "Interrupted by Alpine restart; preserved trajectory, no restart checkpoint."
    )
    prior.failure_kind = None
    prior.sampling_relationship = "same-seed restart; independence unverified"
    records = {r["segment"]: r for r in evidence["records"]}
    for segment in prior.segments:
        segment.status = "failed" if segment.name in records else "pending"
    if records:
        r = max(records.values(), key=lambda r: r["step"])
        prior.live_metrics = dict(
            step=r["step"], timestep_fs=r["timestep_fs"], segment=r["segment"]
        )
    prior.restart_snapshot_evidence = evidence
    destination = prior.package_dir(workspace)
    if not (destination.parent.parent / "job.json").exists():
        shutil.copytree(
            job.package_dir(workspace),
            destination,
            ignore=shutil.ignore_patterns(
                "output", "*.log", "*.out", "*.err", "recovery"
            ),
            dirs_exist_ok=True,
        )
    prior.save(workspace)
    return sid


async def observe(job, workspace, conn):
    """Read small restart evidence; protect legacy .BAK files once on discovery."""
    if not job.slurm_job_id or not job.remote_scratch_dir or job.restart_snapshot:
        return
    scratch = shlex.quote(job.remote_scratch_dir)
    result = await conn.run(
        'scontrol show job -o %s; echo "---NADOC-ATTEMPTS---"; cat %s/output/nadoc_attempts.json 2>/dev/null'
        % (shlex.quote(job.slurm_job_id), scratch)
    )
    sched_text, _, journal_text = (result.stdout or "").partition(
        "---NADOC-ATTEMPTS---"
    )
    scheduler = scheduler_evidence(sched_text)
    try:
        journal = json.loads(journal_text)
    except ValueError:
        journal = {}
    changed = record_events(job, journal, scheduler)
    for event in job.restart_events:
        if event["mode"] != "unknown" or event.get("legacy_checked"):
            continue
        from backend.core import remote_alpine_restart

        await conn.sftp_put(
            remote_alpine_restart.__file__,
            job.remote_scratch_dir + "/nadoc_restart_inspect.py",
        )
        response = await conn.run(
            "cd %s && python3 nadoc_restart_inspect.py inspect --id %s"
            % (scratch, shlex.quote("legacy-" + event["id"]))
        )
        if response.rc:
            event["inspection_error"] = (response.stderr or response.stdout)[-1000:]
            changed = True
            continue
        evidence = normalize_evidence(
            json.loads(response.stdout), job.remote_scratch_dir
        )
        if evidence.get("protected"):
            sid = await asyncio.to_thread(snapshot_job, job, event, evidence, workspace)
            event.update(
                mode="restarted",
                preserved_job_id=sid,
                evidence=evidence,
                acknowledged_at=None,
                legacy_checked=True,
                revision=event.get("revision", 0) + 1,
            )
            job.sampling_relationship = "same-seed restart; independence unverified"
        # Empty backups may be an early startup: do not permanently suppress retry.
        changed = True
    if changed:
        job.save(workspace)


def apply_acknowledgments(job, workspace):
    for event in job.restart_events:
        path = (
            job.job_dir(workspace)
            / "restart_acknowledgments"
            / ("%s-v%d.json" % (event["id"], event.get("revision", 1)))
        )
        if path.exists():
            try:
                event["acknowledged_at"] = json.loads(path.read_text())[
                    "acknowledged_at"
                ]
            except (OSError, ValueError, KeyError):
                logger.warning("Ignoring incomplete restart acknowledgment %s", path)
    return job


def acknowledge(job, events, workspace):
    known = {e["id"]: e for e in job.restart_events}
    for requested in events:
        event = known.get(requested["id"])
        if event is None or requested["revision"] != event.get("revision", 1):
            raise ValueError(
                "Restart details changed; reopen the notice before acknowledging"
            )
    folder = job.job_dir(workspace) / "restart_acknowledgments"
    folder.mkdir(exist_ok=True)
    for requested in events:
        event = known[requested["id"]]
        path = folder / ("%s-v%d.json" % (event["id"], event.get("revision", 1)))
        if not path.exists():
            with tempfile.TemporaryDirectory(dir=folder) as temp:
                from pathlib import Path

                draft = Path(temp) / "ack.json"
                draft.write_text(json.dumps(dict(acknowledged_at=time.time())))
                os.replace(draft, path)
    return apply_acknowledgments(job, workspace)


def owned_inventory(job, inventory):
    """A preserved attempt belongs to its own job, not two hundred-GB downloads."""
    excluded = set()
    directories = []
    for event in job.restart_events:
        if not event.get("preserved_job_id"):
            continue
        evidence = event.get("evidence", {})
        remote = evidence.get("remote_directory", "")
        prefix = (job.remote_scratch_dir or "") + "/"
        if remote.startswith(prefix):
            directories.append(remote[len(prefix) :] + "/")
        for record in evidence.get("records", []):
            excluded.update(
                "output/" + record["segment"] + suffix
                for suffix in (".dcd.BAK", ".xst.BAK")
            )
    return {
        path: size
        for path, size in inventory.items()
        if path not in excluded and not any(path.startswith(d) for d in directories)
    }


def note_progress_regression(job, old, new):
    """A regression is supporting evidence, not proof of a fresh trajectory."""
    if not getattr(job, "slurm_job_id", None) or old.get("segment") != new.get("segment"):
        return
    try:
        regressed = int(new["step"]) < int(old["step"]) and float(
            new["collected_at"]
        ) > float(old["collected_at"])
    except (KeyError, TypeError, ValueError):
        return
    if not regressed or any(
        e.get("slurm_job_id") == job.slurm_job_id for e in job.restart_events
    ):
        return
    job.restart_events.append(
        dict(
            id="progress-" + job.slurm_job_id,
            revision=1,
            mode="unknown",
            source="progress_regression",
            slurm_job_id=job.slurm_job_id,
            detected_at=time.time(),
            acknowledged_at=None,
            segments=[],
            previous_step=old["step"],
            observed_step=new["step"],
        )
    )


def normalize_evidence(evidence, scratch):
    from pathlib import PurePosixPath

    evidence = copy.deepcopy(evidence)

    def absolute(path):
        if ".." in PurePosixPath(path).parts:
            raise ValueError("unsafe preserved output path")
        return path if path.startswith("/") else scratch.rstrip("/") + "/" + path

    evidence["remote_directory"] = absolute(evidence["remote_directory"])
    for record in evidence.get("records", []):
        record["path"] = absolute(record["path"])
    return evidence
