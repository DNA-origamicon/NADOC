"""Versioned NAMD preparation receipts, independent of legacy run/selection guards.

Coverage is the complete frozen design and prepared package, not scientific
validation, solver identity, or proof of what a remote executable actually ran.
Receipts are written only by preparation, never reconstructed by job-list reads.
"""
from __future__ import annotations

import hashlib
import json
import threading
import weakref
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

SCHEMA = 'nadoc.namd-prepared-inputs.v1'
RECEIPT = 'namd_input_receipt.json'
# Only editor bookkeeping is excluded; new model fields are included by default.
EDITOR_FIELDS = {'id', 'feature_log', 'feature_log_cursor',
                 'feature_log_sub_cursor', 'camera_poses', 'animations',
                 'representation_overrides', 'view_volumes', 'annotations',
                 'annotations_enabled', 'visibility_state', 'chain_sim_projects',
                 'plate_layout', 'tm_settings', 'loadouts', 'active_loadout_id',
                 'last_editable_loadout_id'}
INPUT_SUFFIXES = {'.conf', '.psf', '.pdb', '.prm', '.rtf', '.str', '.extra',
                  '.txt', '.tcl', '.coor', '.vel', '.xsc', '.json'}
MUTABLE_METADATA = {'manifest.json', 'nadoc_md_run.json', 'nadoc_wc_plan.json'}
FILE_DIRECTIVES = {'structure', 'coordinates', 'parameters', 'extrabondsfile',
                   'fixedatomsfile', 'consref', 'conskfile', 'bincoordinates',
                   'binvelocities', 'extendedsystem', 'tclforcesscript',
                   'colvarsconfig', 'source', 'velocities', 'langevinfile', 'consforcefile',
                   'tmdfile', 'smdfile', 'gridforcefile', 'gridforcepotfile'}
_active_cache = {}
_lock = threading.Lock()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def design_digest(design):
    from backend.core.models import Design
    if isinstance(design, dict):
        design = Design.model_validate(design)
    value = design.without_reference_geometry().model_dump(mode='json', exclude=EDITOR_FIELDS)
    metadata = value.get('metadata', {})
    for key in ('name', 'description', 'author', 'created_at', 'modified_at', 'tags',
                'identity_last_known_path', 'identity_confirmed_at', 'hardware_defaults',
                'namd_peg_visible'):
        metadata.pop(key, None)
    for field in ('strands', 'helices'):
        for item in value.get(field, []):
            item.pop('color', None)
    return digest(value)


def current_design_digest():
    from backend.api import state
    from backend.api.doc_context import get_current_doc
    try:
        design, revision = state.get_design_with_revision()
        if design is None:
            return None
        doc = get_current_doc()
        with _lock:
            cached = _active_cache.get(doc)
            if cached and cached[0]() is design and cached[1] == revision:
                return cached[2]
        result = design_digest(design)
        current, after = state.get_design_with_revision()
        if current is not design or revision != after:
            return None  # retry on the next request, without recursion under edits
        with _lock:
            if len(_active_cache) > 32:
                _active_cache.clear()
            _active_cache[doc] = (weakref.ref(design), revision, result)
        return result
    except Exception:
        return None


def signature(path):
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


@lru_cache(maxsize=4096)
def _file_hash(path, sig):
    with Path(path).open('rb') as f:
        result = hashlib.file_digest(f, 'sha256').hexdigest()
    if signature(Path(path)) != sig:
        raise OSError('Input changed while hashing')
    return result


def file_hash(path):
    return _file_hash(str(path), signature(path))


@lru_cache(maxsize=128)
def _snapshot_digest(path, sig):
    result = design_digest(json.loads(Path(path).read_text()))
    if signature(Path(path)) != sig:
        raise OSError('Design changed while hashing')
    return result


def snapshot_digest(path):
    return _snapshot_digest(str(path), signature(path))


def input_files(package):
    """Ignore trajectories/logs and runtime outputs; include all prepared assets."""
    files = {p.relative_to(package).as_posix() for p in package.iterdir()
             if p.is_file() and p.suffix in INPUT_SUFFIXES and p.name not in MUTABLE_METADATA}
    ff = package / 'forcefield'
    if ff.is_dir():
        files.update(p.relative_to(package).as_posix() for p in ff.rglob('*') if p.is_file())
    return files


def _inside(package, name):
    p = package / name
    if Path(name).is_absolute() or not p.resolve().is_relative_to(package.resolve()):
        raise ValueError('Input outside package')
    return p


def capture(job, workspace):
    """Seal a newly prepared package. Missing evidence stays explicitly incomplete."""
    jd = job.job_dir(workspace)
    package = job.package_dir(workspace)
    snapshot = jd / 'design.json'
    reasons = []
    model = None
    try:
        model = snapshot_digest(snapshot)
    except (OSError, ValueError, TypeError):
        reasons.append('missing_or_invalid_design_snapshot')
    files = input_files(package)
    configs = sorted(package.glob('*.conf'))
    if not configs:
        reasons.append('missing_namd_configs')
    outputs = set()
    references = []
    seen_directives = set()
    for conf in configs:
        for line in conf.read_text().splitlines():
            words = line.split('#', 1)[0].split()
            if len(words) < 2:
                continue
            key, value = words[0].lower(), words[1].strip('"{}')
            seen_directives.add(key)
            if key == 'outputname':
                outputs.update(value + suffix for suffix in ('.coor', '.vel', '.xsc'))
            if key in FILE_DIRECTIVES:
                references.append(value)
            if key in {'source', 'tclforcesscript', 'colvarsconfig'}:
                reasons.append('script_dependency_coverage_unqualified:' + value)
    for required in ('structure', 'coordinates', 'parameters'):
        if required not in seen_directives:
            reasons.append('missing_required_directive:' + required)
    generated = []
    for name in references:
        if any(c in name for c in '$[];'):
            reasons.append('dynamic_input_reference:' + name)
            continue
        try:
            p = _inside(package, name)
            if p.is_file():
                files.add(name)
            elif name in outputs:
                generated.append(name)
            else:
                reasons.append('missing_input:' + name)
        except (OSError, ValueError):
            reasons.append('external_input:' + name)
    records = []
    for name in sorted(files):
        try:
            p = _inside(package, name)
            records.append({'path': name, 'sha256': file_hash(p)})
        except (OSError, ValueError):
            reasons.append('unreadable_input:' + name)
    receipt = {'schema': SCHEMA, 'engine': 'namd', 'job_id': job.job_id,
               'recorded_at': datetime.now(timezone.utc).isoformat(),
               'origin': 'preparation', 'design_sha256': model,
               'preparation_options_sha256': digest(job.prep_params),
               'parent_job_id': job.parent_job_id,
               'files': records, 'generated_inputs': sorted(set(generated)),
               'coverage': {'complete': not reasons, 'kind': 'namd_prepared_package',
                            'excludes': ['solver_build', 'remote_execution_attestation', 'scientific_validity']},
               'reasons': sorted(set(reasons))}
    # Bind the receipt's inventory and metadata together; detects accidental edits.
    receipt['receipt_sha256'] = digest(receipt)
    temp = jd / (RECEIPT + '.tmp')
    temp.write_text(json.dumps(receipt, indent=2) + '\n')
    temp.replace(jd / RECEIPT)
    return receipt


def comparison(job, workspace, current_digest, legacy):
    """Read-only advisory result. Old guards continue to use their existing digest."""
    path = job.job_dir(workspace) / RECEIPT
    if not path.exists():
        return legacy
    try:
        receipt = json.loads(path.read_text())
        check = dict(receipt)
        recorded_hash = check.pop('receipt_sha256')
        if (digest(check) != recorded_hash or receipt['schema'] != SCHEMA or
                receipt['engine'] != 'namd' or receipt['job_id'] != job.job_id or
                receipt['origin'] != 'preparation'):
            raise ValueError('Invalid preparation receipt')
        records = receipt['files']
        if not records or len({r['path'] for r in records}) != len(records):
            raise ValueError('Invalid input inventory')
        package = job.package_dir(workspace)
        changed, unavailable = [], []
        for item in records:
            try:
                p = _inside(package, item['path'])
                if file_hash(p) != item['sha256']:
                    changed.append(item['path'])
            except (OSError, ValueError):
                unavailable.append(item['path'])
        # An extra config/parameter must not silently escape comparison.
        added = input_files(package) - {r['path'] for r in records}
        changed.extend(sorted(added))
        model_match = (current_digest == receipt['design_sha256']) if current_digest and receipt['design_sha256'] else None
        snapshot_changed = False
        try:
            snapshot_changed = snapshot_digest(job.job_dir(workspace) / 'design.json') != receipt['design_sha256']
        except (OSError, ValueError, TypeError):
            unavailable.append('design.json')
        complete = receipt['coverage']['complete'] is True and not unavailable and model_match is not None
        reasons = list(receipt['reasons'])
        options_changed = digest(job.prep_params) != receipt['preparation_options_sha256']
        if options_changed: reasons.append('preparation_options_changed')
        if unavailable: reasons.append('saved_inputs_unavailable')
        if changed: reasons.append('prepared_package_changed')
        if snapshot_changed: reasons.append('saved_design_changed')
        if model_match is False: reasons.append('design_changed')
        if model_match is None: reasons.append('active_design_unavailable')
        status = 'stale' if changed or snapshot_changed or options_changed or model_match is False else ('current' if complete else 'unknown')
        evidence = {'status': status, 'model_match': model_match,
                    'package_match': not changed and not unavailable,
                    'coverage': {**receipt['coverage'], 'complete': complete},
                    'reasons': reasons, 'changed_files': changed,
                    'unavailable_files': unavailable,
                    'compared_to': {'engine': 'namd', 'subject': 'active_design_and_prepared_package'}}
    except (OSError, ValueError, TypeError, KeyError):
        evidence = {'status': 'unknown', 'model_match': None,
                    'coverage': {'complete': False, 'kind': 'namd_prepared_package'},
                    'reasons': ['invalid_or_unavailable_preparation_receipt']}
    return {**legacy, 'input_freshness': evidence}


def job_status(job, workspace, legacy, current=None):
    if not (job.job_dir(workspace) / RECEIPT).is_file():
        # Old jobs already carry their frozen design. Compare that fuller model
        # without inventing a historical package receipt or writing job metadata.
        snapshot = job.job_dir(workspace) / 'design.json'
        if not snapshot.is_file():
            return legacy
        active = current if current is not None else current_design_digest()
        if active is None:
            return legacy
        try:
            match = snapshot_digest(snapshot) == active
        except (OSError, ValueError, TypeError):
            return legacy
        return {**legacy, 'input_freshness': {
            'status': 'unknown' if match else 'stale',
            'model_match': match,
            'coverage': {'complete': False, 'kind': 'saved_design_snapshot'},
            'reasons': ['historical_package_receipt_unavailable'] + ([] if match else ['design_changed']),
            'compared_to': {'engine': 'namd', 'subject': 'active_design'},
        }}
    return comparison(job, workspace, current if current is not None else current_design_digest(), legacy)
