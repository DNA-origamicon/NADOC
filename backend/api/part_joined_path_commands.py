"""Joined crossbar paths evaluated from stations, never saved path samples."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import ProofBudgetExceeded

KINDS = frozenset({"joined-crossbar-path"})
_Id = Annotated[str, Field(min_length=1, max_length=256, strict=True)]
_Coordinate = Annotated[float, Field(ge=-10000, le=10000, strict=True, allow_inf_nan=False)]
_Point = tuple[_Coordinate, _Coordinate, _Coordinate]
_Count = Annotated[StrictInt, Field(ge=0, le=2015)]


class JoinedPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(default=1, alias="_proof_version")
    deformation_id: _Id
    helix_ids: list[_Id] = Field(min_length=1, max_length=128)
    lattice_column_offset: Annotated[StrictInt, Field(ge=-16384, le=16384)]
    endpoint_a_nm: _Point
    endpoint_b_nm: _Point
    junction_nm: _Point
    tail_bp: Annotated[StrictInt, Field(ge=1, le=2015)]
    central_bp: Annotated[StrictInt, Field(ge=2, le=2014)]
    max_outer_strain: float = Field(gt=0, le=1, strict=True, allow_inf_nan=False)
    extra_left_bp: _Count = 0
    extra_right_bp: _Count = 0

    @model_validator(mode="after")
    def planar_path(self):
        if self.lattice_column_offset % 2 or self.central_bp % 2:
            raise ValueError("Crossbar addresses and central span require even offsets")
        if any(point[1] != 0 for point in (self.endpoint_a_nm, self.endpoint_b_nm, self.junction_nm)):
            raise ValueError("Crossbar source stations must lie in the native XZ plane")
        if 2 * self.tail_bp + self.central_bp + self.extra_left_bp + self.extra_right_bp > 2015:
            raise ValueError("Crossbar tails exceed the supported path extent")
        return self


def _fail(detail, identity, path, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": "helix", "identity": identity, "parameter_path": path}])


def build(kind, design, params):
    if kind not in KINDS:
        raise NotImplementedError(kind)
    import numpy as np
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.join_crossbars import crossbar_path, extend_crossbar_path
    from backend.core.joined_branches import joined_path_operation
    from backend.core.lattice import _lattice_position

    body = JoinedPathRequest.model_validate(params)
    if any(operation.id == body.deformation_id for operation in design.deformations):
        raise ValueError("Joined path output identity already exists")
    helices, seen, cells = [], set(), set()
    for i, identity in enumerate(body.helix_ids):
        path = ["helix_ids", i]
        matches = [helix for helix in design.helices if helix.id == identity]
        if identity in seen or len(matches) > 1:
            _fail("Joined path target identity is ambiguous", identity, path)
        if not matches:
            _fail("Joined path target no longer exists", identity, path, missing=True)
        helix = matches[0]
        if (helix.grid_pos is None or helix.lattice_frame_id is not None or helix.native_residues
                or helix.bp_start != 0 or helix.grid_pos in cells):
            _fail("Joined path requires independent canonical lattice tracks", identity, path)
        row, column = helix.grid_pos
        x, y = _lattice_position(row, column - body.lattice_column_offset, design.lattice_type)
        if not (np.allclose(helix.axis_start.to_array(), [x, y, 0], rtol=0, atol=1e-9)
                and np.allclose(helix.axis_end.to_array(), [x, y, helix.length_bp * BDNA_RISE_PER_BP],
                                rtol=0, atol=1e-9)):
            _fail("Joined path requires canonical XY seed axes", identity, path)
        seen.add(identity)
        cells.add(helix.grid_pos)
        helices.append(helix)
    a, b, junction = map(np.asarray, (body.endpoint_a_nm, body.endpoint_b_nm, body.junction_nm))
    if len(helices) * (np.linalg.norm(a - junction) + np.linalg.norm(b - junction)) > 8000:
        raise ProofBudgetExceeded("Joined path exceeds proof path budget")
    xy = np.array([[helix.axis_start.x, helix.axis_start.y] for helix in helices])
    center = xy.mean(0)
    outer_radius = float(max(abs(xy[:, 0] - center[0])))
    path, *_ = crossbar_path(a, b, junction, body.tail_bp, body.central_bp,
                             outer_radius, body.max_outer_strain)
    if body.extra_left_bp or body.extra_right_bp:
        path = extend_crossbar_path(path, body.extra_left_bp, body.extra_right_bp)
    length = len(path["positions"])
    if length > 2016 or length * len(helices) > 50000:
        raise ProofBudgetExceeded("Joined path exceeds proof nucleotide budget")
    for i, helix in enumerate(helices):
        if helix.length_bp != length:
            _fail("Joined path no longer matches the authored seed extent", helix.id, ["helix_ids", i])
    operation = joined_path_operation(body.helix_ids, path, body.deformation_id)
    return design.copy_with(deformations=[*design.deformations, operation])


def compile_path_params(spec, section_index, helix_ids):
    if spec.get("path_recipe") is None:
        raise ValueError("Joined section needs its retained numeric path recipe")
    return JoinedPathRequest.model_validate({
        **spec["path_recipe"], "deformation_id": f"generated_join_sweep_{section_index}",
        "helix_ids": helix_ids, "lattice_column_offset": 1000 * section_index, "_proof_version": 1,
    }).model_dump(mode="json", by_alias=True)
