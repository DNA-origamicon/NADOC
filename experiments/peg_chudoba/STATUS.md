# PEG port and benchmark status

Generated 2026-09-10T07:03:10.760025+00:00. **Incomplete; reproduction is not yet established.**

The CPU/CUDA port uses one chemical EO bead per repeat, the published bonded terms, temperature-dependent Mie-plus-Gaussian pair interactions, direct-neighbor exclusion, and the outer-tail removal reconstructed from Figure 4(b). Earlier raw and globally shifted runs are controls.

- Chain coverage: 39/45 states have three completed zero-tail replicas; 12 currently recommend extension.
- Pressure coverage: 5/15 states have three completed zero-tail replicas.
- Chain agreement screening: 27 states pass current sampling checks; 1 fall outside the comparison intervals. This comparison includes two simulation SEMs, plotted published intervals where available, and digitization bounds; the published error-bar type is unspecified. It does not establish exact marker agreement.
- Current engine library matches the recorded 91-check validation build: True.
- Final journal main text remains unverified; the preprint and final SI are available. The final PDF was requested from the user.
- Surface, DNA cross-interactions, and electric-field response are not validated by these bulk benchmarks.

| Temperature (K) | Completed chain states | Flagged for extension |
| --- | ---: | ---: |
| 294 | 9 | 0 |
| 320 | 6 | 0 |
| 347 | 6 | 3 |
| 361 | 5 | 2 |
| 371 | 5 | 3 |
| 381 | 4 | 2 |
| 396 | 4 | 2 |

Evidence: [chain comparisons](campaign_comparison.json), [pressure comparisons](eos_comparison.json), [test provenance](verification_zero_tail_manifest.json), [potential-curve audit](reference/potential_curve_audit.json), [radius-definition audit](reference/rg_definition_audit.json), and [published intervals](reference/published_chain_intervals.json).

1 benchmark engines were unsuspended and 12 were suspended when this snapshot was generated. Their PIDs, paths, samplers, conventions and process states are recorded in [status.json](status.json). A snapshot does not establish later liveness. See [serial scheduling](SERIAL_SCHEDULING.md); elapsed run times include pauses and are unsuitable for isolated performance comparisons.

Run `python -m experiments.peg_chudoba.compare_campaigns`, `python -m experiments.peg_chudoba.compare_eos`, then `python -m experiments.peg_chudoba.write_status` to refresh. See [README.md](README.md) for commands, limitations and investigation history.
