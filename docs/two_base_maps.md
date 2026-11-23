# 2-base maps

The bottom of the NAMD Graphs and Metrics card offers **base 1:** and **base 2:**.
Each button captures the one currently selected individual base. If there is no
single-base selection, it waits for the next individual-base selection; click it
again to cancel that wait. Two different bases enable **Generate**. **Show** opens
a 2×2 grid with four dropdown selectors covering all 15 unique pairs of six relative
coordinates. Defaults are displacement xy/xz and rotation-vector xy/xz. Help is
in hover tooltips, including per-point frame/value readouts. Generate, Show and
Export sit beside the title. A percentage bar below the base selectors reports
measured frames (polled every 500 ms, worker snapshots every 25 frames). Progress
is scoped to the individual request and cleaned up after completion/cancellation.

Export uses the standard PNG/Data dialog: PNG is the four currently selected
graphs in a labeled 2×2 image, and CSV contains all six coordinates for every
frame, with base identities and units in the column headers. Dropdown selections
remain available after closing the popup and are reused for export.

Coordinates are measured for all saved free-production frames of the selected
job, independent of the other metrics' preview/all-refit settings. They use the
saved job design and export-aware residue mapping (including extensions/inserts).
The open design must match the job's design identity. Missing or ambiguous
mapping and incomplete or degenerate base rings fail explicitly.

Origins are unweighted base-ring heavy-atom centroids. Each ring is imaged around
its first chemical ring atom before averaging. A least-squares ring plane defines
z, signed by the first three atoms in chemical ring order. x is the projected
N1→C4 span for pyrimidines or N9→C6 for purines; y = z × x. These match the existing
measured base orientation convention. Base 2's centroid displacement is the
nearest periodic image, projected into base 1's frame and expressed in nm.
Triclinic boxes are handled by MDAnalysis minimum-image vectors.

The relative orientation matrix is R1ᵀR2. Its principal rotation vector is reported
as x/y/z components in degrees, in base 1's frame. Its magnitude is the rotation
angle (0–180°); its direction is the axis. This avoids Euler gimbal lock but retains
the unavoidable branch discontinuity at 180°. It is not a set of helical-step
parameters. Plot points are individual frames, without histogram normalization,
interpolation, or downsampling.

Completed results are cached under `JOB/analysis/two_base_maps/<fingerprint>.json`.
The fingerprint includes schema, ordered base keys, frozen design hash, and
ordered input file names/sizes/modification times. Atomic replacement publishes
only complete results. Changed inputs or reversed base order get separate
results. This feature does not currently checkpoint partial work. Switching jobs,
designs or base choices cancels the pending request and invalidates the visible
result; stale responses cannot populate the new selection.

This is read-only analysis: no molecular structure or authoring history changes.
