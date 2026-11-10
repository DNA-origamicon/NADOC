"""UI region persistence; no engine launch or molecular structure generation."""
import asyncio

import pytest
from pydantic import ValidationError
from backend.api.simulation_submodel import SubmodelSelection, read_selection, save_selection


BOX = {"min_corner": [-2, -3, -4], "max_corner": [2, 3, 4], "rotation": [0, 0, 0.6, 0.8]}


def test_saved_reopened_and_removed_selection(tmp_path):
    assert read_selection(tmp_path) == {"box": None}
    selection = SubmodelSelection(box=BOX)
    saved = save_selection(tmp_path, selection)
    assert read_selection(tmp_path) == saved
    assert saved["box"]["rotation"] == BOX["rotation"]
    save_selection(tmp_path, SubmodelSelection())
    assert read_selection(tmp_path) == {"box": None}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["submodel_selection.json"]


@pytest.mark.parametrize("change", [
    {"min_corner": [2, 3, 4]}, {"rotation": [0, 0, 0, 0]},
    {"max_corner": [float("inf"), 3, 4]}, {"shape": "hexagonal"},
])
def test_invalid_box_rejected(change):
    with pytest.raises(ValidationError):
        SubmodelSelection(box={**BOX, **change})


@pytest.mark.parametrize("engine", ["md", "oxdna"])
def test_routes_resolve_job_storage(engine, monkeypatch, tmp_path):
    from importlib import import_module
    from types import SimpleNamespace
    routes = import_module(f"backend.api.routes_{engine}")
    monkeypatch.setattr(routes, "_load_job", lambda id: SimpleNamespace(status="queued", job_dir=lambda ws: tmp_path / id))
    monkeypatch.setattr(routes, "_workspace", lambda: tmp_path)
    (tmp_path / "job-a").mkdir()
    (tmp_path / "job-b").mkdir()
    put = getattr(routes, f"put_{engine}_submodel")
    get = getattr(routes, f"get_{engine}_submodel")
    asyncio.run(put("job-a", SubmodelSelection(box=BOX)))
    assert asyncio.run(get("job-a"))["box"]["min_corner"] == BOX["min_corner"]
    assert asyncio.run(get("job-b")) == {"box": None}


def test_namd_settings_rebuild_preserves_region(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    save_selection(tmp_path, SubmodelSelection(box=BOX))
    (tmp_path / "old-input.txt").write_text("disposable test input")
    routes_md._clear_editable_job_artifacts(SimpleNamespace(job_dir=lambda ws: tmp_path))
    assert read_selection(tmp_path)["box"]["rotation"] == BOX["rotation"]
    assert not (tmp_path / "old-input.txt").exists()


@pytest.mark.parametrize("radius", [-1, 1001, float("inf"), float("nan")])
def test_invalid_shell_rejected(radius):
    with pytest.raises(ValidationError):
        SubmodelSelection(box={**BOX, "shell_nm": radius})


def test_shell_visibility_persistence_and_legacy_default(tmp_path):
    assert SubmodelSelection(box=BOX).box.shell_nm == 3
    save_selection(tmp_path, SubmodelSelection(box={**BOX, "shell_nm": 0, "visible": False}))
    assert read_selection(tmp_path)["box"]["shell_nm"] == 0
    assert read_selection(tmp_path)["box"]["visible"] is False
