"""Build an isolated, opt-in NAMD PME-storage experiment from qualified objects.

The installed engine and its source remain untouched. Activate the candidate
with NADOC_SHARED_PME=1; its default behavior keeps independent PME storage.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ENGINE_SHA256 = '2fda225c5f8838e5dbcb6a4e6a3e7e337f498df61cae2e6e320f994cb7c8b9bf'
SOURCE_SHA256 = 'e8b8e12366255609af2040bf8d90f4ba782b0114e8f2e5cbcaec690a9acf7321'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    original = source / 'Linux-x86_64-g++'
    patch = Path(__file__).with_name('namd_shared_pme.patch')
    if digest(original / 'namd3') != ENGINE_SHA256:
        raise SystemExit('This experiment requires the qualified NAMD binary.')
    if digest(source / 'src/CudaPmeSolverUtil.C') != SOURCE_SHA256:
        raise SystemExit('PME source differs from the reviewed revision.')
    if output.exists():
        raise SystemExit('Use a new output directory; existing builds are preserved.')
    output.mkdir(parents=True)
    build = output / 'build'
    shutil.copytree(original, build, symlinks=True)
    (build / '.rootdir').unlink()
    (build / '.rootdir').symlink_to(source, target_is_directory=True)
    (build / 'src').unlink()
    shutil.copytree(source / 'src', build / 'src', copy_function=shutil.copy2)
    with patch.open('rb') as stream:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=build,
                       stdin=stream, check=True)
    command = ['make', '-j2', 'namd3',
               'CXX=/usr/bin/g++-12 -m64 -std=c++17', 'FSLIB=']
    # The existing Charm++ build selects g++-12 for linking. C++17 supplies
    # filesystem support without the legacy fs_link.sh compiler probe.
    with (output / 'build.log').open('w') as stream:
        subprocess.run(command, cwd=build, check=True, stdout=stream,
                       stderr=subprocess.STDOUT,
                       env={**os.environ, 'PATH': '/usr/bin:/bin'})
    manifest = dict(original_sha256=ENGINE_SHA256,
                    source_sha256=SOURCE_SHA256,
                    patch_sha256=digest(patch),
                    candidate=str(build / 'namd3'),
                    candidate_sha256=digest(build / 'namd3'),
                    command=command, activation='NADOC_SHARED_PME=1',
                    qualification='experimental; not a replacement admission model')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(manifest['candidate'])


if __name__ == '__main__':
    main()
