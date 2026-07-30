---
name: strand-anim
description: Strand-animation sandbox (ssDNA⇄duplex + strand displacement) — pure model/renderer/ticker layers that the main editor now imports in production.
paths:
  - "frontend/src/strand-anim/**"
  - "frontend/strand-anim.html"
---

# strand-anim

**Audited 2026-07-30 against the code.** 11 files, **1,084 LOC**, **zero tests**.

A **display-only** ball-and-slab DNA animation sandbox (`/strand-anim.html`, Help → "Strand
Animations Testing…"). A single φ ∈ [0,1] slider drives un/hybridization across two scenarios
(Unzip / Strand displacement) × two forms (straight / helical). **No Design, no topology, no
backend** — pure parametric geometry.

> ⚠️ **This is no longer only a sandbox.** Three modules in the main app import from this
> directory in production (see *Who imports this*). Editing `params.js` or `melt.js` changes
> editor animations. The sandbox page is the *only* consumer of `model.js`.

**Full detail + integration handoff:** `memory/project_strand_animations.md` §"Integration
handoff". The editor-side half of the story lives in [animation.md](animation.md) — it owns the
three consumer files and documents the two-path split.

## Files

| Layer | File | LOC | Imports |
|---|---|---|---|
| **Model** (pure math) | [model.js](../../frontend/src/strand-anim/model.js) facade | 61 | the 3 builders only |
| | `params.js` (DEFAULTS + `createParamState`) | 62 | **none** |
| | `melt.js` (`meltFraction`, `smoothstep`) | 30 | **none** |
| | `geometry_straight.js` | 129 | `melt.js` |
| | `geometry_helical.js` | 145 | `geometry_straight.js`, `melt.js` |
| | `geometry_displacement.js` | 151 | `geometry_straight.js`, `melt.js` |
| **Renderer** | `strand_renderer.js` | 142 | `three`, `model.js` (`ROLE_COLOR`) |
| **Ticker** | `ticker.js` (`createPhiTicker`) | 108 | **none** |
| **Page glue** | `app.js` (host loop) | 80 | `../scene/scene.js` |
| | `panel.js` | 163 | `../ui/primitives/*` |
| | `main.js` (entry) | 13 | — |
| | `../../strand-anim.html` | 99 | Vite input `vite.config.js:31` |

Purity law **verified held today**: no `three`, DOM, `../scene`, `../state` or `../api` import
exists anywhere in the model layer. Keep it that way — three production modules depend on it.

Menu wiring: `index.html:3552` `#menu-help-strand-anim` → `main.js:7159` `window.open('/strand-anim.html', …)`.

## The two seams

- **`buildStrandGeometry(params, phi)`** ([model.js:56](../../frontend/src/strand-anim/model.js#L56))
  → `{ strands: [{pos, tan, bn, role}], meta }`, flat `Float32Array`s per strand, `meta.readout`
  the status string. It is a 3-way dispatch; the contract is actually produced by the builders
  (`geometry_straight.js:119`, `geometry_helical.js:135`, `geometry_displacement.js:140`).
  Roles: `A`/`B` (unzip), `substrate`/`invader`/`incumbent` (displacement).
  Contract JSDoc `model.js:1-32` is correct — **the per-builder `@returns` blocks are not** (see Traps).
- **`createStrandRenderer(scene, {roleColor?, lineOpacity?})`**
  ([strand_renderer.js:41](../../frontend/src/strand-anim/strand_renderer.js#L41)) → `{update(strands), dispose()}`.
  `lineOpacity` (default 0.55) is **not optional trivia** — production passes it
  (`overhang_strand_anim.js:200`). Adds InstancedMeshes named `strandBeads`/`strandSlabs` (`:68`)
  + pooled `THREE.Line`s named `strandBackbone<n>` (`:78`). Both pools grow 1.5× geometrically and
  never shrink (`_ensureInstanced:57`, `_ensureLines:74`).

Host loop: `renderer.update(buildStrandGeometry(params, phi).strands)` on φ/param change
(`app.js:42` — the only call site of `buildStrandGeometry` in the repo).

## Who imports this — the drop-in already happened

**Grep before you change any signature or default here.** Four external importers:

| Consumer | Imports | Coupling |
|---|---|---|
| [scene/overhang_strand_anim.js](../../frontend/src/scene/overhang_strand_anim.js) 711 LOC | `createStrandRenderer` (`:28`) | **Second implementation of the strand-list contract.** Builds `{pos,tan,bn,role:'invader'}` **by hand** at `:441` (`_displacement`) and `:599` (`_displacementStraight`) — on the *real* helix axis frame captured in `bind()` (`:100`), not the sandbox's synthetic +X/XY frame. Single-strand only. Moves authored beads via `helixCtrl.setBeadOverrides`. |
| [scene/overhang_unzip_overlay.js](../../frontend/src/scene/overhang_unzip_overlay.js) 175 LOC | `meltFraction`, `DEFAULTS as STRAND_DEFAULTS` (`:33-34`) | **`params.js` DEFAULTS is a production constant source** — `:83-84` reads `rise`, `armPull`, `meltBp`. Changing a default here changes editor animation, silently. |
| [ui/strand_anim_panel.js](../../frontend/src/ui/strand_anim_panel.js) 292 LOC | `createParamState`, `createPhiTicker` (`:11-12`) | Authoring UI for the `strand_anim_phi` keyframe track. |
| `strand-anim/app.js` | everything | the sandbox itself |

Consequences:

- **`buildStrandGeometry` is sandbox-only.** The editor consumes the *renderer* seam and
  re-implements the *model* seam. Don't assume a fix to the pure builders reaches the app.
- Any change to the `strands` element shape must be mirrored **by hand** in
  `overhang_strand_anim.js:441` and `:599`. Nothing pins the two together.
- `overhang_strand_anim.js` re-derives smoothstep inline four times (`_sstep` at `:247, :377,
  :519, :567`) instead of importing `melt.js` — so `melt.js`'s exported `smoothstep` is dead
  *and* duplicated.
- The three overhang bead sources a user sees as "strand animation" are **disjoint**:
  `binding_states` (splays real nucleotides via `setBeadOverrides`, `overhang_unzip_overlay.js:142`),
  `strand_anim_phi` (synthetic invader beads, `overhang_strand_anim.js`), and this sandbox.
  See [animation.md](animation.md) for the editor-side dispatch (`animation_player.js:1034/1054`).

## Invariants (don't regress)

1. **Geometry lies along +X in the XY plane; the helix spirals in YZ.** Straight form pins Z=0
   for every nucleotide (`geometry_straight.js:97-99`); helical puts the axis on X and the spiral
   on `(cos, sin)` of Y/Z (`geometry_helical.js:109-111`, `geometry_displacement.js:90-91`).
2. **Helix phase is anchored at the fork / binding front** (continuous), so freed strands peel up
   cleanly and the duplex "twists as pulled apart". `geometry_helical.js:77-78` (`jIdx = f*N-1`,
   `anchorAngle = (π − MINOR_GROOVE)/2`) applied at `:108` as `(i − jIdx)*twist + anchorAngle`;
   displacement equivalent `geometry_displacement.js:80`, anchored at `bIdx`. **Do not re-anchor
   at a fixed end** — that caused the periodic strand-clipping already fixed.
3. **`meltBp` blends each base bound↔free over a few bp around the front** (smooths slab
   reorientation): `melt.js:24-27`, `meltBp ≤ 0` degenerates to a hard step.
4. **Displacement φ = fraction of invader bound over all N bp.** `geometry_displacement.js:69-73`.
   The exposed ss toehold is **emergent** — the substrate loop builds all N beads unconditionally
   (`:107-112`); `t` only partitions the readout and the incumbent's length. Every `toehold`
   string in this directory is a comment or a readout — **keep it that way, don't special-case it.**
5. **Bead/slab constants are copied, not imported** — `BEAD_RADIUS 0.10`, `SLAB {length .30,
   width .06, thickness .70, distance .55}`, `HELIX_RADIUS 1.0`, sphere `(r,10,8)`, and the
   `slabQuaternion` basis all match `scene/helix_renderer.js` (`:57, :978, :45, :77, :266`) and
   `backend/core/constants.py` (`HELIX_RADIUS`, `BDNA_RISE_PER_BP 0.334`,
   `BDNA_TWIST_PER_BP_DEG 34.3`, `BDNA_MINOR_GROOVE_ANGLE_DEG 150.0`) **today**. Nothing enforces
   it. If you change a B-DNA constant anywhere, grep this directory.
6. **`ticker.js` clamps `dt` to `[0, 0.1]`** (`:58-60` — the upper bound is the tab-switch guard)
   and its boundary checks are direction-aware (`:64-69`). Note the *consequence* holds only with
   `bounce` or `loop` on: `play()` always seeds `du = +1` (`:90`), so playing from φ=1 with
   `bounce:false, loop:false` finishes instantly by design (`:73`).

## Traps — code that contradicts itself

Don't "fix" the code to match these comments; fix the comments.

- `geometry_straight.js:40-44` and `geometry_helical.js:49-53` — `@returns` both declare
  `{posA, tanA, bnA, posB, tanB, bnB, meta}`. **Both actually return `{strands:[…], meta}`**
  (`:119`, `:135`). Stale since the strand-list refactor. Only `geometry_displacement.js:33` is right.
- `geometry_helical.js:30-31` — "the ball-and-slab renderer **in app.js**". The renderer is
  `strand_renderer.js`; `app.js:36` only calls it.
- `geometry_displacement.js:8` — contract prose says "bound over … **[0, p)**"; there is no `p`
  in the file. The binding front is `b` / `bIdx` (`:70-71`).
- `ticker.js:10-11` calls `animation_player.js` "990-line" (it is **1,298**);
  `strand_renderer.js:14-15` calls `helix_renderer.js` "4k-line" (it is **5,232**).
- **Latent divergence, not yet a bug:** the model's helix radius is `R = params.W * 0.5`
  (`geometry_helical.js:58`, `geometry_displacement.js:60`) with `W` adjustable over **[0.5 … 4.0]**
  (`params.js:12`), but the renderer's slab offset uses the **hard-coded** `HELIX_RADIUS = 1.0`
  (`strand_renderer.js:98`). They agree only at the default `W = 2.0`. Any other `W` puts the
  slabs at the wrong radial offset.

## Test coverage — state it honestly

**Zero.** No `.test.js` under `frontend/src/strand-anim/`, and no vitest or e2e file anywhere in
the repo mentions `strand-anim`, `buildStrandGeometry`, `createStrandRenderer`, `meltFraction`,
or `createPhiTicker` — against 242 `.test.js` files elsewhere in `frontend/src`. The two editor
consumers (`overhang_strand_anim.js` 711, `overhang_unzip_overlay.js` 175) are also untested.
`tests/test_animation.py:289,312,321` covers the `strand_anim_phi` **API roundtrip** only — no JS.

The builders are *pure and trivially testable* (`node --input-type=module`, or plain vitest —
they import nothing) — that is an unclaimed opportunity, not existing coverage.

## Dead exports (0 importers — check before relying on them)

- `geometry_helical.js:39` re-exports `nucsPerStrand` — **0 importers**; everyone imports it from
  `geometry_straight.js:33` directly.
- `model.js:35` re-exports `nucsPerStrand` — 0 importers outside this directory.
- `melt.js:13` `smoothstep` — 0 external importers, and re-implemented inline 4× in
  `overhang_strand_anim.js` (see *Who imports this*).

## Verify

Frontend-only (no Python) → `just test-smart` decides `FAST`. There is nothing to run for this
subsystem today; if you touch a pure builder, add the vitest file. Exercise the page (scenario ×
form × play, readouts + zero console errors) — and if you touched `params.js`, `melt.js`, or
`strand_renderer.js`, **also exercise the editor's overhang strand animation**, because those
three files ship in the main app. Not part of the routine E2E suite.
