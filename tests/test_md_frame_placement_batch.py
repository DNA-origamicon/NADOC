"""Compare batched strand placement with the established per-strand algorithm."""
import numpy as np
import pytest
from backend.core.md_trajectory import _direct_heavy_pre_positions
from backend.core.atomistic_to_nadoc import _unwrap_min_image


def scalar_reference(raw, p_pre, box, translation, layout):
    anchors = raw[layout['residue_anchor_rows']]
    shift = _unwrap_min_image(anchors, box, layout['residue_segment_ids']) - anchors
    placed = raw + shift[layout['heavy_res_group']] + translation
    for segment in range(layout['n_segments']):
        rows = np.flatnonzero((layout['p_heavy_rows'] >= 0) & (layout['p_segment_group'] == segment))
        if not len(rows):
            continue
        delta = np.median(p_pre[rows] - placed[layout['p_heavy_rows'][rows]], axis=0)
        lattice = np.zeros(3)
        good = box > 0
        lattice[good] = np.round(delta[good] / box[good]) * box[good]
        placed[layout['heavy_segment_group'] == segment] += lattice
    return placed


@pytest.mark.parametrize('box', [[10., 12., 8.], [10., 0., -1.], [0., 0., 0.]])
@pytest.mark.parametrize('cached_rows', [False, True])
def test_batch_preserves_strand_medians_and_recorded_atoms(box, cached_rows):
    box = np.array(box)
    # Odd/even phosphate counts; repeated lengths; a segment without a phosphate;
    # sparse, reordered phosphate rows and an unavailable atom reference.
    groups = np.repeat(np.arange(5), [4, 3, 4, 1, 3])
    residues = np.repeat(np.arange(len(groups)), 3)
    anchors = np.arange(len(groups))*3
    rng = np.random.default_rng(19)
    raw = rng.uniform(-15, 15, (len(residues), 3))
    order = np.array([14, 0, 6, 3, 8, 2, 12, 4, 5, 9, 1, 7, 10, 13])
    p_rows = np.r_[anchors[order], -1]
    p_segments = np.r_[groups[order], -1]
    layout = dict(heavy_res_group=residues, residue_anchor_rows=anchors,
                  residue_segment_ids=groups.astype(str), heavy_segment_group=groups[residues],
                  p_heavy_rows=p_rows, p_segment_group=p_segments, n_segments=5)
    if cached_rows:
        layout['segment_p_rows'] = [np.flatnonzero(p_segments == i) for i in range(5)]
    pre = rng.uniform(-30, 30, (len(p_rows), 3))
    translation = np.array([-3., 5., .25])
    original = raw.copy()
    for t in [0., 2.25, -4.]:
        target = pre + t
        expected = scalar_reference(raw, target, box, translation, layout)
        actual = _direct_heavy_pre_positions(raw, target, box, translation, layout)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(raw, original)
    assert 'segment_p_batches' in layout
