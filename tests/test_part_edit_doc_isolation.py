"""
Part-editor document isolation (multi-document routing).

Regression for the bug where opening multiple parts from an assembly let one
part's design overwrite another's: every part-editor tab shared the assembly's
backend document, so each ``POST /design/import`` clobbered the single design
slot.  The fix gives each part editor its OWN document while the source-fetch
and save-back explicitly address the assembly's document via ``X-NADOC-Doc``.

These tests exercise the HTTP layer with explicit doc headers (the same routing
the frontend now performs) and assert per-document isolation via the
``peek_design`` / ``peek_assembly`` helpers.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests._assembly_compat import v1_instances

from backend.api import assembly_state
from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import make_bundle_design

client = TestClient(app)

DOC_A = "iso-assembly"  # the assembly tab's document
DOC_PA = "iso-part-a"  # Part A editor's own (isolated) document
DOC_PB = "iso-part-b"  # Part B editor's own (isolated) document


def _h(doc):
    return {"X-NADOC-Doc": doc}


@pytest.fixture(autouse=True)
def _reset():
    for d in (DOC_A, DOC_PA, DOC_PB):
        assembly_state.drop_doc(d)
        design_state.drop_doc(d)
    yield
    for d in (DOC_A, DOC_PA, DOC_PB):
        assembly_state.drop_doc(d)
        design_state.drop_doc(d)


def _part(name, cells):
    d = make_bundle_design(cells, length_bp=84)
    d.metadata.name = name
    return d


def _add_instance(name, design):
    return client.post(
        "/api/assembly/instances",
        json={"name": name, "source": {"type": "inline", "design": design.to_dict()}},
        headers=_h(DOC_A),
    )


def test_part_editor_docs_do_not_clobber_each_other():
    # Distinct parts: A has 2 helices, B has 4 — trivially distinguishable.
    design_a = _part("PartA", [(0, 0), (0, 1)])
    design_b = _part("PartB", [(0, 0), (0, 1), (1, 0), (1, 1)])

    client.post("/api/assembly", headers=_h(DOC_A))
    assert _add_instance("A", design_a).status_code == 201
    assert _add_instance("B", design_b).status_code == 201

    insts = {
        i["name"]: i["id"]
        for i in v1_instances(client.get("/api/assembly", headers=_h(DOC_A)).json())
    }
    inst_a, inst_b = insts["A"], insts["B"]

    # Part A editor: fetch source from the assembly doc, import into its OWN doc.
    src_a = client.get(
        f"/api/assembly/instances/{inst_a}/design", headers=_h(DOC_A)
    ).json()["design"]
    assert (
        client.post(
            "/api/design/import",
            json={"content": json.dumps(src_a)},
            headers=_h(DOC_PA),
        ).status_code
        == 200
    )
    # Part B editor: same, into a different doc.
    src_b = client.get(
        f"/api/assembly/instances/{inst_b}/design", headers=_h(DOC_A)
    ).json()["design"]
    assert (
        client.post(
            "/api/design/import",
            json={"content": json.dumps(src_b)},
            headers=_h(DOC_PB),
        ).status_code
        == 200
    )

    # The crux: opening B did NOT overwrite A. Each editor doc holds its own part.
    pa = design_state.peek_design(DOC_PA)
    pb = design_state.peek_design(DOC_PB)
    assert pa is not None and pb is not None
    assert pa.metadata.name == "PartA" and len(pa.helices) == 2
    assert pb.metadata.name == "PartB" and len(pb.helices) == 4
    # The assembly doc's design slot is independent of either editor.
    assert design_state.peek_design(DOC_A) is None


def test_save_back_reaches_assembly_doc_without_touching_editor_docs(
    tmp_path, monkeypatch
):
    # PATCH .../design of an inline instance auto-saves a .nadoc into the
    # workspace and switches the source to file-backed — point that at a temp
    # dir so the test doesn't write into the real workspace.
    import backend.api.assembly as asm_module

    monkeypatch.setattr(asm_module, "_WORKSPACE_DIR", tmp_path)

    design_a = _part("PartA", [(0, 0), (0, 1)])
    design_b = _part("PartB", [(0, 0), (0, 1), (1, 0), (1, 1)])

    client.post("/api/assembly", headers=_h(DOC_A))
    _add_instance("A", design_a)
    _add_instance("B", design_b)
    insts = {
        i["name"]: i["id"]
        for i in v1_instances(client.get("/api/assembly", headers=_h(DOC_A)).json())
    }
    inst_a, inst_b = insts["A"], insts["B"]

    # Both editors load their source into their own docs.
    for inst, doc in ((inst_a, DOC_PA), (inst_b, DOC_PB)):
        src = client.get(
            f"/api/assembly/instances/{inst}/design", headers=_h(DOC_A)
        ).json()["design"]
        client.post(
            "/api/design/import", json={"content": json.dumps(src)}, headers=_h(doc)
        )

    # Part A editor saves an edited design back — targeting the ASSEMBLY doc.
    edited = _part("PartA-edited", [(0, 0), (0, 1)])
    patch = client.patch(
        f"/api/assembly/instances/{inst_a}/design",
        json={"content": edited.to_json()},
        headers=_h(DOC_A),
    )
    assert patch.status_code == 200, patch.text

    # The assembly (doc A) reflects A's edit; instance B is untouched.
    # Read back through the API so it resolves the now-file-backed source.
    got_a = client.get(
        f"/api/assembly/instances/{inst_a}/design", headers=_h(DOC_A)
    ).json()["design"]
    got_b = client.get(
        f"/api/assembly/instances/{inst_b}/design", headers=_h(DOC_A)
    ).json()["design"]
    assert got_a["metadata"]["name"] == "PartA-edited"
    assert got_b["metadata"]["name"] == "PartB"

    # The save-back to doc A left both editor docs alone.
    assert design_state.peek_design(DOC_PA).metadata.name == "PartA"
    assert design_state.peek_design(DOC_PB).metadata.name == "PartB"


def test_undo_redo_are_document_scoped():
    """Undo/redo must act on the document named by ``X-NADOC-Doc``, not the
    default slot.  Regression for the cadnano editor's undo being silently
    broken in multi-document mode: its undo/redo fetches omitted the doc header,
    so they popped the default doc's stack while the edit lived on the editor's
    own doc — undo appeared to do nothing.
    """
    # Two editor docs, each with its own design + an edit to undo.
    for doc, cells in ((DOC_PA, [(0, 0), (0, 1)]), (DOC_PB, [(0, 0), (0, 1), (1, 0)])):
        d = _part(f"part-{doc}", cells)
        assert (
            client.post(
                "/api/design/import", json={"content": d.to_json()}, headers=_h(doc)
            ).status_code
            == 200
        )

    def n_strands(doc):
        return len(
            client.get("/api/design", headers=_h(doc)).json()["design"]["strands"]
        )

    # Edit ONLY doc PA: nick its first helix's scaffold so strand count rises.
    pa = client.get("/api/design", headers=_h(DOC_PA)).json()["design"]
    base_pa, base_pb = n_strands(DOC_PA), n_strands(DOC_PB)
    hid = pa["helices"][0]["id"]
    assert (
        client.post(
            "/api/design/nick",
            json={"helix_id": hid, "bp_index": 20, "direction": "FORWARD"},
            headers=_h(DOC_PA),
        ).status_code
        == 201
    )
    assert n_strands(DOC_PA) == base_pa + 1

    # Undo WITHOUT a doc header → hits the default doc, must NOT touch PA.
    client.post("/api/design/undo")
    assert n_strands(DOC_PA) == base_pa + 1, "undo leaked across documents"

    # Undo WITH PA's header → reverts PA only; PB is never disturbed.
    assert client.post("/api/design/undo", headers=_h(DOC_PA)).status_code == 200
    assert n_strands(DOC_PA) == base_pa
    assert n_strands(DOC_PB) == base_pb

    # Redo WITH PA's header → re-applies the nick on PA only.
    assert client.post("/api/design/redo", headers=_h(DOC_PA)).status_code == 200
    assert n_strands(DOC_PA) == base_pa + 1
    assert n_strands(DOC_PB) == base_pb
