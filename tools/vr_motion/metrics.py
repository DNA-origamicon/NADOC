"""Independent geometry and measurement helpers (metres, XYZW quaternions)."""
import math
from .model import multiply, quaternion


def sub(a, b):
    return [x-y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def norm(v):
    return math.sqrt(dot(v, v))


def rotate(q, v):
    q = quaternion(q)
    return multiply(multiply(q, [*v, 0]), [-x for x in q[:3]]+[q[3]])[:3]


def pose_error(desired, observed):
    a, b = quaternion(desired['orientation']), quaternion(observed['orientation_xyzw'])
    return {'position_mm': 1000*norm(sub(desired['position'], observed['position'])),
            'angle_deg': math.degrees(2*math.acos(min(1, abs(dot(a, b)))))}


def distribution(values):
    if not values:
        raise ValueError('no measurements')
    ordered = sorted(values)
    return {'count': len(values), 'rmse': math.sqrt(sum(v*v for v in values)/len(values)),
            'p95': ordered[math.ceil(.95*len(values))-1], 'max': ordered[-1]}


def target_metrics(target, pose):
    """Ray/rectangle intersection using exported production hit-box axes."""
    r, u = target['hit_half_right'], target['hit_half_up']
    w, h = norm(r), norm(u)
    if min(w, h) <= 0:
        raise ValueError('target has no exported rectangle')
    normal = [r[1]*u[2]-r[2]*u[1], r[2]*u[0]-r[0]*u[2], r[0]*u[1]-r[1]*u[0]]
    d = rotate(pose['orientation_xyzw'], [0, 0, -1])
    offset = sub(target['position'], pose['position'])
    denominator = dot(d, normal)
    t = dot(offset, normal)/denominator if abs(denominator) > 1e-12 else None
    margin = None
    if t is not None and t >= 0:
        delta = sub([pose['position'][i]+t*d[i] for i in range(3)], target['position'])
        margin = min(w-abs(dot(delta, r)/w), h-abs(dot(delta, u)/h))
    distance = norm(offset)
    return {'width_m': 2*w, 'height_m': 2*h, 'distance_m': distance,
            'nominal_angular_width_deg': math.degrees(2*math.atan2(w, distance)),
            'nominal_angular_height_deg': math.degrees(2*math.atan2(h, distance)),
            'ray_distance_m': t, 'edge_margin_m': margin,
            'predicted_hit': margin is not None and margin >= 0}


def visibility(directory, evidence):
    """Count surviving controller fragments, including later overlay occlusion."""
    if (not evidence.get('xr_end_frame_succeeded')
            or evidence.get('controller_classes') != {'left': 4, 'right': 5}):
        raise ValueError('capture lacks submitted controller identity evidence')
    result = {}
    for eye in evidence['eyes']:
        pixels = (directory / (eye['eye']+'.classes.u8')).read_bytes()
        if len(pixels) != eye['width']*eye['height']:
            raise ValueError('invalid class buffer dimensions')
        result[eye['eye']] = {hand: pixels.count(value) for hand, value in
                              evidence['controller_classes'].items()}
    return result
