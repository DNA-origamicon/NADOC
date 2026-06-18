"""Tests for the pure instance-layout geometry (AF-10).

``backend.core.instance_layout`` turns a layout spec (grid / ring) into world
translations.  These pin the analytic formula in isolation (count, spacing,
centring, plane embedding, angular step); the *placed* result is pinned
separately by ``assert_instances_on_grid`` / ``assert_instances_on_ring``.
"""
from __future__ import annotations

import math

import pytest

from backend.core.instance_layout import grid_translations, ring_translations


# ── grid ──────────────────────────────────────────────────────────────────────

def test_grid_count_and_corner_at_origin():
    ts = grid_translations(2, 3, pitch=10.0)
    assert len(ts) == 6
    assert ts[0] == (0.0, 0.0, 0.0)  # slot (0,0) at origin
    # row-major: (0,0),(0,1),(0,2),(1,0),(1,1),(1,2)
    assert ts[1] == (10.0, 0.0, 0.0)   # col 1
    assert ts[3] == (0.0, 10.0, 0.0)   # row 1, col 0


def test_grid_distinct_row_and_col_pitch():
    ts = grid_translations(2, 2, pitch=10.0, row_pitch=4.0)
    xs = sorted({round(t[0], 6) for t in ts})
    ys = sorted({round(t[1], 6) for t in ts})
    assert xs == [0.0, 10.0]   # column pitch
    assert ys == [0.0, 4.0]    # row pitch


def test_grid_centered_mean_is_origin():
    ts = grid_translations(3, 3, pitch=5.0, center=True)
    mx = sum(t[0] for t in ts) / len(ts)
    my = sum(t[1] for t in ts) / len(ts)
    assert mx == pytest.approx(0.0)
    assert my == pytest.approx(0.0)


def test_grid_plane_embedding():
    assert grid_translations(1, 2, pitch=7.0, plane="XZ")[1] == (7.0, 0.0, 0.0)
    assert grid_translations(2, 1, pitch=7.0, plane="XZ")[1] == (0.0, 0.0, 7.0)
    assert grid_translations(2, 1, pitch=7.0, plane="YZ")[1] == (0.0, 0.0, 7.0)


@pytest.mark.parametrize("rows,cols,pitch", [(0, 2, 1.0), (2, 0, 1.0), (2, 2, 0.0), (2, 2, -1.0)])
def test_grid_rejects_non_positive(rows, cols, pitch):
    with pytest.raises(ValueError):
        grid_translations(rows, cols, pitch=pitch)


def test_grid_rejects_bad_plane():
    with pytest.raises(ValueError):
        grid_translations(1, 1, pitch=1.0, plane="QQ")


# ── ring ────────────────────────────────────────────────────────────────────

def test_ring_count_and_radius():
    ts = ring_translations(6, radius=12.0)
    assert len(ts) == 6
    for x, y, z in ts:
        assert math.hypot(x, y) == pytest.approx(12.0)
        assert z == pytest.approx(0.0)


def test_ring_even_angular_step():
    ts = ring_translations(4, radius=10.0)
    angles = sorted(math.atan2(y, x) % (2 * math.pi) for x, y, _ in ts)
    diffs = [b - a for a, b in zip(angles, angles[1:])]
    for d in diffs:
        assert d == pytest.approx(math.pi / 2)  # 360/4 = 90°


def test_ring_start_angle_and_center():
    ts = ring_translations(4, radius=5.0, start_angle_deg=0.0, center=(100.0, 0.0, 0.0))
    # slot 0 at angle 0 → (radius, 0) + center
    assert ts[0] == pytest.approx((105.0, 0.0, 0.0))
    # 90° start rotates slot 0 to (0, radius) + center
    ts90 = ring_translations(4, radius=5.0, start_angle_deg=90.0, center=(100.0, 0.0, 0.0))
    assert ts90[0] == pytest.approx((100.0, 5.0, 0.0))


def test_ring_plane_embedding():
    ts = ring_translations(4, radius=5.0, plane="XZ")
    for x, y, z in ts:
        assert y == pytest.approx(0.0)
        assert math.hypot(x, z) == pytest.approx(5.0)


@pytest.mark.parametrize("n,radius", [(0, 5.0), (-1, 5.0), (4, 0.0), (4, -3.0)])
def test_ring_rejects_non_positive(n, radius):
    with pytest.raises(ValueError):
        ring_translations(n, radius=radius)
