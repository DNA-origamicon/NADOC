#!/usr/bin/env python3
"""Pack bulky experiment summaries losslessly; verify against a compact hash index.

Run from any directory. --pack replaces plain summaries only after validating
compressed bytes. --check verifies existing indexed artifacts without writing.
No Git history or external storage is changed.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ('exp59_kimmdy_extra_base_matrix', 'exp60_extra_vs_native_photoproducts')
INDEX = ROOT / 'experiments/summary_artifacts.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pack():
    previous = json.loads(INDEX.read_text())['artifacts'] if INDEX.exists() else []
    records = {row['path']: row for row in previous}
    for campaign in CAMPAIGNS:
        directory = ROOT / 'experiments' / campaign / 'results/jobs'
        paths = {p.with_suffix('') if p.suffix == '.gz' else p
                 for p in directory.glob('*/summary.json*') if p.name in ('summary.json', 'summary.json.gz')}
        for path in sorted(paths):
            raw = (path.read_bytes() if path.exists() else
                   gzip.decompress(path.with_suffix('.json.gz').read_bytes()))
            report = json.loads(raw)
            compressed = gzip.compress(raw, mtime=0)
            target = path.with_suffix('.json.gz')
            target.write_bytes(compressed)
            if gzip.decompress(target.read_bytes()) != raw:
                raise ValueError(f'Archive verification failed: {target}')
            rel = str(target.relative_to(ROOT))
            records[rel] = dict(path=rel, sha256=digest(raw), bytes=len(raw),
                                compressed_bytes=len(compressed), pairs=len(report.get('pairs', [])))
            # The validated archive is an exact replacement, including whitespace.
            path.unlink(missing_ok=True)
    payload = dict(format='gzip; sha256 covers original JSON bytes',
                   artifacts=sorted(records.values(), key=lambda row: row['path']))
    INDEX.write_text(json.dumps(payload, indent=2) + '\n')


def check():
    records = json.loads(INDEX.read_text())['artifacts']
    for row in records:
        path = (ROOT / row['path']).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Artifact path escapes repository')
        compressed = path.read_bytes()
        raw = gzip.decompress(compressed)
        if digest(raw) != row['sha256'] or len(raw) != row['bytes']:
            raise ValueError(f'Artifact mismatch: {path}')
        if len(compressed) != row['compressed_bytes']:
            raise ValueError(f'Compressed size mismatch: {path}')
        json.loads(raw)
    print(f"Verified {len(records)} artifacts: "
          f"{sum(r['bytes'] for r in records):,} original bytes -> "
          f"{sum(r['compressed_bytes'] for r in records):,} compressed bytes")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--pack', action='store_true')
    modes.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.pack:
        pack()
    check()
