# Phase 2 — DNA-topology + geometry decisions (ANSWERED 2026-07-17) — supporting detail

[Topic head](../../project_surface_strands.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

**Native render integration — CG reps (2026-07-17, user: "full integration into renders"):**
Capture strands now render in the actual representation system (beads/slab/cylinders/hull), not a
separate overlay. Mechanism: overlay emits world-nm bead chains (`onStrands`) → `main` converts via
`captureNucleotidesFromChains` (surface_strands_math) → `designRenderer.setExtraNucleotides(nucs, color)`
merges them into the geometry `_rebuild` consumes + colours them (cyan `_eff[strand_id]`). Synthetic
`cap<i>` helix/strand ids (no `__` → unfiltered), unique bp_index ≥ 1e6 (no slab collision), FORWARD-only.
Overlay keeps ONLY the coverage patch + centre gizmo; highlight→emit chains or []; colour→patch tint +
strand `_eff`. `displayJob` reordered: `onSurfaceStrands` (rebuild) BEFORE `_applyFem` (in-place origami
move) so the rebuild doesn't clobber the FEM overlay. 26 math + 3016 frontend tests green; injection path
error-free on enable/highlight/colour.
**VERIFIED IN APP (2026-07-17, Playwright + loaded design):** strands render as real beads+slabs in
the CG reps (capBeads==extraNucs), selection works (filters apply). FIXES from user feedback:
- **Colour was black** — `_eff[strand_id]` needs an INT but I passed a `'#hex'` string → `setHex`
  rendered black. `setExtraNucleotides` now `parseInt`s it. Verified colour changes apply to the beads.
- **Slabs oriented wrong** — my crude a1/a3 (chain tangent) → the overlay now emits proper B-form frames
  (a3 = surface normal = helix axis; a1 = inward radial = backbone→base). `captureNucleotidesFromChains`
  uses supplied `{p,a1,a3}` (results fall back to chain-tangent). Verified capSlabAxis == surface normal.
- **Highlight toggle** works (emit chains / []; capBeads 568→0→568).
- **Colour control** = hex text box + wheel, synced both ways (`oxdna-surfstrand-color-hex`); wheel is
  canonical. Selection of cap beads works per selection filters (user confirmed).
- Debug hook `designRenderer.debugCaptureRender()` + DEV `window.__nadocDR` (used for validation).
  Gotcha: caps only render when a DESIGN is OPEN in the editor (currentGeometry non-empty) — the file
  browser landing page has no geometry, so `capBeads==0` there is expected, not a bug.
**Heavy reps (surface, vdw/ballstick) STILL NOT covered** — backend meshes (`/design/surface`,
`/design/atomistic` + oxDNA job reconstruction) must emit capture strands (next, larger piece).

**Flexibility-map + trajectory CG integration fix (2026-07-18):** those two display modes
previously applied only their design-keyed origami positions and never performed relaxed display's
`surface_strands` mode switch. Entering either mode directly from setup therefore left the B-form
seed preview injected as native `cap<i>` nucleotides; its rebuild also reset the origami before the
physical frame was applied, producing displaced caps and apparent false connectors. Both modes now
fetch/cache the job's real `/display.surface_strands`, inject them **before** the first FEM-position
update (the same ordering invariant as relaxed display), and reuse them across trajectory scrubs and
map re-toggles. Explicit Refresh invalidates the strand cache so a running job's latest caps are read,
and preserves the mode's current alignment setting. Focused Vitest regressions assert strands-before-
positions ordering and no per-scrub/ref-toggle refetch.

**Result selection/duplicate-glow follow-up (2026-07-18):** the setup card's checked-by-default
“Highlight strands” emphasis was also applied to real simulation results. Its separate glow geometry
made every cap look selected and like a second coincident strand; clicking through that emphasis could
select/highlight the scaffold beneath. Results mode now renders exactly the native cap geometry with no
setup glow (ordinary click selection remains available); preview mode retains the checkbox behavior.
Injected cap nucleotides also carry explicit `strand_type: surface_capture` / `is_surface_capture`
metadata, and the crossover-arc collector defensively rejects them because appended capture chains have
no design-topology crossover or ligation to the origami.

**Run-6 renderer audit + RMSF rebuild root cause (2026-07-18):** added a live Three.js audit
(`window.__nadocDR.debugRenderedAudit(2)`, pure core in `scene/render_bond_audit.js`) that inventories
beads/slabs/connectors, reads current instance positions/colors, and reports every rendered connector
over a threshold with both endpoint identities. The exact `VoltronCoreScad.nadoc` Run 6 job is
`fa9473f11b05`. Evidence: relaxed result = 15,984 beads (948 caps), 15,699 bonds (869 cap bonds), zero
bonds >2 nm, max 1.939 nm. The broken post-RMSF state had 0 caps, 0 FEM updates, 0 scaffold beads
changed from default color, and one unrelated 3.936 nm scaffold crossover (`sc_strand_205`,
`h_sc_49:64:REVERSE` → `h_sc_48:65:FORWARD`). Root cause: `surface_strands_overlay._draw` re-emitted
the same results into `setExtraNucleotides` on later plane/card/highlight redraws; that full rebuild
wiped already-applied RMSF positions/colors. Result-chain emission is now identity-idempotent, pinned by
`surface_strands_overlay.test.js`; actual chain/highlight changes still rebuild.

**Run-6 actual-cone follow-up (2026-07-18):** the user screenshot proved the endpoint-only audit had
missed drawn cone transforms. `debugRenderedAudit` now decomposes every live cone instance matrix and
measures its Y scale (the actual rendered length), reporting matrix length, logical endpoint length,
delta, and endpoint origins. Screenshot diagnosis: the cyan islands were misindexed scaffold segments,
not duplicate capture strands; their normal scaffold bonds became the giant dark cones. Cause was the
production reader's 948-particle shift described above. Exact clean RMSF audit on
`VoltronCoreScad.nadoc`, Run 6 `fa9473f11b05`: 15,984 beads, 15,699 cones, 948 capture beads, 869 capture
cones, 0 capture cross-cones, 16,168 FEM updates, 7,249 RMSF-coloured scaffold beads, and **0 rendered
cones >2 nm** (maximum actual matrix length 1.684847 nm). The Playwright assertion passed on all counts.

**Capture dynamics integration (2026-07-18):** trailing capture particles are no longer merely
excluded from origami parsing. When a job supplies the sequence length, configuration and trajectory
readers expose every appended particle under the renderer's existing stable synthetic identity
(`cap<i>`, high bp index). RMSF accumulation therefore includes their average positions/orientations
and RMSF scalars; composite trajectory keys/frames include them too. The ordinary FEM/scalar renderer
paths consequently move beads, slabs, and cones and recolour them without a second overlay or rebuild.
The trajectory design seed takes capture coordinates from raw frame 0 (never zero placeholders).
Exact Run 6 evidence: RMSF payload 17,116 positions = 16,168 design + 948 capture; capture RMSF range
0.3984–3.6525 nm (mean 1.8939); live scene reports all 948 capture beads scalar-coloured and 0 cones
over 2 nm. A four-frame exact composite sample moved `cap0:1000000` by 0.3687 nm first→last.

**Bbox feedback-loop fix (2026-07-17):** native injection put cap beads into `getBackboneEntries()`,
and BOTH `main._oxdnaStructureBounds` (patch centre) and `view_tool_buttons._designBBox` (surface grid)
built the design bbox from ALL entries → the strands fed their own placement frame. Symptoms: changing
sequence/seed/colour moved the coverage patch; the gizmo moved it randomly (its `_baseCenter` reference
jumped each rebuild). FIX: both bbox loops now exclude `strand_id.startsWith('cap')`. Verified: patch
centre stable across seq 4→16→2 nt; offset mapping round-trips; gizmo reference stable. When ANY code
consumes `getBackboneEntries()` for a design-extent/measurement purpose, it must exclude `cap<i>`.

**Display box-shift clip artifact (diagnosed 2026-07-17, run killed):** an UN-anchored origami in a
surface relax (`fix_diffusion=false`, only capture strands trap-pinned) diffuses freely; on the killed
run it drifted ≈180 nm ≈ one box length. The align=False PBC box-shift (`unwrap_align_to_reference`
snapping to the nearest reference image) then wrapped it by one box vector → rendered it straddling the
plane (false "clipping"; 0 beads physically on the forbidden side). ROOT = the drift. FIX (proposed, not
yet built): auto-anchor the origami (light COM/tether) when a hard surface is enabled for a relax, so it
can't diffuse a box away; the production E-field does the real drive-down. Also revisit box size.

**Display controls DONE (2026-07-17):** card has **Highlight strands** (bead/chain visibility),
**Coverage shape** (patch visibility; centre gizmo tied to it), and a **Colour** picker defaulting to
**cyan #00ffff** (applied to beads+chains+patch). Defaults ON when the options are first enabled
(setup); OFF when a job entry is selected (`applyConfig` unchecks both — toggle on to emphasise for
figures). Overlay: `setHighlight/setShapePreview/setColor`, independent per-mesh visibility in `_draw`
(patch shown in results too, overlaying the coverage area on real strands). Wired via
`main._refreshStrandsOverlay`. NOTE: strands render as the BEAD rep (spheres + backbone lines);
matching the structure's slab/surface/atomistic reps for strands is a FUTURE enhancement.
2. **2b — pre-run 3D viz overlay** of the coverage patch + placed strands (placement points already
   available from `surface_strands_math.surfaceStrandPlacements`; follow anchor-glow pattern).
3. **2c (LAST) — E-field exclusion toggle** → per-particle origami-only `string` blocks (the
   `subjectToField=false` branch); UI toggle already wired + persisted.

### Phase 3 — backend generation + tests (after Phase 2 answers)
Inject strands into the topology/config walk, compose the tether anchors into the forces
file, wire the payload + fingerprint, pytest scratch-session coverage. Verify only via
pytest (never mutate the live server).

---
