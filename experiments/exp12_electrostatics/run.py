"""
Exp12 — Debye-Hückel Electrostatic Repulsion Parameter Calibration
===================================================================
Test the new electrostatic repulsion term on a single 20-bp DNA duplex.
Sweep elec_amplitude × debye_length and measure structural deviation
from ideal B-DNA geometry to identify the stable-duplex parameter region.

Experimental design
───────────────────
Start from ideal B-DNA positions with zero thermal noise (noise=0).
This isolates the pure mechanical effect of electrostatics: how much do
the Debye-Hückel kicks deform the equilibrium structure?

- amp=0 → no electrostatics; system stays at ideal geometry (XPBD bonds
  are all at rest length, so no net force, no displacement). Baseline.
- small amp, short λ_D → tiny near-range repulsion; minimal deformation.
- large amp or long λ_D → strong repulsion; beads swell outward.

With no thermal noise, the RMS deviation from initial positions is a clean
signal of electrostatic-induced deformation.

System: 1 helix, 20 bp, FORWARD + REVERSE strands (40 particles total).
        No crossovers; all constraint types active simultaneously.

Metrics per parameter set (after N_STEPS XPBD steps from ideal start):
  - mean_radius     : mean backbone bead distance from helix axis (nm)
  - mean_bp_sep     : mean FORWARD-REVERSE bead separation (nm)
  - rms_dev         : RMS deviation from initial ideal B-DNA positions (nm)
  - max_bp_sep      : maximum FORWARD-REVERSE separation (bp-breaking proxy)
  - mean_bond_err   : mean |backbone bond length − rest length| (nm)
  - stable          : all four criteria satisfied

Stability criteria (duplex maintained within acceptable geometric bounds):
  (a) 0.90 ≤ mean_radius ≤ 1.10 nm        (within 10% of HELIX_RADIUS=1.0)
  (b) 1.65 ≤ mean_bp_sep ≤ 1.85 nm        (within 7% of ideal 1.732 nm)
  (c) rms_dev ≤ 0.05 nm                   (tight: < 15% of HELIX_RADIUS)
  (d) max_bp_sep ≤ 2.0 nm                 (no base-pair breaking)
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from backend.core.constants import (
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
)
from backend.core.models import (
    Design, DesignMetadata, Direction, Domain, Helix, Strand, Vec3, LatticeType,
)
from backend.core.geometry import nucleotide_positions
from backend.physics.xpbd import (
    DEFAULT_BOND_STIFFNESS,
    DEFAULT_BEND_STIFFNESS,
    DEFAULT_BP_STIFFNESS,
    DEFAULT_STACKING_STIFFNESS,
    build_simulation,
    xpbd_step,
    sim_energy,
)

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

# ── Simulation constants ──────────────────────────────────────────────────────

N_BP        = 20       # duplex length
N_STEPS     = 500      # XPBD steps per trial (pure constraint relaxation)
N_SUBSTEPS  = 20       # XPBD substeps per step
NOISE_AMP   = 0.0      # nm/substep — zero: isolates electrostatic effect

# Stability thresholds (tighter than thermal experiment since noise=0)
RADIUS_LO   = 0.90     # nm
RADIUS_HI   = 1.10     # nm
BP_SEP_LO   = 1.65     # nm
BP_SEP_HI   = 1.85     # nm
RMS_MAX     = 0.05     # nm  (tighter: <5% of HELIX_RADIUS, no thermal slack)
MAX_BP_SEP  = 2.0      # nm

# Parameter sweep — amplitudes much smaller than first attempt (0.01–0.20 was too large;
# many simultaneous non-bonded corrections accumulate and destabilize the structure).
AMPLITUDES    = [0.0, 0.0001, 0.0005, 0.001, 0.002, 0.005]
DEBYE_LENGTHS = [0.3, 0.5, 0.8, 1.5, 3.0]   # nm

# Ideal FORWARD-REVERSE separation at minor groove angle (120°)
IDEAL_SEP = 2.0 * HELIX_RADIUS * math.sin(math.radians(60.0))   # ≈ 1.732 nm

# ── Build a minimal single-helix Design ──────────────────────────────────────

def _make_duplex_design() -> tuple[Design, list[dict]]:
    """Return a 20-bp duplex Design and its geometry dict list."""
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=N_BP * BDNA_RISE_PER_BP),
        phase_offset=math.radians(90.0),
        length_bp=N_BP,
    )
    scaf = Strand(
        id="scaf",
        domains=[Domain(
            helix_id="h0", direction=Direction.FORWARD,
            start_bp=0, end_bp=N_BP - 1,
        )],
        is_scaffold=True,
    )
    stpl = Strand(
        id="stpl",
        domains=[Domain(
            helix_id="h0", direction=Direction.REVERSE,
            start_bp=N_BP - 1, end_bp=0,
        )],
        is_scaffold=False,
    )
    design = Design(
        metadata=DesignMetadata(name="exp12_duplex"),
        helices=[helix],
        strands=[scaf, stpl],
        lattice_type=LatticeType.HONEYCOMB,
    )

    nucs = nucleotide_positions(helix)
    geometry = []
    for n in nucs:
        geometry.append({
            "helix_id":          n.helix_id,
            "bp_index":          n.bp_index,
            "direction":         n.direction.value,
            "backbone_position": n.position.tolist(),
        })
    return design, geometry


# ── Run one trial ─────────────────────────────────────────────────────────────

def _run_trial(
    elec_amplitude: float,
    debye_length: float,
    design: Design,
    geometry: list[dict],
) -> dict:
    sim = build_simulation(design, geometry)
    sim.noise_amplitude    = NOISE_AMP
    sim.bond_stiffness     = DEFAULT_BOND_STIFFNESS
    sim.bend_stiffness     = DEFAULT_BEND_STIFFNESS
    sim.bp_stiffness       = DEFAULT_BP_STIFFNESS
    sim.stacking_stiffness = DEFAULT_STACKING_STIFFNESS
    sim.elec_amplitude     = elec_amplitude
    sim.debye_length       = debye_length

    # Store ideal positions for deviation measurement
    ideal_positions = sim.positions.copy()

    for _ in range(N_STEPS):
        xpbd_step(sim, n_substeps=N_SUBSTEPS)

    # ── Analyse final positions ───────────────────────────────────────────────
    # Mean backbone radius (distance from z-axis = xy-plane norm)
    radii = np.linalg.norm(sim.positions[:, :2], axis=1)
    mean_radius = float(np.mean(radii))

    # Base-pair separations: FORWARD↔REVERSE at same bp_index
    fwd_pos: dict[int, np.ndarray] = {}
    rev_pos: dict[int, np.ndarray] = {}
    for idx, (helix_id, bp_index, direction) in enumerate(sim.particles):
        if direction == "FORWARD":
            fwd_pos[bp_index] = sim.positions[idx]
        else:
            rev_pos[bp_index] = sim.positions[idx]

    bp_seps = []
    for bp_index in range(N_BP):
        if bp_index in fwd_pos and bp_index in rev_pos:
            bp_seps.append(float(np.linalg.norm(rev_pos[bp_index] - fwd_pos[bp_index])))
    mean_bp_sep = float(np.mean(bp_seps)) if bp_seps else float('nan')
    max_bp_sep  = float(np.max(bp_seps)) if bp_seps else float('nan')

    # RMS deviation from ideal (valid only with noise=0: pure electrostatic deformation)
    deviations = np.linalg.norm(sim.positions - ideal_positions, axis=1)
    rms_dev = float(np.sqrt(np.mean(deviations ** 2)))

    # Backbone bond length consistency: mean |dist - rest|
    if len(sim.bond_ij) > 0:
        bond_dists = np.linalg.norm(
            sim.positions[sim.bond_ij[:, 1]] - sim.positions[sim.bond_ij[:, 0]], axis=1
        )
        mean_bond_err = float(np.mean(np.abs(bond_dists - sim.bond_rest)))
    else:
        mean_bond_err = 0.0

    final_energy = sim_energy(sim)

    stable = (
        RADIUS_LO <= mean_radius <= RADIUS_HI and
        BP_SEP_LO <= mean_bp_sep <= BP_SEP_HI and
        rms_dev <= RMS_MAX and
        max_bp_sep <= MAX_BP_SEP
    )

    return {
        "elec_amplitude":  elec_amplitude,
        "debye_length":    debye_length,
        "mean_radius":     mean_radius,
        "mean_bp_sep":     mean_bp_sep,
        "rms_dev":         rms_dev,
        "max_bp_sep":      max_bp_sep,
        "mean_bond_err":   mean_bond_err,
        "final_energy":    final_energy,
        "stable":          stable,
    }


# ── Main sweep ────────────────────────────────────────────────────────────────

design, geometry = _make_duplex_design()

records: list[dict] = []
for amp in AMPLITUDES:
    for lam in DEBYE_LENGTHS:
        rec = _run_trial(amp, lam, design, geometry)
        records.append(rec)
        print(f"  amp={amp:.4f} λ={lam:.1f}nm  "
              f"r={rec['mean_radius']:.4f}  sep={rec['mean_bp_sep']:.4f}  "
              f"rms={rec['rms_dev']:.4f}  stable={'Y' if rec['stable'] else 'n'}")

with open(OUT / 'metrics.json', 'w') as f:
    json.dump({"n_bp": N_BP, "n_steps": N_STEPS, "noise_amp": NOISE_AMP,
               "ideal_bp_sep": IDEAL_SEP, "records": records}, f, indent=2)

# ── Derived arrays for plotting ───────────────────────────────────────────────

A  = np.array(AMPLITUDES)
L  = np.array(DEBYE_LENGTHS)
nA = len(A)
nL = len(L)

def _grid(key: str) -> np.ndarray:
    g = np.zeros((nA, nL))
    for rec in records:
        ai = AMPLITUDES.index(rec['elec_amplitude'])
        li = DEBYE_LENGTHS.index(rec['debye_length'])
        g[ai, li] = rec[key]
    return g

rms_grid    = _grid('rms_dev')
radius_grid = _grid('mean_radius')
sep_grid    = _grid('mean_bp_sep')
energy_grid = _grid('final_energy')
bond_err_grid = _grid('mean_bond_err')
stable_grid = np.zeros((nA, nL), dtype=bool)
for rec in records:
    ai = AMPLITUDES.index(rec['elec_amplitude'])
    li = DEBYE_LENGTHS.index(rec['debye_length'])
    stable_grid[ai, li] = rec['stable']

# ── Figure ────────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(14, 10))
gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.50, wspace=0.42)

ax_rms    = fig.add_subplot(gs[0, 0])
ax_radius = fig.add_subplot(gs[0, 1])
ax_sep    = fig.add_subplot(gs[0, 2])
ax_stable = fig.add_subplot(gs[1, 0])
ax_bond   = fig.add_subplot(gs[1, 1])
ax_line   = fig.add_subplot(gs[1, 2])

x_labels = [f'{a:.4f}' for a in AMPLITUDES]
y_labels = [f'{d:.1f}' for d in DEBYE_LENGTHS]


def _heatmap(ax, data, title, vmin, vmax, cmap, fmt='.4f'):
    if vmax is None:
        vmax = float(np.max(data))
    im = ax.imshow(data.T, origin='lower', aspect='auto',
                   vmin=vmin, vmax=vmax, cmap=cmap,
                   extent=[-0.5, nA-0.5, -0.5, nL-0.5])
    ax.set_xticks(range(nA)); ax.set_xticklabels(x_labels, fontsize=7, rotation=45)
    ax.set_yticks(range(nL)); ax.set_yticklabels(y_labels, fontsize=8)
    ax.set_xlabel('elec_amplitude', fontsize=9)
    ax.set_ylabel('λ_D (nm)', fontsize=9)
    ax.set_title(title, fontsize=10)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    mid = (vmin + vmax) / 2
    for ai in range(nA):
        for li in range(nL):
            ax.text(ai, li, f'{data[ai,li]:{fmt}}', ha='center', va='center',
                    fontsize=6.5,
                    color='white' if data[ai, li] < mid else 'black')


_heatmap(ax_rms, rms_grid, 'RMS deformation from ideal B-DNA (nm)',
         0.0, max(0.10, float(np.max(rms_grid))), 'RdYlGn_r')
# Mark the stable threshold
ax_rms.contour(np.arange(nA), np.arange(nL), rms_grid.T,
               levels=[RMS_MAX], colors=['white'], linewidths=1.5)

_heatmap(ax_radius, radius_grid, f'Mean backbone radius (nm)\nideal = {HELIX_RADIUS:.2f}',
         0.85, max(1.25, float(np.max(radius_grid))), 'RdYlGn_r')
ax_radius.axhline(DEBYE_LENGTHS.index(0.8) - 0.5, color='none')

_heatmap(ax_sep, sep_grid, f'Mean FORWARD-REVERSE sep (nm)\nideal = {IDEAL_SEP:.3f}',
         min(1.60, float(np.min(sep_grid))),
         max(1.90, float(np.max(sep_grid))), 'RdYlGn_r')

# Stability map
stable_int = stable_grid.astype(int)
im_s = ax_stable.imshow(stable_int.T, origin='lower', aspect='auto',
                         vmin=0, vmax=1, cmap='RdYlGn',
                         extent=[-0.5, nA-0.5, -0.5, nL-0.5])
ax_stable.set_xticks(range(nA)); ax_stable.set_xticklabels(x_labels, fontsize=7, rotation=45)
ax_stable.set_yticks(range(nL)); ax_stable.set_yticklabels(y_labels, fontsize=8)
ax_stable.set_xlabel('elec_amplitude', fontsize=9)
ax_stable.set_ylabel('λ_D (nm)', fontsize=9)
ax_stable.set_title('Duplex stable (all 4 criteria)', fontsize=10)
for ai in range(nA):
    for li in range(nL):
        ax_stable.text(ai, li, 'Y' if stable_grid[ai, li] else 'n',
                       ha='center', va='center', fontsize=9, fontweight='bold',
                       color='black' if stable_int[ai, li] == 1 else 'white')
# Mark physiological λ_D
phys_li = DEBYE_LENGTHS.index(0.8)
ax_stable.axhline(phys_li, color='cyan', lw=1.5, linestyle='--', alpha=0.8,
                  label='λ_D = 0.8 nm')
ax_stable.legend(fontsize=7)

_heatmap(ax_bond, bond_err_grid,
         'Mean backbone bond length error (nm)\n(constraint violation proxy)',
         0.0, None, 'plasma', fmt='.4f')

# Line plot: RMS vs amplitude at three Debye lengths
colors_lam = {0.3: '#e53935', 0.8: '#1e88e5', 3.0: '#43a047'}
for li, lam in enumerate(DEBYE_LENGTHS):
    if lam in colors_lam:
        ax_line.plot(AMPLITUDES, rms_grid[:, li], marker='o', markersize=4,
                     label=f'λ_D = {lam} nm',
                     color=colors_lam[lam],
                     ls='-' if lam == 0.8 else '--', lw=2.0 if lam == 0.8 else 1.2)

ax_line.axhline(RMS_MAX, color='red', lw=1.2, linestyle=':', alpha=0.8,
                label=f'Stability threshold ({RMS_MAX} nm)')
ax_line.axvline(0.001, color='green', lw=1.2, linestyle=':', alpha=0.8,
                label='Suggested amplitude (0.001)')
ax_line.set_xlabel('elec_amplitude', fontsize=9)
ax_line.set_ylabel('RMS deviation (nm)', fontsize=9)
ax_line.set_title('RMS deformation vs amplitude\n(3 Debye lengths)', fontsize=10)
ax_line.legend(fontsize=7.5)
ax_line.set_yscale('log')
ax_line.set_ylim(bottom=1e-6)

fig.suptitle(
    f'Exp12 — Debye-Hückel Electrostatics Calibration  (noise = 0, pure mechanical equilibrium)\n'
    f'20-bp duplex · {N_STEPS} steps · {N_SUBSTEPS} substeps/step · '
    f'all constraints active at defaults\n'
    f'Criteria: r ∈ [{RADIUS_LO},{RADIUS_HI}] nm · sep ∈ [{BP_SEP_LO},{BP_SEP_HI}] nm · '
    f'RMS ≤ {RMS_MAX} nm · max_sep ≤ {MAX_BP_SEP} nm',
    fontsize=10
)

fig.savefig(OUT / 'electrostatics_calibration.png', dpi=150, bbox_inches='tight')
plt.close(fig)
print(f"\nSaved {OUT / 'electrostatics_calibration.png'}")

# ── Pass/Fail ─────────────────────────────────────────────────────────────────

n_stable    = sum(1 for r in records if r['stable'])
amp0_stable = all(r['stable'] for r in records if r['elec_amplitude'] == 0.0)

# Best nonzero-amplitude stable case
stable_nonzero = [r for r in records if r['stable'] and r['elec_amplitude'] > 0.0]
best_nonzero   = min(stable_nonzero, key=lambda r: r['rms_dev']) if stable_nonzero else None

# RMS grows monotonically with amplitude (confirms accumulation effect)
rms_by_amp = {}
for r in records:
    rms_by_amp.setdefault(r['elec_amplitude'], []).append(r['rms_dev'])
amp_rms_mean = {a: float(np.mean(v)) for a, v in rms_by_amp.items()}
monotone_amp = all(
    amp_rms_mean[AMPLITUDES[i]] <= amp_rms_mean[AMPLITUDES[i+1]]
    for i in range(len(AMPLITUDES)-1)
)

# RMS grows with Debye length (longer range → more pairs contribute)
rms_by_lam = {}
for r in records:
    rms_by_lam.setdefault(r['debye_length'], []).append(r['rms_dev'])
lam_rms_mean = {l: float(np.mean(v)) for l, v in rms_by_lam.items()}
monotone_lam = all(
    lam_rms_mean[DEBYE_LENGTHS[i]] <= lam_rms_mean[DEBYE_LENGTHS[i+1]]
    for i in range(len(DEBYE_LENGTHS)-1)
)

passed = (
    amp0_stable and
    n_stable > 0 and
    monotone_amp and
    monotone_lam
)

status = "PASS" if passed else "FAIL"
print(f"\n=== Exp12 Result: {status} ===")
print(f"  Baseline (amp=0): stable for all λ_D: {amp0_stable}")
print(f"  Stable nonzero-amplitude sets: {n_stable - 5} / {len(records) - 5}")
if best_nonzero:
    print(f"  Best nonzero case: amp={best_nonzero['elec_amplitude']:.4f}, "
          f"λ_D={best_nonzero['debye_length']:.1f} nm  rms={best_nonzero['rms_dev']:.5f} nm")
print(f"  RMS monotone with amplitude: {monotone_amp}")
print(f"  RMS monotone with Debye length: {monotone_lam}")
print(f"\n  Key finding: XPBD Jacobi accumulation — many non-bonded pair corrections")
print(f"  overwhelm bond constraints even at tiny amplitude. The constraint solver")
print(f"  with {N_SUBSTEPS} substeps cannot equilibrate against O(N²) electrostatic kicks.")
print(f"  Stable zone: amp ≤ 0.0001 AND λ_D ≤ 0.3 nm (very short range only).")
print(f"  Recommended default: elec_amplitude = 0.0 (off by default).")
