# Exp12 — Hypothesis: Debye-Hückel Electrostatic Repulsion Parameter Calibration

## Context

Phase 5 added an XPBD physics engine with backbone bonds, bending stiffness,
base-pair bonds, and excluded-volume repulsion.  A new Debye-Hückel electrostatic
term has been added to the engine (step 7 of each XPBD substep):

    Δpos = −elec_amplitude × 0.5 × exp(−r / λ_D) × r̂

This models the screened Coulomb repulsion between negatively charged phosphate
groups in the DNA backbone, using two user-tunable parameters:

| Parameter       | Physical meaning                        | Default |
|-----------------|----------------------------------------|---------|
| elec_amplitude  | Dimensionless repulsion strength        | 0.03    |
| debye_length λ_D | Screening length (nm); ~0.8 nm at 150 mM NaCl, ~3 nm at 10 mM | 0.8 nm |

## System under test

A single 20-bp B-DNA duplex: one helix, two strands (FORWARD + REVERSE).
No crossovers. This is the simplest system that has all relevant constraint
types active simultaneously (backbone, bending, base-pair, stacking, EV,
electrostatics).

## Predictions

### 1. Without electrostatics (elec_amplitude = 0)

After N = 500 XPBD steps with moderate thermal noise (noise_amplitude = 0.02 nm):
- Mean backbone bead distance from helix axis: 1.0 ± 0.05 nm (HELIX_RADIUS)
- Mean FORWARD-REVERSE bead separation at same bp: ~1.73 nm
  (2 × HELIX_RADIUS × sin(60°) = 1.732 nm, minor groove geometry at 120°)
- RMS deviation from ideal B-DNA positions: < 0.15 nm
- Occasional inter-strand approach < 0.5 nm (EV threshold 0.3 nm too soft for
  full prevention at the geometry level; beads may brush 0.3–0.5 nm range)

### 2. With default electrostatics (elec_amplitude = 0.03, λ_D = 0.8 nm)

At the physiological Debye length of 0.8 nm, the electrostatic energy at the
typical inter-bead distance of 0.68 nm (backbone bond length) is:
    U = 0.03 × exp(−0.68/0.8) = 0.03 × 0.427 ≈ 0.013 nm/substep correction

This is a small additional push (~1.3% of the backbone bond correction
at full stiffness = 1.0). I predict:
- Mean axis distance: unchanged (1.0 ± 0.05 nm)
- Mean FORWARD-REVERSE separation: slightly increased (+0.01–0.05 nm)
- RMS deviation from ideal B-DNA: similar or marginally lower (< 0.15 nm)
- Near-approach events (dist < 0.5 nm): reduced by 20–50%

### 3. Parameter sweep predictions

Sweep: elec_amplitude ∈ {0, 0.01, 0.02, 0.05, 0.10, 0.20}
       debye_length   ∈ {0.3, 0.5, 0.8, 1.5, 3.0} nm

Key prediction: a 2D stability map will show three regions:
- **Under-repulsion** (low amplitude OR very short λ_D): insufficient separation,
  EV violations remain, duplex geometry deviates > 0.2 nm RMS from ideal.
- **Optimal zone**: amplitude 0.02–0.08, λ_D 0.5–1.5 nm. RMS deviation < 0.10 nm,
  near-approach rate < 5%, radius maintained within 2%.
- **Over-repulsion** (high amplitude AND long λ_D): helices swell outward,
  RMS deviation > 0.2 nm, mean axis distance increases > 1.1 nm, duplex widens.

The optimal physiological regime (λ_D = 0.8 nm, amplitude 0.03) should land
solidly in the optimal zone.

### 4. Duplex stability criterion

A parameter set is considered "stable-duplex-approximating" if:
  (a) Mean backbone–axis radius: 0.90–1.10 nm (within 10% of HELIX_RADIUS)
  (b) Mean FORWARD-REVERSE separation: 1.65–1.85 nm (within 7% of 1.732 nm ideal)
  (c) RMS positional deviation from B-DNA ideal: < 0.12 nm
  (d) No base-pair breaking (no FORWARD-REVERSE pair further than 2.5 nm)

## Pass/Fail threshold

The experiment passes if:
1. The default parameters (amplitude=0.03, λ_D=0.8 nm) fall in the optimal zone.
2. At least one parameter region satisfies all four duplex stability criteria.
3. The 2D stability map clearly shows the three predicted qualitative regions.
4. Over-repulsion can be demonstrated (at least one parameter set fails via criterion a or b above).
