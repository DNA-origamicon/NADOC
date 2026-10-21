"""Native per-residue pose and flexible-bead commands with complete inputs."""

from fastapi import HTTPException

NUCLEOTIDE_KINDS = frozenset({
    "nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete",
})

KINDS = NUCLEOTIDE_KINDS | frozenset(
    {
        "flexible-segment-mark",
        "flexible-segment-unmark",
    }
)


def build(kind, design, params):
    if kind.startswith("nucleotide-transform"):
        from backend.api.routes_nucleotide_transforms import (
            NucleotideTransformBody,
            _cpd_unit_bodies,
            _target_exists,
            _apply_transform_body,
        )
        from backend.core.models import NucleotideTransform

        if kind.endswith("-delete"):
            identity = params["transform_id"]
            existing = next(
                (t for t in design.nucleotide_transforms if t.id == identity), None
            )
            if existing is None:
                raise HTTPException(404, detail="Missing nucleotide transform")
            if existing.kind == "extra_base":
                key = f"__xb__:{existing.crossover_id}:{existing.extra_base_k}"
                if any(
                    key in lesion.design_coordinates
                    for lesion in design.photoproduct_junctions
                ):
                    raise HTTPException(
                        422,
                        detail="Remove the CPD before resetting an individual endpoint pose.",
                    )
            return design.copy_with(
                nucleotide_transforms=[
                    t for t in design.nucleotide_transforms if t.id != identity
                ]
            )
        bodies = params["transforms"] if kind.endswith("-batch") else [params]
        bodies = _cpd_unit_bodies(
            design, [NucleotideTransformBody.model_validate(p) for p in bodies]
        )
        requested = [
            NucleotideTransform(**b.model_dump(exclude={"compose"})) for b in bodies
        ]
        if len({t.target_key() for t in requested}) != len(requested):
            raise HTTPException(422, detail="Duplicate nucleotide transform target")
        if any(not _target_exists(design, t) for t in requested):
            raise HTTPException(404, detail="Missing nucleotide transform target")
        transforms = list(design.nucleotide_transforms)
        for body in bodies:
            _apply_transform_body(
                transforms, body, identity_seed=params["history_seed"]
            )
        return design.copy_with(nucleotide_transforms=transforms)

    from backend.core.flexible_segments import apply_marks, unpaired_bead_keys
    from backend.api.routes_flexible_segments import (
        FlexibleSegmentMarkBody,
        _flex_mark_from_body,
    )

    if kind == "flexible-segment-unmark":
        if params.get("replace"):
            return apply_marks(design.copy_with(flexible_segment_marks=[]))
        ids = set(params["mark_ids"])
        if ids - {m.id for m in design.flexible_segment_marks}:
            raise HTTPException(404, detail="Missing flexible mark")
        return apply_marks(
            design.copy_with(
                flexible_segment_marks=[
                    m for m in design.flexible_segment_marks if m.id not in ids
                ]
            )
        )
    unpaired = unpaired_bead_keys(design)
    marks = [
        _flex_mark_from_body(
            design,
            FlexibleSegmentMarkBody.model_validate(m),
            unpaired,
            identity=m["id"],
        )
        for m in params["marks"]
    ]
    existing = [] if params.get("replace") else list(design.flexible_segment_marks)
    if params.get("batch"):
        seen, merged = set(), []
        for mark in [*existing, *marks]:
            key = (mark.strand_id, mark.domain_index, mark.bp_index, mark.direction)
            if key not in seen:
                merged.append(mark)
                seen.add(key)
    else:
        merged = [*existing, *marks]
    return apply_marks(design.copy_with(flexible_segment_marks=merged))
