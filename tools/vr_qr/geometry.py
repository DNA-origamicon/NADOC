"""Camera/marker transforms. Distances are metres, QR axes are right/up/out."""
import re
import time
from urllib.parse import urlparse, parse_qs

import numpy as np


def marker_spec(data):
    """Return printed width and marker-from-anchor; never log invitation tokens."""
    if data.startswith('NADOC-CUBE:1:'):
        fields = data.split(':')
        if len(fields) != 6:
            return None
        try:
            face, edge, width, relief = int(fields[2]), float(fields[3]), float(fields[4]), float(fields[5])
        except ValueError:
            return None
        if not (0 <= face < 6 and 20 <= width <= edge <= 300 and 0 <= relief <= 10):
            return None
        # Columns: face-local right, up, outward normal, in cube coordinates.
        bases = [([1, 0, 0], [0, 1, 0], [0, 0, 1]), ([-1, 0, 0], [0, 1, 0], [0, 0, -1]),
                 ([0, 0, -1], [0, 1, 0], [1, 0, 0]), ([0, 0, 1], [0, 1, 0], [-1, 0, 0]),
                 ([1, 0, 0], [0, 0, -1], [0, 1, 0]), ([1, 0, 0], [0, 0, 1], [0, -1, 0])]
        cube_from_marker = np.eye(4)
        cube_from_marker[:3, :3] = np.array(bases[face]).T
        cube_from_marker[:3, 3] = np.array(bases[face][2]) * (edge / 2 + relief) / 1000
        return width / 1000, np.linalg.inv(cube_from_marker)
    try:
        url = urlparse(data)
        p = parse_qs(url.fragment)
        if url.scheme not in ('http', 'https') or p.get('entry') != ['qr'] or p.get('role') == ['presenter']:
            return None
        if not re.fullmatch('[a-f0-9]{64}', p.get('invite', [''])[0]):
            return None
        if not re.fullmatch('(?:[a-f0-9]{32}|default)', p.get('room', [''])[0]):
            return None
        size = float(p.get('qrmm', ['40'])[0]) / 1000
        return (size, np.eye(4)) if .02 <= size <= 1 else None
    except (ValueError, IndexError):
        return None


def solve_marker(cv, corners, modules, printed_width, intrinsic):
    """Solve square pose from unwarped pixels; reject bad reprojection and back faces."""
    half = printed_width * modules / (modules + 8) / 2
    obj = np.array([[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]], np.float64)
    pixels = np.asarray(corners, np.float64).reshape(4, 2)
    if abs(cv.contourArea(pixels.astype(np.float32))) < 900:
        return None
    result = cv.solvePnPGeneric(obj, pixels, intrinsic, None, flags=cv.SOLVEPNP_IPPE_SQUARE)
    if not result[0]:
        return None
    candidates = []
    for rvec, tvec in zip(result[1], result[2]):
        rotation = cv.Rodrigues(rvec)[0]
        if tvec[2, 0] <= .05 or tvec[2, 0] > 5 or np.dot(rotation[:, 2], tvec[:, 0]) >= 0:
            continue
        projected = cv.projectPoints(obj, rvec, tvec, intrinsic, None)[0].reshape(4, 2)
        error = np.sqrt(np.mean(np.sum((projected - pixels) ** 2, axis=1)))
        if not np.isfinite(error) or error > 2:
            continue
        matrix = np.eye(4); matrix[:3, :3] = rotation; matrix[:3, 3] = tvec[:, 0]
        # OpenCV: right/down/forward. OpenVR camera: right/up/backward.
        matrix = np.diag([1., -1., -1., 1.]) @ matrix
        candidates.append((error, matrix))
    return min(candidates, key=lambda p: p[0])[1] if candidates else None


class StableAnchor:
    """Require consecutive stationary-head observations, reset on loss/mismatch."""
    def __init__(self, count=12):
        self.count = count
        self.reset()

    def reset(self):
        self.samples = []
        self.heads = []
        self.identity = None
        self.since = None

    def update(self, identity, pose, head, timestamp=None):
        timestamp = time.monotonic() if timestamp is None else timestamp
        if pose is None or head is None or not np.isfinite(pose).all() or not np.isfinite(head).all():
            self.reset(); return None
        def close(a, b, distance, degrees):
            cosine = np.clip((np.trace(a[:3, :3].T @ b[:3, :3]) - 1) / 2, -1, 1)
            return np.linalg.norm(a[:3, 3] - b[:3, 3]) <= distance and np.arccos(cosine) <= np.deg2rad(degrees)
        if self.samples and (identity != self.identity or not close(pose, self.samples[0], .015, 3) or not close(head, self.heads[0], .006, 1.5)):
            self.reset()
        if self.since is None:
            self.since = timestamp
        self.identity = identity
        self.samples.append(pose); self.heads.append(head)
        if len(self.samples) < self.count or timestamp - self.since < .8:
            return None
        value = pose.copy()
        value[:3, 3] = np.median([p[:3, 3] for p in self.samples], axis=0)
        self.reset()
        return value
