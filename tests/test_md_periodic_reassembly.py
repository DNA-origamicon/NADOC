"""Whole-strand imaging preserves measured coordinates and already intact runs."""
import json
from pathlib import Path

import numpy as np

from backend.core.atomistic_to_nadoc import (
    _unwrap_min_image, reassemble_to_posed_reference,
)
from backend.core.md_trajectory import aligned_rmsd_nm


def test_p1_runpod_keeps_the_intact_assembly_and_lattice_equivalence():
    fixture = json.loads((Path(__file__).parent / 'fixtures/md_p1_runpod_images.json').read_text())
    ids = np.asarray(fixture['strand_ids'])
    eq = np.asarray(fixture['reference'])
    rigid, snap = np.asarray(fixture['rigid']), np.asarray(fixture['snap'])
    for raw, box in zip(fixture['raw'], fixture['boxes']):
        box = np.asarray(box)
        whole = _unwrap_min_image(np.asarray(raw), box, ids)
        actual, _ = reassemble_to_posed_reference(whole, box, eq, eq[rigid].mean(axis=0), rigid, snap, ids)
        lattice = (actual - whole) / box
        np.testing.assert_allclose(lattice, np.rint(lattice), atol=1e-12)
        for strand in np.unique(ids):
            np.testing.assert_allclose(np.diff(actual[ids == strand], axis=0),
                                       np.diff(whole[ids == strand], axis=0), atol=1e-12)
        # The saved raw coordinates already contain this entire assembly. The
        # reconstruction must not make a different relative strand placement.
        assert aligned_rmsd_nm(actual, whole) < 1e-10
        assert aligned_rmsd_nm(actual[rigid], eq[rigid]) < 0.9


def test_even_strand_ties_never_produce_half_cell_translations():
    rng = np.random.default_rng(19)
    ids = np.repeat(['A', 'B', 'C'], [6, 8, 10])
    box = np.array([4., 5., 8.])
    mask = np.ones(len(ids), dtype=bool)
    for _ in range(40):
        reference = rng.normal(size=(len(ids), 3)) * 2
        measured = reference + rng.normal(size=reference.shape)
        result, _ = reassemble_to_posed_reference(
            measured, box, reference, reference.mean(axis=0), mask, mask, ids)
        shifts = (result - measured) / box
        np.testing.assert_allclose(shifts, np.rint(shifts), atol=1e-12)
        for strand in np.unique(ids):
            np.testing.assert_allclose(np.diff(shifts[ids == strand], axis=0), 0, atol=1e-12)
