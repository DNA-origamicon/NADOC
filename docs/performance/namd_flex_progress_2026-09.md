# NAMD flexibility-map progress and atomistic loading

Job: `9b1151dfca21` (`3x6SQ_norm_skips`), completed trajectory,
150 evenly sampled frames, 149,666 displayed DNA heavy atoms. Measurements on
2026-09-21 use the local job files; no simulation inputs or results were changed.

The reported process-log entry contains a completion timestamp but no duration.
Its original elapsed time cannot be recovered from that excerpt. The timings below
are reproductions, measured around the killable analysis worker, including process
startup and result deserialization, excluding browser rendering and HTTP transfer.

| Path | Seconds |
| --- | ---: |
| Original RMSF atomistic worker | 39.64 |
| Original subsequent atomistic-model request | 2.16 |
| Original combined preparation | 41.80 |
| Updated atom averaging with bundled topology | 7.75 |

The updated path uses the existing DNA-only playback context and its validated,
file/design-keyed metadata cache. It avoids rebuilding the full solvated topology
and design atom model, and returns the topology with the averaged coordinates,
avoiding the second model request. Small alignment operations use one BLAS thread.
The same 150 frames are used; comparison of every serial-indexed averaged coordinate
against the original result found **zero difference**. Unsupported synthetic/legacy
packages retain the existing full-context fallback. Cache warmth and host load
will affect timing; this is one job, not a universal timing guarantee.

The flex bar now reports named stages and completed work within each stage (for
example, averaging atoms: 30/150, 20%), with elapsed seconds. These are stage
percentages, not an estimated percentage of wall time. Setup/transfer/drawing stages
without finer instrumentation report 0/1 work units. A new stage can therefore
restart its percentage. The same bar is reused when an atomistic or surface
representation is requested while flex is active. Initial loading waits for the
requested representation, and atomistic completion is reported only after applying
coordinates and colors to the renderer.

Progress polling ends with its analysis request, failed loads report an error, and
toggling off invalidates pending work and ignores late progress. The underlying
worker remains disconnect-cancellable and bounded by a timeout.

Validation: 462 targeted frontend tests and 27 backend tests passed. The dedicated
Playwright test also passed against the real completed job: the flex bar displayed
percentages during initial analysis, reopened for atomistic mapping, and reached
ready with 149,666 atoms in VDW mode. No separate atomistic-model request occurred.
That headless browser run measured **57.20 seconds** from requesting VDW to observing
ready, including HTTP transfer, browser work, drawing, and test-observation latency.
This is distinct from the 7.75-second worker benchmark and is not a measurement of
the user's original browser session. Cancellation/late-progress cleanup is covered
by the controller, polling, and panel tests.
