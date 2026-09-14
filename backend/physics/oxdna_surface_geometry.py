"""Canonical plane adapter for oxDNA walls, deposition and PEG placement."""
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.constants import NM_TO_OXDNA
from backend.core.surface_transforms import SurfaceFrame, surface_frame, transform_surface, RigidTransform


class SurfaceGeometry(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    dir: list[float] = Field(..., min_length=3, max_length=3)
    position_nm: float | None = None
    plane_point_nm: tuple[float, float, float] | None = None
    tangent_u: tuple[float, float, float] | None = None

    @model_validator(mode='after')
    def validate_geometry(self):
        spec = self.model_dump(exclude_none=True)
        if self.position_nm is None and self.plane_point_nm is None:
            spec['plane_point_nm'] = [0, 0, 0]  # extent will resolve translation
        surface_frame(spec)
        return self


def resolved_wall(wall, cm_oxdna):
    """Return canonical geometry + oxDNA scalar and minimum projection.

    Explicit plane points take precedence over legacy Cartesian positions. An
    offset-only wall is resolved once against the supplied particle extent.
    """
    spec = dict(wall)
    normal = SurfaceFrame([0, 0, 0], wall.get('dir', [0, 1, 0])).normal
    cm = np.asarray(cm_oxdna, float).reshape(-1, 3)
    if not np.isfinite(cm).all():
        raise ValueError('particle coordinates must be finite')
    minimum = float(np.min(cm @ normal)) if len(cm) else 0.
    if spec.get('plane_point_nm') is None and spec.get('position_nm') is None:
        scalar_nm = minimum / NM_TO_OXDNA - float(spec.get('offset_nm', 0))
        spec['plane_point_nm'] = (np.asarray(normal) * scalar_nm).tolist()
    spec['dir'] = normal
    if spec.get('tangent_u') is None:
        # Preserve the existing coating generator's frame, rather than choosing
        # a different arbitrary tangent when this resolved plane is persisted.
        from backend.physics.oxdna_surface_strands import plane_basis
        spec['tangent_u'] = plane_basis(normal)[1].tolist()
    canonical = transform_surface(spec, RigidTransform())
    plane = surface_frame(canonical).oxdna_plane(NM_TO_OXDNA)
    return {**canonical, 'position': plane['position'], 'min_proj': minimum}


def same_plane(first, second, tolerance_nm=1e-6):
    try:
        a, b = surface_frame(first), surface_frame(second)
    except (ValueError, KeyError, TypeError):
        return False
    return (bool(np.allclose(a.normal, b.normal, atol=1e-6, rtol=0))
            and abs(float(a.signed_distance(b.point_nm))) < tolerance_nm)


def persisted_wall(wall, metadata):
    """Preserve registered origins/tangents when saving a writer-resolved wall."""
    resolved = dict(wall)
    if metadata.get('plane_point_nm') is not None:
        for key in ('dir', 'plane_point_nm', 'tangent_u'):
            if key in metadata:
                resolved[key] = metadata[key]
    else:
        frame = SurfaceFrame([0, 0, 0], metadata['dir'])
        resolved['plane_point_nm'] = (
            -float(metadata['position']) / NM_TO_OXDNA * np.asarray(frame.normal)
        ).tolist()
    return transform_surface(resolved, RigidTransform())


def absolute_wall_for_configuration(wall, conf_path):
    """Freeze an offset-only plane before a placement operation moves particles."""
    from backend.physics.oxdna_interface import read_cm_positions_oxdna
    metadata = resolved_wall(wall, read_cm_positions_oxdna(conf_path))
    return persisted_wall(wall, metadata)
