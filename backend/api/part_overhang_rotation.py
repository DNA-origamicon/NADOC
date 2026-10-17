"""Strict input cardinality for native overhang and subdomain rotations."""

from backend.core.models import OverhangRotationLogEntry


def build(design, params):
    from backend.api.crud import _set_subdomain_angles, _validate_sd_angles

    entry = OverhangRotationLogEntry.model_validate(params)
    if len(entry.rotations) != len(entry.overhang_ids):
        raise ValueError("Rotation cardinality does not match overhang targets")
    for i, identity in enumerate(entry.overhang_ids):
        spec = next((o for o in design.overhangs if o.id == identity), None)
        if spec is None:
            raise ValueError("Missing overhang rotation target")
        sd = entry.sub_domain_ids[i] if entry.sub_domain_ids else None
        if sd is not None:
            if sd not in {item.id for item in spec.sub_domains}:
                raise ValueError("Missing subdomain rotation target")
            theta, phi = entry.sub_domain_thetas_deg[i], entry.sub_domain_phis_deg[i]
            _validate_sd_angles(theta, phi)
            design = _set_subdomain_angles(design, identity, sd, theta, phi)
        else:
            from math import isfinite

            rotation = entry.rotations[i]
            if (
                len(rotation) != 4
                or not all(isfinite(x) for x in rotation)
                or abs(sum(x * x for x in rotation) - 1) > 1e-6
            ):
                raise ValueError("Rotation requires a normalized quaternion")
            design = design.copy_with(
                overhangs=[
                    o.model_copy(update={"rotation": rotation})
                    if o.id == identity
                    else o
                    for o in design.overhangs
                ]
            )
    return design
