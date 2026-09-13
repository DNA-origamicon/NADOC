"""Persistent PEG-only review documents and verified historical NAMD job imports."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil

import numpy as np

from backend.core.namd_peg_frames import frame_index, sampled_frames
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.models import Design
from backend.core.namd_metrics import parse_namd_log_frames
from experiments.peg_namd.structure import read_pair
from experiments.peg_wall.validate import analyze, verify_inputs

KIND = 'peg_wall_qualification'


def review_payload(package):
    package = Path(package)
    manifest = verify_inputs(package)
    pair = read_pair(package/'system.psf', package/'system.pdb')
    start = next(i for i, line in enumerate(pair['lines']) if '!NBOND' in line)
    count = int(pair['lines'][start].split()[0])
    numbers = []
    for line in pair['lines'][start+1:]:
        if len(numbers) >= count*2:
            break
        numbers.extend(map(int, line.split()))
    return dict(schema='nadoc.namd_peg_review.v1', case_id=manifest['input_hashes']['system.psf'],
                title=f'Atomistic PEG{manifest["repeat_units"]} / repulsive wall — {manifest["audit"]["atoms"]:,}-atom qualification',
                coordinates_nm=(pair['xyz']/10).tolist(),
                elements=[a[4][0] for a in pair['atoms']],
                bonds=(np.array(numbers[:count*2]).reshape(-1, 2)-1).tolist(),
                peg_indices=manifest['audit']['peg_indices_0'],
                anchor_indices=manifest['audit']['anchor_indices_0'],
                slit=manifest['slit'], chemistry=manifest['chemistry'],
                atoms=manifest['audit']['atoms'], chains=manifest['audit']['chains'],
                repeat_units=manifest['repeat_units'], jobs=[],
                note='Initial coordinates. Harmonic grafts; finite-stiffness repulsive walls. No equilibrium claim.')


def publish_review(package, workspace, filename='NAMD_PEG8_wall_review.nadoc'):
    """Keep only successful stages; copy their immutable native inputs and evidence.

    No process launch and no queued/draft placeholder jobs. Existing documents are
    refused so a retry cannot overwrite user edits or duplicate historical results.
    """
    package, workspace = Path(package).resolve(), Path(workspace).resolve()
    path = workspace/filename
    if Path(filename).name != filename or not filename.endswith('.nadoc'):
        raise ValueError('review filename must be a workspace .nadoc basename')
    if path.exists():
        raise FileExistsError(path)
    manifest = verify_inputs(package)
    review = review_payload(package)
    stages = []
    for stage in ('minimize', 'resident'):
        receipt_path = package/f'{stage}_execution.json'
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text())
        if receipt.get('returncode') != 0:
            continue
        log_path = package/f'{stage}.log'
        rows = parse_namd_log_frames(log_path)
        requested = 1000 if stage == 'minimize' else manifest['steps']
        if (not rows or rows[-1].get('TS') != requested
                or not all(np.isfinite(v) for row in rows for v in row.values())
                or 'End of program' not in log_path.read_text()):
            continue
        if stage == 'resident' and analyze(package)['status'] != 'short_qualification_passed':
            continue
        stages.append((stage, requested, receipt))
    jobs = []
    for stage, steps, receipt in stages:
        job = new_job('NAMD PEG8 wall review', f'PEG wall {stage}', 'system', 'package',
                      threads=2, devices='0', design_source_path=str(path), run_kind=KIND,
                      namd_seed=manifest['seed'])
        job.status = MdStatus.completed
        job.segments = [MdSegmentStatus(stage, 'minimization' if stage == 'minimize' else 'qualification',
                                       100., steps, status='done')]
        job.prep_params = dict(peg_qualification=True, atoms=review['atoms'],
                               timestep_fs=manifest['timestep_fs'], temperature=manifest['temperature_K'])
        jobs.append(job)
        review['jobs'].append(dict(job_id=job.job_id, stage=stage, status='completed'))
    design = Design()
    design.metadata.name = 'NAMD PEG8 wall review'
    design.metadata.description = ('Four atomistic methyl-capped PEG8 chains in water with a repulsive slit '
                                   'and harmonic grafts. A persistent display-only qualification document; '
                                   'no DNA topology or production-ready brush is implied.')
    design.metadata.identity_last_known_path = str(path)
    design.metadata.tags = ['PEG', 'NAMD', 'atomistic', 'qualification']
    design.metadata.namd_peg_review = review
    from backend.core.oxdna_staleness import oxdna_design_fingerprint
    from backend.core.project_revisions import record_simulation_revision
    workspace.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        handle.write(design.model_dump_json(indent=2))
    for job in jobs:
        target = job.package_dir(workspace)
        shutil.copytree(package, target)
        stage = job.segments[0].name
        shutil.copyfile(package/f'{stage}.log', target/f'output/{stage}.log')
        # Add the normal job-viewer manifest shape without changing native inputs.
        viewer_manifest = {**manifest, 'n_atoms': review['atoms'], 'read_only_qualification': True,
                           'minimization': {'name': 'minimize', 'steps': 1000},
                           'segments': [dict(name=stage, stage=job.segments[0].stage,
                                             percent=100, steps=job.segments[0].steps,
                                             temp=manifest['temperature_K'], damping=1,
                                             scale=manifest['graft_k_kcal_mol_A2'], npt=False,
                                             previous='minimize', timestep_fs=manifest['timestep_fs'],
                                             dcd_freq=100)]}
        (target/'manifest.json').write_text(json.dumps(viewer_manifest, indent=2)+'\n')
        # Normal job viewers resolve design.json from the job directory.
        (job.job_dir(workspace)/'design.json').write_text(design.model_dump_json(indent=2))
        (target/'peg_review.json').write_text(json.dumps(review)+'\n')
        job.design_fingerprint = oxdna_design_fingerprint(design)
        provenance = record_simulation_revision(workspace, design, 'namd', job.job_id)
        job.project_id, job.design_revision_id = provenance.project_id, provenance.revision_id
        job.save(workspace)
    return path, jobs


def job_review(workspace, job_id, max_frames=100, segment=None):
    job = MdJob.load(job_id, Path(workspace))
    if job.run_kind not in (KIND, 'peg_fast_relax'):
        raise ValueError('not a completed PEG qualification job')
    package = job.package_dir(Path(workspace))
    payload = json.loads((package/'peg_review.json').read_text())
    payload['job'] = asdict(job)
    indices = {s.name: frame_index(package, s.name, payload['atoms'])
               for s in job.segments if not s.skipped}
    available = [name for name, frames in indices.items() if frames]
    if segment is not None and segment not in indices:
        raise ValueError('Requested PEG segment is unavailable')
    stage = segment or (available[-1] if available else job.segments[0].name)
    frames = sampled_frames(indices.get(stage, []), max_frames)
    payload.update(job_id=job_id, stage=stage, frames=frames,
                   available_stages=available, raw_frames=len(indices.get(stage, [])),
                   sampling='Uniform frame sampling in the fixed surface frame',
                   analysis_ready=stage != 'minimize' and len(frames) >= 2)
    payload['note'] = ('Recorded minimization; iteration numbers are not physical time.' if stage == 'minimize'
                       else 'Completed 1 ps GPU-resident qualification; not equilibrated production.')
    if job.run_kind == 'peg_fast_relax':
        payload['jobs'] = [dict(job_id=job_id, stage='fast relax', status=job.status.value)]
        payload['note'] = (f'Fast relax {job.status.value} · {stage}. '
                           'Fixed NVT wall and permanent harmonic grafts. No equilibrium claim.')
    if not frames:
        payload['note'] += ' Waiting for complete recorded frames.'
    return payload
