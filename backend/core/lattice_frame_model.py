"""Logical lattice identity, separate from editable cluster membership."""
from typing import Literal
from pydantic import BaseModel, Field


class LatticeFrame(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    plane: Literal['XY', 'XZ', 'YZ'] = 'XY'
    # Placement is applied exactly once by the existing rigid-transform pipeline.
    # Identity remains distinct from that cluster, which may acquire child edits.
    placement_cluster_id: str = Field(min_length=1, max_length=128)


def validate_frame_references(design):
    frames = {frame.id: frame for frame in design.lattice_frames}
    if len(frames) != len(design.lattice_frames):
        raise ValueError('duplicate lattice frame identity')
    clusters = {cluster.id for cluster in design.cluster_transforms}
    for frame in frames.values():
        if frame.placement_cluster_id not in clusters:
            raise ValueError('lattice frame placement cluster is missing')
    for helix in design.helices:
        if helix.lattice_frame_id is not None:
            if helix.lattice_frame_id not in frames or helix.grid_pos is None:
                raise ValueError('helix requires a valid lattice frame and local cell')
