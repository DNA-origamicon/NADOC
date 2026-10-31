"""Isolated own-sugar piercing repair with native C3' stereochemistry.

Only an already pierced internal terminal-tail O3'-P bond is considered.
Hold its C3'-O3' direction at the stamped native direction; constrain all four
bridge bond lengths to the existing canonical values and fit the three bridge
angles. This changes no sugar, base, attachment-root or clear-link coordinates.
There are no production callers. An atomic refusal retains the current linker.
"""

from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize

from backend.core import atomistic, atomistic_minimisers
from backend.core.ring_piercing import SUGAR_RING, segment_pierces_ring


def fixed_native_exit(c3, c5, native_o3, initial):
    """Exact bond lengths; native C3' chirality; remaining angles fitted."""
    mm = atomistic_minimisers
    direction = native_o3 - c3
    if np.linalg.norm(direction) < 1e-12:
        return None
    o3 = c3 + direction / np.linalg.norm(direction) * mm._CANON_C3O3

    def cosine(a, b, c):
        u, v = a - b, c - b
        return np.dot(u, v) / max(np.linalg.norm(u) * np.linalg.norm(v), 1e-24)

    def objective(x):
        p, o5 = x[:3], x[3:]
        return sum((cosine(*points) - np.cos(angle * mm._DEG2RAD)) ** 2
                   for points, angle in (((c3, o3, p), mm._CANON_C3O3P),
                                         ((o3, p, o5), mm._CANON_O3PO5),
                                         ((p, o5, c5), mm._CANON_PO5C5)))

    def constraints(x):
        p, o5 = x[:3], x[3:]
        return np.array([np.dot(p - o3, p - o3) - mm._CANON_O3P ** 2,
                         np.dot(o5 - p, o5 - p) - mm._CANON_PO5 ** 2,
                         np.dot(c5 - o5, c5 - o5) - mm._CANON_O5C5 ** 2])

    result = minimize(objective, initial, method="SLSQP",
                      constraints={"type": "eq", "fun": constraints},
                      options={"ftol": 1e-12, "maxiter": 200})
    if not result.success or not np.isfinite(result.x).all():
        return None
    p, o5 = result.x[:3], result.x[3:]
    lengths = np.array([np.linalg.norm(p - o3), np.linalg.norm(o5 - p), np.linalg.norm(c5 - o5)])
    if max(abs(lengths - [mm._CANON_O3P, mm._CANON_PO5, mm._CANON_O5C5])) > 1e-7:
        return None
    return o3, p, o5


def internal_tail_bridge(atoms, src, dst):
    original = atomistic_minimisers._minimize_backbone_bridge
    if "O3'" not in src or "P" not in dst or "O5'" not in dst:
        return original(atoms, src, dst)
    a, b = atoms[src["O3'"]], atoms[dst["P"]]
    if not (a.extension_id and a.extension_id == b.extension_id
            and a.strand_id == b.strand_id and abs(a.ext_k - b.ext_k) == 1
            and all(name in src for name in SUGAR_RING)):
        return original(atoms, src, dst)
    def xyz(i):
        return np.array([atoms[i].x, atoms[i].y, atoms[i].z])

    native_o3 = xyz(src["O3'"])
    original(atoms, src, dst)
    ring = np.array([xyz(src[name]) for name in SUGAR_RING])

    def self_pierced():
        return segment_pierces_ring(xyz(src["O3'"]), xyz(dst["P"]), ring)[0]

    if not self_pierced():
        return
    movable = [src["O3'"]] + [dst[n] for n in ("P", "O5'", "OP1", "OP2") if n in dst]
    previous = {i: xyz(i) for i in movable}
    result = fixed_native_exit(xyz(src["C3'"]), xyz(dst["C5'"]), native_o3,
                               np.concatenate([xyz(dst["P"]), xyz(dst["O5'"])]))
    if result is None:
        return
    o3, p, o5 = result
    delta_p = p - previous[dst["P"]]
    for i, point in ((src["O3'"], o3), (dst["P"], p), (dst["O5'"], o5)):
        atoms[i].x, atoms[i].y, atoms[i].z = point.tolist()
    for name in ("OP1", "OP2"):
        if name in dst:
            point = previous[dst[name]] + delta_p
            atoms[dst[name]].x, atoms[dst[name]].y, atoms[dst[name]].z = point.tolist()
    if self_pierced():
        for i, position in previous.items():
            atoms[i].x, atoms[i].y, atoms[i].z = position.tolist()


def build_candidate(design):
    """Diagnostic process only: retry existing internal-tail own-sugar piercings."""
    build_extensions = atomistic._build_extension_atoms

    def extensions(*args, **kwargs):
        kwargs["bridge_fn"] = internal_tail_bridge
        return build_extensions(*args, **kwargs)

    with patch.object(atomistic, "_build_extension_atoms", extensions):
        return atomistic.build_atomistic_model(design, frame_sink={})
