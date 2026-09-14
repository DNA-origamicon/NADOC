# Charged-wall screening diagnostic

Persistent document: `workspace/NAMD_charged_wall_control.nadoc`.
Managed relaxation: `6ed2945c805e` (69,834 atoms; -26e sheet; 300 mM added NaCl;
298.15 K; fixed-volume periodic two-faced wall). No DNA/PEG is present.

The NAMD Graphs and Metrics card provides a Surface ions and screening button.
It opens an interactive popup with saved graphs, editable bins, maximum sampled
frames, discarded frame fraction, fit interval and reference permittivity. Click
Calculate to replace the graphs with a new result; Export JSON saves that result.
Select the relaxation or its production child. Saved settings/results reload on
opening; changing jobs closes the popup. Invalid inputs and failed calculations
retain the previous graphs with an explicit status message.

POST `/api/md/jobs/{id}/surface-profiles` refreshes the per-job JSON;
GET returns the last result. Defaults: 48 bins, last half of saved frames,
at most 256 uniformly sampled frames, fit 0.6–2.0 nm, reference relative
permittivity 78.4. Trajectories are read only through complete DCD frames.
Restart epochs replace overlapping old frames. Each bin uses projected area
multiplied by actual bin width; each face has its own volume. Concentration is
reported in mM; ionic charge in e/nm³. The wall's instantaneous mean displacement
is removed before minimum-image binning. Fixed orthorhombic cell dimensions are
checked against the package. Initial support is NaCl/water/closed wall only.

The pooled residual sheet fraction is
`1 + 2 * integrated(mean-face ionic charge) / sheet charge`.
Its zero at the midpoint follows from neutrality and is not validation.
The continuum diagnostic fits a free amplitude times
`sinh((h-d)/lambda)/sinh(h/lambda)` for periodic half-reservoir depth h.
It excludes a user-chosen near-wall region, rejects overscreened/sign-changing
windows and poor/bound-limited fits, and reports four contiguous-block estimates
where possible. The plotted Debye reference uses measured midpoint-region ionic
strength and the selected dielectric constant. Neither assumes the water model
has the experimental dielectric response. Ion-only charge omits water
polarization: this is not a microscopic field/potential reconstruction.

Block SEM and first/last block differences are diagnostics, not independent-sample
confidence intervals. Bulk-region flatness, dielectric calibration, bin/window
sensitivity, longer independent trajectories and finite-cell scaling remain
necessary before claiming Debye screening. The nominal 4.8 ns ladder (first 10% at 2 fs; subsequent stages at 4 fs) is an initial
observation window, not a literature-scale convergence guarantee.

See [charged-surface literature and scope](../../docs/namd_charged_surface.md).
A primary MD/continuum comparison motivating separate density and integrated
charge measurements is [Howard et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC3542913/).

## Persistent monitoring

With a user-opened `just test-session`, run:

```bash
scripts/test_guard.sh charged-surface-native 0 1 -- uv run python -m experiments.charged_surface.monitor 6ed2945c805e --start --interval 60
```

The monitor keeps the normal managed runner alive and records
`surface_profile_monitor.jsonl`, latest `surface_profiles.json`, and numbered
profile snapshots inside the job directory. It exits when the job stops/fails/
completes. It does not start additional jobs or certify equilibrium. The ordinary
job Run/Stop and production controls remain authoritative.
