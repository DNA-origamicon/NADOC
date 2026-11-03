
# Primitive library ("Add Primitive") — topic

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Pre-validated DNA-origami building blocks offered in the part editor's right
sidebar. Tools → Add Primitive reveals a collapsible **Primitives** panel
(`#primitives-panel`) listing each primitive as a card: rendered thumbnail +
name + "NHB" badge + short description + "Honeycomb · N helices" meta.

## Status

- **Shipped 2026-06-11 (UI shell):** panel + live catalog + animated hover previews.
- **Shipped 2026-06-11 (placement):** selecting a card now **arms placement** — the
  primitive's cross-section drops onto the lattice as an **additive, feature-logged,
  revertable** extrude. See "Placement" below.
- **Shipped 2026-06-11 (parametric circle):** a `metadata.primitive_kind="circle"`
  primitive (`small_circle.nadoc`) places as a **flat disc of variable radius** — a
  radius-nm box instead of a length box. See "Parametric circle" below.
- Seed primitives: **6hb + 18hb beams + small_circle (disc)** in `workspace/Primitives/`.
- **Hinge primitives (added by user 2026-06-25):** `2x2_single_hinge_link`,
  `2x4_double_hinge_link`, `2x6_triple_hinge_link` in `workspace/Primitives/`. See
  "Hinge primitives" below. **These are THE canonical building blocks for any hinged
  component** — whenever a design (or text-to-DNA request) calls for a hinge, start from
  one of these rather than hand-routing a new one.

<a id="hinge-primitives-2026-06-25"></a>
- [Hinge primitives (2026-06-25)](details/project_primitive_library/01-hinge-primitives-2026-06-25.md#hinge-primitives-2026-06-25)

<a id="placement-2026-06-11"></a>
- [Placement (2026-06-11)](details/project_primitive_library/01-hinge-primitives-2026-06-25.md#placement-2026-06-11)

- [Placement (2026-06-11) — continued detail](details/project_primitive_library/01-hinge-primitives-2026-06-25.md)

<a id="parametric-circle-flat-disc--2026-06-11"></a>
- [Parametric circle (flat disc) — 2026-06-11](details/project_primitive_library/01-hinge-primitives-2026-06-25.md#parametric-circle-flat-disc--2026-06-11)

- [Parametric circle (flat disc) — 2026-06-11 — continued detail](details/project_primitive_library/02-parametric-circle-flat-disc--2026-06-11.md)

<a id="add-a-primitive-onto-an-existing-parts-face--2026-06-11"></a>
- [Add a primitive onto an existing part's FACE — 2026-06-11](details/project_primitive_library/02-parametric-circle-flat-disc--2026-06-11.md#add-a-primitive-onto-an-existing-parts-face--2026-06-11)

<a id="bentdeformed-faces--2026-06-11-shipped-e2e-verified"></a>
- [Bent/deformed faces — 2026-06-11 (shipped, e2e-verified)](details/project_primitive_library/02-parametric-circle-flat-disc--2026-06-11.md#bentdeformed-faces--2026-06-11-shipped-e2e-verified)

<a id="suppress-origin-grid-on-an-existing-structure--2026-06-11"></a>
- [Suppress origin grid on an existing structure — 2026-06-11](details/project_primitive_library/02-parametric-circle-flat-disc--2026-06-11.md#suppress-origin-grid-on-an-existing-structure--2026-06-11)

## Architecture

- **Catalog source (temporary):** backend scans `workspace/Primitives/*.nadoc`
  live. `backend/core/primitive_catalog.py` (pure: `derive_metadata`,
  `list_primitives`, path helpers — metadata auto-derived from the design; a
  design `name` equal to the file stem is ignored so it shows "6-Helix Bundle"
  not "6hb_primitive"). Router `backend/api/routes_primitives.py`: `GET
  /primitives`, `GET /primitives/{id}/preview.gif`, `…/poster.png` (FileResponse).
  Registered in `main.py`. **Better future solution documented but NOT built:**
  in-repo `primitives/<id>/` registry + `manifest.json` — see
  `workspace/Primitives/README.md`.
- **Hover preview pipeline:** `just build-primitives` →
  `frontend/scripts/build-primitives.mjs` (Playwright) loads each design in the
  real app, drives the camera through its **saved camera poses** (ping-pong loop,
  eased), captures frames, encodes a **GIF** (+ first-frame poster PNG) written
  next to the `.nadoc`. Re-run after editing a design/poses.
- **Capture core:** `frontend/src/scene/primitive_preview_capture.js` —
  `buildCameraPath(poses,…)` is the pure, unit-tested planner;
  `capturePosesGif({renderer,…})` renders + grabs in the SAME tick (the
  `export_video.js` pattern → **no `preserveDrawingBuffer` needed**) and encodes
  with the already-bundled `gifenc`. Driven by a DEV-only hook
  `window.__nadocTest.capturePrimitivePreview(opts)` (main.js).
- **Encoder choice:** GIF now (zero new deps — gifenc was already present). The
  encode is isolated in `capturePosesGif`, so swapping to **animated WebP** later
  = change there + the file extension in the baker + the served media type.
  (User picked WebP, but no webp encoder is installed; chose GIF-now to ship.)
- **Panel:** `frontend/src/ui/primitive_library.js` `initPrimitiveLibrary({store,
  api})`. Renders the static `primitive_catalog.js` fallback immediately, then
  upgrades in place from `api.listPrimitives()`. Cards show the poster `<img>`
  that swaps `src` → `preview.gif` on `mouseenter`, back on `mouseleave` (never
  autoplay a wall of GIFs). No preview → inline SVG cross-section schematic
  (`primitiveThumbSvg`). main.js gains only imports + factory init + the
  `menu-tools-add-primitive` handler (module-first; LOC Δ pure wiring).
- **Hover zoom (2026-06-11):** hovering a card ALSO shows a larger preview pinned
  to the **upper-right of the workspace** — a `position:fixed` `#primitive-preview-zoom`
  div (created in `primitive_library.js`, appended to body, `pointer-events:none`).
  `_positionZoom` anchors it against `#viewport-container`.right (just left of the
  right panel, near the cursor) and `#filter-view-strip`.bottom+12 (below the
  selectable strip), size-constrained to the visible workspace so it never spills
  over the left sidebar. Shows
  `preview_url` (animated) → `poster_url` → SVG schematic, with a name caption.
  Dismissed on `mouseleave` and in `hide()`.

## Gotchas / notes

- Build script uses a **unique `?doc` per primitive** (fresh page each) so the
  "wait for backboneSpheres count>0" readiness check starts from 0 — reusing one
  doc would pass instantly on a stale prior design.
- Loads a design by POST `/api/design/load` {path: "workspace/Primitives/…"} +
  a `new BroadcastChannel('nadoc-design')` `design-changed` msg carrying
  `docId` (mirrors `scene_harness.loadScaffoldedPart`). The welcome overlay is
  DOM-only — it doesn't taint canvas pixel capture.
- Posters currently include the origin axes helper (yellow/green/blue lines) when
  visible in the scene — minor; a future polish could hide axes before capture.

<a id="tests"></a>
- [Tests](details/project_primitive_library/03-tests.md#tests)
