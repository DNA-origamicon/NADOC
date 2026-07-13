"""SNUPI base-stacking interaction — Morse "stacking element" (Phase 2, paper Fig 5c/d + Methods).

The dynamics paper models coaxial base stacking between blunt helix ends as a Morse bond between two
"stacking nodes", fitted to the all-atom PMF of the stacking distance:

    Π_sk(r) = ε [ (1 − e^{−a (r − r₀)})² − 1 ]

with the internal force = −dΠ/dr exerted along the bond. The Morse form is BISTABLE in the relevant
sense: a deep well at the stacked distance r₀ (energy −ε) that flattens to 0 as the bond is pulled
apart (unstacked) — so a competing force (the salt-dependent inter-helix electrostatic repulsion,
:mod:`snupi_electrostatics`) can pop the bond from stacked → unstacked, which is the mechanism of the
ion-responsive switch (close→open→close). Fitted parameters from the MD PMF (paper Methods, refs 60/61):
ε = 42.79 pN·nm, a = 2.668 nm⁻¹, r₀ = 0.3742 nm.

Units: nm · pN · ns (see :mod:`snupi_dynamics`) — r in nm, ε in pN·nm, a in nm⁻¹, force in pN.
The stacking topology (which node pairs stack) is an EXPLICIT input — identifying coaxial/blunt-end
stacks from a design is a topological question (Three-Layer Law: never inferred/guessed here).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Morse parameters fitted to the all-atom stacking PMF (paper Methods).
EPS_STACK = 42.79     # pN·nm — stacking dissociation energy (well depth)
A_STACK = 2.668       # nm⁻¹  — Morse shape parameter
R0_STACK = 0.3742     # nm    — equilibrium (stacked) distance


@dataclass(frozen=True)
class MorseParams:
    eps: float = EPS_STACK
    a: float = A_STACK
    r0: float = R0_STACK


def morse_energy(r: float, prm: MorseParams = MorseParams()) -> float:
    """Stacking energy Π_sk(r) (pN·nm). Minimum −ε at r₀; → 0 as r → ∞ (unstacked)."""
    e = 1.0 - math.exp(-prm.a * (r - prm.r0))
    return prm.eps * (e * e - 1.0)


def morse_dEdr(r: float, prm: MorseParams = MorseParams()) -> float:
    """dΠ_sk/dr (pN). Zero at r₀; positive for r > r₀ (restoring toward the stacked well)."""
    ex = math.exp(-prm.a * (r - prm.r0))
    return 2.0 * prm.eps * prm.a * ex * (1.0 - ex)


def morse_d2Edr2(r: float, prm: MorseParams = MorseParams()) -> float:
    """d²Π_sk/dr² (pN/nm) — the axial bond stiffness (well curvature 2εa² at r₀)."""
    ex = math.exp(-prm.a * (r - prm.r0))
    return 2.0 * prm.eps * prm.a * prm.a * ex * (2.0 * ex - 1.0)


def stacking_force(xi: np.ndarray, xj: np.ndarray, prm: MorseParams = MorseParams()):
    """Force pair ``(f_i, f_j)`` (pN, 3-vectors) on the two stacking nodes from the Morse bond
    between them. Force is central (along the bond); ``f_j = −f_i``. The internal force on the bond
    is ``−dΠ/dr``; node j feels ``−dΠ/dr`` along ``+r̂`` (pull toward the well), node i the opposite."""
    d = np.asarray(xj, float) - np.asarray(xi, float)
    r = float(np.linalg.norm(d))
    if r < 1e-9:
        return np.zeros(3), np.zeros(3)
    rh = d / r
    fmag = -morse_dEdr(r, prm)                 # −dΠ/dr : >0 attractive when r>r₀
    f_j = fmag * rh                            # on node j, along +r̂
    return -f_j, f_j


def stacking_tangent(xi: np.ndarray, xj: np.ndarray, prm: MorseParams = MorseParams()) -> np.ndarray:
    """6×6 stiffness (−∂f/∂x) block for the node pair (translational DOF only), for an implicit/Newton
    solve. Central-force Hessian: ``k_ax r̂r̂ + (Π'/r)(I − r̂r̂)`` with ``k_ax = Π''``. NOT used by the
    explicit Langevin loop (which needs only the force) — provided for the corotational shape solve."""
    d = np.asarray(xj, float) - np.asarray(xi, float)
    r = float(np.linalg.norm(d))
    if r < 1e-9:
        return np.zeros((6, 6))
    rh = d / r
    P = np.outer(rh, rh)
    k_ax = morse_d2Edr2(r, prm)
    k_perp = morse_dEdr(r, prm) / r
    Kbb = k_ax * P + k_perp * (np.eye(3) - P)    # ∂²Π/∂x_j∂x_j
    K = np.zeros((6, 6))
    K[0:3, 0:3] = Kbb; K[3:6, 3:6] = Kbb
    K[0:3, 3:6] = -Kbb; K[3:6, 0:3] = -Kbb
    return K


def is_stacked(xi: np.ndarray, xj: np.ndarray, prm: MorseParams = MorseParams(),
               cutoff_nm: float = 1.0) -> bool:
    """True if the bond is in the stacked state (distance within ``cutoff_nm`` of r₀). The Morse well
    is narrow (~0.4 nm); beyond ~1 nm the energy is within a few % of the unstacked plateau."""
    r = float(np.linalg.norm(np.asarray(xj, float) - np.asarray(xi, float)))
    return r < prm.r0 + cutoff_nm


# ── Blunt-end stacking-site detection (Phase 2 — design → Morse node pairs) ──────

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def detect_blunt_end_stacks(
    design=None,
    mesh=None,
    *,
    gap_max_nm: float = 0.85,
    facing_cos: float = -0.7,
    collinear_cos: float = 0.7,
):
    """Auto-detect coaxial **blunt-end** stacking sites → the ``[(node_i, node_j), ...]`` mesh-node
    index pairs the Morse element / :func:`snupi_dynamics.simulate_reconfiguration` consume.

    A **blunt end** is a FREE duplex terminus: a helix-end base pair that is not joined to any other
    helix — no crossover, strand continuation, or ds/ss linker wires it, i.e. the end node carries no
    INTER-helix element / spring / rigid link — and is not covalently ligated (``ForcedLigation``). Two
    blunt ends **stack** when they ABUT coaxially: their terminal bp centres sit within ``gap_max_nm``,
    their outward end-tangents point at each other (``t_i·t_j ≤ facing_cos`` — antiparallel), and the
    gap direction is collinear with those tangents (``|d̂·t_i| ≥ collinear_cos``) — a coaxial end-to-end
    junction, NOT a side-by-side bundle face (where abutting ends are parallel, not facing).

    Read-only (Three-Layer Law): derives Layer-2 geometry (node positions) + Layer-1 topology from the
    design; never writes. The outward end tangent is taken from the terminal FE segment (robust for
    curved/deformed helices). The gap window (0.34–0.85 nm) brackets the stacked rise r₀ ≈ 0.37 nm.

    Args:
        design: the ``Design`` — used to build ``mesh`` if not supplied and to read ``forced_ligations``
            (covalent joins are excluded: a switch stacks reversibly, a ligation does not). May be
            ``None`` when ``mesh`` is given and ligation exclusion isn't needed.
        mesh: a prebuilt ``FEMMesh``; built from ``design`` when ``None``.

    Returns sorted, de-duplicated ``(i, j)`` node-index pairs (``i < j``).
    """
    if mesh is None:
        if design is None:
            raise ValueError("detect_blunt_end_stacks needs a design or a prebuilt mesh")
        from backend.physics.fem_solver import build_fem_mesh
        mesh = build_fem_mesh(design)
    nodes = mesh.nodes
    if len(nodes) < 2:
        return []

    # Nodes joined ACROSS helices (crossover / strand continuation / ds-ss linker) are not free ends.
    joined: set[int] = set()
    for coll in (mesh.elements, mesh.springs, mesh.rigid_links):
        for e in coll:
            if nodes[e.node_i].helix_id != nodes[e.node_j].helix_id:
                joined.add(e.node_i)
                joined.add(e.node_j)

    # Covalently ligated ends → not a reversible stack; exclude by (helix, bp).
    lig_bp: set[tuple] = set()
    for lg in ((getattr(design, "forced_ligations", None) or []) if design is not None else []):
        for pre in ("three_prime", "five_prime"):
            h = getattr(lg, f"{pre}_helix_id", None)
            b = getattr(lg, f"{pre}_bp", None)
            if h is not None and b is not None:
                lig_bp.add((h, int(b)))

    from collections import defaultdict
    by_helix: dict[str, list[int]] = defaultdict(list)
    for idx, nd in enumerate(nodes):
        by_helix[nd.helix_id].append(idx)

    # Each helix contributes up to two free blunt ends: (node_idx, position, outward end-tangent).
    ends = []
    for hid, idxs in by_helix.items():
        if len(idxs) < 2:
            continue
        idxs.sort(key=lambda i: nodes[i].global_bp)
        for node_idx, inward_idx in ((idxs[0], idxs[1]), (idxs[-1], idxs[-2])):
            if node_idx in joined:
                continue
            if (hid, int(nodes[node_idx].global_bp)) in lig_bp:
                continue
            outward = _unit(np.asarray(nodes[node_idx].position, float)
                            - np.asarray(nodes[inward_idx].position, float))
            ends.append((node_idx, np.asarray(nodes[node_idx].position, float), outward))

    pairs: set[tuple] = set()
    for a in range(len(ends)):
        ia, pa, ta = ends[a]
        for b in range(a + 1, len(ends)):
            ib, pb, tb = ends[b]
            d = pb - pa
            dist = float(np.linalg.norm(d))
            if dist < 1e-6 or dist > gap_max_nm:
                continue
            if float(ta @ tb) > facing_cos:                       # ends must face each other
                continue
            if abs(float((d / dist) @ ta)) < collinear_cos:       # gap coaxial, not lateral
                continue
            pairs.add((ia, ib) if ia < ib else (ib, ia))
    return sorted(pairs)
