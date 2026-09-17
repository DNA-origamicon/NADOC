"""Retained local CUDA campaign; run as a module from repository root.
Uses original campaign paths; choose fresh output paths before repeating.
"""
from pathlib import Path
import asyncio
from backend.core.models import Design
from backend.api.crud import _geometry_for_design
from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_runner import prepare_oxdna_job,run_job
from backend.core.oxdna_protocol import OxdnaStageSpec,assign_stage_seeds
from backend.core.oxdna_staleness import oxdna_design_fingerprint
ws=Path('experiments/mobile_gold/ws').resolve();source=ws/'Mobile_gold_review.nadoc';d=Design.from_json(source.read_text())
stages=assign_stage_seeds([OxdnaStageSpec('1_gpu_relax','md_relax','MD',200000,'CUDA',external_forces=True,max_backbone_force=5,max_backbone_force_far=10,print_conf_interval_override=10000),OxdnaStageSpec('2_equil','equil','MD',50000,'CUDA',min_bp_retained=.8,print_conf_interval_override=2500)],1730)
job=new_oxdna_job('Mobile gold review — longer relaxation',[s.to_status() for s in stages],backend='CUDA',random_seed=1730,design_source_path=str(source),design_fingerprint=oxdna_design_fingerprint(d),max_relax_retries=0)
info=prepare_oxdna_job(d,_geometry_for_design(d),job,ws,stages);job.n_nucleotides=info['mobile_gold']['dna_count'];job.save(ws)
print('job',job.job_id,flush=True);asyncio.run(run_job(job,ws,stages));print(job.status.value,job.error,flush=True)
