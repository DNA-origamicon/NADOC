"""Re-run native photoproduct authoring with explicit method and identities.

Scientific preflight/template gates remain authoritative and fail closed when
required evidence is unavailable. A history verdict is not scientific approval.
"""

KINDS = frozenset({"photoproduct-create", "photoproduct-delete"})


def build(kind, design, params):
    if kind == "photoproduct-delete":
        if params["photoproduct_id"] not in {
            p.id for p in design.photoproduct_junctions
        }:
            raise ValueError("Missing photoproduct")
        return design.copy_with(
            photoproduct_junctions=[
                p
                for p in design.photoproduct_junctions
                if p.id != params["photoproduct_id"]
            ]
        )
    if params.get("method") == "convert":
        from backend.core.cpd_design import convert_extra_pair

        return convert_extra_pair(
            design,
            params["base_keys"],
            params["stereochemistry"],
            identity_seed=params["history_seed"],
        )[0]
    if params.get("method") != "preflight":
        raise ValueError("Photoproduct creation method is required")
    from backend.core.photoproducts import (
        preflight_photoproduct,
        create_photoproduct_from_preflight,
    )

    report = preflight_photoproduct(
        design, params["base_keys"], stereochemistry=params["stereochemistry"]
    )
    return create_photoproduct_from_preflight(
        design, report, identity=params["history_seed"]
    )[0]
