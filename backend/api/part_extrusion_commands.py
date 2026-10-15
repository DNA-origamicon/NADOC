"""Native extrusion adapters retain the builder's reconciliation hints."""


def build(kind, design, params):
    from backend.api import crud
    from backend.core.part_history_proof import ProofBudgetExceeded

    specs = {
        "extrude-segment": (crud.BundleSegmentRequest, crud._build_extrude_segment),
        "extrude-continuation": (
            crud.BundleContinuationRequest,
            crud._build_extrude_continuation,
        ),
        "extrude-deformed-continuation": (
            crud.BundleDeformedContinuationRequest,
            crud._build_extrude_deformed_continuation,
        ),
        "circle-segment": (crud.CircleSegmentRequest, crud._build_circle_segment),
    }
    cells = params.get("cells", [])
    work = (
        sum(abs(n) for n in params.get("cell_lengths", []))
        if kind == "circle-segment"
        else len(cells) * abs(params.get("length_bp", 0))
    )
    if len(cells) > 512 or work > 50_000:
        raise ProofBudgetExceeded("Extrusion exceeds proof work budget")
    if kind == "extrude-frame":
        from backend.api.routes_frame_extrusion import (
            FrameExtrusionRequest,
            _candidate_result,
        )

        values = {k: v for k, v in params.items() if k != "_proof_version"}
        values.update(expected_design_id=design.id, expected_revision=0)
        return _candidate_result(design, FrameExtrusionRequest.model_validate(values))
    if set(params.get("_source_helix_ids", [])) - {h.id for h in design.helices}:
        raise ValueError("Continuation source helix is missing")
    schema, builder = specs[kind]
    return builder(design, schema.model_validate(params))


def continuation_sources(design, body):
    from backend.core.continuation_source import continuation_source_helices

    cells = {tuple(c) for c in body.cells}
    return sorted(
        h.id
        for h in continuation_source_helices(design, body.source_frame_id, body.plane)
        if h.grid_pos in cells
    )
