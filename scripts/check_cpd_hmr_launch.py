"""Native smoke of the actual CPD production-child builder, in disposable storage."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from backend.core.md_job import MdJob, new_job
from backend.core.md_ensemble import build_replica_package
from backend.core.cpd_forcefield import packaged_photoproduct_manifest
from scripts.validate_cpd_hmr import geometry, pin, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root=args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    workspace=Path('workspace').resolve()
    jid='edb512c46112'
    parent=MdJob.load(jid,workspace)
    source=parent.package_dir(workspace)
    checkpoint=parent.segments[0].name
    inputs=[pin(parent.job_dir(workspace)/'job.json'),pin(source/'manifest.json'),
            pin(source/f'{parent.name_stem}.psf'),pin(source/f'{checkpoint}.conf')]
    inputs += [pin(source/'output'/f'{checkpoint}.restart.{ext}') for ext in ['coor','vel','xsc']]
    receipt=dict(source_inputs=inputs,worker=pin(__file__),passed=False)
    try:
        with tempfile.TemporaryDirectory(prefix='launch-',dir=root) as temporary:
            ws=Path(temporary)
            (ws/'md_jobs').mkdir()
            # Parent is read-only input. The builder only writes its distinct child.
            (ws/'md_jobs'/jid).symlink_to(parent.job_dir(workspace),target_is_directory=True)
            child=new_job('CPD HMR launch validation',parent.protocol,'','',
                          threads=4,parent_job_id=jid,run_kind='production')
            pkg=build_replica_package(parent,child,seed=731043,index=0,total_steps=2500,
                length_ns=.01,timestep_fs=4.,fast=True,rigid_bonds='all',hmr=True,
                ready_checkpoint=checkpoint,workspace=ws,dcd_freq=250,force_resident=True)
            manifest=json.loads((pkg/'manifest.json').read_text())
            assert manifest['ensemble']['cpd_mass_change_reseed'] is True
            assert manifest['production_timestep_fs']==4 and manifest['production_hmr'] is True
            product=packaged_photoproduct_manifest(pkg)
            stages=[child.minimization.name,child.segments[0].name]
            namd=str(Path(shutil.which('namd3')).resolve())
            receipt.update(engine=pin(namd),manifest=manifest)
            for label,stage in zip(['reseed','production'],stages):
                shutil.copy2(pkg/f'{stage}.conf',root/f'{label}.conf')
                with (root/f'{label}.log').open('w') as log:
                    result=subprocess.run([namd,'+p4','+setcpuaffinity',f'{stage}.conf'],
                        cwd=pkg,stdout=log,stderr=subprocess.STDOUT,timeout=600)
                text=(root/f'{label}.log').read_text()
                assert result.returncode==0 and 'End of program' in text
            receipt['geometry']=geometry(pkg/f'{parent.name_stem}_hmr.psf',pkg/'output'/f'{stages[-1]}.dcd',product)
            assert receipt['geometry']['passed']
            receipt['passed']=True
        receipt['temporary_files_removed']=not Path(temporary).exists()
        assert all(pin(p['path'])==p for p in inputs)
        receipt['source_inputs_unchanged']=True
    finally:
        save(root/'receipt.json',receipt)
    print('Real production builder and native 4 fs/HMR launch passed; temporary child removed.')


if __name__=='__main__':
    main()
