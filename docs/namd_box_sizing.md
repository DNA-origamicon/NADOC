# NAMD box sizing and periodic-image preview

## Choosing a box

In **Simulations → NAMD → Box and solvent**, select:

- **Recommended · 2 nm per face**: fits the current structure's axis-aligned
  bounding box and resets requested padding to 2 nm on each face. Padding remains
  editable. Selecting Recommended again resets it to 2 nm.
- **Current orientation · custom padding**: uses that bounding box with the
  requested padding.
- **Allow any orientation**: fits a cube around the structure's rotational
  envelope, then adds the requested padding on each side. This is a geometric
  envelope, not a rotational-diffusion estimate.
- **Custom dimensions**: uses explicit X/Y/Z lengths; preparation validates fit.

The 2 nm default provides 4 nm initial separation between opposing bounding
envelopes. This is consistent with the water-buffer criterion in
[Yoo & Aksimentiev (2013), Materials and Methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC3864285/).
It does not guarantee clearance throughout NPT contraction, deformation or rotation.
Existing production/submission clearance guards and explicit overrides remain active.
Saved presets can explicitly select a different mode or padding.

Preview and preparation preserve requested padding, sizing mode and explicit axes.
They do not trim padding to a hardware atom cap, replace rotation sizing with a
bounding box to fit memory, or substitute a smaller box based on free-run duration.
Their former automatic-trimming/fallback warning is removed. Hardware capacity
checks may reject a run, but do not authorize changing its solvent geometry.
Existing packages retain their original dimensions and audit metadata.
Surface-control and two-electrode boundary rules remain unchanged.

## Requested padding versus measured clearance

Requested padding is added to the selected envelope. The six displayed **water
clearances** instead measure the distance between actual solute bounds and each
box face. For axis i:

- Negative face: solute_min[i] − (box_center[i] − box_length[i]/2).
- Positive face: (box_center[i] + box_length[i]/2) − solute_max[i].

For a centered structure, both equal (box_length − solute_extent)/2. Rotation-sized
or custom boxes can have very different clearances along each axis. Negative values
mean the bounds extend beyond a face. These are geometric distances, not water
molecule counts. Pending/unavailable previews clear the old readout. Slab water
clearances use the liquid compartment, excluding vacuum padding.

## Display controls

**View details** shows the cell, dimension labels, water-region highlights and
solvent conditions. **View periodic images** occupies a separate row below it and
works independently, but only in **Full** representation.

Periodic images are six non-interactive backbone point copies translated by ±Lx,
±Ly and ±Lz. They share one geometry/material, with at most 12,000 sampled points
per copy. No solvent, corner or edge neighbors are duplicated. Zoom out and orbit
to inspect farther neighbors. For slab setups, normal-axis translation uses the
full vacuum-padded cell.

The copies follow displayed backbone positions and instance colors once per
rendered frame, supporting Full-mode trajectory, deformation and scalar-color
visualizations. Their translations still use the preparation cell, not a changing
trajectory cell. This is a visual shape/spacing aid, not an atomistic contact test.

Switching away from Full unchecks the toggle and removes the copies. Returning to
Full re-enables the control without checking it. A new document resets both display
toggles. Invalidating the preview hides the copies until recalculation completes;
disabling the toggle or disposing the controller releases rendering resources.

## Implementation and verification — 2026-09-22

Sizing: `backend/core/md_box_preview.py`, `backend/core/namd_solvate.py`.
Controls: `frontend/src/ui/md_box_solvent.js`.
Ghost rendering: `frontend/src/scene/md_periodic_images.js`.
`free_ns` and `devices` remain accepted by preparation for caller compatibility;
free duration is provenance, not an automatic sizing policy. `main.js` LOC delta: 0.

- Backend sizing/policy/clearance checks: 76 passed, one native test deselected.
- Backend `test-smart`: `FAST (fast suite only)`; 8,811 passed, seven failed,
  seven skipped. The seven failures require missing photoproduct archive fixtures.
- Latest frontend suite: 6,752 passed across 489 files.
- Latest browser smoke/feature checks: all 24 passed, including actual box dimensions,
  face clearances, shared periodic geometry, separate rows, and Full→Beads→Full.
- Ruff and diff-whitespace checks passed; browser test artifacts were removed.
- No native simulations launched. Human visual-legibility follow-up remains
  recorded as `MV-PERIODIC-IMAGES` in `manual_validation_debt.md`.

The backend's deferred heavy-suite report remains:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
