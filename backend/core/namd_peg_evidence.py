"""Strict, restart-aware PEG energy/trajectory pairing without guessed columns."""
from pathlib import Path
import re

import numpy as np

from backend.core.dcd_fast import read_frame, read_layout

REQUIRED = {'TS', 'POTENTIAL', 'TOTAL', 'TEMP', 'BOUNDARY', 'MISC'}


def read_energy_logs(paths):
    """Resolve a verified common ETITLE, including rows before a delayed header.

    Never guess a schema or silently drop malformed/nonfinite energy records.
    Return separate epochs: identical timesteps across restarts are not identical states.
    """
    texts = [Path(p).read_text(errors='replace') for p in paths]
    headers = [tuple(line.split()[1:]) for text in texts for line in text.splitlines()
               if line.startswith('ETITLE:')]
    if not headers or not REQUIRED <= set(headers[0]) or len(set(headers[0])) != len(headers[0]):
        raise ValueError('energy_schema: missing or invalid ETITLE column schema')
    columns = headers[0]
    if any(h != columns for h in headers):
        raise ValueError('energy_schema: incompatible ETITLE schemas across continuations')
    epochs = []
    for path, text in zip(paths, texts):
        rows = {}
        for number, line in enumerate(text.splitlines(), 1):
            if not line.startswith('ENERGY:'):
                continue
            try:
                values = list(map(float, line.split()[1:]))
                if len(values) != len(columns) or not np.isfinite(values).all():
                    raise ValueError()
                row = dict(zip(columns, values)); step = int(row['TS'])
                if step != row['TS'] or step < 0 or (rows and step <= max(rows)):
                    raise ValueError()
            except (ValueError, OverflowError):
                raise ValueError(f'energy_records: malformed, nonfinite or nonmonotone row at {Path(path).name}:{number}') from None
            rows[step] = row
        epochs.append(rows)
    return epochs, texts


def continuation_epochs(package, segment):
    """Numeric suffix order survives copies, restores and touched file timestamps."""
    package = Path(package)
    epochs = [(0, package/f'{segment}.log', package/'output'/f'{segment}.dcd', 0)]
    for log in package.glob(f'{segment}.resume*.log'):
        match = re.fullmatch(re.escape(segment)+r'\.resume(\d+)\.log', log.name)
        if not match:
            raise ValueError(f'continuation_lineage: invalid log name {log.name}')
        number = int(match[1])
        conf = (package/f'{segment}.resume{number}.conf').read_text()
        starts = re.findall(r'^\s*firsttimestep\s+(\d+)\s*$', conf, re.M)
        if len(starts) != 1:
            raise ValueError(f'continuation_lineage: missing/ambiguous firsttimestep in resume{number}')
        epochs.append((number, log, package/'output'/f'{segment}.cont{number}.dcd', int(starts[0])))
    return sorted(epochs)


def pair_samples(epoch_frames, epoch_rows, starts):
    """Rollback abandons the old future; pair a frame only with its own epoch's energy."""
    selected = {}
    for frames, rows, start in zip(epoch_frames, epoch_rows, starts):
        selected = {s: v for s, v in selected.items() if s <= start}
        for step, xyz in frames.items():
            if step > start:
                selected[step] = (xyz, rows.get(step))
    return selected


def segment_evidence(package, segment, atoms):
    epochs = continuation_epochs(package, segment)
    rows, texts = read_energy_logs([e[1] for e in epochs])
    frames = []
    for _, _, path, _ in epochs:
        layout = read_layout(path)
        if layout.n_atoms != atoms:
            raise ValueError(f'trajectory_atoms: expected {atoms}, got {layout.n_atoms} in {path.name}')
        frames.append({layout.istart+i*layout.nsavc: read_frame(path, layout, i)[0]
                       for i in range(layout.n_frames)})
    samples = pair_samples(frames, rows, [e[3] for e in epochs])
    return samples, texts[-1], [e[1].name for e in epochs]
