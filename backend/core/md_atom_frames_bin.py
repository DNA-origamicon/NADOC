"""Lossless float64 aligned coordinates in sparse simulation-serial order."""
import struct
import numpy as np


def md_frames_atomistic_bin(topology, segments, coordinate, design, indices,
                            max_frames=200, stride=None):
    from backend.core.md_trajectory import (
        _build_playback_ctx, _extract_md_atoms_frame, composite_raw_frame_map,
    )
    ctx = _build_playback_ctx(topology, [s[2] for s in segments], coordinate, design,
                              with_atoms=True)
    raw = composite_raw_frame_map(segments, max_frames, stride)
    indices = sorted({int(i) for i in indices if 0 <= int(i) < len(raw)})
    serials = ctx['heavy_idx']
    nserials = int(serials.max()) + 1 if len(serials) else 0
    # Ship only real heavy atoms. Serial gaps are restored by the browser; no
    # coordinate precision is reduced and no solvent/hydrogen placeholders travel.
    out = bytearray(struct.pack('<6I', 0x4D444146, 2, len(indices), nserials, len(serials), 0))
    out.extend(np.asarray(serials, dtype='<u4').tobytes())
    out.extend(b'\0' * ((-len(out)) % 8))
    from backend.core.md_read_ahead import read_ahead

    with read_ahead(ctx, [raw[i] for i in indices]):
        for index in indices:
            out.extend(struct.pack('<2I', index, 0))
            xyz = _extract_md_atoms_frame(ctx, raw[index], positions_only=True)
            out.extend(np.asarray(xyz, dtype='<f8').tobytes())
    return bytes(out)
