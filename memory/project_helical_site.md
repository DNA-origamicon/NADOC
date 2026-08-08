---
name: helical-site
description: "PLAN, Phases 0-2 DONE: one HelicalSite abstraction — axis point + tangent + radial + labels — that every representation (CG bead, atomistic stamp, oxDNA particle, mrDNA bead, FEM node) derives from cheaply, replacing four independent re-derivations of the same helix formula."
metadata:
  node_type: memory
  type: project
---

# One helical site, many cheap representations

**Status: Phases 0, 1 and 2 DONE (2026-08-07). Phases 3–6 not started; Phase 3 (the periodic
seam solver) is next and is byte-exact.** Owner instruction: *"why not have a unified abstraction then?
From which all representations and models can be built from cheaply"* — yes, and this is what
that costs. Companion to [[project_atomistic_source_of_truth]] (whose audit table this is the
remedy for) and TD-27 in [[project_tech_debt]].

## The idea in one paragraph

A designed nucleotide's geometry is seven numbers: the point on the helix axis it belongs to,
the axis tangent there, the outward radial direction at its helical phase, and its labels
(bp index, strand, loop copy). Every representation is that site projected at some radius,
after some rotation, into some frame. Nothing needs to be built from anything else, and no
projection costs more than a few arithmetic ops per nucleotide — which is the answer to *"is
deriving CG from atomistic expensive?"*: it would be, and it is also unnecessary.

## What a site is

```
HelicalSite: helix_id, bp_index, direction, copy_k,
             axis_point (3,), axis_tangent (3,), radial_hat (3,), azimuth_rad
```

`radial_hat` is redundant with `azimuth_rad` + the helix frame, and is carried anyway: it is
what every consumer actually multiplies by a radius, and carrying it is what makes each
derivation **byte-exact** rather than ULP-close. That matters more than it sounds — see Risks.

## Every representation, as a projection

| Representation | Radius | Rotation off the site | Frame |
|---|---|---|---|
| CG backbone bead (legacy) | `HELIX_RADIUS` 1.000 | 0 (FWD) / ±150° by lattice cell (REV) | — |
| CG bead, measured mode | 0.804 | groove-registered | — |
| CG base bead | 1.000 − `BASE_DISPLACEMENT` | along the cross-strand direction | — |
| Atomistic P | `_ATOMISTIC_P_RADIUS` 0.886 | +58.2°/−1.8° by cell, then `atomistic_phase_offset_rad` | template stamp |
| oxDNA particle | CM radius | the same, plus the a1/a3 convention | (CM, a1, a3) |
| mrDNA bead | 0 (bp midpoint) | — | 3×3 orientation from (radial, tangent) |
| FEM node | 0 (on the axis) | — | — |

## Two producers, one site type

- **P1 — lattice (analytic).** DONE on both paths: `geometry.nucleotide_positions` carries
  `radial_hat` / `axis_point` / `azimuth_rad`, and `nucleotide_positions_arrays` (plus both
  `_extended` variants and the loop/skip fallback) carries `radial_hats` / `axis_points` /
  `azimuths`. It survives cluster transforms and bends — see Phase 1.
- **P2 — measured (from real atoms).** Does **not** exist. `atomistic_to_nadoc.extract_from_pdb`
  is thinner than it looks: it reads P atoms → bead positions in nm and nothing else — no axis,
  no phase. A measured producer needs a per-helix axis fit plus a per-nucleotide radial. Two
  axis fitters already exist to reconcile rather than duplicate (`pdb_to_design.py:521`,
  `pdb_import.py:843`).

P2 is what makes this a unification rather than a tidy-up: with it, a relaxed oxDNA frame, an
MD trajectory frame and an imported PDB all become sites, every representation derives from a
site regardless of provenance, and the `atomistic._phase_invalidated` special case (added
2026-08-07 — "this nucleotide moved, throw the analytic phase away") disappears, because a
moved nucleotide simply has a measured site.

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

### Phase 3 — the periodic seam solver reads the axis instead of inverting for it
`periodic_polymer._section_frame_from_arrs` (`:149-170`) solves a 2×2 to recover the axis from
two beads, assuming `HELIX_RADIUS` and the ±150° groove. Its own comment says it is "only
correct for beads the geometric layer placed" and that measured positioning must never be
pushed into `geometry.py` or it silently returns a wrong axis. With the site it just reads
`axis_point`, and that whole fragility class is retired.
- **Acceptance:** `test_the_periodic_seam_solver_still_gets_a_valid_axis` green; frame equal to
  the old solve within 1e-12 on the periodic fixtures.

### Phase 4 — the oxDNA seed boundary  (**the only phase that may move numbers**)
`nuc_conf_line` writes the CG `backbone_position` into the conf's first three floats, which are
the **centre of mass** — different landmarks. With sites, the CM becomes a projection at its own
radius. LAMMPS inherits it.
- **Gate:** needs an owner decision (CM from the atomistic mass centroid, or from the inverted
  `oxdna_backbone_site`? they differ) plus a FENE re-measure through `oxdna_health` with the
  **site-based** metric, never a CM-based one. Keep out of Phases 1–3 so those stay byte-exact.

### Phase 5 — the measured producer (P2)
Atoms → sites (axis fit + per-nucleotide radial), then retire `_phase_invalidated` and the
bead-derived fallback branch in `_atom_frame`.
- **Acceptance:** a relaxed-display build byte-identical to today's through the new path.

### Phase 6 — `_rigid_frame_calibration` off sites
`atomistic.py:964` builds a synthetic design, writes an oxDNA conf **from `_geometry_for_design`**,
reads it back and Kabsch-fits against `build_atomistic_model` — a CG→atomistic round trip baked
into a cached constant. Feed it sites instead. Its `assert m_res < 1e-6` is the tripwire and the
acceptance criterion at once.

## Explicitly out of scope

- **Pose fitters** (`direct_relax`, `linker_relax`, `duplex_cluster`) — they fit against beads
  and write **persisted** `cluster_transforms`, so this is a migration problem for saved files,
  not a geometry problem. TD-28.
- **Extra-base and extension-tail placers** — `atomistic.py:3036` interpolates between the two
  junction nucleotides' CG beads *on purpose* ("the CG view is the single definition of where an
  extra base sits"). It is the one place a display decision reaches an exported atom, and it
  needs its own decision, not a refactor.
- **`_ATOMISTIC_PHASE_OFFSET_RAD = −32°`** — retiring it is gated on the placers above.
- Making the CG bead a literal function of atom positions. It would move the full rep by 15–46°
  (the correction chain) and cost an atom build per geometry request. The owner has ruled the
  current reps correct; siblings off one site is the design.

## Risks, each with its countermeasure

1. **ULP drift is not cosmetic here.** The scalar path uses `math.cos`, the array path
   `np.cos`, and they differ at the last ULP — `_strand_beads`' docstring says so. Downstream,
   the backbone-bridge L-BFGS-B solve amplifies a last-ULP change into 0.1–1.3 Å at junctions
   (LESSONS H15/H19). **Countermeasure:** each path carries the radial *it* computed; never
   share one path's value with the other, and never accept a regenerated golden as proof —
   measure the atom displacement directly, as Phase 0 did (0.000e+00 nm).
2. **The skip fallback splits the paths.** `nucleotide_positions_arrays` delegates
   loop/skip-bearing helices to the scalar path (`geometry.py:382`). A site added to only one
   producer makes skip-bearing designs disagree with everything else. Phase 1 must cover it,
   and its acceptance fixture set must include one.
3. **A phase that quietly changes numbers.** Only Phase 4 is allowed to. For 1, 2, 3 and 6 the
   bar is `np.array_equal` / byte-identical output, and anything else is a bug in the phase.
4. **Deformation and cluster transforms.** Sites are straight-lattice quantities; deformation is
   applied downstream. Do not let a consumer read a site and skip the deformation pass — that is
   how `mrdna_bridge` ended up re-deriving from the straight helix in the first place.

## Open question for the owner

Phase 4's CM definition (mass centroid of the atomistic nucleotide, vs the inverted
`oxdna_backbone_site` off the phosphorus). They differ, and it is the one number in this plan
that a simulation will feel. Everything else is a refactor with an equality test.
