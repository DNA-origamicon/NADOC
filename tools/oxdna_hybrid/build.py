"""Build an isolated candidate from an explicit existing engine source tree.

Run under `just validate-safe python -m tools.oxdna_hybrid.build ...`.
Never edits the source argument or the application's current-engine symlink.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from tools.oxdna_umbrella.native import digest, scratch_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cuda-root')
    parser.add_argument('--cuda-compiler')
    args = parser.parse_args()
    scratch_root()
    source, output = Path(args.source).resolve(strict=True), Path(args.output).resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError('Need a fresh output directory outside the supplied source')
    if shutil.disk_usage(output.parent).free < 1_000_000_000:
        raise ValueError('Need at least 1 GB free')
    output.mkdir()
    target, build = output/'source', output/'build'
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git', 'build*', '__pycache__'))
    module = Path(__file__).parent
    patches = [module.parent/'oxdna_umbrella/gpu-com-periodic.patch',
               module/'gpu-coordination.patch', module/'coordination-continuity.patch',
               module/'coordination-base-pbc.patch', module/'coordination-cache.patch']
    receipt = {'source': str(source), 'patches': []}
    for patch in patches:
        # An already-applied patch is acceptable only when reverse dry-run succeeds.
        result = subprocess.run(['patch', '-p1', '--batch', '--forward', '--dry-run', '-i', str(patch.resolve())],
                                cwd=target, capture_output=True, text=True)
        if result.returncode == 0:
            subprocess.run(['patch', '-p1', '--batch', '--forward', '-i', str(patch.resolve())], cwd=target, check=True)
            state = 'applied'
        else:
            reverse = subprocess.run(['patch', '-p1', '--batch', '--reverse', '--dry-run', '-i', str(patch.resolve())],
                                     cwd=target, capture_output=True, text=True)
            if reverse.returncode:
                raise RuntimeError(f'Patch context does not match: {patch}\n{result.stdout}')
            state = 'already present'
        receipt['patches'].append({'file': str(patch), 'sha256': digest(patch), 'state': state})
    receipt['source_sha256'] = {str(p.relative_to(target)): digest(p) for p in (target/'src').rglob('*') if p.is_file()}
    command = ['cmake', '-S', str(target), '-B', str(build), '-DCUDA=ON', '-DCUDA_COMMON_ARCH=OFF', '-DPython=OFF']
    if args.cuda_root:
        command.append('-DCUDAToolkit_ROOT='+str(Path(args.cuda_root).resolve(strict=True)))
    if args.cuda_compiler:
        command.append('-DCMAKE_CUDA_COMPILER='+str(Path(args.cuda_compiler).resolve(strict=True)))
    receipt['configure_command'] = command
    (output/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    with (output/'build.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['cmake', '--build', str(build), '--target', 'oxDNA', 'DNAnalysis', '-j1'],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    receipt['library_sha256'] = digest(build/'src/liboxdna_common.so')
    receipt['cmake_cache_sha256'] = digest(build/'CMakeCache.txt')
    (output/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({'library': str(build/'src/liboxdna_common.so'),
                      'library_sha256': receipt['library_sha256']}))


if __name__ == '__main__':
    main()
