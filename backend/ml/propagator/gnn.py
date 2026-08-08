"""Local equivariant GNN propagator + speed benchmark (torch, GPU).

The reframed question is: predict each atom's NEXT standard MD step (≈4 fs) from its
LOCAL environment, skipping the force calculation — and do it FASTER than full MD.

Model: a compact PaiNN-style [Schütt et al. 2021] message-passing net with a radius
cutoff. Scalar (invariant) + vector (equivariant) channels; the vector output is the
per-atom displacement Δx_i, initialised from velocity so the network only has to learn
the LOCAL FORCE CORRECTION (velocity alone already gives most of a 4 fs step — see
baseline.py). A radius cutoff means NO global electrostatics (no PME): that is exactly
the term whose O(N log N) cost we hope to undercut at origami scale.

`speed_benchmark` times the forward pass vs system size against NAMD's measured
7.5 ms/step for 17,827 atoms (job f6b191b31c33, RTX 2080). Message passing is timed
given a prebuilt neighbour list — the fair per-step comparison, since classical MD also
reuses a neighbour list across steps and only re-evaluates forces each step.

torch is an OPTIONAL, ad-hoc dependency (installed into the venv, not the core
lockfile): `uv pip install torch --index-url https://download.pytorch.org/whl/cu124`.
Nothing in the core app imports this module.
"""

from __future__ import annotations

import time

import numpy as np
import torch
import torch.nn as nn

NAMD_MS_PER_STEP = (
    7.5  # measured: 17,827-atom solvated duplex, RTX 2080 (0.0075 s/step)
)
NAMD_REF_N = 17_827
SOLVATED_ATOM_DENSITY = 0.10  # atoms / Å³ (TIP3P-solvated system, ~realistic)


class PaiNNLite(nn.Module):
    """Compact equivariant message-passing propagator: (z, pos, vel, edges) → Δx."""

    def __init__(
        self,
        hidden: int = 128,
        n_layers: int = 3,
        n_rbf: int = 20,
        cutoff: float = 5.0,
        n_elem: int = 20,
    ):
        super().__init__()
        self.hidden, self.cutoff, self.n_rbf = hidden, cutoff, n_rbf
        self.embed = nn.Embedding(n_elem, hidden)
        self.vel_gate = nn.Sequential(
            nn.Linear(hidden, hidden), nn.SiLU(), nn.Linear(hidden, hidden)
        )
        self.msg = nn.ModuleList()
        self.upd = nn.ModuleList()
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
        self.out_dx = nn.Linear(hidden, 1, bias=False)  # Δposition (equivariant vector)
        self.out_dv = nn.Linear(hidden, 1, bias=False)  # Δvelocity (equivariant vector)

    def _rbf(self, d: torch.Tensor) -> torch.Tensor:
        centers = torch.linspace(0, self.cutoff, self.n_rbf, device=d.device)
        return torch.exp(
            -((d[:, None] - centers[None, :]) ** 2) / (self.cutoff / self.n_rbf) ** 2
        )

    def forward(self, z, pos, vel, edge_index):
        i, j = edge_index[0], edge_index[1]
        s = self.embed(z)  # [N,H] scalar
        V = (
            vel[:, :, None] * self.vel_gate(s)[:, None, :]
        )  # [N,3,H] equivariant, seeded by velocity
        r = pos[j] - pos[i]  # [E,3]
        d = r.norm(dim=-1) + 1e-8
        fc = 0.5 * (
            torch.cos(np.pi * d.clamp(max=self.cutoff) / self.cutoff) + 1.0
        )  # cutoff envelope
        unit = r / d[:, None]
        rbf = self._rbf(d) * fc[:, None]

        for msg, upd in zip(self.msg, self.upd):
            phi = msg["phi"](s)[j] * msg["rbf"](rbf)  # [E,3H]
            ms, mv1, mv2 = phi.chunk(3, dim=-1)
            dV = mv1[:, None, :] * V[j] + mv2[:, None, :] * unit[:, :, None]  # [E,3,H]
            dsi = torch.zeros_like(s).index_add_(0, i, ms)
            dVi = torch.zeros_like(V).index_add_(0, i, dV)
            s = s + dsi
            V = V + dVi
            # update block (PaiNN-style scalar/vector mixing)
            Uv, Vv = upd["U"](V), upd["V"](V)  # [N,3,H]
            vv = (Uv * Vv).sum(dim=1)  # invariant [N,H]
            a = upd["mlp"](torch.cat([s, vv], dim=-1))  # [N,3H]
            a_ss, a_sv, a_vv = a.chunk(3, dim=-1)
            s = s + a_ss + a_sv * vv
            V = V + a_vv[:, None, :] * Vv

        # equivariant outputs: contract the H channels of the vector features to a
        # single 3-vector per atom for both the position and velocity increment
        # (velocity-seeded → the net learns the local force correction on top of
        # ballistic motion). Returns (Δx, Δv), both equivariant.
        dx = torch.einsum("nch,h->nc", V, self.out_dx.weight.squeeze(0))
        dv = torch.einsum("nch,h->nc", V, self.out_dv.weight.squeeze(0))
        return dx, dv


# ── neighbour list (setup only, not part of the timed per-step cost) ──────────
def radius_edges(pos: np.ndarray, cutoff: float) -> np.ndarray:
    """Undirected radius graph edge_index [2, E] via a KD-tree (CPU, one-off setup)."""
    from scipy.spatial import cKDTree  # noqa: PLC0415

    tree = cKDTree(pos)
    pairs = tree.query_pairs(r=cutoff, output_type="ndarray")  # [P,2], i<j
    if len(pairs) == 0:
        return np.zeros((2, 0), dtype=np.int64)
    both = np.concatenate([pairs, pairs[:, ::-1]], axis=0)
    return both.T.astype(np.int64)


def _random_system(n: int, density: float = SOLVATED_ATOM_DENSITY):
    L = (n / density) ** (1 / 3)
    rng = np.random.default_rng(0)
    pos = rng.uniform(0, L, size=(n, 3)).astype(np.float32)
    vel = rng.normal(0, 0.7, size=(n, 3)).astype(np.float32)
    z = rng.integers(1, 9, size=n).astype(np.int64)
    return z, pos, vel, L


def speed_benchmark(
    sizes=(1_000, 5_000, 17_827, 50_000, 100_000, 200_000),
    cutoff: float = 5.0,
    hidden: int = 128,
    n_layers: int = 3,
    reps: int = 20,
    device: str = "cuda",
) -> list[dict]:
    """Time the GNN forward pass (per-step cost) vs system size against NAMD.

    Message passing is timed on a prebuilt neighbour list. Reports ms/step and the
    ratio to NAMD's per-step cost (scaled to each N by O(N log N), PME's scaling)."""
    dev = torch.device(device if torch.cuda.is_available() else "cpu")
    model = PaiNNLite(hidden=hidden, n_layers=n_layers, cutoff=cutoff).to(dev).eval()
    rows = []
    print(
        f"=== GNN per-step speed vs NAMD (device={dev}, cutoff={cutoff} Å, "
        f"hidden={hidden}, layers={n_layers}) ==="
    )
    print(
        f"NAMD baseline: {NAMD_MS_PER_STEP:.2f} ms/step @ {NAMD_REF_N} atoms "
        f"(full force+PME+integrate, RTX 2080)"
    )
    print(
        f"{'N atoms':>9} {'edges':>11} {'nbr/atom':>8} {'GNN ms/step':>12} "
        f"{'NAMD~ms':>9} {'GNN/NAMD':>9}"
    )
    for n in sizes:
        z, pos, vel, _L = _random_system(
            n,
        )
        edges = radius_edges(pos, cutoff)
        if edges.shape[1] == 0:
            continue
        try:
            zt = torch.from_numpy(z).to(dev)
            pt = torch.from_numpy(pos).to(dev)
            vt = torch.from_numpy(vel).to(dev)
            et = torch.from_numpy(edges).to(dev)
            with torch.no_grad():
                for _ in range(3):  # warmup
                    model(zt, pt, vt, et)
                if dev.type == "cuda":
                    torch.cuda.synchronize()
                t0 = time.perf_counter()
                for _ in range(reps):
                    model(zt, pt, vt, et)
                if dev.type == "cuda":
                    torch.cuda.synchronize()
                ms = (time.perf_counter() - t0) / reps * 1000.0
        except torch.cuda.OutOfMemoryError:
            print(f"{n:>9} {'OOM (8 GB) — extrapolate from smaller N':>50}")
            torch.cuda.empty_cache()
            break
        # NAMD cost scaled to N by PME's O(N log N)
        namd_scaled = (
            NAMD_MS_PER_STEP
            * (n * np.log2(max(n, 2)))
            / (NAMD_REF_N * np.log2(NAMD_REF_N))
        )
        row = {
            "n": n,
            "edges": int(edges.shape[1]),
            "nbr_per_atom": edges.shape[1] / n,
            "gnn_ms": ms,
            "namd_ms_scaled": namd_scaled,
            "ratio": ms / namd_scaled,
        }
        rows.append(row)
        print(
            f"{n:>9} {row['edges']:>11} {row['nbr_per_atom']:>8.1f} {ms:>12.3f} "
            f"{namd_scaled:>9.2f} {row['ratio']:>9.2f}"
        )
        del zt, pt, vt, et
        if dev.type == "cuda":
            torch.cuda.empty_cache()
    return rows
