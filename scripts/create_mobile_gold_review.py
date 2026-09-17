"""Prepare/run a disposable mobile-gold review using an already authored design.

No editing of the source design; all simulation stages are CUDA. Refuses an
existing review document, so previous review work is never overwritten.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse,asyncio
from backend.core.models import Design
from backend.api.crud import _geometry_for_design
from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_runner import prepare_oxdna_job,run_job
from backend.core.oxdna_protocol import OxdnaStageSpec,assign_stage_seeds
from backend.core.oxdna_staleness import oxdna_design_fingerprint


def create_review(source,workspace,run=False):
    workspace=Path(workspace).resolve();workspace.mkdir(parents=True,exist_ok=True)
    d=Design.from_json(Path(source).read_text());path=workspace/'Mobile_gold_review.nadoc'
    if path.exists():raise FileExistsError(path)
    d.metadata.name='Mobile gold review'
    d.metadata.description='CUDA mobile gold with permanent effective C3 grafts. Numerical qualification model; nonreactive attachment.'
    specs=assign_stage_seeds([
        OxdnaStageSpec('1_gpu_relax','md_relax','MD',10000,'CUDA',external_forces=True,max_backbone_force=5,max_backbone_force_far=10),
        OxdnaStageSpec('2_equil','equil','MD',20000,'CUDA',min_bp_retained=0.0),
    ],1729)
    job=new_oxdna_job(d.metadata.name,[s.to_status() for s in specs],backend='CUDA',random_seed=1729,design_source_path=str(path),design_fingerprint=oxdna_design_fingerprint(d),max_relax_retries=0)
    info=prepare_oxdna_job(d,_geometry_for_design(d),job,workspace,specs)
    job.n_nucleotides=info['mobile_gold']['dna_count']
    path.write_text(d.to_json());job.save(workspace)
    if run:asyncio.run(run_job(job,workspace,specs))
    print({'job_id':job.job_id,'status':job.status.value,'error':job.error,'path':str(path),'job_dir':str(job.job_dir(workspace))})
    return job

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--workspace',type=Path,default=Path('experiments/mobile_gold/ws'));p.add_argument('--run',action='store_true');a=p.parse_args();create_review(a.source,a.workspace,a.run)
