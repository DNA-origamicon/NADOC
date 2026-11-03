# Historical timing and suite implementation notes — historical evidence

[Topic head](../../project_test_parallelization.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

- **Budget policy reworked 2026-07-14 (the 60s ceiling was ratcheting).** The old rule — hard-fail
  any fast run over 60 s — measured three things at once: test weight (a defect), suite SIZE (only
  ever grows), and CPU contention from the user actually *using* NADOC on the same box (not a defect
  either). So every healthy new test eventually pushed 59 s → 61 s and mandated a triage that bought
  the seconds back by relegating something innocent; the churn cost more time than the guard saved
  (user, 2026-07-14). Now: **the per-test 5 s rule is the mandatory gate** (scale-free — a 5 s test is
  heavy at any suite size, and it's what actually catches real offenders), and **total wall-clock is a
  90 s backstop only** (`NADOC_TEST_BUDGET_SEC`), firing only when the suite got fat in aggregate with
  no single culprit. 60–90 s prints a note and requires nothing (`NADOC_TEST_SOFT_BUDGET_SEC`). Pytest
  also now runs under **`nice -n 10`** (`NADOC_TEST_NICE=0` opts out) so `-n auto` doesn't make the app
  stutter while the user is working in it — which alone kept the 62 s run that triggered this change
  under the soft mark.
- **`scripts/select_tests.py` never escalates outside a session.** A FULL/AREAS verdict is
  **downgraded to FAST and the owed groups are parked in `.nadoc-slow-pending`**, accumulating
  across sessions/commits until the user opens a window and runs `just test-slow` (or `just test`,
  which also clears it + bumps the watermark). Outside a session `just test-smart` runs the fast suite only; relevant slow
  checks use `just test-focused TARGET` separately. Reporting
  "DEFERRED slow[cando]" IS a complete verification for a normal change — not a gap to close.
- **Budget watchdog in conftest** (`pytest_runtest_logreport` + `pytest_sessionfinish`, aggregated
  on the xdist controller): times every test, flags any **unmarked** test over 5s
  (`NADOC_PER_TEST_BUDGET_SEC`), writes `.nadoc-slow-candidates.json` (violators + slowest_25 +
  **slowest_files_15** — per-FILE totals matter because `--dist loadfile` makes the slowest single
  file a hard wall-clock floor). That file is the input to **`.claude/skills/triage-slow-tests`**,
  the triage workflow when a broad fast-sweep violator appears. Never raise the budget;
  diagnose fixture size/cache/contention before classifying it as slow.
  The guard reads `violators` out of that JSON — a non-empty list is what triggers triage now,
  ahead of (and independent of) the 90 s total-time backstop.
- **BOTH budgets are SUPPRESSED while a production sim is running (2026-07-28).** A NAMD job at
  `+p16` on a 16-core box drives load average to ~16, and pytest is the side that yields because
  the guard nices it to +10 — so a healthy 2 s test measures 6 s and trips the 5 s per-test gate.
  Triaging on those numbers relegates innocent tests *permanently*, which is the exact ratchet the
  scale-free per-test gate was designed to avoid. conftest now records `sim_running` / `sim_reason`
  in `.nadoc-slow-candidates.json` (from the `_sim_guard()` cache primed in `pytest_configure`, i.e.
  the clean startup window — a test-spawned sim can't flip it), and `test_guard.sh` swaps the triage
  banner for `BUDGET CHECK SUPPRESSED: <reason> … no triage owed`. Violators are still recorded, just
  not treated as debt. A report with `sim_running` **absent** (written before this) reads as idle, so
  the gate can never be silently lost. Pins: `tests/test_test_guard_budget.py` (6 — they run the real
  shell script in a tmp cwd with `NADOC_TEST_LOCK`/`NADOC_TEST_SESSION_FILE` redirected, so they never
  touch the repo's lock; proven to fail against the pre-change guard).
  This complements the older rule that `slow`-marked tests *skip themselves* during a sim — that one
  never covered the fast suite's timings.
- **⚠️ A "violator" that MOVES between runs is a shared cache warming, not a heavy test.**
  Learned the hard way 2026-07-28: the junction topology/winding tests were relegated on readings of
  41 s / 28.8 s / 11.4 s, then un-relegated the same day when a serial idle-machine measurement put the
  slowest at **2.32 s** (both files together ~10 s). Two compounding artifacts:
  `atomistic_minimisers._XB_CACHE` is a **module-level in-memory** cache, so under `-n auto` every xdist
  worker starts cold and whichever test lands first pays the whole one-time minimisation — and the
  sweep also ran under a +p16 NAMD job. The tell was the violator naming a **different test each run**.
  **Diagnostic before relegating anything: re-run the file alone, serially
  (`uv run pytest <file> -m "" --durations=0 -p no:randomly`), on an idle box.** A first-test-pays-the-
  cache cost is not test weight, and relegating for it is precisely the ratchet the scale-free per-test
  gate exists to avoid.
- **🔥 BLAS OVERSUBSCRIPTION was the dominant fake-slowness source — FIXED 2026-07-30.** numpy/scipy
  here are built against **scipy-openblas with `MAX_THREADS=64`**, so every `L-BFGS-B` / `lstsq` /
  `eigh` fanned out across the whole box. Under `-n auto` each xdist worker had its **own** pool →
  a 12-core box oversubscribed ~10x. The fast suite's numeric work is *tiny* (the atomistic
  extra-base joint solve is **29 DOF**), so the thread pool was pure overhead — single-threaded is
  faster even for a **serial** run. `scripts/test_guard.sh` step 4 now exports
  `OMP/OPENBLAS/MKL/NUMEXPR/VECLIB_*_NUM_THREADS=1` for **fast-only (`slow=0`) recipes**;
  `NADOC_TEST_BLAS_THREADS=N` overrides, `=0` leaves the env untouched. Scoped to `slow=0` because
  the heavy suite's large SNUPI/FEM solves may genuinely want threads (unmeasured).
  Whole-suite effect: **total test-seconds 532.8 → 261.3, guard wall-clock 130 s → 59 s,
  per-test violators 8 → 2**, `test_junction_topology.py` 91.9 s → 23.6 s,
  `test_junction_winding.py` 20.6 s → off the top-15, and `test_{pdb_export,namd_extensions,
  threemf_export,snupi_hydro_coarse,fem_solver}.py` all dropped out of the slowest-15.
  **Numerically neutral** — `tests/test_atomistic_geometry_lock.py` yields byte-identical geometry
  hashes at 1 thread and at N (checked explicitly, since that file hash-pins float output).
  **⚠️ That says thread COUNT only — kernel DISPATCH is not neutral.** Same commit, same lockfile,
  same box: AVX-512 OpenBLAS kernels vs `OPENBLAS_CORETYPE=Haswell` move the L-BFGS-B-placed
  crossover/skip bridge atoms by up to 1.3 Å, every other atom bit-identical. That is why four of
  that file's five goldens were machine-specific and ping-ponged across five commits. Fixed
  2026-07-31 by splitting the oracle (byte-exact hash of stamped atoms + tolerance on
  solver-placed bridges); before regenerating any golden there, rule out `OPENBLAS_CORETYPE`
  first. See [[LESSONS]] H19.
  Residual 2 violators (`test_repair_does_not_degrade_geometry[TT]` 5.75 s,
  `test_repaired_build_is_deterministic[TT]` 5.16 s) are **4.14 s / 3.91 s measured alone** — under
  budget in isolation, over it only under suite contention → left unmarked, per the rule above.
  **Diagnostic upgrade: before relegating anything, check CPU time vs wall time.** A serial pytest
  run showing `user 4m14s` for `real 25s` is ~10x hidden threading, i.e. thrash, not weight.

**First run of the guard immediately caught a 3-minute lie:** the "fast" suite was documented as
~50s but was actually **176s**. The whole SNUPI FEM family was unregistered — `test_snupi_element`
(127s), `test_snupi_dynamics` (85s), `test_snupi_corotational` (47s) → `_SLOW_MODULES`, plus
`test_linear_snupi_job_completes_and_caches` → `_SLOW_TESTS`; `_slow_area_for` now routes
`snupi` → **cando** (it previously fell through to the `md` fallback), and `select_tests.LEAF_RULES`
gained `("snupi", ("cando",))` so SNUPI source selects the cando heavy group. Two `test_oxdna_relaxation`
loop/PBC invariant guards were **shrunk instead of relegated** (388bp → 168bp routed 18hb; assertions
unchanged; 7.6s+5.3s → 0.67s+1.33s). Result: **176s → 54s pytest / 57s guard-measured, 4744 passed,
38 skipped, 70 deselected.** Total test-seconds 871 → 366.

**Headroom is thin (~3s).** The floor is now two broad files pinned by `loadfile`:
`test_oxdna_relaxation.py` (34.1s / 217 tests) and `test_headless_oxdna_build.py` (33.5s / 44).
Next levers if it creeps: (a) session-scoped cached routed-18hb fixture (deep-copied per test —
several mutate `helices[].loop_skips`) shared by ~6 call sites incl. `test_cluster_autodetect_core`
(3.7s isolated, not O(n²) — the 14s reading was CPU contention); (b) split `test_oxdna_relaxation.py`
so `loadfile` can spread it.

**Backstop triage 2026-07-22 — `FAST SUITE TOO SLOW` (93–95s) was mostly CPU CONTENTION, not fat.**
Zero per-test violators; 5393 tests. Re-measured on an idle box: **76.8s pytest / 81s guard** — under
the 90s backstop. Lessons for the next time this banner fires:
- **THE TWO COMPUTERS DIFFER — say which one a timing came from.** The numbers in this section were
  measured on the **Ryzen 5 3600** box (6 cores / 12 threads, no AVX-512). The other box is a
  **Ryzen 9 9950X** (16 cores / 32 threads, AVX-512, OpenBLAS dispatching `SkylakeX`), where both
  the timings AND float results differ — a hash-pinned float golden generated on one is red on the
  other ([[LESSONS]] H19). Re-measure rather than trusting a figure below.
- **The Ryzen 5 box is 6 physical cores / 12 threads, so `-n auto` = 12 workers oversubscribes
  SMT and inflates every per-test reading 2–6×.** `test_fem_solver` / `test_snupi_hydro_coarse` tests that
  the report showed at 2–3.1s are **0.3–0.7s in isolation**; `test_headless_oxdna_build` is 22.7s isolated
  vs 32.7s in-suite. **Never relegate off the in-suite number alone — re-time the file in isolation first.**
  Measured: `-n 8` is a wash (76.3s), so worker count is not a lever.
- **~9–15s of the wall is collection** (5742 items, 8.7s per worker, all 12 doing it at once) plus 6-core
  execution of ~336 in-suite test-seconds. That floor is suite SIZE — not a defect, not triage-able.
- **Fixed (accidental, no coverage moved):** `test_engines_ws.py` still paid the full app lifespan per test
  (trap #3 below) in 4 tests → module-scoped `lifespan_client` fixture. **7.6s → 3.6s**, file left the top-15.
- **Nothing was relegated** (correct for the aggregate case — the mandatory gate is per-test). The one file
  that is heavy *by mechanism* is `test_headless_oxdna_build.py` (45 tests × a mock-oxDNA subprocess ×3 stages,
  22.7s isolated, top `loadfile` bin): ignoring it is worth **~7s of wall**. That is the standing lever if the
  backstop ever fires on a genuinely idle box — `_SLOW_MODULES` + area `oxdna` — but it costs 45 fast oxDNA
  orchestration tests, so it was left fast.

**Setup (shipped 2026-06-28):**
- `just test` / `just test-all` use `pytest -n auto --dist loadfile` → ~2.5-3 min *when the heavy sims are skipped/guarded*; **real wall-clock with the full slow sim/FEM tail is ~16 min** (`--dist loadfile` pins the slowest heavy FILE to one core — see the scoping protocol below). A green run bumps the machine-local `.nadoc-test-watermark`. This is the PRE-PUSH gate, not the per-change loop.
- `just test-fast` adds `-m "not slow"` → **~50s** after the 2026-07-10 registry re-refresh (4453 passed, 38 skipped, 12 cores). It had crept back to ~117s as ~50 new heavy sim/FEM/routing tests landed unregistered (one 75 s `test_cando_autorefine` FEM loop alone pinned a worker); the 2026-07-10 pass folded them all in. Use for the tight dev loop; run full `just test` before pushing.
- `just test-affected FILE... [-k pat] [--lf]` (added 2026-07-05) = scoped inner loop, drops slow tests. Point it at the area you're editing; sub-second.
- `--dist loadfile` is REQUIRED (not default `--dist load`): tests share a module-level `TestClient(app)` over global per-doc backend state, so a file's tests must stay in-process and in-order on one worker. **This also sets the wall-clock floor: the single slowest FILE runs entirely on one core** — so heavy tests clustered in few files (cando_autorefine, fem_solver, cando_job, namd_topology) can't spread. Keeping them `slow` is what keeps test-fast fast.
- `pytest-xdist` is in dev deps + uv.lock.

**Overload guard — `scripts/test_guard.sh` wraps every pytest recipe (added 2026-07-13).** *(PARTLY
SUPERSEDED the same day by THE LAW above: the confirm gate is now OFF for `test-fast`/`test-smart`
— they are fast-only and free to run — and ON, plus a session requirement, for `test`/`test-slow`/
`test-all`. The lock below is unchanged.)* repeated/overlapping `just test*` invocations (each `-n auto` across all cores, plus GPU for sim/FEM) saturate the machine. The guard gives every backend pytest recipe two protections: (1) an **exclusive mkdir lock** (`.nadoc-test.lock/`, gitignored, holds pid+label+start) — a second guarded run REFUSES with the running run's pid while one is alive; a dead-owner lock is auto-reclaimed. (2) a **"is this really necessary?" gate** on the full-suite variants (`test`, `test-fast`, `test-smart`, `test-all` → guard arg `gate=1`): interactive callers answer y/N; **non-interactive callers (agents/CI) must set `NADOC_TEST_CONFIRM=1`** or the run refuses and points at tighter loops. Tight loops (`test-affected`, `test-file` → `gate=0`) are **lock-only, no confirm** (they're the recommended lighter alternative). Escape hatch `NADOC_TEST_FORCE=1` bypasses both (stale-lock last resort). **Consequence for the mandated per-change loop:** `just test-smart` now needs `NADOC_TEST_CONFIRM=1 just test-smart` when run by an agent. Recipe wiring: `scripts/test_guard.sh "<label>" <gate> -- <cmd...>` in the justfile.

**Slow-test registry lives in `tests/conftest.py`** (`pytest_collection_modifyitems` hook, `_SLOW_MODULES` + `_SLOW_TESTS`), NOT scattered `@pytest.mark.slow` decorators. Two heavy classes now: (1) real oxDNA/oxpy/GROMACS/protein-fork binaries + MD-trajectory parses (MDAnalysis); (2) **pure-Python CanDo-FEM eigensolves + autorefine density sweeps** (the G1/G3/G4 shape-objective work — test_cando_autorefine/_job/_cylinders/_deviation, test_fem_solver, test_fem_curvature_validation, test_namd_topology, test_oxdna_relaxation, whole module test_md_pipeline). Class (2) was UNREGISTERED until 2026-07-05, silently ballooning test-fast to 3 min. A THIRD bucket was added 2026-07-10: **`_SLOW_CLASSES`** (bare class names) for heavy tests that share an expensive **class-scoped fixture** — marking individual methods is useless there because the fixture just re-fires on a surviving sibling (e.g. `TestSyntheticRoundTrip`/`TestRoutedPrimitiveIntegration` in test_mrdna_pipeline, ~26–32 s each), and it also cleanly covers a class whose methods have generic collision-prone names (`TestMinimize3ExtraBase`'s `test_cache_path`). **To refresh after adding heavy tests:** `just test-fast --durations=25`, fold new ≥~2s "call"/**"setup"** entries into the sets (setup-dominated files → `_SLOW_MODULES`; class-scoped-fixture-dominated classes → `_SLOW_CLASSES`; a heavy test in an otherwise-fast file → `_SLOW_TESTS`). **Non-sim slow-ish tests (assembly/cluster/geometry/browse, ~2–4 s) are deliberately LEFT fast** to keep those subsystems' quick feedback — they don't set the wall-clock floor.

**Two registry upgrades, 2026-07-30.**
- **`_SLOW_PARAMS` — relegate ONE parametrisation, not the whole test.** Matched against
  `item.name` (which carries the param id) rather than `originalname`. Added because
  `test_junction_topology`'s catenation-repair pair was 5.2–5.4 s on `[TT]` (2-insert: two cold
  atomistic builds × the L-BFGS-B repair ladder) but ~1.3 s on `[T]` — and the only options used to
  be "relegate both params or neither", so an earlier session chose neither and left the guard
  demanding triage on every run. Now `[TT]` is heavy (area `atomistic`) and `[T]` stays fast,
  guarding the same two invariants on the 1-insert path.
