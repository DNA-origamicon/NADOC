"""
Physical layer — XPBD constraint engine + overdamped Langevin thermal motion.

Architecture note
─────────────────
  Topological layer  → Design (ground truth)
  Geometric layer    → NucleotidePosition (derived, read-only)
  Physical layer     → SimState / relaxed positions (display only)

Constraints
───────────
  1. Backbone bonds    — consecutive backbone beads along each strand.
  2. 2nd-neighbor      — i↔i+2 bonds along each strand for bending stiffness.
     Makes helices rod-like (persistence length); a section without crossovers
     will visibly flop rather than behave like a stiff rod.
  3. Base-pair bonds   — FORWARD↔REVERSE at the same bp_index on each helix.
     Maintains double-helix cross-sectional shape under thermal noise.
  4. Excluded volume   — hard soft repulsion between non-bonded beads < EV_DIST.
  5. Electrostatics    — Debye-Hückel screened repulsion between all non-bonded
     bead pairs within ELEC_CUTOFF.  Models the phosphate backbone charges in
     solution.  Correction magnitude decays as exp(−r/λ_D) where λ_D is the
     Debye screening length (≈0.8 nm at physiological 150 mM NaCl, ≈3 nm at
     low-salt 10 mM).

     XPBD position correction per substep (per particle, symmetric):
       Δpos = −elec_amplitude × 0.5 × exp(−r/λ_D) × r̂
     This is a purely repulsive smooth kick whose magnitude falls off
     exponentially; elec_amplitude controls overall strength (dimensionless).

Thermal motion (overdamped Langevin)
─────────────────────────────────────
  The correct model for DNA in viscous water is overdamped — inertia-free.
  We approximate this as:
      pos += noise_amplitude × N(0,1)  ← Brownian thermal kick
      [XPBD constraint projection]      ← restoring forces
  Larger noise_amplitude → more thermal motion.
  Higher stiffness values → stronger constraint restoration.

  Default: noise_amplitude=0 (pure constraint relaxation; user enables via slider).

Deferred (DTP-5)
────────────────
  Backbone angle constraints, Numba JIT.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
)
from backend.core.models import Design, Direction


# ── Physical constants ────────────────────────────────────────────────────────

# Ideal B-DNA bond length between consecutive backbone beads.
# chord = 2 R sin(twist/2); bond = √(rise² + chord²)
_CHORD = 2.0 * HELIX_RADIUS * math.sin(BDNA_TWIST_PER_BP_RAD / 2.0)
BACKBONE_BOND_LENGTH: float = math.sqrt(BDNA_RISE_PER_BP ** 2 + _CHORD ** 2)

# Minimum allowed centre-to-centre distance between non-bonded backbone beads.
# Set to 0.3 nm — allows adjacent helix beads at 2.25 nm lattice spacing
# (min approach = 2.25 - 2*1.0 = 0.25 nm) to coexist without artificial tension,
# while still preventing true bead overlap.
EXCLUDED_VOLUME_DIST: float = 0.3  # nm

# Cutoff for building the excluded-volume neighbour list.
# Fixed at 2.0 nm regardless of EV_DIST so adjacent-helix bead pairs are always
# tracked even when thermal noise momentarily pushes them apart.  The correction
# inside xpbd_step only fires when dist < EXCLUDED_VOLUME_DIST, so a large cutoff
# just means more pairs are watched (cheap) with no extra corrections applied.
EV_NEIGHBOUR_CUTOFF: float = 2.0  # nm (fixed, independent of EV_DIST)

# Maximum number of particles above which the O(N²) EV scan is skipped.
EV_MAX_PARTICLES: int = 2000

# Cutoff for building the electrostatic neighbour list.
# Debye-Hückel at r = ELEC_CUTOFF with λ_D = 0.8 nm → exp(−5/0.8) ≈ 0.002.
# At λ_D = 3 nm (low salt) → exp(−5/3) ≈ 0.19, so long-range pairs still
# contribute but are not tracked; this is an accepted approximation.
ELEC_CUTOFF: float = 5.0  # nm

# Default simulation parameters (user-adjustable at runtime via sliders).
DEFAULT_NOISE_AMPLITUDE:      float = 0.0    # nm/substep thermal kick (off by default)
DEFAULT_BOND_STIFFNESS:       float = 1.0    # backbone bond weight [0..1]
DEFAULT_BEND_STIFFNESS:       float = 0.3    # 2nd-neighbor bending weight [0..1]
DEFAULT_BP_STIFFNESS:         float = 0.5    # base-pair bond weight [0..1]
DEFAULT_STACKING_STIFFNESS:   float = 0.2    # 3rd-neighbor stacking weight [0..1]
DEFAULT_ELEC_AMPLITUDE:       float = 0.0    # Debye-Hückel strength; 0 = off (safe default)
DEFAULT_DEBYE_LENGTH:         float = 0.8    # nm; 0.8 ≈ 150 mM NaCl physiological
DEFAULT_EV_REBUILD_INTERVAL:  int   = 5      # rebuild EV + elec lists every N steps


# ── Simulation state ──────────────────────────────────────────────────────────


@dataclass
class SimState:
    """
    Mutable physics simulation state.

    All position arrays are C-contiguous float64.

    Parameters
    ----------
    positions : (N, 3) backbone bead world positions in nm.
    bond_ij   : (M, 2) int32  — consecutive backbone bond pairs.
    bond_rest : (M,) float64  — backbone bond rest lengths.
    second_bond_ij   : (P, 2) int32  — 2nd-neighbor (i↔i+2) bending bond pairs.
    second_bond_rest : (P,) float64  — 2nd-neighbor rest lengths.
    bp_bond_ij   : (Q, 2) int32  — base-pair (FORWARD↔REVERSE) bond pairs.
    bp_bond_rest : (Q,) float64  — base-pair rest lengths.
    stacking_bond_ij   : (S, 2) int32  — 3rd-neighbor stacking bond pairs.
    stacking_bond_rest : (S,) float64  — stacking bond rest lengths.
    excl_ij  : (K, 2) int32  — excluded-volume pairs.
    index_map  : {(helix_id, bp_index, dir_str) → particle_idx}
    particles  : [(helix_id, bp_index, dir_str), ...]
    step       : int
    noise_amplitude : nm/substep thermal kick magnitude (default 0 = off).
    bond_stiffness  : backbone bond compliance weight [0..1].
    bend_stiffness  : 2nd-neighbor bending weight [0..1].
    bp_stiffness    : base-pair bond weight [0..1].
    """
    positions:         np.ndarray
    bond_ij:           np.ndarray
    bond_rest:         np.ndarray
    second_bond_ij:    np.ndarray
    second_bond_rest:  np.ndarray
    bp_bond_ij:        np.ndarray
    bp_bond_rest:      np.ndarray
    stacking_bond_ij:  np.ndarray
    stacking_bond_rest: np.ndarray
    excl_ij:           np.ndarray
    elec_ij:           np.ndarray   # Debye-Hückel non-bonded pairs within ELEC_CUTOFF
    index_map:         Dict[Tuple[str, int, str], int]
    particles:         List[Tuple[str, int, str]]
    step:                int   = 0
    noise_amplitude:     float = DEFAULT_NOISE_AMPLITUDE
    bond_stiffness:      float = DEFAULT_BOND_STIFFNESS
    bend_stiffness:      float = DEFAULT_BEND_STIFFNESS
    bp_stiffness:        float = DEFAULT_BP_STIFFNESS
    stacking_stiffness:  float = DEFAULT_STACKING_STIFFNESS
    elec_amplitude:      float = DEFAULT_ELEC_AMPLITUDE
    debye_length:        float = DEFAULT_DEBYE_LENGTH
    ev_rebuild_interval: int   = DEFAULT_EV_REBUILD_INTERVAL
    # Precomputed set of all bonded pairs (min,max) for EV list filtering.
    _bonds_all: set = field(default_factory=set, repr=False, compare=False)
    rng: np.random.Generator = field(
        default_factory=np.random.default_rng,
        repr=False, compare=False,
    )


# ── Simulation builder ────────────────────────────────────────────────────────


def build_simulation(design: Design, geometry: list[dict]) -> SimState:
    """
    Construct a SimState from the active design and its geometry.

    Parameters
    ----------
    design   : Design (topological layer) — used for strand connectivity.
    geometry : list of nucleotide dicts from GET /api/design/geometry.
               Each dict must have: helix_id, bp_index, direction,
               backbone_position (3-element list, nm).

    Returns
    -------
    SimState with positions initialised to the geometric (B-DNA ideal) positions.
    All bond rest lengths are taken from actual initial inter-particle distances
    so the structure starts at near-equilibrium.
    """
    # ── Build particle array from geometry ─────────────────────────────────────
    index_map:      Dict[Tuple[str, int, str], int] = {}
    particles:      List[Tuple[str, int, str]] = []
    positions_list: list[np.ndarray] = []

    for nuc in geometry:
        key: Tuple[str, int, str] = (
            nuc["helix_id"], nuc["bp_index"], nuc["direction"]
        )
        if key not in index_map:
            idx = len(particles)
            index_map[key] = idx
            particles.append(key)
            positions_list.append(
                np.array(nuc["backbone_position"], dtype=np.float64)
            )

    n = len(particles)
    if n == 0:
        _empty = lambda: np.empty((0, 2), dtype=np.int32)
        return SimState(
            positions=np.empty((0, 3), dtype=np.float64),
            bond_ij=_empty(), bond_rest=np.empty(0, dtype=np.float64),
            second_bond_ij=_empty(), second_bond_rest=np.empty(0, dtype=np.float64),
            bp_bond_ij=_empty(), bp_bond_rest=np.empty(0, dtype=np.float64),
            stacking_bond_ij=_empty(), stacking_bond_rest=np.empty(0, dtype=np.float64),
            excl_ij=_empty(), elec_ij=_empty(),
            index_map=index_map, particles=particles,
        )

    positions = np.array(positions_list, dtype=np.float64)  # (N, 3)

    # ── Walk each strand in 5'→3' order to build an ordered path ──────────────
    # strand_path = ordered list of particle indices for each strand.
    # We use these paths for both backbone bonds (consecutive) and
    # 2nd-neighbor bonds (skip-1 pairs).

    bonds_set:        set[tuple[int, int]] = set()
    bond_pairs:       list[tuple[int, int, float]] = []
    second_bonds_set: set[tuple[int, int]] = set()
    second_bond_pairs: list[tuple[int, int, float]] = []

    def _rest(ia: int, ib: int) -> float:
        return float(np.linalg.norm(positions[ib] - positions[ia]))

    def _add_backbone_bond(ia: int, ib: int) -> None:
        pair = (min(ia, ib), max(ia, ib))
        if pair in bonds_set:
            return
        bonds_set.add(pair)
        # Crossover bonds (different helix_id) must use BACKBONE_BOND_LENGTH as
        # rest length — the physical phosphodiester backbone is ~0.68 nm long
        # regardless of how far apart the helices are in the initial geometry.
        # Using the geometric distance (~4 nm) would set the rest at a relaxed
        # inter-helix distance, creating zero restoring force at the junction.
        if particles[ia][0] != particles[ib][0]:
            rest = BACKBONE_BOND_LENGTH
        else:
            rest = _rest(ia, ib)
        bond_pairs.append((ia, ib, rest))

    def _add_second_bond(ia: int, ib: int) -> None:
        # 2nd-neighbor bonds only within the same helix — bending stiffness is
        # not physically meaningful across a crossover junction.
        if particles[ia][0] != particles[ib][0]:
            return
        pair = (min(ia, ib), max(ia, ib))
        if pair in second_bonds_set or pair in bonds_set:
            return
        second_bonds_set.add(pair)
        second_bond_pairs.append((ia, ib, _rest(ia, ib)))

    stacking_bonds_set:  set[tuple[int, int]] = set()
    stacking_bond_pairs: list[tuple[int, int, float]] = []

    def _add_stacking_bond(ia: int, ib: int) -> None:
        # 3rd-neighbor bonds only within the same helix — models base stacking.
        if particles[ia][0] != particles[ib][0]:
            return
        pair = (min(ia, ib), max(ia, ib))
        if pair in stacking_bonds_set or pair in second_bonds_set or pair in bonds_set:
            return
        stacking_bonds_set.add(pair)
        stacking_bond_pairs.append((ia, ib, _rest(ia, ib)))

    for strand in design.strands:
        strand_path: list[int] = []

        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)

            if domain.direction == Direction.FORWARD:
                bp_order = range(lo, hi + 1)
            else:
                bp_order = range(hi, lo - 1, -1)

            d_str = domain.direction.value
            for bp in bp_order:
                ia = index_map.get((domain.helix_id, bp, d_str))
                if ia is not None:
                    strand_path.append(ia)

        # Backbone bonds: consecutive pairs along 5'→3' path.
        for k in range(len(strand_path) - 1):
            _add_backbone_bond(strand_path[k], strand_path[k + 1])

        # 2nd-neighbor (bending) bonds: skip-1 pairs along 5'→3' path.
        for k in range(len(strand_path) - 2):
            _add_second_bond(strand_path[k], strand_path[k + 2])

        # 3rd-neighbor (stacking) bonds: skip-2 pairs along 5'→3' path.
        for k in range(len(strand_path) - 3):
            _add_stacking_bond(strand_path[k], strand_path[k + 3])

    def _to_arrays(pairs: list[tuple[int, int, float]]) -> tuple[np.ndarray, np.ndarray]:
        if pairs:
            ij   = np.array([(a, b) for a, b, _ in pairs], dtype=np.int32)
            rest = np.array([r for _, _, r in pairs],       dtype=np.float64)
        else:
            ij   = np.empty((0, 2), dtype=np.int32)
            rest = np.empty(0,       dtype=np.float64)
        return ij, rest

    bond_ij,          bond_rest          = _to_arrays(bond_pairs)
    second_bond_ij,   second_bond_rest   = _to_arrays(second_bond_pairs)
    stacking_bond_ij, stacking_bond_rest = _to_arrays(stacking_bond_pairs)

    # ── Base-pair bonds (FORWARD↔REVERSE at same helix + bp_index) ────────────
    # Group existing particles by (helix_id, bp_index) → {dir_str: idx}.
    helix_bp_map: dict[tuple[str, int], dict[str, int]] = {}
    for idx, (helix_id, bp_index, direction) in enumerate(particles):
        key2 = (helix_id, bp_index)
        if key2 not in helix_bp_map:
            helix_bp_map[key2] = {}
        helix_bp_map[key2][direction] = idx

    bp_bond_pairs: list[tuple[int, int, float]] = []
    bp_bonds_set:  set[tuple[int, int]] = set()

    for (helix_id, bp_index), dir_map in helix_bp_map.items():
        ia = dir_map.get("FORWARD")
        ib = dir_map.get("REVERSE")
        if ia is not None and ib is not None:
            pair = (min(ia, ib), max(ia, ib))
            if pair not in bp_bonds_set and pair not in bonds_set:
                bp_bonds_set.add(pair)
                bp_bond_pairs.append((ia, ib, _rest(ia, ib)))

    bp_bond_ij, bp_bond_rest = _to_arrays(bp_bond_pairs)

    # ── Excluded-volume and electrostatic neighbour lists ──────────────────────
    all_bonds = bonds_set | second_bonds_set | bp_bonds_set | stacking_bonds_set
    excl_list: list[tuple[int, int]] = []
    elec_list: list[tuple[int, int]] = []

    if n <= EV_MAX_PARTICLES:
        ev_cutoff_sq   = EV_NEIGHBOUR_CUTOFF ** 2
        elec_cutoff_sq = ELEC_CUTOFF ** 2
        for i in range(n):
            for j in range(i + 1, n):
                if (i, j) in all_bonds:
                    continue
                d  = positions[j] - positions[i]
                d2 = float(d[0]*d[0] + d[1]*d[1] + d[2]*d[2])
                if d2 < ev_cutoff_sq:
                    excl_list.append((i, j))
                if d2 < elec_cutoff_sq:
                    elec_list.append((i, j))

    excl_ij = (np.array(excl_list, dtype=np.int32) if excl_list
               else np.empty((0, 2), dtype=np.int32))
    elec_ij = (np.array(elec_list, dtype=np.int32) if elec_list
               else np.empty((0, 2), dtype=np.int32))

    sim = SimState(
        positions=positions,
        bond_ij=bond_ij,                 bond_rest=bond_rest,
        second_bond_ij=second_bond_ij,   second_bond_rest=second_bond_rest,
        bp_bond_ij=bp_bond_ij,           bp_bond_rest=bp_bond_rest,
        stacking_bond_ij=stacking_bond_ij, stacking_bond_rest=stacking_bond_rest,
        excl_ij=excl_ij, elec_ij=elec_ij,
        index_map=index_map,
        particles=particles,
    )
    sim._bonds_all = all_bonds
    return sim


# ── EV neighbour list rebuild ─────────────────────────────────────────────────


def _rebuild_nonbonded_lists_inplace(sim: SimState) -> None:
    """
    Recompute the excluded-volume and electrostatic neighbour lists.

    Called every sim.ev_rebuild_interval steps so that beads that have drifted
    into each other's neighbourhood are tracked and repelled.  Without this,
    the static list built at construction time misses pairs that approach under
    thermal noise, allowing helix interpenetration.

    Complexity: O(N²) with numpy vectorisation — fast for N ≤ EV_MAX_PARTICLES.
    """
    n = len(sim.positions)
    if n > EV_MAX_PARTICLES or n < 2:
        return

    ev_cutoff_sq   = EV_NEIGHBOUR_CUTOFF ** 2
    elec_cutoff_sq = ELEC_CUTOFF ** 2

    i_idx, j_idx = np.triu_indices(n, k=1)
    d  = sim.positions[j_idx] - sim.positions[i_idx]  # (K, 3)
    d2 = (d * d).sum(axis=1)                           # (K,)

    excl_pairs: list[tuple[int, int]] = []
    elec_pairs: list[tuple[int, int]] = []

    for ci in np.where(d2 < elec_cutoff_sq)[0]:
        ia, ib = int(i_idx[ci]), int(j_idx[ci])
        if (ia, ib) in sim._bonds_all:
            continue
        if d2[ci] < ev_cutoff_sq:
            excl_pairs.append((ia, ib))
        elec_pairs.append((ia, ib))

    sim.excl_ij = (np.array(excl_pairs, dtype=np.int32) if excl_pairs
                   else np.empty((0, 2), dtype=np.int32))
    sim.elec_ij = (np.array(elec_pairs, dtype=np.int32) if elec_pairs
                   else np.empty((0, 2), dtype=np.int32))


# ── XPBD step ─────────────────────────────────────────────────────────────────


def xpbd_step(sim: SimState, n_substeps: int = 10) -> None:
    """
    Perform one XPBD update (n_substeps Gauss-Seidel iterations).

    Modifies sim.positions in-place.  Increments sim.step by one.

    Each substep:
      1. Apply Gaussian thermal noise (if sim.noise_amplitude > 0).
      2. Project backbone bond constraints.
      3. Project 2nd-neighbor (bending) constraints.
      4. Project base-pair constraints.
      5. Project excluded-volume constraints.

    Stiffness parameters (0..1) scale the correction factor:
      fac = stiffness × 0.5 × (dist − rest) / dist
    At stiffness=1 this is the full XPBD correction per substep.
    At stiffness=0 the constraint is not enforced (fully floppy).
    """
    # Periodically rebuild the EV neighbour list so beads that have drifted
    # closer under thermal noise are tracked before penetration occurs.
    if sim.step > 0 and sim.step % sim.ev_rebuild_interval == 0:
        _rebuild_nonbonded_lists_inplace(sim)

    pos = sim.positions
    n   = len(pos)

    for _ in range(n_substeps):

        # ── 1. Thermal kick (overdamped Langevin noise) ────────────────────────
        if sim.noise_amplitude > 0.0 and n > 0:
            pos += sim.noise_amplitude * sim.rng.standard_normal((n, 3))

        # ── 2. Backbone bond constraints ───────────────────────────────────────
        if len(sim.bond_ij) > 0 and sim.bond_stiffness > 0.0:
            ai = sim.bond_ij[:, 0]
            bi = sim.bond_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            valid = dist > 1e-12
            fac   = np.zeros(len(sim.bond_ij))
            fac[valid] = (
                sim.bond_stiffness * 0.5
                * (dist[valid] - sim.bond_rest[valid]) / dist[valid]
            )
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

        # ── 3. 2nd-neighbor (bending) bond constraints ─────────────────────────
        if len(sim.second_bond_ij) > 0 and sim.bend_stiffness > 0.0:
            ai = sim.second_bond_ij[:, 0]
            bi = sim.second_bond_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            valid = dist > 1e-12
            fac   = np.zeros(len(sim.second_bond_ij))
            fac[valid] = (
                sim.bend_stiffness * 0.5
                * (dist[valid] - sim.second_bond_rest[valid]) / dist[valid]
            )
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

        # ── 4. Base-stacking (3rd-neighbor) bond constraints ──────────────────
        if len(sim.stacking_bond_ij) > 0 and sim.stacking_stiffness > 0.0:
            ai = sim.stacking_bond_ij[:, 0]
            bi = sim.stacking_bond_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            valid = dist > 1e-12
            fac   = np.zeros(len(sim.stacking_bond_ij))
            fac[valid] = (
                sim.stacking_stiffness * 0.5
                * (dist[valid] - sim.stacking_bond_rest[valid]) / dist[valid]
            )
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

        # ── 5. Base-pair bond constraints ──────────────────────────────────────
        if len(sim.bp_bond_ij) > 0 and sim.bp_stiffness > 0.0:
            ai = sim.bp_bond_ij[:, 0]
            bi = sim.bp_bond_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            valid = dist > 1e-12
            fac   = np.zeros(len(sim.bp_bond_ij))
            fac[valid] = (
                sim.bp_stiffness * 0.5
                * (dist[valid] - sim.bp_bond_rest[valid]) / dist[valid]
            )
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

        # ── 6. Excluded-volume constraints ─────────────────────────────────────
        if len(sim.excl_ij) > 0:
            ai = sim.excl_ij[:, 0]
            bi = sim.excl_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            active = (dist < EXCLUDED_VOLUME_DIST) & (dist > 1e-12)
            fac    = np.zeros(len(sim.excl_ij))
            fac[active] = (
                0.5 * (dist[active] - EXCLUDED_VOLUME_DIST) / dist[active]
            )
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

        # ── 7. Debye-Hückel electrostatic repulsion ────────────────────────────
        # Correction per particle pair:
        #   Δpos = −elec_amplitude × 0.5 × exp(−r/λ_D) × r̂
        # Negative sign → always repulsive (pushes beads apart).
        # Exponential decay means distant pairs contribute negligibly.
        if len(sim.elec_ij) > 0 and sim.elec_amplitude > 0.0:
            ai   = sim.elec_ij[:, 0]
            bi   = sim.elec_ij[:, 1]
            d    = pos[bi] - pos[ai]
            dist = np.linalg.norm(d, axis=1)
            valid = dist > 1e-12
            fac   = np.zeros(len(sim.elec_ij))
            fac[valid] = (
                -sim.elec_amplitude * 0.5
                * np.exp(-dist[valid] / sim.debye_length)
                / dist[valid]
            )
            corr = fac[:, np.newaxis] * d
            np.add.at(pos, ai,  corr)
            np.add.at(pos, bi, -corr)

    sim.step += 1


# ── Energy / diagnostics ──────────────────────────────────────────────────────


def sim_energy(sim: SimState) -> float:
    """
    Total squared constraint violation energy (all bond types + EV).

    Returns float >= 0.  Zero means all constraints are exactly satisfied.
    """
    pos = sim.positions
    energy = 0.0

    for ij, rest in [
        (sim.bond_ij,           sim.bond_rest),
        (sim.second_bond_ij,    sim.second_bond_rest),
        (sim.bp_bond_ij,        sim.bp_bond_rest),
        (sim.stacking_bond_ij,  sim.stacking_bond_rest),
    ]:
        if len(ij) > 0:
            dist = np.linalg.norm(pos[ij[:, 1]] - pos[ij[:, 0]], axis=1)
            energy += float(np.sum((dist - rest) ** 2))

    if len(sim.excl_ij) > 0:
        dist = np.linalg.norm(
            pos[sim.excl_ij[:, 1]] - pos[sim.excl_ij[:, 0]], axis=1
        )
        viol = dist - EXCLUDED_VOLUME_DIST
        energy += float(np.sum(viol[viol < 0] ** 2))

    # Electrostatic energy: Σ exp(−r/λ_D) over all elec pairs (Yukawa sum).
    if len(sim.elec_ij) > 0 and sim.elec_amplitude > 0.0:
        dist = np.linalg.norm(
            pos[sim.elec_ij[:, 1]] - pos[sim.elec_ij[:, 0]], axis=1
        )
        valid = dist > 1e-12
        energy += float(sim.elec_amplitude
                        * np.sum(np.exp(-dist[valid] / sim.debye_length)))

    return energy


# ── Serialisation helpers ─────────────────────────────────────────────────────


def positions_to_updates(sim: SimState) -> list[dict]:
    """
    Serialise current particle positions to a JSON-safe list of update dicts.

    Returns
    -------
    list of {"helix_id", "bp_index", "direction", "backbone_position": [x,y,z]}
    """
    result = []
    for idx, (helix_id, bp_index, direction) in enumerate(sim.particles):
        result.append({
            "helix_id":          helix_id,
            "bp_index":          bp_index,
            "direction":         direction,
            "backbone_position": sim.positions[idx].tolist(),
        })
    return result
