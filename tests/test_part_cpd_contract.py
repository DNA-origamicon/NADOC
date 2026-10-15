"""CPD admission and isolation; no molecular placement or optimization runs."""

from copy import deepcopy
import uuid

import pytest
from pydantic import ValidationError

from backend.api import part_cpd_commands as commands
from backend.core import part_cpd_contract as contract
from backend.core.models import (
    Crossover, Design, Direction, Domain, HalfCrossover, Helix,
    NucleotideTransform, PhotoproductJunction, Strand, Vec3,
)
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError


SEED = "a8a3bea5-1a9d-43cc-a70b-61e0c7736bd6"
KEYS = ["__xb__:xo:one:0", "__xb__:xo:one:1"]


@pytest.fixture
def design():
    return Design(
        helices=[Helix(id=identity, length_bp=10, axis_start=Vec3(x=x, y=0, z=0),
                       axis_end=Vec3(x=x, y=0, z=3)) for x, identity in enumerate(("a", "b"))],
        strands=[Strand(id="strand", domains=[
            Domain(helix_id=identity, start_bp=0, end_bp=9, direction=Direction.FORWARD)
            for identity in ("a", "b")
        ], sequence="T" * 20)],
        crossovers=[Crossover(id="xo:one", extra_bases="TT",
            half_a=HalfCrossover(helix_id="a", index=9, strand=Direction.FORWARD),
            half_b=HalfCrossover(helix_id="b", index=0, strand=Direction.FORWARD))],
    )


def inputs():
    return {"source": {"kind": "native"}, "base_keys": list(KEYS), "history_seed": SEED}


@pytest.fixture
def environment(monkeypatch):
    template = contract.TemplatePin.model_validate({
        "product_id": "tt-cpd-cis-syn", "schema": "nadoc.photoproduct-coordinate-template.v1",
        "sha256": contract.TEMPLATE_SHA256,
    })
    monkeypatch.setattr(contract, "_qualified_template", lambda: template)
    monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 1})
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": 1})
    return template


@pytest.fixture
def params(environment):
    return contract.prepare_command("photoproduct-create", inputs())


def converted(design):
    lesion = PhotoproductJunction(id=SEED, base_key_1=KEYS[0], base_key_2=KEYS[1],
        design_coordinates={key: {"C5": [0., 0., 0.], "C6": [0., 1., 0.]} for key in KEYS})
    poses = [NucleotideTransform(id=f"pose-{k}", kind="extra_base", crossover_id="xo:one", extra_base_k=k)
             for k in range(2)]
    return design.copy_with(photoproduct_junctions=[lesion], nucleotide_transforms=poses)


@pytest.mark.parametrize("missing", [False, True])
def test_ordinary_executor_resolves_references_without_loading_solver(design, params, monkeypatch, missing):
    from backend.api.part_proof_commands import execute

    monkeypatch.setattr(commands, "build", lambda *_: pytest.fail("Ordinary proof ran CPD builder"))
    monkeypatch.setattr(contract, "validate_environment", lambda *_: pytest.fail("Ordinary proof probed runtime"))
    if missing:
        params["base_keys"][1] = "__xb__:missing:1"
    with pytest.raises(CommandContractError) as error:
        execute("photoproduct-create", design, params)
    assert error.value.code == ("missing_reference" if missing else "long_job_required")
    if missing:
        assert error.value.as_issue()["references"][0]["parameter_path"] == ["base_keys", 1]


def test_prepare_adds_complete_pins_but_parser_never_refreshes_them(params, monkeypatch):
    assert params["_proof_version"] == params["conversion_version"] == 1
    assert params["method"] == "convert"
    assert params["source"] == {"kind": "native"}
    assert params["engine"]["implementation_sha256"] != params["engine"]["runtime_sha256"]
    monkeypatch.setattr(contract, "contract_defaults", lambda: pytest.fail("Parser refreshed pins"))
    assert contract.parse_command("photoproduct-create", params).model_dump(mode="json", by_alias=True) == params


@pytest.mark.parametrize("change", [
    lambda p: p.pop("source"),
    lambda p: p.update(source={"kind": "reference"}),
    lambda p: p.update(source={"kind": "native", "coordinates": []}),
    lambda p: p.update(engine={}),
    lambda p: p.update(template={}),
    lambda p: p.update(design_coordinates={}),
    lambda p: p.update(history_seed="not-a-uuid"),
    lambda p: p.update(stereochemistry="trans-syn-I"),
])
def test_prepare_rejects_implicit_source_caller_pins_and_solved_outputs(change, environment):
    authored = inputs()
    change(authored)
    with pytest.raises(ValidationError):
        contract.prepare_command("photoproduct-create", authored)


@pytest.mark.parametrize("change", [
    lambda p: p.pop("engine"),
    lambda p: p.pop("conversion_version"),
    lambda p: p.update(_proof_version=True),
    lambda p: p.update(conversion_version=True),
    lambda p: p["engine"].update(module_path="/tmp/untrusted.py"),
    lambda p: p.update(design_coordinates={}),
])
def test_complete_schema_does_not_upgrade_legacy_or_accept_code_paths(params, change):
    change(params)
    with pytest.raises(ValidationError):
        contract.parse_command("photoproduct-create", params)


@pytest.mark.parametrize("change,code,index", [
    (lambda d, p: p["base_keys"].__setitem__(1, "__xb__:missing:1"), "missing_reference", 1),
    (lambda d, p: p["base_keys"].__setitem__(1, "__xb__:xo:one:9"), "missing_reference", 1),
    (lambda d, p: p["base_keys"].__setitem__(1, "__xb__:xo:one:01"), "invalid_selection", 1),
    (lambda d, p: p["base_keys"].__setitem__(1, KEYS[0]), "invalid_selection", 1),
    (lambda d, p: p["base_keys"].__setitem__(0, "a:1:FORWARD"), "invalid_selection", 0),
    (lambda d, p: setattr(d.crossovers[0], "extra_bases", "AT"), "invalid_selection", 0),
    (lambda d, p: setattr(d.crossovers[0].half_a, "helix_id", "missing"), "missing_reference", 0),
    (lambda d, p: d.crossovers.append(d.crossovers[0].model_copy()), "invalid_selection", 0),
])
def test_missing_and_invalid_extra_base_targets_are_structured_before_solver(design, params, change, code, index, monkeypatch):
    from backend.core import atomistic
    monkeypatch.setattr(atomistic, "build_atomistic_model", lambda *_a, **_k: pytest.fail("Atomistic build during admission"))
    change(design, params)
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        contract.validate_inputs("photoproduct-create", design, params)
    issue = caught.value.as_issue()
    assert issue["code"] == code
    assert issue["references"][0]["parameter_path"] == ["base_keys", index]
    assert design.model_dump_json() == before


def test_consumed_targets_cannot_be_silently_reconverted(design, params):
    with pytest.raises(ReferenceResolutionError, match="already belongs"):
        contract.validate_inputs("photoproduct-create", converted(design), params)


def test_new_endpoint_pose_identity_collision_is_rejected(design, params):
    pose = NucleotideTransform(id=str(uuid.uuid5(uuid.UUID(SEED), KEYS[0])), kind="base",
                               helix_id="a", bp_index=0, direction=Direction.FORWARD)
    design = design.copy_with(nucleotide_transforms=[pose])
    with pytest.raises(ReferenceResolutionError) as caught:
        contract.validate_inputs("photoproduct-create", design, params)
    assert caught.value.as_issue()["references"][0]["parameter_path"] == ["history_seed"]


def test_missing_relaxation_lesion_is_repairable(design, environment):
    params = contract.prepare_command("photoproduct-relax", {"source": {"kind": "native"}, "photoproduct_id": "missing"})
    with pytest.raises(ReferenceResolutionError) as caught:
        contract.validate_inputs("photoproduct-relax", design, params)
    assert caught.value.as_issue()["references"] == [
        {"kind": "photoproduct", "identity": "missing", "parameter_path": ["photoproduct_id"]},
    ]


@pytest.mark.parametrize("missing_pose", [False, True])
def test_relaxation_requires_converted_coordinates_and_existing_endpoint_identities(design, environment, missing_pose):
    design = converted(design)
    if missing_pose:
        design = design.copy_with(nucleotide_transforms=design.nucleotide_transforms[:1])
    else:
        design.photoproduct_junctions[0].design_coordinates = {}
    params = contract.prepare_command("photoproduct-relax", {"source": {"kind": "native"}, "photoproduct_id": SEED})
    with pytest.raises(ReferenceResolutionError):
        contract.validate_inputs("photoproduct-relax", design, params)


@pytest.mark.parametrize("field", sorted(contract._BLOCKED_FIELDS))
def test_asset_and_connector_source_families_fail_closed(design, field):
    # A nonempty family must be rejected before any of its payload is visited.
    restricted = design.model_copy(update={field: [object()]})
    with pytest.raises(contract.CPDContractError) as caught:
        contract.validate_source(restricted)
    assert caught.value.as_issue()["code"] == "unsupported_source"
    assert field in caught.value.as_issue()["fields"]


@pytest.mark.parametrize("change,field", [
    (lambda d: setattr(d.helices[0], "native_source", "source.pdb"), "helices.native_residues/native_source"),
    (lambda d: setattr(d.helices[0], "id", "__np__carrier"), "helices.synthetic_carrier"),
    (lambda d: setattr(d.strands[0], "is_reference", True), "strands.reference_or_asset_type"),
    (lambda d: setattr(d.strands[0].domains[0], "overhang_id", "absent"), "strands.domains.overhang_reference"),
])
def test_hidden_imported_or_connector_sources_are_not_treated_as_plain_dna(design, change, field):
    change(design)
    with pytest.raises(contract.CPDContractError) as caught:
        contract.validate_source(design)
    assert field in caught.value.as_issue()["fields"]


def test_atom_admission_counts_domain_overruns_and_extra_bases(design):
    assert contract.validate_source(design) == 42 * 32
    design.strands[0].domains[0].end_bp = 1_000_000
    with pytest.raises(contract.CPDContractError) as caught:
        contract.validate_source(design)
    assert caught.value.code == "source_limit"


def test_atom_admission_counts_repeated_overlapping_domain_emission(design):
    design.strands[0].domains = design.strands[0].domains * 100
    with pytest.raises(contract.CPDContractError) as caught:
        contract.validate_source(design)
    assert caught.value.code == "source_limit"


def test_native_source_does_not_copy_recovery_or_physical_payload(design):
    class Poison:
        def __deepcopy__(self, memo):
            pytest.fail("Copied excluded payload")
    source = design.model_copy(update={"atomistic_reference": Poison(), "feature_log": [Poison()]})
    isolated = contract.native_source(source)
    assert isolated.atomistic_reference is None and isolated.feature_log == []
    assert isolated.helices == source.helices and isolated.helices[0] is not source.helices[0]
    isolated.helices[0].label = "local only"
    assert source.helices[0].label is None


def test_environment_mismatches_keep_specific_unverified_issue_codes(params, environment, monkeypatch):
    command = contract.parse_command("photoproduct-create", params)
    contract.validate_environment(command)
    monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 2})
    with pytest.raises(CommandContractError) as caught:
        contract.validate_environment(command)
    assert caught.value.status == "unverified" and caught.value.code == "engine_mismatch"
    monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 1})
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": 2})
    with pytest.raises(CommandContractError) as caught:
        contract.validate_environment(command)
    assert caught.value.code == "runtime_mismatch"


def test_recipe_template_pin_cannot_change_silently(params, environment):
    params["template"]["sha256"] = "0" * 64
    with pytest.raises(contract.CPDContractError) as caught:
        contract.validate_environment(contract.parse_command("photoproduct-create", params))
    assert caught.value.code == "template_mismatch"


def test_current_qualification_can_withdraw_a_previously_pinned_template(monkeypatch):
    from backend.core import photoproduct_registry
    monkeypatch.setattr(photoproduct_registry, "photoproduct_capability", lambda *_: {"simulation_supported": False})
    with pytest.raises(contract.CPDContractError) as caught:
        contract._qualified_template()
    assert caught.value.code == "template_unavailable"


def test_selected_template_requires_fixed_audited_bytes_not_registry_substitution(monkeypatch):
    from backend.core import photoproduct_registry
    monkeypatch.setattr(photoproduct_registry, "photoproduct_capability", lambda *_: {
        "simulation_supported": True, "id": "tt-cpd-cis-syn"})
    monkeypatch.setattr(photoproduct_registry, "photoproduct_registry", lambda: {"products": [{
        "id": "tt-cpd-cis-syn", "assets": {"coordinate_template": {
            "path": "a-new-template.json", "sha256": "f" * 64,
        }},
    }]})
    with pytest.raises(contract.CPDContractError) as caught:
        contract._qualified_template()
    assert caught.value.code == "template_mismatch"


def test_manifest_covers_own_contract_and_dependency_changes_but_not_unrelated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(contract, "_ROOT", tmp_path)
    for name in (*contract.SOURCE_PATHS, *contract.DATA_PATHS):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(name)
    first = contract.implementation_manifest()
    assert "backend/core/part_cpd_contract.py" in first["files"]
    assert "backend/api/part_cpd_commands.py" in first["files"]
    (tmp_path / "unrelated.py").write_text("irrelevant")
    assert contract.implementation_manifest() == first
    (tmp_path / "backend/core/atomistic_helpers.py").write_text("changed helper")
    assert contract.implementation_manifest() != first
    (tmp_path / "backend/core/atomistic_helpers.py").unlink()
    with pytest.raises(contract.CPDContractError) as caught:
        contract.implementation_manifest()
    assert caught.value.code == "engine_unavailable"


def test_runtime_requires_single_thread_and_fingerprints_actual_numerical_libraries(monkeypatch):
    import threadpoolctl
    pools = [{"user_api": "blas", "internal_api": "openblas", "prefix": prefix,
              "filepath": f"/installed/{prefix}.so", "version": "v1", "num_threads": 1,
              "threading_layer": "pthreads", "architecture": "test"} for prefix in ("numpy", "scipy")]
    monkeypatch.setattr(threadpoolctl, "threadpool_info", lambda: deepcopy(pools))
    monkeypatch.setattr(contract, "_file_digest", lambda path: path.name)
    observed = contract._numerical_libraries()
    assert {v["sha256"] for v in observed} == {"numpy.so", "scipy.so"}
    pools[1]["num_threads"] = 2
    with pytest.raises(contract.CPDContractError) as caught:
        contract._numerical_libraries()
    assert caught.value.code == "runtime_mismatch"


def test_command_preserves_physical_and_history_state_but_solver_only_sees_native_source(design, params, monkeypatch):
    from backend.core import cpd_design
    physical, history = object(), object()
    source = design.model_copy(update={"atomistic_reference": physical, "feature_log": [history]})
    before = source.model_dump(include=contract._AUTHORING)
    calls = []
    def fake_convert(local, keys, stereochemistry, *, identity_seed):
        assert local.atomistic_reference is None and local.feature_log == []
        assert local.model_dump(include=contract._AUTHORING) == before
        assert keys == KEYS and stereochemistry == "cis-syn" and identity_seed == SEED
        calls.append(local)
        output = converted(local)
        return output, output.photoproduct_junctions[0]
    monkeypatch.setattr(cpd_design, "convert_extra_pair", fake_convert)
    result = commands.build("photoproduct-create", source, params)
    assert len(calls) == 1
    assert result.atomistic_reference is physical and result.feature_log[0] is history
    assert source.model_dump(include=contract._AUTHORING) == before
    assert result.photoproduct_junctions[0].id == SEED


def test_environment_change_during_execution_prevents_candidate_publication(design, params, monkeypatch):
    from backend.core import cpd_design
    before = design.model_dump_json()
    def fake_convert(local, *_a, **_kw):
        monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 2})
        return converted(local), None
    monkeypatch.setattr(cpd_design, "convert_extra_pair", fake_convert)
    with pytest.raises(contract.CPDContractError) as caught:
        commands.build("photoproduct-create", design, params)
    assert caught.value.code == "engine_mismatch"
    assert design.model_dump_json() == before


def test_relax_adapter_preserves_endpoint_and_lesion_identity(design, environment, monkeypatch):
    from backend.core import cpd_design
    source = converted(design)
    before = source.model_dump_json()
    params = contract.prepare_command("photoproduct-relax", {"source": {"kind": "native"}, "photoproduct_id": SEED})
    def fake_relax(local, identity):
        assert identity == SEED
        local.photoproduct_junctions[0].bond_relaxation = {"new": "derived report"}
        return local, {"report": "diagnostic"}
    monkeypatch.setattr(cpd_design, "relax_existing_cpd", fake_relax)
    result = commands.build("photoproduct-relax", source, params)
    assert source.model_dump_json() == before
    assert [v.id for v in result.nucleotide_transforms] == [v.id for v in source.nucleotide_transforms]
    assert result.photoproduct_junctions[0].id == SEED
    assert result.photoproduct_junctions[0].bond_relaxation == {"new": "derived report"}
