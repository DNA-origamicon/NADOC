"""Real numerical producer histories for the future owned transform worker.

Every topology/owner/joint input starts at a native empty root. These tests use
the existing spawned evaluation worker, not the short-lived preview service.
Measured wall times include worker startup, input replay and result transport;
they do not establish an interactive latency allowance or physical validity.
"""

import json
from multiprocessing.shared_memory import SharedMemory
from time import perf_counter
from uuid import UUID

import pytest

from backend.api import crud
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_proof_commands import dependencies, execute
from backend.core import models as m
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, command_rows
from backend.core.part_verification_capture import capture
from tests.test_part_deformation_preview import _append
from tests.test_part_transform_constraint_history import _overhang_prefix
from tests.test_part_transform_preview import FEATURE, snapshot


WORKER_CEILING_SECONDS = 180  # Existing evaluation ceiling, not a preview target.
STAMP = "2026-10-16T00:00:00Z"


def _seed(index):
    return str(UUID(int=12000 + index))


def native_cpd_prefix():
    """Two 12-bp helices and an actual placed crossover with authored TT extras."""
    source = snapshot(create_empty_part("Native CPD movement prefix", "HONEYCOMB"),
        "bundle-create", crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=12,
            ligate_adjacent=False, history_seed=_seed(1)).model_dump(mode="json"), "bundle")
    first, second = source.helices
    # Same ordinary placement/nick inputs as the qualified extra-base transform
    # fixture. The TT sequence is authored by its own native input command.
    request = crud.PlaceCrossoverRequest(crossover_id=_seed(2),
        half_a={"helix_id": first.id, "index": 7, "strand": "REVERSE"},
        half_b={"helix_id": second.id, "index": 7, "strand": "FORWARD"},
        nick_bp_a=7, nick_bp_b=6).model_dump(mode="json")
    source = snapshot(source, "crossover-place", request, "junction")
    source = snapshot(source, "crossover-extra-bases",
        {"crossover_id": request["crossover_id"], "sequence": "TT"}, "terminal-thymines")
    return source, {"base_keys": [f"__xb__:{request['crossover_id']}:{i}" for i in range(2)]}


def native_duplex_prefix():
    """Actual offered OH ends, native relocation/binding and a native joint row.

    The existing constraint fixture establishes the attachment polarity: left
    free-end to right root, with left driving. No imported or fabricated duplex
    graph substitutes for the real command output.
    """
    source, identities = _overhang_prefix()
    source = snapshot(source, "duplex-connect", {
        "history_seed": _seed(3), "duplex_id": "numerical-duplex", "created_at": 1.0,
        "binding_ids": [], "overhang_a_id": identities["driver"],
        "overhang_b_id": identities["driven"], "overhang_a_attach": "free_end",
        "overhang_b_attach": "root", "driver": "left",
    }, "duplex-connect")
    source = snapshot(source, "joint-place", {
        "cluster_id": identities["primary"], "joint_id": "numerical-driven-joint",
        "name": "Native driven arm", "local_axis_origin": [0, 0, 0],
        "local_axis_direction": [0, 1, 0], "min_angle_deg": -30, "max_angle_deg": 30,
    }, "driven-joint")
    return source, {**identities, "duplex_id": "numerical-duplex",
                    "joint_id": "numerical-driven-joint"}


def selected_transform(source, *, cluster_id=None):
    """Append the actual selected pose and one downstream ordinary extrusion."""
    owner = next((value for value in source.cluster_transforms
                  if value.id == cluster_id), None) if cluster_id is not None else source.cluster_transforms[0]
    assert owner is not None
    source = _append(source, m.ClusterOpLogEntry(id=FEATURE, cluster_id=owner.id,
        translation=[owner.translation[0] + .25, *owner.translation[1:]],
        rotation=list(owner.rotation), pivot=list(owner.pivot), proof_version=1,
        source="native-numerical-history"))
    return snapshot(source, "extrude-segment", {
        "cells": [[8, 8]], "length_bp": 3, "plane": "XY", "history_seed": _seed(4),
    }, "numerical-history-suffix")


def poison_recovery(source):
    """Keep exact inputs while making every legacy recovery shortcut unusable."""
    rows = []
    for original in source.feature_log:
        row = original.model_copy(deep=True)
        for name in ("design_snapshot_gz_b64", "post_state_gz_b64", "pre_state_gz_b64"):
            if name in type(row).model_fields:
                setattr(row, name, "not-decodable-recovery")
        if "evicted" in type(row).model_fields:
            row.evicted = True
        for child in getattr(row, "children", ()):
            for name in ("diff_added_b64", "diff_removed_b64", "diff_modified_b64"):
                if name in type(child).model_fields:
                    setattr(child, name, "not-decodable-diff")
        rows.append(row)
    return source.copy_with(feature_log=rows)


class _PhysicalOutput:
    def __deepcopy__(self, memo):
        raise AssertionError("Physical output entered numerical history capture")

    def __reduce__(self):
        raise AssertionError("Physical output entered numerical worker transport")


def run_worker(source, request, *, identity):
    """Existing bounded worker; returns its result and measured wall seconds."""
    owned = capture(source, preserve_entry_types=True)
    assert owned.atomistic_reference is None
    started = perf_counter()
    worker = EvaluationWorker(owned, {"request": request, "header": {
        "identity": identity, "timestamp": STAMP,
        "source_design_id": source.id, "source_revision": 7,
    }})
    return _finished_worker(worker), perf_counter() - started


def _finished_worker(worker):
    """Every direct worker owns and releases all of its bounded transport."""
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        assert worker.wait(WORKER_CEILING_SECONDS), "Existing numerical worker ceiling exceeded"
        result = worker.result()
    finally:
        worker.close()
        assert worker._closed and worker._process_closed and not worker.is_alive()
        for name in names:
            try:
                leaked = SharedMemory(name=name)
            except FileNotFoundError:
                continue
            leaked.close()
            leaked.unlink()
            pytest.fail("Numerical transform history worker leaked shared transport")
    return result


def _candidate(result):
    assert result["status"] == "ready", result
    raw = result["candidate"]
    value = m.Design.model_validate(raw)
    assert value.recipe_root.kind == "empty"
    assert value.atomistic_reference is None
    assert value.model_dump(mode="json", include=AUTHORING_FIELDS) == {
        name: raw[name] for name in AUTHORING_FIELDS}
    return value


def _record_timings(record_property, capsys, family, timings):
    text = json.dumps({"family": family, "worker_wall_seconds": timings}, sort_keys=True)
    record_property("numerical_history_timings", text)
    with capsys.disabled():
        print(f"\nnative-transform-numerical-history {text}", flush=True)


def transform_worker_roundtrip(source, monkeypatch, timings, *, identity, cluster_id=None):
    """Numerical prefix once, cheap selected-only drafts, full worker Apply.

    This is deliberately below host admission/publication: no lease, live
    document, gesture, undo stack or end-to-end UI claim is made here.
    """
    from backend.api import part_deformation_preview as prefix_service
    from backend.api import part_transform_preview as transform
    from backend.api import part_transform_preview_worker as numerical
    from backend.core import cpd_design, direct_relax, part_history_proof

    candidate = poison_recovery(selected_transform(source, cluster_id=cluster_id))
    # This is a genuine saved native recipe, not a current-model fixture. Its
    # recovery bodies are unusable before worker Prepare as well as cold proof.
    restored = m.Design.from_json(candidate.to_json())
    assert restored == candidate
    physical = _PhysicalOutput()
    restored.atomistic_reference = physical
    before = restored.model_dump(mode="json", include=AUTHORING_FIELDS)
    rows_before = list(command_rows(restored, 64))
    captured = capture(restored, preserve_entry_types=True)
    assert captured.atomistic_reference is None
    captured_before = captured.model_dump(mode="json")

    started = perf_counter()
    result = _finished_worker(numerical.TransformPreviewWorker(captured, FEATURE))
    timings["transform_prepare"] = perf_counter() - started
    assert result["status"] == "prepared", result
    prepared = numerical.decode_prepared(captured, FEATURE, result)
    original = prepared._entry.model_dump(mode="json")
    prefix_before = prepared.copy_prefix().model_dump(mode="json")
    selected = next(row for row in restored.feature_log if row.id == FEATURE)
    patch = {"translation": [selected.translation[0] + .75, *selected.translation[1:]]}
    calls = []
    execute_selected = prefix_service.execute

    def only_selected(kind, design, params):
        calls.append(kind)
        assert kind == "cluster_op", "Slider replayed a prefix or suffix command"
        return execute_selected(kind, design, params)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Selected-only evaluation attempted numerical work, replay or full proof")

    with monkeypatch.context() as guards:
        guards.setattr(prefix_service, "execute", only_selected)
        guards.setattr(prefix_service, "_replay_prefix", forbidden)
        guards.setattr(transform, "_replay_prefix", forbidden)
        guards.setattr(numerical, "execute_long", forbidden)
        guards.setattr(numerical, "prepare_change", forbidden)
        guards.setattr(part_history_proof, "assess", forbidden)
        guards.setattr(cpd_design, "convert_extra_pair", forbidden)
        guards.setattr(cpd_design, "relax_existing_cpd", forbidden)
        guards.setattr(direct_relax, "relax_direct_binding", forbidden)
        durations = []
        for index, draft in enumerate(({}, patch, patch)):
            started = perf_counter()
            evaluated = transform.evaluate(prepared, draft)
            durations.append(perf_counter() - started)
            assert evaluated.entry.id == FEATURE
            assert not evaluated.source_equivalence_checked and not evaluated.downstream_evaluated
            assert len(evaluated.design.helices) == len(source.helices)
            assert evaluated.design.photoproduct_junctions == source.photoproduct_junctions
            assert evaluated.design.nucleotide_transforms == source.nucleotide_transforms
            assert evaluated.design.overhangs == source.overhangs
            actual_owner = next(owner for owner in evaluated.design.cluster_transforms
                                if owner.id == selected.cluster_id)
            assert actual_owner.translation == (patch["translation"] if draft else selected.translation)
            if index == 0:
                # A returned candidate may be discarded/mutated by its owner;
                # subsequent evaluations must still start from the same prefix.
                evaluated.design.cluster_transforms.clear()
        timings["selected_evaluations"] = durations
    assert calls == ["cluster_op"] * 3
    assert prepared.copy_prefix().model_dump(mode="json") == prefix_before
    assert prepared._entry.model_dump(mode="json") == original

    started = perf_counter()
    result = _finished_worker(numerical.TransformPreviewWorker(captured, FEATURE, params=patch))
    timings["transform_apply"] = perf_counter() - started
    assert result["status"] == "ready", result
    applied = numerical.decode_applied(captured, FEATURE, result, params=patch)
    assert applied.recipe_root.kind == "empty" and applied.atomistic_reference is None
    assert captured.model_dump(mode="json") == captured_before
    rows_after = list(command_rows(applied, 64))
    assert [(identity, kind) for identity, kind, _ in rows_after] == [
        (identity, kind) for identity, kind, _ in rows_before]
    for (row_id, _kind, old), (_identity, _kind_after, new) in zip(rows_before, rows_after, strict=True):
        assert new == ({**old, **patch} if row_id == FEATURE else old)
    assert len(applied.helices) == len(restored.helices) == len(source.helices) + 1
    assert next(owner for owner in applied.cluster_transforms
                if owner.id == selected.cluster_id).translation == patch["translation"]
    applied = poison_recovery(applied)
    saved = m.Design.from_json(applied.to_json())
    assert saved == applied
    saved.atomistic_reference = physical
    proof, timings["edited_suffix_cold_proof"] = run_worker(
        saved, {"operation": "verify"}, identity=identity)
    assert proof["status"] == "verified" and proof["native_editable"], proof
    assert proof["checked_commands"] == len(rows_after)
    assert "physical" in proof["excluded_roles"]
    assert restored.model_dump(mode="json", include=AUTHORING_FIELDS) == before
    assert restored.atomistic_reference is saved.atomistic_reference is physical
    return applied


@pytest.mark.parametrize("factory", [native_cpd_prefix, native_duplex_prefix], ids=["cpd", "duplex"])
def test_numerical_source_is_a_complete_native_recipe_before_any_solver(factory):
    source, _ = factory()
    assert source.recipe_root.kind == "empty" and source.recipe_root.source_json is None
    assert not source.input_sources
    proof = assess_part_history(source, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified" and proof["native_editable"], proof
    kinds = [kind for _, kind, _ in command_rows(source, 64)]
    if factory is native_cpd_prefix:
        assert kinds == ["bundle-create", "crossover-place", "crossover-extra-bases"]
        assert source.crossovers[0].extra_bases == "TT"
    else:
        assert kinds.count("overhang-extrude") == 2
        assert kinds[-2:] == ["duplex-connect", "joint-place"]
        # Direct duplex relocation owns its prior topology; no legacy
        # OverhangBinding row is required by this native connection workflow.
        assert source.duplexes[0].bound and source.duplexes[0].prior_driven_topology


@pytest.mark.slow
def test_spawned_native_empty_root_cpd_create_relax_and_transform_cold_proof(
        monkeypatch, record_property, capsys):
    from backend.core import part_cpd_contract as contract

    source, identities = native_cpd_prefix()
    before = source.model_dump(mode="json", include=AUTHORING_FIELDS)
    physical = _PhysicalOutput()
    source.atomistic_reference = physical
    monkeypatch.setattr(contract, "runtime_fingerprint",
        lambda: pytest.fail("Parent authored or validated the CPD runtime pin"))
    timings = {}
    try:
        result, timings["create_append"] = run_worker(source, {
            "operation": "append", "kind": "photoproduct-create",
            "params": {"source": {"kind": "native"}, **identities},
        }, identity=_seed(10))
        converted = _candidate(result)
        assert len(converted.photoproduct_junctions) == 1 and len(converted.nucleotide_transforms) == 2
        entry = converted.feature_log[-1]
        assert entry.params["source"] == {"kind": "native"}
        assert entry.params["base_keys"] == identities["base_keys"]
        assert entry.params["engine"]["id"] == contract.ENGINE_ID
        assert entry.params["template"]["sha256"] == contract.TEMPLATE_SHA256
        converted = poison_recovery(converted)
        converted.atomistic_reference = physical
        result, timings["relax_append"] = run_worker(converted, {
            "operation": "append", "kind": "photoproduct-relax",
            "params": {"source": {"kind": "native"},
                       "photoproduct_id": converted.photoproduct_junctions[0].id},
        }, identity=_seed(11))
        relaxed = _candidate(result)
        assert [p.id for p in relaxed.photoproduct_junctions] == [p.id for p in converted.photoproduct_junctions]
        assert [p.id for p in relaxed.nucleotide_transforms] == [p.id for p in converted.nucleotide_transforms]
        applied = transform_worker_roundtrip(relaxed, monkeypatch, timings, identity=_seed(12))
        assert [row.id for row in applied.feature_log[-2:]] == [FEATURE, "numerical-history-suffix"]
        assert source.model_dump(mode="json", include=AUTHORING_FIELDS) == before
        assert source.atomistic_reference is converted.atomistic_reference is physical
    finally:
        _record_timings(record_property, capsys, "cpd", timings)


@pytest.mark.slow
def test_spawned_native_empty_root_duplex_relax_and_transform_cold_proof(
        monkeypatch, record_property, capsys):
    from backend.core import part_duplex_relax_contract as contract

    source, identities = native_duplex_prefix()
    before = source.model_dump(mode="json", include=AUTHORING_FIELDS)
    physical = _PhysicalOutput()
    source.atomistic_reference = physical
    monkeypatch.setattr(contract, "runtime_fingerprint",
        lambda: pytest.fail("Parent authored or validated the duplex runtime pin"))
    timings = {}
    try:
        result, timings["relax_append"] = run_worker(source, {
            "operation": "append", "kind": "duplex-relax",
            "params": {"source": {"kind": "native"}, "duplex_id": identities["duplex_id"]},
        }, identity=_seed(20))
        relaxed = _candidate(result)
        entry = relaxed.feature_log[-1]
        assert entry.params["engine"]["id"] == contract.ENGINE_ID
        assert entry.params["source"] == {"kind": "native"}
        assert entry.params["driver_overhang_id"] == identities["driver"]
        assert entry.params["driven_overhang_id"] == identities["driven"]
        assert entry.params["joint_ids"] == [identities["joint_id"]]
        assert entry.params["driver_cluster_id"] == identities["fixed"]
        assert entry.params["driven_cluster_id"] == identities["primary"]
        assert len(relaxed.feature_log) == len(source.feature_log) + 1
        assert [p.id for p in relaxed.cluster_transforms] == [p.id for p in source.cluster_transforms]
        assert [p.id for p in relaxed.overhangs] == [p.id for p in source.overhangs]
        applied = transform_worker_roundtrip(relaxed, monkeypatch, timings,
            identity=_seed(21), cluster_id=identities["primary"])
        assert [row.id for row in applied.feature_log[-2:]] == [FEATURE, "numerical-history-suffix"]
        assert source.model_dump(mode="json", include=AUTHORING_FIELDS) == before
        assert source.atomistic_reference is physical
    finally:
        _record_timings(record_property, capsys, "duplex", timings)
