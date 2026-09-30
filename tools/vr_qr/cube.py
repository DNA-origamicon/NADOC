"""Learn a stationary five-plate cube independently of QR IDs and quarter turns."""
import json
import os
from pathlib import Path

import numpy as np

from tools.vr_qr.geometry import marker_spec

# Same display order as the conventional cube: front, back, right, left, top, bottom.
NORMALS = np.array([[0, 0, 1], [0, 0, -1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]])


def cube_spec(data):
    if not data.startswith('NADOC-CUBE:1:') or marker_spec(data) is None:
        return None
    fields = data.split(':')
    return int(fields[2]), tuple(float(v) / 1000 for v in fields[3:])


def rigid(pose):
    pose = np.asarray(pose, dtype=float)
    return (pose.shape == (4, 4) and np.isfinite(pose).all()
            and np.allclose(pose[3], [0, 0, 0, 1])
            and np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), atol=1e-4)
            and abs(np.linalg.det(pose[:3, :3]) - 1) < 1e-4)


def calibration_path():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'nadoc/qr-cube-calibration.json'


class CubeMapping:
    def __init__(self):
        self.stage_from_cube = None
        self.dimensions = None
        self.faces = {}
        self.message = 'Keep cube fixed; scan all five QR faces'

    @property
    def complete(self):
        return set(self.faces) == set(range(5))

    def preview_pose(self, data, stage_from_marker):
        spec = cube_spec(data)
        if spec is None or spec[0] >= 5 or not rigid(stage_from_marker):
            return None
        pose = stage_from_marker.copy()
        edge, _, plate = spec[1]
        pose[:3, 3] -= pose[:3, 2] * (edge / 2 + plate)
        return pose

    def accept(self, data, stage_from_marker):
        """Accept only a pose that has already passed the stationary acquisition gate."""
        spec = cube_spec(data)
        center = self.preview_pose(data, stage_from_marker)
        if center is None:
            self.message = 'Use one of the five exported cube QR plates'
            return False
        face, dimensions = spec
        if self.dimensions is not None and dimensions != self.dimensions:
            self.message = 'Cube size differs; scan the same cube'
            return False
        if self.stage_from_cube is None:
            self.stage_from_cube = center
            self.dimensions = dimensions
        # Moving the cube invalidates the whole session, rather than combining
        # poses captured at different physical locations into an apparently good map.
        if np.linalg.norm(center[:3, 3] - self.stage_from_cube[:3, 3]) > .012:
            self.faces.clear()
            self.stage_from_cube = None
            self.dimensions = None
            self.message = 'Cube moved or plate off-center; restart scans with cube fixed'
            return False
        cube_from_marker = np.linalg.inv(self.stage_from_cube) @ stage_from_marker
        scores = NORMALS @ cube_from_marker[:3, 2]
        slot = int(np.argmax(scores))
        if scores[slot] < np.cos(np.deg2rad(8)):
            self.faces.pop(face, None)
            self.message = 'Face angle uncertain; keep cube fixed and rescan'
            return False
        if any(other != face and entry['slot'] == slot for other, entry in self.faces.items()):
            self.message = 'Two QR IDs on one face; check placement and rescan'
            return False
        previous = self.faces.get(face)
        rotation_changed = previous and np.trace(np.asarray(previous['marker_from_cube'])[:3, :3] @ cube_from_marker[:3, :3]) < 1 + 2 * np.cos(np.deg2rad(8))
        if previous and (previous['slot'] != slot or rotation_changed):
            self.faces.clear()
            self.stage_from_cube = None
            self.dimensions = None
            self.message = 'Cube rotated; restart scans with cube fixed'
            return False
        self.faces[face] = {'slot': slot, 'marker_from_cube': np.linalg.inv(cube_from_marker).tolist()}
        self.message = f'{len(self.faces)}/5 faces calibrated; scan red faces'
        return True

    def states(self):
        states = [0] * 6
        for entry in self.faces.values():
            states[entry['slot']] = 1
        if self.complete:
            states = [state if state else -1 for state in states]  # Unmarked support face.
        return states

    def save(self, path=None):
        if not self.complete:
            raise ValueError('Scan all five faces before saving')
        path = calibration_path() if path is None else Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {'version': 1, 'dimensions': self.dimensions, 'faces': self.faces}
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, indent=2) + '\n')
        os.replace(temp, path)


def load_mapping(path=None):
    """Load only complete, geometrically valid mappings; never load room poses."""
    try:
        path = calibration_path() if path is None else Path(path)
        data = json.loads(path.read_text())
        if data['version'] != 1 or set(data['faces']) != set(map(str, range(5))):
            return None
        dimensions = tuple(data['dimensions'])
        if len(dimensions) != 3:
            return None
        edge, width, plate = dimensions
        if not marker_spec(f'NADOC-CUBE:1:0:{edge*1000}:{width*1000}:{plate*1000}'):
            return None
        slots = set()
        for entry in data['faces'].values():
            slot = entry['slot']
            matrix = np.asarray(entry['marker_from_cube'], dtype=float)
            if type(slot) is not int or not 0 <= slot < 6 or slot in slots or not rigid(matrix):
                return None
            cube_from_marker = np.linalg.inv(matrix)
            expected = cube_from_marker[:3, 2] * (edge / 2 + plate)
            if np.linalg.norm(cube_from_marker[:3, 3] - expected) > .012:
                return None
            if np.dot(NORMALS[slot], cube_from_marker[:3, 2]) < np.cos(np.deg2rad(8)):
                return None
            slots.add(slot)
        return data
    except (OSError, ValueError, TypeError, KeyError, np.linalg.LinAlgError):
        return None


def mapped_marker_spec(data, mapping):
    spec = cube_spec(data)
    if spec is None or mapping is None:
        return marker_spec(data)
    face, dimensions = spec
    if not np.allclose(dimensions, mapping['dimensions'], rtol=0, atol=1e-9):
        return None
    entry = mapping['faces'].get(str(face))
    return (dimensions[1], np.asarray(entry['marker_from_cube'])) if entry else None
