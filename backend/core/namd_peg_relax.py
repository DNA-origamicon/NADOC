"""PEG-only adapter for managed fast relaxation: fixed walls, HMR and polymer cutoff."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil

import numpy as np

from backend.core.md_job import MdJob, MdSegmentStatus, new_job
from backend.core.md_protocols import SegmentSpec, write_hmr_psf
from backend.core.namd_peg_review import KIND, review_payload
from backend.core.namd_peg_wall import RepulsiveSlit
from experiments.peg_wall.build import configurations, sha256
from experiments.peg_wall.validate import verify_inputs

RELAX_KIND = 'peg_fast_relax'


def relax_segments(duration_ps=4800.):
    """Standard p10/p50/p100 cadence, preceded by a 25 ps 2 fs rigid warm-up.

    PEG has no DNA ENM to release. One 4.8 ns NVT rung retains the physical grafts.
    Warm-up cannot be skipped; all assessed chunks run 4 fs HMR dynamics.
    """
    if not np.isfinite(duration_ps) or not 100 <= duration_ps <= 4800:
        raise ValueError('duration_ps must be 100..4800')
    segments = [SegmentSpec('peg_warm_p100', 'PEG 2 fs warm-up', 100, 12500,
                            294, 1, 5, False, 'minimize', reinit=True, dcd_freq=400,
                            timestep_fs=2)]
    previous = segments[0].name
    for percent, fraction in [(10, .1), (50, .4), (100, .5)]:
        steps = int(round(duration_ps*1000/4*fraction/10))*10
        name = f'peg_relax_p{percent}'
        segments.append(SegmentSpec(name, 'PEG 4 fs NVT relaxation', percent, steps,
                                   294, 1, 5, False, previous,
                                   dcd_freq=max(10, steps//30//10*10), timestep_fs=4))
        previous = name
    return segments


def prepare_relax(workspace, source_id, *, duration_ps=4800., early_stop=True, seed=29):
    workspace = Path(workspace)
    source = MdJob.load(source_id, workspace)
    if source.run_kind != KIND or source.status.value != 'completed':
        raise ValueError('Select a completed PEG wall qualification as the source')
    if type(seed) is not int or not 1 <= seed <= 2147483647:
        raise ValueError('seed must be a positive signed 32-bit integer')
    origin = source.package_dir(workspace)
    manifest = verify_inputs(origin)
    segments = relax_segments(duration_ps)
    job = new_job(source.design_name, RELAX_KIND, 'system', 'package', threads=2, devices='0',
                  design_source_path=source.design_source_path, project_id=source.project_id,
                  design_revision_id=source.design_revision_id, parent_job_id=source_id,
                  run_kind=RELAX_KIND, namd_seed=seed)
    job.early_stop_relax = bool(early_stop)
    job.design_fingerprint = source.design_fingerprint
    job.prep_params = dict(peg_fast_relax=True, fast=True, early_stop_relax=bool(early_stop),
                           gpu_resident_mode='on', gpu_fallback_policy='ask', duration_ps=duration_ps,
                           temperature=manifest['temperature_K'])
    target = job.package_dir(workspace)
    target.mkdir(parents=True, exist_ok=False)
    for name in manifest['input_hashes']:
        if not name.endswith('.conf'):
            shutil.copy2(origin/name, target/name)
    (target/'output').mkdir()
    shutil.copy2(source.job_dir(workspace)/'design.json', job.job_dir(workspace)/'design.json')
    n_hmr = write_hmr_psf(target/'system.psf', target/'system_hmr.psf')
    if n_hmr <= 0:
        raise ValueError('PEG HMR did not repartition any hydrogen atoms')
    slit = RepulsiveSlit(**manifest['slit'])
    configs = configurations(slit, manifest['graft_k_kcal_mol_A2'], manifest['temperature_K'], 1000, seed)
    (target/'minimize.conf').write_text(configs['minimize'].replace('minimize 1000', 'minimize 4800'))
    common = configs['resident'].split('# Short qualification')[0]
    for spec in segments:
        spec.temp = manifest['temperature_K']
        spec.scale = manifest['graft_k_kcal_mol_A2']
        text = common.replace('timestep 1.0', f'timestep {spec.timestep_fs}')
        if spec.timestep_fs == 4:
            text = text.replace('structure system.psf', 'structure system_hmr.psf')
        text = text.replace('outputEnergies 10', f'outputEnergies {spec.dcd_freq}')
        text = text.replace('DCDfreq 100', f'DCDfreq {spec.dcd_freq}').replace('restartfreq 100', 'restartfreq 10000')
        text += f'GPUresident on\noutputName output/{spec.name}\nbinCoordinates output/{spec.previous}.coor\n'
        # Reinitialize velocities at the mass transition; old velocities belong to the plain PSF.
        text += f'temperature {spec.temp}\n' if spec.reinit or spec.name.endswith('_p10') else f'binVelocities output/{spec.previous}.vel\n'
        text += f'firsttimestep 0\nrun {spec.steps}\n'
        (target/f'{spec.name}.conf').write_text(text)
    review = review_payload(origin)
    review['jobs'] = [dict(job_id=job.job_id, stage='fast relax', status='queued')]
    (target/'peg_review.json').write_text(json.dumps(review))
    out = {**manifest, 'schema': 'nadoc.peg_fast_relax.v1', 'peg_fast_relax': True,
           'protocol': RELAX_KIND, 'seed': seed, 'status': 'prepared', 'timestep_fs': 4., 'n_atoms': manifest['audit']['atoms'], 'name_stem': 'system',
           'minimization': dict(name='minimize', steps=4800),
           'segments': [asdict(s) for s in segments],
           'fast_relaxation': dict(enabled=True, structure_psf='system_hmr.psf', hmr_atoms=n_hmr),
           'duration_ps': duration_ps, 'source_job_id': source_id,
           'input_hashes': {p.name: sha256(p) for p in target.iterdir() if p.is_file()}}
    (target/'manifest.json').write_text(json.dumps(out, indent=2))
    job.segments = [MdSegmentStatus(s.name, s.stage, s.percent, s.steps) for s in segments]
    job.save(workspace)
    return job


def validate_relax_package(package):
    """Resume the exact prepared PEG force/integrator package, or fail explicitly."""
    package = Path(package)
    manifest = json.loads((package/'manifest.json').read_text())
    if not manifest.get('peg_fast_relax'):
        return
    for name, digest in manifest['input_hashes'].items():
        if Path(name).name != name or sha256(package/name) != digest:
            raise ValueError(f'PEG relaxation input changed since preparation: {name}')
