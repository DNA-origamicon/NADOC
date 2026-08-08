# oxDNA relaxation — archive (experiments + resolved investigations)

Split out of `memory/project_oxdna_relaxation.md` on 2026-07-09 for context economy.
**Read on demand only — never in a routine loop.** Open just the entry you need.

---

## 2. What already exists (audited 2026-06-14 — grounded in real code)

### 2.1 Backend oxDNA I/O — `backend/physics/oxdna_interface.py` (537 lines, COMPLETE)
Physical-layer only; converts Design+geometry ↔ oxDNA format. Never mutates Design.
- `write_topology(design, path)` (L200) — `.top`: `N S` header then `strand(1-based) base 3p 5p`. Handles loop/skip copies + deletions via `_strand_nucleotide_order` (L163) and `_build_ls_lookup` (L153). Sequences from `strand.sequence`, else `'N'`.
- `write_configuration(design, geometry, path, box_nm=None)` (L309) — `.dat`: header (`t`, `b`, `E`) then per-nuc `pos(3) a1(3) a3(3) vel(3) L(3)`. **a1** = base-normal (cross-strand), **a3** = 5′→3′ (`axis_tangent` for FORWARD, negated for REVERSE). Positions `× NM_TO_OXDNA`. Box auto-sized to extent + 20 nm; oxDNA handles PBC so no centering. `geometry` arg = list of dicts from `GET /api/design/geometry` (`helix_id, bp_index, direction, backbone_position, base_normal, axis_tangent`).
- `read_configuration(conf_path, design)` (L411) — parses a `.dat` (e.g. `last_conf.dat`), returns `{(helix_id, bp_index, direction_str): np.ndarray pos_nm}` (× `OXDNA_LENGTH_UNIT`). **Currently returns POSITION ONLY** (drops a1/a3). Loop copies: last copy wins. **Display gap → see §5.3.**
- `write_oxdna_input(top, conf, out, steps, relaxation_steps=...)` (L489) — writes ONE input file, hardcoded `sim_type=MC`, `backend=CPU`, `interaction_type=DNA2`, `T=296K`, `salt_concentration=0.5`, `max_backbone_force=5/far=10`, energy/trajectory/last_conf outputs. **Single-stage, CPU, blocking-oriented.** Needs replacement/extension for the CUDA 3-stage protocol (§5.1).
- `run_oxdna(input_path, oxdna_bin="oxDNA", timeout=300)` (L454) — **BLOCKING** `subprocess.run`, captures output, returns rc or `None` if binary missing. **No async, no PID capture, no live progress.** Must be rewritten async for live progress + stop (§5.2).

### 2.2 Existing oxDNA routes (one-shot, NOT a job manager) — `backend/api/crud.py`
- `POST /design/oxdna/export` (L13368) → ZIP (topology.top, conf.dat, input.txt, README) for manual run.
- `POST /design/oxdna/run?steps=` (L13440) → in-process blocking run; reads back positions. `OXDNA_BIN` env var (default `"oxDNA"`).
- `oxdna_steps`-driven path around crud.py L14374 — part of the CG→atomistic / gromacs-cg bridge (Phase 2 seed territory).

### 2.3 Existing oxDNA frontend (just buttons, no lifecycle) — Dynamics tab
- `index.html` `#oxdna-section` (~L3408): steps slider `#pl-oxdna-steps`, `#btn-oxdna-export`, `#btn-oxdna-run`, `#oxdna-status`.
- `frontend/src/api/client.js`: `exportDesignAsOxdna()`, `runOxdnaMinimization(steps)` (~L1871–1904).

### 2.4 The NAMD MD runner — THE TEMPLATE TO MIRROR
Backend:
- `backend/core/md_job.py` — `MdStatus` enum (queued/preparing/running/paused/failed/stopped/completed), `MdJob` dataclass (persisted to `workspace/md_jobs/{id}/job.json`, survives restart), `MdSegmentStatus`, `MdHealthSample`, `new_job(...)`. **Copy this shape wholesale.**
- `backend/core/namd_runner.py` — threaded async runner: `_RUNNING`/`_ACTIVE_PIDS` registries, `start_job` (daemon thread + asyncio loop), `_run_namd_async` (`asyncio.create_subprocess_exec`, PID capture, SIGTERM→SIGKILL on cancel), segment loop with per-segment health gate, `stop_job`, `reconcile_job_status` (detect detached procs after server restart).
- `backend/core/md_health.py` — health metrics + `append_health_jsonl`. `backend/core/namd_metrics.py` — log parser + `metrics.jsonl`.
- `backend/api/routes_md.py` — sub-router mounted in `backend/api/main.py` via `app.include_router(..., prefix="/api")`. Routes: `POST /md/jobs`, `GET /md/jobs`, `GET /md/jobs/{id}`, `GET /md/jobs/{id}/display`, `POST .../start|stop|production`, `DELETE`, `GET .../health|metrics`, `GET /md/namd-available` (L705 — `shutil.which`-style probe returning `{available, namd_available, gmx_available, recommended_threads}`). Live updates via `ws://…/ws/md-jobs/{id}` for non-terminal jobs; terminal jobs REST-poll.

Frontend:
- `frontend/src/ui/md_jobs_panel.js` (1336 ln) — `initMdJobsPanel({ mdDisplayController, getWorkspacePath })`. Launch button → `POST /api/md/jobs`; `showOpProgress(...)` modal during prep; job list; detail panel; **progress bar** `#md-jobs-progress`; **stage timeline** `#md-jobs-timeline` (●done ✗fail ○running ·pending ⚠advisory); **metrics cards** `#md-jobs-metrics` (incl. WC sparkline tooltip); WebSocket + REST poll; **display toggle** `#md-jobs-display-toggle` → `mdDisplayController.displayLatest(config_path, {forceReload, live})` / `.stopAndRestore()`; auto-stop on leaving Dynamics tab (`nadoc:left-tab-change`); prewarm timer.
- `frontend/src/ui/md_panel.js` (838 ln) — `initMdPanel(store, { designRenderer, mdOverlay, atomisticRenderer })` → returns `mdDisplayController` with `displayLatest/prewarmLatest/requestLatest/stopPrewarm/stopAndRestore`. The `nadoc` repr maps a frame to `applyFemPositions([{helix_id, bp_index, direction, backbone_position:[x,y,z], nx, ny, nz}], amp)` (md_panel.js L530–538).
- `frontend/src/ui/op_progress.js` — shared modal: `showOpProgress / hideOpProgress / setOpProgressLabel / setOpProgressFraction`. Ref-counted.
- Display sink: `designRenderer.applyFemPositions(updates, amp=1.0)` (design_renderer.js L817 → helix_renderer.js L3149). `applyFemPositions(null)` clears/restores. Init in `main.js` ~L1804–1806.
- Dynamics tab is a tabbed left sidebar (main.js ~L5706–5837); sub-panels are collapsible `.panel-section` blocks inside `#tab-content-dynamics` (index.html ~L3376–3832).

---

## 6. Implementation task breakdown (Phase 1)

1. **`oxdna_job.py`** — clone `md_job.py`: `OxdnaStatus`, `OxdnaStageStatus`, `OxdnaHealthSample`,
   `OxdnaJob` (persist `workspace/oxdna_jobs/{id}/job.json`), `new_oxdna_job(...)`. ≥1 unit test
   (round-trip save/load).
2. **`oxdna_protocol.py`** — stage specs + per-stage CUDA input-file writer. Pure functions → unit tests
   asserting input-file contents per stage.
3. **`oxdna_interface.py` EXTEND** — async run variant (PID capture); option-A read with a1 (if chosen).
   Pin async run behind a fake-binary test; pin read with a fixture `.dat`.
4. **`oxdna_health.py`** — base-pair retention, energy parse, clash count. Pure-ish → unit tests with
   small fixtures.
5. **`oxdna_runner.py`** — threaded async runner, stage loop + gates, stop, reconcile. Mirror namd_runner.
6. **`routes_oxdna.py`** — `POST /oxdna/jobs`, `GET /oxdna/jobs`, `GET /oxdna/jobs/{id}`,
   `GET /oxdna/jobs/{id}/display`, `POST .../start|stop`, `DELETE`, `GET .../health|metrics`,
   `GET /oxdna/oxdna-available`; WS `ws://…/ws/oxdna-jobs/{id}`. Mount in `api/main.py`. Backend tests.
7. **`client.js` EXTEND** — oxdna job CRUD + display fetch.
8. **`oxdna_display.js`** — controller reusing `applyFemPositions` (+ prewarm/auto-stop). Vitest for the
   frame→update mapping (pure).
9. **`oxdna_jobs_panel.js`** — clone md_jobs_panel UI (launch/list/detail/progress/timeline/health cards/
   display toggle). Vitest for any pure helpers (status formatting, stage rollups).
10. **`index.html`** — `#oxdna-jobs-*` panel markup in `#tab-content-dynamics` (can replace/augment the
    old `#oxdna-section` buttons; check `project_tech_debt.md` before deleting the legacy export/run UI —
    keep "Export oxDNA ZIP" for manual runs).
11. **`main.js`** — import + `const oxdnaDisplayController = initOxdnaDisplay(...)`; `initOxdnaJobsPanel({ oxdnaDisplayController, getWorkspacePath })`; thin wiring only. Cite LOC Δ.

---

## 11. Environment & oxDNA install (this machine, probed 2026-06-14)

Different machine from the original oxDNA prototype. **Windows + WSL2 Ubuntu 24.04.**
- **GPU present & capable:** NVIDIA RTX 2080 (8 GB), WSL passthrough, driver exposes CUDA 13.2 runtime.
- **Build toolchain MISSING:** no `nvcc` (no CUDA toolkit, no `/usr/local/cuda`), no `cmake`, no `g++`/`make`,
  no conda/mamba. Only `git` + `uv` (`~/.local/bin/uv`).
- **`sudo` is PASSWORD-GATED** (not passwordless) — Claude **cannot** run `sudo apt install …` non-interactively.
  Any system-level install (CUDA toolkit, build-essential, cmake) must be run BY THE USER (or with the user
  pasting a password).
- Disk: ~942 GB free. Plenty.

**oxDNA is NOT installed.** `OXDNA_BIN` unset; env convention is `OXDNA_BIN` (default `"oxDNA"`). Three install paths:

1. **CPU oxDNA via user-space Miniconda (NO sudo) — recommended dev path.** Install Miniconda into `~/miniconda3`
   (user-space, reversible, no system change), then `conda install -c bioconda oxdna`. Gives a working CPU
   `oxDNA` binary. Sufficient to develop + validate the ENTIRE runner/protocol/health/display on the small
   6hb fixture, because the protocol is backend-agnostic (CPU↔CUDA = one input-file line). Slow on large
   origami but fine for 6hb.
2. **CUDA build from source (needs USER sudo) — production GPU path.** User runs:
   `sudo apt install build-essential cmake` + the WSL CUDA toolkit (the WSL-specific package that does NOT
   overwrite the driver — see https://developer.nvidia.com/cuda-downloads, "WSL-Ubuntu"). Then Claude can:
   `git clone https://github.com/lorenzo-rovigatti/oxDNA && cd oxDNA && mkdir build && cd build &&
   cmake .. -DCUDA=ON && make -j`. Binary at `build/bin/oxDNA`; set `OXDNA_BIN` to it. ~3–4 GB download.
3. **Defer install — build code against a fake binary.** All Phase-1 code is writable + unit-testable now with
   a mock oxDNA executable (fake-binary test, like a stub that emits a canned `energy.dat`/`last_conf.dat`),
   and the UI degrades gracefully via the `oxdna-available` probe ("oxDNA not found"), exactly like the NAMD
   path when NAMD is absent. Real binary only needed for live end-to-end validation.

**Recommended sequence:** path 1 (CPU conda) to unblock real validation on 6hb now → develop everything →
path 2 (user installs CUDA toolkit) when ready for GPU production scale. Path 3 is the fallback if the user
doesn't want any install yet.

---

## 12. As-built status (2026-06-14) — Phase 1 code complete, awaiting oxDNA binary

**Backend (DONE, tested):**
- `backend/core/oxdna_job.py` — OxdnaJob/OxdnaStatus/OxdnaStageStatus/OxdnaHealthSample; jobs persist to
  `workspace/oxdna_jobs/{id}/job.json`.
- `backend/core/oxdna_protocol.py` — OxdnaStageSpec + `build_relaxation_stages()` (min CPU `sim_type=min` →
  relax CUDA MD capped-force → equil CUDA MD no cap) + `render_stage_input()` (pure) + `expected_energy_lines()`.
- `backend/core/oxdna_health.py` — `parse_energy_dat`, `energy_is_converged`, `base_pair_retention`
  (base-site proximity, cutoff 1.8 nm — see note), `max_backbone_stretch`, `run_oxdna_health_check` (gates).
- `backend/physics/oxdna_interface.py` — EXTENDED with `read_configuration_full` (pos + a1 + a3) and
  `backbone_bond_pairs`. Chose **display-option A**: relaxed a1 is read and used for both display orientation
  (nx/ny/nz) and bp-retention base sites.
- `backend/core/oxdna_runner.py` — async threaded runner (`find_oxdna`/`oxdna_available`, `prepare_oxdna_job`
  writes topology.top+conf.dat+design.json+stages_spec.json, `run_job` stage loop + health gates, `start_job`/
  `stop_job`, `job_progress` from energy.dat line count). `OXDNA_BIN` env or `~/oxDNA/build/bin/oxDNA`.
- `backend/api/routes_oxdna.py` — POST `/oxdna/jobs`, GET list/{id}/{id}/progress, POST start/stop, DELETE,
  GET health/metrics, GET `/oxdna/jobs/{id}/display` (returns applyFemPositions list directly — single relaxed
  frame, no WS), GET `/oxdna/available`. Mounted in `backend/api/main.py` (prefix `/api`). REST-poll, no WS.
- Tests: `tests/test_oxdna_relaxation.py` (13) incl. full runner orchestration via a **mock oxDNA binary**.
  Full backend suite **2032 passed** (was 2019). Ruff clean.

**Frontend (DONE, tested):**
- `frontend/src/api/client.js` — oxdna job CRUD + display helpers (`createOxdnaJob`, `listOxdnaJobs`,
  `getOxdnaProgress`, `start/stop/deleteOxdnaJob`, `getOxdnaHealth/Metrics/Display`, `oxdnaAvailable`).
- `frontend/src/ui/oxdna_display.js` — `initOxdnaDisplay({designRenderer, api})` + pure `toFemUpdates`;
  deforms NADOC model via `applyFemPositions`, `stopAndRestore()` clears.
- `frontend/src/ui/oxdna_jobs_panel.js` — `initOxdnaJobsPanel({oxdnaDisplay, getWorkspacePath})`: runs the
  CURRENT design, scrollable jobs list filtered to that design (reuses md_jobs_panel `filterJobsForPart` +
  show-all toggle), detail w/ progress bar + stage timeline + 4 health cards + "OxDNA display" toggle.
  REST poll 1.5 s while active; auto-stops display on leaving Dynamics tab.
- `frontend/index.html` — `#oxdna-jobs-panel` markup inserted after `#oxdna-section`.
- `frontend/src/main.js` — +5 lines (2 imports + comment + `const oxdnaDisplay = initOxdnaDisplay(...)` +
  `initOxdnaJobsPanel(...)`); pure wiring, ratchet held. main.js 7171→7176.
- Tests: `oxdna_display.test.js` + `oxdna_jobs_panel.test.js` (10). Full frontend suite **1223 passed**
  (was 1213). `vite build` OK.

**NOT yet done (blocked on local oxDNA binary):**
- oxDNA CUDA build — toolchain (nvcc/cmake/g++) not yet installed on this machine; `~/oxDNA` cloned (105 MB,
  CUDA source present). User running the sudo installs (§11 path 2). Then: `cd ~/oxDNA && mkdir build && cd
  build && cmake .. -DCUDA=ON && make -j`; set `OXDNA_BIN=~/oxDNA/build/bin/oxDNA`.
- **Live app exercise** of a real relaxation on the 6hb fixture (`workspace/Primitives/6hb_primitive.nadoc`)
  + `just smoke` — NOT done. The panel renders + degrades gracefully ("oxDNA binary not found") without it,
  but the live relax+timeline+health+display gesture is UNVERIFIED IN APP. → owes an MV-OXDNA row in
  `manual_validation_debt.md` + a USER TODO smoke block once the binary exists.
- oxDNA input defaults (steps/dt/thermostat) are conservative guesses — tune on the first real 6hb run.
  If CUDA build rejects `sim_type=min`, stage 1 already runs CPU; if it rejects any other key, adjust
  `render_stage_input`.

---

## 13. UPDATE 2026-06-14 (afternoon) — standard protocol + real binary + validation

**oxDNA binary built (CUDA).** Toolchain installed (cmake/g++/CUDA 13.3 nvcc). Built at
`~/oxDNA/build/bin/oxDNA` (`cmake .. -DCUDA=ON && make -j`). CUDA runtime libs resolve via ldconfig — the
app finds it through the `find_oxdna` fallback (`~/oxDNA/build/bin/oxDNA`); no `OXDNA_BIN`/PATH setup
needed at runtime. CPU backend works too (same binary).

**Protocol re-aligned to the STANDARD oxDNA origami relaxation** (https://lorenzo-rovigatti.github.io/oxDNA/relaxation.html):
- Stage 1 **MC** (CPU): `sim_type=MC, ensemble=NVT, delta_translation=0.1, delta_rotation=0.1,
  max_backbone_force=5, max_backbone_force_far=10`, default **1000** steps (10²–10⁴). *(Was `sim_type=min`
  in the first draft — corrected to MC.)*
- Stage 2 **MD relax** (CUDA): `sim_type=MD, dt=0.002, thermostat=bussi, bussi_tau=1000,
  newtonian_steps=53, max_backbone_force=5/10`, default **1,000,000** steps. *(Was brownian/dt=0.003.)*
- Stage 3 **equil** (CUDA): MD, dt=0.003, force cap removed (standard FENE), default **100,000** steps.
- Stage kinds renamed `mc`/`md_relax`/`equil`; request fields `mc_steps`/`md_relax_steps`/`equil_steps`;
  HTML/panel inputs + defaults updated to match. `render_stage_input` branches on `sim_type` (MC keys vs
  MD keys). These are the **standard defaults** a fresh run uses.

**Sequence requirement.** Unsequenced designs are rejected with a 400 at job creation (mirrors the NAMD
route): oxDNA's DNA2 rejects `N` bases, and H-bonding is sequence-dependent (no complementary partners →
melt). The panel surfaces the 400 detail (added `client.lastErrorMessage()`). The 6hb primitive is
unsequenced → use it to see the guard; a real run needs M13+staples assigned.

**Base-pair-retention gate lowered to 0.50** (was 0.80). It's a *catastrophic-melt* detector, not a
quality bar — relaxation inherently frays the lattice (ends especially); the exact % is shown per stage
regardless. (An all-A/all-T homopolymer 6hb relaxed to ~56% retention in a short run and still completed.)

**Real-binary validation (this machine).** A live 6hb run (sequenced FWD→A/REV→T) on the GPU went
`queued → running(MC 0→31%) → running(MD relax 33→65%) → running(equil 67→100%) → completed`, all stages
`done`, health recorded per stage, display read back 504 relaxed frames. The gate-fail path also confirmed
(80% gate → `failed` with "retention …").

**Tests now (all green):**
- Backend `tests/test_oxdna_relaxation.py` — **17 tests**: job round-trip, protocol input (MC/MD/equil,
  bussi/delta keys, standard defaults), health (energy parse/converge, bp-retention, clash), runner via
  mock binary (complete + gate-fail), **real-binary status lifecycle** (`test_runner_real_binary_status_lifecycle`,
  skipif no binary), and **HTTP routes** (`test_oxdna_available_route`, `test_oxdna_create_rejects_unsequenced`,
  `test_oxdna_http_lifecycle` create→poll→completed→display, skipif no binary). Full backend suite **2036**.
- Frontend `oxdna_jobs_panel.test.js` + `oxdna_display.test.js` — **17 tests**: `formatProgress`,
  `latestHealth`, **`detailStatusText`** (begin/monitor/finish/fail status lines), **`stageChips`** (timeline
  glyphs), `toFemUpdates`, display controller. Full frontend suite **1230**. `vite build` OK.
- `just smoke` **23/23** (console-error gate confirms the panel + display init clean in the running app).

**Remaining (human-eye only):** MV-OXDNA in `manual_validation_debt.md` — the live browser gesture
(click Relax, watch the sidebar tick running→completed; OxDNA-display toggle deform). Needs a sequenced
design + a ~10–15 s real run.

**Files touched this update:** `oxdna_protocol.py` (rewrite to standard), `oxdna_health.py` (gate kind
`mc`), `routes_oxdna.py` (request fields + sequence guard), `oxdna_jobs_panel.js` (step ids + pure status
helpers + error surfacing), `index.html` (input ids/labels/defaults), `client.js` (`lastErrorMessage`),
`test_oxdna_relaxation.py` (+real-binary +HTTP tests), `oxdna_jobs_panel.test.js` (+status tests).

---

## 14. UPDATE 2026-06-14 (eve) — CRITICAL: mutual traps required; structure-holds validated

**Finding (load-bearing, non-obvious).** A NADOC-built design fed to oxDNA at raw NADOC geometry does
**NOT hold** — a free MD melts it. Root cause: NADOC's coarse geometry (`HELIX_RADIUS=1.0 nm` → paired
backbones ~1.9 nm apart) places designed WC pairs' base sites **~1.25 nm apart**, far outside oxDNA's
H-bond range (~0.34 nm). So oxDNA never forms the designed pairs; MC keeps backbones roughly in place
(my geometric bp metric reads ~99%) but oxDNA hasn't bonded anything, and the first MD frame lets the
strands drift → bp collapses to ~7% and stays flat (energy fine, backbone intact). Measured directly:
initial base-site sep 1.25 nm → MC-out 0.73 nm (still >> 0.34). This is the documented oxDNA pain point
("many cadnano designs near impossible to relax").

**Fix — mutual-trap external forces (standard oxDNA relaxation aid).** `write_mutual_traps(design, path,
stiff=1.0, r0=1.2)` (in `oxdna_interface.py`) writes an oxDNA external-forces file: two symmetric
`mutual_trap` blocks per designed WC pair (particle indices = 0-based topology order), pulling each pair's
CMs toward `r0` oxDNA units so oxDNA forms the bonds while the backbone relaxes into native geometry.
Wired via `OxdnaStageSpec.external_forces` (ON for `mc` + `md_relax`, OFF for `equil`); `prepare_oxdna_job`
writes `forces.txt`; `render_stage_input(..., forces_name=...)` emits `external_forces = true /
external_forces_file = <abs path>` only for trap-enabled stages. The equil stage runs UNbiased so we can
confirm the pairs self-sustain.

**Validated on the 6hb (real GPU run, M13 scaffold + WC-complement staples).** With traps:
`MC bp=100% → MD-relax(trapped) bp 96→100%` as energy drops (U −0.25 → −1.43, relaxing into native
geometry) `→ equil(UNtrapped) bp 98–100%`, energy **plateaus at ≈−1.48** → **completed**, all stages 100%
retention. The untrapped equil holding ~100% is the proof the structure self-sustains after relaxation —
it plateaued, did not fall apart. (The user asked to "make sure the structure holds + check health until
plateau/fall-apart" — confirmed: plateau at ~100% bp / U≈−1.48.)

**Sequencing caveat.** `assign_staple_sequences` only complements staples against a **single continuous
scaffold**; the 6hb primitive has **6 disconnected scaffolds**, so it only sequenced the first staple
(others → 'N'). The validated path: assign M13 to each scaffold, then set each staple = WC-complement of
its helix's scaffold per (helix,bp). Real origami (one scaffold threaded via crossovers) wouldn't hit
this. The test helper `_sequence_for_oxdna` does the M13+complement approach. *(Potential future fix:
make `assign_staple_sequences` handle multi-scaffold designs — out of scope here.)*

**Tests (+3, full backend 2039):** `test_mutual_traps_file` (252 pairs → 504 trap blocks, valid indices),
`test_stage_external_forces_flags` (mc/md_relax ON, equil OFF), `test_render_includes_forces_only_when_enabled`.
The two real-binary lifecycle tests now use M13+complement + a lenient gate (0.3) + enough relax steps
(mc 500 / md 5000 / equil 2000) so they reliably complete (stochastic oxDNA — they validate the STATUS
lifecycle, not physics quality; ran 3× clean). `test_runner_end_to_end` asserts `forces.txt` staged + the
trapped MD holds ≥0.5. Frontend unchanged (1230).

**Files touched:** `oxdna_interface.py` (+`write_mutual_traps`), `oxdna_protocol.py` (+`external_forces`
field/flags, `render_stage_input` forces param), `oxdna_runner.py` (prepare writes forces.txt, stage passes
it), `test_oxdna_relaxation.py` (+3 trap tests, robust real-binary seq/steps/gate).

---

## 15. UPDATE 2026-06-14 (night) — consolidation, production, display PBC fix, job name

Four changes from user feedback after using the app:

**1. Consolidated to ONE panel.** Removed the legacy `#oxdna-section` (steps slider + "Run oxDNA" +
Export ZIP) from index.html and its `_initOxdnaControls` IIFE + `_initCollapsiblePanel('oxdna-heading'…)`
from main.js. The single collapsible is now `#oxdna-jobs-panel` titled **"oxDNA"**. "Export oxDNA ZIP"
(manual run) moved INTO it as a bottom button. `_DESIGN_PANEL_IDS` updated `oxdna-section`→`oxdna-jobs-panel`.
Legacy `crud.py` routes (`/design/oxdna/export`, `/design/oxdna/run`) + client `exportOxdna`/`runOxdna`
kept (export still used; run is dead but harmless).

**2. Production button (mirrors MD).** `[▶ Relax] [Start Production]` side by side; Production disabled
until the selected job is `completed`. Backend: `build_production_stage()` (kind=`production`, unbiased MD,
no traps, no force cap, no bp gate) + `POST /oxdna/jobs/{id}/production` (400 unless completed) — appends a
4th stage to the job's stages_spec.json + stages and resumes via `start_job`. Validated end-to-end with the
real binary (relax→completed→production→completed, stages `[mc, md_relax, equil, production]`). Frontend:
`appendOxdnaProduction` client helper, `_updateProductionButton` enable/status logic, prod-steps input.

**3. DISPLAY BUG FIX (critical) — "shows nothing but crossover arcs".** Root cause: oxDNA writes
coordinates **wrapped into the periodic box [0,L)**; an intact structure straddling a box face renders as
beads scattered across the ~50–80 nm box → off-screen, leaving only the (separate) crossover/end arcs.
Measured on the user's real job (4b42fb3601d9, 30 crossovers): RAW equil extent was fine-ish but
PBC-wrapped/translated far from the design. Fix: `read_configuration_unwrapped(conf, design, reference)` —
build a bond graph (backbone bonds + designed WC pairs → the whole origami is one connected component via
crossovers+pairs), **BFS each component placing every neighbour at its minimum image** (whole, never torn),
**box-shift each component to the image nearest its reference centroid**, then **exact-recentre the whole
assembly onto the reference (design) centroid**. Result on the user's job: both relaxed stages unwrap to a
compact ~14×14×12 nm structure centred exactly at the original design centroid → beads show in place. The
display route now uses it (reference = the job's `conf.dat`). NOTE: a *crossover-less* design (the 6hb
primitive) genuinely disperses (no bundle) — that's physics, not a bug; the user's real designs have
crossovers and display correctly. (Earlier wrong attempts: per-nucleotide snap-to-reference and per-strand
shift both TORE the structure — must unwrap by connected-component BFS, shift only whole components.)

**4. Job name fix.** A "save as" can leave `design.metadata.name` stale (6hb_OxDNA_test.nadoc carries
"6hb_primitive"). Backend create now derives the job name from `design_source_path` stem when present.
Frontend `jobDisplayName(job)` = source-path stem || design_name — fixes EXISTING jobs too (the user's
completed job stored `design_source_path='6hb_OxDNA_test.nadoc'`, so the list now shows "6hb_OxDNA_test"
without a re-run).

**Sequencing note (still relevant):** `assign_staple_sequences` only handles a single continuous scaffold;
the 6hb primitive (6 disconnected scaffolds) needs per-helix complement (see §14). 6hb_OxDNA_test has 30
crossovers + 9 strands → a real scaffold-routed design where the standard assign works.

**Tests (backend 2043 / frontend 1232 / smoke 23):** +`test_production_stage_spec`,
+`test_read_configuration_unwrapped` (synthetic wrapped→unwrap→compact-at-reference),
+`test_oxdna_production_requires_completed` (400 guard), +`test_oxdna_job_name_from_source_path`,
http_lifecycle extended with production; frontend +`jobDisplayName` tests. ruff clean, vite build OK.

**Files:** `oxdna_interface.py` (+`read_configuration_unwrapped`, `_parse_box_nm`),
`oxdna_protocol.py` (+`build_production_stage`), `routes_oxdna.py` (production endpoint, name-from-source,
display uses unwrap), `index.html` (legacy removed, Relax+Production+Export), `main.js` (legacy init removed,
`_DESIGN_PANEL_IDS`), `oxdna_jobs_panel.js` (production wiring, `jobDisplayName`, export btn),
`client.js` (+`appendOxdnaProduction`), tests.

---

## 16. UPDATE 2026-06-14 (late) — geometry verified correct; bp metric now uses oxDNA's real H-bonds

User saw the display "collapse then explode" while bp stayed ~100%. Investigated both the translation and
the metric with oxDNA's OWN H-bond detector (the `DNAnalysis` binary built alongside oxDNA, via the
`HBList` observable) as ground truth.

**Translation NADOC↔oxDNA is CORRECT.** Verified oxDNA's exact conventions from `src/model.h`: the `.dat`
position is the **centre of mass**; the base (H-bond) site = **CM + 0.4·a1** (POS_BASE=0.4), backbone =
CM − 0.34·a1 + 0.34·a2 (oxDNA2), H-bonds form at ~0.34 units (HYDR_RLOW). On a relaxed 6hb_OxDNA_test
(30 crossovers), designed pairs sit at **median base-site separation 0.35 nm** with a1·a1 = −0.99 (bases
facing) and a3·a3 = −0.93 (antiparallel) → oxDNA forms **real, correctly-oriented WC bonds**. The
"collapse" is the legitimate NADOC→oxDNA radius adjustment (NADOC backbones 1.93 nm apart vs oxDNA's
~1 nm duplex); the "explode" is the bundle breathing into oxDNA geometry — it HOLDS (~62% at 200k steps,
~88% at the default 1e6), it does not melt. No geometry bug. (Minor known imperfection, left as-is: we
write the CM at the NADOC backbone position rather than CM=backbone−site-offset; the relaxation + traps
correct it — the relaxed pairs are at proper 0.35 nm base-site geometry.)

**The bp HEALTH METRIC was the bug — fixed.** Old metric: base site = backbone + 0.3·a1 (treating pos as
backbone) with a **1.8 nm cutoff** — ~5× too loose, so it counted partners as "paired" while far outside
bonding range → read ~100% as the structure melted (exactly the user's symptom). Fixes:
- **`base_pair_retention` corrected** to the oxDNA base site (pos + `OXDNA_BASE_SITE_NM`=0.4·0.8518≈0.341 nm
  along a1) with a **0.8 nm cutoff**, calibrated to oxDNA HBList (0.8 nm → 221 vs 223 = 99% on the relaxed
  6hb; NADOC ideal geometry → 0%, correctly "not bonded yet").
- **Health check now prefers oxDNA's HBList ground truth.** New `count_hbonds(conf, topology,
  dnanalysis_bin, …)` runs `DNAnalysis` with the `hb_list`/`only_count` observable (+`max_backbone_force`
  so it can load strained NADOC-geometry configs; reads stdout as BYTES decoded leniently — DNAnalysis
  emits non-UTF8 that would otherwise crash the check). `find_dnanalysis()` resolves it next to the oxDNA
  binary. `run_oxdna_health_check` uses `n_hb / designed_pairs` when DNAnalysis is available, else the
  (now-correct) geometric proxy. On the user's job this reports **88%** = oxDNA's 223/252, exactly.

So the health % now tracks oxDNA's real base pairing: it climbs as pairs form during relaxation and DROPS
if they break — it will no longer read 100% while the structure melts.

**Test impacts (backend 2045 / frontend 1232):** the old "ideal NADOC = ~100% bp" assumption was WRONG
(ideal NADOC geometry is not oxDNA-bonded → ~0%). Updated: `test_bp_metric_low_on_unrelaxed_nadoc_geometry`
(ideal → <10%), `test_base_pair_retention_formed_vs_broken` (synthetic formed/broken at the oxDNA base
site), `test_count_hbonds_ground_truth` (skipif no DNAnalysis). The mock-binary + real-binary lifecycle
tests now use `min_bp_retained=0` (they validate the STATUS MACHINE; the real metric is genuinely low for
short runs, so gating there would be flaky — the gate is covered by `test_runner_gate_fails_on_melted`,
quality by the manual long run + HBList calibration).

**Files:** `oxdna_interface.py` (+`count_hbonds`), `oxdna_runner.py` (+`find_dnanalysis`, health-check
wiring), `oxdna_health.py` (corrected base-site metric + HBList-preferred retention), tests.

---

## 17. UPDATE 2026-06-14 (latest) — "thrown wildly out of position" = rigid-body drift; params are correct

User: the relaxation throws the 6hb wildly out of position; expected little motion in a relax stage; asked
to check relaxation parameters vs other oxDNA studies.

**Parameters are CORRECT (match the oxDNA docs + defaults).** Verified against
https://lorenzo-rovigatti.github.io/oxDNA/relaxation.html and the literature: our MD-relax input
(`dt=0.002, thermostat=bussi, bussi_tau=1000, newtonian_steps=53, max_backbone_force=5,
max_backbone_force_far=10`) is byte-for-byte the docs' recommended relaxation MD. **salt_concentration=0.5
is oxDNA2's own default** (`DNA2Interaction.cpp`: `_salt_concentration = 0.5`) and the value oxDNA2 was
parameterized at. MC stage matches the docs' MC relax. No parameter change needed. (Lit note: some origami
studies use ~1 M monovalent to mimic Mg²⁺ compaction and dt=0.001 for very strained starts — optional
future knobs, but not the cause here.)

**The structure is NOT actually deforming wildly — it's rigid-body diffusion.** Measured on a real relaxed
6hb_OxDNA_test (relax→production): **radius of gyration is preserved** (orig 5.33 nm → relaxed 4.8–5.6 nm);
median inter-helix spacing 2.25 → 2.66 nm (a small, correct relaxation toward oxDNA's true honeycomb
equilibrium ~2.65 nm; NADOC's was slightly tight); and **Kabsch best-fit RMSD to the original is only
2.5–3.7 nm** on a ~30 nm structure. The earlier "cross-section 6→14 nm" was the BOUNDING BOX inflated by a
few frayed end nucleotides, not real swelling. So the bundle stays intact; what the user saw as "wild
motion" is the whole molecule **translating + tumbling** (rigid-body diffusion — expected oxDNA MD for a
free molecule), and our display only recentred the CENTROID, not the rotation.

**Fix — display Kabsch alignment.** `read_configuration_unwrapped` now rigid-body **superposes** the
unwrapped relaxed structure onto the reference (initial conf.dat) via Kabsch (best-fit rotation +
translation, applied to positions AND the a1/a3 orientation vectors), instead of just recentring the
centroid. Result on the real job: per-nucleotide displacement from the original dropped from **22–35 nm →
2–3 nm mean** (max ~8–10 nm at frayed ends) — the display now shows the relaxed structure overlaid on the
design, with only the genuine internal relaxation visible. (Health metric is unaffected — it uses
`read_configuration_full` on the true relaxed geometry, not the aligned display copy.)

**Tests (backend 2045 / frontend 1232):** `test_read_configuration_unwrapped` upgraded to apply a rigid
ROTATION+translation+PBC-wrap and assert Kabsch recovers it (RMSD < 0.5 nm onto the original frame).

**Files:** `oxdna_interface.py` (`read_configuration_unwrapped` step 3 → Kabsch superpose), tests.

---

## 18. UPDATE 2026-06-14 (latest+1) — duplex "collapse" = CM-vs-backbone display artifact; NAMD-feed status

User: after Kabsch, a clear collapse in helical diameter — paired "slabs" ~80% overlapping. Asked if it's
oxDNA not representing true DNA, and whether the results still feed into NAMD.

**It's mostly OUR translation artifact, not oxDNA.** The oxDNA `.dat` position is the **centre of mass**,
which sits INWARD of the backbone (model.h: backbone = CM − 0.34·a1 + 0.34·a2, oxDNA2). We were rendering
the raw CM. Measured across a WC pair on a relaxed 6hb:
- CM–CM (what we displayed): **1.04 nm** ← collapsed → slab overlap.
- reconstructed true backbone–backbone: **1.64 nm**.
- base–base (H-bond): 0.37 nm ✓ (correctly bonded).
- NADOC native 1.93 nm; real B-DNA phosphate–phosphate ~1.8 nm.

**Fix:** `oxdna_backbone_site(cm, a1, a3)` reconstructs the backbone (CM + POS_MM_BACK1·a1 + POS_MM_BACK2·a2,
a2 = a3×a1) and the **display route** now renders that, not the CM → paired backbones at 1.64 nm. NADOC
slabs are sized for ~1.93 nm, so they overlap ~15% instead of ~80%.

**Residual IS oxDNA being coarse-grained (small):** true oxDNA duplex backbone-backbone 1.64 nm vs B-DNA
~1.8 nm — ~9% narrower. Expected for the CG model; base pairs are correctly H-bonded. So a slightly thinner
duplex than NADOC's idealised B-DNA is real, but the dramatic 80% overlap was the CM artifact.

**psfgen many-chain bugs fixed 2026-06-14 (surfaced via the NAMD seed on `3x6Sq_oxDNA`, 66 strands /
123k atoms).** The equilibrium-aware psfgen topology build (`namd_topology.py`) FATAL'd
("no residue N / failed to apply patch DEOX") on large designs — two independent bugs, both now fixed +
pinned, and verified building the real 3x6Sq seed model (66 segments, audit passed):
1. **Segid collision.** `_psf_segid(chain_id)[:4]` collapsed many strands onto one 4-char segname (chains
   `A`/`AA`/`AB` → `DNAA`), overwriting the shared `DNAA.pdb` + emitting duplicate `segment DNAA` blocks
   with mismatched residue counts. Fix: `_psfgen_segid(index)` = `D` + 3 base-36 digits → unique 4-char
   segname per chain (46 656 capacity); `_write_segment_pdbs` assigns by enumerate index and passes it to
   `_psfgen_pdb_record(atom, serial, segid)`. (Also fixes a latent `md_health` bug — colliding segids made
   it treat different chains as one segment.)
2. **Serial overflow.** The global PDB atom serial passed 99999 mid-file (scaffold alone = 64k atoms) →
   6-digit serials shifted the resid column → psfgen read wrong resids. Fix: write the serial with
   `_h36(serial, 5)` (hybrid-36, always 5 wide) in the ATOM record + TER line.
Tests: `test_psfgen_segid_unique_and_four_chars`, `test_psfgen_pdb_record_serial_stays_five_wide_past_100k`,
`test_write_segment_pdbs_unique_segids_and_aligned_resids` (+ existing psfgen-build test's segname assertion
updated `DNAA`→`D000`). Backend 2063. Files: `namd_topology.py`, `test_namd_topology.py`.

**Skip-relaxation → produce-from-seed 2026-06-14 (user request).** For an MD job seeded by oxDNA the NAMD
relaxation ladder is optional (the structure is already relaxed), so: (1) **"Start Production" is enabled on
a seeded job even with no relaxation checkpoint** — `get_md_job_display` now reports `production_ready=true` +
`production_from_seed=true` when `job.seed_oxdna_job_id` is set, no relaxation/continue checkpoint exists, and
the package manifest is built (`_seed_production_available`). The frontend prod button already follows
`meta.production_ready`, so no panel change was needed for enabling. (2) **Pressing "▶ Start" (run the
relaxation) on a seeded job shows a `window.confirm` continue/cancel** warning that relaxation can be skipped
(matches the existing delete-confirm pattern; `md_jobs_panel.js` startBtn handler). **Production-from-seed
mechanics (user chose "minimize-then-produce"):** `_append_production_segments` gains a `from_seed` branch —
when seeded + no checkpoint, the FIRST production segment starts from the solvated `{stem}.pdb` via new
`_seed_production_conf` (`temperature 310` → `minimize <minsteps>` → `reinitvels 310` → `run`), clearing
fresh-solvent clashes; later split-segments continue from its restart via the normal conservative conf. A
NON-seeded job with no checkpoint still 400s. Tests (backend 2069): from-seed append (first seg minimizes +
reinit + starts from pdb, no binCoordinates; later segs continue normally; manifest `from_seed:true`),
`_seed_production_available`, `get_md_job_display` seeded meta, and the non-seeded-still-blocks guard — all in
`test_md_milestone1.py::TestProductionAppend`. Files: `routes_md.py` (`_seed_production_available`,
`_seed_production_conf`, from-seed branch, display meta), `md_jobs_panel.js` (start confirm). Frontend
confirm is the untested-but-matches-`window.confirm`-delete pattern; live gesture → MV-OXDNA-SEED.

**ENM-prep "hang" fixed 2026-06-14 (NAMD seed on `3x6Sq_oxDNA`).** After the psfgen fix, the seed prep
*looked* hung but was actually finishing in ~6 min: `md_protocols.write_aksimentiev_enm_files` built the
base-ring elastic-network restraints with a Python double-loop over **1.76M residue pairs × ~81 atom-pairs
≈ 142M `numpy.dot` calls** (~5 min) then wrote **10.5M restraints × 3 files (1.4 GB)**. Fixed by replacing
the residue-COM-prefilter + atom double-loop with a single atom-level `cKDTree(pos).query_pairs(cut_ang)` +
vectorised inter-residue filter + chunked writes → **300 s → 28 s (~10×)**. **Also a correctness fix:** the
old 30 Å COM prefilter silently DROPPED ~1.5M valid restraints — when the PDB's 1-char chain column collides
across >62 strands, two physical residues merge under one `(chain,resid,resn)` key, their centroid lands far
away (measured 58 Å), and the prefilter excluded all their real <8 Å pairs. New count 12.05M ⊋ old 10.53M
(old ⊂ new, every extra pair genuinely <8 Å). Tests: `tests/test_aksimentiev_enm.py` (brute-force-equality on
small fixtures, inter-residue-only, empty-range). Backend 2066 (1 pre-existing stochastic oxDNA real-binary
flake, passes isolated). Files: `md_protocols.py` (KD-tree rewrite; dropped dead `math`/`re` imports +
`residue_com_cut_ang` param), `test_aksimentiev_enm.py`. NOTE the ENM is still inherently large (~1.6 GB for
5.7k bases) — NAMD will be slow reading it; reducing it would change the protocol physics (left as-is).

**NAMD feed — yes, but Phase-2 and needs the same fix.** The relaxed oxDNA CAN feed into NAMD via the
existing bridge `cg_to_atomistic.build_atomistic_model_from_cg_spline` (reads relaxed positions →
per-domain Gaussian smoothing σ=2 nt → `nuc_pos_override` → `build_atomistic_model` → existing NAMD package
pipeline). BUT: (1) that handoff is **NOT wired into any route** — it's Phase 2 (deferred, see §3/§10). (2)
The bridge calls `read_configuration` (the **CM**, 1.04 nm) as the backbone guide, so the atomistic duplex
would be too thin → startup clashes — the very thing relaxation should prevent. **Phase-2 TODO: feed the
reconstructed backbone (`oxdna_backbone_site`) — or have `cg_to_atomistic` use `read_configuration_full` +
reconstruct — NOT the raw CM.** Left unmodified now (untested, unwired Phase-2 code).

**Tests:** +`test_oxdna_backbone_site_widens_duplex` (backbone wider than CM, ≈real DNA). Backend 2046,
frontend 1232. (One stochastic real-binary test flaked once then passed on re-run — pre-existing oxDNA MD
nondeterminism, not this change.)

**Files:** `oxdna_interface.py` (+`oxdna_backbone_site`), `routes_oxdna.py` (display renders backbone site).

---

## 19. UPDATE 2026-06-14 (latest+2) — crossover arcs now follow the oxDNA display

User: the crossover arcs still showed the ORIGINAL design positions while the beads followed the oxDNA
relaxation.

Cause: `applyFemPositions` (helix_renderer) updates beads, cross-helix CONES, and base-pair slabs — but the
**regular crossover ARC lines** are owned by `unfold_view` (built as merged QuadraticBezierCurve3
LineSegments from `buildCrossoverConnections`'s "regular crossovers → unfold_view arc system" path), whose
endpoints are cached `from3D`/`to3D` from the design geometry. Nothing updated them on a FEM/oxDNA overlay.
(Extra-base crossovers — bead/slab bezier chains — are the *other* arc type; the 6hb's crossovers are
regular, so the merged arc lines were the stale ones.)

Fix:
- `unfold_view.applyFemArcs(updates|null)` — repositions each arc's endpoints to the relaxed backbone
  position of its from/to nucleotide (matched by `helix_id:bp_index:direction`, same key as
  `applyFemPositions`), drawn as a straight chord (matching the base 3D arc), and also rides any extra-base
  beads via `designRenderer.updateExtraBaseArc`. `null` reverts to `from3D`/`to3D`. Mirrors
  `_updateArcPositions` but uses the FEM endpoints. Exposed on the unfold_view API.
- `design_renderer`: `setFemArcUpdater(fn)` + `applyFemPositions` now calls `_femArcUpdater?.(updates,amp)`
  after moving beads — so ANY applyFemPositions caller (oxDNA display AND mrDNA/MD display) keeps arcs synced.
- `main.js`: `designRenderer.setFemArcUpdater((u) => unfoldView.applyFemArcs(u))` right after `initUnfoldView`.

**Verified:** vite build OK, frontend unit suite 1232, `just smoke` 23/23 (one assembly-exit flake that
passed on isolation + re-run). **NOT hand-verified in app** (Tier-3 visual): the arcs visibly tracking the
relaxed beads needs the oxDNA-display toggle on a crossover-bearing sequenced design + a real relaxation —
human-eye only (added to MV-OXDNA). Logic is a direct mirror of `_updateArcPositions` with the same nuc-key
fields (`_k`, unfold_view L290), so risk is low.

**Files:** `unfold_view.js` (+`applyFemArcs`), `design_renderer.js` (+`setFemArcUpdater`, applyFemPositions
hook), `main.js` (register). Backend unchanged (2046); frontend 1232.

---

## 20. UPDATE 2026-06-14 (latest+3) — jobs list now filters per-design + empty-state note

User: the jobs list showed jobs not belonging to the open design; wanted a "no jobs yet" note for a new design.

Root cause: the oxDNA panel was MISSING the `nadoc:workspace-path-change` listener that md_jobs_panel has
(L513). The filter itself (`filterJobsForPart(_jobs, _currentPartPath(), showAll)`, reused from
md_jobs_panel) is correct — jobs match on `design_source_path` === the active `getWorkspacePath()`, and a
null path returns `[]` (never leaks other designs' jobs). But with no listener, switching/opening a design
never re-ran `_renderList`, so the list kept showing the previous design's jobs (polling only runs while a
job is active, so nothing else refreshed it).

Fix (`oxdna_jobs_panel.js`): added a `nadoc:workspace-path-change` handler that turns off any active
display, clears the selection + detail, resets the production button, and re-filters — `_fetchJobs()` if
open else `_renderList()` (re-filter cached jobs). The empty-state note ("No oxDNA jobs for this design
yet.") already rendered when `_visibleJobs()` is empty, which now correctly fires for a new/unsaved design
(null path → filter returns []).

**Tests:** new `initOxdnaJobsPanel — per-design job filtering` factory block (mountIds + `vi.mock`'d
client): shows only the current design's jobs, re-filters on `workspace-path-change`, shows the note for a
new design with no matching jobs, and shows the note (no leak) when there's no open file path. Frontend
1236 (+4), build OK. Backend untouched.

**File:** `oxdna_jobs_panel.js` (+workspace-path-change listener), `oxdna_jobs_panel.test.js` (+4 tests).

---

## 21. UPDATE 2026-06-14 (latest+4) — Production button finished + Show RMSD

User: finish the Production button — finishing a relaxation flips the job to "production ready"; pressing
Production greys out BOTH relax + production buttons; the progress bar shows steps completed / production
total; add a "Show RMSD" button clickable only after a production run.

All implemented:
- **"production ready" status.** Pure `productionState(job)` → `none|running|done|failed`; `jobListStatus(job)`
  derives the list/detail label+color: completed relaxation w/ no production → **"production ready"** (accent),
  production running → "production", production done → "production done". Used in `_renderList` (row) and
  `_renderDetail` (status line).
- **Button graying.** New central `_updateButtons(job)` (replaces `_updateProductionButton`): Relax disabled
  while `!_available || _launching || prodRunning`; Production enabled only when prodReady (completed relax,
  no production); pressing Production also disables Run immediately for instant feedback. Wired through
  `_checkAvailable`, the run/prod/delete handlers, and `workspace-path-change`.
- **Production step-count progress.** `_renderProgress(job)` — when the production stage is running, the bar
  uses the production stage fraction and a label "Production: <done> / <steps> steps"
  (`stage_fraction × stage.steps`).
- **Show RMSD.** Backend `GET /oxdna/jobs/{id}/rmsd` → `production_rmsd(design, prod_traj, relaxed_ref)`:
  per-frame backbone RMSD of the production trajectory vs the pre-production (relaxed) structure, each frame
  PBC-unwrapped + Kabsch-aligned (rigid diffusion removed) → genuine internal deviation. Uses new
  `read_trajectory_frames_full` + the extracted `unwrap_align_to_reference` core. Returns
  {ready, n_frames, series, mean, max, min}. Button enabled only when a production stage is `done`; click
  shows "RMSD vs relaxed: mean X nm · max Y nm · N frames". Verified on the real 6hb_OxDNA_test production:
  **mean 2.31 nm, max 2.53 nm over 10 frames** (stable — the structure fluctuates ~2.3 nm around the relaxed
  state, doesn't drift).

**Tests (backend 2048 / frontend 1243 / smoke 23):** backend +`test_production_rmsd` (rigid frames → RMSD≈0
after Kabsch), +`test_oxdna_rmsd_not_ready_without_production`. Frontend +`productionState/jobListStatus`
pure tests, +factory tests (completed relax → Production enabled/RMSD disabled; production running → both
buttons greyed; production done → RMSD clickable + reports value). NOT hand-verified in app (Tier-3 visual,
added to MV-OXDNA): the live button-grey/step-count/RMSD gestures on a real production run.

**Files:** `oxdna_interface.py` (+`read_trajectory_frames_full`, extracted `unwrap_align_to_reference`),
`oxdna_health.py` (+`production_rmsd`), `routes_oxdna.py` (+`/rmsd` route), `client.js` (+`getOxdnaRmsd`),
`index.html` (+Show RMSD button/result), `oxdna_jobs_panel.js` (`productionState`/`jobListStatus`/
`_updateButtons`/step-count progress/RMSD handler), tests.

---

## 22. UPDATE 2026-06-14 (latest+5) — ETA to completion for relax + production runs

User: include an estimated time to completion for both relax and production runs.

- **Per-stage start time.** `OxdnaStageStatus.started_at` (Optional[float], defaults None so old job.json loads
  fine); the runner stamps it when a stage goes running.
- **ETA in `job_progress`.** For the running stage, rate = steps_done / (now − started_at) — steps_done =
  stage_fraction × stage.steps (stage_fraction from the energy.dat line count). Falls back to the last MD
  `steps_per_s` health sample if no live rate yet. `eta_seconds = (remaining-in-current + sum of pending
  stages' steps) / rate`. Works for BOTH a relax run (current+pending mc/md/equil) and a production run
  (single appended stage). Added to the `/oxdna/jobs/{id}/progress` payload.
- **Display.** `formatEta(seconds)` → "45s" / "2m 30s" / "1h 6m". `_renderProgress` appends "· ETA ~<t>" to the
  progress label whenever the job is running (and the production label already carries the step count, so you
  get "Production: X / Y steps · ETA ~3m 20s").

**Verified live** on a real 6hb_OxDNA_test relaxation: ETA populates during md_relax and converges to ~200 s
(400k remaining steps ÷ ~2000 st/s) — noisier at 1-2% (small sample), stabilising as it progresses.

**Tests (backend 2049 / frontend 1245):** backend +`test_job_progress_eta` (running stage + started_at +
energy.dat → eta in the expected window). Frontend +`formatEta` pure tests; the production-running factory
test now also asserts the bar shows "X / Y steps · ETA ~3m 20s".

**Files:** `oxdna_job.py` (+`started_at`), `oxdna_runner.py` (stamp start, ETA in `job_progress`),
`oxdna_jobs_panel.js` (+`formatEta`, ETA in `_renderProgress`), tests.

---

## 23. PHASE 2 PLAN — oxDNA-relaxed → NAMD seed (the melt-prevention handoff)

**Goal (the original motivation).** A complex origami often melts in the first steps of an all-atom NAMD
run because it starts from ideal B-DNA with strained crossovers. Phase 2 feeds the **oxDNA-relaxed**
coordinates into NAMD as the starting structure so the fine-grained run begins from an already-relaxed
state. Phase 1 (the oxDNA relax/production loop) is shipped + validated; Phase 2 wires its output into the
existing NAMD pipeline.

**Current state (audited 2026-06-14).**
- A completed oxDNA job has a relaxed `…/3_equil/last_conf.dat` (or `4_production/last_conf.dat`) + a
  `design.json` snapshot + `topology.top` in its job dir (`workspace/oxdna_jobs/{id}/`).
- The bridge EXISTS but is UNWIRED: `cg_to_atomistic.build_atomistic_model_from_cg_spline(design, conf_path,
  sigma=2.0) -> AtomisticModel` reads the relaxed positions, Gaussian-smooths per domain (σ=2 nt, avoids
  crossover smearing), and calls `build_atomistic_model(design, nuc_pos_override=...)`.
- `build_atomistic_model(design, nuc_pos_override=dict[(helix,bp,dir)->np pos])` (atomistic.py:873) ACCEPTS
  a per-nucleotide backbone override — this is the injection point.
- The NAMD pipeline does NOT yet accept relaxed positions: `build_namd_solvated_package(design, …)`
  (namd_solvate.py:1617) takes only a `design` and internally builds ideal B-DNA atoms via
  `build_atomistic_model(design)` / `export_pdb(design)`. `prepare_equilibrium_aware_namd(design, …)` /
  `prepare_mgh_slow_release(design, …)` (md_protocols.py:451/625) are what `routes_md.create_md_job` calls.
  `pdb_export.export_pdb(design, model=<prebuilt>)` already accepts a pre-built AtomisticModel
  (pdb_export.py:1016) — so the override can flow as either a `nuc_pos_override` dict OR a prebuilt model.

**CRITICAL fix first (§16/§18 — do NOT skip).** `build_atomistic_model_from_cg_spline` currently calls
`read_configuration` (the oxDNA CENTRE OF MASS, ~1.04 nm cross-pair) → the atomistic duplex comes out too
THIN → startup clashes (the exact thing we're trying to prevent). Change it to reconstruct the true
backbone: use `read_configuration_full(conf, design)` then `oxdna_backbone_site(cm, a1, a3)` per nucleotide
(both already in `physics/oxdna_interface.py`) → ~1.64 nm cross-pair, near B-DNA. Pin with a test that the
seeded backbone-backbone across a designed pair is ~1.6 nm, not ~1.0 nm.

**Tasks.**
1. **Fix the bridge** (above) + a test on a relaxed fixture (reuse `/tmp` verify-run conf or build one in the
   test via the runner with a mock/real binary).
2. **Thread the override through NAMD prep.** Add an optional `nuc_pos_override` (or `atomistic_model`) param
   to `build_namd_solvated_package` → `prepare_equilibrium_aware_namd` / `prepare_mgh_slow_release` so the
   solvated PDB/PSF is built from the relaxed coords (pass it to the internal `build_atomistic_model` /
   `export_pdb(model=…)` call). Keep the default (no override) = current behavior.
3. **Route + job link.** `routes_md.create_md_job` gains an optional `oxdna_job_id` (or `seed_conf_path`):
   when present, load that oxDNA job's design.json + latest relaxed last_conf, build the override via the
   fixed bridge, and pass it into prepare. (Alternative: a dedicated `POST /oxdna/jobs/{id}/seed-namd` that
   creates the MD job.) Record the seed source on the MD job for provenance.
4. **UI.** On a COMPLETED oxDNA job (status completed / production done), add a **"Use as NAMD seed"** button
   in `oxdna_jobs_panel.js` (next to Show RMSD) that calls the seed endpoint → spawns/pre-fills an MD job in
   the MD panel. Mirror the existing MD launch UX.
5. **Verify.** Seeded NAMD minimization should show FEWER startup clashes / lower initial energy than an
   ideal-B-DNA start on the same design (compare the MD health/metrics first frame). `just test` green;
   exercise once in-app on `workspace/6hb_OxDNA_test.nadoc`.

**Gotchas.** (a) The oxDNA design.json snapshot must match the topology used for the relaxed conf — always
read the job's OWN design.json, not the live editor design (they can differ). (b) Loop/skip copies collapse
in `read_configuration*` (last copy wins) — fine for a seed. (c) Salt/ion setup for NAMD is unchanged
(that's the solvate step); Phase 2 only swaps the DNA starting coordinates. (d) Keep oxDNA output strictly
Physical-layer — the seed is a NAMD INPUT artifact, never written back into Design topology.

**Files to touch:** `cg_to_atomistic.py` (backbone-site fix), `namd_solvate.py` + `md_protocols.py`
(override param), `routes_md.py` (seed link) or new `routes_oxdna` seed endpoint, `oxdna_jobs_panel.js`
(+ "Use as NAMD seed" button), `client.js` (helper), tests. Plan: this section + §10/§16/§18.

---

## 24. PHASE 2 SHIPPED 2026-06-14 — oxDNA-relaxed → NAMD seed (melt-prevention handoff)

All of §23 implemented. The relaxed oxDNA coords now feed the existing NAMD pipeline as the starting
structure instead of ideal B-DNA. **Physical-layer only** — the seed is a NAMD INPUT artifact, never
written back into Design topology; the route always reads the oxDNA job's OWN `design.json` (not the live
editor design).

**CRITICAL fix (done first):** `cg_to_atomistic.build_atomistic_model_from_cg_spline` no longer reads the
raw oxDNA CM (`read_configuration`, ~1.0 nm cross-pair → too-thin duplex → startup clashes). New helper
`read_backbone_positions(conf, design)` = `read_configuration_full` + `oxdna_backbone_site` per nuc →
~1.6 nm. **Validated on the REAL completed 6hb_OxDNA_test job (9d6f57f02ed0):** median CM-CM 1.02 nm →
backbone 1.60 nm over 252 WC pairs (matches §18's 1.04→1.64); seeded model = 11,720 atoms from the equil
`last_conf.dat`.

**Wiring (all default = current ideal-B-DNA behavior when no seed):**
- `namd_topology._write_segment_pdbs(design, tmpdir, model=None)` + `build_charmm_psfgen_topology(design, *,
  atomistic_model=None)` — psfgen path accepts a prebuilt model.
- `namd_solvate.build_namd_solvated_package(design, *, atomistic_model=None)` — passes the model to
  `export_pdb(model=…)` (legacy) or `build_charmm_psfgen_topology(atomistic_model=…)` (full topology). PSF
  is topology-only, unaffected.
- `md_protocols.prepare_mgh_slow_release(…, atomistic_model=None)`; `prepare_equilibrium_aware_namd`
  forwards it via `**kwargs`.
- `oxdna_runner.build_namd_seed(job_id, workspace) -> NamdSeed{design, atomistic_model, stage_name,
  conf_path, source_job_id}` — loads the job's design.json + latest relaxed/production `last_conf.dat`
  (`_latest_relaxed_conf`), builds the model via the fixed bridge. Raises FileNotFoundError if snapshot/conf
  missing.
- `MdJob.seed_oxdna_job_id` (provenance field; `setdefault` for old job.json) + `new_job` kwarg.
- `routes_md.create_md_job`: optional `oxdna_job_id` in CreateJobRequest. When set, builds the seed (in
  threadpool) BEFORE the binary checks → uses the seed's design + passes `atomistic_model` to prepare +
  records `seed_oxdna_job_id`. Bad id → 400.
- Frontend: `client.createMdJob(body)`; `oxdna_jobs_panel.js` pure `seedReady(job)` (= status==='completed')
  + "Use as NAMD seed" button (`#oxdna-jobs-seed-btn`) next to Show RMSD → POSTs `/md/jobs` with
  `oxdna_job_id` + the job's `design_source_path`, `autostart:false`; status line surfaces success/error.

**Tests (backend 2054 / frontend 1248, both green; ruff: only pre-existing unused-import warnings, none
introduced):** backend +`TestReadBackbonePositions` (2, synthetic relaxed conf → backbone wider than CM)
in `test_cg_to_atomistic.py`; +`test_build_namd_seed_uses_snapshot_and_backbone_site`,
+`test_build_namd_seed_missing_conf_raises`, +`test_md_create_with_bad_oxdna_seed_returns_400` in
`test_oxdna_relaxation.py`. Frontend +`seedReady` pure + 2 factory tests (completed→enabled+POST;
running→disabled). vite build OK.

**NOT live-verified in app (NAMD absent on this machine + backend was down):** the full seed→NAMD
minimization run and the live browser button click. The backend handoff IS validated against the real
completed oxDNA job (above) + unit tests; the button is factory-tested (click→createMdJob POST). Owes the
live gesture + the §23-task-5 fewer-clashes/lower-initial-energy comparison once NAMD is installed →
**MV-OXDNA-SEED** in `manual_validation_debt.md`.

**Files:** `cg_to_atomistic.py`, `oxdna_runner.py`, `namd_topology.py`, `namd_solvate.py`, `md_protocols.py`,
`md_job.py`, `routes_md.py`, `client.js`, `oxdna_jobs_panel.js`, `index.html`, tests.

### 24.1 Follow-up fixes 2026-06-14 (user feedback after first use)

**BUG — finished production not recognized (Show RMSD / Use-as-NAMD-seed stayed disabled).** Root cause:
oxDNA jobs had **NO restart reconciliation** (the §5.2 `reconcile_oxdna_status` was planned but never built).
A job is marked `running` only while an in-process runner thread owns it; when the backend restarts mid-run
the persisted `job.json` stays `running` forever even though the oxDNA process finished (last_conf + full
energy.dat on disk). The user's real 3x6Sq job (`75eea57a13f5`) was stuck `running`/production-`running`
with the production stage physically complete (101 ≥ 100 expected energy lines, last_conf written).
**Fix:** new `oxdna_runner.reconcile_oxdna_status(job, ws, specs=None)` — for a `running` job with no live
runner (`not is_running`), recover status from disk: a stage whose `energy.dat ≥ expected_energy_lines` AND
has `last_conf.dat` is marked `done`; all done → `completed`; a stage interrupted mid-run → `stopped`
(resumable). Idempotent; no-op for terminal jobs. Wired into `routes_oxdna._load_job` + `list_oxdna_jobs`
so every panel read self-heals. (The panel polls while a job looks active → next fetch reconciles → buttons
re-enable. `seedReady`=status==='completed' and RMSD=productionState==='done' then both unlock.)

**UX — seed button now hands off to the MD panel.** On seed success the oxDNA panel `_revealMdPanel()`
collapses itself (`setSectionCollapsed('dynamics','oxdna-jobs-panel',true)`) and, if the MD panel is
collapsed, clicks `#md-jobs-panel-heading` to open it (its own handler refreshes the list). The new MD job
row shows an **"oxDNA seeded"** badge (pure `md_jobs_panel.seededBadge(job)` gated on
`job.seed_oxdna_job_id`).

**Tests (backend 2058 / frontend 1250, green; ruff clean on touched files):** backend
+`test_reconcile_completes_detached_finished_production`, +`test_reconcile_interrupted_midstage_to_stopped`,
+`test_reconcile_noop_for_terminal_job`, +`test_oxdna_list_route_reconciles_detached`. Frontend
+`seededBadge` pure + the seed-reveal factory test (oxDNA collapses + MD heading clicked). **Verified on the
user's REAL stuck job:** reconcile flipped `75eea57a13f5` running→completed (production done), other jobs
untouched. **Files:** `oxdna_runner.py` (+reconcile), `routes_oxdna.py` (wire into load/list),
`oxdna_jobs_panel.js` (+`_revealMdPanel`), `md_jobs_panel.js` (+`seededBadge` + row badge), tests.

### 24.2 "Show RMSD" → Flexibility-map display toggle 2026-06-14 (user clarification)

User clarified: the RMSD feature should show the **average per-base structure over the production run,
recoloured by per-base RMSF** (rigid vs flexible), as a **toggle below "OxDNA display"** with a loading bar
+ check icon, disabled (showing "waiting for production") until production finishes. Reworked the one-shot
"Show RMSD" text button into this.

- **Backend `oxdna_health.production_rmsf(design, prod_traj, ref_conf)`** — reads every production frame
  (`read_trajectory_frames_full`), PBC-unwraps + Kabsch-aligns each to the relaxed reference
  (`unwrap_align_to_reference`, removing rigid diffusion/tumbling), then per nucleotide returns the **mean
  true-backbone-site position** (`oxdna_backbone_site`, not the raw CM) + mean a1 + **RMSF** (RMS fluctuation
  about that mean), plus `min/max/mean_rmsf`. **Route `GET /oxdna/jobs/{id}/rmsf`** — ready only once the
  production stage is `done` (else `{ready:false, reason:"waiting for production"}`). Verified on the real
  6012-base job: RMSF 0.25–2.8 nm (rigid p10 0.42, flexible p90 0.98).
- **Per-bead scalar colouring (new renderer capability).** `helix_renderer.applyScalarColors(colorByKey)` /
  `clearScalarColors()` — captures each touched bead's current colour (via `getColorAt`, THREE r172) on
  first apply and restores it on clear (no rebuild). Exposed through `design_renderer`. Colours backbone
  beads by `helix:bp:dir → hex`.
- **Display controller (`oxdna_display.js`).** `displayRmsf(jobId)` fetches `/rmsf`, deforms to the mean
  structure via `applyFemPositions` AND recolours via `applyScalarColors`; pure `viridisHex(t)` +
  `rmsfColorMap(resp)` (RELATIVE min→max scaling, viridis ramp — per the user's choices). `_mode`
  ('relaxed' | 'rmsf') tracks which overlay is active; `stopAndRestore` clears positions + colours;
  `displayJob` clears scalar colours when switching from the flex map. **Mutually exclusive** with OxDNA
  display (panel turns the other off).
- **Panel (`oxdna_jobs_panel.js`).** New `#oxdna-jobs-flex-toggle` below `#oxdna-jobs-display-toggle` +
  `_setFlexBar` (indeterminate `gromacs-indeterminate` stripe while computing → "✓ Flexibility map ready") +
  `_setFlexLegend` (viridis gradient min→max nm) + gating in `_updateButtons` (disabled + "Waiting for
  production" until `productionState==='done'`). `_allDisplaysOff()` turns off whichever overlay is active on
  tab-leave / workspace-change / delete. Removed the old `#oxdna-jobs-rmsd-btn`/result. (`/rmsd` route +
  `getOxdnaRmsd` kept, now unused by the panel.)

**Refinements 2026-06-14 (user follow-up):**
- **Same Kabsch reference as the OxDNA display.** The `/rmsf` route now aligns every production frame to the
  job's `conf.dat` (the design geometry) — IDENTICAL to the display route's `read_configuration_unwrapped(...,
  jd/conf.dat)` — instead of the equil last_conf. RMSF magnitudes are unchanged (RMSF is invariant to a rigid
  transform of the common alignment target), but the average structure now overlays the design in the exact
  same place/orientation as the relaxed display. Verified on the real job: flex-map mean centroid == display
  centroid == design centroid to 0.001 nm.
- **Cones + slabs recolour with the beads.** `helix_renderer.applyScalarColors` now recolours not just
  backbone beads but their direction **cones** (by `fromNuc`) and base-pair **slabs** (by `nuc`), so the whole
  representation reads as one rigid→flexible map. Captured colours are keyed `mesh.uuid:instanceId`
  (dedup across refresh) and restored on clear; `_flagScalarColorMeshes` flips `instanceColor.needsUpdate`
  on all four instanced meshes (iSpheres/iCubes/iCones/iSlabs).

**Tests (backend 2060 / frontend 1258, green; ruff clean):** backend +`test_production_rmsf` (a single
moving base → high RMSF vs the rest), +`test_oxdna_rmsf_waiting_for_production` (route gate). Frontend
+`viridisHex` (2) +`rmsfColorMap` (3, incl. uniform-RMSF no-divide-by-zero) +`displayRmsf` controller (2) +
panel flex-toggle tests (gating/unlock/displayRmsf-call/legend, mutual-exclusivity). **NOT verified in app**
(backend was down; live toggle + the actual recoloured-bead visual is human-eye only) → folded into
MV-OXDNA-SEED's flex-map note. **Files:** `oxdna_health.py`, `routes_oxdna.py` (+`/rmsf`),
`helix_renderer.js` + `design_renderer.js` (+scalar colours), `oxdna_display.js` (rewrite: viridis + rmsf),
`oxdna_jobs_panel.js` (flex toggle), `index.html`, `client.js` (+`getOxdnaRmsf`), tests.

### 24.3 Adjustable workspace colour-scale widget 2026-06-14 (user follow-up)

User: an adjustable scale in the **middle-right of the workspace** where the user sets the upper/lower bounds
of the RMSF→colour scale, starting at the standard min→max.

- **New module `frontend/src/ui/flex_scale.js`** — `initFlexScale({onBoundsChange}) → {show(min,max), hide,
  isVisible, getBounds}` + pure `clampBounds(lo,hi)` (orders/swaps, never zero-span). Owns the
  `#flex-scale` overlay (markup in `index.html` inside `#canvas-area`, pinned middle-right, hidden by
  default): viridis ramp (rigid→flexible) with editable **max** (top) + **min** (bottom) number inputs + a
  **Reset** button (back to data min→max). Tolerates a missing root (no-op) for headless tests.
- **`oxdna_display.js`** — `rmsfColorMap(resp, loBound, hiBound)` now takes optional bounds (default = data
  min→max; out-of-range clamps to the viridis endpoints; reported `min/max` stay the DATA range). The
  controller caches the `/rmsf` payload (`_rmsfResp`) and adds `recolorRmsf(lo,hi)` → rebuilds colours from
  the cache and re-applies via `applyScalarColors` **without re-fetching or moving positions**; cleared on
  `stopAndRestore`.
- **`oxdna_jobs_panel.js`** — instantiates `flexScale` with `onBoundsChange: (lo,hi) =>
  oxdnaDisplay.recolorRmsf(lo,hi)`; `flexScale.show(min,max)` on flex-display success, `flexScale.hide()` in
  `_setFlexOff` (so it disappears on toggle-off / tab-leave / design-switch / delete). The small sidebar
  legend is kept too. **No main.js change** (panel imports the module).

**Tests (frontend 1267, green; backend untouched this turn — frontend-only):** +`flex_scale.test.js`
(`clampBounds` + factory: show/hide/edit-emits/reset/missing-root) + display `recolorRmsf` (2) + bounded
`rmsfColorMap` (1) + panel tests (scale shows seeded min→max; editing a bound calls `recolorRmsf`). vite
build OK. **NOT verified in app** (the live workspace widget + recolour gesture) → MV-OXDNA-SEED flex note.
**Files:** `flex_scale.js` (new), `oxdna_display.js`, `oxdna_jobs_panel.js`, `index.html`, tests.

**Refinement 2026-06-14 — draggable handles + slimmer legend.** Replaced the static gradient with two
**draggable handles** on the viridis track (upper = hi bound, lower = lo bound) that **recolour in real time
while dragging** (each `pointermove` → `onBoundsChange` → `recolorRmsf`); the number inputs remain as
readouts/precise entry + Reset. Removed the "flexible"/"rigid" text column (user intuits it) → the widget is
now ~56 px wide. Pure helpers `valueToFraction`/`fractionToValue` (track-fraction ↔ RMSF, clamped) drive
handle positioning (top as %) and pointer→value mapping (via `track.getBoundingClientRect`); handles can't
cross (min-gap = 1% of the data span). `#flex-scale-track` + `#flex-scale-handle-hi/lo` added to index.html.
Frontend **1270** (+drag-simulation + mapper tests). Live drag gesture still human-eye only (MV-OXDNA-SEED).

**Refinement 2026-06-14 — crossover arcs recolour too.** The flexibility map now recolours the crossover
ARC lines (owned by `unfold_view`, §19) to match the recoloured beads/slabs/cones. `unfold_view`
gains `applyFemArcColors(colorByKey|null)` — each arc takes its from-endpoint's RMSF colour (fallback
to-endpoint) via `_setArcColor`; `null` restores natural colours via `_paintArcByMode` (no `e.color`
mutated). `design_renderer.applyScalarColors`/`clearScalarColors` now also fire a registered
`_scalarArcUpdater` (mirrors `_femArcUpdater`); `main.js` registers
`setScalarArcUpdater((c)=>unfoldView.applyFemArcColors(c))` next to the existing `setFemArcUpdater` line
(one-line wiring). WebGL path — not jsdom-unit-testable (mirrors the untested `applyFemArcs`); frontend
**1270** green + vite build OK. **Files:** `unfold_view.js` (+`applyFemArcColors`), `design_renderer.js`
(+`setScalarArcUpdater` + fire in apply/clear), `main.js` (+1 wiring line).

---

## UPDATE 2026-06-16 — undefined-base guard tightened (any 'N' blocks) + warning popup

The job-creation sequence guard previously rejected only a **fully** unsequenced design
(`sequenced_bases == 0`). Per user: an oxDNA job must be blocked whenever the design **still has
undefined bases** (ANY 'N', not just all-N) → "finish assigning sequences".

- **Backend.** New pure helper `count_undefined_bases(design, exclude_reference=True)` in
  `oxdna_interface.py` — mirrors `write_topology`'s per-nucleotide base assignment exactly (loop copies
  expanded, skips/deletions dropped) and counts every position that would be written `'N'`. Reference
  backdrop strands (`is_reference`) are **excluded** (user decision — consistent with every other export
  path). `routes_oxdna.py` create now `raise HTTPException(400, …)` if `undefined > 0` (replaces the old
  all-N check; the message names the undefined-base count + "Finish assigning sequences").
- **Frontend.** New module `frontend/src/ui/sequence_warning_modal.js` →
  `showSequenceWarningModal({message})` (⚠ blocking popup, OK/✕/click-outside) + pure
  `isUndefinedSequenceError(message)`. `oxdna_jobs_panel.js` Relax handler: on a failed create, if
  `isUndefinedSequenceError(detail)` → show the popup + status "Relaxation blocked — finish assigning
  sequences"; other failures keep the inline status line. Backend stays the source of truth (no
  duplicated sequence logic on the client). Modal is reusable for the NAMD path (same all-N guard).
- **Tests:** backend +5 (`count_undefined_bases` all/full/partial/reference + route rejects-partial),
  full suite **2191**; frontend +5 (`sequence_warning_modal.test.js`), suite **1283**; ruff + vite OK.
- **Live gesture NOT hand-checked → `manual_validation_debt.md` MV-OXSEQ (PENDING).**
- **Files:** `oxdna_interface.py` (+`count_undefined_bases`), `routes_oxdna.py` (guard + import),
  `sequence_warning_modal.js` (new), `oxdna_jobs_panel.js` (import + Relax-fail branch),
  `test_oxdna_relaxation.py` (+5), `sequence_warning_modal.test.js` (new).

---

## UPDATE 2026-06-16 (b) — running-job spinners (list rows + Relax/Production buttons)

User: add a spinning circular indicator so it's obvious an oxDNA job is running; must survive a reload.

- **CSS.** `@keyframes nadoc-spin` + `.nadoc-spinner` (border-ring, `currentColor`, reduced-motion aware)
  in `frontend/src/styles/components.css`. Reusable.
- **Panel** (`oxdna_jobs_panel.js`): new exported pure helpers `jobIsActive` (queued/preparing/running),
  `isRelaxRunning` (running & not production), `isProductionRunning` (running & production stage active) +
  `makeSpinner(color,size)`. List rows render a spinner instead of the ● dot while active; `_updateButtons`
  drives a leading spinner on the **Relax** button (`relaxActive = _launching || any isRelaxRunning`) and the
  **Production** button (`any isProductionRunning`) via `_setBtnSpinner` (rebuilds only on state change —
  `dataset.spinning` — so the animation doesn't restart each poll).
- **Reload-safe:** spinners are derived from LIVE job state, not a click flag. `_fetchJobs` now calls
  `_updateButtons(_selectedJob())` after `_renderList()` so the buttons spin from job state even with nothing
  selected (the reload case); the poll already keeps running via `_hasActiveJob()`.
- **No-stutter:** `_renderList` now early-returns when the list signature (`id:status:productionState` per job
  + selectedId) is unchanged, so a running job's health/progress updates no longer rebuild the rows (which
  would restart the row spinners' CSS animation every 1.5 s).
- **Tests:** `oxdna_jobs_panel.test.js` +7 (helper units + makeSpinner + 3 integration: relax-running,
  production-running, completed-idle — all via `panel.refresh()` with NO selection). Frontend suite **1290**,
  vite build OK, `just smoke` 23/23. Frontend-only (no backend).
- **Live spinning visual + mid-run reload NOT hand-checked → `manual_validation_debt.md` MV-OXSPIN (PENDING).**

---

## UPDATE 2026-06-16 (c) — running job mislabeled `stopped` after dev-server reload (reconcile fix)

**Symptom (user):** a real oxDNA production run for `18hb2.nadoc` was running on the GPU but the panel
showed no spinner. **Root cause:** the oxDNA process was ORPHANED. `uvicorn --reload` auto-restarts on any
backend `.py` edit; that kills the worker that spawned oxDNA, the oxDNA subprocess survives (re-parented to
init) and keeps writing stage output, but the in-memory `_RUNNING`/`_ACTIVE_PIDS` registry is lost. On the
next `GET /oxdna/jobs`, `reconcile_oxdna_status` saw no live runner thread, inspected the still-incomplete
production stage on disk, and marked the job `stopped` — even though the process was alive. The spinner was
correctly reflecting the (wrong) status.

**The gap:** `reconcile_oxdna_status` lacked the process-detection guard that `namd_runner` already has
(`_external_process_running` scans /proc). oxDNA never got it, and the PID isn't persisted to job.json.

**Fix:** added `_external_oxdna_running(job, workspace_dir)` (mirror of namd_runner — scans `/proc/*/cmdline`
for a process whose command line references the job dir AND is the oxDNA binary) and call it in
`reconcile_oxdna_status` right after the `is_running` check: if the orphan is still alive → return the job
UNCHANGED (keep `running`). When the orphan later finishes (stage complete on disk), a subsequent reconcile
promotes it to `completed` as before. Test: `test_reconcile_keeps_running_when_process_still_alive`
(monkeypatches the detector True → status stays running). Full backend **2192**, ruff clean.

**This session's live job recovered:** the 18hb2 production (`eb35207d57ab`) finished on the GPU during
diagnosis; an offline run of the fixed `reconcile_oxdna_status` marked it `completed` (all 4 stages done) —
the production output (`4_production/last_conf.dat` + trajectory) was preserved, not lost.

**Caveat / known follow-up:** the live dev server got wedged during diagnosis (unresponsive; worker PID
unchanged so `--reload` never loaded the fix) — required a manual `just dev` restart to pick up the new code.
PID is still not persisted to job.json (stop_job after a restart still can't signal the orphan — same gap as
NAMD; out of scope here). The /proc scan is the load-bearing recovery path.

**Files:** `oxdna_runner.py` (+`_external_oxdna_running`, reconcile guard), `test_oxdna_relaxation.py` (+1).

---

## UPDATE 2026-06-16 (d) — continue-production + multi-run RMSF + trajectory player

Three user-requested additions to the oxDNA panel:

**1. Continue production (re-run from where it left off).** `build_production_stage` no longer hardcodes
`name="4_production"`; it takes a `name` param. The `/oxdna/jobs/{id}/production` route now names each run
`f"{len(specs)+1}_production"` (→ `4_production`, `5_production`, …), so a re-run gets its own stage dir and
the runner's existing prev-stage chaining continues it from the previous run's `last_conf.dat`. Frontend:
`prodReady = status==='completed'` (was `&& ps==='none'`), so **Start Production** re-enables after a run
finishes; status line reads "Production complete (N runs). Start again to continue…". `productionState` now
reflects the LATEST production stage (was first); `productionRunCount` helper added.

**2. Flexibility map reads ALL production runs.** `production_rmsf(design, traj, ref)` now accepts a LIST of
trajectory paths (normalized) and pools frames across them. The `/rmsf` route gathers every *done*
production stage's `trajectory.dat` and passes the list, so the RMSF map reflects all runs, not just the first.

**3. "View trajectory" toggle (play/pause + scrub slider + stage markers).** New compact endpoint
`GET /oxdna/jobs/{id}/trajectory` → `composite_trajectory()` (in oxdna_health.py): reads every stage that
wrote a `trajectory.dat` (relaxation mc/md_relax/equil + all production runs), PBC-unwraps + Kabsch-aligns
each frame to the design reference (same as display), downsamples PER STAGE to a cap (default 200, ≥1/stage),
and returns a compact payload — `keys` (M nucleotides) sent once + each frame a flat float list
(`[x,y,z,nx,ny,nz]×M`, backbone site + a1) + per-stage counts + transition `markers`. Preload model (user
chose smooth client-side scrub over per-frame streaming).
  - `oxdna_display.js`: new `'trajectory'` mode — `loadTrajectory(jobId)` caches the payload, `showFrame(i)`
    deforms via `applyFemPositions(framesToUpdates(keys, frame))`. Pure `framesToUpdates` exported.
  - NEW module `oxdna_trajectory_player.js` (`initOxdnaTrajectoryPlayer({playBtn,slider,markersEl,label,
    onSeek,fps})`) — play loop (loops continuously), slider sync, frame counter, and stage-transition tick
    markers over the slider (pure `markerPositions`). onSeek → `oxdnaDisplay.showFrame`.
  - Panel: third toggle `#oxdna-jobs-traj-toggle` (+ controls/play/slider/markers/label), mutually exclusive
    with OxDNA-display + Flexibility-map (all share the one bead overlay; `_allDisplaysOff` stops the player
    too). Gated on `hasTrajectory(job)` (≥1 stage started). main.js untouched (panel already wired).

**Tests:** backend +6 (`tests/test_oxdna_relaxation.py`: custom-name stage, rmsf pools multi-traj,
composite_trajectory + downsample, continue-production unique-name route, trajectory not-ready route) →
**2198**; frontend +24 (`oxdna_trajectory_player.test.js` new, `framesToUpdates`/loadTrajectory/showFrame in
oxdna_display.test.js, multi-production helpers + continue-prod + traj-toggle integration in
oxdna_jobs_panel.test.js) → **1307**; ruff clean, vite build OK, `just smoke` 23/23.

**Live gestures NOT hand-checked → `manual_validation_debt.md` MV-OXTRAJ (PENDING)** (continue-production
chaining, RMSF across runs, trajectory play/scrub + markers — needs a real GPU run with ≥2 production runs).

## UPDATE 2026-06-20 — denser trajectory player track (was only ~10 frames)
The player was capped at ~10 frames/stage because each stage only WROTE ~10 configs:
`print_conf_interval = steps // 10`. Bumped to `steps // 100` (~100 frames/stage, matches the
energy-sample cadence) in `oxdna_protocol.py` — the composite endpoint still downsamples across stages
to its 200-frame cap. Also: oxDNA's first trajectory write lands at step `interval` (not t=0), so the
seed configuration (the run's true first frame) was never in any `trajectory.dat`; `composite_trajectory`
now prepends `ref` (the job's `conf.dat`) to the first non-empty stage, so the player starts on the true
starting structure. The per-stage `_stride_pick` already preserves both endpoints, so start+end frames
are guaranteed. Applies to NEW runs only (existing `trajectory.dat` files keep their baked-in ~10 frames).
Tests updated: `test_print_conf_interval` (1k not 10k), `test_job_progress_next_frame_eta` (frame 30,
~0.33 s ETA), `test_composite_trajectory` (6 frames, marker at 3). `just test` 2820 passed.

## UPDATE 2026-06-20 (b) — chained runs + full-lineage trajectory view
The View-trajectory player now shows the WHOLE ancestor chain, and field/production runs can be chained
arbitrarily (relax → field1 → field2 → …, each seeded from the prior's end state).
- **Guard lifted:** `/oxdna/jobs/{id}/field` and `…/run` no longer reject a child parent (the
  `if parent.parent_job_id: raise 400` blocks are gone). `_latest_relaxed_conf` already returns a field
  child's `last_conf`, so branching off a completed child seeds from its final structure. User chose
  "allow arbitrary chaining" (any depth).
- **`_lineage_jobs(job)`** (routes_oxdna.py) walks `parent_job_id` root→…→selected. `GET …/trajectory`
  concatenates every stage of every job in the chain, aligns ALL frames to ONE design-origin reference
  (`_design_ref_conf`, NOT the job's drifted `conf.dat`), and tags each non-root job's first stage with a
  numbered boundary marker ("→ field 1", "→ field 2"). `composite_trajectory` stage tuples are now
  `(name, kind, path)` OR `(name, kind, path, marker_label)` — optional 4th overrides the default
  `→ {kind}` tick. Full Kabsch per frame keeps internal field deflection visible (only rigid tumbling is
  removed), so field1 vs field2 look different.
- **Recursive delete cascade:** `delete_oxdna_job` collects the full descendant subtree (any depth), not
  just direct children; `n_children` now = total descendants.
- **Frontend nesting:** `groupJobsByParent` → **`flattenJobTree(jobs)`** (pre-order DFS, depth + GLOBAL
  run-number index) renders the list nested to any depth with depth-indent; **`descendantIds`** drives the
  delete-cascade warning count; `deleteConfirmMessage` gained a child-with-branches variant. Production
  "Run" button already targets `_selectedId` + is enabled for any completed job, so selecting a chained
  child and running works once it renders.
- Tests: backend +2 (`test_oxdna_trajectory_walks_full_lineage`, `test_delete_cascades_through_a_chained_lineage`),
  `test_headless_oxdna_build.py::test_multiple_field_children_from_one_parent` flipped (chaining now
  allowed → asserts grandchild seeds off the child); frontend `flattenJobTree`/`descendantIds`/
  deleteConfirm tests. `just test` 2822 passed / 55 skipped; `just test-frontend` 1531; vite build clean.
- **NOT hand-verified in app** (needs real chained GPU runs) → `manual_validation_debt.md` **MV-OXCHAIN** (PENDING).

**Files:** `oxdna_protocol.py` (name param), `routes_oxdna.py` (continue-prod naming, /rmsf multi-traj,
/trajectory route), `oxdna_health.py` (production_rmsf list + composite_trajectory), `client.js`
(getOxdnaTrajectory), `oxdna_display.js` (trajectory mode), `oxdna_trajectory_player.js` (new), `index.html`
(traj toggle+controls), `oxdna_jobs_panel.js` (wiring + productionState/Count/hasTrajectory), tests.

---

## UPDATE 2026-06-17 — resume killed jobs (continue-from-checkpoint) + flexibility map available mid-run with a confidence metric

Two user requests. **(1)** A killed/incomplete oxDNA job must be detectable + resumable. **(2)** The
flexibility map (RMSF) should be toggle-able at ANY point after a production run has STARTED (not only
once it finishes), but show a confidence metric so a short run isn't trusted.

**Most of the resume machinery already existed** (see §24.1 / UPDATE 2026-06-16c): `reconcile_oxdna_status`
already flips a detached `running` job to `stopped` (with `_external_oxdna_running` /proc guard to avoid
mislabelling a live orphan), `POST /oxdna/jobs/{id}/start` already resumes `stopped`/`failed`/`queued` jobs,
and the panel already shows `#oxdna-jobs-start-btn` for those states. The gaps were: the button always read
"Start", and resuming **restarted the interrupted stage from scratch** (previous stage's last_conf).

**1. Resume = continue from the killed stage's OWN checkpoint (user choice).** Extracted pure
`oxdna_runner._starting_conf(job, ws, specs, idx, start_idx)` from the inline conf-selection in `run_job`:
when resuming the interrupted stage (`idx == start_idx`) and that stage already wrote a **non-empty
`last_conf.dat`** of its own, the run continues from THAT checkpoint (simulated progress kept) instead of
re-running the stage from the relaxed frame. oxDNA reads conf then overwrites last_conf at the same path —
fine for the real binary (the mock's `shutil.copy` would `SameFileError`, so the test pins the pure
selector, not a mock run). Empty/missing checkpoint → falls back to previous-stage last_conf (idx>0) or the
design conf (idx 0). NOTE: the pre-kill **trajectory frames** of that stage are overwritten by the resumed
run (only the *state* is preserved, not the partial samples) — acceptable; the confidence metric reflects
whatever frames exist.

**2. Resume button label.** Pure `isResumable(job)` (`stopped`/`failed`) + `startButtonLabel(job)`
(→ `▶ Start` for queued, `↻ Resume` for stopped/failed); `_renderDetail` sets `startBtn.textContent`.

**3. Flexibility map available mid-run.** `/oxdna/jobs/{id}/rmsf` no longer requires a `done` production
stage — it pools `trajectory.dat` from production stages in (`done`, `running`) that have written frames.
Reasons: `no production run yet` (no production stage) / `production starting — no frames yet` (stage but
no trajectory). **Supersedes §24.2's "Ready only once a production stage has finished" gate.** Panel:
`_updateButtons` flex `ok = ps === 'done' || ps === 'running'`; the toggle change-handler allows `running`.

**4. Confidence metric (Frames + statistical SE — user choice).** New pure
`oxdna_health.rmsf_confidence(n_frames)` → `{n_frames, rel_error = 1/√(2·N), preliminary = N < RMSF_PRELIM_FRAMES (50)}`
(relative SE of an RMS/STD estimator; treats frames as independent = an optimistic LOWER bound since MD
frames are autocorrelated). The `/rmsf` route merges `confidence` + `production_running`. `oxdna_display.displayRmsf`
passes `nFrames`/`confidence`/`running` through; pure `oxdna_jobs_panel.flexConfidenceText(r)` →
`"N frames pooled · est. RMSF error ±X% · ⚠ Preliminary — production still running / short run"`. Mid-run
map isn't auto-refreshed each poll (expensive Kabsch-per-frame) — re-toggle to update.

**5. Robustness:** `read_trajectory_frames_full` now skips a half-flushed numeric line (try/except around
the float parse) so a mid-write trajectory read during a live run doesn't crash.

**Tests (backend 2431 / frontend 1312, both green; ruff clean, vite build OK):** backend +3
(`test_starting_conf_resumes_from_own_checkpoint`, `test_oxdna_rmsf_available_mid_run_with_confidence`,
`test_rmsf_confidence_metric`); the old `test_oxdna_rmsf_waiting_for_production` → renamed
`test_oxdna_rmsf_gating_before_frames` (new reasons). Frontend: resume-label + `flexConfidenceText` pure
tests, a stopped-job "Resume" factory test, a mid-run flex-unlock + preliminary factory test, and display
confidence-passthrough. **NOT hand-checked in app** → `manual_validation_debt.md` **MV-OXRESUME** (PENDING):
the live kill→Resume-from-checkpoint gesture + the on-screen preliminary readout during a running production.

**Files:** `oxdna_runner.py` (+`_starting_conf`, run_job uses it), `oxdna_health.py` (+`rmsf_confidence`,
`RMSF_PRELIM_FRAMES`), `routes_oxdna.py` (/rmsf mid-run gate + confidence), `oxdna_interface.py`
(read_trajectory_frames_full guard), `oxdna_display.js` (displayRmsf passthrough), `oxdna_jobs_panel.js`
(+`isResumable`/`startButtonLabel`/`flexConfidenceText`, button label, flex gating + confidence status),
tests. No `main.js` change (no new wiring).

### Follow-up 2026-06-17 — resume no longer truncates the partial trajectory + "Resuming" label

User resumed a real 18hb2 production (`eb35207d57ab`, stage `5_production`) and the bar reset to 0. Checked
on disk: the resume was CORRECT — `5_production/input.txt` had `conf_file = …/5_production/last_conf.dat`
(continuing from the 01:45 checkpoint, energy starting at the relaxed U≈−1.465, not ideal geometry), so the
relaxation + `4_production` were untouched and the simulated *state* carried forward. TWO real issues
surfaced: (a) the bar reset reads as a restart because each resumed run writes a FRESH `energy.dat`
(progress = energy-lines/expected for THIS run; note `restart_step_counter=true` + full `steps` means the
resumed run re-runs the stage's full step budget from the checkpoint — a longer trajectory, physically
fine); (b) the killed run's `5_production/trajectory.dat` was **truncated to 0** the instant the resumed
oxDNA reopened it (oxDNA opens trajectory/energy in truncate mode) — those sampled frames were lost (the
relaxation + `4_production` trajectories were safe; only the interrupted stage's partial frames).

Both fixed:
- **Archive partial outputs on resume.** `oxdna_runner._archive_partial_outputs(stage_dir)` renames the
  stage's `trajectory.dat`/`energy.dat` → `…r1.dat` (r2, … next free index) BEFORE the resumed run starts
  (run_job calls it when `_starting_conf` returns the own checkpoint). `last_conf.dat` is left untouched (it
  IS the checkpoint the run reads). The RMSF + composite-trajectory readers now gather ALL parts via
  `routes_oxdna._stage_trajectories(stage_dir)` (archived parts oldest→newest, then the live `trajectory.dat`,
  empties skipped) — so resumed runs pool every frame into the flexibility map and scrub in time order. NOTE:
  this only helps FUTURE resumes; the 18hb2 run already lost its partial frames before the fix.
- **`OxdnaStageStatus.resumed` flag** (default False, `setdefault`-safe for old job.json) set by run_job on
  resume; pure `oxdna_jobs_panel.resumeNote(job)` → "Resuming from checkpoint" prefixed onto the progress
  label for the running resumed stage, so the reset bar reads as continuing, not restarting.

Tests (backend 2433 / frontend 1314, green; ruff clean, vite build OK): backend +2
(`test_archive_partial_outputs_preserves_frames`, `test_stage_trajectories_chronological_order`); the mid-run
rmsf route test extended to assert an archived `trajectory.r1.dat` is pooled (2 archived + 3 current = 5
frames). Frontend +2 (`resumeNote` pure + a resumed-running-production progress-label factory test). Files:
`oxdna_runner.py` (+`_archive_partial_outputs`, run_job archives + sets resumed), `oxdna_job.py`
(+`resumed` field), `routes_oxdna.py` (+`_stage_trajectories`, /rmsf + /trajectory use it),
`oxdna_jobs_panel.js` (+`resumeNote`, progress label), tests. MV-OXRESUME (live kill→resume gesture) still
owes a hand-check.

---

## UPDATE 2026-06-18 — cadnano-import "blow up" diagnosed; 3 size/import fixes

User: imported cadnano structures (e.g. `workspace/VoltronCore.nadoc`, 59 helices SQUARE, 14,774 nt,
134 skips, 666 crossovers) "blow up" in oxDNA; its current job had just FAILED at equil. Investigated the
running job `oxdna_jobs/b43c17a757dd`.

**Verdict: the run was NOT broken/exploding.** Sequences complementary (6954/6954 WC pairs), traps correct,
geometry orientation a1·a1=−1, ONE connected component (crossovers present), energy bounded (−1.34→−1.37),
89% of pairs reached bonding distance after MD-relax, Rg preserved (20.6→21.8 nm, +6%). The visible "blow
up" = a thin floppy slab (extent 47×12×76 nm) **buckling** (Y 12→46 nm) while staying internally intact —
physics, not a melt. Three real defects found, all size/import-specific because the protocol was only ever
validated on the tiny 6hb (~500 nt / 30 nm):

1. **Equil FAILURE = oxDNA's I/O safety valve, not physics.** Large structures write ~4 MB trajectory
   frames; the rate exceeded oxDNA's default `max_io=1` MB/s → self-abort (`rc=1`, energy was fine at
   −1.37). FIX: `render_stage_input` now emits `max_io = 1000.0` for EVERY stage (oxdna_protocol.py).
   Covers mc/md_relax/equil/production/field (all render through that one fn).

2. **`n_nucleotides` mis-counted 33,716 vs real 14,774.** routes_oxdna.py set it to `len(geometry)`, but
   `_geometry_for_design` emits a slot for every position in each helix's full `length_bp` grid — and
   imported cadnano helices span the whole grid (18,942 EMPTY lattice slots here). Harmless to the run
   (conf is keyed by strand order) but mis-reports scale/ETA. FIX: `n_nucleotides =
   len(_strand_nucleotide_order(design))`. Also patched the existing failed job's job.json in place.

3. **Skips were NOT compacted in geometry → 268 backbone bonds stretched to 1.30 nm** (2× normal 0.67 nm,
   past oxDNA's FENE divergence ~0.85 nm) at the 134 skips. User's instinct ("never integrated skips/loops")
   was HALF right: skips ARE excluded from topology AND geometry correctly (the miscount is NOT skips — it's
   empty lattice), but `geometry.py nucleotide_positions` intentionally LEAVES A GAP at each skip (Dietz
   et al. 2009 gap model) — fine for rendering/the loop-skip bend system, a stretched bond for oxDNA.
   FIX (user-approved: **oxDNA path only, compress rise + twist**): added `compact_skips=False` flag to
   `nucleotide_positions` → `nucleotide_positions_arrays` → `deformed_nucleotide_arrays` →
   `_geometry_for_helices`/`_geometry_for_design`; oxDNA route calls `_geometry_for_design(compact_skips=True)`.
   A running `eff_i` counter doesn't advance on a skip, so flanking nucs sit one normal bp apart in BOTH
   rise and twist. Default False → rendering byte-identical. Cluster transforms preserved (cluster-only +
   no-deformation paths transform the compacted `arrs` rigidly; the rare bend/twist-deformation path
   recomputes from bp_index and would lose compaction — graceful degradation, no such design here).
   Verified on VoltronCore: skip-jump bonds 1.296→0.670 nm, keys + cluster transforms intact.

   NOTE: this design has 0 LOOPS (insertions), so the loop-copy compaction path is unexercised; loops still
   bulge (eff advances by 1 per loop column, unchanged). `write_configuration`'s `_compute_nuc_geometry`
   FALLBACK (only hit for keys missing from geo_map) is NOT skip-compacted — fine because compacted
   geometry covers all strand keys. **[SUPERSEDED 2026-07-02 for LOOPS + BENT bundles — see §"Loops in
   oxDNA".]**

**NOT yet addressed (separate from the 3 fixes):** MC/MD step counts are FIXED, not scaled to N — 1000 MC
steps ≈ 0.07 moves/particle on 14.7k nt (a near-no-op; MC extent stayed 47×12×76 flat, then MD popped). The
buckling driver. Candidate next item if large-import shape preservation matters.

Tests: backend +4 (`test_render_raises_io_rate_limit`, `test_oxdna_create_counts_strand_nucleotides_not_lattice`,
`test_skip_leaves_axial_gap_by_default`, `test_compact_skips_closes_axial_gap`). Full suite **2595 passed**,
55 skipped; ruff clean. Files: `oxdna_protocol.py`, `routes_oxdna.py`, `core/geometry.py`,
`core/deformation.py`, `core/design_geometry.py`, `tests/test_oxdna_relaxation.py`, `tests/test_loop_skip.py`.
Existing failed job needs a fresh Relax to benefit (input files are written at prepare time).

### Follow-up 2026-06-18 — #4 (scale steps to N) is NOT warranted; large-structure tests added

Re-examined the "MC is a near-no-op at scale" claim (the proposed #4 fix) and it was WRONG. oxDNA MC does
**N moves per step (a sweep per step)**, not 1: the VoltronCore MC ran 1000 steps in 297 s of
Rotations+Translations for 14,774 particles → ~20 µs/move only if it's 1000×14774 moves (sweeps); at 1
move/step it would be 0.3 s/move (absurd). So 1000 MC steps ≈ 1000 sweeps/particle — substantial (it formed
83% of pairs), and step counts do NOT need to scale with system size (MD steps are time-integration, also
N-independent). **#4 dropped** — it would only slow large jobs with no benefit. The buckling is legitimate
MD equilibration of a thin floppy slab (Rg preserved), not a bug. No remaining fixes beyond 1–3.

Added large-structure (imported-cadnano-scale) validation tests in `test_oxdna_relaxation.py`, all on an
18-helix bundle (~14k nt, VoltronCore-scale) rather than the tiny 6hb:
- `test_large_structure_skip_compaction_no_fene_violation` — with skips peppered down every helix, EVERY
  intra-helix backbone bond (incl. skip-spanning) stays < oxDNA FENE divergence (0.854 nm) when compacted;
  asserts the DEFAULT (uncompacted) DOES violate FENE at ~one bond per skip (proves the test bites).
- `test_large_structure_oxdna_files_self_consistent` — with inflated empty-lattice tails + skips, topology
  N == conf data lines == strand-order count, and geometry slots (> order) don't leak into the run.
Full suite **2597 passed**, 55 skipped, ruff clean.

---

## UPDATE 2026-06-19 — clicking a job repopulates EVERY card with that run's conditions
Before, selecting a job only refreshed status/progress/health; the Advanced / Hard surface / Anchors /
E-field cards kept whatever the user last typed, so a past run's settings (and its anchors + field
direction) weren't shown. Fix: **persist + echo the run conditions.**
- **Backend:** `OxdnaJob` gained `run_config: dict|None` (persisted in job.json, `load()` setdefaults None
  for old jobs). `routes_oxdna.create_oxdna_job` stores `{kind:"relax", backend, device,
  salt_concentration, mc/md_relax/equil_steps, min_bp_retained, surface, anchors}`; the `/run` + `/field`
  routes store `{kind:"run"|"field", steps, field, surface, anchors}` on the child. **Anchor descriptors
  saved camelCase** (`model_dump(by_alias=True, exclude_none=True)`) so the Anchors card re-renders chips
  verbatim.
- **Frontend:** pure `runConfigForJob(job)` in `oxdna_jobs_panel.js` normalizes job→`{advanced, field,
  surface, anchors, prodSteps}` (advanced=null for a field/run child; falls back to stage steps + the
  `efield` record for jobs saved before run_config). `_applyRunControls(job)` fires **only on an explicit
  row click** (never on a status poll → no mid-edit clobber): sets the panel's own Advanced/prod inputs,
  then calls the new `applyRunConfig` dep. main.js distributes via new `applyConfig(...)` methods on
  `efield_setup` (`{open:true}` reveals the direction arrow), `oxdna_floor_setup` (`axisForNormal` inverts
  the stored normal → axis dropdown), `oxdna_anchors_setup` (replaces chips; onChange→purple anchor glow
  shows a field run's pinned strands in 3D). Field child auto-opens the E-field card so the arrow shows.
- Tests: backend `test_run_config_roundtrip` + `test_run_config_persisted_for_panel_cards`; frontend
  `runConfigForJob` (4), `axisForNormal` (3), `applyConfig` on all three setup modules. Full backend 2806
  passed; frontend 1519 passed; vite build + ruff clean. main.js +6 (pure wiring). Live click-to-repopulate
  gesture not hand-checked in-app → MV-OXDNA-CONFIG.

---

## 26. UPDATE 2026-06-19 — equil-readiness fix (VoltronCore equil FENE crash)

**Symptom.** A VoltronCore relax (14,774 nt, hard surface + 64 anchor traps) cleared MC + MD-relax then
the **equil stage aborted at config load**: `ERROR: Distance between bonded neighbors 4857 and 4858 exceeds
acceptable values (d = 1.023805)`. job `175dcf0ba36b`.

**Root cause (calibrated against oxDNA's own report).** oxDNA's backbone is a FENE spring between the
BACKBONE SITES of consecutive nucleotides; it is defined only out to `r0+delta ≈ 1.006` units, beyond which
oxDNA fatally aborts. The relax stages cap the backbone force (`max_backbone_force=5`) so an over-stretched
bond is held by a finite linear spring — masking it. The equil stage REMOVED the cap (bare FENE) and ran
`refresh_vel=true`; md_relax had left ONE bond at **1.024 units** (just over the cliff), and the first
velocity kick tipped it past → abort before a step ran. Site-based metric nails it (max 1.024, exactly 1
bond over the cliff = oxDNA's abort bond); the CM–CM distance metric mis-reads it (median 0.54, "880 over")
because the CM sits ~0.34 units inward of the real backbone — **use the SITE distance for FENE checks**.

**Fix (3 parts, all backend; oxDNA output still Physical-layer only):**
1. **Capped equil (`oxdna_protocol.py`).** Equil now keeps a LARGE cap (`DEFAULT_EQUIL_BACKBONE_FORCE=50/
   far=100`) instead of `None`. Transparent to a healthy bond (its FENE force near equilibrium is ≪50, so
   the cap never engages — physically identical equil), but replaces the divergence with a finite spring for
   a residual over-stretch → never a fatal abort. This alone would have prevented the crash.
2. **FENE-readiness metric + gate (`oxdna_health.py`).** New `backbone_fene_stretch(design, full_map)` →
   (max backbone-SITE bond in oxDNA units, count over `FENE_RMAX_UNITS≈1.006`). `run_oxdna_health_check`
   sets `res.fene_safe = max < FENE_SAFE_MAX_UNITS (0.98)` (0.98 = cliff minus a velocity-kick margin) and
   notes it in the reason. Advisory — drives the retry, does NOT set `passed` (a capped equil tolerates a
   residual over-stretch). New `OxdnaHealthResult` fields `max_backbone_fene_units / n_fene_over / fene_safe`;
   `OxdnaHealthSample.max_backbone_fene` surfaces it.
3. **Escalate-and-retry (`oxdna_runner.py`).** When md_relax passes its bp gate but is NOT equil-ready (or a
   later stage rc-crashes), the runner re-runs the md_relax stage with ESCALATED params and rewinds to it —
   `escalate_md_relax_spec(base, attempt)`: steps ×{3,6,10}, dt→0.001, cap→{20,50,100}/×2. **Escalation, not
   just "longer": the over-stretch is a stable strained plateau (energy had flatlined at −1.34), so the
   higher force cap is what pulls the stuck bond back within FENE range.** Budget = `OxdnaJob.max_relax_retries`
   (default 3; route field `max_relax_retries` 0–5). After the budget is spent still-not-ready → job FAILED
   with a FENE diagnostic ("relax without the surface/anchor traps, lower dt, or simplify geometry").
   `relax_retries` counts spent escalations; escalation re-persists `stages_spec.json` (restart-safe) and
   clears the relax + downstream stage dirs so the re-run is fresh (not a checkpoint resume).
   `base_relax_spec` is captured pristine so escalation never compounds.

**Headless path defaults `max_relax_retries=0`** (`headless_oxdna_build.create_job`) — deterministic short
validation runs (mock copies the unrelaxed conf → never equil-ready) would otherwise spin to exhaustion; the
capped equil still completes them. The `?` route + Dynamics panel default to 3 (no UI change — panel POST
omits the field).

**Why this addresses the root cause (vs the user's "just rerun longer" worry):** rerunning identical params
lands in the same plateau; the escalation's higher cap + smaller dt is what resolves the stuck bond, and the
capped equil is the backstop so a borderline bond never crashes a run that IS otherwise relaxed.

**Tests (backend 2817 passed, +6 net, ruff clean):** `test_escalate_md_relax_spec_schedule`,
`test_backbone_fene_stretch_is_site_based`, `test_health_check_flags_not_equil_ready`,
`test_runner_retries_then_fails_when_not_equil_ready` (escalate+rewind+persist+fail); updated
`test_stage_specs_shape` + `test_render_equil_has_large_force_cap` (equil cap now 50/100); orchestration +
real-binary lifecycle + http-lifecycle pins set `max_relax_retries=0` (they validate the status machine on
intentionally under-relaxed structures). **NOT live-verified on a real VoltronCore GPU re-run → owes an
MV row** (click Relax on VoltronCore, watch it auto-escalate/complete instead of crashing at equil).

## 27. UPDATE 2026-06-19 — OxDNA display follows a RUNNING job + next-frame countdown

The "OxDNA display" toggle used to fetch the latest relaxed frame ONCE and freeze until the job hit
`completed` (the re-fetch in `_fetchJobs` was gated on `sel.status === 'completed'`). User asked: while the
toggle is on, show an estimate until the next frame update. Now the relaxed display **follows the run live**:

- **Backend** `job_progress` (oxdna_runner.py) returns two new fields while a stage runs: `frame_index`
  (which trajectory/last_conf frame is current = `steps_done // print_conf_interval`) and
  `next_frame_eta_seconds` (steps-to-next-frame ÷ the current stage's live rate, clamped to the stage tail).
  New protocol helper `print_conf_interval(spec)` = `max(1, steps//10)` (~10 frames/stage), now the single
  source of the cadence — `render_stage_input` uses it too (was a duplicated local).
- **Frontend** (oxdna_jobs_panel.js): while the relaxed display is active and the selected job is `running`,
  `_fetchJobs` re-fetches the display only when `frame_index` advances (cheap — no redundant Kabsch per
  1.5 s poll), otherwise just ticks the countdown. `_refreshDisplay` stores the base status text + the frame
  it synced to (`_lastFrameIndex`); `_renderDisplayStatus` appends "· next frame ~Xs" (formatEta) while
  running. Works for production / E-field child runs too. `_setDisplayOff` + tab-leave clear the follow.
- Tests: `test_print_conf_interval`, `test_job_progress_next_frame_eta` (frame_index + eta from live rate).
  Backend suite 2820 passed / 55 skipped; frontend oxdna panels 91 passed; vite build OK.
- Live gesture (model stepping frame-to-frame mid-run + the countdown ticking) is human-eye only → **MV-OXLIVE**
  PENDING in `manual_validation_debt.md`.


## 28. UPDATE 2026-06-20 — live solvation progress bar + ETA + hang detection for NAMD-seed prep

User pain: "Use as NAMD seed" (and the MD Relax button) fired one **blocking** `POST /md/jobs` that ran the
whole preparation (seed atomic-model reconstruct → topology → `gmx editconf/solvate` → ion placement →
PSF/PDB string build → Aksimentiev ENM → configs) before returning a `job_id`. The UI could only show an
indeterminate "Solvating…" spinner — no ETA, no way to tell a slow run from a hung one.

**Core restructure:** `create_md_job` now returns immediately with `status=preparing` + `job_id`; prep runs
in a fire-and-forget `asyncio` task (`_prepare_job_bg`, refs held in `_PREP_TASKS`). Engine checks + the
non-seeded sequence check stay synchronous (still 400 on failure); the active design is captured on the
request thread (doc-session contextvar), but seed-build + the seeded sequence check move into the bg worker
(an unsequenced/missing seed now fails the *job*, not the POST). The existing `/ws/md-jobs/{job_id}` socket
(already auto-selected for `preparing` jobs) streams the progress every 1 s while preparing.

**Progress model** — new tested module `backend/core/md_prep_progress.py`:
- `PrepTracker(phases, clock)` — thread-safe weighted-progress + self-calibrating ETA. `report(key, frac,
  msg)` from the worker thread (frac=None = "entered an opaque phase, time-fill it"); `snapshot()` from the
  event loop. Overall fraction = nominal-duration-weighted; ETA = `speed_factor × remaining_nominal` where
  `speed_factor = actual/nominal` over completed phases (so a slow machine still gets an honest countdown).
  A phase past `soft_factor × nominal` sets a non-fatal `warning` ("…may be stalled").
- `build_prep_phases(seeded, size_factor)` — phase catalogue (seed?/topology/solvate/assemble/enm/finalize),
  nominal seconds scaled by `design_size_factor` (≈ nt/7000).
- Sidecar `{job_dir}/prep_progress.json` (`write/read/clear_prep_progress`) — separate from job.json so 1 Hz
  writes never race the job's own writes. A 1 Hz heartbeat task persists `snapshot()`; ws attaches it as
  `payload["prep_progress"]` while `status==preparing`. `MdJob.save` made atomic (temp+rename) for the same
  reason.

**Instrumentation (all via optional `progress=None` kwarg — fully back-compatible):** `progress(phase_key,
frac|None, msg)` threaded through `prepare_mgh_slow_release`/`_equilibrium_aware` → `build_namd_solvated_
package` (topology/solvate emits + assemble emits) → `_gmx_solvate` → `_parse_gro` / `_extend_psf` /
`_build_solvated_pdb` (loop-fraction reports) and `write_aksimentiev_enm_files`.

**Hang policy (user chose warn-then-hard-kill):** new `_run_watched(cmd, hard_timeout_s)` in namd_solvate
replaces `subprocess.run` for the gmx steps — Popen + 2 s poll; on overrun it kills the process and raises
("GROMACS step exceeded Ns … likely hung") → job marked `failed` with the message. `hard_timeout =
max(600, n_dna_atoms × 0.05)` s (generous; only catches a truly stuck process). Python loops can't be killed
but report continuous progress, so a real stall shows as a frozen bar + the soft warning.

**Frontend** (`md_jobs_panel.js`): `_renderProgress` branches on `status==='preparing'` to a new
`_renderPrepProgress(job)` driven by `job.prep_progress` — phase message, determinate %-fill, `_fmtEta`
"~Xm Ys left", "Step i of N · <label>", and an amber warning row. Relax POST is now fast so its modal copy
changed to "Creating job…"; the inline detail bar (fed by the ws) carries the real solvation progress. Seed
button unchanged (already reveals MD panel, which auto-selects the preparing job).

**`_gmx_solvate_periodic` (periodic-cell path) left un-instrumented** — separate feature, not used by the
standard prep.

- A bad `oxdna_job_id` still 400s fast: new cheap `oxdna_runner.assert_namd_seed_available` (job + snapshot +
  relaxed-conf existence, no reconstruction) runs synchronously in the route; only the slow build is deferred.
- Tests: `test_md_prep_progress.py` (17 — tracker fraction/ETA/warning/fail + sidecar) + `test_md_prep_
  wiring.py` (5 — progress threaded through solvation w/ gmx stubbed; `_run_watched` kills a hung proc).
  Full backend suite green (2844 passed / 55 skipped); frontend md+oxdna panels 87 passed.
- **NOT VERIFIED IN APP** (no GROMACS/NAMD + running app exercised this session) — live solvation bar/ETA/
  stall-warning behavior is a human-eye gesture → should become an MV item.


### §28b UPDATE 2026-06-20 — MD-panel cards + seed-didn't-populate fix + orphaned-preparing reconcile

User report: seeding from oxDNA "did not populate the MD jobs". Root causes + fixes:
1. **Seed job not refreshed when MD panel already open.** `oxdna_jobs_panel._revealMdPanel` only triggers a
   fetch on a collapse→expand of the MD panel; if it was already expanded the new `preparing` job never
   appeared. Fix: the seed handler now also `dispatchEvent('nadoc:md-job-created', {jobId})`; `md_jobs_panel`
   listens → `_fetchJobs()` + `_selectJob(jobId)` (selection uses the UNfiltered `_jobs`, so the detail/bar
   shows even if part-filtering would hide the list row).
2. **Orphaned `preparing` jobs hung forever.** Backgrounded prep means a job persisted as `preparing` is
   stranded if its task dies (dev-server reload, OOM during a huge solvation). New `namd_runner.
   _reconcile_preparing` (called from `reconcile_job_status`, which the list route + status ws already invoke):
   if the `prep_progress.json` heartbeat sidecar is missing or its mtime is older than `_PREP_STALE_S = 30 s`,
   the job flips to `failed` with "Preparation was interrupted…". A live prep (1 Hz heartbeat) stays fresh and
   is left alone. Tests: `TestReconcilePreparing` (stale→failed, missing→failed, fresh→preparing).
3. **VoltronCore seedability CONFIRMED.** Both `workspace/VoltronCore.nadoc` oxDNA runs are seedable —
   incl. the **production** run `7c0ffd3177c7` (uses `1_production/last_conf.dat`) and the equil run
   `e5a94ebe5032` (`3_equil/last_conf.dat`); `assert_namd_seed_available` passes for both. The user's seed DID
   create job `b10182b580de` (name resolved to "VoltronCore" → `build_namd_seed` succeeded) but it stuck at
   `preparing` — VoltronCore is 14,774 nt, so explicit-solvent prep is a multi-million-atom build that likely
   OOM'd or was cut by a server reload. The reconcile above now surfaces that as `failed` instead of a hang.

**MD panel UI restructure** (mirrors the oxDNA panel's `ox-card` pattern): run controls (Protocol + Relax/
Start-Production + production box + Display) stay at top; below them the **Benchmark** (already a self-rendered
`bench-card`), a new collapsible **Jobs** `ox-card` (show-all + list; starts open, `md-jobs-list-toggle`), and
**Advanced** converted from a bare ▶ disclosure to an `ox-card` (`md-jobs-adv-*` IDs unchanged so the existing
toggle JS still works). Job detail stays below the Jobs card. Tests: md+oxdna+benchmark panels 95 passed.
NOTE: a **pre-existing** test-isolation bug makes `test_md_milestone1.py` pollute `test_oxdna_relaxation.py`
(`include_router` `'function' object is not iterable`) when run as a 2-file subset — reproduced with all my
changes `git stash`'d, so NOT mine; the full suite passes (alphabetical ordering avoids it). → **MV-SOLVPREP**
extended to cover the new cards + the seed-populate gesture.


### §28c UPDATE 2026-06-20 — solvation hang ROOT-CAUSED + fixed (quadratic MgH ion placement)

The VoltronCore NAMD-seed prep "appeared hung" (`equilibrium_aware_namd` protocol). Live forensics on the
running worker (no py-spy; used `/proc/<tid>/stat` run-states + `prep_progress.json` deltas + `ps`): the worker
thread was `R` (running) at ~200% CPU, RSS 1.8 GB — **not** deadlocked. `gmx solvate` had finished (212 MB
`solvated.gro`, ~1.5 M waters); the bar was frozen in `assemble` / "Placing neutralising ions…" with no
movement for 95+ s.

**Root cause:** `namd_solvate._place_ions_mixed_mgh` was quadratic. Its `pop_random()` did
`rng.choice(tuple(available))` — rebuilding a `tuple` of the ENTIRE (~1.5 M) available-water set on **every**
ion, and VoltronCore needs ~15 k neutralising Na⁺ → ~15 k × 1.5 M ≈ 2×10¹⁰ element copies; plus a full
`sorted(available, key=…)` over all waters per Mg cluster. Tens of minutes, zero progress feedback. Only the
MgH path (which `equilibrium_aware`/`mgh_slow_release` always use) hit this; plain-NaCl `_place_ions` already
used `rng.sample`. Never bit before because earlier seeds were tiny (6hb, 3x6Sq); VoltronCore (14,774 nt) is
the first big enough to expose it.

**Fix:** rewrote `_place_ions_mixed_mgh` to ~O(n_ions·log n_water) — build one `cKDTree` over water O
positions, one `rng.shuffle`'d draw order + a `bytearray` claimed-flag (no giant tuples). Each Mg cluster takes
the next unclaimed water as center + its 5 nearest unclaimed neighbours via one KDTree query (top-up from the
shuffle order if the local cloud is crowded → still exactly 6 waters/cluster); Na⁺/Cl⁻ then take the next
unclaimed sites. Idealized `_ideal_mgh_cluster` geometry unchanged (the 5 neighbours are only *vacated*, never
rendered — so the new selection is behaviour-equivalent, just fast). Threaded `progress` through
`_place_ions_mixed` → `_mgh` so the bar moves during placement (fixes the silent freeze). At a 64 k-water /
6.3 k-ion scale the new path is <1 s (was minutes). Tests: `test_md_ion_placement.py` (8 — counts, exactly-6
waters/cluster, disjoint sites, determinism, zero-mg, too-few-waters raise, progress emitted, and a
`dt < 10 s` anti-quadratic guard at 64 k waters). The killed VoltronCore job was deleted; the user must
**restart `just dev`** (SIGKILL'ing the prep worker took the `--reload` parent down with it).
NOTE: explicit-solvent NAMD for a 14,774-nt origami is still a ~6–7 M-atom system — borderline for a single
GPU even with fast prep; the fix makes prep tractable but the run itself may be impractical.

## 29. UPDATE 2026-06-20 — display "Align to design pose" fix for CHILD jobs + settings reset on design switch

**Bug (user report + image):** a RUNNING production job (`6hb_sim_tests.nadoc`, a production
*child*) displayed its relaxed structure ~185 nm BELOW the design with "Align to design pose"
ON. Root cause: `get_oxdna_display` (and `get_oxdna_rmsf`) used the job's own `jd/conf.dat`
as the Kabsch reference. For a **child** job (production / non-anchor field run) `conf.dat` is
the PARENT's relaxed `last_conf` — the relaxation MD diffused it tens of nm off-origin — so
Kabsch superposed the structure onto that drifted point, not the design pose. (`/trajectory`
already dodged this via `_design_ref_conf`; only `/display` + `/rmsf` were still on `conf.dat`.)
Measured on the live job: OLD ref → aligned centroid `[32,-156,14]`; NEW ref → `[3.9,2.3,14]` =
exactly the design pose centroid.

**Fix (`routes_oxdna.py`):** `_design_ref_conf` is now THE alignment reference for every display
path (display / rmsf / trajectory / field). It regenerates a clean origin-frame
design-geometry config from the job's `design.json` snapshot, cached as `design_ref.dat`. Changed
it to `_geometry_for_design(design, compact_skips=True)` so it is byte-for-byte what
`prepare_oxdna_job` wrote into a ROOT job's `conf.dat` (deletions collapsed to one bp) → root-job
alignment is unchanged; only child jobs are corrected. `/rmsd` still references the *previous
stage's* last_conf on purpose (it measures internal deviation magnitude, Kabsch-invariant to the
absolute frame). Anchor/field branch unchanged (already used `_design_ref_conf`).

**Settings reset on design close/switch (frontend).** The MD + oxDNA panels echo a *selected
job's* run conditions into their inputs, so switching designs left the prior design's settings in
place. New shared pure helper `frontend/src/ui/form_defaults.js`
(`resetControlToDefault`/`resetControlsToDefaults`, 7 vitest tests) restores controls to their
index.html-authored defaults (input `defaultValue`, checkbox `defaultChecked`, select `selected`
option). Wired into BOTH panels' `nadoc:workspace-path-change` handler:
- oxDNA (`oxdna_jobs_panel.js`): `_resetControlsToDefaults()` resets backend/device/salt/mc/md/
  equil-steps/bp-gate/prod-steps, drops the `device.userSet` flag, calls `_clearRunCards()` (turns
  the E-field/hard-surface/anchor cards off via `applyRunConfig({field:null,surface:null,
  anchors:[]})`), and re-runs `_checkAvailable()` to re-apply the recommended device.
- NAMD (`md_jobs_panel.js`): `_resetControlsToDefaults()` resets preset/threads/devices/salt-mode/
  mg/nacl/padding/minsteps/autostart/prod-steps/prod-continue, clears `_threadsInit` + re-runs
  `_checkEngines()` (re-seed host-recommended threads) + `_applySaltMode()` (re-sync mg/nacl).

Tests: backend `just test` 2855 passed / 55 skipped; frontend 1543 passed (incl. new
`form_defaults.test.js` 7). main.js untouched (panels own the wiring). **NOT hand-verified in the
running app** — the alignment fix is confirmed numerically (centroid lands on the design pose) but
the live toggle gesture + the design-switch reset are unexercised in-browser → MV candidate.

---

## UPDATE 2026-06-20 (c) — oxDNA-NATIVE SEED: designed pairs start bonded (no startup collapse)

**Why.** The relaxation's early-stage "collapse/melt then recover" was a NADOC-seeding artifact, not
oxDNA behaviour. Root cause (confirmed empirically on 6hb + 18hb): NADOC writes the `.dat` position
(which oxDNA reads as the centre of mass) at the NADOC backbone position, at `HELIX_RADIUS=1.0 nm` →
paired backbones ~1.93 nm, **base (H-bond) sites ~1.25 nm apart — far outside oxDNA's ~0.34 nm bonding
range**, so a free MD forms zero designed pairs and the mutual traps have to drag every pair into
existence (the visible collapse). Measured frame-0 state of the old seed: **bp = 0.0** and **backbone
bonds OVER oxDNA's FENE cliff** (246 bonds on 6hb, 6 966 on 18hb past 1.006 units) — that over-stretch is
what was triggering the md_relax escalate-and-retry cycles.

**Fix (option 1, Physical-layer only).** New pure `oxdna_interface.oxdna_native_seed_map(design,
resolved_map)`: slides every nucleotide CM inward along its own base normal (a1) by a single uniform
`delta`, derived from THIS design's median designed-pair base-site separation, so the pairs land at
oxDNA's native bonding geometry (base sites ~0.37 nm, reconstructed backbone ~1.63 nm). Uniform shift
(paired AND unpaired alike) keeps every backbone bond length intact → no paired↔unpaired discontinuity →
it REMOVES the FENE over-stretch instead of adding any. a1/a3 untouched. `delta≈0.44 nm` for the
HC lattice; adapts automatically (SQ etc.). Verified frame-0: **bp 0.0→1.0, FENE over 246/6966→0,
cross-pair backbone 1.63 nm.**

This corrects the "minor known imperfection" flagged in §16/§18 ("we write the CM at the NADOC backbone
position rather than CM=backbone−site-offset; the relaxation + traps correct it") — the seed is now placed
at oxDNA equilibrium up front, so the relax/traps barely move the pairs (traps r0=1.2 units ≈ the seed's
1.04 nm CM–CM → basically a safety net now). Mutual traps / topology / health all unchanged.

**Wiring.** `write_configuration(..., oxdna_native_seed=False)` + `hybrid_configuration_text(...,
oxdna_native_seed=False)` gain the flag (default OFF so display/reference/export/benchmark configs keep raw
NADOC geometry — no test breakage). `oxdna_runner.prepare_oxdna_job` passes `oxdna_native_seed=True` for
BOTH the DNA-only and the DNANM hybrid seed. Only the actual relaxation **seed** (`conf.dat`) is native;
the Kabsch/display references and the manual-export ZIP are untouched (a possible future consistency pass —
native-seeding the export + `_design_ref_conf` too — is noted but not done).

**Expected effect on a real run:** bp starts ~1.0 instead of 0, no on-screen collapse, the md_relax
escalate-retry should stop firing on well-formed designs, and the ~5% terminal end-fraying should be
slightly reduced. The FINAL relaxed structure is unchanged (oxDNA's force field sets the endpoint) — only
the early transient is removed.

**Tests (backend 2858 / 55 skipped, ruff clean):** `tests/test_oxdna_relaxation.py` +3 —
`test_oxdna_native_seed_bonds_pairs_at_frame_zero` (the oracle: wide bp<0.05 & FENE over>0 vs native
bp>0.95 & FENE over=0), `test_oxdna_native_seed_preserves_orientation` (a1/a3 identical, CM moved >0.1 nm),
`test_oxdna_native_seed_map_noop_without_pairs`. `test_runner_retries_then_fails_when_not_equil_ready`
updated: it now overwrites `conf.dat` with the raw wide seed after prepare (the test needs an
over-stretched start the native seed no longer provides). Production path confirmed end-to-end:
`prepare_oxdna_job` conf.dat → frame-0 bp=1.0, FENE over=0.

**NOT yet live-verified on a real GPU relaxation** — the numeric oracle is conclusive (seed is bonded +
FENE-safe), but watching a real run start at bp~1.0 with no collapse is human-eye → owes an
`manual_validation_debt.md` row (MV-OXNATIVE) on the next real run.

**Files:** `oxdna_interface.py` (+`oxdna_native_seed_map`, `_POS_BASE_NM`, `OXDNA_NATIVE_HBOND_NM`,
`write_configuration` flag), `oxdna_protein.py` (`hybrid_configuration_text` flag), `oxdna_runner.py`
(prepare passes the flag), `test_oxdna_relaxation.py` (+3, 1 updated).

---

## UPDATE 2026-06-20 (d) — oxDNA→NAMD seed: diagnosed the blow-up + hardened reconstruction + ladder wiring

**Symptom (user, 6hb_sim_tests):** an oxDNA-seeded NAMD job "claimed temp = 0K until it failed." **Diagnosis:**
NOT a temperature bug — `temp 0` was the `minimize 4800` phase (NAMD reports TEMP≈0 during minimization). The
real failure: the from-seed path jumped to **unrestrained 310 K NPT** after a single minimize, and the seeded
all-atom structure was massively clashed → within ~200 dynamics steps atoms 9007/9013 (scaffold GUA) exceeded
the velocity limit → "atoms moving too fast" → FATAL. The solvated PDB had **58,802 DNA heavy-atom clashes
<2.0 Å, 9,310 sub-1.0 Å, some at 0.0 Å** (initial VDW 2.1×10¹⁰, "36,518 atoms with bad contacts").

**Root cause of the seed clashes = reconstruction frame corruption (not just the ~10% narrow duplex).**
`cg_to_atomistic` only overrode each nucleotide's BACKBONE position; `atomistic._atom_frame` then derived the
radial direction (hence helical phase) from `backbone − IDEAL-STRAIGHT-axis_point`. Once a helix bends/drifts
in the relaxed CG structure, the global displacement swamps the true radial → the ~34°/bp twist collapses →
adjacent nucleotides stack and atoms spill into neighbouring helices. Measured clash split: cross-strand
(duplex width) 5,195 · same-strand **adjacent 27,997** · **cross-helix 25,759** — dominated by frame
corruption, not duplex width.

### Fix A — deformed (curved) axis reconstruction
- `atomistic.build_atomistic_model(..., axis_override=None)` — optional per-`(helix,bp)` `(axis_point, tangent)`.
  When present, the placer measures the radial against the BENT centerline + local tangent (phase constants /
  ideal P-radius stay locked). Default None → byte-identical to before (PDB export etc. unaffected).
- `cg_to_atomistic.deformed_helix_axes(design, full_map, sigma)` — centerline = midpoint of the paired strands'
  CMs, interpolated across the helix, Gaussian-smoothed, differentiated for the tangent, sign-aligned to the
  helix axis (no FWD/REV flip), and **extrapolated to cover single-stranded overhang ends** (else they fall back
  to the straight axis and re-clash).
- `build_atomistic_model_from_cg_spline` now uses **RAW backbone sites** for `nuc_pos_override` (NOT smoothed) +
  the deformed axis. The earlier σ=2 smoothing of the per-nucleotide positions flattened the spiral and killed
  the twist (adjacent stacking) — the AXIS is what gets smoothed, not the per-nucleotide phase.
- **Result on the real 6hb_sim_tests seed (oxDNA job c1299e0b07b5): 58,951 → 6,301 clashes (~9×); cross-helix
  25,759 → 326, cross-strand 5,195 → 144, min distance 0.0 → 1.2 Å.** Residual is mostly floppy ss overhangs
  (ladder-relaxable); the dsDNA core twist/rise is correct (C1′–C1′ ~0.5–0.6 nm). A normal minimizable start.

### Fix B — seeded jobs run the restrained ladder (no more skip-to-production)
`routes_md._seed_production_available` now **always False**: the from-seed "minimize → unrestrained produce"
shortcut is removed. A seeded job runs the SAME restrained ENM ladder (00_min ENM k0.5 → 01–04 k0.5→k0.1→k0.01
→MGHH → release) starting from the seeded solvated PDB, then produces from a relaxation checkpoint like any job.
The seed's value is a better GLOBAL starting shape for that ladder, not skipping atomistic relaxation. Display
meta `production_from_seed` is gone; frontend `md_jobs_panel` start no longer shows the "relaxation can be
skipped" confirm. **Supersedes the §"Skip-relaxation → produce-from-seed" feature** (that assumption — "oxDNA
already relaxed it" — was false at the atomistic level).

**Tests (backend 2860 / frontend 1543, ruff clean, vite OK):** `test_cg_to_atomistic.py`
+`TestDeformedHelixAxes` (pure axis: covers all bps, unit tangents on centerline; + bent-6hb clash halving
oracle). `test_md_milestone1.py`: the two from-seed tests rewritten → a seeded job now 400s on production
without a checkpoint and is not production-ready (must relax first). 26 prior cg tests unchanged-green.

**NOT yet live-verified:** the clash oracle is conclusive and the ladder wiring is unit-pinned, but a real
seeded NAMD run on 6hb_sim_tests (relax ladder from the seed → completes without blowing up, then production)
is human-eye → `manual_validation_debt.md` **MV-OXSEED-NAMD** (PENDING). Feasibility verdict: the pipeline is
feasible WITH both fixes (deformed-axis seed + restrained ladder); the seed's benefit is design-dependent
(big/floppy/strained designs gain most).

**Files:** `atomistic.py` (+`axis_override`), `cg_to_atomistic.py` (+`deformed_helix_axes`, raw override),
`routes_md.py` (`_seed_production_available`→False, display meta), `md_jobs_panel.js` (drop skip-confirm),
`test_cg_to_atomistic.py` (+TestDeformedHelixAxes), `test_md_milestone1.py` (2 rewritten).

### Follow-up 2026-06-20 — seed recentered (PDB coord-field overflow → "No DNA base-ring atoms")

After the deformed-axis fix, a seed→NAMD run failed at ENM prep: *"No DNA base-ring atoms found for ENM
generation in …6hb_sim_tests.pdb"*. **Root cause:** oxDNA does NOT fix the centre of mass, so the relaxed
conf had COM-diffused to **Y ≈ -143 nm** (the whole structure intact but far from the origin). `build_namd_seed`
faithfully reproduced that absolute position → the exported PDB's **8-char coordinate fields overflowed**
(`-1488.600` = 9 chars), so `_parse_base_ring_residues`' fixed-width `line[30:38]` parse misaligned and every
base-ring atom failed `float()` → zero residues → `RuntimeError`. NOT a base-naming/reconstruction bug.

**Fix:** `build_namd_seed` now **recenters the model on the origin** (subtract the atom centroid) after building.
Absolute position is irrelevant for a boxed MD seed; recentering keeps coords in PDB's representable range
(real 6hb seed: max |coord| 1488 Å → 164 Å; ENM scan 0 → **1076** base-ring residues). Placed in
`build_namd_seed` (not the spline builder) so `build_atomistic_model_from_cg_spline` stays position-faithful
(its `TestSplineOverrideDrivesBackbonePositions` uniform-shift-propagation contract is preserved). Test:
`test_build_namd_seed_recenters_far_from_origin_conf` (stage a relaxed job, shove the conf +600 nm, assert the
seed model recenters to <100 nm and centroid ≈ 0). Backend 2861 / ruff clean.

**Files:** `oxdna_runner.py` (`build_namd_seed` recenter), `test_oxdna_relaxation.py` (+recenter test).

### Follow-up 2026-06-20 — orphan-job protections (PID persistence + stop-after-restart)

A `uvicorn --reload` (or any server restart/crash) kills the worker thread tracking a running
NAMD/oxDNA job; the subprocess survives, re-parented, and keeps writing output, but the in-memory
`_RUNNING`/`_ACTIVE_PIDS` registry is lost. Reconcile already KEEPS such a live orphan labelled
`running` (via the /proc scan) and recovers terminal status from disk — but the run was **un-stoppable**
after a restart (the PID was only in memory) and its live progress freezes (job.json stops updating).

**Hardened both runners (NAMD + oxDNA):**
- **PID now persisted to job.json** on every subprocess spawn — `_run_namd_async`/`_run_oxdna_async`
  gained an `on_spawn(pid)` callback; `run_job` passes a `_persist_pid` closure that writes
  `job.namd_pid`/`job.oxdna_pid` (cleared to None on process exit). Closes the §24.1 "PID still not
  persisted" caveat.
- **The /proc detectors now RETURN the PID** (`_external_pid` / `_external_oxdna_pid`, matching by stage
  conf / job dir in the command line — self-verifying, no PID-recycling risk); the old `_external_*_running`
  booleans delegate to them.
- **`stop_job` gained an ORPHAN fallback**: with no live runner thread, it loads the job, finds the
  detached PID (prefer the self-verifying /proc match; else the persisted `*_pid` re-checked live via
  `_pid_is_namd`/`_pid_is_oxdna` to guard a recycled PID), kills the process group, and marks the job
  `stopped` on disk — so a restarted server can still stop a runaway run from the UI.

**Still a known limitation (not fixed):** live progress/metrics do NOT resume for an orphan (the
parse/await thread can't re-attach to a process it didn't spawn) — the bar stays frozen until the
stage finishes and a reconcile promotes it. On a Linux-native host (no `--reload`) this only bites on a
real crash/restart, not on normal edits.

**Tests:** `test_md_milestone1.py::TestOrphanStop` (3) + `test_oxdna_relaxation.py` (3) — orphan stop via
/proc PID, persisted-PID fallback, and no-op when nothing to kill. Backend 2867 / ruff clean.

**Files:** `namd_runner.py`, `oxdna_runner.py` (PID persist + `_external_*_pid` + stop orphan fallback +
`_pid_is_*` guards), tests.

---

## Display toggles now drive atomistic + surface reps (2026-06-21)

The three oxDNA Dynamics-panel toggles (**OxDNA display** = relaxed frame, **Flexibility
map** = RMSF average, **View trajectory** = scrub) previously only deformed the CG
beads/slabs via `designRenderer.applyFemPositions`. They now ALSO reconstruct atomistic +
surface geometry when the scene is in a heavy rep.

- **Universal sink:** `oxdna_health.frame_atomistic_flat(design, frame)` /
  `frame_surface_json(design, frame, …)` — ONE per-nucleotide frame dict
  `{(hid,bp,dir):{backbone_position(CM), a1, a3}}` → `_frame_atomistic_overrides` →
  `build_atomistic_model(nuc_pos_override, axis_override)` (+ `compute_surface`). The
  composite-trajectory `composite_trajectory_atomistic/_surface` were refactored onto these
  (pure refactor, pinned). The relaxed `full_map` (from `_relaxed_full_map`, factored out of
  `GET /oxdna/jobs/{id}/display`) IS already this shape; `production_rmsf(...,
  include_average_frame=True)` now also emits an `average_frame` of the same shape (mean CM +
  mean a1/a3 — NOT the backbone-site mean, because the reconstruction re-derives the site).
- **Routes (all POST):** `display-atomistic`/`display-surface` (relaxed) +
  `rmsf-atomistic`/`rmsf-surface` (average). Trajectory `frames-atomistic`/`-surface` already
  existed (from the trajectory-keyframe feature).
- **Controller** (`ui/oxdna_display.js`): new deps `getAtomisticRenderer`/`getSurfaceRenderer`/
  `getCurrentRepr`/`onRestoreDesignHeavy`. `repKind(repr)` → 'atomistic'|'surface'|'cg'.
  `_applyHeavy()` (token-guarded) fires after each CG apply + on `nadoc:representation-change`
  (wired in main.js) so a freshly-built mesh re-overlays the current frame. Coarse/fine
  granularity (`setGranularity`): coarse = downsample bake (caps 40/20) + snap-to-nearest;
  fine = exact frame per scrub. Toggle-off bumps `_epoch`+`_heavyToken` → in-flight
  reconstruction bails; `onRestoreDesignHeavy` rebuilds design atomistic/surface. UI dropdown
  `#oxdna-jobs-heavy-granularity` + amber warning. MV row = **MV-OXREPS**.
- **STILL TODO (separate follow-up):** MD-job **surface** + the "Display MD = silent last-frame
  default, keep live stream when running" UX. MD atomistic already works live (ballstick
  stream); MD surface would need the validated `ws.py`/`md_panel` streaming path touched, so it
  was deliberately deferred.

**Bond-stretch artifact (fixed 2026-06-21):** the atomistic overlay drew long bonds across the
model because `build_atomistic_model` leaves un-overridden nucleotides (loop/insertion copies —
the override is `copy_k==0` + 3-tuple-keyed) at their DESIGN position while neighbours relax.
`atomistic_renderer.applyPositionLerp` now hides bonds longer than `_MAX_BOND_NM` (1.0 nm;
real DNA bonds ≤~0.2 nm). Display-layer fix; the deeper cure (make the override cover insertion
copies) is deferred. Same fix helps the trajectory-keyframe atomistic path.

**"Mesh of short wrong bonds" in atomistic display (fixed 2026-06-21):** diagnosed as NOT a
serial/bond-list/convention bug — `_frame_atomistic_overrides` fed the design's OWN geometry
reproduces `build_atomistic_model(design)` to median bond-diff 0.000 nm, and a pure bend
reconstructs cleanly (max bond 0.276 nm). The crisscross short bonds are per-nucleotide MC
positional NOISE in a raw un-minimised CG frame propagating into the inter-residue O3'→P
backbone bonds (the NAMD-seed path tolerates it because NAMD minimises afterward; display has no
minimisation). Fix: `_frame_atomistic_overrides(smooth_sigma=2.0)` now runs the VALIDATED
crossover-preserving `_smooth_cg_positions_per_domain` over the reconstructed backbone sites —
DISPLAY + trajectory reconstruction only, the `build_atomistic_model_from_cg_spline` NAMD-seed
path is untouched. Synthetic-noise test: stretched bonds (>0.3 nm) 217→2, twist preserved
(median 0.144 nm unchanged), no clashes. Empirically σ=2.0 best; >3 starts to hurt. The long
stranded-nucleotide bonds (insertion copies absent from the 3-tuple-keyed frame) are still only
hidden by the renderer cutoff — covering insertion copies in the override is the deferred cure.

---

## Display reconstruction REWRITTEN — deterministic rigid-frame placer (2026-06-21, supersedes the two band-aids in the section above)

**What changed.** The oxDNA→atomistic/surface DISPLAY reconstruction no longer overrides only the
backbone position + re-derives each base's orientation from `position − axis_point` (the path that
amplified MC positional noise into the crossing / over-stretched backbone-bond mesh, then needed the
σ=2 smoother + the renderer's >1 nm bond-hide to mask it). It now **stamps each nucleotide by its OWN
oxDNA rigid frame**: each particle has `(CM, a1, a3)` from the `.dat` (a2 = a3 × a1), and the all-atom
template is placed by `world = origin + R·local` with **R = F·Q** and **origin = backbone_site + F·c**,
where `F = [a1 a2 a3]`, `backbone_site = oxdna_backbone_site(CM,a1,a3)`, and `(Q, c)` is a single fixed
calibration per bucket. Exact, deterministic, no axis fitting, no smoothing, no seed-clash; covers every
nucleotide including insertion copies.

**Calibration is EMPIRICAL, not hand-derived** (locked `_PHASE_*`/frame constants honored —
ask-first/locked-geometry rule). `atomistic._rigid_frame_calibration()` (lru-cached) builds a clean
ideal 2-helix duplex (h0 FORWARD, h1 REVERSE; FWD+REV strand each → all 4 buckets), writes+reads its
oxDNA conf for the known `(CM,a1,a3)`, and Kabsch-fits, per nucleotide, the transform that makes the
placer reproduce `build_atomistic_model(design)`'s OWN (validated) atom placement. `Q = Fᵀ·R_kg`,
`c = Fᵀ·(origin_kg − backbone_site)`. **Bucketed by `(strand_dir, helix_is_FORWARD)`** — 4 buckets,
mirroring `_atom_frame`'s only direction branches (the REVERSE-strand P azimuthal correction differs for
a FORWARD vs REVERSE/None helix; None≡REVERSE → `helix.direction == FORWARD` is the discriminant). The
fit residual is **0.0 to machine precision** in all 4 buckets (asserted <1e-6 in the function — a silent
drift can't ship), and the placer reproduces the design build to **<0.01 Å max** with identical atom
count, serial→(name,element,residue) map, AND bond list (so the renderer's serial-keyed bond list stays
valid — verified fast-path vs override-path are serial-for-serial identical).

**Where it lives.**
- `backend/core/atomistic.py`: `_oxdna_frame_basis` (F + backbone_site, shared by fit & runtime),
  `_rigid_frame_calibration` (the cached fit), `_oxdna_rigid_frame` (the stamp), and a new
  `build_atomistic_model(..., frame_override={key:(CM,a1,a3)})` arg. In the copy loop, a nucleotide with
  a frame uses `_oxdna_rigid_frame`; else the existing `_atom_frame` path (NAMD-seed `nuc_pos_override` +
  `axis_override` UNTOUCHED — `build_atomistic_model_from_cg_spline` is unchanged). `frame_override` key
  is copy-aware: `(h,bp,dir,copy_k)` then 3-tuple fallback for copy 0.
- `backend/core/oxdna_health.py`: `_frame_atomistic_overrides` (+ σ smoother) **DELETED**; replaced by
  `_frame_override_from_frame` (frame dict → `frame_override`). `frame_atomistic_flat`/`frame_surface_json`
  call `build_atomistic_model(frame_override=…)`. `_aligned_downsampled_frames(copies=…)`;
  `composite_trajectory_atomistic/_surface` pass `copies=True`.
- `backend/physics/oxdna_interface.py`: `read_configuration_full(copies=False)` /
  `read_trajectory_frames_full(copies=False)` / `read_configuration_unwrapped(copies=False)` — when True,
  loop-insertion copies keep their own 4-tuple key (NO-OP for non-insertion designs — only 3-tuples
  exist). `unwrap_align_to_reference` made copy-robust (copies tied to their base/prev-copy in the BFS
  adjacency; WC fwd/rev dict guarded to 3-tuples). **All existing 3-tuple consumers untouched** (default
  `copies=False`): base_pair_retention, CG `/display` toFemUpdates, rmsf flex-map, cg_to_atomistic seed.
- `backend/api/routes_oxdna.py`: `_relaxed_full_map(..., copies=False)`; `display-atomistic`/`-surface`
  pass `copies=True`, CG `/display` stays 3-tuple.
- `frontend/src/scene/atomistic_renderer.js`: `_MAX_BOND_NM` cutoff comment reworded — now a BACKSTOP
  only, not the primary fix.

**Tests (backend 2937, frontend 1622, ruff clean).** Replaced the obsolete
`test_frame_overrides_smoothing_tames_noise_bonds` (the σ band-aid pin) with 4 placer pins in
`test_oxdna_relaxation.py`: `test_rigid_frame_calibration_buckets_exact` (4 buckets, Q orthonormal det+1),
`test_rigid_frame_placer_reproduces_design_build` (<0.01 Å + serial/bond identity), 
`test_rigid_frame_placer_is_rigid_under_reorientation` (rotating every input frame rotates the whole
model by exactly that rotation — orientation IS driven by a1/a3 — + determinism), and
`test_frame_atomistic_covers_insertion_copies` (LoopSkip delta=+1 → copies get distinct frames, all
placed, none stranded). Existing atomistic/surface/trajectory/rmsf pins stay green under the new placer.

**NOT VERIFIED IN APP** (no live oxDNA job here) → MV-OXREPS updated with the human-eye TODO: eyeball a
real relaxed `6hb_OxDNA_test` job — ball-and-stick reads clean (no mesh / over-stretch), dsDNA reads
B-DNA, surface + scrub + flex-map reconstruct cleanly. **Scope note:** the rmsf "flexibility map"
`average_frame` stays copy-0-only (insertion copies in the averaged structure fall back to the renderer
cutoff — acceptable for a smoothed view); single-frame display + trajectory get full copy coverage.

---

## Atomistic display VALIDATION oracle + backbone-closure FIX (2026-06-21)

User saw long/stretched bonds still in the relaxed ball-and-stick (orientation was fixed by the rigid placer,
but the backbone wasn't connected). Built a full validation layer + the fix.

**Validation oracle — `backend/core/atomistic_validation.py`.** Measures EVERY element the oxDNA-display
atomistic rep draws (each bond stick, each atom sphere) so a stretched / hidden / clashing element is
queryable, not just visible. `audit_bonds(design, frame)` reconstructs with the SAME
`build_atomistic_model(frame_override=…)` the renderer uses (audited bonds ARE rendered bonds — identical
serial pairs), classifies every bond **rigid | linker | backbone | bridge**, and flags: **rigid-stamp
violations** (a frame-invariant intra bond ≠ template = a placer bug; the load-bearing signal — expect 0),
over-stretched bonds, bonds the renderer **hides** (>1 nm — drawn as nothing but listed), clashes (<0.08 nm),
non-finite atoms. Entry points `latest_job_for_design` / `relaxed_frame_for_job` / `audit_oxdna_job`. Route
`POST /oxdna/jobs/{id}/display-atomistic-audit` (queryable from the live app). CLI `scripts/audit_atomistic.py`
+ `just audit-atomistic`. Skill `.claude/skills/validate-atomistic/`. Tests `tests/test_atomistic_validation.py`
(10). Bucketing nuance: the crossover/nick/skip bridge minimiser relocates {O3',P,O5',OP1,OP2}, so an intra
bond touching one of those is a "linker" (judged by absolute length), and only a no-minimiser-atom "rigid"
bond is the frame-invariant stamp check.

**Root cause of the long bonds (MEASURED, not reasoned).** On the real 6hb_sim_tests job c1299e0b07b5: rigid
stamp PERFECT (18 279 rigid bonds, max Δ 0.0000 Å, 0 violations), but **sequential O3'→P backbone gaps median
0.91 nm / 95% > 0.6 nm** (ideal 0.166 nm). Systematic, not fraying — oxDNA's per-nucleotide CG frames don't
enforce all-atom backbone continuity, so each rigidly-stamped O3'(i) misses P(i+1). build_atomistic_model
only bridged crossovers/nicks/skips, never the continuous sequential backbone.

**The fix — `atomistic._close_sequential_backbone` (AF-ATOM-CLOSURE, user-authorized).** Gated on
`frame_override` + new `close_backbone=True` (DISPLAY path ONLY — design/PDB/NAMD-seed build with
`frame_override=None` are byte-identical; the rigid-stamp reproduction test sets `close_backbone=False` to
isolate the pure stamp). For each sequential O3'(i)→P(i+1) bond (same helix, consecutive bp, same dir — NOT a
crossover/skip/extra-base, those are bridged already), re-seat ONLY the phosphate linker (O3'/P/O5'/OP1/OP2)
between the rigid C3'(i)/C5'(i+1) anchors via the validated `_interpolate_backbone_bridge` (linear,
~0.01 s/1000 bonds — 2000× faster than the L-BFGS bridge and slightly better quality here; the ribose ring +
base never move, so the rigid-stamp invariant holds). **Audit-verified result:** backbone mean 1.005→0.185 nm,
max **3.155→0.806 nm**, **hidden-by-renderer 266→0** (whole backbone now draws connected), stamp still 0
violations. Residual ~744 mild over-stretches (0.20–0.81 nm) + clashes at genuinely-frayed/tightly-packed
regions — inherent to un-minimised CG→all-atom display, honestly surfaced by the audit; a full display
minimisation is the future step (out of scope).

**Frontend parity (AF-ATOM P2).** `atomistic_renderer.test.js` asserts the renderer hides EXACTLY the >1 nm
bonds (== the audit's `hidden_by_renderer`) and draws the rest at true length, by decomposing the bond
InstancedMesh matrices — the on-screen sticks are now tied to the audited model bond-for-bond.

Backend **2946 passed / 55 skipped**, frontend **1623 passed**, ruff clean. **NOT VERIFIED IN APP** (no live
oxDNA job here) → MV-OXREPS: eyeball the connected backbone on a real relaxed job; `just audit-atomistic
<stem>` gives per-bond numbers for any job. Ledger: AF-ATOM P1/P2/CLOSURE all SHIPPED in
`design_automation_backlog.md` (Tier 5 + Tier F).

---

## CRITICAL CORRECTION (2026-06-21 later) — rigid-frame placer COLLAPSED base pairs; reverted display to axis-derived

User's next screenshot: base positions + bonding STILL fundamentally wrong (bonds appearing to join
strand-adjacent / opposite bases). The earlier audit said "stamp clean / backbone connected" — but it only
checked bond LENGTHS + intra-residue rigidity, NEVER whether nucleotides are POSITIONED/ORIENTED correctly
relative to each other. **Decisive measurement** (added an inter-base diagnostic, then baked it into the
audit): on real job c1299e0b07b5 the **rigid-frame placer collapsed WC pairs — C1'–C1' median 0.48 nm (min
0.034, partner atoms overlapping) vs 0.94 nm correct**; stacking jumbled too. The raw oxDNA CG frame is a
PERFECT duplex (WC bead–bead 1.025 nm, a1·a1 = −0.988), and the IDEAL all-atom build is fine (0.967) — so it
is a RECONSTRUCTION bug, and the rigid placer introduced it.

**Root cause.** The rigid placer orients each nucleotide from oxDNA's relaxed `a1`/`a3`. Comparing
reconstruction paths on the SAME relaxed frame: **rigid placer WC C1'–C1' = 0.48 (collapsed); the
axis-derived path (`nuc_pos_override` = backbone sites + `deformed_helix_axes`) AND the NAMD-seed spline path
both = 0.94 (correct).** So oxDNA's relaxed `a1` does NOT map onto the all-atom base direction the calibration
assumed (a convention mismatch — NOT to be reasoned about; measured). The first task's "reproduces design
build to <0.01 Å" pin was BLIND because it only ever fed IDEAL frames (where a1 = base_normal); it never
tested a real relaxed frame's inter-base geometry. The first task also MISDIAGNOSED the original "bond mesh"
as an orientation problem — it was the backbone discontinuity (the long O3'→P sticks), which the closure fixes.

**Fix (user-authorized end-to-end).** Reverted the DISPLAY reconstruction to the proven axis-derived path:
`oxdna_health.build_display_model(design, frame)` = `_frame_atomistic_overrides` (backbone sites +
`deformed_helix_axes`, copies collapsed to 3-tuple for the axis fit — a real bug fix: `deformed_helix_axes`
unpacks 3-tuple keys and the display route passes copies=True) → `build_atomistic_model(nuc_pos_override,
axis_override, close_backbone=True)`. ONE shared builder drives the atomistic + surface display sinks AND the
audit, so what's measured is what's drawn. Closure is now opt-in via `close_backbone` (default False; gate is
just `if close_backbone`, no longer tied to frame_override → design/PDB/NAMD-seed builds byte-identical). The
σ smoother stays gone. The rigid-frame placer (`frame_override` + `_rigid_frame_calibration` +
`_oxdna_rigid_frame`) is RETAINED only as an exact-on-ideal capability (its 3 pins) and marked SUPERSEDED FOR
DISPLAY in code; the new `wc_collapsed` audit check guards against re-introduction.

**Audit now measures inter-base geometry** (`_base_geometry`): WC-pair + stacking C1'–C1' + a `wc_collapsed`
flag (median WC C1'–C1' < 0.70 nm). This is the metric that would have caught the collapse; it factors into
`ok`. **Real-job result after the fix:** WC C1'–C1' **0.48→0.94 nm (OK)**, stacking 0.47 nm, backbone
connected (mean 0.11 nm), **hidden-by-renderer 266→4**, template stamp 0 violations. Residual: ~249 mild
linker over-stretches (0.20–1.07 nm) + clashes at genuinely-frayed/tightly-packed regions — inherent to
un-minimised CG→all-atom display (a future display minimisation would clear them; the audit tracks them).

**Tests:** `test_atomistic_validation.py` (11) incl. `test_base_geometry_detects_collapse` (the regression
guard); the 3 closure/displaced/insertion tests updated for the axis-derived path; rigid-placer pins kept
(ideal-only capability). Backend **2947**, frontend **1623**, ruff clean (my files). Still **NOT VERIFIED IN
APP** → MV-OXREPS.

---

## INDEX-MAPPING FIX (2026-06-21 latest) — active-design ≠ job-snapshot scrambled the atomistic overlay

User's 3rd screenshot: still wrong bonds/positions + **wrong COLOURS** → correctly inferred a NADOC→oxDNA→
atomistic residue-ID / index-mapping issue. **Root cause (measured, not the backend reconstruction — that is
provably identity-preserving):** the atomistic renderer builds its atoms/colours/bonds from `GET
/api/design/atomistic` (the **currently-loaded** design) while `display-atomistic` returns relaxed positions
for the **job's design.json snapshot**, and `applyPositionLerp` overlays them by `atom.serial`. On the real
job the loaded `6hb_sim_tests.nadoc` had been EDITED after the job ran → **21 812 atoms / hash eb9d96…** vs the
job snapshot's **22 050 / hash b2ca72…** (different sequences). Different serial spaces → every serial maps to
a different residue → scrambled colours/bonds/positions. (Confirmed the backend is clean: `build_display_model`
vs `build_atomistic_model(design)` are identical atom-for-atom in serial→name/element/residue/strand/helix/bp/
dir + bonds; every oxDNA particle key maps to a NADOC strand; per-strand counts preserved.)

**Fix.** (1) `display-atomistic` now returns `topology_hash` (the job snapshot's
`atomistic_reference_topology_hash`) + `n_atoms`. (2) New `GET /oxdna/jobs/{id}/atomistic-model` →
`atomistic_to_json(build_atomistic_model(job_design))` (atoms+bonds, same serial space as the flat positions).
(3) Frontend `oxdna_display._pushAtomistic` now `_ensureJobAtomistic` FIRST — rebuilds the atomistic renderer
from the JOB's own atoms/bonds (`getOxdnaAtomisticModel`, once per job, cached on `_atomTopoJob`, cleared in
`_restoreHeavy`) BEFORE overlaying the relaxed positions, so the rendered strands/residues/colours ALWAYS match
the topology the positions belong to — regardless of what's loaded in the app. Toggle-off restores the design
renderer (`onRestoreDesignHeavy`).

### Forward/reverse phase fix (2026-06-21 latest+1) — REVERSE-lattice helices were mis-phased

After the index-mapping fix, user reported one residual: "incorrect phase mapping between strands for HALF the
helices … forward vs reverse lattice locations … a fix worked out months ago, forgotten for trajectory mapping."
**Measured + confirmed:** the relaxed-display reconstruction collapsed **REVERSE-lattice helices' WC pairs
(C1'-C1' 0.715 nm) while FORWARD-lattice helices were correct (0.958)** — yet the raw oxDNA CG is IDENTICAL for
both (bead-bead 1.024 vs 1.027, a1·a1 −0.988), so oxDNA relaxes both helix types to the same duplex → it's a
RECONSTRUCTION bug, not relaxation. **Root cause:** the geometry places the reverse strand at `fwd ±
minor_groove (±150°)` SIGN-ed by the helix's lattice direction (`geometry.py:181`,
`minor_groove_rad = +150 FORWARD / −150 REVERSE`), and `_atom_frame`'s reverse azimuthal correction undoes that
**per lattice direction** (`+58.2°` FORWARD-helix / `−1.8°` REVERSE-helix — a 60° split). That's correct for
DESIGN-topology input but **oxDNA relaxation ERASES the lattice-location distinction** (both helix types relax
to a real B-DNA duplex at the same physical groove angle), so the relaxed reconstruction must apply the UNIFORM
(forward) branch. Empirically decisive: forcing `helix_direction=FORWARD` for all → REVERSE 0.715→**0.961**
(≈ FORWARD 0.958 ≈ design 0.967); forcing REVERSE → FORWARD collapses to 0.706. **Fix:**
`build_atomistic_model(relaxed_oxdna_phase=…)` — when set (only `build_display_model` sets it), the axis-derived
`_atom_frame` call uses `helix_direction=FORWARD` regardless of the helix's lattice direction. **Touches NO
locked `_PHASE_*` constant** — only which existing branch the relaxed DISPLAY selects; design/PDB/NAMD-seed
(`relaxed_oxdna_phase=False`) keep the real per-direction branch byte-identical. Audit after: WC C1'-C1' uniform
**FORWARD 0.958 / REVERSE 0.961 (balanced)**, hidden 0. **Regression guard:** the audit's `_base_geometry` now
splits WC C1'-C1' by helix lattice direction + a `wc_helix_imbalanced` flag (factored into `ok`); pin
`test_wc_helix_imbalance_detector`. Backend **2950**, ruff clean.

**Validation the user asked for** (NADOC strands → oxDNA → atomistic identity):
`test_strand_identity_preserved_nadoc_to_atomistic` (serial→full-identity + bonds identical; oxDNA keys all map
to strands; per-strand counts preserved) + `test_display_topology_hash_guards_against_design_drift` (route
returns the hash; model route's serial space matches the flat array) + frontend
`oxdna_display.test.js` (rebuilds from job topology once per job before overlay). Backend **2948** (+1 flaky
unrelated), frontend **1624**, vite build OK, ruff clean. **NOT VERIFIED IN APP** → MV-OXREPS: with a design
EDITED after its job, the atomistic display should now show the job's correct coloured/bonded structure, not a
scramble.

---

## 2026-07-02 — LOOPS in oxDNA: two blockers fixed (the loop-copy path was never exercised)

Triggered by "include loops in oxDNA sims", iterated on `workspace/Robot Arm/Arm_pulley_v1.nadoc` (22 helices,
14 322 nt, **204 loop insertions + 207 skip deletions**, honeycomb, fully sequenced; `flexible_connections`
EMPTY — so the ssDNA flexible-arc work does NOT apply here, "loops" = the loop_skip deformation system). It's
a **bent bundle**: column-0 helices net −23/−33, column-2 net +26/+35 — deliberate differential ins/del bends
the arm. Two stacked failures blocked relaxation; both were dormant because every prior oxDNA test design had
**0 loop insertions**.

- **BLOCKER 1 — `oxdna_native_seed_map` KeyError (crashes job-prep).** A loop insertion is a **dsDNA** insert
  (both strands get an extra bp — `nucleotide_positions` adds 2 nucs/loop), so loop copies are WC-paired and
  keyed by a **4-tuple** `(helix, bp, dir, copy_idx)` in `resolved_nuc_map` (816 such keys here). The seed map
  built its FWD/REV pair sets from `k[2]` but then indexed `resolved_map[(hid,bp,"FORWARD")]` as a 3-tuple →
  `KeyError('h_XY_2_1',180,'FORWARD')`. FIX (`oxdna_interface.py`): guard the pair-sep SAMPLE to `len(k)==3`
  (loop copies excluded from the median — they're at the same radius, so 3-tuple pairs are representative);
  the inward a1-shift still applies to EVERY key incl. copies (`a1_of` covers all). Pin
  `test_oxdna_native_seed_map_handles_loop_inserts` (can-go-red: old code raised).

- **BLOCKER 2 — `compact_skips=True` desyncs crossovers on a bent bundle (no relax recovers).** `compact_skips`
  (added for straight uniformly-skipped bundles, §2026-06-18 #3) closes skip gaps by advancing a per-helix
  `eff` counter — i.e. it shifts EACH helix axially by ITS OWN cumulative deletion count. When paired helices
  carry **unequal** skips (h_XY_0_7: 23 skips below bp307 vs h_XY_1_7: 4) the crossover between them stretches
  to **8.4 oxDNA units** (≈19 bp × rise) — far past FENE; 508 crossover bonds over the cliff, max 8.41. The
  un-compacted **deformed** geometry keeps crossovers registered (worst cross-helix bond 3.05, mostly the
  bend edges) and relaxes fine. Skip gaps are INTRA-helix so compaction can only leave crossover bonds equal
  (balanced skips) or worse (bent) — never better. FIX: new `_seed_geometry(design)` in `routes_oxdna.py`
  builds both, and falls back to deformed when `max_crossover_backbone_stretch(deformed) <
  max_crossover_backbone_stretch(compact) − 0.5`; no-loop_skips designs short-circuit to compact (no 2nd
  build). New pure helper `max_crossover_backbone_stretch(design, geometry)` (`oxdna_interface.py`) measures
  the worst cross-helix backbone bond. Wired at ALL THREE seed sites so the display's Kabsch reference matches
  the sim frame: job-prep (`create_oxdna_job`), `_reference_conf` (`design_ref.dat`), protein-transforms; plus
  `routes_oxdna_live.py`'s live design_ref. **CAUTION on the threshold:** ideal NADOC seed crossover bonds are
  inherently ~2–2.5 units (wide 1.0 nm helix radius) even when perfectly registered — do NOT use an absolute
  cutoff (an early 2.0-unit version mis-fired on a normal routed 18hb reading 2.45); the *difference* vs
  deformed is the only clean signal. Pins: `test_max_crossover_stretch_detects_compaction_desync`,
  `test_seed_geometry_falls_back_for_bent_bundle` (both on a synthetic bent 18hb_routed).

- **RESULT.** With both fixes the production `_seed_geometry` path relaxes the arm cleanly: MC 500 → GPU MD
  relax drove energy **+27 → −0.36/particle** (unbiased equil plateau = self-sustaining), all 3 stages
  `completed`, no divergence. Short-probe bp mc 94% → md 74% → equil 66% geometric / 4338 HBList (a 20k-step
  probe, well short of the ~1e6 re-anneal — a standard-defaults run re-anneals further; a full-length
  standard run was launched to confirm quality/gate-pass).

- **KNOWN residual (not a blocker, health blind-spot):** `backbone_bond_pairs` COLLAPSES loop copies to one
  3-tuple and never emits the loop-insert backbone bonds — so the FENE health check (`max_backbone_stretch`)
  can't see loop-copy bonds (they don't match the 4-tuple `resolved_nuc_map` keys → the "missing 816"). oxDNA
  itself simulates them fine (topology threads them, no inconsistency), but a loop bulge that over-stretches
  would be invisible to the gate. Worth threading loop copies into `backbone_bond_pairs` if loop-heavy designs
  need health coverage. Also: loops are still placed as an axial "bulge" (eff advances 1 per loop column), not
  a ⟂ ssDNA loop — physically crude but FENE-safe as a seed; a real ss-loop bulge geometry is a separate job.

### 2026-07-02 (later) — loop base ORDER + groove were topologically wrong on reverse strands

User caught it: a loop bulges along the axis (copy k=0 lowest, k=n−1 highest). A FORWARD strand climbs
`bp_lo → k0 → … → k_{n−1} → bp_hi`; a REVERSE strand runs antiparallel and must DESCEND `bp_hi → k_{n−1} →
… → k0 → bp_lo`. Two bugs made the reverse strand wrong (user model confirmed = **paired extra base-pair /
duplex extension**, fix scope = **all paths**):

- **Bug A — copy ORDER not reversed for reverse strands.** `_walk_strand_nucleotides` emitted `for k in
  range(n_copies)` for BOTH directions → the reverse strand threaded `bp_hi → k0[low] → k1 → … → bp_lo`, a
  ZIG-ZAG with a ~1.9-unit out-of-order backbone bond on every reverse-strand loop (measured: 1.89 oxu on a
  δ=2 loop). This also mis-assigned `strand.sequence` letters to the wrong copies on reverse strands. FIX:
  `copy_order = range(n) if FORWARD else range(n−1,−1,−1)`. The 4-tuple key still carries the TRUE k, so WC
  pairing (copy k ↔ copy k, same axial level) and per-copy geometry are unchanged — only the emission (n3/n5
  chain + sequence) order flips.
- **Bug B — loop copies came from a DIFFERENT groove convention.** `resolved_nuc_map` recomputed loop copies
  via `_compute_nuc_geometry_copy` → `_compute_nuc_geometry`, whose reverse minor-groove sign is OPPOSITE to
  geometry.py `nucleotide_positions` (oxdna_interface L119 `groove=−150° FWD-helix` vs geometry.py L181
  `+150°`). Real bases dodge it (taken from the geometry LIST = geometry.py); only loop copies hit the
  divergent path → the reverse loop copy landed ACROSS the duplex (a 2nd ~1.7-unit junction bond). FORWARD
  copies were immune (they return `fwd_backbone`, groove-independent). FIX: `resolved_nuc_map` now sources
  the k-th loop copy from the geometry LIST itself (grouped per (helix,bp,dir) in emission order = k
  ascending) instead of recomputing — same groove as real bases. `_compute_nuc_geometry_copy` kept only as a
  fallback when the list lacks the copy. **NOTE the broader latent issue:** `_compute_nuc_geometry`'s reverse
  groove genuinely disagrees with geometry.py — it's only masked now because real bases never use it and loop
  copies no longer do; reverse OVERHANG bases (outside helix span) may still hit it. Reconcile if touched.
- **RESULT** (δ=2 loop): reverse strand now mirrors forward exactly — `bp_hi → k2(0.69) → k1(0.39) →
  k0(0.39) → bp_lo(0.69)`, monotone, no over-stretch. On the real arm: loop-copy bonds median 0.73 / max
  2.47 / only 3-of-1224 over FENE (were hundreds); oxDNA topology inits clean + relaxes to `completed`. Pin
  `test_loop_copies_thread_monotonically_on_both_strands` (both strands monotone + all bonds < FENE).
- **THREE separate walks — NO single shared one.** Each consumer resolves loop-copy order independently
  (geometry is emitted PER HELIX, ascending-axial k; both strand directions traverse each helix, so no
  single emission order suits both — the reversal MUST happen per-consumer at its strand walk):
  - **oxDNA (DONE):** `_walk_strand_nucleotides` + `resolved_nuc_map` (above).
  - **Render (DONE 2026-07-02):** `helix_renderer.js buildHelixObjects` sorted each strand's nucs by
    (domain, direction-aware bp) and drew a backbone cone between consecutive nucs — but loop copies share
    a bp_index, so JS's STABLE sort kept them in geometry-list order (ascending axial) for BOTH directions →
    a REVERSE strand (e.g. `loop_test.nadoc`: scaffold is REVERSE on the looped helix) zig-zagged the cone
    into the bulge and back. FIX: extracted `export function orderStrandNucleotides(nucs)` — same sort +
    a direction-aware LOOP-COPY tiebreak (copy index = per-(helix,bp,dir) appearance order in the list;
    FORWARD threads 0→n-1, REVERSE n-1→0). Pin: `helix_renderer.test.js` (`orderStrandNucleotides`, pure).
    Verified in-app via a throwaway Playwright spec on `loop_test.nadoc` (scaffold is REVERSE on the looped
    helix): max scaffold backbone bond <1.0 nm (was ~1.6 nm). No groove bug here (render uses geometry.py
    positions throughout).
  - **atomistic.py (DONE 2026-07-02 — PDB/NAMD export):** its OWN walk, DIFFERENT key convention (3-tuple
    k=0, 4-tuple k≥1), same forward-only copy iteration in THREE coupled loops — seq_map (`_build_sequence_map`),
    atom placement, and O3′→P backbone bonds (all in `build_atomistic_model`). New shared helper
    `_loop_copy_order(direction, n_copies)` (range ascending FORWARD / descending REVERSE); all three loops
    restructured to iterate it (placement/bond `while copy_k` → count `n_copies` then `for copy_k in
    _loop_copy_order(...)`). `bp_to_sugar_serials` (crossover/skip bridge representative) pinned to
    copy `n-1` explicitly so its "last-copy-wins" value is order-independent (unchanged behaviour). Uses
    geometry.py positions → order only, no groove bug. Pin `test_atomistic_loop_backbone_threads_in_order_on_reverse_strand`
    (reverse worst O3′→P bond must match forward; can-go-red: pre-fix reverse 0.83 nm vs forward 0.42).
  All three walks now correct. The real long-term cleanup is to UNIFY them onto one strand walk (they
  triplicate the domain→bp→copy traversal with three different key conventions) — a separate refactor.

### 2026-07-02 (later still) — loop bases now FOLLOW the sim in all 4 display overlays

User: toggling oxDNA display left loop bases at their design positions (didn't follow the relaxed sim).
Root cause = the SAME collapse everywhere: the display/flex/deviation/trajectory data keyed nucleotides by
the 3-tuple `(helix,bp,dir)`, so loop-insertion copies collapsed (last copy wins) — one update moved one
bead, the rest stayed put. Fix = surface + address a **loop-copy index** end-to-end (loop copies are already
4-tuple `(helix,bp,dir,copy)` in `read_configuration_full(copies=True)`):

- **Frontend bead addressing (shared enabler, `helix_renderer.js`):** new `_copyKeyToEntry`
  (`"helix:bp:dir:copy"→entry`, copy = per-(helix,bp,dir) appearance order in `backboneEntries`) + `entry._copy`
  + `slab._copy`. `applyFemPositions` addresses `_copyKeyToEntry.get(...:${upd.copy ?? 0})` (falls back to
  `_keyToEntry` → backward-compatible); slab-normal `normalMap` + `applyScalarColors` (beads/slabs/cones) all
  key by copy. Cones follow free (nuc-identity via `_nucToEntry`). Non-loop designs unchanged (copy 0).
- **Each data path adds a `copy` field** (0 for plain nucleotides / `__xb__` inserts):
  - **Display** (`get_oxdna_display`): `_relaxed_full_map(..., copies=True)` + emit `copy=key[3] if len==4`.
    `toFemUpdates` carries it.
  - **Flex** (`production_rmsf(..., copies=True)`, route passes it): reads ref+traj with copies, per-copy
    positions. `rmsfColorMap` emits `copy` + a 4-part `colorByKey` (plus a 3-part alias for copy 0 so the
    crossover-arc recolour, which lands on real nucleotides, still matches).
  - **Deviation** (`geometry_deviation_map`): copy-aware INLINE lookups (kept `_backbone_lookup` untouched —
    it's shared by rmsd/field/skip-twist self-consistency); `core_reference_geometry` (skip_twist_tuning) now
    emits `copy` (additive). `deviationColorMap` mirrors `rmsfColorMap`.
  - **Trajectory** (`composite_trajectory` + `_aligned_downsampled_frames(copies=True)`): the KEY BUG was
    `key_list = [k[:3] for …]` truncating even under copies=True → changed to `(k if copies else k[:3])`;
    `composite_trajectory_meta` matched. Keys ship as `[h,bp,dir,copy]`; `framesToUpdates` reads `keys[j][3]`.
- **Verified:** backend function calls on the arm's real trajectory — FLEX 408 / DEVIATION 408 / TRAJECTORY
  816 loop-copy entries (were collapsed); display route returns 408 loop-bp groups with 2 distinct copies.
  In-app Playwright (throwaway) on Arm_pulley_v1 + a seeded relax job: display + trajectory move ALL 408 loop
  bps' copies to distinct positions; `applyScalarColors` gives a loop bp's two copies distinct colours. Pins:
  vitest `oxdna_display.test.js` (copy carried through toFemUpdates/framesToUpdates/rmsf/deviation) +
  `helix_renderer.test.js`; backend `test_geometry_deviation_map_keeps_loop_copies_distinct`. Frontend 1932 /
  build clean; backend suite green; ruff clean on touched files (4 pre-existing errors in untouched
  oxdna_health functions left per no_bulk_reformat).

- **FOLLOW-UP BUG (same session) — copies=True ORPHANED loop copies in the PBC unwrap → giant display bonds.**
  User screenshot: massively over-stretched bonds shooting off the structure. Root cause: `_build_unwrap_adjacency`
  built the backbone graph from `backbone_bond_pairs` (which COLLAPSES loop copies to a 3-tuple that isn't in
  the copies=True map) + a 4-tuple copy-tie to a NON-existent 3-tuple base — so ALL 816 loop copies became
  isolated components (measured: 469 components, every 4-tuple orphaned). `unwrap_align_to_reference` box-shifts
  each component independently, so once the diffused structure straddles a box face the loop-copy islands land
  at the wrong image → giant bonds. FIX: new `_backbone_adjacency_pairs(design)` walks the REAL strand order
  (`_walk_strand_nucleotides`) threading loop copies as 4-tuples (prev_real → copy0 → … → next_real);
  `_build_unwrap_adjacency` uses it with a `_present()` resolver that maps each walk key to whatever is in the
  map (full 4-tuple when copies kept, collapsed 3-tuple when copies=False) — so BOTH conventions connect, and
  the 4-tuple-tie block is gone. Result: 1 connected component (arm copies True/False AND a no-loop 18hb all =
  1). Verified: wrap-the-structure-across-the-box then unwrap → worst loop-copy bond 1.99 nm, 0 giant (>3 nm).
  Pin `test_unwrap_adjacency_keeps_loop_copies_in_one_component` (can-go-red: pre-fix 469 components). This
  fix benefits EVERY unwrap consumer (display/flex/deviation/trajectory/field/rmsf) since they share the graph.

---



## Pre-hygiene head snapshot — 2026-08-08

Preserved verbatim when the current-state head was compacted. Earlier archive material remains authoritative for its own dates.

# Project: Local oxDNA Relaxation Runner + Display

## 📤 Trajectory-range export: 3-phase progress + a measured cost profile — 2026-07-23

Symptom: an export ran ~20 min with **nothing** in the UI, so it read as broken. It wasn't — the
build reported one opaque `phase:"align"` with `done` pinned at 0 for its entire duration, and the
bar only renders on a counter. Two fixes, and one measurement worth keeping.

- **Backend now reports three phases** (`_EXPORT_PROGRESS`): `align` (PBC-unwrap + Kabsch, one
  opaque pass, no counter) → `atoms` (per-frame all-atom rebuild, counts) → `write` (per-frame PDB,
  counts). `composite_trajectory_atomistic` gained an optional `progress(done, total)`; it ticks per
  *requested* index, so a range overrunning the trajectory still reaches 100 % instead of stalling.
- **Frontend treats `align` as INDETERMINATE** — barber-pole + "can take several minutes", never a
  frozen 0 %. `exportProgressView` returns `{pct, text, indeterminate}`. The bar also paints on
  click instead of waiting for the first 250 ms poll.

**Measured on VoltronCoreScad (16,168 nt ≈ 330k atoms, 51 frames), 2026-07-23:**
`align`+`atoms` ≈ **17 s/frame** (≥14 min), `write` ≈ **6 s/frame** (~5 min), peak RSS **14.5 GB**.
So **~75 % of an export is the all-atom rebuild**, not PDB writing — optimise there first.

### All four levers SHIPPED — 2026-07-23

1. **New `dcd` export format, now the default radio.** Topology PDB + binary DCD, zipped with a
   README carrying the ChimeraX lines (`open s.pdb` / `open s.dcd structureModel #1`). Writer added
   to [dcd_fast.py] (`write_header`/`append_frame`/`write_trajectory`) next to the reader that
   already owned the format — round-tripped through that independent reader in
   `tests/test_dcd_writer.py`. Frames are written one at a time, so peak memory is one frame.
   **DCD is NOT faster to build — don't claim it is.** Fresh-process head-to-head, 6 frames of the
   330k-atom design: pdb 419.6 s / 168.4 MB vs dcd 420.5 s / 28.1 MB. Identical build time (0.2 %
   apart), **~6× smaller file**. Both formats pay the same per-frame atomistic rebuild, which
   dominates; the format only changes how each frame is serialised. The UI radio was briefly
   mislabelled "fastest" on the strength of an unfair measurement — the size win is the real one.
2. **`_cross3`** in `atomistic.py` — `np.cross`'s generic-axis dispatch (`moveaxis` +
   `normalize_axis_tuple`) dominated the arithmetic on (3,) inputs. Applied to the hot sites only
   (`_atom_frame`, `_oxdna_frame_basis`, `_extra_base_frame` ≈ 57k of 57.5k calls); batched `(N,3)`
   sites still use `np.cross`. Plus `atomistic_positions_flat` vectorised (997k `round()` → `np.round`).
   **A/B'd on the real 330k-atom design: output bit-identical, 6.62 s → 5.24 s per frame.**
3. **`MultiframePdbTemplate`** (`pdb_export.py`) — one `export_pdb` render split into frame-invariant
   text + coordinate slots; per frame only PDB cols 31–54 are spliced. **Self-validating**: the route
   renders frame 1 the slow authoritative way and falls back to per-frame `export_pdb` unless the
   splice reproduces it byte-for-byte, because a silently mis-mapped splice would corrupt every
   exported coordinate. `build_multiframe_pdb_template` returns None (⇒ fall back) if the ATOM-line
   count disagrees with the model or the source is multi-MODEL.
4. **`StreamingResponse`** + `iter_composite_trajectory_atomistic` (generator sibling of the dict
   version) — frames are emitted as built, never accumulated. The export also passes `cache=False`:
   51 large frames are ~50 M elements against a 6 M budget, so caching evicted the whole live
   display cache to keep ~6 frames nobody re-requests.

**Progress phases are now `align` → `frames`** (rebuild+write merged, since streaming does both per
frame). `atoms`/`write` labels are kept for the fallback path.

**Lesson: cProfile lied about the size of the win.** It attributed ~3.0 s/frame to `np.cross`; the
real A/B saved 1.38 s. Per-call profiling overhead inflates call-heavy code (57.5k calls) far more
than it inflates a few big loops. Always A/B the actual change before quoting a speedup.

### OPEN: ~4× of a big export's wall-clock is still unaccounted for

Measured components on 13bb7151f234 (330k atoms), fresh process:
`composite_trajectory_meta` cold **7.9 s** (warm 0.03 s) · align pass **34.9 s** / 198 frames ·
per-frame atomistic rebuild **5.2–5.6 s** · `export_pdb` full render **~3.6 s** · template splice
**~1.2 s/frame**.

Those sum to **~95 s** for a 6-frame export. The full path measured **420 s** for the same 6 frames,
BOTH formats (419.6 / 420.5 — so it is format-independent and sits in the shared rebuild pipeline,
not in serialisation). **The ~325 s gap is not explained.** A cold-`composite_trajectory_meta`
hypothesis was tested and REJECTED (7.9 s). Prime suspect not yet tested: GC/allocator pressure from
`_aligned_downsampled_frames(copies=True)` holding 198 frames × 16,168 nucleotides of per-nucleotide
dicts + numpy triples (this is what drove the server to 14.5 GB RSS). Next step if anyone picks this
up: profile the ROUTE path end-to-end (not `frame_atomistic_flat` in isolation) and watch RSS/GC —
don't trust the component sum, it under-predicts by 4×.

## 💥 Crash recovery: a host restart cost 53 % of a run and reported 0 % — 2026-07-22

Real loss (`fb83ff00287a`, VoltronCoreScad · production, 50 M steps). Host restarted at ~26.6 M
steps; NADOC resumed; the resumed run **diverged** ("Invalid cell -2147483648 … pos: inf -inf inf")
at 3.9 M steps; the job then displayed **0 %**. THREE independent defects, all in
[oxdna_runner.py](../backend/core/oxdna_runner.py):

1. **Progress counted only the current attempt.** `_archive_partial_outputs` renames an interrupted
   run's outputs to `energy.rN.dat` / `trajectory.rN.dat`, but `_stage_energy_lines` reads only
   `energy.dat` — and `stage_frac` was computed **only when `status == "running"`**. A crashed stage
   therefore reported 0 % no matter how much it had banked. Now `stage_completed_steps` /
   `stage_fraction` sum every attempt's energy file and are reported for `failed`/`stopped` stages
   too. **Kept CHEAP** (energy arithmetic only, no trajectory scan, no writes — 0.3 ms) because it
   runs on the job-list poll path.
2. **Resume restarted the step BUDGET.** oxDNA always runs with `restart_step_counter = true`, so
   the resumed run re-ran the stage's *full* `steps`. The structure continued but the banked work
   was silently repeated. Resume now sets `steps = remaining` and pins
   `print_energy_every_override` / `print_conf_interval_override` to the ORIGINAL cadence, so the
   output intervals stay comparable across attempts (they default to `steps//100`, which a
   shortened budget would otherwise change mid-stage and desynchronise the accounting).
3. **Resume trusted a torn checkpoint.** `_starting_conf` accepted `last_conf.dat` on `size > 0`
   alone. oxDNA rewrites that file IN PLACE every `print_conf_interval`, so a crash mid-write leaves
   a plausible-sized file with inconsistent contents; oxDNA loads it happily and diverges millions of
   steps later — which reads as a sim instability, not a corrupt restart. New `resume_point()`
   validates it (complete particle count + all-finite), and otherwise walks back through the
   append-only trajectories for the newest COMPLETE frame (tail-seek, not a full parse — these are
   >1 GB). **`error_conf.dat` present ⇒ that attempt DIVERGED and is skipped entirely**, falling
   back to the attempt that ended cleanly. The recovered frame is written to **`restart_conf.dat`,
   a separate file** — `conf_file` and `lastconf_file` were both `last_conf.dat`, so a resumed run
   overwrote the very point it started from, which is what made the second crash unrecoverable.

**Invariant:** the restart configuration and the consumed-step count MUST come from the same source.
A blind sum over attempts credits work the chosen restart point doesn't contain (here: 30 M summed
vs 26.6 M actually recoverable, because the diverged 3.5 M tail is discarded).

**Second invariant (regression, found the hard way):** `completed_steps` must be cleared by EVERY
from-scratch start. `_halve_dt_and_restart` reset `resumed`/outputs but not the banked count, so a
retry that begins at step 0 kept crediting a previous resume's 26.6 M — a 20 %-done rerun reported
63 %. Cleared there AND on the runner loop's non-resume branch.

### ⚠️ What this did NOT fix — Run 6's divergence was NOT file corruption

The resume ran correctly (verified in `input.txt`: `conf_file=restart_conf.dat`, `steps=23400000`,
original cadence pinned) and **diverged again 27 min in** — matching the previous failure's 26 min.
So resuming from a byte-verified complete frame reproduced the blow-up: the instability is real, at
`dt = 0.005`, most plausibly because the structure at ~26 M steps is already strained, so ANY late
run-1 frame diverges. Do not read the recovery work as a cure for that.

What actually salvaged Run 6 was the pre-existing **`_halve_dt_and_restart`** retry: dt 0.005 →
0.0025, restart from the relaxed seed, full 50 M steps. Completed cleanly (final E_pot −1.3709 from
−1.3419, 2.23 GB trajectory, `production_retries: 1`). **Lesson: when a resume diverges on the same
timescale as the crash it was recovering from, suspect the physics, not the file.** The earlier
in-session conclusion ("cleared the previous divergence point ⇒ torn checkpoint confirmed") was
wrong twice over — the run being watched had restarted from zero, and its progress was inflated by
the stale `completed_steps` above.

Tests: `tests/test_oxdna_crash_recovery.py` (17, fast). Verified against the real job: reports
**53.2 %**, recovers step 26,600,000 from `trajectory.r1.dat`, 23.4 M remaining.

## 🐌→⚡ The panel poll was re-reading the whole job lineage every 1.5 s — 2026-07-21

Symptom: while a production run was live, the "Working…" popup fired on nearly every poll AND the
sim ran ~35 % slow (GPU 61 % util). Backend was reading **498 MB/s sustained** (10.7 TB lifetime)
from a 1.4 GB working set. Three compounding causes, all fixed:

1. **`_count_dat_frames` was an un-memoized DUPLICATE of `count_trajectory_frames`** — so
   `composite_trajectory_meta` bypassed the very cache added to stop lineage re-scans. It's now a
   thin alias (`oxdna_health.py`).
2. **`count_trajectory_frames` recounted a GROWING file from byte 0** (its old key included size +
   mtime, so a live trajectory never hit). Now **incremental**: cache holds `{size, reported,
   offset, count, anchor}`; unchanged size → stat-only hit; grown → scan the new tail only;
   truncation, or an anchor mismatch (a restarted stage rewinds to `t = 0` with an identical head),
   → full recount. A dangling final header with no newline is *reported* but not committed to the
   resume point. Tests: `test_count_trajectory_frames_incremental`, `test_count_dat_frames_is_memoized`.
3. **`nadoc:oxdna-job-selected` was level-triggered** — `_renderDetail` fires it on every 1.5 s poll
   tick, and `oxdna_export_card` rebuilds its timeline (→ a full-lineage frame count) on it. Now
   edge-triggered via pure `jobSelectionSignature(job)` = `job_id|status|stage statuses`; deselect
   (empty signature) always announces. **Consequence:** the export card's frame timeline no longer
   grows live mid-run — it re-syncs on any status change or re-selection. Fine for the fringe case
   of exporting a partial run; revisit only if that becomes a real workflow.

Measured after: `trajectory-meta` 26.9 s → **0.06 s**, `progress` 10.5 s → **0.3 s** (the 5 s busy-popup
threshold is no longer reachable), backend read rate 498 MB/s → **0.3 MB/s**.

**Lesson worth keeping:** a slow endpoint here was NOT slow work — profiling the handler's own
functions showed 0.3 s. It was queue contention from overlapping copies of a 27 s scan launched
every 1.5 s. Measure `/proc/<pid>/io` `rchar` and sample `fdinfo` offsets before optimizing the code
you *think* is hot.

## ⚡ Hard surface: absolute world POSITION replaces the clearance offset — 2026-07-16 (out-of-session work)

The Offset slider became a **"Position" number box in nm** — you type the plane's absolute world-axis
coordinate; changing **Side snaps it to structure contact**; the scene grid renders exactly there.
- New pure fns (tested) in `scene/oxdna_floor_math.js`: `floorContactCoordinate`,
  `floorClearanceFromAbsolute`, `floorAbsoluteFromClearance`. `ui/oxdna_floor_setup.js` gained a
  `getStructureBounds` dep (main.js builds a `THREE.Box3` from `designRenderer.getBackboneEntries()`).
- **THE BACKEND STILL SPEAKS CLEARANCE — the UI is the conversion boundary.** `getSurfaceSpec()`
  converts on the way out; sign convention is `const sign = axis[0] === '-' ? 1 : -1`. `applyConfig`
  PREFERS a persisted `surface.position_nm` and only derives from `offset_nm` + bounds as a fallback.
  No bounds available → conversions degrade to identity.
- `view_tool_buttons.setSurfaceGrid({…, positionNm})` now drives grid placement purely from the
  absolute coordinate (`offsetNm: 0`); the legacy bbox±offset path survives only when `positionNm` is
  null/non-finite. **No per-frame refresh — the simulation wall is fixed in world space** and must not
  follow trajectory entries as they move.
- **Backend persists where the wall actually landed.** `routes_oxdna._wall_axis_position_nm(wall_meta)`
  converts oxDNA's plane form (`dir·r + position = 0`, oxDNA units) → world nm; `create_oxdna_job` and
  `append_oxdna_run` write `job.run_config["surface"]["position_nm"]` (response-shape addition).
  Why: "the descriptor's offset alone is insufficient after the structure moves or a trajectory is
  scrubbed; visualization must render the exact plane oxDNA used at run start."
  Unit test in `tests/test_oxdna_surface.py` pins the sign convention (a `-Y` normal ⇒ world Y has the
  opposite sign from the scalar along the normal).

**Status:** PHASE 1 SHIPPED + USER-VALIDATED 2026-06-14. Full relax→production→analyze loop: staged CUDA
relaxation + mutual traps + production, oxDNA-HBList base-pair health, PBC-unwrap + Kabsch-aligned +
true-backbone display with following crossover arcs, per-design job filtering, production "ready" + button
graying + step-count + ETA, Show-RMSD. CUDA binary at `~/oxDNA/build/bin/oxDNA`. All gestures user-confirmed
in-app (MV-OXDNA → VALIDATED). **NAMD-seed handoff (Phase 2) SHIPPED 2026-06-14 — see §24** (relaxed
last_conf → fixed cg_to_atomistic backbone-site bridge → NAMD starting structure; "Use as NAMD seed" button;
backend validated on the real 6hb job, live NAMD run owes MV-OXDNA-SEED). §1–§22 = Phase 1 build log; §23 =
the plan; §24 = as-built. **§25 = hard surface + anchors + consolidated `/run` + relax-on-surface + the
`fix_diffusion=false` KEYSTONE FIX + grid-unify + display align toggle (SHIPPED 2026-06-18, commit 0dcb838).**
**Goal:** A 1-click *local* oxDNA coarse-grained relaxation pass that drives a complex
origami toward positions where a subsequent finer-grained NAMD/MD run is less likely to
melt at startup. Built as a new sub-panel in the **Dynamics** tab, mirroring the existing
NAMD MD job runner (job manager + staged protocol + stage checks + loading bars + health
readouts), plus an **"OxDNA display"** toggle that deforms the NADOC model to the last
stored relaxed positions — the exact analogue of the existing "Display MD" toggle.

This file is written so a fresh session can implement with minimal re-discovery. Read it
top to bottom before touching code. Honor the **Three-Layer Law** (CLAUDE.md): oxDNA output
is **Physical layer / display state only** — it is NEVER written back into Design topology.

---

## 1. Locked design decisions (from user, 2026-06-14)

| Question | Decision |
|---|---|
| oxDNA runtime + protocol | **CUDA build, full 3-stage relax**: (1) steric/min relaxation with capped backbone force to clear crossover clashes → (2) MD relaxation with capped/external forces → (3) short unbiased equilibration. Per-stage health gates. **Protocol is backend-agnostic** — CPU vs CUDA is one input-file line (`backend = CPU/CUDA`), so develop on CPU oxDNA, flip to CUDA for production. See §11 for the install situation on this machine. |
| Test fixture + job scoping | Backend validation on the **6hb primitive** (`workspace/Primitives/` 6hb beam). Frontend MUST run the **currently-loaded design** and show jobs **only for that design** in a **scrollable** list (filter by `design_source_path` + `getWorkspacePath`, mirror md_jobs_panel). |
| NAMD-seed handoff | **Standalone now; handoff is Phase 2.** Phase 1 = self-contained oxDNA job manager + display + health. Phase 2 (documented, not built) = feed relaxed CG positions as the NAMD starting structure via `cg_to_atomistic`. |
| "OxDNA display" rendering | **Deform the NADOC model** via `designRenderer.applyFemPositions(...)` — identical to MD display's `nadoc` representation. (No beads/atomistic modes in Phase 1.) |
| Health/convergence readouts (all four) | (a) **Base-pair retention %** — fraction of designed WC pairs still formed; (b) **Potential-energy convergence** — per-particle U trend + plateau sparkline; (c) **Max backbone force / clash** — steric-clash resolution during the min stage; (d) **Stage timeline + speed** — steps/s and per-stage done/running/failed timeline. |

---

## 3. Scope — Phase 1 (build now)

A standalone oxDNA relaxation subsystem that:
1. Launches a **3-stage CUDA relaxation** job from the active design (1-click, with advanced params).
2. Runs it as a **managed, restart-surviving job** with live progress, a stage timeline, and a stop button.
3. Computes **per-stage health**: base-pair retention %, potential-energy convergence, max-backbone-force/clash, steps/s.
4. Persists results so the **"OxDNA display"** toggle can deform the NADOC model to the **last stored relaxed positions** of the current structure at any time (even after restart, without re-running).

**Phase 2 (documented, deferred):** wire relaxed oxDNA positions → `cg_to_atomistic` smoothing → NAMD starting structure (the melt-prevention handoff end-to-end). Hooks: `read_configuration` already returns the position map; `cg_to_atomistic.build_atomistic_model_from_cg_spline(design, conf_path)` already exists.

---

## 4. Target architecture (mirror NAMD, simplified — oxDNA has stages not "segments")

```
backend/
  core/
    oxdna_job.py        NEW  — OxdnaJob dataclass + OxdnaStatus + OxdnaStageStatus + OxdnaHealthSample
                              (clone md_job.py; jobs in workspace/oxdna_jobs/{id}/job.json)
    oxdna_runner.py     NEW  — async threaded runner: start_job/stop_job/reconcile, _run_oxdna_async
                              (PID capture + cancel), per-stage loop + health gate, progress parsing
    oxdna_protocol.py   NEW  — stage specs (min/relax/equil) + per-stage input-file generation (CUDA)
    oxdna_health.py     NEW  — base-pair retention, energy convergence, clash/backbone-force, from
                              energy.dat + trajectory .dat using read_configuration geometry
  physics/
    oxdna_interface.py  EXTEND — async run_oxdna variant; per-stage input writer (or move to protocol);
                              read_configuration to also return a1 (base_normal) for display (§5.3)
  api/
    routes_oxdna.py     NEW  — sub-router (mirror routes_md.py); mount in api/main.py with prefix="/api"

frontend/src/
  ui/
    oxdna_jobs_panel.js NEW  — initOxdnaJobsPanel({ oxdnaDisplayController, getWorkspacePath })
                              (clone md_jobs_panel.js: launch, list, detail, progress bar, stage
                              timeline, health cards, WS+poll, "OxDNA display" toggle)
    oxdna_display.js    NEW (or extend md_panel.js) — initOxdnaDisplay(...) → controller with
                              displayLatest/stopAndRestore reusing applyFemPositions
  api/client.js         EXTEND — oxdna job CRUD + display fetch helpers
  main.js               THIN WIRING ONLY — import + factory init + per-action wiring (module-first law)
index.html              ADD  — #oxdna-jobs-* panel markup inside #tab-content-dynamics
```

**Module-first law (CLAUDE.md / FEATURE_DEVELOPMENT.md):** all cohesive logic lands in the new
modules above as `initX({deps})→{api}` factories. `main.js` gains ONLY imports + factory inits +
thin wiring; its LOC must stay flat/lower. Cite the `main.js` LOC Δ in the done message.

---

## 5. Key technical specifics to get right

### 5.1 The 3-stage CUDA relaxation protocol (`oxdna_protocol.py`)
Standard oxDNA pre-relaxation. Each stage = its own oxDNA input file + run. Document defaults; expose
in advanced params (like md_jobs_panel). Suggested starting defaults (a DNA-origami PhD will tune):

- **Stage 1 — MIN / steric relax (clears crossover clashes).** `sim_type = min` (oxDNA `MD` min,
  or `MC` with strong `max_backbone_force`). CUDA may not support `min`; the robust portable choice is
  short **MD with capped backbone force**: `backend = CUDA`, `sim_type = MD`, `T = 0C→ low`,
  `dt = 0.001` (small), `max_backbone_force = 5`, `max_backbone_force_far = 10`, `thermostat = brownian`,
  modest `steps`. Gate: backbone-force/clash resolved.
- **Stage 2 — MD relaxation.** `backend = CUDA`, `sim_type = MD`, `interaction_type = DNA2`,
  `T = 296K` (≈23 °C), `salt_concentration` from advanced params (default 0.5 M), `dt = 0.003`,
  `thermostat = john`/brownian, `max_backbone_force` still capped (relax stretched bonds), external
  forces / mutual traps OPTIONAL (defer trap-file generation unless needed). Gate: base-pair retention
  ≥ threshold AND energy trending down.
- **Stage 3 — short unbiased equilibration.** Same as 2 but `max_backbone_force` removed (or large),
  no external forces, standard `dt`. Gate: base-pair retention plateau + energy plateau.

Each stage continues from the previous stage's `last_conf.dat` (set `conf_file` = prior `last_conf.dat`,
`topology` constant). Mirror `MdSegmentStatus` with `OxdnaStageStatus(name, kind, steps, status)`.
CUDA device selectable via `CUDA_device = {n}` (advanced param, like NAMD `devices`).

oxDNA binary: env `OXDNA_BIN` (existing convention, default `"oxDNA"`). CUDA build availability probe →
`GET /api/oxdna/oxdna-available` returning `{available, oxdna_bin, cuda, recommended_device}` (mirror
`namd_available`, use `shutil.which`). NOTE: a CUDA oxDNA build still uses the same `oxDNA` executable
with `backend = CUDA` in the input — there is not necessarily a separate binary; detection should run a
`--version`/dry probe or check the input acceptance rather than assume a distinct CUDA binary.

### 5.2 Async runner + live progress (`oxdna_runner.py`)
`run_oxdna` is currently blocking — rewrite an async variant mirroring `_run_namd_async`:
`asyncio.create_subprocess_exec(oxdna_bin, input_path, cwd=stage_dir, stdout=PIPE, stderr=PIPE)`,
stream stdout to a `.log`, capture PID into `_ACTIVE_OXDNA_PIDS` for `stop_job` (SIGTERM→SIGKILL),
run stages sequentially in a daemon thread + asyncio loop. **Progress source:** oxDNA prints step lines
to stdout AND writes `energy.dat` (one line per `print_energy_every`). Compute stage % as
`min(1, lines_in_energy.dat / expected_energy_lines)` or parse the step counter from stdout. Persist
`current_stage_idx` for resume; `reconcile_oxdna_status` detects detached procs after restart.

oxDNA output files per stage dir: `trajectory.dat`, `energy.dat` (cols: `time  U  K  total`, per
particle in oxDNA units), `last_conf.dat`. Use a per-stage subdir under `workspace/oxdna_jobs/{id}/`.

### 5.3 "OxDNA display" — deform NADOC model (`oxdna_display.js` + read extension)
Toggle `#oxdna-jobs-display-toggle` → controller `displayLatest()` → `GET /api/oxdna/jobs/{id}/display`
returns the path to the latest stage's `last_conf.dat` (or a precomputed positions JSON). Backend reads
it with `read_configuration(conf_path, design)` → `{(helix,bp,dir): pos_nm}`, formats to the
`applyFemPositions` update list: `[{helix_id, bp_index, direction, backbone_position:[x,y,z], nx, ny, nz}]`.

**GAP:** `read_configuration` currently drops orientation. The display sink wants `nx,ny,nz` (base normal).
Two options — pick one:
- **(A, recommended)** Extend `read_configuration` to also parse a1 from the `.dat` and return it →
  `nx,ny,nz = a1`. Faithful to relaxed orientation.
- **(B, cheaper)** Reuse the design's *static* geometry base_normal for `nx,ny,nz`, applying only relaxed
  positions. Good enough if rotation isn't visually critical for a relaxation preview. Simpler; ship (B)
  first, upgrade to (A) if needed.

"Last stored position data of current structure": the display must work on the latest oxDNA job whose
design matches the active design/doc (filter by `design_source_path` like md_jobs_panel does via
`getWorkspacePath`). Wire a prewarm + auto-stop-on-tab-leave exactly like md_jobs_panel. `stopAndRestore()`
calls `applyFemPositions(null)`.

### 5.4 Health computation (`oxdna_health.py`) — display-state only, never writes topology
- **Base-pair retention %:** designed WC pairs = `(helix,bp,FORWARD)`↔`(helix,bp,REVERSE)` present in
  topology. From a frame (`read_configuration`), count pairs whose paired-bead distance is within a
  cutoff of the expected B-DNA pair separation (analogue of NAMD's C1' gate, on CG beads). Robust + local,
  no `oat`/external dep. (Optionally upgrade later to oxDNA's H-bond-energy observable via a `DNAnalysis`
  backend run, but the geometric count is sufficient for a gate.)
- **Potential-energy convergence:** parse `energy.dat` column U; plateau = slope over last K samples
  below epsilon. Expose as a sparkline like the NAMD WC tooltip.
- **Max backbone force / clash:** during Stage 1, count backbone bonds whose bead distance exceeds the
  capped-force threshold (overstretched) → "clashes remaining"; gate Stage 1 done when ~0.
- **Steps/s + stage timeline:** wall-clock vs steps completed; per-stage done/running/failed/pending.
Append to `output/health.jsonl` + `output/metrics.jsonl` (mirror NAMD). Embed latest in `job.json`.

### 5.5 Unit conventions (already handled in oxdna_interface)
`NM_TO_OXDNA = 1/0.8518 ≈ 1.1740`, `OXDNA_LENGTH_UNIT = 0.8518 nm`. Positions out × NM_TO_OXDNA, back ×
OXDNA_LENGTH_UNIT. a1/a3 are unit vectors (no scaling). Energy.dat is per-particle in oxDNA energy units.

---

## 7. Risks / gotchas / invariants

- **Three-Layer Law:** oxDNA positions are Physical/display only. Never write them into `Design`. The
  display path uses `applyFemPositions` (a render override), exactly like MD display. (Phase 2's
  cg→atomistic is also display/export, not topology.)
- **`run_oxdna` is blocking today** — the live progress + stop story REQUIRES the async rewrite (§5.2).
  Don't ship the panel against the blocking call.
- **CUDA detection nuance** — CUDA oxDNA is usually the same `oxDNA` binary with `backend = CUDA` in the
  input, not a separate executable. Probe accordingly (§5.1).
- **Display orientation gap** — `read_configuration` drops a1; pick option A or B in §5.3 explicitly.
- **Design/doc scoping** — filter jobs to the active design (`design_source_path` + `getWorkspacePath`),
  multi-doc aware (see `project_session_recovery.md`). Don't show another structure's relaxed positions.
- **Loop/skip copies** — `read_configuration` collapses copies (last wins). Fine for display; note it.
- **Sequences optional** — oxDNA topology accepts `'N'`; relaxation doesn't need assigned sequence.
- **Module-first / main.js ratchet** — cohesive logic in modules; main.js stays flat. Refactor-extraction
  test rules apply to any pure functions pulled out.
- **LESSONS.md** — check the stale-state and rendering-invariant entries before wiring the display toggle
  (display-override clear/restore is a known footgun class).

## 8. Verification plan
- Backend: `just test` green (cite count); new unit tests for job round-trip, protocol input files,
  health metrics, read/async run. Flag any test-count drop.
  **Primary backend fixture = the 6hb primitive** (`workspace/Primitives/` 6hb beam) — small + fast on CPU oxDNA.
- Frontend: `just test-frontend` green for pure helpers; exercise in running app (`just frontend`) —
  load a design and launch a relax on **the currently-loaded design** (the panel runs the active design,
  no design picker). Confirm the jobs list shows **only that design's jobs**, is **scrollable**, then
  watch the 3 stages tick with progress + timeline + health cards, toggle
  "OxDNA display" and confirm the model deforms to relaxed positions and restores on toggle-off.
  Live gesture/visual not unit-testable → add a `USER TODO` smoke block (see `feedback_user_todo_smoke_tests`)
  + a `manual_validation_debt.md` PENDING row (MV-OXDNA) for the live relax+display gesture.
- Requires a local oxDNA (CUDA) install to fully exercise; until then the panel + `oxdna-available`
  probe should degrade gracefully ("oxDNA not found") exactly like the NAMD path.

## 9. Open questions to resolve at implementation time
- Exact per-stage step counts / dt / thermostat defaults (user will tune — start conservative).
- Whether Stage 2 needs mutual-trap external forces for very strained designs (defer trap-file gen unless
  a test design melts without it).
- Display orientation: ship option B (static normals) first, or invest in option A (relaxed a1) up front?
- Keep or retire the legacy `#oxdna-section` export/run buttons (check `project_tech_debt.md`).

## 10. Phase 2 (deferred) — NAMD-seed handoff
Relaxed `last_conf.dat` → `cg_to_atomistic.build_atomistic_model_from_cg_spline(design, conf_path)`
(Gaussian smoothing per domain, exists) → atomistic PDB/PSF → existing NAMD solvate/job pipeline as the
*starting structure* instead of ideal B-DNA. UI: a "Use as NAMD seed" action on a completed oxDNA job that
pre-fills a new MD job. This closes the melt-prevention loop end-to-end.

### 10.1 The seed is a PURE function of the oxDNA positions (fixed 2026-07-11)
A NAMD seed reconstructs each nucleotide from its oxDNA CG frame (CM, a1, a3) and must NOT re-apply any
design-level geometry. `build_atomistic_model` normally ends with `apply_deformations_to_atoms(atoms, design)`
(deformations + `cluster_transforms`); for a seed that would DOUBLE transforms the oxDNA frame already carries
→ the GT_corner_v2 "explosion" (K3). The seed path now calls `build_atomistic_model(..., apply_design_geometry=
False)` so the reconstruction depends ONLY on the oxDNA conf. Pinned by `tests/test_cg_seed_cluster_transform.py`
(cluster rotation/translation/multi-cluster all reconstruct ~1× with WC intact). Guard in
`build_atomistic_model_from_cg_spline` still raises on any >2× span blow-up as a safety net. See [[LESSONS]] K3.

### 10.2 Seed backmap must RIGID-STAMP unpaired ssDNA (fixed 2026-07-20 — the VoltronCore seed failure)
The oxDNA-seeded NAMD run for **VoltronCore** (job `5a90e8ceadc4`, seeded from oxDNA `5ce768ef2acf`)
died at NAMD startup: `FATAL ERROR: Bad global angle count! (1697578 vs 1697584)` — NAMD's signature
for **coincident atoms** (it can't distribute bonded terms through degenerate atoms; also showed as a
32-dihedral deficit + BOND energy 1.6e8 in the k0.5 min log). The `failure_kind:"instability"` tag is a
MISCLASSIFICATION — it's a structure-integrity abort, not a dynamics blow-up. The oxDNA relax itself
COMPLETED clean; the damage was in the backmap. Root cause: `build_atomistic_model_from_cg_spline` placed
every nucleotide by a fitted helix AXIS (`axis_override=deformed_helix_axes`). **Unpaired ssDNA — overhangs
/ tails / unpaired scaffold loops — has no helix to fit**, so a folded ssDNA run's nucleotides (0.5–1.1 nm
apart in the conf, e.g. h_XY_3_18 bp47↔bp67 at 1.14 nm) collapsed onto <0.05 Å-coincident atoms.
VoltronCore carries **962 unpaired ssDNA nt (5.9%, ≈55 overhangs, SQUARE lattice)** → 37–55 coincident
pairs → abort. This is the SAME root cause the DISPLAY path already fixed (§26c `_ssdna_frame_override`);
the SEED path never got it. **Fix:** `build_atomistic_model_from_cg_spline` now also passes
`frame_override=_ssdna_frame_override(design, full_map)` (lazy import — breaks the cg_to_atomistic↔oxdna_health
cycle) so unpaired ssDNA is stamped from its oxDNA a1/a3 RIGID frame; duplex stays on the axis path (the
rigid stamp collapses WC pairs, ssDNA has none). Duplex atoms byte-identical (fix strictly scoped to ssDNA).
**Verified (CPU backmap, no sim): VoltronCore coincident 37→0**; 2hb_noT / 6hb_validated (295k atoms) /
6hbx100_noT / 6hbx100_1xT (extra-base) all seed 0 coincident with AND without the fix — the workflow already
worked for duplex-dominated designs; only substantial floppy ssDNA tripped it. Pin:
`tests/test_cg_seed_ssdna_collapse.py` (hairpin-folds a plain 20-nt overhang; no-fix ~115 near-coincident,
fix ~18; can-go-red in-process). Full end-to-end NAMD relaunch of VoltronCore still owes a test-dedicated
session (heavy GPU) — the deterministic CAUSE of the abort is eliminated. See [[md-job-system]].

---

## 25. Hard surface + anchors + consolidated run + relax-on-surface (SHIPPED 2026-06-18, commit 0dcb838)

Surface-bound floppy origami in oxDNA. **NOT GPU-verified** — all backend file/stage composition is unit-
+ endpoint-tested with the runner/`start_job` mocked; no real CUDA surface relaxation or consolidated run
was executed. New tests in `tests/test_oxdna_surface.py` (backend) + `oxdna_floor_math.test.js` etc.
Backend `just test` 2615 passed / 55 skipped; frontend 1438 passed; smoke green.

### 25.1 Consolidated production run — `POST /oxdna/jobs/{id}/run`
One button composes any combination of **field + hard surface + anchors** as independent elements; branches
a CHILD job from the relaxed parent (fan-out, like the field run). `RunRequest{steps, field?, surface?,
anchors[], anchor_stiff}`. A field with **no anchors is rejected** (unanchored uniform force drifts the COM).
- `oxdna_interface.write_run_forces(... field, wall, anchors)` composes the external-forces file =
  `field_string_block` + `surface_anchor_forces_text` (the shared wall + trap text). `build_run_stage`
  (kind="production", so it pools into RMSD/RMSF). The old `/field` endpoint + `write_field_forces` stay
  (legacy); the frontend routes everything through `/run`.
- Frontend: the panel's Production button reads `getRunElements()` (field=efieldSetup, surface=floorSetup,
  anchors=anchorsSetup) → `api.appendOxdnaRun`. The E-field card is now **spec-only** (`getFieldSpec`→
  {field_pN,dir,enabled}); anchors + the per-card run buttons were removed.

### 25.2 Hard surface (repulsion plane) — render-from-extent
`repulsion_plane_block(stiff, dir, position)` (particle=-1, all nts). Plane height derived from the
**structure's extent** along the normal at run start: `wall_position_from_extent(cm, dir, offset_oxdna)` →
`position = offset_oxdna − min_proj` (works with zero anchors → a bare steric wall is valid). `SurfaceElement
{dir, offset_nm, stiff}`; default stiff=5 (fine once fix_diffusion is off — see §25.5). UI = the "Hard
surface" card (`oxdna_floor_setup.js` / pure `oxdna_floor_math.js`): Apply checkbox + 6-axis side (photo-
floor convention) + offset + stiffness.

### 25.3 Anchors — own card, shared by field + surface
Fixed elements (overhang / cluster / domain / whole strand / individual base → traps) live in the
standalone **Anchors** card (`oxdna_anchors_setup.js`, reuses `efield_math` anchor helpers). Used by field
(required), surface, or alone. Descriptor kinds resolved in `resolve_anchor_particles`
(`oxdna_interface.py`) + `resolveSelectionAnchors`/`anchorKey`/`anchorLabel` (`efield_math.js`) +
`resolveAnchorEntries` (`anchor_glow.js`): `{kind:'overhang',id}`, `{kind:'cluster',id}`,
`{kind:'domain',strandId,domainIndex}`, **`{kind:'strand',id}`** (whole strand — pin an overhang-binding
oligo; select the binder strand → Add anchor), **`{kind:'base',helixId,bp,direction}`** (one nucleotide;
click a bead → Add anchor). `AnchorRef` (routes_oxdna.py) carries the base fields; camelCase persisted.
Added 2026-07-04.

### 25.4 Relax-on-a-surface (surface + anchors during relaxation, NO field)
A structure relaxed free settles differently than one bound to a surface, so relaxation now carries the
surface + anchors (the field is production-only — a field-relaxed structure isn't how it'd settle).
- `CreateOxdnaJobRequest` gained `surface?/anchors[]/anchor_stiff`; the relax button sends them (not field).
- `prepare_oxdna_job(..., surface, anchors)` writes `forces.txt` = mutual_traps **+** surface/anchor blocks
  (via `write_mutual_traps(extra_text=...)`), and a separate `equil_forces.txt` = surface/anchors only
  (equil drops the pair traps but keeps the structure bound). `build_relaxation_stages(surface_present=True)`
  flips the equil stage to carry `equil_forces.txt`.

### 25.5 ⚠ KEYSTONE FIX — `fix_diffusion = false` for absolute-coordinate forces
**The VoltronCore `2_md_relax` explosion.** oxDNA's `fix_diffusion` (default ON) periodically recenters the
COM by a box vector. `repulsion_plane` + `trap` anchors are defined in **absolute coordinates**, so the
recenter shifts the structure while the wall stays put → the wall cuts deep into the structure → enormous
spurious force → cell-overflow blow-up (log: `INFO: diffusion fixed..` immediately precedes the energy
spike). This is the "much more repulsive than intended" symptom — NOT the stiffness.
**Fix:** `OxdnaStageSpec.absolute_forces` → renders `fix_diffusion = false`. Set on surface-bound relax
stages (all 3), the `/run` stage when wall/anchors present, and **every field stage** (their anchor traps
had the same latent drift bug). Mutual-traps-only relaxations are unaffected (relative/PBC traps, diffusion-
fix stays on). Any FUTURE absolute-position force MUST set this flag.

### 25.6 Hard surface renders as the View grid (unified)
One shared `THREE.GridHelper` (`view_tool_buttons.js`): the View "grid" toggle AND the surface viz.
`setSurfaceGrid({enabled, axis, offsetNm})` positions/orients it at the plane (design bbox + side + offset)
and flips the grid button on; disabling resets it to the origin reference grid. The Hard surface card drives
it on enable/axis/offset (`main.js` wires `setSurfaceGrid` via a forward-declared `let _viewToolButtons`).

### 25.7 OxDNA display "Align to design pose" toggle
`GET /oxdna/jobs/{id}/display?align=false` → `read_configuration_unwrapped(..., align=False)` →
`unwrap_align_to_reference` skips the Kabsch superpose (structure made whole + on-screen, but left in its
own frame — how it settled on the surface, lined up with the grid). Default align=true = prior behavior.
UI = `oxdna-jobs-align-toggle` under the display toggle; flipping it re-fetches live.

### 25.8 Panel reorg
Collapsible `.ox-card`s (CSS in `components.css`): **Jobs / Advanced / Anchors / Hard surface / Electric
field / Health**. Loading bar (`oxdna-jobs-progress`) moved ABOVE the Relax/Production buttons; jobs list +
Health pulled out of the hidden `#oxdna-jobs-detail` into their own cards (`_hideDetail()` clears the
relocated bar + health on deselect).

## 2026-06-23 — KEY FINDING: headless relaxation defaults are MOCK-TUNED (10⁴× too few steps) → no re-anneal

Surfaced during the AF-24 design-automation loop. User's domain insight cracked it: *oxDNA drops base-pairing
initially, then RE-ANNEALS over the long md_relax stage.* Verified on CUDA (RTX 2080 SUPER) with oxDNA's OWN `HBList`
(`oxdna_interface.count_hbonds` → `DNAnalysis`) as ground truth.

- **THE BUG:** `headless_oxdna_build.create_job` defaults to **mc=100 / md_relax=100 / equil=100**,
  `min_bp_retained=0.0`, `max_relax_retries=0` — EXPLICITLY mock-tuned (its docstring says a real run "should raise
  the gate to ~0.5" + "pass a positive retry budget"). The STANDARD relax (`oxdna_protocol`/`routes_oxdna` defaults)
  is **mc=1000 / md_relax=1_000_000 / equil=100_000**. The AF Tier-6 builders (`build_field_specimen`/`run_field`)
  inherited the mock defaults → 10⁴× too few md_relax steps → the duplex dropped pairing and never re-annealed. (An
  earlier draft said "the relaxation MELTS a perfect export" — WRONG; an artifact of probing with small EQUAL step
  counts that truncate before the re-anneal.)
- **PROOF the protocol is correct** (`workspace/test343.nadoc` = 42 bp duplex + 7 nt overhang, user's working app
  case, run HEADLESS with STANDARD steps, 217 s GPU): HBList **mc 35 → md 39 → equil 42/42** — drops then RE-ANNEALS
  to perfect 42/42, and `3_equil` (mutual traps OFF) HOLDS 42/42 → the annealed structure SELF-SUSTAINS.
- **The oxDNA EXPORT is flawless** (t=0 HBList 42/42, `a1·a1=a3·a3=−1.00`, backbone bonds 0.785 units) and
  **`base_pair_retention` is SOUND** (agrees with HBList). Neither is the problem.
- **Secondary issue:** the bare `make_minimal_design(1 helix, 42 bp)` CRASHES at md=1e6 — oxDNA cell-list overflow
  (`a cell contains more than _max_n_per_cell (42)`, "box too large"): `box_nm_for_positions` → sparse 50 nm box and
  `render_stage_input` doesn't set `cells_auto_optimisation=false`/`max_density_multiplier`. Use a real-design
  fixture, or add those keys for sparse small systems.
- **`write_mutual_traps` docstring is WRONG** (claims backbones ~1.9 nm apart / unformed; reality 1.05 nm, fully
  bonded). Fix when touched.

**THE FIX (well-understood, NOT ASK-FIRST):** the real-engine path (incl. AF Tier-6) must run a STANDARD-grade
relaxation (mc≈1000, md_relax≈1e6, equil≈1e5, `min_bp_retained≈0.5`, `max_relax_retries>0`) on a real-design
fixture, not the mock defaults. Repro: scratchpad `af24_standard.py` (test343 standard relax), `af24_duplex.py`,
t=0 HBList/orientation probes. Full write-up: `design_automation_log.md` difficulties ledger "AF-24 ROOT-CAUSED".

## 2026-07-02 — bp-MELT now escalates the relax ladder (was a hard fail) + SQ seed characterised

Triggered by a user report: `workspace/2x6_triple_strut.nadoc` (2610 nt, **SQUARE** lattice) "fell apart at md_relax".
Job `workspace/oxdna_jobs/333e9682f27c`: oxDNA ran clean ("everything went OK") — a HEALTH-GATE fail, not a crash.
Per-stage bp (measured on the saved confs): **seed 100% → mc 97% → md_relax 39%** (oxDNA HBList read 24%; both < 50% gate).

- **Root cause = the §2026-06-23 re-anneal phenomenon.** oxDNA drops pairing early then re-anneals over a LONG
  md_relax. The run used `md_relax_steps=100_000` (the user hand-lowered it for speed; both backend & frontend
  DEFAULT to 1_000_000) — 10× short of re-anneal, so it dropped pairing and never recovered. Not a real melt.
- **Retry-ladder gap FIXED (`oxdna_runner.py`, ~L1073).** A bp-melt (or non-finite blow-up) at md_relax was a HARD
  FAIL — only FENE-not-ready escalated. Now a failing md_relax health gate routes through the SAME
  `_escalate_relax_and_rewind` ladder (steps ×{3,6,10}, dt→0.001) when `relax_retries < max_relax_retries`; exhausting
  the budget fails with a melt-specific message ("could not hold the structure together after N escalating attempt(s)").
  **Quickness preserved:** the fast default runs first; only a failed melt pays. And the ×10 rung takes a 100k base to
  **exactly 1e6** = the proven re-anneal count, so an auto-escalated 100k run reaches standard grade on retry 3.
  Tests: `test_run_job_recovers_from_md_relax_bp_melt`, `test_run_job_fails_after_exhausting_melt_retries`.
- **SQ native seed characterised (NOT the proximate cause).** `oxdna_native_seed_map`'s uniform inward-along-a1 shift
  gives a FENE-CLEAN seed on honeycomb (6hb/18hb: fene_over=0, max 0.785) but leaves **~140 backbone bonds over the
  1.006 cliff on this SQ design** (max ~1.7 units; the saved job's conf read 103 / 3.588). Almost certainly the
  crossover backbones — the intra-duplex narrowing shift doesn't fix SQ's 90° inter-helix crossover spans. MC relax
  neutralises it (fene→0, bp 97%), so it did NOT trigger the melt. Seed docstring's "REMOVES the FENE over-stretch"
  claim is HONEYCOMB-ONLY — improving the SQ seed (crossover-aware shift) is a real but separate ASK-FIRST geometry job.
- **Also fixed this session:** the "View error log" button did nothing — `_showErrorLog` built the modal but never
  called `modal.open()` (`frontend/src/ui/oxdna_jobs_panel.js`). One line + regression test.

## UPDATE 2026-07-09 — WSL CUDA segfault (`rc=-11` / md_relax) root-caused: native NVIDIA driver shadowing

**Symptom:** every GPU oxDNA job (any design, incl. the corner_miter_optimized fold + previously-passing
6hb_curved) died `rc=-11` (SIGSEGV) at the FIRST MD force step of `2_md_relax`, right after
`INFO: Initial kinetic energy: …`. Job error: `oxDNA failed for 2_md_relax (rc=-11)`. CPU backend ran the
identical input fine — so NOT the config, NOT the traps, NOT precision, NOT the neighbor list (tested all).

**Root cause (environmental, not code):** a LAMMPS setup ran `apt install nvidia-cuda-toolkit` (2026-07-02
14:30, AFTER the last good GPU run at 11:16). That pulled in **`libnvidia-compute-535`** — a *native Linux*
NVIDIA driver userspace package — which dropped `/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.535…`
(+ `libcuda.so.535`, CUDA-12 runtime) and registered them in the ldconfig cache. In WSL the GPU is reachable
ONLY through the Windows-driver passthrough libs in `/usr/lib/wsl/`. oxDNA (built w/ CUDA 13.3, driver ceiling
13.2) JIT-compiles its embedded PTX at the first kernel launch and grabbed the **mismatched native 535 JIT
compiler** instead of the driver-matched one in `/usr/lib/wsl/drivers/<inf>/` (that dir is NOT on the ldconfig
path, so it loses) → SIGSEGV. Diagnosis nailed with `LD_DEBUG=libs` showing
`calling init: /lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.1`.

**Fix (shipped, no sudo, keeps LAMMPS packages):** `oxdna_runner.oxdna_subprocess_env()` prepends the active
WSL driver dir (newest `/usr/lib/wsl/drivers/*/` that ships `libnvidia-ptxjitcompiler.so.1`, via
`_wsl_gpu_driver_dir()`) to `LD_LIBRARY_PATH` for the oxDNA child process, so the driver-matched CUDA/JIT libs
win. Passed as `env=` to the single `create_subprocess_exec` in `_run_oxdna_async`. Returns None off WSL / when
absent → child inherits `os.environ` unchanged. Verified: corner md_relax GPU run → `rc=0`, "everything went
OK!". Tests: `test_wsl_driver_dir_picks_newest_with_jit`, `test_subprocess_env_prepends_driver_dir`,
`test_subprocess_env_none_off_wsl` (test_oxdna_relaxation.py, 209 green).

**Cleaner system-level alternative (needs user sudo, not required):** `apt remove nvidia-cuda-toolkit
libnvidia-compute-535` (Ubuntu's meta-pkg should never be installed in WSL — use the `cuda-toolkit-13-3`
packages + WSL driver for LAMMPS). The LD_LIBRARY_PATH fix makes this optional. See [[project_lammps_oxdna]].

**Post-removal reality (2026-07-09):** the user ran that `apt remove`, but it did NOT clear the shadow —
`libnvidia-compute-535-server` is still installed and STILL ships `libnvidia-ptxjitcompiler.so.535` +
`libcuda.so.535` in `/lib/x86_64-linux-gnu`, so a BARE oxDNA GPU run still segfaults (`rc=-11`) and the code
fix stays load-bearing (verified: bare rc=-11, with-fix rc=0). The removal broke NO engine — only two pkgs
went (`nvidia-cuda-toolkit`, `libnvidia-compute-535`), no cascade; every engine binary's `ldd` is clean
(oxDNA/DNAnalysis→cuda-13.3, NAMD/ARBD/anm-oxDNA/lmp self-contained or WSL-driver), CUDA-12 runtime
(`libcudart.so.12`/`libcublas.so.12`, needed by the KOKKOS+GPU LAMMPS) still present, cuda-13.3 intact.
NAMD-CUDA enumerates the GPU via the WSL driver WITHOUT loading the JIT compiler (native sm_75 SASS) → not
affected by the shadow. To fully purge the shadow the user would also need `apt remove
libnvidia-compute-535-server`. If any OTHER GPU engine (LAMMPS-GPU/ARBD/mrdna) is ever seen to segfault the
same way, the identical env fix applies — factor `oxdna_subprocess_env`'s driver-dir logic into their runners.

## §26. Fast CG→atomistic display (vectored per-nucleotide stamp) — SHIPPED 2026-07-14

The relaxed-display atomistic rep no longer serialises every atom's XYZ per frame. The all-atom
placement is, per nucleotide, a **fixed local template rigidly stamped by that nucleotide's frame**
(`world = origin + R·local`, `_atom_frame`), except a ~24% non-rigid minority (backbone-closure
linkers `O3'/P/O5'/OP1/OP2`, crossover/skip bridges, extra-base inserts, extension tails, proteins).

- **`build_atomistic_model(..., frame_sink=dict)`** ([atomistic.py](../backend/core/atomistic.py)) —
  out-param records `{(h,bp,dir,copy): (origin, R)}` from the ONE authoritative loop (no second
  code path → zero placement drift). Requesting a `frame_sink` forces the full loop (skips the
  cached-reference fast return).
- **`atomistic_stamp_descriptor(design)`** (cached by topology hash) — design-fixed: per atom serial,
  rigid (its template-local coord + nucleotide index) vs non-rigid. Classified EMPIRICALLY from ONE
  `close_backbone=True` build: non-rigid iff built pos deviates >1e-6 nm from its stamp (closure
  moves linkers ~1 Å; ring/base atoms sit exactly on the stamp).
- **`oxdna_health.display_frames_payload(design, frame)`** — compact per-frame payload
  `{frames:[12·n_nuc] (origin+R, deformation folded via 4-marker `apply_deformations_to_atoms`),
  nonrigid_xyz:[3·k]}`. Runs the authoritative `build_display_model` once (memoised); non-rigid
  coords are byte-exact from `model.atoms`.
- **Routes** ([routes_oxdna.py](../backend/api/routes_oxdna.py)): `GET .../atomistic-stamp` (once/job),
  `POST .../display-atomistic-frames`. **No MD mirror** — NAMD heavy rep is direct-atom from PSF/DCD.
- **Frontend**: [scene/atomistic_stamp.js](../frontend/src/scene/atomistic_stamp.js) pure
  `expandStampFrames(descriptor, frame)` → flat Float32 (serial-indexed) → the SAME
  `atomistic_renderer.applyPositionLerp(flat, flat, 0)`. Wired in
  [ui/oxdna_display.js](../frontend/src/ui/oxdna_display.js) `_relaxedAtomisticFlat` (relaxed mode
  only; rmsf/trajectory still on the legacy route — Phase 3). Falls back to the legacy full-flat
  route when the stamp endpoints are absent (e.g. the MD viz adapter → its atomistic branch stays a
  no-op as before).
- **Validated**: golden parity `tests/test_atomistic_display_split.py` (slow[atomistic]) + live real
  jobs → reassembly matches `frame_atomistic_flat` to **5.5e-6 nm**.

### §26b. The REAL latency fix (2026-07-14) — the payload split was NOT the bottleneck

User tested on VoltronCore (14774 nt): "native loads, then ~5 min later the oxDNA display positions
appear." Profiling `build_display_model` showed the 58 s build is **~42 s of L-BFGS-B backbone-bridge
minimisation** (`_minimize_backbone_bridge` at every crossover/skip) — MD-SEED-quality phosphate
geometry, pointless for a viewer. The per-frame TRANSFER (what the split shrank) was never the cost.

Fixes (user-approved; all display-only, never touch MD seeds / PDB export / topology):
- **`fast_bridges` param on `build_atomistic_model`** — swaps `_minimize_backbone_bridge` for the cheap
  `_interpolate_backbone_bridge` (already the minimiser's x0). **6.2× faster build (34 s→5.5 s)**; only
  the ~1.5% phosphate-linker atoms move (≤2.4 Å at junctions, invisible at scale). Threaded through the
  two direct crossover/skip sites + `_build_extra_base_atoms`/`_build_extension_atoms` (`bridge_fn`).
  Default False. ON for: `build_display_model`, the descriptor, `GET /oxdna/jobs/{id}/atomistic-model`,
  and **`GET /design/atomistic`** (the "native flash" renderer source — every atomistic view is 6× faster).
- **`atomistic_display_bundle(design)` + `GET /oxdna/jobs/{id}/atomistic-display-bundle`** — ONE build
  serving BOTH renderer topology (atoms+bonds) AND the stamp descriptor, **disk-cached per job**
  (`job_dir/atomistic_display_bundle.json`, keyed by topology_hash). Frontend `_ensureJobAtomistic`
  fetches it (descriptor rides along) instead of separate model + stamp fetches. `_classify_stamp` is
  the shared classifier.
- Net VoltronCore: first switch **~5 min → ~25 s** (`/design/atomistic` ~6 s + bundle ~13 s cold/~4 s
  disk + frames ~6.5 s); repeat switches near-instant (bundle cached frontend-side, frames memoised).
  **STALE as of 2026-07-18** — see §26b-follow-up below; the extensions/extra-bases sim work
  regressed the cold bundle to ~290 s and this fix restores it to ~9.5 s.

### §26b-follow-up. Extra-base minimiser now respects `fast_bridges` (2026-07-18) — cold bundle 290 s → 9.5 s

§26b threaded `fast_bridges` through the crossover/skip phosphate **bridge_fn**, but the per-insert
solvers `_minimize_{1,2,3}_extra_base` (glycosidic + steric-repulsion L-BFGS-B, `atomistic_helpers.py`)
were NOT gated by it. After the extra-bases/extensions SIM work landed, VoltronCore carries **566
extra-base crossovers** → 566 scipy solves → the cold `atomistic_display_bundle` build measured **290 s**
(profiled: `_minimize_lbfgsb` cumulative == whole build; `_cos_angle_grad`/`_repulsion_cost_grad`
dominate). Those native-geometry positions are then **discarded** for a relaxed frame (the `_xb_overridden`
path already rigidly stamps inserts from their oxDNA a1/a3 and skips the minimiser at `atomistic.py:2901`).
Fix: `_build_extra_base_atoms` takes `fast_bridges`; when True and both anchors exist it closes the
phosphodiester linker with the cheap `bridge_fn` interpolation instead of the minimiser (same as the
already-shipped `n>3` fallback). `build_atomistic_model` passes it through. **Bundle 290 s → 9.5 s**,
atom+bond counts byte-identical (330622/369756), 0 new long bonds on inserts (verified). MD seeds / PDB /
NAMD keep the exact minimiser (`fast_bridges=False`). Regenerated the Con4 + 2hb_xover_val geometry-lock
goldens (they were already stale from committed `91a8eed`, unrelated to this fast-path change).
Plus: **single-flight** on `GET .../atomistic-display-bundle` (`_bundle_build_lock`, per topology hash —
concurrent first-clicks/warm race collapse to one build) and **warm-ahead** — `oxdna_display.displayJob`
fires a fire-and-forget bundle prefetch so the build happens while the user views the CG relaxed structure.
Tests: `test_oxdna_bundle_single_flight.py` (3).

**Atomistic-switch render-ordering (2026-07-18):** the fast path painted the renderer at the bundle's
NATIVE positions (`ar.update`) and THEN awaited the multi-second relaxed-frame build — so native atoms
(extra bases/extensions on their straight arcs) sat on screen for seconds before jumping to sim positions.
Fixed by splitting fetch from render: `_ensureJobAtomistic` fetches topology only (holds it in
`_pendingTopoModel`), and `_applyJobTopology` + `applyPositionLerp` run in ONE synchronous tick inside
`_pushAtomistic` so native never paints. Pin: `oxdna_display.test.js` "does NOT paint … before the
relaxed frame arrives".

**"Full rep flashes back while VDW loads" + VDW skips bonds (2026-07-21).** Symptom: with VDW already
active, turning on an oxDNA display showed the CG Full model for the whole (multi-second) atom build —
users read it as NADOC breaking. Nothing was VDW-specific in the slow path: `repKind` maps `vdw` and
`ballstick` to the same `'atomistic'` branch, so VDW already gets every §26/§26b speedup (and skips bond
cylinders entirely). Two independent causes, both fixed:
- **Visibility.** `atom_surface_display._setCGVisible` poked `getHelixCtrl().root.visible` DIRECTLY,
  leaving design_renderer's `_designVisible` stale at `true`. `displayJob` → `onSurfaceStrands` →
  `setExtraNucleotides` → `_rebuild` then allocated a fresh root (visible by default) and — uniquely
  among `_rebuild` call sites — never re-applied the hidden state, so the CG popped back until
  `onHeavyApplied` fired at the END of `_pushAtomistic`. `_setCGVisible` now goes through
  `designRenderer.setDesignVisible` (single source of truth) and `setExtraNucleotides` re-applies
  `_designVisible` after its rebuild, like every other call site. Pin: `atom_surface_display.test.js`
  "a rebuild after setCGVisible(false) leaves the CG hidden" (verified failing against the old code).
- **Spurious rebuild.** `surface_strands_overlay._draw` builds a fresh `let chains = []` each call and
  `createSurfaceStrandEmitter` compared by IDENTITY, so a job with NO capture strands triggered a full
  CG rebuild on every `displayJob`/`stopAndRestore`. Empty→empty is now compared by emptiness.
- **`bonds=false` on the bundle route.** VDW draws no cylinders; the bond list is ~370k pairs / 6 MB of
  the 124 MB bundle. The blocking fetch now asks for `bonds=false`, the warm-ahead prefetch too (the
  DISK cache always stores the full bundle, so nothing rebuilds). `_atomTopoBonds` tracks whether the
  held topology carries bonds; `_warmBonds()` pulls them in the background after a VDW push so a later
  vdw→ballstick flip repaints from the held model instead of stalling — without it the flip would show
  stickless ball-and-stick for seconds.

### §26c. Columnar/binary atomistic bundle — SHIPPED 2026-07-21. 129 MB → 17.9 MB, parse 899 ms → 13 ms

The measured remaining stall was the payload, not the GPU: `atomistic_display_bundle.json` is **129 MB**
for VoltronCore (330,622 atoms as verbose per-atom dicts = **112 MB**, ~340 B/atom; bonds only 6 MB), and
`JSON.parse` materialises 330k JS objects before anything draws. The surface mesh had already gone binary
(`display-surface-bin`) and the frames compact (§26 stamp); the atom topology was the last holdout.

- **`pack_bundle_bin(bundle)`** ([atomistic.py](../backend/core/atomistic.py)) — pure function over the
  dict the disk cache already holds, so there is still exactly ONE build path. Drops `serial` (asserted
  dense 0..n-1 → it IS the row index, which is also what lets the serial-keyed relaxed frames be indexed
  directly), drops the **seven fields no frontend code reads** (`name`, `residue`, `chain_id`, `seq_num`,
  `is_modified`, `crossover_id`, `extra_base_k` — ~40% of the atom payload), and interns the five string
  fields (a whole origami has ~200 strands / ~60 helices / 2 directions / 4 elements) to u8/u16 indices +
  tables in a small JSON header. Raises `BundleNotPackable` on any invariant break → route 409s → client
  falls back to JSON. **`atom_nuc` is i32, not u32** — `-1` is expandStampFrames' non-rigid sentinel.
- **`GET .../atomistic-display-bundle-bin`** ([routes_oxdna.py](../backend/api/routes_oxdna.py)) with its
  OWN disk cache `atomistic_display_bundle_{thash[:16]}.bin` (hash in the filename → self-invalidating).
  Both bundle routes now share `_atomistic_bundle_ctx` / `_atomistic_bundle_cached`.
- **The blob is packed at BUILD time**, off the in-memory bundle (`_write_atomistic_bin_cache`, called from
  `_atomistic_bundle_cached`'s persist step) — so the normal path NEVER reads the 129 MB JSON cache. Packing
  lazily on the first bin request instead cost ~1.4 s reparsing that JSON just to throw the dict away.
  Falling through to a repack in the bin route is now only the one-time migration for a job whose JSON cache
  predates this format; it writes the blob so it happens at most once per job. The 9 existing jobs were
  pre-packed by hand, so nothing pays it interactively. Cache reads/writes also moved to **orjson** (a
  declared dep; 1.39 s → 0.91 s on the 129 MB file) for the paths that still touch JSON.
  Measured after: **~50 ms** for every job's bin request on a cold server.
- `pack_bundle_bin` validates the required atom fields up front and raises `BundleNotPackable` rather than
  letting a `KeyError` escape — a malformed bundle must degrade to the JSON fallback, never a 500.
- **Frontend**: [scene/atomistic_bundle_bin.js](../frontend/src/scene/atomistic_bundle_bin.js) decodes to
  typed-array views (mirrors `surface_bin.js`); [scene/atom_table.js](../frontend/src/scene/atom_table.js)
  is the new seam — **`makeAtomTable(data)` accepts EITHER the columnar payload or a legacy object array**,
  so the six other `atomisticRenderer.update()` producers (design atomistic, protein, instance, filtered
  subsets, baked NAMD frames, live MD websocket) needed no change at all.
- **`atomistic_renderer` now stores atom ROW INDICES, not objects** — `elementAtoms[el]` is an `Int32Array`
  and `bondAtomPairs` (370k `{a,b}` object pairs) became a flat `bondAtomIdx` `Int32Array`.
  ⚠️ **Flyweight contract**: for a columnar table `table.get(i)` returns a SHARED mutable view, valid only
  until the next `get()`. `raycastPick` therefore uses `materialize(i)` — its result escapes to
  `selection_manager`/`main.js`. On the object-array path `get()` returns the real record, so a violation
  of this is INVISIBLE on the design/protein/MD paths and only corrupts the oxDNA bundle. Read the header
  comment in `atom_table.js` before touching any renderer loop.
- **Validated at full scale** (not just unit fixtures): decoded the real 17.9 MB blob for job
  `fb83ff00287a` and cross-checked all 330,622 atoms against the JSON bundle → **0 field mismatches**,
  max |Δxyz| **3.8e-6 nm** (f32 rounding, below §26's already-accepted 5.5e-6 nm stamp parity), all
  369,756 bonds identical, all 102,608 non-rigid sentinels preserved. Live route: **129 MB / 3.7 s →
  17.9 MB / 0.06 s** warm (2.9 s cold repack, then cached). Client-side **decode 13 ms vs JSON.parse
  899 ms**.
- Tests: `tests/test_atomistic_bundle_bin.py` (10, fast — includes an independent re-implementation of the
  decoder so a layout drift on either side fails) + `frontend/src/scene/atomistic_bundle_bin.test.js` (7,
  pinned against a **real backend-encoded blob** so the two languages are checked against each other).

**Extra-base / extension CG snap (2026-07-18):** switching atomistic→FULL left `__xb__` extra-base beads
(and `__ext_` tails) stuck at NATIVE while the duplex stayed relaxed — PERSISTENT. Root cause (NOT a
`_rebuild`): `setCGVisible(true)` → `unfold_view.refreshArcVisibility()` → `_updateArcPositions(0,…,null)`
→ `design_renderer.updateExtraBaseArc(...)`, which drove the `__xb__` beads onto the NATIVE Bezier and —
unlike `applyClusterCrossoverUpdate` — never consulted `_simXbByCrossover`. Backend is clean (the frame
serves relaxed positions for all 102608 non-rigid atoms; verified). Two-part frontend fix, both display-only:
(1) `updateExtraBaseArc` now short-circuits to `setExtraBaseInstanceFromSim` when `_simXbByCrossover` has the
crossover (mirrors `applyClusterCrossoverUpdate`) — pins `__xb__` under any arc driver (rep switch, unfold,
deform); (2) `oxdna_display.reapplyForRepr` re-applies the cached relaxed overlay (`_lastCgUpdates`) when a
CG rep is restored, re-pinning `__ext_` tails (helix-mesh beads) and any other overlay-dropped bead.
Pin: `oxdna_display.test.js` "re-applies the relaxed CG overlay when a CG rep is restored". Frontend 3018
green. NOT yet visually confirmed in the running app.
- **Native-flash skip (2026-07-14, DONE):** switching full→atomistic while an oxDNA overlay is active
  in a mode that reconstructs atomistic (relaxed/rmsf/trajectory — NOT live/deviation, which are
  CG-only) no longer builds+shows the DESIGN atoms first. `atom_surface_display._applyAtomisticMode`
  defers (keeps relaxed CG up, skips the design fetch) when `getSimOverlayWillDriveAtomistic()` →
  `oxdnaDisplay.drivesHeavy()`; the overlay hides CG when its atoms land via `onHeavyApplied`.

### §26c. ssDNA overhangs mis-placed in the atomistic display (2026-07-14, FIXED)

User (VoltronCore +z view): the atomistic rep put the green ssDNA overhangs (and cluster edges) in
different positions than the CG "expected" display. Diagnosis: **547/14774 nucleotides >10 Å off, worst
~74 nm; 81% are ssDNA** (51% of all ssDNA). Cause: the DISPLAY placement is AXIS-DERIVED
(`_frame_atomistic_overrides` fits `deformed_helix_axes`, `_atom_frame` measures each base's radial vs
that centerline). Floppy UNPAIRED ssDNA has no helix to fit → garbage centerline → atoms flung tens of
nm off. The CG bead display places beads DIRECTLY at the oxDNA backbone site → always right (why they
diverged).

Fix — `oxdna_health._ssdna_frame_override(frame)`: for UNPAIRED real nucleotides (no WC partner at
`(helix,bp,other_dir)`) build the a1/a3 rigid-frame override `{key:(CM,a1,a3)}`; `build_display_model`
passes it as `frame_override`, so ssDNA is placed by the calibrated `_oxdna_rigid_frame` stamp (which
lands atoms at the relaxed pose) while paired duplex stays on the axis path (correct WC pairing). The
a1/a3 stamp was rejected for DUPLEX (collapses WC C1'–C1') — but ssDNA has no pair to collapse, so it's
exactly right there. **VoltronCore: ssDNA max 737 Å → 44.5 Å (median 6.5 Å); duplex max 364 → 38 Å.**
Stamp reassembly still matches `frame_atomistic_flat` to 5.5e-6 nm (fast path carries the fix; the
descriptor is topology-fixed, unaffected).

**Cluster double-transform (2026-07-14, FIXED — same session):** the 2×3 cluster shifted ~3.2 nm
full→atomistic. Cause: `build_display_model` ran `build_atomistic_model` with the DEFAULT
`apply_design_geometry=True`, re-applying the design's cluster/deformation rigid transform on top of
sim positions that ALREADY include it (the CG bead display applies none → they diverged by exactly the
cluster transform). Fix: `build_display_model` now passes **`apply_design_geometry=False`** (the sim
frame is the final deformed+clustered world; the axis is fit from it) and `display_frames_payload`
dropped its now-redundant deformation/cluster G-fold (markers). **VoltronCore cluster duplex: median
32 Å → 3.8 Å, max 38 → 12.9 Å**; non-cluster unchanged; parity 5.5e-6 nm. Applies to ALL display
builds (legacy display-atomistic, surface, audit) — a strict fix for clustered/deformed designs, no-op
otherwise. NB the seed path already used False for the identical "don't double-apply" reason (see
`build_atomistic_model` docstring ~L1617).

- **Still open:** first-switch ~25 s (one authoritative build + 300k-atom JSON/mesh) — precompute or a
  lean frames-only build would push toward instant. See [[project_md_viz_tools]].

### §27. Surface-display speedups (2026-07-15)

Surface has NO per-nucleotide decomposition (it's one global marching-cubes mesh), so the atomistic
stamp trick doesn't apply. VoltronCore first view was ~14 s + a ~46 MB JSON mesh. Profile:
`build_display_model` ~6 s (shared, Atom-object creation) · `compute_surface` 4.6 s (binary_erosion
1.8 · marching_cubes 1.1 · strand KDTree 0.8 · grid 0.6) · `smooth_mesh` 1.5 s. Four wins shipped:

- **Adaptive grid** (`surface.adaptive_grid_spacing`, cap `_ADAPTIVE_VOXEL_CAP=3.5M`) — coarsen the
  occupancy grid on LARGE structures (0.20→~0.31 nm on VoltronCore) so voxel count stays bounded.
  Compute ~4.6→~2 s, mesh 723k→337k verts, invisible at 10-100 nm scale. Small designs keep 0.20.
- **`close_backbone=False` for surface** — a VdW envelope needs atom positions, not connected
  phosphate linkers; skips the closure (`build_display_model(..., close_backbone=…)` param).
- **Binary mesh transfer** — `oxdna_health.pack_surface_bin` + `POST .../display-surface-bin`
  (`Response` octet-stream: u32 magic/nVerts/nFaces/colorKind · f32 verts · u32 faces · u8 rgb | f32
  rmsf; nVerts=0 ⇒ not ready). Frontend `scene/surface_bin.js parseSurfaceBin` wraps the buffer as
  typed arrays — **no million-number JSON.parse** and ~2× smaller (VoltronCore 30→13.6 MB). Wired in
  `oxdna_display._relaxedSurfaceMesh` (binary-first, JSON fallback for the MD adapter). rmsf/traj
  surface still JSON (follow-on).
- **Native-flash skip for surface** — `atom_surface_display._applySurfaceMode` defers to the overlay
  (keeps relaxed CG up, skips the `/design/surface` design build) when
  `getSimOverlayWillDriveHeavy()` (renamed from `…Atomistic`; covers atomistic+surface) → the overlay
  hides CG when its mesh lands (`_pushSurface`→`onHeavyApplied`). Loading toast now covers
  `kind==='surface'` ("Computing surface…") via the heavy-status listener.

Net VoltronCore: ~14 s + 46 MB JSON → **~9.4 s + 13.6 MB binary**, repeat views cached. Floor is the
shared ~6 s all-atom build (a positions-only build would trim it — same open item as atomistic).

**Surface-defer render bug (2026-07-15, FIXED same day):** the native-flash skip broke surface
rendering — `surface_renderer._mode`/`_mesh` are set ONLY by `update(data)`, and the defer path
`return`ed before it, so the renderer stayed mode 'off' with no mesh and `_pushSurface` bailed → the
surface NEVER drew (looked like it "took forever"; toast dismissed because the build finished without
drawing). Fix: the defer path now `surfaceRenderer.update({vertices:[],faces:[]}, colorMode)` to
activate mode 'on' + an empty mesh the overlay's `applyPositionLerp` populates (mirrors how the
atomistic defer sets `atomisticRenderer.setMode()` up front). The "extra-bases at native" the user saw
was the flexible crossover-arc overlay (`flexible_arcs.setRepresentation` shows only for full/beads →
hidden in surface, revealing the geometric arc) while the CG lingered during the broken never-render
state — moot once the surface draws and `onHeavyApplied` hides the CG. Predicate renamed
`getSimOverlayWillDriveAtomistic`→`…Heavy` (covers atomistic+surface).

**Surface probe-radius on an overlay (2026-07-15, FIXED):** changing probe radius while a sim overlay
owned the surface called `_applySurfaceMode` → the defer path → blanked to an empty mesh (reverted to
CG) and never regenerated, AND the overlay surface fetch ignored the sidebar params. Fix: when
`getSimOverlayWillDriveHeavy()`, the probe/colour-mode change calls `onSurfaceParamsChanged` (→
`oxdnaDisplay.reapplyForRepr`, DEBOUNCED 250 ms in main.js since each rebuild is seconds) instead of
`_applySurfaceMode`; `oxdna_display._relaxedSurfaceMesh` now passes `getSurfaceParams()`
(`{probe_radius, color_mode}` from `atom_surface_display`) to the surface fetch, and the route's cache
key already includes them → new probe = rebuild. Verified: probe 0.28→0.6 gives 337k→252k verts.

**Rep persistence on sim-display OFF (2026-07-15, FIXED + audited):** turning the sim display off while
in a heavy rep (surface/atomistic) reverted the display to CG/full. Root cause (a native-flash-skip
regression): `oxdna_display.stopAndRestore` called `_restoreHeavy()` (→ `onRestoreDesignHeavy` →
`_restoreDesignHeavy` → `applySurfaceMode/applyAtomisticMode`) BEFORE clearing `_active`/`_mode`, so
`drivesHeavy()` still returned true and the restore's applyMode DEFERRED — blanking the design
surface/atoms and leaving the CG up. Fix: clear `_active=false; _mode=null; _jobId=null` FIRST, then
restore. Also removed the `_heavyActive` gate on `onRestoreDesignHeavy` (self-gates on
getMode/getSurfaceMode) so turning off DURING the deferred build (before the overlay pushed, when
`_heavyActive` is still false) also restores the design heavy rep instead of leaving the CG up.
**Rep-persistence audit** (surface/atomistic/full × sim on/off): sim-OFF in heavy rep → FIXED (design
heavy shown, rep persists); switch sim mode (relaxed↔rmsf↔traj) in heavy rep → persists (brief
design-heavy rebuild between, pre-existing, could optimise); switch rep while sim on → intended change
(reapplyForRepr); turn sim ON in heavy rep → persists (sim heavy); deviation/live in heavy rep → NOT a
revert but CG-only modes don't reconstruct the heavy rep (heavy shows design — known limitation).
No store-level rep reset in any off/panel path (`setCGVisible(true)` at atom_surface:85 is
`applySurfaceMode('off')` = leaving surface rep, an intended change).

**DESIGN surface was still the OLD slow path (2026-07-15, FIXED):** toggling the sim surface OFF shows
the DESIGN surface via `GET /design/surface` (`routes_display_geometry.get_surface`) — a SEPARATE route
from the oxDNA-overlay surface, and it had none of the optimizations, so Off was ~37 s vs the overlay's
~9 s. Fixed by giving it the same `fast_bridges=True` build + `adaptive_grid_spacing` (VoltronCore
37 s→6 s, 6×). Still JSON (not binary) — its ~30 MB transfer is the only remaining gap vs the overlay's
13.6 MB binary; add a `/design/surface-bin` + frontend `_ensureSurfaceData` binary path if it matters.
NB the STL-export route builds its own model (exact geometry) — unaffected by the display fast_bridges.

**CG-bead surface = the real speedup (2026-07-15):** profiling showed the all-atom REBUILD (~300k
`Atom` objects + per-nucleotide numpy overhead) dominates, and it's wasted — at the ~0.3 nm display grid
individual atoms aren't resolved (subsampling atoms 8× → 1.6 Å envelope change). So the DEFAULT surface
now rasterises ~2 coarse spheres/nucleotide (backbone + base, `bead_radius=0.5 nm`) straight from the CG
geometry / relaxed frame — NO all-atom rebuild. `surface.cg_surface_mesh` + `make_cg_bead`;
`oxdna_health._cg_beads_from_frame` (backbone via `oxdna_backbone_site`, base ≈ CM+a1·0.34 nm) +
`_strand_id_map`; design beads from `_geometry_for_design` in `get_surface`. Envelope within ~2.8 Å of
the all-atom surface (< the grid's own spacing) — ChimeraX-style low-res. **VoltronCore: design surface
6 s→1.4 s (4×), sim surface 9.4 s→4.8 s (2×).** A `detail` param ('coarse' default | 'fine' = exact
all-atom) on `frame_surface_json` + `get_surface` + `OxdnaSurfaceBody`; frontend **"High detail"
checkbox** (`cb-surface-highdetail`) in the Surface-options sidebar threads `detail` via
`getSurfaceParams` (overlay) + the `/design/surface` URL. Coarse mesh is slightly bumpier/bigger (CG
beads) — raise `CG_BEAD_RADIUS_NM` toward 0.55-0.6 if it reads too bumpy. Still open: sim-coarse's
`_strand_id_map` (_geometry_for_design ~0.6 s) + per-nuc `oxdna_backbone_site` are the residual overhead.

### §27b. Vectorized fine-surface build + design-surface binary transfer (2026-07-15)

Two follow-ons to §27, both validated by a new visual-regression suite.

- **Surface visual-regression tests** (`tests/test_surface_visual_regression.py`, slow+atomistic;
  6hb stays fast). `surface_hausdorff(meshA, meshB)` (symmetric cKDTree vertex distance,
  mean/p99/max) + `mesh_volume`/`mesh_area` oracles; panel = 6hb · 18hb_routed · VoltronCore
  (`workspace/oxdna_jobs/154d3ea291b7/design.json`, skips if absent). Pins: fine-surface
  determinism (rebuild → 0 Å), vertex/face/volume/area invariants (±8%/±5% bands), coarse-vs-fine
  characterization (~2.8 Å mean), and a provably-red perturbation test. **These gate the vectorized
  build** (`test_vectorized_fine_surface_matches_exact_build` + a deformed case).

- **`atomistic.surface_atom_cloud(design) → (positions, radii, strand_ids)`** — vectorised all-atom
  point cloud for the DESIGN fine surface, no 300k `Atom` objects. `_atom_frames_batch` (the
  per-nucleotide frame math batched over `(N,3)` stacks — **byte-identical** to the locked scalar
  `_atom_frame`, the 37k `numpy.cross` calls collapsed) → einsum template stamp → `_apply_cloud_bridges`
  (the fast_bridges crossover + skip phosphate-linker lerp, array form) → 4-marker deformation/cluster
  fold. `surface.compute_surface_from_cloud` rasterises it (occupancy grid grouped by radius; **must**
  pad the bbox by `max(VDW_RADIUS.values())×scale` like `_build_occupancy_grid`, else the grid shifts
  ~1 Å). **Byte-identical (0 Å) to the exact fast_bridges build on all panel designs**; VoltronCore
  fine build **7.1 s → 0.83 s**, full fine surface ~2.4 s. Wired in `routes_display_geometry.
  _build_design_surface_mesh` detail='fine' via `_can_use_surface_cloud` — designs with
  flexible-ssDNA frames / extra-base crossovers / extension tails FALL BACK to the exact `Atom` build
  (those atoms aren't in the cloud yet — no envelope regression, just no speedup). The relaxed-overlay
  fine surface (`frame_surface_json` detail='fine') was left on the existing path (coarse is its default).

- **`GET /design/surface-bin`** — binary sibling of `/design/surface` (JSON), mirrors the overlay's
  `display-surface-bin`. `pack_surface_bin` extended with an OPTIONAL trailing strand-index block
  (`strand_kind` u32 · JSON id table · u32[nVerts]) so the design surface still recolours client-side;
  the overlay omits it (backward-compatible). Frontend `surface_bin.js parseSurfaceBin` reads the tail
  (alignment-safe `buf.slice` for the index array); `surface_renderer` `_isIndexable` accepts a
  Uint32Array `vertex_strand_index`; `atom_surface_display._ensureSurfaceData` fetches binary-first
  (`api.getDesignSurfaceBin`) with JSON fallback. **VoltronCore coarse design surface 74 MB JSON →
  19.7 MB binary (3.75×)** and no million-number `JSON.parse`. NB the live dev server needs a restart to
  serve the new route; until then the frontend falls back to JSON automatically.

**SURFACE VISUAL QUALITY — experimental "ChimeraX quality" toggle shipped (2026-07-15).**
Root cause CONFIRMED: it was never the SES *algorithm* (compute_surface's dilate→erode closing
IS a valid solvent-excluded surface) nor base-bead placement — it was **grid RESOLUTION**. Both
the coarse default AND "High detail" run through `adaptive_grid_spacing` (cap `_ADAPTIVE_VOXEL_CAP`
3.5M → ~0.31 nm on big designs), which staircases the ~1 nm helical grooves into blobs; even the
all-atom "fine" mesh gets rasterised onto that coarse grid and the atom detail is thrown away.
Proof on the 2hb extra-base test part: coarse=5910 verts, fine=5894 verts (≈identical!), **chimerax
=74711 verts** — 12.7× denser at the same size. New `detail='chimerax'` path (`surface.CHIMERAX_*`
constants + `routes_display_geometry._build_chimerax_surface`, mirrored in `oxdna_health.
frame_surface_json`): FINE all-atom envelope at ChimeraX's 0.5 Å grid + 1.4 Å water probe + TRUE
VdW radii (no display 1.2× inflation), voxel cap 12M (small parts get full res; huge designs
auto-coarsen). Frontend: experimental checkbox `cb-surface-chimerax` in Surface options (overrides
High detail while on; disables it). Test part `workspace/surface_chimerax_test.nadoc` (=Examples/
2hb_xover_atoms_test, extra bases TT/T → exact Atom build, so extra-base atoms included). Params
(`CHIMERAX_GRID_SPACING`/`_PROBE_RADIUS`/`_RADIUS_SCALE`) are ONE-line tunable — pending a 1:1
tune against a NADOC→PDB→ChimeraX SES screenshot from the user. **NOT YET VISUALLY VERIFIED IN
APP** (backend mesh density verified numerically; the rendered look + ChimeraX match is the open
tuning loop). App-side test part is now `workspace/6hbx32.nadoc` (ChimeraX ref = `Examples/6hbx32.pdb`;
PDB exporter was broken so the user exported it manually) — the 2hb was dropped.

**Crisp per-strand colour ZONES (2026-07-15, follow-up).** User feedback: chimerax surface looks
great but strand colours *bleed* into each other vs ChimeraX's sharp boundaries. Cause: per-vertex
strand colours are Gouraud-interpolated, so every triangle straddling two strands blends them into a
one-triangle-wide band. Fix in `surface_renderer.js` (`setCrispZones(on)` + `_buildCrispGeometry`):
in crisp mode the mesh is rebuilt NON-INDEXED with one flat strand colour per face (majority of the
3 corners → boundary falls on a triangle edge), while NORMALS are computed on the shared/indexed
topology and copied to the corners so SHADING stays smooth (ChimeraX "colour zone" look = crisp
colour + rounded shape). `atom_surface_display` turns it on only when `_surfaceDetail==='chimerax'`
(coarse/fine keep Gouraud blending — no default regression). `applyStrandColors`/`strandIdAt` are
crisp-aware. Tests: `surface_renderer.test.js` (5, new).

**Per-STRAND split surface — the real ChimeraX match (2026-07-15, SUPERSEDES crisp-only).** User
feedback with side-by-side: crisp zones removed the colour bleed but the strands were still one
FUSED blob with a jagged seam; ChimeraX's default `surface` builds a SEPARATE surface per chain, so
complementary strands are distinct geometry with a real solvent GAP between them (the double-helix
groove pattern). Fix: `surface.compute_split_surfaces_from_cloud(positions, radii, strand_ids)` —
each strand's atoms get their OWN cropped occupancy grid → dilate/erode by the probe → marching
cubes → Taubin smooth, then concatenate (offset face indices), one strand id per vertex.
`routes_display_geometry._build_chimerax_surface` now calls it (cloud path, or exact Atom build for
extra-base designs). Every vertex is unambiguously one strand → per-vertex colours are already solid
and the separation is GEOMETRIC, so **crisp mode is turned OFF for chimerax** (`setCrispZones(false)`
in atom_surface_display; the crisp renderer code + its 5 tests stay as a general capability). Cost:
ONE marching pass per strand — 6hbx32 (9 strands) = **513k verts / 13.6s**; bounded by a shared
`_SPLIT_VOXEL_BUDGET=90M` split across strands (`eff_cap` floor 500k) so a 200-staple origami
auto-coarsens instead of hanging. NB the internal base-pair kiss (~0.03 Å) is EXPECTED (H-bonded
atoms overlap even in ChimeraX) and hidden in the duplex core; the visible outer backbone ridges are
groove-separated. Tests: `tests/test_surface_split.py` (3, fast). NB per-face crisp colour is crisp
because triangles on the fine mesh are sub-nm (that path is now dormant for chimerax). Interior-cavity
AO shading (also in the ChimeraX ref) is a SEPARATE lever = photo-mode GTAO/SSAO, not added to the
live viewport — flag if the user wants it live.

**Prior framing (superseded by the toggle above).** On a VoltronCore-
size design ChimeraX is about as slow as NADOC but its molecular surface looks markedly better
than ours. User confirmed via ChimeraX. Investigated + ruled out as NON-fixes for the coarse
default: bases ARE included and contribute (removing them shifts the envelope up to ~9.6 Å), but
the outer duplex surface is backbone-defined by physics — pushing the CG base bead toward the
axis is FLAT (coarse-vs-fine ~2.75 Å regardless of displacement 0.3→0.9 nm; it only fills
invisible core), and larger bead radius just fattens away from the true all-atom envelope (0.45 nm
matches fine best). So the quality gap is NOT base-bead placement. Likely levers to explore next
session: true SES/Connolly (rolling-probe reentrant surfaces, not morphological closing on a voxel
grid) · finer/adaptive meshing + better normals/shading · higher grid resolution where afforded ·
matching ChimeraX's probe/vertex-density defaults. A NEW session owns this — this commit's
vectorized build + binary transfer are DONE and shipped; the visual quality is the open item.

> **History.** Experiment narratives, dated UPDATE sections + resolved investigations live in [project_oxdna_relaxation_archive.md](project_oxdna_relaxation_archive.md). Read on demand only.
