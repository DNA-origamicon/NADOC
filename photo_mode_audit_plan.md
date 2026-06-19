# Photo-mode remediation + automation-validation plan

**Source:** the 2026-06-18 photo-mode audit (this session). User symptom: intermittent,
non-repeatable **yellow/purple wash over ~80% of the viewport**, plus a sense that the
**lighting systems conflict**. No code was changed during the audit; this file is the plan.

**Scope note.** Photo mode is a *frontend-only, display-layer* subsystem
([frontend/src/scene/photo_renderer.js](frontend/src/scene/photo_renderer.js) + `photo_renderer/*`
+ [frontend/src/ui/photo_panel.js](frontend/src/ui/photo_panel.js)). It has **no REST route** — its
"automation API" is the JS controller's ~45 setters (exposed on `window.__photoRenderer`). So this
plan does *not* land in `headless_build.py`/`backend/core`; it lands in the renderer modules + a new
vitest oracle suite. The automation-features ledger entry (Part 4) flags that divergence honestly.

---

## Part 1 — Rendering remediation (fix the glitch + the lighting conflict)

Ordered by value-to-effort. R1 alone is the most likely single fix for the yellow/purple wash.

### R1 — Add tone mapping + exposure (the headline fix)
**Problem.** The renderer is created with no tone mapping ([scene.js:38](frontend/src/scene/scene.js#L38)),
so `OutputPass` runs `NoToneMapping` — HDR values just **hard-clip at 1.0**. Photo mode produces
genuinely HDR inputs (metallic env reflections; emissive fluorophores at `intensity ≤ 100 ×
_FLUORO_LIGHT_GAIN 12`). Clipped primaries + Bloom (threshold `0.85`) smear large saturated patches —
exactly "a shade of yellow or purple over 80% of the screen." No production photomode ships without
filmic tone mapping for this reason.

**Change.**
- In `activate()`, **save** `renderer.toneMapping` + `renderer.toneMappingExposure`, set
  `THREE.ACESFilmicToneMapping` (or `AgXToneMapping`), restore both in `deactivate()` (extend the
  existing saved-state pattern — `_savedToneMapping`, `_savedExposure`).
- Add a master **Exposure** setting + setter (`exposure`, `setExposure(v)` → `renderer.toneMappingExposure`),
  a slider in the panel, persisted in profiles via `getSettings()`.
- Re-evaluate the bloom threshold default now that it operates on tone-mapped range (likely raise it,
  or keep but expect far less spill).

**Files:** `photo_renderer.js` (activate/deactivate + setter), `photo_panel.js` + `index.html` (slider).
**Risk:** low. Tone mapping is scoped to photo mode and restored on exit; the live editor is untouched.
**Validates the audit:** turning Bloom off should already reduce the wash; tone mapping should remove it
even with Bloom on.

### R2 — Unify the lighting budget (the "conflicting lights")
**Problem.** Up to **four independent illumination systems** stack with no shared exposure budget:
preset rig (`_photoGroup`), independent Sun (`_sunGroup`), per-fluorophore `PointLight`s
(`_fluoroLightGroup`), and image-based lighting (`scene.environment` PMREM). Specific defects:
- **"Sun = sole light source" is not sole** — `_applyRigVisibility()` only hides the preset rig; IBL
  and fluorophore lights keep contributing. The UI implies one light; the scene has several.
- The **one-key-light shadow rule** governs only shadow *casting*, not *illumination* — fill stacks.
- **Fluorophore lights respawn** when instance count changes (animation/cluster moves), so total scene
  exposure pops frame-to-frame → intermittent brightness → feeds the R1 clip/bloom problem.
- **Dead branch:** the inscatter light-gather reads `isHemisphereLight`
  ([photo_renderer.js:419](frontend/src/scene/photo_renderer.js#L419)) but no preset creates one — the
  gather and the presets have drifted.

**Change.**
- Make Sun-mode honestly single-source: when `sun` is on, *also* gate IBL contribution
  (`scene.environment` → null or `envMapIntensity → 0`) and fluorophore PointLights, OR expose explicit
  per-contributor toggles so the user controls the sum. Decide via the AskUserQuestion below.
- Add one **IBL intensity** control (`envMapIntensity` on the swapped materials) so image-based light is
  one slider, not an uncontrolled stacked term.
- Remove the `isHemisphereLight` dead branch (or actually add a hemisphere term to the presets — pick one).
- With R1's tone mapping in place, the per-frame exposure pops from fluoro respawn become graceful
  roll-off instead of hard clipping.

**Files:** `photo_renderer.js` (`_applySun`, `_applyRigVisibility`, `_gatherLightsForInscatter`,
material swap), `lighting_presets.js`. **Risk:** medium — touches the documented Sun/shadow rules;
re-verify the one-key-light invariant after.

### R3 — Isolate the mid-session PMREM re-bake
**Problem.** `activate()` deliberately bakes the HDRI env **after** the composer is built and never
rebuilds the composer, because `PMREMGenerator` mutates renderer GL state and a composer built afterward
inherits it (the documented "bloom paints garbage colored tint" bug). **But `setEnvironment()` re-bakes
on the live renderer *after* the composer already exists**
([photo_renderer.js:357-360](frontend/src/scene/photo_renderer.js#L357)) — i.e. changing the Environment
dropdown mid-session re-enters exactly that hazardous state. The only guard is the per-frame
`resetState()`, so a transient colored garbage frame is possible on the bake. **Intermittent by
construction** → a prime suspect for "non-repeatable."

**Change (evaluate two options):**
- **(a) Mirror the activate ordering on env change:** dispose the composer → bake env → rebuild composer.
  This is the *correct* order (bake-then-construct), unlike the previously-reverted `setSSAO`/`setBloom`
  rebuild attempt (which constructed *before* re-baking). Cost: one composer rebuild per env change (rare,
  user-driven). **Recommended.**
- **(b) Bake on a throwaway renderer**, then accept that cross-context PMREM textures render black
  (documented) — so (b) is likely a dead end; (a) is the real fix.

**Files:** `photo_renderer.js` (`setEnvironment`). **Risk:** low-medium; rebuild path is already exercised
by activate.

### R4 — Reduce reliance on per-frame `resetState()` (deeper, optional)
**Problem.** `renderer.resetState()` every frame ([photo_renderer.js:1172](frontend/src/scene/photo_renderer.js#L1172))
is a band-aid for a WebGLState texture-unit desync caused by sharing **one** renderer across the raster
composer, PMREM, the `Reflector` mirror floor (which renders its own pass mid-frame via `onBeforeRender`,
[floor.js:209](frontend/src/scene/photo_renderer/floor.js#L209)), and the path-tracer `FullScreenQuad`.
`resetState()` doesn't reset all GL state and varies by driver (WSL software-GL) — hence the residual
intermittency.

**Change (only if R1–R3 don't fully resolve it):** give photo mode its **own dedicated `WebGLRenderer`**
for the preview (the codebase already does a second renderer in
[zoom_scope.js:38](frontend/src/scene/zoom_scope.js#L38)), so its GL state never collides with the live
editor's. Heavier; treat as a follow-up if needed.

### R5 — Clamp emissive / bloom energy (small hardening)
With R1 in place, optionally clamp fluorophore `emissiveIntensity × gain` to a sane ceiling, or route
emissive through a separate bloom buffer, so a maxed slider can't dominate the frame. Low priority once
tone mapping rolls off highlights.

**Decision needed before R2/R3 implementation** — see the question at the end.

---

## Part 2 — Automation & validation harness (the AF-style item)

### The gap
[photo_renderer.js](frontend/src/scene/photo_renderer.js) — 1588 lines, ~45 setters — has **zero test
coverage**. Only the thin `photo_mode.js` overlay wrapper is tested (`photo_mode.test.js`, via mocks).
There is **no automated proof that any photomode option actually takes effect**, and no proof that every
option is reachable + persisted programmatically. That is the exact failure the design-automation loop
exists to close — applied to a frontend subsystem.

### The anti-shovel principle (read the object, not the intent)
`getSettings()` only echoes the stored `_settings` object — asserting `getSettings().bloom === true` is a
**passthrough** that proves nothing reached the GPU-facing object. Every oracle here must read the **real
Three.js state** the setter is supposed to drive (a light in the scene graph, a `material.metalness`, a
`pass.enabled`, a `camera.fov`). That is the "validation gained, not a passthrough" deliverable.

### Feasibility (the enabling discovery)
Nearly every setter's effect is observable **without a GPU**: `createPhotoRenderer` can be constructed in
jsdom with a real `THREE.Scene` + `PerspectiveCamera` and a lightweight fake `renderer`, then
`activate({ environment: 'off' })` (so no PMREM bake). The `EffectComposer` and its passes **construct**
fine in jsdom (only `.render()` and PMREM baking touch GL), so `bloomPass.enabled` / `ssaoPass.enabled` /
inscatter uniforms are all assertable too. Only actual pixel output, PMREM-bake results, and the
tone-mapped *look* need real WebGL.

### Tier P-A — per-setter effect oracles (vitest, no GL) — the bulk
A new `photo_renderer.test.js` with a shared harness `makePhotoRenderer()` (real scene/camera + fake
renderer + a few seeded meshes named `backboneSpheres`, `dna-surface`, an atomistic mesh, an
`extensionFluorophores` instanced mesh). Then a **table-driven** test: drive each setter, assert the
observable. See Part 3 for the full table. This is the reusable augment; it can go red if a setter updates
`_settings` but forgets to call its `_apply*`.

### Tier P-B — the automation contract (vitest)
Two oracles that directly answer "ensure **all** photomode options can be set through API/automation":
1. **Completeness / no-orphans:** every key in `getSettings()` has a setter that writes it, and every
   setter's key appears in `getSettings()` (so it persists in a profile). Catches an option that's
   settable-but-not-saved or saved-but-unsettable.
2. **Profile round-trip:** snapshot `getSettings()` → drive every setter to a non-default value →
   `getSettings()` reflects them → re-apply the snapshot through the panel's `_applyProfile` path →
   `getSettings()` deep-equals the snapshot. Documents the two known exceptions (`environment:'file'`→`off`,
   path-tracing rebuild). This proves the *whole* option surface is programmatically reachable in one shot.

### Tier P-C — GPU-truth (Playwright, troubleshooting-only → manual-validation debt)
The handful that need real WebGL2 — and the **regression guard for the actual bug**:
- `setEnvironment('room')` bakes a non-null `scene.environment` texture.
- `setBloom(true)` / `setSSAO(true)` / mist visibly change rendered pixels.
- **No-tint regression:** render the worst-case stack (HDRI Room + Bloom + metallic + maxed fluorophore
  emissive), sample the frame, assert no large uniform saturated region (the yellow/purple wash) and a
  non-black opaque image. This is the e2e that pins R1–R3.
- **Mid-session env-change guard:** enter → `setEnvironment` a few times under Bloom → assert no garbage
  frame (pins R3).

Per CLAUDE.md, Playwright is **not** routine — these ship as `MV-N` manual-validation-debt rows + one
opt-in e2e spec, not as a default "done" gate.

---

## Part 3 — Concrete per-setter validation catalogue (Tier P-A unless noted)

| Setter | Observable oracle (the real object) | Tier |
|---|---|---|
| `setLighting(preset)` | `_photoGroup` children: 1 `AmbientLight` (color/intensity == preset) + N `DirectionalLight` == preset.lights | P-A |
| `setLightingDirection(yaw,pitch)` | `_photoGroup.rotation` == expected Euler (YXZ) | P-A |
| `setMaterialPreset(repr,preset)` | matching meshes' `material.metalness/roughness/clearcoat` == preset params | P-A |
| `setTranslucency(amt)` | full/cylinders `material.transmission` == amt; surface untouched | P-A |
| `setFluorophoreEmissive(on,i)` | fluoro mesh `material.emissiveIntensity` == i; `_fluoroLightGroup` PointLight count == fluoro count | P-A |
| `setFluorophoreIntensity(i)` | each PointLight `.intensity` == i × gain | P-A |
| `setSun(on)` | `_sunGroup` has a DirectionalLight; `_photoGroup.visible` == !on | P-A |
| `setSunAzimuth/Elevation` | sun DirectionalLight direction matches polar→cartesian on floor normal | P-A |
| `setSunStrength/Color` | sun light `.intensity` / `.color` | P-A |
| `setFloor(axis)` | floor mesh present, positioned on the named bbox face | P-A |
| `setFloorMaterial(name)` | floor `material`/object type (PBR vs `Reflector` vs `ShadowMaterial`) | P-A |
| `setFloorColor/Opacity/Offset/Grid*` | corresponding floor material/grid property | P-A |
| `setFloorShadows(on)` | with floor on, exactly one (or zero) shadow-casting DirectionalLight (one-key rule) | P-A |
| `setBackground(type,color)` | `scene.background` (null/Color) + saved clear params | P-A |
| `setFOV(fov)` | `camera.fov` == fov; projection updated | P-A |
| `setSSAO(on)` | `composer.ssaoPass.enabled` == on | P-A |
| `setBloom(on,s,r,t)` | `composer.bloomPass.enabled` + strength/radius/threshold uniforms | P-A |
| `setEnvironmentalEffect('mist')` | `inscatterPass.enabled` == true | P-A |
| `setMistDensity/Color/HaloIntensity/Noise` | inscatter pass uniforms | P-A |
| `setExposure(v)` *(new, R1)* | `renderer.toneMappingExposure` == v | P-A |
| `setEnvironment('room'/'file')` | `scene.environment` is a non-null Texture (needs PMREM bake) | **P-C** |
| `setEnvironmentBackground(on)` | `scene.background` swaps to env texture when on | **P-C** |
| `enablePathTracing()` | render fn swapped; PT renderer built | **P-C** |

---

## Part 4 — Ledger entries (the requested ledger additions)

**Backlog (`design_automation_backlog.md`):** add a new item — **AF-PHOTO** — under a short
"Frontend display subsystems" note, since it diverges from the backend headless shape. Text proposed
below (Part 5). It is *intake*, not a shipped session, so **no `design_automation_log.md` metrics row
yet** (those are added when a phase ships).

**Manual-validation debt (`manual_validation_debt.md`):** push `MV-PHOTO-1` (no-tint regression render)
and `MV-PHOTO-2` (mid-session env-change garbage-frame guard) as GPU-truth checks that can only be
hand/e2e-validated.

---

## Part 5 — Proposed AF-PHOTO backlog item (verbatim, for the ledger)

> **AF-PHOTO — photomode option-coverage + effect oracles (frontend display subsystem).** Photo mode has
> ~45 controller setters (`window.__photoRenderer`, the de-facto automation API — no REST route) and
> **zero test coverage** of [photo_renderer.js](frontend/src/scene/photo_renderer.js). Diverges from the
> backend headless shape: the augment is a **vitest oracle suite reading real Three.js state**, not a
> `headless_build` wrapper. **Phases:** (P-A) table-driven per-setter effect oracles — assert the setter
> drove the *object* (scene-graph light / `material.metalness` / `pass.enabled` / `camera.fov`), NOT
> `getSettings()` (the passthrough trap). (P-B) automation-contract oracles — setter⇄getSettings
> completeness + full profile round-trip (proves every option is reachable + persisted programmatically).
> (P-C, MV-debt) GPU-truth e2e incl. the **yellow/purple no-tint regression** guarding the R1–R3 render
> fixes. **Validation gained, not a passthrough:** first automated proof that photomode options take
> effect on the GPU-facing objects + that the full option surface round-trips. **Bound by
> `FEATURE_DEVELOPMENT.md`:** lands in `photo_renderer.js` + new `photo_renderer.test.js`, never a god-file.

---

## Recommended sequencing
1. **R1 (tone mapping + exposure)** — highest probability of killing the wash; cheap; low risk.
2. **P-A + P-B vitest oracles** — they pin R1 *and* give the whole subsystem its first safety net before
   touching the trickier lighting/PMREM code.
3. **R3 (env re-bake isolation)** then **R2 (lighting budget)** — both behind the new test net.
4. **P-C / MV rows** — the GPU regression guard, once R1–R3 land.
5. **R4/R5** — only if intermittency survives R1–R3.

## Resolved decision (user, 2026-06-18)
**Sun = truly sole (option a).** When the Sun is toggled on, image-based environment lighting
(`scene.environment` → null) AND fluorophore point-lights are both auto-disabled, so the sun is the only
thing illuminating the geometry. Implemented in R2 (`_applyEnvToScene` gates IBL on `_settings.sun`;
`_spawnFluoroLights`/`_syncFluoroLights` skip while sun is on; `_applyRigVisibility` hides the preset rig).
Consequence (expected): a metallic rep under sun-only reads dark — metals need an environment to reflect.

---

## Implementation status (2026-06-18)
**SHIPPED this session:** R1 (tone mapping + exposure: filmic ACES in `activate`, restored in `deactivate`,
`setExposure` + panel slider, propagated to both export renderers), R2 (Sun-sole per the decision above),
R3 (one-shot `resetState()` after the mid-session PMREM re-bake — a composer *rebuild* was rejected because
the codebase's own history shows it reintroduces the documented bloom-tint bug). New diagnostic
`getComposerState()` reads real pass state. **Validation:** `frontend/src/scene/photo_renderer.test.js` —
39 oracles (P-A per-setter effect + P-B automation contract), full frontend suite green (1410 tests).
`MV-PHOTO-1`/`MV-PHOTO-2` pushed for the GPU-pixel checks.

**Also shipped (2026-06-18, follow-up):**
- **R5 — emissive bloom-blowout clamp.** `FLUORO_EMISSIVE_MAX = 25` in `material_presets.js` caps the
  fluorophore *self-emission* that feeds `UnrealBloomPass` (which runs pre-tone-map, so filmic roll-off
  alone can't tame it). The per-fluorophore *PointLight* keeps its full 0–100 range (the user-requested
  reflection strength) — only the bloom-feeding term is bounded. Pinned in `photo_renderer.test.js`.
- **R4 — targeted isolation (NOT the dedicated renderer).** The original R4 ("own renderer so it can't
  collide with the live editor") was rejected: photo mode swaps the render *function*, so it never renders
  concurrently with the live editor — the desync is *internal* (PMREM + bloom + Reflector + PT quad on one
  renderer), which a second renderer wouldn't fix. Instead, the prime remaining internal offender — the
  `Reflector` mirror floor's nested mid-frame render — is now isolated: `floor.js` wraps its
  `onBeforeRender` to flush `renderer.resetState()` right after the reflection render, so its GL-state
  churn can't bleed into the rest of the composer frame. Pinned in `floor.test.js`.

**Deferred / not pursued:** the full dedicated-renderer R4 (premise doesn't hold — see above); P-C e2e
(optional, troubleshooting-only). **NOT VERIFIED IN APP** — the render fixes are pixel/GPU effects; jsdom
has no WebGL, so the actual disappearance of the wash is the `MV-PHOTO-1`/`MV-PHOTO-2` hand-checks.
