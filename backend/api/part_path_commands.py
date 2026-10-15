"""Small native path, routing-window and scaffold-fitting recipe commands.

Path samples and fitted geometry are outputs of the existing scientific builders,
never accepted as command parameters. Each adapter preserves unrelated state.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.core.models import CrossoverConstraint, Design
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import ProofBudgetExceeded

KINDS = frozenset({
    "fork-path", "crossover-constraint-create", "crossover-constraint-delete",
    "encode-sweep-curvature", "scaffold-budget-fit",
})
_Id = Annotated[str, Field(min_length=1, max_length=256, strict=True)]
_Ids = Annotated[list[_Id], Field(min_length=1, max_length=128)]
_Bp = Annotated[StrictInt, Field(ge=1, le=2015)]
_Index = Annotated[StrictInt, Field(ge=-1_000_000, le=1_000_000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(default=1, alias="_proof_version")


class ForkPathRequest(_Input):
    deformation_id: _Id
    helix_ids: _Ids
    radius_nm: float = Field(gt=0, le=1000, allow_inf_nan=False, strict=True)
    stem_bp: _Bp
    arc_bp: _Bp
    tail_bp: _Bp
    double: StrictBool
    mirror: Annotated[StrictInt, Field(ge=-1, le=1)]

    @model_validator(mode="after")
    def bounded_path(self):
        if self.mirror not in {-1, 1}:
            raise ValueError("Fork mirror must be -1 or 1")
        if self.steps > 2015:
            raise ValueError("Fork path exceeds the supported 2016-base extent")
        return self

    @property
    def steps(self):
        return self.stem_bp + (self.arc_bp + self.tail_bp) * (2 if self.double else 1) + (0 if self.double else self.tail_bp)


class ConstraintCreateRequest(_Input):
    constraint_id: _Id
    helix_ids_a: _Ids
    helix_ids_b: _Ids
    allowed_bp_intervals: list[tuple[_Index, _Index]] = Field(max_length=128)

    @model_validator(mode="after")
    def ordered_intervals(self):
        if any(lo > hi for lo, hi in self.allowed_bp_intervals):
            raise ValueError("Allowed crossover intervals must have lo <= hi")
        if any(a[1] >= b[0] for a, b in zip(self.allowed_bp_intervals, self.allowed_bp_intervals[1:])):
            raise ValueError("Allowed crossover intervals must be ordered and nonoverlapping")
        return self


class ConstraintDeleteRequest(_Input):
    constraint_id: _Id


class EncodeSweepRequest(_Input):
    op_ids: _Ids


class ScaffoldBudgetRequest(_Input):
    scaffold_id: _Id
    target_nt: Annotated[StrictInt, Field(ge=1, le=50_000)]


def _fail(detail, kind, identity, path, *, missing=False):
    raise ReferenceResolutionError(
        detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )


def _selected(records, identities, kind, field):
    selected, seen = [], set()
    for i, identity in enumerate(identities):
        path = [field, i]
        if identity in seen:
            _fail("A target may be selected only once", kind, identity, path)
        seen.add(identity)
        matches = [record for record in records if record.id == identity]
        if len(matches) != 1:
            _fail("Target is missing or has ambiguous identity", kind, identity, path,
                  missing=not matches)
        selected.append(matches[0])
    return selected


def _fresh(records, identity, kind, field):
    if any(record.id == identity for record in records):
        _fail("Command output identity already exists", kind, identity, [field])


def fork_path(design, params):
    import numpy as np

    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.curved_branches import _path, apply_fork_geometry
    from backend.core.lattice import _lattice_position

    body = ForkPathRequest.model_validate(params)
    _fresh(design.deformations, body.deformation_id, "deformation", "deformation_id")
    helices = _selected(design.helices, body.helix_ids, "helix", "helix_ids")
    if len(helices) * (body.steps + 1) > 50_000:
        raise ProofBudgetExceeded("Fork path exceeds proof nucleotide budget")
    cells = set()
    for i, helix in enumerate(helices):
        if (helix.grid_pos is None or helix.lattice_frame_id is not None
                or helix.grid_pos in cells or helix.native_residues
                or helix.bp_start != 0 or helix.length_bp != body.steps + 1):
            _fail("Fork path requires distinct unframed lattice tracks of its authored extent",
                  "helix", helix.id, ["helix_ids", i])
        cells.add(helix.grid_pos)
        x, y = _lattice_position(*helix.grid_pos, design.lattice_type)
        if not (np.allclose(helix.axis_start.to_array(), [x, y, 0], rtol=0, atol=1e-9)
                and np.allclose(helix.axis_end.to_array(),
                                [x, y, helix.length_bp * BDNA_RISE_PER_BP], rtol=0, atol=1e-9)):
            _fail("Fork path requires canonical XY lattice axes", "helix", helix.id,
                  ["helix_ids", i])
    path = _path(body.radius_nm, body.stem_bp, body.arc_bp, body.tail_bp,
                 body.double, body.mirror)
    local = Design(lattice_type=design.lattice_type, helices=helices)
    native = apply_fork_geometry(local, {
        "fork_faces": [[list(helix.grid_pos) for helix in helices]],
        "fork_paths": [path], "fork_rule_specs": [], "fork_crossover_intervals": [],
    })
    operation = native.deformations[0].model_copy(update={"id": body.deformation_id})
    return design.copy_with(deformations=[*design.deformations, operation])


def create_constraint(design, params):
    body = ConstraintCreateRequest.model_validate(params)
    _fresh(design.crossover_constraints, body.constraint_id, "crossover_constraint", "constraint_id")
    first = _selected(design.helices, body.helix_ids_a, "helix", "helix_ids_a")
    second = _selected(design.helices, body.helix_ids_b, "helix", "helix_ids_b")
    for i, identity in enumerate(body.helix_ids_b):
        if identity in body.helix_ids_a:
            _fail("Crossover constraint groups must be disjoint", "helix", identity,
                  ["helix_ids_b", i])
    for field, helices in (("helix_ids_a", first), ("helix_ids_b", second)):
        for i, helix in enumerate(helices):
            if any(lo < helix.bp_start or hi >= helix.bp_start + helix.length_bp
                   for lo, hi in body.allowed_bp_intervals):
                _fail("Crossover interval exceeds its target helix extent", "helix", helix.id,
                      [field, i])
    rule = CrossoverConstraint(id=body.constraint_id, helix_ids_a=body.helix_ids_a,
                               helix_ids_b=body.helix_ids_b,
                               allowed_bp_intervals=body.allowed_bp_intervals)
    return design.copy_with(crossover_constraints=[*design.crossover_constraints, rule])


def delete_constraint(design, params):
    body = ConstraintDeleteRequest.model_validate(params)
    matches = [item for item in design.crossover_constraints if item.id == body.constraint_id]
    if len(matches) != 1:
        _fail("Crossover constraint is missing or ambiguous", "crossover_constraint",
              body.constraint_id, ["constraint_id"], missing=not matches)
    return design.copy_with(crossover_constraints=[
        item for item in design.crossover_constraints if item.id != body.constraint_id
    ])


def encode_curvature(design, params):
    from backend.core.generated_sweep import encode_sweep

    body = EncodeSweepRequest.model_validate(params)
    if sum(helix.length_bp for helix in design.helices) > 50_000:
        raise ProofBudgetExceeded("Curvature encoding exceeds proof nucleotide budget")
    operations = _selected(design.deformations, body.op_ids, "deformation", "op_ids")
    for i, operation in enumerate(operations):
        if operation.type != "sweep" or not operation.affected_helix_ids:
            _fail("Curvature encoding requires an explicitly scoped sweep", "deformation",
                  operation.id, ["op_ids", i])
        existing = {helix.id for helix in design.helices}
        missing = set(operation.affected_helix_ids) - existing
        if missing:
            _fail("Sweep has a missing helix dependency", "deformation", operation.id,
                  ["op_ids", i])
    return encode_sweep(design, operation_ids=body.op_ids)


def _budget_attachments(design, scaffold):
    from backend.core.part_scope_references import COLLECTIONS, referenced_resources

    helices = {domain.helix_id for domain in scaffold.domains}
    strands = {strand.id for strand in design.strands
               if any(domain.helix_id in helices for domain in strand.domains)}
    resources = {("helix", identity) for identity in helices} | {("strand", identity) for identity in strands}
    resources |= {("crossover", item.id) for item in design.crossovers
                  if item.half_a.helix_id in helices or item.half_b.helix_id in helices}
    for strand in design.strands:
        if strand.id in strands and (strand.is_reference or any(
            domain.overhang_id or domain.binds_overhang_id for domain in strand.domains
        )):
            _fail("Budget fitting cannot trim reference or overhang-bearing strands",
                  "strand", scaffold.id, ["scaffold_id"])
    # The native fitter checks crossover clearance and preserves helix geometry.
    # Other strand/endpoint ownership needs a separate trim contract.
    handled = {"helices", "strands", "crossovers", "crossover_constraints"}
    for field in COLLECTIONS.keys() - handled:
        for item in getattr(design, field):
            try:
                refs = referenced_resources(item)
            except NotImplementedError as exc:
                _fail(f"Budget fitting cannot classify {field} dependencies: {exc}",
                      "strand", scaffold.id, ["scaffold_id"])
            if field in {"deformations", "cluster_transforms"}:
                refs = {ref for ref in refs if ref[0] == "strand"}
            if refs & resources:
                _fail(f"Budget fitting target has unsupported {field} dependencies",
                      "strand", scaffold.id, ["scaffold_id"])


def fit_budget(design, params):
    from backend.core.branch_optimizer import trim_to_budget

    body = ScaffoldBudgetRequest.model_validate(params)
    matches = [strand for strand in design.strands if strand.id == body.scaffold_id]
    if len(matches) != 1:
        _fail("Scaffold target is missing or ambiguous", "strand", body.scaffold_id,
              ["scaffold_id"], missing=not matches)
    scaffolds = [strand for strand in design.scaffolds() if not strand.is_reference]
    if len(scaffolds) != 1 or scaffolds[0].id != body.scaffold_id or not scaffolds[0].domains:
        _fail("Budget fitting requires exactly the selected single active scaffold",
              "strand", body.scaffold_id, ["scaffold_id"])
    if sum(helix.length_bp for helix in design.helices) > 50_000:
        raise ProofBudgetExceeded("Scaffold fitting exceeds proof nucleotide budget")
    for domain in scaffolds[0].domains:
        if design.find_helix(domain.helix_id) is None:
            _fail("Scaffold has a missing helix dependency", "strand", body.scaffold_id,
                  ["scaffold_id"])
    _budget_attachments(design, scaffolds[0])
    updated = trim_to_budget(design, body.target_nt)
    identities = [strand.id for strand in updated.strands]
    if len(identities) != len(set(identities)):
        _fail("Budget fitting would create duplicate strand identities", "strand",
              body.scaffold_id, ["scaffold_id"])
    return updated


def build(kind, design, params):
    builder = {
        "fork-path": fork_path,
        "crossover-constraint-create": create_constraint,
        "crossover-constraint-delete": delete_constraint,
        "encode-sweep-curvature": encode_curvature,
        "scaffold-budget-fit": fit_budget,
    }.get(kind)
    if builder is None:
        raise NotImplementedError(kind)
    return builder(design, params)
