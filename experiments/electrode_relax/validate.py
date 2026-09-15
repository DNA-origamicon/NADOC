"""Prepare/run user-authorized native electrode cases, separate from test suites."""
import argparse
import asyncio
import shutil
import json
from pathlib import Path
from backend.core.models import Design
from backend.core.namd_electrode_protocol import prepare_electrode_namd


def cases(output):
    from tests.conftest import make_minimal_design
    dna=make_minimal_design(helix_length_bp=12)
    dna.strands[0].sequence='ACGTACGTACGT'
    dna.strands[1].sequence='ACGTACGTACGT'
    for label,design in [('without_dna',Design()),('with_dna',dna),('peg_only',Design()),('dna_peg',dna)]:
        dest=output/label
        dest.mkdir(parents=True,exist_ok=False)
        (dest/'design.json').write_text(design.model_dump_json())
        result=prepare_electrode_namd(design,dest,two_electrodes=dict(normal='z',gap_nm=8,width_nm=8,depth_nm=8,working_charge_C_m2=-.0413),
            namd_peg_coating={'enabled':True,'spec':{'size_nm':4,'density_per_nm2':.125,'repeat_units':4,'shape':'square'}} if 'peg' in label else None,
            ion_conc_mM=150,mg_conc_mM=0,salt_mode='custom',fast=False,early_stop_relax=True,seed=173,
            declash=False,seed_lattice_nm=None,gpu_resident_mode='on')
        (dest/'prepared.json').write_text(json.dumps({'package_subdir':result[0],'name_stem':result[1]},indent=2))
        print(label,'prepared',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if args.run:
        from backend.core.md_job import new_job, MdSegmentStatus
        from backend.core.namd_runner import run_job
        from backend.core.md_protocols import segments_from_manifest
        results=[]
        for case in sorted(args.output.iterdir()):
            if not (case/'prepared.json').exists():continue
            data=json.loads((case/'prepared.json').read_text())
            origin=case/data['package_subdir']
            _,segments=segments_from_manifest(origin/'manifest.json')
            job=new_job('electrode_validation_'+case.name,'electrode_equilibration_namd','system','package',threads=1,devices='0',namd_seed=173)
            ws=Path('workspace');target=job.package_dir(ws)
            shutil.copytree(origin,target)
            shutil.copy2(case/'design.json',job.job_dir(ws)/'design.json')
            job.early_stop_relax=True
            job.prep_params={'protocol':'electrode_equilibration_namd','early_stop_relax':True,'gpu_resident_mode':'on','gpu_fallback_policy':'ask'}
            job.segments=[MdSegmentStatus(t.name,t.stage,t.percent,t.steps) for t in segments]
            job.save(ws)
            print('Running',case.name,job.job_id,flush=True)
            asyncio.run(run_job(job,ws))
            results.append({'case':case.name,'job_id':job.job_id,'status':job.status.value,'error':job.error,'skipped':[t.name for t in job.segments if t.skipped]})
            (args.output/'validation.json').write_text(json.dumps(results,indent=2)+'\n')
            print(results[-1],flush=True)
        return
    cases(args.output)

if __name__=='__main__':main()
