# Project: Local oxDNA Relaxation Runner + Display

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

> **History.** Experiment narratives, dated UPDATE sections + resolved investigations live in [project_oxdna_relaxation_archive.md](project_oxdna_relaxation_archive.md). Read on demand only.
