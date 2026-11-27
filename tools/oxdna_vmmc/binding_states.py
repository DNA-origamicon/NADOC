"""Audit native versus non-native pairing in existing saved trajectories."""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np

from backend.core.oxdna_vmmc import duplex_pairs
from tools.oxdna_umbrella.native import digest


def analyse(campaign, binary, output):
    root = Path(campaign).resolve(strict=True)
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    final = json.loads((root/'result.json').read_text())
    manifest = json.loads((root/'manifest.json').read_text())
    library_hash = digest(binary.parent.parent/'lib/liboxdna_common.so')
    if library_hash != manifest['library_sha256']:
        raise ValueError('Pairing audit must use the same native library as the campaign.')
    native_pairs = {tuple(sorted(p)) for p in duplex_pairs(root/'topology.top')}
    strands = [int(row.split()[0]) for row in (root/'topology.top').read_text().splitlines()[1:]]
    paths = final.get('production_directories') or [[str(root/f'replica_{i}_block_{j:02}') for j in range(final['completed_blocks'])] for i in range(4)]
    reports = []
    for replica, row in enumerate(paths):
        samples = []
        for block, path in enumerate(row):
            source = Path(path)
            directory = output/f'replica_{replica}_block_{block:02}'
            directory.mkdir()
            text = f'''backend = CPU
interaction_type = DNA2
T = {manifest['protocol']['temperature_c']}C
salt_concentration = {manifest['salt_M']}
use_average_seq = false
seq_dep_file = {root/'oxDNA2_sequence_dependent_parameters.txt'}
topology = {root/'topology.top'}
trajectory_file = {source/'trajectory.dat'}
verlet_skin = 1
analysis_data_output_1 = {{
name = all_hb.dat
print_every = 1
col_1 = {{ type = hb_list }}
}}
'''
            (directory/'input.txt').write_text(text)
            with (directory/'native.log').open('w') as log:
                result = subprocess.run([str(binary), 'input.txt'], cwd=directory, stdout=log, stderr=subprocess.STDOUT, timeout=30)
            if result.returncode:
                raise RuntimeError((directory/'native.log').read_text()[-2000:])
            energy = {int(r[0]): int(r[-2]) for r in np.loadtxt(source/'energy.dat')}
            frames = (directory/'all_hb.dat').read_text().split('# step ')[1:]
            for frame in frames:
                lines = frame.splitlines()
                step = int(lines[0])
                pairs = {tuple(sorted(map(int, line.split()))) for line in lines[1:] if line.strip()}
                native = len(pairs & native_pairs)
                inter = sum(strands[i] != strands[j] for i, j in pairs)
                intra = len(pairs)-inter
                if native != energy[step]:
                    raise ValueError('Native pairing disagrees with the recorded order parameter.')
                samples.append([step, native, inter, intra])
            (directory/'provenance.json').write_text(json.dumps(dict(source=str(source), trajectory_sha256=digest(source/'trajectory.dat'), analysed_frames=len(frames)))+'\n')
        a = np.asarray(samples)
        q0 = a[:, 1] == 0
        reports.append(dict(replica=replica+1, frames=len(a), native_unpaired_frames=int(q0.sum()),
                            native_unpaired_with_interstrand_hb=int(np.sum(q0 & (a[:, 2] > 0))),
                            native_unpaired_with_intrastrand_hb=int(np.sum(q0 & (a[:, 3] > 0))),
                            any_non_native_interstrand_frames=int(np.sum(a[:, 2] > a[:, 1]))))
    report = dict(replicas=reports, binary=str(binary), binary_sha256=digest(binary),
                  library_sha256=library_hash,
                  qualification='Recorded biased-ensemble frame counts, not equilibrium populations. Tests whether zero native pairs actually means no interstrand hydrogen bonds at saved frames.')
    (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyse(args.campaign, args.binary.resolve(strict=True), args.output), indent=2))
