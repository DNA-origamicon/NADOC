"""Exact spatial pruning for the loop rotor's repeated piercing checks.

The detector and its search radius are unchanged. A rotor can affect only bonds
with a moved endpoint or rings containing a moved atom. Their complete trial
envelope bounds every other bond midpoint/ring centre the detector could visit.
"""
import numpy as np

from backend.core.ring_piercing import SEARCH_NM, _scan, residue_key, ring_names_for


class RotorPiercingIndex:
    def __init__(self, model):
        residues = {}
        for i, atom in enumerate(model.atoms):
            residues.setdefault(residue_key(atom), {})[atom.name] = i
        self.rings = [
            (key, kind, [names[name] for name in ring])
            for key, names in residues.items()
            for kind, ring in ring_names_for(names)
        ]
        self.ring_groups = []
        for size in sorted({len(row[2]) for row in self.rings}):
            ids = np.array([i for i, row in enumerate(self.rings) if len(row[2]) == size])
            self.ring_groups.append((ids, np.array([self.rings[i][2] for i in ids])))
        self.bonds = np.asarray([
            (i, j) for i, j in model.bonds
            if not model.atoms[i].name.startswith('H') and not model.atoms[j].name.startswith('H')
        ], dtype=int).reshape(-1, 2)

    def scope(self, positions, serials, states):
        own = set(map(int, serials))
        moving_bonds = np.isin(self.bonds, serials).any(axis=1)
        moving_rings = np.zeros(len(self.rings), dtype=bool)
        centres = np.empty((len(self.rings), 3))
        for ids, atoms in self.ring_groups:
            moving_rings[ids] = np.isin(atoms, serials).any(axis=1)
            centres[ids] = positions[atoms].mean(axis=1)
        # Include fixed endpoints of incident bonds and fixed atoms of any
        # partially moved ring. All trial midpoints/centres lie in this hull.
        incident = set(self.bonds[moving_bonds].ravel())
        for moving, row in zip(moving_rings, self.rings):
            if moving:
                incident.update(row[2])
        envelope = states.reshape(-1, 3)
        if incident:
            envelope = np.concatenate((envelope, positions[sorted(incident)]))
        lo = envelope.min(axis=0) - SEARCH_NM - 1e-12
        hi = envelope.max(axis=0) + SEARCH_NM + 1e-12
        mids = positions[self.bonds].mean(axis=1)
        near_bonds = moving_bonds | ((mids >= lo) & (mids <= hi)).all(axis=1)
        near_rings = moving_rings | ((centres >= lo) & (centres <= hi)).all(axis=1)
        bonds = self.bonds[near_bonds].tolist()
        rings = [row for keep, row in zip(near_rings, self.rings) if keep]

        def hits(trial):
            return {
                (tuple(h['bond_serials']), tuple(h['ring_serials']))
                for h in _scan(trial, bonds, rings, max_report=len(bonds)*len(rings))
                if own.intersection((*h['bond_serials'], *h['ring_serials']))
            }
        return hits
