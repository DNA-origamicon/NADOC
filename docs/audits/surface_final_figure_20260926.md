# Permanent remeshed Figure quality, measured progress, and lossless speedups

## Requested behavior

- Default display probe: **0.06 nm**, including native and simulation display defaults.
- Default surface opacity: **1.0**, in store, renderer, and controls.
- Figure quality now includes continuous-field extraction and bounded local remeshing.
  The temporary checkbox was removed. `chimerax` and `remeshed` select the same
  permanent mode; `continuous` remains an internal unremeshed comparison.
- Shared world grid 0.05 nm, physical Gaussian sigma 0.0425 nm, four Taubin passes,
  and maximum local remesh displacement 0.01 nm are unchanged. No atom coordinates,
  strand topology, saved designs, geometry locks, or visual goldens were changed.

The probe change affects the surface shape as requested. Performance comparisons
below hold probe and all quality parameters fixed, so they isolate the optimization.

## Progress contract

The centered “Computing surface…” popup is owned by the surface transport. It
sends a random request ID and polls `/api/surface-progress/{id}` every 250 ms,
without overlapping polls. The original document headers remain frozen across tab
changes. The pure ASGI middleware binds a ContextVar reporter; Starlette copies it
into sync worker threads. The async polling route can respond while those workers
compute. A bounded, locked registry stores only status/counters and expires finished
records after ten minutes; active long computations do not expire mid-stage.

The bar counts **completed work in the current stage**, not elapsed time or a guessed
percentage of total runtime. Tile extraction and Taubin passes report real counters.
Labels include the current strand and strand count. Preparation, welding, identity
assignment, sharp-edge detection, remeshing, and packing remain indeterminate when
there is no measurable denominator. Remesh pass labels explicitly say “up to 8”,
because convergence can stop early. Stage changes can reset the bar; the caption
states that these are stage-local work units. There is no invented ETA.

Each popup has an ownership token. Older request updates cannot overwrite a newer
operation; finishing an old request cannot hide another popup. Restored operations
retain their labels, fractions, and cancellation controls. Success, failure, and
abort clean up polling. Native binary and JSON fallback plus simulation binary/JSON
surface requests use the same transport wrapper. The popup covers computation and
payload receipt; browser mesh upload/rendering is outside its counters.

## Lossless optimizations

1. Tiled welding uses stable numeric lexicographic sorting instead of NumPy's
   structured-row `unique`. Unique-key ordering, first occurrence, and remapping
   are identical, including duplicate boundary vertices.
2. Local remeshing reuses one stable sorted edge ordering for unique edges, inverse
   indices, and adjacent-face ownership, eliminating a redundant second sort.
3. Native binary packing retains numeric arrays instead of creating millions of
   Python floats/ints and then converting them back. Palette lookup is vectorized;
   identity tables preserve first-appearance ordering with compact integer arrays.
   JSON callers retain their previous JSON-safe representation.

Read-only `workspace/mini_rect.nadoc`, probe 0.06 nm, CUDA initialized, one warmup
per mode followed by three alternating warm comparisons:

| Generation + packing | Median |
|---|---:|
| Previous algorithms / list packing | 12.002 s |
| Optimized algorithms / array packing | 9.927 s |

**17.3% lower total time.** Packing alone fell from approximately 1.394 s to 0.367 s.
HTTP compression, transfer, browser parsing/upload, and rendering are excluded.
No other benchmark or broad test suite ran during the measured samples.

Every comparison produced identical complete binary bytes, including mesh, colors,
and strand/nucleotide identity. SHA-256:
`31054ffb8843d9db1616db73a5ac272ec9f0a2b849a10bb4575f339a6c1c2fe6`.
The payload contains 1,469,329 vertices and 2,939,950 faces (69,107,287 bytes).
No resolution, triangle count, smoothing pass, or remesh quality reduction was used.

At the newly requested smaller probe, the diagnostic reports 4,887 >60° edges
(0.02935% of measured edge length), maximum turn 121.4°, and zero boundary,
nonmanifold, or degenerate edges/faces. These counts differ from the previous
0.10 nm setting because probe radius changes the narrow-contact geometry; they
are identical before/after the speed optimizations. Counts are tessellation-sensitive
and do not equal the number of visible spikes or establish physical surface validity.

Reproduce: `uv run python -m scripts.benchmark_surface_final_figure`.
Full measurements: `.development-artifacts/surface-final-figure/benchmark.json`.
The reference functions in that script preserve the prior sorting algorithms;
byte equality is asserted on every run.

## Verification

- Initial surface-focused run: 30 passed. Final focused run after trajectory defaults
  and edge-sort changes: 20 passed. Coverage includes independent edge ownership,
  tile/dense parity, byte-identical array packing, mode/default routing, live worker
  progress, document isolation, duplicate IDs, failure state, and expiry.
- Frontend: 544 files / 7,080 tests passed, one skipped. Final controller/progress
  checks after fallback and popup restoration changes: 52 passed.
- Lint and diff whitespace checks passed. `main.js` LOC delta: 0.
- `just test-smart`: **FAST**, 9,285 passed, 15 skipped, eight previously recorded
  photoproduct-review/CPD-preview failures. Pytest 100.97 s; guard wall time 106 s
  exceeded the aggregate 90 s backstop. The required `triage-slow-tests` skill was
  followed: no individual violators, broad 1–4 s tests, no newly identified shared
  accidental slowness. No tests were arbitrarily reclassified and no guard changed.
  Aggregate timing remains an unresolved broad-suite issue.

Selector debt, verbatim:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

Playwright pre-run inventory: fixture session, revision store, workspace/scratch
prefixes, report directories, and isolated viewer credentials were absent. The
six-helix fixture uses `__e2e__surface-continuous`; exact afterEach cleanup covers
its session/revision/scratch paths, global teardown covers prefixed workspace files
and credentials, and the cleanup reporter removes Playwright reports. Intentional
figure/progress evidence is retained alongside the benchmark outside the workspace.

Final app verification: 23 smoke/assembly checks passed. The focused Figure quality
check then passed in 33.7 s after correcting the test to observe the popup before
awaiting the entire surface operation. The popup was visibly present during work,
actual backend 1/2-tile snapshots matched 50% UI updates, and it cleared only after
payload receipt. Opacity 1.0, probe 0.06, removal of the temporary toggle, a nonblank
colored render, and no page/shader errors were verified. The saved figure screenshot
was inspected. `progress.json` retains paired server counters and UI events.
Post-run checks confirmed all inventoried fixture, session, revision, report, and
isolated credential paths were absent, including after the initial test failure.
