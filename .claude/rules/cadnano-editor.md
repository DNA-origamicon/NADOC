---
name: cadnano-editor
description: The standalone Cadnano EDITOR app (separate Vite page, own store, own api.js) — pathview canvas, sliceview, element-key codec, cross-tab broadcast sync, doc scoping.
paths:
  - "frontend/src/cadnano-editor/**"
  - "frontend/cadnano-editor.html"
  - "frontend/src/shared/broadcast.js"
  - "frontend/src/shared/doc_id.js"
---

# cadnano-editor

**A second, separate app.** `frontend/cadnano-editor.html` (1725 ln) is its own Vite multi-page
entry (`frontend/vite.config.js:30`), bootstrapped by `cadnano-editor/main.js`
(`cadnano-editor.html:1723`). **10,713 LOC across 13 files.**

**Three URLs reach it** — normal use is `window.open` from the 3D app (below), but there is also a
FastAPI route `@app.get("/cadnano")` `backend/api/main.py:295` (prod: `FileResponse` of the dist
`cadnano-editor.html`; dev: 302 → `http://localhost:5173/cadnano-editor.html`), and all three e2e
specs use a *third* form, `page.goto('/cadnano-editor')` (no `.html`). Don't assume one entry path.

**Not this rule:** `scene/cadnano_view.js` is the 3D app's K-key *view mode* — a read-only camera
flattening. It shares **no module** with this editor; neither imports the other. See
[cadnano-2d](cadnano-2d.md). Also not this rule: `ui/overhang_pathview.js` lives in the 3D app,
but it **imports from here** — see *Reverse coupling* below.

## File map

| LOC | File | Owns | Entry |
|---|---|---|---|
| 4977 | `pathview.js` | the 2D strand-editing canvas | `initPathview(canvasEl, containerEl, {…24 callbacks})` :260 |
| 2554 | `main.js` | composition root — menus, modals, hotkeys, autosave, sync badge, wiring. **Zero exports**; IIFE :2539 | — |
| 724 | `api.js` | HTTP client + stale-response watermark | `mutate()` :141, `fetchDesign()` :130 |
| 657 | `strands_spreadsheet.js` | bottom strand table, column toggles, inline seq/colour edit | `initStrandsSpreadsheet({…})` :198 |
| 631 | `sliceview.js` | SVG cross-section grid; add/remove helix | `initSliceview(svgEl, containerEl, {onAddHelix, onRemoveHelix})` :96 |
| 433 | `ligation_debug.js` | Ctrl+Shift+L overlay + `window._ligDebug` | `initLigationDebug()` :349 |
| 151 | `zoom_scope.js` | Space-held 240 px magnifier lens | `initZoomScope(canvas, pathview)` :28 |
| 129 | `pathview/palette.js` | all colour constants + per-strand-id staple-colour pinning | `ensureStapleColors()` :105, `stapleColorOf()` :123 |
| 111 | `element_keys.js` | selection-key codec (see below) | 6 builders / 5 parsers |
| 80 | `store.js` | editor-local reactive store | `editorStore` :63 |
| 65 | `sequence_layout.js` | pure: skip/loop-compressed sequence ↔ geometric bp columns | `skipMapFromHelices()` :22, `sequenceColumns()` :47 |
| — | `element_keys.test.js`, `sequence_layout.test.js` | the only unit tests in the directory | — |

`pathview.js` exports exactly two things: `initPathview` (:260) and the four layout constants
(:256). Everything else is closure-private. Returned API :4809 — `update(design)` :4909,
`setTool` :4828, `setSelection` :4867, `setPaintColor` :4842, `setSelectFilter` :4846,
`setViewTools` :4850, `setNativeOrientation` :4891, `setUnligatedCrossoverIds` :4901,
`fitToContent` :4826, `drawToLens` :4816, `getZoom/getPanX/getPanY` :4821-23.

Useful `pathview.js` internal landmarks: coordinate helpers :614 · periodic-boundary helpers :637 ·
`_rebuildLayout()` :807 · hit tests :898 · strand colouring + crossover slots :1425 · draw domains
:1761 · draw placed crossover arcs :2172 · valid-site indicators :2530 · end-drag :2760 ·
domain-drag :2954 · crossover-drag :3095 · `_draw()` :3726 · pointerdown dispatch tree :3825 ·
keyboard :4750.

## Separate-app model (read before "sharing" anything)

`store.js` defines its **own** store. `store.js:5`: *"Does NOT share state with the main 3D window."*
Nothing under `cadnano-editor/` imports `src/state/store.js`. State keys :14-58 — `design` :16,
`selectedTool` :19 (`select|pencil|nick|paint|skip|loop`), `paintColorIdx` :22, `paintCustomColor`
:28, `hoveredStrand` :34, `selectFilter` :47, `viewTools` :51, `loading` :54, `lastError` :57.

⚠️ A 10th key, `unligatedCrossoverIds`, is written by `api.js:120` (`_absorbAuxFields`) but is
**absent from `_initialState`** — `undefined` until the first mutation response. `pathview.js:4901`
defends with `new Set(ids ?? [])`. Any new reader must too.

**Ground truth is the backend, not a shared store.** The two apps stay in step via
`shared/broadcast.js` (channel `'nadoc-design'` :28, per-page-load `_id` :27, self-messages dropped
:42): `emit(type, extra)` :32 · `onMessage(handler)` :40 · `isSameDoc(data)` :52 · `tabId` :55.
Messages are **notifications, not payloads** — the receiver refetches.

Editor's single real subscriber: `cadnano-editor/main.js:2302` — `design-changed` → `fetchDesign()`,
`selection-changed` → `pathview.setSelection` + spreadsheet, plus `editor-list-request`/
`editor-announce`. 3D side subscribes at `frontend/src/main.js:7738`.
(`ligation_debug.js:353` also listens, log-only.)

**Opened from the 3D app at two sites, with different semantics:**
- `main.js:4223` `btn-open-editor` → `window.open('/cadnano-editor.html'+qs, 'nadoc-editor-'+docId)`
  — *named* window, so re-clicking focuses the existing editor for that doc.
- `main.js:7875` "Open New Editor ↗" → window name `'nadoc-editor-'+Date.now()` — always a fresh tab.

## Doc scoping (`shared/doc_id.js`)

`doc_id.js:16` branches at module level: `const _isEditor = location.pathname.includes('cadnano-editor')`,
consumed at `:28` — **an editor tab never mints a doc id.** A *main-app* tab with no `?doc=` mints a
sticky `sessionStorage` id and rewrites the URL (:29-41); a *standalone editor* tab with no `?doc=`
falls back to the backend `__default__` doc and sends **no** `X-NADOC-Doc` header. That asymmetry is
deliberate — don't "fix" it.

Exports: `getDocId()` :47 · `hasExplicitDoc()` :50 · `docHeaders()` :53 · `docHeadersFor()` :63 ·
`docKey(base)` :70 · `docKeyFor()` :74 · `mintDocId()` :77.

## Backend surface

**There is no dedicated editor router.** Only two endpoints are editor-specific, and both live in
the shared god-file `backend/api/crud.py` (mounted `backend/api/main.py:214`, prefix `/api`):

| Route | Where |
|---|---|
| `POST /design/helix-at-cell` | `crud.py:1964` |
| `POST /design/scaffold-domain-paint` | `crud.py:2315` (feature-log subtype :2393; enum `models.py:1603`) |

Everything else (~65 calls in `api.js`) is shared with the 3D app across `crud.py`,
`routes_extensions.py`, and the feature-log / sequences / scaffold-routing / loop-skip routers.

**`helix-at-cell` places relative to a NEIGHBOUR, not to the lattice formula** (`crud.py:1965`
docstring + `:1998-2020`). A sliceview cell-click picks the nearest existing lattice helix by
Manhattan grid distance (linker helices — `_LINKER_HELIX_PREFIX` — excluded), takes XY from that
helix's *real* axis via `_overhang_neighbor_xy` (`backend/core/lattice.py:2684`), and **copies its
`axis_start.z`/`axis_end.z`, `bp_start` and `length_bp`.** Only an *empty* design falls back to the
raw `_lattice_position` + the requested default (42 bp, `bp_start=0`). Why it must stay this way:
on imported / re-centered designs (caDNAno files with `bp_start≠0`) the raw formula put the new
track at z=0, so a strand penned at path-view column *c* landed at a different 3D Z than its
neighbour's column *c*. This was the only add-helix path that skipped the physical-offset
derivation `make_bundle` continuation and overhang-extrude already do.
Frontend sends `populate_strands: false` (`api.js:164`) — cell-click makes a **bare** track, the
user pens strands. The `true` path is legacy-only and uses GLOBAL bp (`lo = bp_start`).

### Two header conventions — both load-bearing

Every `api.js` call funnels through `_request()` (:81); headers at :86-96:

```javascript
...docHeaders(),                    // :88  — target THIS editor's document
'X-NADOC-Skip-Geometry': '1',       // :94  — 2D renders from topology only
```

Backend: `SKIP_GEOMETRY_HEADER` `backend/api/doc_context.py:69`, contextvar :40, extracted in the
ASGI middleware :110/:128, honoured `crud.py:289` and `crud.py:381`.

**Skip-geometry strips TWO things, and the second one is a data-loss trap.**
`should_skip_geometry()` gates (a) `_design_response_with_geometry` (`crud.py:339`) falling back to
the geometry-free `_design_response` (`:268`) — 3D geometry the 2D editor parses and throws away
(VoltronCore: 829 ms / 23.4 MB → ~9 ms); **and (b) `_strip_feature_log_payloads` (`crud.py:244`,
called `:289`)** — snapshot pre/post blobs → `""`, per-child diff blobs → `"1"` sentinel, because
the panel only checks `evicted`/`diffs_evicted` and diff *presence*, never decodes. That was ~1.2 MB
of every response; total 1.93 MB → 0.71 MB.

⚠️ **The editor's in-memory design is therefore INCOMPLETE.** Its restart-recovery
(`main.js:213-232`, backend-came-back-empty branch) must reload from the **workspace file**
(`getLibraryFileContent` → `importDesign`) — re-importing the stripped in-memory copy would
**permanently destroy the fine-routing revert history**. The in-memory fallback is reached only for
a never-saved design, and it prompts. Server-side revert/seek/save are unaffected: the backend keeps
the real blobs and only the response *copy* is edited. Any new "restore from the editor" path
inherits this trap.

**All mutations MUST go through `mutate()`** — `api.js:655-660` records why: an old inline bare
`fetch` in main.js carried no doc header, so revert/delete/seek hit the wrong document and threw
*"Feature index N out of range (log has 1 entries)"*. Undo/redo (:693, :713) hand-roll both headers
for the same reason (:691) and treat 404 as silent.

Sanctioned bare-`fetch` escapes: the three exports (`api.js:552/566/580`) carry `docHeaders()` but
deliberately **omit** skip-geometry (exports need geometry). Editor `main.js:137/234/290` also
fetches directly for export/workspace save-load.

### Stale-response watermark (don't remove)

`api.js:24-56`. `_lastAppliedRev` is monotonic; `_applyDesignResponse` (:41) **drops** any response
with `revision < _lastAppliedRev`. This is what stops the "nick appears, then reverts a second
later" bug under concurrent edits. `resetRevisionWatermark()` (:59) **must** be called on backend
restart or the editor freezes on stale data — the connection monitor at `main.js:190` owns that.

## Element-key codec law (`element_keys.js`)

**bp indices CAN BE NEGATIVE.** Helices start as low as bp −17. Every parser matches `-?\d+`; a
`\d+`-only regex silently fails to match a negative key, which once made negative-bp scaffold stubs
undeletable (`issues_ledger.md` ISSUE-7). The law is stated in the file header :6-11.

```javascript
const LINE_RE = /^line:(.+)_(-?\d+)_(-?\d+)_(FORWARD|REVERSE)$/   // :79
const END_RE  = /^end:(.+)_(-?\d+)_(FORWARD|REVERSE)$/            // :80
const XO_RE   = /^xo:(.+)_(-?\d+)_(FORWARD|REVERSE)$/             // :81
const LS_RE   = /^ls:(.+)_(-?\d+)_(loop|skip)$/                   // :82
```

Builders: `domainLineKey` :20 · `domainEndKey` :27 (5p/3p resolved from direction :30-31) ·
`xoverKey` :36 · `forcedLigKey` :41 (`fl:${id}`) · `loopSkipKey` :70. Parsers :85/:91/:97/:103/:109.
Also `crossoverJunctionSlots(design)` :55 — a `Set` of `"{helix}_{bp}_{dir}"` mirroring the backend
`crossover_junction_slots`.

The `(.+)` for helix_id is **greedy on purpose** (:75-77): helix ids contain underscores *and*
digits (`h_XY_0_0`), so backtracking is what makes the split correct.

Sweep verified 2026-07-30: **no `\d+`-only offender exists** anywhere in `frontend/`. Everything
outside the codec is prefix dispatch that delegates the numeric parse back
(`pathview.js:2766/2960/4000/4730`, `main.js:2054/2069/2081/2082/2085/2123`) — with one exception,
`main.js:2070` `key.slice(3)`, an inline duplicate of `parseForcedLigKey` (index-free, so harmless,
but it is codec logic living outside the codec).

## Geometry / layout

World-space px, `pathview.js:18-32`:

```
GUTTER 40   RULER_H 26   TOP_PAD 18   BP_W 10   LABEL_R 16
CELL_H 12   PAIR_Y 12 (= CELL_H)   ROW_H 40   GROUP_GAP 28
EXTEND_BPS 56   MIN_ZOOM 0.06   MAX_ZOOM 10   XOVER_R 4 (:102)
EXT_LEN_PX 18 / EXT_ANGLE_RAD 145°  (:35-36)
```

**bp → x** (`:629-636`) — cell-boundary convention, quoted from the code:

```javascript
// bp index N corresponds to the Nth cell (square).
// Cell N occupies world x ∈ [_bpToX(N), _bpToX(N+1)]; its centre is _bpCenterX(N).
// Nick/crossover gaps also land at _bpToX(N) boundaries — NOT at cell centres.
function _bpToX(bp)     { return GUTTER + bp * BP_W }
function _bpCenterX(bp) { return GUTTER + (bp + 0.5) * BP_W }
function _xToBp(worldX) { return Math.floor((worldX - GUTTER) / BP_W) }
```

**helix → y** comes from `_rowMap`, built in `_rebuildLayout()` (:809):
`{fwdY, revY: fwdY + PAIR_Y, scaffoldFwd, cell, idx, label}`, `fwdY` advancing by `ROW_H` with
`+GROUP_GAP` at flood-fill group boundaries. Row hit-test is a `ROW_H/2` band around the pair
midpoint (`_helixAtWY` :617-624).

**Negative bp bites the fit path too** — `_fitToContent` :882-889 offsets `panX` by `worldLeft`
(`Math.min(0, _minBp)`), because `_bpToX` applies no bp0 shift and negative cells otherwise render
left of the canvas and become unclickable. Repeat this in any new fit/pan/cull path.

**Two ordering conventions coexist by design.** `_nativeOrientation` (`pathview.js:811-813`,
`sliceview.js:104-107`): gutter labels use the **native** index (`nativeIdx`, computed before the
reverse) while row order is reversed when not native, so pathview matches the sliceview's Y-up.
Label ≠ row position — don't "fix" it. Lattice parity: `sliceview.js:71-72` even `(row+col)` →
FORWARD (cadnano2 convention), mirrored in `scene/slice_plane/lattice_math.js:19`.

## Invariants

- **pathview is render-only.** It imports **no** `api.js`; every mutation exits through one of the
  24 `on*` callbacks passed to `initPathview` (:261-283). Three-Layer Law — keep it that way.
- **Crossover offset tables mirror the backend** (`pathview.js:122`; likewise
  `crossoverJunctionSlots` `element_keys.js:46-53`). Editing one side alone desyncs the clickable
  crossover sites from what the backend will accept.
- **Staple colours are pinned per strand id, not array index** (`pathview/palette.js:91-102`).
  Index-based colouring meant a nick or ligation renumbered every later strand and silently
  recoloured untouched ones, and the canvas disagreed with the sorted spreadsheet.
  `ensureStapleColors(design)` must run before `stapleColorOf()`; the map resets on `design.id`
  change (:107-110).
- **Periodic-boundary auto-shift is a user-stated law** (`pathview.js:4930-4944`): auto-shift fires
  only when an **edit grows the extent outward past a slider**, then translates *both* sliders so
  period P stays constant. Deliberately *not* "slider is inside the structure" — a user may park a
  seam at an interior jagged point. Two `MUST stay in sync` notes at :2334 / :2354 tie the
  mirror-pass drawing to `is_periodic_seam`.
- **Domain-shift clamping asymmetry** (`pathview.js:2992`): ForcedLigation records do **not** clamp;
  their bp is shifted by the same delta on commit.
- **`update()` clears selection** (`pathview.js:4923-4925`), so any broadcast-driven refetch from
  the 3D tab wipes the editor's selection. The reverse direction is guarded against an echo loop by
  `_syncingFromBroadcast` (`main.js:2321-2324`).
- **Every local edit autosaves; the badge is only the fallback.** `_runAutosave` (`main.js:356`) /
  `_scheduleAutosave` (:394, `_AUTOSAVE_DEBOUNCE_MS = 600`), driven from the store's `design`
  subscriber, with in-flight + pending guards and a `_lastSavedDesign` reference check. It is gated
  on `_hasSaveTarget()` (:352 — a workspace path in `localStorage` **or** a File System Access
  handle); a never-saved design keeps the yellow "unsaved" badge until the first manual Save
  establishes a target (user's choice). Workspace-path save wins over the file handle.
  - **The write is announced BEFORE it happens** — `nadocBroadcast.emit('file-saved', {path})`
    (:371) precedes `saveDesignToWorkspace` so the 3D tab skips its SSE file-changed reload
    (5 s self-saved window on the receiver). Drop that emit and the 3D tab reloads our autosave
    into the shared backend doc — a stale snapshot over in-progress edits, surfacing as
    "the nick reverts a second later". (Distinct from the `_lastAppliedRev` watermark above:
    that one drops stale *responses*, this one suppresses a stale *file reload*.)
  - **Only the originating tab autosaves** — `_suppressUnsavedBadge` (`main.js:334-335`) is set in
    the broadcast handler (:2308) and on initial load (:2543), because loading backend state is not
    a local edit. Forget it and every sibling-tab edit looks like a local change, triggering a
    redundant write and a two-tab race (resolution is last-write-wins).
- **The two pathview caches key on `_design` REFERENCE identity, so the design object must never be
  mutated in place.** `_ensureStrandIndex` (`pathview.js:1440`, bucket index for `_findStrandIdxAt`
  — which is otherwise O(strands × domains) and runs ~2×/crossover/frame: 9.5 → 0.85 ms on a
  1252-crossover design) and `_ensureComponents` (:1508, the crossover-slot set + `ensureStapleColors`).
  Both compare `_designRef !== _design` and rebuild only on change — that is what makes pan/zoom
  free. An in-place edit of the current design object silently reuses a stale index and hit-tests
  the wrong strand. Replace the reference; don't patch it. (`_helixById` :376 is rebuilt
  unconditionally in `_rebuildLayout` :818 — different lifecycle.)
- **`DBG` is commit-time state** — `pathview.js:104-109` `const DBG = false`, *"flip to true while
  debugging, then revert before commit"*.

## Reverse coupling (the trap)

`frontend/src/ui/overhang_pathview.js` is a **3D-app** module that imports **upward into this app**:

- `:32-37` — `BP_W, CELL_H, PAIR_Y, GUTTER` from `../cadnano-editor/pathview.js`
- `:38-54` — `STAPLE_PALETTE` + 14 `CLR_*` from `../cadnano-editor/pathview/palette.js`

Consequences: (a) changing any of those four numbers moves geometry in **two** apps; (b) importing
`pathview.js` for four constants drags the whole 4977-LOC module and its dependency graph into the
main-app bundle. Note also `:60-63` re-declares `RULER_H/LABEL_R/TOP_PAD` **locally** with
`LABEL_R`/`TOP_PAD` deliberately *different* from pathview's 16/18 — the "mirrors cadnano-editor"
comment there is only partly true.

`STAPLE_PALETTE` is a **five-way** invariant, not three (all agree today — same 12 colours, same order):

| Copy | Where | Form |
|---|---|---|
| **3D (canonical)** | `scene/helix_renderer/palette.js:28` | `0xrrggbb` |
| backend | `backend/core/constants.py` | `'#rrggbb'` |
| backend surface | `backend/core/surface.py` `_STAPLE_PALETTE_HEX` | `0xRRGGBB` |
| editor | `cadnano-editor/pathview/palette.js:85-89` | `'#rrggbb'` |
| atomistic / picker | `scene/color_util.js` `ATOM_STAPLE_PALETTE`, `scene/selection_manager.js` `PICKER_COLORS` | `0xrrggbb` / `{hex,css,label}` |

The sync-pointer comments all named `scene/helix_renderer.js`, which has only *imported* the constant
(:33) since the palette module was extracted — **corrected 2026-07-31** (TD-02); the full copy list now
lives in one place, the comment above `STAPLE_PALETTE` in `backend/core/constants.py`.
**Frontend code must import `STAPLE_PALETTE`, never re-declare it.**

⚠️ Matching the palette *list* is only half of it — **the ASSIGNMENT must match too.** 3D pins a slot
per `strand.id` for the life of the design (`buildStapleColorMap`), exactly as this editor's
`ensureStapleColors` does; `ui/spreadsheet.js` re-derived `index % 12` and drifted after every
mutation until 2026-07-31. See `memory/project_tech_debt.md` TD-02.

## Hotkeys

Global handler `main.js:1337` (window keydown). **Guard order matters:** undo/redo/open/save are
checked *before* the INPUT/TEXTAREA bail (:1375), then `if (ctrl) return` (:1376).

| Key | Action | Where |
|---|---|---|
| `Ctrl/⌘+Z` / `Ctrl+Y` / `Ctrl+Shift+Z` | undo / redo | main.js:1342 / :1349 |
| `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` | open / save / save-as (clicks the menu item) | main.js:1358/1364/1369 |
| `F` | fit to view (slice + path) | main.js:1379 |
| `R` | **cycle tool** `select→pencil→nick→paint` | main.js:1387 |
| `N` | Nick tool | main.js:1397 |
| `P` | Paint tool; **P again while on Paint nudges the custom colour +1 hex** | main.js:1406 |
| `Tab` | cycle select-filter (`preventDefault`) | main.js:1422 |
| `1` | Scaffold ends routing | main.js:1436 |
| `2` | Full autostaple | main.js:1439 |
| `4` `5` `6` | update routing / assign scaffold seq / assign staple seq | main.js:1440-1442 |
| `S` | toggle strands spreadsheet | main.js:1445 |
| `?` / `F1` | help modal | main.js:1448 |
| `Escape` | close help modal, else drop back to Select | main.js:1449 |
| `Space` (hold) | zoom-scope magnifier | zoom_scope.js:131 / :139 |
| `Ctrl+Shift+D` | sync-debug panel | main.js:326-327 |
| `Ctrl+Shift+L` | ligation-debug overlay | ligation_debug.js:403 |
| `Escape` | cancel in-progress forced ligation | pathview.js:4751 |
| `Shift` ↓/↑ | scaffold-side crossover indicators + ligation ghost (`_shiftHeld`) | pathview.js:4757 / :4777 |
| `D` | sprite hit-radius debug overlay + `console.table` | pathview.js:4759 |
| `Delete` / `Backspace` | delete selection (Select tool, non-empty) | pathview.js:4781-4790 |

Gotchas: **`3` is not bound** (`2` subsumed the old auto-crossover/autobreak keys — comment
:1437-1438). `skip` and `loop`, both legal `selectedTool` values, are **not reachable by hotkey** —
toolbar only; `R`'s cycle is 4-long. `Escape` is bound in three places without `stopPropagation`, so
cancelling a forced ligation *also* resets the tool to Select. `Ctrl+Shift+L` matches `'L'`
case-sensitively with no lowercase fallback (`Ctrl+Shift+D` at :327 tests both).

## Test coverage — state it honestly: there is almost none

**Unit: 2 files, 176 LOC of the 10,512 production LOC (≈1.6%), 21 assertions.**
`element_keys.test.js` (15 `it()`s — negative-bp ISSUE-7 regression :12, round-trips :44, wrong-prefix
null :85, junction slots :96) and `sequence_layout.test.js` (6). `pathview.js` (4977), `main.js`
(2554), `api.js` (724), `strands_spreadsheet.js` (657), `sliceview.js` (631), `ligation_debug.js`
(433), `zoom_scope.js`, `store.js`, `pathview/palette.js` have **zero** unit tests.

**Backend: `tests/test_cadnano_editor_api.py` — 25 tests / 433 LOC**, covering exactly the two
editor-only endpoints + the skip-geometry header: `TestHelixAtCell` :54 (13),
`TestScaffoldDomainPaint` :267 (8), `TestSkipGeometryHeader` :391 (3). The other ~65 endpoints the
editor calls are covered, if at all, by the general `crud` test files.

**E2E (Playwright — not routine):** `e2e/cadnano_sliceview_positions.spec.js:86` (asserts each
occupied `.sv-cell` label equals the helix's index in `design.helices` — creation order, no
geometric sort — plus the row-0 y-flip) and `e2e/autobreak_edges.spec.js:194,257`.
**`e2e/cadnano_crosssection.spec.js` does NOT touch this app** — it drives the *3D* slice plane on
an imported caDNAno file. All editor specs `goto('/cadnano-editor')` without `.html` and never with
`?doc=`, so E2E only ever exercises the default-document path.

Treat every change to `pathview.js`/`main.js` as unpinned: exercise it in the running app.

## Debug handles

`window._ligDebug` (`ligation_debug.js`, Ctrl+Shift+L) · Ctrl+Shift+D sync panel (`main.js:326`) ·
`D` in pathview for sprite hit radii · `DBG` const `pathview.js:104` (revert before commit).

## Removed API / do-not-resurrect

| Name | Reality |
|---|---|
| `frontend/src/cadnano/` | Never existed. This app is `frontend/src/cadnano-editor/` |
| a shared store between the two apps | Explicitly refused — `store.js:5`. Sync is BroadcastChannel + backend refetch |
| a dedicated editor FastAPI router | None. The 2 editor-only routes live in `crud.py` |
| `\d+` in any element-key regex | Forbidden — bp is signed (ISSUE-7). Always `-?\d+` |
| bare `fetch` for a mutation | Forbidden — misses `docHeaders()`, hits the default doc (`api.js:655-660`) |
| `ui/lattice_editor.js` | Deleted 2026-07-25; orphaned by the 2026-04-11 editor overhaul |
| hotkey `3` | Unbound; folded into `2` (full autostaple) |
| `_flMutate` | Gone. The feature-log panel gets a 4-method `_flApi` delegate (`main.js:2433` → `initFeatureLogPanel` :2440); it routes through `api.js` `mutate()`, which broadcasts `design-changed` (:51). The old inline shim skipped `docHeaders()` — see :2429-2432 |
| `Origami`, `Connection`, `?origami_id=` | **Vocabulary from the abandoned 2026-04 phase plan.** Never built. What shipped instead: `Part`/`PartInstance`/`PartGroup` (`models.py:2682+`), the `?doc=` per-document registry (`state.py` `_sessions`), and cross-origami strand links as **overhang connections / assembly bindings** — not a `Connection` model. Don't reintroduce the names |
| FEM/RMSF heat-map overlay in pathview | Planned in 2026-04, never built, and now unbuildable — the FEM/XPBD code was retired. Zero `fem\|rmsf\|xpbd` hits under `cadnano-editor/` |
