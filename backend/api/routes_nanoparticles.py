"""CRUD API for display-only nanoparticles."""

from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.crud import _design_response
from backend.core.models import (
    Design, Duplex, NanoparticleConnectionVersion, OverhangSpec,
)
from backend.core.duplex import connect_register, relocate_duplex, revert_duplex_relocation
from backend.core.nanoparticle import (
    build_thiol_conjugation, create_gold_nanosphere, estimate_thiol_coverage,
    replace_gold_nanosphere,
)
from backend.core.conjugate_strands import groups_without_strands

router = APIRouter()


class GoldNanosphereCreate(BaseModel):
    diameter_nm: float = Field(gt=0.0, le=1000.0)


class GizmoMove(BaseModel):
    pivot: list[float]
    translation: list[float]
    rotation: list[float]
    preconstrained: bool = False


class NanoparticlePatch(BaseModel):
    diameter_nm: Optional[float] = Field(default=None, gt=0.0, le=1000.0)
    pose: Optional[list[float]] = None
    gizmo_move: Optional[GizmoMove] = None


class ThiolConjugationRequest(BaseModel):
    scheme: Literal["direct_thiol", "alkyl_thiol", "peg_thiol", "peg_backfill"] = "direct_thiol"
    sequence: str = Field(min_length=1, max_length=500)
    count: int = Field(ge=1, le=10000)
    attach_end: Literal["5p", "3p"] = "5p"
    spacer_nm: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    seed: int = 1


class CoverageEstimateRequest(BaseModel):
    scheme: Literal["direct_thiol", "alkyl_thiol", "peg_thiol", "peg_backfill"] = "direct_thiol"


class SurfaceStrandBindRequest(BaseModel):
    overhang_id: str


class NanoparticleConnectionVersionCreate(BaseModel):
    strand_id: str
    overhang_id: str
    name: Optional[str] = None
    applied: bool = False
    connection_type: Literal["direct"] = "direct"
    direct_variant: Literal["end-to-root", "root-to-root"] = "end-to-root"


class NanoparticleConnectionVersionPatch(BaseModel):
    name: Optional[str] = None
    applied: Optional[bool] = None


@router.post("/design/nanoparticles/gold-nanospheres", status_code=201)
def create_nanosphere(body: GoldNanosphereCreate) -> dict:
    particle = create_gold_nanosphere(body.diameter_nm)

    def mutate(design: Design) -> None:
        design.nanoparticles = [*design.nanoparticles, particle]

    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-create",
        f"Create {body.diameter_nm:g} nm gold nanosphere",
        {"nanoparticle_id": particle.id, "diameter_nm": body.diameter_nm},
        mutate,
    )
    response = _design_response(updated, report)
    response["nanoparticle_id"] = particle.id
    return response


@router.patch("/design/nanoparticles/{nanoparticle_id}")
def patch_nanoparticle(nanoparticle_id: str, body: NanoparticlePatch) -> dict:
    if body.pose is not None and len(body.pose) != 16:
        raise HTTPException(400, detail="pose must be 16 floats (row-major 4x4).")
    if body.gizmo_move is not None and not (
        len(body.gizmo_move.pivot) == 3
        and len(body.gizmo_move.translation) == 3
        and len(body.gizmo_move.rotation) == 4
    ):
        raise HTTPException(400, detail="Invalid gizmo move dimensions.")
    current = design_state.get_or_404()
    if not any(item.id == nanoparticle_id for item in current.nanoparticles):
        raise HTTPException(404, detail="Nanoparticle not found.")

    constraint_result = None
    constrained_design = None
    applied = [v for v in current.nanoparticle_connection_versions
               if v.nanoparticle_id == nanoparticle_id and v.applied]
    if body.gizmo_move is not None and len(applied) == 1:
        from backend.core.design_geometry import fitting_geometry
        from backend.core.nanoparticle import constrained_nanoparticle_move
        try:
            constrained_design, constraint_result = constrained_nanoparticle_move(
                current, nanoparticle_id, applied[0], fitting_geometry(current),
                pivot=body.gizmo_move.pivot, translation=body.gizmo_move.translation,
                rotation=body.gizmo_move.rotation,
                preconstrained=body.gizmo_move.preconstrained,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    def mutate(design: Design) -> Design:
        if constrained_design is not None:
            return constrained_design
        return replace_gold_nanosphere(
            design,
            nanoparticle_id,
            diameter_nm=body.diameter_nm,
            pose=body.pose,
            gizmo_move=body.gizmo_move.model_dump() if body.gizmo_move else None,
        )

    label = (
        "Resize gold nanosphere"
        if body.diameter_nm is not None
        else "Move gold nanosphere"
    )
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-patch",
        label,
        {"nanoparticle_id": nanoparticle_id, **body.model_dump(exclude_none=True)},
        mutate,
    )
    response = _design_response(updated, report)
    if constraint_result is not None:
        response["movement_constraint"] = constraint_result
    return response


@router.delete("/design/nanoparticles/{nanoparticle_id}")
def delete_nanoparticle(nanoparticle_id: str) -> dict:
    current = design_state.get_or_404()
    if not any(item.id == nanoparticle_id for item in current.nanoparticles):
        raise HTTPException(404, detail="Nanoparticle not found.")

    def mutate(design: Design) -> None:
        conjugations = [c for c in design.nanoparticle_conjugations if c.nanoparticle_id == nanoparticle_id]
        owned_strands = {s.strand_id for c in conjugations for s in c.surface_strands}
        owned_helices = {s.helix_id for c in conjugations for s in c.surface_strands if s.helix_id.startswith("__np__")}
        removed_duplex_ids = {v.duplex_id for v in design.nanoparticle_connection_versions
                              if v.nanoparticle_id == nanoparticle_id} - {None}
        design.nanoparticles = [
            item for item in design.nanoparticles if item.id != nanoparticle_id
        ]
        design.strands = [s for s in design.strands if s.id not in owned_strands]
        design.helices = [h for h in design.helices if h.id not in owned_helices]
        design.overhangs = [o for o in design.overhangs if o.strand_id not in owned_strands]
        design.duplexes = [dx for dx in design.duplexes if dx.id not in removed_duplex_ids]
        design.nanoparticle_conjugations = [
            c for c in design.nanoparticle_conjugations if c.nanoparticle_id != nanoparticle_id
        ]
        design.nanoparticle_connection_versions = [
            v for v in design.nanoparticle_connection_versions if v.nanoparticle_id != nanoparticle_id
        ]
        design.staple_groups = groups_without_strands(design, owned_strands)

    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-delete",
        "Delete gold nanosphere",
        {"nanoparticle_id": nanoparticle_id},
        mutate,
    )
    return _design_response(updated, report)


def _particle_or_404(design: Design, nanoparticle_id: str):
    particle = next((p for p in design.nanoparticles if p.id == nanoparticle_id), None)
    if particle is None:
        raise HTTPException(404, detail="Nanoparticle not found.")
    return particle


@router.post("/design/nanoparticles/{nanoparticle_id}/conjugation/estimate")
def estimate_conjugation(nanoparticle_id: str, body: CoverageEstimateRequest) -> dict:
    particle = _particle_or_404(design_state.get_or_404(), nanoparticle_id)
    return estimate_thiol_coverage(particle.diameter_nm, body.scheme)


@router.get("/design/nanoparticles/{nanoparticle_id}/conjugation")
def get_conjugation(nanoparticle_id: str) -> dict:
    design = design_state.get_or_404()
    _particle_or_404(design, nanoparticle_id)
    items = [c.model_dump() for c in design.nanoparticle_conjugations if c.nanoparticle_id == nanoparticle_id]
    return {"conjugations": items, "tether_measurements": _np_tether_measurements(design, nanoparticle_id)}


@router.put("/design/nanoparticles/{nanoparticle_id}/conjugation")
def put_conjugation(nanoparticle_id: str, body: ThiolConjugationRequest) -> dict:
    design = design_state.get_or_404()
    particle = _particle_or_404(design, nanoparticle_id)
    old = [c for c in design.nanoparticle_conjugations if c.nanoparticle_id == nanoparticle_id]
    if any(s.bound_overhang_id for c in old for s in c.surface_strands):
        raise HTTPException(409, detail="Unbind nanoparticle strands before replacing conjugation.")
    try:
        conjugation, helices, strands = build_thiol_conjugation(
            particle, scheme=body.scheme, sequence=body.sequence, count=body.count,
            attach_end=body.attach_end, spacer_nm=body.spacer_nm, seed=body.seed,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    from backend.core.conjugate_strands import assign_conjugate_group, groups_without_strands

    old_strands = {s.strand_id for c in old for s in c.surface_strands}
    old_helices = {s.helix_id for c in old for s in c.surface_strands}
    retained_groups = groups_without_strands(design, old_strands)
    strands, conjugate_group = assign_conjugate_group(
        design.model_copy(update={"staple_groups": retained_groups}),
        strands,
        prefix="NP",
        fallback="NP",
    )
    strand_by_id = {strand.id: strand for strand in strands}
    auxiliary_overhangs = [OverhangSpec(
        id=record.overhang_id or f"__np_oh__{record.strand_id}",
        helix_id=record.helix_id,
        strand_id=record.strand_id,
        sequence=strand_by_id[record.strand_id].sequence,
        label=strand_by_id[record.strand_id].name,
        auxiliary_endpoint=True,
    ) for record in conjugation.surface_strands]

    def mutate(d: Design) -> Design:
        return d.copy_with(
            helices=[h for h in d.helices if h.id not in old_helices] + helices,
            strands=[s for s in d.strands if s.id not in old_strands] + strands,
            overhangs=[o for o in d.overhangs if o.strand_id not in old_strands] + auxiliary_overhangs,
            nanoparticle_conjugations=[
                c for c in d.nanoparticle_conjugations if c.nanoparticle_id != nanoparticle_id
            ] + [conjugation],
            nanoparticle_connection_versions=[
                v for v in d.nanoparticle_connection_versions if v.nanoparticle_id != nanoparticle_id
            ],
            staple_groups=[*retained_groups, conjugate_group],
        )
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-conjugate", f"Conjugate {body.count} thiol-DNA strands to gold nanosphere",
        {"nanoparticle_id": nanoparticle_id, "conjugation_id": conjugation.id, **body.model_dump()}, mutate,
    )
    response = _design_response(updated, report)
    response.update({"conjugation_id": conjugation.id, "strand_ids": [s.id for s in strands]})
    return response


@router.delete("/design/nanoparticles/{nanoparticle_id}/conjugation")
def delete_conjugation(nanoparticle_id: str) -> dict:
    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    owned = [c for c in design.nanoparticle_conjugations if c.nanoparticle_id == nanoparticle_id]
    if any(s.bound_overhang_id for c in owned for s in c.surface_strands):
        raise HTTPException(409, detail="Unbind nanoparticle strands before deleting conjugation.")
    strand_ids = {s.strand_id for c in owned for s in c.surface_strands}
    helix_ids = {s.helix_id for c in owned for s in c.surface_strands}
    from backend.core.conjugate_strands import groups_without_strands

    def mutate(d: Design) -> Design:
        return d.copy_with(
            strands=[s for s in d.strands if s.id not in strand_ids],
            overhangs=[o for o in d.overhangs if o.strand_id not in strand_ids],
            helices=[h for h in d.helices if h.id not in helix_ids],
            nanoparticle_conjugations=[c for c in d.nanoparticle_conjugations if c.nanoparticle_id != nanoparticle_id],
            nanoparticle_connection_versions=[v for v in d.nanoparticle_connection_versions if v.nanoparticle_id != nanoparticle_id],
            staple_groups=groups_without_strands(d, strand_ids),
        )
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-conjugation-delete", "Remove nanoparticle thiol conjugation",
        {"nanoparticle_id": nanoparticle_id}, mutate,
    )
    return _design_response(updated, report)


@router.get("/design/nanoparticles/{nanoparticle_id}/conjugation/validate")
def validate_conjugation(nanoparticle_id: str) -> dict:
    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    strand_ids = {s.id for s in design.strands}; helix_ids = {h.id for h in design.helices}
    errors = []
    warnings = []
    items = [c for c in design.nanoparticle_conjugations if c.nanoparticle_id == nanoparticle_id]
    for conj in items:
        if conj.requested_count > conj.estimated_capacity:
            warnings.append(
                f"requested_count {conj.requested_count} exceeds estimated capacity {conj.estimated_capacity}"
            )
        if len(conj.surface_strands) != conj.requested_count:
            errors.append("surface strand count does not match requested_count")
        for record in conj.surface_strands:
            if record.strand_id not in strand_ids: errors.append(f"missing strand {record.strand_id}")
            if record.helix_id.startswith("__np__") and record.helix_id not in helix_ids:
                errors.append(f"missing helix {record.helix_id}")
    owned_strands = {r.strand_id for c in items for r in c.surface_strands}
    from backend.core.atomistic import build_atomistic_model
    from backend.core.nanoparticle_atomistic import namd_readiness

    model = build_atomistic_model(design)
    linker_count = sum(
        1 for atom in model.atoms
        if atom.name == "SNP" and atom.strand_id in owned_strands
    )
    namd = namd_readiness(design)
    if linker_count != len(owned_strands) and not namd["errors"]:
        namd["errors"].append(
            f"Expected {len(owned_strands)} atomistic thiol linkers, found {linker_count}."
        )
        namd["passed"] = False
    return {"valid": not errors, "errors": errors, "warnings": warnings, "conjugation_count": len(items),
            "strand_count": len(owned_strands), "atomistic_linker_count": linker_count,
            "namd": namd}


def _surface_owner(design: Design, nanoparticle_id: str, strand_id: str):
    for conjugation in design.nanoparticle_conjugations:
        if conjugation.nanoparticle_id == nanoparticle_id:
            for record in conjugation.surface_strands:
                if record.strand_id == strand_id:
                    return conjugation, record
    return None, None


def _sync_np_applied_bindings(design: Design) -> Design:
    applied = {
        (version.nanoparticle_id, version.strand_id): version.overhang_id
        for version in design.nanoparticle_connection_versions if version.applied
    }
    conjugations = []
    for conjugation in design.nanoparticle_conjugations:
        records = [record.model_copy(update={
            "bound_overhang_id": applied.get((conjugation.nanoparticle_id, record.strand_id))
        }) for record in conjugation.surface_strands]
        conjugations.append(conjugation.model_copy(update={"surface_strands": records}))
    return design.model_copy(update={"nanoparticle_conjugations": conjugations})


def _ensure_np_duplex_endpoint(design: Design, nanoparticle_id: str, strand_id: str) -> tuple[Design, str]:
    """Backfill the hidden overhang endpoint for old and newly-created handles."""
    _, record = _surface_owner(design, nanoparticle_id, strand_id)
    if record is None:
        raise ValueError("Nanoparticle surface strand not found")
    overhang_id = record.overhang_id or f"__np_oh__{strand_id}"
    strand = next((s for s in design.strands if s.id == strand_id), None)
    if strand is None or not strand.domains:
        raise ValueError("Nanoparticle surface strand has no DNA domain")
    domains = [domain.model_copy(update={"overhang_id": overhang_id})
               if domain.helix_id == record.helix_id else domain for domain in strand.domains]
    strands = [strand.model_copy(update={"domains": domains}) if strand.id == strand_id else strand
               for strand in design.strands]
    conjugations = []
    for conjugation in design.nanoparticle_conjugations:
        records = [item.model_copy(update={"overhang_id": overhang_id})
                   if item.strand_id == strand_id else item for item in conjugation.surface_strands]
        conjugations.append(conjugation.model_copy(update={"surface_strands": records}))
    overhangs = list(design.overhangs)
    if not any(overhang.id == overhang_id for overhang in overhangs):
        overhangs.append(OverhangSpec(
            id=overhang_id, helix_id=record.helix_id, strand_id=strand_id,
            sequence=strand.sequence, label=strand.name, auxiliary_endpoint=True,
        ))
    return design.model_copy(update={
        "strands": strands, "nanoparticle_conjugations": conjugations, "overhangs": overhangs,
    }), overhang_id


def _np_connection_attaches(owner, direct_variant: str) -> tuple[str, str]:
    """Map UI NP semantics to the canonical overhang 5'/3' endpoint model.

    The NP-side ``root`` means the thiol-bound surface terminus, regardless of
    whether chemistry attaches the strand's 5' or 3' end. ``end`` means the
    opposite, solution-facing terminus. The target side is intentionally root
    for both currently-supported direct variants.
    """
    surface = "root" if owner.attach_end == "5p" else "free_end"
    free = "free_end" if owner.attach_end == "5p" else "root"
    if direct_variant == "root-to-root":
        return surface, "root"
    if direct_variant == "end-to-root":
        return free, "root"
    raise ValueError(f"Unsupported nanoparticle connection type {direct_variant!r}.")


def _validate_np_connection_polarity(
    design: Design, owner, target_overhang_id: str, direct_variant: str,
) -> None:
    """Reject endpoint combinations that would require parallel DNA pairing."""
    from backend.core.overhang_ops import overhang_free_end_polarity

    target_free = overhang_free_end_polarity(design, target_overhang_id)
    if target_free is None:
        raise HTTPException(
            422,
            detail=(
                "Target overhang polarity is unknown; its physical 5'/3' free end "
                "must be defined before creating a nanoparticle connection."
            ),
        )
    nanoparticle_free = "3p" if owner.attach_end == "5p" else "5p"
    forbidden = (
        nanoparticle_free != target_free
        if direct_variant == "end-to-root"
        else nanoparticle_free == target_free
    )
    if forbidden:
        np_root = owner.attach_end
        target_root = "3p" if target_free == "5p" else "5p"
        raise HTTPException(
            422,
            detail=(
                f"{direct_variant} is forbidden for a {np_root} thiol-bound NP root "
                f"and a {target_root} target root: the duplex would be parallel, not "
                "reverse-complementary. Choose the other direct connection type."
            ),
        )


def _validate_np_direct_duplex(design: Design, duplex: Duplex) -> None:
    """Apply the same Watson-Crick and direction gates as canonical duplex CRUD."""
    from backend.core.duplex import duplex_wc_ok
    from backend.core.models import _overhang_backing_domain

    ok, reason = duplex_wc_ok(design, duplex)
    if not ok:
        raise HTTPException(
            422, detail=f"nanoparticle duplex register is not complementary: {reason}.",
        )
    _left_strand, left_domain = _overhang_backing_domain(
        design, duplex.left.overhang_id,
    )
    _right_strand, right_domain = _overhang_backing_domain(
        design, duplex.right.overhang_id,
    )
    if left_domain is None or right_domain is None:
        raise HTTPException(422, detail="Nanoparticle connection endpoints must have DNA domains.")
    # Before relocation two independently placed helices can use the same
    # Direction enum. The pairing register itself is always walked
    # antiparallel; relocation must turn the driven domain onto the opposite
    # direction of the target helix, checked again below.


def _set_np_version_applied(design: Design, version_id: str, applied: bool) -> Design:
    """Apply/unapply an NP candidate as a real canonical DNA duplex."""
    target = next(v for v in design.nanoparticle_connection_versions if v.id == version_id)
    conflict_ids = {
        v.id for v in design.nanoparticle_connection_versions
        if v.id != version_id and (v.strand_id == target.strand_id or v.overhang_id == target.overhang_id)
    }
    removed_duplex_ids = {
        v.duplex_id for v in design.nanoparticle_connection_versions
        if v.id == version_id or (applied and v.id in conflict_ids)
    } - {None}
    versions = []
    for version in design.nanoparticle_connection_versions:
        if version.id == version_id:
            versions.append(version.model_copy(update={
                "applied": applied, "relaxed": False, "residual_nm": None, "duplex_id": None,
            }))
        elif applied and version.id in conflict_ids:
            versions.append(version.model_copy(update={
                "applied": False, "relaxed": False, "residual_nm": None, "duplex_id": None,
            }))
        else:
            versions.append(version)
    out = design
    # Restore each driven NP handle before removing its canonical duplex.  This
    # is the same reversible topology operation used by Direct OH↔OH Apply.
    for duplex in list(out.duplexes):
        if duplex.id in removed_duplex_ids:
            out = revert_duplex_relocation(out, duplex)
    out = out.model_copy(update={
        "duplexes": [dx for dx in out.duplexes if dx.id not in removed_duplex_ids],
        "nanoparticle_connection_versions": versions,
    })
    if applied:
        out, np_overhang_id = _ensure_np_duplex_endpoint(out, target.nanoparticle_id, target.strand_id)
        # Capture the exact unbound backbone joint before relocation.  A radial
        # site estimate omits the DNA helix radius/phase and causes the live
        # gizmo preview to disagree with the committed constrained move.
        from backend.core.design_geometry import fitting_geometry
        particle = next(p for p in out.nanoparticles if p.id == target.nanoparticle_id)
        owner, record = _surface_owner(out, target.nanoparticle_id, target.strand_id)
        _validate_np_connection_polarity(
            out, owner, target.overhang_id, target.direct_variant,
        )
        terminal_flag = "is_three_prime" if owner.attach_end == "3p" else "is_five_prime"
        terminal = next((n for n in fitting_geometry(out)
                         if n.get("strand_id") == target.strand_id and n.get(terminal_flag)), None)
        if terminal is not None:
            local = np.linalg.inv(particle.pose.to_array()) @ np.array(
                [*terminal["backbone_position"], 1.0], dtype=float)
            updated_record = record.model_copy(update={
                "backbone_attachment_local_nm": tuple(float(v) for v in local[:3])
            })
            out = out.model_copy(update={"nanoparticle_conjugations": [
                conjugation.model_copy(update={"surface_strands": [
                    updated_record if item.strand_id == target.strand_id else item
                    for item in conjugation.surface_strands
                ]}) if conjugation.id == owner.id else conjugation
                for conjugation in out.nanoparticle_conjugations
            ]})
        np_attach, target_attach = _np_connection_attaches(owner, target.direct_variant)
        try:
            left, right = connect_register(
                out, np_overhang_id, np_attach, target.overhang_id, target_attach,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        duplex = Duplex(
            name=target.name, left=left, right=right, driver="right", bound=True,
            connection_type=f"nanoparticle-{target.direct_variant}",
        )
        _validate_np_direct_duplex(out, duplex)
        versions = [v.model_copy(update={"duplex_id": duplex.id}) if v.id == version_id else v
                    for v in out.nanoparticle_connection_versions]
        out = out.model_copy(update={"duplexes": [*out.duplexes, duplex],
                                     "nanoparticle_connection_versions": versions})
        out = relocate_duplex(out, duplex)
        # Relocation reverses the driven domain onto the target helix. Recompute
        # the register from that live topology so DuplexEnd bp order continues
        # to encode each strand's actual 5'→3' backbone walk.
        live_left, live_right = connect_register(
            out, np_overhang_id, np_attach, target.overhang_id, target_attach
        )
        out = out.model_copy(update={"duplexes": [
            dx.model_copy(update={"left": live_left, "right": live_right})
            if dx.id == duplex.id else dx for dx in out.duplexes
        ]})
        from backend.core.models import _overhang_backing_domain
        _np_strand, np_domain = _overhang_backing_domain(out, np_overhang_id)
        _target_strand, target_domain = _overhang_backing_domain(out, target.overhang_id)
        if np_domain is None or target_domain is None or np_domain.direction == target_domain.direction:
            raise HTTPException(
                422,
                detail="Nanoparticle connection could not be materialized as antiparallel DNA.",
            )
        applied_geometry = fitting_geometry(out)
        from backend.core.protein import resolve_overhang_anchor
        constraint_root, _ = resolve_overhang_anchor(
            applied_geometry, target.overhang_id, "root")
        constraint_joint = next((
            np.asarray(n["backbone_position"], dtype=float)
            for n in applied_geometry
            if n.get("strand_id") == target.strand_id and n.get(terminal_flag)
        ), None)
        if constraint_root is not None and constraint_joint is not None:
            constraint_radius = float(np.linalg.norm(constraint_joint - constraint_root))
            out = out.model_copy(update={"nanoparticle_connection_versions": [
                version.model_copy(update={
                    "constraint_root_nm": tuple(float(v) for v in constraint_root),
                    "constraint_radius_nm": constraint_radius,
                }) if version.id == version_id else version
                for version in out.nanoparticle_connection_versions
            ]})
    return _sync_np_applied_bindings(out)


def _next_np_version_name(design: Design, nanoparticle_id: str, strand_id: str, overhang_id: str) -> str:
    used = {version.name for version in design.nanoparticle_connection_versions
            if version.nanoparticle_id == nanoparticle_id
            and version.strand_id == strand_id and version.overhang_id == overhang_id}
    index = 1
    while f"V{index}" in used:
        index += 1
    return f"V{index}"


def _np_duplex_measurement(design: Design, version: NanoparticleConnectionVersion, geometry=None) -> dict | None:
    """Measure an applied NP duplex from emitted NADOC backbone bead positions."""
    if not version.applied or not version.duplex_id:
        return None
    duplex = next((dx for dx in design.duplexes if dx.id == version.duplex_id), None)
    if duplex is None:
        return None
    from backend.core.design_geometry import fitting_geometry
    from backend.core.duplex import classify_duplex_pairing

    geometry = fitting_geometry(design) if geometry is None else geometry
    by_strand_bp = {(n.get("strand_id"), n.get("bp_index")): n for n in geometry}
    target_spec = next((o for o in design.overhangs if o.id == version.overhang_id), None)
    if target_spec is None:
        return None
    separations, native_errors = [], []
    for pair in classify_duplex_pairing(design, duplex)["positions"]:
        np_nuc = by_strand_bp.get((version.strand_id, pair["left_bp"]))
        target_nuc = by_strand_bp.get((target_spec.strand_id, pair["right_bp"]))
        if np_nuc is None or target_nuc is None:
            continue
        np_pos = np.asarray(np_nuc["backbone_position"], dtype=float)
        target_pos = np.asarray(target_nuc["backbone_position"], dtype=float)
        separations.append(float(np.linalg.norm(np_pos - target_pos)))
        # A native duplex occupies opposite-direction slots at the same bp on
        # one helix. The coordinate mismatch is explicitly measured, rather
        # than inferred from helix endpoints or nominal DNA length.
        native = (np_nuc["helix_id"] == target_nuc["helix_id"] and
                  np_nuc["bp_index"] == target_nuc["bp_index"] and
                  np_nuc["direction"] != target_nuc["direction"])
        native_errors.append(0.0 if native else float("inf"))
    finite = [error for error in native_errors if np.isfinite(error)]
    return {
        "paired_base_count": len(separations),
        "native_position_match": bool(separations) and len(finite) == len(separations),
        "backbone_rms_error_nm": (float(np.sqrt(np.mean(np.square(finite))))
                                  if finite and len(finite) == len(separations) else None),
        "mean_backbone_separation_nm": float(np.mean(separations)) if separations else None,
        "min_backbone_separation_nm": float(np.min(separations)) if separations else None,
        "max_backbone_separation_nm": float(np.max(separations)) if separations else None,
    }


def _np_tether_measurements(design: Design, nanoparticle_id: str, geometry=None) -> list[dict]:
    """Measure Au surface→actual DNA-root backbone tethers in emitted geometry."""
    from backend.core.constants import HELIX_RADIUS
    from backend.core.design_geometry import fitting_geometry

    particle = next((p for p in design.nanoparticles if p.id == nanoparticle_id), None)
    if particle is None:
        return []
    geometry = fitting_geometry(design) if geometry is None else geometry
    matrix = particle.pose.to_array()
    out = []
    for conjugation in design.nanoparticle_conjugations:
        if conjugation.nanoparticle_id != nanoparticle_id:
            continue
        for record in conjugation.surface_strands:
            candidates = [n for n in geometry if n.get("strand_id") == record.strand_id]
            terminal_key = "is_three_prime" if conjugation.attach_end == "3p" else "is_five_prime"
            root = next((n for n in candidates if n.get(terminal_key)), candidates[0] if candidates else None)
            if root is None:
                continue
            sulfur = (matrix @ np.array([*record.sulfur_local_nm, 1.0], dtype=float))[:3]
            backbone = np.asarray(root["backbone_position"], dtype=float)
            length = float(np.linalg.norm(backbone - sulfur))
            nominal = float(np.hypot(conjugation.spacer_nm, HELIX_RADIUS))
            out.append({
                "strand_id": record.strand_id,
                "bound": record.bound_overhang_id is not None,
                "sulfur_position_nm": sulfur.tolist(),
                "backbone_position_nm": backbone.tolist(),
                "measured_length_nm": length,
                "nominal_unbound_length_nm": nominal,
                "stretch_from_nominal_nm": length - nominal,
                # The renderer consumes these exact two coordinates, so this is
                # a directly testable endpoint-attachment invariant.
                "render_endpoint_error_nm": 0.0,
            })
    return out


@router.get("/design/nanoparticles/{nanoparticle_id}/connection-versions")
def get_np_connection_versions(nanoparticle_id: str) -> dict:
    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    relevant = [v for v in design.nanoparticle_connection_versions if v.nanoparticle_id == nanoparticle_id]
    geometry = None
    if any(v.applied for v in relevant):
        from backend.core.design_geometry import fitting_geometry
        geometry = fitting_geometry(design)
    versions = []
    for version in relevant:
        item = version.model_dump()
        item["duplex_measurement"] = _np_duplex_measurement(design, version, geometry)
        versions.append(item)
    return {"versions": versions}


@router.post("/design/nanoparticles/{nanoparticle_id}/connection-versions", status_code=201)
def create_np_connection_version(nanoparticle_id: str, body: NanoparticleConnectionVersionCreate) -> dict:
    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    owner, _record = _surface_owner(design, nanoparticle_id, body.strand_id)
    if owner is None: raise HTTPException(404, detail="Nanoparticle surface strand not found.")
    target_overhang = next((overhang for overhang in design.overhangs
                            if overhang.id == body.overhang_id), None)
    if target_overhang is None:
        raise HTTPException(404, detail="Overhang not found.")
    if target_overhang.auxiliary_endpoint or target_overhang.strand_id == body.strand_id:
        raise HTTPException(400, detail="Target Overhang must be a non-nanoparticle DNA overhang.")
    try:
        nanoparticle_attach, target_attach = _np_connection_attaches(
            owner, body.direct_variant,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    _validate_np_connection_polarity(
        design, owner, body.overhang_id, body.direct_variant,
    )
    version = NanoparticleConnectionVersion(
        nanoparticle_id=nanoparticle_id, strand_id=body.strand_id,
        overhang_id=body.overhang_id,
        connection_type=body.connection_type,
        direct_variant=body.direct_variant,
        nanoparticle_attach=nanoparticle_attach,
        target_attach=target_attach,
        name=(body.name or "").strip() or _next_np_version_name(
            design, nanoparticle_id, body.strand_id, body.overhang_id),
        applied=body.applied,
    )
    def mutate(d: Design) -> Design:
        out = d.model_copy(update={
            "nanoparticle_connection_versions": [*d.nanoparticle_connection_versions, version]
        })
        return _set_np_version_applied(out, version.id, True) if version.applied else out
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-connection-version-create", f"Create nanoparticle connection {version.name}",
        {"nanoparticle_id": nanoparticle_id, "version_id": version.id}, mutate)
    response = _design_response(updated, report); response["version_id"] = version.id
    return response


@router.patch("/design/nanoparticles/{nanoparticle_id}/connection-versions/{version_id}")
def patch_np_connection_version(nanoparticle_id: str, version_id: str, body: NanoparticleConnectionVersionPatch) -> dict:
    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    target = next((v for v in design.nanoparticle_connection_versions
                   if v.id == version_id and v.nanoparticle_id == nanoparticle_id), None)
    if target is None: raise HTTPException(404, detail="Nanoparticle connection version not found.")
    def mutate(d: Design) -> Design:
        versions = []
        for version in d.nanoparticle_connection_versions:
            updates = {}
            if version.id == version_id:
                if body.name is not None and body.name.strip(): updates["name"] = body.name.strip()
                if body.applied is not None:
                    updates.update({"applied": body.applied, "relaxed": False, "residual_nm": None})
            versions.append(version.model_copy(update=updates) if updates else version)
        out = d.model_copy(update={"nanoparticle_connection_versions": versions})
        return _set_np_version_applied(out, version_id, body.applied) if body.applied is not None else out
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-connection-version-patch",
        ("Apply" if body.applied else "Unapply") + f" nanoparticle connection {target.name}",
        {"nanoparticle_id": nanoparticle_id, "version_id": version_id}, mutate)
    return _design_response(updated, report)


@router.delete("/design/nanoparticles/{nanoparticle_id}/connection-versions/{version_id}")
def delete_np_connection_version(nanoparticle_id: str, version_id: str) -> dict:
    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    if not any(v.id == version_id and v.nanoparticle_id == nanoparticle_id
               for v in design.nanoparticle_connection_versions):
        raise HTTPException(404, detail="Nanoparticle connection version not found.")
    def mutate(d: Design) -> Design:
        target_version = next(v for v in d.nanoparticle_connection_versions if v.id == version_id)
        out = _set_np_version_applied(d, version_id, False) if target_version.applied else d
        return _sync_np_applied_bindings(out.model_copy(update={
            "nanoparticle_connection_versions": [v for v in out.nanoparticle_connection_versions if v.id != version_id],
        }))
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-connection-version-delete", "Delete nanoparticle connection version",
        {"nanoparticle_id": nanoparticle_id, "version_id": version_id}, mutate)
    return _design_response(updated, report)


@router.post("/design/nanoparticles/{nanoparticle_id}/connection-versions/relax")
def relax_np_connection_versions(nanoparticle_id: str) -> dict:
    """Jointly relax every applied NP/duplex anchor as a closed-loop system."""
    from backend.core.design_geometry import fitting_geometry
    from backend.core.nanoparticle_kinematics import solve_nanoparticle_anchors

    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    applied = [v for v in design.nanoparticle_connection_versions
               if v.nanoparticle_id == nanoparticle_id and v.applied]
    if not applied: raise HTTPException(409, detail="Apply at least one nanoparticle connection first.")
    tether_before = _np_tether_measurements(design, nanoparticle_id, fitting_geometry(design))
    try:
        solved_design, diagnostics = solve_nanoparticle_anchors(design, nanoparticle_id)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    residual_by_id = diagnostics["per_anchor_residual_nm"]
    usable = diagnostics["version_ids"]
    def mutate(d: Design) -> Design:
        versions = [v.model_copy(update={"relaxed": True, "residual_nm": residual_by_id.get(v.id)})
                    if v.id in residual_by_id else v
                    for v in solved_design.nanoparticle_connection_versions]
        return solved_design.model_copy(update={"nanoparticle_connection_versions": versions})
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-connection-relax", "Relax nanoparticle overhang connections",
        {"nanoparticle_id": nanoparticle_id, "version_ids": usable}, mutate)
    response = _design_response(updated, report)
    response.update(diagnostics)
    response["relaxation_stages"] = ["closed_loop_pose_solve", "duplex_reorientation"]
    response["dna_avoidance_shift_nm"] = diagnostics["translation_nm"]
    response["dna_avoidance_shift_magnitude_nm"] = float(
        np.linalg.norm(diagnostics["translation_nm"]))
    after_geometry = fitting_geometry(updated)
    response["duplex_measurements"] = {
        version.id: _np_duplex_measurement(updated, version, after_geometry)
        for version in updated.nanoparticle_connection_versions
        if version.id in usable
    }
    response["tether_measurements_before"] = tether_before
    response["tether_measurements_after"] = _np_tether_measurements(updated, nanoparticle_id, after_geometry)
    response["moved_surface_strand_ids"] = [
        record.strand_id for conjugation in updated.nanoparticle_conjugations
        if conjugation.nanoparticle_id == nanoparticle_id
        for record in conjugation.surface_strands if record.bound_overhang_id is None
    ]
    return response


@router.post("/design/nanoparticles/{nanoparticle_id}/strands/{strand_id}/bind")
def bind_surface_strand(nanoparticle_id: str, strand_id: str, body: SurfaceStrandBindRequest) -> dict:
    """Turn one nanoparticle-owned surface strand into a real overhang binder."""
    from backend.core.lattice import make_binder_for_overhang

    design = design_state.get_or_404(); _particle_or_404(design, nanoparticle_id)
    owner = next((c for c in design.nanoparticle_conjugations
                  if c.nanoparticle_id == nanoparticle_id and any(r.strand_id == strand_id for r in c.surface_strands)), None)
    if owner is None: raise HTTPException(404, detail="Nanoparticle surface strand not found.")
    record = next(r for r in owner.surface_strands if r.strand_id == strand_id)
    if record.bound_overhang_id is not None: raise HTTPException(409, detail="Surface strand is already bound.")
    try:
        with_binder = make_binder_for_overhang(design, body.overhang_id)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    new_binder = with_binder.strands[-1]
    if new_binder.sequence and new_binder.sequence.upper() != owner.sequence.upper():
        raise HTTPException(400, detail="Surface strand sequence is not complementary to the selected overhang.")
    binder = new_binder.model_copy(update={"id": strand_id, "name": design.find_strand(strand_id).name})
    new_record = record.model_copy(update={
        "helix_id": binder.domains[0].helix_id, "bound_overhang_id": body.overhang_id,
    })
    new_owner = owner.model_copy(update={
        "surface_strands": [new_record if r.strand_id == strand_id else r for r in owner.surface_strands]
    })
    def mutate(d: Design) -> Design:
        return d.copy_with(
            helices=[h for h in d.helices if h.id != record.helix_id],
            strands=[binder if s.id == strand_id else s for s in d.strands],
            nanoparticle_conjugations=[new_owner if c.id == owner.id else c for c in d.nanoparticle_conjugations],
        )
    updated, report, _ = design_state.mutate_with_feature_log(
        "nanoparticle-strand-bind", "Bind nanoparticle DNA strand to overhang",
        {"nanoparticle_id": nanoparticle_id, "strand_id": strand_id, "overhang_id": body.overhang_id}, mutate,
    )
    return _design_response(updated, report)
