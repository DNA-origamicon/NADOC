# Phase 1 — SHIPPED 2026-05-23 (single-document, resilient) — supporting detail

[Topic head](../../project_session_recovery.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Phase 1 — SHIPPED 2026-05-23 (single-document, resilient)

**Backend**
- `backend/api/server_info.py` (new): `SERVER_INSTANCE_ID` (fresh per process) +
  `STARTED_AT`. The restart-detection beacon.
- `backend/api/session_cache.py` (new): debounced background autosave thread →
  `<workspace>/.session/{active_design.nadoc, active_assembly.nass, session.json}`.
  Restores them on startup so a restart silently brings the doc back. Started in
  `main.py` lifespan (so it never runs during the test suite — tests don't enter
  lifespan). Atomic temp-file writes. Snapshots a deep copy under the lock
  (`copy_for_persist`) then serializes OFF the lock.
- `state.py` / `assembly_state.py`: added `_revision` counter (bumped under lock on
  every `_active_design`/`_active_assembly` reassignment) + `revision()` +
  `copy_for_persist()`. The flush thread skips writing when revision is unchanged.
- `routes.py` `GET /health` returns `server_instance_id`, `started_at`,
  `design_loaded`, `assembly_loaded`. **LOCK-FREE (2026-05-24):** uses
  `state.has_design_unlocked()` / `assembly_state.has_assembly_unlocked()` (read
  `_sessions` without `_lock`, never create a session) instead of `get_design`/
  `get_assembly` — a liveness probe must never block behind a long mutation that
  holds `_lock`, or the frontend probe times out and flashes a false "disconnected".
  Dropped the now-unused `design_id`/`design_name`/`assembly_id` (frontend only ever
  read `design_loaded` + `server_instance_id`).
- `library_events.py`: watchdog ignores any path under `.session` so autosave
  writes don't fire SSE file-changed events.

**Frontend**
- `frontend/src/shared/connection_monitor.js` (new): polls `/api/health` (5 s; 1.5 s
  while reconnecting; 4 s AbortController timeout on the probe). Emits
  `connected`/`disconnected`/`reconnected`/`restarted`. `notifyRequestFailure()` /
  `notifyRequestSuccess()` are called from the two `_request` wrappers
  (`api/client.js`, `cadnano-editor/api.js`) so a failed request flips status fast.
- **UX rework (2026-05-24): real traffic is the liveness signal; poll only when idle
  and visible.** Three changes to stop "constant health pings" interfering with UX:
  (1) `notifyRequestSuccess` now DEFERS the next idle heartbeat a full interval while
  connected — during active editing the dedicated `/health` poll never fires (every
  real request already proves liveness); it only resumes once the user goes idle.
  (2) Visibility-gated: `_scheduleNext` pauses (no timer) while `document.hidden`;
  `visibilitychange→visible` re-probes immediately (catches a restart that happened
  while backgrounded). (3) Down-transition debounced: `FAILURES_BEFORE_DOWN=2` — a
  single failed/stalled probe no longer flashes red; needs two consecutive failures
  (a 1.5 s retry happens between). Combined with the lock-free `/health`, false
  "reconnecting…" flicker during heavy ops is essentially gone. TRADEOFF (acceptable
  for chosen scope): a SEAMLESS backend restart during continuous editing isn't
  detected until the user pauses ~5 s (work is session-cache-safe regardless; a restart
  that drops the connection still flips fast via `notifyRequestFailure`). The
  "instance-id on every response header" option would close that gap but was not chosen.
- Badge wiring: both `main.js` and `cadnano-editor/main.js` call
  `connectionMonitor.start({onChange})` and drive the existing `_setSyncStatus`
  (red "reconnecting…"; on `restarted` → re-pull doc; green when synced).
- Restart recovery: on `restarted`, if `health.design_loaded` → passive re-pull
  (`getDesign`+`getGeometry`, or `getAssembly`+rebuild). If backend came back EMPTY,
  3D view offers `window.confirm` → `importDesign(getPersistedDesign())`; cadnano
  editor offers to push its in-memory design back via `POST /design/import`.
- Interim multi-tab guard (REMOVE in Phase 2): `main.js` broadcasts `doc-presence`
  (designId/name) on design-identity change + `doc-presence-request` at startup;
  warns once via toast when another plain-design tab reports a DIFFERENT design id
  (assembly tabs skipped — they use the separate `/api/assembly` slot).

**Verified**: `just test` 1441 passed (2 pre-existing routing failures in
`test_seamed_router`/`test_seamless_router`, unrelated — fail on HEAD too). Live
uvicorn restart test: load design → autosave writes `.session/` → kill → restart →
`/health` shows NEW instance id + `design_loaded:true` + same id; `GET /design`
returns full topology. Vite production build of both entry points clean.
**UI visuals (badge color, confirm prompt, clobber toast) NOT visually exercised in
a browser by the implementer** — wiring verified via build + live backend only.

## Phase 2 — SHIPPED 2026-05-23 (multi-document backend)

**Backend** (1441 tests still green — default-doc keeps single-doc behavior identical):
- `doc_context.py` (new): `DEFAULT_DOC_ID="__default__"`, `current_doc` ContextVar,
  `DocContextMiddleware` (PURE-ASGI — not BaseHTTPMiddleware, which wouldn't
  propagate the contextvar to endpoints). Reads `X-NADOC-Doc` header / `?doc=` query.
- `state.py` / `assembly_state.py`: globals replaced by `dict[doc_id -> _DesignSession/
  _AssemblySession]` (design/assembly + history + redo + pdb/display_state + revision).
  `_session()` resolves the current doc under the lock. Call sites in crud.py/assembly.py
  UNCHANGED (the lever). New helpers: `list_doc_ids`, `peek_*`, `drop_doc`,
  `restore_doc_*`, `revision_map`, `copy_doc_for_persist`, `undo_depth`/`redo_depth`.
  `_protein_library` stays a module global (shared across docs). `close_session` clears
  the current doc + the shared lib (legacy); `drop_doc` (DELETE /documents) leaves lib.
- `documents.py` (new): `POST /documents` mints a uuid doc_id (session created lazily),
  `GET /documents` lists docs with design/assembly names, `DELETE /documents/{id}` drops.
- `session_cache.py`: now per-doc — `.session/<doc_id>/{active_design.nadoc,active_assembly.nass}`
  + top-level `registry.json`; restore() loads every subdir into its doc.
- `main.py`: `add_middleware(DocContextMiddleware)` + documents router.
- Tests that poked globals updated: `state.undo_depth()` (added) instead of
  `len(_history)`; `close_session()` instead of `_active_design = None`
  (test_ws_helpers, test_assembly_api, test_assembly_models).

**Frontend**:
- `shared/doc_id.js` (new): per-tab doc id from `?doc=`; `docHeaders()` (X-NADOC-Doc),
  `docKey()` (doc-scoped localStorage), `mintDocId()`.
- Both `_request` wrappers (client.js, cadnano api.js) + scattered raw `fetch('/api/…')`
  calls send `docHeaders()`. **INCOMPLETE — three rendering fetches were MISSED; fixed
  2026-05-27, see follow-up below.** localStorage design/assembly keys doc-scoped (default doc
  keeps bare legacy key). BroadcastChannel stamps `docId`; `isSameDoc()` gates
  design-changed/selection-changed so cross-doc tabs don't refetch each other.
- New tab carries its doc: cadnano-editor open passes the parent's doc id. **Edit-Part
  is the EXCEPTION (changed 2026-05-24, see follow-up below): it passes `&assembly-doc=`
  (NOT `&doc=`) so the part editor gets its OWN isolated doc.**
- **New/Open new-tab behavior** (the originally-deferred feature now enabled): New Part /
  New Assembly / Open File spawn a new tab `?doc=<minted>&new=part|assembly` or
  `&open=<path>&open-type=…` UNLESS the current space is empty (`_spaceHasContent()` =
  no helices/strands/instances and no feature-log). Boot dispatch at end of main()
  runs the action for the new tab's doc, then strips the action params (keeps ?doc=).

**Verified**: just test 1441 pass (2 pre-existing router fails unrelated); TestClient +
live uvicorn (:8013, isolated ws) two-doc isolation (tabA/tabB don't clobber, default
doc untouched, GET/DELETE /documents work); per-doc cache flush+restore; Vite build clean.
**UI new-tab flow NOT exercised in a browser by the implementer** (verified via build +
live HTTP only).

### Follow-up fix 2026-05-23 — cross-contamination between open files
Two bugs after initial P2: (1) cadnano editors synced across unrelated tabs; (2) two
open .nadoc files cross-contaminated on Ctrl+S. Root causes + fixes:
- **Two independently-opened main-app tabs both fell on the backend DEFAULT doc** (only
  `?doc=`-spawned tabs were isolated). Saving wrote the backend's last-loaded design to
  the saving tab's path. Fix: `shared/doc_id.js` now auto-assigns a STICKY per-tab doc id
  for any main-app tab with no `?doc=` — `sessionStorage['nadoc:tab-doc']` (survives
  reload, unique per tab) pinned into the URL via replaceState. Standalone cadnano editor
  (no `?doc=`) still uses the default doc. So no two tabs ever share a document.
- **`nadoc:workspace-path` / `nadoc:assembly-workspace-path` / `nadoc:design-filename`
  were NOT doc-scoped** (shared across tabs) → cadnano editor read another tab's
  filename/save-path. Fix: wrapped in `docKey()` in both `main.js` and
  `cadnano-editor/main.js`. design-changed/selection-changed already doc-scoped via
  `nadocBroadcast.isSameDoc`, so each editor now syncs only with its own doc's tab.
- Verified live: `/design/save` writes the doc named by `X-NADOC-Doc` (docA→fileA,
  docB→fileB, re-saving A leaves B untouched). Browser flow still implementer-unverified.
