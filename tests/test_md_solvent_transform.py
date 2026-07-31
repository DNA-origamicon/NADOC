"""The display affine — the load-bearing piece of the solvent overlay.

Served MD frames are NOT in the simulation's own frame: the extractors reassemble
DNA across periodic images and Kabsch-align it onto the design pose. Solvent
coordinates and the periodic-box corners must ride that same map, or they will
sit somewhere else entirely from the DNA they belong to.

`apply_xform` is therefore pinned against a TRANSCRIBED copy of the expression at
backend/core/md_trajectory.py `_extract_md_atoms_frame`
(``pos_nm = (pos_pre - mob_c) @ R_align.T + eq_centroid``). If that line ever
changes, this test is the tripwire.
"""

import numpy as np
import pytest

from backend.core.md_solvent import (
    BOX_EDGES,
    DisplayXform,
    apply_xform,
    box_corners,
    min_image,
)


def _random_rotation(rng):
    """A proper rotation (det = +1) via QR."""
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    q = q @ np.diag(np.sign(np.diag(r)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def _xform(rng, *, with_rotation=True, box=(4.0, 5.0, 6.0)):
    return DisplayXform.build(
        T_dyn=rng.normal(size=3),
        c_box=rng.normal(size=3) + 10.0,
        box_nm=np.array(box, dtype=float),
        mob_c=rng.normal(size=3),
        eq_centroid=rng.normal(size=3),
        R=_random_rotation(rng) if with_rotation else None,
    )


class TestApplyXform:
    # The pin: identical arithmetic to md_trajectory's own line, transcribed.
    def test_matches_the_extractor_expression(self):
        rng = np.random.default_rng(20260730)
        for _ in range(20):
            xf = _xform(rng)
            pts = rng.normal(size=(50, 3)) * 3.0
            expected = (pts - xf.mob_c) @ xf.R.T + xf.eq_centroid
            np.testing.assert_allclose(apply_xform(pts, xf), expected, rtol=0, atol=1e-12)

    def test_no_rotation_is_a_pure_translation(self):
        rng = np.random.default_rng(7)
        xf = _xform(rng, with_rotation=False)
        pts = rng.normal(size=(10, 3))
        np.testing.assert_allclose(apply_xform(pts, xf), pts - xf.mob_c + xf.eq_centroid,
                                   rtol=0, atol=1e-12)

    def test_identity_transform_is_a_no_op(self):
        xf = DisplayXform.build(T_dyn=None, c_box=None, box_nm=(0, 0, 0))
        pts = np.array([[1.0, 2.0, 3.0], [-4.0, 5.0, -6.0]])
        np.testing.assert_array_equal(apply_xform(pts, xf), pts)

    def test_empty_input_keeps_the_nx3_shape(self):
        xf = DisplayXform.build(T_dyn=None, c_box=None, box_nm=(1, 1, 1))
        assert apply_xform(np.zeros((0, 3)), xf).shape == (0, 3)

    # A rotation+translation is an isometry, so a molecule placed within `shell`
    # of its anchor in PRE coordinates is still within `shell` of that anchor
    # after the map. This is what makes "hydration shell" mean the same thing on
    # screen as it did in the selection.
    def test_the_shell_survives_the_transform(self):
        rng = np.random.default_rng(99)
        xf = _xform(rng)
        anchors = rng.normal(size=(40, 3))
        shell = 0.5
        offsets = rng.normal(size=(40, 3))
        offsets *= (shell * 0.9) / np.linalg.norm(offsets, axis=1, keepdims=True)
        waters = anchors + offsets

        d_display = np.linalg.norm(apply_xform(waters, xf) - apply_xform(anchors, xf), axis=1)
        np.testing.assert_allclose(d_display, np.linalg.norm(offsets, axis=1),
                                   rtol=0, atol=1e-12)
        assert (d_display <= shell + 1e-9).all()


class TestMinImage:
    def test_folds_a_full_box_displacement_to_zero(self):
        box = np.array([4.0, 5.0, 6.0])
        np.testing.assert_allclose(min_image(np.array([[4.0, 5.0, 6.0]]), box),
                                   [[0.0, 0.0, 0.0]], atol=1e-12)

    def test_leaves_a_short_displacement_alone(self):
        box = np.array([4.0, 5.0, 6.0])
        d = np.array([[0.3, -0.4, 0.5]])
        np.testing.assert_allclose(min_image(d, box), d, atol=1e-12)

    def test_result_is_always_within_half_a_box(self):
        rng = np.random.default_rng(3)
        box = np.array([4.0, 5.0, 6.0])
        d = rng.uniform(-40, 40, size=(500, 3))
        assert (np.abs(min_image(d, box)) <= box / 2 + 1e-9).all()

    # A zero box length means "unknown / not periodic on this axis" — folding
    # there would divide by zero.
    def test_a_zero_box_axis_is_untouched(self):
        d = np.array([[9.0, 9.0, 9.0]])
        out = min_image(d, np.array([4.0, 0.0, 6.0]))
        assert out[0, 1] == 9.0

    def test_does_not_mutate_its_input(self):
        d = np.array([[9.0, 9.0, 9.0]])
        min_image(d, np.array([4.0, 5.0, 6.0]))
        np.testing.assert_array_equal(d, [[9.0, 9.0, 9.0]])


class TestBoxCorners:
    def test_eight_corners_centred_on_the_dna_anchor(self):
        rng = np.random.default_rng(11)
        xf = _xform(rng)
        c = box_corners(xf)
        assert c.shape == (8, 3)
        # A cuboid's corners average to its centre; the centre is c_box + T_dyn
        # carried through the same affine as everything else.
        np.testing.assert_allclose(
            c.mean(axis=0),
            apply_xform((xf.c_box + xf.T_dyn)[None, :], xf)[0],
            rtol=0, atol=1e-10)

    def test_edge_lengths_are_the_cell_lengths(self):
        rng = np.random.default_rng(12)
        box = np.array([4.0, 5.0, 6.0])
        xf = _xform(rng, box=tuple(box))
        c = box_corners(xf)
        # Each edge joins corners differing in one bit; that bit names the axis.
        for a, b in BOX_EDGES:
            axis = int(np.log2((a ^ b)))
            np.testing.assert_allclose(np.linalg.norm(c[b] - c[a]), box[axis],
                                       rtol=0, atol=1e-10)

    def test_twelve_edges_each_differing_in_exactly_one_bit(self):
        assert len(BOX_EDGES) == 12
        assert len(set(BOX_EDGES)) == 12
        for a, b in BOX_EDGES:
            assert bin(a ^ b).count("1") == 1

    def test_corners_stay_a_right_cuboid_under_rotation(self):
        rng = np.random.default_rng(13)
        xf = _xform(rng)
        c = box_corners(xf)
        # The three edges meeting at corner 0 must remain mutually orthogonal.
        e = [c[1] - c[0], c[2] - c[0], c[4] - c[0]]
        for i in range(3):
            for j in range(i + 1, 3):
                assert abs(float(np.dot(e[i], e[j]))) < 1e-9

    def test_box_breathes_with_the_cell(self):
        rng = np.random.default_rng(14)
        small = _xform(rng, box=(4.0, 5.0, 6.0))
        big = DisplayXform.build(
            T_dyn=small.T_dyn, c_box=small.c_box, box_nm=(8.0, 10.0, 12.0),
            mob_c=small.mob_c, eq_centroid=small.eq_centroid, R=small.R)
        a, b = box_corners(small), box_corners(big)
        assert np.linalg.norm(b[7] - b[0]) == pytest.approx(2 * np.linalg.norm(a[7] - a[0]))

    def test_no_box_yields_no_corners(self):
        xf = DisplayXform.build(T_dyn=None, c_box=None, box_nm=(0.0, 0.0, 0.0))
        assert box_corners(xf).shape == (0, 3)
        assert not xf.has_box

    # Everything the DNA got, the box gets: a wrapped solvent atom placed beside
    # its anchor must land INSIDE the drawn cell.
    def test_a_wrapped_point_lands_inside_the_drawn_cell(self):
        rng = np.random.default_rng(15)
        box = np.array([4.0, 5.0, 6.0])
        xf = _xform(rng, box=tuple(box))
        raw = rng.uniform(-30, 30, size=(200, 3))
        pre = (xf.c_box + xf.T_dyn) + min_image(raw - xf.c_box, box)
        pts = apply_xform(pre, xf)
        c = box_corners(xf)
        # Project onto the cell's own (rotated) axes and check the extent.
        origin = c[0]
        axes = [(c[1] - c[0]), (c[2] - c[0]), (c[4] - c[0])]
        for a, L in zip(axes, box):
            unit = a / np.linalg.norm(a)
            t = (pts - origin) @ unit
            assert t.min() >= -1e-6
            assert t.max() <= L + 1e-6
