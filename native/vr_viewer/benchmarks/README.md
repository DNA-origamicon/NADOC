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
matrix multiplication for sphere instances whose positive similarity transforms
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
