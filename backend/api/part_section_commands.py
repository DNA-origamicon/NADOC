"""Independent part sections with native lattice geometry and bounded routing.

Physical lattice axes and address separation have distinct authored inputs, as
in joined_seed. Placement, paths, and Join bridges remain separate features.
"""

from typing import Annotated
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_branch_commands import BranchSeedRequest
from backend.core.models import Design
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import ProofBudgetExceeded

KINDS = frozenset({"independent-section-seed", "auto-scaffold-bounded-section"})
_Offset = Annotated[StrictInt, Field(ge=-16384, le=16384)]


class SectionSeedRequest(BranchSeedRequest):
    lattice_column_offset: _Offset

    @model_validator(mode="after")
    def independent_extent(self):
        if self.lattice_column_offset % 2:
            raise ValueError("Independent lattice addresses require an even column offset")
        if any(len(track.intervals) != 1 or track.intervals[0].lo_bp != 0
               or track.intervals[0].hi_bp != self.nominal_length_bp - 1 for track in self.tracks):
            raise ValueError("An independent section must occupy its complete authored extent")
        return self


class SectionRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(default=1, alias="_proof_version")
    history_seed: UUID
    cluster_id: Annotated[str, Field(min_length=1, max_length=256, strict=True)]
    lattice_column_offset: _Offset

    @model_validator(mode="after")
    def even_offset(self):
        if self.lattice_column_offset % 2:
            raise ValueError("Independent lattice addresses require an even column offset")
        return self


def _fail(detail, identity, *, kind="cluster", missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity, "parameter_path": ["cluster_id"]}])


def seed(design, params):
    from backend.api.part_branch_commands import seed as sparse_seed

    body = SectionSeedRequest.model_validate(params)
    cells = {(track.cell[0], track.cell[1] + body.lattice_column_offset) for track in body.tracks}
    if cells & {helix.grid_pos for helix in design.helices if helix.lattice_frame_id is None}:
        raise ValueError("Independent section lattice addresses overlap existing tracks")
    created = sparse_seed(design, body.model_dump(mode="json", by_alias=True,
                                                 exclude={"lattice_column_offset"}))
    existing = {helix.id for helix in design.helices}
    return created.copy_with(helices=[
        helix if helix.id in existing else helix.model_copy(update={
            "grid_pos": (helix.grid_pos[0], helix.grid_pos[1] + body.lattice_column_offset),
        }) for helix in created.helices
    ])


def compile_seed_params(spec, section_index, history_seed):
    """Compile one section's lattice inputs; evaluated path/pose data stay out."""
    from backend.api.part_branch_commands import compile_sparse_seed_params

    if type(section_index) is not int or section_index < 0:
        raise ValueError("A section index must be a nonnegative integer")
    params = compile_sparse_seed_params({
        "cells": spec["cells"], "nominal_length_bp": spec["length_bp"],
        "branch_tracks": [{"cell": cell, "intervals": [[0, spec["length_bp"] - 1]]}
                          for cell in spec["cells"]],
    }, history_seed)
    return SectionSeedRequest.model_validate({
        **params, "lattice_column_offset": 1000 * section_index,
    }).model_dump(mode="json", by_alias=True)


def _selection(design, body):
    from backend.core.part_scope_references import COLLECTIONS, identity_index, referenced_resources

    records, _ = identity_index(design)
    cluster = records.get(("cluster", body.cluster_id))
    if cluster is None:
        _fail("Bounded routing cluster no longer exists", body.cluster_id, missing=True)
    ids = set(cluster.helix_ids)
    if not ids or cluster.domain_ids or len(ids) != len(cluster.helix_ids) or len(ids) > 128:
        _fail("Bounded routing requires a nonempty distinct whole-helix section", body.cluster_id)
    for identity in sorted(ids):
        if ("helix", identity) not in records:
            _fail("Bounded routing section has a missing helix", identity, kind="helix", missing=True)
    helices = [helix for helix in design.helices if helix.id in ids]
    if any(helix.grid_pos is None or helix.lattice_frame_id is not None for helix in helices):
        _fail("Bounded routing requires unframed lattice tracks", body.cluster_id)
    if len({helix.grid_pos for helix in helices}) != len(helices):
        _fail("Bounded routing section has ambiguous lattice addresses", body.cluster_id)
    if sum(helix.length_bp for helix in helices) > 50_000:
        raise ProofBudgetExceeded("Bounded section exceeds proof nucleotide budget")
    strands = []
    for strand in design.strands:
        members = {domain.helix_id for domain in strand.domains}
        if not members & ids:
            continue
        if members - ids or strand.is_reference or any(
            domain.overhang_id or domain.binds_overhang_id for domain in strand.domains
        ):
            _fail("Bounded routing cannot split an existing or attached strand", body.cluster_id)
        strands.append(strand)
    helix_resources = {("helix", identity) for identity in ids}
    strand_resources = {("strand", strand.id) for strand in strands}
    cluster_resources = {("cluster", cluster.id) for cluster in design.cluster_transforms
                         if set(cluster.helix_ids) & ids or any(
                             ("strand", ref.strand_id) in strand_resources for ref in cluster.domain_ids)}
    values = {"helices": helices, "strands": strands}
    topology = {"crossovers", "forced_ligations", "crossover_constraints", "deformations"}
    for field in topology:
        values[field] = []
        for item in getattr(design, field):
            refs = referenced_resources(item)
            if not refs & (helix_resources | strand_resources | cluster_resources):
                continue
            if refs - helix_resources or (field == "deformations" and (
                item.targets or item.target_ranges or item.cluster_ids
            )):
                _fail("Bounded routing selection crosses an existing dependency", body.cluster_id)
            values[field].append(item)
    resources = helix_resources | strand_resources
    resources |= {("crossover", crossover.id) for crossover in values["crossovers"]}
    for field in COLLECTIONS.keys() - topology - {"helices", "strands"}:
        for item in getattr(design, field):
            refs = (set(("strand", ref.strand_id) for ref in item.domain_ids)
                    if field == "cluster_transforms" else referenced_resources(item))
            if refs & resources:
                _fail(f"Bounded routing target has unsupported {field} dependencies", body.cluster_id)
    return Design(lattice_type=design.lattice_type, **values).model_copy(deep=True)


def route(design, params):
    from backend.api.generated_native_scope import merge_changes
    from backend.core.part_scope_references import remap_design
    from backend.core.routing_identity import identity_scope
    from backend.core.seamed_router import auto_scaffold_seamed_bounded

    body = SectionRouteRequest.model_validate(params)
    selected = _selection(design, body)
    # Sorting the local cell names retains the original per-section router's
    # choices even when persistent UUIDs or distant addresses sort differently.
    canonical = {("helix", helix.id): f"h_XY_{helix.grid_pos[0]}_{helix.grid_pos[1] - body.lattice_column_offset}"
                 for helix in selected.helices}
    local = remap_design(selected, canonical)
    with identity_scope(body.history_seed):
        updated, report = auto_scaffold_seamed_bounded(local)
    scaffolds = [strand for strand in updated.scaffolds() if not strand.is_reference]
    if not report.valid or len(scaffolds) != 1:
        raise ValueError("Independent section could not be routed as one scaffold")
    inverse = {(kind, value): identity for (kind, identity), value in canonical.items()}
    inverse["strand", scaffolds[0].id] = str(uuid5(body.history_seed, "section-scaffold"))
    updated = remap_design(updated, inverse)
    return merge_changes(design, selected, updated), report


def build(kind, design, params):
    if kind == "independent-section-seed":
        return seed(design, params)
    if kind == "auto-scaffold-bounded-section":
        return route(design, params)[0]
    raise NotImplementedError(kind)
