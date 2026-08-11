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
from backend.core.models import (
    Direction,
    Domain,
    OverhangConnection,
    Strand,
    StrandExtension,
    StrandType,
)
from backend.core.render_diff import (
    _cluster_diff_payload,
    _diff_is_cluster_only,
    _local_changed_helices,
    _strand_occupancy,
    _topology_diff_field,
    _topology_unchanged,
)


def _ct(
    cid="c0",
    *,
    translation=None,
    rotation=None,
    pivot=None,
    helix_ids=("h0",),
    name="Cluster",
    is_default=False,
    domain_ids=(),
):
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
        id="h0",
        length_bp=8,
        bp_start=0,
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
        id="h0",
        length_bp=8,
        bp_start=0,
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


# ── _strand_occupancy / _local_changed_helices ───────────────────────────


def _dom(
    helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD, overhang_id=None
):
    return Domain(
        helix_id=helix_id,
        start_bp=start_bp,
        end_bp=end_bp,
        direction=direction,
        overhang_id=overhang_id,
    )


def _strand(sid, domains, strand_type=StrandType.STAPLE):
    return Strand(id=sid, domains=domains, strand_type=strand_type)


def _occ_design(strands=(), extensions=(), connections=()):
    d = Design()
    d.strands = list(strands)
    d.extensions = list(extensions)
    d.overhang_connections = list(connections)
    return d


def test_occupancy_snapshot_survives_in_place_mutation():
    """The snapshot captures plain values, so mutating the design afterwards
    must not retroactively change the 'before' picture."""
    s = _strand("s0", [_dom(end_bp=7)])
    d = _occ_design([s])
    before = _strand_occupancy(d)
    s.domains[0].end_bp = 3  # in-place edit of the SAME object
    assert before["sig"]["s0"][1][0][2] == 7
    assert _strand_occupancy(d)["sig"]["s0"][1][0][2] == 3


def test_occupancy_tracks_helices_per_strand():
    d = _occ_design([_strand("s0", [_dom("h0"), _dom("h1")])])
    assert _strand_occupancy(d)["helices"]["s0"] == frozenset({"h0", "h1"})


def test_no_occupancy_change_returns_none():
    """An empty changed-list would trip the frontend's full-replacement branch
    and wipe the scene — the contract is None, not []."""
    d = _occ_design([_strand("s0", [_dom()])])
    snap = _strand_occupancy(d)
    assert _local_changed_helices(snap, snap) is None


def test_changed_strand_yields_its_helices():
    before = _strand_occupancy(_occ_design([_strand("s0", [_dom("h0")])]))
    after = _strand_occupancy(_occ_design([_strand("s0", [_dom("h0", end_bp=3)])]))
    assert _local_changed_helices(before, after) == ["h0"]


def test_split_unions_helices_from_both_snapshots():
    """A nick splits s0 (h0+h1) into s0 (h0) + s1 (h1). The fragment id s1 is
    new, and s0 loses h1 — both helices must be reshipped."""
    before = _strand_occupancy(_occ_design([_strand("s0", [_dom("h0"), _dom("h1")])]))
    after = _strand_occupancy(
        _occ_design(
            [
                _strand("s0", [_dom("h0")]),
                _strand("s1", [_dom("h1")]),
            ]
        )
    )
    assert sorted(_local_changed_helices(before, after)) == ["h0", "h1"]


def test_unchanged_strands_are_not_reshipped():
    keep = [_strand("keep", [_dom("h9")])]
    before = _strand_occupancy(_occ_design(keep + [_strand("s0", [_dom("h0")])]))
    after = _strand_occupancy(
        _occ_design(keep + [_strand("s0", [_dom("h0", end_bp=3)])])
    )
    assert _local_changed_helices(before, after) == ["h0"]


def test_strand_type_change_alone_counts_as_changed():
    before = _strand_occupancy(_occ_design([_strand("s0", [_dom("h0")])]))
    after = _strand_occupancy(
        _occ_design([_strand("s0", [_dom("h0")], strand_type=StrandType.SCAFFOLD)])
    )
    assert _local_changed_helices(before, after) == ["h0"]


def test_extension_change_forces_full_geometry():
    """Extensions are synthetic geometry the partial path never re-emits."""
    ext = StrandExtension(id="e0", strand_id="s1", end="three_prime", sequence="TTTT")
    before = _strand_occupancy(_occ_design([_strand("s0", [_dom("h0")])]))
    after = _strand_occupancy(
        _occ_design([_strand("s0", [_dom("h0", end_bp=3)])], extensions=[ext])
    )
    assert _local_changed_helices(before, after) is None


def test_changed_strand_carrying_extension_reships_its_synthetic_geometry():
    ext = StrandExtension(id="e0", strand_id="s0", end="three_prime", sequence="TTTT")
    before = _strand_occupancy(
        _occ_design([_strand("s0", [_dom("h0")])], extensions=[ext])
    )
    after = _strand_occupancy(
        _occ_design([_strand("s0", [_dom("h0", end_bp=3)])], extensions=[ext])
    )
    assert sorted(_local_changed_helices(before, after)) == ["__ext_e0", "h0"]


def test_ds_linker_connection_change_forces_full_geometry():
    conn = OverhangConnection(
        id="c0",
        overhang_a_id="oa",
        overhang_a_attach="free_end",
        overhang_b_id="ob",
        overhang_b_attach="free_end",
        linker_type="ds",
        length_value=8,
        length_unit="bp",
    )
    before = _strand_occupancy(_occ_design([_strand("s0", [_dom("h0")])]))
    after = _strand_occupancy(
        _occ_design([_strand("s0", [_dom("h0", end_bp=3)])], connections=[conn])
    )
    assert _local_changed_helices(before, after) is None
