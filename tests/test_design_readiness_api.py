"""Active-document/assembly host parity and readiness cache invalidation."""

from collections import OrderedDict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_design_readiness as routes
from backend.core.assembly_flatten import flatten_assembly
from backend.core.models import Assembly, Design, PartInstance, PartSourceFile, PartSourceInline
from tests.test_design_readiness import save_job, sequenced_design, steps


@pytest.fixture
def host(monkeypatch, tmp_path):
    from backend.api import assembly, assembly_state, state

    values = {"design": None, "assembly": None, "revision": 1}
    monkeypatch.setattr(routes, "_CACHE", OrderedDict())
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(state, "get_design_with_revision", lambda: (values["design"], values["revision"]))
    monkeypatch.setattr(assembly_state, "get_assembly", lambda: values["assembly"])
    monkeypatch.setattr(assembly_state, "revision", lambda: values["revision"])
    return values


def instance(design, **kwargs):
    return PartInstance(source=PartSourceInline(design=design), **kwargs)


def test_route_empty_and_part_assembly_parity_without_state_writes(host):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    client = TestClient(app)
    assert not client.get("/api/design/readiness").json()["available"]
    design = sequenced_design()
    assembly = Assembly(instances=[instance(design)])
    host.update(design=design, assembly=assembly)
    before = (design.model_dump(), assembly.model_dump())
    part = client.get("/api/design/readiness").json()
    combined = client.get("/api/design/readiness?assembly=true").json()
    assert part["state"] == combined["state"] == "simulation_recommended"
    assert part["completed_steps"] == combined["completed_steps"] == 5
    assert combined["context"] == "assembly"
    assert combined["document_id"] == assembly.id
    assert combined["design_id"] == f"flat_{assembly.id}"
    assert part["document_id"] == design.id
    assert (design.model_dump(), assembly.model_dump()) == before


def test_simulation_finishes_without_design_revision_change(host, tmp_path):
    host["design"] = sequenced_design()
    assert routes.get_design_readiness()["state"] == "simulation_recommended"
    save_job(tmp_path, host["design"])
    assert routes.get_design_readiness()["state"] == "ready"
    host["design"] = host["design"].model_copy(deep=True)
    host["design"].strands[0].sequence = "C" + host["design"].strands[0].sequence[1:]
    host["revision"] += 1
    assert routes.get_design_readiness()["state"] == "simulation_recommended"


def test_assembly_exposes_missing_owning_part_and_does_not_count_other_parts(host):
    good = sequenced_design()
    bad = sequenced_design(with_scaffold=False)
    broken = instance(bad, id="missing-scaffold", name="Missing scaffold")
    host["assembly"] = Assembly(instances=[instance(good), broken])
    report = routes.get_design_readiness(assembly=True)
    scaffold = steps(report)["scaffold_routing"]
    assert not scaffold["complete"]
    assert scaffold["targets"][0]["instance_id"] == broken.id
    assert report["state"] == "incomplete"


def test_hidden_parts_are_excluded_and_assembly_simulation_must_match_flattening(host, tmp_path):
    good = sequenced_design()
    host["assembly"] = Assembly(instances=[instance(good), instance(sequenced_design(with_scaffold=False), visible=False)])
    flat = Design.from_json(flatten_assembly(host["assembly"]).to_json())
    save_job(tmp_path, good)
    assert routes.get_design_readiness(assembly=True)["state"] == "simulation_recommended"
    save_job(tmp_path, flat, job_id="assembly-fine")
    assert routes.get_design_readiness(assembly=True)["state"] == "ready"


def test_source_file_changes_invalidate_without_assembly_revision_change(host, tmp_path):
    source = tmp_path / "part.nadoc"
    design = sequenced_design()
    source.write_text(design.to_json())
    host["assembly"] = Assembly(instances=[PartInstance(source=PartSourceFile(path=str(source)))])
    assert routes.get_design_readiness(assembly=True)["state"] == "simulation_recommended"
    design.strands[1].sequence = None
    source.write_text(design.to_json())
    assert routes.get_design_readiness(assembly=True)["state"] == "incomplete"


def test_missing_part_is_actionable_and_does_not_check_stale_active_part(host, tmp_path):
    host["design"] = sequenced_design()
    host["assembly"] = Assembly(instances=[PartInstance(id="missing", source=PartSourceFile(path=str(tmp_path / "missing.nadoc")))])
    report = routes.get_design_readiness(assembly=True)
    assert report["available"]
    assert report["state"] == "incomplete"
    assert steps(report)["topology"]["targets"][0]["instance_id"] == "missing"
