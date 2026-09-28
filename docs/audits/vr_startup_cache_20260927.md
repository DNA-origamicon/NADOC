# Visualization tour startup cache

The reported slow launch was reproduced in the user's last visualization run:
`.development-artifacts/vr-debug-tours/20260927-195016-046979dc/evidence/` recorded
26.30 s exporting a 697,442,501-byte scene, then 10.52 s launching the native viewer.
Every new process exported again, even when the document had not changed.

Implemented a persistent, content-addressed export cache in
`tools/vr_workflows/snapshot_cache.py`, used by the existing Visualization demo and
validation entries. Geometry production and native loading are unchanged.

Keys include full document bytes, backend API/core/template data, the workflow
exporter/cache code, and uv.lock. Hits check file length and full SHA-256. A process
lock prevents duplicate concurrent builds; interrupted exports cannot publish a
usable entry. Cache retention is capped at two entries and 2 GiB, evicting least
recently used entries. Hard links preserve immutable run snapshots through cache
eviction without copying hundreds of MB. Retained evidence has a separate lifetime.
The cache survives viewer/backend resets; changed documents or code rebuild.
`--no-cache` explicitly bypasses reading and populating it for cold benchmarks.

## Paired measurement

Both runs use the same read-only document captured by the user's previous launch,
SHA-256 `c58e0031de49c6f02890867a2e6bb70af8b7eafb8ae2b847eca1391fcefc727f`.
Runs execute sequentially, with no simultaneous regression runners.

| Phase | Cold cache miss | Warm cache hit |
| --- | ---: | ---: |
| Snapshot preparation | 32.54 s | 0.317 s |
| Native launch to live ready | 10.15 s | 10.59 s |
| Total preparation to live ready | 42.93 s | 11.09 s |

This paired run improved startup by **74.2%**. Absolute cold timing differs from the
prior run; these are wall-clock samples, not a hardware-independent guarantee.
A new/edited design still pays the full export cost. Remaining native parsing and
GPU preparation (~10.6 s) are not optimized by this change. Native logs attribute
6.14 s to parsing/validating 4.41 million scene records and ~0.82 s to preparing
the four initial representation styles. Timing begins before
snapshot preparation, excluding Python interpreter/import and browser transport.

Evidence under `.development-artifacts/vr-representations/`:

- `startup-cache-cold/`: 12 directed transitions and desktop mirror check passed.
- `startup-cache-warm/`: all 48 directed switches across four controller profiles
  passed, with at least 162,158 visible design pixels per eye and a minimum 15 px
  gap from the right menu. Desktop pixel check passed (matching fraction 1.0).
  Submitted stereo captures and controller traces retained. Cold and warm snapshot
  paths share an inode. The owned viewer closed cleanly.
- `startup-cache-tests-final.log`: five tests passed; covers reuse, unsaved edits,
  exporter changes, corruption, interrupted builds, byte/entry limits, concurrent
  launches and explicit bypass. No real simulation or headset in unit tests.
- `startup-smart.log`: FAST selection, 9,296 passed / 92 skipped, pre-existing
  `test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree` failure.
  A mocked headless oxDNA orchestration test exceeded its per-test budget (8.25 s);
  isolated triage found a 0.15 s call / 0.68 s setup, with no real simulation/GPU
  (the fixture installs a mock binary and disables native DNAnalysis). This does
  not establish an inherently heavy test, so no slow reclassification was made.
  The final fast-suite rerun limits xdist to two workers to reduce contention;
  test guards and budgets remain unchanged.
- `startup-smart-final.log`: FAST, 9,296 passed / 92 skipped, same existing geometry
  failure. Zero individual tests exceeded the budget. Limiting execution to two
  workers increased total wall time to 95 s, above the 90 s aggregate backstop.
  Under the triage skill, reduced concurrency is not grounds for relabeling fast
  tests; no thresholds were raised and no third broad sweep was run.
- Ruff and whitespace checks passed. No remaining viewer/test processes or partial
  cache exports. Cache currently contains one 697,442,501-byte snapshot.

Broad-suite deferral from test-smart:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

No source design is written. Cache and evidence live in the existing ignored
artifact tree. Stereo captures establish application-submitted output, not physical
through-lens headset comfort. This cache currently applies to the isolated Debug
Visualization tours, not the normal live-editing VR launch route.
