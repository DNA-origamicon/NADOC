"""Original-byte recovery workers return exact downloadable text, not Designs."""

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from multiprocessing.shared_memory import SharedMemory
import pickle
import struct
from types import SimpleNamespace

import pytest

from backend.api import part_evaluation_worker, part_verification_worker


def module():
    return importlib.import_module("backend.api.part_recipe_file_worker")


def operation(kind="inspect"):
    if kind == "inspect":
        return {"version": 1, "operation": "inspect"}
    return {"version": 1, "operation": "recover", "request": {
        "version": 1, "expected_source_sha256": sha256(b"original").hexdigest(),
        "actions": [{"action": "upgrade_cluster_creation", "feature_id": "group-feature",
                     "child_id": None, "expected_version": 1, "expected_cluster_id": "group",
                     "expected_definition_sha256": "a" * 64}]}}


def receipt(raw=b"original"):
    return {"source_sha256": sha256(raw).hexdigest(), "source_size_bytes": len(raw),
            "source_design_id": "original", "old_state_verified": False,
            "basis": "saved_recipe_inputs", "excluded_fields": ["helices"],
            "stripped_recovery_field_count": 0}


def ready(raw=b"original"):
    return {"status": "ready", "issues": [], "candidate": {
        "id": "recovered", "finite_float": 12.0, "finite_integer": 12, "name": "Recovery α"},
        "proof": {"status": "verified"}, "validation": {"passed": True},
        "recovery": {**receipt(raw), "recovered_design_id": "recovered"}, "repair": {"complete": True}}


class ObservedMapping:
    def __init__(self, mapping):
        self.mapping = mapping
        self.closed = False

    @property
    def buf(self):
        return self.mapping.buf

    @property
    def size(self):
        return self.mapping.size

    def close(self):
        self.mapping.close()
        self.closed = True


@contextmanager
def shared_buffers(monkeypatch, payload):
    worker = module()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        monkeypatch.setenv(name, "1")  # restore parent environment after in-process child execution
    source = SharedMemory(create=True, size=len(payload) + 8)
    output = None
    mappings = {"input": [], "output": []}
    try:
        source.buf[:len(payload)] = payload
        output = SharedMemory(create=True, size=worker.MAX_RESULT_BYTES + worker.RESULT_HEADER_BYTES)

        def attach(*, name):
            role = "input" if name == source.name else "output" if name == output.name else None
            assert role is not None
            child = ObservedMapping(SharedMemory(name=name))
            mappings[role].append(child)
            return child

        with monkeypatch.context() as patch:
            patch.setattr(worker, "SharedMemory", attach)
            yield SimpleNamespace(source=source, output=output, mappings=mappings, size=len(payload))
    finally:
        try:
            for group in mappings.values():
                for child in group:
                    if not child.closed:
                        child.close()
        finally:
            source.close()
            source.unlink()
            if output is not None:
                output.close()
                output.unlink()


def read_result(buffers):
    size = struct.unpack_from("!I", buffers.output.buf, 0)[0]
    assert 0 < size <= module().MAX_RESULT_BYTES
    return json.loads(bytes(buffers.output.buf[4:4 + size]))


def test_operations_are_closed_strict_and_independently_owned():
    raw = operation("recover")
    parsed = module().parse_operation(raw)
    assert parsed == raw and parsed is not raw
    parsed["request"]["actions"][0]["expected_cluster_id"] = "changed"
    assert raw["request"]["actions"][0]["expected_cluster_id"] == "group"
    assert module().parse_operation(operation()) == operation()


@pytest.mark.parametrize("raw", [
    {"operation": "inspect"}, {"version": True, "operation": "inspect"},
    {"version": 1.0, "operation": "inspect"}, {"version": 2, "operation": "inspect"},
    {"version": 1, "operation": "inspect", "request": {}},
    {"version": 1, "operation": "recover"}, {"version": 1, "operation": "verify"},
    {"version": 1, "operation": "inspect", "candidate": {}},
], ids=["version-missing", "bool", "float", "future", "inspect-request", "recover-request", "unknown", "candidate"])
def test_unreviewed_operations_refuse_before_shared_memory(raw, monkeypatch):
    monkeypatch.setattr(part_verification_worker, "SharedMemory", lambda **_k: pytest.fail("Allocated rejected operation"))
    with pytest.raises(ValueError):
        module().RecipeFileWorker(b"original", raw)


def test_constructor_checks_raw_and_combined_pickle_bounds_before_allocation(monkeypatch):
    monkeypatch.setattr(part_verification_worker, "SharedMemory", lambda **_k: pytest.fail("Allocated rejected input"))
    with pytest.raises(ValueError):
        module().RecipeFileWorker(bytearray(b"original"), operation())
    with pytest.raises(ValueError):
        module().RecipeFileWorker(b"x" * (module().MAX_FILE_BYTES + 1), operation())
    monkeypatch.setattr(part_verification_worker, "MAX_INPUT_BYTES", 32)
    with pytest.raises(part_verification_worker.WorkerLimit):
        module().RecipeFileWorker(b"original", operation())


def test_parent_constructor_passes_only_raw_bytes_and_strict_operation_to_shared_transport(monkeypatch):
    from backend.api import part_recipe_file_recovery
    from backend.core import part_recipe_file

    monkeypatch.setattr(part_recipe_file, "admit_recipe_file", lambda *_a, **_k: pytest.fail("Parent parsed file"))
    monkeypatch.setattr(part_recipe_file_recovery, "inspect_recipe_file", lambda *_a, **_k: pytest.fail("Parent inspected file"))
    received = []
    monkeypatch.setattr(part_verification_worker.VerificationWorker, "__init__",
                        lambda _self, value, **kwargs: received.append((value, kwargs)))
    module().RecipeFileWorker(b"original", operation())
    value, options = received[0]
    assert value == {"raw": b"original", "operation": operation()}
    assert options["_result_limit"] == 16_000_000


@pytest.mark.parametrize("kind", ["inspect", "recover"])
def test_child_input_mapping_closes_before_work_and_exact_original_bytes_survive_parent_mutation(monkeypatch, kind):
    worker = module()
    payload = pickle.dumps({"raw": b"original", "operation": operation(kind)})
    with shared_buffers(monkeypatch, payload) as buffers:
        def evaluate(raw, selected):
            assert buffers.mappings["input"] and buffers.mappings["input"][0].closed
            buffers.source.buf[:] = b"!" * buffers.source.size
            assert raw == b"original" and type(raw) is bytes and selected == operation(kind)
            return ready(raw) if kind == "recover" else {"status": "review", "issues": [], "recovery": receipt(raw), "upgrades": []}

        monkeypatch.setattr(worker, "evaluate_file", evaluate)
        worker._evaluate(buffers.source.name, buffers.size, buffers.output.name)
        result = read_result(buffers)
        assert result["status"] == ("ready" if kind == "recover" else "review")
        assert all(mapping.closed for group in buffers.mappings.values() for mapping in group)


def test_ready_output_is_exact_ascii_json_with_content_digest_and_no_candidate(monkeypatch):
    worker = module()
    original = ready()
    original_copy = deepcopy(original)
    payload = pickle.dumps({"raw": b"original", "operation": operation("recover")})
    with shared_buffers(monkeypatch, payload) as buffers:
        monkeypatch.setattr(worker, "evaluate_file", lambda *_: original)
        worker._evaluate(buffers.source.name, buffers.size, buffers.output.name)
        result = read_result(buffers)
    assert "candidate" not in result
    artifact = result.pop("recovered_file")
    exact = json.dumps(original["candidate"], separators=(",", ":"), allow_nan=False).encode("ascii")
    assert artifact == {"json_text": exact.decode("ascii"), "sha256": sha256(exact).hexdigest(), "size_bytes": len(exact)}
    assert '"finite_float":12.0' in artifact["json_text"]
    assert '"finite_integer":12' in artifact["json_text"]
    assert artifact["json_text"].isascii() and "\\u03b1" in artifact["json_text"]
    assert result == {key: value for key, value in original.items() if key != "candidate"}
    assert original == original_copy


def test_child_refuses_whole_escaped_envelope_overflow_not_just_candidate_size(monkeypatch):
    worker = module()
    monkeypatch.setattr(worker, "MAX_RESULT_BYTES", 1200)
    fake = ready()
    fake["candidate"] = {"id": "recovered", "text": '"' * 200}
    fake["proof"]["diagnostic"] = "x" * 450
    assert len(json.dumps(fake["candidate"]).encode()) < 1200
    payload = pickle.dumps({"raw": b"original", "operation": operation("recover")})
    with shared_buffers(monkeypatch, payload) as buffers:
        monkeypatch.setattr(worker, "evaluate_file", lambda *_: fake)
        worker._evaluate(buffers.source.name, buffers.size, buffers.output.name)
        result = read_result(buffers)
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "result_limit"
    assert "candidate" not in result and "recovered_file" not in result


@pytest.mark.parametrize("variant", ["pickle", "keys", "operation", "size", "bool-size"])
def test_malformed_internal_transport_refuses_and_closes_all_mappings(monkeypatch, variant):
    worker = module()
    request = {"raw": b"original", "operation": operation()}
    if variant == "keys":
        request["source"] = {}
    if variant == "operation":
        request["operation"] = {"version": 1, "operation": "unknown"}
    payload = b"not a pickle" if variant == "pickle" else pickle.dumps(request)
    with shared_buffers(monkeypatch, payload) as buffers:
        monkeypatch.setattr(worker, "evaluate_file", lambda *_: pytest.fail("Evaluated malformed transport"))
        size = buffers.source.size + 1 if variant == "size" else True if variant == "bool-size" else buffers.size
        worker._evaluate(buffers.source.name, size, buffers.output.name)
        result = read_result(buffers)
        assert all(mapping.closed for group in buffers.mappings.values() for mapping in group)
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "recovery_worker_error"


def test_evaluation_exception_has_no_file_and_closes_output(monkeypatch):
    worker = module()
    payload = pickle.dumps({"raw": b"original", "operation": operation()})
    with shared_buffers(monkeypatch, payload) as buffers:
        def fail(*_):
            raise RuntimeError("isolated evaluation failed")
        monkeypatch.setattr(worker, "evaluate_file", fail)
        worker._evaluate(buffers.source.name, buffers.size, buffers.output.name)
        result = read_result(buffers)
        assert all(mapping.closed for group in buffers.mappings.values() for mapping in group)
    assert result["status"] == "unverified" and "recovered_file" not in result


def test_input_close_failure_prevents_evaluation_and_parent_can_finish_cleanup(monkeypatch):
    worker = module()
    payload = pickle.dumps({"raw": b"original", "operation": operation()})
    with shared_buffers(monkeypatch, payload) as buffers:
        original_close = ObservedMapping.close
        failed = False

        def fail_once(mapping):
            nonlocal failed
            if mapping.mapping.name == buffers.source.name and not failed:
                failed = True
                raise BufferError("injected close failure")
            return original_close(mapping)

        monkeypatch.setattr(ObservedMapping, "close", fail_once)
        monkeypatch.setattr(worker, "evaluate_file", lambda *_: pytest.fail("Evaluated before input close"))
        worker._evaluate(buffers.source.name, buffers.size, buffers.output.name)
        result = read_result(buffers)
        assert failed and not buffers.mappings["input"][0].closed
        assert buffers.mappings["output"][0].closed
    assert result["status"] == "unverified"


def fake_reader(result, *, kind="recover"):
    worker = object.__new__(module().RecipeFileWorker)
    worker._source_sha256 = sha256(b"original").hexdigest()
    worker._source_size = len(b"original")
    worker._operation_kind = kind
    worker._read_result = lambda: result
    return worker


def downloadable():
    result = ready()
    raw = json.dumps(result.pop("candidate"), separators=(",", ":"), allow_nan=False).encode("ascii")
    result["recovered_file"] = {"json_text": raw.decode("ascii"), "sha256": sha256(raw).hexdigest(), "size_bytes": len(raw)}
    return result


@pytest.mark.parametrize("variant", ["candidate", "hash", "size", "bool-size", "text", "nonascii", "missing", "wrong-source", "status"])
def test_parent_refuses_malformed_or_unbound_results_without_parsing_design(variant, monkeypatch):
    from backend.core.models import Design

    result = downloadable()
    if variant == "candidate":
        result["candidate"] = {}
    elif variant == "hash":
        result["recovered_file"]["sha256"] = "0" * 64
    elif variant == "size":
        result["recovered_file"]["size_bytes"] += 1
    elif variant == "bool-size":
        result["recovered_file"]["size_bytes"] = True
    elif variant == "text":
        result["recovered_file"]["json_text"] = {}
    elif variant == "nonascii":
        result["recovered_file"]["json_text"] = "α"
    elif variant == "missing":
        del result["recovered_file"]
    elif variant == "wrong-source":
        result["recovery"]["source_sha256"] = "0" * 64
    else:
        result["status"] = "verified"
    monkeypatch.setattr(Design, "from_json", lambda *_a, **_k: pytest.fail("Parent parsed Design"))
    with pytest.raises(ValueError):
        fake_reader(result).result()


def test_review_and_failures_cannot_smuggle_file_or_candidate():
    for status in ("review", "failed", "unverified"):
        for field in ("candidate", "recovered_file"):
            value = {"status": status, "issues": [], "recovery": receipt(), field: {}}
            with pytest.raises(ValueError):
                fake_reader(value, kind="inspect").result()
    with pytest.raises(ValueError):
        fake_reader(downloadable(), kind="inspect").result()


def test_parent_returns_exact_download_without_reserializing_candidate(monkeypatch):
    result = downloadable()
    monkeypatch.setattr(json, "loads", lambda *_a, **_k: pytest.fail("Parsed download document"))
    assert fake_reader(result).result() is result


def test_response_bytes_validates_then_returns_exact_child_envelope_without_serializing(monkeypatch):
    result = downloadable()
    raw = json.dumps(result, ensure_ascii=True, indent=1).encode("ascii")
    worker = fake_reader(result)
    worker._output = SimpleNamespace(buf=struct.pack("!I", len(raw)) + raw)
    worker._result_limit = module().MAX_RESULT_BYTES
    monkeypatch.setattr(json, "dumps", lambda *_a, **_k: pytest.fail("Reencoded child response"))
    assert worker.response_bytes() == raw
    result["recovered_file"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        worker.response_bytes()


def test_shared_native_thread_context_wraps_both_existing_and_recovery_evaluators(monkeypatch):
    import threadpoolctl
    from backend.api import part_evaluation, part_recipe_file_recovery

    actions = []

    @contextmanager
    def limited(*, limits):
        assert limits == 1
        actions.append("enter")
        try:
            yield
        finally:
            actions.append("exit")

    monkeypatch.setattr(part_evaluation_worker, "import_module", lambda name: actions.append(name))
    monkeypatch.setattr(threadpoolctl, "threadpool_limits", limited)
    monkeypatch.setattr(part_evaluation, "evaluate", lambda *_: actions.append("old") or {"old": True})
    monkeypatch.setattr(part_recipe_file_recovery, "inspect_recipe_file", lambda *_: actions.append("file") or {"file": True})
    assert part_evaluation_worker.evaluate_native("source", "operation") == {"old": True}
    assert module().evaluate_file(b"original", operation()) == {"file": True}
    expected_imports = ["numpy", "scipy.linalg", "scipy.optimize", "scipy.spatial.transform",
                        "scipy.spatial.distance", "scipy.interpolate"]
    assert actions == [*expected_imports, "enter", "old", "exit", *expected_imports, "enter", "file", "exit"]


@pytest.mark.parametrize("kind", ["inspect", "recover"])
def test_real_spawned_worker_inspects_or_recovers_tiny_native_recipe_and_unlinks_buffers(kind):
    from backend.core.models import Design
    from tests.test_part_recipe_file_recovery import group_actions, request, saved
    from tests.test_part_structure_proof import assess

    source, raw = saved()
    chosen = {"version": 1, "operation": kind}
    if kind == "recover":
        chosen["request"] = request(raw, group_actions(source))
    worker = module().RecipeFileWorker(raw, chosen)
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        assert worker.wait(15), "Tiny isolated recovery did not complete"
        result = worker.result()
        assert result["recovery"]["source_sha256"] == sha256(raw).hexdigest()
        assert "candidate" not in result
        if kind == "inspect":
            assert result["status"] == "review" and result["upgrades"]
        else:
            assert result["status"] == "ready", result
            artifact = result["recovered_file"]
            restored = Design.from_json(artifact["json_text"])
            assert restored.id != source.id
            assert restored.feature_log[1].proof_version == 2
            assert assess(restored)["status"] == "verified"
            assert artifact["sha256"] == sha256(artifact["json_text"].encode("ascii")).hexdigest()
    finally:
        worker.close()
        for name in names:
            try:
                leaked = SharedMemory(name=name)
            except FileNotFoundError:
                continue
            try:
                pytest.fail("Recovery worker left a shared-memory allocation")
            finally:
                leaked.close()
                leaked.unlink()
    assert not worker.is_alive()
