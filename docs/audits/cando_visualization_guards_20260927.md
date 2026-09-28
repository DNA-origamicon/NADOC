# CanDo completed-result visualization guards

Scope: all four CanDo visualization modes, color-scale changes, selection/Off/tab
transitions, and RMSF/deviation graphs on completed assembly jobs. Original input:
`workspace/cando_jobs/8ed8754fac18` (BigO-poly, 424,144 nucleotide records,
211,680 FEM nodes, completed thermal job). No solver rerun or original result edit.

## Findings and changes

- Nucleotide views rebuilt a full job-snapshot sphere/slab scene on each selection.
  Prior execution audit measured roughly 80 s per software-rendered full BigO
  frame. Above 50,000 nucleotides, all three nucleotide modes now draw every
  position in point buffers. The CanDo-style mode retains every true axis segment
  and crossover connector in line buffers. Spatial tiles cull offscreen data and
  use a progressive, zoom-dependent draw prefix; close-up tiles expose full detail.
  Line endpoints are sampled as indivisible pairs, so no new connectors are invented. The status explicitly identifies this rendering
  choice. This preserves positions/identities and scalar coverage at float32
  WebGL precision; it does not preserve sphere/slab silhouettes or tube radius
  appearance at close zoom. Small results retain their normal detailed glyphs.
- Large views use a versioned compact binary endpoint, zero-copy typed-array
  decoding, and small spatial tiles with a shared shader. No snapshot geometry, full display JSON, or
  ensemble trajectory downloads are needed. Browser transfer and decode guards
  reject oversized/malformed buffers (256 MiB budget). Failed compact loads do
  not fall back to the expensive full-scene path.
- Scalar recoloring changes a small color texture and shader uniforms. It does
  not regenerate nucleotide geometry or a million-entry string-key color map.
  Smaller cylinder views also recolor their existing GPU instances in place.
- Thermal cylinder joints previously searched every axis node for every endpoint
  (~9.6 billion distance comparisons on BigO). Legacy mapping now indexes exact
  endpoint coordinates. Large views construct connectors against the actual
  representative FEM axis on the backend. Backend cylinder grouping is one pass
  rather than a full-axis scan for every helix. The cylinder overlay is drawn once.
- The shared assembly renderer now hides source roots, rather than relying only
  on shader visibility and zero instance counts. This excludes hidden native
  geometry and its LOD/upload hooks from rendering. Source rebuilds respect the
  external visibility state. Loading a large result hides the expensive native
  scene immediately; Off/failure restores it.
- Controller epochs are checked after paint yields; aborts, Off, tab leave,
  deselection and rapid radio/job changes cannot let stale work overwrite or
  cancel the newest display. Partial overlays and response caches are released.
  Panel loading status cannot be overwritten by an older active mode.
- Compact result bounds drive camera clipping while native assembly geometry is
  hidden. Display state never mutates the job snapshot or live topology.
- Deviation compares the conformation actually displayed with the intended
  geometry, including direction and loop-copy identity. Previously thermal
  positions were colored using deviation of the static mean. The direct
  deviation endpoint follows the same representative-conformation convention;
  the autorefine computation itself is unchanged.
- Heavy deviation/cylinder preparation runs in worker threads. Compact builds are
  serialized to prevent overlapping requests from multiplying peak memory; files
  are written atomically and reused until source result/snapshot timestamps change.
  These disposable derived files live in the owning job directory.
- Large metric graphs use the compact scalar/identity columns, aggregate with
  event-loop yields, coalesce duplicate requests, cancel abandoned loads, and
  retain at most the selected job's two metrics. Helix sorting reuses one numeric
  collator. CSV export retains all aggregated rows (float32 display scalars).

## Validation

Completed BigO Playwright exercise: **1 passed (3.4 min)**. Every mode retained
424,144 nucleotide records or 465,480 cylinder endpoint records (232,740 segments),
and rendered non-black colored pixels. Camera changes, scale bounds/colormap,
RMSF (211,680 rows) and deviation (212,464 rows) graphs, delayed stale-response
races, and Off passed. No console errors. No snapshot, display-JSON, representative
JSON, or ensemble requests. Original assembly bytes and in-app assembly state
were unchanged. Test storage and reports were verified removed.

| View | Largest post-load 50-ms timer gap | GPU output at whole-assembly zoom |
|---|---:|---:|
| Predicted shape | 111 ms | 32,097 points |
| RMSF | 173 ms | 32,097 points |
| Deviation | 154 ms | 32,097 points |
| CanDo style | 183 ms | 50,333 line segments |

All four had zero triangles. Full-resolution records remain in memory; the
zoom-dependent index prefixes and frustum culling only affect drawing. The initial
native-to-result transition had a 1.23 s gap in software WebGL; subsequent loading
periods had maximum gaps of 200–277 ms. First-use deviation preparation is still
noticeable backend work, but the current display remains responsive. The logged
7.6–27.3 s per-mode scenario times include loading, camera/scale interactions,
pixel checks and a 1 s sampling wait; they are **not** pure load-time benchmarks.

Focused backend transport/cache/route checks: **8 passed**. Focused frontend
checks cover parser budgets, exact identities, progressive endpoint pairing,
zoom-to-full-detail, GPU lifecycle, hidden native source roots, linear joint lookup,
metric request coalescing/cancellation, and stale controller/panel requests.
Final frontend regression: **554 files passed; 7,127 tests passed, 1 skipped**.
`just smoke`: **23 passed (2.1 min)** in a disposable workspace on ports
8001/5174; cleanup verified. Production build and `just lint` passed. Build retains the existing large-chunk
warning. `git diff --check` passed.

The initial backend aggregate exposed an object-ID reuse bug in the shared
simulation fingerprint cache. Cache hits now verify a weak reference to the
actual design, without keeping closed large designs alive. A deterministic
collision regression failed before the fix; all **18 staleness tests** pass after it.
The initial FAST run also exceeded its 90 s aggregate backstop without any
individual test exceeding its budget. The slow-test triage skill found no
per-test violators; no budgets or classifications were weakened.

The opt-in browser test is `frontend/e2e/assembly_cando_visualization.spec.js`,
run with `scripts/verify_assembly_fem.py --visualization JOB_DIR`. Its disposable
workspace receives copies of only job.json, design.json, display.json, rmsf.json,
and thermal_representative.bin. Copied identity metadata associates the test job
with the `__e2e__` assembly. Generated caches, documents, revisions, autosaves,
logs and bridge credentials are removed in `finally`, after terminating only
workspace-owned processes. Playwright teardown/reporter remove its output.
Original assembly sources and completed result files remain read-only.

Initial attempts caught a copied-project-ID fixture mismatch and exposed the
native-render transition/hidden-source overhead; these were corrected rather
than treated as successful app verification. Drawing all 424k points still took
0.65–0.9 s in SwiftShader (zero triangles, one draw), motivating adaptive detail.
The final test copy uses native Hull Prism to bound setup/Off rendering time;
its physical result data and all four result modes are unchanged. Timer gaps during loading and after
the result is visible are measured separately. Headless Chromium uses SwiftShader;
these timings are not hardware-GPU performance guarantees.

`main.js` net delta for this task: **+3 lines**, limited to import/factory wiring,
a forward declaration, and consuming the compact result's camera bounds.

## Final backend gate

`just test-smart` decision: **FAST**. **9,319 passed, 15 skipped, 8 failed**
(96.48 s pytest; 104 s guard, above its 90 s aggregate backstop). Seven failures
require the unavailable external photoproduct review packet under
`/media/jojo/Archive/NADOC_archive/photoproduct_evidence/`; the eighth is the
existing CPD preview golden mismatch. No CanDo or staleness test failed.
Final slow-test triage: 9,342 tests, 419.6 aggregate worker-test seconds, no
per-test violators; slowest individual test 4.7 s. Per the triage skill, aggregate
size alone does not justify moving arbitrary tests to the slow suite.

Selector notice, verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

No broad/full sweep was run. Temporary verification logs were removed after
recording these results; browser workspaces, reports and test bridge credentials
were verified absent. No commit or push was made for this change.
