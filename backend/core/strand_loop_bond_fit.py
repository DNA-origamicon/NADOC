"""User-selected discrete bond optimum for rigid loop nucleotide display poses.

Both displayed centers stay fixed. This fits O3′–P lengths, not sterics or
chemistry; clash/piercing checks remain independent and exports stay guarded.
"""
from functools import lru_cache

import numpy as np
from scipy.spatial.transform import Rotation

ANGLES = np.arange(-180., 180., 5.)
ZERO = 36
TARGET_NM = .1600


@lru_cache(maxsize=16)
def _local_landmarks(residue, direction, loop):
    if loop:
        from backend.core.strand_loop_atoms import loop_template
        definitions, o5, frame = loop_template(residue, direction)
        xyz = {name: np.array(pos) for name, _, *pos in definitions}
    else:
        from backend.core.measured_atomistic import measured_templates
        from backend.core.native_full_placement import positions_in_native_frame
        from backend.core.native_slab_placement import _frame
        definitions = sum(measured_templates()[(direction, residue)], ())
        xyz = {name: np.array(pos) for name, _, *pos in definitions}
        o5, _, normal = positions_in_native_frame(np.zeros(3), np.array([1., 0, 0]),
                                                 np.array([0., 0, 1.]), direction == 'REVERSE')
        frame = _frame(normal, np.array([0., 0, 1.]))
    return np.array([frame.T @ (xyz[name] - o5) for name in ('P', "O3'")])


def landmarks(record, loop=False):
    """P/O3′ from the same rigid templates and native display frames as atoms."""
    base = record.get('nucleobase') or 'N'
    residue = 'D' + (base if base in 'ACGT' else 'T')
    local = _local_landmarks(residue, record['direction'], loop)
    matrix = Rotation.from_quat(record['slab_quaternion']).as_matrix()
    return local @ matrix.T + record['backbone_position']


def optimal_states(p, o3):
    """Exact finite-grid chain optimum, with each linker constrained not to grow."""
    initial = [0] + [ZERO] * (len(p) - 2) + [0]
    score = np.zeros(1)
    back = []
    for k, (left, right) in enumerate(zip(o3[:-1], p[1:])):
        distance = np.linalg.norm(left[:, None, :] - right[None, :, :], axis=2)
        limit = distance[initial[k], initial[k + 1]]
        valid = (distance <= limit + 1e-10) & (distance >= min(limit, TARGET_NM) - 1e-10)
        total = score[:, None] + np.where(valid, (distance - TARGET_NM)**2, np.inf)
        best = np.argmin(total, axis=0)
        score = total[best, np.arange(len(best))]
        if k < len(p) - 2:
            score += 1e-12 * np.deg2rad(ANGLES)**2
        back.append(best)
    if not np.isfinite(score[0]):
        raise ValueError('Loop bond fit lost its unchanged feasible state')
    selected = [0]
    for prev in reversed(back):
        selected.append(int(prev[selected[-1]]))
    return list(reversed(selected))[1:-1]


def fit_loop_bonds(anchor, inserted, following):
    """Rotate slabs about bead-to-center axes; never move centers or attachments."""
    p, o3, rotations = [], [], []
    for record, is_loop in [(anchor, False), *[(r, True) for r in inserted], (following, False)]:
        coords = landmarks(record, is_loop)
        if is_loop:
            bead = np.asarray(record['backbone_position'])
            axis = np.asarray(record['slab_position']) - bead
            axis /= np.linalg.norm(axis)
            rot = Rotation.from_rotvec(np.deg2rad(ANGLES)[:, None] * axis).as_matrix()
            states = np.einsum('kij,nj->kni', rot, coords - bead) + bead
            states[ZERO] = coords
            rotations.append(rot)
        else:
            states = coords[None]
        p.append(states[:, 0])
        o3.append(states[:, 1])
    for record, rotation, state in zip(inserted, rotations, optimal_states(p, o3)):
        matrix = rotation[state] @ Rotation.from_quat(record['slab_quaternion']).as_matrix()
        record['slab_quaternion'] = Rotation.from_matrix(matrix).as_quat().tolist()
        # Keep the geometric path tangent and radial normal unchanged. The slab
        # orientation is the independently fitted rigid nucleotide display frame.
        record['loop_bond_rotation_deg'] = float(ANGLES[state])
