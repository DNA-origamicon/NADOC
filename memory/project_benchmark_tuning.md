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
- `tests/test_benchmark.py` (24): parse, ladder, grids, plan+cap, pick-best tie-breaks,
  metadata round-trip, synthetic-no-undefined-bases, mocked-runner sequential+cleanup,
  routes (hardware/apply→metadata/409/404).
- `frontend/src/ui/benchmark_panel.test.js` (5): mount, oxDNA sweep poll→apply-fills-inputs,
  failed sweep, NAMD apply, null-start.

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

## Verification status
- oxDNA sweep **GPU-verified end-to-end** at runner level: CPU 477 vs CUDA 1045 steps/s
  on RTX 2080 SUPER → recommends CUDA, temp dir cleaned.
- Live `GET /benchmark/hardware` confirmed against real nvidia-smi (12 CPU, 1 GPU).
- Routes/apply/metadata TestClient-pinned; full panel flow vitest-pinned.
- **NOT verified**: live browser button gesture (dev server was wedged mid-reload) →
  see **MV-BENCH** in `manual_validation_debt.md`. NAMD real-binary ns/day not run here.
