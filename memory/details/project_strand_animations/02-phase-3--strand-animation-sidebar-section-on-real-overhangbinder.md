# Phase 3 — "Strand Animation" sidebar section on REAL overhang+binder (2026-05-29) — supporting detail

[Topic head](../../project_strand_animations.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Phase 3 — "Strand Animation" sidebar section on REAL overhang+binder (2026-05-29)
Drives the actual rendered overhang + binder beads (user chose "drive real beads", NOT a
synthetic overlay; Unzip only; in-context). NOTE: the user REJECTED the sandbox's symmetric
peel — the motion is a custom **radial decomposition about the real helix axis**, NOT the
sandbox `buildStrandGeometry`. Only `createParamState`, `createPhiTicker`, `melt.meltFraction`
are reused from the sandbox.

**Motion (user-confirmed, refined 2026-05-29):**
- Unzips from the ROOT side: fork travels root(i=0) → tip(i=M−1) as φ:1→0.
  `forkPos = (1−φ)·(M+meltBp) − meltBp/2`; `w_i = smoothstep((forkPos−i)/meltBp + 0.5)` →
  fully paired (w=0 ∀i) at φ=1 (authored, jump-free), fully freed (w=1) at φ=0. Freed = behind
  the fork (root side).
- STILL-PAIRED remainder ROTATES about the axis as the helix unwinds:
  `dTheta = −unwindScale · freedCount · twist` (twist = mean authored azimuthal step / bp;
  `freedCount = clamp(forkPos,0,M)`; `unwindScale` slider default 1, range −2..2). Applied to
  paired beads of BOTH strands (rigid rotation → duplex stays intact, spins).
- Freed part settles at a FIXED angle (does NOT track the rotating fork). Freed OVERHANG bead
  azimuth → `thetaRoot` (straight line at radius R). Freed BINDER = a straight ssDNA ARM (like
  the sandbox): emanates from the fork point (axis@forkPos + R·`bref`, `bref` = radial unit at
  the binder root azimuth) leaning −cos(θ)·Adir (toward root) + sin(θ)·bref (outward), normalized;
  bead at arc-length `(forkPos−i)·armStep` along it (`armStep = meanRise·armPull`). Splay angle
  `thetaDeg` (0=axial, 85=radial) + `armPull` (ssDNA stretch) controls. Blend authored+dTheta
  (paired) → arm (freed) by w_i (position lerp). [Replaced the earlier per-bead radial drift.]
- Slabs: paired-region slabs of BOTH strands rotate by dTheta (authored base_normal cached in
  the U,V,Adir frame → rotate the U,V part), tracking the unwinding duplex. Freed OVERHANG slabs
  → inward −rhat (toward axis). Freed BINDER slabs → toward the helix AXIS (`_inwardAxis` at the
  freed arm position, blended from the paired orientation by w) so all unzipped binder slabs face
  the axis. (Superseded an earlier "90° from arm `perpDir`" version — now removed.) Jump-free at φ=1.
- forkPos has a −0.5 margin so φ=1 is fully paired even at meltBp=0 (hard step). Cones follow
  (setBeadOverrides recompose). Verified headless: freed binder slabs uniform (dot 1.0) + ⟂ arm
  (dot 0.0); jump-free pos+normal at meltBp∈{0,1.5}.

**Driver** `frontend/src/scene/overhang_strand_anim.js`: `initOverhangStrandAnim({getHelixCtrl,
getGeometry, getDesign})` → `{bind(ovhgId,binderId), setPhi(phi,params), getFrame, isBound,
clear, dispose}` + `findBinderStrand(design,ovhgId)`.
- Helix axis from `design.helices[ohHelix].axis_start/axis_end` (fallback: overhang root→tip,
  then `axis_tangent`). Perp frame (U,V)⟂Adir for azimuth. CAVEAT: straight-axis assumption —
  a deformed/bent overhang helix would mis-decompose (overhangs are usually short/straight).
- Per bead: decompose backbone → (axisPt, R, θ). Pairing by bp_index (binder partner = same bp,
  opposite direction). Root at i=0 (reverse if tip — `is_five/three_prime` terminus — is at low
  bp). `setPhi` reconstructs pos = axisPt + R·(cosθ·U + sinθ·V); at w=0 = authored exactly.
- Restore via `_movedKeys`/`_authoredUpdate`. Reuses `helixCtrl.setBeadOverrides`
  (helix_renderer.js ~2830).

**Binder arm direction** is `−cos(splay)·Adir + sin(splay)·bref`, where `bref` is the radial
unit at azimuth `bnRootTheta + exitAngleDeg` — so **Splay angle** (lean from axis) AND **Exit
angle** (azimuthal departure direction around the axis) are both adjustable. `bref` is computed
per-frame in setPhi from `bnRootTheta` (cached) + the exit param.

**Panel** `frontend/src/ui/strand_anim_panel.js`: `initStrandAnimPanel(store,{getHelixCtrl,
getGeometry,getDesign})`, init in main.js before `clusterGizmo`. Section `#strand-anim-panel`
(index.html, after `#overhang-panel`). Controls: **Overhang dropdown** (top), φ slider +
Play/Reset, direction, speed, easing, loop, bounce, Melt width, **Splay angle**, **Exit angle**,
**ssDNA stretch** (armPull), Unwind; read-only N + Radius R. Sandbox shape controls
(form/twist/W/forkToCenter) DROPPED.
- **Persistent overhang dropdown** (`_ovhgSelect`, NOT in the grayed `_inputs` — always usable):
  populated with overhangs that have a binder (`findBinderStrand`); `_activeId` = its value is
  the source of truth for what's animated. `_bind(id)` stops ticker + `driver.bind` + ungrays.
  Store subscription AUTOFILLS the dropdown when a NEW binder-overhang is selected (3D/list), but
  is STICKY — clicking away (null / non-binder selection) leaves `_activeId` + dropdown unchanged.
  Rebuilds options on design change (preserves valid selection); rebinds on geometry change.
- Selection sources: 3D click (`multiSelectedOverhangIds`) OR overhang-list row click (guarded vs
  input/button). `#overhang-list` is a fixed-size scrollable box (max-height 240px).

**Different lengths (2026-05-29):** `bind` no longer requires `binder.length === M`. Overhang
beads (M) and binder beads (Mb) are decomposed separately; `bnToOh[bk]` maps each binder bead to
its overhang index by bp_index (−1 = unpaired). The fork/arm use the binder's paired overhang
index; unpaired binder beads stay authored. twist+meanRise come from the overhang. Works binder-
shorter (toehold), binder-longer, or equal — all jump-free.

**Straight form (2026-05-29):** `form` control (`helical | straight`) for BOTH modes (the
sandbox's straight/helical toggle, ported to the real beads). Helical = the radial model on the
real spiral. Straight = each strand DE-SPIRALS into a straight line at its OWN ROOT azimuth/radius (NOT a
symmetric ±halfW ladder): overhang rail = `ohAxis_i + ohR[0]·rhat(thetaRoot)`, binder/invader rail
= `ohAxis_oj + bnRootR·rhat(bnRootTheta)` (`_straightFrame` helper). So the overhang ROOT backbone
bead stays at its REAL position (aligned with the helix axis, unmoved) and the overhang runs
parallel to the axis from there — same target as the helical unwind. `_unzipStraight` /
`_displacementStraight`: no spiral, no unwind; overhang is STATIC; binder/invader peel into
straight arms (toward root + outward `+bref`, bref = rhat(bnRootTheta+exit)); overhang slab →
toward axis (−ohRhat). DISPLACED-strand (binder) slabs → toward the helix-axis CENTER via
`_inwardAxis(b,px,py,pz)` (perp component of pos−axis, negated; ⟂ Adir) — both straight modes.
INVADER slab orientation (BOTH forms): the bound→unbound transition uses a QUATERNION SLERP
between the bound slab frame (tangent=axis, base-normal=toward overhang/axis) and the unbound
frame (tangent=arm, base-normal=toward axis ⟂ arm) — `_slerpFrame(bt,bn,ft,fn,t,tanArr,bnArr,o)`
+ `_frameQuat` (orthonormalizes each endpoint via Gram-Schmidt, makeBasis→quat, slerp, extract
tangent=col1 / base-normal=col2). This replaced a per-frame vector-lerp+orthogonalize that hit an
orthogonalization SINGULARITY when the lerped normal became ∥ the lerped tangent (the normal
collapsed → ~180° flip → "indirect path / unnecessary steps"). Verified: degenerate config
vector-lerp swept 269° (with flip) vs slerp 127° (shortest, monotone, no flip).
**Free-tangent sign fix:** the UNBOUND frame's tangent must be the backbone direction IN ARRAY
ORDER = `axSign·arm` (NOT the arm-extension direction `+arm`). For `toeholdAtTip` (axSign=−1) the
free arm extends in the −array direction, so passing `+aInv` made the free tangent point ~opposite
the bound tangent (+Adir) → the slab plate (thin axis ≈ tangent) rotated ~150° (≈180° "flip")
even though the normal was right. With `axSign·aInv` the free tangent stays ≈+Adir, so the slab
rotates only by the splay angle (the legitimate tilt). Applied to both helical + straight invader
slerp calls. Switching to straight SNAPS to the de-spiraled lines (not the helical
positions — inherent; `clear()` restores). Verified headless: overhang root bead = real root pos
(err 0), all overhang beads at root radius+azimuth (straight line aligned with root), straight
displacement renders the invader. (Earlier flat-`±halfW`-ladder version replaced; `meanW` now
unused by the straight path.)

**Toehold displacement (TMSD) mode (2026-05-29):** Mode dropdown `unzip | displacement`. Toehold
= overhang indices NOT covered by the binder (needs binder shorter than overhang; hint otherwise).
`bind` computes `hasToehold`, `dOf[j]` (displacement coordinate; toehold end → d=0, detected from
mean covered vs toehold index), `grooveOffset` (mean binder azimuthal offset). `_displacement`
(driver): φ=0 free+bound→1 bound+displaced; binding front `bf = φ·(M+meltBp)−meltBp/2−0.5` sweeps
d. SYNTHETIC INVADER rendered via sandbox `createStrandRenderer(scene)` (role 'invader' green,
lazy, `getScene` passed main.js→panel→driver): bound part pairs the overhang (antiparallel partner
= ohAxis+R·rhat(ohTheta+grooveOffset)), free part trails from the branch point. Real BINDER beads
displaced (covered beads peel off as bf passes, toehold-adjacent first); overhang SUBSTRATE stays
authored. Two free tails splay in a Λ (invader +d, binder −d, both +bref outward) with SEPARATE splay
angles: **Splay angle** (`thetaDeg`) = displaced binder arm; **Invader splay** (`invaderSplayDeg`,
falls back to thetaDeg) = invader free arm. The binder's
displacement front LEADS the invader's binding front by `dispGap` bp ("Branch gap" control,
default 1): binder df uses `bfB = bf + gap` and its arm anchors at `bfB`, so the binder vacates
a position before the invader occupies it (unbound zone between the two fronts → no clipping;
binder stays ahead). No backend/topology. Verified headless: hasToehold, φ=0 binder jump-free + substrate fixed, φ=0.5 toehold-
adjacent binder displaces first, φ=1 fully displaced, invader meshes present.

**Verified headless:** synthetic spiral (overhang+binder on a cylinder around +Z) — bind ok;
φ=1 = authored (0 err, jump-free); φ=0 overhang max|R−1|=0 + angle-spread=0 (straight line at
radius R) + binder radius = R+drift (drifted out); φ=1-again + clear restore to 0. Frontend
build clean. **NOT visually click-tested in a live browser** — user smoke-tests on
`workspace/OH6hb_test.nadoc`.

**Cones + slabs (2026-05-29 follow-up):** `setBeadOverrides` (helix_renderer.js) now also
recomposes the inter-bead connector CONES whose endpoints moved — new `_keyToCones` map
(bead key → cones) + `_recomposeCone(cone)` helper (same math as the `applyFemPositions` cone
loop), called for the moved beads only (dedup). Without this the cones stayed put while beads
animated. The driver also passes per-bead slab base-normals (`nx,ny,nz`) for OVERHANG beads =
blend(authored base_normal → inward −rhat) by the melt fraction, so the overhang slabs point
TOWARD the helix axis as it unwinds (jump-free at φ=1). `_authoredUpdate` restores the authored
`base_normal` too (else slabs stay inward after stop). Binder slabs are not reoriented (just
translate). Cached `ohBn` in `bind`.

Superseded one-shot ("Animate binding" menu items + `overhang_unzip_overlay.updateBinder` +
`_animateBindingForOverhang` + `onAnimateBinding` threading) was removed. Kept
`overhang_unzip_overlay.update`/`clear` for the animation player's bind/unbind playback.
