---
name: tech-debt-ledger
description: Tech-debt ledger + driver for the /audit-debt loop — ID'd debt items, each driven to a terminal state (fixed / deleted / stale / decided / promoted / accepted). Check when touching a flagged area.
metadata:
  node_type: memory
  type: project
  originSessionId: a42a916c-90da-4711-b831-59182e249f46
---

# Tech-Debt Ledger — drive each item to a terminal state

Two jobs in one file:

1. **Reference** — when you touch a flagged area, the `TD-NN` section tells you what's rotten there.
2. **Driver for the `/audit-debt` loop** — one `TD-NN` per iteration, probed against live code and
   driven to a terminal state. The loop ends when the queue is empty.

This is the **head**. Closed items move to `project_tech_debt_archive.md` — **never read the
archive in a routine pass.** Protocol: `.claude/skills/audit-debt/SKILL.md`.

## The bright line (read first)

**A debt entry is a claim, not a fact.** Most entries here were written by an `/audit-plan` pass on
2026-07-30/31; code has moved since, and some bullets were wrong when written. **Probe first, act
second** — a bullet whose anchor no longer exists is STALE, not a fix. Two more:

- **"Decide before deleting" means the user decides.** Several entries name dead code that is
  *dead because a feature was retired* — deleting it can bury a latent bug (`reapplyLerp`) or a
  cheaper code path (the deformation in-place-PATCH branch). Those go to **DECISIONS**, never to a
  silent delete.
- **Never invent scope.** If resolving a bullet turns into a program of work (write 4 new rules,
  test a 4k-LOC module, carve a god-file), that is **PROMOTE**, not this loop.

## Terminal states (pick exactly one per bullet)

| State | Test | Action |
|---|---|---|
| **STALE** | The probe shows the anchor is gone / already fixed / never existed. | Strike the bullet + date + one line of probe evidence. No code change. |
| **FIXED** | Small, safe, verifiable change (wrong comment, wrong default, missing field, real defect). | Fix, run the gate, strike + date + what changed. |
| **DELETED** | Dead symbol/file/test with **zero callers**, and no open question about why it died. | Verify zero callers repo-wide, delete, run the gate, strike. |
| **DECIDE** | The bullet itself flags a judgement call (revive vs excise, behavior change, science call). | Move a **one-question** framing to **DECISIONS** below. Do not guess. |
| **PROMOTE** | Real, but a multi-session program (new rules, test suites for 4k-LOC modules, carve-ups). | Point it at the owning loop/plan (create the topic file if none), strike here with the pointer. |
| **ACCEPTED** | Deliberate, correct as-is; only costs a re-investigation each sweep. | Move a one-liner to **ACCEPTED** below so future sweeps stop re-finding it. |

An iteration's target `TD-NN` is **done when every bullet in it carries one of the six** — not when
the easy ones are cleared.

## Gate (per iteration)

- Backend code touched → `just test-smart`; cite decision (`FAST`/`fast+slow[area]`) + pass count +
  any `DEFERRED` group. Never `just test` / `just test-slow` (test-dedicated session only).
- Frontend code touched → `just test-frontend`, **plus exercise it in the running app**, or lead the
  report with `NOT VERIFIED IN APP`.
- Prose-only bullets (comments, docs, memory files) → no tests; say so.
- Deleting code that a test names → the test goes with it; say which tests were removed and why the
  behavior is still covered (or that it is not).

## Queue (priority top-first; `▶ NEXT` = this iteration's target)

Rank = **active harm × cheapness**. A bullet that paints the wrong colour in an exported oligo sheet
outranks a stale comment; a stale comment outranks a program of work.

| ID | Item | Band | Why here |
|---|---|---|---|
| ~~TD-01~~ | ~~`just lint` is RED (5 `F401`)~~ | — | **CLOSED 2026-07-31** — lint exits 0. 5 FIXED + 1 ACCEPTED (propagator per-file-ignore). Archived. |
| ~~TD-02~~ | ~~`STAPLE_PALETTE` index agreement + 2 stale sync comments~~ | — | **CLOSED 2026-07-31** — 1 STALE / 4 FIXED / 1 DECIDE (DEC-01). Found + fixed a bug the entry didn't know about: the backend .xlsx export was still on the retired palette. Archived. |
| ~~TD-03~~ | ~~Cadnano-editor app stragglers~~ | — | **CLOSED 2026-07-31** — 5 FIXED / 1 PROMOTED (MV-EDITORDOC) / 1 DECIDE (DEC-02) / 2 ACCEPTED / 1 STALE. Also closed TD-14's reverse-coupling bullet; spawned TD-26. Archived. |
| ~~TD-04~~ | ~~Dead `POST /design/auto-scaffold` + orphaned matched-ends fns~~ | — | **CLOSED 2026-08-01** — 2 FIXED / 1 DELETED. The "silently fake coverage" was false: all 4 call sites guarded the dead POST and fell back to domain-paint, so the specs always scaffolded. Archived. |
| ~~TD-05~~ | ~~Rendering stragglers~~ | — | **CLOSED 2026-08-01** — 2 FIXED / 2 DECIDE (DEC-03, DEC-04) / 1 ACCEPTED / 1 PROMOTED. The `refreshAllGlow` lag bug was real *and understated* (fires on every sim frame, not just unfold); fixed + pinned. Also closed TD-09's `reapplyLerp` half. Section kept here until DEC-03/04 are answered. |
| ▶ TD-06 | Cross-cutting sweeps (see its section) | P0 | Three separate audits each re-found the same rot (`docs/triage/` fiction, `, null)` init args, phantom `MAP_*.md`). Resolve once, strike in all sections. |
| TD-07 | Dead `lattice.auto_scaffold(mode=…)` in 2 scripts | P1 | Two unrunnable scripts (ImportError) + an orphaned `_pull_window_turns`. |
| TD-08 | `CELLS_6HB` / `CELLS_18HB` divergent copies | P1 | Copying the name between files silently changes the neighbour graph. |
| TD-09 | Deformation stragglers | P1 | 3 comments that contradict the code + a possible silent bend-loss in `assembly_flatten.py`. |
| TD-10 | Cluster-scoped deformation stragglers | P1 | `_arm_filter_cluster` resolves by list order (mechanical root of the two-cluster limitation). |
| TD-11 | Autorefine skip-placement stragglers | P1 | `finetune` has opposite defaults route vs function; unsigned-metric ranking is **always on**. |
| TD-12 | Selection stragglers | P1 | 4 wrong comments + an incomplete `selectableTypes` write. |
| TD-13 | `api-and-state` stragglers | P1 | Doc-only rot (`PATCH /design/extensions/{id}`) + the `responses.py` extraction question. |
| TD-14 | Cadnano-2D-mode stragglers | P2 | Dead `clearFemOverlay`, duplicated `PERSP_FOV_DEG`, vestigial param. |
| TD-15 | Animation stragglers | P2 | `captureClusterBase` has two incompatible signatures on the same path. |
| TD-16 | Unfold stragglers | P2 | Two divergent fan-out lists; `unfoldHelixOrder` derived 4×. |
| TD-17 | Strand-anim stragglers | P2 | Sandbox `DEFAULTS` is a production constant source; 6 stale comments. |
| TD-18 | Stale workspace-fixture test skips | P2 | Silently skips; pick one of the 3 documented options. |
| TD-19 | Unimported frontend modules (5 held) | P2 | A decision per file, not another audit. |
| TD-20 | `main.js` stragglers | P3 | Mostly PROMOTE → the main.js carve-up loop (which has no slash command — that gap is itself a bullet). |
| TD-21 | DELETE-ON-COMPLETION: legacy OverhangSpec pose overlay | P3 · **BLOCKED** | Gated on `overhang_duplex_cluster` P4 migrate-on-load. Don't start until that ships. |
| TD-22 | Rule coverage is 33% of production LOC | P3 | PROMOTE — 4 new rules, one per pass, not a debt fix. |
| TD-23 | Duplex-foundation stragglers | P1 | Two `showChoice`s; 20 e2e specs hardcode an absolute path; `reassign_if_sequenced` is a zero-caller footgun with 3 lying docstrings. |
| TD-24 | Photo-mode v1 stragglers | P2 | Orphaned fluorophore fn whose comment is the only record of *why* the clamp exists. |
| TD-25 | `just lint`'s SCOPE hides 193 findings | P2 | Found closing TD-01. The gate is green but only lints `backend/ tests/`; `scripts/` + root are unlinted. |
| TD-26 | 3D store's undeclared `unligatedCrossoverIds` | P2 | Found closing TD-03 — same defect, but adding the key means picking a store slice. |
| ~~TD-29~~ | ~~Honeycomb twist incommensurate with the 21-bp repeat~~ | — | **FIXED 2026-08-06.** New lattice constant `HONEYCOMB_TWIST_PER_BP_DEG = 2*360/21` (physical `BDNA_TWIST_PER_BP_DEG` left at 34.3, square untouched). Drift 0.657 → 0.000 u/1000 bp; same-lattice designs now numerically identical; DX rotation optimum became design-independent (−3°). 8 test failures, all understood + fixed; 2 new pins. |
| TD-28 | DEFERRED AUDIT: all linker + relax code (~5.2k LOC) | P2 · **BLOCKED by design** | Parked until TD-27's basic-design geometry is settled. These modules fit poses against bead positions and are the 14 failures blocking TD-27's flip — re-deriving them before the placement settles means doing it twice. |
| TD-30 | Extra-base inserts pierce nucleotide rings at most helical phases — 41 slow tests red | P1 · **needs a dedicated session** | Full suite 2026-08-07: 17 of 22 swept phases thread a ring on the reciprocal fixture, and the build gate refuses them. Pre-existing (identical on `6076989`) and red since the suite last passed on 2026-07-20. Owner: park it, do not fix in a normal session. |
| TD-27 | Nucleotide-geometry correction stack — 5 tiers that partly cancel each other | P1 · staged | Mostly a program of work (→ P3 by the rubric), but it carries **two confirmed live groove-sign bugs** (`oxdna_interface.py:119`, `mrdna_bridge.py:381`) and a false "net effect = 0°" comment on a locked constant. Staged so the cheap, behaviour-preserving half lands first. |

## DECISIONS — one question each, the user's call

Park a bullet here when the call is genuinely the user's. Keep it to **one question + the two
outcomes**; surface them in batches, don't block a pass on an answer.

- **DEC-01 (from TD-02, 2026-07-31) — should the two frontend palette *lookalikes* be unified with
  `STAPLE_PALETTE`, or stay independent?** `scene/color_util.js` `ATOM_STAPLE_PALETTE` (byte-identical
  ints, indexed by **cluster** for atomistic/surface colouring) and `scene/selection_manager.js`
  `PICKER_COLORS` (same 12 with `{hex, css, label}` names, the user colour picker) are *values*-
  identical to the canonical staple palette but *semantically* different indexings.
  **(a) Unify** — both import `STAPLE_PALETTE`; two fewer copies to drift, but a future staple-palette
  tweak silently repaints the atomistic view and renames the picker swatches.
  **(b) Keep separate** — they stay free to diverge on purpose; the cost is the cross-reference
  comments added 2026-07-31, which future sweeps must trust.
  *(No code change either way is risky — the values already match. This is purely "should they be
  allowed to diverge later".)*
- **DEC-03 (from TD-05 + TD-09, 2026-08-01) — is `deform_view.reapplyLerp()` a latent bug to WIRE,
  or an obsolete invariant to DELETE?** It has zero callers and never has had one (verified
  repo-wide 2026-08-01; the only other mentions are two comments at `helix_renderer.js:555,595`).
  The mechanism it would fix is real and reads as a genuine defect: stopping an oxDNA/mrDNA/
  trajectory overlay calls `applyFemPositions(null)` → `revertToGeometry()` **with no arguments**
  (`helix_renderer.js:3317`), which restores `nuc.backbone_position` — the **deformed** backend
  geometry — ignoring the deform view's `_currentT`. So with the deform toggle OFF (t=0), stopping a
  sim overlay should snap the design **bent** while the toggle reads straight.
  **Not reproduced in-app — mechanism verified by reading only.**
  **(a) Wire it** — call it (or pass the straight maps to `revertToGeometry(straightPosMap,
  straightAxesMap)`, which is what `unfold_view.js:925/1024` already do) on the overlay-stop paths.
  Fixes the bend-snap if it is real; touches 8 display modules' stop path.
  **(b) Delete it** — plus `setT`/`getT`, and drop the invariant from the rule and runbook (both
  already corrected to say it has no callers). Cheap and honest if the bend-snap can't be reproduced.
  *Cheapest way to settle it: load a design with an active deformation, run any sim overlay, stop
  it, and see whether the design snaps bent. One app exercise decides the whole question — I'd want
  that observation before writing either patch.*
- **DEC-04 (from TD-05, 2026-08-01) — delete `frontend/src/scene/arc_tube_geometry.test.js`?**
  It is a 4-test file testing a module that does not exist (`rg --files` confirms: no
  `arc_tube_geometry.js` anywhere), its own header calls it *"a throwaway diagnostic test — delete
  once the cause is fixed + pinned"* (2026-06-07), it imports only `vitest` + `three` and
  re-implements the tube build inline, and it has **drifted** — hardcoded radius `0.63` vs the live
  `PREVIEW_ARC_RADIUS = SELECTION_ARC_RADIUS = 0.147` (`design_renderer.js:78-79`).
  **(a) Delete it** — recommended; it is green, pins nothing, and its bbox assertions now describe
  geometry the app has not built since 2026-06-07, so a future reader will trust it wrongly.
  **(b) Keep it** — only worth it if the 2026-06-07 crossover-selection TubeGeometry collapse is
  still considered unfixed and this is the record of it; then it needs re-pinning to `0.147`.
  *(Deleting a test is a user call per `CLAUDE.md` → Risky-action policy — the only reason this is
  a DECISION rather than a DELETED. No behaviour is covered by it either way.)*
- ~~**DEC-02 (from TD-03, 2026-07-31)**~~ — **RESOLVED 2026-08-01: user chose (a), delete.** The four
  `run.py` files are gone. **Only the scripts** — each directory keeps its `hypothesis.md`,
  `conclusion.md` and `results/` (metrics.json + plots), verified present before deleting, so the
  scientific record is intact and only the unrunnable code left. `experiments/README.md` now carries
  a note saying why and pointing at git history for recovery. **This unblocks TD-25 option (a)** —
  widening `just lint` to `ruff check .` now waits on TD-07's two scripts alone. Original framing:
  *the four scripts are unrunnable and unrevivable as written: delete them, or keep them as a frozen
  record?* All four
  import `from backend.physics.xpbd import build_simulation, xpbd_step, …` and **`backend/physics/xpbd.py`
  no longer exists** (retired with the FEM/XPBD code to `archive/physics_xpbd_fem/`); they also
  construct `LatticeType.FREE` (deleted 2026-04-06 — the enum is now exactly `{HONEYCOMB, SQUARE}`)
  and import `_geometry_for_design` from `backend/api/crud.py`, which moved to
  `backend/core/design_geometry.py:567`. Sites: `exp01_bond_integrity/run.py:40`,
  `exp02_thermal_stability/run.py:41`, `exp03_excluded_volume/run.py:46,54`,
  `exp04_crossover_geometry/run.py:56,64`.
  **(a) Delete the four scripts** — they measure bond integrity / thermal stability / excluded volume
  / crossover geometry under an XPBD solver that is gone, so "fixing" them means re-writing the
  physics, not swapping an enum. Deleting also unblocks **TD-25** (widening `just lint` to
  `ruff check .`) and removes a standing trap for the next sweep.
  **(b) Keep them, stamped unrunnable** — a header comment naming the three dead imports, so the
  experimental *protocol* survives as a record even though the code can't execute. Costs a per-file
  lint ignore.
  *(This is a delete-files call, so it is the user's per `CLAUDE.md` → Risky-action policy. Note
  option (a) is only safe if these experiments' RESULTS are recorded elsewhere — I did not check
  whether `experiments/exp0*/` holds output data alongside the scripts.)*

## ACCEPTED — deliberate, do not re-report

- **`backend/ml/propagator/` lint errors (6)** — shelved BLADE/atomistic-propagator code, dormant on
  purpose (user decision 2026-07-31). **The per-file-ignore now exists**
  (`pyproject.toml` → `[tool.ruff.lint.per-file-ignores]`, `"backend/ml/propagator/*.py" =
  ["F401","F541","F841"]`, added 2026-07-31 closing TD-01) — so lint is green *and* the dormant code
  is untouched. **Reviving that directory means deleting the ignore entry first**; the entry says so
  in a comment. Never edit the dormant code to satisfy lint.
- **`scene/joint_panel_experiments.js`** (456 ln) — a DevTools console harness for still-live
  `_computeExteriorPanels`. Unreferenced *by design*, like `src/debug_snippet.js`. See TD-19.
- **`slice_plane.js` deformed-mode label swap within 0.6 nm** (from TD-03, 2026-07-31) — `TOL = 0.6`
  at `scene/slice_plane.js:840` (labels) vs `TOL = 0.5` at `:647` (`_cellStateDeformed`). Same
  proximity test, different thresholds → a 0.5–0.6 nm annulus reads `'free'` but still gets a label.
  Known since 2026-05, deliberately unfixed, low priority. Don't re-report.
- **Default helix length 42 bp has no user setting** (from TD-03, 2026-07-31) — hard-coded twice
  (`backend/api/crud.py:490`, `frontend/src/cadnano-editor/api.js:163`), but it only applies to the
  first helix on an *empty* design; every later cell inherits its neighbour's `bp_start`/`length_bp`
  (`crud.py:1907-1919`). Nice-to-have, not a trap. Don't re-report.

## Next-session handoff

**Pass 5 (2026-08-01) closed TD-05** — **2 FIXED / 2 DECIDE / 1 ACCEPTED / 1 PROMOTED.** First pass
in five where the ledger **understated** the headline item instead of overstating it, and the first
that shipped a real bug fix.

- **The `refreshAllGlow` bug was real and bigger than written.** The entry said capture glow "will
  lag its beads during unfold animation". It has **5 callers**, and the one the entry didn't know
  about is inside `applyFemPositions` (`design_renderer.js:1069`) — every simulation frame. The
  omitted layer decorates the oxDNA **surface capture strands**, which are exactly the beads
  `applyFemPositions` moves. So the white halos sat at design positions while the strands they
  highlight went to the oxDNA frame. One line to fix.
- **The lesson to carry: when an entry says "X is omitted from Y", the debt is in Y's CALLERS,
  not in X.** Pass 4's lesson was *read the block, not the line*; this is the next ring out —
  **read the call sites, not the block.** The block (`refreshAllGlow`'s body) told me a layer was
  missing. Only `rg refreshAllGlow` told me how often and in what context that costs, and that is
  what moved it from cosmetic-lag to a visible defect in a shipped feature.
- **Severity ran the other way on the cheap bullet.** `blunt_ends` naming was filed "cosmetic".
  `getBluntEnds` is a named dep in **7 factory signatures** + 4 destructured opts + 4 mock-building
  test files, and `toolFilters.bluntEnds` is a **persisted** store key — renaming it resets a user
  toggle without a migration. Fixed the 3 comments; ACCEPTED the identifiers with the reason
  recorded so no sweep re-opens it. Also: `blunt` is in 79 files and most of it is **correct** DNA
  vocabulary (`blunt_end_menus.js`, `blunt_end_connectors.js`, the backend). Never blanket-rename.
- **Anchor drift, again, and one flatly wrong:** `refreshAllGlow` `:955` → `:980`,
  `design_renderer.js` 1,529 → 1,549 LOC, and `main.js:2988` (the `initDomainEnds` site) is
  **`main.js:3006`** — that wrong anchor had been copied into **4** `.claude/rules/*.md` files.
  All corrected. Prose anchors in this ledger remain roughly half-reliable at 5 passes in.
- **Test-ordering discipline paid off.** `design_renderer.test.js` was written first, run against
  the unfixed file, and failed with exactly `[ '_captureGlowLayer' ]`. That is the only thing that
  makes "green after the fix" evidence rather than decoration — and it is now the template for the
  rest of this pipeline (see the promoted plan in `.claude/rules/rendering.md` § Coverage).

**▶ NEXT: TD-06** (cross-cutting sweeps). It moves to the top by default — it is the other P0, and
it is the item whose whole purpose is *resolve once, strike in N sections*, which this pass just
demonstrated the value of twice (TD-09's `reapplyLerp` bullet closed for free; one bad `main.js`
anchor was fixed in 4 rule files at once).

**The traps to expect in TD-06:** (1) It is a **meta-item** — its bullets are "the same rot appears
in N places", so the failure mode is doing N separate fixes instead of one. Find the single source
first. (2) `docs/triage/*.md` is 12 files of the same 2026-vintage fiction (TD-15 already proved
`05_animation.md` documents three symbols that never existed); deleting or stamping a `docs/`
directory is a **file deletion → user confirm**, so expect a DECIDE, and probe the other 11 before
framing it — one question about 12 files beats 12 questions. (3) The phantom `MAP_*.md` bullet is
pure absence-evidence: per pass 3's lesson, every "never existed" verdict must cite the
`rg --files` that proves the *path* was searched correctly. (4) Given this pass, when a bullet says
"harmless / cosmetic / doc-only", spend the one extra grep on **who calls it** before agreeing.

**Pass 4 (2026-08-01) closed TD-04** — **2 FIXED / 1 DELETED / 0 DECIDE.** Cheapest pass yet; no
user decisions raised. The predicted miscount was real (queue said "4 E2E specs"; it is **3 files /
4 call sites** — `atomistic_helix_parity.spec.js` holds two), and one line anchor had drifted
(`client.js:1103` → **1155**). But the pass's finding is the *severity* claim, again:

- **"That coverage is silently fake" was false.** Every one of the four sites read
  `const r = await request.post(…/auto-scaffold); if (!r.ok()) { …paint a scaffold domain… }`. The
  route has been gone for weeks, so the guarded fallback is what has run every time — the specs
  scaffolded correctly and passed. The debt was a dead round-trip and a misleading comment, not
  missing coverage. **Fourth pass in a row where the entry overstated harm.**
- **The lesson to carry: read the lines AROUND the anchor, not the anchor line.** The 2026-07-30
  sweep grepped `/design/auto-scaffold`, found four hits, and wrote the severity from the hit
  itself. The disproof was on the *next line*. A grepped line tells you a symbol is referenced; it
  never tells you what happens when that reference fails. (Pass 3's lesson was *prove the path you
  grepped exists*; this is its sibling — **prove you read the block, not the line**.)
- **Repo-specific delete check, worth reusing:** before deleting an exported API wrapper here,
  grep the **bare name as a string**, not just call syntax — `ui/autoscaffold_picker.js` dispatches
  client methods by string (`apiMethod: 'autoScaffoldSeamed'`), so a live caller can exist with no
  `foo(` anywhere. `autoScaffoldMatched` was clean on that test; the next one may not be.

*(Pass 4's four trap predictions for TD-05 all landed: the pre-declared DECIDE stayed a DECIDE and
closed TD-09's twin, the test file went to user-confirm, the CG-coverage and representation/LOD
bullets stayed out of this loop. Its one miss was telling pass 5 to check whether the glow omission
"only lags if something re-reads entry.pos during unfold" — the right question, but the answer came
from the caller list, not the layer.)*

**Pass 3 (2026-07-31) closed TD-03** — **5 FIXED / 1 PROMOTED / 1 DECIDE / 2 ACCEPTED / 1 STALE.**
The predicted landmine (the `experiments/` scripts) was real but *understated*, and the two cheapest
bullets were both **overstated**. Pattern for pass 4: **this ledger's severity adjectives are the
least reliable part of it.** Concretely —

- **Overstated ×2.** `unligatedCrossoverIds` "a second reader would crash": there are 5 readers and
  **none** can crash — the two that look undefended feed a sink that normalises with
  `new Set(x ?? [])`. And `DEBUG = true` "logs to the production console": it gates `console.debug`,
  the browser's *verbose* level, hidden by default. Both were still worth the one-line fix; neither
  was the P0 the queue implied.
- **Understated ×2.** The `LatticeType.FREE` bullet named 3 files; it is **4** (`exp01` missed), and
  the enum is the *third* import failure — `backend/physics/xpbd` doesn't exist at all, so "fix to
  HC/SQ" was never an option (→ **DEC-02**). And "re-declares RULER_H/LABEL_R/TOP_PAD" was a symptom:
  the editor's `pathview.js` exported only 4 of its 7 layout constants, which is *why* the fork
  re-declared and drifted.
- **Flatly false ×1.** `paletteColor` "never existed" — it exists, at `ui/spreadsheet.js:62`, with 4
  references. The 2026-07-30 probe searched `ui/strands_spreadsheet.js`, **a path that has never
  existed**; the real file is `cadnano-editor/strands_spreadsheet.js`. Two same-named panels in two
  directories. The `plan_audit_ledger.md:427` lesson built on it was amended too.

**Generalise that last one — it is the pass's real lesson.** *A grep that returns nothing proves
nothing until you have proved the path you grepped exists.* "Zero hits" and "wrong filename" are
indistinguishable in the output. Every future STALE verdict that rests on absence must cite the
`ls`/`rg --files` that shows the file is real. This is the third pass in a row where the *entry* was
wrong rather than the code, but the first where a bad anchor manufactured a fake finding instead of
just a dead one.

**Bonus closed:** TD-14's reverse-coupling bullet. Extracting `cadnano-editor/pathview/layout.js`
(9 constants, verbatim, zero imports) means nothing imports the 4977-LOC `pathview.js` for constants
any more, so it left the main-app bundle. Probe first confirmed it had exactly two importers repo-wide
— that check is what made a refactor of an untested 5k-LOC module a 15-minute job instead of a program.

*(Pass 3's trap prediction for TD-04 — "assume the 4-specs count is wrong" — was correct, and the
`scene_harness.js` half-migration it flagged turned out to be the template for the fix. Both
resolved; see the archive.)*

The 20 open items below are otherwise as `/audit-plan` left them on 2026-07-30/31 — **treat every
anchor as unverified.** Three passes in, the hit rate on prose-written anchors is roughly half.

---

## Open items

### TD-30 — extra-base inserts pierce nucleotide rings at most helical phases (found 2026-08-07 by the first full-suite run since 2026-07-20)

**Owner decision 2026-08-07: PARK IT.** Not to be fixed in an ordinary coding session — piercing,
clash and extra-base geometry get a dedicated session. This entry exists so the red suite is a
known, attributed state rather than a surprise.

**The failure.** `just test` → **43 failed, 7248 passed, 88 skipped** (33 min). 41 of the 43 share
one root: an extra base's own `C3'-O3'` bond threads a nucleotide ring.

| failures | test | note |
|---|---|---|
| 20 | `test_ring_piercing.py` — `test_no_phase_pierces[bp-T/TT]` and siblings | the direct symptom |
| 21 | `test_junction_topology.py::test_a_catenating_phase_cannot_reach_a_seed` | **not a second bug**: it asserts a catenation-clean phase builds without raising, and `gate_seed_topology` also checks piercing, so it raises |
| 1 | `test_namd_topology::test_extra_base_junction_backbone_bonds_are_sane` | same family |
| 1 | `test_surface_visual_regression[VoltronCore]` | **different root** — see below |

**Attributed, not assumed.** Measured on a worktree at `6076989` (before this session and before
the other computer's three commits): the pre-session tree pierces the **same 17 of 22** phases.
`test_namd_topology` also fails there. So the piercing is pre-existing and has been red since the
watermark, `29d8c9af` (2026-07-20) — through the measured-template landing and the honeycomb twist
fix, both of which moved insert geometry.

**The gate is working.** These builds are being REFUSED, not silently shipped. A pierced ring is a
permanent topological defect that no relaxation can undo, so refusing is the correct behaviour;
what is broken is that most phases produce one.

**One thing the 2026-08-07 atomistic junction-balance roll DID make worse, recorded so the
dedicated session has it:** catenating phases on the synthetic reciprocal fixture went **7/33 →
11/33**. It causes none of the failures above (those are piercing), but it is a real degradation of
insert topology, and it is the coupling helical-site Phase 7 closed as "no change needed" — that
judgement was about DISPLAY leakage, which was right, and did not consider that moving the duplex
atoms moves inserts relative to their neighbours' rings.

**The one unrelated failure.** `test_surface_visual_regression[VoltronCore]` is a stale baseline,
not a topology bug: area **+4.98%** against a 5% band WITHOUT the balance roll (i.e. it was 0.02
percentage points from failing on its own) and **+5.35%** with it. Subject is
`workspace/oxdna_jobs/154d3ea291b7/design.json`, not `workspace/VoltronCore.nadoc` — measuring the
latter gives a different area and a wrong attribution. Re-baselining is a judgement call on a
visual-regression panel and was deliberately left alone.

**For the dedicated session.** `_reciprocal_design(extra, bp)` in `tests/test_junction_topology.py`
is the sweep fixture; `_PHASE_SWEEP` is bp 8-18 (one helical turn). `piercing_report` /
`catenation_report` are the oracles and both are cheap (seconds for the whole sweep), so the inner
loop is fast. Insert positions come from `_build_extra_base_atoms` (`atomistic.py:3046`), which
interpolates a Bezier between the two junction nucleotides' geometric-layer beads — inserts follow
that chord and nothing adjusts them afterwards.

### TD-27 — the nucleotide-geometry correction stack: five tiers that partly cancel each other (found 2026-08-06, audit prompted by the measured-atomistic landing)

The MD-measured templates shipped native on 2026-08-06 ([[measured-atomistic]]) but landed **on top
of** the correction stack they were meant to replace: `measured_atomistic.legacy_local_templates()`
exists *solely* to re-express the measured base-pair-frame coordinates in the old `_atom_frame`
convention so the 1ZEW-era corrections don't have to be removed. Five tiers now stack:

| tier | what it does | where |
|---|---|---|
| **1 build** | `BDNA_MINOR_GROOVE_ANGLE_DEG = 150.0` applied with a **per-lattice-cell sign flip** → FWD cells at 150°, REV at 210°. Measured value is 183.9°. | `geometry.py` ×4 (`:181,:324,:409,:496`), `mrdna_bridge.py` ×5, `oxdna_interface.py:119` (**opposite sign**), `oxdna_surface_strands.py:288` |
| **2 stamp** | 4 stacked corrections: `_FRAME_ROT_RAD −37.05°`, `_ATOMISTIC_P_RADIUS 0.886`, per-cell `+58.2°/−1.8°` against a *hardcoded* `radians(150.0)`, `_ATOMISTIC_PHASE_OFFSET_RAD −32°` ("calibrated by overlaying on the bead rep"). Implemented twice (scalar + batch) plus a 5th `relaxed_oxdna_phase` override. | `atomistic.py:511-548`, `_atom_frame:602`, `_atom_frames_batch:702`, `:1545` |
| **3 calibrate** | `_rigid_frame_calibration()` Kabsch-fits itself against its own output, bucketed to mirror tier 2's branches. | `atomistic.py:818-950` |
| **4 measured** | The real MD table — served through `legacy_local_templates()` / `_legacy_frame_in_bp_coords()` purely to keep tiers 1–3 alive. | `measured_atomistic.py:165-235` |
| **5 CG + JS** | `apply_measured_positioning` runs in **1 of ~50** geometry paths; `_geometry_for_design:602` drops the flag. Dual-mode branching in `new_positioning.js`; `0.6568` hardcoded in JS. | `design_geometry.py:359`, `new_positioning.js:41` |

**Three findings that reshape the obvious fix** (each cost a wrong first guess — do not re-derive):

1. **`_FRAME_ROT_RAD` is a trap, not dead weight.** Its comment claims "net effect = 0°" — false. It
   *defines* the frame the template literals are quoted in; the **pair** is a no-op, the constant
   alone is not. Three application sites (`atomistic.py:696`, `:760`, and `:2757` in
   `_extra_base_frame`), external readers in `pdb_import.py:982` and `measured_positioning.py:222`,
   and it is declared **locked** alongside `_PHASE_*` at `atomistic_minimisers.py:28`. Retiring it
   means re-quoting ~300 1ZEW coordinates **and** moving `_extra_base_frame` in the same commit —
   which the out-of-scope extra-base/tail placers depend on. **Gated on those placers.**
2. **There is a fifth un-flagged CG path.** `_positions_for_design` (`design_geometry.py:718`) has no
   measured branch at all, and `crud.py:1270`/`:446` ship its output as `straight_positions_by_helix`
   **in the same response** as the measured nucleotides. So the four `helix_renderer.js` sites that
   look like they bypass measured positioning (`:2055, :2284, :3865/:3869`) are **correct as
   written** — they read straight positions, which genuinely are legacy. Backend before frontend, or
   the picture gets worse.
3. **The measured coating is already partial.** `_emit_arrs` at `design_geometry.py:446`/`:455` passes
   no axis line, and `_emit_bridge_nucs` / `_strand_extension_geometry` bypass `_emit_arrs` entirely.
   Overhang bp, ds-linker bridges and extension tails stay legacy even with the flag ON.

**⚠ ARCHITECTURE DECIDED 2026-08-06 — read [[atomistic-source-of-truth]] before continuing TD-27.**
The owner has settled the question this item kept circling: the atomistic rep is the source of truth,
the CG rep is derived from it and tuned only for figures, and the CG rep must never reach a
simulation. Several TD-27 stages are reframed by that (the Stage-3 default flip, the seed-boundary
adapter, the −32° phase offset), and the plan doc supersedes this entry where they conflict.

**⚠ THE MEASURED PLACEMENT BREAKS HOLLIDAY-JUNCTION SYMMETRY — quantified 2026-08-06.**
User-reported ("crossovers still look asymmetric in both full and atomistic reps") and confirmed.
This is separate from TD-29's twist drift, which is fixed: with the commensurate twist the LEGACY
placement is uniform to ±0.0000 across all 28 junctions of `6hbx100_noT` and very nearly symmetric.
The residual is the measured bead.

At a DX junction with staple crossovers at bp *i* and *i*+1:

| rep | metric | bp i | bp i+1 | Δ |
|---|---|---|---|---|
| full (CG) | bead–bead, legacy | 0.6797 | 0.6802 | **+0.0005 nm** |
| full (CG) | bead–bead, **measured** | 0.7008 | **1.2455** | **+0.5448 nm** |
| atomistic | O3′→P bond, legacy | 0.2687 ±0.0000 | 0.2470 ±0.0000 | **−0.0218 nm** |
| atomistic | O3′→P bond, **measured** | 0.1775 | **0.2970** | **+0.1195 nm** |

(ideal phosphodiester O3′–P = 0.160 nm.) The sign is identical across every junction (28/0, 336/0) —
systematic, not scatter. **Cause:** measured places FORWARD at +24.52° and REVERSE at 154.70°
(separation 130.2°) where legacy uses ±150°, so the junction's dyad symmetry is broken. Measured
makes bond *i* nearly ideal (0.178 vs 0.160) at the cost of i+1 (0.297).

**Two measurement traps here, both of which produced a wrong answer first:**
1. The CG bead separation is a DISTANCE and so direction-agnostic, but the atomistic O3′→P bond is
   NOT — assuming `half_a → half_b` is 5′→3′ is backwards for half of all crossovers and yields
   garbage (±0.31 spread, `close_backbone=True` appearing to do nothing). Take the pairing from
   `_walk_strand_nucleotides`, which gives true 5′→3′ order; the spread then collapses to ±0.0037.
2. Report per-junction signed Δ, not means of the two populations. Here the sign happens to be
   uniform so means were safe, but they would hide an alternating asymmetry entirely.

**Two confirmed live bugs carried inside this item — both FIXED 2026-08-06 (Stage 2):**
- `oxdna_interface._compute_nuc_geometry` used the **opposite** groove sign to `geometry.py`.
  Measured: FORWARD beads 0.0000 nm out (they never depended on the groove), every REVERSE bead
  exactly **1.000 nm** out — two points at r = 1.0 whose placements differ by 2×150° give a chord of
  2·sin(30°). It carried a **second, previously unrecorded defect** as well: it indexed by a raw
  `bp_index - bp_start`, ignoring loop/skip deltas, so on a skip-bearing helix even the FORWARD bead
  was half a rise out (0.167 nm on `U6hb`). Both fixed by **delegating to `geometry.py`** rather than
  flipping a sign, so neither can recur. `_compute_nuc_geometry_copy` had to move with it: the
  geometric layer's emitted loop copies already carry the ±0.5·rise offset, so its old
  "add `(k-(n-1)/2)·rise` to a nominal position" would have applied it twice — it now selects copy k
  from the geometric layer's own emission order (verified 0.0 nm over all 72 loop copies on `U6hb`).
- `mrdna_bridge.py:381` applied `+BDNA_MINOR_GROOVE_ANGLE_RAD` with **no** lattice sign flip, unlike
  the other four sites in the same file. User-confirmed live bug; same 1.000 nm REVERSE-cell error.
  `helix_info` now carries the per-helix groove.

**Two things Stage 2 corrected in this ledger entry's own earlier claims:**
- *"The `:896-898` workaround routes around the bug"* — half right. The bug is now fixed at source and
  both paths agree exactly, but the workaround **still stands** for a different reason: the geometry
  list carries deformation and cluster transforms, and the straight-geometry fallback deliberately
  does not. Its comment now says so.
- The Stage-1 pin `test_the_oxdna_fallback_geometry_agrees_with_the_geometric_layer` was written with
  the **wrong oracle** — `_geometry_for_design` (deformed) instead of `nucleotide_positions_arrays`
  (straight). On a clustered design the served positions legitimately differ by up to 2.0 nm, so that
  oracle asserted a bug that wasn't there while hiding the two that were. **`_compute_nuc_geometry`
  reproduces the STRAIGHT layer by design** — any future test of it must use the straight oracle.

**Performance note (Stage 2):** delegating made `_compute_nuc_geometry` rebuild a helix's whole array
per call — O(N²) over a helix, 26 s to walk three fixtures. `oxdna_interface._straight_arrays` memoises
on a **value** fingerprint of the helix (never `id()`, which recycles across re-parsed designs); back to
0.5 s. The fallback is rarely hit in the writer (0 keys on all 8 Examples fixtures), so this was a
latent landmine rather than a live cost.

**⚠ THE REAL BLOCKER, found 2026-08-06 (user observation, then confirmed): the relative phase
between helices has NEVER been measured.** Correcting the intra-duplex geometry while holding the
crossover phase fixed breaks half the crossovers, and the phase side of the problem rests on an
assumption, not data.

- **Mechanism, measured.** The measured sites are quoted with azimuth 0 = the *legacy forward bead*.
  Swings: FORWARD-cell helix → FWD +24.5°, REV **+4.7°**; REVERSE-cell helix → FWD +24.5°, REV
  **−55.3°** (a 0.83 nm chord — this IS the "max bead displacement 0.86 nm, the legitimate cell-type
  groove correction" recorded in [[measured-atomistic]]). Collapsing both cell types onto one 130.2°
  C3'–C3' separation is correct physics — cell type is caDNAno bookkeeping, not a molecule — but the
  crossover phase was calibrated *to the 150/210 split*, so reverse-cell reverse beads end up 55°
  from their crossover partner.
- **Confirmed in the seed.** Crossover bonds split ~50/50 by strand (337/332, 493/503, 120/120) and
  the damage lands almost entirely on the REVERSE half — newly-over-cliff FWD/REV: VoltronCore
  11/27, NS_trans_fix 3/**54**, U6hb 1/**46**; U6hb REVERSE median Δlength **+0.557 units**.
- **There is NO measurement to check it against.** `_lattice_phase_offset` (π/2, 2π/3) and
  `BDNA_MINOR_GROOVE_ANGLE_DEG` are calibrated against **caDNAno** (`experiments/exp15_phase_offset_search`
  uses caDNAno crossover positions as ground truth), and the 1ZEW numbers are crystal. `bundle_extract.py`
  *cannot* hold the answer: its frame comes from an arbitrary lab vector and its rotation is the
  minimal axis-to-axis rotation — a 2-DOF object with **no roll term by construction**, which is why
  `q3`/`q5` are documented gimbal-locked "do not use". The only shipped inter-helix angle,
  `hj_equilibrium_angle_deg = −7.5°`, comes from a **2-helix isolated DX system** and is flagged
  `k_dihedral_converged: false`.
- **MEASURED 2026-08-06 — and the phase convention SURVIVES.** `scripts/measure_interhelix_phase.py`
  now measures it across all five free-NAMD origami. The equilibrated crossover backbone sits
  **+7.6° ± 0.4°** off the inter-helix direction across the three insert-free systems
  (6hbx100_noT +8.1°, 24hb_0xT +7.4°, 18hb +7.3°; |φ| median 19.1 ± 0.5°, n up to 13,182).
  On the **same design** as the trajectory, NADOC legacy predicts +3.3° / |φ| median 17.2° — inside
  the MD spread. **So `_PHASE_*` and the groove constant are validated against MD for the first
  time; do NOT change them.** The measured CG *bead* is what loses registration (+15.4° / 21.9° on
  the simple 6hb, and VoltronCore |φ| median 17.0° → 41.5°), so the fix belongs at the consumer
  boundary — which is what `_oxdna_cm_radius_map` already does for the oxDNA seed. Full table,
  the insert-series result, and the pipeline validation live in [[measured-atomistic]].
- **Do not "fix" this by editing `_PHASE_*` or the groove constant** — both locked
  ([[feedback_phase_constants_locked]]), and this is precisely the airtight-looking geometric
  argument that rule exists to stop.

**Also worth knowing:** `direction is None` is a *third* convention — `geometry.py` → `−G`,
`atomistic._atom_frame` → the `−1.8°` branch (agrees), `oxdna_interface:119` → `+G` (opposite). Any
shared helper must pin `None` explicitly or it silently picks a side.

**Scope, decided by the user 2026-08-06** — Depth B (consolidate + make measured native everywhere),
delete the legacy **mode** entirely, extra-base/tail placers out of scope. Staged:

- **Stage 1 — behaviour-preserving consolidation.** One `groove_offset_rad` helper in `geometry.py`;
  hoist `_FRAME_ROT_M` / `_REV_P_DELTA_*` / the hardcoded `radians(150.0)` in `atomistic.py`; four
  `mrdna_bridge` sites onto the helper; move the zero-caller `template_p_azimuth_offset_rad` into its
  test; add the missing Python↔JS agreement pins. Acceptance bar is `np.array_equal`, not a
  tolerance — **`tests/test_atomistic_geometry_lock.py` must stay green with the SAME hashes.**
- **Stage 1b** — rewire the JS constant copies (`0.334`/`34.3`/`1.0` ×6 files; four independent slab-
  param copies) onto `constants.js` / a shared `SLAB_DEFAULTS`.
- **Stage 2 — DONE 2026-08-06.** Both groove-sign bugs above, fixed by delegation rather than by
  flipping signs. `BDNA_MINOR_GROOVE_ANGLE_RAD` is now unused in both `oxdna_interface.py` and
  `mrdna_bridge.py` — removing the last re-derivation removed the need for the constant entirely, and
  **`geometry.groove_offset_rad` is the only implementation of the sign rule left in the backend.**
- **Stage 3 — INFRASTRUCTURE DONE 2026-08-06, THE DEFAULT FLIP IS BLOCKED.** Everything except the
  flip has landed: `_positions_for_design` and both extended `_emit_arrs` calls now apply the
  measured re-placement, `_geometry_for_design` **forwards** the flag instead of dropping it, and
  the two firewalls are pinned as tests. `measured_positioning` still defaults **False**.

  **Two of the planned items needed no code.** Extension tails already follow their anchor (they
  read `nuc_pos_map`, populated *after* the re-placement — 0.389 nm move), and their internal step
  is ssDNA contour (0.680 nm, identical in both modes). Bridge anchors likewise read
  `backbone_position` out of `result`. Also: **no fixture in `Examples/` or `workspace/` has a ds
  linker**, so the bridge ↔ `linker_relax` pairing cannot be verified locally at all.

  **The FENE question did NOT need a test session.** The cliff is geometric; `oxdna_health` already
  documents the right oracle (site-based, not CM-based). Measured through the real
  `oxdna_native_seed_map`, bonds over `FENE_RMAX_UNITS`, legacy → measured → measured+conversion:
  6hb_test 2/2/2 · 26hb 0/0/0 · NS_trans_fix 588/620/**535** · VoltronCore 538/580/**551** ·
  U6hb 114/172/**165**.

  **Why a delta re-tune could not fix it, and what does.** The newly-over-cliff bonds are NOT
  already-broken junctions: they sit at 1.08–1.50 units having been 0.63–0.89 under legacy. The
  mechanism is that pulling the bead from r=1.0 to the measured C3' at r=0.804 widens every
  inter-helix crossover gap by 2×0.196 = 0.39 nm. `delta` slides CROSS-STRAND, so it is the wrong
  degree of freedom. The fix is `oxdna_interface._oxdna_cm_radius_map`, which restores the oxDNA
  **centre-of-mass** radius at the seed boundary (`nuc_conf_line` writes `backbone_position` as the
  CM, and `HELIX_RADIUS` is defined as exactly that). It deliberately keeps the +24.5° azimuth —
  restoring that too would just be reverting to legacy wholesale, which is why U6hb keeps most of
  its regression. **Two traps it cost to find:** tail beads have no axis of their own and must be
  translated RIGIDLY WITH THEIR ANCHOR (else 9 extension-FENE tests fail), and the trigger must be
  "bead is at a MEASURED radius", never "bead is not at HELIX_RADIUS" — folded ssDNA seeds and
  relaxed overrides are legitimately off-cylinder and get straightened by the looser rule
  (`tests/test_cg_seed_ssdna_collapse.py` catches it).

  **What blocks the flip — measured, not guessed.** With the default True the fast suite shows
  **24 failures**:
  - **14 pose-fitters needing re-calibration, not re-plumbing** — `linker_relax`, `direct_relax`,
    `duplex_cluster`, child-cluster composition, `assembly_linker_relax`, `headless_build` relax
    routes. They fit poses against bead positions and need their targets re-derived. This is the
    real remaining work and it is a scientific job, not plumbing.
  - **3 oxDNA tests whose PREMISE the measured placement invalidates** — they assert raw NADOC
    geometry is *not* oxDNA-bonded (`assert frac < 0.1`). With measured base beads at the real ring
    centroids (0.62 nm apart, not the reconstructed 1.33) **base-pair retention goes 0 → 100 %**:
    every designed pair is inside oxDNA's H-bond range straight out of the builder. Those tests need
    a deliberately-bad fixture rather than relying on NADOC geometry being bad. **This is the
    headline result of Stage 3 and an argument FOR the flip.**
  - 2 animation geometry-batch snapshot comparisons, 5 misc.

  Still unverified for the flip: every `nuc_pos_override` producer (the measured FORWARD bead sits
  at azimuth **+24.52°**, not 0° — feeding one in as an override rotates every atom ~24.5°),
  `oxdna_surface_strands.py:280-310`, and `_rigid_frame_calibration` (its `assert m_res < 1e-6` at
  `:938` is the tripwire).
- **Stage 4 — NOT STARTED, gated on the Stage-3 flip.** Delete the mode: the flag, both query params,
  the Help toggle, the dual-mode branches. Pointless before the flip lands, since the flag is what
  Stage 4 removes.
  **The 1ZEW arrays stay** (the out-of-scope placers + the `MeasuredTemplateUnavailable` fallback need
  them). "Delete the legacy path" = delete the mode, not the arrays.

**Invariant this item must not violate:** `periodic_polymer._section_frame_from_arrs:111-168`
**analytically inverts** `HELIX_RADIUS` + `±150°` to recover the axis. It is immune only while the
measured re-placement stays at the `_emit_arrs` *serialiser* boundary. **Never push measured
positioning down into `geometry.py`.**

**Deliberately out of scope, logged here so no future sweep re-finds them:**
- The extra-crossover-base placer (`atomistic.py:2960`) and strand-extension-tail placer (`:3322`)
  keep the 1ZEW templates. Their local origins are calibrated to it — swapping moved an insert
  **0.41 nm** off the CG chord and stretched a tail bond to **3.5 Å** (limit 3.2). Re-deriving both is
  its own job, and it **gates retiring `_FRAME_ROT_RAD`**.
- Changing the build-layer groove angle (150°/210° → measured 183.9°). Phase-constant-adjacent, and
  183.9° is flagged **provisional** in both `measured_positioning.py:70-82` and
  [[measured-atomistic]] — every trajectory in the repo was seeded from NADOC's own 183.84° build.
  Settling it needs `experiments/exp52_groove_seed_sweep`, whose **jobs are not on this machine**.

### TD-29 — ⚠ `BDNA_TWIST_PER_BP_DEG = 34.3` is INCOMMENSURATE with the honeycomb 21-bp repeat — crossover strain ramps along every helix (found 2026-08-06)

**The user's invariance principle is correct and NADOC currently violates it: crossover geometry
should depend only on lattice type, and today it depends on how far along the helix you are.**

Honeycomb assumes **10.5 bp/turn**, so the 21-bp repeat is exactly 2 turns and the twist must be
`720/21 = 34.2857°/bp` (= 360/10.5). The shipped constant is the **rounded** `34.3`, leaving
`+0.0143°/bp` → **+0.300° per 21-bp repeat**, which accumulates without bound.

Measured on one invariant crossover class (face (0,1), FORWARD, bp%21 == 0), oxDNA backbone-site
separation along the helix:

| design | twist | drift / 1000 bp | class range (units) | mean | max |
|---|---|---|---|---|---|
| 6hb_validated (1218 bp) | 34.3 | **+0.657** | 1.069 … **1.841** | 0.979 | 1.850 |
| 6hb_validated | **34.2857** | **−0.0000** | 1.069 … 1.069 | 0.920 | 1.069 |
| 6hbx100_noT (115 bp) | 34.3 | +0.651 | 1.069 … 1.124 | 0.919 | 1.133 |
| 6hbx100_noT | **34.2857** | **−0.0000** | 1.069 … 1.069 | 0.920 | 1.069 |

With the commensurate twist the drift is exactly zero **and the two designs become numerically
identical** — which is the invariance that should have held all along.

**What was ruled OUT first** (so nobody re-derives it): the nucleotide geometry is bit-identical
between the two designs (Δazimuth 0.000, Δz 0.000 at every helix/bp/strand — `bp_start` cancels
exactly as the local-bp=0 convention intends); the crossover topology is identical (all spans
`b.index − a.index == 0`, all cross-strand, identical (face, strand, bp%21) classes); XY spacing is
identical at 2.25 nm. The ONLY difference is helix length, i.e. how much ramp each design samples.

**Square lattice is already correct by construction** — `SQUARE_TWIST_PER_BP_DEG = 3*360/32` is
written as a formula and 32 bp is exactly 3 turns. Only honeycomb got a rounded decimal.

**Consequences already observed:**
- It is why the DX-junction balancing rotation looked design-specific (−4° on `6hbx100_noT`, −14° on
  `6hb_validated`). Those were not two optima — they were two samplings of one ramp, and a rigid
  rotation cannot flatten a ramp (338 → 256 over-cliff at best on the long design).
- The residual after fixing the twist is a **uniform** 1.069 u per crossover, slightly over
  `FENE_RMAX_UNITS` = 1.0064. Uniform strain a rotation CAN address — see TD-27's rotation scan and
  `scripts/build_rotated_seed.py`.

**FIXED 2026-08-06 on the user's instruction** ("ensure the positions are periodic over every 21 bp
interval and not cumulative"). The fix is a **new lattice-specific constant**, not a change to the
physical one:

- `constants.HONEYCOMB_TWIST_PER_BP_DEG = 2 * 360.0 / 21` — written as a FORMULA, mirroring
  `SQUARE_TWIST_PER_BP_DEG = 3 * 360.0 / 32`, which was already commensurate by construction.
- `lattice._lattice_twist` returns it for honeycomb. **`BDNA_TWIST_PER_BP_DEG` stays 34.3** as the
  physical B-DNA value; only the LATTICE build changed. Square lattice is provably untouched (its
  branch is unchanged and its designs still carry 33.75).
- The alternative — wrapping the angle every 21 bp while keeping 34.3 — was rejected: it makes the
  phase periodic by inserting a 0.3° kink at each repeat boundary, which is worse than the drift.
- `_lattice_phase_offset` was NOT touched. Periodicity depends only on the twist, so the locked
  phase constants are unaffected (the half-bp term differs by 0.007°, deliberately left alone).

**Verified after the fix:** drift exactly `−0.000000` per 1000 bp; the crossover class collapses from
a 1.069→1.841 ramp to the single value **1.0691**; and `6hbx100_noT`, `6hb_validated` and
`6hbx100_1xT` now return **numerically identical** geometry (mean 0.920, max 1.069) — the invariance
that motivated the fix. The DX-junction rotation optimum is now design-independent too: **−3°** takes
BOTH designs to 0 over the FENE cliff and 0 over the safe threshold (was −4° / −14°, and −14° could
only reach 338→256). CG bead separation across a junction is now exactly equal (0.680/0.680, Δ 0.000);
the residual 0.299 u asymmetry is purely in the oxDNA SITE metric, i.e. the a1/a2 lever arm.

**Test fallout — 8 failures, all understood, none a regression:**
- 5 × `test_atomistic_geometry_lock` goldens. All five golden designs are honeycomb, so all five had
  to move; regenerated deliberately via the documented `--update`. Square was checked as the control.
- `test_hc_twist_is_bdna` asserted the HC twist IS the B-DNA constant — that was the premise being
  changed. Renamed to `test_hc_twist_is_commensurate_with_the_21bp_repeat` and now asserts 21 bp = 2
  turns exactly.
- `test_extension_seed_bonds_sit_inside_the_fene_window[three_prime-10]`: missed an `abs=1e-6`
  tolerance by 1.1e-6 on a bond SOLVED onto the rest length through an arccos/cos round trip.
  Widened to 1e-5.
- `test_configuration_map_matches_file_readout_real_oxpy`: a **periodic-boundary wrap** (50.615 vs
  0.615 nm — exactly one box edge). Now compared under minimum image, with the tolerance set from the
  measured readout distribution (median 3e-14, p99 1.4e-7, max 4.2e-7 nm, 3.8e-5 outlier across runs)
  rather than guessed.

**Pinned so it cannot silently regress** — three tests in `tests/test_geometry.py`:
`test_lattice_twists_are_commensurate_with_their_crossover_periods` (21 × HC = 720°, 32 × SQ = 1080°,
and HC ≠ the rounded physical constant), `test_honeycomb_crossover_geometry_does_not_drift_along_a_helix`
(CG azimuth identical to 1e-9 across every 21-bp repeat over 210 bp), and
`test_the_atomistic_representation_is_periodic_over_the_21bp_repeat_too`.

**Reaches BOTH representations, verified not assumed.** The fix enters at
`deformation.effective_helix_for_geometry` — the documented single phase/axis decision point shared
by CG geometry, atomistic placement and deformation frames — so the STORED `twist_per_bp_rad` in a
saved `.nadoc` (still 34.3 in every existing file) is ignored for lattice helices and the lattice
value substituted. Measured per-nucleotide azimuth periodicity over a 21-bp repeat:

| representation | drift per 21 bp |
|---|---|
| full / CG beads | **5.7e-12°** |
| atomistic (P atoms) | **0.000°** median; deviations only at crossover / domain-end nucleotides |

The atomistic outliers were chased down rather than waved through: on `6hbx100_noT` **all 4 of 4**
sit on a crossover or a domain end, i.e. nucleotides the build deliberately relocates. Two traps in
measuring this — the measured templates are **per-residue**, so bp *i* and *i*+21 must be the same
base before comparing (different bases legitimately place P differently, up to 3.9°); and the raw
max is meaningless because relocated junction nucleotides dominate it, so the median is the signal.

**One documented non-participant:** helices where `_helix_preserves_stored_pose` is true (dedicated
overhang and `__lnk__` helices) bypass `_normalize_helix_for_grid` and keep their stored 34.3. That
is coherent, not a gap — they are free duplexes with no 21-bp crossover period to close over, so the
physical B-DNA value is the right one. Noted in that function's docstring. Only `Untitled.nadoc`
currently has any.

**Still open for the owner:** the `_PHASE_*` calibration was fitted against caDNAno *with the rounded
twist in place* (`experiments/exp15_phase_offset_search`). It was independently validated against
equilibrated-origami MD after this change (NADOC legacy crossover azimuth |φ| median 17.1° vs MD
18.6–19.5°, and now identical across designs), so there is no evidence it needs revisiting — but the
fit's premise did move.

### TD-28 — DEFERRED AUDIT: all linker + relax code, to be reviewed AFTER basic designs are settled (opened 2026-08-06, user decision)

**⚠ SUPERSEDING CONTEXT (2026-08-06):** the owner has since decided the architecture — the ATOMISTIC
rep becomes the single source of truth, the CG "full" rep becomes purely derived + figure-tuned, and
the display rep may never reach a simulation. See [[atomistic-source-of-truth]]. That makes this
audit's real job **re-fitting these modules against the atomistic model instead of CG beads**, not
tidying them in place. It is also blocker #1 of that plan: these fitters write `cluster_transforms`,
a PERSISTED design field, from CG bead positions — so the display rep cannot be tuned at all until
they move. Do this audit and that plan step together.

**Deliberately parked, not forgotten.** While TD-27 is settling the geometry of *basic* designs
(plain lattice helices, staple crossovers, no extra bases, no skips, no ssDNA), the linker and relax
family is explicitly out of scope and gets its own audit afterwards. Do not fix these piecemeal from
inside a TD-27 session — the whole point is to settle the underlying placement first, because these
modules all fit poses *against* bead positions and would have to be re-derived twice otherwise.

**Surface (≈5.2k LOC):** `backend/core/linker_relax.py` (1016), `direct_relax.py` (623),
`bond_relax.py` (472), `assembly_linker.py` (461), `assembly_linker_relax.py` (337),
`flexible_relax.py` (282), `binding_relax.py`, plus `duplex_cluster.py`'s pose fitting and the
`headless_build` relax routes.

**What the audit already has to work with, measured rather than guessed:**
- **These are exactly the 14 fast-suite failures that block TD-27's default flip** — `linker_relax`,
  `direct_relax`, `duplex_cluster`, child-cluster composition, `assembly_linker_relax`,
  `headless_build` relax routes. They need their targets re-derived, not re-plumbed.
- `linker_relax.py:186-193` re-declares `_BDNA_TWIST_RAD` / `_MINOR_GROOVE_RAD` /
  `_HELIX_RADIUS_NM` with the comment "must match the bridge geometry emitted by
  `_emit_bridge_nucs`" — an unenforced hand-sync across two files, and its pointer is stale (it
  names `crud.py`, which no longer owns that function). Atomic pair with any bridge change.
- **No fixture in `Examples/` or `workspace/` has a ds linker at all**, so none of the bridge path is
  covered by a local design. Building one is probably the audit's first task.
- ds-linker bridges and extension tails bypass `_emit_arrs` entirely, so they never receive the
  measured re-placement even when the flag is on (TD-27 finding 3).

**Do not start this until TD-27's basic-design work is closed.**

### TD-25 — `just lint` is now green, but it only lints `backend/ tests/` — 193 findings sit outside the gate (found 2026-07-31, closing TD-01)

TD-01 got `just lint` to exit 0. It does **not** follow that the repo is lint-clean: the recipe is
`uv run ruff check backend/ tests/` ([justfile:163](justfile#L163)), so everything else is invisible
to the gate. `uv run ruff check .` reports **204 total** — 11 of which TD-01 just cleared, leaving
**193 under `scripts/` and the repo root**, e.g. `scripts/test_gromacs_6hb_bend.py` (4× `F841`
assigned-never-used locals — the class of finding that *is* usually a real bug), `test_gromacs_health.py`
(repo root, `F401` numpy + `F541`), `scripts/validate_domain_axis_rotation.py`,
`scripts/verify_blunt_ends_scaffold_delete.py`, `scripts/snupi_visual_compare.py`.

**Why it's debt, and why it is NOT simply "widen the recipe":** several of these scripts are already
known-unrunnable for unrelated reasons (TD-07's `auto_scaffold(mode=…)` ImportErrors — the four
`experiments/exp0*/run.py` scripts that used to be the other blocker were deleted 2026-08-01 per
DEC-02), so widening the glob today would re-RED the gate
that TD-01 just made trustworthy — the exact failure mode TD-01 existed to fix. The `F841`s are worth
a read on their own (an assigned-never-used result usually means a check was silently dropped).

**Options (pick one, don't drift):** (a) widen to `ruff check .` only *after* TD-07 lands (**DEC-02
is now answered — the four `experiments/exp0*/run.py` were deleted 2026-08-01, so TD-07's two scripts
are the last blocker**), (b) add a separate non-gating `just lint-all` now so the findings are at least visible,
or (c) accept `backend/ tests/` as the deliberate gate scope and record that decision here so no
future sweep re-finds it. Note the scope is **not** documented anywhere today — that absence is what
made this a surprise.

### TD-21 — DELETE-ON-COMPLETION: legacy OverhangSpec pose overlay + standalone orientation panel (superseded by the duplex CLUSTER)
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

### TD-18 — Stale workspace-fixture test skips instead of running (TODO: re-pin or rebuild fixture)
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

### TD-19 — Unimported frontend modules — 5 held, 2 deleted (dead-file sweep 2026-07-25)
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

### TD-07 — Dead `lattice.auto_scaffold(mode=…)` API still referenced by 2 scripts + 1 auto-loaded rule (found 2026-07-30, `/audit-plan`)
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

### TD-08 — `CELLS_6HB` / `CELLS_18HB` are copy-pasted with *divergent* geometry (found 2026-07-30, `/audit-plan`)
Both read like shared fixtures — every doc that mentions them says "use `CELLS_6HB` as the minimum test
fixture" — but there is no shared definition. Each is re-declared locally with **different cell lists**:
`CELLS_6HB` in `scripts/inspect_bp0.py:16` `[(0,0),(0,1),(1,0),(1,2),(0,2),(2,1)]` vs
`tests/test_helix_neighbors.py:61` `[(0,1),(0,2),(0,3),(1,1),(1,2),(1,3)]` (also
`scripts/gen_examples.py:56`, `tests/test_overhang_geometry.py:47`); `CELLS_18HB` in 5 more places
(`tests/test_helix_neighbors.py:58`, `experiments/exp06,07,09/run.py`, `gen_examples.py:61`). The two 6HB
variants are not the same shape — one is a bent/L cluster, the other two clean rows — so a test copied
between files silently changes its neighbour graph. Fix = one fixture module; until then, never copy the
name without copying the list.

### TD-14 — Cadnano-2D-mode stragglers (found 2026-07-30, `/audit-plan` rule sweep)
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
- ~~**Reverse coupling:** `overhang_pathview.js` imports `BP_W/CELL_H/PAIR_Y/GUTTER` from
  `cadnano-editor/pathview.js`~~ — **FIXED 2026-07-31 while closing TD-03.** The 9 drawing-grid
  constants were lifted verbatim into a new leaf module `cadnano-editor/pathview/layout.js` (zero
  imports, pinned by `layout.test.js`); `pathview.js` now imports them and its
  `export { BP_W, CELL_H, PAIR_Y, GUTTER }` re-export is gone. Probe confirmed `pathview.js` had
  exactly **two** importers repo-wide, so nothing else broke: `cadnano-editor/main.js:41` takes only
  `initPathview`, and the fork now takes its 5 shared constants from `layout.js`. **The 4977-LOC
  module no longer enters the main-app bundle.** *Still true, and still fine:* the fork imports
  `STAPLE_PALETTE` + 14 `CLR_*` from `cadnano-editor/pathview/palette.js` — but that is already a
  129-line leaf with **zero imports of its own**, so it carries no graph. Cross-app value coupling
  is now explicit and one-way into two leaf modules; that is the intended end state, not debt.

### TD-26 — the *3D* store has the same undeclared `unligatedCrossoverIds` key (found 2026-07-31, closing TD-03)
`frontend/src/state/store.js` has **no** `unligatedCrossoverIds` in its initial state, yet
`api/client.js:428` and `:743` both `setState` it from `json.unligated_crossover_ids`. Exactly the
editor-store defect TD-03 just fixed, in the app that has the *un*defended readers
(`frontend/src/main.js:1778`, `scene/response_delta.js:106` pass the raw value on). **Not a live
crash today** — the sink `unligated_crossover_markers.js:103` normalises with
`new Set(unligatedIds ?? [])` — so this is shape hygiene, same as TD-03's. Deliberately **not** fixed
opportunistically in that pass: the 3D store dispatches by slice (`_SLICES`, `store.js:395-398`), so
adding a key means picking its slice, which is a real decision the TD-03 probe didn't cover.
Fix = add the key to the right slice's initial state, then drop the `?? []` folklore from the two
call sites. Cheap; needs the slice question answered first.

### TD-15 — Animation stragglers (found 2026-07-30, `/audit-plan` rule sweep)
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

### TD-12 — Selection stragglers (found 2026-07-30, `/audit-plan` rule sweep)
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

### TD-22 — Rule coverage is 33% of production LOC — the measured hole (found 2026-07-30, `/audit-plan` coverage sweep)
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

### TD-13 — `api-and-state` stragglers (found 2026-07-30, `/audit-plan` rule sweep)
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

### TD-20 — `main.js` stragglers — the composition root is re-growing and has zero tests (found 2026-07-30, `/audit-plan` rule sweep)
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
- ~~**`_floorReach` is a permanent `() => null` stub**~~ **RESOLVED 2026-08-01.** The seam is live:
  photo mode's shadow catcher (`scene/photo_renderer/shadow_catcher.js`) reports its centre + far
  corner through `getFloorReach()`, so the per-frame branch does real work. See
  [[project_photo_mode]].
- **The main.js carve-up loop has no slash command.** `/carve-router` explicitly disclaims main.js
  ("NOT for frontend main.js — that's its own loop"), but that loop's only artifacts are
  `main_js_carveup.md` + `main_js_extraction_log.md` + `memory/main_init_detail.md`. Every other
  loop in the repo has a skill; this one is invoked from memory. Plausible cause of the 5-week idle.

### ~~TD-05~~ — Rendering stragglers — **CLOSED 2026-08-01** (2 FIXED / 2 DECIDE / 1 ACCEPTED / 1 PROMOTED)
Found 2026-07-30 rewriting `.claude/rules/rendering.md` + `RUNBOOK_RENDERING.md`.
▶ REMAINING: nothing in this loop. Two user calls are parked as **DEC-03** and **DEC-04** below.

- ~~**`deform_view.reapplyLerp()` is exported with ZERO callers**~~ — **DECIDE 2026-08-01 → DEC-03.**
  Probe reproduced every claim exactly, no drift: definition `deform_view.js:378`, export `:409`,
  and the ONLY other references repo-wide are the two *comments* at `helix_renderer.js:555,595` —
  zero call sites in any code file, string-name search included. Confirmed
  `helix_renderer.js:3317` is `if (!updates) { revertToGeometry(); return }` — argument-less, so it
  restores `nuc.backbone_position` (the **deformed** geometry) ignoring `_currentT`, exactly the
  mechanism described. One correction: `oxdna_display.test.js:425` asserts only
  `applyFemPositions` `toHaveBeenLastCalledWith(null)` — it would **not** fail if a `reapplyLerp`
  call were added after it, so it is a much weaker argument for "obsolete" than the entry claimed.
  **The identical bullet is the first one in TD-09 — resolving DEC-03 closes both.**
- ~~**`refreshAllGlow()` refreshes 6 of the 7 glow layers**~~ — **FIXED 2026-08-01.** Real bug, and
  the entry **understated** it. Line anchor had drifted `:955-962` → `:975-982`; content was exact
  (7 created at `:60,62,65,68,71,75,106`, `_captureGlowLayer` the only one omitted). The severity
  miss: `refreshAllGlow` has **5 callers**, and the entry only knew about unfold. The fifth is
  `design_renderer.js:1069`, **inside `applyFemPositions`** — i.e. every simulation frame. And
  `_extraNucs` are, per `:420-422`, the oxDNA **surface capture strands** that `applyFemPositions`
  moves; `_applyCaptureGlow` (`:431`) hands the layer the *same* entry objects the helix renderer
  mutates in place (`helix_renderer.js:3335` `entry.pos.set(...)`), and `_applyCaptureGlow` is
  called from only `:502` (post-rebuild) and `:1111`. So with "Highlight strands" on, the white
  halos stayed at the design positions while the strands they decorate moved to the oxDNA frame,
  until the next full rebuild. Fix = one added `_captureGlowLayer.refresh()` line.
  **Pinned by a new `frontend/src/scene/design_renderer.test.js`** (3 tests) — source-text
  assertions that the created-glow-layer list and the refreshed list agree, so an 8th layer can't
  repeat this. **Pin proven by test-ordering:** written first, run against the unfixed file, failed
  with exactly `[ '_captureGlowLayer' ]`, then the fix made it green.
- ~~**`scene/arc_tube_geometry.test.js` (4 tests) tests a module that does not exist**~~ —
  **DECIDE 2026-08-01 → DEC-04** (deleting a test is a user call, `CLAUDE.md` → Risky-action).
  Probe confirmed with `rg --files`: exactly one `arc_tube` file in the repo and it is the
  `.test.js`; `frontend/src/scene/` has `assembly_connector_arcs.js` / `flexible_arcs.js` /
  `overhang_link_arcs.js` but **no `arc_tube_geometry.js`**. It imports only `vitest` + `three` and
  re-implements the tube inline. **New finding: it has also drifted** — it hardcodes radius `0.63`
  while the live constants are `PREVIEW_ARC_RADIUS = SELECTION_ARC_RADIUS = 0.147`
  (`design_renderer.js:78-79`, changed 2026-06-07), so its exact bbox tuples pin geometry the app
  no longer builds. Green, and describing nothing.
- ~~**The CG render pipeline has ~20 tests for ~8.6k LOC**~~ — **PROMOTED 2026-08-01 to
  `.claude/rules/rendering.md` § Coverage — honest**, which now carries the ranked plan (pin pure
  functions; use source-text cross-list tests) and is the owner because it **auto-loads** on these
  files, which this ledger does not. All figures re-verified: `design_renderer.js` 1,529 → **1,549**
  LOC (pre-fix), `helix_renderer.js` **5,232** exact, `glow_layer.js` 188; no `design_renderer.test.js`
  or `glow_layer.test.js` existed; `helix_renderer.test.js` is 4 tests on `orderStrandNucleotides` +
  `directConnectedOverhangIds` only; all four named sibling tests do build literal `designRenderer`
  mocks. Not started here — a test program is not this loop (`design_renderer.test.js` above is the
  first instalment, added because the glow fix needed a pin).
- ~~**Stale `blunt_ends` naming survives the `domain_ends.js` rename**~~ — **3 comments FIXED /
  identifier rename ACCEPTED, 2026-08-01.** Fixed the three comments (`loop_skip_highlight.js:254`,
  `unfold_view.js:1170`, `cadnano_view.js:91`). One anchor was **wrong**: `main.js:2988` is a
  comment about the extensions dialog; the real init is **`main.js:3006`** (that stale anchor was
  also copied into 4 `.claude/rules/*.md` — all corrected). **"Cosmetic" was badly understated and
  the rename is now ACCEPTED, not deferred:** `getBluntEnds` is a named dep in **7 factory
  signatures** (`unfold_view:42`, `cadnano_view:42`, `deform_view:25`, `slice_plane:144`,
  `expanded_spacing`, `animation_player`, `debug_overlay`), a destructured `bluntEnds` opt in 4 more
  (`photo_mode`, `overhang_orientation_panel`, `response_delta`, `script_runner`) with 4 test files
  building the mocks — and **`toolFilters.bluntEnds` is a PERSISTED store key** (`store.js:137`, in
  the persisted `ui` slice `:411`, read by 4 modules, pinned by 3 test files). Renaming it silently
  resets that toggle for every existing session unless migrated: not worth it for a name.
  **Do not blanket-rename `blunt`** — `ui/blunt_end_menus.js`, `scene/blunt_end_connectors.js` and
  the backend's `blunt` usage are correctly named (real blunt-end duplex termini). `blunt` appears
  in 79 files; only the `getBluntEnds`/`bluntEnds` wiring is the stale subset.
- ~~**`ui/representation_switcher.js` has 7 representations; `setDetailLevel` has 3 levels**~~ —
  **ACCEPTED 2026-08-01.** Both counts verified exact and line-exact (`:36-44`, `helix_renderer.js:64`),
  and "no shared constant" confirmed: `CG_LOD` is imported by exactly 3 modules, all in the assembly
  stack, and `representation_switcher.js` is not one of them. The entry says it plainly — *"not a bug
  today"* — and the mapping is documented in `.claude/rules/rendering.md` § Representation / LOD plus
  a comment block at `representation_switcher.js:29-35`. Deliberate: 4 of the 7 reps are separate
  renderers, so a shared enum would imply a relationship that does not exist. Don't re-report.

### TD-09 — Deformation stragglers (found 2026-07-30, `/audit-plan` rule sweep)

- **`deform_view.js` exposes 8 methods; 4 have ZERO callers in all of `frontend/`** —
  `reapplyLerp` (`:378`), `snapOff` (`:218`), `setT` (`:388`), `getT` (`:403`), plus `dispose`.
  **`reapplyLerp` half: DECIDE 2026-08-01 → DEC-03** (probed while closing TD-05 — same bullet;
  every anchor reproduced, and `oxdna_display.test.js` turned out to be a weaker "it's obsolete"
  argument than claimed). The `snapOff`/`setT`/`getT` half is still open here.
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

### TD-10 — Cluster-scoped deformation stragglers (found 2026-07-30, `/audit-plan` — [[deformation-cluster-scope]])

- **The in-place-PATCH edit branch in `deformation_editor.js` is fully written and unreachable.**
  `_editOpId`/`_editOrigParams`/`_editDirty`/`_editCommitted` (`:60-63`), their assignment in
  `startToolForEdit:163-166`, the revert-on-exit guard `:510-516`, and the `_editOpId` arm of the
  `previewDeformation` update path (`:388`, `const updOpId = _editOpId ?? _previewOpId`) are dead:
  the only UI caller now passes `opId=null` (`main.js:1523`, the peel-and-preview rewrite).
  `markEditCommitted` (`:117`) is still called from `main.js:1383` but only feeds the unreachable
  guard. **Decide before deleting** — the branch is the cheaper edit flow (one PATCH per slider tick
  vs delete+re-add) and its coalescing guard is shared with the live `_previewOpId` path, so a naive
  delete takes the flood protection with it.
- **`_arm_filter_cluster` (`deformation.py:603`) resolves by arbitrary list order.** It returns the
  first **non-default** cluster containing the helix and never consults `op.cluster_ids`, so a helix
  in two non-default clusters picks a winner by `design.clusters` ordering. This is the mechanical
  root of the "two clusters sharing a helix conflict" limitation and the prerequisite for any
  per-cluster sub-axis work.
- **`cluster_ids` vs `affected_helix_ids` can drift silently.** Scope is frozen into
  `affected_helix_ids` at create/edit time and *only that* is read by geometry; a saved op is never
  recomputed on load. No validator checks the two agree. Cheap fix: assert consistency in the debug
  route (`routes_deformation.py:203`) or on load.
- **Legacy singular `cluster_id` is silently swallowed, not rejected.** `backend/core/models.py`
  declares no `model_config`/`ConfigDict`, so pydantic v2's default `extra='ignore'` drops unknown
  fields on every model in the file. For deformations that means an old op loads *unscoped* with no
  warning. Worth deciding globally (`extra='forbid'` on `Design`-adjacent models would surface a
  whole class of silent-drop bugs, and would need a load-path audit first).
- **Stale docstring** at `backend/api/crud.py:9924` still says the deformation edit branch updates
  "`affected_helix_ids` / `cluster_id`" — singular field is gone, and the branch delegates to
  `core/feature_log_edit.py` rather than updating anything itself.
- **Vestigial singular-era coercion** at `frontend/src/api/client.js:1331` —
  `Array.isArray(clusterIds) ? clusterIds : (clusterIds ? [clusterIds] : [])` defends against a
  scalar `cluster_id` that no caller has passed since 2026-05-14.
- **Name collision:** two unrelated `_bundle_centroid_and_tangent` — `deformation.py:189` (8 call
  sites, the arm-centroid one) and `loop_skip_calculator.py:148`. A grep for the name returns both.

### TD-16 — Unfold stragglers (found 2026-07-30, `/audit-plan` rule sweep)

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

### TD-17 — Strand-anim stragglers (found 2026-07-30, `/audit-plan` rule sweep — final rule)

- **`strand-anim/params.js` `DEFAULTS` is a production constant source, not sandbox-local.**
  `scene/overhang_unzip_overlay.js:33-34` imports it as `STRAND_DEFAULTS` and reads `rise`,
  `armPull`, `meltBp` at `:83-84`. Editing a "sandbox slider default" silently changes the
  editor's overhang unzip animation. Three more editor modules import from this directory
  (`overhang_strand_anim.js:28` → `createStrandRenderer`; `overhang_unzip_overlay.js:33` →
  `meltFraction`; `ui/strand_anim_panel.js:11-12` → `createParamState`/`createPhiTicker`).
  Nothing in either directory says so; the topic file still calls the module "drop-in" in the
  future tense.
- **Second hand-rolled implementation of the strand-list contract.**
  `scene/overhang_strand_anim.js:441` and `:599` build `{pos,tan,bn,role}` inline instead of
  calling any `strand-anim` builder, then feed it to the sandbox's `createStrandRenderer`. A
  change to the contract shape must be mirrored by hand in both files; nothing pins them. Same
  shape as the `expanded_spacing.js` divergence from the unfold pass. It also re-implements
  `melt.js`'s exported `smoothstep` inline **4×** (`_sstep` at `:247, :377, :519, :567`), which
  is why that export has zero external importers.
- **Latent slab-radius divergence.** The model's helix radius is `R = params.W * 0.5`
  (`geometry_helical.js:58`, `geometry_displacement.js:60`) with `W` adjustable over [0.5 … 4.0]
  (`params.js:12`), but the renderer's slab offset uses hard-coded `HELIX_RADIUS = 1.0`
  (`strand_renderer.js:98`). Correct only at the default `W = 2.0`; any other `W` renders slabs at
  the wrong radial offset. Not a live bug (nothing ships a non-default `W`), but the rule/topic
  file both state `HELIX_RADIUS 1.0` as an invariant without the condition.
- **1,084 LOC / 0 tests, and the builders are the easiest test target in the repo** — pure, zero
  imports, deterministic `(params, phi) → Float32Arrays`. No `.test.js` under
  `frontend/src/strand-anim/`, and no test file anywhere mentions `buildStrandGeometry`,
  `createStrandRenderer`, `meltFraction` or `createPhiTicker`. Add the two consumers
  (`overhang_strand_anim.js` 711, `overhang_unzip_overlay.js` 175) and it is 1,970 LOC untested.
- **Six stale comments inside the subsystem** (rule now carries a Traps section):
  `geometry_straight.js:40-44` and `geometry_helical.js:49-53` both `@returns` the pre-2026-05-29
  `{posA,tanA,bnA,posB,…}` shape the functions stopped returning; `geometry_helical.js:30-31`
  says the renderer is "in app.js" (it is `strand_renderer.js`); `geometry_displacement.js:8`
  references a variable `p` that does not exist in the file (it is `b`/`bIdx`); `ticker.js:10-11`
  calls `animation_player.js` "990-line" (1,298) and `strand_renderer.js:14-15` calls
  `helix_renderer.js` "4k-line" (5,232).
- **Three 0-importer exports:** `geometry_helical.js:39` re-exports `nucsPerStrand` (everyone
  imports it from `geometry_straight.js:33`), `model.js:35` re-exports it again, and
  `melt.js:13` `smoothstep` (see above). Facade surface vs dead code — decide before deleting.

### TD-11 — Autorefine skip placement — stragglers found by the 2026-07-30 plan audit ([[project_regional_autorefine]])
- **`redistribute_by_twist_profile` (`backend/core/regional_skip_placer.py:208`) is fully
  orphaned** — zero non-test callers; its only references are 3 tests
  (`tests/test_regional_skip_placer.py:207/234/263`). It is the wholesale-redistribution
  controller that was refuted four times (LESSONS A7). **Decide before deleting:** the rest of
  the module is load-bearing (`core_candidates` is imported by production
  `backend/core/cando_autorefine.py:161-162`), so this is a function-level delete, not a
  module-level one, and the 3 tests go with it.
- **A dead API surface reachable only by hand-POSTing.** `AutorefineStartRequest.regional` /
  `w_dev` / `w_strain` / `min_spacing` (`backend/api/routes_autorefine.py:31-46`) thread all the
  way down to `place_regional_skips`, but the frontend exposes **no control for any of them**
  and `regional` defaults `False`. Either delete the four fields + the `regional=True` branch in
  `autorefine_sq_design` (`skip_twist_tuning.py:599-622`, which is also the only builder of the
  `on_measure` hook), or document them as a deliberate expert/API-only escape hatch. Right now
  they read as a live feature.
- **The shipped fine-tuner ranks on an unsigned metric.** `greedy_finetune_skips` /
  `identify_finetune_edits` accept an edit on `dev_max` improvement, which violates LESSONS A6
  (unsigned deviation can't tell over- from under-wound). Needs the signed-twist variant. Already
  flagged as follow-up in `project_skip_twist_curvature_sweep.md`; repeated here because the code
  is **always on** for every ✦ Autorefine click.
- **`finetune` has two different defaults.** `AutorefineStartRequest.finetune=True`
  (`routes_autorefine.py:47`) but `autorefine_sq_design(..., finetune=False)`
  (`skip_twist_tuning.py:504`). Any non-route caller (headless, scripts, tests) silently gets the
  opposite behavior from the app. Pick one.
- **Stale doc citation in code:** `backend/core/skip_finetune.py:9` points at
  `project_regional_autorefine.md` for the ±30–45° wholesale-swing figure. That figure is a
  pre-exp34 mid-transient measurement (LESSONS A8) — still qualitatively right, but the comment
  should say so or point at `project_skip_twist_curvature_sweep.md`.

### TD-24 — Photo-mode v1 stragglers (found 2026-07-30, `/audit-plan` — [[photo-mode]])

- **A live module holds an orphaned function.** `frontend/src/scene/photo_renderer/material_presets.js`
  SURVIVED the v1 archival (it is one of the six shared sub-modules v2 kept), but its
  `makeFluorophoreEmissive()` + `FLUORO_EMISSIVE_MAX = 25` (`:163`/`:178`) have **no caller under
  `src/`** — live `photo_mode.js:42` imports only `makeMaterial`, and the only callers are in
  `frontend/archive/photo_mode_v1/photo_renderer.js:356,1314`. There is no `material_presets.test.js`
  either, so it is uncalled *and* untested. **Do not just delete it:** its comment block (`:152-162`)
  is the only in-code record of *why* the fluorophore slider had to be clamped (bloom samples
  pre-tone-map, so filmic roll-off can't tame a maxed emissive) — that explanation is now also in
  `project_photo_mode_archive.md`, so deletion is safe once you've checked v1 revival is off the table.
- **Stale sync pointer in that same comment.** It cites `_FLUORO_LIGHT_GAIN in photo_renderer.js` —
  there is no live `frontend/src/scene/photo_renderer.js` (archive-only). Same shape as the
  `STAPLE_PALETTE` comments above: a comment naming a file that no longer holds the constant.
- **~1400 LOC of archived tests that can never run.** `frontend/archive/photo_mode_v1/` contains
  `photo_renderer.test.js` (24 `it(`, incl. a 21-case table), `photo_mode.test.js` (15),
  `style_presets.test.js` (13), `photo_renderer/floor.test.js` (2) and two Playwright specs — all
  outside vitest's `include: ['src/**/*.test.js']`. Fine as archive, but nothing marks them as
  non-running, so a future grep for "is X tested?" will find false positives. Consider a one-line
  banner in `frontend/archive/photo_mode_v1/README.md`.
- ~~**`_floorReach` is a permanent `() => null` stub** in `main.js`~~ **RESOLVED 2026-08-01** —
  the shadow catcher closed the seam. See [[project_photo_mode]].

### TD-23 — Duplex-foundation stragglers (found 2026-07-30, `/audit-plan` — [[overhang-duplex-foundation]])

- **Two `showChoice` implementations.** `frontend/src/ui/primitives/choice.js:32` (used by
  `overhang_gen.js`, `run_location.js`) and `frontend/src/ui/primitives/confirm.js:111` (used by
  `job_activity.js`) both export a function of that name from the same `primitives/` directory.
  A session that imports "the" `showChoice` has a 50% chance of the wrong modal. Pick one, keep a
  re-export shim in the other for a release. (Same shape as the duplicated `PERSP_FOV_DEG`.)
- **Every e2e spec hardcodes an absolute fixture path.** `frontend/e2e/duplex_pairing_display.spec.js:8`
  is `/home/joshua/NADOC/workspace/playwright_tests/duplex_demo.nadoc`, and **20 spec files** do the
  same. It happens to work on both computers because both check out to `/home/joshua/NADOC`, but it
  is a one-rename-away break. A `FIXTURE_DIR` helper resolved from the spec's own location would
  retire all 20 at once.
- **The plan-owned duplex code defects are NOT here** — orphaned `revert_duplex_relocation`,
  never-read `binding_mode`/`target_joint_id`/`locked_angle_deg`, the false `models.py:537`
  docstring, and the three zero-caller client fns are open items **1-6** in
  `project_overhang_duplex_foundation.md`, because that plan owns them.
- **Three stale references to a deleted function, `apply_end_to_root_binder`.** The end-to-root
  binder *splice* was deleted 2026-06-30 (unified into one relocated `OverhangBinding`), but two
  docstrings — `backend/core/lattice.py:3394` and `:3693` — plus a comment at
  `backend/core/deformation.py:1029` still describe it as if it runs. A session reading
  `autodetect_overhangs` or the co-rotation predicate is told about a code path that no longer
  exists. (Found by `/audit-plan` 2026-07-31 on `overhang_connections_panel`; the panel-owned
  stragglers stayed in that plan's head.)
- **`sequences.reassign_if_sequenced` (`backend/core/sequences.py:742`) has zero callers.** It was
  the design-wide re-derive, replaced 2026-07-27 by targeted `reassign_strands` +
  `overhang_dependent_strand_ids` (it silently destroyed hand-typed staple sequences). It was left
  in "for headless/ML callers" — no such caller was ever written, in backend, tests, or scripts.
  Its only surviving mentions are docstrings that *describe the behavior it no longer performs*
  (`sequences.py:719`, `tests/test_overhang_sequence_propagation.py:7`, `tests/test_targeted_reassign.py:6`),
  which is worse than nothing: a session reading them is told the old semantics are current.
  Delete the function and fix the three docstrings. (Found by `/audit-plan` 2026-07-31 on
  `overhang_sequence_display`; that plan's own display defects stayed in its head.)
- **`.claude/rules/rendering.md:237` cites `main.js:4119`; the glow-layer injection is at
  `main.js:4130`.** Eleven-line drift in an auto-loaded rule. Cheap to fix, but the real lesson is
  that line anchors in auto-loaded rules need re-probing whenever `main.js` moves.
- **~900 LOC of zero-importer parameterization tooling, with a third duplicated ESS estimator.**
  `backend/parameterization/local_crossover_extract.py` (426 L) and `bundle_extract.py` (480 L)
  are *tracked* backend modules with **no importer anywhere** — not backend, not tests, not
  scripts (`bundle_extract` is named only by itself). They are hand-run research tooling that
  landed in `backend/` instead of `runs/`. Worse, effective-sample-size is now implemented
  **three times**: `convergence.py` (the canonical gate), `bundle_extract.py:186` `_ess`, and
  `local_crossover_extract.py:154` `_ess_1d` — so a fix to the convergence criterion reaches one
  of three call paths. Either import `convergence._ess` from both, or move both modules out of
  `backend/`. `validation_stub.py` is a related stub with no caller (and its own `ruff` F821
  exemption at `pyproject.toml:84`). (Found by `/audit-plan` 2026-07-31 on
  `pipeline_validation_log`.)

### TD-06 — Cross-cutting sweeps: the same rot found independently by 3+ audits (synthesized 2026-07-31)

Each bullet below is written up *inside* two or more other TD sections. Resolving it means one
repo-wide sweep, then striking it in **every** section that names it (listed per bullet). Doing it
per-section is how it got re-discovered three times.

- **`docs/triage/` is 3-for-3 fiction across the audits that probed it** — `05_animation.md`
  documents `config_panel.js` / `DesignConfiguration` / `update_configuration` (none exist);
  `04_deform_tools.md` cites the never-existent `MAP_DEFORMATION.md` and repeats an obsolete
  `Design(...)` invariant as *critical*; `00_MASTER_GUIDE.md` / `01_expanded_quick_view.md` /
  `02_cadnano_3d_mode.md` cite `MAP_CADNANO.md`, also never existent. **12 files, 3 probed, 3 false.**
  Sweep = probe the other 9, then delete the directory or move it under `archive/` with a banner.
  **Deleting a docs directory is user-confirm territory → expect DECIDE, not a silent `rm`.**
  (Named in TD-15, TD-09, TD-16.)
- **Phantom `MAP_*.md` citations — 5 filenames that never existed in this repo.** They read
  authoritative and cost a search every time. Sweep `rg 'MAP_[A-Z_]+\.md'` and repoint or strike
  each cite. (Named in TD-09, TD-16.)
- **Vestigial `, null)` init arguments — 3 known, sweep for the rest.**
  `initCadnanoView(..., _getCrossoverLocations, ...)` (`cadnano_view.js:42`, always `null` from
  `main.js:1542`), `initDeformView`'s 3rd `_getCrossoverMarkers` (`main.js:1558`),
  `initUnfoldView`'s 7th `_getCrossoverLocations` (`main.js:1535`). Each is a dead parameter that
  a reader must trace. One sweep of the `init*` call sites, not three notes.
  (Named in TD-14, TD-09, TD-16.)
- **"Keep in sync with X" comments naming a file that no longer holds the constant.** Confirmed:
  ~~`cadnano-editor/pathview/palette.js:83-84` and `backend/core/constants.py:324`~~ — **FIXED
  2026-07-31 (TD-02)**, along with two more the sweep missed (`pathview/palette.js:6-9`,
  `surface.py:44`); the palette copy list now lives in one place. Still open:
  `photo_renderer/material_presets.js` citing
  `_FLUORO_LIGHT_GAIN in photo_renderer.js` (no live file of that name). Sweep for the pattern —
  a stale sync pointer is worse than no pointer, because it *stops* the reader looking further.
  (Named in TD-02, TD-24.)
- **Line-number anchors inside auto-loaded `.claude/rules/*.md` drift silently.**
  `rendering.md:237` cites `main.js:4119`; the glow-layer injection is at `main.js:4130`. Rules are
  loaded automatically, so a drifted anchor teaches the wrong location with no signal. Sweep every
  `file.js:NNNN` in `.claude/rules/` and re-probe; prefer symbol names over line numbers when
  rewriting. (Named in TD-23, and it is the mechanism behind half of TD-20's staleness.)
