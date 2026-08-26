# Arbitrary-Design KIMMDY Analysis

## Purpose

`scripts/analyze_kimmdy_design.py` applies the KIMMDY CPD geometric analysis to any
prepared NADOC NAMD design without a frontend. It consolidates the earlier AutoNAMD
candidate-scan/ranking experiments and the reusable geometry developed in
`/home/jojo/Work/kimmdy-namd-cpd` into one design-aware workflow.

This is analysis only. It does not form bonds, change charges, modify a topology, estimate
quantum yield, or report an absolute kinetic rate. The exported score is a dimensionless
geometric propensity. It also does not draw a stochastic KMC "winner": without a calibrated
physical rate scale, that random selection would be less informative than the complete ranked
propensity and occupancy tables exported here.

## Pair-selection modes

### Designed welds

```bash
uv run python scripts/analyze_kimmdy_design.py \
  --job workspace/md_jobs/JOB_ID \
  --mode designed
```

`designed` uses NADOC topology intent. It analyzes only thymine inserts carried by adjacent
reciprocal crossover partners. A reciprocal weld is retained even when it never passes the
proximity cutoff because excluding the intended target would make off-target comparisons
misleading.

### Whole-design T–T scan

```bash
uv run python scripts/analyze_kimmdy_design.py \
  --job /absolute/path/to/archive_job \
  --mode all-tt \
  --pair-scope interstrand \
  --screen-cutoff-ang 6 \
  --stride 50 \
  --max-frames 2000
```

`all-tt` performs two passes over the selected frames:

1. A periodic-boundary-aware spatial search retains thymine pairs whose C5=C6 bond-midpoint
   distance reaches the screen cutoff. This corrects the earlier AutoNAMD pre-screen, which
   used C5–C5 even though KIMMDY is parameterized against the bond-midpoint distance.
2. The retained pairs receive full per-frame midpoint distance, C5–C6–C6–C5 dihedral, and
   propensity analysis in a single vectorized trajectory pass.

`--pair-scope` accepts `all`, `interstrand`, or `intrastrand`. `--max-candidates` bounds the
second pass for very large origami; intended NADOC weld pairs are never dropped by that cap.

Only T–T pairs are scored. The previous broad AutoNAMD scan also listed T–C and C–C contacts,
but the KIMMDY dimerization parameters were calibrated for thymine dimers. Applying those
parameters to other pyrimidine products would present an unsupported number as a prediction.

### Explicit pairs

```bash
uv run python scripts/analyze_kimmdy_design.py \
  --design workspace/example.nadoc \
  --topology /absolute/path/system.psf \
  --dcd /absolute/path/run.dcd /absolute/path/run.cont1.dcd \
  --mode explicit \
  --pair 'D000:43~D017:22' \
  --pair 'D004:81~D004:82'
```

Explicit identities are `(segid, resid)`, not a globally ambiguous residue number. This fixes
a limitation of the earlier `kimmdy-namd-cpd` grouping path, where equal residue numbers on
different segments could collide.

## Input discovery

With `--job`, the command reads:

- `job.json` for `package_subdir` and `name_stem`;
- the job's immutable `design.json` snapshot;
- `<stem>_hmr.psf` or `<stem>.psf`; and
- chronological `*production*.dcd` files from the package output directory.

`--topology` and `--dcd` override automatic discovery. This is the intended route for archived
branches, a subset of production pieces, or a deliberately chosen equilibration segment.
Automatic discovery accepts one base DCD plus its `.contN.dcd` continuation pieces. If an old
archive contains multiple independent protocols or replicas, the command stops and requires an
explicit `--dcd` list rather than silently pooling unlike conditions.

With `--design`, `--topology` and at least one `--dcd` are required. The topology must have the
same atom order as every trajectory and must preserve NADOC's `D000`, `D001`, … segment IDs if
designed-weld classification is required.

## Rate-model contract

Both scores are always saved:

- `upstream_propensity` reproduces the original KIMMDY expression, including its plain
  `abs(eta - eta0)` angular penalty. It is the default primary ranking so new analyses remain
  directly comparable to the previous AutoNAMD tables.
- `periodic_propensity` uses the shortest circular angular separation. This is NADOC's corrected
  interpretation near the −180°/180° boundary.

Select the primary ranking with `--rate-model upstream|periodic`. Exporting both prevents a
silent convention change from altering a ranking.

The reactive-corner count remains the more interpretable joint diagnostic:

`d_mid < 0.45 nm` and circular `|eta - eta0| < 45°`.

The KIMMDY optimum `d0 = 0.157177 nm` is product-like covalent geometry. An ordinary classical
trajectory generally bottoms out near van der Waals contact and cannot sample that product bond.

## Sampling and periodic boundaries

`--start`, `--stop`, and `--stride` select frames. `--max-frames` widens sampling over the full
requested interval; it never truncates analysis to the beginning of a long trajectory. Use
`--max-frames 0` to disable the cap.

C5/C6 bonds, pair midpoint displacement, and the four-atom dihedral are reconstructed with local
minimum-image vectors on every frame. This works with orthorhombic or triclinic boxes and does not
require bringing an entire large origami into one image before measuring a local candidate.

## Outputs

Managed jobs default to `JOB/analysis/kimmdy/`; explicit inputs default to
`./kimmdy_analysis/`. Use `--out` to choose another location.

- `summary.json` — provenance, parameters, frame selection, screen audit, ranked pair statistics,
  design identities, and each pair's maximum-propensity representative frame.
- `pairs.tsv` — flat ranking table suitable for pandas, R, or a manuscript data pipeline.
- `timeseries.npz` — rank-aligned matrices for `d_mid_nm`, `eta_deg`, both propensities, real
  trajectory frame indices, per-file trajectory/local-frame provenance, and times. DCD time can
  restart at continuation or replica boundaries, so file plus local frame is the stable locator.

## NAMD visualization

The NAMD tab's **Visualizations** card includes **Photoproduct propensity (T–T)** for jobs
with free production dynamics. Activating it runs the same whole-design, periodic-aware T–T
screen in a killable analysis worker and false-colors every mapped topology thymine with the
`magma` scale.

The view shows determinate progress throughout the load: topology/trajectory preparation,
candidate screening, per-frame geometry measurement, pair-to-base aggregation, payload
serialization, and application of the false colors. Screening and measurement report frame
counts; aggregation reports pair counts; serialization and coloring report base counts. The
status remains visible at completion and reports failures explicitly.

For a base, the displayed value is the sum of ensemble-mean pair propensities for all analysed
T–T candidates incident on that base, divided by the largest such base sum in the design. Thus
the scale is relative from 0 to 1. It is not an absolute probability, quantum yield, or kinetic
rate. Every displayed base is false-colored: non-thymines, unmapped bases, and thymines with no
reactive candidate receive the colormap's zero color because the present KIMMDY parameters do not
assign them a supported nonzero score. Restrained equilibration frames are excluded.

## Validation

`tests/test_kimmdy_analysis.py` covers bounded full-interval sampling, segment-safe explicit
identity, both angular conventions, a synthetic two-thymine trajectory, proximity screening,
rank-aligned series, job discovery, and the complete output bundle.

A real `2hb_1xT` archive smoke test was also run against a 30-frame NAMD DCD. Designed mode
resolved its intended reciprocal insert pair, while `all-tt` independently found a closer
off-target cross-strand thymine and retained the intended pair for comparison. That short,
restrained segment is a functionality check, not scientific population evidence.
