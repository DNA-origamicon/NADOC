# EM analysis

Open **EM Analysis** on the right sidebar rail (or **Tools → Nanoparticles → EM Analysis…**), then use **Calculate 520 nm map** at the top. The wavelength input directly below
changes both the calculation and button label; the default remains 520 nm.
The analysis reads the current scene's gold sphere positions (including hidden
particles and live particle poses); it never edits the design, DNA, history or
simulation. Assembly inputs use each instance's world transform. One to four
spheres, 5–100 nm diameters, gaps ≥2 nm and a volume ≤500 nm per axis are supported.
Other nanoparticle materials reject rather than silently disappearing.

The backend runs MiePy 1.1.0 generalized multiparticle Mie theory in an isolated
process. It solves mutually coupled electric and magnetic multipoles, with an
incident plane wave at the selected **vacuum wavelength** in water, n=1.333.
The supported input range is 187.9–1937 nm, matching the bundled Johnson–Christy
gold n/k table, interpolated at the selected wavelength; positive imaginary
permittivity corresponds to the solver's exp(-iωt) convention.

The initial polarization is along the first pair's center-to-center axis; the
perpendicular option rotates E by 90°. A deterministic orthogonal propagation
axis is chosen. Numeric vectors in the result report E/k in world space;
direction arrows are omitted from the scene and exports.
For one sphere, the pair axis is world X. Slice XY spans the pair axis and its
transverse direction; propagation is local Z.

Coating controls show only inputs used by the selected model: bare spheres hide
all DNA-layer fields, specified thickness hides oligo/persistence lengths, and
the length-based estimate hides specified thickness. Explanations appear as label
hover tooltips. Wavelength persists with the other EM settings and is included in
simulation/trajectory requests and downloaded field metadata and filenames.

Enabling **Lighting and Appearance** with GPU path tracing and a visible EM field
opens a rendering-time warning before activation. **Continue** keeps both;
**Clear field** removes active EM overlays (and turns off simulation EM display);
**Disable path tracing** keeps the field and uses raster lighting; **Cancel**
leaves lighting off. Escape/closing the dialog also cancels. Enabling path tracing
from Appearance with a field present gives the same choices.

## Sidebar and viewport color legend

EM Analysis is a docked right-sidebar column. The right-sidebar toggle hides or
shows it with the other columns; its header × closes that column independently.
Closing the column retains the calculated field and viewport legend. **Clear
field** removes a standalone field; simulation EM remains controlled by its own
visualization checkbox. Particle/optical changes still invalidate stale results.

The viewport legend follows the flexibility-map placement at the right-center
of the canvas. When the flexibility legend is also visible, EM sits beside it.
Drag the handles or enter positive bounds to adjust the logarithmic intensity
color window, and use the palette button for the shared colormap choices.
Bounds default to 0.1–100× with Jet; Reset restores those bounds. Choices persist
in browser storage and apply to clouds, slices, smooth glow and trajectory frames,
including their rendered colors in image/video exports. This is a viewport DOM
legend, like the flex legend; it is not embedded into the rendered image.
Color bounds do not change the 3D intensity cutoff or recalculate the optical
field. Smooth recoloring reuses tetrahedron buffers.

## Direct adaptive-volume glow

Choose **Display → Smooth 3D glow** (also available for trajectory fields).
The default intensity cutoff remains **3×**; existing saved choices are retained.
Dot size has no effect on this mode. The persistent legend controls the palette
and log intensity mapping independently of the cutoff.

The former 32 nested contour surfaces have been replaced by direct ray integration.
Adaptive fields use the original sample positions and Delaunay tetrahedra;
uniform fields are split into conforming tetrahedra using every source node.
Intensity is interpolated linearly in each tetrahedron. There is no coarse-grid
resampling or cell-volume averaging. Masked/nonfinite samples contribute zero,
and the field ends at the sample convex hull. Recalculate legacy responses that
lack display connectivity. Scientific results and molecular documents are unchanged.

Numerically coplanar cells (relative determinant within 64 double-precision
epsilons of zero) are excluded before inversion. This removes roundoff-volume
cells whose GPU interpolation planes can become unstable; genuine thin cells
and their original intensities remain. GPU interpolation is bounded to each
cell's sample range, so precision loss cannot invent a brighter hotspot.

Each projected tetrahedron supplies its exact ray entry/exit interval. The interval
is clipped analytically to the intensity cutoff, camera near/far planes and opaque
scene depth, then integrated with eight-point Gauss–Legendre quadrature. There is
no fixed spatial marching step that can skip a tiny refined tetrahedron. Cells
entirely below cutoff are omitted. The palette is evaluated along the interval,
not at an isosurface or a cell-average intensity. Subpixel hotspots can still be
smaller than point sprites; integration is not a maximum-intensity projection.

This first version uses **additive emission without field absorption**. A 1×
background contributes zero. Local RGB emission is the palette color multiplied
by `(I - 1) / 99`, with 100× contributing two linear radiance units per 10 nm of
ray length. This fixed illustrative transfer does not normalize by the frame
maximum, cell size or sample count. Weak foreground fields cannot attenuate a
hotspot, although colors from overlapping regions add and bright overlaps can
saturate. Glow has greater contrast against a dark background.

The same camera-volume integration runs in ordinary raster views and over WebGL,
WebGPU and Native OptiX Appearance previews/exports, before figure effects and
color grading. Camera-compositor hulls are excluded from trace snapshots. A depth pass uses the
original scene materials, including display impostors, and clips at depth-writing
surfaces. Transparent objects do not provide volumetric refraction or attenuation.
**Native OptiX also traces smooth EM emission in glossy reflection rays**, including
gold nanoparticle reflections. It receives the original retained tetrahedra and
their vertex intensities. Linked tetrahedral volumes evaluate the same linear
intensity interpolation, logarithmic palette, cutoff and enhancement-weighted
emission. Full affine cell transforms are preserved, including shear. Boundary
hulls have a small overlap for reliable native traversal, but shader membership
clips emission to the original cells, preventing energy overlap. No contour
shells, coarse voxel resampling or intensity averaging are used. Native instances
use compact procedural instances on Blender 3.4+ (validated with 4.5.9 LTS).
An SVD rotation/scale/rotation decomposition preserves the full affine cells,
including shear and reflected orientation. Four scalar instance attributes avoid
color-alpha conversion of intensity values. Shared shader ramps retain all 256
palette entries and avoid stale generated-texture caches during legend changes.
The Blender 3.3 compatibility path expands native objects and is substantially
slower and more memory-intensive for dense fields; use the newer runtime.

Native volume emission is suppressed for camera rays, which continue to use the
existing compositor, and for diffuse/transmission/shadow rays. This avoids a second
camera glow and keeps the separate Illuminate control's existing behavior.
Illuminate uses eight normalized approximate point lights. Raster, WebGL and
WebGPU still use camera-visible glow plus those optional approximate lights;
they do not yet trace the smooth volume in reflections. Volume refraction,
absorption and scattering remain unsupported. This is illustrative intensity
visualization, not calibrated optical emission or full medium light transport.

Palette changes reuse the tetrahedron buffers. Trajectory endpoints use independent
fields with emission weights that sum to one; no correspondence between adaptive
cells is assumed. Changed views require a depth render and volume integration. Unchanged views
reuse a context-local radiance image; camera, geometry, visibility and palette
changes invalidate it. Crossfade weights composite the cached endpoint images.
Dense projected overlap still costs fill rate during integration. Publication-resolution appearance,
subpixel peaks and two-field movies remain review items.

The alternative of increasing the number of opacity-corrected contour surfaces
was not implemented. Historical contour extraction helpers remain for their
regression tests; the Smooth display path now uses `em_volume*.js`.

## Appearance image and video export

**Appearance → Art & materials → GPU path tracing** enables progressive lighting
and reflections. A spinner indicates ongoing work, and the progress bar below
the toggle has one status line for percentage, current phase, completion or
errors. It includes measured preparation and delivery work as well as samples;
reused preparation is excluded on warm renders. This is weighted work, not a
time estimate.

Native OptiX now updates the viewport after each completed sample chunk: 1, 4,
8, 16, 32, then every 16 samples up to the selected target. Dense fields above
100,000 cells start with 16 samples, then use up to 64 new samples per chunk to
amortize native per-render overhead. Each request traces
only its own sample range; linear radiance is averaged by sample count before
denoising. The last completed image stays visible during the next chunk. Camera,
field or material changes discard obsolete accumulation. Exports still wait for
the selected total. Chunk delivery does not reduce the sample target or smooth
the original EM grid.

The native EM shader bypasses interpolation and palette calculations on paths
that cannot receive reflected emission, and excludes cells from shadow rays.
Other ray visibility remains enabled to track cells containing a reflection's
starting point. Dense EM tracing still costs more than tracing without the field.

**Advanced → Trace samples** sets 1–512 samples (default 64),
for both the stationary preview and each offline exported frame. Type a value
and press Enter or leave the box to apply it. Up/down buttons and arrow keys
step the draft through powers of two (1, 2, 4, …, 512). Advanced control
explanations are available as hover tooltips. Samples and export backend can be
changed before enabling tracing. Settings are
saved with the Appearance profile; changing Art Themes preserves the tracing
choice. Moving the camera or playing a trajectory uses raster preview until the
view settles. PNG, photo GIF/WebM and compiled presentations wait for the traced
frame rather than capturing a partially accumulated preview.

Completed viewport samples can be reused by WebGL export when the scene,
camera, native pixel dimensions and sample requirement match exactly. Partial
previews, different resolutions and different rendering backends start a new
accumulation. The last completed export is also cached for an identical repeat
or held video frame (one image only, cleared when tracing stops). Scene,
material, field, lighting, camera, settings and resolution changes invalidate
that match. Text/annotations and zoom insets are composited afresh. EM analysis
results are read from the displayed field; image export does not rerun the EM
solver. Changed frames retain the existing renderer/geometry reuse path.

Image exports use the standard cancellable NADOC progress popup. Geometry
building, actual completed samples across tiles, compositing and PNG encoding
are reported separately. Steps without a measurable total are indeterminate;
percentages describe completed work in the named stage, not elapsed-time
predictions. Video export includes the current frame's tracing samples and
stage in its existing phase-weighted bar. OptiX reports native preparation
stages and Cycles sample counts through a frame-specific status endpoint; polling
stops on completion/cancellation and ignores older frame IDs.

Every visible EM sample becomes a small colored emissive sphere in a disposable
rendering projection, including both clouds in a smooth crossfade. Centers,
palette, opacity and apparent dot diameter follow the displayed field. These
emitters participate in ray intersections, reflections and indirect lighting;
the eight raster EM lights are excluded to avoid adding the same light twice.
This is illustrative emission, not calibrated optical radiance or a second EM
solver. WebGL/WebGPU brightness depends on the visible sample density and dot size.
Native OptiX retains that primary-ray dot appearance, while surface illumination
uses cell-volume-weighted log enhancement with a normalized RGB power budget.
Refining sampling does not add power; dot radius changes emitting area and
compensating radiance, rather than total illumination power. Reflections and
indirect lighting use normalized emission. Marker occlusion, soft shadows and
very-near-field illumination can still change with marker size. Crossfade opacity
scales each cloud; suppressed (≤1×) samples remain visible but add no surface
power. These are illustrative rendering weights, not calibrated optical power.
No molecular geometry, EM values or feature history is changed.

The installed WebGL 2 path tracer requires floating-point render targets.
Preview uses the actual drawing-buffer resolution, including device pixel ratio,
with tiles no larger than approximately 256 pixels per edge. Increasing sample
count reduces Monte Carlo noise; it does not increase spatial resolution. The
former 1024-pixel cap blurred enlarged previews and has been removed. More pixels
require proportionally more ray work; the preview retains raster output if the
viewport exceeds the GPU target limit. Both preview and export
submit bounded tile batches, wait for GPU completion, and adapt toward a 4 ms
batch using GPU timer queries (two tiles when timers are unavailable). This
bounds queued work; it cannot guarantee a GPU time share alongside oxDNA.
A worker builds the ray-intersection tree. Stable connectivity reuses the tree;
position changes refit it, with a rebuild after 32 refits or topology changes.
The renderer, texture atlas and unchanged studio environment persist across
exported frames. CPU snapshot preparation still occurs for changed frames. The former
three-million-triangle cutoff has been removed. WebGL checks packed vertex/index
textures against the active device’s maximum texture dimensions and checks the
actual built acceleration structure before uploading it. The 32-bit index range
remains an implementation limit. GPU/geometry
errors retain raster preview with a visible explanation; requested traced
exports fail explicitly. Scene guides and the raster shadow-catching floor are
omitted. Unrecognized custom shaders and section clipping require raster mode.
Low sample counts can be noisy, particularly in indirect light and reflections.

**Advanced → Trace export** selects WebGL (default), experimental WebGPU, or
experimental OptiX. **Trace preview** independently selects WebGL or Native OptiX. The chosen backend is fixed for an
export session; unsupported hardware or materials produce an explicit error.
All three backends retain every visible EM sample within the snapshot budget.
Export errors identify the backend and failing step (EM preparation, renderer
loading, initialization or tile rendering). Native connection errors retain the
HTTP status/server explanation when available. Oversized native uploads are
checked against current server RAM/scratch availability before transmission;
there is no silent fallback.
Figure effects, tone mapping, grading and annotations use the existing export
pipeline after the traced frame is ready. Experimental lighting can differ.

WebGPU uses an isolated pinned Three.js 0.187 / tracer 0.0.28 dependency tree;
`npm install` in `frontend` installs it through the postinstall hook. The editor
keeps its current Three.js version. A WebGPU-capable browser/adapter is required.
Renderer resources persist, but this first implementation rebuilds the scene
BVHs per changed frame and reads linear float pixels back into the shared
export compositor. This transfer cost means WebGPU is not automatically faster.
BVH workers terminate on cancellation; sample readback bounds the compute queue.
The device is requested with the adapter’s reported buffer/texture capacities,
rather than WebGPU’s smaller default limits. Packed geometry buffers are checked
against the resulting device limits; validation, memory and device-loss failures
are reported explicitly.

OptiX runs a persistent Blender/Cycles worker on an NVIDIA OptiX device, with
mesh reuse for unchanged connectivity and two CPU support threads. Native EM
clouds transfer compact centers/radii/colors/power and one icosahedron template,
instead of expanded triangles. The worker still uses the same 20-face geometry;
this reduces browser preparation and transport, not native triangle count.
EM-only updates retain molecular meshes and the studio environment. Unchanged
clouds skip updates; palette/power/opacity edits update attributes without
rebuilding their geometry. Membership/position/radius changes update cloud geometry.
Session diagnostics report the actual Blender version and light-tree capability.
The worker enables the light tree when supported and explicitly enables emission
sampling. Blender 3.3 lacks the light tree; configuring OptiX alone does not add it.
 Install the
optional Linux x64 runtime with `uv run python scripts/setup_optix_renderer.py`,
or configure an existing Blender with `--executable /path/to/blender` (the
`NADOC_BLENDER` environment variable takes precedence). Runtime selection is
local to the machine. On this WSL workstation, native Windows Blender 3.3 was
verified on the RTX 2080 SUPER; the installed Linux 4.5.9 runtime could not use
OptiX through the available WSL driver. No driver changes were made.

The experimental native bridge supports solid standard materials and EM
palettes; general textures and layered transmission/clearcoat/sheen/iridescence
are rejected. The fixed 128 MiB upload ceiling and native triangle cutoff have
been removed. Scene uploads stream into owned scratch instead of holding and
re-encoding the geometry in the web-server process. Admission uses current OS
RAM availability, applicable container/cgroup headroom, and scratch free space,
and rechecks capacity while receiving data. Each render tile is at most 2048²
pixels and 512 samples; large output images use the existing export tiles. One native export may run
at a time. Cancel, error, server shutdown or 120-second idle expiry closes the
owned worker and removes its scratch directory. Persistent data avoids repeated
worker/kernel initialization within a movie; it does not reserve GPU capacity
from other applications. Full-resolution Run1 throughput and cross-backend
lighting/quality comparisons remain manual validation debt (MV-EM-TRACE).

Passing capacity checks is not a guarantee that a scene fits VRAM: browser APIs
report texture/buffer limits but do not expose reliable free GPU memory. Cycles
and the browser can still reject allocations; concurrent oxDNA/display work,
fragmentation and driver constraints affect that result. No guessed VRAM total
or fixed percentage is used to reject a scene, and no atoms or EM emitters are
thinned to fit. See the [WebGPU limits specification](https://www.w3.org/TR/webgpu/#limits).

The active EM overlay is included in Appearance PNGs and animation GIF/WebM
frames. Capture explicitly prepares the current field (or both smooth-playback
endpoints) before drawing; it does not depend on the live animation loop running.
An unfinished, missing or mismatched analysis stops export with an explanation
instead of saving a stale or empty field. Complete analysis for the trajectory
range used by the animation before export. Changing job, alignment or loaded
range requires matching EM analysis. GIF refreshes its 256-color palette every
EM frame to retain new hues; this adds encoding work compared with ordinary
video palette reuse. GIF quantization can still lose faint, low-opacity blended
colors against a similar background; PNG retains those rendered colors.
Smooth intermediate fields remain visual
crossfades, not additional Maxwell solutions.

**EM lighting**, in the shared EM settings, offers plain samples, glowing samples
(the default), or glow plus nearby surface illumination. Glowing samples use
soft, self-lit point sprites, including on white figure backgrounds. Their size
scales with export resolution across all tiles and restores afterward. The same
settings apply to standalone maps and simulation overlays.

Surface illumination is an illustrative, normalized lighting approximation: cell
volume and log enhancement weight at most eight spatially aggregated point
lights per field (sixteen during a crossfade). Adaptive subdivision does not
increase the light budget or total brightness merely by adding samples. Lights
cast no extra shadows and fade with their field. This is not optical radiance,
fluorescence, emitted power, or an additional electromagnetic calculation. The
field color scale and exported numeric results retain their original meaning.
Plain/glow modes add no active surface lights. The bounded illumination option
can still cost more on dense molecular scenes; glow is the fast default.

## What is displayed

The 3D field cloud and XY/XZ/YZ slices show **|E_total|²/|E_incident|²** on a fixed
logarithmic color scale, initially 0.1× to 100× with Jet (values above the upper
bound saturate at the palette endpoint); adjust it in the viewport legend.
Cloud thresholding affects display only; slices retain suppressed-field regions.
The result is an intensity map, not a saved complex vector-field volume, optical
cycle animation, SERS factor, or fluorescence enhancement prediction.

The sampling volume spans the outer sphere/shell envelope plus 10 nm on each side.
The UI defaults to field-driven adaptive sampling; a uniform grid remains
available. Quality levels use budgets of 25³, 33³ and 49³ samples. These control
output sampling, not the Maxwell solver or multipole order. Metal
interiors and points within 0.05 nm of their surfaces are masked. Multipole orders
4, 6, 8, 10, 12 are tried until the maximum relative vector-field change is below
1% at exterior volume and gap probes; normalization uses max(|E|, 1). Failure to
converge rejects the map. This is a probe check, not a full spatial convergence
certificate. The reported maximum is the largest sampled grid value; refine the
output grid before interpreting a hotspot maximum.

An optional full-coverage dielectric DNA shell uses an explicit length-based
estimate or specified thickness; see the shell model and limits below. The origami
body, explicit linkers, substrates, faceting, heating, nonlocality/tunnelling, and
thermal ensemble statistics are excluded. Particle motion is captured when
Calculate is pressed. Results clear when particle configuration or optical settings
change; automatic ingestion of MD trajectories is not implemented.

Download saves the scalar field, exterior mask, grid/world transform, exact
optical input snapshot and SHA-256, solver version, optical table hash,
illumination, convergence diagnostics, field evaluator version, stage timings
and model assumptions. This is derived
analysis data, not an authored NADOC structure. Closing removes the overlay.
Only one solve runs per backend process; cancellation kills its worker and a
180 s timeout bounds each calculation. Worker numerical libraries use one thread.

## Field evaluation performance

With MiePy 1.1.0, NADOC reuses radial functions per multipole degree and angular
functions across electric/magnetic terms and ±m when evaluating exterior fields.
The coupled-particle solution, every expansion coefficient, 1% probe convergence
test, surface mask and output grid are retained. There is no dipole approximation,
coefficient pruning or interpolation between frames. Other MiePy versions use
their original evaluator until separately qualified.

The optimized evaluator is checked against MiePy's complex vector fields for
orders 4–12, unequal spheres, both linear and complex polarization, exact/near
poles and synthetic coefficients exercising every mode (normalized vector error
<1e-10). Five complete-map comparisons retained the same convergence orders and
masks and identical exported intensities at six-decimal precision. Equivalent
symmetry-related maxima can exchange the reported peak coordinate through
floating-point roundoff; the field map and peak magnitude agree.

Local single-thread measurements, November 24, 2026, with both evaluators warm:

| Optical snapshot | Grid | Original | Optimized | Speedup |
| --- | --- | --- | --- | --- |
| Plasmonic_test, two particles | 33³ | 10.13 s | 1.05 s | 9.6× |
| Two 20 nm spheres, 5 nm gap | 33³ | 10.52 s | 1.04 s | 10.2× |
| Same close-gap pair | 49³ | 33.81 s | 3.29 s | 10.3× |
| Four asymmetric spheres | 33³ | 34.64 s | 3.26 s | 10.6× |

These are local calculation measurements, not real-time playback rates; process
startup, network transfer and rendering add latency. Reproduce with
`scripts/benchmark_em_analysis.py --output PATH.json` in the isolated interpreter
under `just validate-safe`, with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`.
Benchmark inputs are optical spheres only and do not author NADOC structures.
Receipts are in `.development-artifacts/em-performance/comparison.json`.

## Successive optical snapshots

The engine also accepts a stream of optical input snapshots, one request JSON
per line. It emits one result per line, in order, keeping imports warm and only
one field volume in memory. Each snapshot receives its own input hash and full
convergence check. An invalid or nonconvergent snapshot emits an error and exits
nonzero; later frames are not calculated or filled with stale results.
Three nearby Plasmonic snapshots took 3.89 s in one process (1.30 s/frame including
startup), versus 5.31 s in three fresh optimized processes. These were three
optical snapshots with small particle displacements, not a trajectory/movie test.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  "$EM_ENV/bin/python" -m backend.physics.em_analysis --stream < frames.jsonl > fields.jsonl
```

This is an engine building block, not trajectory import or movie export. The
interactive API retains its isolated, cancellable worker. For a scientific movie,
trajectory frame selection/time mapping, a fixed sampling volume, explicit fixed
laboratory illumination (or deliberate particle-following illumination), and a
fixed color scale must be specified. The current snapshot convention realigns the
grid and illumination with the first pair each time; blindly animating these
snapshots would also change the experiment's illumination as that pair rotates.

## Isolated engine installation

Keep this optional engine separate from oxDNA/NAMD/PyTorch environments:

```bash
EM_ENV="${XDG_DATA_HOME:-$HOME/.local/share}/nadoc/engines/em/.venv"
uv venv --python 3.12 "$EM_ENV"
uv pip install --python "$EM_ENV/bin/python" miepy==1.1.0
```

The API discovers that environment automatically. Set `NADOC_EM_PYTHON` to use
another interpreter. Existing installations with MiePy in the backend interpreter
are also recognized as a fallback. Missing installation produces an explicit error;
there is no dipole or synthetic-field fallback.

Implementation: `backend/physics/em_analysis.py`,
`backend/api/routes_em_analysis.py`, `frontend/src/ui/em_analysis.js`, and
`frontend/src/scene/em_field.js`.

References: [MiePy](https://github.com/johnaparker/miepy),
[Johnson–Christy optical constants](https://doi.org/10.1103/PhysRevB.6.4370).

## Compact volumetric batches

For hundreds of frames, use the derived volume archive instead of JSON arrays:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  "$EM_ENV/bin/python" -m backend.physics.em_volume_archive movie.emvol < snapshots.jsonl
```

Each input line is `{"frame_index": 120, "time_ps": 24.0, "input": {...}}`, where
`input` is the ordinary optical request (`particles`, `resolution`, `polarization`).
Frame indices must be unique nonnegative integers; time is optional, in ps. These
identifiers come from the caller: this command does not yet extract MD snapshots.
An existing destination is refused. The CLI returns a small completion summary;
solver diagnostics go to stderr. An error stops the batch and exits nonzero.

`movie.emvol` is a directory containing an atomic `manifest.json` and one compressed
NPZ per completed frame. Each frame retains **unrounded float64 intensity**, a
bit-packed exterior mask, inputs/hash, grid bounds/basis/origin, illumination,
optical constants/hash, convergence diagnostics and source frame/time. Grid
coordinates are implicit: `origin + local_xyz @ basis`, with inclusive linspace
axes between lower/upper bounds, `ij` indexing and C order (z fastest). Metal
interiors remain masked. No complex vector field is stored; the archived quantity
is the full 3D intensity volume used by the current analysis.

Float64 bytes are shuffled by byte position before ZIP/DEFLATE compression. This
is reversible byte rearrangement, not quantization. The mask uses one bit per
sample, little bit order. NPZ entries are `intensity_f64_bytes` (uint8, 8×N),
`outside_bits` (uint8, ceil(N/8)), and `metadata_utf8` (uint8 JSON). The reader
requires no pickle or new dependencies. It checks the frame SHA-256 and reads only
the requested frame:

```python
from backend.physics.em_volume_archive import read_frame
frame = read_frame("movie.emvol", 17)  # ordinal within selected frames
intensity_xyz = frame["intensity"]    # float64 [nx, ny, nz]
valid_xyz = frame["outside"]          # bool [nx, ny, nz]
```

Committed frames remain readable if a later solve fails. The manifest records
`writing`, `complete`, or `failed`; a killed worker cannot claim completion.
Automatic resume and movie playback are not implemented. Per-frame files avoid
an ever-growing in-memory trajectory and permit future bounded prefetch/parallel
workers. At these grid sizes, one frame is a useful access/compression unit;
HDF5/Zarr spatial chunks can be revisited if much larger volumes need slab access.

Measured locally with 300 entries cycling two independently solved close-gap
optical snapshots per resolution (a **storage benchmark, not 300 MD solves**):

| Volume | Existing six-decimal JSON | Lossless float64 archive | Reduction | Write 300 | Read one frame* |
| --- | ---: | ---: | ---: | ---: | ---: |
| 33³ | 147.3 MB | 26.9 MB | 5.47× | 2.74 s | 1.98 ms |
| 49³ | 480.9 MB | 114.5 MB | 4.20× | 6.19 s | 4.34 ms |

Decimal MB; includes manifest/metadata. *Mean of three random reads, warm filesystem
cache, includes integrity check. Compression varies with geometry. Repeated frames
are compressed independently, so this does not exploit temporal duplication.
Decoded intensities matched the original float64 bytes exactly; masks also matched.
Reproduce with `scripts/benchmark_em_volumes.py --output PATH.json` under
`just validate-safe` in the isolated engine, with BLAS/OpenMP threads limited to one.
Receipt: `.development-artifacts/em-performance/volumes.json`.

## CPU/GPU research and measured applicability (November 24, 2026)

The relevant distinction is **coupled multipole solving versus evaluating the
result at many spatial samples**. Our current 1–4-sphere volume workload is dominated
by the latter. Hundreds of frames provide a second independent parallel dimension.

- **MiePy:** the author's software report gives approximately **12×** GPU speedup
  near 1,000 particles (about 6 s CPU versus 0.5 s GPU), with a crossover around
  25 particles. This is an author benchmark, not an independently reproduced result.
  The JAX backend targets interaction-matrix assembly and linear solving.
  [Author report](https://www.johnaparker.com/blog/gpu-accelerating-miepy/).
  Version 1.1.0's backend dispatch is in
  [interactions.py](https://raw.githubusercontent.com/johnaparker/miepy/v1.1.0/src/miepy/interactions.py);
  its [field evaluation](https://raw.githubusercontent.com/johnaparker/miepy/v1.1.0/src/miepy/sphere_cluster.py)
  still uses CPU NumPy/VSH expansion. Enabling that backend alone does not move
  NADOC's volume evaluator onto the GPU.
- **CELES:** Table 1 reports GPU runtimes of 1,096–15,951 s versus MSTM's
  2,715–39,380 s across 10,000/20,000-sphere cases: **2.19–5.21×** faster.
  Hardware was a Maxwell GTX Titan X versus 12 Xeon E5-2620 cores (six for the
  20,000-sphere cases because of memory). This comparison includes different
  algorithms, lookup interpolation, single precision and preconditioning; it is
  not a pure device-only speedup or a benchmark of few-particle volume movies.
  [Egel et al., 2017, Table 1 and §§3–4](https://arxiv.org/pdf/1706.02145).
- **SMUTHI:** Figure 6 compares CPU direct/iterative solving with GPU iterative
  solving on Xeon/Tesla T4 hardware. The documented GPU coupling path uses lookup
  interpolation and favors many particles. Its near-field tutorial also recommends
  GPU acceleration, but provides no portable numerical speedup for our workload.
  [Paper, Fig. 6 and §4.4](https://arxiv.org/pdf/2105.04259),
  [near-field tutorial](https://smuthi.readthedocs.io/en/latest/_source/04%20examples/02_plotting_the_near_field/discussion.html).
- **BIM-Sim:** a closer example of GPU spatial-field evaluation reports 400–500 ms
  per scattered field for a 512² slice with 400 Monte Carlo samples of one sphere
  on a GTX 970, using float32. This establishes feasibility of accelerated field
  sampling, not equivalent accuracy/physics or a speedup against our implementation.
  [BIM-Sim, 2017, §4.2](https://www.frontiersin.org/journals/physics/articles/10.3389/fphy.2017.00005/full).
- **CPU parallelism:** MSTM uses MPI for multisphere calculations; Meep supports
  MPI and OpenMP field updates/near-to-far work. MPI processes and OpenMP threads
  are distinct mechanisms. Neither provides a justified speedup factor for our
  Python field loop. [Mackowski & Mishchenko, 2011](https://doi.org/10.1016/j.jqsrt.2011.02.019),
  [Meep parallel documentation](https://meep.readthedocs.io/en/latest/Parallel_Meep/).

A local 49³ dimer field-only test at multipole order 10, with fixed 2,048-point
chunks and two repeats, measured **3.08–3.14 s with one Python thread,
2.74–2.78 s with two, and 16.62–16.74 s with four**. All vectors agreed exactly.
Two threads gave only about 1.13×; four were substantially slower. This measures
ThreadPoolExecutor around our current evaluator, not native OpenMP. Python/native
call overhead and contention are plausible contributors; their relative costs
have not been profiled. Production defaults remain single-threaded.

Recommended next experiments are bounded **independent-frame processes**, and a
**compiled CPU or GPU spatial-field kernel**, keeping the small coupled solve on
CPU. GPU work should batch enough spatial samples, reuse allocations/compiled
kernels, and transfer only coefficients/poses in and intensity/mask out. Compare
cold and warm total times including transfers and archive writes. Preserve
float64 initially; any float32/mixed-precision mode needs explicit validation at
hot spots, near surfaces and angular poles against the existing vector oracle.
This workstation exposes an RTX 2080 SUPER with 8 GiB; no GPU performance claim
has yet been measured here. Fixed laboratory illumination/grid and consistent
color scaling remain required movie-workflow work, independent of compression.

## Full multipoles and optical DNA coverage (November 24, 2026)

The solver already used generalized multiparticle Mie theory with coupled electric
and magnetic multipoles. The Solver menu now exposes **Full multipole Maxwell ·
optimized** and **Full multipole Maxwell · reference evaluation**. These solve the
same equations; the second retains MiePy's original exterior field evaluator for
comparison. Neither is a dipole-only model. The coated-shell region uses the same
stable regular/irregular spherical-Bessel expansion in both options.

The UI defaults to a **full-coverage dielectric shell**, independent of the number
of conjugates modeled in the molecular document. No DNA molecules are created,
removed or repositioned. Common optical oligo length (default 20 nt), persistence
length and shell index are explicit analysis inputs applying to every sphere;
these are not inferred from a sparsely modeled subset of conjugates. Bare spheres
remain selectable. Existing API requests omitting `shell` retain bare behavior.
For different experimental coating lengths, separate parameter sets must currently
be analyzed; per-particle shell controls are not yet exposed.

Shell choices are:

- `none`: original bare-metal model.
- `ssdna_wlc`: length-dependent worm-like-chain RMS size proxy,
  `t = sqrt(2 lp L - 2 lp² (1 - exp(-L/lp)))`, `L = 0.59 N` nm.
  This equates chain RMS end-to-end size with effective radial shell thickness as
  an **explicit modeling assumption**, not a validated optical calibration or a
  full grafted-brush theory. It does not model duplexes, secondary structure, salt,
  curvature-dependent grafting, or linker contour length.
- `manual`: specified effective radial thickness, appropriate for measured or
  independently calibrated shells.

`lp=2.5 nm` is a poly-T pure-water literature value, not an origami-buffer default
validated for Mg²⁺. `n_shell=1.7` is an adjustable optical-model starting point
from prior DNA-coated gold studies, not a universal hydrated DNA index. Full
coverage means a continuous angular dielectric shell, not pure dry DNA filling
all its volume. The user must choose an appropriate **effective** index.
All choices and resolved thicknesses are exported in `inputs` and `dna_shell`,
and therefore retained in volume archives and included in the input hash.

The coated calculation solves tangential E/H continuity at the core/shell and
shell/water boundaries at each multipole order, then recomputes the full coupled
particle solution using those scattering coefficients. Maps include the field
inside the DNA dielectric; only metal interiors remain masked. Coefficient parity
against MiePy's core-shell solver, a transparent-shell limit and outer-interface
continuity are checked in `tests/em_shell_oracle.py`. Shell settings cannot be
implemented by merely enlarging a gold sphere or changing water's index.

**Concentric shells must not overlap or touch.** The calculation explicitly rejects
such configurations instead of clipping thickness, changing particle positions,
or treating shell material as water. In close experimental dimers, DNA can compress
or interpenetrate; representing that requires a spatially resolved dielectric
geometry and an appropriate solver. Reducing thickness is justified only by a
chosen/measured effective-shell model, not as an automatic numerical workaround.
The WLC default can thus reject close dimers, including the current Plasmonic
configuration. Bare mode and specified thickness remain available and explicit.

### What is known about oligo length versus shell size

- **Pease et al., 2007:** gas-phase measurements of dried ssDNA-coated gold showed
  approximately square-root length scaling consistent with random coils. Their
  reported `H` is the **diameter increment**, twice radial shell thickness. Dry
  morphology should not be transferred directly to hydrated optical models.
  [Primary paper](https://mrzgroup.ucr.edu/sites/default/files/2019-02/2007_jpc_dnaongold.pdf),
  DOI 10.1021/jp075571t.
- **Falabella et al., 2010:** studied poly-T lengths 5–30 on nominal 10/20 nm gold.
  A fully extended-chain model better predicted sedimentation, but overestimated
  measured hydrodynamic diameters beyond five bases; WLC sizes followed those
  diameters more closely. Their WLC used 0.59 nm/base and lp=2.5 nm. This illustrates
  that even different size measurements need not imply the same shell model.
  [NIST manuscript, Eq. 9 and Fig. 7](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=904829),
  [published article](https://doi.org/10.1021/la100761f).
- **Vargas-Lara et al., 2022:** simulation/theory explicitly examines grafted-chain
  length, density, conformational fluctuations and hydrodynamic screening. A
  hydrodynamic radius is not simply the furthest DNA endpoint or a sharp optical
  dielectric boundary. [Primary article](https://pmc.ncbi.nlm.nih.gov/articles/PMC9514572/).
- **Salt effects:** in-situ SAXS of lattice-bound ssDNA brushes found stronger
  contraction with divalent salts and collapse with trivalent salts. Length alone
  cannot establish thickness for an arbitrary experimental buffer.
  [Primary study](https://doi.org/10.1039/D1SM01171E).
- **Optical calibration:** the Thacker dimer study estimated a 2.5±0.5 nm ssDNA
  coating from TEM and inferred n≈1.7 from optical spectra; it does not establish
  a universal nt-to-optical-thickness law.
  [Primary paper](https://www.repository.cam.ac.uk/bitstreams/69ccd032-598e-4309-912e-dcd3dc866e27/download).

The evidence supports length dependence, but does **not** establish a unique
transferable function `optical thickness = f(nt)` across sequence, salt, particle
size, grafting density and hydration. Use the length proxy for sensitivity studies;
use experimental shell measurements and spectra to calibrate quantitative claims.

Validation for the shell/selector change: 21 focused backend tests and eight
frontend tests pass. The isolated browser flow computed bare and coated maps on
`Plasmonic_test.nadoc`, exercised solver-setting invalidation and overlay teardown,
and confirmed the source file hash was unchanged. Its temporary workspace and
artifacts were verified removed. Focused lint and whitespace checks pass.

## Surface-distance adaptive sampling (November 24, 2026)

Choose **Adaptive · field variation and hotspots**, **Adaptive · near particle
surfaces**, or **Uniform grid** in the Sampling menu. Existing API/CLI requests remain uniform unless `"sampling":"adaptive"`
is supplied. Adaptive quality selects a base leaf/sample budget of 15,625,
35,937 or 117,649, plus the close-gap refinement below. All particle pairs and both metal/coating boundaries participate;
refinement is independent of the illumination and computed field strength.

The octree partitions the bounding box into nonoverlapping rectangular cells.
It prioritizes cells using cell width divided by a target spacing that grows with
conservative distance to the nearest spherical interface. Cells wholly inside
masked metal are not refined. The nominal surface target is `0.25 * 33 / resolution`
nm; distant cells target at most the longest box dimension divided by eight.
The budget can prevent reaching the nominal target. Actual minimum/maximum cell
widths and budget exhaustion are reported; these are not accuracy guarantees.

Each leaf stores the field evaluated directly at its center, with the usual metal
mask. These are not interpolated values or cell averages. The multipole probe
convergence check remains separate. Increasing sampling quality remains necessary
to assess hotspot maxima; a distance criterion does not certify field error.

Adaptive results have `shape:[N]`, `sampling.layout:"octree"`, and local-frame
`sample_positions_nm` and `cell_sizes_nm` arrays of shape `[N,3]`. Apply the exported
basis/origin for world coordinates. Cell volumes are the product of the three
widths: use spatial weights when estimating volume integrals, not an unweighted
average of densely clustered samples. Cells crossing metal boundaries require
additional boundary treatment for accurate integrals; the center mask is not an
exact exterior-volume fraction.

The renderer uses actual sample positions. Adaptive slices select cells intersecting
the requested physical plane and show their center values; they are sampled slabs,
not freshly solved planar fields. Cloud point density represents sampling effort,
not optical intensity. Compare colors rather than cloud opacity. Frames may have
different cell layouts; animations must use their own coordinates, never match
samples by array index. No temporal interpolation has been introduced.

Archive format v2 stores adaptive positions and cell widths as compressed float64
arrays alongside the lossless intensity/mask data. The reader also accepts existing
v1 uniform archives. JSON exports retain the complete adaptive geometry. Molecular
structures and feature histories are unchanged.

Adaptive validation: 31 focused backend tests and nine frontend tests pass.
The isolated browser flow passed uniform and adaptive/coated maps, physical slice
display, settings invalidation and overlay teardown on `Plasmonic_test.nadoc`,
with an unchanged source-file hash. Temporary workspace/cache/browser artifacts
were verified removed. Focused lint and whitespace checks pass.

## Default-shell rejection and recovery

For the current `Plasmonic_test.nadoc`, the 4.55 nm metal gap cannot contain
two default 20-nt WLC shells (6.83 nm each; combined unrounded thickness 13.65 nm).
The panel now retains the backend rejection, including gap and required shell
clearance, instead of replacing it with “No EM result returned”. It offers
**Calculate without DNA coating** as an explicit recovery action. This changes
the visible coating selector to bare mode and starts a new solve; it never
silently clips shells or substitutes different physics. A calibrated thinner
shell can instead be entered manually. Other errors retain their own explanation
and do not offer an unrelated coating workaround.

The default-error/recovery path is covered by eight panel tests, ten backend shell
tests and an isolated browser check starting from untouched defaults. The browser
verified successful explicit bare-mode recovery, a subsequent coated solve, unchanged
source-file hash and cleanup.

## Extra close-gap samples and dot size

Adaptive sampling now refines the neck between facing metal surfaces for every
particle pair with a metal gap ≤10 nm. The neck radius is `sqrt(min(radius) * gap)`;
conservative cell intersection includes the adjacent boundary cells. Cells wholly
inside masked metal are excluded. Each selected base cell is split along its two
longest dimensions into four equal-volume cells, each evaluated at its own center.
This quadruples local sample density rather than merely increasing a priority that
could be displaced by the global budget. The base surface-distance grid elsewhere
is retained; uniform sampling is unchanged.

The extra allocation is bounded by four times the base budget in the worst case;
usually only a small subset of cells is selected. Exports report the base budget,
total cap, refined-cell count, close-gap threshold and multiplier. Archive validation
accepts the enlarged bounded layout. Compare quality levels for convergence; more
samples do not change the multipole solver or its model limitations.

**Sampling dot size** controls point diameter from 1 to 12 screen pixels in half-pixel
steps, for both cloud and slices. It redraws immediately without an API request,
changing scientific data, invalidating the map, or altering downloaded results.

Close-gap refinement/dot-size validation: 13 focused backend tests and 13 frontend
tests pass. The isolated Plasmonic browser flow verified refined maps, a live
6-pixel dot material, retained export readiness, slices, coated recalculation and
cleanup. Source-file hash unchanged; temporary workspace verified removed.

## Field-driven sampling

The UI now defaults to `sampling:"field_adaptive"`. API/CLI defaults remain uniform;
`sampling:"adaptive"` retains geometry-only refinement. Field-driven mode first
solves the surface/gap seed grid, then estimates `|gradient log10(1 + I)| * cell_width`
from up to eight nearest unmasked neighbors, where `I = |E_total/E_incident|²`.
A variation estimate greater than 0.1 decades is a refinement candidate. Bright
regions also qualify when intensity exceeds the maximum of 10, a quarter of the
current sampled peak, and twice the median exterior intensity. This uses intensity,
not the phase-sensitive gradient of the complex vector field.

Candidates are ranked by variation/0.1 or hotspot intensity/threshold. Selected
cells split into eight children and each child receives a fresh Maxwell evaluation;
unchanged cells retain their computed samples. Re-estimation continues for up to
three passes, with at most one base quality budget of extra leaves beyond the
surface/gap seed (total absolute cap ≤5 times the base budget). Each pass spends
at most a third of that additional budget. Cells at or below a longest width of
`0.125 * 33 / resolution` nm stop refining. These bounds complement the existing
worker timeout. Metal masks are excluded from gradient estimation, not treated
as artificial zero fields.

The panel and export report pass count, refined cells, actual sample count, extra
field evaluations and remaining candidates/width-limited cells. A limit warning
means further variation or hotspot refinement was requested. This is a sampling
heuristic, not a certified interpolation-error estimator or a new Maxwell solver.
An unsampled hotspot can still be missed; the geometric/gap seed helps but does not
guarantee detection. Compare sampling quality levels and multipole convergence
separately. Field-driven layouts vary between trajectory frames; use exported
positions and cell widths rather than assuming array-index correspondence.

Field-driven validation: 28 focused backend tests and 13 frontend tests pass.
Manufactured fields verify moving-hotspot refinement, steep variation, constant-field
non-refinement, mask handling, direct sample values and archive round-trips. The
isolated Plasmonic browser flow passed the new default mode, error recovery,
field-refinement status, slices/dot-size control and coated recalculation. Source
file hash remained unchanged; temporary workspace and browser artifacts removed.

## Experimental GPU trajectory processing (November 24, 2026)

The optical snapshot archive CLI accepts `--compute-backend auto|gpu|cpu` (default `auto`).
It consumes the same `{frame_index,time_ps?,input}` JSONL envelopes, preserving
frame identity, optical inputs, backend/device metadata, convergence diagnostics,
and lossless float64 volumes. This is a trajectory-processing engine, not yet an
MD-file importer, movie exporter, or UI GPU selector. It evaluates each frame
independently; no fields are interpolated between frames. A single persistent
process reuses the CUDA context and compiled kernel across frames.

Install the optional dependencies into the **isolated EM environment**:

```bash
uv pip install --python "$EM_ENV/bin/python" threadpoolctl==3.6.0 cupy-cuda12x==13.6.0 \
  nvidia-cuda-nvrtc-cu12==12.9.86 nvidia-cuda-runtime-cu12==12.9.79
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 "$EM_ENV/bin/python" \
  -m backend.physics.em_volume_archive /path/to/new/archive \
  --compute-backend gpu < optical-snapshots.jsonl
```

Requires a compatible NVIDIA CUDA 12 driver. CPU runs do not import CuPy. An
explicit GPU request fails if unavailable; it never silently becomes a CPU run.
The trajectory CLI selects a concrete backend and records it in each snapshot input;
the lower-level serial `write_snapshots` helper still accepts per-frame backends.
The archive retains completed frames if a later frame fails, and refuses overwrite.

`em_gpu.py` evaluates the full outgoing electric/magnetic vector spherical
harmonic expansion in float64/complex128, with one CUDA thread per spatial point.
It retains every mode through the converged order (maximum 12). The small coupled
sphere solve and convergence probes remain on CPU. Sampling, masks, compression,
incident field, near-pole convention and dielectric-shell **interior** evaluation
also remain on CPU. Thus this is explicitly a hybrid implementation. The original
optimized and reference CPU solvers remain unchanged and selectable. GPU requires
the qualified MiePy 1.1.0 optimized solver and a real water background.

Exterior batches are bounded at 65,536 points, avoiding one kernel launch per tiny
CPU batch; this is internal field batching, not large-trajectory chunk management.
Device-to-host copies synchronize before intensity/refinement processing, so
reported elapsed times include GPU execution and transfers. Adaptive passes may
select different cells if floating-point noise breaks exact score ties; full-map
comparisons must check coordinates rather than comparing array ordinals blindly.
Refinement remains budget-limited, not a certified spatial-error tolerance.

Validation: `NADOC_TEST_EM_GPU=1 just test-focused tests/test_em_gpu.py` opts into
real-device checks. The vector oracle compares physical and synthetic all-mode
coefficients against independent MiePy fields for orders 4–12, three polarizations,
near/far/surface/pole points, plus four unequal coated spheres. Optional hardware
checks otherwise skip, while backend failure/selection contracts still run.
Run `scripts/benchmark_em_gpu.py --output PATH.json` in the EM environment under
`just validate-safe`, with BLAS/OpenMP limited to one thread, for matched CPU/GPU
full-frame solves, compressed archives, reopened-output comparisons and cleanup.
The benchmark reads Plasmonic_test.nadoc without changing it and creates optical
snapshots only; it does not author a molecular structure or simulate MD.

### Initial matched trajectory benchmark

RTX 2080 SUPER (8 GiB), Ryzen 5 3600, one CPU compute thread, three distinct
snapshots per case, field-adaptive mode, full solve plus compressed volume writes:

| Workload | CPU s/frame | GPU s/frame | Speedup |
|---|---:|---:|---:|
| Standard, ~4.3–4.8 nm metal gaps, bare | 3.579 | 1.288 | 2.78× |
| Standard, ~24.3–24.8 nm metal gaps, bare | 1.711 | 1.064 | 1.61× |
| Fine, ~4.3–4.8 nm metal gaps, bare | 10.762 | 3.852 | 2.79× |
| Standard, close, 0.5 nm shell (n=1.7) | 5.810 | 2.992 | 1.94× |

These are 12 optical snapshots solved on **each** backend, not 100 MD frames.
GPU initialization took 0.827 s with a compiled kernel cache already available;
first-ever compilation is not represented by this warm initialization number.
Rendering/video encoding and large-trajectory import are excluded. The 0.5 nm
shell is an explicit test setting, not the overlapping default WLC shell.
With 90 separated and 10 close Standard bare frames, the measured means extrapolate
to 190 s CPU versus 109 s GPU (~1.74×), plus startup. Separation does not guarantee
a hotspot-free frame; these are geometric representatives, not an intensity-class
frequency measurement. CPU concurrency is not included in this comparison.

All compared peak intensities agree within 1.3e-15 relative error. Where adaptive
cell selections match exactly, complete intensity maps agree within 9.2e-14
normalized error. Some selections differ due to symmetry-related ranking ties;
those maps are not claimed pointwise identical. The independent complex-vector
oracle qualifies the evaluator separately from adaptive cell-selection decisions.
Receipt: `.development-artifacts/em-performance/gpu-trajectory.json`.

## Automatic backend and parallel CPU trajectories

The archive CLI defaults to `auto`. CPU processing now uses **separate processes
for independent frames**, with one numerical thread per process, rather than
multiple Python threads contending in the same field evaluator. Install
`threadpoolctl==3.6.0` in the isolated EM environment for both CPU and GPU modes.
No CUDA packages are needed for CPU-only installations.

```bash
uv pip install --python "$EM_ENV/bin/python" threadpoolctl==3.6.0
"$EM_ENV/bin/python" -m backend.physics.em_volume_archive /path/to/new/archive \
  --compute-backend auto --workers 2 < optical-snapshots.jsonl
```

`--workers` is an upper bound, not a reservation or an instruction to ignore other
jobs. The policy caps CPU concurrency at four, reserves two physical cores when
possible, reduces concurrency with CPU load/available memory, and caps it at two
when a recognized simulation (including oxDNA) is active. Workers have reduced
OS priority where supported and numerical thread pools are explicitly capped.
Less than 2 GiB available host memory stops before starting another batch.
Memory estimates are conservative allowances, not hard per-worker quotas.

Automatic mode first computes one CPU pilot frame. It probes the GPU **only** if
telemetry shows no external compute process, no recognized simulation, low GPU
utilization and at least 2 GiB free device memory. If eligible, it computes that
same frame on GPU and compares measured wall times, including worker startup.
GPU must beat the estimated parallel CPU throughput (`CPU pilot / worker count`)
by 15%. The selected pilot result is reused in the archive. This is a conservative
first-frame heuristic, not a guarantee that every subsequent geometry favors the
same backend; parallel CPU scaling is estimated, not benchmarked in the pilot.
No GPU, unknown telemetry, unavailable CUDA dependencies, or a failed GPU pilot
leads to CPU selection, with the reason/error retained in manifest `processing`.

Resource observations repeat between bounded batches (at most one frame per
worker in flight). CPU concurrency can decrease. If a GPU becomes occupied,
automatic mode moves remaining frames to CPU; it does not repeatedly probe a busy
GPU. Explicit GPU mode instead stops and retains completed frames. The optional
`--allow-busy-gpu` flag explicitly permits contention; it is never enabled by
autodetection. Checks cannot prevent a different job starting during an in-flight
frame and do not preempt that frame. Telemetry is conservative across detected
GPUs; selecting among multiple devices is not implemented.

Only the coordinator writes the archive, in input order, retaining source frame
indices/times. A failed frame leaves a readable completed prefix and a failed
manifest; later work in that bounded batch is discarded. No input trajectory is
loaded wholesale and no molecular document or running simulation is modified.
This adds scheduling, not automatic resume/chunk recovery or MD-file ingestion.
Both backend selection and subsequent resource-driven changes are recorded in
the archive manifest; each volume records its actual backend and optical inputs.

## Tools menu and simulation visualization integration

EM Analysis is available under **Tools → Nanoparticles → EM Analysis**. Optical
and display settings persist in local browser storage across sidebar closure and
reload. The oxDNA and NAMD Visualizations cards share these settings, with an
**EM visualization** checkbox and adjacent options gear. The gear opens settings
without starting a separate standalone solve. Display/Flex/Deviation overlays use
the actually rendered nanoparticle positions; changing a stable displayed state
invalidates and recalculates its map. A moving live display waits for a stable
snapshot rather than repeatedly launching/cancelling workers.

Once a trajectory is loaded, **EM Analysis** appears at the bottom of its card.
The confirmation uses NADOC’s shared centered modal, paragraph text and footer
buttons (Cancel/primary Continue), with Escape, close and backdrop dismissal. It
states the stable number of frames in the selected trajectory, including pages
still streaming. Continue reads missing pages and retains only optical sphere
inputs, then starts a resource-aware CPU/GPU archive job. It does not scrub the
scene; oxDNA page reads do not reconstruct DNA meshes. Source indices and the selected stride/scope
are retained; changing trajectories or disabling EM cancels preparation. A yellow strip immediately beneath the scrubber marks completed frame
positions (including gaps); status and tooltip report the percentage of submitted
loaded frames analyzed. Gear and analysis controls use shared NADOC buttons/icons
and explain their actions on hover.

Completed saved-frame maps follow scrubbing on every render tick, without the
former 400 ms display throttle. A sequential look-ahead cache fetches up to 32
volumes and prepares display arrays ahead of playback, using a
128 MiB memory allowance (at least the current volume). Raw numeric fields use
float64 typed arrays, masks use bytes, and the allowance includes prepared
positions/colours. The endpoint serializes NumPy arrays directly with orjson in
a worker thread, avoiding recursive FastAPI scalar conversion on the event loop. Render objects and
same-sized GPU buffers are reused. Cached frame changes require no HTTP request.
The selected frame has a separate demand lane: a seek cancels obsolete demand,
stops the old look-ahead sequence, and requests the new field on the next render
tick. Normal playback preserves in-flight requests and the look-ahead sequence
instead of treating every advance as a seek. Shared requests are coalesced, late cancelled results are discarded, and
the current field is protected from look-ahead eviction. Progress polling no
longer waits for volume downloads. A separate status explains buffering,
unfinished/unsubmitted analysis, or a displayed-particle pose mismatch.
Uncached jumps, initial buffering and unusually large maps can still take time;
this is not a guaranteed frame-rate claim for arbitrary trajectories/hardware.

Starting trajectory EM enables Smooth playback, with **0.5 seconds between saved
frames** (two saved frames per second). Particle motion and EM transitions share
the same playback clock. The player waits for both calculated endpoint fields
before starting a transition; if the next pair is late, it holds at the saved
endpoint and resumes without skipping frames. Stage and loop boundaries retain
the player's existing discontinuous transitions. The checkbox remains available
for saved-frame-only playback; disabling EM restores its previous preference
and normal playback timing.

Between endpoints, two prepared point clouds crossfade using GPU material
opacity. Adaptive cells are not paired by array index: their locations and counts
can differ between solves. This is **visual interpolation**, not a Maxwell solve
at the intermediate particle pose, nor pointwise interpolation of intensity or
phase. The status identifies it as such. Pause and exact scrubbing return to
calculated saved-frame data. The pose check uses the actual molecular interpolation
coordinates; unrelated pose changes still clear the overlay. No interpolated
field is written to the scientific archive or molecular history.

The active field pair and pending endpoint reads are protected from cache eviction.
The memory allowance may be exceeded by that small working set for very large
fields; background look-ahead remains bounded. Prepared arrays are uploaded when
the pair or display settings change; animation ticks change only opacity.

oxDNA cores use recorded centers from 6/9/12-value transport layouts. NAMD's
current implicit fixed-sphere model retains the displayed fixed centers when
there are no moving gold-core records; the confirmation explicitly identifies
this. No motion is inferred from DNA or linker coordinates. Compact gold display
updates likewise use their centers without inventing an unrecorded orientation.

Changing optical settings invalidates a trajectory cache and requires Continue
again for a full rerun; changing dot size/slice/color threshold redraws existing
results. Closing the options sidebar preserves settings and the active simulation
overlay. Disabling the EM toggle, switching away from its analyzed trajectory,
or disposing the controller cancels work and deletes the derived cache.

API: `POST /api/em-analysis/trajectories` accepts bounded validated
`{frames:[{frame_index,input}]}` optical envelopes. GET on the returned job ID
reports progress and selected CPU/GPU policy; `/frames/{ordinal}` reads a completed
volume; DELETE cancels the process group and removes scratch. One EM calculation
runs at a time across snapshot and trajectory endpoints. Results are temporary,
with four cached jobs maximum and 30-minute idle expiry checked on access; the
server also cleans caches/workers on shutdown. Storage is preflighted using a
conservative uncompressed-volume allowance. Simulation jobs and part histories
are not written by this analysis.
