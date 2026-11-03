# Benchmark record template — supporting detail

[Topic head](../../project_simulate_panel_overhaul.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Benchmark record template

```text
#### ITER-<N> — <user action / process> — <date>
State: selected | baseline | implemented | verified | retained-slow-with-progress | rejected
Fixture + scale:
Full code path read:
Research (primary sources):
Benchmark/test + environment:
Expected improvement:
Before (end-to-end + phases):
Change:
After (same measurement):
Correctness/equivalence:
UX for any remaining >1 s phase:
Decision + next candidate:
```

## Current optimization iterations

#### ITER-1 — oxDNA View trajectory — 2026-08-24

**State:** verified; advance to the next candidate.

**Fixture + scale:** the baseline hot phase used real job `1d509398c348` (VoltronCoreScad),
16,133 origami nucleotide keys plus a 13,944-particle captured surface, with one representative
frame repeated 50 times for five warm samples. Full-route validation used completed job
`2d8b40a0d507` (96 nt, 201 frames) through the running API and browser. The large fixture's
historical 200-frame flattening floor alone exceeded 1 s.

**Full code path read:** trajectory checkbox and status in `oxdna_jobs_panel.js` →
`oxdna_display.js` → API client/transport → `routes_oxdna.py` → composite-input discovery,
downsampling/alignment and frame flattening in `oxdna_health.py` → response decode → typed-frame
updates → trajectory player/scene. Existing cache, gzip, cancellation, surface-strand and growing-
trajectory behavior were included in the audit.

**Research:** NumPy documents that `ndarray.tolist()` converts array values to Python scalars;
orjson documents native contiguous NumPy serialization that avoids that expansion. The measured
bottleneck was broader than JSON encoding, so the retained method is a compact contiguous
little-endian float32 typed-array wire format, matching NADOC's existing binary visualization
routes, with small JSON metadata and the old JSON route as compatibility fallback.

**Benchmark/test + environment:** five same-process warm samples on the local workstation for
the representative pack/encode phase; three full HTTP requests per format on the running local
API; backend binary-vs-JSON equivalence and route tests; frontend parser, streaming client,
typed-frame update, player-phase, and panel tests; browser exercise through the running app.

**Expected improvement:** at least 4× smaller wire data and materially lower server/client
conversion work, while retaining scientific display equivalence and exposing all remaining load
phases.

**Before:** legacy 50-frame list expansion plus JSON encoding p50 `0.327034 s`,
`77,994,412 B` (samples `0.334360, 0.324400, 0.326680, 0.327760, 0.327034 s`). The full small
route returned `2,221,280 B`; warm samples were `0.2089, 0.1104, 0.1731 s`. Loading had one
aggregate status rather than durable per-phase progress rows.

**Change:** vectorized frame packing now produces one contiguous float32 array and a versioned
binary response. The client streams into a correctly sized/growing buffer, parses frames as
zero-copy `Float32Array` views, and avoids `JSON.parse` plus millions of boxed numbers. A response
header reports uncompressed length because a live proxy probe exposed compressed
`Content-Length`. The JSON endpoint remains the fallback. Backend and UI report `align`, `pack`,
`download`, `decode`, `surface-strands`, and `display` independently; the trajectory player keeps
one labelled progress bar per subprocess until completion.

**After:** binary pack p50 `0.256356 s`, `19,359,600 B` (samples
`0.257640, 0.257320, 0.256350, 0.256360, 0.254450 s`): **1.276× faster CPU phase and 75.18%
smaller** (4.03×). The full small route returned `466,188 B` (79.01% smaller) and warm samples
`0.10313, 0.10285, 0.10295 s`, about **1.67× faster** by median. Browser validation loaded all
201 frames through `/trajectory-bin`, enabled controls, and scrubbed to frame 50 without invoking
the JSON fallback.

**Correctness/equivalence:** real generated trajectory data matches the JSON representation at
`rtol=1e-6`, `atol=2e-5`, appropriate to display-only float32 positions/directions. Tests cover
the full file→align→pack→wire path, malformed/truncated payloads, zero-copy frame views, streamed
progress, compressed-length mismatch, JSON fallback, and progress phase retention. Focused tests,
the complete 5,857-test frontend suite, and the repository FAST suite pass. The FULL backend suite
remains deferred by repository policy until a user-opened test session exists.

**UX for any remaining >1 s phase:** the large 200-frame load can still exceed 1 s depending on
disk, alignment, network and GPU upload, so each named subprocess now has its own status/progress
row. The last valid scene remains visible during loading; failure/cancellation use the existing
terminal status path.

**Decision + next candidate:** the expectation was met; further packing work has diminishing
returns relative to alignment and rendering. Advance to NAMD Display-MD/trajectory loading. A live
probe also observed an unrelated 500 from one background `/api/md/jobs/.../trajectory-meta`
request, so establish whether stale-job metadata lookup is part of that path before benchmarking.

#### ITER-2 — NAMD View trajectory — 2026-08-24

**State:** verified; retained-slow-with-progress; advance to another simulation tab.

**Fixture + scale:** archived real job `c8bcf4c1406f` (`2hb_1xT`), ten physical DCD
segments and 300 raw frames sampled to 200 composite frames, 96 nucleotides. A scaling probe also
used archived job `4c0ba3a85587`, a 30 GB DCD with 40,000 raw frames.

**Full code path read:** NAMD trajectory radio, interval pricing and polling in
`md_jobs_panel.js` → shared `oxdna_display.js` controller through `md_viz_adapter.js` → client
JSON transport → `routes_md.py` job/archive resolution, segment discovery and killable analysis
subprocess → `md_analysis_runner.py` → PSF/DCD context construction, composite indices,
per-frame PBC/Kabsch/base-normal extraction and Python-list flattening in `md_trajectory.py` →
browser JSON parse, FEM updates and trajectory player. The separate WebSocket-backed live
**Display MD** path was read to distinguish it from this scrub-trajectory action; it was not
changed in this iteration.

**Research:** MDAnalysis' official DCD documentation confirms indexed/sliced reads and that DCD
is the NAMD trajectory format, while its user guide confirms that trajectory iteration advances
the Universe frame. NumPy's official array documentation confirms that `tolist()` creates nested
Python scalar lists whereas `tobytes()` emits raw C-order array bytes. Because NADOC's scientific
per-frame extraction is already array-vectorized, the suitable improvement was to retain its
float32 arrays through transport rather than parallelizing DCD reads and risking I/O contention,
stateful-Universe races, and extra per-process PSF construction.

**Benchmark/test + environment:** three matched HTTP samples per format against the running local
API, plus five same-process samples of the full synthetic 200-frame selection/extract/flatten/
encode shape (100 P keys + four termini). A CI-safe regression drives selection, extraction,
packing and wire decode; a live Playwright test opens the real design/job and records requests and
progress mutations.

**Expected improvement:** at least 4× smaller wire data and at least 5× faster Python
flatten/serialization, with lower browser allocation. Total route time was expected to improve
only where encoding/transfer was material because PSF/DCD setup and scientific extraction remain.

**Before:** real JSON payload `2,205,832 B`; samples `3.492021, 1.760410, 1.761027 s`
(warm p50 about `1.761 s`). The controlled conversion path was p50 `0.008931 s` over samples
`0.009023, 0.009029, 0.008931, 0.008540, 0.008692 s`, `1,356,482 B`. The UI exposed only one
frame counter and did not name topology initialization, transport, decode, or first-frame work.
The 30 GB scaling probe remained inside MDAnalysis DCD discovery/setup beyond 180 s and was
cancelled rather than allowed to monopolize the workstation; it establishes a separate dominant
large-file candidate without being used as a completed timing sample.

**Change:** added the shared versioned `NTRJ` float32 response for NAMD, filled one preallocated
NumPy matrix with slice assignments, and streamed/decoded it as zero-copy typed frame views using
the ITER-1 browser parser. JSON remains a fallback. Progress now distinguishes `initialize`,
`extract`, `pack`, `download`, `decode`, `surface-strands`, and `display`. A FastAPI route-schema
registration failure caught during the first reload was fixed by disabling response-model
inference for the mixed binary/not-ready endpoint and pinned through app-import/route tests.

**After:** real binary payload `465,472 B` (**78.90% smaller; 4.74×**); samples
`1.771016, 1.755785, 1.757162 s` (p50 `1.757 s`). Warm total time is essentially unchanged
(about 0.2% faster), proving the remaining `~1.76 s` is extraction/context dominated rather than
encoding dominated at this small 96-nt size. The controlled conversion p50 is `0.000605 s`
(samples `0.000661, 0.000658, 0.000604, 0.000605, 0.000605 s`), **14.8× faster**, with a
`500,644 B` payload versus `1,356,482 B` for deliberately simple synthetic values. The expected
wire and conversion improvements were exceeded; expecting a large total-route win on this fixture
would have been incorrect.
