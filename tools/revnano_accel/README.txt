Bounded-memory REVNANO adapter
=============================

Purpose
-------
Run the locally pinned REVNANO1.1 source more efficiently. Default settings preserve
its scientific heuristics; optional reconstruction experiments are documented below. This is a separate command-line research tool, not a
change to NADOC's design model or UI. Upstream solver: Ben Shirt-Ediss,2020–2023;
https://revnano.readthedocs.io/en/latest/ (MIT). The hook patch modifies only the
Stage0 Pass2 execution mechanism; the main solver implementation remains upstream.

Setup (already performed in this workspace)
-------------------------------------------
Sibling checkouts:
 .development-artifacts/revnano-gerling2018/REVNANO
 .development-artifacts/revnano-gerling2018/contactmap
Pinned commits:
 REVNANO:36a72c13670004a23bc7aad0db44c2ab36c1b207
 contactmap:8bd39737d2341f1d47dba8456fc1ce8f9bb86150
Apply stage0_hook.patch to a clean REVNANO checkout of that commit. Use the
existing Python environment with networkx/scipy; no GPU dependency.

Run from NADOC repository root
-----------------------------
.venv/bin/python tools/revnano_accel/run.py \
  analysis/gerling2018_revnano_20261027/42hb13_raw.rev \
  --output analysis/gerling2018_revnano_20261027/new_parallel_run \
  --workers 4 --budget-mib 4096 --parent-mib 1024 --worker-mib 512

Use a new output directory each run. Inputs are never edited. No wall-clock
termination limit is imposed by this adapter. Ctrl-C interrupts the run.
summary.json records parameters, timings, per-process peaks, task failures,
scientific errors, exact tree digests and contact-map hash if a map was produced.
A successful reconstruction also emits contactmap.json and native contactmap.csv.
Exit0 means the requested stages completed without solver error; inspect the
placed-staple count because partial maps are a supported upstream outcome.
Exit2 means an upstream scientific failure; exit3 means an execution failure.
Argument/import/startup errors also exit nonzero. No memory failure is silently
converted into an omitted/unroutable staple.

Execution and memory controls
-----------------------------
* Stage0 Pass1 remains sequential: its footprint updates affect later staples.
* Sequence-only scaffold scans use an LRU cache capped at32MiB per process.
  Cache accounting conservatively counts Python key/value sizes. Zero disables
  retention. Other solver state is outside this cache budget.
* Stage0 Pass2 uses a frozen Pass1 footprint snapshot and a spawned process pool.
  At most one task per worker is submitted per batch. Results are committed in
  original staple order, preserving deterministic behavior. The existing
 10000-subtree limit and MU_MIN retry rules remain unchanged.
* Each worker writes its completed tree directly to disk; IPC returns only
  metadata. Subsequent stages use a mutable disk-backed mapping caching one tree.
  Mutations are persisted before eviction. In-progress trees are not streamed
  node-by-node; each active search must fit within its worker allowance.
* Later constraint propagation remains sequential. There is no assumption that
  those order-dependent operations can safely be parallelized.
* Linux RLIMIT_AS imposes an address-space ceiling on the controller and each
  worker. This includes libraries, Python and tree allocations, not just RSS.
  Workers are clamped by requested count, CPU count and remaining memory budget.
  Defaults allow four512MiB workers plus a1024MiB controller (3072MiB summed
  ceilings under the4096MiB configured budget). The multiprocessing resource
  tracker and OS filesystem cache are not included in this sum.
* BLAS/OpenMP thread counts are set to1 to prevent nested thread multiplication.
* Temporary tree files are cleaned on normal completion/error. They are not a
  resume checkpoint. Outputs and summary remain. Disk capacity is not capped;
  a disk-full error aborts rather than discarding results.
* Reported sum_process_peak_rss_mib_upper_bound sums each process's peak; it is
  NOT a measurement of simultaneous total RSS. Wall time in solver_seconds
  excludes initial imports and input parsing, consistently across modes.

Validation modes
----------------
--mode original : unchanged upstream execution, no cache or parallel hook.
--mode cached   : same sequential solver with only the bounded scan cache.
--mode parallel : cache, parallel Pass2 and disk-backed subsequent tree access.
--stage0-only   : diagnostic tree construction; no full contact map.
--limit-staples N : diagnostic prefix only, unavailable with loopout inputs.

Validation scripts and results:
 analysis/gerling2018_revnano_20261027/performance/
 compare.py checks exact stage outcomes, no-tree IDs, every tree digest and
 final contact-map hashes across all three modes on four fixtures.
 run_full.py compares cached serial and parallel on both complete raw42hb lists.
 tools/revnano_accel/test_engine.py checks mutation persistence on eviction,
 exact linear/circular cached matching, cache byte bounds and fail-closed memory
 exhaustion. The adapter is deliberately tied to one upstream revision.

Scientific limitation
---------------------
Speed and memory management do not identify which Ts are unpaired. Correct
REVNANO input still requires *...* annotations around tails and loopouts.
A solver result can also be a sequence-compatible but geometrically wrong route.

Optional reconstruction experiments (2026-10-27)
-----------------------------------------------
--mu-min {5,6}, --sigma 0..10 and --beta (0,1] expose upstream settings; defaults
remain6/4/0.3. MU_MIN5 is documented upstream for wireframes; it is an exploratory
setting for these42hb raster designs, not a validated geometry model.

--ordered-pruning enables a narrowly scoped correction to upstream Stage2.
Upstream's shortest-route pruning uses segment membership rather than segment
order, so two permutations of the same segments can both survive and cause an
endless force-placement loop. The hook keeps only the selected ordered route.
A real42hb14 failure reproduced directly on a saved tree, independently of the
parallel/disk adapter. Both default whole-map controls retain identical hashes;
synthetic order/permutation and unchanged-behavior regression tests pass.
The upstream checkout is not edited. Enabling this hook is recorded in summary.

--seven-route-bonus {0,1,3,7} is a separate EXPERIMENTAL scientific preference.
Default0 retains upstream shortest-path distances. Positive values subtract the
bonus per7 paired bases belonging to domains whose length is a multiple of7.
For example14 and7+7 receive equal preference. This only ranks existing Stage2
routes; it does not create routes, revise T annotations, or guarantee geometry.
Use with --ordered-pruning for these experiments. Report use of the route prior
when interpreting results; it is not an upstream REVNANO default.

Every new run saves adapter_source/ for reproducibility, the parameter values,
ordered-pruning counters and fragment_diagnostics.json. The latter distinguishes
virtual fragments from complete physical staples; do not count fragments as fully
resolved published staples. Ctrl-C now records execution_error=KeyboardInterrupt
and exit_status130 before propagating interruption.

Full annotation search, copied experimental adapter versions, regression evidence,
per-trial logs and comparisons: analysis/gerling2018_revnano_variations_20261027/.
