"""Inactive broken input evidence remains visible and repairable."""

import base64
import gzip

import pytest

from backend.core.design_loadouts import encode_snapshot
from backend.core.models import Design, DesignLoadout, SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_source_audit import audit_current_sources, audit_loadout_sources


def branch(*, missing=False):
    content = b"source bytes"
    source = describe(content, format="pdb", media_type="chemical/x-pdb")
    entry = SnapshotLogEntry(id="import-feature", op_kind="protein-import", label="Import source",
        params={"_proof_version": 1, "source": source.model_dump()})
    design = create_empty_part("Test", "HONEYCOMB").copy_with(feature_log=[entry], input_sources=(
        {} if missing else {source.sha256: embed(source, content)}))
    return design, source


def loadout(design, identity="inactive"):
    encoded, size = encode_snapshot(design)
    return DesignLoadout(id=identity, name=identity, design_snapshot_gz_b64=encoded,
                         snapshot_size_bytes=size)


def test_missing_inactive_source_reports_exact_branch_feature_and_hash_without_mutation():
    broken, source = branch(missing=True)
    design = Design(loadouts=[loadout(broken)])
    before = design.model_dump_json()
    result = audit_loadout_sources(design)
    issue = result["loadouts"][0]["issues"][0]
    assert result["complete"]
    assert issue["status"] == "unverified" and issue["code"] == "source_unavailable"
    assert (issue["loadout_id"], issue["feature_id"]) == ("inactive", "import-feature")
    assert issue["references"] == [{"kind": "input_source", "identity": source.sha256,
                                     "parameter_path": ["source"]}]
    assert design.model_dump_json() == before


def test_source_tables_are_branch_local_and_no_outer_cache_substitutes_for_missing_bytes():
    valid, source = branch()
    broken, _ = branch(missing=True)
    design = valid.copy_with(loadouts=[loadout(broken)])
    assert not audit_current_sources(design)["issues"]
    assert audit_loadout_sources(design)["loadouts"][0]["issues"][0]["code"] == "source_unavailable"
    assert audit_loadout_sources(Design(loadouts=[loadout(valid)]))["loadouts"][0]["sources"] == [source.model_dump()]


def test_repeated_source_references_are_verified_once_per_explicit_audit(monkeypatch):
    from backend.core import part_source_audit
    original = part_source_audit.EmbeddedResolver
    calls = []
    class CountedResolver(original):
        def __call__(self, source):
            calls.append(source.sha256)
            return super().__call__(source)
    monkeypatch.setattr(part_source_audit, "EmbeddedResolver", CountedResolver)
    design, source = branch()
    design.feature_log.append(design.feature_log[0].model_copy(update={"id": "another-import"}))
    assert audit_current_sources(design)["issues"] == []
    assert calls == [source.sha256]


def test_audit_never_decodes_feature_recovery_outputs():
    design, _ = branch()
    design.feature_log[0].design_snapshot_gz_b64 = "poisoned output"
    design.feature_log[0].post_state_gz_b64 = "poisoned output"
    assert audit_current_sources(design)["issues"] == []


def test_cumulative_decode_and_count_budgets_surface_uninspected_branches():
    design, _ = branch()
    saved = loadout(design)
    current = Design(loadouts=[saved, saved.model_copy(update={"id": "second"})])
    result = audit_loadout_sources(current, max_bytes=saved.snapshot_size_bytes)
    assert not result["complete"]
    assert result["issues"][0]["loadout_id"] == "second"
    assert result["issues"][0]["remaining_loadouts"] == 1
    assert len(audit_loadout_sources(current, max_loadouts=1)["loadouts"]) == 1


def test_bomb_and_corrupt_loadout_are_retained_as_diagnostics_and_charge_budget():
    bomb = base64.b64encode(gzip.compress(b"x" * 1000)).decode()
    current = Design(loadouts=[DesignLoadout(id="bomb", design_snapshot_gz_b64=bomb),
                              DesignLoadout(id="not-visited", design_snapshot_gz_b64="bad")])
    result = audit_loadout_sources(current, max_bytes=100)
    assert result["loadouts"][0]["issues"][0]["code"] == "document_transport_limit"
    assert result["issues"][0]["loadout_id"] == "not-visited"
    assert len(current.loadouts) == 2


def test_nested_legacy_loadouts_warn_without_recursive_decode():
    design, _ = branch()
    nested = design.copy_with(loadouts=[DesignLoadout(design_snapshot_gz_b64="poisoned nested")])
    # Historical externally-authored nesting; ordinary encode strips loadouts.
    payload = base64.b64encode(gzip.compress(nested.model_dump_json().encode())).decode()
    current = Design(loadouts=[DesignLoadout(id="outer", design_snapshot_gz_b64=payload)])
    result = audit_loadout_sources(current)
    assert result["loadouts"][0]["issues"][0]["code"] == "nested_loadout_sources"
    assert not result["complete"]


def test_loadout_activation_warns_but_preserves_the_repairable_definition(monkeypatch):
    from backend.api import routes_design_loadouts as routes
    broken, source = branch(missing=True)
    saved = loadout(broken)
    current = Design(loadouts=[saved], active_loadout_id="inactive")
    published = []
    monkeypatch.setattr(routes.design_state, "get_or_404", lambda: current)
    monkeypatch.setattr(routes.design_state, "set_design_branch", published.append)
    monkeypatch.setattr(routes, "validate_design", lambda d: None)
    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda d, r, **kw: {"id": d.id})
    response = routes.select_loadout("inactive", save_current=False)
    assert response["source_warnings"][0]["references"][0]["identity"] == source.sha256
    assert published[0].feature_log[0].id == "import-feature"
    assert published[0].input_sources == {}
    assert published[0].loadouts == [saved]


def test_explicit_audit_endpoint_inspects_branches_without_publishing(monkeypatch):
    from backend.api import routes_design_loadouts as routes
    broken, _ = branch(missing=True)
    current = Design(loadouts=[loadout(broken)])
    monkeypatch.setattr(routes.design_state, "get_or_404", lambda: current)
    monkeypatch.setattr(routes.design_state, "set_design_branch", lambda *_: pytest.fail("Audit published state"))
    result = routes.audit_loadout_inputs()
    assert not result["current"]["issues"]
    assert result["loadouts"][0]["issues"][0]["code"] == "source_unavailable"


def test_native_proof_ignores_inactive_recovery_even_when_undecodable():
    from backend.core.part_history_proof import assess
    from backend.api.part_proof_commands import dependencies, execute
    design = create_empty_part("Test", "HONEYCOMB").copy_with(loadouts=[DesignLoadout(design_snapshot_gz_b64="poisoned")])
    result = assess(design, max_entries=10, execute=execute, dependencies=dependencies, checkpoint=None)
    assert result["status"] == "verified"


@pytest.mark.parametrize("mode", ["thin", "full"])
def test_package_preserves_inactive_broken_draft_and_returns_repair_warnings(tmp_path, monkeypatch, mode):
    from backend.core import native_part_package as package

    broken, source = branch(missing=True)
    original = Design(loadouts=[loadout(broken)])
    workspace = tmp_path / "source"
    workspace.mkdir()
    part = workspace / "part.nadoc"
    part.write_text(original.to_json())
    monkeypatch.setattr(package, "_job_classes", lambda: ())
    archive = tmp_path / "part.nadocpkg"
    manifest = package.create_package(workspace, "part.nadoc", archive, mode=mode)
    assert manifest["authoring_loadouts"]["loadouts"][0]["issues"][0]["code"] == "source_unavailable"
    restored = package.import_package(tmp_path / "target", archive, "part.nadoc")
    assert restored["source_warnings"][0]["references"][0]["identity"] == source.sha256
    assert (tmp_path / "target/part.nadoc").read_text() == original.to_json()


def test_open_current_broken_draft_warns_without_inactive_decode(monkeypatch):
    from backend.api import crud
    from backend.core import part_source_audit, validator

    broken, _ = branch(missing=True)
    broken = broken.copy_with(loadouts=[DesignLoadout(design_snapshot_gz_b64="poisoned")])
    installed = []
    monkeypatch.setattr(crud.design_state, "load_design", installed.append)
    monkeypatch.setattr(crud, "_design_response", lambda d, r, **kw: {"id": d.id})
    monkeypatch.setattr(validator, "validate_design", lambda d: None)
    monkeypatch.setattr(part_source_audit, "decode_snapshot_bytes", lambda *_a, **_kw: pytest.fail("Decoded inactive branch"))
    response = crud._install_loaded_design(broken)
    assert response["source_warnings"][0]["code"] == "source_unavailable"
    assert installed == [broken]


def test_multiple_source_inputs_report_each_exact_repair_path_even_with_cached_errors():
    pdb = describe(b"missing assembly", format="pdb", media_type="chemical/x-pdb")
    coverage = describe(b"missing publication", format="json", media_type="application/json")
    coating = SnapshotLogEntry(id="coating", op_kind="nanoparticle-patch", label="Coating", params={
        "_proof_version": 1, "coating_version": 1, "action": "set",
        "pdb_source": pdb.model_dump(), "coverage_source": coverage.model_dump()})
    other = SnapshotLogEntry(id="import", op_kind="protein-import", label="Import", params={
        "_proof_version": 1, "source": pdb.model_dump()})
    design = Design(feature_log=[coating, other])
    before = design.model_dump_json()
    result = audit_current_sources(design)
    assert result["complete"] and len(result["sources"]) == 2
    assert [(issue["feature_id"], issue["references"][0]["parameter_path"])
            for issue in result["issues"]] == [
        ("coating", ["pdb_source"]), ("coating", ["coverage_source"]), ("import", ["source"])]
    assert all(issue["code"] == "source_unavailable" for issue in result["issues"])
    assert design.model_dump_json() == before
