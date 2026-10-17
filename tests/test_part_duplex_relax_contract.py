"""Pinned relaxation admission and isolation without running the optimizer."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_duplex_commands as commands
from backend.core import part_duplex_relax_contract as contract
from backend.core.models import ClusterJoint, ClusterRigidTransform
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from tests.test_part_duplex_commands import SEED, connect_params, source


def connected(*, joints=True):
    original = source(rooted=True)
    original = original.copy_with(cluster_transforms=[
        ClusterRigidTransform(id="parent-a", helix_ids=["a", "root-a"]),
        ClusterRigidTransform(id="parent-b", helix_ids=["b", "root-b"]),
        ClusterRigidTransform(id="unrelated", helix_ids=[]),
    ])
    result = commands.build("duplex-connect", original, connect_params())
    # Match the ordinary recording postprocessor after relocation removes b.
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    result = reconcile_cluster_membership(original, result)
    if joints:
        result = result.copy_with(cluster_joints=[
            ClusterJoint(id="joint-b", cluster_id="parent-b", min_angle_deg=-60, max_angle_deg=60),
            ClusterJoint(id="unrelated-joint", cluster_id="unrelated"),
        ])
    return result


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 1})
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": 1})


def inputs():
    return {"source": {"kind": "native"}, "duplex_id": "duplex", "history_seed": SEED}


def test_prepare_captures_exact_selection_and_parser_never_refreshes_pins(environment, monkeypatch):
    design = connected()
    params = contract.prepare_command(design, inputs())
    assert params["joint_ids"] == ["joint-b"]
    assert params["driver_cluster_id"] == "parent-a"
    assert params["driven_cluster_id"] == "parent-b"
    assert params["duplex_cluster_id"] == next(c.id for c in design.cluster_transforms
                                                if c.overhang_duplex_driver_id == "oh-a")
    assert params["driver_overhang_id"] == "oh-a"
    assert params["driven_overhang_id"] == "oh-b"
    monkeypatch.setattr(contract, "contract_defaults", lambda: pytest.fail("Parser refreshed authored pins"))
    assert commands.parse_command("duplex-relax", params).model_dump(mode="json", by_alias=True) == params
    # Unrelated joints are not declared dependencies and can disappear freely.
    changed = design.copy_with(cluster_joints=[design.cluster_joints[0]])
    assert contract.validate_inputs(changed, params).joint_ids == ["joint-b"]


@pytest.mark.parametrize("changes", [
    {"source": {"kind": "reference"}}, {"history_seed": "bad"}, {"engine": {}},
    {"joint_ids": []}, {"rotation": [0, 0, 0, 1]}, {"target_nm": 0.7},
])
def test_prepare_rejects_caller_pins_selections_and_solved_output(environment, changes):
    with pytest.raises(ValidationError):
        contract.prepare_command(connected(), {**inputs(), **changes})


@pytest.mark.parametrize("changes", [
    {"_proof_version": True}, {"relaxation_version": True}, {"relaxation_version": 2},
    {"engine": {}}, {"joint_ids": ["joint-b", "joint-b"]}, {"sampled_geometry": []},
])
def test_complete_contract_is_strict_and_versioned(environment, changes):
    params = contract.prepare_command(connected(), inputs())
    with pytest.raises(ValidationError):
        contract.parse_command({**params, **changes})


@pytest.mark.parametrize("missing", ["duplex", "overhang", "joint", "cluster"])
def test_ordinary_executor_resolves_missing_inputs_without_solver_or_runtime(environment, monkeypatch, missing):
    from backend.api.part_proof_commands import execute

    design = connected()
    params = contract.prepare_command(design, inputs())
    monkeypatch.setattr(commands, "relax", lambda *_: pytest.fail("Ordinary execution reached relaxation"))
    monkeypatch.setattr(contract, "validate_environment", lambda *_: pytest.fail("Ordinary execution probed runtime"))
    with pytest.raises(CommandContractError) as caught:
        execute("duplex-relax", design, params)
    assert caught.value.code == "long_job_required"
    field, identity = {"duplex": ("duplexes", "duplex"), "overhang": ("overhangs", "oh-a"),
                       "joint": ("cluster_joints", "joint-b"), "cluster": ("cluster_transforms", "parent-b")}[missing]
    changed = design.copy_with(**{field: [item for item in getattr(design, field) if item.id != identity]})
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("duplex-relax", changed, params)
    assert caught.value.code == "missing_reference"
    assert caught.value.as_issue()["references"][0]["identity"] == identity


def test_changed_driver_or_joint_selection_requires_explicit_repair(environment):
    design = connected()
    params = contract.prepare_command(design, inputs())
    with pytest.raises(ReferenceResolutionError, match="driver relationship"):
        contract.validate_inputs(design.copy_with(duplexes=[design.duplexes[0].model_copy(update={"driver": "right"})]), params)
    added = ClusterJoint(id="new-selected-joint", cluster_id="parent-a")
    with pytest.raises(ReferenceResolutionError, match="selection no longer"):
        contract.validate_inputs(design.copy_with(cluster_joints=[*design.cluster_joints, added]), params)


@pytest.mark.parametrize("field", sorted(contract._BLOCKED_FIELDS))
def test_unsupported_geometry_families_fail_before_placement(field):
    design = connected()
    with pytest.raises(contract.DuplexRelaxContractError) as caught:
        contract.validate_source(design.copy_with(**{field: [object()]}))
    assert caught.value.code == "unsupported_source"
    assert field in caught.value.fields


def test_source_work_admission_counts_domains_and_repeated_emission():
    design = connected()
    assert contract.validate_source(design) < 100
    huge = design.model_copy(deep=True)
    huge.strands[0].domains[0].start_bp = 1_000_000
    with pytest.raises(contract.DuplexRelaxContractError) as caught:
        contract.validate_source(huge)
    assert caught.value.code == "source_limit"
    repeated = design.model_copy(deep=True)
    repeated.strands[0].domains *= 20_000
    with pytest.raises(contract.DuplexRelaxContractError) as caught:
        contract.validate_source(repeated)
    assert caught.value.code == "source_limit"


def test_engine_and_runtime_mismatch_precede_solver(environment, monkeypatch):
    from backend.core import direct_relax

    design = connected()
    params = contract.prepare_command(design, inputs())
    monkeypatch.setattr(direct_relax, "relax_direct_binding", lambda *_a, **_kw: pytest.fail("Mismatched engine ran solver"))
    monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 2})
    with pytest.raises(contract.DuplexRelaxContractError) as caught:
        commands.build("duplex-relax", design, params)
    assert caught.value.code == "engine_mismatch"
    monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 1})
    monkeypatch.setattr(contract, "runtime_fingerprint", lambda: {"runtime": 2})
    with pytest.raises(contract.DuplexRelaxContractError) as caught:
        commands.build("duplex-relax", design, params)
    assert caught.value.code == "runtime_mismatch"


def test_solver_receives_only_native_authoring_and_incidental_history_is_discarded(environment, monkeypatch):
    from backend.core import direct_relax

    design = connected()
    params = contract.prepare_command(design, inputs())
    physical, history = object(), object()
    design = design.copy_with(atomistic_reference=physical, feature_log=[history])
    before = deepcopy(design.model_dump(mode="json", include=contract.AUTHORING))

    def fake_solver(local, driver, driven, *, joint_ids):
        assert local.atomistic_reference is None and local.feature_log == []
        assert local.model_dump(mode="json", include=contract.AUTHORING) == before
        assert (driver, driven, joint_ids) == ("oh-a", "oh-b", ["joint-b"])
        changed = [item.model_copy(update={"translation": [1.0, 2.0, 3.0]}) if item.id == driver else item
                   for item in local.overhangs]
        return local.copy_with(overhangs=changed, feature_log=[object()]), {}

    monkeypatch.setattr(direct_relax, "relax_direct_binding", fake_solver)
    result = commands.build("duplex-relax", design, params)
    assert next(item for item in result.overhangs if item.id == "oh-a").translation == [1.0, 2.0, 3.0]
    assert result.feature_log == [history] and result.atomistic_reference is physical
    assert design.model_dump(mode="json", include=contract.AUTHORING) == before


@pytest.mark.parametrize("change", ["topology", "identity", "nan", "engine"])
def test_solver_output_and_post_solve_environment_guards_preserve_source(environment, monkeypatch, change):
    from backend.core import direct_relax

    design = connected()
    params = contract.prepare_command(design, inputs())
    original = design.model_dump_json()

    def faulty_solver(local, *_args, **_kwargs):
        if change == "topology":
            local.strands.reverse()  # Even an accidental in-place mutation stays isolated.
        elif change == "identity":
            local.overhangs[0].id = "replaced"
        elif change == "nan":
            local.overhangs[0].translation = [float("nan"), 0.0, 0.0]
        else:
            monkeypatch.setattr(contract, "implementation_manifest", lambda: {"implementation": 2})
        return local, {}

    monkeypatch.setattr(direct_relax, "relax_direct_binding", faulty_solver)
    with pytest.raises(contract.DuplexRelaxContractError) as caught:
        commands.build("duplex-relax", design, params)
    assert caught.value.code == ("engine_mismatch" if change == "engine" else "builder_output_mismatch")
    assert design.model_dump_json() == original


def test_shared_runtime_preserves_cpd_fingerprint_shape(monkeypatch):
    from backend.core import part_cpd_contract, part_numerical_runtime

    libraries = [{"user_api": "blas", "sha256": "library-pin"}]
    monkeypatch.setattr(part_cpd_contract, "_numerical_libraries", lambda: deepcopy(libraries))
    assert part_cpd_contract.runtime_fingerprint() == part_numerical_runtime.runtime_fingerprint(libraries=libraries)
