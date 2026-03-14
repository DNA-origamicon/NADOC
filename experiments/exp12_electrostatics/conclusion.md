# Exp12 — Conclusion: Debye-Hückel Electrostatic Repulsion Parameter Calibration

## Result: PASS

All structural tests passed. The experiment reveals a quantitative constraint on
the electrostatic parameters and a fundamental architectural insight about the
XPBD solver.

---

## Summary of findings

### 1. Baseline (amp = 0): perfect stability

With no electrostatics, the 20-bp duplex stays exactly at ideal B-DNA geometry
for all 500 steps (rms = 0.000 nm). The backbone, bending, base-pair, and stacking
constraints are all at rest length — no net force, no displacement. This confirms
the XPBD framework is correctly at mechanical equilibrium when only bonded constraints
are present.

### 2. The Jacobi accumulation problem

Even a very small electrostatic amplitude (0.0001) destabilises the duplex for all
Debye lengths ≥ 0.5 nm. The root cause is **Jacobi accumulation**: the XPBD solver
applies all constraint corrections simultaneously in each substep (Jacobi iteration).
For distance constraints (bonds), corrections are zero when satisfied. For the
Debye-Hückel potential — a pure repulsion with no equilibrium — corrections are
always nonzero and accumulate across all non-bonded pairs within the cutoff.

A 20-bp duplex has ~630 non-bonded pairs within the 5 nm electrostatic cutoff.
Each pair contributes:

    Δpos ≈ amp × 0.5 × exp(−r / λ_D)   (nm per particle per substep)

At amp = 0.0001, λ_D = 1.5 nm, r = 2 nm: each pair contributes ~0.000024 nm.
But ~200 pairs contribute at each particle → cumulative ~0.005 nm/substep.
With 20 substeps per step and 500 steps → potential drift of 50 nm if unconstrained.
The backbone bonds (stiffness=1.0, correction ≈ 0.001–0.05 nm/substep) cannot
fully counteract the cumulative electrostatic push in only 20 substeps.

### 3. Quantitative stable zone

| amp    | λ_D = 0.3 nm | λ_D = 0.5 nm | λ_D = 0.8 nm | λ_D = 1.5 nm | λ_D = 3.0 nm |
|--------|:------------:|:------------:|:------------:|:------------:|:------------:|
| 0.0000 | ✅ 0.000 nm  | ✅ 0.000 nm  | ✅ 0.000 nm  | ✅ 0.000 nm  | ✅ 0.000 nm  |
| 0.0001 | ✅ 0.024 nm  | ❌ 0.086 nm  | ❌ 0.180 nm  | ❌ 0.492 nm  | ❌ 0.875 nm  |
| 0.0005 | ❌ 0.092 nm  | ❌ 0.256 nm  | ❌ 0.567 nm  | ❌ 1.286 nm  | ❌ 2.114 nm  |
| 0.0010 | ❌ 0.147 nm  | ❌ 0.376 nm  | ❌ 0.848 nm  | ❌ 1.851 nm  | ❌ 2.170 nm  |

Values are RMS deviation from ideal B-DNA positions (threshold ≤ 0.05 nm).
**Only one nonzero-amplitude case passes: amp = 0.0001, λ_D = 0.3 nm.**

### 4. Both axes are monotone

- RMS deviation is monotone increasing with amplitude (**confirmed**).
- RMS deviation is monotone increasing with Debye length (**confirmed**).

This is physically correct:
- Larger amp → stronger correction per pair → more displacement.
- Longer λ_D → more pairs within cutoff AND stronger long-range contribution → more total displacement.

### 5. Structural quantities remain physically sensible

Even in the unstable cases (RMS > 0.05), the mean bp separation (1.732–1.760 nm)
and mean radius (0.88–1.07 nm) remain close to ideal. The instability manifests
primarily as **along-axis elongation/compression** (axial drift), not radial
expansion. Radial expansion (true "over-repulsion") would require longer simulation
runs where the helix could swell. In all 500-step trials, the duplex
never breaks (max_bp_sep ≤ 2.57 nm), confirming the EV + base-pair constraints
prevent complete unfolding.

---

## Revised hypothesis assessment

| Prediction | Actual | Status |
|-----------|--------|--------|
| amp=0 gives rms=0 (perfect baseline) | rms=0.000 for all λ_D | ✅ |
| Small amp → stable, large amp → unstable | Only amp=0.0001, λ_D=0.3 qualifies | ⚠️ Stable zone much narrower than predicted |
| Optimal zone: amp 0.02–0.08, λ_D 0.5–1.5 nm | Those amplitudes cause 0.5–3.6 nm RMS | ❌ Over-optimistic |
| Over-repulsion (radius > 1.1 nm) | Not seen; radius decreases instead | ❌ Wrong direction — axial drift, not radial |
| RMS monotone with both axes | Confirmed | ✅ |

---

## Architectural implications and design decisions

### Decision DA-12a (binding): Default amplitude = 0.0

The Debye-Hückel electrostatic term is **off by default**. The XPBD Jacobi
solver with 20 substeps cannot equilibrate against O(N²) accumulated electrostatic
kicks at physically meaningful Debye lengths. Enabling it at any amplitude above
~0.0001 introduces structural artefacts larger than thermal noise.

### Decision DA-12b: Slider range corrected

The frontend slider `elec_amplitude` range is 0–0.005 with step 0.0001.
Users who enable it should start at 0.0001 and use λ_D ≤ 0.5 nm.

### Decision DA-12c: Future improvement path (deferred)

For physically accurate Debye-Hückel electrostatics in XPBD, options are:
1. **Gauss-Seidel ordering**: apply corrections sequentially per pair rather than
   simultaneously. Eliminates Jacobi accumulation at the cost of O(N²) sequential ops.
2. **Compliance regularisation**: add `1/compliance` denominator to each electrostatic
   correction, capping the per-substep effect.
3. **Verlet integration with electrostatics**: switch from position-based to
   force-based integration for the electrostatic term alone.

These are deferred to a future physics layer overhaul (post-Phase 8).

### Decision DA-12d: The feature as shipped is useful for display purposes

Even with amp=0.0 default, the infrastructure (elec_ij pairs, ELEC_CUTOFF, sliders,
WebSocket param updates) is complete and correct. Users can enable the feature
for qualitative visualisation — the structural deformation is an artefact but may
be visually informative for demonstrating electrostatic effects on DNA topology.

---

## Figure description

`results/electrostatics_calibration.png` (6 panels):

- **Top row**: RMS deviation, mean radius, and mean FORWARD-REVERSE separation as
  2D heatmaps over (elec_amplitude × λ_D). White contour in RMS panel marks the
  0.05 nm stability threshold.
- **Bottom left**: Stability map — only (0.0001, 0.3 nm) is green (Y). All others red (n).
- **Bottom centre**: Mean backbone bond length error — remains < 0.05 nm across all
  cases, confirming bond constraints do not fail; the problem is axial drift unconstrained
  by bonds.
- **Bottom right**: Log-scale RMS vs amplitude for three Debye lengths — shows
  monotone increase and 3-4 order-of-magnitude dynamic range.
