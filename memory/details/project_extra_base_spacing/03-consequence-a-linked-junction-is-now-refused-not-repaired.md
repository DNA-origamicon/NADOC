# ⚠ Consequence: a linked junction is now REFUSED, not repaired — supporting detail

[Topic head](../../project_extra_base_spacing.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### ⚠ Consequence: a linked junction is now REFUSED, not repaired

With nothing adjusting positions, **3 of 14 phases on the reciprocal fixture catenate** (T bp16,
T bp18, TT bp16) and the build threads 2 covalent bonds through rings on TT/bp8. The repair that
used to drive both to zero is gone. `gate_seed_topology` still detects them, so such a design now
**raises instead of building a seed** — the defect cannot reach a trajectory silently, but the
design cannot be packaged either until its phase changes.

Tests were rewritten around the property that survives: a linked phase must be refused
(`test_a_linked_phase_is_refused_rather_than_re_placed`, `test_a_catenating_phase_cannot_reach_a_seed`).
The old "the repair guarantees Lk = 0" contract is deleted — it was a promise the code no longer
makes. `_WOUND_BP`/`_CLEAN_BP` in `test_junction_winding` exist because a wound build and a clean
one are now two different PHASES, not two settings.

## Opt-in seed pre-expansion (`seed_lattice_nm`) — still live

`POST /md/jobs` takes `seed_lattice_nm`: `null` (default, build as designed), `"auto"`, or a float
in nm. It scales a **copy** of the design's helix axes laterally about the bundle centroid before
anything reads geometry (`lattice.scale_helix_spacing`), so the topology gate, atomistic model, box
sizer and every exported map describe one structure. Saved `.nadoc` and `HONEYCOMB_LATTICE_RADIUS`
are untouched. Recorded in `manifest.json` — a trajectory from a pre-expanded seed is **not**
comparable to one that swelled into its spacing.

**Measured effect** (6hbx100; bonded-excluded insert contacts < 3 Å, O3′–P bridge p99):

| design | spacing | insert contacts | bridge p99 |
|---|---|---|---|
| noT | 2.25 → 2.45 | 0 → 0 | 2.67 → 3.09 Å ✗ |
| 1xT | 2.25 → 2.53 | 3428 → 2586 (−25%) | 1.93 → 3.18 Å ✗ |
| 2xT | 2.25 → 2.55 | 14283 → **6058** (−58%) | 2.37 → **1.80 Å** ✓ |

The benefit scales with insert count and the bridge cost **inverts**: two inserts carry enough
contour to span 2.55 nm so the bridges actually relax; one insert is stretched by 2.53; with none
there is nothing to relieve and the backbone only stretches. **That is why `"auto"` declines an
insert-free design.** Not default-on: at 1xT it is a genuine trade, so the caller picks.

(These contact numbers predate the CG-placement purge and were measured against the then-current
arc pose. The *direction* of each effect is a lattice property and still holds; re-measure before
quoting an absolute.)

## The ATOMISTIC reps show the MD seed — still live

`GET /design/atomistic?seed_lattice_nm=auto` returns the **t=0 pre-minimisation** coordinates for
the whole model. Absent the param it is the old display build, unchanged. Seed mode differs by:
exact L-BFGS-B linkers instead of `fast_bridges`' cheap interpolation (which moves the ~1.5%
phosphodiester atoms by up to 2.4 Å at junctions); no flexible-display frame override; and optional
lattice pre-expansion. Measured on 6hbx100_2xT: same 29 629 atoms, **mean 3.17 Å per-atom shift**
display → seed. ~26 s then `build_atomistic_model_cached` serves it in 0.07 s.

`atom_surface_display.setSeedLattice(nm|null)` swaps the URL and drops `_atomDataCache`;
`expanded_spacing` drives it from the toggle. **`_applyAll` must NOT also call `applyUnfoldOffsets`
on the atomistic renderer while seed mode is live** — those atoms were BUILT at the expanded
lattice and offsetting them again doubles the expansion. `isSeedLatticeActive()` guards it.
**Refused for a PDB-imported design** (409): measured coordinates that no lattice scale applies to.

### ⚠ Pre-existing: returning to t=0 FLATTENS the insert chain (0.168 nm)

`unfold_view._updateArcPositions` places the extra-base beads on the arc LINE's control point —
`dist * MAX_BOW_FRAC * t`, i.e. **straight at t=0** — while `buildCrossoverConnections` built them
at their own `BOW_FRAC_3D = 0.3`. Any return to t=0 collapses the bow. Measured **0.168 nm,
identical via the Q expand toggle**, which predates this work; unfold has it too. Not fixed: the
two modules use different bow-direction conventions and guessing is how this area goes wrong.

### The CG bead / atomistic ~5 Å register gap — DIAGNOSED 2026-08-05

CG backbone bead → atomistic P atom is **5.02 Å mean** at the design lattice (5.05 Å scaled, so the
lattice is not the cause). The bead's *nearest* atom is not consistently a backbone atom: C3′ for
632 residues (2.9 Å), O5′ for 272 (2.8 Å), but for ~350 residues it is a **base** atom — N7 at
6.1 Å, N4 at 4.6 Å, C7 at 4.4 Å.

The dedicated audit session ran. **Two independent defects**, both now measured — full write-up +
numbers + provenance in `backend/core/measured_positioning.py`, pinned by
`tests/test_measured_positioning.py`:

1. `geometry.py` flips the groove sign with the helix's lattice cell, so FORWARD cells build at
   150° and REVERSE at 210°. Both stay right-handed, so these are **not enantiomers** — they are
   two right-handed helices with the minor groove on opposite sides, one marking the major groove
   as the minor. A wrong-side-marker defect, not a wrong-molecule one, and it is confined to the
   CG bead layer (atomistic's per-cell correction equalises both). On a mixed design the P–P
   separation reads **180° ± 30°**, the ±30 being purely the cell-type split.
2. `atomistic.py`'s 208.2° correction is applied to the template **frame origin**, but the
   template's P sits 0.1887 nm off that origin and the two strands' frames are z-mirrored → the
   two phosphates rotate *toward* each other. Realised separation **183.84°**, exactly
   208.2 − 2×12.182, identical at every bp in both cell types.

Together: ~0.1 nm radial + 26–34° azimuth at r ≈ 0.93 = the 5 Å.

**Measured truth** (`scripts/measure_cg_registration.py`, free `MGHH_only` stage of job
`dbd8ad3b7d4f`, phosphate-cylinder axis fit; estimator reproduces 1ZEW at 208.5°/0.881 nm):
P **0.925 nm**, C1′ 0.566, base-ring centroid **0.324**, C1′–C1′ 1.074, rise 0.347, twist 34.21°.
The CG base bead sits at **0.714 nm** against a measured 0.324 — the largest single error found.

**The atomistic rep cannot be fixed by re-placement.** Built vs measured: P −0.023, C1′ −0.073,
base centroid +0.027 — mutually inconsistent under every whole-body transform (a rigid move onto
the P cylinder opens WC 0.309→0.355 nm; a radial affine fit to P+C1′ throws the base centroid to
0.442). It is a **template** defect → re-extraction, the never-executed recipe in
[[project_o3prime_investigation]].

Shipped: **Help ▸ New Positioning** (display-only, default OFF) re-places the *full* rep onto the
measured geometry. ⚠ `pp_separation_deg = 183.9` is **PROVISIONAL** — every trajectory in this repo
was seeded at 183.84°, so the MD cannot arbitrate it. `experiments/exp52_groove_seed_sweep`
(4 arms seeded 150/184/208/232°, solvated and queued, not yet run) is the test that settles it.
