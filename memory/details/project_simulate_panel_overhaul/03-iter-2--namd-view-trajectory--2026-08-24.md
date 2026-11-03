# ITER-2 — NAMD View trajectory — 2026-08-24 — supporting detail

[Topic head](../../project_simulate_panel_overhaul.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

**Correctness/equivalence:** the real 200-frame binary metadata exactly equals JSON and all
coordinates match at `rtol=1e-6`, `atol=2e-5`; observed maximum absolute difference was
`4.77e-7 nm`. The focused 33 backend and 324 frontend tests pass; repository FAST is
`7202 passed, 117 skipped`; complete frontend is `5860 passed`. The live browser used
`/trajectory-bin?stride=20`, made no JSON trajectory fallback request, reached the loaded frame
status, and observed named phase rows. FULL backend remains deferred until the user opens the
repository's test-dedicated session.

**UX for any remaining >1 s phase:** retained labelled rows show topology/DCD initialization
(indeterminate until file counts are known), frame extraction/alignment (determinate by selected
frame), packing, byte download, decode, surface-strand handling and first-frame application. Rows
remain visible together until the load terminates; the existing AbortSignal and killable worker
preserve cancellation/error behavior.

**Decision + next candidate:** the transport iteration is complete. Do not keep tuning a 0.6 ms
packer while the warm route spends ~1.76 s in MDAnalysis context/extraction. Record the 30 GB DCD
offset/setup behavior as a future same-process candidate; advance now to CanDo relaxed-shape and
metrics visualization so the audit begins covering another active tab.

#### ITER-3 — CanDo predicted shape / static visualization — 2026-08-24

**State:** verified; retained-slow-with-progress; advance to the analogous SNUPI path.

**Fixture + scale:** archived completed job `080f75d47c3d` for `6hb_validated`: 14,410
nucleotides, 7,164 FEM axis nodes and 48 thermal normal-mode frames. Its job cache contained a
`684 KB` design snapshot, `5.3 MB` display payload, `516 KB` RMSF payload and `45 MB` thermal
trajectory. This is large enough to expose both browser object-allocation and WebGL scene costs.

**Full code path read:** CanDo job-row selection and all five visualization radios/status handling
in `cando_jobs_panel.js` → mode controller and thermal/flex/deviation/cylinder transforms in
`cando_display.js` → client transport → `routes_cando.py` snapshot/display/RMSF/thermal/deviation/
cylinder/shape-source routes → `cando_runner.py` cache generation and legacy cache reads, plus
`cando_deviation.py` and `cando_cylinders.py` → `design_renderer.js` external-scene lifecycle,
FEM overlay and crossover refresh → the complete `helix_renderer.js::applyFemPositions` instance
matrix, connector, slab-frame and overhang update path. `cando_metrics_card.js` was also read to
rule out eager graph fetching: selection merely enables its collapsed controls.

**Research:** [NumPy's `tobytes()` documentation](https://numpy.org/doc/stable/reference/generated/numpy.ndarray.tobytes.html)
supports a contiguous numeric wire body instead of nested Python scalars. The official
[Three.js `InstancedMesh` documentation](https://threejs.org/docs/pages/InstancedMesh.html) says
instancing reduces draw calls, while the official
[resource-disposal guide](https://threejs.org/manual/en/how-to-dispose-of-objects.html) explains
that geometries allocate WebGL buffers and that disposal/recreation can incur a current-frame
performance penalty. Therefore the safe optimization order was: eliminate unused ensemble
frames, retain an already-instanced scene when the exact design fingerprint proves topology
identity, and column-pack the remaining representative conformation. It was not safe to reuse a
scene for an out-of-date/unknown fingerprint, nor useful to GPU-accelerate the already-cached FEM
result merely to display it.

**Benchmark/test + expectation:** the regression measures the complete real browser gesture from
the `Predicted shape` change event through final applied status, captures every named progress
mutation, and audits its requests. Direct endpoint samples separate server/cache/wire effects.
Backend packing and browser decoding have independent equivalence tests. Expected improvements
after reading the path were at least 80% less static-view wire data and at least 20% off the matched
full gesture; renderer work was expected to keep the gesture above one second, requiring retained
subprocess progress.

**Before:** every static mode downloaded/parses the entire 48-frame `44,184,003 B` ensemble even
though it displays only `representative_positions`/`representative_axis`. Direct samples were:
display `4,332,960 B` at `0.060759, 0.058992, 0.069652 s`; snapshot `8,046,798 B` at
`0.216389, 0.217884, 0.215054 s`; full thermal `44,184,003 B` at
`0.439477, 0.475391, 0.430573 s`. The exact browser gesture took `16,730 ms`, requested compressed
display/thermal/snapshot bodies of `853,092 / 20,122,567 / 1,108,748 B`, rebuilt the full scene,
and showed no subprocess indicator.

**Change (three reassessments of the same candidate):**

1. Cache and serve `thermal_representative.json`, deriving it once for legacy jobs; all modes now
   prefer it and skip the redundant display request when it already carries the predicted rows.
2. When the selected job reports `out_of_date:false`, use that fingerprint proof to retain the
   matching live instanced geometry. Unknown/stale jobs still fetch and render their own snapshot,
   preserving historical-job correctness.
3. Cache/serve versioned little-endian `CFRM` data: exact integer identity columns plus nine
   float32 visual coordinates per nucleotide and three per axis node, with one de-duplicated helix
   string table. The browser streams bytes with determinate progress, decodes the compact rows,
   and falls back to representative JSON on older/unavailable servers.

Every mode now yields so progress can paint and retains one row each for download, decode,
transform, snapshot build or exact-scene reuse, and visualization application. Flex/deviation/
cylinder-specific fetches get their own rows. A failed load retains an explicit failure row and
toast rather than silently clearing the status.

**After:** representative JSON alone was `5,063,009 B` (**88.54% smaller** than the ensemble),
with first legacy derivation `0.386679 s` and warm requests `0.062053, 0.063847 s`. `CFRM` is
`892,800 B`: **82.36% smaller than the compact endpoint and 97.98% smaller than the original
ensemble**. First derive/pack/delivery took `0.054278 s`; cached direct samples were
`0.001322, 0.000904 s`. The final matched browser gesture took `12,686 ms`, **24.2% faster** than
the `16,730 ms` baseline, meeting the stated complete-action expectation. One intermediate JSON +
snapshot pass measured `10,996 ms` and another retained-scene JSON pass `14,351 ms`, so these
headless whole-gesture numbers have real renderer/scheduling variance and should not be presented
as serialization-only precision. The final phase timeline is more diagnostic: from the first
mode phase to applied status, `4.193 s`; binary decode itself `13 ms`; transform, scene-yield and
apply each completed in the next heavily loaded headless render frame. The remaining pre-event
delay came from the large design finishing scheduled frames after job selection, not the cache
route.

**Correctness/equivalence:** all 14,410 helix/bp/copy/direction identities are exact; the observed
float32 maximum absolute error is `1.526e-5 nm`, below the `2e-5 nm` visual tolerance and WebGL's
float32 precision floor. Representative fields are exact subsets of the full cache; new jobs write
both sidecars, legacy jobs derive them; out-of-date jobs retain their snapshot route. Focused gates
pass (`3` backend and `65` frontend tests), repository FAST passes, complete frontend is
`351 files / 5,864 tests`, and the live real-fixture Playwright proof passes while observing the
binary route, no JSON/full-thermal/display/snapshot fallback, named retained phase rows, and final
thermal status. FULL backend remains deferred until the user opens a test-dedicated session.

**Decision + next candidate:** further transport work would tune a 13 ms decoder and a ~1 ms warm
route while WebGL frame/application work dominates. Keep the >1 s process visibly phased and
advance. SNUPI uses a sibling FEM UI and is the highest-value next audit: establish whether it
duplicates the old full-thermal/snapshot path or can share the proven CanDo representation without
crossing material-law/job-cache boundaries.
