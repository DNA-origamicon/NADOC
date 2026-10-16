"""Pure adapters for the existing helix/strand/domain authoring operations."""

from fastapi import HTTPException

from backend.core.models import Domain, Helix, Strand, StrandType

KINDS = frozenset(
    {
        "helix-add",
        "helix-update",
        "helix-delete",
        "helix-reorder",
        "strand-add",
        "strand-update",
        "domain-add",
        "strands-color-bulk",
        "strands-reference",
    }
)


def _replace(items, identity, replacement):
    if not any(item.id == identity for item in items):
        raise HTTPException(404, detail=f"Target {identity!r} not found")
    return [replacement if item.id == identity else item for item in items]


def build(kind, design, params):
    from backend.api.crud import HelixRequest, StrandRequest, DomainRequest

    if kind in {"helix-add", "helix-update"}:
        body = HelixRequest.model_validate(params)
        identity = params["_helix_id"] if kind == "helix-add" else params["helix_id"]
        helix = Helix(
            id=identity,
            axis_start=body.axis_start,
            axis_end=body.axis_end,
            length_bp=body.length_bp,
            phase_offset=body.phase_offset,
        )
        helices = (
            [*design.helices, helix]
            if kind == "helix-add"
            else _replace(design.helices, identity, helix)
        )
        updated = design.copy_with(helices=helices)
        if kind == "helix-add":
            from backend.core.cluster_autodetect import with_default_cluster
            from backend.core.feature_identity import identity_factory

            updated = with_default_cluster(
                updated, identity_factory=identity_factory(identity)
            )
        return updated
    if kind == "helix-delete":
        identity = params["helix_id"]
        if any(d.helix_id == identity for s in design.strands for d in s.domains):
            raise HTTPException(409, detail="Helix is referenced by strands")
        if design.find_helix(identity) is None:
            raise HTTPException(404, detail="Helix not found")
        return design.copy_with(helices=[h for h in design.helices if h.id != identity])
    if kind == "helix-reorder":
        ids = params["ordered_ids"]
        if len(set(ids)) != len(ids) or set(ids) != {h.id for h in design.helices}:
            raise HTTPException(
                400, detail="Reorder must contain every helix exactly once"
            )
        labelled = {
            h.id: h.model_copy(update={"label": str(i) if h.label is None else h.label})
            for i, h in enumerate(design.helices)
        }
        return design.copy_with(helices=[labelled[hid] for hid in ids])
    if kind in {"strand-add", "strand-update"}:
        body = StrandRequest.model_validate(params)
        if {d.helix_id for d in body.domains} - {h.id for h in design.helices}:
            raise HTTPException(404, detail="Missing strand helix")
        identity = params["_strand_id"] if kind == "strand-add" else params["strand_id"]
        strand = Strand(
            id=identity,
            domains=[
                Domain(
                    helix_id=d.helix_id,
                    start_bp=d.start_bp,
                    end_bp=d.end_bp,
                    direction=d.direction,
                )
                for d in body.domains
            ],
            strand_type=body.strand_type,
            sequence=body.sequence,
            color=params.get("_color") if kind == "strand-add" else None,
        )
        if kind == "strand-add" and strand.strand_type == StrandType.STAPLE:
            from backend.core.lattice import tag_painted_binder

            strand = tag_painted_binder(design, strand)
        strands = (
            [*design.strands, strand]
            if kind == "strand-add"
            else _replace(design.strands, identity, strand)
        )
        return design.copy_with(strands=strands)
    if kind == "domain-add":
        strand = design.find_strand(params["strand_id"])
        if strand is None:
            raise HTTPException(404, detail="Strand not found")
        body = DomainRequest.model_validate(params)
        if design.find_helix(body.helix_id) is None:
            raise HTTPException(404, detail="Missing domain helix")
        domain = Domain(
            helix_id=body.helix_id,
            start_bp=body.start_bp,
            end_bp=body.end_bp,
            direction=body.direction,
        )
        return design.copy_with(
            strands=_replace(
                design.strands,
                strand.id,
                strand.model_copy(update={"domains": [*strand.domains, domain]}),
            )
        )
    if kind in {"strands-color-bulk", "strands-reference"}:
        ids = set(params["strand_ids"])
        if ids - {s.id for s in design.strands}:
            raise HTTPException(404, detail="Strand target missing")
        field = "color" if kind == "strands-color-bulk" else "is_reference"
        return design.copy_with(
            strands=[
                s.model_copy(update={field: params.get(field)}) if s.id in ids else s
                for s in design.strands
            ]
        )
    raise NotImplementedError(kind)
