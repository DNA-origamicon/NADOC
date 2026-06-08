# backend router carve-up map — crud.py / assembly.py decomposition backlog

**Purpose.** `backend/api/crud.py` (≈15.6k lines, 190 routes) and `backend/api/assembly.py` (≈7.8k lines,
112 routes) are the two backend god-files. This loop decomposes them the way `main_js_carveup.md`
decomposed `main.js` — **one cohesive block per session, one commit, a metrics row in
`backend_router_extraction_log.md`.** The pattern is already proven twice in-repo:
`routes_loop_skip.py` (Refactor 10-F) and `routes_camera_poses.py` (13-B) were lifted out of crud.py
this exact way. This framework just makes the loop repeatable and *measured*, so we don't backslide into
shoveling lines around.

**The two god-files are worked independently. A session names ONE.** See "Single-line invocation" below.

> **⚠ THIS MAP IS SEQUENCING-ONLY.** Line numbers drift on every extraction; the banner text and the
> coarse coupling probe are the only durable facts here. Before claiming any region: **READ it**, find
> where the *cohesive* block actually ends (banners group by adjacency, which ≠ cohesion), and re-derive
> its real route count / back-import surface / risk. Locate a region by its `# ──` banner
> (`grep -n "# ──" backend/api/crud.py`), never by the printed line number. Fix the entry you touched on
> your way out so the next session pays less tax than you did.

---

## Target shape (NOT frontend factories)

main.js extracted to `initX({deps})→{api}` closures. **The backend target is different — it is two shapes,
and which one a block wants is the first thing you decide:**

1. **Router extraction** — a cohesive *route cluster* (all `/design/animations/*`, all `/assembly/joints/*`,
   …) → a new `backend/api/routes_<area>.py` holding its own `router = APIRouter()`, its request-body
   `BaseModel`s, and the route handlers. **URLs are unchanged** (the prefix stays `/api`, mounted in
   `main.py` via `app.include_router(...)`). Shared response helpers (`_design_response`,
   `_design_response_with_geometry`, `_helix_label`) **stay in crud.py and are imported back** — that
   import is fine *and small* (see the coupling gate). Mirror `routes_loop_skip.py` / `routes_camera_poses.py`
   exactly; they are the canonical templates.

2. **Service extraction** — *business logic* sitting inside a fat route handler, or in the api-layer's
   "Internal helpers" block, that has no business being in the api layer at all → a pure, HTTP-free function
   in `backend/core/<area>.py`, unit-tested directly (no `TestClient`). The route handler shrinks to
   **parse request → call the core service → format the response.** This is where the *real* improvement
   lives: crud.py's lines 157–1618 are ~1460 lines of "Internal helpers" (cluster autodetect at 848–1168,
   etc.) — that is core logic marooned in the api file. `backend/core/` may import nothing from `backend/api/`;
   the dependency arrow is **api → core, never the reverse.**

A single session usually does ONE of these. Some blocks want both (lift the cluster to a router *and*
push its fattest handler's logic into core) — that's two commits, do the service push first.

---

## Improvement metrics — the anti-shovel contract (READ THIS; it is the point)

The failure mode this loop exists to prevent: **relocating 400 lines from crud.py to routes_foo.py, watching
crud.py's LOC drop, and calling it a win — when routes_foo.py still imports 25 private helpers back from
crud.py.** That is not decoupling; it's a god-file with a long umbilical cord. LOC went down, coupling
didn't, nothing improved.

So **LOC is never the pass criterion.** It is narrative only — a *side effect* of a real improvement, logged
for the story, never the goal. A move is valid only if it moves one of these the right way:

### Primary metric — back-import surface `B` (the shovel detector)
`B` = the count of **distinct private symbols** (`_foo`) the new `routes_<area>.py` imports back from
crud.py/assembly.py. Lower is better.
- **The two shipped exemplars have B = 1–2** (`_design_response`, +`_helix_label`). That is the bar.
- **Gate: B ≤ 3 to ship a router extraction.** If a candidate's B is higher, the cluster is NOT cleanly
  separable yet — you have three honest options, in order of preference:
  1. **Co-extract the shared helpers into `backend/core/<area>.py`** (they were service logic too) and import
     them from core in *both* files — coupling genuinely drops.
  2. **Promote a truly-shared helper** (used by 50+ routes, like `_design_response`) — it stays in crud.py and
     is imported; that's an accepted shared-kernel dependency, not coupling debt. Count it toward B but don't
     let it block you (the exemplars do exactly this).
  3. **Pick a different cluster.** A high-B cluster that's all bespoke helpers is telling you it isn't ripe.
- Measure B with the probe in the extraction log's "Coupling probe" section before you start. Log
  *before-B and after-B* in the metrics row.

### Secondary metrics (log the ones that moved)
- **Handler thinness** — for a service extraction, the max route-handler body LOC in the touched cluster,
  before→after. A handler doing 120 lines of math should leave ~15 (parse→delegate→respond). Report the drop.
- **Business-logic lines relocated to a testable core fn** — the count of lines that moved from an api file
  into a `backend/core` function that now has a direct unit test. This is the delegation metric; it's the
  positive twin of B.
- **God-file route count** — routes remaining in crud.py / assembly.py. This is the LOC-correlated metric
  that actually *means* something (fewer concerns in the god-file), so track it instead of raw LOC.
- **Cohesion** — state the new module's **one reason to change** in a sentence. If you can't, it's not cohesive.
- **Tests** — ≥1 direct unit test per extracted core service fn; `just test` green (cite count). Router-only
  lifts (verbatim handler bodies, behavior preserved by construction) are covered by the existing route tests
  + the green suite; a service extraction MUST add a unit test for the new pure fn.

### The required justification line
Every metrics row ends with one sentence: **"Real improvement, not a shovel: ___"** naming which metric
above moved and why this wasn't just relocation. If you can't write that sentence honestly, you shoveled —
revert and pick a cleaner block.

---

## Per-session loop protocol

A fresh session keeps token cost low. Per session:

1. Read this map + `backend_router_extraction_log.md` (conventions + coupling probe + lessons + difficulties).
   Skim `.claude/rules/api-and-state.md` (the mutation flow you must not break).
2. **The session names ONE file** (crud or assembly — see invocation). Pick the topmost unchecked region in
   that file's backlog whose coupling probe looks cleanest, or one the user names.
3. **Still-used gate (cheap, do it):** confirm the routes are still called by the frontend —
   `rg "design/animations" frontend/src/api/client.js`. A dead route cluster gets *deleted*, not extracted.
4. **Run the coupling probe** (extraction log → "Coupling probe") on the region's line range. Record before-B.
   If B > 3, apply the high-B playbook above before proceeding.
5. **Decide the move type** (router vs service vs both). Extract:
   - Router: new `backend/api/routes_<area>.py` mirroring `routes_loop_skip.py` — `router = APIRouter()`,
     move the `BaseModel`s + handlers **verbatim**, import shared helpers back. Add
     `app.include_router(<area>_router, prefix="/api")` in `main.py`. Remove the moved code from crud.py.
   - Service: new/existing `backend/core/<area>.py` pure fn + a direct unit test in `tests/`; the handler
     keeps its decorator and shrinks to delegate.
6. **Gate:** `just test` green (cite pass count; flag any count *drop* — that's a regression, not a win).
   `just lint` clean on touched files. A service extraction without a new unit test does not ship.
7. **One region per commit** (`area: extract <cluster> router/service from crud.py`). Update this map (check
   the box, note the commit), add a metrics row to the log **with the required justification line**.
8. **Route what you found** (don't let it die): a bug found in/near the region → `issues_ledger.md` dossier
   (+ `issues_fix_log.md` row if fixed). A genuinely-stuck region → the log's difficulties ledger with *why*.
9. **Overwrite the `## Next-session handoff` block** below (≤8 lines): the one recommended next region for
   *each* file + its probed before-B, the fixture/route to sanity-check, and any gotcha this batch uncovered.
   It's a living pointer — replace, don't append.

**Don't:** parallelize edits to one god-file (serial is correct for a single file — worktrees collide on the
shared import block). Touch `_PHASE_*`, the mutation contract (`mutate_and_validate`/`set_design_silent`/
`snapshot` — see api-and-state.md), or any route URL. Let `backend/core` import from `backend/api`.

---

## Single-line invocation

A session is started by one line naming the target file. Either:

- **Slash command:** `/carve-router crud`  or  `/carve-router assembly`
  (skill at `.claude/skills/carve-router/SKILL.md` — loads this map, the log, picks the topmost clean region
  in the named file, runs the probe, and proceeds through the protocol).
- **Plain prompt, if you prefer:** *"Run a backend router carve-up loop on crud.py"* (or assembly.py).

The `crud` / `assembly` argument is the **only** required input — it selects which god-file and which backlog
section drives the session.

---

## Next-session handoff

_Living pointer — each session overwrites this (step 9). Last updated 2026-06-08 after Refactor #2
(Strand extensions → routes_extensions.py shipped, B=1, 1752 passed / 1 PRE-EXISTING failure unrelated)._

**▶ NEXT — crud.py:** **Deformation endpoints + debug** (banners `# ── Deformation endpoints` +
`# ── Deformation debug`, find via `grep -n "# ── Deformation" backend/api/crud.py`, ~12688–13136, ~450 ln) →
`routes_deformation.py`. **Bootstrap-probed B=1** (`_design_response`, ×3) — re-run the probe on the live
range (line numbers drifted ~−400 after #1+#2). Bend/twist op CRUD (`POST/PATCH/DELETE /design/deformation`)
+ the `GET /design/deformation/debug`-style summary route. **Confirm the debug route isn't dead first**
(`rg "deformation/debug\|deformation\b" frontend/src/api/client.js`) — it may be View>Debug-only; if dead,
propose deleting rather than moving it. Mirror `routes_extensions.py` verbatim, mount in main.py.
Alt clean B=1 warm-up: **Flexible ssDNA segments** (`# ── Flexible ssDNA segments`, B=1 on
`_design_response_with_geometry`; read `memory/project_ssdna_ball_joints.md` first).

**Gotchas banked (cumulative):** (1) **Adjacency ≠ cohesion** — #2's `# ── Strand extensions` banner secretly
contained 4 plate-layout / representation-override routes between the extension handlers; READ the whole
banner-to-banner span and cut on *concept*, not the banner label. (2) Before deleting a moved block, grep each
request `BaseModel` across the WHOLE god-file (`grep -rn ClassName backend/`) — #1's block held
`BindingDisplayPoseBody` used by 2 non-animation handlers. (3) After moving, ruff F401 will flag now-orphaned
`backend.core.models` imports in crud.py's import block — remove them (#2 dropped `StrandExtension`,
`VALID_MODIFICATIONS`; #1 dropped `DesignAnimation`/`AnimationKeyframe`).

**⚠ PRE-EXISTING TEST FAILURE (not from the carve-up):** `tests/test_seamless_router.py::test_teeth_closing_zig`
fails in the **full** `just test` run (passes in isolation) — confirmed failing on clean HEAD 250f91e with all
working-tree changes stashed, so it's a cross-test global-state leak independent of any extraction. Full-suite
green count is therefore **1752 passed / 1 failed**, not 1753. Don't chase it during a carve-up; logged to
`issues_ledger.md`.

**▶ NEXT — assembly.py:** **Forward-kinematics helpers** (banner `# ── Forward kinematics helpers`,
~446–1106, ~660 ln) is the highest-value *service* extraction — pure FK math marooned in the api file →
`backend/core/assembly_fk.py` with direct unit tests (no router involved). But if you want a clean *router*
warm-up first, **Gear relations** (banner `# ── Gear relations`, ~5244–5414) or **Belt paths**
(~5414–5612) are small self-contained route clusters — probe B before committing.

**Gotcha banked from bootstrap:** crud.py defines **131** module-level private helpers; most candidate
clusters touch only `_design_response` / `_design_response_with_geometry`. The high-B clusters are the ones
entangled with the overhang/cluster helper web (overhang connections, bindings, sub-domains) — defer those
until the easy B=1 clusters are drained and the loop is grooved.

---

## crud.py backlog

Ordered roughly easiest-coupling first. **Probed B** is the bootstrap measurement (verify before claiming).
Tiers are priority hints, not gospel.

### Tier 1 — clean router lifts (B = 1, mirror the exemplars)

- [x] **Animations** — `# ── Animations` → `routes_animations.py` (Refactor #1, 2026-06-08). **B=1**
  (`_design_response`). 7 routes moved (animation + keyframe CRUD + reorder). `BindingDisplayPoseBody` left in
  crud.py (used by 2 non-animation handlers). crud.py 190→183 routes, −222 LOC.
- [x] **Strand extensions** — `# ── Strand extensions` → `routes_extensions.py` (Refactor #2, 2026-06-08).
  **B=1** (`_design_response`). 5 routes moved (single CRUD + batch upsert/delete) + their 5 request models.
  Dead `_EXT_SEQ_RE` regex dropped. **Banner was NOT cohesive** — it interleaved 4 *non-extension* routes
  (`/design/plate-layout` ×2, `/design/representation-overrides` ×2); those stayed in crud.py under a retitled
  banner and are a future candidate. crud.py 183→178 routes.
- [ ] **Deformation endpoints + debug** — `# ── Deformation endpoints` + `# ── Deformation debug`
  (~12690–13139) → `routes_deformation.py`. **Probed B=1** (`_design_response`). Bend/twist op CRUD +
  the debug summary route. (Confirm the debug route isn't dead before moving — it may be `View>Debug`-only.)
- [ ] **Flexible ssDNA segments** — `# ── Flexible ssDNA segments` (~13521–13723) →
  `routes_flexible_segments.py`. **Probed B=1** (`_design_response_with_geometry`). See
  `memory/project_ssdna_ball_joints.md` before touching.

### Tier 2 — router lifts, probe first (likely B = 1–3)

- [ ] **Camera poses** — ALREADY DONE (`routes_camera_poses.py`, 13-B). Listed only so nobody re-lifts it.
- [ ] **Cluster rigid transforms** — `# ── Cluster rigid transforms` (~13383–13521) → `routes_clusters.py`
  (consider pairing with **Cluster joint routes** ~13796–14178 — same resource). Probe B; cluster helpers
  may pull in more than the response helper.
- [ ] **oxDNA + atomistic export** — `# ── oxDNA export / run` (~14440–14596) + `# ── Atomistic model + PDB/PSF`
  (~14596–15092) + `# ── NAMD bundle templates` (~15092) → `routes_export_atomistic.py`. Export cluster;
  heavy `backend/core` delegation already — probe for export-helper back-imports.
- [ ] **caDNAno sequence export** — `# ── caDNAno sequence export` (~11019–11189) → fold into a
  `routes_sequences.py` with the sequence-assignment block (~7288–8029) and overhang random-gen (~8029–8485).

### Tier 3 — service-heavy (do a service push first, then maybe a router)

- [ ] **Cluster autodetect → `backend/core`** — the "Internal helpers" mass (~157–1618), esp. the cluster
  autodetect phases (~848–1168) and the rebuild logic (~1021–1618). **This is the single biggest *real*
  improvement available** — ~1460 lines of pure topology/clustering logic living in the api file. Push it to
  `backend/core/cluster_autodetect.py` (or extend `cluster_reconcile.py`) with direct unit tests. **No router,
  no URL change — pure service extraction.** Big payoff on handler-thinness + testability; expect LOC drop as
  a *result*. Multi-session; carve it by phase.
- [ ] **Feature log + edit-feature dispatch** — `# ── Feature log endpoints` (~11189–11909) + `# ── Edit-feature
  dispatch` (~11683–12690) → router + a `backend/core/feature_log_edit.py` service for the giant
  `edit_feature` dispatcher (the deformation/cluster_op branch logic is business logic). High value, higher
  coupling — probe and split.
- [ ] **Overhang web (defer)** — overhang connections (~9548–10110), relax bond (~10110–10445), bindings
  (~10445–11019), sub-domains (~8485–9548), free-end resize (~8784–8950). These share the overhang/cluster
  helper web → **high B**. Drain the B=1 clusters first; come back when the loop is grooved and tackle the
  shared helpers as a `backend/core/overhang_ops.py` service extraction up front.
- [ ] **Protein** — `# ── Protein import + library` + `# ── Protein attachments` (~3278–3596) →
  `routes_protein.py`. **Probed B=4** (`_design_for_export`, `_design_response`, `_find_ovhg_or_404`,
  `_geometry_for_helices`). Co-move `_find_ovhg_or_404` + `_geometry_for_helices` (or share via core) to get
  B down. See `memory/project_protein_attachment.md`.

### Stays in crud.py (the shared kernel — do NOT extract)
- `_design_response` / `_design_response_with_geometry` / `_helix_label` (used by 100+ routes), the request
  models shared across clusters, and the design endpoints proper (`GET/POST /design`, metadata, geometry).
  These are the composition kernel — the terminal state is crud.py = design-core routes + shared response
  helpers, with every cohesive sub-resource lifted out.

---

## assembly.py backlog

- [ ] **Forward-kinematics helpers → `backend/core/assembly_fk.py`** — `# ── Forward kinematics helpers`
  (~446–1106, ~660 ln). **Service extraction, highest value** — pure FK transform math in the api file.
  Direct unit tests. See `memory/project_path_to_thousands.md` (O(N) backend) before touching.
- [ ] **Joint routes** — `# ── Joint routes` (~4183–5244, ~1060 ln incl. the revolute-drive logic) →
  `routes_assembly_joints.py` + push the endpoint-aware revolute drive (~4477) into
  `backend/core/assembly_polymer.py` or a new service. Biggest single assembly cluster; split.
- [ ] **PartGroup routes** — `# ── PartGroup routes` (~3863–4183) → `routes_assembly_groups.py`. Self-contained
  (PowerPoint-style grouping). See `memory/project_assembly_groups.md`.
- [ ] **Gear relations** — `# ── Gear relations` (~5244–5414) → `routes_assembly_gears.py`. Small, cohesive.
  See `memory/project_gear_relations.md`.
- [ ] **Belt paths + riders + polymerize** — `# ── Belt paths` (~5414–5612) + `# ── Belt riders` (~5542) +
  `# ── Polymerize along a belt` (~5612) → `routes_assembly_belts.py`. See `memory/project_belt_paths.md`.
- [ ] **Polymerize Origami** — `# ── Polymerize Origami` (~5679–6357) → `routes_assembly_polymerize.py` +
  push the replication/pattern-mate math (~5805–6293) into `backend/core/` (much of it may already be in
  `assembly_polymer.py` / `periodic_polymer.py` — dedup, don't duplicate). See `memory/project_polymerize_origami.md`.
- [ ] **Overhang bindings + connections** — `# ── Assembly-level overhang bindings` (~2559) + `# ── …overhang
  connections` (~2695–3863) → `routes_assembly_overhangs.py`. Larger; the cross-part linker logic is partly
  in `assembly_linker.py` / `assembly_linker_relax.py` already — probe what's still inline. See
  `memory/project_assembly_overhang_bindings.md` + `project_assembly_linker_relax.md`.
- [ ] **Configurations + camera poses** — `# ── Assembly configurations` (~6461) + `# ── Assembly camera poses`
  (~6636) → `routes_assembly_configs.py`. See `memory/project_assembly_configurations.md`.
- [ ] **Linker helices/strands/geometry** — `# ── Linker helices` (~6693) + `# ── Linker strands` (~6729) +
  `# ── Linker geometry` (~6785–6913) → `routes_assembly_linkers.py`.
- [ ] **Animation CRUD** — `# ── Animation CRUD` (~7462–7660) → `routes_assembly_animations.py`.
- [ ] **Instance / connector / library / validation / flatten / debug** — the remaining banners
  (`# ── Instance routes` ~1394, `# ── Instance connectors` ~6357, `# ── Workspace library` ~6927,
  `# ── Assembly validation` ~7660, `# ── Flatten to Design` ~7747, `# ── Debug endpoints` ~7783). Pick off
  the cohesive ones; the core-assembly routes (`GET/POST /assembly`, undo/redo) are the kernel that stays.

### Stays in assembly.py (kernel)
- Core assembly routes (`# ── Core assembly routes` ~1289), undo/redo, the geometry cache, and the shared
  `_assembly_response`-style helpers. Same terminal state as crud.py: kernel + lifted sub-resources.

---

**The goal is NOT a LOC number.** It is: **each god-file holds only its design/assembly-core kernel routes +
the shared response helpers, with every cohesive sub-resource in its own `routes_<area>.py` and every chunk
of business logic in `backend/core`.** When the backlog is drained and the only thing left in crud.py is the
kernel, the loop is done — LOC lands wherever it lands as a *result*. Keep it done by extracting new route
clusters into their own router from the start (same law as `FEATURE_DEVELOPMENT.md` for the frontend).
