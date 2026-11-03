---
name: crossover-catenation
description: "Crossover extra bases can be built topologically CATENATED (Gauss Lk = ±1) at reciprocal pairs. Detector + hard build GATE. The repair and the joint solve were DELETED 2026-08-05 — a linked phase is now refused, not fixed."
metadata:
  node_type: memory
  type: project
---

# Catenated crossover junctions — detector and gate

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Catenation detection was retired August 11; ring piercing and heavy-atom clashes remain active diagnostics (see the status text). Historical detector/repair recipes below are evidence, not authorization to restore the retired gate.

> **⚠ SUPERSEDED IN PART, 2026-08-05.** Everything below about the *joint solve* and the
> *verify-and-repair ladder* describes code that **no longer exists**. Extra-base positions are now
> a straight read of the CG representation and nothing modifies them afterwards
> (`extra_base_repair.py`, `_minimize_{1,2,3}_extra_base` and `solve_extra_base_pose` are deleted —
> see [[extra-base-spacing]]).
>
> **What still holds:** the detector, the Gauss-Lk measurement, the reciprocal-pair analysis, and
> the **build gate** (`gate_seed_topology`), which is now the only protection. **What changed:** a
> linked junction is **REFUSED** rather than repaired. Measured after the purge: 3 of 14 phases on
> the reciprocal fixture link (T bp16, T bp18, TT bp16), and TT/bp8 threads 2 covalent bonds through
> rings. Those designs cannot be packaged until their crossover phase changes.
>
> Read the rest as history — it is why the gate exists and how the defect behaves, not a
> description of the current builder.

**Status 2026-07-28: catenation FIXED and gated.** Every design screened is clean, including
24hb_2xT (170 reciprocal pairs). MD-validated on 2hb (see the archive); 6hb in progress
(`experiments/exp45_extra_base_catenation/`).

**Status 2026-07-31: a SECOND permanent defect of the same family — a covalent bond built
through a nucleotide RING — was found, and the catenation repair itself was manufacturing it.**
Detector + ranking term + gate shipped; every design in the workspace now builds with 0 of both.
See the ⭐ section below; that is the one to read if you are here about extra-base geometry.

<a id="what-was-wrong"></a>
- [What was wrong](details/project_crossover_catenation/01-what-was-wrong.md#what-was-wrong)

<a id="root-cause--the-joint-solve-not-the-pose"></a>
- [Root cause — the joint solve, NOT the pose](details/project_crossover_catenation/01-what-was-wrong.md#root-cause--the-joint-solve-not-the-pose)

<a id="-refinement-2026-08-05--the-joint-solve-is-the-dominant-cause-not-the-only-one"></a>
- [⚠ Refinement 2026-08-05 — the joint solve is the DOMINANT cause, not the only one](details/project_crossover_catenation/01-what-was-wrong.md#-refinement-2026-08-05--the-joint-solve-is-the-dominant-cause-not-the-only-one)

<a id="the-fix--verify-and-repair-backendcoreextra_base_repairpy"></a>
- [The fix — verify and repair (`backend/core/extra_base_repair.py`)](details/project_crossover_catenation/01-what-was-wrong.md#the-fix--verify-and-repair-backendcoreextra_base_repairpy)

<a id="-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permanent-defect-threaded-rings"></a>
- [⭐ 2026-07-31 — the repair ladder was manufacturing a SECOND permanent defect: THREADED RINGS](details/project_crossover_catenation/02-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permane.md#-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permanent-defect-threaded-rings)

- [⭐ 2026-07-31 — the repair ladder was manufacturing a SECOND permanent defect: THREADED RINGS — continued detail](details/project_crossover_catenation/02-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permane.md)

<a id="the-fix"></a>
- [The fix](details/project_crossover_catenation/02-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permane.md#the-fix)

<a id="-two-traps-in-inferring-connectivity-mid-build--both-produced-silent-wrong-answers"></a>
- [⚠ Two traps in inferring connectivity mid-build — both produced silent wrong answers](details/project_crossover_catenation/02-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permane.md#-two-traps-in-inferring-connectivity-mid-build--both-produced-silent-wrong-answers)

<a id="completed-history--archive"></a>
- [Completed history → archive](details/project_crossover_catenation/02-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permane.md#completed-history--archive)

<a id="detection-use-f_hi-never-the-modal-crossing-number"></a>
- [Detection: use f_hi, never the modal crossing number](details/project_crossover_catenation/02-2026-07-31--the-repair-ladder-was-manufacturing-a-second-permane.md#detection-use-f_hi-never-the-modal-crossing-number)

## Invariants to preserve

- All six geometry-lock hashes are **byte-unchanged** by the fix (verified, and re-verified
  2026-07-31 by rebuilding at `e810dd8` and `e810dd8^` — identical). The repair only touches
  geometry where a pair was actually linked, and no `Examples/` design has one. If a golden
  moves, the change leaked into the shared bridge minimiser.
  - **This fix was twice blamed for a failure it did not cause.** `3093b83` regenerated two
    goldens "after the catenation fix" and `ce1ef35` reverted them; the real cause was BLAS
    kernel dispatch differing between the two dev computers, not any commit. See
    [[LESSONS]] H19. `test_atomistic_geometry_lock.py` no longer hashes solver-placed atoms
    at all, so it can no longer implicate this fix that way — but the invariant above still
    holds and is still the right thing to check.
- The build must stay **byte-reproducible** — the ladder is a fixed, ordered search.
- The gate must never fire on the display path (`fast_bridges=True`) or the oxDNA-override
  paths; it lives in the packaging functions only.

<a id="where-things-are"></a>
- [Where things are](details/project_crossover_catenation/03-where-things-are.md#where-things-are)

## Open / adjacent

- **`n ≥ 4` inserts are NOT repaired** — there is no joint solve to bound, so the ladder has no
  lever. Rare (real designs use 1–2), and the gate refuses it rather than shipping it.
- **Fix B is not applied by the normal prep path.** `md_protocols` calls `write_hmr_psf` without
  `heavy_residues`, so an extra-base design prepped through the UI gets standard HMR, which
  *lightens* the dangling bases — the failure mode `project_extra_base_4fs_geometric_fixb`
  documents. Only `prep_24hb_seeded.py` (and now the exp45 harness) does it correctly.
- **`audit_bonds` crashes on 6hb_2xT** — `h.direction` is `None` at
  `atomistic_validation.py:166`. Pre-existing, unrelated.
- The oxDNA seed (`_resolve_extra_base_geometry`, straight chord lerp) has **not** been measured
  for catenation yet; unifying both engines on one placer is still open.
- **The pierced runs have not been re-run.** `2hb_2xT` (job `c8c4a87e2033`) needs rebuilding and
  relaxing from scratch — it has one reciprocal pair and that pair was the pierced one, so no
  junction observable from it is usable. `24hb_2xT` (`336a067ba241`, 51 piercings) is the source
  of `extra_base_co`.
- **The `n_ring_pierced_after` in the ladder summary is a scoped, per-pair count** taken at the
  winning rung, not a whole-model measurement — a pair cleared as a side effect of repairing its
  neighbour can read high. The manifest's `topology_check` is the authority.
- **`PierceScope` covers the reciprocal pair's neighbourhood, not the whole model.** A piercing
  between two crossovers that are not a registered reciprocal pair would be caught by the gate
  (build refused) but has no repair lever. Not observed on any design screened.
