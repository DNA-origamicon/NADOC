"""Independent spawned replay is the batch oracle, not its recovery snapshots."""

import pytest

from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_verification_capture import capture
from tests.test_part_registered_batch import prepare


@pytest.mark.parametrize("poison", [False, True])
def test_whole_mixed_history_replays_in_cold_worker_after_transport(poison):
    result = prepare()
    assert result["status"] == "ready", result
    candidate = Design.from_json(result["candidate"].to_json())
    expected_ids = [(entry.id, [child.id for child in getattr(entry, "children", [])]) for entry in candidate.feature_log]
    if poison:
        for entry in candidate.feature_log:
            if entry.feature_type == "snapshot":
                entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "not a saved design"
            elif entry.feature_type == "routing-cluster":
                entry.pre_state_gz_b64 = entry.post_state_gz_b64 = "not a routing snapshot"
                for child in entry.children:
                    child.diff_added_b64 = child.diff_removed_b64 = child.diff_modified_b64 = "not a child diff"
    worker = VerificationWorker(capture(candidate))
    try:
        worker.start()
        assert worker.wait(5), "Small registered batch exceeded the existing verification worker allowance"
        proof = worker.result()
        assert proof["status"] == "verified", proof
        assert proof["checked_commands"] == 6
        assert proof["native_editable"] is True
    finally:
        worker.close()
    assert [(entry.id, [child.id for child in getattr(entry, "children", [])]) for entry in candidate.feature_log] == expected_ids
