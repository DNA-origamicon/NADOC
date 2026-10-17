"""Incoming recovery is bounded storage, never trustworthy construction input."""

import pytest

from backend.api.part_recovery_budget import retained_recovery_bytes
from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_verification_capture import CaptureLimit


def test_actual_payloads_and_children_count_without_trusting_size_metadata():
    child = MinorMutationLogEntry(op_subtype="helix-update", label="Edit helix", diff_added_b64="abc", diff_removed_b64="de")
    group = RoutingClusterLogEntry(label="Routing", children=[child], pre_state_gz_b64="broken")
    snapshot = SnapshotLogEntry(op_kind="nanoparticle-create", label="Create gold", design_snapshot_gz_b64="f",
                                post_state_gz_b64="gh", snapshot_size_bytes=0, post_state_size_bytes=10**9)
    assert retained_recovery_bytes([group, snapshot], max_rows=3, limit=14) == 14
    with pytest.raises(CaptureLimit, match="byte allowance"):
        retained_recovery_bytes([group, snapshot], max_rows=3, limit=13)
    with pytest.raises(CaptureLimit, match="row allowance"):
        retained_recovery_bytes([group, snapshot], max_rows=2)


@pytest.mark.parametrize("field", ["design_snapshot_gz_b64", "post_state_gz_b64"])
def test_non_ascii_corruption_is_conservatively_charged_but_not_decoded(field):
    row = SnapshotLogEntry(op_kind="nanoparticle-create", label="Create gold", **{field: "é☂"})
    assert retained_recovery_bytes([row], max_rows=1, limit=8) == 8
    with pytest.raises(CaptureLimit):
        retained_recovery_bytes([row], max_rows=1, limit=7)


def test_invalid_payload_refuses_without_copy_or_string_coercion():
    class Invalid:
        def __deepcopy__(self, _memo):
            pytest.fail("Copied invalid recovery")
        def __str__(self):
            pytest.fail("Coerced invalid recovery")

    row = SnapshotLogEntry(op_kind="nanoparticle-create", label="Create gold")
    row.post_state_gz_b64 = Invalid()
    with pytest.raises(CaptureLimit, match="encoded strings"):
        retained_recovery_bytes([row], max_rows=1)


def test_parent_count_refuses_before_visiting_unbounded_children():
    class Unvisited:
        @property
        def __dict__(self):
            pytest.fail("Visited excluded history")

    with pytest.raises(CaptureLimit, match="row allowance"):
        retained_recovery_bytes([Unvisited(), Unvisited()], max_rows=1)
