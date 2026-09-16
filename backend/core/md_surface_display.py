"""Read a selected package's own surface settings, independent of surviving parents."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=128)
def _manifest_surface(path: str, modified: int, size: int) -> dict:
    manifest = json.loads(Path(path).read_text())
    wall = manifest.get('graphene_nanopore')
    if not isinstance(wall, dict) or not wall:
        return {}
    result = {'graphene_nanopore': True}
    if not wall.get('surface_axis'):
        axes = {(1, 0, 0): '-x', (-1, 0, 0): '+x', (0, 1, 0): '-y',
                (0, -1, 0): '+y', (0, 0, 1): '-z', (0, 0, -1): '+z'}
        axis = axes.get(tuple(wall.get('dir') or []))
        if axis:
            result['graphene_surface_axis'] = axis
    for source, target in (
        ('surface_axis', 'graphene_surface_axis'),
        ('surface_offset_nm', 'graphene_surface_offset_nm'),
        ('pore_diameter_nm', 'graphene_pore_diameter_nm'),
        ('layers', 'graphene_layers'),
        ('layer_spacing_nm', 'graphene_layer_spacing_nm'),
        ('atomistic_clearance_nm', 'graphene_atomistic_clearance_nm'),
        ('water_clearance_nm', 'graphene_water_clearance_nm'),
        ('sheet_margin_nm', 'graphene_sheet_margin_nm'),
    ):
        if wall.get(source) is not None:
            result[target] = wall[source]
    return result


def surface_prep_params(job, workspace) -> dict:
    if not job.package_subdir:
        return {}
    path = job.package_dir(workspace) / 'manifest.json'
    try:
        stat = path.stat()
        return dict(_manifest_surface(str(path), stat.st_mtime_ns, stat.st_size))
    except (OSError, ValueError, TypeError):
        return {}
