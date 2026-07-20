"""Calibrated uncertainty for BLADE (dev-order #6-8) — the second co-equal MVP capability.

BLADE = exact CHARMM+GBSA baseline + learned ForceNet correction.  The baseline carries NO
uncertainty; ALL epistemic uncertainty lives in the ~6% solvent correction the NN supplies.
A DEEP ENSEMBLE of independently-seeded ForceNets estimates it: where the members AGREE the
correction is trustworthy; where they DISAGREE (novel/undertrained local environments — skip
sites, strained junctions, motifs unseen in training) the correction is unreliable.

The point is CALIBRATION: ensemble disagreement must actually predict where the correction is
WRONG.  If it does, the per-atom uncertainty is a map for (dev #9-11) proposing a LOCAL region
for explicit-MD verification — flag the junction, not the whole box.

torch is the optional dep (see energy.py).
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from backend.ml.propagator.energy import ForceNet


class EnsembleForceNet(nn.Module):
    """K independently-seeded ForceNets → (mean force, per-atom epistemic uncertainty).

    ``forward`` returns the ensemble-mean force [N,3] (a better correction than any single
    member — ensembling averages out variance) and a per-atom scalar uncertainty u_i =
    RMS deviation of the members' force vectors at atom i (Å-force units)."""

    def __init__(self, k: int = 5, hidden: int = 48, n_layers: int = 3, cutoff: float = 5.0):
        super().__init__()
        self.members = nn.ModuleList([
            ForceNet(hidden=hidden, n_layers=n_layers, cutoff=cutoff) for _ in range(k)
        ])

    def stack(self, z, pos, edge_index) -> torch.Tensor:
        """All members' force predictions, stacked [K, N, 3]."""
        return torch.stack([m(z, pos, edge_index) for m in self.members], dim=0)

    def forward(self, z, pos, edge_index):
        f = self.stack(z, pos, edge_index)                 # [K,N,3]
        mean = f.mean(dim=0)                                # [N,3]
        # per-atom epistemic uncertainty: RMS spread of the force VECTORS across members
        var = ((f - mean[None]) ** 2).sum(dim=-1).mean(dim=0)   # [N]  (mean_k |f_k - fbar|^2)
        return mean, torch.sqrt(var + 1e-12)


def reliability_curve(uncertainty, error, n_bins: int = 10):
    """Bin atoms by predicted uncertainty; return per-bin (mean uncertainty, mean actual
    error, count).  A CALIBRATED signal is monotone increasing — higher uncertainty bins
    carry higher actual error.  Inputs are 1-D numpy arrays (per-atom)."""
    u = np.asarray(uncertainty, dtype=float)
    e = np.asarray(error, dtype=float)
    order = np.argsort(u)
    u, e = u[order], e[order]
    bins = np.array_split(np.arange(len(u)), n_bins)
    return np.array([[u[b].mean(), e[b].mean(), len(b)] for b in bins if len(b)])


def calibration_score(uncertainty, error) -> dict:
    """How well does per-atom uncertainty predict per-atom error?
    Returns Pearson + Spearman correlation and the monotonicity of the reliability curve."""
    u = np.asarray(uncertainty, dtype=float)
    e = np.asarray(error, dtype=float)
    pear = float(np.corrcoef(u, e)[0, 1])
    ru = np.argsort(np.argsort(u)); re = np.argsort(np.argsort(e))     # rank transform
    spear = float(np.corrcoef(ru, re)[0, 1])
    rc = reliability_curve(u, e)
    # fraction of adjacent reliability-bin steps that increase (1.0 = perfectly monotone)
    mono = float(np.mean(np.diff(rc[:, 1]) > 0)) if len(rc) > 1 else float("nan")
    return {"pearson": pear, "spearman": spear, "reliability_monotonicity": mono}
