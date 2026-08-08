"""Learned-energy / force-matched propagator (A2 solute-focused, learned-energy head).

The pivot away from the displacement-regressor (which had no energy basin → 347× RMSF
drift): learn a SCALAR energy E_θ(x) over the DNA solute, get forces by autograd
(F = -∇E_θ), and integrate with a Langevin thermostat.  Because E is invariant, F is
equivariant by construction; because Langevin dynamics on E samples the Boltzmann
distribution of E, a well-fit E gives a GUARANTEED restoring basin — stability by design.

Training = FORCE MATCHING.  The captured per-atom forces on the DNA solute are the
instantaneous forces from the full explicit-solvent system.  Their solvent-average is the
mean force -∇W where W is the potential of mean force (the implicit-solvent free energy).
Least-squares matching E_θ's gradient to these forces therefore learns W: the fluctuating
(solvent-collision) part averages out into what the Langevin noise then re-injects
(Mori-Zwanzig with a Markovian/Langevin closure).  So this IS a machine-learned
implicit-solvent DNA force field — the theoretically-correct A2 solute engine.

torch is the optional dep (see gnn.py).  DNA-only solute first (fixed atom set); ion
shell + hydration shell (which exchange) come in M2.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

KB_KCAL = 0.0019872041  # Boltzmann constant, kcal/mol/K


class EnergyNet(nn.Module):
    """PaiNN-style equivariant net outputting a SCALAR energy (sum of per-atom energies).

    Scalar (invariant) + vector (equivariant) channels; only the invariant scalar stream
    feeds the energy readout, so E is rotation/translation invariant and F = -dE/dx is
    equivariant.  A radius cutoff → local, transferable, no PME (composes onto origami)."""

    def __init__(
        self,
        hidden: int = 64,
        n_layers: int = 3,
        n_rbf: int = 20,
        cutoff: float = 6.0,
        n_elem: int = 20,
    ):
        super().__init__()
        self.hidden, self.cutoff, self.n_rbf = hidden, cutoff, n_rbf
        self.embed = nn.Embedding(n_elem, hidden)
        self.msg, self.upd = nn.ModuleList(), nn.ModuleList()
        for _ in range(n_layers):
            self.msg.append(
                nn.ModuleDict(
                    {
                        "phi": nn.Sequential(
                            nn.Linear(hidden, hidden),
                            nn.SiLU(),
                            nn.Linear(hidden, 3 * hidden),
                        ),
                        "rbf": nn.Linear(n_rbf, 3 * hidden),
                    }
                )
            )
            self.upd.append(
                nn.ModuleDict(
                    {
                        "U": nn.Linear(hidden, hidden, bias=False),
                        "V": nn.Linear(hidden, hidden, bias=False),
                        "mlp": nn.Sequential(
                            nn.Linear(2 * hidden, hidden),
                            nn.SiLU(),
                            nn.Linear(hidden, 3 * hidden),
                        ),
                    }
                )
            )
        self.readout = nn.Sequential(
            nn.Linear(hidden, hidden), nn.SiLU(), nn.Linear(hidden, 1)
        )

    def _rbf(self, d):
        c = torch.linspace(0, self.cutoff, self.n_rbf, device=d.device)
        return torch.exp(
            -((d[:, None] - c[None, :]) ** 2) / (self.cutoff / self.n_rbf) ** 2
        )

    def energy(self, z, pos, edge_index):
        i, j = edge_index[0], edge_index[1]
        s = self.embed(z)
        V = torch.zeros(pos.shape[0], 3, self.hidden, device=pos.device)
        r = pos[j] - pos[i]
        d = r.norm(dim=-1) + 1e-8
        fc = 0.5 * (torch.cos(np.pi * d.clamp(max=self.cutoff) / self.cutoff) + 1.0)
        unit = r / d[:, None]
        rbf = self._rbf(d) * fc[:, None]
        for msg, upd in zip(self.msg, self.upd):
            phi = msg["phi"](s)[j] * msg["rbf"](rbf)
            ms, mv1, mv2 = phi.chunk(3, dim=-1)
            dV = mv1[:, None, :] * V[j] + mv2[:, None, :] * unit[:, :, None]
            s = s + torch.zeros_like(s).index_add_(0, i, ms)
            V = V + torch.zeros_like(V).index_add_(0, i, dV)
            Uv, Vv = upd["U"](V), upd["V"](V)
            vv = (Uv * Vv).sum(dim=1)
            a = upd["mlp"](torch.cat([s, vv], dim=-1))
            a_ss, a_sv, a_vv = a.chunk(3, dim=-1)
            s = s + a_ss + a_sv * vv
            V = V + a_vv[:, None, :] * Vv
        return self.readout(s).sum()  # total scalar energy (sum of per-atom)

    def forces(self, z, pos, edge_index):
        """F = -dE/dx.  Equivariant because E is invariant.  Returns (E, F)."""
        pos = pos.detach().requires_grad_(True)
        E = self.energy(z, pos, edge_index)
        (grad,) = torch.autograd.grad(E, pos, create_graph=self.training)
        return E, -grad


class ForceNet(nn.Module):
    """DIRECT-force equivariant net — outputs a per-atom force vector in ONE forward pass
    (no energy, no autograd.grad).  ~2× cheaper per step than EnergyNet (skips the backward)
    AND ~2-3× cheaper to train (first-order loss, no second-order autograd).

    NON-conservative (the output isn't a gradient → no energy basin), so use it ONLY as the
    solvent-PMF CORRECTION on top of a conservative baseline (CHARMM+GBSA) that supplies the
    basin; the Langevin thermostat absorbs the small energy injection from non-conservativeness.
    Same PaiNN message passing as EnergyNet with an equivariant vector readout instead of the
    scalar energy readout."""

    def __init__(
        self,
        hidden: int = 48,
        n_layers: int = 3,
        n_rbf: int = 20,
        cutoff: float = 5.0,
        n_elem: int = 20,
    ):
        super().__init__()
        self.hidden, self.cutoff, self.n_rbf = hidden, cutoff, n_rbf
        self.embed = nn.Embedding(n_elem, hidden)
        self.msg, self.upd = nn.ModuleList(), nn.ModuleList()
        for _ in range(n_layers):
            self.msg.append(
                nn.ModuleDict(
                    {
                        "phi": nn.Sequential(
                            nn.Linear(hidden, hidden),
                            nn.SiLU(),
                            nn.Linear(hidden, 3 * hidden),
                        ),
                        "rbf": nn.Linear(n_rbf, 3 * hidden),
                    }
                )
            )
            self.upd.append(
                nn.ModuleDict(
                    {
                        "U": nn.Linear(hidden, hidden, bias=False),
                        "V": nn.Linear(hidden, hidden, bias=False),
                        "mlp": nn.Sequential(
                            nn.Linear(2 * hidden, hidden),
                            nn.SiLU(),
                            nn.Linear(hidden, 3 * hidden),
                        ),
                    }
                )
            )
        self.out = nn.Linear(
            hidden, 1, bias=False
        )  # contracts V's H channels → 3-vector

    def _rbf(self, d):
        c = torch.linspace(0, self.cutoff, self.n_rbf, device=d.device)
        return torch.exp(
            -((d[:, None] - c[None, :]) ** 2) / (self.cutoff / self.n_rbf) ** 2
        )

    def forward(self, z, pos, edge_index):
        i, j = edge_index[0], edge_index[1]
        s = self.embed(z)
        V = torch.zeros(pos.shape[0], 3, self.hidden, device=pos.device)
        r = pos[j] - pos[i]
        d = r.norm(dim=-1) + 1e-8
        fc = 0.5 * (torch.cos(np.pi * d.clamp(max=self.cutoff) / self.cutoff) + 1.0)
        unit = r / d[:, None]
        rbf = self._rbf(d) * fc[:, None]
        for msg, upd in zip(self.msg, self.upd):
            phi = msg["phi"](s)[j] * msg["rbf"](rbf)
            ms, mv1, mv2 = phi.chunk(3, dim=-1)
            dV = mv1[:, None, :] * V[j] + mv2[:, None, :] * unit[:, :, None]
            s = s + torch.zeros_like(s).index_add_(0, i, ms)
            V = V + torch.zeros_like(V).index_add_(0, i, dV)
            Uv, Vv = upd["U"](V), upd["V"](V)
            vv = (Uv * Vv).sum(dim=1)
            a = upd["mlp"](torch.cat([s, vv], dim=-1))
            a_ss, a_sv, a_vv = a.chunk(3, dim=-1)
            s = s + a_ss + a_sv * vv
            V = V + a_vv[:, None, :] * Vv
        return torch.einsum(
            "nch,h->nc", V, self.out.weight.squeeze(0)
        )  # equivariant force


def force_match_loss(model, z, pos, edge_index, f_true):
    _E, f_pred = model.forces(z, pos, edge_index)
    return ((f_pred - f_true) ** 2).mean()


def langevin_rollout(
    force_fn,
    x,
    v,
    mass,
    *,
    dt_fs,
    steps,
    gamma_ps=147.0,
    temp_K=300.0,
    callback=None,
    callback_every=100,
):
    """Force-CACHED BAOAB Langevin rollout — the fast inner loop for validation.

    ``force_fn(x, step) -> F`` returns the total force (kcal/mol/Å) at ``x``; the caller
    composes it however it likes. Two speed patterns this enables (measured on the
    DNA-duplex solute, RTX 2080):
      * **force caching** — BAOAB reuses the force from the end of one step as the start
        of the next, so ``force_fn`` runs ONCE per step, not twice (free 2×). Built in here.
      * **RESPA subsampling** — inside ``force_fn``, recompute only the SLOW part (e.g. the
        GBSA implicit-solvent correction, ~66 ms) every k steps keyed on ``step`` while the
        cheap part (bonded FF ~4 ms, compiled NN ~5 ms) runs every step. k=8 gave 3.1× with
        the invariant measure preserved (Rg drift unchanged). ``force_fn`` owns that policy.
    x, v, mass are torch [N,3]/[N] tensors on the model device. Returns final (x, v)."""
    import torch  # noqa: PLC0415

    ACC = 4.184e-4
    m = mass[:, None] if mass.dim() == 1 else mass
    g = gamma_ps * 1e-3
    c1 = float(np.exp(-g * dt_fs))
    c2 = float(np.sqrt(max(0.0, 1 - c1 * c1)))
    sig = torch.sqrt(torch.as_tensor(KB_KCAL * temp_K * ACC, device=x.device) / m)
    f = force_fn(x, 0)
    for k in range(steps):
        a = f * ACC / m
        v = v + 0.5 * dt_fs * a
        x = x + 0.5 * dt_fs * v  # A
        v = c1 * v + c2 * sig * torch.randn_like(v)  # O (thermostat)
        x = x + 0.5 * dt_fs * v  # A
        f = force_fn(x, k + 1)  # ONE eval → next step's opening B
        a = f * ACC / m
        v = v + 0.5 * dt_fs * a
        if callback is not None and k % callback_every == 0:
            callback(k, x, v)
    return x, v


def langevin_step(
    model, z, x, v, edge_index, mass, *, dt_fs, gamma_ps=5.0, temp_K=300.0
):
    """One BAOAB Langevin step with learned forces.  dt in fs, gamma in 1/ps.
    Units: pos Å, force kcal/mol/Å, mass amu → accel in Å/fs² via the 418.4 factor
    (1 kcal/mol/Å/amu = 418.4 Å/ps² = 4.184e-4 Å/fs²)."""
    ACC = 4.184e-4  # (kcal/mol/Å)/amu → Å/fs²
    dt = dt_fs
    g = gamma_ps * 1e-3  # 1/ps → 1/fs
    m = mass[:, None]
    _E, f = model.forces(z, x, edge_index)
    a = f * ACC / m
    v = v + 0.5 * dt * a  # B
    x = x + 0.5 * dt * v  # A
    c1 = np.exp(-g * dt)
    c2 = np.sqrt(max(0.0, 1 - c1 * c1))
    sigma = torch.sqrt(
        torch.as_tensor(KB_KCAL * temp_K * ACC) / m
    )  # Å/fs thermal speed
    v = c1 * v + c2 * sigma * torch.randn_like(v)  # O
    x = x + 0.5 * dt * v  # A
    _E, f = model.forces(z, x, edge_index)
    a = f * ACC / m
    v = v + 0.5 * dt * a  # B
    return x, v
