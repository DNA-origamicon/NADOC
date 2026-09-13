"""Direct NAMD PEG surface drafts and schematic graft layout; no atom placement."""
import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.surface_transforms import SurfaceFrame


class NamdPegSurface(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field('PEG surface', min_length=1, max_length=100)
    material: Literal['hard_wall', 'graphene'] = 'hard_wall'
    normal_axis: Literal['+x', '-x', '+y', '-y', '+z', '-z'] = '+z'
    position_nm: float = Field(0, ge=-10000, le=10000)
    shape: Literal['square', 'circle'] = 'square'
    size_nm: float = Field(20, ge=2, le=1000)
    pore_diameter_nm: float = Field(0, ge=0, le=1000)
    layers: int = Field(1, ge=1, le=6)
    density_per_nm2: float = Field(.05, gt=0, le=10)
    seed: int = Field(17, ge=0, le=4294967295)
    representation: Literal['atomistic', 'coarse_grained'] = 'atomistic'
    repeat_units: int = Field(36, ge=1, le=10000)
    segments: int = Field(8, ge=2, le=1000)
    end_groups: str = Field('', max_length=200)
    topology_reference: str = Field('', max_length=500)
    parameter_reference: str = Field('', max_length=500)

    @model_validator(mode='after')
    def validate_layout(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('Enter a surface name')
        if self.material == 'hard_wall' and (self.pore_diameter_nm != 0 or self.layers != 1):
            raise ValueError('Pores and layers apply to graphene only')
        if self.pore_diameter_nm >= self.size_nm:
            raise ValueError('Pore diameter must be smaller than the patch size')
        if self.chain_count() < 1:
            raise ValueError('Increase patch size or density to request at least one chain')
        if self.chain_count() > 10000:
            raise ValueError('Surface drafts support at most 10,000 chains')
        return self

    def area_nm2(self):
        return (self.size_nm ** 2 * (math.pi / 4 if self.shape == 'circle' else 1)
                - math.pi * (self.pore_diameter_nm / 2) ** 2)

    def chain_count(self):
        return int(math.floor(self.area_nm2() * self.density_per_nm2 + .5))


def review_surface(spec: NamdPegSurface):
    """Deterministic sample of intended graft sites, not a molecular conformation."""
    normal = np.zeros(3)
    axis = 'xyz'.index(spec.normal_axis[1])
    normal[axis] = 1 if spec.normal_axis[0] == '+' else -1
    point = np.zeros(3)
    point[axis] = spec.position_nm
    frame = SurfaceFrame(point, normal)
    count = spec.chain_count()
    rng = np.random.default_rng(spec.seed)
    # Uniform annulus sampling avoids slow rejection near a large circular pore.
    shown = min(count, 256)
    points = []
    for _ in range(shown):
        if spec.shape == 'circle':
            radius = math.sqrt(rng.uniform((spec.pore_diameter_nm/2)**2, (spec.size_nm/2)**2))
            theta = rng.uniform(0, 2*math.pi)
            xy = [radius*math.cos(theta), radius*math.sin(theta)]
        else:
            while True:
                xy = rng.uniform(-spec.size_nm/2, spec.size_nm/2, 2)
                if np.linalg.norm(xy) >= spec.pore_diameter_nm/2:
                    break
        points.append(list(map(float, xy)))
    local = np.asarray(points)
    world = point + local[:, :1]*frame.tangent_u + local[:, 1:]*frame.tangent_v
    barriers = [
        {'code': 'target_assets', 'message': 'PEG topology and force-field references must be supplied and validated.'},
        {'code': 'graft_chemistry', 'message': 'Graft chemistry and DNA/PEG/surface interactions must be specified and validated.'},
        {'code': 'molecular_build', 'message': 'Atom placement, solvent preparation and engine validation are not implemented for these drafts.'},
    ]
    if spec.representation == 'atomistic' and not spec.end_groups.strip():
        barriers.insert(0, {'code': 'end_groups', 'message': 'Specify the grafted and free PEG end groups.'})
    if spec.material == 'hard_wall':
        barriers.append({'code': 'wall_force', 'message': 'A NAMD hard-wall force implementation and parameters must be selected.'})
    if spec.representation == 'coarse_grained':
        barriers.append({'code': 'hybrid_model', 'message': 'The coarse-grained PEG model and its atomistic cross interactions require validation.'})
    return {'schema': 'nadoc.namd_peg_surface.v1', 'engine': 'NAMD', 'origin': 'direct',
            'status': 'draft', 'launch_ready': False, 'spec': spec.model_dump(),
            'summary': {'chains': count, 'area_nm2': spec.area_nm2(), 'preview_sites': shown},
            'surface': {'dir': list(frame.normal), 'plane_point_nm': list(frame.point_nm),
                        'tangent_u': list(frame.tangent_u)},
            'preview': {'local_sites_nm': points, 'graft_sites_nm': world.tolist()},
            'barriers': barriers}
