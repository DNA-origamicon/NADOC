# N275, 320 K: sensitivity to discarded early samples

The same three completed extension trajectories were analyzed with four discard
fractions. The published marker is 3.94832 nm.

| Discarded | RMS radius ± SEM, nm | Minimum ESS | R-hat | Overlaps plotted interval with allowances |
| ---: | ---: | ---: | ---: | :--- |
| 10% | 4.33802 ± 0.02418 | 631 | 1.00089 | No |
| 25% | 4.33822 ± 0.02311 | 521 | 1.00078 | No |
| 50% | 4.30307 ± 0.02732 | 399 | 1.00025 | Yes |
| 75% | 4.33747 ± 0.03558 | 189 | 1.00011 | No |

The radius remains roughly 9–10% above the published marker under all four
choices, and each subset passes the current sampling checks. This does not
suggest a simple decay from an expanded starting configuration toward the
published marker over these trajectories.

However, the binary plotted-interval comparison is sensitive to the discard
choice: retaining only the last half overlaps after including two simulation
SEMs and the digitization allowance. Therefore the marker discrepancy is robust
to this check, but failure of that broader comparison is not universal. Retain
the predefined 10% analysis rather than selecting a discard fraction to pass.

These estimates use overlapping data and are not independent replications.
Neither discard stability nor R-hat proves equilibrium or identifies the source
of the discrepancy. No simulation inputs or model parameters were changed.

[Numerical results and source directories](n275_t320_discard_audit.json).
