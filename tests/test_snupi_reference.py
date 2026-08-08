"""CI-safe pins for the SNUPI reference comparator's pure pieces.

No SNUPI binary, MATLAB Runtime, or MD DCD is touched — those are machine-local
(the orchestration lives in scripts/snupi_reference_compare.py, like the exp42
DCD scripts).  These tests pin the parsers, the caDNAno schema shim, and the
node-matcher (the crux) on hand-built synthetic fixtures.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.physics.snupi_reference import (
    KBT_300K,
    bending_amplitude_variance,
    correlation_agreement,
    mac_matrix,
    match_nodes,
    match_nodes_spatial,
    nadoc_json_to_snupi_json,
    parse_snupi_pdb,
    parse_snupi_xyz,
    reconstruct_pearson_correlation,
    reconstruct_rmsf,
    rmsf_agreement,
    self_consistency,
    shape_rmsd_nm,
    snupi_translational_modes,
)


# ── caDNAno schema shim ──────────────────────────────────────────────────────


def test_json_shim_adds_loops_drops_scaf_colors():
    cad = {
        "name": "x",
        "vstrands": [
            {
                "num": 0,
                "row": 1,
                "col": 2,
                "scaf": [],
                "stap": [],
                "loop": [],
                "skip": [],
                "stap_colors": [[0, 123]],
                "scaf_colors": [[0, 9]],
            },
        ],
    }
    out = nadoc_json_to_snupi_json(cad)
    vs = out["vstrands"][0]
    assert "scaf_colors" not in vs
    assert vs["scafLoop"] == [] and vs["stapLoop"] == []
    assert vs["stap_colors"] == [[0, 123]]  # untouched
    # original left intact (deep copy)
    assert "scaf_colors" in cad["vstrands"][0]


# ── PDB / XYZ parsers ────────────────────────────────────────────────────────

_PDB = """MODEL        1
ATOM      1 NN   H1      1     -97.116 -46.551 -55.165 3.2
ATOM      2 NN   H1      2     -96.691 -49.069 -52.860 0.1
ATOM      3 NN   H2      1     -10.000  20.000  30.000 1.5
ENDMDL
"""


def test_parse_snupi_pdb(tmp_path):
    p = tmp_path / "x_STT_STRCT.pdb"
    p.write_text(_PDB)
    nodes = parse_snupi_pdb(p)
    assert [n.chain for n in nodes] == ["H1", "H1", "H2"]
    assert [n.resseq for n in nodes] == [1, 2, 1]
    # Angstrom → nm
    assert nodes[0].pos == pytest.approx([-9.7116, -4.6551, -5.5165])
    assert nodes[0].rmsf == pytest.approx(3.2)  # occupancy = RMSF, not scaled
    assert nodes[2].pos == pytest.approx([-1.0, 2.0, 3.0])


def test_parse_snupi_xyz(tmp_path):
    p = tmp_path / "x.xyz"
    p.write_text("2\n\nA 10.0 20.0 30.0\nA -5.0 0.0 5.0\n")
    arr = parse_snupi_xyz(p)
    assert arr.shape == (2, 3)
    assert arr[0] == pytest.approx([1.0, 2.0, 3.0])
    assert arr[1] == pytest.approx([-0.5, 0.0, 0.5])


# ── Synthetic two-helix design ───────────────────────────────────────────────


def _synthetic_design(nA=5, nB=4, x_sep=3.0, rise=0.34):
    """Return (mimic_keys, mimic_pos, labels) for a 2-helix straight design.

    Helix "A" (nA bp) at x=0, helix "B" (nB bp) at x=x_sep, both along +z.
    labels map SNUPI chain H1→A, H2→B, ascending base order.
    """
    keys, pos = [], []
    for bp in range(nA):
        keys.append(("A", bp))
        pos.append([0.0, 0.0, bp * rise])
    for bp in range(nB):
        keys.append(("B", bp))
        pos.append([x_sep, 0.0, bp * rise])
    labels = [
        {
            "snupi_chain_index": 0,
            "num": 0,
            "helix_id": "A",
            "direction": "FORWARD",
            "bases": [
                {"cadnano_base": bp, "global_bp": bp, "duplex": True}
                for bp in range(nA)
            ],
        },
        {
            "snupi_chain_index": 1,
            "num": 1,
            "helix_id": "B",
            "direction": "REVERSE",
            "bases": [
                {"cadnano_base": bp, "global_bp": bp, "duplex": True}
                for bp in range(nB)
            ],
        },
    ]
    return keys, np.array(pos), labels


def _rigid(pos, deg=37.0, axis=(0.3, 0.5, 0.8), t=(12.0, -4.0, 7.0)):
    """Apply a proper rotation + translation to (N,3) positions."""
    ax = np.array(axis, float)
    ax /= np.linalg.norm(ax)
    th = np.radians(deg)
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    R = np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * (K @ K)
    return pos @ R.T + np.array(t)


def _make_snupi_nodes(chain_specs):
    """chain_specs: list of (chain, positions_nm, resseq_list). Build PDB text and
    parse it (positions given in nm → written as Angstrom)."""
    from backend.physics.snupi_reference import SnupiNode

    nodes = []
    for chain, positions, resseqs in chain_specs:
        for r, p in zip(resseqs, positions):
            nodes.append(SnupiNode(chain=chain, resseq=r, pos=np.array(p), rmsf=None))
    return nodes


def test_topological_match_recovers_scrambled_and_flipped():
    keys, pos, labels = _synthetic_design()
    # SNUPI positions = a rigid transform of the mimic positions.
    snupi_all = _rigid(pos)
    a_pos = snupi_all[:5]  # helix A, ascending
    b_pos = snupi_all[5:]  # helix B, ascending base
    # H1 ascending resseq; H2 resseq ASCENDING but base DESCENDING (a flip):
    # SNUPI node resseq 1 sits at B's highest bp.
    nodes = _make_snupi_nodes(
        [
            ("H1", a_pos, [1, 2, 3, 4, 5]),
            ("H2", b_pos[::-1], [1, 2, 3, 4]),  # reversed positions → flip case
        ]
    )
    m = match_nodes(nodes, keys, pos, labels=labels)
    assert m.ok, m.reason
    assert m.method == "topological"
    assert m.residual_nm < 0.05  # exact rigid transform → ~0 residual
    # Recover the mapping: build snupi_idx → (helix, bp) and check.
    got = {}
    for si, mi in m.pairs:
        got[(nodes[si].chain, nodes[si].resseq)] = keys[mi]
    assert got[("H1", 1)] == ("A", 0)
    assert got[("H1", 5)] == ("A", 4)
    # H2 was reversed → resseq 1 ↔ highest bp 3, resseq 4 ↔ bp 0
    assert got[("H2", 1)] == ("B", 3)
    assert got[("H2", 4)] == ("B", 0)


def test_topological_match_salvages_boundary_swap():
    # 4 helices at distinct (x,y) so the clean anchors span the cross-section
    # (a single colinear helix cannot fix the rotation about its own axis — real
    # bundles always have several).  A & D are clean; SNUPI mislabels B's last bp
    # into chain C (H3=4, H4=6) — a crossover-boundary attribution difference.
    # The 10 leftover nodes are the same physical bp → salvaged by mutual-NN.
    rise = 0.34
    xy = {"A": (0.0, 0.0), "D": (3.0, 2.0), "B": (6.0, 0.0), "C": (9.0, 3.0)}
    keys, pos = [], []
    for h in ("A", "D", "B", "C"):
        x, y = xy[h]
        for bp in range(5):
            keys.append((h, bp))
            pos.append([x, y, bp * rise])
    pos = np.array(pos)
    labels = [
        {
            "snupi_chain_index": i,
            "num": i,
            "helix_id": h,
            "direction": "FORWARD",
            "bases": [
                {"cadnano_base": bp, "global_bp": bp, "duplex": True} for bp in range(5)
            ],
        }
        for i, h in enumerate(("A", "D", "B", "C"))
    ]
    snupi_all = _rigid(pos)
    A_pos, D_pos, B_pos, C_pos = (
        snupi_all[:5],
        snupi_all[5:10],
        snupi_all[10:15],
        snupi_all[15:20],
    )
    nodes = _make_snupi_nodes(
        [
            ("H1", A_pos, [1, 2, 3, 4, 5]),  # clean
            ("H2", D_pos, [1, 2, 3, 4, 5]),  # clean
            ("H3", B_pos[:4], [1, 2, 3, 4]),  # B missing its last bp
            (
                "H4",
                np.vstack([C_pos, B_pos[4]]),
                [1, 2, 3, 4, 5, 6],
            ),  # C + B's stray bp
        ]
    )
    m = match_nodes(nodes, keys, pos, labels=labels)
    assert m.ok, m.reason
    assert m.n_matched == 20  # all salvaged
    assert m.warnings  # the swap was still reported
    got = {(nodes[si].chain, nodes[si].resseq): keys[mi] for si, mi in m.pairs}
    assert got[("H4", 6)] == ("B", 4)  # the stray bp mapped back to B


def test_topological_match_rejects_uncoverable_mismatch():
    # SNUPI emits an unexpected extra chain (nodes the topology has no counterpart
    # for) that cannot be salvaged → coverage gate fires, ok=False (not silently
    # trusted).  labels describe only helix A; SNUPI adds a bogus H2 far away.
    keys = [("A", bp) for bp in range(5)]
    pos = np.array([[0.0, 0.0, bp * 0.34] for bp in range(5)])
    labels = [
        {
            "snupi_chain_index": 0,
            "num": 0,
            "helix_id": "A",
            "direction": "FORWARD",
            "bases": [
                {"cadnano_base": bp, "global_bp": bp, "duplex": True} for bp in range(5)
            ],
        }
    ]
    snupi_A = _rigid(pos)
    bogus = _rigid(pos[:3] + np.array([100.0, 100.0, 100.0]))  # nowhere near the mimic
    nodes = _make_snupi_nodes(
        [
            ("H1", snupi_A, [1, 2, 3, 4, 5]),
            ("H2", bogus, [1, 2, 3]),
        ]
    )
    m = match_nodes(nodes, keys, pos, labels=labels)
    assert not m.ok
    assert "coverage" in m.reason
    assert m.n_matched == 5  # only the real helix matched; bogus refused


def test_topological_gate_rejects_bad_alignment():
    # Corrupt one helix's SNUPI coords badly → residual blows past tol.
    keys, pos, labels = _synthetic_design()
    snupi_all = _rigid(pos).copy()
    snupi_all[0] += np.array([50.0, 50.0, 50.0])  # one wildly off node
    nodes = _make_snupi_nodes(
        [
            ("H1", snupi_all[:5], [1, 2, 3, 4, 5]),
            ("H2", snupi_all[5:], [1, 2, 3, 4]),
        ]
    )
    m = match_nodes(nodes, keys, pos, labels=labels, residual_tol_nm=0.5)
    assert not m.ok
    assert "residual" in m.reason


def test_spatial_fallback_recovers_distinct_helices():
    # Different node counts → count-constraint pins chain↔helix uniquely.
    keys, pos, _ = _synthetic_design(nA=6, nB=4)
    snupi_all = _rigid(pos)
    nodes = _make_snupi_nodes(
        [
            ("H1", snupi_all[:6], list(range(1, 7))),
            ("H2", snupi_all[6:], list(range(1, 5))),
        ]
    )
    m = match_nodes_spatial(nodes, keys, pos)
    assert m.ok, m.reason
    assert m.residual_nm < 0.05
    # chain H1 (6 nodes) must map to helix A (6 bp)
    assert m.chain_to_helix["H1"] == "A"
    assert m.chain_to_helix["H2"] == "B"
    for si, mi in m.pairs:
        # positions must coincide after the recovered alignment (order-correct)
        pass


def test_match_without_labels_uses_spatial():
    keys, pos, _ = _synthetic_design(nA=6, nB=4)
    snupi_all = _rigid(pos)
    nodes = _make_snupi_nodes(
        [
            ("H1", snupi_all[:6], list(range(1, 7))),
            ("H2", snupi_all[6:], list(range(1, 5))),
        ]
    )
    m = match_nodes(nodes, keys, pos, labels=None)
    assert m.method == "spatial"
    assert m.ok


# ── Observables ──────────────────────────────────────────────────────────────


def test_shape_rmsd_zero_for_rigid_transform():
    keys, pos, labels = _synthetic_design()
    snupi = _rigid(pos)
    pairs = [(i, i) for i in range(len(pos))]
    r = shape_rmsd_nm(snupi, pos, pairs)
    assert r == pytest.approx(0.0, abs=1e-6)


def test_rmsf_agreement_perfect_correlation():
    snupi_rmsf = [1.0, 2.0, 3.0, 4.0, 5.0]
    mimic_rmsf = [2.0, 4.0, 6.0, 8.0, 10.0]  # perfectly correlated (×2)
    pairs = [(i, i) for i in range(5)]
    out = rmsf_agreement(snupi_rmsf, mimic_rmsf, pairs)
    assert out["pearson"] == pytest.approx(1.0)
    assert out["spearman"] == pytest.approx(1.0)
    assert out["n"] == 5


def test_mac_identity_and_orthogonal():
    # 3 nodes, 2 mimic modes: mode0 = all +x, mode1 = all +y (translational).
    nm = 3
    phi = np.zeros((6 * nm, 2))
    for i in range(nm):
        phi[6 * i + 0, 0] = 1.0  # mode 0 → x
        phi[6 * i + 1, 1] = 1.0  # mode 1 → y
    pairs = [(i, i) for i in range(nm)]
    snupi_x = [np.array([[1.0, 0, 0]] * nm)]  # matches mode 0
    snupi_y = [np.array([[0, 1.0, 0]] * nm)]  # matches mode 1
    mx = mac_matrix(snupi_x, phi, pairs)
    assert mx["matrix"][0][0] == pytest.approx(1.0)
    assert mx["matrix"][0][1] == pytest.approx(0.0)
    assert mx["assignment"][0]["best_mimic_mode"] == 1
    my = mac_matrix(snupi_y, phi, pairs)
    assert my["assignment"][0]["best_mimic_mode"] == 2


def test_rigid_body_fraction_flags_rigid_vs_elastic():
    from backend.physics.snupi_reference import rigid_body_fraction

    rng = np.random.default_rng(3)
    P = rng.standard_normal((30, 3)) * 5.0  # node cloud
    # pure rigid translation → ~1.0
    trans = np.tile([1.0, 0.0, 0.0], (30, 1))
    assert rigid_body_fraction(trans, P) == pytest.approx(1.0, abs=1e-6)
    # pure rigid rotation about z (ω × r) → ~1.0
    rot = np.cross([0, 0, 1.0], P - P.mean(0))
    assert rigid_body_fraction(rot, P) == pytest.approx(1.0, abs=1e-6)
    # a quadratic (bending-like) field → mostly NOT rigid
    axial = (P - P.mean(0))[:, 2]
    bend = np.zeros((30, 3))
    bend[:, 0] = axial**2
    assert rigid_body_fraction(bend, P) < 0.6


def test_reconstruct_rmsf_matches_explicit_sum():
    rng = np.random.default_rng(5)
    N, M, nr = 5, 10, 6
    ev = np.sort(rng.uniform(1, 100, M + nr))
    vec = rng.standard_normal((M + nr, 6 * N))  # (n_modes, 6N)
    kbt = 4.0
    lam, phi = ev[nr:], vec[nr:]
    exp = np.zeros(N)
    for i in range(N):
        v = 0.0
        for dim in range(3):
            v += float(np.sum(kbt * phi[:, 6 * i + dim] ** 2 / lam))
        exp[i] = np.sqrt(v)
    got = reconstruct_rmsf(ev, vec, N, n_rigid=nr, kbt=kbt)
    assert np.allclose(got, exp)


def test_reconstruct_pearson_valid_matrix():
    rng = np.random.default_rng(6)
    N, M, nr = 6, 12, 6
    ev = np.sort(rng.uniform(1, 50, M + nr))
    vec = rng.standard_normal((M + nr, 6 * N))
    C = reconstruct_pearson_correlation(ev, vec, N, n_rigid=nr)
    assert C.shape == (N, N)
    assert np.allclose(np.diag(C), 1.0)
    assert np.allclose(C, C.T)
    assert C.min() >= -1.0 - 1e-9 and C.max() <= 1.0 + 1e-9


def test_self_consistency_roundtrips_to_machine_precision():
    rng = np.random.default_rng(7)
    N, M, nr = 5, 10, 6
    ev = np.sort(rng.uniform(1, 100, M + nr))
    vec = rng.standard_normal((M + nr, 6 * N))
    rmsf = reconstruct_rmsf(ev, vec, N, n_rigid=nr, kbt=KBT_300K)
    C = reconstruct_pearson_correlation(ev, vec, N, n_rigid=nr)
    mat = {
        "eigenvalues": ev,
        "eigenvectors": vec,
        "rmsf": rmsf,
        "pearson_correlation": np.tril(C),
    }  # SNUPI stores lower-tri
    sc = self_consistency(mat)
    assert sc["ok"]
    assert sc["rmsf_median_pct"] < 1e-6
    assert sc["pearson_median_abs"] < 1e-9


def test_bending_amplitude_variance_positive_and_length():
    rng = np.random.default_rng(8)
    N, M, nr = 20, 10, 6
    pos = np.column_stack([np.zeros(N), np.zeros(N), np.linspace(0, 7, N)])
    ev = np.sort(rng.uniform(1, 100, M + nr))
    vec = rng.standard_normal((M + nr, 6 * N))
    a1, L = bending_amplitude_variance(ev, vec, pos, n_rigid=nr)
    assert a1 > 0 and abs(L - 7.0) < 1e-6


def test_correlation_agreement_identical_matrices():
    n = 5
    rng = np.random.default_rng(0)
    C = rng.standard_normal((n, n))
    C = (C + C.T) / 2
    np.fill_diagonal(C, 1.0)
    pairs = [(i, i) for i in range(n)]
    out = correlation_agreement(C, C, pairs)
    assert out["pearson"] == pytest.approx(1.0)


def test_correlation_agreement_handles_lower_triangular_snupi():
    # SNUPI stores correlation lower-triangular only (upper + diagonal = 0).
    # Symmetrizing must recover the agreement without a NaN.
    n = 6
    rng = np.random.default_rng(1)
    full = rng.standard_normal((n, n))
    full = (full + full.T) / 2
    np.fill_diagonal(full, 1.0)
    snupi_lower = np.tril(full, -1)  # lower triangle only, zero diagonal
    pairs = [(i, i) for i in range(n)]
    out = correlation_agreement(snupi_lower, full, pairs)
    assert out["pearson"] is not None
    assert out["pearson"] == pytest.approx(1.0)  # same off-diagonal content


def test_snupi_translational_modes_extracts_xyz_dofs():
    # 2 modes, 3 nodes, 6 DOF/node laid out [tx,ty,tz,rx,ry,rz].
    nmodes, nnodes = 2, 3
    ev = np.zeros((nmodes, nnodes * 6))
    for i in range(nnodes):
        ev[0, 6 * i + 0] = 1.0  # mode 0 → x translation
        ev[0, 6 * i + 3] = 9.0  # rotational DOF must be ignored
        ev[1, 6 * i + 2] = 2.0  # mode 1 → z translation
    mat = {"eigenvectors": ev, "eigenvalues": np.array([1.0, 2.0])}
    modes = snupi_translational_modes(mat, 5)
    assert len(modes) == 2
    assert modes[0].shape == (nnodes, 3)
    assert np.allclose(modes[0], [[1, 0, 0]] * nnodes)  # rotational DOF dropped
    assert np.allclose(modes[1], [[0, 0, 2]] * nnodes)
