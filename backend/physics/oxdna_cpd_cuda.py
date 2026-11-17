"""CUDA CPD package capabilities; never silently downgrade requested dynamics."""
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wants_cuda(specs):
    return any(s.sim_type == 'MD' and s.backend == 'CUDA' for s in specs)


def verify_cuda(directory, manifest):
    path = Path(directory) / 'cpd_plugin/CUDACpdDNA2.so'
    if not manifest.get('cuda_plugin_sha256') or not path.is_file():
        raise ValueError('This frozen CPD package has no CUDA plugin. Create a GPU continuation or copy with GPU settings.')
    if digest(path) != manifest['cuda_plugin_sha256']:
        raise ValueError('Frozen CPD CUDA plugin changed')


def add_cuda(directory, manifest, plugin):
    """Attach the installed CUDA implementation to a newly prepared/copied package."""
    directory, plugin = Path(directory), Path(plugin)
    build = json.loads((plugin / 'build.json').read_text())
    binary = plugin / 'CUDACpdDNA2.so'
    if not binary.is_file() or digest(binary) != build.get('cuda_plugin_sha256'):
        raise ValueError('Build CUDA CPD support with python tools/oxdna_cpd/build.py before selecting GPU.')
    sources = Path(__file__).resolve().parents[2] / 'tools/oxdna_cpd'
    if digest(sources / 'CUDACpdDNA2.cu') != build.get('cuda_source_sha256') or digest(sources / 'build_cuda.py') != build.get('cuda_builder_sha256'):
        raise ValueError('Rebuild the changed CPD CUDA plugin with python tools/oxdna_cpd/build.py.')
    shutil.copy2(binary, directory / 'cpd_plugin/CUDACpdDNA2.so')
    (directory / 'cpd_plugin/cuda_build.json').write_text(json.dumps(build, indent=2)+'\n')
    manifest['cuda_plugin_sha256'] = build['cuda_plugin_sha256']
    manifest['cuda_build_sha256'] = digest(directory / 'cpd_plugin/cuda_build.json')
    manifest['backends'] = ['CPU', 'CUDA']
    return manifest
