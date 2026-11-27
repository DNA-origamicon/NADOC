"""Check whether q=0 hides non-native interstrand bonds in saved production frames."""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np

from backend.core.oxdna_vmmc import duplex_pairs
from tools.oxdna_umbrella.native import digest


def audit(directory, binary, output_name='pairing_audit'):
    directory, binary = Path(directory).resolve(), Path(binary).resolve()
    manifest = json.loads((directory/'manifest.json').read_text())
    candidates = [binary.parent.parent/'src/liboxdna_common.so', binary.parent.parent/'lib/liboxdna_common.so']
    if not any(p.exists() and digest(p) == manifest['library_sha256'] for p in candidates):
        raise ValueError('Audit must use the sampling engine')
    if not output_name.isidentifier():
        raise ValueError('Audit output name must be a simple identifier')
    output = directory/output_name
    output.mkdir(exist_ok=False)
    root = directory/'inputs'
    native_pairs = {tuple(sorted(pair)) for pair in duplex_pairs(root/'topology.top')}
    strands = [int(line.split()[0]) for line in (root/'topology.top').read_text().splitlines()[1:]]
    protocol = manifest['protocol']
    rows = []
    for i in range(protocol['walkers']):
        source = directory/'production'/f'replica_{i}'
        destination = output/f'replica_{i}'
        destination.mkdir()
        text = (source/'input.txt').read_text().split('data_output_1 =')[0]
        text = text.replace('external_forces = true', 'external_forces = false')
        text = text.replace('trajectory_file = trajectory.dat', f"trajectory_file = {source/'trajectory.dat'}")
        text += '''analysis_data_output_1 = {
name = all_hb.dat
print_every = 1
col_1 = { type = hb_list }
}
'''
        (destination/'input.txt').write_text(text)
        with (destination/'native.log').open('w') as log:
            subprocess.run([str(binary), 'input.txt'], cwd=destination, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        recorded = {int(row[0]): int(row[2]) for row in np.loadtxt(source/'samples.dat')}
        samples, seen = [], set()
        for frame in (destination/'all_hb.dat').read_text().split('# step ')[1:]:
            lines = frame.splitlines()
            step = int(lines[0])
            if step in seen or not protocol['equil_steps'] <= step < protocol['equil_steps']+protocol['production_steps']:
                continue
            seen.add(step)
            pairs = {tuple(sorted(map(int, line.split()))) for line in lines[1:] if line.strip()}
            native = len(pairs & native_pairs)
            if recorded[step] != native:
                raise ValueError('Native pairing count does not match saved sampling output')
            inter = sum(strands[a] != strands[b] for a, b in pairs)
            samples.append([step, native, inter, len(pairs)-inter])
        data = np.asarray(samples)
        np.savetxt(destination/'counts.csv', data, fmt='%d', delimiter=',', header='step,native_pairs,interstrand_pairs,intrastrand_pairs')
        rows.append({'replica': i, 'frames': len(data), 'q0_frames': int(np.sum(data[:, 1] == 0)),
                     'q0_with_interstrand_bonds': int(np.sum((data[:, 1] == 0) & (data[:, 2] > 0))),
                     'trajectory_sha256': digest(source/'trajectory.dat')})
    result = {'replicas': rows, 'qualification': 'Biased saved-frame counts, not equilibrium fractions.'}
    (output/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    p.add_argument('--binary', required=True)
    p.add_argument('--output-name', default='pairing_audit')
    args = p.parse_args()
    audit(args.directory, args.binary, args.output_name)
