"""Explicit synthetic operator strategy, not a learned human motion estimate."""
import math
from tools.vr_motion.model import vector
from tools.vr_motion.metrics import dot, norm, sub, rotate


def control_approach(target, controller):
    """Aim from 30cm along the rectangle normal, on the current hand's side.

    The caller must reach this position through the unchanged noisy trajectory;
    it is never an applied teleport or an endpoint correction.
    """
    center = vector(target['position'],3)
    hand = vector(controller,3)
    r = vector(target['hit_half_right'],3)
    u = vector(target['hit_half_up'],3)
    normal = [r[1]*u[2]-r[2]*u[1], r[2]*u[0]-r[0]*u[2], r[0]*u[1]-r[1]*u[0]]
    length = norm(normal)
    if not math.isfinite(length) or length < 1e-10:
        raise ValueError('degenerate control rectangle')
    side = dot(sub(hand,center),normal)
    if abs(side/length) < 1e-6:
        raise ValueError('controller lies in target plane; approach side unknown')
    scale = (.3 if side > 0 else -.3)/length
    return [p+n*scale for p,n in zip(center,normal)]


def lattice_approach(panel, cell_position, controller):
    """Apply the same approach to a cell; these axes do not define its hit area."""
    orientation = panel['panel_orientation_xyzw']
    return control_approach({
        'position': cell_position,
        'hit_half_right': rotate(orientation,[1,0,0]),
        'hit_half_up': rotate(orientation,[0,1,0]),
    }, controller)
