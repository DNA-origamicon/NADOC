"""Existing nanoparticle endpoint, naming and native application operations.

Application arithmetic and operation order are shared by compatibility routes
and explicit recipes; only recipes supply deterministic output IDs and time.
"""

import numpy as np

from backend.core.overhang_ops import overhang_free_end_polarity
from backend.core.models import Design, Duplex, OverhangSpec
from backend.core.duplex import connect_register, relocate_duplex, revert_duplex_relocation


class ConnectionApplicationError(ValueError):
    """Native application failure; the API boundary owns HTTP translation."""

    def __init__(self, status_code, *, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def connection_attaches(owner, direct_variant):
    """Map NP chemical ends to the existing canonical 5'/3' endpoint model."""
    surface = "root" if owner.attach_end == "5p" else "free_end"
    free = "free_end" if owner.attach_end == "5p" else "root"
    if direct_variant == "root-to-root":
        return surface, "root"
    if direct_variant == "end-to-root":
        return free, "root"
    raise ValueError(f"Unsupported nanoparticle connection type {direct_variant!r}.")


def polarity_error(design, owner, target_overhang_id, direct_variant):
    """Return the unchanged legacy error and its authored selector, or None."""
    target_free = overhang_free_end_polarity(design, target_overhang_id)
    if target_free is None:
        return ("Target overhang polarity is unknown; its physical 5'/3' free end "
                "must be defined before creating a nanoparticle connection.", "overhang_id")
    nanoparticle_free = "3p" if owner.attach_end == "5p" else "5p"
    forbidden = (nanoparticle_free != target_free if direct_variant == "end-to-root"
                 else nanoparticle_free == target_free)
    if forbidden:
        np_root = owner.attach_end
        target_root = "3p" if target_free == "5p" else "5p"
        return (f"{direct_variant} is forbidden for a {np_root} thiol-bound NP root "
                f"and a {target_root} target root: the duplex would be parallel, not "
                "reverse-complementary. Choose the other direct connection type.", "direct_variant")
    return None


def next_version_name(design, nanoparticle_id, strand_id, overhang_id):
    used = {version.name for version in design.nanoparticle_connection_versions
            if version.nanoparticle_id == nanoparticle_id
            and version.strand_id == strand_id and version.overhang_id == overhang_id}
    index = 1
    while f"V{index}" in used:
        index += 1
    return f"V{index}"


# Shared native application. The interactive wrappers keep their historical
# random/default identities; versioned commands supply explicit IDs/time.


def surface_owner(design: Design, nanoparticle_id: str, strand_id: str):
    for conjugation in design.nanoparticle_conjugations:
        if conjugation.nanoparticle_id == nanoparticle_id:
            for record in conjugation.surface_strands:
                if record.strand_id == strand_id:
                    return conjugation, record
    return None, None


def sync_applied_bindings(design: Design, affected: set[tuple[str, str]]) -> Design:
    """Refresh only the handle ownership changed by this application transition.

    A surface carrier follows its exact live strand/domain/auxiliary endpoint.
    Ambiguous legacy ownership remains visible; this helper never guesses a
    replacement or normalizes an unrelated direct binding.
    """
    applied = {
        (version.nanoparticle_id, version.strand_id): version.overhang_id
        for version in design.nanoparticle_connection_versions if version.applied
    }
    selected_strands = {strand_id for _, strand_id in affected}
    strands, endpoints = {}, {}
    for strand in design.strands:
        if strand.id in selected_strands:
            strands.setdefault(strand.id, []).append(strand)
    for endpoint in design.overhangs:
        if endpoint.strand_id in selected_strands:
            endpoints.setdefault(endpoint.id, []).append(endpoint)
    conjugations = []
    for conjugation in design.nanoparticle_conjugations:
        changed, records = False, []
        for record in conjugation.surface_strands:
            key = conjugation.nanoparticle_id, record.strand_id
            if key not in affected:
                records.append(record)
                continue
            values = {"bound_overhang_id": applied.get(key)}
            owners = strands.get(record.strand_id, ())
            specs = endpoints.get(record.overhang_id, ())
            if len(owners) == 1 and len(specs) == 1 and specs[0].auxiliary_endpoint:
                domains = [domain for domain in owners[0].domains if domain.overhang_id == record.overhang_id]
                if len(domains) == 1 and domains[0].helix_id == specs[0].helix_id:
                    values["helix_id"] = domains[0].helix_id
            records.append(record.model_copy(update=values))
            changed = True
        conjugations.append(conjugation.model_copy(update={"surface_strands": records}) if changed else conjugation)
    return design.model_copy(update={"nanoparticle_conjugations": conjugations})


def ensure_duplex_endpoint(design: Design, nanoparticle_id: str, strand_id: str) -> tuple[Design, str]:
    """Backfill the hidden overhang endpoint for old and newly-created handles."""
    _, record = surface_owner(design, nanoparticle_id, strand_id)
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


def validate_connection_polarity(
    design: Design, owner, target_overhang_id: str, direct_variant: str,
) -> None:
    """Reject endpoint combinations that would require parallel DNA pairing."""
    error = polarity_error(design, owner, target_overhang_id, direct_variant)
    if error:
        raise ConnectionApplicationError(422, detail=error[0])


def validate_direct_duplex(design: Design, duplex: Duplex) -> None:
    """Apply the same Watson-Crick and direction gates as canonical duplex CRUD."""
    from backend.core.duplex import duplex_wc_ok
    from backend.core.models import _overhang_backing_domain

    ok, reason = duplex_wc_ok(design, duplex)
    if not ok:
        raise ConnectionApplicationError(
            422, detail=f"nanoparticle duplex register is not complementary: {reason}.",
        )
    _left_strand, left_domain = _overhang_backing_domain(
        design, duplex.left.overhang_id,
    )
    _right_strand, right_domain = _overhang_backing_domain(
        design, duplex.right.overhang_id,
    )
    if left_domain is None or right_domain is None:
        raise ConnectionApplicationError(422, detail="Nanoparticle connection endpoints must have DNA domains.")
    # Before relocation two independently placed helices can use the same
    # Direction enum. The pairing register itself is always walked
    # antiparallel; relocation must turn the driven domain onto the opposite
    # direction of the target helix, checked again in set_version_applied.


def set_version_applied(design: Design, version_id: str, applied: bool, *,
                        duplex_id=None, duplex_created_at=None, identity_seed=None) -> Design:
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
    affected_handles = {(target.nanoparticle_id, target.strand_id)} | {
        (version.nanoparticle_id, version.strand_id)
        for version in design.nanoparticle_connection_versions
        if applied and version.id in conflict_ids and (version.applied or version.duplex_id is not None)
    }
    versions = []
    for version in design.nanoparticle_connection_versions:
        if version.id == version_id:
            versions.append(version.model_copy(update={
                "applied": applied, "relaxed": False, "residual_nm": None, "duplex_id": None,
                "constraint_root_nm": None, "constraint_radius_nm": None,
            }))
        elif applied and version.id in conflict_ids:
            versions.append(version.model_copy(update={
                "applied": False, "relaxed": False, "residual_nm": None, "duplex_id": None,
                "constraint_root_nm": None, "constraint_radius_nm": None,
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
        out, np_overhang_id = ensure_duplex_endpoint(out, target.nanoparticle_id, target.strand_id)
        # Capture the exact unbound backbone joint before relocation.  A radial
        # site estimate omits the DNA helix radius/phase and causes the live
        # gizmo preview to disagree with the committed constrained move.
        from backend.core.design_geometry import fitting_geometry
        particle = next(p for p in out.nanoparticles if p.id == target.nanoparticle_id)
        owner, record = surface_owner(out, target.nanoparticle_id, target.strand_id)
        validate_connection_polarity(
            out, owner, target.overhang_id, target.direct_variant,
        )
        terminal_flag = "is_three_prime" if owner.attach_end == "3p" else "is_five_prime"
        terminal = next((n for n in fitting_geometry(out, strand_ids={target.strand_id})
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
        np_attach, target_attach = connection_attaches(owner, target.direct_variant)
        try:
            left, right = connect_register(
                out, np_overhang_id, np_attach, target.overhang_id, target_attach,
            )
        except ValueError as exc:
            raise ConnectionApplicationError(422, detail=str(exc)) from exc
        identity = ({"id": duplex_id, "created_at": duplex_created_at}
                    if duplex_id is not None else {})
        duplex = Duplex(
            **identity,
            name=target.name, left=left, right=right, driver="right", bound=True,
            connection_type=f"nanoparticle-{target.direct_variant}",
        )
        validate_direct_duplex(out, duplex)
        versions = [v.model_copy(update={"duplex_id": duplex.id}) if v.id == version_id else v
                    for v in out.nanoparticle_connection_versions]
        out = out.model_copy(update={"duplexes": [*out.duplexes, duplex],
                                     "nanoparticle_connection_versions": versions})
        out = (relocate_duplex(out, duplex, identity_seed=identity_seed)
               if identity_seed is not None else relocate_duplex(out, duplex))
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
            raise ConnectionApplicationError(
                422,
                detail="Nanoparticle connection could not be materialized as antiparallel DNA.",
            )
        applied_geometry = fitting_geometry(out, strand_ids={target.strand_id},
                                            overhang_ids={target.overhang_id})
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
    return sync_applied_bindings(out, affected_handles)
