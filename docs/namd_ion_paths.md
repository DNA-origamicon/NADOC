# NAMD nanopore ion paths

Select a NAMD job with inherited nanopore preparation settings and saved trajectory,
then choose **View nanopore ion paths** under Visualizations & processing.

- Separate **Frames before crossing** and **Frames after crossing** inputs use raw
  saved DCD frames, independent of View trajectory's interval. Each ranges from
  1 to 1,000,000; windows clip at file/segment boundaries. Large entries can cover
  the full available trajectory.
- **Line thickness (px)** changes the GPU wide-line material immediately (0.5–12 px).
- Paths use the existing ion transport analysis criterion: consecutive samples
  intersect the membrane plane inside the circular pore aperture. Recrossings are
  included. This is a plane-crossing view, not a claim of complete translocation
  through a membrane of finite thickness.
- **Ion paths shown** ranges from 0% to 100%. A stable, distributed subset of complete
  crossing paths is drawn; increasing the percentage retains the existing subset.
  The readout gives the shown and total counts. No network request or geometry
  rebuild is needed when dragging the slider.
- Cyan shows the origami's existing RMSF average, including 5′ termini and measured
  mean base positions. It uses the same up-to-150-frame sampling and Kabsch alignment
  as the flexibility map. The exact first saved frame's affine places that average
  relative to the pore; this is a fitted RMSF mean, not a time average of lab-frame
  translation and rotation.
- Grey shows the simulated graphene coordinates from the first saved frame, with a
  ring marking the aperture. The origami and graphene remain visible at 0% paths.
  The previous scene is restored when leaving the mode.
- Periodic minimum-image steps keep paths continuous. No crossing or path is inferred
  across DCD file boundaries. Orthogonal cells are required.

The backend streams the PSF atom section and memory-maps only selected ion slices
from DCD files. Random-access advice prevents OS readahead of the surrounding water.
A synchronized, single-snapshot cache holds ion positions and crossing identities;
changing window sizes reuses it. File size/mtime changes invalidate the snapshot.
The source cache is limited to 768 MiB of ion coordinates. The browser endpoint
returns NIPT v1 binary data: JSON crossing/window metadata followed by shared float32
tracks. Overlapping windows of the same ion share coordinates. Periodic-image
offsets keep each crossing centred correctly. The old one-million-expanded-point
cap no longer applies to the visualization.

The renderer also shares overlapping segments in the same periodic image. Each
segment appears when the first selected path containing it is shown, so the
percentage slider still reveals complete paths and updates only instance counts.
Failed downloads retain the current scene and controls, report the backend error,
and can be retried with **Reload paths**.

## Verification (2026-09-09)

Real fixture: `small_plate P1 Alpine`, job `a5e2cf157a76`, production DCD
`small_plate_01_production_200ns_k0.dcd`.

- All **5,597** saved frames and **6,799** ions analyzed.
- **8,846** aperture crossings: **8,710 Na+**, **136 Cl-**.
- Optimized full scan: **25.97 s** on this machine. Cached asymmetric-window
  extraction (3 before, 5 after): **0.35 s** in the preceding scan process.
- Actual payload loaded into the new controls and Three.js renderer through a local
  HTTP fixture in headless Chromium/SwiftShader: **3 draw calls**, no JavaScript
  errors, **176,757** line segments with the default 10/10 window. Changing width
  from 2 to 6 px made no additional request. Leaving the mode disposed its geometry.
  This browser fixture used the real payload and visualization modules; the full
  application panel's gating and mode switching were covered separately in Vitest.
- Synthetic DCD/PSF regression verifies ion identity, excludes MGH hydration water,
  rejects wall/periodic-face crossings, unwraps continuous paths, clips windows, and
  verifies cache reuse. Controls cover cancellation, empty results, thickness, and
  nanopore-only gating. Production frontend build passed.

## Average-structure and percentage-slider verification

On the same P1 Alpine fixture, the combined load took **49.77 s** and included the
RMSF average of **1,600 nucleotides over 150 samples**, **44,664 graphene carbons**,
and the unchanged **8,846 crossings**. The average is placed by inverting the exact
first-frame RMSF affine and choosing the pore's matching periodic image.

Headless Chromium rendered the real payload with both context structures visible.
At 5%, the readout showed **442 / 8,846 paths**. At 0%, only the origami, graphene,
and aperture remained visible. Both changes used the original single data request;
1,000 percentage updates averaged **0.001 ms** of CPU work per update. No browser
errors occurred, and leaving the mode disposed all its geometry. These timings
measure slider updates, not full-scene GPU frame time.

Regression tests cover inverse rotation/translation and periodic pore imaging,
unchanged RMSF means when requesting context, strand-aware backbone adjacency,
first-frame graphene extraction, stable whole-path subsets, 0% context visibility,
and absence of fetches or geometry rebuilds on slider input. Production build passes.

## Large-window regression (2026-09-09)

P1 Alpine, all 8,846 crossings:

| Before / after | Expanded points | Shared points | Binary response |
| --- | ---: | ---: | ---: |
| 10 / 200 | 1,826,943 | 299,576 | 7,846,240 bytes |
| 200 / 200 | 3,482,103 | 502,800 | 10,283,448 bytes |
| 10,000 / 10,000 | 49,511,062 | 5,697,746 | 72,606,172 bytes |

The latter request clips to the 5,597 saved frames. After the initial scan and RMSF
context load, building the 200/200 and 10,000/10,000 binary responses took 0.48 s and
0.78 s respectively. No saved coordinates or crossings were downsampled.

Browser verification uses the actual binary payload, production API client, decoder,
controls, and Three.js renderer served through a local HTTP fixture. Regression
tests cover periodic-image equivalence to individual windows, file-boundary clipping,
binary bounds checks, shared-segment visibility at fractional percentages, meaningful
HTTP errors, cancellation, and retaining the current view after a failed reload.

The real browser loaded 10/200 and 200/200 with the option still selected. Scene
preparation took about 0.41 s and 0.58 s. The 10,000/10,000 payload built 5,881,396
unique rendered segments in 1.47 s; that largest browser check used 0% paths to
verify preparation without treating software-GPU throughput as a performance claim.
An injected HTTP error retained all six scene objects, left the option checked,
and displayed its actual error detail; the following larger-window load succeeded.
There were no browser JavaScript errors.

## Shared representations and load progress (September 2026)

Ion paths now use the existing NAMD RMSF display controller for the mean origami.
The separate cyan bead renderer and scene-wide visibility snapshot are removed.
The pore, graphene, and paths receive the inverse of the first-frame pore transform
so they share the ordinary simulation display frame. Graphene changes keep using
one membrane. Exiting the mode releases both the companions and the RMSF display.

The initial load prepares the coarse mean, atomistic mean/topology, and molecular
surface once. It seeds the shared controller's existing caches, including bonds;
representation switches do not issue further RMSF or topology requests. Atomistic
averaging uses NumPy accumulation and DNA-prefix DCD reads. Bond filtering reads
stored integer topology pairs without constructing solvent bond objects.

A request-scoped progress endpoint reports topology, ion coordinates, crossings,
RMSF setup/sampling, atomistic setup/sampling/bonds, surface generation/smoothing,
window construction, and serialization. The browser adds streamed download,
decoding, scene construction, and representation application. The fixed work
weights reserve 30% for transfer/rendering; this is work completion, not a time
estimate. Parameter reloads reset progress and superseded replies cannot finish
or overwrite the current load. Failures retain editable controls and show an error.

P1 Alpine validation used the actual 5,597-frame trajectory and all 8,846 crossings:
32748 mean atoms, 36731 bonds, 97752 surface vertices, and 1600 mean nucleotides.
The complete cold preparation of all representations took 51.7 seconds; another
200/200 window reused them and built in 0.22 seconds. DNA-prefix extraction matched
full-frame coordinates exactly in a three-frame comparison (6.2 vs 78.5 ms median).
Pore-to-shared-frame round-trip error was below 0.000006 nm.

Full-app Playwright checks loaded the frozen P1 design into a separate document
and served the real precomputed binary through HTTP. Native state used the normal
API. Mesh inventory and GPU completion checks confirmed atoms, bonds, surface,
and restoration to the mean coarse geometry. No browser JavaScript errors or
additional MD heavy-analysis requests occurred during switching. Full-path scene
checks succeeded; compositor capture of the full surface timed out under SwiftShader,
so repeat timing checks used 10% of paths to separate representation switching
from software-GPU path throughput. Hardware frame rate is not inferred from these
headless measurements.

Final warm-switch comparison (milliseconds, representation application only):

| Representation | Native | Nanopore ion paths |
| --- | ---: | ---: |
| VDW | 37 | 77 |
| Ball-and-stick | 123 | 114 |
| Surface | 780 | 107 |

These are browser measurements with 10% paths and SwiftShader, not hardware FPS
claims. The additional VDW work is about 40 ms. Mean topology is now primed while
its renderer is dormant, so the first switch builds directly from the mean.
Identical scalar/color maps are not repainted; per-renderer paint tracking keeps
shared color preferences correct across the global and region renderers. Prepared
mean atoms carry their exact RMSF lookup keys and use depth-correct sphere impostors.
The graphics driver showed large cold shader/compositor stalls in both native and
ion-path tests; warm draw completion was in milliseconds. The once-per-load
preparation and driver initialization must not be conflated with warm switching.

Final validation: 39 backend tests, 497 frontend tests, production Vite build,
full-application Playwright mesh inventories and GPU completion checks. No source
trajectory or design coordinates were modified.
