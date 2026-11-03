"""Read-only counterparts of local engine reconciliation, never lifecycle owners.

Native jobs and paths are host-selected. Preparation stays with its separate
owner; bounded unknowns are not permission to hide activity or mark a job stopped.
"""
import fnmatch
import json
from pathlib import Path

from backend.core import simulation_runtime as runtime
from backend.core.activity_assessment import Assessment
from backend.core.activity_observation import Observation, _name, _owned, _path
from backend.core.activity_evidence_io import EvidenceUnavailable


class OxdnaEvidence:
    """Supply finite reads to native stage/attempt interpretation helpers."""
    def __init__(self, evidence):
        self.io = evidence

    def specs(self, path):
        text = self.io.json_text(path)
        records = json.loads(text)
        if type(records) is not list or len(records) > 128:
            raise EvidenceUnavailable('spec_budget')
        for record in records:
            self.io.tick()
            if type(record) is not dict:
                raise EvidenceUnavailable('invalid_spec')
        return text

    def attempt_files(self, directory):
        try:
            paths = [Path(entry.path) for entry in self.io.entries(directory)
                     if fnmatch.fnmatchcase(entry.name, 'energy.r*.dat')]
        except FileNotFoundError:
            paths = []
        return sorted(paths, key=lambda path: path.name) + [directory / 'energy.dat']

    def exploded(self, directory):
        return self.io.size(directory / 'error_conf.dat') > 0

    def attempt_steps(self, path, every):
        from backend.core.oxdna_runner import _attempt_steps
        return _attempt_steps(path, every, reader=self.io.text, exists=self.io.exists)


def _oxdna_outputs(job, workspace, evidence):
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import OxdnaStageStatus
    if type(job.stages) is not list or len(job.stages) > 128:
        raise EvidenceUnavailable('stage_budget')
    reader = OxdnaEvidence(evidence)
    specs = runner.load_stage_specs(job.job_dir(workspace), reader=reader.specs, exists=evidence.exists)
    if not specs or len(specs) < len(job.stages):
        raise EvidenceUnavailable('missing_stage_specs')
    for index, stage in enumerate(job.stages):
        evidence.tick()
        if type(stage) is not OxdnaStageStatus or type(stage.status) is not str or len(stage.status) > 32:
            raise EvidenceUnavailable('invalid_stage')
        if stage.status == 'done':
            continue
        _name(stage.name)
        spec = specs[index]
        for value in (spec.steps, spec.print_energy_every_override or 0):
            if type(value) is not int or not 0 <= value < 2**63:
                raise EvidenceUnavailable('invalid_steps')
        directory = job.stage_dir(workspace, stage.name)
        expected = runner.expected_energy_lines(spec)
        has_conf = evidence.exists(directory / 'last_conf.dat')
        complete = has_conf and runner._stage_energy_lines(directory,
            reader=evidence.text, exists=evidence.exists) >= expected
        if not complete and job.status.value == 'stopped':
            try:
                tail = evidence.text(directory / 'oxdna.log')[-64_000:]
            except FileNotFoundError:
                tail = ''
            complete = (has_conf and 'END OF THE SIMULATION, everything went OK!' in tail
                and runner.stage_completed_steps(directory, spec, evidence=reader) >= spec.steps)
        if not complete or stage.status == 'failed':
            return False
    return True


def observe_local_engine(engine, job, workspace, evidence):
    """Native activity decision for oxDNA/LAMMPS/CanDo/SNUPI, without repair."""
    from backend.core import oxdna_runner, lammps_runner, cando_runner
    from backend.core.oxdna_job import OxdnaJob, OxdnaStatus
    from backend.core.lammps_job import LammpsJob, LammpsStatus
    from backend.core.cando_job import CandoJob, CandoStatus
    from backend.core.snupi_job import SnupiJob, SnupiStatus
    families = {
        'oxdna': (OxdnaJob, OxdnaStatus, oxdna_runner),
        'lammps': (LammpsJob, LammpsStatus, lammps_runner),
        'cando': (CandoJob, CandoStatus, cando_runner),
        'snupi': (SnupiJob, SnupiStatus, None),
    }
    facts = {}
    missing = 'job'
    try:
        evidence.tick()
        if type(engine) is not str or len(engine) > 16 or engine not in families:
            raise EvidenceUnavailable('unsupported_engine')
        model, status, runner = families[engine]
        if type(job) is not model or type(job.status) is not status:
            raise EvidenceUnavailable('invalid_job')
        _name(job.job_id)
        if job.status.value == 'preparing':
            raise EvidenceUnavailable('separate_owner')
        if getattr(job, 'execution_target', 'local') != 'local':
            raise EvidenceUnavailable('separate_owner')
        facts['running'] = job.status.value == 'running'
        if not facts['running'] and not (engine == 'oxdna' and job.status.value == 'stopped'):
            return Observation(Assessment('unchanged'), facts)
        directory = _path(job.job_dir(workspace))
        missing = 'live'
        live = _owned(job, workspace, directory, runner if facts['running'] else None, evidence)
        if not live and engine == 'snupi':
            if not runtime.known(directory, exists=evidence.exists):
                live = evidence.pid_evidence(job.pid)
        elif not live and engine == 'lammps':
            command = evidence.pid_evidence(job.lammps_pid, command=True).lower()
            live = b'lmp' in command or b'lammps' in command
        elif not live and engine == 'oxdna' and facts['running']:
            needle = str(directory).encode()
            for command, _ in evidence.processes():
                evidence.tick()
                if needle in command and b'oxdna' in command.lower():
                    live = True
                    break
            if not live and not evidence.processes_complete:
                raise EvidenceUnavailable('process_inventory_incomplete')
        facts['live'] = live
        if live:
            return Observation(Assessment('live'), facts)
        if engine == 'lammps':
            return Observation(Assessment('stopped'), facts)
        if engine != 'oxdna':
            missing = 'cached'
            facts['cached'] = evidence.exists(directory / 'display.json')
            return Observation(Assessment('completed_cache' if facts['cached'] else 'stopped'), facts)
        missing = 'outputs_complete'
        if job.archived and not evidence.exists(directory / 'job.json'):
            raise EvidenceUnavailable('archive_unavailable')
        facts['outputs_complete'] = _oxdna_outputs(job, workspace, evidence)
        action = 'completed_outputs' if facts['outputs_complete'] else 'stopped' if facts['running'] else 'unchanged'
        return Observation(Assessment(action), facts)
    except (EvidenceUnavailable, OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        reason = str(exc) if isinstance(exc, EvidenceUnavailable) else 'unavailable'
        return Observation(Assessment('unknown', missing), facts, reason)
