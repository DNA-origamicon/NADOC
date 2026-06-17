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

### Primary metric — back-import surface `B`, split into **bespoke-B** (the gate) and **raw-B** (a debt signal)
`B` = the count of **distinct private symbols** (`_foo`) the new `routes_<area>.py` imports back from
crud.py/assembly.py. It splits in two, and you must report BOTH:
- **bespoke-B** = back-imports that are *private region helpers* — logic specific to this cluster that
  didn't make it out. **This is the gate.**
- **raw-B** = bespoke-B + the *exempt shared kernel* (`_design_response`/`_assembly_response`, the
  `mutate_and_validate` wrappers, 20+-caller trivial lookups like `_find_instance`, and L4-blocked file-IO
  infra). The exempt set is documented in L19.

- **GATE: bespoke-B = 0 to ship a router extraction.** (Not "raw B ≤ 3" — that was the original heuristic;
  L19 corrected it. The shipped routers sit at bespoke-B=0 with raw-B anywhere from 1 to 11, and that's the
  real bar.) If even ONE back-import is a bespoke region helper, the cluster is NOT cleanly separable — three
  honest options, in order of preference:
  1. **Co-extract the shared helpers into `backend/core/<area>.py`** (they were service logic too) and import
     them from core in *both* files — coupling genuinely drops.
  2. **Move the bespoke helper IN** with the router (if it has no caller outside the moved cluster) — then it
     isn't a back-import at all.
  3. **Pick a different cluster.** A cluster that's all bespoke helpers is telling you it isn't ripe.

- **HIGH raw-B IS NOT A PASS — it is a debt marker (NEW, 2026-06-16, the reviewer's point).** bespoke-B=0
  means "no umbilical of *cluster-specific* logic," NOT "cleanly decoupled." A router that ships at
  bespoke-B=0 / **raw-B ≥ 6** (e.g. `routes_assembly_geometry` at 8, `routes_assembly_joints` at 11) still
  has a broad dependency on the god-file's *kernel surface* — that is an **intermediate state, not a victory
  lap.** When you ship such a row you MUST, in the same session, **append a Tier-3 service-push candidate to
  the backlog** naming the broad kernel cluster the router leaned on (e.g. "the `_geo_cache_*` trio +
  `_load_design_from_source`/`_design_with_instance_overrides` file-IO → `backend/core/assembly_geometry.py`").
  The router lift is fine; it just doesn't *finish* the decoupling, and the loop must not lose the thread.
- Measure B with the probe in the extraction log's "Coupling probe" section before you start. Log
  *before-B → after-B for BOTH bespoke-B and raw-B* in the metrics row.

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
   - **Repo-wide lint debt (2026-06-16): `just lint` reports ~13 pre-existing errors, NONE from the carve-up**
     — they live in NAMD/oxDNA/polymer feature code (`namd_runner.py`, `routes_md.py`, `polymer_router.py`,
     `seamed_router.py`, `namd_solvate.py`) + four test files (mostly F401 unused-import / F841 unused-local,
     ~10 of 13 are `ruff --fix`-able). The carve-up didn't cause them and isn't on the hook to fix them all,
     BUT: (a) **never let the count rise** — after a lift, `ruff` will flag now-orphaned `core.models` imports
     in the god-file (gotcha #3); remove them so your touched files are clean; (b) **opportunistic fix** — if a
     pre-existing F401/F841 is in a file you're already editing or directly adjacent, fix it in the same commit.
     A standalone `ruff check --fix backend/ tests/` lint-sweep commit (separate from any extraction) is welcome
     any session — it's mechanical and drains the gate without touching the carve-up's risk surface.
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

_Living pointer — each session overwrites this (step 9). Last updated 2026-06-16 after Refactor #42
(**crud.py: Molecular Dynamics load FOLD-IN → the existing `routes_md.py`**). The 3 MD-load routes
(`/md/resolve-config` + `/md/load` + `/md/browse`) + their 2 request models moved verbatim into `routes_md.py`
(the NAMD-job-runner router) — **B=0** (the probe printed ZERO crud privates; they depend only on `design_state`,
function-local `backend.core.*` imports, and their own models). **L12 fold-in, not a new module** — `routes_md.py`
already owns the MD subsystem; no `main.py` change. The whole "Molecular Dynamics load" concern is now out of
crud.py. **Finding (→ issues_ledger):** `/md/resolve-config` + `/md/load` are dead REST routes — the live
MD-load path is the `/ws/md-run` WebSocket (`ws.py`); only `/md/browse` is frontend-used (`md_panel.js`). **Both
dead routes + their request models were then DELETED (user-approved, same session) → ISSUE-10 DONE in
`issues_ledger.md`/`issues_fix_log.md`**; `/md/browse` kept. crud.py **125→122 routes**, −161 LOC; `routes_md.py`
nets **+1 route** (browse). **2130→2130 passed** / 55 skipped, 0 failed (deletion of dead code, no test delta). #42 COMMITTED + pushed
2026-06-16; #41 COMMITTED (8e4a0cc, Protein → `routes_protein.py`, bespoke-B=0); #40 (9fa033b); #39 (fa65f73);
#38 (70685aa); #37 (e65028c). assembly.py at **29 routes** (routes drained, kernel-surface reduction pending).
**New exemplar banked:** an L12 fold-into-an-existing-sibling-router (B=0) is a legit, clean alternative to a new
`routes_<area>.py` when the concern already has a home — prefer it over spawning a tiny module._

**▶ LOOP PHASE SHIFT (2026-06-16, post-review):** the cheap **B=1 router lifts are drained** — 173 routes now
live in extracted routers, crud.py is at 139 routes / assembly.py at 29. An external review confirmed the router
layer is much healthier BUT flagged that the **next real architectural jump is SERVICE extraction, not more
router lifts** — several shipped routers sit at bespoke-B=0 / raw-B 6–11, i.e. they still lean on a broad
god-file *kernel surface* (geometry cache, file-IO design-load, cluster autodetect). Those are intermediate
states. **Prefer a Tier-3 service push over a router lift from here on** unless a clean B=1 cluster is sitting
right there. The two highest-value targets: crud's **Cluster autodetect** (~1460 ln) and the assembly
**geometry-cache + file-load kernel** (`_geo_cache_*` + `_load_design_from_source`/`_design_with_instance_overrides`,
the surface `routes_assembly_geometry`/`_joints`/`_frames` all lean on).

**▶ NEXT — crud.py (the cheap router lifts AND the overhang-web service push are now DRAINED; PRIMARY = the
assembly geometry-cache/design-load service push, OR a remaining crud display/export cluster):** #41 lifted
Protein → `routes_protein.py` (bespoke-B=0; the last clean cohesive cluster). What's LEFT in crud.py is mostly the
shared kernel + L4-blocked marooned mass: the overhang web's `_resplice_overhang_in_strand`/`_build_overhang_*`/
binding topology-relocation engine/relax-bond `design_state` mutators, the feature-log MUTATING half (welded to
the `_build_*`+`_replay_minor_op` replay engine — difficulties ledger), the crossover/ligation/forced-ligation
endpoints, and the design-core kernel (`GET/POST /design`, helices, strands, geometry/atomistic/surface display
routes). **No obvious B=0 router cluster remains** — the next real architectural jump is the **assembly
geometry-cache + design-load SERVICE push** (the higher-value Tier-3 target, see the assembly handoff below;
`routes_assembly_geometry`/`_joints`/`_frames` all lean on its 8–11-symbol kernel surface). _If you'd rather stay
in crud: probe the remaining display/export clusters (`/design/atomistic`/`/surface`/`/surface/region` display
routes ~11096 area, the STL/3mf 3D-print exports) for a cohesive B≤3 lift — but expect them to lean on
`_geometry_for_design`/`_design_for_export` geometry-export infra (raw-B>0, bespoke-B likely 0). Probe the LIVE
range first._

**▶ DONE (Refactor #37) — crud.py feature-log read-only seek/scrub/batch ROUTER half → `routes_feature_log.py`**
(see the handoff header above + the `[~] Feature log` backlog row). B=3, bespoke-B=0, verbatim 4-route lift,
crud.py 136→132 routes. The mutating half stayed (difficulties ledger). **#36 (Sequence-assignment router,
`routes_assign_sequences.py`, B=3 bespoke-B=0) was the prior crud extraction.**

**Gotchas banked (cumulative):** (1) **Adjacency ≠ cohesion** — #2's `# ── Strand extensions` banner secretly
contained 4 plate-layout / representation-override routes; #3's `# ── Deformation endpoints` banner held
`_rollback_last_feature` (feature-log revert, NOT a deformation route — left in crud.py). READ the whole
banner-to-banner span and cut on *concept*, not the banner label. (2) Before deleting a moved block, grep each
request `BaseModel` across the WHOLE god-file (`grep -rn ClassName backend/`) — #1's block held
`BindingDisplayPoseBody` used by 2 non-animation handlers. (3) After moving, ruff F401 will flag now-orphaned
`backend.core.models` imports in crud.py's import block — remove them (#3 dropped `BendParams`,
`DeformationOp`, `TwistParams`; #2 dropped `StrandExtension`, `VALID_MODIFICATIONS`). (4) **NEW (L10):
region-internal helpers can be imported CROSS-FILE.** #3's `_parse_params`/`_resolve_cluster_scope` were
imported by `routes_loop_skip.py`'s `/design/deformation/validate` route — a grep scoped to crud.py missed it
and the full suite caught it (`ImportError`). Always `grep -rn` the whole `backend/` for every helper you move
or delete; if 2+ callers, do a **service push to `backend/core` first** (which is exactly what made #3's B=1).

**✅ RESOLVED (2026-06-08, ISSUE-6):** `tests/test_seamless_router.py::test_teeth_closing_zig` was NOT a
cross-test state leak — it was hash-seed-dependent nondeterminism in the shared `_hamiltonian_path`
(`seamed_router.py`) missing a lexicographic tiebreaker. Fixed + the test re-pinned to the closing-zig
topological event instead of a brittle strand count. **Full-suite green is now 1753 passed / 0 failed.**
See ISSUE-6 in `issues_ledger.md`.

**▶ NEXT — assembly.py (PRIMARY = service push, per the phase shift above):** assembly.py is at **29 routes**
("routes drained") but is **NOT done** — `routes_assembly_geometry`/`_joints`/`_frames` lean on a broad 8–11-symbol
kernel surface (the `_geo_cache_*` trio tied to module global `_GEO_CACHE`, + `_load_design_from_source`/
`_design_with_instance_overrides` file-IO design-load). **The remaining real work is a SERVICE push of that
geometry-cache + design-load kernel → `backend/core/assembly_geometry.py`** (raw-B on those three routers drops
once the cache/load infra is in core; carve by phase, direct unit tests, B=0 by construction for the pure parts —
the file-IO half may be L4-blocked and stay, classify per L20). That is what moves assembly.py from "routes
drained" to actually-done. _Secondary router-lift option (only if a clean cluster is sitting there):_ the cohesive
bits of **`# ── Instance routes`**
(`grep -n "# ── Instance routes" backend/api/assembly.py`, ~602) — the per-instance CRUD (add / patch / delete
instance, visibility, source-swap). **CAUTION: kernel-adjacent + HIGH coupling** — these handlers run FK
propagation (`_propagate_fk_inplace` / `_enforce_connector_coincidence`) + the mutation contract
(`_apply_assembly_mutation_with_feature_log`) + cluster-delta propagation; probe B on the LIVE range and expect
several shared back-imports (classify each as bespoke-vs-exempt per L19 before committing). It may NOT split
cleanly — if the probe shows bespoke-B>0, this is a "leave in the kernel" region, not a forced extraction.
**Still L4-blocked, leave behind:** the cluster-inference trio
(`_infer_cluster_ids_for_connector_label`→`_design_with_instance_overrides` file-IO, `_joint_side_cluster_ids`,
`_propagate_cluster_delta_to_mates`). `_apply_prismatic_joint` + `_mat4_from_model`/`_mat4_to_model` stay
(26+ unrelated callers). **Leave the kernel:** `GET/POST /assembly`, undo/redo (`# ── Core assembly routes`),
the feature-log seek/replay + per-entry-actions banners (the `_replay_assembly_op` dispatcher lives here and is
called by everything — it's kernel), and `# ── Debug endpoints` (`/debug/assembly` IS still frontend-used — not
dead). **When the Instance-routes probe says "kernel, don't extract," assembly.py's ROUTER carve-up is drained** — but
the file is still not done (see the geometry-cache/design-load service push above). Either do that service push,
or switch the loop to crud.py's Cluster-autodetect service push (the higher-value Tier-3 target).
GOTCHA re-banked (#23/#24, → L21+circular): when the extracted router imports kernel helpers BACK from
assembly.py, any reference in a STAYING function (esp. `_replay_assembly_op`) to a moved handler/model must
become a **function-local** `from backend.api.routes_<area> import ...` — a top-level import is circular. Both
#23 (polymerize) and #24 (overhang connections) hit this; resolve via the function-local import, don't fight it.
**FLAKE banked (#24, L9):** the new oxDNA Phase-2 subprocess tests (`tests/test_oxdna_relaxation.py`, commit
6cd7ebd) flake on test ORDER — `test_runner_end_to_end` (json.decoder) fails in the full randomized suite but
passes in isolation; `test_oxdna_http_lifecycle` fails under `pytest-randomly` within the file alone. A
controlled deterministic before/after (`-p no:randomly`, oxdna+overhang files) is **68 passed both at clean
HEAD and with the #24 changes** — the failures are environmental, NOT extraction-caused. If you see an oxDNA
failure after a verbatim assembly lift, re-run deterministic + isolated before suspecting your change.

**Gotcha banked (assembly.py, #4):** the assembly-side shared kernel helper is **`_assembly_response`** (the twin
of crud's `_design_response`) — it stays in assembly.py, counts toward B, never blocks. Animation keyframe-patch
uses `assembly_state.set_assembly_silent` (no undo) while the other 6 use `set_assembly` — preserve which one
each handler calls (L6 mutation contract). assembly.py's private helpers are NOT prefixed-probe-clean like crud's:
the gear/belt/group cluster shares a dense helper web, so probe B on the LIVE range before every assembly pick.

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
- [x] **Deformation endpoints + debug** — `# ── Deformation endpoints` + `# ── Deformation debug`
  → `routes_deformation.py` (Refactor #3, 2026-06-08). **B=1** (`_design_response`). 4 routes moved
  (add/update/delete deformation + debug). **Service push first:** the shared `_parse_params` +
  `_resolve_cluster_scope` were lifted to `backend/core/deformation.py` as `parse_deformation_params`
  (ValueError variant) + `resolve_cluster_scope` (+9 unit tests) because they were imported by THREE
  callers (deformation routes, crud's edit-feature branch, AND `routes_loop_skip.py`'s validate route —
  a *cross-file* back-import the in-file grep missed). `_rollback_last_feature` left in crud.py (used only
  by the feature-log revert path, not by any deformation route — adjacency, not cohesion). crud.py 178→174 routes.
- [x] **Flexible ssDNA segments** — `# ── Flexible ssDNA segments` → `routes_flexible_segments.py`
  (Refactor #27, 2026-06-16). **B=1** (`_design_response_with_geometry`). 5 routes moved (flexible-relax +
  mark/unmark/batch + GET connections) + their 4 request models + the 2 region-only helpers
  (`_flex_mark_from_body`, `_flex_log_response`, zero external callers). **Banner was NOT cohesive (L8):** the
  two generic undo-stack routes physically under it (`POST /design/cluster/{id}/begin-drag`,
  `POST /design/snapshot`) are cluster-drag / undo utilities, NOT flexible-specific — left in crud.py under a
  retitled `# ── Cluster drag / undo-stack snapshot utilities` banner. Verbatim lift; `test_flexible_segments.py`
  covers. crud.py 178→173 routes.

### Tier 2 — router lifts, probe first (likely B = 1–3)

- [ ] **Camera poses** — ALREADY DONE (`routes_camera_poses.py`, 13-B). Listed only so nobody re-lifts it.
- [x] **Cluster rigid transforms** — `# ── Cluster rigid transforms` → `routes_clusters.py` (Refactor #28,
  2026-06-16). **B=2** (`_design_response` kernel + `_ensure_default_cluster` — shared cross-region, also
  called by crud's auto-cluster path ~1337, so left back; bespoke-B=1, gate ≤3 passes). 3 routes
  (POST/PATCH/DELETE `/design/cluster`) + 2 region-only request models (`AddClusterBody`/`PatchClusterBody`)
  moved verbatim. `ClusterOpLogEntry` is a `core.models` model (imported directly, not a back-import).
  **Cluster joint routes** (`# ── Cluster joint routes`) NOT folded in — different resource (joints vs
  transforms), separate reason to change. crud.py 173→170 routes. `test_clusters*` + `test_cluster_*` cover.
- [x] **Cluster joint routes** — `# ── Cluster joint routes` → `routes_cluster_joints.py` (Refactor #29,
  2026-06-16). **B=1** (`_design_response`), bespoke-B=0. 3 routes (place/patch/delete joint) + 2 region-only
  request models + the 3 pure builders (`_build_add/update/delete_joint`) moved IN. **L8:** the 2 `loop/skip`
  routes physically under the same banner (`clear-all`, `apply-deformations`) are a separate concern — LEFT in
  crud.py. **L21 circular-import:** the builders are also called by crud's `_replay_minor_op` dispatcher (stays),
  so it imports them **function-locally** (top-level = circular). Sibling of #28 but separate resource → own
  module. crud.py 170→167 routes. `test_joints.py` (9 route + replay) covers.
- [x] **MD/structural file exports** — the handoff's big "oxDNA+atomistic+NAMD" range (banners
  `# ── oxDNA export / run`, `# ── Atomistic model + PDB/PSF export`, `# ── NAMD bundle templates`).
  **NAMD + GROMACS complete-package exports DONE** (Refactor #30, 2026-06-16): the contiguous
  `# ── NAMD bundle templates` banner (9 routes) → `routes_export_md.py` at **B=2, bespoke-B=0**
  (`_design_for_export` + `_geometry_for_design`, both shared cross-file/cross-region export/geometry
  infra). Moved IN: the 2 NAMD templates + the GROMACS background-job store (`_gromacs_jobs`/`_lock`,
  was at crud.py top). Orphaned `import copy` + `import threading` cleaned from crud.py (their only real
  users moved out). **L8 cut:** the full 28-route span is interleaved with NON-cohesive routes — leave them
  for crud.py: the atomistic/surface *display* routes (`/design/atomistic`, `/design/surface`,
  `/design/surface/region` — feed the renderer, not file downloads), the 3D-print exports
  (`/design/export/stl`, `/3mf` — own concern + topic file), and `/design/debug/strand-stats` (crossover
  diagnostic, unrelated). **DONE (Refactor #31, 2026-06-16):** the cohesive single-file structural-export
  cluster left behind — `# ── oxDNA export / run` (2 routes) + the individual exporters under
  `# ── Atomistic model + PDB/PSF export` (`/design/export/pdb|psf|identity|identity-tsv|design-maps|
  basepairs|basepairs-tsv|stacking|stacking-tsv|restraints-dry-implicit` + `/design/debug/mrdna-roundtrip`)
  → `routes_export_structure.py` at **B=2, bespoke-B=0** (`_design_for_export` + `_geometry_for_design`, the
  same shared export/geometry pair as #30; mrdna's gromacs/mrdna deps were function-local core imports, NOT crud
  privates — probe was empty for that segment). 3-segment cut held (oxDNA / pdb→mrdna contiguous / psf), with the
  display + 3D-print + strand-stats routes correctly LEFT in crud.py. Zero region-local helpers/models. crud.py
  158→145 routes, −441 LOC. Verbatim lift; 2071 passed / 55 skipped unchanged.
- [x] **caDNAno sequence export** — `# ── caDNAno sequence export` → `routes_sequences.py` (Refactor #32,
  2026-06-16). **B=1** (`_design_for_export`), bespoke-B=0. 2 routes moved (`/design/export/sequence-csv` +
  `/design/export/sequence-xlsx`) + the region-only `_SequenceXlsxRequest` model. **Did NOT force the fold**
  (per L8/L19 + the handoff): sequence-assignment (B=2, bespoke `_place_auto_crossovers`) and overhang
  random-gen (B=7, 5 bespoke) stay in crud.py — the clean caDNAno-export half lifted alone. Verbatim;
  `test_reference_geometry.py` hits the csv route. Orphaned `pydantic.Field` import cleaned from crud.py.
  crud.py 145→143 routes, −170 LOC.

- [x] **Auto-scaffold routing variants** — the 4 routing endpoints mislabeled under the
  `# ── Sequence assignment endpoints` banner (`auto-scaffold-seamed`/`-matched`/`-seamless` +
  `route-for-polymerization`) → `routes_scaffold_routing.py` (Refactor #33, 2026-06-16). **B=1**
  (`_design_response_with_geometry`), bespoke-B=0. 4 routes + their shared `_run_auto_scaffold_with_feature_log`
  helper (moved IN, zero external callers) — no request models. **L8 banner-trap caught + the handoff's
  fold-into-routes_sequences plan REJECTED:** these place crossovers/seams (topology routing), NOT sequences;
  the actual sequence-assignment + full-autostaple routes stay in crud.py (full-autostaple's
  `_place_auto_crossovers`/`_linearize_staple_precursors` are shared cross-region + test-imported → defer to a
  later sequence/overhang service push). **L23 banked:** `headless_build.py` imported 2 of these handlers as fns
  → repointed at the new module. crud.py 143→139 routes.

- [x] **Sequence assignment** — `# ── Sequence assignment endpoints` → `routes_assign_sequences.py`
  (Refactor #36, 2026-06-16). **B=3, bespoke-B=0** — `_design_response`(2) + `_design_response_with_geometry`(1)
  (shared kernel, exempt) + `_place_auto_crossovers`(1) (L13 leave-and-import-back: lives in crud's crossover
  region ~4257, called by a crossover route there + `tests/test_simple_router.py`, so NOT
  sequence-assignment-bespoke — cross-region shared infra, same call as #28's `_ensure_default_cluster`). 3 routes
  (`assign-scaffold-sequence`, `assign-staple-sequences`, `full-autostaple`) + the 2 region-only models
  (`_ScaffoldSeqBody`/`_FullAutostapleBody`) + the 2 region-only helpers
  (`_linearize_staple_precursors`/`_assert_no_circular_staples`) moved IN. **TWO L23 repoints (same commit):**
  (1) `tests/test_simple_router.py` import split — `_linearize_staple_precursors` now from the new module,
  `_place_auto_crossovers` still from crud; (2) `headless_build.py`'s 4 imports (`_ScaffoldSeqBody`/
  `_FullAutostapleBody`/`assign_scaffold_sequence_endpoint`/`full_autostaple_endpoint`) repointed at the new
  module. Verbatim lift; 2088 passed / 55 skipped unchanged. crud.py 139→136 routes, −257 LOC.

- [x] **Molecular Dynamics load** — `# ── Molecular Dynamics load` (`/md/resolve-config` + `/md/load` +
  `/md/browse`) **folded into the existing `routes_md.py`** (Refactor #42, 2026-06-16). **B=0** — the probe
  printed ZERO crud privates; the 3 handlers depend only on `design_state` (already imported in `routes_md.py`),
  function-local `backend.core.*` imports, and their own 2 request models (moved with them). **L12 fold-in**
  (not a new module): `routes_md.py` already owns the MD subsystem (`/md/jobs/*`, `/md/namd-available`); the
  load/resolve/browse routes share that reason to change + the `/md` prefix. No `main.py` change (already
  mounted). **Finding:** `/md/resolve-config` + `/md/load` have no frontend/test caller (the live load path is
  the `/ws/md-run` WebSocket in `ws.py`); only `/md/browse` is live (`md_panel.js`). Moved verbatim, not deleted
  (deletion needs user sign-off) → see `issues_ledger.md`. crud.py 125→**122 routes**, −161 LOC. The whole MD
  concern is now out of crud.py.

### Tier 3 — service-heavy (do a service push first, then maybe a router)

- [x] **Cluster autodetect → `backend/core/cluster_autodetect.py`** — DONE (Refactor #34, 2026-06-16).
  **Service push, B=0** (the new core module imports nothing from `backend.api` — only `backend.core.models` +
  `crossover_positions` + `constants`). Moved the 5 pure cluster-detection functions **byte-identical**
  (`_cluster_bundle_regions`, `_cluster_by_lattice_neighbors`, `_cluster_by_scaffold_routing`,
  `_geometry_clusters_multi_scaffold`, `_autodetect_clusters`, ~640 ln) out of crud.py's `# ── Internal
  helpers` block. crud.py imports back only the 2 entry points its routes call (`_autodetect_clusters` ×2,
  `_cluster_bundle_regions` ×1); the 3 inner phase helpers are module-private in core (L17). `_ensure_default_cluster`
  STAYS (calls `design_state.set_design_silent`, shared cross-region). +4 direct unit tests
  (`tests/test_cluster_autodetect_core.py`). 2071→2075 passed (the +4), 55 skipped unchanged. crud.py routes
  unchanged (139 — no router moved). The residual "Internal helpers" mass is now response/geometry/export
  helpers (`_design_response*`, `_geometry_for_*`, `_strand_nucleotide_info`) — a *different* concern (kernel +
  export-geometry), not autodetect; the topology-clustering logic is fully out.
- [~] **Feature log + edit-feature dispatch** — `# ── Feature log endpoints` + `# ── Edit-feature dispatch`
  → router + a `backend/core/feature_log_edit.py` service for the giant `edit_feature` dispatcher.
  **SERVICE PUSH (edit branches) DONE — Refactor #35, 2026-06-16, B=0.** The two pure model-transform branches
  (`edit_cluster_op_entry` = last-op-wins cluster pose rewrite; `edit_deformation_entry` = op-snapshot rewrite +
  deformation-set rebuild-from-log) moved to `backend/core/feature_log_edit.py` with a `FeatureEditError(status=…)`
  HTTP-free error carrier; the api shims (`_edit_cluster_op_feature`/`_edit_deformation_feature`) shrank ~60→~14 ln
  each (delegate → translate error → re-bake/commit/respond). The deformed-continuation re-bake
  (`_rebuild_deformed_continuations`, needs `design_state` snapshot decode + live builders) STAYS in the api shim
  (L4-blocked). +13 direct unit tests (`tests/test_feature_log_edit_core.py`). crud.py −94 LOC, routes unchanged (139).
  **STILL OPEN:** (1) `_edit_dispatch_run` (the extrusion replay dispatcher) is **L4-blocked** — it calls crud-private
  builders (`_build_bundle`/`_build_extrude_*`/`_build_overhang_extrude`), so it stays in the api layer.
  **ROUTER half — READ-ONLY seek/scrub/batch SUB-HALF DONE (Refactor #37, 2026-06-16):** the 4 read-only
  feature-log geometry-preview routes (`/design/features/seek` + `/geometry-batch` + `/atomistic-batch` +
  `/surface-batch`) → NEW `routes_feature_log.py` at **B=3, bespoke-B=0** (`_seek_feature_log` L13 leave-and-import-back
  [shared cross-file w/ assembly.py + L4-blocked on the builder/replay engine], `_design_replace_response` kernel
  response-family, `_compact_geometry_for_design` geometry-kernel; + `_TimingTrace` shared timing-utility *class*,
  exempt). All 3 region-only request models moved IN. Verbatim lift; 2088 passed / 55 skipped unchanged.
  crud.py 136→**132 routes**, −148 LOC. **The MUTATING half STAYS (genuinely-stuck — see difficulties ledger):** the
  delete/edit/revert/rollback routes are welded to the bespoke L4-blocked builder+replay engine (`_edit_dispatch_run`→
  `_build_*`, `_replay_minor_op`, `_topology_substitute`, `_rebuild_deformed_continuations`, `_delete_routing_child`,
  `_revert_before_routing_child`, `_rollback_last_feature`) — these helpers are feature-log-bespoke AND can't go to core
  (call crud builders + design_state), so neither leaving-back (bespoke-B>0) nor moving-out (drags the `_build_*`
  builders → bespoke builder back-imports) hits the gate. This is replay-engine kernel that stays with the builders.
- [~] **Overhang web** — overhang connections, relax bond, bindings, sub-domains, free-end resize. These
  share the overhang/cluster helper web → **high B**. **`backend/core/overhang_ops.py` ESTABLISHED (Refactor
  #38, 2026-06-16):** the pure polarity/linker-compatibility cluster (`_overhang_end`/`_used_overhang_ends`/
  `_check_linker_compatibility` + 3 sibling-private) service-pushed at B=0, +15 unit tests; the connection-create
  handler keeps the `HTTPException` translation (L15). **SLICE 2 DONE (Refactor #39, 2026-06-16):** the
  sub-domain tiling/sequence/annotation cluster — 4 pure fns moved verbatim
  (`_ovhg_domain_lengths`/`_ovhg_backing_length`/`_resolve_sub_domain_sequence`/`_compute_sub_domain_annotations`)
  + the tiling validator L15-split (`_validate_sub_domain_tiling` → core `validate_sub_domain_tiling` raising
  `SubDomainTilingError`; thin api shim translates) → `overhang_ops.py` at B=0, +19 unit tests. Dead
  `_next_sub_domain_name` deleted (zero callers). **SLICE 3 DONE (Refactor #40, 2026-06-16):** the two pure
  model transforms `_apply_boundary_hairpin_warnings` (sub-domain hairpin-warning recompute, 4 route call sites)
  + `_replace_ovhg` (pure `model_copy` overhang swap — the handoff's predicted blocker, turned out fully pure, so
  it moved WITH the scan; leaving it in api would have forced core to import `backend.api`/L4) moved verbatim →
  `overhang_ops.py` at B=0, +7 unit tests. **REMAINING:** the easy pure overhang fns are now drained — the
  marooned mass (`_resplice_overhang_in_strand`, `_build_overhang_*`, the binding topology-relocation engine,
  relax-bond's `design_state` mutators) is L4-blocked — leave as thin api shims. The overhang-web service push is
  effectively complete; switch the loop to a different region (see handoff).
- [x] **Protein** — `# ── Protein import + library` + `# ── Protein attachments` →
  `routes_protein.py` (Refactor #41, 2026-06-16). **B=3, bespoke-B=0** (L19): the probe's `_design_for_export`
  belonged to the adjacent `/design/export/cadnano` route (NOT protein — L8, left in crud); the live protein-only
  range probes `_design_response`(3, kernel) + `_geometry_for_helices`(1, geometry kernel, 10 cross-region
  callers) + `_find_ovhg_or_404`(1, trivial overhang lookup, 11 overhang-region callers) — all exempt
  leave-and-import-back. 7 routes (import/library/delete/atomistic + attach POST/PATCH/DELETE) + 4 request models
  + region-only `_resolve_protein_asset` moved IN. **Service push (high-B-playbook option 1):** `_protein_asset_meta`
  was shared with the staying `_import_protein_free` (generic PDB-import path) → would've been a bespoke
  back-import (bespoke-B=1, fails gate); it's pure (asset→dict), so pushed to `backend/core/protein.py` as
  `protein_asset_meta` + imported from core in BOTH files + 1 unit test (`test_protein_asset_meta_shape`).
  crud.py 132→125 routes, −274 LOC. See `memory/project_protein_attachment.md`.

### Stays in crud.py (the shared kernel — do NOT extract)
- `_design_response` / `_design_response_with_geometry` / `_helix_label` (used by 100+ routes), the request
  models shared across clusters, and the design endpoints proper (`GET/POST /design`, metadata, geometry).
  These are the composition kernel — the terminal state is crud.py = design-core routes + shared response
  helpers, with every cohesive sub-resource lifted out.

---

## assembly.py backlog

- [x] **Forward-kinematics helpers → `backend/core/assembly_fk.py`** — `# ── Forward kinematics helpers`
  (Refactor #7, 2026-06-08). **Service extraction, B=0** (the new core module imports nothing from
  `backend.api` — only numpy + `Mat4x4`). Moved the **pure FK graph-propagation kernel** (5 helpers:
  `_fk_apply_to_joint`, `_build_inst_by_id`, `_fk_expand_rigid_group`, `_fk_propagate`,
  `_move_instance_with_fk_delta`) **verbatim** → `backend/core/assembly_fk.py` + 12 direct unit tests
  (`test_assembly_fk_core.py`). assembly.py imports them back under their original names (~50 call sites
  unchanged). **The other ~565 ln of the banner stayed (L4-blocked):** the connector-resolution
  (`_get_connector_world*`, `_build_*connector_frames`, `_resolve_*_label_local`) + cluster-mate
  inference (`_infer_cluster_ids_for_connector_label`, `_joint_side_cluster_ids`,
  `_propagate_cluster_delta_to_mates`) helpers depend on api-layer `_design_with_instance_overrides`
  (→ `_load_design_from_source`, file IO + `HTTPException`) and `_mat4_from_model` — can't go to core
  without inverting the arrow. assembly.py 7243→7160 LOC; routes unchanged (92, no routes moved).
- [x] **Connector-frame resolution kernel → `backend/core/assembly_connectors.py`** — the read-only geometry
  half of #7's "~565 ln left behind" (Refactor #12, 2026-06-08). **Service push, B=0.** Moved the 10 pure
  label→SE3-frame helpers (`_build_frame_from_normal`, `_resolve_{blunt,seam,live}_label_local`,
  `_get_connector_world{,_frame}`, `_local_frame_for_label`, `_build{,_world}_connector_frames`,
  `_refresh_connector_frames_for_instance`) verbatim; the ONLY edit was `_mat4_from_model(x)`→`x.to_array()`
  (byte-identical — `Mat4x4.to_array` already existed, so the api free fn dropped out of core entirely).
  17 unit tests (`test_assembly_connectors_core.py`). **5 of the 10 became module-private in core** (only the
  5 public resolvers import back — L17). assembly.py −386 LOC, 79 routes unchanged, 1818 passed. **STILL behind
  (L4-blocked / file-IO, correctly left):** `_infer_cluster_ids_for_connector_label`
  (→`_design_with_instance_overrides` file-IO), `_joint_side_cluster_ids`, `_propagate_cluster_delta_to_mates`,
  `_cluster_se3`.
- [x] **Connector-coincidence enforcement → `backend/core/assembly_connectors.py`** (Refactor #13, 2026-06-08).
  **Service push, B=0.** Moved `_enforce_connector_coincidence` (the write-side twin of #12's resolvers — re-docks
  a constrained child whose mated connector drifted, then propagates the snap down its rigid subtree) verbatim
  except `_mat4_from_model(x)`→`x.to_array()` (byte-identical, same as #12). Pure graph-mutation: back-imports
  NOTHING from assembly.py (calls the module-local `_get_connector_world` + the `assembly_fk` FK helpers). 7 new
  unit tests (24 total in the file); its 7 call sites import it back. assembly.py −50 LOC, 79 routes unchanged,
  1825 passed. The cluster-inference trio + `_cluster_se3` stay (L4-blocked, file-IO).
- [x] **Revolute-drive + gear/belt coupling kinematics kernel** → `backend/core/assembly_kinematics.py`
  (Refactor #15, 2026-06-08). **Service push, B=0** (imports only numpy/scipy + `Mat4x4`/`GearRelation` +
  the already-extracted `assembly_fk`/`assembly_connectors`). 10 fns moved verbatim (two byte-identical
  `Mat4x4` converter swaps the only adaptation); 6 imported back, 4 module-private (L17); 27 unit tests
  (`test_assembly_kinematics_core.py`). Dead `_gear_endpoint_seed` removed. assembly.py −418 ln, routes
  unchanged (77). **This unblocks the Gear/Belt/PartGroup/Joint routers** (L18) — the drive math is now in core.
- [x] **Joint routes** — `# ── Joint routes` split by cohesion into two routers (handoff "split if cohesion
  divides"). **Frame-inspection half DONE** (Refactor #19): the 3 read-only routes →
  `routes_assembly_frames.py` at **B=6, bespoke-B=0** (`_cluster_se3` moved IN). **Joint-CRUD mutator half DONE**
  (Refactor #20, 2026-06-08) → `routes_assembly_joints.py`: 5 routes (add_joint / create_mate / patch_joint /
  refresh_mate / delete_joint) + region-local `_compose_add_joint` + 4 request models
  (AddJointRequest/MateConnectorSpec/CreateMateRequest/PatchJointRequest, all region-only) moved IN.
  **B=11, bespoke-B=0** (L19) — every back-import is exempt: kernel `_assembly_response` +
  `_apply_assembly_mutation_with_feature_log`; lookups `_find_joint`/`_find_instance`; converters
  `_mat4_from_model`/`_mat4_to_model`/`_apply_prismatic_joint` (26+ callers); file-IO infra
  `_assembly_source_path`/`_design_with_instance_overrides`/`_propagate_fk_inplace`; L4-blocked cross-region
  `_infer_cluster_ids_for_connector_label`. Drive math imported from `backend/core` directly (#7/#12/#15), NOT
  back from the god-file. Verbatim lift; `test_joints.py` covers. 58→53 routes, −564 LOC. **L21 banked:** removing
  the now-locally-unused `_get_connector_world` re-export from assembly.py broke a TEST that imported it from
  there — `grep -rn` the whole `tests/` too, not just `backend/`, before deleting an F401-flagged re-export.
- [x] **PartGroup routes** — `# ── PartGroup routes` → `routes_assembly_groups.py` (Refactor #18, 2026-06-08).
  **B=3** — all shared kernel/infra, **bespoke-B=0** (L19): `_assembly_response` + `_apply_assembly_mutation_with_feature_log`
  (kernel) + `resolve_assembly` (the kernel joint-solver ROUTE, called inside `transform_group` to re-snap
  externally-mated partners — shared infra, stays in assembly.py). 6 routes (create/ungroup/patch/duplicate/
  cascade-delete/transform) + 4 request models + the 2 group-only helpers (`_find_group`, `_autogen_group_name`)
  moved IN. The grouping math was already in `backend/core/assembly_groups.py` (#groups feature) and the gear-sync
  in `backend/core/assembly_kinematics.py` (#15) — the router imports both from core directly, NOT back from the
  god-file. Orphaned `PartGroup` `core.models` import cleaned. assembly.py 67→61 routes, −321 LOC. Self-contained
  (PowerPoint-style grouping). See `memory/project_assembly_groups.md`.
- [x] **Gear relations** — `# ── Gear relations` → `routes_assembly_gears.py` (Refactor #16, 2026-06-08).
  **B=3** (`_assembly_response` + `_apply_assembly_mutation_with_feature_log` + `_resolve_gear_endpoint`). 4 routes
  (create/patch/delete/resolve) + 2 request models + region-local `_find_gear_relation` moved in. The drive math
  (`_build_inst_by_id`/`_gear_endpoint_side`/`_apply_revolute_value_to_gear_endpoint`) is imported from
  `backend/core` directly (#15), not back from the god-file. **`_resolve_gear_endpoint` STAYED in assembly.py**
  (L13: shared cross-region with Belt's `_resolve_belt_pulley`, raises `HTTPException` so L4-blocked from core) —
  imported back, the only bespoke back-import. Orphaned `GearRelation`/`_gear_endpoint_side` imports cleaned.
  assembly.py 77→73 routes.
- [x] **Belt paths + riders + polymerize** — `# ── Belt paths` + `# ── Belt riders` +
  `# ── Polymerize along a belt` → `routes_assembly_belts.py` (Refactor #17, 2026-06-08). **B=4** — all four
  shared kernel/infra, ZERO bespoke: `_assembly_response` + `_apply_assembly_mutation_with_feature_log`
  (kernel) + `_find_instance` (54-caller lookup) + `_resolve_gear_endpoint` (L13 shared gear+belt, L4-blocked).
  6 routes + 6 request models + region-local `_find_belt_path`/`_resolve_belt_pulley` moved IN. Belt→gear-edge
  math (`_belt_to_relation`) already in core (#15). High-B-playbook option-2: every back-import is the
  accepted shared kernel, so B=4 is not bespoke entanglement. assembly.py 73→67 routes. `tests/test_belt_paths.py`
  covers (verbatim lift).
- [x] **Polymerize Origami** — `# ── Polymerize Origami` → `routes_assembly_polymerize.py` + service push. ALL
  THREE PHASES DONE. #21 (2026-06-08): `polymerize_assembly`'s ~365-ln record-assembly orchestration →
  `build_polymer_chain` (**B=0**, +12 tests); handler ~440→~80 ln. #22 (2026-06-15):
  `polymerize_periodic_assembly`'s ~110-ln build span → `build_periodic_chain` (**B=0**, +8 tests); handler
  ~175→~50 ln. **#23 (2026-06-15) ROUTER half:** the 3 thinned routes (`/assembly/polymerize`,
  `GET .../periodic-closure`, `/assembly/polymerize-periodic`) + their 2 request models →
  `routes_assembly_polymerize.py` at **B=6, bespoke-B=0** (all shared infra: `_assembly_response` /
  `_apply_assembly_mutation_with_feature_log` / `_find_instance` / `_find_joint` / `_assembly_source_path` /
  `_design_with_instance_overrides`; the probe's `_display_design(1)` was a comment-only false positive). The
  `_replay_assembly_op` GOTCHA was resolved via option (b): the two op-kind branches now do a **function-local**
  `from backend.api.routes_assembly_polymerize import ...` (top-level would be circular — the router imports the
  kernel helpers back from assembly.py). Verbatim lift, behavior preserved; 2076/2076 green (no new tests). 53→50
  routes. See `memory/project_polymerize_origami.md`.
- [x] **Overhang bindings + connections** — `# ── Assembly-level overhang bindings` + `# ── …overhang
  connections` → `routes_assembly_overhangs.py` (Refactor #24, 2026-06-15). **B=7, bespoke-B=0** (L19): all
  seven back-imports are the exempt shared set — kernel `_assembly_response` +
  `_apply_assembly_mutation_with_feature_log`, the `_find_instance` lookup, the file-IO design-load infra
  `_assembly_source_path`/`_load_design_from_source` (L4-blocked, 20+ shared callers), the L13 forced-shared
  `_linker_geometry_for_assembly` (api-bound via `crud._geometry_for_design`, cross-region + relax tests), and
  `_propagate_fk_inplace` (shared FK mover). 8 routes (3 binding + 3 connection CRUD + relax-status + relax) +
  5 request models + the 6 region-only helpers (`_validate_overhang_ref`/`_validate_overhang_in_instance`/
  `_check_polarity_allowed`/`_overhang_polarity`/`_variant_id_for`/`_find_assembly_connection`) moved IN. The
  linker/kinematics math is imported from `backend/core` DIRECTLY (`_build_inst_by_id` from `assembly_fk`;
  `generate_assembly_linker_topology`/`remove_assembly_linker_topology`/`recompose_strand_sequences_for_connection`
  from `assembly_linker`; `assembly_relax_status`/`relax_assembly_linker`/`relax_assembly_indirect_linker` from
  `assembly_linker_relax`), NOT back from the god-file. **`_replay_assembly_op` GOTCHA resolved via #23 option
  (b):** its two op-kind branches (`assembly-overhang-connection-add`/`-patch`) now `from
  backend.api.routes_assembly_overhangs import ...` **function-locally** (top-level = circular). The
  `SeekAssemblyFeaturesRequest` model — physically nested under the bindings banner but used by the staying
  feature-log seek route — was relocated to a new `# ── Assembly feature-log seek / replay` banner (L8 adjacency
  ≠ cohesion). assembly.py 50→42 routes. See `memory/project_assembly_overhang_bindings.md` +
  `project_assembly_linker_relax.md`.
- [x] **Configurations + camera poses** — `# ── Assembly configurations` + `# ── Assembly camera poses`
  → `routes_assembly_configs.py` (Refactor #5, 2026-06-08). **B=1** (`_assembly_response`). 8 routes moved
  (4 config CRUD + 4 camera-pose CRUD/reorder) + their 5 request models + region-internal
  `_capture_assembly_configuration`. Both probed B=1 independently; folded per the handoff. silent-vs-undo
  contract preserved (restore + patch use `set_assembly_silent`). 5 orphaned `core.models` imports cleaned.
  assembly.py 105→97 routes, −268 LOC. See `memory/project_assembly_configurations.md`.
- [x] **Linker helices/strands/geometry** — `# ── Linker helices`/`# ── Linker strands`/`# ── Linker geometry`
  → `routes_assembly_linkers.py` (Refactor #6, 2026-06-08). **B=2** (`_assembly_response` +
  `_linker_geometry_for_assembly`). 5 routes moved (helix/strand CRUD + GET linker-geometry) + their 2 request
  models. The compute helper `_linker_geometry_for_assembly` + `assembly_connector_arc_lengths` **stayed in
  assembly.py** — the former depends on api-layer `crud._geometry_for_design` (can't go to `backend/core`
  without inverting the api→core arrow) AND is called from the overhang-connections region (lines ~3022/3057)
  + the relax test suite; moving it would create 3+ reverse imports, so importing the one helper back is
  strictly less coupling. Orphaned `Helix`/`Strand` `core.models` imports cleaned. assembly.py 97→92 routes.
- [x] **Animation CRUD** — `# ── Animation CRUD` → `routes_assembly_animations.py` (Refactor #4, 2026-06-08).
  **B=1** (`_assembly_response`). 7 routes moved (animation + keyframe CRUD + reorder) + their 5 request models
  + region-internal `_find_animation`. Orphaned `DesignAnimation` / `AnimationKeyframe` `core.models` imports
  cleaned from assembly.py. First assembly.py extraction; mirrors the crud.py exemplars exactly. assembly.py
  −200 LOC.
- [x] **Assembly validation** — `# ── Assembly validation` → `backend/core/assembly_validate.py`
  (Refactor #8, 2026-06-08). **Service push, B=0** (the new core module imports nothing from `backend.api` —
  only `Assembly` + delegates to `assembly_flatten`). Moved the pure `_validate_assembly` body **byte-identical**
  → `validate_assembly_report` + 8 direct unit tests (`test_assembly_validate_core.py`). The `GET
  /assembly/validate` handler shrank ~84→4 ln (parse→delegate→respond). Routes unchanged (92). assembly.py −76 LOC.
- [x] **Validation + Flatten to Design** — `# ── Assembly validation` + `# ── Flatten to Design`
  → `routes_assembly_validation.py` (Refactor #9, 2026-06-08). **B=1** (`crud._design_response`, function-local
  on `load-as-design` only; from assembly.py's own helpers B=0). 3 cohesive read-only "inspect/derive the
  assembly" routes moved verbatim (`GET /assembly/validate`, `GET /assembly/flatten`,
  `POST /assembly/flatten/load-as-design`). Debug endpoints correctly left behind (probe B=4:
  `_find_joint`/`_find_instance`/`_mat4_from_model`/`_apply_revolute_joint`). assembly.py 92→89 routes, −46 LOC.
- [~] **Instance / connector / library / debug** — the remaining banners
  (`# ── Instance routes` ~1286, `# ── Workspace library` ~6463, `# ── Debug endpoints` ~7044).
  Pick off the cohesive ones; the core-assembly routes
  (`GET/POST /assembly`, undo/redo) are the kernel that stays. **Instance connectors router DONE**
  (Refactor #14, 2026-06-08): `# ── Instance connectors (InterfacePoints)` (2 routes, add/delete) →
  `routes_assembly_connectors.py` at **B=3** (all shared infra: `_assembly_response` +
  `_apply_assembly_mutation_with_feature_log` + `_find_instance`); 79→77 routes, −68 LOC, 1825 green.
  **Workspace library service push DONE**
  (Refactor #10, 2026-06-08): the 3 bespoke helpers (`_dedup_filename`/`_patch_references`/`_safe_workspace_path`)
  are now `backend/core/workspace.py` (B=0, 19 unit tests). **Router half DONE (Refactor #11, 2026-06-08):**
  `# ── Workspace library` (10 routes) → `routes_assembly_workspace.py` at **B=2** — the router calls the core
  fns directly (`dedup_filename`/`patch_nass_files`/`patch_assembly_instances`), back-imports only
  `_safe_workspace_path` (shared api wrapper, L13) + `_assembly_response` (kernel), and moved the workspace-only
  `_patch_references` in. `# ── Part library (legacy)` (~6357 now) is a SEPARATE concern (scans `parts-library/`,
  uses `_sha256_file`/`_LIBRARY_DIR`) — left behind. assembly.py 89→79 routes. See L16 (monkeypatch-fidelity).
  **Instance loadouts router DONE** (Refactor #25, 2026-06-15): the 4 per-instance loadout routes
  (create/select/rename/delete) + their 2 region-only request models → `routes_assembly_loadouts.py` at
  **B=5, bespoke-B=0** (all shared infra: `_assembly_response` + `_find_instance` +
  `_load_design_from_source`/`_assembly_source_path` file-IO + `_replace_instance_design` cross-region writer);
  the loadout snapshot codec stays function-locally imported from `crud` (shared with `/design/loadouts`).
  42→38 routes, ≈−104 LOC, 2076 green. **No route tests exist for these 4 — verbatim-lift guarantee only.**
  **Instance design / geometry router DONE** (Refactor #26, 2026-06-15): the 6 read-only GET geometry routes
  (`/assembly/instances/{id}/design` + `/geometry` + `/bend-centers` + `/atomistic-geometry` +
  `/surface-geometry` + the batch `/assembly/geometry`) → `routes_assembly_geometry.py` at **B=8, bespoke-B=0**
  (L19): every back-import is the exempt shared set — `_find_instance` lookup + the file-IO design-load infra
  `_assembly_source_path`/`_load_design_from_source`/`_design_with_instance_overrides` (L4-blocked) +
  `_display_design` (shared cross-region with polymerize router) + the geometry-cache trio
  `_geo_cache_key`/`_geo_cache_get`/`_geo_cache_set` (tied to assembly.py's module-level `_GEO_CACHE`, also
  read by other assembly routes + the frames router). The geometry math (`_geometry_for_design` from `crud`,
  `deformed_helix_axes`/`compute_bend_centers` from `backend.core.deformation`, `build_atomistic_model`/
  `compute_surface`) stays **function-locally imported** inside each handler exactly as before — NOT back from
  the god-file. No module-level helpers/models in the region (only a nested `_source_key_for`), all 6 GETs →
  read-only, no mutation contract, no `_replay_assembly_op` gotcha. Verbatim lift; 38→32 routes, −221 LOC,
  2076 passed / 55 skipped unchanged.
  **Part library (legacy) DELETED (2026-06-15, post-#26, user-approved):** the 3 dead routes
  (`/assembly/library` + `/library/register` + `/library/rescan`) + their `_sha256_file` / `_LIBRARY_DIR`
  helpers + `RegisterLibraryRequest` model removed (confirmed zero `frontend/src` refs). **GOTCHA (→ L22):**
  the routes were frontend-dead but had **5 backend route tests** in `tests/test_assembly_api.py`
  (`test_library_*` / `test_register_library_*`) — the still-used gate (step 4) only greps `frontend/src`, so a
  full deterministic suite went 5-RED until those tests were deleted alongside. `PartLibraryEntry` model STAYS
  in `core/models.py` (independently tested by `test_assembly_models.py`). assembly.py 32→29 routes, −~70 LOC,
  deterministic full suite **2071 passed / 55 skipped / 0 failed** (the prior "5 failed" was exactly these
  deleted tests; the banked oxDNA flake did NOT reappear — 540755b's atomic-write fix holds).

### Tier 3 — assembly service pushes (the remaining REAL decoupling, post-review 2026-06-16)
- [ ] **Geometry-cache + design-load kernel → `backend/core/assembly_geometry.py`** — the surface that
  `routes_assembly_geometry` (raw-B=8), `routes_assembly_joints` (raw-B=11), and `routes_assembly_frames` all
  lean back on: the `_geo_cache_key`/`_geo_cache_get`/`_geo_cache_set` trio (tied to module global `_GEO_CACHE`)
  + the file-IO design-load infra `_load_design_from_source`/`_design_with_instance_overrides`/
  `_assembly_source_path`. Push the cache logic + the pure parts of design-load to core with direct unit tests;
  the genuinely file-IO/`HTTPException` parts may be L4-blocked and stay (classify per L20). This is what drops
  those routers' raw-B and moves assembly.py from "routes drained" to actually-done. (Module-global `_GEO_CACHE`
  must be read through its module post-move — L16.)

### Stays in assembly.py (kernel)
- Core assembly routes (`# ── Core assembly routes` ~1289), undo/redo, and the shared
  `_assembly_response`-style helpers. Same terminal state as crud.py: kernel + lifted sub-resources. (The
  geometry cache is currently here too but is a Tier-3 service-push target — see above, not permanent kernel.)

---

**The goal is NOT a LOC number.** It is: **each god-file holds only its design/assembly-core kernel routes +
the shared response helpers, with every cohesive sub-resource in its own `routes_<area>.py` and every chunk
of business logic in `backend/core`.** LOC lands wherever it lands as a *result*. Keep it done by extracting
new route clusters into their own router from the start (same law as `FEATURE_DEVELOPMENT.md` for the frontend).

**"Routes drained" ≠ "done" (2026-06-16, post-review).** Having lifted all the route clusters out is only HALF
the terminal state. The loop is done **only when the residual kernel surface is also small** — i.e. the routers'
**max raw-B against the god-file is low** AND the marooned business logic (cluster autodetect, geometry/cache/
file-load helpers) has moved to tested `backend/core` modules. assembly.py at 29 routes is "routes drained," but
its routers still lean on an 8–11-symbol kernel surface (geometry cache + file-IO design-load), so it is **NOT
done** — the geometry/file-load service push is the remaining work. State the file's status as *"routes drained,
kernel-surface reduction pending"* until that surface is itself extracted, not *"near terminal / done."*
