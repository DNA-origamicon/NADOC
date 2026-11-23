"""Real lattice import boundaries flag suspicious junctions without rewriting them."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import crud, routes_part_cadnano_import, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import execute
from backend.core.models import Design
from backend.core.part_cadnano_source import MAX_SOURCE_BYTES
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from tests.test_part_cadnano_commands import path_into, source as cadnano_source
from tests.test_part_scadnano_commands import source as scadnano_source


@pytest.fixture
def client():
    token = set_current_doc("__e2e__import-bond-review")
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    app.include_router(routes_part_cadnano_import.router, prefix="/api")
    state.load_design(create_empty_part("Import target", "HONEYCOMB"))
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


def source(format_name, *, flagged=True):
    if format_name == "cadnano":
        data = cadnano_source()
        if flagged:
            data["vstrands"][1]["col"] = 3
            path_into(data, "scaf", [(0, bp) for bp in range(21)]
                      + [(1, bp) for bp in range(20, -1, -1)])
        return data
    data = scadnano_source()
    if flagged:
        data["helices"][1]["grid_position"] = [3, 0]
    else:
        data["strands"] = [{**strand, "domains": [domain]}
                           for strand in data["strands"] for domain in strand["domains"]]
    return data


def import_source(client, format_name, entrypoint, *, flagged=True):
    content = json.dumps(source(format_name, flagged=flagged))
    if entrypoint == "pinned":
        return client.post(f"/api/design/features/import/{format_name}",
            content=content, headers={"content-type": "application/json"},
            params={"expected_design_id": state.get_or_404().id,
                    "expected_revision": state.revision()})
    if entrypoint == "fallback":
        content += " " * MAX_SOURCE_BYTES
    return client.post(f"/api/design/import/{format_name}", json={"content": content})


@pytest.mark.parametrize("format_name", ["cadnano", "scadnano"])
@pytest.mark.parametrize("entrypoint", ["pinned", "ordinary", "fallback"])
def test_flagged_import_warns_and_preserves_real_history_without_approval(client, format_name, entrypoint):
    response = import_source(client, format_name, entrypoint)
    assert response.status_code == (201 if entrypoint == "pinned" else 200), response.text
    payload = response.json()
    review = payload["import_bond_review"]
    assert review["review_required"]
    assert review["ratios"]["forced_interhelix"] == 1
    assert review["ratios"]["forced_all"] < 0.2
    assert review["reason_codes"] == ["FORCED_JUNCTION_FRACTION_GT_20_PERCENT"]
    assert review["geometry"]["requested"] is False
    assert any("Bond review required:" in message and "no approval" in message
               for message in payload["import_warnings"])
    design = state.get_or_404()
    assert len(design.forced_ligations) == review["counts"]["matched_forced_bonds"]
    if entrypoint == "fallback":
        assert payload["import_history"]["status"] == "unverified"
        assert design.feature_log == [] and design.recipe_root is None
        return

    # Serialization retains the flag in the actual import operation, while its
    # source-driven command still reproduces every molecular authoring field.
    reopened = Design.model_validate_json(design.model_dump_json())
    row, = reopened.feature_log
    assert row.op_kind == f"{format_name}-import"
    assert "REVIEW REQUIRED: forced bonds" in row.label
    counts = review["counts"]
    assert f"junctions {counts['matched_forced_interhelix_bonds']}/{counts['interhelix_bonds']}" in row.label
    assert "bond_review" not in row.params and "approved" not in row.params
    initial = state.decode_design_snapshot(row.design_snapshot_gz_b64)
    replayed = execute(row.op_kind, initial, row.params)
    assert replayed.model_dump(include=AUTHORING_FIELDS) == reopened.model_dump(include=AUTHORING_FIELDS)


@pytest.mark.parametrize("format_name", ["cadnano", "scadnano"])
def test_unflagged_import_does_not_claim_scientific_approval(client, format_name):
    response = import_source(client, format_name, "ordinary", flagged=False)
    assert response.status_code == 200, response.text
    payload = response.json()
    review = payload["import_bond_review"]
    assert review["review_required"] is False and review["reason_codes"] == []
    assert review["geometry"]["requested"] is False
    assert "approved" not in review
    assert all("Bond review required:" not in message for message in payload.get("import_warnings", []))
    assert "REVIEW REQUIRED" not in state.get_or_404().feature_log[0].label
