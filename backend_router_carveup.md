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

_Living pointer — each session overwrites this (step 9). Last updated 2026-06-15 after Refactor #24
(**Overhang bindings + connections** → `routes_assembly_overhangs.py` — the largest remaining cohesive assembly
cluster). **B=7, bespoke-B=0** (L19): all seven back-imports are the exempt shared set (`_assembly_response` /
`_apply_assembly_mutation_with_feature_log` kernel + `_find_instance` lookup + file-IO
`_assembly_source_path`/`_load_design_from_source` + L13 forced-shared `_linker_geometry_for_assembly` +
`_propagate_fk_inplace`). 8 routes (3 binding + 3 connection CRUD + relax-status + relax) + 5 request models +
6 region-only helpers moved IN; the linker/kinematics math imported from `backend/core` directly. The
**`_replay_assembly_op` circular-import GOTCHA** (same as #23) resolved via function-local imports in the two
overhang-connection op-kind branches. `SeekAssemblyFeaturesRequest` (nested under the bindings banner, used by
the staying feature-log seek route) relocated to a new feature-log banner (L8). assembly.py 50→42 routes,
~−547 ln (extraction's own). Verbatim lift — no new tests; existing `test_assembly_overhang_bindings.py` (27) +
`test_assembly_linker_relax.py` (16) cover (43 green). **Working tree carries uncommitted #22 + #23 + #24**
(awaiting user commit). **oxDNA flake** (see ▶ NEXT, L9): not extraction-caused — deterministic before/after is
68 passed both ways._

**▶ NEXT — crud.py:** **Flexible ssDNA segments** (banner `# ── Flexible ssDNA segments`, find via
`grep -n "# ── Flexible ssDNA" backend/api/crud.py`, ~13200s after #3's −315 ln drift) →
`routes_flexible_segments.py`. **Probed B=1** (`_design_response_with_geometry`). **Read
`memory/project_ssdna_ball_joints.md` first.** Re-run the probe on the live range AND — per the new L10
gotcha — `grep -rn "_helpername" backend/api/` (the WHOLE api dir, not just crud.py) for every helper the
region defines, to catch cross-file back-imports like the one #3 hit. Mirror `routes_deformation.py`,
mount in main.py. Alt: **Cluster rigid transforms** (`# ── Cluster rigid transforms`) — probe first,
cluster helpers may pull more than the response helper.

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

**▶ NEXT — assembly.py:** **Instance routes** (`# ── Instance routes`, `grep -n "# ── Instance routes"
backend/api/assembly.py`) — the largest remaining banner (~610–1290). It is NOT monolithic: it holds
`add_instance`/`patch_instance`/`delete_instance`/`duplicate_instance` (CRUD) + the loadout sub-routes
(`# ── Per-entry actions` region carries the 4 `/assembly/instances/{id}/loadouts*` routes, now adjacent at
~2918 after this extraction) + a BFS re-application block. **Cut on cohesion, not the banner (L8):** the
clean sub-cluster is **Instance loadouts** (`create/select/rename/delete` loadout — 4 routes, region-local,
probe expected B≈3 = `_assembly_response`/`_apply_assembly_mutation_with_feature_log`/`_find_instance`) →
`routes_assembly_loadouts.py`. Probe the LIVE range first. **Leave the kernel:** `GET/POST /assembly`,
undo/redo, geometry cache (`# ── Core assembly routes`). **Still L4-blocked, leave:** the cluster-inference
trio (`_infer_cluster_ids_for_connector_label`→`_design_with_instance_overrides` file-IO,
`_joint_side_cluster_ids`, `_propagate_cluster_delta_to_mates`). NOTE: `_apply_prismatic_joint` +
`_mat4_from_model`/`_mat4_to_model` stay in assembly.py (26+ unrelated callers).
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

### Stays in assembly.py (kernel)
- Core assembly routes (`# ── Core assembly routes` ~1289), undo/redo, the geometry cache, and the shared
  `_assembly_response`-style helpers. Same terminal state as crud.py: kernel + lifted sub-resources.

---

**The goal is NOT a LOC number.** It is: **each god-file holds only its design/assembly-core kernel routes +
the shared response helpers, with every cohesive sub-resource in its own `routes_<area>.py` and every chunk
of business logic in `backend/core`.** When the backlog is drained and the only thing left in crud.py is the
kernel, the loop is done — LOC lands wherever it lands as a *result*. Keep it done by extracting new route
clusters into their own router from the start (same law as `FEATURE_DEVELOPMENT.md` for the frontend).
