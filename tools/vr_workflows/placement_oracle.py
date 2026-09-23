"""Forward-project saved canonical placement to the applied tracking pose.

Independent of native inverse-placement code. Units are explicit at the boundary;
normalization/presentation are observation data, never authored geometry inputs.
"""
import math
import numpy as np


def rotation(q):
    q = np.asarray(q, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q)-1) > .001:
        raise ValueError('invalid XYZW rotation')
    x,y,z,w = q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def vector(value):
    value = np.asarray(value, dtype=float)
    if value.shape != (3,) or not np.isfinite(value).all():
        raise ValueError('invalid finite 3-vector')
    return value


def compare(presentation, applied_pose, cluster, plane):
    """Require saved origin and all orientation axes to reproduce the captured pose."""
    matrix = np.asarray(presentation['model_to_tracking_rows'],dtype=float)
    if (matrix.shape != (4,4) or not np.isfinite(matrix).all() or
            not np.allclose(matrix[3],[0,0,0,1],atol=1e-7,rtol=0)):
        raise ValueError('invalid presentation matrix')
    linear = matrix[:3,:3]
    scale = np.linalg.norm(linear[:,0])
    if scale < 1e-8:
        raise ValueError('degenerate presentation')
    view_rotation = linear/scale
    if (not np.allclose(view_rotation.T@view_rotation,np.eye(3),atol=1e-4,rtol=0)
            or np.linalg.det(view_rotation) < 0):
        raise ValueError('presentation must be a proper uniform similarity')
    normalization = float(presentation['normalization_model_per_nm'])
    if not math.isfinite(normalization) or normalization <= 0:
        raise ValueError('invalid normalization')
    if np.linalg.norm(vector(cluster['pivot'])) > 1e-8 or cluster.get('parent_cluster_id'):
        raise ValueError('freeform placement must have zero pivot and no parent')
    source_origin = vector(cluster['translation'])
    normalized = ((source_origin-vector(presentation['source_center_nm']))*normalization
                  + vector(presentation['normalized_offset_model']))
    projected = linear@normalized + matrix[:3,3]
    # Canonical axial direction maps to controller -Z; retain the transverse axes.
    alignment = {
        'XY':np.diag([-1,1,-1]),
        'XZ':np.array([[1,0,0],[0,0,1],[0,-1,0]]),
        'YZ':np.array([[0,0,1],[0,1,0],[-1,0,0]]),
    }[plane]
    expected_axes = rotation(applied_pose['orientation_xyzw'])@alignment
    projected_axes = view_rotation@rotation(cluster['rotation'])
    delta = expected_axes.T@projected_axes
    angular_error = math.degrees(math.acos(float(np.clip((np.trace(delta)-1)/2,-1,1))))
    position_error = float(np.linalg.norm(projected-vector(applied_pose['position']))*1000)
    return {'passed':position_error <= .1 and angular_error <= .05,
            'position_error_mm':position_error,'orientation_error_deg':angular_error,
            'position_tolerance_mm':.1,'orientation_tolerance_deg':.05,
            'projected_origin_m':projected.tolist(),
            'scope':'saved cluster forward projection versus actual captured controller pose'}


def check_design(capture, design):
    frame = design['lattice_frames'][-1]
    cluster = next(c for c in design['cluster_transforms'] if c['id']==frame['placement_cluster_id'])
    if not capture['state']['extrude']['freeform_placed']:
        raise ValueError('freeform pose was not captured')
    return compare(capture['state']['presentation'],capture['actual_capture_pose'],cluster,frame['plane'])


if __name__ == '__main__':
    import json
    import sys
    from pathlib import Path
    verdict = check_design(json.loads(Path(sys.argv[1]).read_text()),json.load(sys.stdin))
    print(json.dumps(verdict))
    raise SystemExit(0 if verdict['passed'] else 1)
