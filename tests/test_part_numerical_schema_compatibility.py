"""Exact, disclosed schema-only compatibility; no numerical solver executes."""

from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.part_command_errors import CommandContractError
from backend.core.part_numerical_runtime import digest


ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "docs/audits/feature_history_20261014/grouping_schema_compatibility_before.json"
DISSOLVE_BEFORE = ROOT / "docs/audits/feature_history_20261014/cluster_dissolve_schema_compatibility_before.json"
BASELINES = {"grouping-v1": BEFORE, "grouping-v2": DISSOLVE_BEFORE}
FAMILIES = ("part_cpd_contract", "part_duplex_relax_contract", "part_streptavidin_contract")
ENGINE = "nadoc.cpd-native-engine.v1"
EVENT = "cluster-create-proof-v2"
SCHEMA = "nadoc.numerical-schema-compatibility.v1"


def manifest():
    return {"id": ENGINE, "solver": "unchanged", "files": {
        "backend/core/models.py": "1" * 64,
        "backend/core/kernel.py": "2" * 64,
    }, "data": {"template.json": "3" * 64}}


def transition(old, current, *, identity="grouping-cpd-v1"):
    return {"id": identity, "event": EVENT, "source_checkpoint": "1ae1137f",
            "engine_id": old["id"], "from_sha256": digest(old), "to_sha256": digest(current),
            "changed_paths": ["backend/core/models.py"],
            "rationale": "Only the reviewed grouping history schema changes."}


@pytest.fixture
def compatibility():
    # Lazy import keeps the tests-first baseline independent of production edits.
    return import_module("backend.core.part_numerical_schema_compatibility")


def install_policy(monkeypatch, tmp_path, compatibility, entries, *, raw=None):
    path = tmp_path / "policy.json"
    path.write_text(raw if raw is not None else json.dumps({"schema": SCHEMA, "transitions": entries}))
    monkeypatch.setattr(compatibility, "POLICY_PATH", path)
    return path


def require(compatibility, authored, current, *, engine=ENGINE):
    return compatibility.require_implementation(engine, authored, current,
        error_type=CommandContractError, detail="Numerical implementation changed")


def test_exact_current_pin_does_not_need_compatibility_policy(compatibility, monkeypatch, tmp_path):
    monkeypatch.setattr(compatibility, "POLICY_PATH", tmp_path / "absent.json")
    current = manifest()
    assert require(compatibility, digest(current), current) is None


def test_direct_exact_transition_is_disclosed_without_rewriting_inputs(compatibility, monkeypatch, tmp_path):
    old, current = manifest(), manifest()
    current["files"]["backend/core/models.py"] = "4" * 64
    saved = deepcopy(current)
    authored = digest(old)
    install_policy(monkeypatch, tmp_path, compatibility, [transition(old, current)])
    assert require(compatibility, authored, current) == "grouping-cpd-v1"
    assert current == saved and authored == digest(old)


@pytest.mark.parametrize("mutation", ["kernel", "model", "data", "solver", "added_file", "missing_file", "foreign_id"])
def test_policy_never_accepts_partial_manifest_similarity(compatibility, monkeypatch, tmp_path, mutation):
    old, current = manifest(), manifest()
    current["files"]["backend/core/models.py"] = "4" * 64
    install_policy(monkeypatch, tmp_path, compatibility, [transition(old, current)])
    changed = deepcopy(current)
    if mutation in {"kernel", "model"}:
        changed["files"]["backend/core/kernel.py" if mutation == "kernel" else "backend/core/models.py"] = "5" * 64
    elif mutation == "data":
        changed["data"]["template.json"] = "5" * 64
    elif mutation == "solver":
        changed["solver"] = "different"
    elif mutation == "added_file":
        changed["files"]["other.py"] = "5" * 64
    elif mutation == "missing_file":
        del changed["files"]["backend/core/kernel.py"]
    else:
        changed["id"] = "another-engine"
    with pytest.raises(CommandContractError, match="Numerical implementation changed") as error:
        require(compatibility, digest(old), changed)
    assert error.value.code == "engine_mismatch"


def test_no_transitive_or_cross_engine_compatibility(compatibility, monkeypatch, tmp_path):
    old, middle, current = manifest(), manifest(), manifest()
    middle["files"]["backend/core/models.py"] = "4" * 64
    current["files"]["backend/core/models.py"] = "5" * 64
    install_policy(monkeypatch, tmp_path, compatibility, [
        transition(old, middle), transition(middle, current, identity="second-event")])
    for pin, engine in ((digest(old), ENGINE), (digest(middle), "foreign-engine"), ("f" * 64, ENGINE)):
        with pytest.raises(CommandContractError) as error:
            require(compatibility, pin, current, engine=engine)
        assert error.value.code == "engine_mismatch"


@pytest.mark.parametrize("raw", [
    "{", '{"schema":"wrong","transitions":[]}',
    '{"schema":true,"transitions":[]}',
    '{"schema":"nadoc.numerical-schema-compatibility.v1","transitions":[],"unknown":1}',
    '{"schema":"nadoc.numerical-schema-compatibility.v1","transitions":[],"transitions":[]}',
    '{"schema":"nadoc.numerical-schema-compatibility.v1","transitions":NaN}',
])
def test_invalid_policy_fails_closed(compatibility, monkeypatch, tmp_path, raw):
    install_policy(monkeypatch, tmp_path, compatibility, [], raw=raw)
    with pytest.raises(CommandContractError) as error:
        require(compatibility, "f" * 64, manifest())
    assert error.value.code == "engine_mismatch"


def test_oversized_policy_is_bounded(compatibility, monkeypatch, tmp_path):
    install_policy(monkeypatch, tmp_path, compatibility, [], raw=" " * (64 * 1024))
    with pytest.raises(CommandContractError) as error:
        require(compatibility, "f" * 64, manifest())
    assert error.value.code == "engine_mismatch"


def environment(monkeypatch, contract, implementation_pin):
    runtime = {"runtime": "same qualified worker"}
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: runtime)
    engine = contract.EnginePin(id=contract.ENGINE_ID,
        implementation_sha256=implementation_pin, runtime_sha256=digest(runtime))
    if contract.__name__.endswith("part_streptavidin_contract"):
        return engine, engine
    command = SimpleNamespace(engine=engine)
    if contract.__name__.endswith("part_cpd_contract"):
        template = contract.TemplatePin.model_validate({"product_id": "tt-cpd-cis-syn",
            "schema": "nadoc.photoproduct-coordinate-template.v1", "sha256": contract.TEMPLATE_SHA256})
        command.template = template
        monkeypatch.setattr(contract, "_qualified_template", lambda: template)
    return command, engine


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("generation", BASELINES)
def test_real_captured_old_manifest_has_one_exact_reviewed_transition(compatibility, monkeypatch, family, generation):
    contract = import_module(f"backend.core.{family}")
    capture = json.loads(BASELINES[generation].read_text())
    before = capture["engines"][contract.ENGINE_ID]
    current = contract.implementation_manifest()
    assert digest(before["manifest"]) == before["implementation_sha256"]
    assert digest(current) != before["implementation_sha256"]
    policy = json.loads(compatibility.POLICY_PATH.read_text())
    entries = [entry for entry in policy["transitions"]
               if entry["engine_id"] == contract.ENGINE_ID
               and entry["from_sha256"] == before["implementation_sha256"]
               and entry["to_sha256"] == digest(current)]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == f"cluster-dissolve-v1.from-{generation}.{contract.ENGINE_ID}"
    assert entry["event"] == "cluster-dissolve-v1"
    assert entry["source_checkpoint"] == capture["checkpoint"]
    old_files, new_files = before["manifest"]["files"], current["files"]
    changes = {path for path in old_files.keys() | new_files.keys() if old_files.get(path) != new_files.get(path)}
    expected = {"backend/core/models.py"}
    if generation == "grouping-v1":
        expected |= {f"backend/core/{family}.py", "backend/core/part_numerical_schema_compatibility.py"}
    assert changes == set(entry["changed_paths"]) == expected
    assert {key: value for key, value in before["manifest"].items() if key != "files"} == {
        key: value for key, value in current.items() if key != "files"}
    command, engine = environment(monkeypatch, contract, before["implementation_sha256"])
    saved = engine.model_dump()
    assert contract.validate_environment(command) == entry["id"]
    assert engine.model_dump() == saved
    assert contract.contract_defaults()["engine"]["implementation_sha256"] == digest(current)


@pytest.mark.parametrize("family", FAMILIES)
def test_original_reviewed_edges_remain_available_as_exact_historical_evidence(compatibility, family):
    contract = import_module(f"backend.core.{family}")
    oldest = json.loads(BEFORE.read_text())
    prior = json.loads(DISSOLVE_BEFORE.read_text())["engines"][contract.ENGINE_ID]
    original = oldest["engines"][contract.ENGINE_ID]
    entries = [entry for entry in compatibility._policy()
               if entry["id"] == f"grouping-proof-v2.{contract.ENGINE_ID}"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == EVENT and entry["source_checkpoint"] == oldest["checkpoint"]
    assert entry["from_sha256"] == original["implementation_sha256"]
    assert entry["to_sha256"] == prior["implementation_sha256"] == digest(prior["manifest"])
    changed = {path for path in original["manifest"]["files"].keys() | prior["manifest"]["files"].keys()
               if original["manifest"]["files"].get(path) != prior["manifest"]["files"].get(path)}
    assert changed == set(entry["changed_paths"]) == {
        "backend/core/models.py", f"backend/core/{family}.py",
        "backend/core/part_numerical_schema_compatibility.py"}


@pytest.mark.parametrize("family", FAMILIES)
def test_real_three_generation_policy_requires_the_explicit_direct_edge(compatibility, monkeypatch, tmp_path, family):
    contract = import_module(f"backend.core.{family}")
    oldest = json.loads(BEFORE.read_text())["engines"][contract.ENGINE_ID]
    prior = json.loads(DISSOLVE_BEFORE.read_text())["engines"][contract.ENGINE_ID]
    current = contract.implementation_manifest()
    without_direct = [entry for entry in compatibility._policy()
                      if not (entry["engine_id"] == contract.ENGINE_ID
                              and entry["from_sha256"] == oldest["implementation_sha256"]
                              and entry["to_sha256"] == digest(current))]
    install_policy(monkeypatch, tmp_path, compatibility, without_direct)
    # The old→prior and prior→current pair remains usable individually. It
    # cannot infer approval for old→current if that separately reviewed edge
    # is absent, even when all three captured manifests are genuine.
    assert require(compatibility, oldest["implementation_sha256"], prior["manifest"], engine=contract.ENGINE_ID)
    assert require(compatibility, prior["implementation_sha256"], current, engine=contract.ENGINE_ID)
    with pytest.raises(CommandContractError) as error:
        require(compatibility, oldest["implementation_sha256"], current, engine=contract.ENGINE_ID)
    assert error.value.code == "engine_mismatch"


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("generation", BASELINES)
def test_every_participating_file_data_and_runtime_remain_strict(compatibility, monkeypatch, family, generation):
    contract = import_module(f"backend.core.{family}")
    before = json.loads(BASELINES[generation].read_text())["engines"][contract.ENGINE_ID]
    current = contract.implementation_manifest()
    command, engine = environment(monkeypatch, contract, before["implementation_sha256"])
    assert contract.validate_environment(command)
    saved = engine.model_dump()
    for section in ("files", "data"):
        for path in current.get(section, {}):
            changed = deepcopy(current)
            changed[section][path] = "f" * 64
            monkeypatch.setattr(contract, "implementation_manifest", lambda value=changed: value)
            with pytest.raises(CommandContractError) as error:
                contract.validate_environment(command)
            assert error.value.code == "engine_mismatch", (family, path)
    monkeypatch.setattr(contract, "implementation_manifest", lambda: current)
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": "different"})
    with pytest.raises(CommandContractError) as error:
        contract.validate_environment(command)
    assert error.value.code == "runtime_mismatch"
    assert engine.model_dump() == saved


@pytest.mark.parametrize("generation", BASELINES)
def test_template_check_is_not_bypassed_by_schema_transition(compatibility, monkeypatch, generation):
    from backend.core import part_cpd_contract as contract

    before = json.loads(BASELINES[generation].read_text())["engines"][contract.ENGINE_ID]
    command, _ = environment(monkeypatch, contract, before["implementation_sha256"])
    assert contract.validate_environment(command)
    command.template = command.template.model_copy(update={"sha256": "f" * 64})
    with pytest.raises(CommandContractError) as error:
        contract.validate_environment(command)
    assert error.value.code == "template_mismatch"


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("failure", [None, "before", "during"])
def test_existing_builder_environment_fences_and_kernel_counts_are_preserved(
        compatibility, monkeypatch, family, failure):
    """Only the numerical leaf is fake; each real adapter keeps both fences."""
    from backend.core.models import Design, Nanoparticle

    contract = import_module(f"backend.core.{family}")
    before = json.loads(BEFORE.read_text())["engines"][contract.ENGINE_ID]
    command, engine = environment(monkeypatch, contract, before["implementation_sha256"])
    pin = engine.model_dump()
    calls = []
    source = Design()

    def kernel(candidate=None, *_args, **_kwargs):
        calls.append(True)
        if failure == "during":
            monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": "changed during work"})
        return candidate, {}

    if family == "part_cpd_contract":
        from backend.api import part_cpd_commands as commands
        from backend.core import cpd_design

        command.base_keys, command.stereochemistry, command.history_seed = ["a", "b"], "cis-syn", "seed"
        monkeypatch.setattr(commands, "validate_inputs", lambda *_: command)
        monkeypatch.setattr(commands, "native_source", lambda value: value.model_copy(deep=True))
        monkeypatch.setattr(cpd_design, "convert_extra_pair", kernel)

        def run():
            return commands.build("photoproduct-create", source, {})

    elif family == "part_duplex_relax_contract":
        from backend.api import part_duplex_commands as commands
        from backend.core import direct_relax

        command.driver_overhang_id, command.driven_overhang_id, command.joint_ids = "driver", "driven", []
        monkeypatch.setattr(contract, "validate_inputs", lambda *_: command)
        monkeypatch.setattr(contract, "native_source", lambda value: value.model_copy(deep=True))
        monkeypatch.setattr(direct_relax, "relax_direct_binding", kernel)

        def run():
            return commands.relax(source, {})

    else:
        from backend.api import part_streptavidin_commands as commands
        from backend.core import streptavidin

        source = Design(nanoparticles=[Nanoparticle(id="gold", diameter_nm=20)])
        command = commands.SetRequest.model_construct(engine=engine, mode="adsorption", footprint_nm2=40.0,
            spacer_nm=0.3, seed=1, coverage_reference=None, count_override=1)
        prepared = SimpleNamespace(command=command, particle=source.nanoparticles[0],
            diameter_nm=20.0, pdb_text="unused pinned fixture", coverage_data=None)
        monkeypatch.setattr(commands, "validate_inputs", lambda *_args, **_kwargs: prepared)
        monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text", lambda *_: object())

        def packing(*_args, **_kwargs):
            kernel()
            return None

        monkeypatch.setattr(streptavidin, "build_streptavidin_coating_from_inputs", packing)

        def run():
            return commands.build("nanoparticle-patch", source, {}, resolver=None)

    original = source.model_dump(mode="json")
    if failure == "before":
        monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": "different"})
    if failure is None:
        assert run().model_dump(mode="json") == original
    else:
        with pytest.raises(CommandContractError) as error:
            run()
        assert error.value.code == "runtime_mismatch"
    assert len(calls) == (0 if failure == "before" else 1)
    assert source.model_dump(mode="json") == original
    assert engine.model_dump() == pin


def test_diagnostics_are_scoped_deduplicated_and_restore_after_nested_failure(
        compatibility, monkeypatch, tmp_path):
    old, current = manifest(), manifest()
    current["files"]["backend/core/models.py"] = "4" * 64
    install_policy(monkeypatch, tmp_path, compatibility, [transition(old, current)])
    with compatibility.collect_implementation_compatibility() as outer:
        require(compatibility, digest(old), current)
        with pytest.raises(RuntimeError), compatibility.collect_implementation_compatibility() as inner:
            assert inner == {"transitions": [], "truncated": False}
            require(compatibility, digest(old), current)
            raise RuntimeError("verification failed after acceptance")
        require(compatibility, digest(old), current)
        assert len(outer["transitions"]) == len(inner["transitions"]) == 1
        assert outer["transitions"][0] is not inner["transitions"][0]
    snapshot = deepcopy(outer)
    require(compatibility, digest(old), current)  # No collector inherits old evidence.
    assert outer == snapshot and outer["truncated"] is False
    with compatibility.collect_implementation_compatibility() as fresh:
        require(compatibility, digest(current), current)
        assert fresh == {"transitions": [], "truncated": False}


def test_concurrent_verification_collectors_do_not_mix(compatibility, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    pairs = []
    for engine in (ENGINE, "nadoc.duplex-relax-native.v1"):
        old, current = manifest(), manifest()
        old["id"] = current["id"] = engine
        current["files"]["backend/core/models.py"] = "4" * 64
        pairs.append((old, current))
    install_policy(monkeypatch, tmp_path, compatibility,
        [transition(old, current, identity=f"event-{index}") for index, (old, current) in enumerate(pairs)])
    barrier = Barrier(2, timeout=3)

    def assess(pair):
        old, current = pair
        with compatibility.collect_implementation_compatibility() as evidence:
            barrier.wait()
            require(compatibility, digest(old), current, engine=old["id"])
            barrier.wait()
            return evidence

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(assess, pairs))
    assert [item["transitions"][0]["engine_id"] for item in results] == [pair[0]["id"] for pair in pairs]
    assert all(len(item["transitions"]) == 1 and not item["truncated"] for item in results)


def test_diagnostic_overflow_is_explicit_and_bounded(compatibility, monkeypatch, tmp_path):
    pairs = []
    for index in range(4):
        old, current = manifest(), manifest()
        old["id"] = current["id"] = f"reviewed-engine-{index}"
        current["files"]["backend/core/models.py"] = "4" * 64
        pairs.append((old, current))
    install_policy(monkeypatch, tmp_path, compatibility,
        [transition(old, current, identity=f"event-{index}") for index, (old, current) in enumerate(pairs)])
    with compatibility.collect_implementation_compatibility() as evidence:
        for old, current in pairs:
            require(compatibility, digest(old), current, engine=old["id"])
    assert len(evidence["transitions"]) == 3 and evidence["truncated"] is True


def test_runtime_failure_retains_the_separate_implementation_decision(compatibility, monkeypatch):
    from backend.core import part_streptavidin_contract as contract

    before = json.loads(BEFORE.read_text())["engines"][contract.ENGINE_ID]
    command, _ = environment(monkeypatch, contract, before["implementation_sha256"])
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": "wrong"})
    with compatibility.collect_implementation_compatibility() as evidence:
        with pytest.raises(CommandContractError) as error:
            contract.validate_environment(command)
        assert error.value.code == "runtime_mismatch"
    assert len(evidence["transitions"]) == 1
    assert evidence["transitions"][0]["engine_id"] == contract.ENGINE_ID
