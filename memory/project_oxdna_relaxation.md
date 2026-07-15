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

### 10.1 The seed is a PURE function of the oxDNA positions (fixed 2026-07-11)
A NAMD seed reconstructs each nucleotide from its oxDNA CG frame (CM, a1, a3) and must NOT re-apply any
design-level geometry. `build_atomistic_model` normally ends with `apply_deformations_to_atoms(atoms, design)`
(deformations + `cluster_transforms`); for a seed that would DOUBLE transforms the oxDNA frame already carries
→ the GT_corner_v2 "explosion" (K3). The seed path now calls `build_atomistic_model(..., apply_design_geometry=
False)` so the reconstruction depends ONLY on the oxDNA conf. Pinned by `tests/test_cg_seed_cluster_transform.py`
(cluster rotation/translation/multi-cluster all reconstruct ~1× with WC intact). Guard in
`build_atomistic_model_from_cg_spline` still raises on any >2× span blow-up as a safety net. See [[LESSONS]] K3.

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

**STILL OPEN — surface VISUAL QUALITY (next session's focus, 2026-07-15).** Speed is now
maxed (build 7 s→0.8 s, byte-identical); the remaining gap is *appearance*. On a VoltronCore-
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
