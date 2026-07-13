"""Phase 2 — base-stacking Morse element (:mod:`backend.physics.snupi_stacking`)."""
from __future__ import annotations

import numpy as np
import pytest

from backend.physics import snupi_stacking as stk


def test_morse_well_depth_and_dissociation():
    p = stk.MorseParams()
    assert stk.morse_energy(p.r0, p) == pytest.approx(-p.eps)      # min = −ε at r₀
    assert stk.morse_energy(5.0, p) == pytest.approx(0.0, abs=1e-2)  # → 0 unstacked
    assert stk.morse_energy(0.05, p) > 0.0                         # steep repulsive wall when compressed
    # compressing below r₀ produces a repulsive (push-apart) force: −dΠ/dr > 0
    assert -stk.morse_dEdr(0.2, p) > 0.0


def test_morse_force_matches_finite_difference():
    p = stk.MorseParams()
    for r in (0.2, p.r0, 0.6, 1.2):
        h = 1e-6
        fd = (stk.morse_energy(r + h, p) - stk.morse_energy(r - h, p)) / (2 * h)
        assert stk.morse_dEdr(r, p) == pytest.approx(fd, abs=1e-3)
    assert stk.morse_dEdr(p.r0, p) == pytest.approx(0.0, abs=1e-9)  # force zero at the well


def test_morse_rupture_force_is_finite_barrier():
    """The bond ruptures once the pulling force exceeds max(dΠ/dr) ≈ 57 pN at r ≈ r₀ + ln2/a — the
    finite barrier that makes the stack a bistable latch (below it stacked, above it unstacks)."""
    p = stk.MorseParams()
    rs = np.linspace(p.r0, p.r0 + 2.0, 400)
    fmax = max(stk.morse_dEdr(float(r), p) for r in rs)
    assert 50.0 < fmax < 65.0


def test_stacking_force_is_central_and_newton_paired():
    xi = np.array([0.0, 0.0, 0.0]); xj = np.array([0.6, 0.0, 0.0])
    fi, fj = stk.stacking_force(xi, xj)
    assert np.allclose(fi, -fj)                     # Newton's third law
    assert fj[0] < 0 and abs(fj[1]) < 1e-9 and abs(fj[2]) < 1e-9   # attractive along the bond (r>r₀)


def test_stacking_tangent_matches_finite_difference():
    xi = np.array([0.0, 0.0, 0.0]); xj = np.array([0.6, 0.1, 0.0])
    K = stk.stacking_tangent(xi, xj)
    base = np.concatenate(stk.stacking_force(xi, xj))
    h = 1e-6
    Knum = np.zeros((6, 6))
    for k in range(6):
        dx = np.zeros(6); dx[k] = h
        f2 = np.concatenate(stk.stacking_force(xi + dx[:3], xj + dx[3:]))
        Knum[:, k] = -(f2 - base) / h
    assert np.abs(K - Knum).max() < 1e-2


def test_is_stacked_distinguishes_states():
    assert stk.is_stacked(np.zeros(3), np.array([stk.R0_STACK, 0, 0]))
    assert not stk.is_stacked(np.zeros(3), np.array([3.0, 0, 0]))


# ── Phase 2: blunt-end stacking-site auto-detection ─────────────────────────────

def _mesh(helices, springs=None):
    """Build a synthetic FEMMesh. ``helices`` = {helix_id: [(global_bp, (x,y,z)), ...]}; node index =
    order of insertion. ``springs`` = list of (i, j) inter-node links."""
    from backend.physics.fem_solver import FEMNode, FEMMesh, FEMSpring
    nodes = []
    for hid, pts in helices.items():
        for bp, pos in pts:
            nodes.append(FEMNode(helix_id=hid, global_bp=bp, position=np.array(pos, float)))
    sp = [FEMSpring(node_i=i, node_j=j, k_trans=1.0, k_rot=0.0) for (i, j) in (springs or [])]
    return FEMMesh(nodes=nodes, elements=[], springs=sp, rigid_links=[])


def _line(hid, x0, n=5, step=0.34, y=0.0, z=0.0):
    return (hid, [(k, (x0 + k * step, y, z)) for k in range(n)])


def test_detect_blunt_stack_coaxial_abutment():
    """Two collinear helices end-to-end with a ~0.34 nm gap → the facing terminal nodes are detected
    as a stacking pair (helix A's high end, helix B's low end)."""
    a = dict([_line("A", 0.0)]); b = dict([_line("B", 1.70)])   # gap 1.70−1.36 = 0.34 nm
    mesh = _mesh({**a, **b})
    pairs = stk.detect_blunt_end_stacks(mesh=mesh)
    assert pairs == [(4, 5)]                                     # A_hi (idx4) ↔ B_lo (idx5)


def test_detect_blunt_stack_rejects_side_by_side():
    """Parallel helices pointing the SAME way (a bundle face) do NOT stack — their end tangents are
    parallel, not facing — even though the ends are close."""
    mesh = _mesh(dict([_line("A", 0.0, y=0.0), _line("B", 0.0, y=0.6)]))
    assert stk.detect_blunt_end_stacks(mesh=mesh) == []


def test_detect_blunt_stack_rejects_large_gap():
    """Collinear but too far apart → no stack."""
    mesh = _mesh(dict([_line("A", 0.0), _line("B", 3.5)]))       # gap 3.5−1.36 ≫ 0.85 nm
    assert stk.detect_blunt_end_stacks(mesh=mesh) == []


def test_detect_blunt_stack_excludes_joined_ends():
    """An end wired to another helix (crossover / continuation / linker → an inter-helix spring) is NOT
    a free blunt end, so an otherwise-abutting pair is rejected."""
    mesh = _mesh(dict([_line("A", 0.0), _line("B", 1.70)]), springs=[(4, 5)])
    assert stk.detect_blunt_end_stacks(mesh=mesh) == []


def test_detect_blunt_stack_excludes_ligated_ends():
    """A covalent ForcedLigation at the abutting ends is a permanent join, not a reversible stack →
    excluded (the switch stacks reversibly)."""
    from types import SimpleNamespace
    mesh = _mesh(dict([_line("A", 0.0), _line("B", 1.70)]))
    design = SimpleNamespace(forced_ligations=[
        SimpleNamespace(three_prime_helix_id="A", three_prime_bp=4,
                        five_prime_helix_id="B", five_prime_bp=0)])
    assert stk.detect_blunt_end_stacks(design=design, mesh=mesh) == []
