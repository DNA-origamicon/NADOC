"""Read-only, restart-aware PEG trajectory snapshots, including growing DCDs."""
import struct

import numpy as np

from backend.core.dcd_fast import UnsupportedDCD, read_frame, read_layout
from backend.core.namd_peg_evidence import continuation_epochs


def frame_index(package, stage, atoms):
    """Discard abandoned futures at each restart, even before its first frame exists."""
    selected = {}
    for epoch, _, path, start in continuation_epochs(package, stage):
        if epoch:
            selected = {step: ref for step, ref in selected.items() if step <= start}
        if not path.exists():
            continue
        try:
            layout = read_layout(path)
        except (UnsupportedDCD, struct.error):
            # A growing file may not yet have a full header. Corrupt full headers
            # should surface as errors instead of displaying a misleading snapshot.
            if path.stat().st_size < 276:
                continue
            raise ValueError(f'Unreadable PEG trajectory: {path.name}') from None
        if layout.n_atoms != atoms or layout.nsavc <= 0:
            raise ValueError(f'PEG trajectory layout does not match saved atoms: {path.name}')
        for i in range(layout.n_frames):
            step = layout.istart + i * layout.nsavc
            if not epoch or step > start:
                selected[step] = (path, layout, i)
    return sorted(selected.items())


def sampled_frames(index, max_frames):
    if not 1 <= max_frames <= 200:
        raise ValueError('PEG frame limit must be between 1 and 200')
    if not index:
        return []
    picks = [len(index)-1] if max_frames == 1 else np.unique(
        np.linspace(0, len(index)-1, min(max_frames, len(index)), dtype=int))
    result = []
    for pick in picks:
        step, (path, layout, i) = index[pick]
        xyz = read_frame(path, layout, int(i))[0]
        if not np.isfinite(xyz).all():
            raise ValueError(f'Nonfinite PEG coordinates in {path.name}, step {step}')
        result.append(dict(step=int(step), coordinates_nm=(xyz/10).tolist()))
    return result
