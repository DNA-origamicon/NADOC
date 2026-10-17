"""Replay a connectivity section from authored segment and shared-station inputs.

Endpoint poses describe the selected path. Indexed positions/frames remain
outputs of the established segment builder and are never request parameters.
"""

import math
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_path_commands import _fail, _fresh, _selected
from backend.core.models import Design, LatticeType
from backend.core.part_history_proof import ProofBudgetExceeded

KINDS = frozenset({"connectivity-path", "auto-scaffold-connectivity-section"})
_Id = Annotated[str, Field(min_length=1, max_length=256, strict=True)]
_Number = Annotated[float, Field(ge=-10_000, le=10_000, allow_inf_nan=False, strict=True)]
_Point = tuple[_Number, _Number, _Number]
_Rotation = tuple[_Point, _Point, _Point]
_Bp = Annotated[StrictInt, Field(ge=0, le=2015)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectivitySegment(_Input):
    start_nm: _Point
    end_nm: _Point
    start_rotation: _Rotation
    end_rotation: _Rotation
    straight_bp: _Bp = 0

    @model_validator(mode="after")
    def rotations(self):
        for value in (self.start_rotation, self.end_rotation):
            matrix = np.asarray(value)
            if not (np.allclose(matrix.T @ matrix, np.eye(3), rtol=0, atol=1e-8)
                    and abs(np.linalg.det(matrix) - 1) <= 1e-8):
                raise ValueError("Connectivity endpoint orientation must be a proper rotation")
        return self


class ConnectivityPathRequest(_Input):
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(default=1, alias="_proof_version")
    deformation_id: _Id
    helix_ids: list[_Id] = Field(min_length=1, max_length=128)
    start_bp: _Bp
    segments: list[ConnectivitySegment] = Field(min_length=1, max_length=13)
    parent_deformation_id: _Id | None = None
    shared_interval: tuple[_Bp, _Bp] | None = None

    @model_validator(mode="after")
    def parent_interval(self):
        if (self.parent_deformation_id is None) != (self.shared_interval is None):
            raise ValueError("A shared interval requires exactly one parent path")
        if self.shared_interval is not None:
            lo, hi = self.shared_interval
            if lo > hi or lo != self.start_bp or hi >= 2015:
                raise ValueError("Shared interval must start this path and include its final station")
        return self


def _tracks(design, identities, field):
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.lattice import honeycomb_position

    helices = _selected(design.helices, identities, "helix", field)
    cells = set()
    for index, helix in enumerate(helices):
        if (helix.grid_pos is None or helix.grid_pos in cells or helix.bp_start != 0
                or helix.lattice_frame_id is not None or helix.native_residues):
            _fail("Connectivity paths require distinct unframed lattice tracks", "helix",
                  helix.id, [field, index])
        cells.add(helix.grid_pos)
        x, y = honeycomb_position(*helix.grid_pos)
        if not (np.allclose(helix.axis_start.to_array(), [x, y, 0], rtol=0, atol=1e-9)
                and np.allclose(helix.axis_end.to_array(),
                                [x, y, helix.length_bp * BDNA_RISE_PER_BP], rtol=0, atol=1e-9)):
            _fail("Connectivity paths require canonical XY lattice axes", "helix",
                  helix.id, [field, index])
    return helices


def _shared_stations(design, body, helices):
    from backend.core.lattice import honeycomb_position

    parents = [op for op in design.deformations if op.id == body.parent_deformation_id]
    if len(parents) != 1:
        _fail("Parent connectivity path is missing or ambiguous", "deformation",
              body.parent_deformation_id, ["parent_deformation_id"], missing=not parents)
    parent = parents[0]
    def invalid(detail):
        _fail(detail, "deformation", parent.id, ["parent_deformation_id"])

    if (parent.type != "sweep" or parent.targets or parent.target_ranges or parent.cluster_ids
            or not parent.affected_helix_ids or getattr(parent.params, "preceding_op_ids", None)):
        invalid("Shared stations require a whole-helix indexed parent sweep")
    parent_helices = _tracks(design, parent.affected_helix_ids, "parent_helix_ids")
    if set(parent.affected_helix_ids) & set(body.helix_ids):
        invalid("Parent and daughter connectivity faces must be disjoint")
    extent = parent.plane_b_bp - parent.plane_a_bp + 1
    raw_positions = getattr(parent.params, "bp_positions_nm", None)
    raw_frames = getattr(parent.params, "bp_frames", None)
    if (extent < 2 or extent > 2016 or raw_positions is None or raw_frames is None
            or len(raw_positions) != extent or len(raw_frames) != extent):
        invalid("Parent sweep has no complete indexed station geometry")
    positions, frames = np.asarray(raw_positions, dtype=float), np.asarray(raw_frames, dtype=float)
    if (positions.shape != (extent, 3)
            or frames.shape != (extent, 9)
            or not np.isfinite(positions).all() or not np.isfinite(frames).all()):
        invalid("Parent sweep has no complete indexed station geometry")
    lo, hi = body.shared_interval
    if lo < parent.plane_a_bp or hi + 1 > parent.plane_b_bp:
        invalid("Shared interval exceeds the parent path's station extent")
    parent_center = np.mean([honeycomb_position(*h.grid_pos) for h in parent_helices], axis=0)
    child_center = np.mean([honeycomb_position(*h.grid_pos) for h in helices], axis=0)
    delta = np.r_[child_center - parent_center, 0]
    frames = frames.reshape(-1, 3, 3)
    indices = range(lo - parent.plane_a_bp, hi + 2 - parent.plane_a_bp)
    return ([positions[i] + frames[i] @ delta for i in indices],
            [frames[i] for i in indices])


def _admit(body, helix_count, initial_count):
    """Bound native allocation using the cubic control polygon's arc upper bound."""
    from backend.core.connectivity_generator import RISE

    upper_steps = 0
    for item in body.segments:
        a, b = np.asarray(item.start_nm), np.asarray(item.end_nm)
        ra, rb = np.asarray(item.start_rotation), np.asarray(item.end_rotation)
        pre = b - rb[:, 2] * item.straight_bp * RISE
        chord = np.linalg.norm(pre - a)
        handle = min(chord / 3, 12.0)
        controls = np.array([a, a + ra[:, 2] * handle, pre - rb[:, 2] * handle, pre])
        upper_arc = float(np.linalg.norm(np.diff(controls, axis=0), axis=1).sum())
        steps = max(7, math.ceil(upper_arc / RISE / 7) * 7) + item.straight_bp
        if steps > 2015:
            raise ProofBudgetExceeded("Connectivity segment exceeds the supported station budget")
        upper_steps += steps
    if (initial_count + upper_steps) * helix_count > 50_000:
        raise ProofBudgetExceeded("Connectivity path exceeds the proof nucleotide budget")


def path(design, params):
    from backend.core.connectivity_generator import apply_connectivity_geometry, segment

    body = ConnectivityPathRequest.model_validate(params)
    if design.lattice_type != LatticeType.HONEYCOMB:
        raise ValueError("Connectivity paths require the honeycomb lattice")
    _fresh(design.deformations, body.deformation_id, "deformation", "deformation_id")
    helices = _tracks(design, body.helix_ids, "helix_ids")
    initial_count = (body.shared_interval[1] - body.shared_interval[0] + 2
                     if body.shared_interval is not None else 1)
    _admit(body, len(helices), initial_count)
    if body.parent_deformation_id is None:
        points = [np.asarray(body.segments[0].start_nm)]
        frames = [np.asarray(body.segments[0].start_rotation)]
    else:
        points, frames = _shared_stations(design, body, helices)
    for index, item in enumerate(body.segments):
        if not (np.allclose(points[-1], item.start_nm, rtol=0, atol=1e-8)
                and np.allclose(frames[-1], item.start_rotation, rtol=0, atol=1e-8)):
            if index == 0 and body.parent_deformation_id is not None:
                _fail("Shared junction no longer meets the daughter segment's authored endpoint pose",
                      "deformation", body.parent_deformation_id, ["parent_deformation_id"])
            raise ValueError("Connectivity segment endpoint pose must continue the preceding path")
        p, r = segment(np.asarray(item.start_nm), np.asarray(item.end_nm),
                       np.asarray(item.start_rotation), np.asarray(item.end_rotation), item.straight_bp)
        if not np.isfinite(p).all() or not np.isfinite(r).all():
            raise ValueError("Connectivity segment produced invalid station geometry")
        points.extend(p[1:])
        frames.extend(r[1:])
        if body.start_bp + len(points) > 2016:
            raise ProofBudgetExceeded("Connectivity path exceeds the supported base-pair span")
    for index, helix in enumerate(helices):
        if body.start_bp + len(points) > helix.length_bp:
            _fail("Connectivity path exceeds its selected helix extent", "helix", helix.id,
                  ["helix_ids", index])
    native = apply_connectivity_geometry(Design(lattice_type=design.lattice_type, helices=helices), {
        "connectivity_faces": [[h.grid_pos for h in helices]],
        "connectivity_paths": [{"start": body.start_bp, "positions": np.asarray(points).tolist(),
                                "frames": np.asarray(frames).reshape(-1, 9).tolist()}],
        "connectivity_junctions": [],
    })
    operation = native.deformations[0].model_copy(update={"id": body.deformation_id})
    return design.copy_with(deformations=[*design.deformations, operation])


def build(kind, design, params):
    if kind == "connectivity-path":
        return path(design, params)
    if kind == "auto-scaffold-connectivity-section":
        from backend.api.part_section_commands import SectionRouteRequest, _route
        from backend.core.seamed_router import auto_scaffold_seamed

        body = SectionRouteRequest.model_validate(params)
        if body.lattice_column_offset != 0 or design.lattice_type != LatticeType.HONEYCOMB:
            raise ValueError("Connectivity routing requires its canonical honeycomb lattice addresses")
        return _route(design, params, auto_scaffold_seamed)[0]
    raise NotImplementedError(kind)
