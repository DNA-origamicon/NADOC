"""Which DCD frames the NAMD composite trajectory keeps — the "View trajectory"
frame-interval control.

``_composite_indices`` is the ONE place that decides this.  ``md_composite_meta`` and
``md_composite_trajectory`` used to carry separate copies of the arithmetic; any drift
between them desyncs the slider from the frames it scrubs.  Pure index math, no
MDAnalysis and no on-disk job fixture, so unlike the rest of test_md_trajectory.py
these run in the fast suite.
"""
from __future__ import annotations

import pytest


def _legacy_indices(seg_counts, max_frames=200):
    """The pre-interval selection, transcribed from md_composite_trajectory as it was
    before ``stride`` existed.  The compat pin: omitting an interval must keep picking
    exactly these frames, because the animation panel's trajectory keyframes and
    blade_runner still ride that path."""
    from backend.core.md_trajectory import _stride_pick

    total = sum(seg_counts)
    out, offset = [], 0
    for count in seg_counts:
        if count <= 0:
            out.append([])
            continue
        gi = list(range(offset, offset + count))
        keep = max(1, round(count * max_frames / total)) if total > max_frames else count
        out.append(_stride_pick(gi, keep))
        offset += count
    return out


@pytest.mark.parametrize("counts", [
    [10], [0], [0, 5], [100, 100], [1, 1, 1], [500, 3, 2000],
    [199], [200], [201], [1, 199, 1], [7, 0, 0, 13], [1000, 1000, 1000],
])
def test_without_stride_matches_the_legacy_budget(counts):
    from backend.core.md_trajectory import _composite_indices
    assert _composite_indices(counts, 200, None) == _legacy_indices(counts, 200)


def test_strides_each_segment_independently():
    """A frame INTERVAL takes every Nth frame OF EACH SEGMENT (what VMD's DCD stride
    does to each loaded file), not every Nth frame of the concatenation — so a short
    segment can't be phase-skipped by a long neighbour."""
    from backend.core.md_trajectory import _composite_indices

    picked = _composite_indices([10, 7], 200, 3)
    assert picked == [[0, 3, 6, 9], [10, 13, 16]]     # 2nd segment restarts at its own frame 0


def test_interval_one_keeps_every_frame():
    from backend.core.md_trajectory import _composite_indices
    assert _composite_indices([4, 3], 200, 1) == [[0, 1, 2, 3], [4, 5, 6]]


def test_interval_ignores_the_max_frames_budget():
    """An interval is an absolute density, not a fraction — a long run must be allowed
    to exceed the legacy 200-frame cap.  That is the whole point of the control."""
    from backend.core.md_trajectory import _composite_indices

    picked = _composite_indices([10_000], 200, 20)
    assert len(picked[0]) == 500 > 200


def test_short_segment_still_contributes_one_frame():
    """Every non-empty segment keeps at least its own frame 0, so the boundary marker
    the slider draws for it points at a frame that exists."""
    from backend.core.md_trajectory import _composite_indices

    picked = _composite_indices([100, 3], 200, 50)
    assert picked[0] == [0, 50]
    assert picked[1] == [100]


def test_empty_segments_do_not_shift_later_offsets():
    """A segment with no written frames contributes nothing but must not consume index
    space — a later segment's global indices still have to point at its real frames."""
    from backend.core.md_trajectory import _composite_indices

    assert _composite_indices([2, 0, 5], 200, 4) == [[0], [], [2, 6]]


def test_composite_trajectory_positional_order_matches_the_route_tuple():
    """``GET /md/jobs/{id}/trajectory`` hands its arguments to the analysis SUBPROCESS
    as a positional tuple ``(psf, segments, ref, design, 200, stride)`` — there are no
    keywords to bind by name.  Reordering md_composite_trajectory's parameters would
    silently pass the interval as ``max_frames`` (and vice versa), which looks like a
    working request and returns the wrong frames."""
    import inspect
    from backend.core.md_trajectory import md_composite_trajectory

    params = list(inspect.signature(md_composite_trajectory).parameters)
    assert params[:6] == ["topology_path", "segments", "coordinate_path", "design",
                          "max_frames", "stride"]


@pytest.mark.parametrize("raw,expected", [
    (None, None), (0, None), (-3, None), ("x", None), ("", None),
    (1, 1), (20, 20), ("20", 20), (2.9, 2),
])
def test_route_normalizes_the_stride_query_param(raw, expected):
    """`?stride=` must land on None for anything unusable — None is what selects the
    legacy at-most-200-frames budget, the path the animation panel's trajectory
    keyframes still ride, so a junk value must not pick some third downsample."""
    from backend.api.routes_md import _traj_stride
    assert _traj_stride(raw) == expected


# ── Composite → raw translation (what the heavy reps address) ──────────────────
# The beads the user scrubs are downsampled; the per-frame atomistic/surface reps
# re-render "the same frame" from the raw universe.  Without this translation the
# atomistic view sits on a different point in the run than the beads beside it, which
# is invisible unless you compare them.

def _raw_map(counts, max_frames=200, stride=None):
    """composite_raw_frame_map without the DCD headers (it only reads counts)."""
    from backend.core.md_trajectory import _composite_indices
    return [g for seg in _composite_indices(counts, max_frames, stride) for g in seg]


def test_raw_map_is_identity_only_while_nothing_was_dropped():
    # Under the cap, every frame is kept → composite index == raw index, which is
    # exactly why the missing translation went unnoticed on short runs.
    assert _raw_map([4, 3]) == [0, 1, 2, 3, 4, 5, 6]
    # Over the cap it is emphatically NOT the identity.
    big = _raw_map([1000])
    assert big[0] == 0 and big[-1] == 999
    assert big != list(range(len(big)))


def test_raw_map_addresses_the_frames_the_interval_actually_kept():
    counts = [10, 7]
    stride = 3
    raw = _raw_map(counts, stride=stride)
    assert raw == [0, 3, 6, 9, 10, 13, 16]
    # Composite index i must land on the i-th kept frame, per segment.
    assert raw[0] == 0 and raw[3] == 9      # last of segment 1
    assert raw[4] == 10                     # first of segment 2, not frame 12


def test_raw_map_length_matches_the_trajectory_frame_count():
    """The heavy fetchers reject out-of-range composite indices against this map, so a
    disagreement with the slider's length would silently drop the last frames."""
    from backend.core.md_trajectory import _composite_indices
    for counts, stride in ([[10, 7], 3], [[1000], None], [[100, 3], 50], [[4, 3], 1]):
        picked = _composite_indices(counts, 200, stride)
        assert len(_raw_map(counts, 200, stride)) == sum(len(p) for p in picked)


def test_heavy_frame_fetchers_take_the_same_stride_as_the_trajectory():
    """Both heavy fetchers are invoked positionally through the analysis subprocess, so
    their trailing (max_frames, stride) pair must line up with what routes_md sends."""
    import inspect
    from backend.core.md_trajectory import md_frames_atomistic, md_frames_surface

    atom = list(inspect.signature(md_frames_atomistic).parameters)
    assert atom[:7] == ["topology_path", "segments", "coordinate_path", "design",
                        "frame_indices", "max_frames", "stride"]
    surf = list(inspect.signature(md_frames_surface).parameters)
    assert surf[:10] == ["topology_path", "segments", "coordinate_path", "design",
                         "frame_indices", "probe_radius", "grid_spacing",
                         "radius_inflate", "smooth", "max_frames"]
    assert surf[10] == "stride"


def test_atomistic_model_and_positions_only_are_a_matched_pair():
    """The all-atom trajectory is only affordable because identity is fetched ONCE and
    frames carry coordinates alone.  Both halves are applied POSITIONALLY through the
    analysis subprocess, so their signatures are the contract."""
    import inspect
    from backend.core.md_trajectory import md_atomistic_model, md_frames_atomistic

    assert list(inspect.signature(md_atomistic_model).parameters) == [
        "topology_path", "segments", "coordinate_path", "design"]
    assert list(inspect.signature(md_frames_atomistic).parameters) == [
        "topology_path", "segments", "coordinate_path", "design",
        "frame_indices", "max_frames", "stride", "positions_only"]
