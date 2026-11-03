"""Manual formed-product intent API (chemistry gated separately)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.crud import _design_response
from backend.core.models import TTCPDStereochemistry
from backend.core.photoproducts import (
    create_photoproduct_from_preflight,
    preflight_photoproduct,
)

router = APIRouter()


class PhotoproductPreflightBody(BaseModel):
    base_keys: list[str] = Field(min_length=0, max_length=100)
    stereochemistry: str = "cis-syn"
    expected_revision: int | None = None


class PhotoproductCreateBody(BaseModel):
    base_keys: list[str] = Field(min_length=2, max_length=2)
    stereochemistry: TTCPDStereochemistry = "cis-syn"
    expected_revision: int | None = None
    placement: Literal["legacy", "bases-only", "contextual"] = "legacy"


class PhotoproductVisualReviewBody(BaseModel):
    stage: str
    product_id: str
    conformer_id: str | None = None
    decision: str
    partition: str | None = None
    reviewer: str
    notes: str


@router.get("/design/photoproducts/capability")
def get_photoproduct_capability() -> dict:
    from backend.core.cpd_forcefield import cpd_capability

    return cpd_capability()


@router.get("/design/photoproducts/catalog")
def get_photoproduct_catalog() -> dict:
    from backend.core.photoproduct_registry import photoproduct_capabilities

    return photoproduct_capabilities()


@router.get("/design/photoproducts/toolchain")
def get_photoproduct_toolchain() -> dict:
    from backend.core.photoproduct_toolchain import photoproduct_toolchain_status

    return photoproduct_toolchain_status()


@router.get("/design/photoproducts/scientific-review")
def get_photoproduct_scientific_review() -> dict:
    from backend.core.photoproduct_review import (
        PhotoproductReviewError,
        build_photoproduct_review_catalog,
    )

    try:
        return build_photoproduct_review_catalog()
    except PhotoproductReviewError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.put("/design/photoproducts/scientific-review/decision")
def put_photoproduct_scientific_review_decision(
    body: PhotoproductVisualReviewBody,
) -> dict:
    from backend.core.photoproduct_review import (
        PhotoproductReviewError,
        record_photoproduct_visual_decision,
    )

    try:
        return record_photoproduct_visual_decision(**body.model_dump())
    except PhotoproductReviewError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/design/photoproducts/catalog/{product_id}/model-trajectory")
def get_photoproduct_model_trajectory(product_id: str) -> dict:
    from backend.core.photoproduct_registry import (
        PhotoproductRegistryError,
        photoproduct_help_trajectory,
    )

    try:
        return photoproduct_help_trajectory(product_id)
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except PhotoproductRegistryError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/design/photoproducts/preflight")
def post_photoproduct_preflight(body: PhotoproductPreflightBody) -> dict:
    if (
        body.expected_revision is not None
        and body.expected_revision != design_state.revision()
    ):
        raise HTTPException(
            409, detail="Design changed while photoproduct preflight was requested."
        )
    return preflight_photoproduct(
        design_state.get_or_404(), body.base_keys, stereochemistry=body.stereochemistry
    )


@router.post("/design/photoproducts")
def post_photoproduct(body: PhotoproductCreateBody) -> dict:
    from uuid import uuid4
    identity = str(uuid4())
    lesion_holder = {}
    report_holder = {}

    def apply(current):
        report = preflight_photoproduct(
            current, body.base_keys, stereochemistry=body.stereochemistry
        )
        report_holder["report"] = report
        if not report["eligible"]:
            raise HTTPException(status_code=422, detail=report)
        updated, lesion = create_photoproduct_from_preflight(current, report, identity=identity)
        lesion_holder["lesion"] = lesion
        return updated

    updated, validation, entry = design_state.mutate_with_feature_log(
        "photoproduct-create",
        f"Form {body.stereochemistry} TT-CPD",
        {
            "base_keys": sorted(body.base_keys),
            "product": "TT-CPD",
            "history_seed": identity,
            "method": "preflight",
            "stereochemistry": body.stereochemistry,
        },
        apply,
        expected_revision=body.expected_revision,
    )
    payload = _design_response(updated, validation, preserve_feature_log_id=entry.id)
    payload["photoproduct"] = lesion_holder["lesion"].model_dump()
    payload["preflight"] = report_holder["report"]
    payload["geometry_unchanged"] = True
    return payload


@router.delete("/design/photoproducts/{photoproduct_id}")
def delete_photoproduct(photoproduct_id: str) -> dict:
    design = design_state.get_or_404()
    lesion = next(
        (item for item in design.photoproduct_junctions if item.id == photoproduct_id),
        None,
    )
    if lesion is None:
        raise HTTPException(404, detail=f"Photoproduct {photoproduct_id!r} not found.")
    updated, validation, entry = design_state.mutate_with_feature_log(
        "photoproduct-delete",
        f"Remove {lesion.stereochemistry} TT-CPD",
        {"photoproduct_id": photoproduct_id},
        lambda current: current.copy_with(
            photoproduct_junctions=[
                item
                for item in current.photoproduct_junctions
                if item.id != photoproduct_id
            ]
        ),
    )
    if lesion.orientation_method in {"manual-base-only-mvp-v1", "manual-six-residue-mvp-v1"}:
        from backend.api.crud import _design_response_with_geometry
        payload = _design_response_with_geometry(updated, validation, preserve_feature_log_id=entry.id)
    else:
        payload = _design_response(updated, validation, preserve_feature_log_id=entry.id)
        payload["geometry_unchanged"] = True
    payload["removed_photoproduct_id"] = photoproduct_id
    return payload


@router.get("/design/photoproducts/template/{stereochemistry}")
def get_design_template(stereochemistry: str) -> dict:
    from backend.core.cpd_design import template_preview
    try:
        return template_preview(stereochemistry)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/design/photoproducts/conversion-options")
def get_conversion_options():
    from backend.core.cpd_conversion import conversion_catalog
    return conversion_catalog()


@router.post("/design/photoproducts/conversion-preview")
def preview_conversion(body: PhotoproductCreateBody):
    from backend.core.cpd_conversion import prepare_conversion
    revision = design_state.revision()
    if body.expected_revision is not None and body.expected_revision != revision:
        raise HTTPException(409, detail="Design changed; reopen the CPD preview.")
    try:
        _, preview = prepare_conversion(design_state.get_or_404(), body.base_keys, body.stereochemistry)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if design_state.revision() != revision:
        raise HTTPException(409, detail="Design changed while building the CPD preview.")
    return {**preview, "revision": revision}


@router.post("/design/photoproducts/convert")
def convert_design_photoproduct(body: PhotoproductCreateBody) -> dict:
    from uuid import uuid4
    identity = str(uuid4())
    from backend.core.cpd_design import convert_extra_pair
    from backend.core.cpd_conversion import convert_thymine_pair
    converter = convert_thymine_pair if body.placement != "legacy" else convert_extra_pair
    def apply(current):
        try:
            return converter(current, body.base_keys, body.stereochemistry, identity_seed=identity)[0]
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc
    updated, validation, entry = design_state.mutate_with_feature_log(
        "photoproduct-create", f"Convert thymines to {body.stereochemistry} CPD",
        {"base_keys": body.base_keys, "stereochemistry": body.stereochemistry, "history_seed": identity,
         "method": body.placement if body.placement != "legacy" else "convert"}, apply,
        expected_revision=body.expected_revision,
    )
    if body.placement != "legacy":
        from backend.api.crud import _design_response_with_geometry
        return _design_response_with_geometry(updated, validation, preserve_feature_log_id=entry.id)
    payload = _design_response(updated, validation, preserve_feature_log_id=entry.id)
    payload["geometry_unchanged"] = True  # Extra-base poses are rendered client-side.
    return payload


class PhotoproductRelaxBody(BaseModel):
    expected_revision: int | None = None


@router.post("/design/photoproducts/{photoproduct_id}/relax")
def relax_design_photoproduct(photoproduct_id: str, body: PhotoproductRelaxBody) -> dict:
    from backend.core.cpd_design import relax_existing_cpd
    result = {}
    def apply(current):
        try:
            updated, report = relax_existing_cpd(current, photoproduct_id)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        result.update(report)
        return updated
    updated, validation, entry = design_state.mutate_with_feature_log(
        "photoproduct-relax", "Relax CPD bonds and nearby clashes",
        {"photoproduct_id": photoproduct_id}, apply,
        expected_revision=body.expected_revision,
    )
    payload = _design_response(updated, validation, preserve_feature_log_id=entry.id)
    payload["geometry_unchanged"] = True
    payload["bond_relaxation"] = result
    return payload
