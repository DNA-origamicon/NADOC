# Fine-stage display collapses a tight-bundle helix → coarse fallback (FIXED 2026-07-04) — supporting detail

[Topic head](../../project_mrdna_panel.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Fine-stage display collapses a tight-bundle helix → coarse fallback (FIXED 2026-07-04)
Toggling the deform display on a FINE `2hb_2xT` job squashed ONE helix into a bead
**ring** (the other stayed a rod). Root cause: `nuc_pos_override_display_from_coarse`
assigns each relaxed bead to the nearest **design** axis, but `_sim_paths` feeds a fine
job the highest CG stage (`mrdna_relax-2`), whose initial structure has already DRIFTED
off the design frame (it's a multiresolution intermediate, not the clean B-DNA frame).
On a 2hb the two helices sit ~2.3 nm apart, so one helix's drifted beads get dumped onto
its neighbour (measured: h_XY_1_1 got 7 beads / 3 distinct bp vs h_XY_0_1's 35) → its
spline collapses to a 3.2 nm blob (≈38% of its 8.3 nm contour). The COARSE stage
(`mrdna_relax-0`) beads still sit cleanly at the design axes (7/7 split, perp 0.27 nm).
Straight 6hb ALSO collapsed a helix on fine (h_XY_0_3 → 51%); only well-separated
bundles were unaffected.
- **Fix (`mrdna_runner`):** `_display_positions` runs the fine reconstruction, then
  `_override_has_collapsed_helix` checks each helix's 3-D bounding-box diagonal vs
  `length_bp × rise`; if any helix is a blob (< 0.45×), it recomputes from the coarse
  stage (`_coarse_sim_paths` = lowest-numbered CG stage) and uses that if clean.
  `_DISPLAY_VERSION` 3→4 regenerates stale caches on read.
- **Collapse metric = 3-D bounding DIAGONAL, NOT axial projection (KEYSTONE):** a
  genuinely BENT helix (curved design's loop/skip bend) has a short axial projection but
  still spans a large arc — even a 180° semicircle keeps ~64% diagonal. Using axial extent
  would false-fire on curvature and drop the fine reconstruction the curvature readout
  needs. The diagonal only trips on a true collapse. So curved designs KEEP fine; only
  tight straight bundles fall back to coarse.
- Validated: 2hb → both helices 7.7/7.8 nm (ring gone), live `/display` API confirmed,
  Playwright screenshot (`frontend/e2e/mrdna_display_collapse.spec.js`) shows two extended
  strands. Pins: `test_mrdna_jobs.py::test_collapse_detector_flags_blob_but_not_full_or_bent`
  (blob trips, full rod + full-contour bent arc do NOT).

### Overstretched backbone bonds (partial mis-assignment) → same coarse fallback, generalised (2026-07-04)
6hb_2xT's fine display was a jumbled blob with long stray bonds (max 2.2 nm; 29 backbone
bonds > 1.3 nm). NOT a full collapse (so the diagonal detector missed it): the fine stage
assigned a helix only a **sparse, gappy** set of beads (h_XY_1_2 got 19 beads at bp
-1..11, 18, 39..42 — bp 12–38 nearly empty), and the per-helix spline **leaps across the
gaps** → 2.2 nm consecutive-backbone jumps on both strands. Same fine-stage
nearest-design-axis mis-assignment root cause as the 2hb collapse, just partial.
- **Generalised the fallback:** `_display_positions` now scores the fine reconstruction
  with `_reconstruction_badness` = `1000 × collapsed-helix + _count_stretched_backbone_bonds`
  (consecutive same-helix backbone steps > 1.3 nm; canonical helical P–P ≈ 0.67 nm) and
  falls back to the coarse stage when it scores **distinctly cleaner** (fires on
  collapse OR ≥12 stretched bonds, switches only if coarse's badness is strictly lower).
  6hb_2xT: fine 29 → coarse **14** stretched, max 2.2 → 2.0 nm, blob → recognizable
  bundle. `_DISPLAY_VERSION` 4→5.
- **Bond-stretch is a LOCAL metric → safe for curved designs:** bending doesn't stretch
  backbone P–P bonds, so a genuinely curved fine reconstruction is NOT penalised and keeps
  fine (unlike an axial-extent metric). The ≥12 gate + strictly-cleaner rule also keeps a
  clean fine reconstruction, so only artifact-heavy fine displays fall back.
- **CURVATURE tradeoff (accept + flag):** curvature (`load_curvature` → `measured_curvature`)
  reads the SAME display positions, and the coarse stage carries no twist → less bend
  (~2° vs fine's ~12–16° on 6hb_curved, LESSONS A9). So a design whose fine reconstruction
  is artifact-heavy now shows LOWER simulated curvature. This is acceptable: an
  artifact-heavy (jumpy) fine axis gives a NOISY/unreliable curvature anyway; a clean fine
  reconstruction (few stretched bonds) is kept and its curvature preserved. If a curved
  design regresses, decouple curvature onto its own fine-stage reconstruction path.
- **RESIDUAL (not fixed):** coarse still leaves ~14/700 stretched bonds on 6hb_2xT (≤2.0 nm),
  at crossover-adjacent bp and helix-end/negative-bp spline endpoints — inherent to splining
  through sparse 5 bp/bead CG beads + ideal duplex reconstruction. Eliminating them needs a
  reworked reconstruction (spline endpoint handling / crossover backbone), a larger change.
- Pins: `test_stretched_bond_detector_and_badness`; Playwright `mrdna_6hb_bonds.spec.js`
  (reports max/median/over-threshold + screenshot).

### Beadless helix-end → flat ring; fixed AT THE SOURCE by straight extrapolation (2026-07-04)
Re-running the fine display on `6hb_2xT` still showed a **ring of bases** (a helix end
"collapsed onto a 2-D plane to make a circle") near the top of the bundle, even after the
coarse-fallback work above. Root cause is NOT the fallback — it's the reconstruction itself.
`nuc_pos_override_display_from_coarse` (mrdna_bridge) placed each nucleotide on the per-helix
cubic spline at **`t = np.clip(bp, t_lo, t_hi)`** where `t_lo/t_hi` = min/max **bead-covered**
bp. When the fine stage's nearest-design-axis assignment leaves a helix END beadless (the same
tight-bundle drift as the collapse/stretched-bond modes, localized to one terminus), **every bp
past `t_hi` was pinned to the single point `cs(t_hi)`**, and the duplex twist fan (line ~772)
then splayed those pinned nucleotides into a flat circle of radius **HELIX_RADIUS** — literally
the reported ring.
- **Why BOTH fallback detectors miss it (KEYSTONE):** the whole-helix bounding **diagonal**
  stays large (the rest of the helix is extended, so ~16 nm ≫ 0.45×contour → `_override_has_collapsed_helix`
  silent), AND ring neighbours are only `2R·sin(twist/2) ≈ 0.58 nm` apart (well under the 1.3 nm
  jump threshold → `_count_stretched_backbone_bonds` silent). On the stochastic re-run 6hb_2xT
  scored fine-badness **11**, one under the `≥12` gate — the metric was both blind to end-rings
  AND riding a knife-edge. So a detector tweak can't fix this; the source must.
- **Fix (source):** new pure helper **`mrdna_bridge._relaxed_axis_at_bp(cs, bp, t_lo, t_hi,
  ideal_axis_hat, rise_ang)`** — inside `[t_lo,t_hi]` evaluates the spline; BEYOND it continues
  the axis **straight along the endpoint tangent at ideal B-DNA rise** instead of clipping.
  Linear (not cubic) extrapolation keeps the tail bounded and canonically spaced, so it never
  trips the stretched-bond fallback. Display fn now calls it in place of the `clip`+`cs(t)` axis
  lookup. `_DISPLAY_VERSION` **5→6** (stale ring caches regenerate on read). Only the DISPLAY fn
  had the bug: the re-idealised siblings (`nuc_pos_override_from_mrdna_coarse` L548,
  `nuc_pos_override_from_arbd_strands` L937) set position from `ideal_axis_pt = ax_s +
  local_i·rise·ideal_axis_hat`, so their clip only picks the tangent direction — no pin, no ring.
- On the clean on-disk 6hb_2xT job the fix is a strict improvement (per-helix diagonals 16→19–22
  nm = full contour as the ends extend; stretched-bond count unchanged at 11 → no new jumps).
- Pins: `test_mrdna_pipeline.py::TestBeadlessEndNoRing` (2 pure unit tests, no mrdna/ARBD/MDA:
  extrapolation-not-pinned + full-duplex-tail-extends-vs-clip-makes-a-flat-HELIX_RADIUS-ring).
  Both proven can-go-red by reverting the helper to clip. This also partly addresses the
  "helix-end/negative-bp spline endpoints" RESIDUAL noted in the stretched-bonds section above.

### Far-end single-stranded scaffold crossovers → stretched bonds; fixed by ssDNA harvest + both-ends anchor (2026-07-04)
After the ring fix, 6hb_2xT's deform display still showed **scaffold backbone bonds
stretched 4–6 nm at the far ends** (worst 6.36 nm, a helix-to-helix crossover at bp −12).
Mechanically diagnosed (NO geometric reasoning): the helix ENDS (bp −1..−12, 42..53) are
**genuinely single-stranded** — 104 unpaired scaffold nts, ZERO with a complementary
staple (checked via `_build_nt_arrays` pairing + design presence). mrDNA correctly models
them as ssDNA (`NAS` beads); there are NO dsDNA (`DNA`) beads there. So the crossovers DO
register in the sim (short `NAS` bonds) — the stretch was a **display** artifact: the
reconstruction phantom-duplexed each unpaired nt onto the dsDNA helix spline (extrapolated
straight past the beadless end), so at a crossover the two helices' extrapolated ends
diverge and the connecting scaffold bond stretches.
- **Fix (`_display_positions`, mrdna_runner):** after the ds reconstruction, merge the
  relaxed ssDNA positions from **`nuc_pos_override_ssdna_from_arbd(..., prefer_continuity=True)`**
  (the SAME harvest the MD seed uses), `{**ds, **ss}` so ss wins at unpaired keys.
- **`prefer_continuity` flag (new, DISPLAY-only):** the seed's ss placement maximizes
  CLEARANCE (avoid MD clashes) and will leave a run at its detached-ideal design position —
  wrong for display (floats the junction). Display needs CONTINUITY: pick the
  highest-fidelity anchored candidate instead of the farthest-from-body one.
- **Both-ends "blend" (KEYSTONE):** the far-end scaffold runs are **bridging loops**
  (ds…ss→crossover→ss…ds) with a relaxed root at BOTH ends; anchoring only one (the seed's
  single root) floats the far ss/ds junction (4.2 nm). `_ssdna_runs` now returns
  `root5_key`/`root3_key` (both sides); the new pure `_blend_run_both_ends(ideal, d5, d3)`
  adds each nt its NEAR root's ideal→relaxed displacement, linearly blended 5′→3′ — pins
  BOTH ends one bond from their relaxed roots while preserving the ideal loop shape. Result
  on 6hb_2xT: max scaffold bond **6.36 → 2.02 nm** (residual 2.02 is the pre-existing
  ds-spline artifact, not a crossover); far-end crossovers now reconstruct at **1.4–1.9 nm =
  their design inter-helix gaps** (1.99/2.00/1.42). Placement: 30/30 runs `blend`.
- **Seed path UNCHANGED:** `prefer_continuity` defaults False, so the blend candidate is
  skipped and the clearance selector + single-root behavior are byte-identical for the MD
  seed. `_ssdna_runs` only ADDS keys. `_DISPLAY_VERSION` 6→7.
- Pins: `test_mrdna_pipeline.py::TestSsdnaBridgeContinuity` (3 pure unit: `_ssdna_runs`
  both-roots for a bridging run via monkeypatched `_build_nt_arrays`; `_blend_run_both_ends`
  pins both ends where single-anchor floats; n==1 centers). Free overhangs (one root only)
  keep spline/translate — unchanged.
