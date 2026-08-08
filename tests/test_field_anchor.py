"""The shared "a uniform field needs something to hold it" rule (field_anchor.py).

A field drifts the COM unless held by ≥1 strand anchor OR a hard surface it presses into
(a deposition setup). This pins the geometry so every field path — persisted runs, live
sessions, chain-launch validation — agrees, and so the exact 6hbx100_1xT stage 1 config
(field −y into a +y floor) is recognised as held.
"""

from __future__ import annotations

from backend.core.field_anchor import (
    field_needs_strand_anchor,
    surface_opposes_field,
)


# ── surface_opposes_field geometry ───────────────────────────────────────────────


def test_field_straight_into_the_floor_is_opposed():
    # The real stage-1 config: field points −y, floor normal +y → held.
    assert surface_opposes_field([0, -1, 0], [0, 1, 0]) is True


def test_field_away_from_the_surface_is_not_opposed():
    # Field along +normal pushes the structure OFF the plane — not held.
    assert surface_opposes_field([0, 1, 0], [0, 1, 0]) is False


def test_in_plane_field_is_not_opposed():
    # Field parallel to the plane drifts sideways unopposed.
    assert surface_opposes_field([1, 0, 0], [0, 1, 0]) is False


def test_mostly_in_plane_field_is_not_opposed():
    # A field only slightly into the plane (large lateral component) still drifts.
    assert surface_opposes_field([1.0, -0.2, 0.0], [0, 1, 0]) is False


def test_nearly_normal_field_is_opposed_within_tolerance():
    # ~14° off straight-in (cos ≈ 0.97 > 0.906) → still held.
    assert surface_opposes_field([0.25, -1.0, 0.0], [0, 1, 0]) is True


def test_missing_or_zero_directions_are_not_opposed():
    assert surface_opposes_field(None, [0, 1, 0]) is False
    assert surface_opposes_field([0, -1, 0], None) is False
    assert surface_opposes_field([0, 0, 0], [0, 1, 0]) is False


# ── field_needs_strand_anchor decision ───────────────────────────────────────────


def test_no_field_never_needs_an_anchor():
    assert field_needs_strand_anchor(has_field=False, has_anchors=False) is False


def test_field_with_anchors_is_satisfied():
    assert field_needs_strand_anchor(has_field=True, has_anchors=True) is False


def test_field_alone_needs_an_anchor():
    assert (
        field_needs_strand_anchor(
            has_field=True, has_anchors=False, field_dir=[0, -1, 0], surface_dir=None
        )
        is True
    )


def test_field_into_opposing_surface_needs_no_anchor():
    # THE fix: the 6hbx100_1xT deposition stage is now valid without a strand anchor.
    assert (
        field_needs_strand_anchor(
            has_field=True,
            has_anchors=False,
            field_dir=[0, -1, 0],
            surface_dir=[0, 1, 0],
        )
        is False
    )


def test_field_with_non_opposing_surface_still_needs_an_anchor():
    # A surface parallel to the field's drift (field in-plane) does not hold it.
    assert (
        field_needs_strand_anchor(
            has_field=True,
            has_anchors=False,
            field_dir=[1, 0, 0],
            surface_dir=[0, 1, 0],
        )
        is True
    )
