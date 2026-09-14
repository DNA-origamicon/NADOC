"""Periodic graphene in rotated orthorhombic cells, with explicit cell vectors."""
from copy import deepcopy

import numpy as np

from backend.core.surface_transforms import RigidTransform, transform_surface


def transform_pdb_coordinates(text, transform):
    """Rigidly transform all ATOM/HETATM coordinates, preserving atom identities."""
    result = []
    for line in text.splitlines():
        if line.startswith(('ATOM  ', 'HETATM')):
            point = [float(line[i:i + 8]) / 10 for i in (30, 38, 46)]
            fields = [f'{x * 10:8.3f}' for x in transform.points(point)]
            if any(len(field) != 8 for field in fields):
                raise ValueError('transformed coordinates overflow PDB fields')
            line = line[:30] + ''.join(fields) + line[54:]
        result.append(line)
    return '\n'.join(result) + '\n'


def tile_in_cell_frame(pdb_text, box_nm, spec, cell_vectors_nm):
    """Tile a plane parallel to a face of a rotated orthorhombic periodic cell.

    Vectors are ROWS in world nm, cell origin is zero. Sheared/triclinic cells or
    planes incommensurate with the supplied cell are rejected. To accommodate an
    arbitrary source plane, use surface_aligned_cell before solvating instead.
    """
    from backend.core.namd_graphene import tile_graphene_to_cell

    vectors = np.asarray(cell_vectors_nm, float)
    lengths = np.asarray(box_nm, float)
    if (vectors.shape != (3, 3) or lengths.shape != (3,)
            or not np.isfinite(vectors).all() or not np.isfinite(lengths).all()
            or np.any(lengths <= 0)
            or not np.allclose(np.linalg.norm(vectors, axis=1), lengths, atol=1e-8, rtol=0)):
        raise ValueError('cell vectors must match the three positive box lengths')
    rotate = RigidTransform(vectors / lengths[:, None])
    local_spec = transform_surface(spec, rotate)
    local_spec['_first_site_nm'] = rotate.points(spec['_first_site_nm']).tolist()
    local_pdb = transform_pdb_coordinates(pdb_text, rotate)
    tiled = tile_graphene_to_cell(local_pdb, lengths, local_spec)
    world_spec = transform_surface(local_spec, rotate.inverse())
    world_spec['periodic_cell_vectors_nm'] = vectors.tolist()
    world_spec['periodic_cell_origin_nm'] = [0., 0., 0.]
    spec.clear()
    spec.update(world_spec)
    return transform_pdb_coordinates(tiled, rotate.inverse())


def namd_cell_basis(spec):
    """NAMD cellBasisVector declarations in Å for an explicitly oriented cell.

    Callers must use this with matching solute/solvent coordinates. It does not
    change barostat policy or configure a simulation.
    """
    vectors = np.asarray(deepcopy(spec['periodic_cell_vectors_nm']), float)
    if vectors.shape != (3, 3) or not np.isfinite(vectors).all() or np.linalg.det(vectors) <= 0:
        raise ValueError('invalid periodic cell vectors')
    return '\n'.join(
        f'cellBasisVector{i + 1} ' + ' '.join(f'{v * 10:.10g}' for v in row)
        for i, row in enumerate(vectors)
    ) + '\n'
