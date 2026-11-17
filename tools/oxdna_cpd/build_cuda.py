"""Build CPD CUDA kernels against the installed engine's exact DNA2 implementation.

Patch a private generated copy, never the engine source or the user's runtime.
Every upstream splice is checked; changed upstream code fails the build explicitly.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile


def splice(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError(f'Unsupported oxDNA CUDA source: expected {count} occurrences of {old!r}')
    return text.replace(old, new)


def build_cuda(source, library, output):
    source, library, output = (Path(p).resolve() for p in (source, library, output))
    upstream = source / 'src/CUDA/Interactions'
    own = Path(__file__).resolve().parent
    header = (upstream / 'CUDADNAInteraction.h').read_text().replace('CUDADNAInteraction', 'CpdCudaBase').replace('CUDADNAINTERACTION_H_', 'CPD_CUDA_BASE_H_')
    cu = (upstream / 'CUDADNAInteraction.cu').read_text().replace('CUDADNAInteraction', 'CpdCudaBase').replace('CUDA_DNA.cuh', 'CPD_DNA.cuh')
    kernels = (upstream / 'CUDA_DNA.cuh').read_text()
    kernels = '#include "CUDA/cuda_utils/CUDA_lr_common.cuh"\n__device__ int *cpd_partner;\n__device__ bool cpd_pair(c_number4 a, c_number4 b) { return cpd_partner[get_particle_index(a)] == get_particle_index(b); }\n' + kernels
    marker = '\t// EXCLUDED VOLUME\n\t_bonded_excluded_volume<qIsN3>'
    kernels = splice(kernels, marker, '\tif(cpd_pair(n5pos, n3pos)) {\n\t\tif(qIsN3) { F += Ftmp; T += Ttmp; } else { F -= Ftmp; T -= Ttmp; }\n\t\treturn;\n\t}\n' + marker)
    # Both edge and matrix-list paths call this common nonbonded primitive.
    start = kernels.index('__device__ void _particle_particle_DNA_interaction(')
    brace = kernels.index('{', start)
    kernels = kernels[:brace+1] + '\n\tif(cpd_pair(ppos, qpos)) return;\n' + kernels[brace+1:]
    template = (own / 'CUDACpdDNA2.cu').read_text()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nadoc-cpd-cuda-') as scratch:
        scratch = Path(scratch)
        (scratch / 'CpdCudaBase.h').write_text(header)
        (scratch / 'CPD_DNA.cuh').write_text(kernels)
        (scratch / 'CUDACpdDNA2.cu').write_text('#include <string>\n' + cu + '\n' + template)
        command = [os.environ.get('NVCC', 'nvcc'), '-std=c++17', '-O3', '-shared', '-Xcompiler=-fPIC',
                   '-Xlinker=-Bsymbolic', '-arch=' + os.environ.get('NADOC_CUDA_ARCH', 'native'),
                   '-I' + str(source / 'src'), '-I' + str(source / 'src/extern'), '-I' + str(upstream),
                   str(scratch / 'CUDACpdDNA2.cu'), '-L' + str(library), '-loxdna_common',
                   '-Xlinker=-rpath,' + str(library), '-o', str(output / 'CUDACpdDNA2.so')]
        subprocess.run(command, check=True)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    manifest = json.loads((output / 'build.json').read_text())
    manifest.update(backends=['CPU', 'CUDA'], cuda_plugin_sha256=digest((output / 'CUDACpdDNA2.so').read_bytes()),
                    cuda_source_sha256=digest(template.encode()), cuda_builder_sha256=digest(Path(__file__).read_bytes()),
                    cuda_generated_sha256=digest((header + kernels + cu + template).encode()),
                    cuda_upstream_sha256={name: digest((upstream / name).read_bytes()) for name in
                                         ['CUDADNAInteraction.h', 'CUDADNAInteraction.cu', 'CUDA_DNA.cuh']})
    (output / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('library', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build_cuda(args.source, args.library, args.output)
