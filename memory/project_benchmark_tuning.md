# Simulation hardware benchmark (oxDNA + NAMD auto-tuning)

Shipped 2026-06-18. "⏱ Benchmark this machine" button in **both** Dynamics-panel
subsections (oxDNA + Molecular Dynamics). Auto-discovers the fastest hardware config
for the current machine and stores it in the design, keyed by hostname.

## What it does
1. Build a **synthetic** 6hb proxy sized ≈ the open design's nucleotide count
   (NOT the real design — avoids solvating a huge real structure). Size-driven only,
   so even an empty design yields a small valid proxy.
2. Run a short trial on each candidate config **sequentially** (GPU contention),
   measure throughput, keep the fastest.
   - oxDNA grid: CPU + one CUDA trial per device. Metric `steps_per_s`.
   - NAMD grid: thread ladder {n//4, n//2, n} × {each GPU, CPU-only}. Metric `ns_per_day`.
3. Store winner in `Design.metadata.hardware_defaults[hostname]` (typed Pydantic,
   round-trips). Apply also saves the `.nadoc` if a workspace path is known, and
   pre-fills the panel inputs (oxDNA Backend/CUDA-device · NAMD Threads/CUDA-device).

## UX (2026-06-19 follow-up)
- Each engine's benchmark is its **own collapsible card** (chevron header, collapsed by
  default) rendered by the module into `#oxdna-benchmark-mount` / `#md-benchmark-mount`.
- While a sweep runs: a **spinner** on the button, a **loading bar + ETA** (ETA =
  mean completed-trial time × trials left, from `state.eta_seconds`/`fraction`), and a
  **Cancel** button. **All other controls in BOTH Dynamics panels are disabled**
  (`_lockPanels` saves+restores prior `disabled` state; Cancel stays clickable) — a
  concurrent job would corrupt timing.
- **Live "Log output & engine calls" pane** (2026-06-30): a native `<details>` inside the
  card body shows the actual engine command lines + a live tail of each trial's log file
  as the sweep runs (so a hung vs working run is visible). Backend: `BenchmarkState.log_blocks`
  (one per launched process — pre-relax/minimize + each trial) with `start_block`/`finish_block`;
  the running block's file is live-tailed by `to_dict()` (`_tail_text`, last 6 KB), finished
  blocks snapshot their tail BEFORE the temp dir is `rmtree`d. Surfaced via the existing poll
  as `to_dict()["commands"]` + `["log"]`. Frontend `runSweep` `_showLog` pins-to-bottom unless
  the user scrolled up.
- **Cancel** → `POST /benchmark/{id}/cancel` → `cancel_benchmark` cancels the asyncio
  task; the runner's CancelledError path kills the in-flight subprocess + `rmtree`s the
  temp dir; state → `cancelled`; existing defaults untouched (Apply never ran).
- **Dummy-proof single-config guard**: backend never builds CUDA configs without a GPU
  (`enumerate_cuda_devices` → []). If the relevant grid has ≤1 entry (no GPU → oxDNA
  CPU-only, or single-core CPU), the frontend `window.confirm`s "nothing to compare,
  won't improve settings — run anyway?" before starting.
- **Concurrency guard**: `is_any_running()` → start routes return 409 if one is live.
- Cancel race fix: `_RunningHandle.ready` Event; `cancel_benchmark` waits ≤1s for the
  worker's task to be assigned (so the cancel route is **sync/threadpooled**, not async).

## Decisions (locked with user)
- Synthetic matched-size workload · medium sweep grid · per-machine storage by hostname.

## Files
- `backend/core/hardware.py` — `parse_nvidia_smi_l` (pure), `enumerate_cuda_devices`,
  `cpu_thread_ladder`, `hostname`.
- `backend/core/benchmark.py` — PURE: `oxdna_config_grid`/`namd_config_grid`,
  `synthetic_bundle_plan` (+ caps `OXDNA_MAX_NT=50k`, `NAMD_MAX_NT=4k`),
  `pick_best_oxdna`/`pick_best_namd` (tie-break GPU>CPU, fewer threads),
  `extrapolate_note` (no-silent-caps), `SIX_HB_CELLS`.
- `backend/core/benchmark_runner.py` — sequential async orchestration + in-memory
  `_BENCH` registry; `build_synthetic_design` (build_bundle + `_sequence_synthetic`
  cyclic ACGT so neither engine 400s on undefined bases); `run_oxdna_trials`
  (reuses `render_stage_input` + `_run_oxdna_async`); `run_namd_trials` (solvate once,
  minimize once, `_run_namd_bench` local launcher); try/finally `shutil.rmtree`.
- `backend/api/routes_benchmark.py` — `GET /benchmark/hardware`, `POST /benchmark/{oxdna,namd}`,
  `GET /benchmark/{id}`, `POST /benchmark/{id}/apply`. Mounted in `main.py`.
- `backend/core/models.py` — `OxdnaHardwareDefault`/`NamdHardwareDefault`/`HardwareBenchmark`
  + `DesignMetadata.hardware_defaults: Dict[str, HardwareBenchmark]`.
- `frontend/src/ui/benchmark_panel.js` — `initBenchmarkPanel({api, getWorkspacePath})` →
  `{mountOxdna, mountNamd}`; main.js gains only import + init + 2 mount lines.
- `frontend/src/api/client.js` — `benchmarkHardware/startOxdnaBenchmark/startNamdBenchmark/
  getBenchmark/applyBenchmark`.

## Gotchas baked in (don't regress)
- **oxDNA MC is CPU-only** → benchmark uses a single short **MD** stage.
- **Backbone force caps required** (`max_backbone_force=5.0/10.0`): a raw bundle's ideal
  geometry has over-long backbone bonds at helix junctions that stock FENE rejects at
  init — without the caps the trial exits rc=1 ("Distance between bonded neighbors
  exceeds acceptable values"). Same caps the real MD-relax stage uses.
- **oxDNA input path must be absolute** — oxDNA runs with `cwd=stage_dir`; a repo-relative
  path won't resolve. topology/conf referenced as `../name` (relative to stage_dir).
- **NAMD CPU-only** (`devices=""`): `_run_namd_bench` omits `+devices` (shared
  `_run_namd_async` always appends it → empty arg confuses NAMD).
- **Solvate ONCE** per NAMD sweep (GROMACS, 60-120s); per-config solvation would be
  minutes×configs.
- **Size cap is honest**: `proxy_nucleotides` stored + extrapolation note surfaced.

## Tests
- `tests/test_benchmark.py` (26): parse, ladder, grids, plan+cap, pick-best tie-breaks,
  metadata round-trip, synthetic-no-undefined-bases, mocked-runner sequential+cleanup,
  routes (hardware/apply→metadata/409/404), log-block live-tail-then-snapshot + oxDNA
  command/log capture.
- `frontend/src/ui/benchmark_panel.test.js` (6): mount, oxDNA sweep poll→apply-fills-inputs,
  log-pane reveal + live output, failed sweep, NAMD apply, null-start.

## Headless access (AF-17, 2026-06-19)

Feature automation can now run a benchmark + relax on its result without the panel:
- `backend/api/headless_oxdna_build.py` → `run_oxdna_benchmark(design, ws, *, configs=, runner=, steps=)`
  (drives the REAL `benchmark_runner.run_oxdna_trials` sweep inline → `result["recommendation"]`),
  `apply_oxdna_benchmark(design, rec)` (writes into a COPY's `metadata.hardware_defaults[host]`),
  `run_relaxation_tuned(design, ws, **params)` (resolves the stored default → backend/device → `run_relaxation`).
- `backend/core/benchmark.py` → `resolve_oxdna_relax_config(HardwareBenchmark | None) → {backend, device}` (pure,
  CPU/"0" fallback). Oracle `assert_relax_honors_hardware_default` (tests/automation_harness.py).
- This is the bridge AF-13 P4's iterate-until-met loop uses so each relaxation runs on the fastest discovered
  backend instead of a hard-coded CPU. See `design_automation_log.md` AF-17 row. NAMD headless tuning still TODO.

## NAMD path never ran end-to-end → two FATALs (FIXED 2026-06-30)
The NAMD sweep was only ever unit-mocked; the first real-binary run failed entirely. Root causes,
both in `_write_namd_bench_confs`:
1. **stepsPerCycle**: `minimize 200` / `run 2000` aren't multiples of `stepspercycle` → NAMD FATALs at
   the TCL `minimize`/`run` command. Fix: `NAMD_MIN_STEPS` / `NAMD_BENCH_STEPS` are exact multiples,
   plus `_round_to_cycle()` guards any caller `steps`.
   ⚠️ `stepspercycle` is **20** as of 2026-07-12 (was 12) and is duplicated in TWO places that must be
   kept in sync: `md_protocols.AKSIMENTIEV_STEPS_PER_CYCLE` (which `_common_header` writes) and
   `benchmark_runner.NAMD_STEPS_PER_CYCLE`. Change one → change both, and re-check every hardcoded
   step count near it. See [[project_water_shell_carve]].
2. **`reinitvels` → misleading `langevinTemp` FATAL**: a restart conf (`binCoordinates`) with BOTH
   `temperature` and `reinitvels` makes NAMD 3.0.2 abort with "'langevinTemp' is a required
   configuration option" even though it's present. Bisected: `temperature`-only restart runs clean
   (rc=0); `reinitvels` is the trigger and is redundant (`temperature` already assigns fresh Boltzmann
   velocities). Fix: dropped the `reinitvels` line from `bench.conf`.
Also: the minimize's return code was IGNORED → a failed minimize cascaded into N confusing per-trial
"missing bench_min.coor" errors. Now fails fast with the real minimize exit code.
Regression guard: `test_namd_benchmark_completes_end_to_end_on_a_6hb` (`@pytest.mark.slow`, skips if no
NAMD) builds a 6hb from scratch, presses the real route + polls, asserts `completed` + ns/day > 0.

## NAMD benchmark aligned to production fast-mode (2026-06-30)
The plain bench conf (2 fs, no HMR, `GPUresident off`) under-reported throughput ~3-5x vs a real
run — a user's 3x6x200 read 5.8 ns/day while production fast-mode gives ~16. The timed `bench.conf`
now mirrors production fast mode: **HMR PSF (`{stem}_hmr.psf` via `write_hmr_psf`) + 4 fs +
`GPUresident on`**. Gotchas found + fixed:
- **GPUresident crashes on the raw proxy** ("Low global CUDA exclusion count") — the synthetic bundle
  has ~+1e6 kcal/mol VDW clashes and a 204-step minimize doesn't clear them. Fix: the one-time settle
  is now `minimize 2004` + a short soft `run 1200` (rigidBonds none) → VDW ≈ −4.8e6, fast mode stable.
  Trials still measure only the fast-mode `run` restarting from that settled conf. Constants:
  `NAMD_MIN_STEPS=2004`, `NAMD_SETTLE_MD_STEPS=1200`.
- **Parser missed NAMD 3's `ns/day` format**: GPUresident prints `29.3 ns/day` (value-first, no colon)
  vs the old `0.027 days/ns`. `namd_metrics.parse_namd_log` now handles both, taking the LAST
  Benchmark line (`_RE_DAYS_PER_NS` / `_RE_NS_PER_DAY`). Non-GPUresident runs still emit days/ns.
- With the `multicore-CUDA` binary EVERY trial uses the GPU (the `+devices` flag only picks which),
  so `GPUresident on` is valid for all grid configs. Verified full 6-config sweep on a capped 4000-nt
  proxy: ~28-34 ns/day, `completed`. NOTE the benchmark is still a proxy (≤`NAMD_MAX_NT=4000`, 6hb rod),
  so its absolute ns/day ≈ production for same-size systems but won't equal a much larger real design.

## "CPU-only" NAMD config was a fiction on CUDA builds (FIXED 2026-06-30)
User saw "best = +p16 CPU 29 ns/day" and rightly asked how CPU beats GPU. Root cause: the
installed NAMD is a `multicore-CUDA` binary — it ALWAYS runs on a GPU; omitting `+devices`
just auto-selects device 0. Verified: the `devices=""` trial logs "binding to CUDA device 0 …
Running with GPU-resident mode". So "+p16 CPU" and "+p16 GPU:0" were the SAME GPU path (why they
tied within noise); the "CPU" label was wrong and there was no real CPU-only result.
Fix:
- `namd_runner.namd_is_cuda_build(bin)` (lru_cached) runs the binary bare, greps its banner for
  "CUDA". `routes_benchmark._namd_is_cuda_build()` feeds it to the grid.
- `benchmark.namd_config_grid(..., cuda_build=)`: CUDA build → per-GPU targets only (no fake CPU
  arm); single GPU → just thread-count sweep on GPU:0; **multi**-GPU → adds a real `GPU:all`
  (`devices=""`) config. CPU build / NAMD absent → CPU-thread configs (unchanged).
- Recommendation now carries the honest `label`; frontend `_recLine` uses it (never prints
  "CPU-only" for a GPU run). Real grid here: `['+p8 GPU:0','+p16 GPU:0','+p32 GPU:0']`.

## Verification status
- oxDNA sweep **GPU-verified end-to-end** at runner level: CPU 477 vs CUDA 1045 steps/s
  on RTX 2080 SUPER → recommends CUDA, temp dir cleaned.
- **NAMD sweep now verified end-to-end** (2026-06-30, RTX 3080 Ti / 32-core): full 6-config grid
  completes, e.g. +p16 CPU 116 ns/day; single-CPU slow test green in ~9 s.
- Live `GET /benchmark/hardware` confirmed against real nvidia-smi (12 CPU, 1 GPU).
- Routes/apply/metadata TestClient-pinned; full panel flow vitest-pinned.
- **NOT verified**: live browser button gesture → see **MV-BENCH** in `manual_validation_debt.md`.
