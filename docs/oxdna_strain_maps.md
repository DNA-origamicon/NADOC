# oxDNA strain maps

The oxDNA Visualizations card offers backbone FENE strain and designed
Watson–Crick pair separation, both as dimensionless `(distance − r₀) / r₀`.
Blue is compression, white is zero, and red is extension. These are local
geometric measures, not stress, torque, elastic energy, or local duplex twist.

**Over time → Auto** chooses signed peak magnitude for torsion jobs and signed
mean for ordinary production/field jobs. Either can be selected explicitly.
Peak retains the signed value with greatest absolute magnitude at each particle
among the sampled frames. Peaks at different particles need not be simultaneous;
thermal fluctuations contribute, and this is not a subtraction of an unloaded
control. Sampling uses the existing bounded trajectory walk (normally 60 evenly
spaced frames), so it cannot certify the maximum across every saved frame.

Both statistics are measured per frame before aggregation. Display coordinates
are the mean geometry, not the geometry at each particle's individual peak.
The scale uses robust symmetric bounds; values outside those bounds saturate,
and the status separately reports the actual range. The dsDNA filter changes
which particles are colored and the scale, while all particles still move with
the displayed structure. Unmeasured particles retain their native colors. Flexible
segments use the same per-nucleotide map on their beads and base slabs, with
interpolated tube colors between those sites. Scalar colors take precedence over
native magenta or cluster colors and survive geometry/representation refreshes;
clearing the map restores native colors. Unpaired flexible ssDNA has no WC value,
and enabling dsDNA-only intentionally excludes it from coloring.

Insertion copies keep distinct coordinates and values. Backbone neighbors follow
the exported strand walk through every insertion. Designed pair matching retains
the copy index; an unmatched copy is unpaired. Synthetic tails and crossover
extra bases are measured for backbone strain, but do not acquire WC partners.

Scalar distances use minimum-image raw oxDNA sites, independently of display
alignment. The normal periodic reconstruction remains the first display choice.
If assumed designed WC edges tear a covalent chain after partners separate,
the map retries reconstruction with covalent edges only and reports the recovered
frame count. Frames that still fail the backbone checks remain excluded and are
reported. An all-rejected trajectory is distinguished from an empty trajectory.

The API is `GET /api/oxdna/jobs/{id}/strain`, with `metric=backbone|wc`,
`aggregation=mean|peak` (default `mean`), and `align=true|false`. It reads the job's
frozen topology. Aggregation participates in the cache key and is returned in the
response; the legend and scalar export title identify it.

Regression coverage: `tests/test_oxdna_strain_map.py`,
`frontend/src/api/client_strain.test.js`, and the existing oxDNA display/panel
unit tests. `frontend/playwright.strain.config.js` runs the opt-in real-job review
in `frontend/e2e/oxdna_strain_real.spec.js`. Supply `NADOC_STRAIN_MANIFEST` with
`[{name,id,source,torsion}]` and `SCRYWRITE_TEST_WORKSPACE` containing disposable
job metadata and `__e2e__` source copies. The caller must remove that workspace
in a `finally` block and verify original source hashes. Analysis-only trajectory
symlinks are permitted; session persistence and background precomputation are
disabled. Screenshots/replies stay in the configured development-artifact output.
