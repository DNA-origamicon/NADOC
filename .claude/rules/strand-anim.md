---
name: strand-anim
description: Strand-animation sandbox (ssDNA⇄duplex + strand displacement) — layered model/renderer/host for drop-in to the main animation toolset.
paths:
  - "frontend/src/strand-anim/**"
  - "frontend/strand-anim.html"
---

# strand-anim

Standalone **display-only** ball-and-slab DNA animation sandbox (`/strand-anim.html`,
Help → "Strand Animations Testing…"). A single φ ∈ [0,1] slider drives un/hybridization
across two scenarios (Unzip / Strand displacement) × two forms (straight / helical).
**No Design, no topology, no backend** — pure parametric geometry.

**Full detail + integration handoff:** `memory/project_strand_animations.md` (read the
"Integration handoff" section — this module is being merged into the main animation toolset).

## Layering (the key thing to know before editing)

Built for drop-in: keep the model/renderer pure and page-free.

| Layer | Files | Deps |
|---|---|---|
| **Model** (pure math) | `model.js` (facade), `params.js`, `melt.js`, `geometry_{straight,helical,displacement}.js` | none |
| **Renderer** (THREE only) | `strand_renderer.js` | `three`, `model.js` |
| **Ticker** (RAF only) | `ticker.js` | none |
| **Page glue** | `app.js`, `panel.js`, `main.js`, `strand-anim.html` | scene / DOM / page primitives |

**Do not** import THREE, DOM, scene, store, or `../api` into the model layer — it must stay
host-agnostic. Rendering math lives in `strand_renderer.js`, not the builders.

## Two seams a host uses
- `buildStrandGeometry(params, phi)` (model.js) → `{ strands:[{pos,tan,bn,role}], meta }`.
  Flat Float32Arrays per strand; `meta.readout` is the status string. Contract JSDoc is at the
  top of `model.js`.
- `createStrandRenderer(scene, {roleColor?})` (strand_renderer.js) → `{ update(strands), dispose() }`.
  Adds `strandBeads`/`strandSlabs` InstancedMeshes + pooled `strandBackbone*` Lines; grows buffers
  automatically. Bead/slab constants are copied verbatim from `scene/helix_renderer.js`.

Host loop: `renderer.update(buildStrandGeometry(params, phi).strands)` on φ/param change.

## Invariants (don't regress)
- Geometry lies along **+X in the XY plane**; helix spirals in **YZ**. Bead positions + slab
  orientation match `backend/core/geometry.py` / `helix_renderer.js` (HELIX_RADIUS 1.0, 150°
  minor groove, 34.3°/bp twist, `base_normal` = cross-strand chord, `axis_tangent` = helix axis).
- Helix phase is anchored at the **fork / binding front** (continuous), so freed strands peel up
  cleanly and the duplex "twists as pulled apart". Don't re-anchor at a fixed end (causes the
  periodic strand-clipping that was already fixed).
- `meltBp` blends each base bound↔free over a few bp around the front (smooths slab reorientation).
- Displacement φ = fraction of invader bound over all N bp: φ∈[0,t/N] zips the toehold, then
  branch-migration. The substrate region between the binding front and `t` has no partner → it is
  the exposed ss toehold (emergent, not special-cased).
- `ticker.js`: `dt` clamped ≥0 and boundary checks are direction-aware — needed so Play from a
  boundary (φ=0/φ=1) sweeps inward instead of instantly finishing.

## Verify
Frontend-only (no Python). Pure builders are node-testable directly
(`node --input-type=module` importing the geometry files). Exercise the page via the headless
Playwright pattern used throughout the topic file (readouts + screenshots; check zero console
errors across scenario×form×play). Not part of the routine E2E suite.
