"""Coarse-grained SNUPI hydrodynamics — a blob (bead-shell) RPY friction that never forms a dense
6N×6N matrix, so full-size origami hydrodynamics fits in RAM.

**Why.** The exact friction ``Z = Ξ⁻¹`` of :mod:`backend.physics.snupi_hydrodynamics` is dense and
O(N²) in memory, with N = one FE node per base pair. Measured peak is ≈ 1.5e-6·N² GB, so a full M13
origami (N ≈ 7240) needs ≈ 79 GB — it OOMs a 30 GB machine. That wall is inherent to the method, not
to our code: the SNUPI dynamics SI (Note 4.3) holds several dense 6N×6N matrices at once (Z, the
Cholesky factor S, the auxiliary inverses j and b), and the only dynamics example SNUPI ships is a
339-bp structure. Full-size brick origami is simply outside the regime the method was demonstrated in.

**The physics.** One hydrodynamic bead per bp is over-resolved to begin with: the beads have radius
σ = 1.1 nm and sit 0.34 nm apart, i.e. ~90% overlapping, so we are resolving the flow field far below
any scale on which it varies. We therefore group ``coarse_bp`` consecutive bp of a helix into ONE blob
and let the blobs carry the hydrodynamic coupling, while every node keeps its own exact Stokes
self-drag:

    Ξ = D + Aᵀ C A

* ``C`` — the generalized RPY mobility (all four blocks, :func:`rpy_mobility_generalized`) between the
  B blob centres, at the blob radius σ_b. SPD.
* ``A`` — the (6B × 6N) node→blob map: it sums nodal forces onto a blob and broadcasts the blob's
  velocity back to its nodes (the rigid-blob picture).
* ``D`` — diagonal, ``D_i = μ_self(σ) − μ_self(σ_b)`` per node, i.e. exactly the self-mobility the blob
  does NOT already supply. Positive because σ_b > σ, so Ξ stays SPD.

Consequences, which are the right ones: a node's self-drag is EXACT; two nodes in the same blob are
hydrodynamically locked at the blob's mobility (they move together through the fluid, as they
physically must at 0.34 nm separation); two nodes in different blobs couple through the RPY tensor
between blob centres — a monopole truncation of the true pair coupling, controlled by σ_b and accurate
once the blobs are separated by more than their own size.

**Valid range: k ≥ 4, and k = 8 is the calibrated default.** The model assumes a blob is meaningfully
BIGGER than a bead. At small k it is not — σ_b(2) = 1.113 nm against σ = 1.1 nm, so ``D`` is a mere 1.1%
of the node self-mobility and the blob supplies ~99% of the drag while containing two nodes. That
slaves them together and over-damps intra-blob motion, and the hydrodynamic enhancement is LOST: on
6hbx100_noT the breathing-mode relaxation time at k = 2 collapses to τ/τ_exact = 0.52, essentially the
no-hydrodynamics Stokes value (0.58), while k = 8 gives 0.97. So this is NOT a model that converges to
the exact one as k → 1 — it degenerates. (Formally k = 1 IS exact — A = I, D = 0, Ξ = C = the exact RPY —
but D = 0 makes the Woodbury undefined, so k = 1 is routed to :mod:`snupi_hydrodynamics` instead, and
2 ≤ k ≤ 3 is refused rather than silently returning Stokes-like kinetics.) ``build_coarse_friction``
enforces this floor.

**The structure that buys the memory.** Woodbury on Ξ = D + AᵀCA gives

    Z = D⁻¹ − Yᵀ G⁻¹ Y ,   Y = A D⁻¹ ,   G = C⁻¹ + A D⁻¹ Aᵀ

— *diagonal minus rank-6B*. Nothing here is 6N×6N: ``D`` and ``E`` are diagonal (O(N)), ``Y`` is sparse
(one 6×6 diagonal block per node), and the only dense object is 6B×6B. Applying ``Z``, applying the GJF
auxiliary inverse ``(I + Δt·Z̃/2)⁻¹`` (a second Woodbury), and drawing the correlated random force are
all O(N + (6B)²). At M13 scale with ``coarse_bp=8`` that is ≈ 0.4 GB instead of 79 GB.

**The noise.** We never Cholesky-factor Z (which is the expensive dense step in the paper's algorithm).
Instead we sample from the MOBILITY side, where the covariance is a sum rather than an inverse:

    y = M^{1/2} D^{1/2} g₁ + M^{1/2} Aᵀ L_C g₂    ⇒   cov(y) = Ξ̃      (L_C = chol C, 6B×6B)
    β̃ = √(2 k_BT Δt) · Z̃ y                        ⇒   cov(β̃) = 2 k_BT Δt · Z̃   ✓

which is the exact fluctuation–dissipation covariance, obtained with only a 6B×6B Cholesky.

**Free ssDNA tails (SS-3).** Pass the dynamics-side :class:`snupi_tails.TailBlock` and the tail beads
join the blob set too, so overhangs feel the solvent and the solvent feels them. Two species now share
one model, and the way they are reconciled is the whole trick:

* A node's OWN hydrodynamic radius is its species' — σ = 1.1 nm for a base pair, σ_ss = 0.5 nm for an
  ssDNA nucleotide (:data:`snupi_tails.SS_HYDRO_RADIUS_NM`). It enters only ``D``, so every node's
  self-drag stays EXACT for its species: ``Ξ_ii = D_i + C_bb = μ_self(σ_i)`` by construction.
* Every BLOB, of either species, is the SAME sphere σ_b. That keeps ``C`` a single-radius RPY — no
  unequal-radius (Zuk 2014) tensor, no new overlap regularizations, and the existing PD guarantee and
  the k = 8 calibration carry over untouched. What we choose instead is how many NUCLEOTIDES fit in
  that sphere: :func:`ss_blob_nt` inverts the worm-like chain to find the run length whose coil has the
  same enclosing radius as a k-bp duplex blob (k = 8 ⇒ σ_b = 1.62 nm ⇒ 11 nt). A blob is then a
  uniformly sized hydrodynamic object everywhere in the structure, which is exactly what the
  single-radius RPY assumes.

This is a good approximation and not merely a convenient one, because the pair mobility we actually
need is nearly radius-blind: the leading RPY term is ``1/(8πηr)`` — Oseen, INDEPENDENT of bead radius —
so blob↔blob coupling is right at leading order whatever σ_b is. (Check, at the separation that
matters: an ssDNA bead 2 nm from a bp bead has true unequal-radius RPY cross-mobility 0.19·μ_self(σ_ss);
this blob model gives 0.20.) Only the near-field/overlap correction carries a radius, and there the
blob model under-couples (0.24 vs 0.37 at r = 1.2 nm) — i.e. tails come out slightly more free-draining
than reality, which is the conservative direction.

Tails are never merged into a duplex blob, even the 3-mers: sharing a blob means sharing a mobility,
and a tail slaved to its anchor helix's blob would be dragged around by the duplex instead of waving.

The friction is built ONCE, from the reference configuration (SNUPI's own ``DYN_MAT_FREQ 0`` default),
so where a tail's blobs SIT is fixed by the conformation it starts in — and this is the second reason
:func:`snupi_tails._coil_run` had to exist. A tail started as a straight rod (SS-2) would put its outer
blobs 19 nm out into the solvent, far from where the chain actually spends its time, and freeze that
misplacement into the friction for the whole run. Started as a thermal coil, the blob centres sit in a
typical conformation from the first step.

Everything is in the module's nm · pN · ns unit system (see :mod:`snupi_dynamics`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.physics.snupi_dynamics import HYDRO_RADIUS_NM
from backend.physics.snupi_hydrodynamics import (
    mobility_translational_6n,
    mu_self_rot,
    mu_self_trans,
    rpy_mobility_generalized,
)


# Below this the blob is not meaningfully bigger than a bead (see the module docstring): D → 0, the
# nodes get slaved to their blob, and the hydrodynamic enhancement is lost. Calibrated on 6hbx100_noT
# against the exact generalized RPY: τ/τ_exact = 0.52 (k=2), 0.86 (k=4), 0.97 (k=8), 1.10 (k=16),
# vs 0.58 for no-hydrodynamics Stokes.
MIN_COARSE_BP = 4
DEFAULT_COARSE_BP = 8


def blob_radius_nm(coarse_bp: int, sigma: float = HYDRO_RADIUS_NM) -> float:
    """Radius σ_b of a blob standing in for ``coarse_bp`` consecutive bp of duplex: the sphere that
    encloses that cylinder — half-length ``(k−1)·rise/2`` along the axis, duplex radius σ across it.
    Strictly > σ for k > 1, which is what keeps ``D = μ_self(σ) − μ_self(σ_b)`` positive (⇒ Ξ SPD)."""
    half_len = 0.5 * (max(int(coarse_bp), 1) - 1) * BDNA_RISE_PER_BP
    return float(math.hypot(half_len, sigma))


@lru_cache(maxsize=None)
def ss_blob_nt(coarse_bp: int) -> int:
    """How many ssDNA NUCLEOTIDES stand in one blob, so that an ssDNA blob is the same sphere as a
    ``coarse_bp``-bp duplex blob (see the module docstring: one blob radius ⇒ one-radius RPY).

    A duplex blob of k bp encloses a rigid cylinder ⇒ radius :func:`blob_radius_nm`. An ssDNA run of
    n nt is not rigid — it is a coil whose mean size is its worm-like-chain RMS end-to-end distance
    ``√⟨R²⟩`` (:func:`snupi_tails.wlc_mean_square_end_to_end`) — so it encloses a sphere of radius
    ``hypot(√⟨R²⟩/2, σ_ss)``. Return the n whose sphere is closest to the duplex blob's.

    k = 8 ⇒ σ_b = 1.62 nm ⇒ **11 nt**. Note it is NOT the naive contour ratio (0.68 nm/nt vs the
    0.34 nm rise would say 4 nt): a coil is far more compact than the chain laid out straight, so
    many more nucleotides fit in the same sphere.
    """
    from backend.physics.snupi_tails import SS_HYDRO_RADIUS_NM, wlc_mean_square_end_to_end

    target = blob_radius_nm(coarse_bp)
    best, best_err = 1, math.inf
    for n in range(1, 129):
        r = math.hypot(0.5 * math.sqrt(wlc_mean_square_end_to_end(n)), SS_HYDRO_RADIUS_NM)
        err = abs(r - target)
        if err < best_err:
            best, best_err = n, err
        elif r > target:                      # radius is monotone in n — past the target, stop
            break
    return best


def blob_partition(mesh, coarse_bp: int, block=None) -> np.ndarray:
    """Assign each node to a blob: ``coarse_bp`` CONSECUTIVE bp of the same helix per blob.
    Returns ``bead_of`` (int array) with blob ids 0..B-1. Blobs never straddle a helix — a helix whose
    length is not a multiple of ``coarse_bp`` just ends in a short blob.

    With a :class:`snupi_tails.TailBlock`, the tail beads (global indices ``n_bp..``) are partitioned
    too and the array is length ``block.n_total``. A tail is a chain of its own, so it is partitioned
    ALONG the chain, one run at a time, into ⌈n/:func:`ss_blob_nt`⌉ blobs of as-equal-as-possible size —
    balanced rather than greedy so a run never ends in a 1-bead sliver. A tail shorter than
    ``ss_blob_nt`` is one blob (VoltronCore's 24 3-mers), and NEVER joins its anchor's duplex blob:
    blob-mates share a mobility, and a tail sharing the helix's would be dragged along by it instead of
    fluctuating freely.
    """
    k = max(int(coarse_bp), 1)
    n_core = len(mesh.nodes)
    n_tot = n_core if block is None else block.n_total
    bead_of = np.empty(n_tot, dtype=int)
    nxt = 0
    per_helix: dict[str, List[int]] = {}
    for i, nd in enumerate(mesh.nodes):
        per_helix.setdefault(nd.helix_id, []).append(i)
    for hid in sorted(per_helix):
        idx = sorted(per_helix[hid], key=lambda i: mesh.nodes[i].global_bp)
        for c in range(0, len(idx), k):
            for i in idx[c:c + k]:
                bead_of[i] = nxt
            nxt += 1

    if block is not None and block.n_tail:
        k_ss = ss_blob_nt(k)
        per_run: dict[int, List[int]] = {}
        for g, nd in enumerate(block.nodes):
            per_run.setdefault(nd.run, []).append(g)
        for run in sorted(per_run):
            beads = sorted(per_run[run], key=lambda g: block.nodes[g].index_in_run)
            n_blob = max(1, math.ceil(len(beads) / k_ss))
            for chunk in np.array_split(np.array(beads, dtype=int), n_blob):
                bead_of[n_core + chunk] = nxt
                nxt += 1
    return bead_of


def blob_count(mesh, coarse_bp: int, block=None) -> int:
    """Number of blobs :func:`blob_partition` will produce — the B that sets the coarse friction's
    only dense object (6B×6B), so the memory preflight needs it BEFORE anything is allocated.
    O(N) and allocation-free; ⌈N/k⌉ is NOT a valid substitute once helices and tails fragment it."""
    return int(blob_partition(mesh, coarse_bp, block).max()) + 1


@dataclass
class CoarseFriction:
    """Structured (diagonal-minus-low-rank) friction ``Z`` for the coarse blob model.

    Exposes exactly what the operator GJF integrator needs — ``apply_Z``, ``apply_b_inv``, ``sample_beta``
    — with O(N + (6B)²) memory and cost. Built once (the friction is configuration-independent over the
    run, matching SNUPI's own ``DYN_MAT_FREQ 0`` default)."""
    bead_of: np.ndarray        # (N,) node → blob id
    n_nodes: int
    n_beads: int
    dinv: np.ndarray           # (6N,) diagonal of D⁻¹
    dhalf: np.ndarray          # (6N,) diagonal of D^{1/2}
    Ginv: np.ndarray           # (6B,6B) = (C⁻¹ + A D⁻¹ Aᵀ)⁻¹
    Lc: np.ndarray             # (6B,6B) Cholesky factor of C
    minv_half: np.ndarray      # (6N,) M^{-1/2}
    m_half: np.ndarray         # (6N,) M^{1/2}
    _Kinv: Optional[np.ndarray] = None   # (6B,6B) for the GJF auxiliary inverse, set by prepare_gjf
    _Ediag: Optional[np.ndarray] = None  # (6N,) diagonal of E = I + (Δt/2)·D̃

    # ── sparse A operators (one 6×6 diagonal block per node) ────────────────────
    def _scatter(self, x6n: np.ndarray) -> np.ndarray:
        """A·x — sum the per-node 6-vectors of ``x6n`` onto their blobs. Returns (6B,)."""
        out = np.zeros(6 * self.n_beads)
        xm = x6n.reshape(self.n_nodes, 6)
        np.add.at(out.reshape(self.n_beads, 6), self.bead_of, xm)
        return out

    def _gather(self, w6b: np.ndarray) -> np.ndarray:
        """Aᵀ·w — broadcast each blob's 6-vector back to its nodes. Returns (6N,)."""
        return w6b.reshape(self.n_beads, 6)[self.bead_of].reshape(-1)

    # ── the friction itself ─────────────────────────────────────────────────────
    def apply_Z(self, x: np.ndarray) -> np.ndarray:
        """``Z·x`` = D⁻¹x − Yᵀ G⁻¹ Y x  with Y = A D⁻¹  (Woodbury; never forms 6N×6N)."""
        dx = self.dinv * x
        return dx - self.dinv * self._gather(self.Ginv @ self._scatter(dx))

    def apply_Ztilde(self, x: np.ndarray) -> np.ndarray:
        """``Z̃·x`` with Z̃ = M^{-1/2} Z M^{-1/2} — the mass-weighted friction the GJF works in."""
        return self.minv_half * self.apply_Z(self.minv_half * x)

    # ── GJF auxiliary inverse (I + (Δt/2)·Z̃)⁻¹, a second Woodbury ───────────────
    def prepare_gjf(self, dt: float) -> None:
        """Precompute the 6B×6B factor for ``apply_b_inv`` at this Δt. Z̃ = D̃ − Ỹᵀ G⁻¹ Ỹ is diagonal
        minus low-rank, so (E − (Δt/2)Ỹᵀ G⁻¹ Ỹ)⁻¹ with E = I + (Δt/2)D̃ is Woodbury again."""
        c = 0.5 * dt
        dtil = self.minv_half * self.dinv * self.minv_half          # diag(D̃)
        self._Ediag = 1.0 + c * dtil
        # Ỹ = A D⁻¹ M^{-1/2}: per node a 6×6 diagonal block  s_i = dinv_i · minv_half_i
        s = self.dinv * self.minv_half
        # K = G − c · Ỹ E⁻¹ Ỹᵀ ; Ỹ E⁻¹ Ỹᵀ is BLOCK-DIAGONAL (6×6 per blob)
        w = (s * s) / self._Ediag                                    # (6N,)
        blk = self._scatter(w)                                       # (6B,) — the 6×6 blocks are diagonal
        G = np.linalg.inv(self.Ginv)
        K = G - c * np.diag(blk)
        self._Kinv = np.linalg.inv(K)

    def apply_b_inv(self, x: np.ndarray, dt: float) -> np.ndarray:
        """``(I + (Δt/2)·Z̃)⁻¹ · x`` — the GJF ``b`` operator."""
        if self._Kinv is None or self._Ediag is None:
            self.prepare_gjf(dt)
        c = 0.5 * dt
        s = self.dinv * self.minv_half
        ex = x / self._Ediag
        corr = s * self._gather(self._Kinv @ self._scatter(s * ex))
        return ex + c * (corr / self._Ediag)

    # ── correlated random force ─────────────────────────────────────────────────
    def sample_beta(self, kT: float, dt: float, rng: np.random.Generator) -> np.ndarray:
        """Random impulse β̃ with ⟨β̃β̃ᵀ⟩ = 2 k_BT Δt · Z̃, drawn from the MOBILITY side so that only a
        6B×6B Cholesky is ever needed (never a 6N×6N one — the paper's dense bottleneck)."""
        g1 = rng.standard_normal(6 * self.n_nodes)
        g2 = rng.standard_normal(6 * self.n_beads)
        y = self.m_half * (self.dhalf * g1 + self._gather(self.Lc @ g2))   # cov(y) = Ξ̃
        return math.sqrt(2.0 * kT * dt) * self.apply_Ztilde(y)


def node_radii(mesh, block=None, sigma: float = HYDRO_RADIUS_NM) -> np.ndarray:
    """Per-node hydrodynamic radius (N,) — σ = 1.1 nm for a duplex bp node, σ_ss = 0.5 nm for an ssDNA
    tail bead. This is the ONLY place the two species differ hydrodynamically; it enters ``D``, which
    is what makes each node's self-drag exact for its own species (see the module docstring)."""
    from backend.physics.snupi_tails import SS_HYDRO_RADIUS_NM

    n_core = len(mesh.nodes)
    n_tot = n_core if block is None else block.n_total
    a = np.full(n_tot, float(sigma))
    a[n_core:] = SS_HYDRO_RADIUS_NM
    return a


def build_coarse_friction(mesh, X0: np.ndarray, m_diag: np.ndarray, coarse_bp: int,
                          sigma: float = HYDRO_RADIUS_NM,
                          generalized: bool = True,
                          block=None) -> CoarseFriction:
    """Assemble the blob RPY friction for ``mesh`` at reference positions ``X0`` (N,3 nm).

    ``m_diag`` is the (6N,) diagonal mass (dynamics units). ``coarse_bp`` bp per blob; 1 = exact model
    (but then use :mod:`snupi_hydrodynamics` directly — D would vanish).

    ``block`` (SS-3) is the dynamics-side :class:`snupi_tails.TailBlock`. Its beads extend ``X0``,
    ``m_diag`` and the blob set, so free ssDNA tails get hydrodynamic drag and hydrodynamic coupling
    rather than the diagonal Stokes drag of SS-2. ``X0``/``m_diag`` must then already cover core+tails.

    ``generalized`` defaults to True here (unlike the exact path): the blob coupling matrix is only
    6B×6B, so the paper-faithful rotation–translation / rotation–rotation coupling costs nothing worth
    saving. The blobs are also well separated (k·0.34 nm apart at radius σ_b), which is the regime the
    generalized RPY is most comfortable in."""
    k = max(int(coarse_bp), 1)
    if k == 1:
        raise ValueError("coarse_bp=1 is the exact model — call snupi_hydrodynamics.friction_matrix")
    if k < MIN_COARSE_BP:
        raise ValueError(
            f"coarse_bp={k} is in the degenerate regime: the blob radius σ_b={blob_radius_nm(k):.3f} nm "
            f"is barely above the bead radius {sigma:.2f} nm, so the blob supplies almost all of the "
            f"node's drag while containing {k} nodes — it slaves them together, over-damps intra-blob "
            f"motion and LOSES the hydrodynamic enhancement (τ collapses to the Stokes value). Use "
            f"coarse_bp ≥ {MIN_COARSE_BP} ({DEFAULT_COARSE_BP} is the calibrated default), or "
            f"coarse_bp=None for the exact per-bp friction."
        )
    bead_of = blob_partition(mesh, k, block)
    n = len(bead_of)
    nb = int(bead_of.max()) + 1

    centres = np.zeros((nb, 3))
    counts = np.zeros(nb)
    np.add.at(centres, bead_of, np.asarray(X0, float))
    np.add.at(counts, bead_of, 1.0)
    centres /= counts[:, None]

    # ONE radius for every blob, of either species — that is what keeps C a single-radius RPY (module
    # docstring). The species enters through the per-NODE radius below, not here.
    sigma_b = blob_radius_nm(k, sigma)
    if generalized:
        C = rpy_mobility_generalized(centres, sigma_b)      # (6B,6B) SPD — all four blocks
    else:
        C = mobility_translational_6n(centres, sigma_b)     # tt coupling + self rotational Stokes

    # D = μ_self(σ_i) − μ_self(σ_b) per node: exactly the self-mobility the blob does NOT already
    # supply, so that Ξ_ii = D_i + C_bb = μ_self(σ_i) is the node's EXACT Stokes self-mobility — for a
    # 0.5 nm ssDNA bead as much as for a 1.1 nm bp. Positive because σ_b > σ_i for BOTH species and
    # μ_self falls as 1/a (trans) / 1/a³ (rot) ⇒ Ξ stays SPD.
    a_node = node_radii(mesh, block, sigma)
    d = np.empty(6 * n, dtype=float)
    d.reshape(n, 6)[:, :3] = (mu_self_trans(a_node) - mu_self_trans(sigma_b))[:, None]
    d.reshape(n, 6)[:, 3:] = (mu_self_rot(a_node) - mu_self_rot(sigma_b))[:, None]
    if not (d > 0).all():                                   # pragma: no cover — σ_b > σ guarantees it
        raise ValueError("coarse D is not positive — blob radius must exceed every bead radius")

    dinv = 1.0 / d
    # G = C⁻¹ + A D⁻¹ Aᵀ  (the second term is block-diagonal: sum of D⁻¹ over each blob's nodes)
    Ginv_acc = np.zeros(6 * nb)
    np.add.at(Ginv_acc.reshape(nb, 6), bead_of, dinv.reshape(n, 6))
    G = np.linalg.inv(C) + np.diag(Ginv_acc)
    m_diag = np.asarray(m_diag, float)
    return CoarseFriction(
        bead_of=bead_of, n_nodes=n, n_beads=nb,
        dinv=dinv, dhalf=np.sqrt(d),
        Ginv=np.linalg.inv(G), Lc=np.linalg.cholesky(C),
        minv_half=1.0 / np.sqrt(m_diag), m_half=np.sqrt(m_diag),
    )
