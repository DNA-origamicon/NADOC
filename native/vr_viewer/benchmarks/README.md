# Offline exported-mesh experiment

`nadoc-vr-view-mesh-benchmark` is an explicit diagnostic executable. It reads a
preserved version 5/6 `.viewtools` file and a successful application-eye capture.
It never initializes OpenXR or submits images. Run it only in a coordinated GPU
measurement window through the original `scripts/validation_guard.sh`, with
build/output/TMPDIR on Archive. Another rendering process can affect its timings.

```bash
python native/vr_viewer/benchmarks/prepare_view_mesh_benchmark.py \
  EXISTING_CAPTURE/evidence.json NEW_STATE.txt
cmake --build EXISTING_ARCHIVE_BUILD --target nadoc-vr-view-mesh-benchmark -j1
EXISTING_ARCHIVE_BUILD/nadoc-vr-view-mesh-benchmark \
  PRESERVED.viewtools NEW_STATE.txt NEW_OUTPUT_DIRECTORY 12
```

The executable uploads the original instance records once, applying the same
saved normalization as the viewer. It uses the production shader source, small
mesh grouping helper and exact indexing helper. Both saved eye poses/FOV and the
same-frame model presentation are used. It preserves batch/instance/triangle
order. Original triangle/line/sprite arrays, menus, floor, mirror, canonical
shadow rendering and runtime submission are excluded and counted in the report.
The shadow sampler uses a declared synthetic 2048-square depth pattern, not the
live canonical shadow map. This is a mesh experiment, not a full-frame benchmark.

Eight initial conditions isolate indexing, blending, sphere-batch backface culling, shadow sampling,
a constant-color fragment shader and a one-pixel viewport. The last two change
the image intentionally; the constant fragment may also eliminate unused vertex
outputs, so it is not a fragment-only isolation. Culling remains diagnostic.
Three further conditions compare exact indexed groups of eight, direct normal
matrix multiplication for instances whose positive similarity transforms
pass a declared relative Gram residual bound of 2e-5, and their combination.
The direct-normal experiment changes floating arithmetic; its original-pixel
differences are reported, without an exact-equivalence claim. No condition changes the
production renderer. Each has three warmups; timed order alternates forward and
reverse. GPU query results are synchronously read only in this offline tool.
Raw elapsed samples include scheduling gaps and other-context GPU contention.

The result includes exact RGBA/depth/object-ID differences against the array
baseline, coverage and PPM images for baseline, culling and constant fragment.
Captured JSON pose precision is retained. Determinant/affine checks, outward face
counts and conservative camera/near/far bounding-sphere checks help assess culling,
but do not prove manifold closure or authorize culling in arbitrary views.
Pixel equality at one saved viewpoint is not a universal visual-equivalence proof.

## Indexed group-size sweep

Pass `groups` after the iteration count to compare original arrays and indexed
groups of 1, 2, 4, 8 (production), 16, 32 and 64. Each size gets a separately
compiled constant shader, including the unchanged production eight-instance
shader. The same vertex/index buffers preserve primitive and instance order;
tails draw only the remaining instances. Expanded experimental mesh storage is
bounded at 64 MiB. Small bond batches keep their production grouping.

This mode fails on blank output or any color, depth or object-ID difference.
It is an offline experiment, not authorization to change production defaults.
Use at least two alternating-order repeats before interpreting small differences.

To export a current completed production trajectory using the registered CPD
playback workflow, set `NADOC_CPD_GPU_EXPORT=1` and
`NADOC_VR_TRANSFORM_UPDATES=0`. The opt-in export runs after timing, seeks a
resident frame, copies the actual browser Blob, applies the production backend camera rotation,
and checks that the stereo capture
has the identical native snapshot version. The wrapper owns private job copies;
exported `<representation>.viewtools` files stay in its Archive report directory.
Export-mode playback timings use full snapshots, not production transform updates.

The sphere-culling diagnostic recognizes both historical 420-record and current
2160-record exported spheres. This vertex-count check is only a diagnostic
selector; it is not a closed-mesh proof and must not become production eligibility.
Always inspect offline framing against submitted-eye pixels: matching snapshot
versions alone does not detect a missing backend view rotation.

## Vertex-fetch experiments

Pass `cache` after the iteration count to compare production group-eight buffers,
16-bit indices, deterministic triangle cache ordering, and compact vertices.
The compact condition uses 24-byte position/normal records for eligible indexed
groups, with their byte-identical constant color and UV supplied as GL generic
attributes. Eligible small bond groups use the same packing. Production retains
original fallback buffers and caps extra packed CPU storage at 1 MiB per view;
`NADOC_VR_COMPACT_VIEW_VERTICES=0` disables packing for comparisons.

Cache mode reports all color/depth/ID differences without treating experimental
differences as a tool failure. Check the results explicitly. Triangle reordering
and 16-bit indices remain offline experiments; neither is a production default.
