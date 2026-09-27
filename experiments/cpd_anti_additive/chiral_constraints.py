"""Analytic signed tetrahedral volumes for isolated coordinate construction."""

import numpy as np
from scipy.sparse import csr_matrix


def volumes_and_derivatives(positions):
    """Return scalar triple products and their Cartesian derivatives, in Å³/Å²."""
    a, b, c, d = np.moveaxis(np.asarray(positions), -2, 0)
    ab, ac, ad = b-a, c-a, d-a
    gb, gc, gd = np.cross(ac, ad), np.cross(ad, ab), np.cross(ab, ac)
    ga = -gb-gc-gd
    return np.einsum('...i,...i->...', ab, gb), np.stack((ga, gb, gc, gd), axis=-2)


class SignedVolumes:
    def __init__(self, initial, mobile, indices, signs):
        self.initial = np.array(initial, dtype=float, copy=True)
        self.mobile = np.asarray(mobile, dtype=int)
        self.indices = np.asarray(indices, dtype=int)
        self.signs = np.asarray(signs, dtype=float)
        assert self.indices.shape == (len(self.signs), 4)
        assert np.isin(self.signs, [-1., 1.]).all()
        mapping = {int(atom): i for i, atom in enumerate(self.mobile)}
        self.entries = [(r, j, mapping[int(atom)]) for r, ns in enumerate(self.indices)
                        for j, atom in enumerate(ns) if int(atom) in mapping]

    def positions(self, flat):
        out = self.initial.copy()
        out[self.mobile] = np.asarray(flat).reshape(-1, 3)
        return out

    def values(self, flat):
        v, _ = volumes_and_derivatives(self.positions(flat)[self.indices])
        return self.signs*v

    def jacobian(self, flat):
        _, g = volumes_and_derivatives(self.positions(flat)[self.indices])
        rows, cols, values = [], [], []
        for row, neighbor, atom in self.entries:
            for axis in range(3):
                rows.append(row); cols.append(3*atom+axis)
                values.append(self.signs[row]*g[row, neighbor, axis])
        return csr_matrix((values, (rows, cols)), shape=(len(self.signs), 3*len(self.mobile)))
