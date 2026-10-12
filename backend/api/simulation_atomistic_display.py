"""Stateless display adapter for FEM/CG engines without an atomic trajectory."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.models import Design
from backend.api.routes_export_structure import PdbVisualizationPosition, _pdb_visualization_overrides

router = APIRouter()


class SimulationAtomisticRequest(BaseModel):
    design: Design
    positions: list[PdbVisualizationPosition] = Field(min_length=1)


@router.post("/design/atomistic/visualized")
def simulation_atomistic_display(body: SimulationAtomisticRequest) -> dict:
    # Use the established visualized-PDB reconstruction, never write positions
    # into the authored design. Measured MD and oxDNA keep their own job pathways.
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json
    from backend.core.cg_to_atomistic import deformed_helix_axes

    regular, crossover, extension = _pdb_visualization_overrides(body.positions)
    if not (regular or crossover or extension):
        raise HTTPException(422, "No mapped simulation positions")
    # Position overrides alone still orient/place duplex atoms around the native
    # helix. Reuse the established deformed-centerline reconstruction as well.
    frame = {key[:3]: {"backbone_position": position}
             for key, position in regular.items() if len(key) == 3 or key[3] == 0}
    axes = deformed_helix_axes(body.design, frame)
    model = build_atomistic_model(
        body.design, nuc_pos_override=regular,
        axis_override=axes or None,
        xb_pos_override=crossover or None, ext_pos_override=extension or None,
        close_backbone=True,
    )
    return atomistic_to_json(model)
