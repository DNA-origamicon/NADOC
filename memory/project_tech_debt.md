---
name: tech-debt-ledger
description: Running technical-debt ledger — code paths flagged for review/removal (with why + supersession). Check when touching a flagged area.
metadata: 
  node_type: memory
  type: project
  originSessionId: a42a916c-90da-4711-b831-59182e249f46
---

Running ledger of known technical debt — code that works today but is flagged for
review or removal. Each entry: location, why it's debt, what supersedes it. Append
new items; strike through (and date) when resolved.

## Open

### DELETE-ON-COMPLETION: legacy OverhangSpec pose overlay + standalone orientation panel (superseded by the duplex CLUSTER)
- **Where / delete when [[overhang-duplex-cluster]] ships end-to-end:**
  - `OverhangSpec.rotation` / `OverhangSpec.translation` (backend/core/models.py) — the
    world-frame per-overhang pose. Superseded by the child `ClusterRigidTransform`
    (`overhang_duplex_driver_id`) whose pose is stored in the driver part's rest frame
    (drift-free). Keep the FIELDS until all `.nadoc` are migrated-on-load; delete the
    OVERLAY application.
  - `apply_overhang_rotation_if_needed` Layer-1 whole-overhang rotation/translation +
    `_apply_ovhg_rotations_to_axes` (backend/core/deformation.py) — the overlay + its axis
    follow. Replaced by the cluster (bead + child-aware axis) path. (Layer-2 sub-domain
    chain rotation may outlive this — reassess.)
  - `patch_overhang_rotations_batch` / `OverhangRotationLogEntry` (crud.py, models.py) —
    the overlay's edit API + feature-log entry. **DO NOT DELETE OUTRIGHT** (scope-corrected
    2026-07-01): `OverhangRotationLogEntry` is DUAL-PURPOSE — whole-overhang rotation (→ cluster
    `ClusterOpLogEntry`) AND per-sub-domain θ/φ (NO cluster equivalent). Keep the type + the
    per-sub-domain path; only whole-overhang-duplex slots migrate. Migrate-on-load still REMAINING
    (see [[overhang-duplex-cluster]] P4).
  - `frontend/src/ui/overhang_orientation_panel.js` + `overhang_orientation_menu.js`
    "Edit/Reset Orientation" — **NOT deleted outright** (scope-corrected 2026-07-01). The panel
    also orients STANDALONE/unconnected overhangs (no cluster exists → gizmo can't cover). Retired
    ONLY for duplex-backed overhangs: the menu now routes those to the cluster gizmo ("Move / Rotate
    duplex" + cluster-identity Reset); standalone overhangs keep the panel. The panel + menu STAY.
  - `direct_relax.relax_direct_binding` currently writes the pose onto `OverhangSpec`
    (re-seat + clash). Migrate to write the child cluster (Phase 1b), then this note's
    OverhangSpec writes go away.
- **Why it's debt:** dual representation (overlay AND cluster) risks double-transform; the
  overlay's world-frame storage drifts when the driver part is rotated after the pose is
  set — the whole reason for the child-cluster rebuild.
- **Guard already in place:** `validate_design` flags a duplex cluster whose driver still
  carries a non-identity OverhangSpec pose (double-transform). `materialize_duplex_cluster`
  clears the pose; `dematerialize` restores it. Do NOT delete until Apply/relax/axis are on
  the cluster AND a migration-on-load converts existing `.nadoc`.

### Stale workspace-fixture test skips instead of running (TODO: re-pin or rebuild fixture)
- **Where:** [tests/test_feature_log_snapshot.py](tests/test_feature_log_snapshot.py)
  `test_delete_workspace_independent_strutted_corner_extrude_scrubs_survivors`.
- **Why it's debt:** the test loads `workspace/2x2_strutted_corner.nadoc`, which is
  **gitignored + untracked** (varies per machine). The local copy was regenerated
  with a different routing/feature-log — it no longer has an `extrude-segment` op
  or the helices `h_XY_0_4`/`h_XY_0_5` the test hard-pins to. As of 2026-06-28 the
  stale `assert feature_log[1].op_kind == "extrude-segment"` was converted to a
  **skip-guard** (skip when the fixture doesn't match the pinned structure) so the
  backend suite stays green. The scrub-on-delete behaviour it intended to test is
  still covered fixture-free by `test_delete_independent_parallel_extrusion_survives`.
- **Fix options:** (a) commit a SMALL tracked fixture + re-pin the test to it,
  (b) rebuild the assertion synthetically (no workspace file), or (c) delete the
  test as redundant. Until then it silently skips when the local fixture has drifted.

### Unimported frontend modules — 5 held, 2 deleted (dead-file sweep 2026-07-25)
A repo-wide sweep found 7 `frontend/src` modules with **zero references** anywhere (no import, no
dynamic/glob import, no `index.html` id, no e2e). Two were deleted; the other five were HELD because
each has a documented reason to exist. Re-check this list before assuming any of them is dead.

- **DELETED 2026-07-25** (git history retains both): `scene/seam_plane.js` (283 ln — was wired, then
  deliberately unwired in `7c5039c` when the Autoscaffold UI was reworked; seam routing lives in the
  backend `seamed_router` now) and `ui/lattice_editor.js` (185 ln — `git log -S` shows main.js NEVER
  imported it in any commit; orphaned by the 2026-04-11 cadnano 2D-editor overhaul that replaced it).
- **HELD — `physics/mrdna_relax_client.js`** (64 ln). Extraction log #63 (2026-06-05) deleted the CG
  Relax panel but *explicitly* left this client intact for later re-wiring; backend `/ws/mrdna-relax`
  still exists. Half-built feature (working backend, never-wired frontend) — see [[project_mrdna_panel]].
- **HELD — `ui/validation_report_panel.js`** (41 ln). NOT dead: `store.validationReport` is populated
  live by every mutation response (`client.js` `_syncFromDesignResponse`), and this is its intended
  renderer. It is item #15 on the [[project_ux_overhaul]] roadmap (clickable rows + severity + jump-to-locate).
- **HELD — `ui/presets_panel.js`** (121 ln). [[project_ux_overhaul]] lists "Preset thumbnails in
  presets_panel.js" under *Deferred indefinitely* — parked by user decision, not abandoned.
- **HELD — `ui/validation_panel.js`** (165 ln). The "dead handedness checkpoint walkthrough";
  [[project_ux_overhaul]] item #15 floats reviving it as "Renderer Checkpoints". Weakest of the holds —
  the one to revisit first if this list is swept again.
- **NOT DEAD — `scene/joint_panel_experiments.js`** (456 ln). A DevTools *console* harness (self-
  documented "Usage (browser DevTools console)") validating `_computeExteriorPanels`, which is **still
  live** at `scene/joint_renderer.js:251`. Unreferenced by design, like `src/debug_snippet.js` (which
  main.js points at in a comment). Do not sweep it as dead code.

**Why this is debt at all:** unreferenced modules read as dead to every future sweep, so each one costs
a fresh investigation. The fix is a decision per file (revive or delete), not another audit.

### Dead `lattice.auto_scaffold(mode=…)` API still referenced by 2 scripts + 1 auto-loaded rule (found 2026-07-30, `/audit-plan`)
The old per-helix router (`auto_scaffold(design, mode="seam_line"|"end_to_end", scaffold_loops=…)`,
`_build_seam_line_domains`, `_expand_helices_for_seam`, `_assemble_dumbbell_path`, `_HC_SCAF_VALID`,
`_route_standard_virt_seg`, `_scaffold_direction_from_helix_id`, `_HC_XOVER_PERIOD`) was **deleted from
`backend/core/lattice.py`**; routing is now shape-dispatched (`auto_scaffold_seamed` / `_matched` /
`_seamless` → `section_router.route_sections` via `has_multisection_helix`). Three stragglers still name
the dead API:
- `scripts/inspect_bp0.py:13,66-68` — imports `auto_scaffold` from `lattice`, loops `mode in ("seam_line","end_to_end")`. **Cannot run** (ImportError). Revive against the new entry points or delete.
- `scripts/gen_examples.py:41-49,183` — imports 6 symbols that no longer exist (only `make_bundle_design`, `make_merge_short_staples` survive) and calls `auto_scaffold(design, mode="seam_line")`. **Cannot run.**
- ~~`.claude/rules/scaffold-and-loops.md`~~ — **FIXED 2026-07-30** (`/audit-plan`): fully re-verified
  symbol-by-symbol and rewritten against the live routers, with a "Removed API — do not resurrect"
  block naming the dead names. Its frontmatter globs were also wrong (`scaffold*.py`/`seamless*.py`
  never matched `seamed_router.py` or `section_router.py`, so the rule failed to auto-load on the
  primary router file) — globs now cover all three routers + both route files.
Also orphaned: `section_router.py:255` `_pull_window_turns` — self-labelled `⚠ WIP — NOT YET WIRED`, called nowhere.

### `CELLS_6HB` / `CELLS_18HB` are copy-pasted with *divergent* geometry (found 2026-07-30, `/audit-plan`)
Both read like shared fixtures — every doc that mentions them says "use `CELLS_6HB` as the minimum test
fixture" — but there is no shared definition. Each is re-declared locally with **different cell lists**:
`CELLS_6HB` in `scripts/inspect_bp0.py:16` `[(0,0),(0,1),(1,0),(1,2),(0,2),(2,1)]` vs
`tests/test_helix_neighbors.py:61` `[(0,1),(0,2),(0,3),(1,1),(1,2),(1,3)]` (also
`scripts/gen_examples.py:56`, `tests/test_overhang_geometry.py:47`); `CELLS_18HB` in 5 more places
(`tests/test_helix_neighbors.py:58`, `experiments/exp06,07,09/run.py`, `gen_examples.py:61`). The two 6HB
variants are not the same shape — one is a bent/L cluster, the other two clean rows — so a test copied
between files silently changes its neighbour graph. Fix = one fixture module; until then, never copy the
name without copying the list.

### Dead `POST /design/auto-scaffold` (unsuffixed) + orphaned matched-ends client fns (found 2026-07-30, `/audit-plan`)
Commit `e9d6750` consolidated the plain endpoint into `-seamed`/`-seamless` (the three live routes are
`routes_scaffold_routing.py:86/112/140`). Stragglers:
- **4 E2E specs still POST the removed path → 404 at runtime:** `frontend/e2e/atomistic_helix_parity.spec.js:41,157`,
  `impostor_beads.spec.js:35`, `atomistic_mode_guard.spec.js:24`. (`e2e/helpers/scene_harness.js:75` already documents
  the removal — the specs just weren't updated.) These are Playwright-only, so they fail silently in the normal loop.
- **`autoScaffoldMatched()` is defined twice and called nowhere:** `frontend/src/api/client.js:1103`,
  `frontend/src/cadnano-editor/api.js:197`. Matched routing is reached *implicitly* — `auto_scaffold_seamed`
  tries `matched_ends=True` first and falls back (`seamed_router.py:1275-1289`), which is why the picker
  says "matched ends when feasible". There is no `value="matched"` radio (only `seamed`/`seamless`, in
  `frontend/index.html:2751/2758` + `cadnano-editor.html:1540/1547`).
- **Stale header comment:** `frontend/src/ui/autoscaffold_picker.js:2` still lists "seamed / seamless / matched /
  advanced-*" while `AUTOSCAFFOLD_MODES` (`:11-19`) has exactly two keys.

### Cadnano-2D-mode stragglers (found 2026-07-30, `/audit-plan` rule sweep)
Turned up while rewriting `.claude/rules/cadnano-2d.md` against the code. All low-stakes but each is
a live trap for the next reader:
- **`design_renderer.clearFemOverlay()` is dead code** — `frontend/src/scene/design_renderer.js:1241`,
  **zero callers repo-wide**. It survived the FEM/XPBD retirement; its doc comment now describes the
  mrDNA relaxed-position overlay instead, and its `_helixCtrl.clearFemColors()` line is gone (no such
  function exists in the frontend). Its `if (!cadnanoActive && !unfoldActive)` guard is the only reason
  to keep it — if nothing revives it, delete the function and drop the guard folklore with it.
- **`PERSP_FOV_DEG = 55` is a hardcoded duplicate** — `frontend/src/scene/cadnano_view.js:40` must stay
  in lockstep with `scene/scene.js`'s camera FOV or the ortho↔perspective switch stops being seamless.
  Nothing enforces it; there is no shared constant.
- **Vestigial 5th init param** — `initCadnanoView(..., _getCrossoverLocations, ...)`
  (`cadnano_view.js:42`) is always passed `null` (`main.js:1542`) and never referenced in the body.
- **`frontend/src/cadnano-editor/` is 10,713 LOC with ~1.6% unit-test coverage** — only
  `element_keys.test.js` + `sequence_layout.test.js` (176 LOC of the 10,512 production LOC).
  `pathview.js` (4977 LOC — second-largest JS file in the repo after `main.js`), `main.js` (2554),
  `api.js` (724) and `sliceview.js` are entirely unpinned. Only 2 e2e specs load the page
  (`autobreak_edges.spec.js`, `cadnano_sliceview_positions.spec.js`).
  ~~Undocumented~~ — **documented 2026-07-30** in the new `.claude/rules/cadnano-editor.md`.
- **Reverse coupling:** `frontend/src/ui/overhang_pathview.js:32-54` imports
  `BP_W/CELL_H/PAIR_Y/GUTTER` **and `STAPLE_PALETTE` + 14 `CLR_*`** from `cadnano-editor/pathview.js` +
  `cadnano-editor/pathview/palette.js`. So editing the *editor's* layout constants or palette silently
  moves the main app's Domain Designer — and pulling 4 numbers out of `pathview.js` drags the whole
  4977-LOC module graph into the main-app bundle.

### `STAPLE_PALETTE` — 3 copies that agree, 1 that doesn't, and 3 comments pointing at the wrong files (found 2026-07-30, `/audit-plan`)
- **Agreeing three-way invariant** (same 12 colours, same order today): `backend/core/constants.py:325-329`
  (`'#rrggbb'`) · `frontend/src/cadnano-editor/pathview/palette.js:85-89` (`'#rrggbb'`) ·
  `frontend/src/scene/helix_renderer/palette.js:23-26` (`0xrrggbb` ints).
- **Every one of the three "keep in sync with…" comments names a file that no longer holds the constant**
  (`palette.js:83-84`, `constants.py:324`, `helix_renderer/palette.js:21-22` — the last points at
  `cadnano-editor/pathview.js`, stale since the extraction to `pathview/palette.js`).
  `scene/helix_renderer.js` only *imports* `STAPLE_PALETTE` (`:33`, used `:2719/2848/2907`) — it has
  not defined it for some time, yet two docs and one code comment still say it does.
- ~~**A fourth copy that is NOT in sync:** `frontend/src/ui/spreadsheet.js:54-60`~~ — **FIXED 2026-07-30.**
  It declared a module-private `STAPLE_PALETTE` with **completely different colours**
  (`#e06c75 #98c379 #d19a66 #61afef …` — an editor syntax theme) under the false comment
  `// Staple palette (mirrors helix_renderer.js)`. Because `paletteColor` is the last-resort fallback in
  `effectiveColor`, every staple arriving with `color === null` (the normal case — **Full Autostaple
  stamps no colour**; only `POST /design/strands` and `_build_nick` do) was painted one hue in the panel
  and another in 3D (index 1 green vs yellow, index 3 blue vs orange) — and via `getStapleColorOrder` →
  `exportSequenceXlsx`, the wrong hues reached the **exported oligo order sheet**. Now imports the
  canonical `STAPLE_PALETTE` from `scene/helix_renderer/palette.js` and formats int→`'#rrggbb'`.
  Pinned by 3 tests in `ui/spreadsheet.test.js` ("Staple colour fallback uses the canonical shared
  palette"). The sync-pointer comment in `helix_renderer/palette.js` was corrected at the same time.
  (`scene/color_util.js:35 ATOM_STAPLE_PALETTE` is a separate, intentionally different atomistic palette.)
- **STILL OPEN — the two remaining stale sync-pointer comments** (`pathview/palette.js:83-84`,
  `constants.py:324`) still name files that no longer hold the constant.
- **STILL OPEN — index agreement, not just palette agreement.** The 3D view does **not** use a plain
  `strandIndex % 12`: `buildStapleColorMap` (`scene/helix_renderer/palette.js:172`) **pins** colours per
  strand id at first encounter and takes the slot from a **union-find root** over crossover-joined
  staples (`:186-200`), so it survives mutations and groups topology-connected oligos. `ui/spreadsheet.js`
  recomputes from the raw array index. They now agree on the *palette* and on a freshly-loaded design
  with no crossover unions, but can still drift apart after mutations. **Real fix** = have the spreadsheet
  consume the renderer's `buildStapleColorMap` (it already receives `designRenderer`) instead of
  recomputing — one source of truth for the assignment, not just for the colour list.

### Cadnano-editor app stragglers (found 2026-07-30, `/audit-plan` rule sweep)
Small, each a live trap; all documented in `.claude/rules/cadnano-editor.md`.
- **`unligatedCrossoverIds` is written but never declared** — `cadnano-editor/api.js:120`
  (`_absorbAuxFields`) sets it on the store, but it is absent from `store.js:14-58` `_initialState`,
  so it is `undefined` until the first mutation response. Only `pathview.js:4901` defends
  (`new Set(ids ?? [])`); a second reader would crash. Add it to the initial state.
- **`Ctrl+Shift+L` is case-sensitive** — `ligation_debug.js:403` tests `e.key === 'L'` with no
  lowercase fallback, unlike `Ctrl+Shift+D` (`main.js:327`) which tests both. Works in practice only
  because Shift produces uppercase.
- **Codec logic outside the codec** — `cadnano-editor/main.js:2070` `const flId = key.slice(3)`
  duplicates `parseForcedLigKey` (`element_keys.js:109`). Index-free so it can't hit the negative-bp
  bug, but it is the exact pattern ISSUE-7 came from.
- **`const DEBUG = true` is shipping** — `frontend/src/ui/overhang_pathview.js:61`. Its editor
  counterpart (`pathview.js:104` `DBG = false`) documents the flip-then-revert convention; this one
  was never reverted, so the Domain Designer logs to the console in production.
- **`ui/overhang_pathview.js:60-63` re-declares `RULER_H/LABEL_R/TOP_PAD` locally** with `LABEL_R`/
  `TOP_PAD` deliberately *different* from pathview's 16/18, under a comment claiming it mirrors the
  editor. Partly true is worse than silent here — say which three are shared and which two diverge.
- **All 3 editor e2e specs `goto('/cadnano-editor')` with no `?doc=`**, so the multi-document path
  (`X-NADOC-Doc`, per-doc undo stacks) has **zero** end-to-end coverage — and multi-doc is exactly
  where the undo/redo header bug (`api.js:691`) lived.

### Animation stragglers (found 2026-07-30, `/audit-plan` rule sweep)
Found while rewriting `.claude/rules/animation.md`. The rule + `RUNBOOK_ANIMATION.md` are fixed;
these are the artifacts outside them.
- **`docs/triage/05_animation.md` (193 lines) is fiction** — it documents `config_panel.js`
  (`:16, :122`), `DesignConfiguration`/`ClusterConfigEntry` (`:19`), and `update_configuration`, none
  of which exist. It is the last surviving source of the design-scoped-configurations myth and it
  reads authoritative. Delete it or stamp it superseded; the other 11 `docs/triage/*.md` files were
  not audited and are the same vintage — assume they are stale until probed.
- **`animation_player.js` has zero tests** — 1298 LOC, 23 injected deps, the whole keyframe lerp,
  pre-bake, bounce/loop, bind-hinge and restore paths. So do `export_video.js` (374),
  `overhang_unzip_overlay.js` (175), `overhang_strand_anim.js` (711), `camera_panel.js` (363).
  ~2900 LOC of display logic with no unit test and **no e2e spec** anywhere in `frontend/e2e/`.
  The one thing that *is* pinned (`assembly_config_animator.test.js`, 13 tests) is the pure
  interpolation core — the pattern to copy: extract the pure part, pin that.
- **`captureClusterBase` has two incompatible signatures** — `helix_renderer.js:4441`
  `(helixIds, domainIds, append, {forceAxes})` vs `domain_ends.js:758`
  `(transformKeys, append, domainIds)`. Same name, `append` in a different position, both live on
  the animation path. A positional-arg slip silently captures the wrong base set and shows up as
  "clusters jump on playback". Unify the order or rename one.
- **`Design.configurations` was documented in `memory/REFERENCE_MODELS.md:25`** as
  `List[DesignConfiguration]` — a field and a model that never existed. Fixed 2026-07-30; noted here
  because the same stale root fed the rule, the runbook, and `docs/triage/`.

### Selection stragglers (found 2026-07-30, `/audit-plan` rule sweep)
Found while rewriting `.claude/rules/selection.md` + `RUNBOOK_SELECTION.md`. Both are fixed;
these are the artifacts outside them.
- **`selection_manager.js` is 4179 LOC with ZERO unit tests** — no `selection_manager.test.js`
  exists. It owns all raycasting, every click/lasso/modifier path, four multi-select pools, hover
  preview and the remaining context menus. The three tested siblings (`selection_level.js` 33,
  `selection_bbox.js` 17, `selection_filter.js` 15) are tested *because* they were extracted pure —
  that's the pattern to continue: any new (level, hit, flags) → decision logic belongs in
  `selection_level.js`, not the closure.
- **Four code comments that contradict the code they sit on** (all verified 2026-07-30):
  `ui/keyboard_shortcuts.js:282` + the `description` at `:287` say the Tab cycle includes
  `cluster` (it does not — `TAB_CYCLE`, `selection_level.js:30`); `selection_level.js:59`,
  `selection_manager.js:2028` and `:2126` call the yellow (`0xffe000`) hover preview **red**;
  `store.js:69` documents `selectedObject.type` as 3 values when **10** are assigned
  (`nucleotide, strand, cluster, protein, domain, crossover, overhang, helix, forced_ligation,
  cone`); `selection_manager.js:1647` JSDoc lists 7 of the **26** `initSelectionManager` opts.
  Cheap to fix and each one has already misled a doc rewrite.
- **`main.js:4318–4335` deform-gate writes an incomplete `selectableTypes` object** — it replaces
  the whole object with 9 of the 11 flags, dropping `clusters` and `extensions` entirely (they come
  back on restore from `_savedSelectableTypes`). Harmless today (`undefined` is falsy) but the
  store's shape is inconsistent for the duration of a deform edit, and any `in`/`Object.keys` check
  over `selectableTypes` will disagree with `store.js:148`.
- **`lassoCaptureType`'s `beadLevel` field is hard-coded `false`** (`selection_level.js:105`) and
  read by the single caller — a dead field carried through a pure function's public return shape.
- **~40 selection-owning frontend modules are matched by no `.claude/rules/*.md` glob.**
  ~~most notably `frontend/src/state/store.js`~~ — **store.js FIXED 2026-07-30**: `api-and-state.md`
  gained the glob `frontend/src/state/**/*.js` and a full store section. Still uncovered:
  every `scene/assembly_*.js` (a parallel selection stack with its own tests), `measurement_tool`,
  `force_crossover_tool`, `translate_rotate_tool`, `sub_domain_gizmo`, `cluster_clipboard`,
  `slice_plane`, `cross_section_minimap`, and every `ui/*_panel.js`. The selection rewrite claimed
  the 10 most load-bearing; the rest is a real hole.
- **`isolatedStrandId` (isolate mode) is documented nowhere.** Menu item built in
  `selection_manager.js:782–789`; consumers span `scene/photo_mode.js`, `joint_renderer.js`,
  `domain_ends.js`, `helix_renderer.js`, `design_renderer.js`, `ui/file_io.js`,
  `ui/conjugate_manager.js`. A cross-cutting display mode with 7 consumers and no owning doc.

### Rule coverage is 33% of production LOC — the measured hole (found 2026-07-30, `/audit-plan` coverage sweep)
- **Method (reusable):** match every `.py`/`.js` under `frontend/src/` + `backend/` against the
  `paths:` globs of all 11 `.claude/rules/*.md` (minimatch semantics: `a/**/*.py` matches
  `a/x.py`). Script kept at the pass's scratchpad; ~20 lines, re-runnable.
- **Result:** **205,091 of 306,950 production LOC (67%) are matched by no rule glob.** Per rule:
  `api-and-state` 82 files/50.7k, `cadnano-editor` 13/10.7k, `main-init` 1/8.1k, `rendering` 5/8.4k,
  `animation` 16/6.6k, `selection` 10/5.8k, `scaffold-and-loops` 10/5.0k, `deformation` 4/4.6k,
  `unfold` 1/1.6k, `strand-anim` 11/1.1k, `cadnano-2d` 2/1.1k.
- **Uncovered LOC by directory:** `backend/core` **91,134** · `frontend/src/ui` **53,213** ·
  `frontend/src/scene` **38,047** · `backend/physics` 11,671 · `backend/parameterization` 3,546 ·
  `backend/ml/propagator` 2,350.
- **The worst individual holes** (no rule, no owner):
  - `backend/core/lattice.py` (4,923) — **holds the LOCKED `_PHASE_*` constants** that `CLAUDE.md`
    forbids changing without approval. That prohibition is in `CLAUDE.md` but the file itself
    auto-loads no rule.
  - `backend/core/models.py` (3,314) — the `Design` model, every schema in the app. Only
    `memory/REFERENCE_MODELS.md` covers it, and that is *not* auto-loaded.
  - `backend/core/oxdna_health.py` (4,047), `atomistic.py` (3,473), `gromacs_package.py` (3,030),
    `md_protocols.py` (2,576), `namd_solvate.py` (2,560) — the entire MD/sim core.
  - `frontend/src/scene/assembly_renderer_shared.js` (3,940), `joint_renderer.js` (3,224),
    `assembly_joint_renderer.js` (2,839) — the assembly render stack, ~10k LOC, no rule.
  - `frontend/src/ui/md_jobs_panel.js` (3,707), `oxdna_jobs_panel.js` (2,554),
    `overhangs_manager_popup.js` (2,473) — the biggest panels.
- **Why it's debt:** an absent rule produces no signal (unlike a stale one, which announces itself
  at the first dead symbol), so these areas get re-derived every session. Candidate new rules, in
  value order: `models-and-schema` (models.py + validator.py), `assembly-render`
  (`scene/assembly_*.js` + `joint_renderer.js`), `md-jobs` (backend MD core + the job panels),
  `lattice-geometry` (lattice.py + constants.py, carrying the locked-constants warning).

### `api-and-state` stragglers (found 2026-07-30, `/audit-plan` rule sweep)
- **`crud.py` is the response chokepoint for the whole backend.** `_design_response` /
  `_design_response_with_geometry` ([crud.py:268/339](backend/api/crud.py#L268)) are imported by
  **34 modules** — every `routes_*.py`, plus `backend/core/design_geometry.py`, `api/state.py` and
  `api/doc_context.py`. So the carve-up can move handlers out of `crud.py` but every sub-router
  still imports back into it; `crud.py` remains 11,266 LOC / 114 routes. The response builders
  should move to their own module (`api/responses.py`) before the next carve-router pass, or the
  import graph keeps `crud.py` structurally central no matter how many routes leave.
- **`frontend/src/state/store.js` has zero tests** — 541 LOC, 53 state keys, 7 subscriber slices,
  31 importing modules, and the slice-dispatch logic at :438-446 is real branching. The only
  `*store*` test is `test-helpers/mock_store.test.js`, which tests `createMockStore` — a
  *different* module whose filename implies coverage it does not provide.
- **`store.js:460` JSDoc contradicts the code** — lists 6 slices, omits `assembly` (live at :414,
  accepted by the runtime check at :468). Logged as a Trap in `api-and-state.md`; fix the comment,
  not the code.
- **`RUNBOOK_API.md` shipped a bug-causing instruction for an unknown period** — ":20 the ONLY
  correct way to mutate the active design is `state.mutate_and_validate(fn)`" while
  `mutate_with_reconcile` has been *mandatory* for any cluster-scope-affecting topology mutation
  ([state.py:264](backend/api/state.py#L264)). Following the runbook silently skipped
  `reconcile_cluster_membership`. Rewritten 2026-07-30. Worth grepping past cluster-membership bugs
  against this.
- **`PATCH /design/extensions/{id}` is documented but does not exist** — `routes_extensions.py` has
  POST/PUT/DELETE + both `/batch` forms, no PATCH decorator. Either the route was dropped or the
  partial-update capability was never built; nothing calls it, so it's doc-only rot today.

### `main.js` stragglers — the composition root is re-growing and has zero tests (found 2026-07-30, `/audit-plan` rule sweep)
- **`main.js` is 8,059 LOC and RISING.** Measured 2026-07-30: **+245 since 7,814 (2026-07-13)** and
  **+1,094 since the 6,965 the last carve session left it at (2026-06-06)**. MD/SNUPI/jobs feature
  work is landing cohesive blocks in the closure — the module-first law in `CLAUDE.md` /
  `FEATURE_DEVELOPMENT.md` is leaking. `main_js_carveup.md` already flags this as *the* finding and
  is sitting mid-gate with all four TERMINAL-STATE GATE boxes unchecked, **idle since ~2026-06-06**.
  Logged here too because tech_debt is what gets scanned when the carve-up loop isn't running.
- **`main.js` has zero unit tests** — no `main.test.js`, no test imports it. ~30 sibling
  `*.test.js` files reference it only in "extracted from main.js" comments; `e2e/*.spec.js` pins no
  main.js symbol. 8,059 LOC whose only gates are `just smoke` and hand-exercising the app. This is
  structural: the closure isn't importable. Every extraction shrinks the untested surface — that's
  the argument for the carve-up beyond LOC.
- **`_clearStapleChecks()` is an empty no-op still called from 5 sites**
  ([main.js:733](frontend/src/main.js#L733); callers `:829`, `:840`, `:3496`, `:3891`, `:3918`).
  `_routingChecks` lost its `prebreak` and `autoMerge` fields; the clear-hook survived them. Either
  delete the function + its 5 calls, or restore whatever staple-routing check it was clearing.
- **`_floorReach` is a permanent `() => null` stub** ([main.js:614](frontend/src/main.js#L614))
  whose only consumer is a live per-frame callback (`:615`) that therefore evaluates a dead branch
  every frame. Deliberate revive seam for photo-mode v1's ground plane (archived to
  `archive/photo_mode_v1/`) — keep or excise, but it's currently cost with no benefit.
- **The main.js carve-up loop has no slash command.** `/carve-router` explicitly disclaims main.js
  ("NOT for frontend main.js — that's its own loop"), but that loop's only artifacts are
  `main_js_carveup.md` + `main_js_extraction_log.md` + `memory/main_init_detail.md`. Every other
  loop in the repo has a skill; this one is invoked from memory. Plausible cause of the 5-week idle.

### Rendering stragglers (found 2026-07-30, `/audit-plan` rule sweep)
Turned up rewriting `.claude/rules/rendering.md` + `RUNBOOK_RENDERING.md` against the code.

- **`deform_view.reapplyLerp()` is exported with ZERO callers** —
  [deform_view.js:378](frontend/src/scene/deform_view.js#L378), exported `:409`; the only other hits
  are two comments in `helix_renderer.js:555,595`. Both the rendering rule and its runbook stated,
  as a first-check invariant, *"after any `revertToGeometry()`, call `deformView.reapplyLerp()`"* —
  **nothing has ever called it.** So either (a) there is a real latent bug (a design with an active
  deformation that comes back straight after a sim overlay toggles off), or (b) the invariant is
  obsolete and the function should be deleted. `oxdna_display.test.js:424` explicitly pins that
  `applyFemPositions(null)` is the LAST call with no re-apply after it, which suggests (b) — but it
  pins the *current* behaviour, not the correct one. **Decide before deleting**; the wired analogue
  for unfold is `getUnfoldView?.()?.reapplyIfActive()` (`deform_view.js:308`, `domain_ends.js:593`).
  Related: `clearFemOverlay` above, same family of dead overlay-teardown code.
- **`refreshAllGlow()` refreshes 6 of the 7 glow layers** —
  [design_renderer.js:955-962](frontend/src/scene/design_renderer.js#L955) omits `_captureGlowLayer`
  (created `:71`) while refreshing `_glowLayer`, `_undefinedGlowLayer`, `_anchorGlowLayer`,
  `_clashGlowLayer`, `_previewGlowLayer`, `_fluoroGlowLayer`. Since the function's job is "re-read
  entry.pos each frame during unfold animation", capture glow will lag its beads. Looks like an
  omission at the time a 7th layer was added, not a decision.
- **`scene/arc_tube_geometry.test.js` (4 tests) tests a module that does not exist** — there is no
  `arc_tube_geometry.js`. Its own header calls it "a throwaway diagnostic test — delete once the
  cause is fixed + pinned" (2026-06-07, crossover-selection TubeGeometry collapse). Still in the
  suite, still green, pinning nothing.
- **The CG render pipeline has ~20 tests for ~8.6k LOC.** `design_renderer.js` (1,529 LOC, **92
  public methods**) and `glow_layer.js` have **zero** test files; `helix_renderer.js` (5,232 LOC,
  69 controller methods) has **4** tests, both on pure helpers — `buildHelixObjects` (~2,200 LOC)
  is untested. Worse than the raw number: `ui/cando_display.test.js`, `ui/lammps_display.test.js`,
  `ui/md_panel.test.js`, `scene/slice_highlighter.test.js` all **mock** `designRenderer`, so a green
  suite is evidence about the callers only. Cheapest real win: pin the pure functions
  (`_effectiveColors`, `bezierAt`/`arcControlPoint` in `crossover_connections.js`, `CG_LOD`
  mapping) rather than attempting a WebGL harness.
- **Stale `blunt_ends` naming survives the `domain_ends.js` rename** — comments at
  `loop_skip_highlight.js:254`, `unfold_view.js:1170`, `cadnano_view.js:91`, and the live local
  variable/opt names `bluntEnds`/`getBluntEnds` (`main.js:2988`, `unfold_view.js:1279`,
  `cadnano_view.js:439,582`). Cosmetic, but it is why two separate rule audits had to re-derive
  that `domain_ends.js` is the file. (`.claude/rules/unfold.md`'s dead `blunt_ends.js` path was
  fixed in this pass.)
- **`ui/representation_switcher.js` has 7 representations; `setDetailLevel` has 3 levels** — no
  shared constant ties `hull-prism/cylinders/beads/full/surface/vdw/ballstick` (`:36-44`) to
  `CG_LOD = {full:0, beads:1, cylinders:2}` (`helix_renderer.js:64`). Four of the seven silently
  bypass this pipeline entirely. Not a bug today; it is the reason the LOD/representation
  distinction keeps getting confused in docs.

### Deformation stragglers (found 2026-07-30, `/audit-plan` rule sweep)

- **`deform_view.js` exposes 8 methods; 4 have ZERO callers in all of `frontend/`** —
  `reapplyLerp` (`:378`), `snapOff` (`:218`), `setT` (`:388`), `getT` (`:403`), plus `dispose`.
  **Decide before deleting `reapplyLerp`:** it is `_applyLerp(_currentT)` and its JSDoc says
  "call after physics is stopped" — XPBD/FEM was retired to `archive/physics_xpbd_fem/`, which is
  how it lost its caller. It is also the written-but-unwired fix for a real mechanism:
  `applyFemPositions(null)` → `revertToGeometry()` **with no args** (`helix_renderer.js:3316-3317`)
  restores `nuc.backbone_position`, i.e. the **deformed** backend geometry, ignoring `_currentT`.
  With deform view OFF (t=0), stopping an oxDNA/mrDNA/trajectory overlay should therefore snap the
  design **bent** while the toggle reads straight. Mechanism verified by reading; **not reproduced
  in-app**. Either wire it into the overlay-stop paths or pass the straight maps to
  `revertToGeometry(straightPosMap, straightAxesMap)` the way `unfold_view.js:925/1024` already do.
  `setT`'s JSDoc claims the animation player drives it — `ui/animation_panel.js` does not.
  Two stale comments still name it: `helix_renderer.js:555`, `:595`.
- **Three source comments claim `_effective_bend_window` auto-extends the bend window; it does
  not** (`deformation.py:311-324` explicitly `del`s its `arm_helices` arg and returns the typed
  planes). Offenders: `deformation.py:337-340`, `models.py:1110` (BendParams docstring),
  `tests/test_periodic_polymer.py:161` (prose assertion). Don't "fix" the code to match them, and
  don't delete the function — 2 live call sites (`:348`, `:2603`).
- **`bend_twist_popup.js:64` JSDoc lists 3 callbacks; `main.js:1361` passes 4**
  (`onPlaneChanged` missing). Same class as the other stale in-file signature comments.
- **1,941 LOC of deformation frontend with ZERO tests** — `deformation_editor.js` (1,031, a module
  singleton with 21 exports and the whole preview/confirm lifecycle), `deform_view.js` (417, the
  6-subsystem lerp fan-out), `bend_twist_popup.js` (493). No test anywhere exercises
  `applyDeformLerp` behaviour; `devtools_helpers.test.js:13` only mocks the name. Backend is well
  covered by contrast (36 tests across 5 `test_deform*` files). The untested paths include
  "does teardown run if `confirmDeformation()` throws".
- **`POST /design/deformation` takes `preview` in the request BODY
  (`routes_deformation.py:55`) while `DELETE …/{op_id}` takes it as a `Query(False)`
  (`:178`).** Gratuitous asymmetry; every doc that wrote `?preview=true` was half wrong.
- **`assembly_flatten.py:273` constructs a `Design(...)` carrying neither `deformations` nor
  `cluster_transforms`.** Possibly deliberate (a flatten artifact), but it is the one remaining
  place a bend could silently vanish now that `lattice.py` rebuilds via `copy_with`. Confirm
  intent, then comment it either way.
- **`initDeformView`'s 3rd parameter `_getCrossoverMarkers` is passed literal `null`**
  (`main.js:1558`) — vestigial, same class as `cadnano_view.js`'s dead 8th arg.
- **`docs/triage/04_deform_tools.md` is built on two things that don't exist** — it cites
  `MAP_DEFORMATION.md` (**never existed anywhere in the repo**, 4th phantom `MAP_*.md`) at `:28`
  and `:34`, and repeats the obsolete "every `Design(...)` in `lattice.py` MUST include
  `deformations=`" invariant as *critical*. `docs/triage/00_MASTER_GUIDE.md:4` points at `n.md`
  for the same thing. Extends the existing `docs/triage/` finding from the animation pass — that
  directory is now 2 for 2 fiction; treat all 12 files as suspect.

### Unfold stragglers (found 2026-07-30, `/audit-plan` rule sweep)

- **Two parallel implementations of the `applyUnfoldOffsets` fan-out, with different callee
  lists.** `unfold_view.js` notifies 5 (`:883-893`, `:941-949`, `:997-1002`, `:1277-1284`);
  `expanded_spacing.js:182-194` notifies **7** — the same 5 plus `applyUnfoldOffsetsExtensions`
  and **`atomisticRenderer.applyUnfoldOffsets` (`:194`)**, which is the *only* caller of
  `atomistic_renderer.js:452`. Adding a position-owning subsystem silently requires editing both
  files, and there is no shared helper or test pinning the two lists together. The asymmetry is
  currently harmless (unfold refuses to enter atomistic mode, `main.js:2547`) — but nothing
  encodes that, so a future "unfold in atomistic" feature inherits a half-wired fan-out.
- **`unfoldHelixOrder` is derived in 4 places.** `unfold_view.js:830` and `cadnano_view.js:97`,
  `:164`, `:264` each independently compute `unfoldHelixOrder ?? allIds` + append-missing. One
  helper, four copies; drift here shows up as cadnano and unfold stacking helices differently.
- **2,618 LOC of unfold frontend with ZERO unit tests** — `unfold_view.js` (1,610, 30-method API,
  9 store subscribers), `cross_section_minimap.js` (712), `expanded_spacing.js` (296). No
  `.test.js` anywhere imports any of them. Sole coverage is `e2e/test_unfold_debug.spec.js`
  (43 lines): loads a design, toggles unfold, asserts no console errors — zero position, offset or
  arc assertions. Same shape as the deformation and rendering test holes.
- **Two source comments contradict their own file.** `cross_section_minimap.js:2-3` says the
  overlay is in the "lower-right corner"; the CSS at `:58-66` is `bottom:8px; left:8px`
  (lower-**left**). `unfold_view.js:9` calls the arcs `THREE.Line`; `:189` constructs
  `THREE.LineSegments`. Both were faithfully copied into the rule and runbook and survived there
  for months. Don't "fix" the code to match the comments.
- **`initUnfoldView`'s 7th parameter `_getCrossoverLocations` is passed literal `null`**
  (`main.js:1535`) — vestigial, third instance of this pattern after `initDeformView`'s
  `_getCrossoverMarkers` and `cadnano_view.js`'s dead 8th arg. Worth one sweep for `, null)`
  init args rather than three separate notes.
- **`MAP_CADNANO.md` is a 5th phantom `MAP_*.md`** — never existed in this repo, cited by
  `docs/triage/00_MASTER_GUIDE.md:172`, `01_expanded_quick_view.md:36`, `02_cadnano_3d_mode.md`
  (multiple), `04_deform_tools.md:49`. `docs/triage/` is now **3 for 3 fiction** across the
  animation, deformation and unfold passes; the directory should be deleted or moved under
  `archive/` rather than audited file by file.

### ~~Advanced/seamless scaffold routing is hash-seed non-deterministic~~ — FIXED 2026-07-13
- **Resolution (verified 2026-07-13):** the `(len(adj[n]), n)` lex tiebreaker is now applied to
  **both** the starter sort and the neighbor key handed to `_ham_path_search`
  ([seamed_router.py:296](backend/core/seamed_router.py#L296)); the in-code
  `FIXME(advanced-routing-nondeterminism)` is gone. `test_seamless_router.py::
  test_teeth_closing_zig` passes **8/8 fresh `PYTHONHASHSEED` values** (was ~4/8).
  Routing is deterministic run-to-run again. **Invariant: keep the tiebreaker on BOTH keys** —
  dropping either silently reintroduces run-to-run scaffold-strand-count drift (this
  regressed once already, via the 2026-06-01 budgeted-DFS refactor).
- **Historical detail (why it happened)** — kept because it regressed once and could again:
- **Where it was:** [seamed_router.py](backend/core/seamed_router.py) `_ham_path_ending`
  (~line 291) + the neighbor key it hands to `_ham_path_search`. Both sorted by
  `len(adj[n])` with **no secondary `n` tiebreaker**, so equal-degree nodes kept
  their set-derived (hash-seed-dependent) order.
- **Why it was debt:** the Hamiltonian path → scaffold routing came out differently
  run-to-run. `auto_scaffold_seamless` / `auto_scaffold_advanced_seamed` emitted a
  **different scaffold-strand count** depending on `PYTHONHASHSEED`. Real-app impact:
  the same design routed differently on different backend runs (not just tests).
- **Repro (2026-06-04, now stale):** `tests/test_seamless_router.py::test_teeth_closing_zig`
  (asserts exact `bridge_xovers==6`, `scaf_strands==4`) was **flaky ~50%** — 4 pass /
  4 fail across 8 fresh processes. Also varied `advanced_seamed` on teeth between 1
  and 4 scaffolds (originally misattributed to the live app rewriting the fixture).
- **History:** `seamless_router._ham_path_ending` (its OWN copy) deliberately used
  `(len(adj[n]), n)` WITH the `n` tiebreaker to avoid exactly this (documented in
  [[seamless-scaffold-router-architecture-and-hard-won-lessons]]). The
  2026-06-01 budgeted-DFS refactor that delegated the search to the shared
  `seamed_router._ham_path_search` dropped the tiebreaker → regression. The fix
  restored it on both keys.
- **Topology check on the fix:** teeth routing topology is unchanged
  (`bridge_xovers==6`, `scaf_strands==4`) — that is exactly what the now-deterministic
  test asserts, so the tiebreaker picked the same path the good seeds always picked.
  It de-flaked the test without moving the route.

### ~~Overhang Bind/Unbind button (legacy OverhangBinding pair model)~~ — REMOVED 2026-06-30
- **Where:** [overhang_sequences_panel.js](frontend/src/ui/overhang_sequences_panel.js).
- **Resolution (2026-06-30, final):** the per-row Bind/Unbind toggle was **removed entirely**
  — user feedback: mixing bind/relax actions between the Overhangs list and the Overhang
  Connections section was a bad idea; keep each section's job separate. (A short-lived
  intermediate version rewired the toggle to the unified relax; that was scrapped.)
- **Replaced by a LINK ICON:** for any overhang that participates in a connection (a
  `overhang_bindings` / `overhang_connections` / `connection_versions` entry — see pure
  `connectionPairForOverhang(design, ovhgId)`), the last column shows a chain-link button.
  Click → `openConnectionForPair(a, b)` (new export from
  [overhang_connections_panel.js](frontend/src/ui/overhang_connections_panel.js)) which
  expands the Connections section, sets the A/B dropdowns to the pair, and selects the
  pair's **applied** ConnectionVersion (falling back to the live linker/binding row).
  Imported directly (singleton entry point) → **no main.js change**. All bind/unbind /
  relax lives in the Connections section only.
- **Keystone backend fix (kept):** `crud.patch_overhang_binding` passes `driver_side`
  (from `target.driver_oh_id`) into `compute_bind_topology`, so toggling a UNIFIED
  same-rigid-body root-to-root binding's `bound` flag no longer 422s on the same-cluster
  guard. This now serves the Connections section's **Bound checkbox** (the proper home of
  bind/unbind), NOT the removed sidebar button. Legacy bindings (`driver_oh_id=None`)
  unchanged. Pin: `test_direct_connection_unified.py::
  test_unbind_then_rebind_roundtrips_same_body_unified_binding` (proven red without it).
- **Note:** the OverhangBinding model is NOT abandoned — it IS the current unified direct
  connection record (see [[overhang-connections-panel]]). The old "superseded by oh_binder"
  framing was stale.
- **NOT hand-driven in-app** (manual-validation debt): the link icon (appears for connected
  overhangs, click opens the Connections section on the applied version) is pinned by jsdom
  but not exercised against a real overhang-bearing design in the running app.
