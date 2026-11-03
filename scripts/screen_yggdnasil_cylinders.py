#!/usr/bin/env python3
"""Screen the bounded straight-cylinder atlas with native traversal rules."""
import hashlib
import json
import subprocess
from screen_yggdnasil import ROOT, screen_entry


def main():
    command = "import {enumerateCylinders} from './frontend/src/design/yggdnasil_cylinders.js'; console.log(JSON.stringify(enumerateCylinders({length:100})));"
    atlas = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', command], cwd=ROOT))
    records = []
    for i, entry in enumerate(atlas['entries']):
        record = screen_entry(entry)
        record['key'] = entry['sources'][0]['key']
        record['keys'] = [s['key'] for s in entry['sources']]
        records.append(record)
        if (i + 1) % 500 == 0:
            print(f"Screened {i + 1}/{len(atlas['entries'])} cylinders", flush=True)
    sources = ['frontend/src/design/yggdnasil.js', 'frontend/src/design/yggdnasil_cylinders.js',
               'scripts/screen_yggdnasil.py', 'scripts/screen_yggdnasil_cylinders.py',
               'backend/core/seamed_router.py', 'backend/core/crossover_positions.py', 'backend/core/constants.py']
    report = {'schema': 1, 'scope': atlas['scope'] + ' Native full-period Hamiltonian helix-traversal screening only; no nucleotide-level routing certification.',
              'budget_per_footprint': 20000, 'max_scaffold': 7249, 'screened_length': 100, 'max_helices': 72,
              'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
              'records': records}
    destination = ROOT / 'frontend/src/design/yggdnasil_cylinder_routing.json'
    destination.write_text(json.dumps(report, separators=(',', ':')) + '\n')
    print({status: sum(r['status'] == status for r in records) for status in sorted({r['status'] for r in records})})
    print(f'Wrote {destination}')


if __name__ == '__main__':
    main()
