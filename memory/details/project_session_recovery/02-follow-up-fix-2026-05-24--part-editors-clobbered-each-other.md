# Follow-up fix 2026-05-24 — part editors clobbered each other — supporting detail

[Topic head](../../project_session_recovery.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Follow-up fix 2026-05-24 — part editors clobbered each other
Opening several parts from an assembly (then their cadnano editors) let Part B's design
replace Part A's. **Root cause:** every part-editor tab inherited the ASSEMBLY's doc
(`onEditPart` opened `?part-instance=…&doc=<assemblyDoc>`), and part-edit init does
`POST /design/import` → `set_design()` which overwrites that doc's single design slot. So
each part import clobbered the previous one; the cadnano editors (inheriting the shared
doc) saw the clobbered slot. The doc was shared on purpose so save-back
(`patchInstanceDesign`) hit the same assembly the assembly tab shows.
**Fix (frontend-only — backend already keys per-doc):** separate the two concerns. Each
part editor gets its OWN isolated doc; the assembly doc rides in a NEW `?assembly-doc=`
param. Exactly three ops address the assembly doc via a one-off `X-NADOC-Doc` override:
source-design fetch, save-back (`patchInstanceDesign`), and the cross-tab sync re-import.

**GOTCHA that broke the first attempt (fixed same day):** the part editor's own doc must
be passed EXPLICITLY as `?doc=pe-<asmDoc>-<instanceId>` (deterministic, uuid-unique per
instance). It CANNOT be left to `doc_id.js` sticky synthesis: `window.open()` copies the
opener's `sessionStorage` into the child, so the assembly tab's sticky `nadoc:tab-doc`
leaks in and every part editor resolves to the SAME doc — re-creating the exact clobber
(B overrides A). This inheritance is intentional for cadnano editors (they SHOULD share
the parent doc) but wrong for part editors. Explicit `?doc=` wins in `_resolveDocId`
(returns before the sessionStorage branch), so it overrides the inherited id. Mechanism:
- `doc_id.js`: new `docHeadersFor(docId)` + `docKeyFor(base, docId)` (address an explicit,
  non-own doc).
- `client.js`: `_request(..., { docId })` override (default `undefined` = unchanged);
  `patchInstanceDesign`/`importAssembly` accept `{ docId }`; `getPersistedAssembly(docId)`
  reads another doc's recovery cache.
- `main.js`: part-edit init reads `assembly-doc`, fetches source + restart-restore +
  sync-reimport against it, stores it in `_partEditContext.assemblyDoc`, **drops the old
  `api.getAssembly()`** (its only consumer was beforeunload persist — now guarded:
  `persistAssembly()` skipped in part-edit). `_savePartToAssembly` save-back uses
  `{ docId: assemblyDoc }`. `onEditPart` opens `?doc=pe-<asmDoc>-<instId>&assembly-doc=`.
- `assembly_panel.js` Edit button: same `?doc=pe-…&assembly-doc=` (previously passed NO doc → would
  have broken save-back). cadnano open unchanged — `getDocId()` is now the part's own
  isolated doc, so each part's editor lands in a distinct `nadoc-editor-<doc>` window.
- Regression test: `tests/test_part_edit_doc_isolation.py` (import-isolation across two
  part docs + save-back routing to the assembly doc, via `peek_design`/`peek_assembly`).
  `just test` 1445 pass (the 1 fail is the known PYTHONHASHSEED-flaky `test_seamed_router`).
- **Multi-tab/multi-window browser flow NOT exercised by the implementer** — needs a 2+ part
  assembly and is best confirmed manually (USER TODO given).

### Follow-up fix 2026-05-27 — surface + atomistic reps broken (missing docHeaders)
Symptom: surface (F5) and BOTH atomistic reps (vdw F6, ballstick F7) render nothing, while
CG/cylinders/beads/hull work. **Root cause:** three raw `fetch()` calls in `main.js` omitted
`docHeaders()` — surface (`_applySurfaceMode`, ~L2040), atomistic apply (`_applyAtomisticMode`,
~L2341), atomistic refetch (`_refetchAtomistic`, ~L2136). Since the 2026-05-23 sticky-per-tab-doc
change, EVERY main-app tab is on a non-default doc, so those header-less requests hit the empty
`__default__` doc → 404 → the renderers got no data. CG/cylinders/hull render from store data
(loaded via the api client, which sends the header), so they were unaffected. The
`/api/design/surface` + `/api/design/atomistic` route handlers were fine — purely a frontend
doc-routing miss. **Fix:** added `{ headers: docHeaders() }` to all three (docHeaders already
imported, main.js L119). Also fixed the same omission in the three fetch-based export helpers in
`client.js` (`exportSequenceCsv`, `exportCadnano`, `exportSurfaceStl`) — they'd export the empty
default doc in a spawned tab. Verified via TestClient: design in a non-default doc → both endpoints
404 without header, 200 with header (surface 60842 faces, atomistic 10080 atoms).
**STILL BROKEN (not fixed, flagged to user):** PDB/PSF/NAMD-package exports in `main.js` use
anchor-`href` navigation (`a.href='/api/design/export/pdb'`), which can't send custom headers →
they hit the default doc in a spawned tab. Fix requires switching to a `?doc=<getDocId()>` query
param (backend's `DocContextMiddleware` reads `?doc=`) or the blob+fetch pattern. **General lesson:
any raw `fetch('/api/…')` or anchor-href to a design/assembly endpoint MUST carry the doc id, or it
silently targets `__default__`.** See [[lessons]] stale-state/doc-isolation.
