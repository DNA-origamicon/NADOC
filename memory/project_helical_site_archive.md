---
name: helical-site-archive
description: "History for [[project_helical_site]] — the per-phase record of the 0-10 helical-site work (2026-08-07), with every measurement that justified each step. Mine it for a specific past decision; never read it in a routine loop."
metadata:
  node_type: memory
  type: project
---

# Helical site — per-phase record (archive)

The lean head is [[project_helical_site]]. Everything below is the completed work: what each
phase changed, the numbers that justified it, and the three phases whose SCOPE turned out to be
wrong (2 — "byte-identical" would have preserved two bugs; 4 — the premise measured the wrong
file; 7 — the rows it was built on were retracted).

## Phases

Each is independently shippable and leaves the suite green. **Acceptance is byte-exactness
except where a phase is explicitly allowed to move numbers.**

### Phase 0 — DONE (2026-08-07)
Scalar path carries the site; `_atom_frame` / `_atom_frames_batch` read it. Pinned by
`test_the_stamp_ignores_the_bead_and_reads_the_phase` (move every bead to r = 3.7 nm, zero
atoms move) and `test_the_cg_bead_is_a_projection_of_the_helical_site`.

### Phase 1 — the vectorised path carries the site — **DONE 2026-08-07**
`nucleotide_positions_arrays` gains `radial_hats` / `axis_points` / `azimuths`, and
`_nuc_arrays_from_list` (the loop/skip fallback) must carry the scalar path's own values
through — otherwise the two paths disagree exactly on skip-bearing designs.
- **Acceptance, met:** **3220 arrays byte-identical** (`np.array_equal`, 0 different) across
  5 fixtures — plain HC + SQ, two skip-bearing (18 and 6 skip helices), one clustered
  (VoltronCore, 3 transforms, 46 skip helices) — over straight / `compact_skips` / deformed /
  both `_extended` variants. Projection identity `position == axis_point +
  HELIX_RADIUS·radial_hat` exact on **151,386** nucleotides.
- **Cost:** array path unchanged at 4.0 ms on `3x6_Sq_full`; the predicted 0.3–0.5 ms for the
  two extra arrays is inside the noise.
- **The site had to survive TRANSFORMS, which the scope under-called.** Phase 3's consumer
  (`_section_frame_from_arrs`) reads *deformed* arrays, so dropping the site there would have
  blocked it. Both transform paths now carry it: `_apply_cluster_rigid_transform_arrays`
  moves `axis_points` as a point and `radial_hats` as a direction (`azimuths` is invariant —
  it is an angle in the helix's own rotating frame), and the bend path splits `nuc_locals`
  into radial + axial parts so the identity survives the rotation. Residual after a bend:
  **3.6e-15 nm**, so deformed arrays assert at 1e-12 and straight ones at exact equality.
- **The trap this created and closed:** the domain-level cluster path copies *all* keys and
  then overwrites a fixed tuple of transformed ones. Carried untransformed, the site would
  have been STALE — `positions` moved, `axis_points` still on the straight lattice, and it
  reads as valid. The key tuple is now `_xf_keys_present()` in one place, and
  `test_the_site_moves_with_the_beads_under_a_cluster_transform` fails if it regresses
  (verified by reverting the helper: the pin fires).
- Unblocks Phases 2, 3 and 6.
- **Pins:** `tests/test_helical_site.py` (12). Two fixture facts worth keeping: the repo's
  bend fixtures store `curvature_deg_per_bp = 0.0` (`multi_domain_test3_bend90` included), so
  the extended-loop test BUILDS its bend; and a LOW-side extension anchors at the bend
  window's start where the frame is identity, so it must be taken off the HIGH side or the
  test is vacuous.

### Phase 2 — mrDNA reads sites — **DONE 2026-08-07**
`mrdna_bridge._build_nt_arrays` was a **fourth** full re-derivation of the helix formula. It now
reads the site, keyed `(helix_id, bp_index, direction, copy_k)`.

**The planned acceptance — "seed byte-identical" — was WRONG, and finding that out is the
result.** The inline copy read `phase_offset` / `twist_per_bp_rad` / `axis_start` **straight off
the stored helix**, while every other representation goes through
`effective_helix_for_geometry`, which re-derives them from `grid_pos`. mrDNA was the only engine
seeded on stored values, so byte-identity would have meant preserving two live defects:

| design | lattice | longest helix | seed moved (median / max) | cause |
|---|---|---|---|---|
| `6hb_test` | HC | 42 bp | 19.53 / **19.99 Å** | one helix **175° out of phase** — a full helix diameter |
| `U6hb` | HC | 420 bp | 0.52 / 1.04 Å | pre-TD-29 twist |
| `18hb` | HC | 400 bp | 0.48 / 0.99 Å | pre-TD-29 twist |
| `Con4` | HC | 21 bp | 0.03 / 0.05 Å | pre-TD-29 twist |
| `2x3x100_Sq`, `3x6x400_Sq` | SQ | 123 / 422 bp | **0.000 Å** | control — stored already matched |

The honeycomb column is TD-29's incommensurate twist (34.3 vs 720/21): mrDNA kept the
crossover-strain ramp that was fixed everywhere else on 2026-08-06, and it grows without bound
with helix length (0.05 Å at 21 bp → 1.0 Å at 400 bp). Square is the control and did not move
at all, which is what says the change is the stale-pose fix and nothing else.

- **Acceptance as met:** every mrDNA bead is `np.array_equal` to the geometric layer's bead
  (`position × 10`) on plain HC, plain SQ, a skip-bearing design and a loop-bearing one.
- **`compact_skips` behaviour preserved** — the site is read from `nucleotide_positions(eh)`
  with the default (uncompacted) walk, which is what the inline copy did.
- **Nothing in the suite caught the seed change** (6854 pass either way): mrDNA geometry was
  pinned only against itself. `tests/test_helical_site.py` now pins it against the site.
- **⚠ Flag, not measured:** `backend/parameterization/mrdna_inject.py` fits `k_bond`,
  `hj_equilibrium_angle_deg` and `k_dihedral` through this same function, so any honeycomb
  parameters in the live DB were fitted on the ramped geometry. Re-checking them needs mrdna +
  the fit jobs — see [[project_crossover_parameterization]].

### Phase 3 — the periodic seam solver reads the axis — **DONE 2026-08-07**
`_section_frame_from_arrs` now reads the forward nucleotide's own `axis_points` /
`radial_hats` instead of solving a 2×2 for them. The `helix_dir` parameter is gone with the
solve, and with it the whole "only correct for beads the geometric layer placed" fragility.

**Acceptance, met — and it found a live bug.** Over 5549 sampled cross-sections on 6 fixtures:
**5514 unchanged** (worst residual 1.4e-14) and **35 changed, all on clustered designs**.

The 35 are a fix, not a regression. Cluster transforms are applied **per DOMAIN**, so a base
pair whose two strands belong to different domain-level clusters has one bead moved and the
other left behind. The chord-based solve fed those two beads into one 2×2 as though they
shared a frame — measured on `VoltronCore`, the reverse bead sits **7.5–7.9 nm** from the
forward bead's axis instead of ~1 nm, and the recovered axis was out by up to **1.94 nm**.
Each bead is exactly `HELIX_RADIUS` from *its own* axis point, which is how you can tell the
sites are right and the chord was the wrong question. Same per-domain trap
[[project_measured_atomistic]] recorded for the measured re-placement.

- **Pins:** `test_the_seam_frame_is_the_forward_nucleotides_own_site` and
  `test_the_seam_solver_survives_a_base_pair_split_across_two_clusters` (fails if no split
  pair exists, so the fixture cannot silently stop proving it).
- `test_the_periodic_seam_solver_still_gets_a_valid_axis` kept its assertion; its docstring
  described the inversion and was rewritten.

### Phase 4 — the oxDNA seed boundary — **DONE 2026-08-07, and the scope was wrong**

**The premise was wrong and the audit table row was overstated.** `nuc_conf_line` does write the
display bead into the CM slot, but **every production path already passes
`oxdna_native_seed=True`** (`oxdna_runner`, `lammps_runner`, `namd_seed_sanity`,
`build_rotated_seed`), and `oxdna_native_seed_map` slides each nucleotide along a1 so designed
pairs start inside oxDNA's bonding range. The raw `False` is only the API default.

⚠ **`design_ref.dat` in a job dir is NOT the seed** — it is an unconverted reference, and
measuring it is what produced a wrong "every seed ever written is 0.9 nm too wide" reading. The
seed is `conf.dat`. On job `4e37b500ad84`: `design_ref` 1.9319 nm, **`conf.dat` 1.0514 nm**,
relaxed 1.0227 nm.

**What was actually wrong: a fitted constant where the model publishes one.**
`OXDNA_NATIVE_HBOND_NM` was `0.37` nm, "the separation a relaxed duplex settles at on this
machine". oxDNA's published `HYDR_R0` is **0.4 length units = 0.34072 nm**, and three
independent numbers agree on it:

| | CM–CM | backbone–backbone |
|---|---|---|
| oxDNA relaxed output (482 pairs) | 1.0227 | 1.6056 |
| seed, old `0.37` | 1.0514 (err **0.0287**) | 1.6307 (err 0.0251) |
| seed, `HYDR_R0` | **1.0222** (err **0.0005**) | **1.6014** (err 0.0042) |

**The a1 SLIDE is the right mechanism; a radial re-projection is not.** Projecting the CMs onto
a 0.529 nm cylinder reproduces the relaxed CM–CM and *misses* the backbone–backbone, because it
changes the pair's azimuthal geometry. The slide reproduces both. That settles the open question
this phase was gated on — it was a false dichotomy: neither "atomistic mass centroid" nor
"inverted `oxdna_backbone_site`", but the model's own HB equilibrium.

**Literature.** oxDNA's stored position is the CM and the model defines it *only* through fixed
offsets to the interaction sites — the oxDNA docs flag that the convention changed between
Ouldridge's thesis (0.24 units from the backbone site) and oxDNA1 (0.4), so it is notional and
cannot be derived from an atomistic centroid. tacoxDNA's PDB→oxDNA converter uses the unweighted
mean of all heavy atoms (`get_com()`), which on our own atomistic model sits at 0.5747 nm from
the axis — a converter's fallback for when you do *not* know where the sites belong, which here
we do.

- **FENE: neutral** (over-cliff 17→17, 2→2, 24→24, 529→530 on four designs); median bond length
  moves slightly toward the rest length (0.7763 → 0.7692 units).
- **Pin:** `test_the_native_seed_reproduces_oxdnas_own_equilibrium_pair_geometry`.
- **Not changed:** `nuc_conf_line` still writes `backbone_position`; the conversion stays in the
  seed map where it already lived. Row 5 of the audit table in [[project_atomistic_source_of_truth]]
  should be read with this correction.

### Phase 5 — the measured producer (P2) — **DONE 2026-08-07, narrower than scoped**
`geometry.site_from_bead` / `site_from_beads_arrays` are the second producer: given a
position and an axis they return `(radial_hat, axial_offset)`, the same pair the analytic
producer emits. `_atom_frame` and `_atom_frames_batch` now read **two producers, one site**
— analytic where the nucleotide carries one, measured otherwise — instead of a path and an
unnamed fallback.

- **Acceptance, met:** the two producers agree to **1 ULP** on lattice geometry, and a full
  atomistic build is **byte-identical** either way (0.000e+00 nm over three designs, the
  same check Phase 0 used). Not bit-exact on the hats themselves: the measured producer
  subtracts the axial component before normalising and for a lattice bead that component is
  tiny but not exactly zero. The pin asserts 1e-15 and says why.
- **`_phase_invalidated` STAYS, and that is correct.** The scope said to retire it. It is
  not a workaround — it is how a caller *selects* the measured producer, and the selection
  is real: a moved nucleotide's lattice phase is genuinely no longer descriptive. Retiring
  it would mean guessing which producer to use from the data, which is exactly the
  ambiguity that caused the Phase-0 bug.
- **The axis FIT was not built, deliberately.** Every caller of `_atom_frame` already has
  an axis (a lattice helix, or an explicit `axis_override` for a bent centreline), so a
  per-nucleotide fit has no consumer today. Building one now would be speculative; the
  entry point for it, when a consumer appears, is `site_from_bead`'s axis argument, and the
  two existing fitters to reconcile are still `pdb_to_design.py:521` / `pdb_import.py:843`.
  **So "a relaxed oxDNA frame becomes a site" is true only where the caller supplies the
  axis** — which is the case for every path in the codebase, and is not the same as the
  standalone atoms→sites converter the scope implied.
- **Pins:** 4 in `tests/test_helical_site.py` — producer agreement, scalar/array twins, the
  on-axis degenerate case, and the override contract (move the bead, atoms follow it),
  which is the mirror of `test_the_stamp_ignores_the_bead_and_reads_the_phase`.

### Phase 6 — `_rigid_frame_calibration` off sites — **DONE 2026-08-07**
The oxDNA particle frame (CM, a1, a3) now comes straight from `nucleotide_positions`; the
temp-file write + read is gone. The round trip only ever converted CG geometry into a frame,
and it cost two things:

- **it quantised the fit's own inputs.** The conf is text at `%.6f` oxDNA units, so every frame
  was rounded to 8.5e-7 nm — measured perturbation 4.3e-7 nm in position and 5.0e-7 in a1 — and
  that noise landed inside the residual its `assert m_res < 1e-6` is meant to police;
- **it made a cached constant depend on `_geometry_for_design`**, the DISPLAY serialiser, so a
  display-side default (measured re-placement, the junction-balance roll) could have moved it.

**Acceptance:** the constant moves by ≤ **1.1e-7 nm** (dQ ≤ 7.3e-8, dc ≤ 1.1e-7) — exactly the
quantisation removed — and all four buckets stay proper rotations with the tripwire green.
**Pins:** `test_the_rigid_frame_calibration_is_orthonormal_and_complete` and
`..._does_not_touch_the_display_serialiser`, the latter breaking `_geometry_for_design` and
requiring the calibration to be unaffected (the patch-visibility mechanism was checked, so the
firewall is not vacuous).

## Round-2 phases — what the re-verified audit left open (added 2026-08-07)

Phases 0–6 closed 4 of the 11 live CG couplings.  These cover the rest.  **None of them is a
refactor**: 7 and 8 are decisions with code attached, which is why they were out of the first
plan's scope rather than forgotten.

### Phase 7 — the placers — **RESOLVED 2026-08-07: the premise was false, no change needed**

**Audit rows 8 and 9 said "the one place a display decision reaches an exported atom". That is
wrong.** Both placers read `geometry.nucleotide_positions` — the GEOMETRIC layer — not
`_geometry_for_design`, the display serialiser:

- `_build_extra_base_atoms`: `nucA`/`nucB` come from a `nuc_pos_cache` filled by
  `nucleotide_positions(helix)` (`atomistic.py:3010`).
- `_build_extension_atoms`: reads the same cache. Its docstring *mentions*
  `design_geometry._strand_extension_geometry` but does **not call it** — it replicates the arc.

So neither the MD-measured bead re-placement nor the junction-balance roll can reach an exported
atom through these, and the chord endpoints are the site projected at `HELIX_RADIUS`
(`position == axis_point + HELIX_RADIUS·radial_hat`) — i.e. already a site read in all but name.
**No decision is required and no code should change.** The remaining choice — chord on the bead
radius vs on the atomistic anchor — is not worth taking: insert bonds are already clean (0 of
25,470 over 0.32 nm on `VoltronCoreScad`, max 0.2298), the chain endpoints already use the real
C3'/C5' atoms, and moving the chord would take inserts off the bead the user is looking at, which
is the property the placer was built to have.

⚠ The one thing to preserve: they must keep reading `nucleotide_positions`, not
`_geometry_for_design`. There is no test for that; add one if either placer is ever touched.

*Superseded detail, kept because it is the reason the rows read as they did:* both placers take
their ANCHOR from atoms and their SHAPE from the geometric layer.

- `_build_extra_base_atoms` (`atomistic.py:3046`): the interpolation line's endpoints
  `line_p0/line_p1` are the two junction nucleotides' **CG backbone beads**, and the
  chain-direction endpoints for a SIMULATED insert are the real C3'/C5' **atoms**.
- `_build_extension_atoms` (`:3302`): reuses `design_geometry._strand_extension_geometry`'s
  Bézier arc — CG — but roots it on the anchor's real C3'/C5' atom, "the trick
  `_build_extra_base_atoms` uses to get physical O3'→P bond lengths".

So the open question is narrow and answerable: **may the CG view define the PATH an insert or
tail takes between two atomistic anchors?**  Today it does, deliberately — "the CG view is the
single definition of where an extra base sits, and this reproduces it ... so an insert's atoms
land on the bead the user is looking at, by construction rather than by agreement."

- **Owner decision:** keep that (a display convention defines an exported atom's path — the one
  place in the codebase where that is still true), or re-derive both paths from the atomistic
  anchors and accept that inserts stop tracking the drawn bead.
- **What it costs if changed:** swapping the template under these placers moved an insert
  **0.41 nm** off the chord and stretched a tail bond to **3.5 Å** (limit 3.2) — recorded in
  [[project_measured_atomistic]].  A re-derivation must re-fit both local origins.
- **Acceptance:** insert and tail bond lengths no worse than today, measured the way Phase 4's
  collateral was (`2hb_xover_atoms_test` extra-base max 0.1835 nm; `VoltronCoreScad` 0.2298 over
  25,470 insert bonds, tails 0.5364 max over 7,348).
- **Unblocks Phase 9.**

### Phase 8 — the pose fitters — **PART DONE 2026-08-07; the rest still needs a decision**

**Done, decision-free:** `design_geometry.fitting_geometry(design)` now states the contract the
three fitters were only inheriting, and all 8 call sites use it. They were correct *by accident* —
both display tweaks default OFF, and flipping `measured_positioning` to True is TD-27 Stage 3's
stated goal, at which point all three would have silently started fitting against measured beads
and writing different PERSISTED poses with nothing to catch it. Pinned by
`test_a_display_default_flip_cannot_reach_the_pose_fitters`, which simulates the flip and requires
`fitting_geometry` to be unmoved while the plain call follows it.

**CLOSED 2026-08-07, owner decision: leave saved `cluster_transforms` as-is.** No migration, no
re-fit on load, no versioned field. Re-targeting the fitters from the bead onto the site is
therefore not happening either — it would change what a saved pose means, which is precisely what
"leave as-is" rules out. The default-flip hazard is closed and that was the real risk; the bead
convention stays load-bearing for saved poses, deliberately.

*Original framing:*

`direct_relax` (4 sites), `linker_relax` (3), `duplex_cluster` (2) call
`_geometry_for_design(design)` and write **persisted** `cluster_transforms`.

**They are already firewalled from both display tweaks** — every call passes no flags, so
`measured_positioning=False` and `junction_balance=False`; they read the legacy geometric layer,
not the display.  That is better than the original audit implied and it removes the urgency.

What remains is the real coupling: they fit against **beads** at the r=1.0 lattice convention and
write the result to a field that is saved in the `.nadoc` file.  So the bead convention is
load-bearing for every pose a user has already committed to disk.

- **Owner decision (still open from the original plan):** designs carrying saved
  `cluster_transforms` — re-fit on load, leave them, or version the field?
- **Then:** re-target the fitters at the site (`axis_point` + `radial_hat`) rather than the bead,
  which makes them independent of what radius the display chooses.
- **Acceptance:** on every fixture with saved transforms, a re-fit reproduces the stored pose
  within a stated tolerance, or the migration is explicit and tested.  Fixtures that exercise it:
  `VoltronCore` (3 transforms), `DollarSign` (2 deformations + 3), `Ultimate Polymer Hinge` (4).

### Phase 9 — **DONE 2026-08-07: decoupled by re-justification; the value did not move**

**Two scoping errors corrected first.** (a) It is NOT gated on the placers, and (b) it is NOT
gated on re-quoting the 1ZEW templates — that is `_FRAME_ROT_RAD`'s gate. The two are separable
operations: this rotates `e_radial` (orbiting the whole nucleotide about the helix axis),
`_FRAME_ROT_M` post-multiplies the frame (spinning the template in place, origin fixed).

The constant's problem was its JUSTIFICATION, not its value. It read "calibrated by overlaying
the atomistic model on the NADOC bead/slab representation" — the display deciding where atoms go.
Checked instead against the only measurement that can settle it, the crossover-backbone azimuth
of equilibrated free-NAMD origami, on `18hb` with 1420 crossovers in
`measure_interhelix_phase.py`'s exact convention:

| roll | φ mean | R | \|φ\| median |
|---|---|---|---|
| −32° alone | **+5.72°** | 0.920 | 15.68 |
| −32° + junction balance (ships) | −1.22° | 0.924 | 21.53 |
| junction balance alone | +13.93° | 0.896 | 3.48 |
| **MD (free NAMD, 18hb)** | **+7.30°** | — | **19.10** |

**−32° is 1.6° from the MD mean.** It stands on its own atomistic evidence, so the decoupling is
a re-justification: no geometry moved, no golden moved, no test needed reconfirming because
nothing changed. Pinned by `test_the_atomistic_crossover_azimuth_stays_in_the_md_envelope`.

**⚠ What this measurement EXPOSED, and it is open.** The TOTAL that ships is −46.6°, because
`atomistic_phase_offset_rad` adds the DX-junction balance (−14.6° on honeycomb). That takes the
crossover azimuth **8.5° to the far side of the MD mean** (−1.22 vs +7.30). Two measured criteria
disagree by 14.6°:

- **junction linker SYMMETRY** — user-reported defect, anchor gaps 0.586/1.086 → 0.724/0.724,
  worst linker 1.126 → 0.761 nm, visually confirmed by the owner;
- **equilibrium crossover AZIMUTH** — best near −32°, which is where the balance roll is absent.

They measure different things (a seed's local strain vs where relaxed DNA settles) and both are
real. The envelope pin is deliberately loose so it catches drift out of physical range without
pretending the 8.5° is resolved. **Needs an owner call — see the open question below.**

*Original entry:*

`atomistic.py:583`, −32°, "calibrated by overlaying the atomistic model on the NADOC bead/slab
representation" — a constant whose stated purpose is to align atoms to the DISPLAY.  It is now
summed with the measured junction-balance term inside `atomistic_phase_offset_rad`, so retiring it
means re-deriving that **sum**, not just deleting a number.

- **Gate:** `_FRAME_ROT_RAD` is locked and declared so at `atomistic_minimisers.py:28`; retiring
  the pair means re-quoting ~300 1ZEW coordinates **and** moving `_extra_base_frame` in the same
  commit — which is Phase 7's territory.
- **Acceptance:** `test_atomistic_geometry_lock` goldens must be regenerated ONCE with the atom
  displacement measured directly (LESSONS H19: never accept a regenerated golden as the proof).

### Phase 10 — the standalone atoms→sites converter  ⟨no consumer yet; do on demand⟩

Phase 5 built the measured producer with the axis as an INPUT.  A converter that also **fits** the
axis — turning a bare PDB or a relaxed trajectory into sites with no design to lean on — was
deliberately not built because nothing asks for one.

- **Entry point when something does:** `site_from_bead`'s axis argument.
- **Reconcile, do not add a third:** `pdb_to_design.py:521` and `pdb_import.py:843` are the two
  existing axis fitters; `atomistic_to_nadoc.extract_from_pdb` reads P atoms → bead positions and
  nothing else.

