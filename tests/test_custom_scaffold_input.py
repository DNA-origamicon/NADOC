"""New scaffold submissions accept only ATGC; rejected requests cannot edit a design."""

import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.core.models import (
    Design,
    Helix,
    Vec3,
    Strand,
    StrandType,
    Domain,
    Direction,
)


@pytest.fixture
def client():
    doc = "custom-scaffold-input-test"
    token = set_current_doc(doc)
    state.load_design(
        Design(
            helices=[
                Helix(
                    id="h0",
                    length_bp=8,
                    axis_start=Vec3(x=0, y=0, z=0),
                    axis_end=Vec3(x=0, y=0, z=2.38),
                )
            ],
            strands=[
                Strand(
                    id="s0",
                    strand_type=StrandType.SCAFFOLD,
                    domains=[
                        Domain(
                            helix_id="h0",
                            start_bp=0,
                            end_bp=7,
                            direction=Direction.FORWARD,
                        )
                    ],
                )
            ],
        )
    )
    try:
        yield TestClient(app, headers={"X-NADOC-Doc": doc})
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize(
    "sequence", ["ATGCN", "ATGU", "ATG1", "A-CG", ">seq\nATGC", "", " \n\t", None]
)
def test_invalid_custom_input_is_rejected_without_mutation(client, sequence):
    before = state.get_or_404().model_dump()
    response = client.post(
        "/api/design/assign-scaffold-sequence",
        json={"scaffold_name": "custom", "custom_sequence": sequence},
    )
    assert response.status_code == 422
    assert state.get_or_404().model_dump() == before


def test_formatted_custom_input_applies_exact_bases(client):
    response = client.post(
        "/api/design/assign-scaffold-sequence",
        json={
            "scaffold_name": "custom",
            "custom_sequence": " a t\nG\tc A T g c ",
            "strand_id": "s0",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["scaffold_len"] == 8
    assert state.get_or_404().strands[0].sequence == "ATGCATGC"
    assert state.get_or_404().feature_log[-1].params["custom_sequence"] == "ATGCATGC"


def test_preset_remains_available(client):
    response = client.post(
        "/api/design/assign-scaffold-sequence", json={"scaffold_name": "M13mp18"}
    )
    assert response.status_code == 200, response.text
    assert len(state.get_or_404().strands[0].sequence) == 8
