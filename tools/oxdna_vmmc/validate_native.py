"""Explicit native smoke workflow using existing simulation inputs, in disposable storage.

Run with python -m tools.oxdna_vmmc.validate_native --job-dir ... --binary ... --report ...
This is an execution/analysis validation, not a convergence or melting benchmark.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import tempfile

from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_protocol import build_production_stage
from backend.core.oxdna_vmmc import VmmcMelting, configure
from backend.core.oxdna_vmmc_runner import run


def validate(source, binary, report):
    source,binary,report=map(lambda p:Path(p).resolve(),(source,binary,report))
    original=json.loads((source/'job.json').read_text())
    os.environ['OXDNA_BIN']=str(binary)
    cfg=VmmcMelting(**{**original['run_config']['vmmc_melting'],
        'tuning_steps':10000,'equil_steps':10000,'production_steps':100000})
    scratch=Path(os.environ.get('NADOC_TEST_SCRATCH_ROOT',tempfile.gettempdir())).expanduser().resolve(strict=True)
    if not scratch.is_dir():
        raise RuntimeError('Configured scratch root must be an existing directory; no fallback.')
    if 'NADOC_TEST_SCRATCH_MOUNT' in os.environ:
        mount=Path(os.environ['NADOC_TEST_SCRATCH_MOUNT']).expanduser().resolve(strict=True)
        if not mount.is_mount() or not scratch.is_relative_to(mount) or scratch.stat().st_dev!=mount.stat().st_dev:
            raise RuntimeError('Scratch root is not on the required mounted filesystem; no fallback.')
    with tempfile.TemporaryDirectory(prefix='nadoc-vmmc-native-',dir=scratch) as temporary:
        workspace=Path(temporary)
        if shutil.disk_usage(workspace).free<100_000_000:
            raise RuntimeError('Native validation requires 100 MB free scratch space.')
        job=new_oxdna_job('VMMC native validation',[],n_nucleotides=original['n_nucleotides'])
        job.run_config={};job.random_seed=1478532
        specs=configure(job,build_production_stage(salt_concentration=original['salt_concentration']),cfg)
        root=job.job_dir(workspace);root.mkdir(parents=True)
        for name in ['topology.top','conf.dat','oxDNA2_sequence_dependent_parameters.txt']:
            shutil.copy2(source/name,root/name)
        job.save(workspace)
        asyncio.run(run(job,workspace,specs))
        result={'status':job.status.value,'stages':[(s.name,s.status) for s in job.stages],
                'analysis':job.run_config['vmmc_result'],'engine':str(binary),
                'qualification':'Short execution smoke test; not a convergence validation.'}
        assert all(s.status=='done' for s in job.stages)
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'status':result['status'],'completed_stages':len(job.stages),
                          'analysis_status':result['analysis']['status']}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-dir',required=True)
    parser.add_argument('--binary',required=True)
    parser.add_argument('--report',required=True)
    args=parser.parse_args()
    validate(args.job_dir,args.binary,args.report)
