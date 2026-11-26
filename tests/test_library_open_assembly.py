"""Transport adapter checks; no synthetic molecular files are authored."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from backend.api import assembly
from backend.api.routes_library_open import OpenAssemblyRequest, open_library_assembly


def test_open_delegates_exact_file_to_existing_import(monkeypatch):
    source = Mock(suffix=".nass")
    source.is_file.return_value = True
    source.read_text.return_value = '{"feature_log": "opaque upstream history"}'
    resolve = Mock(return_value=source)
    command = Mock(return_value={"assembly": "existing response", "notice": "memory policy"})
    monkeypatch.setattr(assembly, "_safe_workspace_path", resolve)
    monkeypatch.setattr(assembly, "import_assembly", command)
    result = open_library_assembly(OpenAssemblyRequest(path="folder/scene.nass"))
    resolve.assert_called_once_with("folder/scene.nass")
    assert command.call_args.args[0].content == source.read_text.return_value
    assert result is command.return_value


@pytest.mark.parametrize("suffix,exists,status", [(".nadoc", True, 400), (".nass", False, 404)])
def test_invalid_file_is_not_imported(monkeypatch, suffix, exists, status):
    source = Mock(suffix=suffix)
    source.is_file.return_value = exists
    monkeypatch.setattr(assembly, "_safe_workspace_path", lambda _: source)
    with pytest.raises(HTTPException) as exc:
        open_library_assembly(OpenAssemblyRequest(path="scene" + suffix))
    assert exc.value.status_code == status
    source.read_text.assert_not_called()


def test_workspace_traversal_still_rejected():
    with pytest.raises(HTTPException) as exc:
        open_library_assembly(OpenAssemblyRequest(path="../../outside.nass"))
    assert exc.value.status_code == 400
