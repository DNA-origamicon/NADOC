# Surface capture strands (oxDNA immobilization) — plan + status — supporting detail

[Topic head](../../project_surface_strands.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

**Setup card froze on open — FIXED 2026-08-18.** The card became inert: enabling strands drew one
preview, then every later edit (density/size/shape/seed/offset) changed nothing in the 3D and the
status line stopped updating.
- ROOT CAUSE: the 2026-08-08 coordinate unification (`4c332526` "remove legacy slab positioning",
  `8d3d1020`) made `nuc.base_position` MANDATORY in the slab builder. The old
  `slabCenter(bbPos, bnDir, distance, basePosition = null)` accepted null and fell back to a fixed
  radial offset; `pairedSlabCenter` spreads it unconditionally. `captureNucleotidesFromChains` never
  emitted `base_position`, so every injected cap nucleotide threw
  `TypeError: nuc.base_position is not iterable` out of `buildHelixObjects`.
- WHY IT LOOKED LIKE A FREEZE (the interesting part): that throw unwound through
  `setExtraNucleotides → onStrands → _draw → overlay.setHighlight → _refreshStrandsOverlay →
  onChange() → _render`. `setHighlight` runs BEFORE `update()` in `_refreshStrandsOverlay`, so
  `_lastSpec` was never replaced — the overlay re-rendered the FIRST spec forever and re-threw, and
  `_render` aborted before its own `_setStatus`. Nothing downstream of the first line of `_render`
  ever ran again.
- FIXES: (a) `captureNucleotidesFromChains` emits `base_position = backbone + BASE_DISPLACEMENT_NM
  (0.3) × base_normal`, matching `backend/core/geometry.py`; (b) the slab loop skips a nucleotide with
  no `base_position` instead of throwing (bead yes, slab no); (c) `_render` wraps `onChange` in
  try/catch so a renderer failure can never freeze the card again; (d) `createSurfaceStrandEmitter`
  takes a content `key` — preview chains are a fresh array per `_draw`, so identity always missed and
  ONE card edit cost THREE full design rebuilds (setHighlight + setShapePreview + update); the key
  includes the requested colour because `main`'s `onStrands` re-reads `getColor()` at emit time;
  (e) 90 ms debounce on typed/dragged inputs (discrete toggles stay immediate) so typing "3000" is
  one rebuild, not four.
- VERIFIED: `frontend/e2e/surface_strands_setup.spec.js` (new) drives the real card in a browser and
  asserts density/size/shape/sequence-length/seed/offset/colour/highlight each change the RENDERED
  inventory, `capSlabAxis == surface normal`, and a clean console. 5749 vitest green.
- **Lesson for anyone injecting synthetic nucleotides:** `setExtraNucleotides` bypasses the backend
  nucleotide contract, so a new mandatory field in `helix_renderer` breaks it SILENTLY at the type
  level and LOUDLY at runtime. `backbone_position`, `base_position`, `base_normal`, `axis_tangent`
  are all required.

**Display bug fixed 2026-08-01 (tech-debt TD-05).** The "Highlight strands" toggle's white halo
did **not** follow the capture strands during a sim overlay. `design_renderer.refreshAllGlow()` —
called on every `applyFemPositions` frame — refreshed 6 of its 7 glow layers and omitted
`_captureGlowLayer`, so the halos stayed at the build positions while the strands moved to the
oxDNA frame, until the next full rebuild. One line; pinned by `scene/design_renderer.test.js`,
which asserts the created- and refreshed-layer lists agree. **Not re-verified in-app** — needs a
design with capture strands + a live oxDNA job; worth an eyeball next time one is running.

**Audit note (2026-07-25):** codebase probe confirmed anchors 1–9 EXISTS+WIRED. The
"topology build DEFERRED to Phase 2" framing in older indexes is **STALE** — Phase 2a–2d all shipped.
Doc-path nit: `prepare_oxdna_job` lives in `backend/core/oxdna_runner.py` (not `backend/physics/`).

**Goal.** Simulate immobilization of a DNA origami on a functionalized surface: the hard
surface (repulsion plane) carries a random dispersion of ssDNA **capture strands**
complementary to the origami's overhangs. The origami's overhangs hybridize to these,
tethering it to the surface. An optional E-field drifts the origami toward the surface so
compute isn't wasted waiting for first contact — with a toggle to **exclude** the capture
strands from that field (else a downward drift field presses them flat against the plane).

**Scope guard.** oxDNA engine ONLY. Under the existing "Hard surface" card.

**Three-Layer note.** Capture strands are new *topological* entities (real oxDNA strands
the origami must be able to bond to). They are NOT a display overlay and NOT a
production-only force. They change the built topology → change the design fingerprint →
require the system they live in to be present from the build/relax stage, not bolted onto
a relaxed origami-only structure. This is the crux of Phase 2.

---

## Phases

### Phase 1 — UI + pure placement math + plumbing (DONE, decision-free)
Frontend-only, no topology decisions, no backend. Everything here is either display wiring
or pure deterministic math with unit tests.

- **Pure math** `frontend/src/scene/surface_strands_math.js` (+ `.test.js`):
  - `mulberry32(seed)` — deterministic PRNG, chosen to be trivially re-implementable in
    Python so a seed reproduces the *same* dispersion in the eventual backend generator.
  - `surfaceStrandArea`, `surfaceStrandCount` (density/µm² × area → N), `surfaceStrandPlacements`
    (seeded in-plane (u,v) points; area-uniform for circle, uniform for square, centred on
    the X/Y offset), `surfaceStrandsSpec` (normalize raw UI fields → clean spec + count).
- **UI card** `frontend/src/ui/oxdna_surface_strands_setup.js` (factory
  `initOxdnaSurfaceStrandsSetup({onChange, ids}) → {getStrandsSpec, isEnabled, applyConfig, refresh}`)
  mounted in the Hard-surface card body (`index.html`, inside `#oxdna-floor-body`). Fields:
  sequence, attach end (5′/3′), density (/µm²), shape (circle/square), radius|side (nm),
  X/Y offset (nm), seed, and the **"Subject surface strands to the E-field"** toggle. Live
  preview shows the resulting strand count.
- **Wiring** `main.js`: import + one-line factory init + `surfaceStrands` added to
  `_oxdnaRunElements()` and echoed in `_oxdnaApplyConfig()`. The spec is carried but NOT yet
  injected into the submit payload — the production/relax payload builders in
  `oxdna_jobs_panel.js` still read only `dir/offsetNm/stiff` from `surface`, so nothing about
  job submission changes yet.

### Phase 2 — DNA-topology + geometry decisions (ANSWERED 2026-07-17)
The "ask first" questions, now resolved by the user (JJ):

1. **Build, not overlay.** ✅ Capture strands are baked into the built system and present
   through relaxation — a dedicated immobilization build. NOT a production-time force on a
   relaxed origami-only `.dat`.
2. **Geometry = ssDNA coil.** ✅ Random-walk coil (not a rigid standing rod). Seed backbone
   spacing inside the FENE-safe window (0.506–1.006 units, r0=0.7564); `SSDNA_CONTOUR_PER_NT
   = 0.68 nm`. Reuse the strand-extensions anchor-outward frame solve, anchored at the
   attach-end backbone site and coiling outward.
3. **Tether = C-C-covalent-stiff trap.** ✅ One `trap` per strand at its attach-end backbone
   site, stiffness ≈ a covalent C-C bond (~400 N/m). Converts to **≈ 7000 oxDNA stiff
   units** (stiff unit = ε/σ² = 48.63 pN / 0.8518 nm ≈ 57.1 pN/nm; 400 N/m = 4e5 pN/nm →
   ~7005). ~7× `DEFAULT_ANCHOR_STIFF`. Verify MD stability (`dt·√stiff` vs the RATTLE/FENE
   budget) — may need the smaller production `dt`. Absolute coords → **`fix_diffusion=false`**.
4. **Sequence = verbatim + a "Gen" button.** ✅ Take the entered sequence 5′→3′ verbatim.
   ALSO add a **Gen** button that designs a sequence via the **Johnson et al. algorithm**.
   ⚠ OPEN: need the reference / spec for that algorithm before building Gen (see Open items).
5. **E-field exclusion — worth it, but LAST.** ✅ Ship field-on-ALL first (capture strands
   feel the field); implement the per-particle exclusion (origami-only `string` blocks) as
   the final phase so field-on-all is testable meanwhile. The UI toggle already exists and
   defaults on; wire its `false` branch last.
6. **Placement = 2 nm min spacing, no origami avoidance.** ✅ 2 nm min centre-to-centre baked
   into placement (`MIN_SPACING_NM`, rejection sampling — DONE in Phase 1 math). Do NOT
   exclude the origami footprint. Default coverage diameter/width **100 nm**
   (`DEFAULT_COVERAGE_NM`, HTML default — DONE).
7. **Synthetic key + filter audit.** New capture-strand nucleotides need a `__`-prefixed key
   and an audit of every `isinstance(k[1], int)` / `__`-guard filter (`oxdna_health`,
   `atomistic_to_nadoc`, `*_shape_source`, `skip_twist`). Add the field to
   `oxdna_design_fingerprint`.
8. **Viz.** 3D overlay of the coverage patch + placed strands (anchor-glow `_anchorsByEngine`
   pattern; placement points already available from the Phase 1 math).

**Seed-geometry decision (2026-07-17, user):**
- **B-form geometry** for the standing capture strand (reuse NADOC's B-DNA helical frames —
  the locked `_PHASE_*` convention — NOT a hand-rolled straight ssDNA rod). B-DNA backbone-to-
  backbone spacing ≈ 0.68 nm → FENE-safe, consistent with the origami build.
- **Clash → WARN, never block.** Compute min capture-bead↔origami-bead distance; surface a
  non-blocking warning (like the field-anchor warn-only policy). Do NOT auto-raise clearance.
- **Absolute surface placement, trust the user.** Strands attach at the user's absolute surface
  position; the user is responsible for setting the surface offset so there's no t=0 clash.
  (Ties into the "surface position is absolute across simulations" work — `position_nm`.)

**Phase ordering going forward:** (2a) revise builder to B-form frames + clash warning; wire
into `prepare_oxdna_job` (relax build) so strands are present through relax + C-C-stiff attach-
end traps + `fix_diffusion=false`; thread `surface_strands` through the relax/RunRequest payload
+ persist in `run_config`; pytest coverage. (2b) 3D viz overlay. (2c — LAST) E-field exclusion
toggle → per-particle origami-only field blocks. (2d — DONE) the "Gen" sequence button.
