# UV crosslinking analysis

The NAMD Visualizations card has one **UV crosslinking analysis** option. It
replaces the separate photoproduct-propensity and weld-pair controls. Colors are
applied to **native design positions**, without deforming the design to a mean or
trajectory frame. The shared flex-map color scale supplies palette and numeric
range controls, including representation changes and export of the active scale.

Selecting the option reveals **show interstrand**, **show intrastrand** (both
initially checked), and **Show T-T only** (initially unchecked). These filters act
locally on cached pairs; they do not start another trajectory pass. The scale is
the frame fraction, not a per-filter renormalization. Each base takes the maximum
opportunity of its visible incident pairs, avoiding summing competing partners as
if they were independent probabilities. Bases without a visible opportunity use
the zero color. The explanation lives in the option’s hover tooltip; candidate-pair details are
not displayed in this compact view.

## Scientific interpretation

The map uses an explicitly exploratory common **geometric opportunity** screen
for TT, TC, CT and CC: C5=C6 midpoint distance below 4.5 Å and circular deviation
of C5–C6–C6–C5 dihedral from 16.7436519° below 45°. A pair's opportunity is the
fraction of analyzed production frames satisfying both conditions. This extends
the existing geometric window, not the fitted T–T KIMMDY propensity, to other
pyrimidines. It is not a calibrated reaction probability, rate, UV yield, or
all-isomer predictor. Zero observed opportunity does not exclude photochemistry.

For T–T pairs only, the saved analysis retains the circular-angle KIMMDY score
**averaged over frames within the 6 Å screening cutoff**. This contact-conditioned
diagnostic is not the full-trajectory KIMMDY mean from
`scripts/analyze_kimmdy_design.py`. CT/TC/CC do not receive a fitted KIMMDY score.

All saved production frames are analyzed, without a frame or candidate cap.
Restrained equilibration segments are excluded. Local minimum-image geometry
handles periodic boundaries. Saturated pyrimidine carbons with cross-residue
C5/C6 bonds are excluded from reactant screening. The analysis uses the saved
job snapshot and export-aware residue threading, including terminal extensions,
crossover inserts and loop copies; missing mapping fails explicitly.

## Persistence and interruption

`JOB/analysis/uv_crosslinking/<input-fingerprint>/analysis.sqlite` stores sites,
pair sufficient statistics, input provenance and the completed-frame cursor.
The cursor and pair updates commit in one SQLite transaction per frame. Turning
the view off cancels the worker; selecting it again starts at the first
uncommitted frame. A partially processed frame is safely repeated. Complete
caches load without parsing a PSF or reading DCD coordinates.

The cache uses SQLite WAL with `synchronous=NORMAL`: committed frames survive
worker cancellation and application crashes without a disk flush per frame.
Power loss can roll back recent cache transactions, but cannot separate the
cursor from its statistics; those frames are recomputed on resume. See the
[SQLite durability contract](https://www.sqlite.org/pragma.html#pragma_synchronous).

The fingerprint covers the algorithm schema, frozen design hash, and ordered
topology/trajectory filenames, sizes and modification times. Changing or growing
inputs starts a new cache namespace; it never mixes old results into a changed
trajectory. Moving an intact job preserves reusable results when file metadata
is preserved. No topology, design or molecular coordinates are written.

The established `photoproduct-likelihood` and `photoproduct-progress` HTTP paths
remain as transport compatibility names; their UI now serves the unified UV
analysis. The standalone legacy KIMMDY script and designed-weld analysis APIs
remain available for research workflows, but are not separate visualization
options.
