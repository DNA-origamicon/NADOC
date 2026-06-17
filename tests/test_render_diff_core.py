"""Direct unit tests for the render fast-path diff kernel.

These pin the pure Design×Design comparison functions service-pushed out of
crud.py into ``backend/core/render_diff.py`` (carve-up #47). They import
DIRECTLY from the core module (not via crud's re-export) so they assert the
core module's own input→output behavior — the earned pin for the moved code.
"""

from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Helix,
)
from backend.core.render_diff import (
    _cluster_diff_payload,
    _diff_is_cluster_only,
    _topology_diff_field,
    _topology_unchanged,
)


def _ct(cid="c0", *, translation=None, rotation=None, pivot=None,
        helix_ids=("h0",), name="Cluster", is_default=False, domain_ids=()):
    return ClusterRigidTransform(
        id=cid,
        name=name,
        is_default=is_default,
        helix_ids=list(helix_ids),
        domain_ids=list(domain_ids),
        translation=list(translation or [0.0, 0.0, 0.0]),
        rotation=list(rotation or [0.0, 0.0, 0.0, 1.0]),
        pivot=list(pivot or [0.0, 0.0, 0.0]),
    )


def _design(*, clusters=None, helices=None):
    d = Design()
    if clusters is not None:
        d.cluster_transforms = clusters
    if helices is not None:
        d.helices = helices
    return d


# ── _diff_is_cluster_only ────────────────────────────────────────────────

def test_cluster_only_true_when_translation_changes():
    prev = _design(clusters=[_ct(translation=[0, 0, 0])])
    new = _design(clusters=[_ct(translation=[5, 0, 0])])
    assert _diff_is_cluster_only(prev, new) is True


def test_cluster_only_false_when_nothing_changed():
    # Identical cluster transforms → let the regular path handle it.
    prev = _design(clusters=[_ct()])
    new = _design(clusters=[_ct()])
    assert _diff_is_cluster_only(prev, new) is False


def test_cluster_only_false_when_structural_field_differs():
    prev = _design(clusters=[_ct(translation=[0, 0, 0])], helices=[])
    h = Helix(
        id="h0", length_bp=8, bp_start=0,
        axis_start={"x": 0, "y": 0, "z": 0},
        axis_end={"x": 0, "y": 0, "z": 8},
        phase_offset=0.0,
    )
    new = _design(clusters=[_ct(translation=[5, 0, 0])], helices=[h])
    assert _diff_is_cluster_only(prev, new) is False


def test_cluster_only_false_when_cluster_added():
    prev = _design(clusters=[_ct("c0")])
    new = _design(clusters=[_ct("c0", translation=[1, 0, 0]), _ct("c1")])
    assert _diff_is_cluster_only(prev, new) is False


def test_cluster_only_false_when_pivot_changes():
    # Pivot change is excluded — the frontend delta math requires equal pivots.
    prev = _design(clusters=[_ct(pivot=[0, 0, 0])])
    new = _design(clusters=[_ct(pivot=[1, 0, 0])])
    assert _diff_is_cluster_only(prev, new) is False


# ── _cluster_diff_payload ────────────────────────────────────────────────

def test_cluster_diff_payload_emits_changed_cluster():
    prev = _design(clusters=[_ct("c0", translation=[0, 0, 0])])
    new = _design(clusters=[_ct("c0", translation=[5, 0, 0])])
    payload = _cluster_diff_payload(prev, new)
    assert len(payload) == 1
    rec = payload[0]
    assert rec["cluster_id"] == "c0"
    assert rec["old_translation"] == [0.0, 0.0, 0.0]
    assert rec["new_translation"] == [5.0, 0.0, 0.0]
    assert rec["helix_ids"] == ["h0"]


def test_cluster_diff_payload_skips_unchanged_cluster():
    prev = _design(clusters=[_ct("c0"), _ct("c1", translation=[0, 0, 0])])
    new = _design(clusters=[_ct("c0"), _ct("c1", translation=[2, 0, 0])])
    payload = _cluster_diff_payload(prev, new)
    assert [r["cluster_id"] for r in payload] == ["c1"]


def test_cluster_diff_payload_skips_newly_added_cluster():
    # A cluster with no prev counterpart is skipped (caller guarantees cluster-only).
    prev = _design(clusters=[_ct("c0")])
    new = _design(clusters=[_ct("c0", translation=[1, 0, 0]), _ct("c1")])
    payload = _cluster_diff_payload(prev, new)
    assert [r["cluster_id"] for r in payload] == ["c0"]


# ── _topology_diff_field / _topology_unchanged ───────────────────────────

def test_topology_unchanged_for_identical_designs():
    d = _design()
    assert _topology_diff_field(d, d) is None
    assert _topology_unchanged(d, d) is True


def test_topology_unchanged_allows_cluster_transform_diff():
    prev = _design(clusters=[_ct(translation=[0, 0, 0])])
    new = _design(clusters=[_ct(translation=[9, 0, 0])])
    # Cluster transforms are NOT a topology field → positions-only path stays open.
    assert _topology_diff_field(prev, new) is None
    assert _topology_unchanged(prev, new) is True


def test_topology_diff_field_names_helices():
    prev = _design(helices=[])
    h = Helix(
        id="h0", length_bp=8, bp_start=0,
        axis_start={"x": 0, "y": 0, "z": 0},
        axis_end={"x": 0, "y": 0, "z": 8},
        phase_offset=0.0,
    )
    new = _design(helices=[h])
    assert _topology_diff_field(prev, new) == "helices"
    assert _topology_unchanged(prev, new) is False


def test_topology_diff_field_names_flexible_segment_marks():
    prev = _design()
    new = _design()
    new.flexible_segment_marks = [{"helix_id": "h0", "start_bp": 0, "end_bp": 4}]
    assert _topology_diff_field(prev, new) == "flexible_segment_marks"
