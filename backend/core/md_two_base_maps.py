"""Read-only six-coordinate relative base measurements from saved production frames."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from MDAnalysis.lib.distances import minimize_vectors
from scipy.spatial.transform import Rotation

from backend.core.md_base_frames import ordered_ring_indices
from backend.core.md_two_base_progress import write_progress

SCHEMA = 1
LABELS = ['x (nm)', 'y (nm)', 'z (nm)', 'rotation x (°)', 'rotation y (°)', 'rotation z (°)']
NOTE = ('Base 2 relative to base 1. Origins are unweighted base-ring centroids. '
        'x points N1→C4 (pyrimidines) or N9→C6 (purines), projected into the ring plane; '
        'z is the fitted ring normal signed by chemical ring order; y = z × x. '
        'Displacement uses the nearest periodic image in base 1’s moving frame. '
        'Orientation is the principal rotation vector of frame 1ᵀ frame 2, in degrees: '
        'its direction is the rotation axis and its magnitude is the angle (0–180°). '
        'Components can jump at 180°; these are not Euler angles or helical step parameters. '
        'Each point is one saved production frame; no equilibration frames or subsampling.')


def image(delta, box):
    if box is None or not np.isfinite(box).all() or np.any(np.asarray(box)[:3] <= 0):
        return np.asarray(delta, dtype=float)
    return minimize_vectors(np.asarray(delta, dtype=float), np.asarray(box, dtype=float))


def ring_frame(points, box=None):
    points = np.asarray(points, dtype=float)
    if not np.isfinite(points).all():
        raise ValueError('Nonfinite base ring coordinates')
    points = points[0] + image(points-points[0], box)
    center = points.mean(axis=0)
    _, singular, axes = np.linalg.svd(points-center)
    if singular[1] < 1e-8:
        raise ValueError('Degenerate base ring')
    z = axes[-1]
    sign = np.dot(z, np.cross(points[1]-points[0], points[2]-points[0]))
    if abs(sign) < 1e-8:
        raise ValueError('Undefined base ring orientation')
    z *= 1 if sign > 0 else -1
    x = points[4 if len(points) == 9 else 3] - points[0]
    x -= np.dot(x,z)*z
    length = np.linalg.norm(x)
    if length < 1e-8:
        raise ValueError('Undefined base in-plane axis')
    x /= length
    return center, np.column_stack((x,np.cross(z,x),z))


def relative_coordinates(first, second, box=None):
    a, axes_a = ring_frame(first,box)
    b, axes_b = ring_frame(second,box)
    displacement = image(b-a,box) @ axes_a / 10
    rotation = Rotation.from_matrix(axes_a.T @ axes_b).as_rotvec(degrees=True)
    return np.concatenate((displacement,rotation)).tolist()


def residue_rings(universe, design_path, package, bases):
    from backend.core.models import Design
    from backend.core.atomistic_to_nadoc import build_namd_coarse_reference, load_segid_chain_map
    design = Design.model_validate_json(Path(design_path).read_text())
    segmap = load_segid_chain_map(Path(package))
    if not segmap:
        raise ValueError('Saved simulation residue mapping is unavailable')
    mapping, _ = build_namd_coarse_reference(design,None,segmap,mapping_only=True)
    found = {}
    for residue in universe.residues:
        chain = segmap.get(residue.segid)
        key = mapping.get((chain,int(residue.resid)))
        if key is None:
            continue
        key = ':'.join(map(str,key[:-1] if len(key)==4 and key[-1]==0 else key))
        if key not in bases:
            continue
        atoms = {str(a.name):int(a.index) for a in residue.atoms}
        indices = ordered_ring_indices(atoms)
        if len(indices) != (9 if 'N9' in atoms else 6):
            raise ValueError(f'Incomplete base ring: {key}')
        if key in found:
            raise ValueError(f'Ambiguous simulation base: {key}')
        found[key] = indices
    if any(key not in found for key in bases):
        raise ValueError('Selected base is not mapped in this simulation’s saved design')
    return [found[key] for key in bases]


def md_two_base_maps(topology, trajectories, design, job_dir, bases, progress_path=None):
    import MDAnalysis as mda
    paths = list(map(Path,[topology,*trajectories,design]))
    source = dict(schema=SCHEMA,bases=bases,files=[[str(p.name),p.stat().st_size,p.stat().st_mtime_ns] for p in paths],
                  design_hash=hashlib.sha256(Path(design).read_bytes()).hexdigest())
    fingerprint = hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
    folder = Path(job_dir)/'analysis'/'two_base_maps'
    cached = folder/(fingerprint+'.json')
    if cached.exists():
        result = json.loads(cached.read_text())
        write_progress(progress_path,result['frames'],result['frames'])
        return result
    universe = mda.Universe(str(topology),list(map(str,trajectories)))
    try:
        rings = residue_rings(universe,design,Path(topology).parent,bases)
        rows = []
        total = len(universe.trajectory)
        write_progress(progress_path,0,total)
        for ts in universe.trajectory:
            rows.append(relative_coordinates(ts.positions[rings[0]],ts.positions[rings[1]],ts.dimensions))
            if len(rows) % 25 == 0:
                write_progress(progress_path,len(rows),total)
    finally:
        universe.trajectory.close()
    if not rows:
        raise ValueError('No production frames available')
    result = dict(bases=bases,labels=LABELS,rows=rows,frames=len(rows),note=NOTE,source=source)
    folder.mkdir(parents=True,exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=folder,suffix='.tmp',delete=False) as f:
            temp = Path(f.name)
            json.dump(result,f,allow_nan=False)
        os.replace(temp,cached)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    write_progress(progress_path,len(rows),len(rows))
    return result
