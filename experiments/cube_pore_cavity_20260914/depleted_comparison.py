"""Compare the two branches at equal elapsed time, preserving their limitations."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parent
data = json.loads((root / 'control_analysis.json').read_text())
initial = json.loads((root / 'open_pore/fill_92_npzat/initial_hydration.json').read_text())
result = {
    'parent_checkpoint_time_ps': 156,
    'comparison_elapsed_ps': 200,
    'initial': initial,
    'branches': {},
    'limitations': [
        'Single stochastic continuation in each condition; no independent replicates.',
        'NVT uses CPU integration/GPU force offload after the source GPU-resident run failed; NPzAT uses GPU-resident integration.',
        'Both branches use the same 4 A patch margin, force field, composition, restraints, and immutable starting coordinates, velocities, and cell.',
        'Grid void volumes are geometric diagnostics; connected components are not stitched across periodic boundaries.',
    ],
}
hashes = {}
for name in ['fill_92_nvt_offload', 'fill_92_npzat']:
    directory = root / 'open_pore' / name
    hashes[name] = {
        ext: hashlib.sha256((directory / ('start.' + ext)).read_bytes()).hexdigest()
        for ext in ['coor', 'vel', 'xsc']
    }
    frames = data[name]['frames']
    matched = [frame for frame in frames if abs(frame['time_ps'] - 200) < 1e-6]
    common_tail = [frame for frame in frames if 150 < frame['time_ps'] <= 200]
    result['branches'][name] = {
        'matched_200ps': matched[0] if matched else None,
        'last_saved_frame': frames[-1],
        'mean_void_last_50ps_of_common_window_nm3': (
            sum(frame['total_water_void_nm3'] for frame in common_tail) / len(common_tail)
            if matched else None
        ),
    }
result['starting_binary_files_identical'] = hashes['fill_92_nvt_offload'] == hashes['fill_92_npzat']
assert result['starting_binary_files_identical']
result['starting_sha256'] = hashes['fill_92_npzat']
(root / 'depleted_comparison.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
