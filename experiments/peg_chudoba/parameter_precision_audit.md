# Figure 5 parameter precision audit

The plotted fit curves contain slightly different coefficients than the rounded Table 2 expressions. Vector coordinates and axes were inspected directly in the preprint. No polymer-size observations were used to reconstruct these curves.

| T (K) | Table 2 pair B₂ (nm³) | Figure 5 pair B₂ (nm³) | Change |
| ---: | ---: | ---: | ---: |
| 294 | 0.055708 | 0.056114 | +0.73% |
| 320 | 0.043911 | 0.044510 | +1.37% |
| 347 | 0.030165 | 0.030982 | +2.71% |
| 361 | 0.022687 | 0.023618 | +4.10% |
| 371 | 0.017302 | 0.018311 | +5.83% |
| 381 | 0.011944 | 0.013028 | +9.08% |

The reconstructed curves increase the two-bead excluded-volume integral across all six temperatures. That direction does not offer a straightforward explanation for simulations already producing somewhat larger chains than the published markers. This is a qualitative inference, not a prediction of polymer radius; pair B₂ is not the polymer osmotic virial coefficient.

Decision: retain the printed Table 2 model. Do not introduce reconstructed curve coefficients as a benchmark fit. Final paper/original tables remain needed to establish simulation parameter precision. At 396 K the existing discrete SI convention is unaffected.

[Source coordinates, reconstructed coefficients, residuals and quadrature results](reference/parameter_curve_audit.json). Reproduce with `.venv/bin/python -m experiments.peg_chudoba.audit_parameter_curves`.
