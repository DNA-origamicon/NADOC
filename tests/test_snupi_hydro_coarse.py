"""Coarse-grained SNUPI hydrodynamics (blob RPY) + the RPY positive-definiteness parity fix.

Two things are pinned here:

1. **The generalized-RPY PD parity.** ``μ^rt`` is antisymmetric and ODD in r, so reciprocity forces the
   two cross-blocks of a pair to be EQUAL, not transposes. We previously stored ``tr`` / ``trᵀ`` (the
   SI's literal ``μ^rt = [μ^tr]ᵀ``), which flips one sign; the error COMPOUNDS through the many-body
   superposition and made the mobility indefinite, which we wrongly recorded as "RPY loses PD at
   origami bead density". These tests pin that Ξ is PD and that its min eigenvalue is STABLE in N
   (the old bug's signature was a min eigenvalue marching negative as beads were added).

2. **The coarse blob friction.** Every operator is checked against a DENSE oracle, and the whole thing
   against the Boltzmann covariance ``⟨qqᵀ⟩ = k_BT·K⁻¹`` — which any valid (SPD) friction must sample,
   so a mis-scaled or non-SPD friction cannot pass.
"""
import numpy as np
import pytest

from backend.physics.snupi_dynamics import (
    KBT_300,
    gjf_integrate_operator_friction,
    HYDRO_RADIUS_NM,
)
from backend.physics.snupi_hydro_coarse import (
    DEFAULT_COARSE_BP,
    MIN_COARSE_BP,
    blob_partition,
    blob_radius_nm,
    build_coarse_friction,
)
from backend.physics.snupi_hydrodynamics import (
    HydroMemoryError,
    check_friction_memory,
    estimate_friction_memory_gb,
    friction_matrix,
    mu_self_rot,
    mu_self_trans,
    rpy_mobility_generalized,
)


class _Node:
    def __init__(self, helix_id, global_bp):
        self.helix_id, self.global_bp = helix_id, global_bp


class _Mesh:
    def __init__(self, nodes):
        self.nodes = nodes


def _lattice(n_helix=3, per=12):
    """An origami-like bead set: helices 2.6 nm apart, bp every 0.34 nm (deep in the RPY overlap
    regime — r/a ≈ 0.3, which is exactly where the old parity bug destroyed PD)."""
    nodes = [_Node(f"h{h}", b) for h in range(n_helix) for b in range(per)]
    X0 = np.array([[h * 2.6, 0.0, b * 0.34] for h in range(n_helix) for b in range(per)], float)
    n = len(nodes)
    m = np.tile([1.086e-3] * 3 + [2.0e-4] * 3, n)
    return _Mesh(nodes), X0, m, n


# ── 1. generalized RPY is positive-definite at origami bead density ─────────────

@pytest.mark.parametrize("per", [4, 10, 20])
def test_generalized_rpy_is_positive_definite_at_origami_density(per):
    """The paper (SI Note 4.2) Cholesky-factors Z on exactly this bead set, so Ξ must be PD."""
    _mesh, X0, _m, _n = _lattice(n_helix=3, per=per)
    Xi = rpy_mobility_generalized(X0)
    assert np.allclose(Xi, Xi.T, atol=1e-12), "grand mobility must be symmetric (Lorentz reciprocity)"
    np.linalg.cholesky(Xi)                       # raises if not PD — the paper's requirement
    assert np.linalg.eigvalsh(Xi).min() > 0


def test_generalized_rpy_min_eigenvalue_is_stable_in_N():
    """The old cross-block parity bug made the min eigenvalue march NEGATIVE as beads accumulated
    (−2.6e-2 → −1.8e-1 for N = 40 → 480). With the parity right it is positive and ~constant — that
    STABILITY in N, not merely positivity, is what distinguishes the fix from a lucky small case."""
    mins = []
    for per in (6, 12, 24):
        _mesh, X0, _m, _n = _lattice(n_helix=3, per=per)
        mins.append(float(np.linalg.eigvalsh(rpy_mobility_generalized(X0)).min()))
    assert all(v > 0 for v in mins)
    assert max(mins) / min(mins) < 1.2, f"min eigenvalue should be stable in N, got {mins}"


@pytest.mark.slow
def test_generalized_rpy_stays_pd_at_larger_bead_counts():
    """The compounding signature again, at a size where the old bug was unmistakable (N ≈ 480)."""
    _mesh, X0, _m, _n = _lattice(n_helix=6, per=80)
    assert np.linalg.eigvalsh(rpy_mobility_generalized(X0)).min() > 0


def test_friction_matrix_generalized_returns_spd_z():
    _mesh, X0, _m, _n = _lattice(n_helix=2, per=10)
    Z = friction_matrix(X0, generalized=True)
    assert np.allclose(Z, Z.T, atol=1e-9)
    assert np.linalg.eigvalsh(Z).min() > 0


def test_mobility_self_terms_scale_with_bead_radius():
    """The pair/self helpers take a radius `a`; they must actually USE it (they hardcoded the σ=1.1 nm
    drag before, which silently mis-scaled any blob-radius call)."""
    assert mu_self_trans(2.2) == pytest.approx(0.5 * mu_self_trans(1.1))     # 1/(6πηa) ∝ 1/a
    assert mu_self_rot(2.2) == pytest.approx(mu_self_rot(1.1) / 8.0)         # 1/(8πηa³) ∝ 1/a³
    Xi = rpy_mobility_generalized(np.array([[0.0, 0.0, 0.0], [50.0, 0.0, 0.0]]), a=2.0)
    assert Xi[0, 0] == pytest.approx(mu_self_trans(2.0))
    assert Xi[3, 3] == pytest.approx(mu_self_rot(2.0))


# ── 2. blob partition ───────────────────────────────────────────────────────────

def test_blob_partition_groups_consecutive_bp_and_never_straddles_helices():
    mesh, _X0, _m, _n = _lattice(n_helix=3, per=10)
    bead_of = blob_partition(mesh, 4)
    # 10 bp / 4 → blobs of 4,4,2 per helix ⇒ 3 blobs × 3 helices
    assert bead_of.max() + 1 == 9
    for i, nd in enumerate(mesh.nodes):
        for j, nd2 in enumerate(mesh.nodes):
            if bead_of[i] == bead_of[j]:
                assert nd.helix_id == nd2.helix_id, "a blob must not straddle two helices"


def test_blob_radius_exceeds_bead_radius_so_D_stays_positive():
    assert blob_radius_nm(1) == pytest.approx(HYDRO_RADIUS_NM)
    for k in (2, 4, 8, 16):
        assert blob_radius_nm(k) > HYDRO_RADIUS_NM


def test_degenerate_small_k_is_refused_not_silently_wrong():
    """k = 2..3 puts σ_b barely above σ, so D → 0, the nodes get slaved to their blob and the
    hydrodynamic enhancement is LOST (τ collapses to the Stokes value). Refuse rather than return
    kinetics that look like no-hydrodynamics while claiming RPY. k = 1 is the exact model, not this one."""
    mesh, X0, m, _n = _lattice(n_helix=2, per=8)
    for bad in (2, 3):
        with pytest.raises(ValueError, match="degenerate"):
            build_coarse_friction(mesh, X0, m, bad)
    with pytest.raises(ValueError, match="exact model"):
        build_coarse_friction(mesh, X0, m, 1)
    build_coarse_friction(mesh, X0, m, MIN_COARSE_BP)      # the floor itself must work


def test_blob_supplies_a_real_fraction_of_the_drag_at_the_default_k():
    """The model assumes a blob is meaningfully BIGGER than a bead. Quantify it: D/μ_self is 1.1% at
    k=2 (degenerate) but ~31% at the k=8 default — a real, non-vanishing residual node drag."""
    frac = lambda k: 1.0 - mu_self_trans(blob_radius_nm(k)) / mu_self_trans(HYDRO_RADIUS_NM)  # noqa: E731
    assert frac(2) < 0.02
    assert frac(DEFAULT_COARSE_BP) > 0.25


# ── 3. the coarse friction operators vs a DENSE oracle ──────────────────────────

def _dense_xi(mesh, X0, k, n):
    """Independent dense build of Ξ = D + AᵀCA — the oracle the Woodbury operators must reproduce."""
    bead_of = blob_partition(mesh, k)
    nb = bead_of.max() + 1
    cen = np.zeros((nb, 3))
    cnt = np.zeros(nb)
    np.add.at(cen, bead_of, X0)
    np.add.at(cnt, bead_of, 1.0)
    cen /= cnt[:, None]
    sb = blob_radius_nm(k)
    C = rpy_mobility_generalized(cen, sb)
    A = np.zeros((6 * nb, 6 * n))
    for i in range(n):
        A[6 * bead_of[i]:6 * bead_of[i] + 6, 6 * i:6 * i + 6] = np.eye(6)
    d = np.tile([mu_self_trans(HYDRO_RADIUS_NM) - mu_self_trans(sb)] * 3
                + [mu_self_rot(HYDRO_RADIUS_NM) - mu_self_rot(sb)] * 3, n)
    return np.diag(d) + A.T @ C @ A


def test_coarse_xi_is_spd_and_apply_Z_matches_dense_inverse():
    mesh, X0, m, n = _lattice(n_helix=3, per=12)
    k = 4
    Xi = _dense_xi(mesh, X0, k, n)
    assert np.linalg.eigvalsh(Xi).min() > 0
    Zd = np.linalg.inv(Xi)

    fr = build_coarse_friction(mesh, X0, m, k)
    x = np.random.default_rng(0).standard_normal(6 * n)
    assert np.allclose(fr.apply_Z(x), Zd @ x, rtol=1e-9, atol=1e-12)


def test_coarse_apply_b_inv_matches_the_dense_gjf_operator():
    """(I + Δt·Z̃/2)⁻¹ via the second Woodbury must equal the dense inverse."""
    mesh, X0, m, n = _lattice(n_helix=2, per=10)
    k = 5
    dt = 0.002
    Ztil = np.diag(1 / np.sqrt(m)) @ np.linalg.inv(_dense_xi(mesh, X0, k, n)) @ np.diag(1 / np.sqrt(m))
    dense = np.linalg.inv(np.eye(6 * n) + 0.5 * dt * Ztil)

    fr = build_coarse_friction(mesh, X0, m, k)
    fr.prepare_gjf(dt)
    x = np.random.default_rng(1).standard_normal(6 * n)
    assert np.allclose(fr.apply_b_inv(x, dt), dense @ x, rtol=1e-8, atol=1e-12)
    assert np.allclose(fr.apply_Ztilde(x), Ztil @ x, rtol=1e-8, atol=1e-12)


def test_coarse_noise_has_the_fluctuation_dissipation_covariance():
    """⟨β̃β̃ᵀ⟩ = 2·k_BT·Δt·Z̃ — sampled from the MOBILITY side (only a 6B×6B Cholesky, never 6N×6N)."""
    mesh, X0, m, n = _lattice(n_helix=2, per=6)
    k, dt = 4, 0.002
    fr = build_coarse_friction(mesh, X0, m, k)
    rng = np.random.default_rng(4)
    S = np.array([fr.sample_beta(KBT_300, dt, rng) for _ in range(20000)])
    Ztil = np.diag(1 / np.sqrt(m)) @ np.linalg.inv(_dense_xi(mesh, X0, k, n)) @ np.diag(1 / np.sqrt(m))
    target = 2.0 * KBT_300 * dt * Ztil
    ratio = np.mean(np.diag(np.cov(S.T)) / np.diag(target))
    assert 0.95 < ratio < 1.05, f"noise variance off by {ratio:.3f}×"


# ── 4. the end-to-end gate: any valid friction samples ⟨qqᵀ⟩ = k_BT·K⁻¹ ─────────

@pytest.mark.slow
def test_operator_gjf_with_coarse_friction_samples_the_boltzmann_covariance():
    """The equilibrium distribution is FRICTION-INDEPENDENT, so the coarse blob friction must sample
    exactly k_BT·K⁻¹. A mis-scaled or non-SPD friction fails this. Stiff K keeps τ = ζ/k short so the
    covariance converges in a short run (a soft K would measure sampling error instead)."""
    mesh, X0, m, n = _lattice(n_helix=2, per=5)
    ndof = 6 * n
    rng = np.random.default_rng(11)
    A = rng.standard_normal((ndof, ndof))
    K = 200.0 * (A @ A.T / ndof + 3.0 * np.eye(ndof))
    target = KBT_300 * np.linalg.inv(K)

    fr = build_coarse_friction(mesh, X0, m, 4)
    samples, _v = gjf_integrate_operator_friction(
        lambda q: -(K @ q), np.zeros(ndof), m, fr,
        kT=KBT_300, dt=0.0002, n_steps=200000, n_equil=20000, sample_every=4,
        rng=np.random.default_rng(2),
    )
    ratio = np.mean(np.diag(np.cov(samples.T)) / np.diag(target))
    assert 0.92 < ratio < 1.08, f"coarse friction does not sample kT·K⁻¹ (variance ratio {ratio:.3f})"


# ── 5. the memory guard ─────────────────────────────────────────────────────────

def test_memory_estimate_is_quadratic_and_coarse_graining_shrinks_it_quadratically():
    assert estimate_friction_memory_gb(2000) == pytest.approx(4 * estimate_friction_memory_gb(1000))
    # k-fold coarse-graining cuts the dense dimension k-fold ⇒ k² less memory
    assert estimate_friction_memory_gb(8000, 8) == pytest.approx(estimate_friction_memory_gb(1000),
                                                                 rel=1e-6)


def test_full_m13_scale_exact_is_refused_but_coarse_is_allowed(monkeypatch):
    """A full M13 origami (≈7240 nodes) needs ≈83 GB exact — refuse it up front rather than let the
    OOM killer take the machine. The same design coarse-grained at k=8 fits in ~1 GB."""
    monkeypatch.setenv("NADOC_HYDRO_MEM_GB", "16")
    with pytest.raises(HydroMemoryError) as exc:
        check_friction_memory(7240, None)
    msg = str(exc.value)
    assert "7240 nodes" in msg
    assert "coarse" in msg.lower()          # tells the user the way out
    check_friction_memory(7240, 8)          # must NOT raise
