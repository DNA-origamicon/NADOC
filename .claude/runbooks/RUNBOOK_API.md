# api-and-state — diagnostics runbook

Loaded on demand from the `api-and-state` rule's Diagnostics pointer. Symptom → diagnosis; not
auto-loaded. The rule holds the architecture (per-doc sessions, the mutation contract, the router
map); this file holds only "it's behaving wrong, where do I look".

## Symptom index

| Symptom | Go to |
|---|---|
| Python test correct, API returns something else | §1 |
| API returns 200 but nothing changes on screen | §2 |
| Change lands, then reverts a moment later | §2 |
| Undo skips steps / reverts too much | §3 |
| Undo does nothing (404) | §4 |
| Clusters silently wrong after a topology edit | §5 |
| Design "lost" after reload or server restart | §6 |
| 409 Conflict on DELETE | §7 |
| Frontend function returned `undefined`/crashed on `.id` | §8 |

---

## §1 — Python test correct, but the API returns a different result

**First question is no longer "is the server stale" — it is "which document did the request hit".**
The backend holds one Design *per document* (`_sessions` keyed by the `X-NADOC-Doc` header). A
request from a different tab, from the cadnano editor, or a bare `curl` with no header (→
`__default__`) reads a **different design**. Restarting the server will never explain that.

1. Check the doc id on both sides. Frontend stamps it in `_request`
   ([client.js:268](../../frontend/src/api/client.js#L268)); backend resolves it in
   `doc_context.get_current_doc()` ([doc_context.py:72](../../backend/api/doc_context.py#L72)).
   A bare `curl http://localhost:8000/api/design` is `__default__` — usually *not* the tab you're
   looking at. Add `-H 'X-NADOC-Doc: <id>'` or `?doc=<id>`.
2. Only if the doc matches: **stale server state.** `just dev` runs uvicorn `--reload`
   ([justfile:18](../../justfile#L18)) and `_sessions` lives across requests, so earlier
   curl/test ops leave residue. **STOP — do not add logging, do not dig into backend Python.**
   Ask the user to restart the server.
3. **A restart may not clear it.** `session_cache` flushes each doc to `.session/<doc>` and calls
   `restore()` on boot ([session_cache.py:184](../../backend/api/session_cache.py#L184)), so the
   bad state can come straight back. If a restart doesn't help, ask the user before touching
   `.session/` — that directory is their in-flight work.
4. Still wrong with the right doc and a clean session → it's a real bug. Now investigate.

## §2 — 200 OK, but the UI doesn't change (or changes then reverts)

Check in this order:

1. **The staleness watermark.** `_syncFromDesignResponse` drops any response whose `revision` is
   below `_lastAppliedRevision` ([client.js:362, :51-57](../../frontend/src/api/client.js#L362)).
   Two causes: (a) responses genuinely arrived out of order — working as designed; (b) the backend
   restarted and its revisions reset *below* the client's watermark, so the client now ignores
   **every** response. Fix for (b) is `resetRevisionWatermark()` ([client.js:62](../../frontend/src/api/client.js#L62)) —
   if a code path restarts/reseeds the backend without calling it, that's the bug.
2. **The route didn't bump the revision.** Only the `state.mutate_*` / `set_design_silent*` helpers
   call `_bump_revision` ([state.py:89](../../backend/api/state.py#L89)). A handler that assigns
   `s.design` directly returns a correct-looking payload the client then discards as stale.
3. **The response carried no geometry.** If `nucleotides` is absent the client makes a second
   `getGeometry()` round-trip ([client.js:547](../../frontend/src/api/client.js#L547)); if *that*
   call fails you get a new design with old positions. Check both calls, not just the first.
4. "Changes then reverts" is usually a slow earlier response landing after a fast later one — see
   (1); it is also the classic signature of two subscribers writing the same store key.

## §3 — Undo skips a step or reverts too much

1. The op must push exactly **one** undo entry. `mutate_and_validate` /
   `mutate_with_reconcile` / `replace_with_reconcile` each push one; `set_design_silent*` push
   none; `snapshot()` pushes one without changing the design.
2. Correct multi-step shape — `snapshot()` once, `set_design_silent_reconciled(...)` for every
   intermediate step, a `mutate_*` for the last. Two `mutate_*` calls in one route = two Ctrl-Z.
3. Reverts too much → an unexpected `clear_history()`. It is **not** limited to bundle creation:
   9 call sites in `crud.py` alone (design load, JSON import, cadnano import, new design) plus
   [headless_build.py:174](../../backend/api/headless_build.py#L174). Grep the handler's whole
   call chain, not just the handler.
4. Depth is capped: `MAX_UNDO_STEPS = 50` ([state.py:58](../../backend/api/state.py#L58)), **per
   document**.

## §4 — Undo does nothing (404)

`_DesignSession.history` for *this document* is empty
([state.py:77](../../backend/api/state.py#L77)). Either `clear_history()` ran (see §3.3), or no
mutation has happened yet **in this doc** — a mutation made in another tab does not fill this
tab's stack. There is no module-level `_history`; don't go looking for one.

## §5 — Clusters are wrong after a topology edit

The mutation used the wrong helper. Any edit that can move cluster membership —
crossover/nick/ligation, autostaple/autobreak, end-extend, slice-plane extrude, overhang/linker
creation, helix CRUD — **must** call `mutate_with_reconcile`
([state.py:264](../../backend/api/state.py#L264)), which runs `reconcile_cluster_membership` and
`_retry_pending_ligations`. Plain `mutate_and_validate` skips both and fails silently.

The inverse is also a bug: routes that *explicitly* edit `cluster_transforms` (cluster CRUD,
feature-log replay, `relax_overhang_connection`, importers) must stay on `mutate_and_validate` —
reconciling would fight their own edit. The exclusion list is in the docstring at
[state.py:277-283](../../backend/api/state.py#L277).

Assembly-side equivalents live in a separate module — `assembly_state.py`, with its own undo stack
and diff snapshots. Don't reach for `state.py` helpers there.

## §6 — Design "lost" after a reload or restart

**Persistence exists on both sides** — this symptom is a failure, not the design.

- Frontend: `persistDesign()` writes `nadoc:design:<docId>` to localStorage on every design
  response ([client.js:30/:70/:556](../../frontend/src/api/client.js#L30)). A wrong/missing doc id
  means it wrote under a key nothing reads back.
- Backend: `session_cache` flushes to `.session/<doc>` and restores on boot
  ([session_cache.py:83, :184, :234](../../backend/api/session_cache.py#L83)).

So check the **doc id** first (§1.1), then whether the flush thread actually started. Manual
`File > Export Design (.nadoc)` is the durable save, but it is not the only persistence.

## §7 — 409 Conflict on DELETE

The entity is still referenced (helix referenced by a strand, strand by another). Delete the
referencing entities first, or use the batch endpoint, which deletes atomically. Examples:
[crud.py:2280](../../backend/api/crud.py#L2280) (helix), :2367, :4323.

## §8 — A frontend api call returned `null`

By contract. Every `_request` non-OK path sets `store.lastError = {status, message}` and returns
`null` ([client.js:330-335](../../frontend/src/api/client.js#L330)); it does not throw. A crash on
`result.id` downstream means a missing null-check at the call site — read `lastError` for the real
server message before debugging the caller.

## Debug endpoints

- `GET /api/design/debug/strand-stats` — strand length/type/sequence stats
  ([crud.py:11200](../../backend/api/crud.py#L11200)).
