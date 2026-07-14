"""Free ssDNA tails as explicit Langevin chains — phase SS-2.

**This is a NADOC extension beyond published SNUPI, and it must be described as one.**  SNUPI's
ssDNA finite element (ACS Nano 2021 15(12):20430; :func:`snupi_material.ssdna_element`) is by
construction an *end-to-end connection between two base-pair nodes*.  A free tail — an overhang, a
toehold, a dangling scaffold end — has no distal base pair, so it contributes no element, no node,
no mass and no drag to SNUPI at all.  The words "overhang" and "toehold" appear zero times in
SNUPI's docs, options file, or shipped examples.  This module adds what SNUPI structurally cannot
represent: an explicit one-bead-per-nucleotide chain that hangs off its anchor base pair and
fluctuates thermally.

**The load-bearing architectural decision (memory/project_snupi_ssdna.md, decision 1): tail DOF
live in the DYNAMICS engine ONLY.  They never enter the static stiffness matrix or the NMA.**  A
floppy tail has near-zero eigenvalues; were its DOF in the NMA operator, the 200 lowest modes would
all become tail modes and the validated duplex-core RMSF would be destroyed.  It would also
near-singularise the static shape solve.  That decision is *enforced structurally* rather than
merely observed: the tail block is assembled HERE, by the dynamics side, and is never handed to
:func:`fem_solver.build_fem_mesh`, whose ``FEMMesh`` therefore still carries duplex bp nodes only.
Langevin samples the tails naturally and correctly, and every validated static number stays
byte-identical.  If you ever want tail RMSF as an observable, take it from the trajectory.

**The chain.**  Beads are indexed in the GLOBAL dynamics DOF space: core bp nodes 0..n_bp-1 (the
mesh's own ordering, untouched), then tail beads n_bp.. .  Each tail is a chain of corotational
Euler-Bernoulli beams — anchor bp node → bead 0 → bead 1 → … — with the per-nucleotide constants of
:func:`snupi_material.ssdna_link_element`.  The beams must be COROTATIONAL, not linear: a waving
tail undergoes large rotations, and a linear beam would confine it to a harmonic well around its
initial pose (its end-to-end distance would never relax to the polymer value).  The anchor beam
also transmits the tail's force and moment back into the core node, which is how the core comes to
feel the tail's mass and drag.

Three-Layer Law: tail bead positions are Physical-layer / display state only.  They are derived
from Layer-1 topology (the strand path, via :func:`snupi_ssdna.classify_ssdna_runs`) and are never
written back to it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.core.models import Design
from backend.physics.snupi_material import (
    SS_CONTOUR_PER_NT,
    SS_PERSISTENCE_NM,
    ssdna_link_element,
)

# ── Bead physical constants ─────────────────────────────────────────────────────

# Mean nucleotide molar mass (g/mol) over A/T/G/C. Sequence-resolving this is a ≤7% effect on a
# quantity that only sets the KINETICS (the equilibrium Boltzmann distribution is mass-independent),
# so the mean is used and the per-base lookup is deliberately not done.
SS_NT_MOLAR_MASS_G = 326.95
_N_AVOGADRO = 6.02214076e23

# Rotational inertia of a nucleotide bead = m·r_g² (nm²). A nucleotide is roughly a 0.5 nm-radius
# blob → r_g² ≈ R²/2 ≈ 0.125 nm². Like the bp value (fem_solver._BP_GYRATION_NM2 = 0.5, for the
# larger duplex cross-section) this is a modeling choice: it makes the 3 rotational DOF massive, so
# there is no infinite-frequency mode, and it affects only kinetics/step size, not equilibrium.
SS_NT_GYRATION_NM2 = 0.125

# Hydrodynamic radius of an ssDNA nucleotide bead (nm). NOT the duplex value
# (snupi_dynamics.HYDRO_RADIUS_NM = 1.1 nm, half the ~2 nm B-DNA diameter): single-stranded DNA is a
# bare backbone roughly 1 nm across, so σ_ss ≈ 0.5 nm. Used for the diagonal Stokes drag here, and
# re-used by the coarse-blob hydrodynamics in SS-3 — keep it defined in ONE place.
SS_HYDRO_RADIUS_NM = 0.5

_ETA_WATER = 8.9e-4                                    # Pa·s (matches snupi_dynamics.ETA_WATER)
_sigma_m = SS_HYDRO_RADIUS_NM * 1e-9
SS_STOKES_TRANS = 6.0 * math.pi * _ETA_WATER * _sigma_m * 1e12        # pN·ns/nm
SS_STOKES_ROT = 8.0 * math.pi * _ETA_WATER * _sigma_m**3 * 1e30       # pN·nm·ns

# Mass of one nucleotide bead in the dynamics unit system (pN·ns²/nm = 1e-21 kg), matching
# snupi_dynamics.MASS_G6_TO_DYN applied to the core's SI mass matrix.
SS_NT_MASS_DYN = SS_NT_MOLAR_MASS_G * 1e-3 / _N_AVOGADRO * 1e21


# ── Data ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TailNode:
    """One ssDNA nucleotide bead. ``(helix_id, bp, direction)`` is the render-bead key, so SS-4 can
    map a simulated bead straight back onto the nucleotide the renderer draws."""
    helix_id: str
    bp: int
    direction: str
    run: int              # index of the tail run this bead belongs to
    # 0-based position along the chain measured FROM THE ANCHOR OUTWARD (0 = the nucleotide
    # covalently continuous with the anchor, n-1 = the free tip).  This is NOT 5'→3': a tail
    # anchored on its 3' side runs 3'→5' outward, and conflating the two bonded the anchor to
    # the free tip on 24 of VoltronCore's 55 tails.  See build_tail_block.
    index_in_run: int
    overhang_ids: Tuple[str, ...] = ()


@dataclass
class TailBlock:
    """The whole tail sub-system, in the GLOBAL dynamics DOF space (core nodes first).

    ``elements`` are corotational beams ``(i, j, ref, K12)`` with i/j indexing the concatenated
    ``[core bp nodes | tail beads]`` array — the same tuple shape
    :func:`fem_solver.build_corotational_elements` produces, so the same force kernel drives them.
    """
    n_bp: int                          # core node count (tail bead g gets global index n_bp + g)
    nodes: List[TailNode] = field(default_factory=list)
    positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))   # (T,3) initial, nm
    elements: List[tuple] = field(default_factory=list)
    anchors: List[int] = field(default_factory=list)   # core node index per run
    # (6T,) initial generalized coordinate of the tail beads. TRANSLATIONS ARE ZERO — `positions` is
    # already the initial (coiled) configuration — and the ROTATIONS carry the bead triads that go with
    # it. Both are needed: the element's rest state is the STRAIGHT chain, so a coiled chain whose
    # triads were left at the identity would read as bent by the angle between its bond and the rest
    # direction — an error that ACCUMULATES down the chain (bond 20 can point 120° from the rest
    # direction) and would inject enormous spurious energy. See :func:`_coil_run`.
    q0: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @property
    def n_tail(self) -> int:
        return len(self.nodes)

    @property
    def n_total(self) -> int:
        return self.n_bp + self.n_tail

    def mass_diag(self) -> np.ndarray:
        """(6T,) per-DOF mass of the tail beads, in dynamics units — appended after the core's."""
        m = np.empty(6 * self.n_tail, dtype=float)
        m.reshape(self.n_tail, 6)[:, :3] = SS_NT_MASS_DYN
        m.reshape(self.n_tail, 6)[:, 3:] = SS_NT_MASS_DYN * SS_NT_GYRATION_NM2
        return m

    def stokes_diag(self) -> np.ndarray:
        """(6T,) per-DOF diagonal Stokes friction of the tail beads at ``SS_HYDRO_RADIUS_NM`` — the
        no-hydrodynamics path. With ``hydrodynamics=True`` the tails instead join the coarse blob
        model (SS-3, :func:`snupi_hydro_coarse.build_coarse_friction`), which reproduces exactly this
        self-drag on the diagonal and adds the hydrodynamic coupling around it."""
        g = np.empty(6 * self.n_tail, dtype=float)
        g.reshape(self.n_tail, 6)[:, :3] = SS_STOKES_TRANS
        g.reshape(self.n_tail, 6)[:, 3:] = SS_STOKES_ROT
        return g

    def touched_nodes(self) -> np.ndarray:
        """Global indices of every node any tail element touches — the tail beads plus their anchor
        core nodes. The force kernel builds nodal rotations for these ONLY, so its cost scales with
        the tails, not with the (much larger) core."""
        idx = {i for (i, j, _r, _k) in self.elements for i in (i, j)}
        return np.array(sorted(idx), dtype=int)

    # Packed element arrays for the vectorised force. Built once (the element list is fixed for the
    # life of a run) and cached; `touched` is part of the key because it defines the compact
    # node indexing the force kernel works in.
    _cache: Optional[dict] = None
    _idx_i: Optional[np.ndarray] = None
    _idx_j: Optional[np.ndarray] = None

    def _kinematics(self, touched: np.ndarray) -> dict:
        if self._cache is not None and self._cache["touched_len"] == len(touched):
            return self._cache
        loc = np.full(self.n_total, -1, dtype=int)
        loc[touched] = np.arange(len(touched))
        gi = np.array([e[0] for e in self.elements], dtype=int)
        gj = np.array([e[1] for e in self.elements], dtype=int)
        self._idx_i, self._idx_j = gi, gj
        self._cache = {
            "touched_len": len(touched),
            "ei": loc[gi],
            "ej": loc[gj],
            "L0": np.array([e[2][0] for e in self.elements], dtype=float),
            # ref = (L0, E0, Rref1, Rref2). The local deformation needs Rrefᵀ (see
            # snupi_corotational._local_defo), so cache the transposes. Both are stored rather than
            # assuming Rref1 == Rref2 — they only coincide because the rest triads are identity.
            "RR1T": np.array([e[2][2].T for e in self.elements], dtype=float),
            "RR2T": np.array([e[2][3].T for e in self.elements], dtype=float),
            "K12": self.elements[0][3],       # every ssDNA link is the same element
        }
        return self._cache


# ── Initial conformation: a thermal coil, not a rod ─────────────────────────────
#
# **This is the difference between a tail that waves and a tail that does not, and it was measured,
# not assumed.**  SS-2 laid every chain out STRAIGHT from its anchor (zero elastic energy — the
# rendered pose could not be used, since its 0.34 nm duplex rise would compress every ssDNA bond ~2×)
# and reasoned that "the initial pose does not survive equilibration anyway".  On VoltronCore it does:
# a 16-nt tail starts at ⟨R_ee²⟩ = 118 nm² (a 10.9 nm rod) against the worm-like-chain equilibrium of
# 13.7 nm², and after 4000 steps (0.6 ns) it has reached only 101 nm².  It is barely moving, because
# collapsing a rod into a coil IS the slow long-wavelength mode that SS-2's own finding 3 established
# that molecular dynamics cannot converge — the very reason the pivot sampler had to exist.  Started
# as a rod, a tail stays a rod for any trajectory we can afford: wrong physics, and a figure of 55
# spikes.
#
# So start it at equilibrium instead.  The corotational energy is frame-indifferent, so rotating
# everything beyond bead k rigidly about bead k — positions AND triads together — changes the energy of
# exactly ONE element, (k, k+1), and by exactly the bend it introduces.  Walking that pivot down the
# chain with bend angles drawn from the worm-like chain's own bond-angle distribution therefore builds
# a chain that (a) has the correct tangent correlation ⟨u_i·u_{i+1}⟩ = e^{−b/L_p} by construction, so
# ⟨R_ee²⟩ starts at the WLC value; (b) keeps every bond EXACTLY at the rest length (a rigid rotation
# preserves distance), so there is still zero stretch energy; and (c) carries only a local, thermal-
# sized bend per element, with no accumulation.  It is the pivot move of :func:`pivot_sample_chain`,
# used to construct rather than to sample.


def _bend_concentration(l_p: float, b: float) -> float:
    """Concentration ``x`` of the bond-angle density ``p(cos θ) ∝ e^{x·cos θ}`` (von Mises–Fisher on the
    sphere) whose mean ``⟨cos θ⟩ = L(x) = coth x − 1/x`` equals the worm-like chain's ``e^{−b/L_p}``.
    Bisection — L is monotone. At L_p = 0.67 nm, b = 0.68 nm: ⟨cos θ⟩ = 0.362 ⇒ x ≈ 1.19."""
    target = math.exp(-b / l_p)
    lo, hi = 1e-6, 60.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if (1.0 / math.tanh(mid) - 1.0 / mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _coil_run(pos: np.ndarray, x_conc: float, rng: np.random.Generator):
    """Turn a STRAIGHT run of beads into an equilibrium worm-like coil by successive rigid pivots.

    ``pos`` (T,3) is the straight chain hanging off its anchor. Returns ``(pos, triads)`` — the coiled
    positions and the (T,3,3) bead triads that came along for the ride, which the caller hands to the
    integrator as the rotational part of ``q0``. The first bond is left alone, so the tail still
    EMERGES along the direction the renderer draws it in and only then coils away.
    """
    T = len(pos)
    triads = np.tile(np.eye(3), (max(T, 1), 1, 1))
    for k in range(T - 1):                       # pivot about bead k → bends element (k, k+1) only
        d = pos[k + 1] - pos[k]
        d /= np.linalg.norm(d)
        axis = np.cross(d, rng.standard_normal(3))       # any axis ⟂ the bond tilts it by θ,
        na = np.linalg.norm(axis)                        # and the random ⟂ choice makes φ uniform
        if na < 1e-9:
            continue
        axis /= na
        u = rng.random()                                 # inverse-CDF draw of cos θ from e^{x·cos θ}
        c = 1.0 + math.log(u + (1.0 - u) * math.exp(-2.0 * x_conc)) / x_conc
        theta = math.acos(max(-1.0, min(1.0, c)))
        Rp = _exp_so3_batch(np.array([axis * theta]))[0]
        tail = slice(k + 1, T)
        pos[tail] = pos[k] + (pos[tail] - pos[k]) @ Rp.T
        triads[tail] = Rp @ triads[tail]
    return pos, triads


# ── Builder ─────────────────────────────────────────────────────────────────────

def build_tail_block(design: Design, mesh, *, max_nt: Optional[int] = None,
                     coil: bool = True, seed: int = 0) -> TailBlock:
    """Build the explicit-chain tail sub-system for ``design`` against an already-built ``mesh``.

    ``mesh`` supplies the core node ordering and the anchors' positions; it is READ ONLY and is not
    modified — the tails never enter it (see the module docstring).  Tail runs come from
    :func:`snupi_ssdna.classify_ssdna_runs`, i.e. the nucleotide-exact strand walk, so a run is a
    tail precisely when it has exactly ONE meshed neighbour (the user's anchor rule).  Runs that are
    bridges (two anchors — SNUPI's own element, already in the mesh under ``material="snupi"``) and
    free runs (no anchor — nothing to hang from) are skipped.

    ``max_nt`` optionally truncates each tail to its first ``max_nt`` nucleotides from the anchor
    (a coarse-graining escape hatch; ``None`` = the physically correct 1 bead/nt, since ssDNA's
    persistence length is about one nucleotide of contour).

    ``coil`` (default True) starts each tail as an equilibrium worm-like COIL rather than the straight
    rod SS-2 laid out — see :func:`_coil_run` for why that is not cosmetic. ``coil=False`` restores the
    straight chain, and is for tests that want the rod as a control.
    """
    from backend.physics.snupi_ssdna import classify_ssdna_runs
    from backend.physics import snupi_corotational as cr

    node_map: Dict[Tuple[str, int], int] = {
        (nd.helix_id, nd.global_bp): i for i, nd in enumerate(mesh.nodes)
    }
    n_bp = len(mesh.nodes)
    block = TailBlock(n_bp=n_bp)

    link = ssdna_link_element()
    K12 = cr.local_beam_stiffness_12(link["l_rest"], link["ea"], link["gj"],
                                     link["ei"], link["ei"])

    helix_by_id = {h.id: h for h in design.helices}
    rng = np.random.default_rng(seed)
    x_conc = _bend_concentration(SS_PERSISTENCE_NM, SS_CONTOUR_PER_NT)
    positions: List[np.ndarray] = []
    rotations: List[np.ndarray] = []

    for run_i, run in enumerate(classify_ssdna_runs(design)):
        if run.kind != "tail":
            continue
        anchor = run.anchor
        a_idx = node_map.get((anchor.helix_id, anchor.bp))
        if a_idx is None:                      # anchor bp is not actually meshed — nothing to hang from
            continue
        # ORDER THE RUN ANCHOR-OUTWARD, which is NOT the same as 5'→3'.  `run.nts` is the strand
        # path order, and the anchor is whichever end crosses back into the embedded staple (the
        # user's rule) — so for a tail whose anchor sits on its 3' side, the 5'-most nucleotide is
        # the FREE TIP and the 3'-most is the one covalently continuous with the anchor.  Chaining
        # from nts[0] regardless would bond the anchor to the tip and fling the nucleotide that
        # actually adjoins the staple out to the far end of the coil — a backbone bond stretched by
        # the tail's whole end-to-end distance (measured on VoltronCore before this fix: 2.75 nm
        # mean, 8.18 nm worst on a 28-mer, vs 0.93 nm for the 5'-anchored tails; 24 of its 55 tails
        # are 3'-anchored).  It also mis-seeded `_tail_direction`, which reads nts[0] as "the
        # nucleotide out of the anchor", and made `max_nt` truncate from the tip instead of the
        # anchor.  Both fall out of ordering once, here.
        nts = list(run.nts) if run.anchor_5 else list(reversed(run.nts))
        if max_nt is not None:
            nts = nts[:max_nt]
        if not nts:
            continue

        a_pos = np.asarray(mesh.nodes[a_idx].position, dtype=float)
        u = _tail_direction(design, helix_by_id, anchor, nts, a_pos)

        # The chain is first laid out STRAIGHT, at the ssDNA rest bond length. That is the ELEMENTS'
        # rest state (each ref below is a straight segment along `u` with identity triads), and it is
        # not the rendered pose on purpose: the renderer spaces nucleotides at the 0.34 nm duplex rise,
        # half the ssDNA contour per nt, so every bond would start compressed ~2× and inject a large
        # spurious axial stress. `_coil_run` then bends this rod into a thermal coil by rigid pivots,
        # which preserves every bond length exactly — so the rest state, and the zero stretch energy,
        # survive the coiling.
        run_pos = np.array([a_pos + u * (SS_CONTOUR_PER_NT * (k + 1)) for k in range(len(nts))])

        prev_global = a_idx
        for k, (hid, bp, direction) in enumerate(nts):
            g = n_bp + len(block.nodes)
            block.nodes.append(TailNode(
                helix_id=hid, bp=bp, direction=direction,
                run=run_i, index_in_run=k, overhang_ids=run.overhang_ids,
            ))
            ref = cr.element_reference(
                run_pos[k] - u * SS_CONTOUR_PER_NT, run_pos[k],
                np.eye(3), np.eye(3), rest_length=link["l_rest"],
            )
            block.elements.append((prev_global, g, ref, K12))
            prev_global = g
        block.anchors.append(a_idx)

        if coil:
            run_pos, triads = _coil_run(run_pos, x_conc, rng)
        else:
            triads = np.tile(np.eye(3), (len(nts), 1, 1))
        positions.extend(run_pos)
        rotations.extend(_log_so3_batch(triads))

    block.positions = (np.array(positions, dtype=float) if positions
                       else np.zeros((0, 3), dtype=float))
    block.q0 = np.zeros(6 * block.n_tail, dtype=float)
    if rotations:
        # translations stay 0 (X0 IS the coil); the rotations are the triads the coil came with
        block.q0.reshape(block.n_tail, 6)[:, 3:] = np.array(rotations, dtype=float)
    return block


def _tail_direction(design, helix_by_id, anchor, nts, a_pos: np.ndarray) -> np.ndarray:
    """Unit direction the tail is laid out along, out of its anchor.

    Prefer the anchor → first-single-stranded-nucleotide direction taken from the design's own
    geometry (the tail then starts pointing where the renderer draws it).  Degenerate cases — the
    overhang sits on the anchor's own bp, or on a helix with no usable axis — fall back to the
    anchor helix's axis, and finally to +z, so a tail can never be built with a zero-length chord
    (which would divide by zero in the corotational frame).
    """
    p0 = _ideal_position(helix_by_id, nts[0][0], nts[0][1])
    if p0 is not None:
        d = p0 - a_pos
        n = float(np.linalg.norm(d))
        if n > 1e-6:
            return d / n
    h = helix_by_id.get(anchor.helix_id)
    if h is not None:
        d = np.array([h.axis_end.x - h.axis_start.x,
                      h.axis_end.y - h.axis_start.y,
                      h.axis_end.z - h.axis_start.z], dtype=float)
        n = float(np.linalg.norm(d))
        if n > 1e-9:
            return d / n
    return np.array([0.0, 0.0, 1.0])


def _ideal_position(helix_by_id, helix_id: str, bp: int) -> Optional[np.ndarray]:
    """Geometric axis position of ``bp`` on ``helix_id`` — the same formula the mesh builder uses
    for a duplex node. ``None`` if the helix is missing or its axis is degenerate."""
    from backend.physics.fem_solver import FEM_RISE_PER_BP

    h = helix_by_id.get(helix_id)
    if h is None:
        return None
    start = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z], dtype=float)
    end = np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z], dtype=float)
    v = end - start
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return None
    return start + (v / n) * ((bp - h.bp_start) * FEM_RISE_PER_BP)


# ── Force ───────────────────────────────────────────────────────────────────────
#
# The force is COROTATIONAL because a tail rotates through large angles: the corotational filter
# removes rigid-body motion, so swinging a straight tail about its anchor costs NOTHING (as it
# physically must) while bending it costs the ssDNA bending energy.  A linear beam would instead
# penalise the swing and pin the tail near its initial pose — its end-to-end distance could never
# relax to the polymer value, and the tails would not wave.
#
# It is also VECTORISED over elements, and that is not premature.  The Langevin loop evaluates this
# twice per step; the scalar Python element loop below costs ~19 ms per evaluation on VoltronCore's
# 571 tail beads against ~0.3 ms for the entire 7088-node duplex core, i.e. the tails would make
# every step 68x more expensive and turn a 17 s trajectory into a 20-minute one.  The scalar
# implementation is kept as `_tail_internal_force_scalar` and is the correctness oracle the
# vectorised path is pinned against (tests/test_snupi_ssdna.py).


def _exp_so3_batch(phi: np.ndarray) -> np.ndarray:
    """Rodrigues over a stack of rotation vectors ``(M,3)`` → ``(M,3,3)``. Matches
    :func:`snupi_corotational.exp_so3` including its small-angle branch."""
    a = np.linalg.norm(phi, axis=1)                      # (M,)
    small = a < 1e-12
    safe = np.where(small, 1.0, a)
    k = phi / safe[:, None]
    K = np.zeros((len(phi), 3, 3))
    K[:, 0, 1], K[:, 0, 2] = -k[:, 2], k[:, 1]
    K[:, 1, 0], K[:, 1, 2] = k[:, 2], -k[:, 0]
    K[:, 2, 0], K[:, 2, 1] = -k[:, 1], k[:, 0]
    s, c = np.sin(a)[:, None, None], (1.0 - np.cos(a))[:, None, None]
    R = np.eye(3)[None] + s * K + c * (K @ K)
    if small.any():                                      # I + skew(phi), as the scalar version does
        Ks = np.zeros((int(small.sum()), 3, 3))
        p = phi[small]
        Ks[:, 0, 1], Ks[:, 0, 2] = -p[:, 2], p[:, 1]
        Ks[:, 1, 0], Ks[:, 1, 2] = p[:, 2], -p[:, 0]
        Ks[:, 2, 0], Ks[:, 2, 1] = -p[:, 1], p[:, 0]
        R[small] = np.eye(3)[None] + Ks
    return R


def _log_so3_batch(R: np.ndarray) -> np.ndarray:
    """Inverse of :func:`_exp_so3_batch` over a stack ``(M,3,3)`` → ``(M,3)``.

    The generic branch is vectorised; the two degenerate branches (a ≈ 0 and a ≈ π, where the
    generic formula divides by sin a ≈ 0) are rare enough to defer to the scalar routine, which
    keeps this bit-for-bit consistent with :func:`snupi_corotational.log_so3` rather than
    re-deriving a second, subtly different implementation.
    """
    from backend.physics.snupi_corotational import log_so3

    tr = np.trace(R, axis1=1, axis2=2)
    c = np.clip((tr - 1.0) / 2.0, -1.0, 1.0)
    a = np.arccos(c)
    w = np.stack([R[:, 2, 1] - R[:, 1, 2],
                  R[:, 0, 2] - R[:, 2, 0],
                  R[:, 1, 0] - R[:, 0, 1]], axis=1)
    sa = np.sin(a)
    degenerate = (a < 1e-10) | (np.abs(a - np.pi) < 1e-6)
    scale = np.where(degenerate, 0.0, a / (2.0 * np.where(degenerate, 1.0, sa)))
    phi = scale[:, None] * w
    for m in np.flatnonzero(degenerate):                 # exact, and essentially never taken
        phi[m] = log_so3(R[m])
    return phi


def tail_internal_force(q: np.ndarray, X0: np.ndarray, block: TailBlock,
                        touched: Optional[np.ndarray] = None) -> np.ndarray:
    """Corotational internal elastic force of the tail chains → a flat ``(6·n_total,)`` vector.

    Vectorised over elements (see the block comment above). Nodal rotations are exponentiated only
    for the nodes the tails actually touch (:meth:`TailBlock.touched_nodes`) — the ~626 tail beads
    and anchors on VoltronCore, not all 7659 nodes.
    """
    X0 = np.asarray(X0, dtype=float)
    N = len(X0)
    qn = np.asarray(q, dtype=float).reshape(N, 6)
    if not block.elements:
        return np.zeros(6 * N, dtype=float)
    if touched is None:
        touched = block.touched_nodes()

    cache = block._kinematics(touched)
    ei, ej, L0, K12 = cache["ei"], cache["ej"], cache["L0"], cache["K12"]
    RR1T, RR2T = cache["RR1T"], cache["RR2T"]

    loc_x = X0[touched] + qn[touched, :3]                        # (T,3) current positions
    loc_R = _exp_so3_batch(qn[touched, 3:6])                     # (T,3,3) current triads

    x1, x2 = loc_x[ei], loc_x[ej]
    R1, R2 = loc_R[ei], loc_R[ej]

    # corotated frame E (cols [e1,e2,e3], e3 = chord) — snupi_corotational._cr_frame, batched
    d = x2 - x1
    Lf = np.linalg.norm(d, axis=1)
    e3 = d / Lf[:, None]
    aux = 0.5 * (R1[:, :, 0] + R2[:, :, 0])                      # Battini auxiliary vector
    e2 = np.cross(e3, aux)
    n2 = np.linalg.norm(e2, axis=1)
    bad = n2 < 1e-8                                              # chord ∥ aux → use the y-axis
    if bad.any():
        aux2 = 0.5 * (R1[bad, :, 1] + R2[bad, :, 1])
        e2[bad] = np.cross(e3[bad], aux2)
        n2[bad] = np.linalg.norm(e2[bad], axis=1)
    e2 = e2 / n2[:, None]
    e1 = np.cross(e2, e3)
    E = np.stack([e1, e2, e3], axis=2)                           # (M,3,3), columns
    ET = np.transpose(E, (0, 2, 1))

    # local deformational displacement: nodal rotations relative to the rest frame + axial stretch
    phi1 = _log_so3_batch(RR1T @ (ET @ R1))
    phi2 = _log_so3_batch(RR2T @ (ET @ R2))
    dl = np.zeros((len(ei), 12))
    dl[:, 3:6] = phi1
    dl[:, 8] = Lf - L0
    dl[:, 9:12] = phi2

    fl = dl @ K12                                                # K12 symmetric
    fg = np.empty_like(fl)
    for b in range(4):                                           # f_g = T12 · f_l, T12 = diag(E×4)
        fg[:, 3 * b:3 * b + 3] = np.einsum("mab,mb->ma", E, fl[:, 3 * b:3 * b + 3])

    f = np.zeros((N, 6))
    np.add.at(f, block._idx_i, fg[:, :6])
    np.add.at(f, block._idx_j, fg[:, 6:])
    return f.reshape(-1)


def _tail_internal_force_scalar(q: np.ndarray, X0: np.ndarray, block: TailBlock,
                                touched: Optional[np.ndarray] = None) -> np.ndarray:
    """Reference implementation of :func:`tail_internal_force`, one element at a time through the
    validated :func:`snupi_corotational._internal_force`. Kept as the correctness ORACLE for the
    vectorised path — it is ~68x slower and is not used in a job."""
    from backend.physics.snupi_corotational import _internal_force, exp_so3

    X0 = np.asarray(X0, dtype=float)
    N = len(X0)
    qn = np.asarray(q, dtype=float).reshape(N, 6)
    if touched is None:
        touched = block.touched_nodes()

    X = X0 + qn[:, :3]
    R: Dict[int, np.ndarray] = {int(n): exp_so3(qn[n, 3:6]) for n in touched}

    f = np.zeros(6 * N, dtype=float)
    for (i, j, ref, K12) in block.elements:
        fg = _internal_force(X[i], X[j], R[i], R[j], ref, K12)
        f[6 * i:6 * i + 6] += fg[:6]
        f[6 * j:6 * j + 6] += fg[6:]
    return f


def tail_omega_max(block: TailBlock) -> float:
    """Largest generalized frequency (1/ns) the tail chain introduces — a Gershgorin-style bound
    ``√(max_d K12[d,d] / m_d)`` over the link element's DOF.

    The Langevin step is auto-sized from the stiffest mode of the whole system.  The core's ω_max
    comes from an eigensolve on (K, M); the tails are not in K, so their stiffest mode has to be
    accounted for separately or a tail-driven instability would only show up as a divergence retry.
    """
    if not block.elements:
        return 0.0
    _i, _j, _ref, K12 = block.elements[0]
    m = np.empty(12, dtype=float)
    m.reshape(2, 6)[:, :3] = SS_NT_MASS_DYN
    m.reshape(2, 6)[:, 3:] = SS_NT_MASS_DYN * SS_NT_GYRATION_NM2
    return float(np.sqrt(np.max(np.abs(np.diag(K12)) / m)))


# ── Trajectory observable: the WLC oracle ───────────────────────────────────────

def wlc_mean_square_end_to_end(n_nt: int, *, l_p: float = 0.67,
                               b: float = SS_CONTOUR_PER_NT) -> float:
    """Worm-like-chain ⟨R_ee²⟩ (nm²) for a free ``n_nt``-mer:

        ⟨R²⟩ = 2·L_p·L_c·[1 − (L_p/L_c)(1 − e^{−L_c/L_p})],   L_c = n·b

    The SS-2 validation oracle. A simulated free tail must converge to this — one number that
    simultaneously validates the link element, the bead mass, the noise amplitude and the
    fluctuation–dissipation consistency of the integrator.
    """
    l_c = n_nt * b
    if l_c <= 0.0:
        return 0.0
    return float(2.0 * l_p * l_c * (1.0 - (l_p / l_c) * (1.0 - math.exp(-l_c / l_p))))


def pivot_sample_chain(n_nt: int, ei: float, *, ea: float = None, gj: float = None,
                       n_sweep: int = 15000, seed: int = 0) -> dict:
    """Equilibrium sampler for an isolated ssDNA chain — **validation only, never used in a job.**

    This exists because sampling a polymer's END-TO-END distance by molecular dynamics is a trap,
    and the trap is not obvious.  A chain's local bond angles relax in picoseconds while its
    long-wavelength bending modes relax orders of magnitude more slowly, so a Langevin run (or a
    local-move Monte Carlo) happily converges ``⟨cos θ⟩`` while leaving the global conformation
    frozen near wherever it started.  The tell is that the tangent correlation ``⟨u_i·u_{i+k}⟩``
    PLATEAUS at a finite value instead of decaying to zero, and ``⟨R_ee²⟩`` comes out several-fold
    too large.  Both happened during SS-2, and both samplers agreed with each other while being
    wrong — which is exactly why a cross-check between two *equally under-converged* methods proves
    nothing.

    The cure is the **pivot move**: rotate every node beyond node ``i`` — positions AND triads —
    rigidly about node ``i``.  The corotational energy is frame-indifferent, so everything past the
    pivot moves rigidly at zero energy change and exactly ONE element, ``(i, i+1)``, changes energy.
    The move is therefore O(1) to evaluate and decorrelates the whole conformation in a handful of
    moves.  With it the tangent correlation decays to zero, as a worm-like chain's must.

    Returns ``{"r2", "corr", "bond"}`` — ⟨R_ee²⟩ (nm²), the tangent correlation vs separation, and
    the mean bond length.  See :func:`wlc_mean_square_end_to_end` for what ``r2`` must match, and
    ``scripts/snupi_tail_calibrate.py`` (which drives this) for the calibration it produced.
    """
    from backend.physics import snupi_corotational as cr
    from backend.physics.snupi_material import SS_EA_TAUT, SS_GJ_SHORT

    ea = SS_EA_TAUT if ea is None else ea
    gj = SS_GJ_SHORT if gj is None else gj
    kT = 4.142
    b = SS_CONTOUR_PER_NT
    N = n_nt + 1

    Xr = np.zeros((N, 3))
    Xr[:, 2] = np.arange(N) * b
    K12 = cr.local_beam_stiffness_12(b, ea, gj, ei, ei)
    refs = [cr.element_reference(Xr[i], Xr[i + 1], np.eye(3), np.eye(3), rest_length=b)
            for i in range(N - 1)]

    def e_el(i, X, R):
        E, _ = cr._cr_frame(X[i], X[i + 1], R[i], R[i + 1])
        d = cr._local_defo(X[i], X[i + 1], R[i], R[i + 1], refs[i], E)
        return 0.5 * float(d @ K12 @ d)

    rng = np.random.default_rng(seed)
    X = Xr.copy()
    R = [np.eye(3) for _ in range(N)]
    Ue = np.array([e_el(i, X, R) for i in range(N - 1)])
    corr = np.zeros(max(n_nt, 2))
    cnt = np.zeros(max(n_nt, 2))
    r2s: List[float] = []
    blens: List[float] = []

    for s in range(n_sweep):
        for _ in range(N):                                   # local moves
            i = int(rng.integers(N))
            Xo, Ro = X[i].copy(), R[i].copy()
            els = [e for e in (i - 1, i) if 0 <= e < N - 1]
            old = sum(Ue[e] for e in els)
            if rng.random() < 0.5:
                X[i] = X[i] + 0.06 * rng.standard_normal(3)
            else:
                R[i] = cr.exp_so3(0.20 * rng.standard_normal(3)) @ R[i]
            new = [e_el(e, X, R) for e in els]
            if sum(new) - old < 0 or rng.random() < math.exp(-(sum(new) - old) / kT):
                for e, v in zip(els, new):
                    Ue[e] = v
            else:
                X[i], R[i] = Xo, Ro
        for _ in range(4):                                   # PIVOT moves
            i = int(rng.integers(0, N - 1))
            ax = rng.standard_normal(3)
            ax /= np.linalg.norm(ax)
            Rp = cr.exp_so3(ax * rng.normal(0.0, 0.6))
            Xn = X.copy()
            Rn = list(R)
            for j in range(i + 1, N):
                Xn[j] = X[i] + Rp @ (X[j] - X[i])
                Rn[j] = Rp @ R[j]
            new_e = e_el(i, Xn, Rn)                          # only element i changes energy
            if new_e - Ue[i] < 0 or rng.random() < math.exp(-(new_e - Ue[i]) / kT):
                X, R, Ue[i] = Xn, Rn, new_e
        if s >= n_sweep // 4 and s % 2 == 0:                 # sample after burn-in
            bv = X[1:] - X[:-1]
            bl = np.linalg.norm(bv, axis=1)
            u = bv / bl[:, None]
            for k in range(1, n_nt):
                c = (u[:-k] * u[k:]).sum(axis=1)
                corr[k] += c.sum()
                cnt[k] += len(c)
            r2s.append(float(((X[-1] - X[0]) ** 2).sum()))
            blens.append(float(bl.mean()))

    corr[1:] /= np.maximum(cnt[1:], 1)
    return {"r2": float(np.mean(r2s)), "corr": corr, "bond": float(np.mean(blens))}


def tail_end_to_end(frames: np.ndarray, block: TailBlock, run: int) -> np.ndarray:
    """Per-frame end-to-end distance (nm) of one tail: anchor bp node → the tail's last bead.
    ``frames`` is the FULL (F, n_total, 3) absolute-position stack of a tails-enabled trajectory."""
    beads = [k for k, nd in enumerate(block.nodes) if nd.run == run]
    if not beads:
        raise ValueError(f"no tail beads for run {run}")
    # `run` is the id the CLASSIFIER gave this run, so it is not a contiguous index into `anchors`
    # (bridges and free runs carry ids too, and are skipped). `anchors` is in tail-build order —
    # recover the position of this run within that order.
    order = sorted({nd.run for nd in block.nodes})
    anchor = block.anchors[order.index(run)]
    last = block.n_bp + beads[-1]
    frames = np.asarray(frames, dtype=float)
    return np.linalg.norm(frames[:, last, :] - frames[:, anchor, :], axis=1)
