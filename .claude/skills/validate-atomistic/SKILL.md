---
name: validate-atomistic
description: Audit the atomistic (ball-and-stick / VDW) display of an oxDNA job's relaxed frame — every drawn bond and atom measured + flagged for invalid bonds, over-stretched sticks, hidden bonds, clashes, and stranded atoms. Use when the user invokes `/validate-atomistic` (optionally `/validate-atomistic <design-stem> [job_id]`) or asks to "check atomistic bonds", "validate the oxDNA atomistic display", "find bad/long bonds in the relaxed structure", or "is the ball-and-stick correct". Read-only measurement; never mutates topology.
---

# validate-atomistic

Run the **atomistic display validation oracle** against a design's latest oxDNA job. The principle this
skill enforces: **no visual element of the atomistic representation is un-validatable.** Everything the
ball-and-stick / VDW view draws under the **OxDNA-display** toggle — every bond (stick) and atom (sphere) —
is measured programmatically, including bonds the renderer *hides* (so a stretched bond you can't see on
screen is still queryable).

Default target is `workspace/6hb_sim_tests.nadoc`'s latest relaxed job; an argument overrides it.

## What it measures (oracle: `backend/core/atomistic_validation.py`)

The oracle reconstructs the atomistic model at the job's relaxed frame using the SAME
`build_atomistic_model(frame_override=…)` the renderer's rep-enable build uses, so the audited bonds ARE
the rendered bonds (identical serial pairs). Every bond is classified by what governs its geometry:

| class | what it is on screen | validity rule |
|---|---|---|
| `rigid` | sticks inside one base (sugar ring + base + glycosidic) | **frame-invariant** — must equal the design template to `intra_rigid_tol_nm` (5e-3 nm). A deviation is a **rigid-stamp violation = a placer bug** (expect **0**). |
| `linker` | C3'–O3' / P–O5' / O5'–C5' at a residue (the phosphate atoms the crossover/nick/skip bridge minimiser may relocate) | flagged if absolute length > `covalent_max_nm` (0.20 nm) — an over-stretched stick. |
| `backbone` | the O3'→P stick between consecutive nucleotides on a strand | flagged if length > `backbone_stretch_nm` (0.30 nm). |
| `bridge` | the O3'→P that reaches across helices (crossover / nick) | flagged if length > `backbone_stretch_nm`. |

Plus: `hidden_by_renderer` (bonds > `render_hide_nm` = 1.0 nm, drawn as nothing but listed), `clashes`
(non-bonded atoms < `clash_nm` = 0.08 nm), `bad_atoms` (non-finite positions).

**Inter-base geometry (`base_geometry`)** — bond lengths alone are blind to a nucleotide that is internally
rigid + backbone-connected yet MIS-PLACED relative to its neighbours. So the audit also measures, on the C1'
atoms: **WC-pair C1'–C1'** (designed (h,bp) with both strands → B-DNA ~1.05 nm) and **consecutive-base
stacking C1'–C1'** (~0.5–0.7 nm). `wc_collapsed` fires when the median WC C1'–C1' falls below
`wc_collapse_nm` (0.70 nm) — the bases are crushed onto their partners (the "bonds to opposite/adjacent
bases" symptom). This is the check that catches a base-positioning regression (e.g. an orientation/
calibration bug) that the bond-length checks miss; a clean run needs WC C1'–C1' ≈ 0.9–1.0 nm.

## How to run

```bash
just audit-atomistic                                 # 6hb_sim_tests, latest job (human-readable)
just audit-atomistic 18hb2 --json                    # args pass through
uv run python scripts/audit_atomistic.py             # same, directly
uv run python scripts/audit_atomistic.py 18hb2       # another design stem
uv run python scripts/audit_atomistic.py 6hb_sim_tests c1299e0b07b5   # explicit job
uv run python scripts/audit_atomistic.py --json      # machine-readable (exit 1 if not ok)
uv run python scripts/audit_atomistic.py --no-align  # audit the un-aligned (own-frame) display
```

Programmatic / live-app query (the running backend): `POST /api/oxdna/jobs/{job_id}/display-atomistic-audit?align=true`
returns the same report for the frame the app is displaying.

### Trajectory frames (View-trajectory scrub)

The single-frame audit above covers only the relaxed *display* frame. The **View-trajectory** scrubber
shows EVERY composite-trajectory frame (whole lineage: relax stages → production → field children) through
the *same* display reconstruction, so the settled fixes (rigid stamp, forward/reverse phase, backbone
closure, identity) must hold on **every** frame, not just frame 0. Audit a sampling of them:

```bash
just audit-trajectory                                # 6hb_sim_tests latest job, 8 evenly-sampled frames
just audit-trajectory 6hb_sim_tests c1299e0b07b5     # explicit job
just audit-trajectory 6hb_sim_tests c1299e0b07b5 --json
```

Route: `POST /api/oxdna/jobs/{job_id}/trajectory-audit` (body `{frame_indices?, max_audit}`) — `frame_indices`
audits exactly those composite-frame indices (what you'd assert after scrubbing to a specific frame), omit it
to evenly sample `max_audit`. The per-frame **pass gate** (`summary.all_invariants_ok`) is the
reconstruction-correctness set only: **0 rigid-stamp violations, no `wc_collapsed`, no `wc_helix_imbalanced`
(forward/reverse phase balanced), no non-finite atom, identity preserved**. Over-stretch + clash counts are
reported per frame as quality metrics but are NOT a gate — a raw (un-minimised) CG trajectory frame carries
100s of inherent 0.3–1.0 nm backbone over-stretches (the >1 nm ones the renderer hides), the same roughness
the single relaxed frame shows; only a *true* soundness break fails a frame. Oracle:
`atomistic_validation.audit_trajectory_frames` (core `oxdna_health.composite_trajectory` frames).

## Steps

1. **Resolve the target.** Argument `<stem> [job_id]` → that design/job. No argument → `6hb_sim_tests`
   latest. Confirm a relaxed job exists (`latest_job_for_design`); if none, say so — there is nothing to
   audit until the user runs a relaxation.
2. **Run** `uv run python scripts/audit_atomistic.py <args>` and read the report.
3. **Interpret against the bright line** (below). Lead with the verdict and the load-bearing number
   (`rigid_stamp_max_dev` + violation count), then the dominant failure class.
4. **Route findings:**
   - `n_rigid_stamp_violations > 0` → a **reconstruction/placer bug** (the rigid stamp is not frame-
     invariant). Investigate `_oxdna_rigid_frame` / the calibration in `backend/core/atomistic.py`. This is
     a real defect, not relaxation.
   - Over-stretched `backbone` / `bridge` / `linker` bonds with `rigid_stamp` clean → **inherent CG→atomistic
     backbone discontinuity** (oxDNA's one-bead-per-nucleotide frames don't enforce all-atom backbone
     continuity, so O3'→P sticks open up). NOT a placer bug. If the user wants these *fixed* (not just
     measured), that is a new feature (display-time backbone closure / mini-minimisation) → add it to
     `design_automation_backlog.md`, do not hack it in here.
   - A **new visual element** appears in the atomistic rep that the oracle doesn't yet measure → extend
     `atomistic_validation.py` + its tests, and (if it needs a route / frontend introspection) add an AF
     item. The standing requirement: every drawn element stays validatable.

## The bright line

This skill **measures and classifies**; it does not declare geometry "fine" by eye. A clean run means:
`n_rigid_stamp_violations == 0` (placer correct) **and** no over-stretched bonds **and** no clashes **and**
no stranded atoms. The verdict `INVALID` with `rigid_stamp` clean tells the user precisely *which* class of
visual artifact is present and that it is a geometry/relaxation issue, not a reconstruction bug — that
distinction is the whole point.

## Reach for / not

- **Reach for it** to check whether the atomistic display of a relaxed structure is geometrically sound,
  to quantify the long/stretched bonds seen on screen, or to regression-check the rigid-frame placer.
- **Not** for the CG-bead display (that path renders beads, not atoms — different validation), nor for
  *fixing* stretched backbones (that's a feature → the AF backlog), nor for topology validation
  (`validate_design`).

## Strand/residue identity (NADOC → oxDNA → atomistic)

The renderer applies relaxed positions by `atom.serial` onto atoms whose colour/strand/residue come from a
SEPARATE build. If those two builds are different topologies, every serial maps to the wrong atom →
scrambled colours/bonds/positions. Two guarantees keep identity intact, both tested:
- **Backend reconstruction is identity-preserving:** `build_display_model` is identical, atom-for-atom, to
  `build_atomistic_model(design)` in serial → name/element/residue/strand_id/helix/bp/direction + bond list
  (`test_strand_identity_preserved_nadoc_to_atomistic`). Only positions differ.
- **Topology guard at the display boundary:** `display-atomistic` returns the JOB snapshot's `topology_hash`;
  the renderer rebuilds from `GET /oxdna/jobs/{id}/atomistic-model` (the job's own atoms+bonds) before
  overlaying positions — so a design EDITED after the job ran (different sequence → different atoms/serials)
  cannot scramble the overlay. If you ever see wrong COLOURS on an oxDNA atomistic overlay, suspect this:
  compare `atomistic_reference_topology_hash(active_design)` vs the job's.

## Files

- Oracle: `backend/core/atomistic_validation.py` (`audit_bonds`, `audit_oxdna_job`, `audit_trajectory_frames`,
  `latest_job_for_design`, `relaxed_frame_for_job`) — reusable + unit-tested in `tests/test_atomistic_validation.py`.
- CLI: `scripts/audit_atomistic.py` (`--trajectory` for the per-frame scrub audit). Routes:
  `POST /oxdna/jobs/{id}/display-atomistic-audit` (single frame) + `POST /oxdna/jobs/{id}/trajectory-audit`
  (sampled composite frames), both in routes_oxdna.
- Reconstruction it validates: `oxdna_health.frame_atomistic_flat` → `atomistic.build_atomistic_model
  (frame_override=…)` → `_oxdna_rigid_frame`. Renderer cutoff it mirrors: `atomistic_renderer._MAX_BOND_NM`.
- Deeper coverage tracked in `design_automation_backlog.md` (Tier-F AF items: live renderer-state
  introspection — assert the renderer HIDES exactly the bonds the audit flags).
