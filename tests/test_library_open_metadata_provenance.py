"""Opening a Save As copy under its filename must record the metadata rename."""
from backend.api import crud, assembly, routes_assembly_workspace
from backend.core.models import Design
from scripts.agent_structure_guard import audit
from tests.test_agent_structure_guard import part


def test_library_name_stamp_is_replayable_and_idempotent(monkeypatch, tmp_path):
    source = part().design
    marker = tmp_path / 'exists'
    marker.touch()  # Existence fixture only; no unaudited structure file.
    monkeypatch.setattr(assembly, '_safe_workspace_path', lambda _: marker)
    monkeypatch.setattr(routes_assembly_workspace, '_reconcile_nadoc_file', lambda *_: (source, 'confirmed'))
    monkeypatch.setattr(crud, '_install_loaded_design', lambda design: {'design': design})
    try:
        renamed = crud.open_library_part(crud.OpenLibraryPartRequest(path='copy.nadoc', name='Copy'))['design']
        assert source.metadata.name == 'Agent process test'
        assert renamed.metadata.name == 'Copy'
        assert audit(Design.model_validate_json(renamed.model_dump_json()))['status'] == 'verified'
        assert renamed.document_history[-1].kind == 'document-metadata'
        source = renamed
        reopened = crud.open_library_part(crud.OpenLibraryPartRequest(path='copy.nadoc', name='Copy'))['design']
        assert reopened.document_history == renamed.document_history
    finally:
        marker.unlink()
