---
name: api-and-state
description: The backend mutation contract (which state.mutate_* to call), the per-document session model, the router map, the frontend api client, and frontend/src/state/store.js.
paths:
  - "backend/api/**/*.py"
  - "frontend/src/api/**/*.js"
  - "frontend/src/state/**/*.js"
---

# api-and-state

**Scope.** How a mutation travels: browser → `api/client.js` → an `/api/...` route → a
`state.mutate_*` helper → a `_design_response` → `store.setState`. Owns the **mutation contract**
(which helper a route must call), the **per-document session model**, the **router map**, and the
frontend **`store.js`**. Does *not* own what any individual route computes — that's the
domain rule (`scaffold-and-loops`, `deformation`, `selection`, …).

This rule's globs auto-load it on **82 files / ~51k LOC**, so it is deliberately about the
*contract*, not an inventory. There is **no route index here** — it rotted to 13% coverage with
10 dead entries and was deleted (see "Finding a route" below for what replaced it).

## The model, in one paragraph

The backend holds **one Design per document**, not one global design. Every request names its
document with an `X-NADOC-Doc` header (or `?doc=`), resolved by `doc_context.get_current_doc()`
([doc_context.py:72](../../backend/api/doc_context.py#L72)) into a `_DesignSession`
([state.py:74](../../backend/api/state.py#L74)) pulled from `_sessions: dict[str, _DesignSession]`
([state.py:87](../../backend/api/state.py#L87)). Each session carries its own design, its own
`history`/`redo` deques (`MAX_UNDO_STEPS = 50`, [state.py:58](../../backend/api/state.py#L58)),
and its own monotonic `revision`. Sessions are flushed to `.session/<doc>` by a background thread
and **restored on boot** ([session_cache.py:83, :184](../../backend/api/session_cache.py#L83)).

## Files

| File | LOC | What it is |
|---|---|---|
| [backend/api/state.py](../../backend/api/state.py) | 758 | Per-doc sessions, undo/redo, **all 35 mutation helpers** |
| [backend/api/assembly_state.py](../../backend/api/assembly_state.py) | 726 | The **parallel** state module for the assembly layer — own `get_or_404`/`undo`/`redo`/`snapshot`/`set_assembly_silent`, plus diff snapshots (`encode_diff_snapshot`:417, `apply_diff_forward`:541, `apply_diff_inverse`:668) that `state.py` has no counterpart for |
| [backend/api/doc_context.py](../../backend/api/doc_context.py) | 139 | The per-request doc contextvar the whole model rests on |
| [backend/api/session_cache.py](../../backend/api/session_cache.py) | 328 | Background flush to `.session/<doc>` + `restore()` on boot |
| [backend/api/crud.py](../../backend/api/crud.py) | 11266 | Still the largest router (114 routes) **and** the response chokepoint — `_design_response`:268 / `_design_response_with_geometry`:339 are imported by **34 other modules** |
| [backend/api/main.py](../../backend/api/main.py) | 302 | `include_router` × 62, [:212-273](../../backend/api/main.py#L212) |
| [backend/api/ws.py](../../backend/api/ws.py) | 1585 | WebSockets — the **only** router mounted with no `/api` prefix ([main.py:273](../../backend/api/main.py#L273)) |
| [backend/core/validator.py](../../backend/core/validator.py) | — | `ValidationReport`:25, `validate_design(design)`:70 |
| [frontend/src/api/client.js](../../frontend/src/api/client.js) | 3880 | `_request`:251, `_syncFromDesignResponse`:360, **275 exported API functions** |
| `frontend/src/api/` siblings | — | `overhang_endpoints.js` 347, `animation_endpoints.js` 107, `recent_files.js` 82, `chain_sim_endpoints.js` 31 |
| [frontend/src/state/store.js](../../frontend/src/state/store.js) | 541 | The whole-app store. 53 keys, 7 slices, 31 importers, **zero tests** |

## The mutation contract (the load-bearing part)

`state.py` exposes **35 public functions**. Picking the wrong one is a silent correctness bug, not
an error. The decision:

| Situation | Call | Why |
|---|---|---|
| Topology mutation that may move cluster membership — crossover/nick/ligation, autostaple/autobreak, end-extend, slice-plane extrude, overhang/linker creation, helix CRUD | **`mutate_with_reconcile(fn)`** [:264](../../backend/api/state.py#L264) | Runs `reconcile_cluster_membership` + `_retry_pending_ligations` after `fn`. **Skipping this leaves clusters silently wrong.** |
| Routes that *explicitly* edit `cluster_transforms` — cluster CRUD, feature-log replay, `relax_overhang_connection`, importers | **`mutate_and_validate(fn)`** [:244](../../backend/api/state.py#L244) | Reconciling would fight the route's own edit. The docstring at :277-283 states this exclusion — obey it. |
| Whole-design replacement that still needs reconcile | `replace_with_reconcile` [:300](../../backend/api/state.py#L300) | |
| Mutation that must appear in the feature log | `mutate_with_feature_log` [:421](../../backend/api/state.py#L421) / `mutate_with_minor_log` [:508](../../backend/api/state.py#L508) | Snapshot payloads, evicted against `MAX_SNAPSHOT_BUDGET_BYTES` (5 MB, [:64](../../backend/api/state.py#L64)) |
| Intermediate step inside a `snapshot()` bracket | `set_design_silent_reconciled(new, before, report)` [:740](../../backend/api/state.py#L740) — **preferred**; plain `set_design_silent` [:728](../../backend/api/state.py#L728) only when no topology moved | Callers named in its docstring: `place_crossover`, `forced_ligation`, `add_nick_batch` |

Multi-step op = one Ctrl-Z:

```python
state.snapshot()                                       # ONE undo checkpoint for the whole op
state.set_design_silent_reconciled(d1, before, rep)    # intermediate — no undo push
design, report = state.mutate_with_reconcile(step_n)   # final step validates
```

All of these bump `revision` (`_bump_revision`, [:89](../../backend/api/state.py#L89)) — that
number is what the frontend's stale-response watermark reads. Do not mutate `s.design` outside
these helpers; nothing else takes `_lock` or bumps the revision.

## Finding a route (there is no index here)

`backend/api/` is **76 files / 46,306 LOC / 567 live routes** across **63 `routes_*.py` modules**.
Any enumeration in a doc rots within weeks. Instead:

```bash
rg -n '@router\.(get|post|put|patch|delete)\("/design/nick' backend/api/     # by path
rg -n 'def full_autostaple' backend/api/                                     # by handler name
rg -n 'include_router' backend/api/main.py                                   # what's mounted
```

**Every HTTP router mounts with `prefix="/api"`** ([main.py:212-273](../../backend/api/main.py#L212));
no router declares its own prefix. So a decorator reading `"/design/nick"` is really
`/api/design/nick`. `ws_router` is the sole exception (bare, [:273](../../backend/api/main.py#L273)).

Router families, so you know which file to grep first:

| Family | Files | Rough route count |
|---|---|---|
| Core design topology | `crud.py` (11266) | 114 — strands, domains, helices, crossovers, nicks, import/export, protein-pdb-auto |
| Assembly layer | `assembly.py` + `routes_assembly_*.py` (~20 files) | ~150 |
| MD / NAMD | `routes_md.py` (3781), `routes_md_metrics.py`, `routes_jobs.py`, `routes_runpod.py` | ~70 |
| oxDNA | `routes_oxdna.py` (2667), `routes_oxdna_live.py`, `routes_oxdna_metrics.py`, `routes_lammps.py` | ~65 |
| Shape prediction | `routes_snupi.py`, `routes_cando.py`, `routes_mrdna.py`, `routes_blade.py`, `routes_*_autorefine.py` | ~60 |
| Scaffold / loops | `routes_scaffold_routing.py`, `routes_loop_skip.py` | see `scaffold-and-loops` rule |
| Everything else | `routes_deformation`, `routes_extensions`, `routes_clusters`, `routes_cluster_joints`, `routes_camera_poses`, `routes_animations`, `routes_feature_log`, `routes_display_geometry`, `routes_display_metadata`, `routes_duplex`, `routes_protein`, `routes_sequences`, `routes_assign_sequences`, `routes_export_*`, `routes_flexible_segments`, `routes_primitives`, `routes_fs`, `routes_engines`, `routes_system` | — |

Headless/CLI entry points live beside the routers but are **not** routes: `headless_build.py`
(1609), `headless_oxdna_build.py`, `headless_corner_build.py`, `headless_assembly_build.py`,
`headless_spec_build.py`, `headless_hinge_build.py`.

## Response shape

`_design_response` ([crud.py:268](../../backend/api/crud.py#L268)) returns:

```json
{
  "design": { },                    // full Design
  "validation": { },                // ValidationReport
  "unligated_crossover_ids": [ ],   // drives the unligated-crossover highlight
  "revision": 42                    // monotonic per-doc; the staleness watermark
}
```

`_design_response_with_geometry` ([crud.py:339](../../backend/api/crud.py#L339)) adds geometry so
the client needs **one** round-trip instead of two. Depending on the route it may carry
`nucleotides`, `nucleotides_compact`, `helix_axes`, `partial_geometry` + `changed_helix_ids`, and
`straight_positions_by_helix` + `straight_helix_axes`.

## Frontend: `api/client.js`

`_request(method, path, body, { signal, suppressBusy, docId, timeoutMs })`
([:251](../../frontend/src/api/client.js#L251)) — **not** the 3-arg function older docs describe.
Beyond the fetch it owns: a hard `AbortController` timeout, the busy-popup delay + `pokeProbe()`
wedge detector (:282-290), connection tracking (`notifyRequestSuccess/Failure`, :296/:299), a
Server-Timing perf trace (:321-329), and the **always-stamped `X-NADOC-Doc` header** (:268) that
routes the call to this tab's document.

On error: `store.setState({ lastError: { status, message } })` and **return `null`**
([:330-335](../../frontend/src/api/client.js#L330)) — callers must null-check. On success,
`lastError` is cleared.

`_syncFromDesignResponse(json, { skipGeometry, transient })`
([:360](../../frontend/src/api/client.js#L360)) is the single write path into the store:

1. **Staleness gate first** — `_isStaleDesignResponse(json)` (:362) drops any response whose
   `json.revision` is below `_lastAppliedRevision` (:51-57). Out-of-order responses are discarded,
   not applied. `resetRevisionWatermark()` (:62) exists for backend restarts; if it is not called
   the client will silently ignore every response from a restarted server.
2. Geometry: `nucleotides` present → one `setState` (:536). Absent → a second round-trip via
   `getGeometry()` (:547). `nucleotides_compact` is re-materialized at :427-460; the
   `partial_geometry`/`changed_helix_ids` merge is at :468-483.
3. Writes **10** store keys: `currentDesign`, `validationReport`, `loopStrandIds`,
   `unligatedCrossoverIds`, `strandColors`, `currentGeometry`, `currentHelixAxes`,
   `lastPartialChangedHelixIds`, `straightGeometry`, `straightHelixAxes`.
4. Then `_signalDesignChanged()`, `persistDesign()`, `_clearStaleSelections()` (:554-557).

`persistDesign()` writes a per-doc localStorage snapshot (`nadoc:design:<id>`, :30/:70) on **every**
design response. Combined with `session_cache`, **the design does survive a reload and a server
restart** — do not tell a user their work is only in memory.

## Frontend: `state/store.js`

One file, 541 LOC, **no test**, imported by 31 modules. Exports: the `store` singleton
([:477](../../frontend/src/state/store.js#L477)) with `getState`/`setState`/`subscribe`/
`subscribeSlice`, plus 5 action helpers — `setDomainDesignerSelection`:489,
`setDomainDesignerModalActive`:506, `toggleDomainDesignerHelix`:514, `pushGroupUndo`:523,
`popGroupUndo`:532. `createStore` is **not** exported.

`_initialState` has **53 top-level keys** (:16-371), three of them nested objects (`toolFilters`
:136, `selectableTypes` :148, `domainDesigner` :308).

**7 slices** ([:383-417](../../frontend/src/state/store.js#L383)) — `subscribeSlice(name, fn)`
throws on any other name:

| Slice | Keys |
|---|---|
| `physics` | `cgRelaxPositions`, `cgRelaxStats` |
| `viz` | unfold ×3, `cadnanoActive`, `deformVisuActive`, `straightGeometry`/`straightHelixAxes`, `showHelixLabels`, `atomisticMode`, surface ×3, `coloringMode`, `staplesHidden`, `isolatedStrandId`, `showSequences`, `showPeriodicSeamArcs` |
| `selection` | `selectedObject`, 4 multi-select id pools, `selectableTypes`, `crossoverPlacement`, `deformToolActive`, `activeClusterId`, `translateRotateActive`, `debugOverlayActive`, `domainDesigner` |
| `design` | `currentDesign`, `currentGeometry`, `currentHelixAxes`, `currentPlane`, `loopStrandIds`, `isCadnanoImport`, `validationReport`, `lastPartialChangedHelixIds` |
| `style` | `strandColors`, `strandGroups`, `strandGroupsHistory` |
| `ui` | `toolFilters`, `lastError` |
| `assembly` | `currentAssembly`, `assemblyActive`, `activeInstanceId`, `multiSelectedInstanceIds`, `activeGroupId`, `groupDiveStack`, `assemblyOverhangSelection` |

`setState` notifies **every** global `subscribe` listener unconditionally, then a slice's listeners
only if `changedKeys` intersects that slice ([:438-446](../../frontend/src/state/store.js#L438)).
So `subscribe` is not a cheap hook — prefer `subscribeSlice`.

Note `domainDesigner` is deliberately in **both** `viz` and `selection`.

## Invariants

1. **One design per document, not per server.** Anything that reasons about "the active design"
   must go through `_session()`. There is no global design object.
2. **Never mutate `s.design` outside a `state.mutate_*`/`set_design_silent*` helper** — only those
   take `_lock` and bump `revision`, and an unbumped revision makes the client ignore the response.
3. **`mutate_with_reconcile` for cluster-affecting topology; `mutate_and_validate` for routes that
   own `cluster_transforms`.** Getting this backwards is silent.
4. **A client call can return `null`.** Every mutation helper in `client.js` returns `null` on a
   non-OK response after setting `lastError`.
5. **Responses older than the watermark are dropped, not applied.** If a design change "doesn't
   land" but the network tab shows a 200, check `revision` before checking anything else.
6. `subscribe` fires on every `setState`; use `subscribeSlice` for anything doing real work.

## Traps — code comments that contradict the code

- [store.js:460](../../frontend/src/state/store.js#L460) — the `subscribeSlice` JSDoc lists
  *"'physics' | 'viz' | 'selection' | 'design' | 'style' | 'ui'"* and **omits `assembly`**, which
  has existed at :414 and is accepted by the runtime check at :468. Don't "fix" the code to match
  the comment.

## Test coverage (honest)

- `backend/api/state.py` and `assembly_state.py`: exercised indirectly by the route tests in
  `tests/`; there is no dedicated `test_state.py`.
- `frontend/src/api/`: 5 vitest files (`assembly_v2_expand`, `client_viz_opts`, `client_recovery`,
  `md_client_doc_header`, `roll_design_sync`) against a 3880-LOC client — narrow slices only.
- **`frontend/src/state/store.js`: zero tests.** `test-helpers/mock_store.test.js` tests
  `createMockStore`, a *different* module — the filename implies coverage it does not provide.

## Removed API — do not resurrect

| Dead name | Reality |
|---|---|
| `_active_design` | Never existed in the current model; zero hits repo-wide. Use `_session().design`. |
| `_history` (module-level deque) | Now `_DesignSession.history` ([state.py:77](../../backend/api/state.py#L77)), per document. |
| `design_state` as *a global design* | It's only the conventional import alias `from backend.api import state as design_state`. Not an object. |
| `MAP_API_FLOW.md` | **Never existed anywhere in this repo.** Was linked from this rule's "Related" for its whole life. |
| `POST /design/auto-scaffold` | → `/design/auto-scaffold-{seamed,matched,seamless}` ([routes_scaffold_routing.py:86/112/140](../../backend/api/routes_scaffold_routing.py#L86)) |
| `POST /design/scaffold-nick`, `-extrude-near`, `-extrude-far` | Gone, no replacement, no caller. |
| `POST /design/prebreak` | Gone, no replacement, no caller. |
| `PATCH /design/extensions/{id}` | `routes_extensions.py` has POST/PUT/DELETE + both `/batch` forms — **no PATCH**. |
| `POST|PATCH|PUT|DELETE /design/configurations…` | Whole group dead. Configurations are **assembly**-scoped: [routes_assembly_configs.py:130/147/216/244](../../backend/api/routes_assembly_configs.py#L130). See `animation.md`. |

## Diagnostics → [.claude/runbooks/RUNBOOK_API.md](../runbooks/RUNBOOK_API.md)
