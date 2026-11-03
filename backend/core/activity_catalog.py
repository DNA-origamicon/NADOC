"""Finite internal activity catalog; no HTTP admission or persisted status repair.

Native metadata normalization is shared with ordinary loaders. External archives
are represented from local cached metadata, with explicit unverified provenance;
this path never refreshes caches or accesses arbitrary archive mounts.
"""
import json
import math
from pathlib import Path
import time

from backend.core.activity_evidence_io import Evidence, EvidenceUnavailable
from backend.core.activity_observation import _name, observe_namd, observe_mrdna
from backend.core.activity_local_engines import observe_local_engine
from backend.core.part_capture_graph import GraphBudget, CaptureLimit

MAX_JOBS = 128
MAX_NODES = 30000
MAX_OUTPUT_BYTES = 2_000_000


def _families():
    from backend.core.md_job import MdJob
    from backend.core.oxdna_job import OxdnaJob
    from backend.core.mrdna_job import MrdnaJob
    from backend.core.lammps_job import LammpsJob
    from backend.core.cando_job import CandoJob
    from backend.core.snupi_job import SnupiJob
    return (('md', MdJob), ('oxdna', OxdnaJob), ('mrdna', MrdnaJob),
            ('lammps', LammpsJob), ('cando', CandoJob), ('snupi', SnupiJob))


def _string(value, limit=1024, *, optional=False):
    if value is None and optional:
        return None
    if type(value) is not str or len(value) > limit:
        raise EvidenceUnavailable('invalid_summary_string')
    return value


def _number(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 2**63:
        raise EvidenceUnavailable('invalid_summary_number')
    return value


def _json(path, evidence, graph):
    if path.is_symlink() or path.parent.is_symlink():
        raise EvidenceUnavailable('symlink_metadata_unqualified')
    value = json.loads(evidence.json_text(path))
    graph.charge(value)
    evidence.tick()
    if type(value) is not dict:
        raise EvidenceUnavailable('invalid_metadata')
    return value


def _discover(folder, engine, evidence, graph):
    if folder.is_symlink():
        raise EvidenceUnavailable('symlink_discovery_unqualified')
    index = {}
    # LAMMPS intentionally has no archive-aware native loader/list contract.
    if engine != 'lammps':
        try:
            index = _json(folder / '.archive_index.json', evidence, graph)
        except FileNotFoundError:
            pass
        if len(index) > MAX_JOBS:
            raise EvidenceUnavailable('job_budget')
        for identifier, location in index.items():
            evidence.tick(); _name(identifier); _string(location, 4096)
    identifiers = set(index)
    try:
        for entry in evidence.entries(folder):
            if entry.name in ('.archive_metadata',):
                continue
            if entry.is_symlink():
                raise EvidenceUnavailable('symlink_discovery_unqualified')
            if entry.is_dir(follow_symlinks=False) and evidence.exists(Path(entry.path) / 'job.json'):
                _name(entry.name)
                identifiers.add(entry.name)
                if len(identifiers) > MAX_JOBS:
                    raise EvidenceUnavailable('job_budget')
    except FileNotFoundError:
        pass
    return [(identifier, identifier in index) for identifier in sorted(identifiers)]


def _normalize(model, data, identifier):
    if data.get('job_id') != identifier:
        raise EvidenceUnavailable('job_identity_mismatch')
    for key in ('segments', 'stages', 'health_samples'):
        value = data.get(key, [])
        if type(value) is not list or len(value) > 128:
            raise EvidenceUnavailable('metadata_collection_budget')
    # from_metadata owns only this private parsed dictionary; no overlays or reads.
    return model.from_metadata(data)


def _project(engine, job, workspace, evidence, archived):
    summary = {
        'engine': engine, 'job_id': _name(job.job_id),
        'design_name': _string(job.design_name),
        'design_source_path': _string(job.design_source_path, 4096, optional=True),
        'status': _string(job.status.value, 32), 'created_at': _number(job.created_at),
        'execution_target': _string(getattr(job, 'execution_target', 'local'), 32),
        'resource_class': 'gpu' if engine in ('md', 'mrdna') else 'cpu',
        'eta_seconds': None,
    }
    if engine == 'oxdna':
        backend = _string(job.backend, 32)
        summary['resource_class'] = 'gpu' if backend == 'CUDA' else 'cpu'
    if engine == 'md':
        metrics = job.live_metrics
        if metrics is not None and type(metrics) is not dict:
            raise EvidenceUnavailable('invalid_live_metrics')
        summary.update(accelerator_name=None,
            slurm_job_id=_string(job.slurm_job_id, 256, optional=True),
            slurm_state=_string(job.slurm_state, 128, optional=True),
            last_synced_at=_number((metrics or {}).get('retrieved_at')))
    issues = []
    if archived or getattr(job, 'archived', False):
        action = 'unknown'; active = None
        issues.append('archive_live_unverified')
    elif job.status.value not in ('running', 'preparing'):
        # Native activity polling only reconciles initially busy records.
        action = 'unchanged'; active = False
    else:
        observation = (observe_namd(job, workspace, evidence) if engine == 'md' else
            observe_mrdna(job, workspace, evidence) if engine == 'mrdna' else
            observe_local_engine(engine, job, workspace, evidence))
        action = observation.assessment.action
        if action in ('live', 'resume_minimization', 'resume_checkpoint', 'resume_unstarted_segment'):
            active = True
        elif action in ('stopped', 'completed_cache', 'completed_outputs', 'failed_without_checkpoint'):
            active = False
        else:
            active = None
            issues.append(observation.reason or action)
    if active is not False:
        if not summary['design_source_path']:
            issues.append('source_identity_unverified')
        if engine in ('md', 'oxdna') and job.status.value == 'running':
            issues.append('eta_unverified')
        if engine == 'md' and summary['execution_target'] != 'local':
            issues.append('accelerator_unverified')
    return {'summary': summary, 'active': active, 'action': action, 'issues': issues}


def activity_catalog(workspace, *, evidence=None):
    """Return bounded records plus completeness, never a misleading empty list."""
    evidence = evidence if evidence is not None else Evidence()
    workspace = Path(workspace)
    graph = GraphBudget(max_nodes=MAX_NODES, max_bytes=MAX_OUTPUT_BYTES, seconds=None, clock=time.monotonic)
    records = []; issues = []
    for engine, model in _families():
        folder = workspace / f'{engine}_jobs'
        try:
            evidence.tick()
            candidates = _discover(folder, engine, evidence, graph)
            if len(records) + len(candidates) > MAX_JOBS:
                raise EvidenceUnavailable('job_budget')
            for identifier, archived in candidates:
                evidence.tick()
                path = folder / '.archive_metadata' / f'{identifier}.json' if archived else folder / identifier / 'job.json'
                try:
                    data = _json(path, evidence, graph)
                    job = _normalize(model, data, identifier)
                    record = _project(engine, job, workspace, evidence, archived)
                except (EvidenceUnavailable, OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
                    reason = str(exc) if isinstance(exc, EvidenceUnavailable) else 'metadata_unavailable'
                    record = {'summary': {'engine': engine, 'job_id': identifier},
                              'active': None, 'action': 'unknown', 'issues': [reason]}
                records.append(record)
        except (EvidenceUnavailable, OSError, ValueError, TypeError) as exc:
            reason = str(exc) if isinstance(exc, EvidenceUnavailable) else 'discovery_unavailable'
            issues.append({'engine': engine, 'reason': reason})
    result = {'records': records, 'issues': issues,
              'complete': not issues and not any(record['issues'] for record in records)}
    # Check graph and wire budgets before returning to any future HTTP serializer.
    try:
        evidence.tick()
        GraphBudget(max_nodes=MAX_NODES, max_bytes=MAX_OUTPUT_BYTES, seconds=None,
                    clock=time.monotonic).charge(result)
        size = 0
        for chunk in json.JSONEncoder(allow_nan=False, separators=(',', ':')).iterencode(result):
            size += len(chunk.encode('utf-8'))
            if size > MAX_OUTPUT_BYTES:
                raise CaptureLimit('catalog output budget')
        evidence.tick()
    except (CaptureLimit, EvidenceUnavailable, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, EvidenceUnavailable) else 'output_budget'
        return {'records': [], 'issues': [{'reason': reason}], 'complete': False}
    return result
