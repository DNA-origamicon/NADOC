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


def test_assembly_retains_precursor_obligations_for_owning_part(host):
    from backend.core.lattice import make_bundle_design

    pending = instance(make_bundle_design([(0, 0), (0, 1)], 84), id='unrouted', name='New extrusion')
    host['assembly'] = Assembly(instances=[instance(sequenced_design()), pending])
    report = steps(routes.get_design_readiness(assembly=True))
    for key in ('scaffold_routing', 'staple_routing'):
        assert not report[key]['complete']
        assert report[key]['action'] == key
        assert report[key]['targets'][0]['instance_id'] == pending.id


def test_assembly_integrity_penalty_is_once_per_design(host):
    from backend.core.models import StrandExtension

    bad = sequenced_design()
    bad.extensions = [StrandExtension(strand_id='missing', end='five_prime', modification='biotin')]
    host['assembly'] = Assembly(instances=[instance(bad), instance(bad)])
    report = routes.get_design_readiness(assembly=True)
    assert report['completed_steps'] == report['total_steps'] == 5
    assert report['score'] == 4
    assert report['integrity_penalty'] == -1
    assert len(steps(report)['topology']['targets']) == 2
    assert report['state'] == 'incomplete'


def test_representation_revisions_reuse_assessment_but_refresh_simulation_jobs(host, tmp_path, monkeypatch):
    host['assembly'] = Assembly(instances=[instance(sequenced_design())])
    calls = {'report': 0, 'semantic': 0, 'fingerprint': 0}
    for attribute, label in (('_assembly_report', 'report'),
                             ('assembly_readiness_fingerprint', 'semantic'),
                             ('design_build_fingerprint', 'fingerprint')):
        original = getattr(routes, attribute)
        def counted(*args, _original=original, _label=label, **kwargs):
            calls[_label] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(routes, attribute, counted)
    first = routes.get_design_readiness(assembly=True)
    assert routes.get_design_readiness(assembly=True) == first
    assert calls == {'report': 1, 'semantic': 1, 'fingerprint': 1}
    for representation in ('beads', 'cylinders', 'full'):
        host['assembly'] = host['assembly'].model_copy(deep=True)
        host['assembly'].instances[0].representation = representation
        host['revision'] += 1
        assert routes.get_design_readiness(assembly=True) == first
    assert calls == {'report': 1, 'semantic': 4, 'fingerprint': 1}
    flat = Design.from_json(flatten_assembly(host['assembly']).to_json())
    save_job(tmp_path, flat, job_id='after-representation-change')
    assert routes.get_design_readiness(assembly=True)['state'] == 'ready'
    assert calls == {'report': 1, 'semantic': 4, 'fingerprint': 1}


@pytest.mark.parametrize('changed', ['visibility', 'name', 'pose', 'joint_state', 'source', 'owned_dna', 'configuration'])
def test_semantic_assembly_cache_retains_all_assessment_inputs(host, monkeypatch, changed):
    host['assembly'] = Assembly(instances=[instance(sequenced_design())])
    reports = []
    original = routes._assembly_report
    def counted(assembly):
        reports.append(assembly.id)
        return original(assembly)
    monkeypatch.setattr(routes, '_assembly_report', counted)
    routes.get_design_readiness(assembly=True)
    host['assembly'] = host['assembly'].model_copy(deep=True)
    current = host['assembly']
    part = current.instances[0]
    if changed == 'visibility':
        part.visible = False
    elif changed == 'name':
        part.name = 'Renamed part'
    elif changed == 'pose':
        part.transform.values[3] = 7
    elif changed == 'joint_state':
        part.joint_states['test-joint'] = .4
    elif changed == 'source':
        part.source.design.strands[0].sequence = 'C' + part.source.design.strands[0].sequence[1:]
    elif changed == 'owned_dna':
        current.assembly_helices.append(part.source.design.helices[0].model_copy(update={'id': 'owned'}))
    else:
        current.configuration_cursor = 'other-configuration'
    host['revision'] += 1
    routes.get_design_readiness(assembly=True)
    assert len(reports) == 2


def test_semantic_fingerprint_does_not_alias_distinct_inline_designs_with_same_id():
    from backend.core.readiness_cache import assembly_readiness_fingerprint

    original = sequenced_design()
    other = original.model_copy(deep=True)
    assembly = Assembly(instances=[instance(original), instance(other)])
    before = assembly_readiness_fingerprint(assembly)
    other.strands[0].sequence = 'C' + other.strands[0].sequence[1:]
    assert assembly_readiness_fingerprint(assembly) != before


@pytest.mark.parametrize(("length", "complete"), [(7203, False), (7249, True), (7250, False), (7560, True), (8064, True)])
def test_api_reports_exact_scaffold_length_without_mutating_design(host, length, complete):
    from tests.conftest import make_minimal_design

    design = make_minimal_design(helix_length_bp=length)
    host["design"] = design
    before = design.model_dump()
    check = steps(routes.get_design_readiness())["scaffold_length"]
    assert check["complete"] is complete
    assert check["scaffolds"][0]["actual_nt"] == length
    assert check["action"] == "validation"
    assert design.model_dump() == before


def test_scaffold_length_is_independent_per_assembly_owner_and_ignores_hidden_parts(host):
    from tests.conftest import make_minimal_design

    good = make_minimal_design(helix_length_bp=7249)
    bad = make_minimal_design(helix_length_bp=7203)
    broken = instance(bad, id="short-route", name="Short route")
    host["assembly"] = Assembly(instances=[instance(good), broken, instance(bad, visible=False)])
    check = steps(routes.get_design_readiness(assembly=True))["scaffold_length"]
    assert not check["complete"]
    assert check["action"] == "validation"
    assert [target["instance_id"] for target in check["targets"]] == [broken.id]
    assert sorted(row["actual_nt"] for row in check["scaffolds"]) == [7203, 7249]
    assert any("46 nt short of 7249 nt" in issue for issue in check["issues"])


def test_custom_source_length_survives_assembly_projection_and_reload(host):
    custom = sequenced_design(helix_length_bp=200)
    host["design"] = Design.from_json(custom.to_json())
    host["assembly"] = Assembly(instances=[instance(host["design"]), instance(host["design"])])
    part = steps(routes.get_design_readiness())["scaffold_length"]
    combined = steps(routes.get_design_readiness(assembly=True))["scaffold_length"]
    assert part["complete"] and combined["complete"]
    assert [row["actual_nt"] for row in combined["scaffolds"]] == [200, 200]
    assert all(row["matched_scaffold"] == "declared custom scaffold" for row in combined["scaffolds"])
    assert combined["targets"] == []


def test_assembly_owned_scaffold_length_cannot_be_satisfied_by_valid_parts(host):
    from tests.conftest import make_minimal_design

    owned = make_minimal_design(helix_length_bp=200, with_staple=False)
    host["assembly"] = Assembly(
        instances=[instance(sequenced_design())],
        assembly_helices=owned.helices, assembly_strands=owned.strands,
    )
    check = steps(routes.get_design_readiness(assembly=True))["scaffold_length"]
    assert not check["complete"]
    assert check["targets"] == []
    assert any(row["strand_id"] == "asm::scaf" and not row["complete"] for row in check["scaffolds"])
