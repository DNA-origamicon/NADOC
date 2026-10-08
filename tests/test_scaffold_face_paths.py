"""Free-face planning for a six-track trunk widened to ten tracks by Sweep."""

from backend.core.scaffold_face_paths import seamed_face_path, seamless_face_path


def _stepped_tracks():
    # Honeycomb 2×5 strip. The first three columns continue from bp 0; the
    # added two columns have true free low ends at bp 63. All end at bp 230.
    ids = [f"{row}:{col}" for row in range(2) for col in range(1, 6)]
    adj = {hid: set() for hid in ids}
    for row in range(2):
        for col in range(1, 5):
            a, b = f"{row}:{col}", f"{row}:{col + 1}"
            adj[a].add(b)
            adj[b].add(a)
    for col in (1, 3, 5):
        a, b = f"0:{col}", f"1:{col}"
        adj[a].add(b)
        adj[b].add(a)
    coverage = {
        hid: [{"lo": 0 if int(hid[-1]) <= 3 else 63, "hi": 230}]
        for hid in ids
    }
    forward = {hid: sum(map(int, hid.split(":"))) % 2 == 0 for hid in ids}
    return ids, adj, coverage, forward


def test_seamless_cycle_uses_only_actual_free_faces():
    ids, adj, coverage, forward = _stepped_tracks()
    path = seamless_face_path(ids, adj, coverage, forward)
    assert path is not None
    assert len(path) == len(ids) and set(path) == set(ids)
    turns = list(zip(path, path[1:] + path[:1]))
    # Traversal must cross the 6→10 width boundary at the shared high end;
    # there must be no U-turn at bp 63 on any of the six continuing tracks.
    assert any(coverage[a] != coverage[b] for a, b in turns)
    for a, b in turns:
        assert b in adj[a]
        face = "hi" if forward[a] else "lo"
        assert coverage[a][0][face] == coverage[b][0][face]


def test_seamed_pairs_share_both_free_faces():
    ids, adj, coverage, _ = _stepped_tracks()
    path = seamed_face_path(ids, adj, coverage)
    assert path is not None
    assert len(path) == len(ids) and set(path) == set(ids)
    assert all(b in adj[a] for a, b in zip(path, path[1:]))
    assert all(coverage[a] == coverage[b] for a, b in zip(path[::2], path[1::2]))
    assert any(coverage[a] != coverage[b] for a, b in zip(path[1::2], path[2::2]))


def test_lateral_cycle_does_not_authorize_turn_at_internal_boundary():
    ids = list("abcdef")
    adj = {hid: {ids[i - 1], ids[(i + 1) % 6]} for i, hid in enumerate(ids)}
    coverage = {hid: [{"lo": 0, "hi": 230}] for hid in ids}
    coverage["b"] = [{"lo": 63, "hi": 230}]
    forward = {hid: i % 2 == 0 for i, hid in enumerate(ids)}
    assert seamless_face_path(ids, adj, coverage, forward) is None
    assert seamed_face_path(ids, adj, coverage) is None
    # An explicitly open path may enter the shortened helix at its high face,
    # ending at its otherwise-unmatched low face.
    path = seamless_face_path(ids, adj, coverage, forward, close_cycle=False)
    assert path is not None and set(path) == set(ids)
    assert path[-1] == "b"


def test_search_is_deterministic_and_respects_visit_budget():
    ids, adj, coverage, forward = _stepped_tracks()
    path = seamless_face_path(ids, adj, coverage, forward)
    assert seamless_face_path(list(reversed(ids)), adj, coverage, forward) == path
    assert seamless_face_path(ids, adj, coverage, forward, max_visits=0) is None
    assert seamed_face_path(ids, adj, coverage, max_visits=0) is None


def test_segmented_tracks_are_left_for_section_router():
    ids, adj, coverage, forward = _stepped_tracks()
    coverage[ids[0]].append({"lo": 250, "hi": 280})
    assert seamless_face_path(ids, adj, coverage, forward) is None
    assert seamed_face_path(ids, adj, coverage) is None
