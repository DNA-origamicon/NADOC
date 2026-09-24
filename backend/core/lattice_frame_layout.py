"""Collision-free 2D layout of explicit lattice frames for legacy grid consumers.

Offsets are multiples of six rows: both square parity and honeycomb row phase
remain unchanged. Original local addresses remain on the helices themselves.
"""
import math


def packed_frame_cells(helices):
    groups = {}
    for helix in helices:
        if helix.grid_pos is None:
            raise ValueError('frame layout requires explicit cell addresses')
        groups.setdefault(helix.lattice_frame_id, []).append(helix)
    result = {}
    cursor = None
    for group in groups.values():
        cells = [h.grid_pos for h in group]
        if len(set(cells)) != len(cells):
            raise ValueError('multiple segments on one frame cell need segment consolidation')
        minimum = min(row for row, col in cells)
        shift = 0 if cursor is None else max(0, math.ceil((cursor-minimum)/6)*6)
        for helix in group:
            row, col = helix.grid_pos
            result[helix.id] = (row+shift, col)
        cursor = max(row+shift for row, col in cells)+6
    return result
