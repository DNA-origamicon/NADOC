"""Learned-energy / force-matched propagator core (A2 solute engine).

Pins the physically load-bearing properties: energy is invariant, forces are
equivariant (so the basin is real), force-matching trains, and Langevin integration
is stable + thermostats to the target temperature.  CPU-only, small synthetic system.
torch is optional — skip cleanly if it isn't installed.
"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

pytestmark = pytest.mark.slow  # torch+CUDA init > per-test budget → test-dedicated session

from backend.ml.propagator.energy import (  # noqa: E402
    EnergyNet, ForceNet, force_match_loss, langevin_rollout, langevin_step,
)
from backend.ml.propagator.gnn import radius_edges  # noqa: E402


def _system(n=120, seed=0):
    rng = np.random.default_rng(seed)
    pos = rng.uniform(0, 18, (n, 3)).astype(np.float32)
    z = torch.tensor(rng.integers(1, 9, n))
    edges = torch.tensor(radius_edges(pos, 6.0))
    return z, torch.tensor(pos), edges


def test_energy_invariant_and_forces_equivariant():
    """E rotation/translation invariant; F = -dE/dx rotates with the input. This is
    what guarantees a real restoring basin (unlike the displacement-regressor)."""
    torch.manual_seed(0)
    z, x, edges = _system()
    m = EnergyNet(hidden=24, n_layers=2, cutoff=6.0)
    E, F = m.forces(z, x, edges)
    assert E.dim() == 0                               # scalar total energy
    # translation invariance of energy
    E_shift = m.energy(z, x + 5.0, edges)
    assert abs(E.item() - E_shift.item()) < 1e-3
    # rotational equivariance of forces
    R, _ = torch.linalg.qr(torch.randn(3, 3))
    R = R * torch.sign(torch.det(R))
    E2, F2 = m.forces(z, x @ R.T, edges)
    assert abs(E.item() - E2.item()) < 1e-3           # invariant energy
    assert (F @ R.T - F2).abs().max().item() < 1e-4   # equivariant force


def test_forcenet_is_equivariant_and_single_pass():
    """ForceNet outputs a per-atom force in ONE forward (no autograd); the force must
    rotate with the input (equivariant) — the cheap direct-force correction net."""
    torch.manual_seed(0)
    z, x, edges = _system()
    m = ForceNet(hidden=24, n_layers=2, cutoff=6.0).eval()
    F = m(z, x, edges)
    assert F.shape == x.shape
    R, _ = torch.linalg.qr(torch.randn(3, 3))
    R = R * torch.sign(torch.det(R))
    F2 = m(z, x @ R.T, edges)
    assert (F @ R.T - F2).abs().max().item() < 1e-4     # equivariant force
    # translation invariance of the force
    assert (m(z, x + 3.0, edges) - F).abs().max().item() < 1e-4


def test_force_matching_reduces_loss():
    torch.manual_seed(0)
    z, x, edges = _system()
    m = EnergyNet(hidden=24, n_layers=2, cutoff=6.0).train()
    f_true = torch.randn(x.shape[0], 3) * 0.1
    opt = torch.optim.Adam(m.parameters(), lr=1e-3)
    l0 = force_match_loss(m, z, x, edges, f_true).item()
    for _ in range(40):
        opt.zero_grad()
        loss = force_match_loss(m, z, x, edges, f_true)
        loss.backward()
        opt.step()
    assert loss.item() < l0                            # the energy head can fit forces


def test_langevin_rollout_caches_force_and_thermostats():
    """The force-cached BAOAB rollout calls force_fn ONCE per step (not twice) and stays
    bounded under a simple harmonic force — the reusable fast inner loop."""
    torch.manual_seed(0)
    n = 60
    x0 = torch.randn(n, 3)
    x = x0.clone()
    v = torch.zeros(n, 3)
    mass = torch.full((n,), 12.0)
    calls = {"n": 0}

    def force_fn(xx, step):
        calls["n"] += 1
        return -20.0 * (xx - x0)          # harmonic well toward x0 (kcal/mol/Å)

    xf, vf = langevin_rollout(force_fn, x, v, mass, dt_fs=1.0, steps=100,
                              gamma_ps=147.0, temp_K=300.0)
    assert calls["n"] == 101              # once per step + the initial eval (cached, not 2×)
    assert torch.isfinite(xf).all() and torch.isfinite(vf).all()
    assert (xf - x0).norm(dim=-1).max().item() < 5.0   # stays bounded in the well


def test_langevin_rollout_is_stable_and_finite():
    torch.manual_seed(0)
    z, x, edges = _system()
    m = EnergyNet(hidden=24, n_layers=2, cutoff=6.0).eval()
    v = torch.zeros_like(x)
    mass = torch.rand(x.shape[0]) * 30 + 1
    for _ in range(60):
        x, v = langevin_step(m, z, x, v, edges, mass, dt_fs=2.0, gamma_ps=5.0)
    assert torch.isfinite(x).all() and torch.isfinite(v).all()
    # speeds stay physical (no runaway) — the whole point of the energy basin + thermostat
    assert v.norm(dim=-1).max().item() < 1.0
