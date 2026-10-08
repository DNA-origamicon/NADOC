"""Occupied source-lattice addresses, independent of the displayed deformation."""
from types import SimpleNamespace
import re

from backend.core.extrude_plane import resolve_extrude_plane


def occupied_lattice_cells(design, plane, *, frame_id=None):
    frames = {f.id: f for f in getattr(design, 'lattice_frames', ())}
    cells = set()
    for helix in getattr(design, 'helices', ()):
        address = re.match(r'^h_(XY|XZ|YZ)_(-?\d+)_(-?\d+)(?:_|$)', helix.id)
        cell = helix.grid_pos
        if cell is None and address:
            cell = (int(address[2]), int(address[3]))
        if cell is None or (frame_id is not None and helix.lattice_frame_id != frame_id):
            continue
        frame = frames.get(helix.lattice_frame_id)
        source_plane, reason = ((frame.plane, 'geometry') if frame else
                                resolve_extrude_plane(SimpleNamespace(helices=[helix])))
        if reason == 'geometry' and source_plane == plane:
            cells.add(tuple(cell))
    return cells


def require_vacant_lattice_cells(design, cells, plane, *, frame_id=None):
    conflicts = set(map(tuple, cells)) & occupied_lattice_cells(design, plane, frame_id=frame_id)
    if conflicts:
        raise ValueError(f'Painted cells already occupied on {plane}: {sorted(conflicts)}')
