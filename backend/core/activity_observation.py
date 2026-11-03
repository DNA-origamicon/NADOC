"""Bounded NAMD/mrDNA facts for shared decisions; no status repair or extraction.

Paths and already-loaded job models belong to the host, not a public request.
Each Evidence instance is one short-lived poll, shared across both engine families.
Preparation and remote ownership remain explicitly outside these local decisions.
"""
from dataclasses import dataclass
import fnmatch
from pathlib import Path

from backend.core.activity_assessment import (
    Assessment, mrdna_activity, namd_activity, raw_mrdna_complete,
)
from backend.core.activity_evidence_io import EvidenceUnavailable
from backend.core import simulation_runtime as runtime
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus
from backend.core.mrdna_job import MrdnaJob, MrdnaStatus
from backend.core.namd_process import is_segment_command


@dataclass(frozen=True)
class Observation:
    assessment: Assessment
    facts: dict
    reason: str | None = None


def _name(value):
    if type(value) is not str or not 0 < len(value) <= 256 or value in ('.', '..') or '/' in value or '\\' in value or '\0' in value:
        raise EvidenceUnavailable('invalid_name')
    return value


def _path(value):
    if len(str(value)) > 4096:
        raise EvidenceUnavailable('path_budget')
    return Path(value).resolve()


def _owned(job, workspace, directory, runner, evidence):
    evidence.tick()
    with runtime.use_workspace(workspace):
        if runner is not None:
            handle = runner._RUNNING.get(job.job_id)
            if handle is not None and handle.thread.is_alive():
                return True
        return runtime.is_owned(directory, opener=evidence.open_regular)


def _live(job, workspace, directory, runner, evidence, *, segment=None, package=None):
    if _owned(job, workspace, directory, runner, evidence):
        return True
    for command, cwd in evidence.processes():
        evidence.tick()
        if package is not None:
            if segment is not None and is_segment_command(command, segment):
                return True
            if b'namd' in command.lower() and cwd == package:
                return True
        elif b'arbd' in command.lower() and (str(directory).encode() in command or cwd == directory):
            return True
    if not evidence.processes_complete:
        raise EvidenceUnavailable('process_inventory_incomplete')
    return False


def _logs(evidence, package, name):
    if evidence.exists(package / f'{name}.log'):
        return True
    try:
        for entry in evidence.entries(package):
            if fnmatch.fnmatchcase(entry.name, f'{name}.resume*.log') and evidence.exists(entry.path):
                return True
    except FileNotFoundError:
        pass
    return False


def observe_namd(job, workspace, evidence):
    from backend.core import namd_runner as runner
    facts = {}
    try:
        evidence.tick()
        if type(job) is not MdJob or type(job.status) is not MdStatus:
            raise EvidenceUnavailable('invalid_job')
        _name(job.job_id)
        if job.status == MdStatus.preparing or job.execution_target != 'local':
            raise EvidenceUnavailable('separate_owner')
        facts['running'] = job.status == MdStatus.running
        if not facts['running']:
            return Observation(namd_activity(facts), facts)
        if type(job.segments) is not list or len(job.segments) > 128 or type(job.current_segment_idx) is not int:
            raise EvidenceUnavailable('segment_budget')
        _name(job.package_subdir)
        directory = _path(job.job_dir(workspace))
        if job.archived and not evidence.exists(directory / 'job.json'):
            raise EvidenceUnavailable('archive_unavailable')
        package = _path(job.package_dir(workspace))
        valid = 0 <= job.current_segment_idx < len(job.segments)
        active = job.segments[job.current_segment_idx] if valid else None
        if active is not None and type(active) is not MdSegmentStatus:
            raise EvidenceUnavailable('invalid_segment')
        name = _name(active.name) if active is not None else None
        facts['live'] = _live(job, workspace, directory, runner, evidence, segment=name, package=package)
        facts['segment_valid'] = valid
        if facts['live'] or not valid:
            return Observation(namd_activity(facts), facts)
        output = package / 'output'
        facts['outputs_complete'] = runner._segment_outputs_complete(output, name, exists=evidence.exists)
        if not facts['outputs_complete']:
            min_name = runner._reconcile_min_name(job, package / 'manifest.json', reader=evidence.json_text)
            if min_name:
                _name(min_name)
            facts['minimization_missing'] = bool(min_name and not evidence.exists(output / f'{min_name}.coor'))
            if not facts['minimization_missing']:
                step = runner._read_xsc_step(output / f'{name}.restart.xsc', reader=evidence.text)
                facts['checkpoint'] = bool(step and step > 0)
                if not facts['checkpoint']:
                    facts['log_exists'] = _logs(evidence, package, name)
        return Observation(namd_activity(facts), facts)
    except (EvidenceUnavailable, OSError, RecursionError, OverflowError) as exc:
        return Observation(namd_activity(facts), facts, str(exc) if isinstance(exc, EvidenceUnavailable) else 'unavailable')


def observe_mrdna(job, workspace, evidence):
    from backend.core import mrdna_runner as runner
    facts = {}
    try:
        evidence.tick()
        if type(job) is not MrdnaJob or type(job.status) is not MrdnaStatus:
            raise EvidenceUnavailable('invalid_job')
        _name(job.job_id)
        if job.status == MrdnaStatus.preparing:
            raise EvidenceUnavailable('separate_owner')
        directory = _path(job.job_dir(workspace))
        if job.archived and not evidence.exists(directory / 'job.json'):
            raise EvidenceUnavailable('archive_unavailable')
        facts['live'] = _live(job, workspace, directory, runner, evidence)
        if facts['live']:
            return Observation(mrdna_activity(facts), facts)
        facts['cached'] = evidence.exists(directory / 'display.json')
        if not facts['cached']:
            for value in (job.fine_steps, job.coarse_steps, job.output_period):
                if type(value) is not int or not 0 <= value < 2**63:
                    raise EvidenceUnavailable('invalid_steps')
            if job.fine_steps > 0 and (job.coarse_steps == 0 or job.output_period == 0):
                raise EvidenceUnavailable('invalid_steps')
            progress = runner._multiresolution_progress(job, workspace,
                frame_count=lambda path: runner._dcd_frame_count(path,
                    reader=lambda path: evidence.read(path, 12, prefix=True)))
            facts['raw_complete'] = raw_mrdna_complete(job.fine_steps, progress[0] if progress else None)
            facts['running'] = job.status == MrdnaStatus.running
        return Observation(mrdna_activity(facts), facts)
    except (EvidenceUnavailable, OSError, RecursionError) as exc:
        return Observation(mrdna_activity(facts), facts, str(exc) if isinstance(exc, EvidenceUnavailable) else 'unavailable')
