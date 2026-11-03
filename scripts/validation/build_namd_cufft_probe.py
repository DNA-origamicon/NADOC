"""Build the workspace-only probe from the qualified NAMD build's CUDA archive.

Usage: python scripts/validation/build_namd_cufft_probe.py --engine PATH --cuda PATH
The CUDA path must be the build's CUDADIR, not a newer installed toolkit.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from backend.core.namd_allocation_model import QUALIFIED_ENGINE,QUALIFIED_CUFFT_ARCHIVE,probe_manifest_path
from backend.core.namd_provenance import file_identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--cuda',type=Path,required=True)
    args=parser.parse_args();engine=args.engine.resolve();cuda=args.cuda.resolve()
    if file_identity(engine)['sha256']!=QUALIFIED_ENGINE:
        raise ValueError('This helper requires qualification against the selected NAMD build')
    config=(engine.parent/'Make.config').read_text()
    recorded=re.search(r'^CUDADIR\s*=\s*(.+)$',config,re.M)
    if not recorded or Path(recorded[1]).resolve()!=cuda:
        raise ValueError('CUDA path does not match the NAMD build configuration')
    if file_identity(cuda/'lib64/libcufft_static.a')['sha256']!=QUALIFIED_CUFFT_ARCHIVE:
        raise ValueError('CUDA archive changed; repeat matching-plan qualification before using it')
    target=probe_manifest_path();target.parent.mkdir(parents=True,exist_ok=True)
    source=ROOT/'scripts/validation/namd_cufft_probe.cpp'
    with tempfile.TemporaryDirectory(prefix='namd-fft-') as directory:
        obj=Path(directory)/'probe.o';link=Path(directory)/'dlink.o';binary=Path(directory)/'probe'
        commands=[['/usr/bin/g++','-std=c++17','-O2','-I'+str(cuda/'include'),'-c',str(source),'-o',str(obj)],
            [str(cuda/'bin/nvcc'),'-ccbin','/usr/bin/g++','-allow-unsupported-compiler',
             '-I'+str(cuda/'include'),'-dlink',str(obj),'-lcufft_static','-o',str(link)],
            ['/usr/bin/g++',str(obj),str(link),'-L'+str(cuda/'lib64'),'-lcufft_static',
             '-lculibos','-lcudart_static','-ldl','-lpthread','-lrt','-o',str(binary)]]
        for cmd in commands:subprocess.run(cmd,check=True,timeout=120)
        import shutil
        helper=target.parent/'probe';shutil.copy2(binary,helper)
    manifest=dict(helper=str(helper),helper_sha256=file_identity(helper)['sha256'],
        engine_sha256=QUALIFIED_ENGINE,source_sha256=file_identity(source)['sha256'],
        cufft_archive=str(cuda/'lib64/libcufft_static.a'),
        cufft_archive_sha256=file_identity(cuda/'lib64/libcufft_static.a')['sha256'])
    target.write_text(json.dumps(manifest,indent=2)+'\n');print(target)


if __name__=='__main__':main()
