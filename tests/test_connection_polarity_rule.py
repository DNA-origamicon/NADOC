"""Server-side connection-type polarity rule (twin of frontend ctIsForbidden).

dsDNA linkers between incompatible polarities would put both bridge strands in
the same direction on the __lnk__ helix: two bases per (helix, bp, direction)
slot. The rule must refuse them from every entry point, not only the UI.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.core.overhang_ops import (
    _check_linker_compatibility, connection_type_forbidden, connection_type_polarity_error,
)

ATTACH = {"root-to-root": ("root", "root"), "end-to-end": ("free_end", "free_end"),
          "end-to-root": ("free_end", "root"), "root-to-end": ("root", "free_end")}
ENDS = ("5p", "3p")


@pytest.mark.parametrize("prefix", sorted(ATTACH))
@pytest.mark.parametrize("linker", ["ds", "ss"])
def test_linker_variants_match_the_comp_first_bridge_rule(prefix, linker):
    attach_a, attach_b = ATTACH[prefix]
    for end_a in ENDS:
        for end_b in ENDS:
            expected = _check_linker_compatibility(end_a, end_b, attach_a, attach_b, linker) is not None
            assert connection_type_forbidden(f"{prefix}-{linker}dna-linker", end_a, end_b) is expected


def test_direct_and_indirect_variants_match_the_frontend_table():
    # ui/ct_icons.js ctIsForbidden: end-to-root needs equal, root-to-root opposite,
    # same-attach indirect opposite polarity.
    assert connection_type_forbidden("end-to-root", "5p", "3p")
    assert not connection_type_forbidden("end-to-root", "3p", "3p")
    assert connection_type_forbidden("root-to-root", "5p", "5p")
    assert not connection_type_forbidden("root-to-root", "5p", "3p")
    assert connection_type_forbidden("end-to-end-indirect", "3p", "3p")
    assert not connection_type_forbidden("unknown-variant", "5p", "3p")
    assert not connection_type_forbidden("root-to-root-dsdna-linker", None, "5p")  # untagged ids


def test_error_names_the_double_occupancy_for_ds_linkers():
    error = connection_type_polarity_error("root-to-root-dsdna-linker", "ovhg_h_0_5p", "ovhg_h_1_3p")
    assert "same direction" in error and "two bases per position" in error
    assert connection_type_polarity_error("root-to-root-dsdna-linker", "ovhg_h_0_5p", "ovhg_h_1_5p") is None


@pytest.fixture
def http():
    from backend.api.main import app

    identity = f"polarity-{uuid4()}"
    headers = {"X-NADOC-Doc": identity}
    client = TestClient(app)  # no lifespan
    assert client.post("/api/design", headers=headers, json={"name": "p", "lattice_type": "HONEYCOMB"}).status_code == 201
    try:
        yield client, headers
    finally:
        token = doc_context.set_current_doc(identity)
        try:
            state.drop_doc(identity)
        finally:
            doc_context.reset_current_doc(token)
        client.close()


@pytest.mark.parametrize("path", ["/api/design/connection-versions", "/api/design/connection-versions/connect"])
def test_connection_version_routes_refuse_forbidden_pairs_before_anything_else(http, path):
    client, headers = http
    body = {"overhang_a_id": "ovhg_h_0_5p", "overhang_b_id": "ovhg_h_1_3p",
            "connection_type": "root-to-root-dsdna-linker"}
    forbidden = client.post(path, headers=headers, json=body)
    assert forbidden.status_code == 400 and "two bases per position" in forbidden.json()["detail"]
    allowed = client.post(path, headers=headers, json={**body, "overhang_b_id": "ovhg_h_1_5p"})
    assert allowed.status_code == 404  # passes the rule; the overhangs simply do not exist


def test_apply_refuses_a_stored_forbidden_version(http):
    client, headers = http
    from backend.core.models import ConnectionVersion

    token = doc_context.set_current_doc(headers["X-NADOC-Doc"])
    try:
        design = state.get_or_404()
        version = ConnectionVersion(name="v", overhang_a_id="ovhg_h_0_5p", overhang_b_id="ovhg_h_1_3p",
                                    connection_type="end-to-end-dsdna-linker")
        state.load_design(design.copy_with(connection_versions=[version]))
    finally:
        doc_context.reset_current_doc(token)
    response = client.post(f"/api/design/connection-versions/{version.id}/apply", headers=headers)
    assert response.status_code == 400 and "same direction" in response.json()["detail"]
