"""Re-run ordinary photoproduct preflight/deletion with explicit identities.

Scientific preflight/template gates remain authoritative and fail closed when
required evidence is unavailable. A history verdict is not scientific approval.
Conversion and relaxation use the separate pinned, bounded CPD adapter.
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
    if params.get("method") != "preflight":
        raise ValueError("Ordinary photoproduct authoring requires method='preflight'")
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
