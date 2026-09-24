"""Bounded rigid source-coordinate placement for native extrusion drafts."""
import math


def validate_freeform_placement(value):
    if not isinstance(value, dict) or set(value) != {'translation_nm', 'rotation_xyzw'}:
        raise ValueError('invalid freeform placement')
    t, q = value['translation_nm'], value['rotation_xyzw']
    def vector(v, size):
        return (isinstance(v, list) and len(v) == size and
                all(type(n) in (int, float) and math.isfinite(n) for n in v))
    if not vector(t, 3) or any(abs(n) > 1e6 for n in t) or not vector(q, 4):
        raise ValueError('invalid freeform placement vector')
    norm = math.hypot(*q)
    if abs(norm-1) > 1e-3:
        raise ValueError('freeform placement requires a unit quaternion')
    return {'translation_nm':list(t), 'rotation_xyzw':[n/norm for n in q]}
