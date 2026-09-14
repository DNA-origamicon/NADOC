"""Create one persistent PEG/DNA review document and optionally run its smoke simulation.

Usage: .venv/bin/python scripts/create_peg_surface_review.py --run
Requires scripts/build-oxdna-peg.sh. Refuses to overwrite an existing review file.
"""
from __future__ import annotations
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.models import Design, Helix, Strand, Domain, Direction, StrandType, Vec3


def make_review_design():
    helix = Helix(id='peg_probe', axis_start=Vec3(x=0,y=0,z=0),
                  axis_end=Vec3(x=0,y=0,z=16*.334), length_bp=16)
    design = Design(helices=[helix], strands=[
        Strand(id='probe_forward', strand_type=StrandType.SCAFFOLD,
               sequence='GCGCATGCGCATGCGC', domains=[Domain(helix_id=helix.id,
               start_bp=0, end_bp=15, direction=Direction.FORWARD)]),
        Strand(id='probe_reverse', strand_type=StrandType.STAPLE,
               sequence='GCGCATGCGCATGCGC', domains=[Domain(helix_id=helix.id,
               start_bp=15, end_bp=0, direction=Direction.REVERSE)]),
    ])
    design.metadata.name = 'PEG surface review'
    design.metadata.description = ('Experimental DNA2PEG v1: four neutral PEG-like chains, '
        'eight 0.7 nm statistical segments each, grafted to a repulsive plane; '
        '16 bp DNA probe with its forward strand anchored. Open Dynamics / oxDNA '
        'to inspect the saved simulation. This is an uncalibrated bead-spring model, '
        'not chemically resolved PEG or a validated electric-field response.')
    design.metadata.tags = ['PEG', 'experimental', 'oxDNA']
    design.metadata.peg_surface = {
        'surface': {'dir':[0,1,0], 'position_nm':-7.0, 'offset_nm':7.0, 'stiff':100.0},
        'anchors': [{'kind':'strand', 'id':'probe_forward'}],
        'surface_strands': {'enabled':True, 'material':'PEG', 'segments':8,
            'bondLengthNm':0.7, 'beadDiameterNm':0.5, 'terminalChargeE':0.0,
            'shape':'square', 'sizeNm':12.0, 'densityPerUm2':27778.0,
            'offsetXNm':0.0, 'offsetYNm':0.0, 'seed':17, 'subjectToField':False},
    }
    return design


def create_review(workspace: Path, run=False):
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_protocol import build_relaxation_stages, assign_stage_seeds, OxdnaStageSpec
    from backend.core.oxdna_runner import prepare_oxdna_job, run_job
    from backend.core.oxdna_staleness import oxdna_design_fingerprint
    from backend.core.project_revisions import record_simulation_revision
    from backend.physics.oxdna_peg import find_peg_oxdna
    if not find_peg_oxdna():
        raise RuntimeError('Build the PEG engine first: bash scripts/build-oxdna-peg.sh')
    workspace = workspace.resolve()
    path = workspace / 'PEG_surface_review.nadoc'
    if path.exists():
        raise FileExistsError(f'Refusing to overwrite {path}')
    workspace.mkdir(parents=True, exist_ok=True)
    design = make_review_design()
    design.metadata.identity_last_known_path = str(path)
    setup = design.metadata.peg_surface
    specs = build_relaxation_stages(mc_steps=100, md_relax_steps=20000,
        equil_steps=10000, backend='CUDA', surface_present=True)
    specs.append(OxdnaStageSpec(name='4_peg_production', kind='production',
        sim_type='MD', steps=50000, backend='CUDA', dt=.001,
        external_forces=True, absolute_forces=True, forces_file='equil_forces.txt'))
    specs = assign_stage_seeds(specs, 1729)
    job = new_oxdna_job(design.metadata.name, [s.to_status() for s in specs],
        n_nucleotides=32, backend='CUDA', random_seed=1729,
        design_source_path=str(path), design_fingerprint=oxdna_design_fingerprint(design),
        run_config={'kind':'relax', 'backend':'CUDA', 'device':'0',
            'interaction_type':'DNA2', 'engine_variant':'auto', 'execution_target':'local',
            'seed':1729, 'salt_concentration':.5, 'mc_steps':100,
            'md_relax_steps':20000, 'equil_steps':10000, 'min_bp_retained':.5,
            'max_relax_retries':3, **setup})
    info = prepare_oxdna_job(design, _geometry_for_design(design), job, workspace,
        specs, surface=setup['surface'], anchors=setup['anchors'],
        surface_strands=setup['surface_strands'])
    job.run_config['surface_strands'] = {**setup['surface_strands'], 'built':info['capture']}
    job.n_nucleotides += info['capture']['n_beads']
    with path.open('x') as handle:
        handle.write(design.model_dump_json(indent=2))
    provenance = record_simulation_revision(workspace, design, 'oxdna', job.job_id)
    job.project_id, job.design_revision_id = provenance.project_id, provenance.revision_id
    job.save(workspace)
    print(f'Document: {path}\nJob: {job.job_id}', flush=True)
    if run:
        asyncio.run(run_job(job, workspace, specs))
        print(f'Status: {job.status}; error: {job.error}', flush=True)
        if str(job.status.value) != 'completed':
            raise RuntimeError(f'Review simulation did not complete: {job.error}')
    return path, job


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[1]/'workspace')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    create_review(args.workspace, args.run)
