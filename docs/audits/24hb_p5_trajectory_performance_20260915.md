# P5 trajectory loading performance — 2026-09-15

## Outcome

The interrupted Alpine P5 job `594917c0d119` (`24hb_0xT`) reaches actual ball-and-stick playback in **3.167 s**, with an already active atomistic representation and every 20th frame selected. Initial buffering completes in **2.912 s**. This is a real browser measurement on the workstation GPU, after advisory eviction of the relevant trajectory, PSF, and PDB pages immediately before loading. The test backend starts with an empty derived topology cache.

Playback uses exact frames progressively. It does not require all selected coordinates to be resident before enabling Play. The complete run contains 6,032 frames, so the browser test exposes 302 selected frames. A separate accuracy and disk benchmark uses precisely the requested 5,000-frame window: 250 selected frames, raw indices 0 through 4,980.

Across those 250 frames, the optimized extraction has **zero numerical difference** from the existing measured-coordinate extraction, for both 137,493 heavy atoms and 6,720 Full bases. Atom identities and all 154,202 bonds, including their order, match. Binary atom transport preserves float64 coordinates. No additional frame decimation, coordinate quantization, interpolation, or regenerated molecular geometry is used.

## Research and design

Large trajectory applications avoid materializing every frame at startup. [VMD BigDCD](https://www.ks.uiuc.edu/Research/vmd/script_library/scripts/bigdcd/) processes individual frames and discards them in background analysis. [OVITO's file source](https://www.ovito.org/manual/reference/pipelines/data_sources/external_file.html) loads the current frame on demand; loading an entire trajectory into memory is optional. [MDAnalysis trajectory slicing](https://userguide.mdanalysis.org/1.1.1/trajectories/slicing_trajectories.html) iterates selected frames, and its [DCD reader](https://docs.mdanalysis.org/stable/documentation_pages/coordinates/DCD.html) supports indexed access. NADOC now applies these principles to interactive playback: indexed reads, bounded buffering, and asynchronous prefetch.

The main changes are:

- Read only the DNA coordinate prefix at exact selected DCD offsets; count complete frames from the file layout, including an interrupted run with stale header counts or an incomplete final frame.
- Build playback topology directly from validated PSF identities and the design mapping. Avoid repeated solvent topology construction, atomistic model minimization, and the redundant 102 MB PDB scan. Unsupported mappings retain the original extraction fallback.
- Cache static topology using source-file identities and the complete design. Private atomic disk caches and per-key locks prevent concurrent duplicate builds. Frame alignment state stays request-local.
- Reuse up to three cancellable worker processes, with idle expiry, and overlap the next selected disk read with current-frame alignment.
- Transfer static atom topology in columnar binary form and heavy-atom coordinates as dense float64 blocks with an exact sparse serial map. Disable gzip only for the atom-coordinate stream: it cost 0.944 s per 16-frame block to save only 6.1% of its 53.35 MB payload.
- Fetch initial topology and atom coordinates concurrently with the first Full page. Buffer eight frames initially, then sixteen per page; retain at most three stream pages. Slider metadata covers the full selected range immediately. Playback and arbitrary seeks wait for the exact selected frame, displaying “buffering…” when necessary.
- Avoid fetching invisible solvent/graphene companions when package metadata establishes their absence.

These changes fix general loading paths; an interrupted P5 simulation is not the underlying cause of the previous startup delay. The earlier position/color fixes remain in effect; see [representation audit](24hb_p5_representation_20260915.md).

## Measurements and limits

Hardware: Ryzen 9 9950X, approximately 30 GiB RAM, NVIDIA RTX 3080 Ti; archive drive `/dev/sdb`, Seagate ST8000DM004-2U9188 rotational HDD, ext4. Browser WebGL reports ANGLE on the NVIDIA GPU. Headless SwiftShader is unsuitable for assessing this workstation's atomistic rendering speed; the benchmark uses headed Chromium.

The P5 DCD is 95,559,957,652 bytes and contains 1,320,174 atoms per frame. For 250 selected frames, reading the needed 213,444-atom prefix requires 640,332,000 coordinate bytes spread across 750 axis records. Solvent coordinates are not read for this DNA playback path.

| Measurement | Seconds |
|---|---:|
| Earlier instrumented legacy context setup | 22.639 |
| Browser selected-to-buffered, final cold advisory trial | 2.912 |
| Browser selected-to-first actual playback advance, same trial | 3.167 |
| 250 frames, cold raw prefix reads, initial trial | 10.748 |
| 250 frames, cold reads plus atom alignment with read-ahead | 10.701 |
| Reproducible CLI: cold raw reads, independent trial | 10.930 |
| Reproducible CLI: cold reads plus atom alignment | 10.675 |
| Reproducible CLI: cold reads plus measured Full bases | 10.856 |
| 250 frames, warm raw reads | 0.076 |
| 250 frames, warm aligned atoms | 3.035 |
| 250 frames, warm measured Full bases | 3.845 |

Cold here means targeted Linux `POSIX_FADV_DONTNEED`, an advisory eviction rather than a guarantee that all drive/controller caches are empty. Each CLI cold operation is preceded by eviction of its selected coordinate pages. No system-wide cache flush is used. The small apparent advantage of processing over raw reads is normal run-to-run disk variation, not a claim that computation accelerates disk hardware.

The selected-frame extraction is now limited by the measured HDD service time: read plus alignment is effectively the same speed as raw reads. Loading all 250 exact frames into memory within five seconds is not possible at the observed cold random-read rate. Progressive loading meets the user's selected-to-playable target without that prerequisite. This is an empirical limit for this access pattern and drive, not a proof of a universal theoretical hardware maximum.

Cold-disk stalls can still occur during playback. The preceding trial advanced past 64 selected frames in 12.842 s after the first advance, including two slow pages taking roughly 4.2–4.7 s each. The final trial completed that interval in 8.040 s; other trials took 8.3–11.3 s. Buffering preserves the exact sequence rather than dropping frames to maintain a nominal rate. Faster sustained cold playback would require different storage/access locality or a prepared trajectory cache; these startup improvements do not conceal that limitation.

## Reproduction

Read-only extraction benchmark (largest DCD in the selected job; optional `--design` selects an explicit reference):

```sh
uv run python scripts/benchmark_md_playback.py --job 594917c0d119 --frames 5000 --stride 20 --cold
```

Actual application benchmark from `frontend/`, on the workstation display:

```sh
DISPLAY=:1 NADOC_E2E_COLD_TRAJECTORY=1 npx playwright test e2e/namd_trajectory_performance.spec.js --headed --workers=1
```

The browser timer starts when trajectory loading is selected, after the existing native ball-and-stick representation is rendered and stride is set. It stops after Play causes the first frame advance. It includes metadata, topology, coordinate transfer, decoding, and trajectory display preparation. Initial application launch and initial native design construction are excluded because the task specifies an already active atomistic representation.

The browser test also plays across several buffer boundaries, seeks to selected frame 249, switches to Full, and checks for page errors. A separate representation test checks 137,493 atom colors and 6,720 base positions after switching; no incorrect colors, maximum GPU-rendered slab/atom ring centroid discrepancy 0.00000450 nm.

Playwright uses isolated servers on ports 8002/5175. Session persistence is disabled. Its only derived workspace cache is `workspace/playwright_tests/__e2e__md-playback`, removed by global teardown even on failure. The cleanup reporter removes screenshots, traces, and report directories. Neither test saves or modifies the simulation or design.

## Verification

The frontend suite passes **6,493 tests in 445 files**. Backend `just test-smart` selected **FAST**: **8,536 passed, 110 skipped, 27 failed, 9 errors** (the same pre-existing failure set). Machine-readable results are in the accompanying JSON. Existing failures concern native oxDNA build freshness and missing assembly/aptamer fixtures; they do not occur in the changed MD tests. Focused playback, binary transport, cancellation, composite indexing, and interrupted-DCD checks pass. The full frontend suite and real application checks pass.

The test guard reported:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

No slow-suite gate was bypassed. The user-authorized P5 performance and accuracy measurements are separate job-specific diagnostics.


## Follow-up: retain the entire selected trajectory for scrubbing

The initial three-page retention policy has been replaced by automatic background filling and
retention of the full selection, subject to a 1.5 GiB coordinate budget. Initial playback still
starts after the first eight exact frames. Scrub requests take priority over the next background
page; only one background page is queued at a time. The panel shows the buffered frame count,
then **fully buffered**. Oversized selections retain a bounded exact cache and show **memory
limit**, rather than silently reducing frame resolution.

The atom cache now retains dense float64 coordinates and their original sparse serial map.
Only the displayed frame is expanded, using a reusable scratch buffer. This removes unused
serial slots without changing precision, topology, or atom positions. P5's 302 selected frames
require approximately 1.1 GB of coordinates including Full-base data (plus metadata and scene
memory), versus about 1.64 GB with expanded sparse atom arrays. Closing the trajectory releases
the stream, cached atom frames, and display scratch array, including when the view was suspended.

An additional real-GPU, immediately advisory-cold browser run measured:

| Operation | Time |
|---|---:|
| Initial buffer ready | 2.876 s |
| First actual playback advance | 3.130 s |
| Entire 302-frame selection buffered, from loading selection | 32.088 s |
| Six distant seeks after full buffering, including rendering | 128, 132, 115, 117, 117, 135 ms |

Those six seeks issued **zero additional coordinate requests**. They visited selected indices
0, 301, 149, 2, 249, and 0. Full/ball-and-stick switching still passed. Disk loading and UI
rendering are separate: full buffering eliminates I/O waits, but drawing a 137,493-atom frame
still takes finite time. The app remains usable during background filling.

Tests cover full retention, exact sparse expansion with scratch reuse, priority seeks,
memory-limited fallback, cancellation/stale data, and release after suspension. The frontend
suite passes 6,496 tests; `just smoke` passes all 23 app checks. Test artifacts were removed
and cleanup verified. No backend behavior changed in this follow-up. `just lint` reports
three pre-existing issues in untouched files (`routes_oxdna.py`, `test_oxdna_peg.py`, and
`test_streptavidin.py`); lint delta is zero. `main.js` LOC Δ: **0**.
