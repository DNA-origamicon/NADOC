"""Independent process prevents other tests from warming a deferred serializer."""

import subprocess
import sys


def test_cold_design_decode_preserves_nested_dna_under_exact_serialization():
    script = """
from backend.core.models import Design
from backend.api.part_immutable_revision import _decoded_exact, _canonical_payload

# Construct through the outer validator only: strict recovery and worker byte
# transport must not depend on a prior direct Helix construction in this process.
design = Design.model_validate({
    "helices": [{"id": "cold-helix", "axis_start": {"x": 0, "y": 0, "z": 0},
        "axis_end": {"x": 0, "y": 0, "z": 2.38}, "length_bp": 8,
        "loop_skips": [{"bp_index": 2, "delta": 1}, {"bp_index": 5, "delta": -1}]}],
    "strands": [{"id": "cold-strand", "strand_type": "scaffold",
        "domains": [{"helix_id": "cold-helix", "start_bp": 0, "end_bp": 7,
                     "direction": "FORWARD"}]}],
})
expected = design.model_dump(mode="json", warnings="error")
payload = _canonical_payload(expected, lambda: None)
actual = _decoded_exact(payload, lambda: None).model_dump(mode="json", serialize_as_any=True, warnings="error")
assert actual == expected
restored = Design.model_validate_json(design.model_dump_json())
assert restored.model_dump(mode="json", serialize_as_any=True, warnings="error") == expected
assert actual["helices"][0]["loop_skips"] == [
    {"bp_index": 2, "delta": 1}, {"bp_index": 5, "delta": -1}]
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
