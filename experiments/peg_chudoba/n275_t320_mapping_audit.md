# N275, 320 K discrepancy: mapping and cross-state audit

**Updated evidence:** The subsequently completed N455/320 K cohort gives 5.81854 ± 0.04269 nm (SEM), 0.945% below the published marker, and passes sampling and marker-comparison checks. Thus the earlier increasing-discrepancy trend below applies only through N275 and does not extend to N455. Do not infer a general chain-length-dependent bias from those first four points. See [new cohort](n455_t320_completed_comparison.json) and the updated [plot](n275_t320_discrepancy.png).

The preprint methods explicitly specify chains with 275 EO units and one neutral
bead per EO. All three completed extension topologies contain exactly 275 beads
in one chain. The Figure 7 caption's molecular weight of 12,100 g/mol also agrees
with 275 × 44 g/mol. No terminal-group or chain-length correction is justified
by these checks.

The methods accompanying Figure 6 explicitly state parametric interpolation
over 294–381 K and discrete Table S1 parameters at 396 K. The current choice at
320 K follows that instruction. The earlier parameter-precision audit found
that coefficients reconstructed from Figure 5 increase the pair excluded-volume
integral; this does not provide a straightforward explanation for excessive
chain expansion. Original simulation tables remain unavailable.

| EO units | RMS radius, nm | Published marker, nm | Difference |
| ---: | ---: | ---: | ---: |
| 36 | 1.3107 | 1.2741 | +2.87% |
| 76 | 2.0207 | 1.9474 | +3.77% |
| 135 | 2.8388 | 2.6990 | +5.18% |
| 275 | 4.3380 | 3.9483 | +9.87% |

All four 320 K cohorts pass current sampling checks. The increasing discrepancy
with length suggests investigating systematic interaction or sampling effects;
it does not identify their cause. N275 at 294 K is only 0.64% above its marker.
The other N275 temperature cohorts remain flagged for insufficient sampling.

Changing the observable to arithmetic mean radius would give 4.25184 nm, still
7.69% above the marker. That would not resolve the marker discrepancy and would
contradict the existing Figure 7(a) density-moment audit supporting RMS radius.
The main text uses the word “mean”; final-source verification remains necessary.

No force parameters, mapping, allocations or running simulations were changed.
The next fidelity investigation should examine interaction conventions and
independent sampler evidence, without fitting parameters to this one marker.

[Machine-readable audit and topology hashes](n275_t320_mapping_audit.json).
Source: local preprint `reference/preprint.txt`, methods §2.1–2.2 and discussion
of Figures 6–7. See also [parameter precision](parameter_precision_audit.md) and
[radius-definition evidence](reference/rg_definition_audit.json).
