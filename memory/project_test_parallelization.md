---
name: project_test_parallelization
description: Backend test suite runs in parallel (pytest-xdist); slow-test registry + global-state isolation gotcha
metadata: 
  node_type: memory
  type: project
  originSessionId: 2557a198-2648-4182-8f9b-1f6ff948cb26
---

The backend suite (3410 tests) was ~6 min serial; now runs parallel via pytest-xdist.

## THE LAW (2026-07-13) — slow tests are locked behind a test-dedicated session

Claude kept escalating to the full suite (~16 min) after changes that only *distantly* touched
simulations, and that was killing dev velocity. So heavy (`slow`) tests **no longer run at all in
an ordinary coding session**. Three new pieces, all machine-local + gitignored:

- **`scripts/test_session.sh` + `just test-session`** — the USER opens a 4h window in THEIR OWN
  terminal; it writes `.nadoc-test-session` (expiry epoch). **TTY-only by design**: an agent can
  fake an env var, it cannot fake a human. `just test-session status|off`; `just test-status`
  shows the window + what's owed.
- **`scripts/test_guard.sh` grew a 3rd arg** → `<label> <gate> <slow>`. `slow=1` recipes
  (`test`, `test-slow`, `test-all`) **REFUSE to start** unless the session window is open.
  `slow=0` recipes (`test-smart`, `test-fast`, `test-affected`, `test-file`) are fast-only, need
  no confirm any more (the gate was pure friction once they couldn't run sims), and are subject to
  a **60s wall-clock BUDGET** (`NADOC_TEST_BUDGET_SEC`). Over budget → loud banner demanding a
  triage subagent. Budget is skipped inside a session (test-smart legitimately drains heavy groups there).
- **`scripts/select_tests.py` never escalates outside a session.** A FULL/AREAS verdict is
  **downgraded to FAST and the owed groups are parked in `.nadoc-slow-pending`**, accumulating
  across sessions/commits until the user opens a window and runs `just test-slow` (or `just test`,
  which also clears it + bumps the watermark). So `just test-smart` is *always* <60s. Reporting
  "DEFERRED slow[cando]" IS a complete verification for a normal change — not a gap to close.
- **Budget watchdog in conftest** (`pytest_runtest_logreport` + `pytest_sessionfinish`, aggregated
  on the xdist controller): times every test, flags any **unmarked** test over 5s
  (`NADOC_PER_TEST_BUDGET_SEC`), writes `.nadoc-slow-candidates.json` (violators + slowest_25 +
  **slowest_files_15** — per-FILE totals matter because `--dist loadfile` makes the slowest single
  file a hard wall-clock floor). That file is the input to **`.claude/skills/triage-slow-tests`**,
  the mandated subagent when the budget blows. Never raise the budget; relegate the offender.

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

**Test-scoping protocol — decide which slow tests are actually relevant BEFORE running (added 2026-07-10).**
*(Largely MOOT under THE LAW: an agent can no longer run the slow tail at all, so the judgement calls below
now only apply inside a user-opened test-dedicated session.)*
The full `just test` is ~16 min *by design* (real oxDNA/GROMACS/ARBD binaries + CanDo-FEM eigensolves, and `--dist loadfile` pins the slowest heavy FILE to one core → it sits at "98%" for minutes while one core grinds the last file). Do NOT reflexively run it as a diagnostic loop. First ask: **can my change affect any `slow` test at all?** A slow test is relevant only if the change touches (a) `backend/` source in that test's `area` (oxdna/cando/namd/mrdna/atomistic/md/headless), or (b) a fixture/helper that a slow test *consumes*.
- **Test-only / conftest / fixture changes** (no `backend/` source touched): the changed tests + fixtures are what to verify. If they are themselves non-slow and no slow test imports them, `just test-fast` (`-m "not slow"`, ~45s) + `just test-affected <the touched files>` is COMPLETE coverage — a full run adds nothing but 15 min. (Grep to confirm: `grep -rl <new_helper> tests/` → if only non-slow files, you're done.)
- **`test-smart` escalates any `tests/conftest.py` edit to FULL** (foundational/unknown-blast-radius rule). That is blast-radius caution, NOT a relevance signal — a conftest change whose new/edited code is only consumed by fast tests does not need the slow tail. Override the escalation manually with `-m "not slow or <area>"` (or just `test-fast` + the affected files) once you've confirmed by grep which tests consume the change.
- **The one real reason to run the slow tail for an autouse/global fixture change:** an autouse fixture executes for slow tests too, so it *could* break one. But that risk is retired by a SINGLE green full run; don't re-run the tail for a follow-up change that touches no slow test. (Worked example: the 2026-07-10 workspace-isolation fixture + chain-completion fixture rebuild — both fast; one full run confirmed the autouse fixture left slow tests untouched, after which `test-fast` + `test_chain_completion_e2e.py` was sufficient.)
Reserve full `just test` for the pre-push gate on a `backend/` source change, or the first run that introduces a global/autouse fixture. Everything else: scope it.

**Change-based selection — `just test-smart` is the DEFAULT per-change loop (added 2026-07-05, the safe testmon substitute; watermark added 2026-07-10):**
`scripts/select_tests.py` classifies changed source → runs the fast suite (always) PLUS only the heavy `slow` groups affected — **but since 2026-07-13 it only RUNS those groups inside a test-dedicated session; outside one it defers them to `.nadoc-slow-pending` (see THE LAW).** Foundational/shared/unknown change → FULL; a leaf change (oxdna/cando/namd/mrdna/atomistic/md/headless) → `-m "not slow or <area>"`; frontend/docs-only → FAST (no backend tests — run `just test-frontend` for JS). Safe because the fast suite always runs — a mis-map can only skip a heavy SIM test whose fast cousins still ran, never basic coverage. Slow tests carry a `slow` + one `area` marker (assigned in conftest `_slow_area_for`; areas registered in pyproject `markers`). Full-trigger list + leaf rules live in the script; `--dry-run` shows the decision. Route files (`backend/api/routes_*.py` except main/ws/state) → FULL by default (unknown blast radius; tune leaf rules if too coarse).

**Watermark — what "changed" means, and why full runs got rare (added 2026-07-10):** `just test-smart` now defaults to `--since-last-full`: it diffs against `.nadoc-test-watermark` (a gitignored, machine-local file holding the git SHA at which the FULL suite last passed *here*), not just uncommitted changes. This fixes the gap where committing your work hid it from the scope — affected slow-areas now **accumulate across sessions/commits** until a full run clears them. A green full run (`just test` / `just test-all`, or a `test-smart` run that itself escalated to FULL) bumps the watermark to HEAD. No watermark yet (fresh clone / fresh worktree) → forced FULL, which establishes the baseline. Net effect: a fresh session touching only frontend runs `just test-frontend` and **zero** backend tests; the ~16min full run happens only before a push or on a foundational change. **Guidance:** CLAUDE.md Verification/Done-checklist + the skill Gates now name `just test-smart` (cite its decision) as the per-change command; full `just test` is the pre-push gate. Note: uncommitted-only scope is still available via `just test-smart --base HEAD` or the raw `python scripts/select_tests.py` (no `--since-last-full`); `--base origin/master` overrides the watermark.

**Resource guard — skip heavy tests while a real sim runs (added 2026-07-05):** a live production NAMD/oxDNA/mrDNA job on the machine starves the test suite → heavy tests time out (flaky). `backend/core/hardware.heavy_sim_running()` detects one via `pgrep -l 'namd|oxDNA|arbd|gmx'` (process names — avoids the NoMachine `nxnode.bin` GPU false-positive) + a high (85%) GPU-util backstop for oxpy-in-python; FAIL-OPEN on any probe error. conftest `pytest_configure` primes the check ONCE per worker at startup (clean window, before any test spawns its own oxDNA subprocess → no self-reference), caches it; `pytest_runtest_setup` skips `slow`-marked tests when a sim is live. Fast suite (`not slow`) is never affected. Override: `NADOC_IGNORE_SIM_GUARD=1`. Pure parsers (`parse_pgrep_l`, `parse_gpu_utilization`, `assess_heavy_sim`) unit-tested in test_benchmark.py.

**WSL host-probe trap — never let a test call `engines_status()` or `fs_browse` unstubbed (found 2026-07-13, budget triage):** the fast suite blew the 60 s budget with **zero** per-test violators (nothing over 5 s) — pure broad drift, and both causes were *accidental* slowness that got **fixed, not relegated** (no coverage moved, `slow` registry untouched):
1. **`engines_status()` costs 3–5.5 s per call on WSL.** It fires ~39 `shutil.which` calls — and WSL appends the whole **Windows** PATH, so each one stats dozens of `/mnt/c` drvfs paths (~950 `stat` syscalls) — plus six subprocess spawns (`nvidia-smi` ×2, a real `mpicxx -E` C++ preprocess, `lmp -h`). `test_engines_ws.py` paid it 3× (~4.8 s/test). Fix: a `stub_host_probes` fixture pinning the finders + `shutil.which` + `_gpu_arch`/`_mpi_build_usable`/`lammps_supports_cgdna`, i.e. the same trick `test_engines.py::_patch_all` already used — the real `engines_status()` still runs, so every assertion survives (and FORCE_MISSING now has to override a *found* binary, which is strictly stronger).
2. **`fs_browse.default_downloads_dir()` resolves to the real `/mnt/c/Users/<you>/Downloads`** (2000+ entries) and `list_dir` scandir+stats all of it over drvfs → 2–4 s. Fix: `monkeypatch` the default to a `tmp_path` in the two tests that hit it; the real resolver keeps its own cheap (glob-only) test.
3. **`with TestClient(app)` runs the whole app lifespan** (~0.45 s: workspace scan, session-cache restore, MD-supervisor task). Function-scoped, it multiplies by test count (`test_routes_runpod.py`: 12 × 0.45 s). Make the client **module-scoped** and keep isolation in a separate function-scoped teardown — the fresh app was never what isolated them.
Net: total test-seconds 403 → 324; those three files left the top-15 entirely. **Also beware when timing the suite: a concurrent `just test-smart` from another session (or a leaked multiprocessing worker) inflates the wall by 20–40 % — check `uptime` / the `.nadoc-test.lock` before trusting a budget number.**

**KNOWN FLAKY (open, found 2026-07-13) — `test_snupi_element.py::test_g12_salt_ignored_by_cando`:** failed once
in a full `just test-smart` run (1 failed / 4719 passed), then **passed in isolation** (`uv run pytest
tests/test_snupi_element.py::test_g12_salt_ignored_by_cando` → 1 passed in 90s). Found during the 2026-07-13
docs-cleanup audit, in a run where **zero non-doc files had changed** — so it is NOT caused by a code change;
it is a pre-existing cross-test isolation flake, same family as the two entries below. Not yet root-caused
(the likely shape, by precedent: another test leaking global/module state that the CanDo-vs-SNUPI salt
comparison reads). If it bites a real run, start by looking for a polluter that mutates SNUPI/CanDo material
or salt globals, exactly as the `_routes_md` leak below was found.

**~~KNOWN FLAKY~~ FIXED 2026-07-10 — `test_md_executor.py::test_remote_recommendation_unknown_{partition_400,profile_404}`:** used to fail intermittently under `-n auto`/`16`/`4` (green at `-n 8`, green in isolation). It WAS the same leak as the polluter below (`test_md_milestone1.py::TestProductionAppend::_routes_md` leaking a stubbed `backend.api.routes_md`); fixing the polluter fixed this too. Two full `-m "not slow"` runs at `-n auto` post-fix: 4455 passed, 0 failures. No change was needed in test_md_executor itself.

**~~KNOWN POLLUTER~~ FIXED 2026-07-10 — `test_md_milestone1.py::TestProductionAppend::_routes_md`:** the helper stubs `fastapi` in `sys.modules` and re-imports `backend.api.routes_md` under that stub so its tests can exercise routes_md's pure helpers without real FastAPI. It leaked the stub-bound module into the next file on the `loadfile` worker → `TypeError: 'function' object is not iterable` in `include_router` (stub `_Router` bound as `md_router`) or `StopIteration` on `/md/jobs` (stub's `_workspace` served, job missing). **The fix (helper now):** snapshot `dict(sys.modules)` after a real baseline import, do the stubbed import inside a `try`, and in `finally` (a) delete any keys imported under the stub, (b) `sys.modules.update(snapshot)`, AND — the part every earlier attempt missed — **(c) re-point the parent-package submodule ATTRIBUTES** (`backend.api.routes_md`, `backend.api.assembly`) back at the real modules. **Why (c) was the missing piece:** `import backend.api.routes_md` rebinds the submodule as an *attribute* on the `backend.api` package object, and the victim's `from backend.api import routes_md` reads that attribute, NOT `sys.modules` — so restoring `sys.modules` alone (what `monkeypatch.setitem`/`delitem` and the "write real back into sys.modules" idea all did) still handed the victim the stub. Independent of monkeypatch undo ordering, so no mid-teardown abort. **Verified:** `pytest test_md_milestone1.py test_job_archive.py -n0` → 84 passed (was 4 errors + 1 fail); TestProductionAppend's own 72 still green; two full `-m "not slow" -n auto` runs → 0 failures. Its sibling victims (`test_md_executor` above, `test_cando_extra_bases` in the slow-inclusive balance) are the same leak and are fixed by this.

**pytest-testmon (change-based impact analysis) is BLOCKED:** latest 2.2.0 declares `pytest<10` but is in fact broken against our pytest 9.0.2 — collects 0 items under the repo config, `KeyError: 'lf'` with cacheprovider disabled. No newer release exists. Would need pinning the project to pytest 8.x (major downgrade). NOTE: `uv remove pytest-testmon` re-syncs and PRUNES the out-of-band editable installs (oxpy, mrdna, zstandard) that aren't in pyproject — reinstall with `uv pip install -e /home/jojo/{oxDNA/build_oxpy_cuda/python,mrdna-tool}` + `uv pip install zstandard`, then re-check oxpy `BaseForce.F0/.dir`.

**Workspace isolation (autouse, added 2026-07-10):** `tests/conftest.py` has an autouse `_isolate_workspace` fixture that redirects `backend.api.assembly._WORKSPACE_DIR` (the single source of truth every inline-part save path reads *dynamically*) to a per-test temp dir. Fixes tests silently dropping `Bundle_N.nadoc` into the real `workspace/`: the culprits were `test_assembly_api.py::test_{extrude,patch}_instance_overhang_writes_feature_log_on_both_levels` — they add an INLINE part (design name defaults to "Bundle") then hit the overhang endpoint → `_replace_instance_design` auto-saves `<name>_N.nadoc` with no cleanup. Also covers `/assembly/save`, `/design/save-workspace`, loadout routes (same attr via the `_asm` alias / imported `_replace_instance_design`). Safe as a global autouse (unlike an active-design reset — see below): no test READS committed workspace files through this attr (only the 2 self-cleaning writers `test_periodic_polymer`/`test_seek_no_cluster` reference it, and they write+read their own file); tests wanting their own workspace `monkeypatch.setattr(assembly,"_WORKSPACE_DIR",...)` again and win (function scope runs after autouse). Job-runner routes (routes_md/oxdna/cando/…) bind their OWN `_WORKSPACE_DIR` copy and already self-isolate — this fixture doesn't touch them. Culprit found empirically via a throwaway workspace-diffing pytest plugin, not static grep (the static scan missed them — they write through the overhang endpoint, not `PATCH /design`).

**Isolation gotcha (parallelism exposed a latent bug):** the oxDNA `/run` endpoint's `_assert_job_current` guard compares a job's snapshot fingerprint to the *global active design* (`_current_design_fingerprint()` → `state.get_or_404()`). Tests that don't set the active design pass only when the global store is empty (current_fp→None→guard skipped). Reordering under xdist lets another test's leftover design fire a spurious 409. Fixed in `test_oxdna_surface.py::_run_client` by monkeypatching `routes_oxdna._current_design_fingerprint` → `None` (those tests exercise run COMPOSITION, not staleness — which has its own tests). **NOT a production bug.** When adding new oxDNA/MD tests that hit job-run/staleness endpoints under parallelism, set the active design explicitly or neutralize the guard. Do NOT add a global autouse active-design reset — 68 files share a module-level client and build state across tests within a file.

See [[LESSONS]] (stale-state category).
