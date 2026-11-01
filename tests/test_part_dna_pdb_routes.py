"""Ordinary DNA import keeps its navigation semantics and original atom display."""

from dataclasses import asdict
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import crud, doc_context, routes_design_interchange as routes, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from tests.test_part_dna_pdb_commands import pdb_bytes as pdb_bytes


@pytest.fixture
def client():
    doc = f"__e2e__dna-pdb-{uuid4()}"
    token = doc_context.set_current_doc(doc)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.include_router(crud.router, prefix="/api")
    app.add_middleware(doc_context.DocContextMiddleware)
    state.load_design(create_empty_part("Before import", "HONEYCOMB"))
    try:
        with TestClient(app, headers={"X-NADOC-Doc": doc}) as api:
            yield api
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)


def signature():
    return (state.get_or_404().model_dump_json(), state.revision(), state.undo_depth(), state.get_pdb_atomistic())


@pytest.mark.parametrize("endpoint", ["pdb", "pdb-auto"])
def test_ordinary_import_records_original_bytes_and_keeps_navigation_and_atom_display(client, pdb_bytes, endpoint):
    previous, revision = state.get_or_404(), state.revision()
    response = client.post(f"/api/design/import/{endpoint}", json={"content": pdb_bytes.decode()})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["import_history"] == {"status": "reproduced_import", "native_editable": False,
                                         "loss_policy": "existing-duplex-projection-v1"}
    current = state.get_or_404()
    assert current is not previous and state.revision() == revision + 1 and state.undo_depth() == 0
    assert len(current.feature_log) == 1 and current.feature_log[0].op_kind == "dna-pdb-import"
    assert payload["design"]["feature_log"][0]["post_state_gz_b64"]
    atoms = state.get_pdb_atomistic()
    assert atoms and len(atoms.atoms) > 100
    assert {atom.helix_id for atom in atoms.atoms} <= {helix.id for helix in current.helices}
    assert {atom.strand_id for atom in atoms.atoms} <= {strand.id for strand in current.strands}
    from backend.api.part_dna_pdb_commands import evaluate
    _, _, rebuilt_atoms = evaluate("dna-pdb-import", create_empty_part("PDB Import", "HONEYCOMB").copy_with(
        input_sources=current.input_sources), current.feature_log[0].params,
        resolver=lambda _source: pdb_bytes)
    assert asdict(rebuilt_atoms) == asdict(atoms)
    reopened = Design.from_json(current.to_json())
    assert assess_part_history(reopened, execute=execute, dependencies=dependencies)["status"] == "reproduced_import"


@pytest.mark.parametrize("endpoint", ["pdb", "pdb-auto"])
def test_multi_model_compatibility_remains_explicitly_unverified(client, pdb_bytes, endpoint):
    content = "MODEL        1\n" + pdb_bytes.decode() + "ENDMDL\n"
    response = client.post(f"/api/design/import/{endpoint}", json={"content": content})
    assert response.status_code == 200, response.text
    assert response.json()["import_history"]["status"] == "unverified"
    assert "model" in response.json()["import_history"]["reason"]
    assert not state.get_or_404().input_sources


@pytest.mark.parametrize("endpoint", ["pdb", "pdb-auto"])
def test_existing_helix_merge_keeps_legacy_contract(client, pdb_bytes, endpoint):
    from tests.conftest import make_minimal_design
    initial = make_minimal_design()
    state.load_design(initial)
    response = client.post(f"/api/design/import/{endpoint}", json={"content": pdb_bytes.decode(),
        **({"merge": True} if endpoint == "pdb" else {})})
    assert response.status_code == 200, response.text
    assert response.json()["import_history"]["status"] == "unverified"
    assert "Merging" in response.json()["import_history"]["reason"]
    assert state.get_or_404().helices[0].id == initial.helices[0].id
    assert state.undo_depth() == 1


@pytest.mark.parametrize("stage", ["converter", "encoding", "response"])
def test_selected_native_failure_never_retries_converter_or_changes_state(client, pdb_bytes, monkeypatch, stage):
    from backend.core import pdb_to_design
    before, calls = signature(), []
    original = pdb_to_design.import_pdb
    def converter(*args, **kwargs):
        calls.append(True)
        if stage == "converter":
            raise ValueError("chosen conversion failed")
        return original(*args, **kwargs)
    monkeypatch.setattr(pdb_to_design, "import_pdb", converter)
    def fail(*_args, **_kwargs):
        raise RuntimeError(f"{stage} failed")
    if stage == "encoding":
        monkeypatch.setattr(state, "encode_design_snapshot", fail)
    elif stage == "response":
        monkeypatch.setattr(crud, "_design_response", fail)
    if stage == "converter":
        response = client.post("/api/design/import/pdb", json={"content": pdb_bytes.decode()})
        assert response.status_code == 400 and "chosen conversion failed" in response.text
    else:
        with pytest.raises(RuntimeError, match=f"{stage} failed"):
            client.post("/api/design/import/pdb", json={"content": pdb_bytes.decode()})
    assert len(calls) == (0 if stage == "encoding" else 1)
    assert signature() == before


def test_auto_cancellation_after_conversion_preserves_original_session(client, pdb_bytes, monkeypatch):
    before = signature()
    async def cancelled(*_args):
        raise HTTPException(499, detail="Cancelled before publication")
    monkeypatch.setattr(routes, "_reject_disconnected_import", cancelled)
    response = client.post("/api/design/import/pdb-auto", json={"content": pdb_bytes.decode()})
    assert response.status_code == 499
    assert signature() == before
