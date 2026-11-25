"""Compare unchanged NumPy metadata fallback and compiled integer assignment.

Read-only input. No structures or derived molecular files are authored. Run
under validation_guard.sh; timings are warm component measurements, not UI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--part', type=Path, required=True)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=21)
    args = parser.parse_args()
    if args.samples < 3:
        parser.error('At least three samples are required')
    os.environ['NADOC_NATIVE_DOMAIN_LIBRARY'] = str(args.library.resolve(strict=True))
    os.environ['NADOC_NATIVE_DOMAINS'] = '1'
    from backend.core import native_compact_geometry as compact
    from backend.core.domain_assignment import native_domains_available
    from backend.core.models import Design
    from backend.core.native_geometry_binary import pack_geometry_binary
    assert native_domains_available(), 'Compiled library could not be loaded'
    raw = args.part.read_bytes()
    design = Design.model_validate_json(raw)

    def generate(native):
        with patch.object(compact, 'native_domains_available', lambda: native):
            return compact.native_compact_geometry(design)

    baseline = generate(False)
    if baseline is None:
        parser.error('Part requires the general geometry path, outside this kernel scope')
    packet = pack_geometry_binary(baseline)
    assert packet == pack_geometry_binary(generate(True)), 'Exact transport parity failed'
    samples = {'python_numpy': [], 'cpp_metadata': []}
    for index in range(args.samples):
        for native in ((False, True) if index % 2 else (True, False)):
            start = time.perf_counter()
            generate(native)
            samples['cpp_metadata' if native else 'python_numpy'].append((time.perf_counter() - start) * 1000)
    assert args.part.read_bytes() == raw, 'Source changed during benchmark'
    print(json.dumps({'part_sha256': hashlib.sha256(raw).hexdigest(),
        'library_sha256': hashlib.sha256(args.library.read_bytes()).hexdigest(),
        'compact_packet_sha256': hashlib.sha256(packet).hexdigest(),
        'exact_compact_packet_parity': True, 'source_unchanged': True,
        'scope': 'Alternating warm component calls, GC enabled. Coordinates and native placement authority unchanged. Not application-opening latency.',
        'samples_ms': samples, 'median_ms': {k: statistics.median(v) for k, v in samples.items()}}, indent=2))


if __name__ == '__main__':
    main()
