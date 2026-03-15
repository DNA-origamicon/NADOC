# Exp01 — Bond Integrity Conclusion

## Result: PASS

## What happened

Starting from ideal B-DNA geometry, all 82 backbone bonds were exactly at rest
length (0.6778 nm, std < 1e-15 nm — machine precision).

After uniform ±0.5 nm perturbation:
- Mean bond length jumped to 0.9552 nm (41% above rest)
- Max bond length reached 1.5839 nm (2.3× rest)
- Min bond length dropped to 0.2720 nm (0.4× rest)
- Max deviation from rest: 0.906 nm

After 100 × xpbd_step(n_substeps=20) with noise_amplitude=0:
- Mean bond length: 0.6783 nm (deviation from t=0: 0.00056 nm, threshold 0.01)
- Std bond length: 0.00067 nm (extremely tight)
- Max deviation from rest: 0.00243 nm (threshold 0.05)

## What this means for the physics engine

The XPBD constraint solver is working correctly. It recovers backbone geometry
from a large perturbation (up to 0.9 nm per bead) with residual error at the
sub-angstrom level (0.002 nm max). The 100-step relaxation with 20 substeps each
gives 2000 Gauss-Seidel iterations — sufficient for full convergence.

The tiny residual deviation (0.0024 nm) indicates the constraint solver is
not exactly converging to the rest length but to a consistent near-minimum. This
is expected for XPBD with stiffness=1.0 (not a hard constraint but a strong spring).

## Actionable conclusions

- The backbone constraint solver is numerically stable and physically correct.
- 20 substeps per frame is sufficient for static relaxation.
- Rest lengths from initial geometry (not BACKBONE_BOND_LENGTH constant) are used —
  this is correct since geometric positions have one uniform bond length.
- No issue here; this layer is trustworthy as a foundation.
