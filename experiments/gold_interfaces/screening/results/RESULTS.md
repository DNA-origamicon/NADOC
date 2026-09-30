# Explicit gold versus existing Debye screening tests

## Verdict

**The fixed-charge screening experiment ran; gold screening is not yet physically
validated.** These 300 ps pilots supply neutral controls and charge-response data.
They cannot establish a converged Debye length, specific adsorption or conducting
metal behavior. The neutral production gold implementation remains unchanged.

The charged seeds give **5.000 nm (optimizer upper bound)** and **0.434 nm**.
The upper-bound value is not a measured 5 nm screening length. Raw ionic
compensation is **81.8% / 64.1%**, or **72.0% / 46.3%** after subtracting each
paired neutral background. These differences remain unresolved by the pilot.
All four central water densities are 33.77–33.84 waters/nm³ and no water or ions
leave the compartment. Stable water density therefore does not establish stationary
ion screening. The central-field response also differs across seeds; no zero-field
claim is made from a midplane potential gauge.

## Measured primary window: 100–300 ps

| Control | Water / nm³ | Central salt, mM | Half-cell ion excess, e | Compensation | Fitted length, nm |
| --- | ---: | ---: | ---: | ---: | ---: |
| charged_317 | 33.774 | 374.3 | 13.20 | 0.818 | 5.000 (at bound) |
| charged_719 | 33.829 | 241.7 | 10.34 | 0.641 | 0.434 |
| neutral_317 | 33.789 | 307.7 | 1.58 | — | Not interpretable (neutral) |
| neutral_719 | 33.836 | 247.3 | 2.87 | — | Not interpretable (neutral) |

Compensation divides the lower-half Na−Cl excess by the imposed lower-electrode
charge magnitude. It is undefined for neutral controls. The same seed's neutral
background is also subtracted in [paired_response.json](paired_response.json).
Neither raw nor subtracted compensation is an automatic acceptance score.

The old abstract-wall RunPod trajectory gives **0.655 nm** in its matched early
200 ps window and **0.556 nm** over its late 20 ns. Its central ionic strength
changes from **276.2 to 320.3 mM** between those windows. Gold cannot be required
to match the late result on a much shorter timescale or with unmeasured dielectric
response. Area, timestep, contact forces, solvent inventory and normal cell size
also differ; see the [declared protocol](../README.md).

Even within the historical late 20 ns, individual 200 ps windows yield fitted
lengths whose empirical 2.5th–97.5th percentiles span **0.314–1.667 nm**. This is
window-to-window variability, not a confidence interval or an acceptance band.
It demonstrates how weakly a single new 200 ps fit can constrain model agreement.

The historical analysis uses 300 ps bootstrap blocks. The new 200 ps primary
window contains **zero complete blocks**, so no screening confidence interval is
reported. Density intervals in the JSON are conditional sampling estimates, not
physical acceptance limits. Separate 100 ps fits and exclusion sensitivity are
retained, including fit boundaries and optimizer results for neutral null controls.

## Evidence

- [Profiles, time evolution and window fits](screening_comparison.png)
- [All measurements and historical comparison](comparison.json)
- [Input and native-run integrity](integrity_audit.json)
- [Deterministic PB estimator check](estimator_reference.json)
- [Historical early/late reanalysis](historical_comparison.json)
- [Historical 200 ps window variability](historical_short_window_variability.json)

Per-frame water/ion counts, temperatures and potential components remain in local
`screening_samples.npz` files. The microscopic potential includes explicit water,
ions and charged Au separately; their sum reproduces the all-charge calculation.
Neutral-subtracted potential component CSVs are retained for each paired seed.
Per-case profile CSVs include water density, ion concentrations and dipole orientation;
the JSON also reports the central all-charge field slope without claiming zero field.
Water polarization is why ionic screening agreement alone cannot validate the
full double-layer potential: [Limaye et al.](https://doi.org/10.1039/D3FD00114H).

## What was implemented

An isolated experiment assigns prescribed equal/opposite charges to the inner Au
layers while retaining neutral-IFF LJ contact parameters. PSF and EW3DC charges
are identical, total charge is zero, and the experimental manifests are rejected
by the registered neutral-gold verifier. There is **no constant-potential solve,
induced/image response, voltage conversion or production API change**.

Both gold arms use 1 fs steps. This avoids simply inheriting the old 4 fs choice;
[timestep-dependent rigid-water errors](https://doi.org/10.1039/D4SC08437C) remain
an independent validation question, along with the electrolyte dielectric response.

## Next steps supported by these data

1. Assess independent longer stationary windows at this geometry and controlled
   inventory; estimate uncertainty from block-length sensitivity before comparing
   a gold screening length with continuum or historical values.
2. Add a same-integrator abstract-wall comparison and a salt series. Use measured
   central ionic strength and a force-field-specific dielectric assessment.
3. Validate matched published gold hydration/ion contact separately. The present
   prescribed-charge Au model is an intermediate screening diagnostic, not a
   conducting-metal or adsorption benchmark.
4. Proceed with the source-audited constant-potential design only after choosing
   its charge-width/hardness model and independent energy/force reference.

## Cost and checks

4 completed 300 ps dynamics controls; recorded native wall time including
minimizations: **20.40 minutes**. Local GPU only. Prior calibration/restart
work plus this campaign remains within the four-hour ceiling. The existing Debye
and gold unit checks passed (29 tests). Native integrity checks are recorded
separately from physical qualification. Scoped Ruff checks and `git diff --check`
passed. No application/backend behavior changed, so app/browser suites were not
rerun for this isolated experiment.
