# Lattice window controls — 2026-09-28

The length-button values below describe the initial window-control revision.
They were subsequently updated to lattice-specific steps; see
[the square extrusion audit](vr_square_extrude_20260928.md).

The extrusion length wheel is attached to the lattice window. It follows the
window's position, orientation and size and stays available without the legacy
settings menu. The Extrude sidebar pairs −21/+21 and −1/+1 controls, retaining
individual ray targets and horizontal trackpad navigation.

Grip behavior:

- One grip on the window border moves and rotates the window. Two border grips
  resize it, including the wheel.
- Grip inside the painting area with each controller, then spread/pinch to zoom
  the lattice. The first grip waits for the second without moving the scene.
  Painted addresses, window placement and the part remain unchanged.
- Interior acquisition accepts controller origins within 9 cm on either side of
  the panel. The existing 7.5 cm border proximity takes priority near the frame.
  Interior hover shows a yellow cross; a held grip is green. Once acquired,
  grips stay latched outside the acquisition band until release/tracking loss.
- Zoom uses separation projected onto the window plane; depth motion alone
  does not change zoom. Window and content size have separate state.
- Outside these targets, grips retain normal scene manipulation.

The initial steady_fast experiment acquired content zoom at 0, ±4 and ±7 cm
and rejected ±13 cm. It exposed competing border acquisition between the
painter and the sidebar. The painter now spawns with enough separation for its
wheel and border targets, and an active painter gesture retains ownership.
Failed evidence remains in `lattice-pilot-1`; the motion profiles and thresholds
were not changed to disguise that failure.

Validation runs use the existing isolated fresh-part Extrude tour. It paints the
canonical six-helix ring, checks zoom at all seven depths, verifies border
movement/resizing and painted-cell preservation, operates the wheel to set
42 bp, commits the model, checks local view-volume rendering and saves/reloads
in a temporary workspace. Existing fixtures and user parts are not modified.

ScryWrite evidence is submitted native stereo output and applied simulated
controller input through the physical runtime. It does not establish headset
comfort or through-lens readability for a human operator.

## Measured depth comparison

All four unchanged controller profiles completed five intended acquisitions each
(at 0, ±4, ±7 cm) plus two outside negative controls (±13 cm). Reclassifying the
same measured acquisition poses by depth gives:

| Symmetric depth band | Intended two-hand acquisitions inside band |
| --- | ---: |
| 5 cm | 11 / 20 |
| 7.5 cm | 19 / 20 |
| 9 cm (production) | 20 / 20 |

The variable_deliberate profile reached 7.69 cm on a requested 7 cm acquisition,
so using the border's 7.5 cm tolerance for the interior would miss that sample.
All eight outside checks rejected both hands. All four profiles passed border
movement/resizing with the grid zoom unchanged. This small deterministic sweep
supports the 9 cm default; it is not a population estimate of human success.

Evidence: `.development-artifacts/vr-extrude/lattice-validated-20260928/`, including
`depth-comparison.json`, per-profile `extrude/lattice-grips/grips.json`, submitted
stereo captures of grid scaling/window resizing, and wheel motion records.
Both variable profiles overshot the wheel from 0 to 49 bp and used seven ordinary
−1 bp clicks to reach 42 bp; their overshoots and corrections remain in
`wheel-profile.json`. Both steady profiles reached 42 bp in one drag.

## Final verification

- 44 native CTest cases passed, including paired-row navigation, interior vs
  border ownership, signed depth checks, tracking loss, projected zoom, and
  wheel availability with the legacy menu closed.
- 23 focused Python tests passed; focused Ruff and `git diff --check` passed.
- The headed steady_fast demo passed (`lattice-pilot-2`).
- All four complete fresh-part ScryWrite tours passed in
  `lattice-validated-20260928`: steady_fast, steady_deliberate, variable_fast and
  variable_deliberate. Each includes the canonical 42 bp 6HB, local volume
  rendering and save/reload verification. Test-owned viewer and temporary
  workspace were cleaned up.
- Submitted-eye captures were visually reviewed for grid scaling, the attached
  wheel after window movement/resizing, and the paired length controls.

Launch the updated demonstration or validation from **Debug → VR Tours & Tests →
Tools · Authoring → Extrude a 6HB and inspect a volume**.
