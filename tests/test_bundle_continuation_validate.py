from fastapi.testclient import TestClient
import pytest

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


def _single_cell_bundle() -> tuple[dict, str]:
    response = client.post(
        "/api/design/bundle",
        json={"cells": [[0, 0]], "length_bp": 42, "plane": "XY"},
    )
    assert response.status_code == 201
    design = response.json()["design"]
    return design, design["helices"][0]["id"]


def test_continuation_validate_dry_runs_exact_builder_without_mutation():
    before, helix_id = _single_cell_bundle()
    request = {
        "cells": [[0, 0]],
        "length_bp": 7,
        "plane": "XY",
        "offset_nm": 42 * BDNA_RISE_PER_BP,
        "strand_filter": "both",
        "ligate_adjacent": True,
    }

    response = client.post("/api/design/bundle-continuation/validate", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["new_helix_ids"] == []
    assert payload["extended_helix_ids"] == [helix_id]
    assert len(payload["affected_strand_ids"]) == 2
    assert client.get("/api/design").json()["design"] == before

    committed = client.post("/api/design/bundle-continuation", json=request)
    assert committed.status_code == 201
    assert committed.json()["design"]["helices"][0]["length_bp"] == 49


def test_continuation_validate_blocks_inward_overlap_and_commit_shares_guard():
    before, _ = _single_cell_bundle()
    request = {
        "cells": [[0, 0]],
        "length_bp": -7,
        "plane": "XY",
        "offset_nm": 42 * BDNA_RISE_PER_BP,
    }

    response = client.post("/api/design/bundle-continuation/validate", json=request)

    assert response.status_code == 200
    assert response.json()["status"] == "block"
    assert "overlaps existing DNA" in response.json()["message"]
    assert client.get("/api/design").json()["design"] == before
    committed = client.post("/api/design/bundle-continuation", json=request)
    assert committed.status_code == 400
    assert client.get("/api/design").json()["design"] == before


def test_continuation_validate_allows_near_end_outward_contact_and_blocks_bad_shape():
    before, helix_id = _single_cell_bundle()
    outward = client.post(
        "/api/design/bundle-continuation/validate",
        json={
            "cells": [[0, 0]], "length_bp": -7,
            "plane": "XY", "offset_nm": 0,
        },
    )
    assert outward.status_code == 200
    assert outward.json()["status"] == "ok"
    assert outward.json()["extended_helix_ids"] == [helix_id]

    duplicate = client.post(
        "/api/design/bundle-continuation/validate",
        json={
            "cells": [[0, 0], [0, 0]], "length_bp": 7,
            "plane": "XY", "offset_nm": 42 * BDNA_RISE_PER_BP,
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "block"
    assert "duplicates" in duplicate.json()["message"]
    assert client.get("/api/design").json()["design"] == before
