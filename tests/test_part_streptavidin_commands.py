"""Pinned coating inputs preserve native preparation, packing and rigid motion."""

from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.api import part_streptavidin_commands as commands
from backend.core import models as m, streptavidin
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_input_sources import EmbeddedResolver, SourceContractError, describe, embed
from backend.core import part_streptavidin_contract as contract


@pytest.fixture(scope="module")
def sources():
    directory = Path(__file__).resolve().parents[1] / "backend/data/proteins"
    pdb = (directory / "1STP-assembly1.pdb").read_bytes()
    coverage = (directory / "streptavidin_coverage.json").read_bytes()
    pdb_source = describe(pdb, format="pdb", media_type="chemical/x-pdb")
    coverage_source = describe(coverage, format="json", media_type="application/json")
    # Match the actual isolated worker policy without changing production
    # thread settings. Load numerical pools before the temporary test context.
    for module in ("scipy.linalg", "scipy.optimize", "scipy.spatial.transform",
                   "scipy.spatial.distance", "scipy.interpolate"):
        import_module(module)
    from threadpoolctl import threadpool_limits

    with threadpool_limits(limits=1):
        yield {"pdb": pdb, "coverage": coverage, "pdb_source": pdb_source,
               "coverage_source": coverage_source, "engine": contract.contract_defaults()["engine"],
               "table": {pdb_source.sha256: embed(pdb_source, pdb),
                         coverage_source.sha256: embed(coverage_source, coverage)}}


def inputs(sources, **changes):
    return {"_proof_version": 1, "coating_version": 1, "importer_version": 1,
            "engine": sources["engine"],
            "nanoparticle_id": "gold", "action": "set",
            "pdb_source": sources["pdb_source"].model_dump(), "coverage_source": None,
            "coverage_reference": None, "mode": "adsorption", "footprint_nm2": 40.0,
            "spacer_nm": 0.3, "seed": 1, "count_override": 1, **changes}


def source_design(sources):
    return create_empty_part("Pinned coating", "HONEYCOMB").copy_with(
        input_sources=dict(sources["table"]),
        nanoparticles=[m.Nanoparticle(id="gold", diameter_nm=20.0, visible=False,
            pose=m.Mat4x4(values=[0, -1, 0, 3, 1, 0, 0, -2, 0, 0, 1, 4, 0, 0, 0, 1]))])


def action(name, **changes):
    return {"_proof_version": 1, "coating_version": 1, "nanoparticle_id": "gold",
            "action": name, **changes}


def build(design, params):
    return commands.build("nanoparticle-patch", design, params,
                          resolver=EmbeddedResolver(design.input_sources))


def authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


def block_bundle(monkeypatch):
    class NoBundle:
        def read_text(self, *_args, **_kwargs):
            pytest.fail("Pinned command read the installed PDB")

        @property
        def parent(self):
            pytest.fail("Pinned command read installed coverage data")

    monkeypatch.setattr(streptavidin, "PDB_PATH", NoBundle())
    monkeypatch.setattr(streptavidin, "streptavidin_asset",
                        lambda *_a, **_k: pytest.fail("Pinned command used the process asset cache"))


@pytest.mark.parametrize("mode", ["adsorption", "biotin_tether"])
@pytest.mark.parametrize("preset,count,diameter", [(None, 1, 20.0), ("gold_2017", None, 14.1)])
def test_explicit_source_matches_native_full_authoring_after_bundle_access_is_removed(
        sources, monkeypatch, mode, preset, count, diameter):
    design = source_design(sources)
    spacer = 0.3 if mode == "adsorption" else 4.0
    expected_coating = streptavidin.build_streptavidin_coating(diameter, mode=mode,
        footprint_nm2=40.0, spacer_nm=spacer, seed=3, coverage_reference=preset, count_override=count)
    expected = replace_gold_nanosphere(design, "gold", diameter_nm=diameter)
    expected.nanoparticles[0] = expected.nanoparticles[0].model_copy(update={"coating": expected_coating})
    before = design.model_dump_json()
    params = inputs(sources, mode=mode, spacer_nm=spacer, seed=3, count_override=count,
        coverage_reference=preset,
        coverage_source=sources["coverage_source"].model_dump() if preset else None,
        diameter_nm=diameter)
    block_bundle(monkeypatch)
    candidate = build(design, params)
    assert authored(candidate) == authored(expected)
    assert design.model_dump_json() == before
    assert candidate.input_sources == design.input_sources
    restored = m.Design.model_validate_json(design.model_dump_json())
    assert authored(build(restored, params)) == authored(expected)
    asset = candidate.nanoparticles[0].coating.protein
    assert {atom.chain_id for atom in asset.atoms} == set("ABCD")
    assert sum(atom.res_name == "BTN" for atom in asset.atoms) == (16 if mode == "biotin_tether" else 0)
    assert asset.metadata["source_sha256"] == commands.PDB_SHA256


@pytest.fixture(scope="module")
def coated(sources):
    return build(source_design(sources), inputs(sources))


@pytest.mark.parametrize("motion", [
    {"pose": [1, 0, 0, 9, 0, 1, 0, 8, 0, 0, 1, 7, 0, 0, 0, 1]},
    {"gizmo_move": {"pivot": [2, 3, 4], "translation": [-4, 2, 1], "rotation": [0, 0, 1, 0]}},
    {"pose": [1, 0, 0, 9, 0, 1, 0, 8, 0, 0, 1, 7, 0, 0, 0, 1],
     "gizmo_move": {"pivot": [2, 3, 4], "translation": [-4, 2, 1], "rotation": [0, 0, 1, 0]}},
])
def test_pose_only_motion_retains_local_asset_and_uses_native_precedence_without_sources(coated, monkeypatch, motion):
    before = coated.model_dump_json()
    expected = replace_gold_nanosphere(coated, "gold", **motion)
    block_bundle(monkeypatch)
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Motion parsed atoms"))
    candidate = commands.build("nanoparticle-patch", coated, action("move", **motion),
        resolver=lambda *_a: pytest.fail("Motion re-read a source"))
    assert authored(candidate) == authored(expected)
    assert candidate.nanoparticles[0].coating == coated.nanoparticles[0].coating
    assert coated.model_dump_json() == before
    assert commands.resources("nanoparticle-patch", action("move", **motion)) == {"sources": (), "imports": False}


def test_explicit_resize_replacement_and_removal_preserve_particle_and_sources(sources, coated, monkeypatch):
    expected_coating = streptavidin.build_streptavidin_coating(12.0, mode="biotin_tether", spacer_nm=4.0,
        coverage_reference="gurtovenko_2019", count_override=2, seed=5)
    block_bundle(monkeypatch)
    params = inputs(sources, diameter_nm=12.0, mode="biotin_tether", spacer_nm=4.0, seed=5,
        count_override=2, coverage_reference="gurtovenko_2019",
        coverage_source=sources["coverage_source"].model_dump())
    candidate = build(coated, params)
    particle = candidate.nanoparticles[0]
    assert particle.coating == expected_coating
    assert particle.id == "gold" and particle.diameter_nm == 12.0
    assert particle.pose == coated.nanoparticles[0].pose and particle.visible is False
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Removal parsed atoms"))
    removed = commands.build("nanoparticle-patch", candidate, action("remove"),
        resolver=lambda *_a: pytest.fail("Removal re-read a source"))
    assert removed.nanoparticles[0] == particle.model_copy(update={"coating": None})
    assert removed.input_sources == candidate.input_sources == coated.input_sources
    assert coated.nanoparticles[0].coating.mode == "adsorption"
    assert commands.resources("nanoparticle-patch", params) == {
        "sources": (sources["pdb_source"], sources["coverage_source"]), "imports": True}
    assert commands.resources("nanoparticle-patch", action("remove")) == {"sources": (), "imports": False}


def test_updated_pinned_coverage_is_an_input_even_with_count_override(sources, monkeypatch):
    coverage = json.loads(sources["coverage"])
    coverage["presets"][0].update(effective_area_nm2=80.0, url="https://example.test/revised-source")
    raw = json.dumps(coverage).encode()
    descriptor = describe(raw, format="json", media_type="application/json")
    design = source_design(sources)
    design.input_sources[descriptor.sha256] = embed(descriptor, raw)
    params = inputs(sources, count_override=1, coverage_reference="gold_2007",
        coverage_source=descriptor.model_dump())
    block_bundle(monkeypatch)
    candidate = build(design, params)
    coating = candidate.nanoparticles[0].coating
    assert coating.target_count == 1 and coating.source == "https://example.test/revised-source"
    params["count_override"] = None
    candidate = build(design, params)
    assert candidate.nanoparticles[0].coating.target_count == 15


@pytest.mark.parametrize("change", [
    {"count_override": 65}, {"diameter_nm": 100.0, "count_override": None},
    {"diameter_nm": 100.0, "count_override": None, "coverage_reference": "gold_2017"},
])
def test_requested_work_is_rejected_before_atom_preparation(sources, monkeypatch, change):
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Parsed over-budget atoms"))
    params = inputs(sources, **change)
    if params["coverage_reference"]:
        params["coverage_source"] = sources["coverage_source"].model_dump()
    with pytest.raises(ProofBudgetExceeded, match="64 requested"):
        build(source_design(sources), params)


def test_maximum_count_cheap_admission_does_not_construct_geometry(sources, monkeypatch):
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Admission parsed atoms"))
    monkeypatch.setattr(streptavidin, "build_streptavidin_coating_from_inputs", lambda *_a, **_k: pytest.fail("Admission packed atoms"))
    design = source_design(sources)
    prepared = commands.validate_inputs("nanoparticle-patch", design, inputs(sources, count_override=64),
                                       resolver=EmbeddedResolver(design.input_sources))
    assert prepared.command.count_override == 64


@pytest.mark.parametrize("fault,code,path", [
    ("missing_pdb", "source_unavailable", "pdb_source"),
    ("tampered_pdb", "source_integrity_mismatch", "pdb_source"),
    ("other_pdb", "unsupported_source", "pdb_source"),
    ("missing_coverage", "source_unavailable", "coverage_source"),
])
def test_missing_or_changed_sources_are_unverified_with_exact_repair_path(sources, monkeypatch, fault, code, path):
    design, params = source_design(sources), inputs(sources)
    resolver = EmbeddedResolver(design.input_sources)
    if fault == "missing_pdb":
        resolver = EmbeddedResolver({})
    elif fault == "tampered_pdb":
        resolver = lambda _s: sources["pdb"][:-1] + b"X"
    elif fault == "other_pdb":
        params["pdb_source"] = describe(b"other source", format="pdb", media_type="chemical/x-pdb").model_dump()
    else:
        params.update(coverage_reference="gold_2007", coverage_source=sources["coverage_source"].model_dump())
        resolver = EmbeddedResolver({sources["pdb_source"].sha256: design.input_sources[sources["pdb_source"].sha256]})
    before = design.model_dump_json()
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Parsed unavailable source"))
    with pytest.raises(SourceContractError) as error:
        commands.build("nanoparticle-patch", design, params, resolver=resolver)
    assert error.value.status == "unverified" and error.value.code == code
    assert error.value.as_issue()["references"][0]["parameter_path"] == [path]
    assert design.model_dump_json() == before


@pytest.mark.parametrize("fault", ["duplicate_field", "duplicate_id", "unknown_field", "unknown_id",
    "absent_selection", "nonfinite", "quoted_number", "zero_area", "overflow_area", "oversize"])
def test_coverage_shape_and_count_arithmetic_fail_before_atom_preparation(sources, monkeypatch, fault):
    value = json.loads(sources["coverage"])
    if fault == "duplicate_id":
        value["presets"][1]["id"] = value["presets"][0]["id"]
    elif fault == "unknown_field":
        value["poses"] = []
    elif fault == "unknown_id":
        value["presets"][0]["id"] = "unknown"
    elif fault == "absent_selection":
        value["presets"] = value["presets"][1:]
    elif fault == "nonfinite":
        value["presets"][0]["effective_area_nm2"] = float("inf")
    elif fault == "quoted_number":
        value["presets"][0]["effective_area_nm2"] = "40"
    elif fault == "zero_area":
        value["presets"][0]["effective_area_nm2"] = 0
    elif fault == "overflow_area":
        value["presets"][0]["effective_area_nm2"] = 5e-324
    raw = json.dumps(value).encode()
    if fault == "duplicate_field":
        raw = b'{"presets": [],' + raw[1:]
    elif fault == "oversize":
        raw += b" " * (commands.MAX_COVERAGE_BYTES + 1)
    descriptor = describe(raw, format="json", media_type="application/json")
    design = source_design(sources)
    design.input_sources[descriptor.sha256] = embed(descriptor, raw)
    params = inputs(sources, coverage_reference="gold_2007", coverage_source=descriptor.model_dump())
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Parsed invalid coverage"))
    with pytest.raises(SourceContractError) as error:
        build(design, params)
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["coverage_source"]


@pytest.mark.parametrize("fault", ["missing", "duplicate", "gold_metadata", "biotin", "thiol", "connection", "pose"])
def test_actual_target_and_ownership_failures_are_typed_and_atomic(sources, monkeypatch, fault):
    design = source_design(sources)
    if fault == "missing":
        design.nanoparticles = []
    elif fault == "duplicate":
        design.nanoparticles *= 2
    elif fault == "gold_metadata":
        design.nanoparticles[0].kind = "quantum_dot"
    elif fault == "biotin":
        design.nanoparticles[0].biotin_dna = [m.BiotinDNA(strand_id="absent", helix_id="absent", chain="A")]
    elif fault == "thiol":
        design.nanoparticle_conjugations = [m.NanoparticleConjugation(nanoparticle_id="gold",
            sequence="ACGT", requested_count=1, estimated_capacity=1, density_per_nm2=1)]
    elif fault == "connection":
        design.nanoparticle_connection_versions = [m.NanoparticleConnectionVersion(
            nanoparticle_id="gold", strand_id="absent", overhang_id="absent")]
    else:
        design.nanoparticles[0].pose.values[3] = float("nan")
    before = design.model_dump_json()
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Parsed invalid target"))
    with pytest.raises(ReferenceResolutionError) as error:
        build(design, inputs(sources))
    assert error.value.as_issue()["references"] == [{"kind": "nanoparticle", "identity": "gold",
                                                     "parameter_path": ["nanoparticle_id"]}]
    assert design.model_dump_json() == before


@pytest.mark.parametrize("field", ["helices", "deformations", "protein_assets", "nanoparticle_conjugations"])
def test_additional_or_opaque_scope_is_unverified_before_native_work(sources, field):
    design = source_design(sources)
    if field == "nanoparticle_conjugations":
        design.nanoparticle_conjugations = [m.NanoparticleConjugation(nanoparticle_id="elsewhere",
            sequence="ACGT", requested_count=1, estimated_capacity=1, density_per_nm2=1)]
    else:
        setattr(design, field, [object()])
    with pytest.raises(CommandContractError) as error:
        build(design, inputs(sources))
    assert error.value.status == "unverified" and error.value.code == "unsupported_coating_scope"


@pytest.mark.parametrize("operation", [action("remove"), action("move", pose=[1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])])
def test_absent_coating_cannot_turn_native_remove_or_motion_into_a_noop(sources, operation):
    with pytest.raises(ReferenceResolutionError) as error:
        build(source_design(sources), operation)
    assert error.value.code == "missing_reference"


@pytest.mark.parametrize("change", [
    {"coating_version": True}, {"coating_version": 2}, {"importer_version": 2}, {"seed": True},
    {"count_override": True}, {"footprint_nm2": "40"}, {"spacer_nm": None},
    {"diameter_nm": float("inf")}, {"pose": [0] * 16}, {"atoms": []}, {"coating": {}},
    {"coverage_reference": "gold_2007"}, {"pdb_source": {"path": "/tmp/asset.pdb"}},
    {"engine": None}, {"engine": {"id": "caller-engine"}},
])
def test_strict_versioned_inputs_do_not_accept_outputs_or_implicit_choices(sources, change):
    with pytest.raises(ValidationError):
        commands.parse_command("nanoparticle-patch", inputs(sources, **change))


def test_mutable_prepared_assets_are_not_shared_between_output_and_input(sources):
    asset = streptavidin.streptavidin_asset_from_text(sources["pdb"].decode(), "adsorption")
    before = deepcopy(asset)
    result = streptavidin.build_streptavidin_coating_from_inputs(20.0, count_override=1, asset=asset)
    result.protein.atoms[0].x += 1
    result.protein.metadata["source_sha256"] = "changed output"
    assert asset == before


@pytest.mark.parametrize("field,code", [("implementation_sha256", "engine_mismatch"),
                                       ("runtime_sha256", "runtime_mismatch")])
def test_mismatched_engine_is_unverified_before_atom_parsing(sources, monkeypatch, field, code):
    design = source_design(sources)
    params = inputs(sources, engine={**sources["engine"], field: "0" * 64})
    before = design.model_dump_json()
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_a, **_k: pytest.fail("Unqualified engine parsed atoms"))
    with pytest.raises(CommandContractError) as error:
        build(design, params)
    assert error.value.status == "unverified" and error.value.code == code
    assert design.model_dump_json() == before


def test_runtime_change_during_packing_rejects_candidate_without_mutating_input(sources, monkeypatch):
    design, params = source_design(sources), inputs(sources)
    before = design.model_dump_json()
    original = streptavidin.build_streptavidin_coating_from_inputs

    def pack_then_runtime_changes(*args, **kwargs):
        coating = original(*args, **kwargs)
        monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"changed": True})
        return coating

    monkeypatch.setattr(streptavidin, "build_streptavidin_coating_from_inputs", pack_then_runtime_changes)
    with pytest.raises(CommandContractError) as error:
        build(design, params)
    assert error.value.code == "runtime_mismatch"
    assert design.model_dump_json() == before


def test_input_admission_and_move_remove_do_not_initialize_or_repin_runtime(sources, coated, monkeypatch):
    params = inputs(sources)
    monkeypatch.setattr(contract, "contract_defaults", lambda: pytest.fail("Replay silently re-pinned engine"))
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: pytest.fail("Cheap or rigid operation probed runtime"))
    commands.validate_inputs("nanoparticle-patch", source_design(sources), params,
                             resolver=EmbeddedResolver(sources["table"]))
    build(coated, action("move", pose=[1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]))
    build(coated, action("remove"))
