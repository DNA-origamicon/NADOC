# Lattice-specific extrusion lengths and square VR validation

The right-hand Extrude menu derives its two button increments from the part:

| Part lattice | Small buttons | Large buttons | Wheel detent |
| --- | --- | --- | --- |
| Honeycomb | −7 / +7 bp | −21 / +21 bp | 7 bp |
| Square | −8 / +8 bp | −24 / +24 bp | 8 bp |

Button actions add/subtract exactly their displayed increment and clamp at zero
and the existing maximum. Labels and actions share the lattice-step definition.
The paired layout and horizontal trackpad navigation are retained. ScryWrite's
wheel correction uses the corresponding small step rather than assuming 1 bp.

The fresh-part tour now supports `--lattice square` and `--lattice honeycomb`.
With `--validate` and no lattice argument it runs both lattices through all four
unchanged human-motion profiles. The normal demo still defaults to honeycomb.

Square verification creates an empty square part using File → New, paints six
cells in a 2×3 rectangle with VR triggers, exercises both directions of both
button increments, operates the wheel, and commits six 48 bp helices. An
independent browser-side geometry check verifies the exact cell addresses and
2.25 nm perpendicular square-grid pitches. The same case checks local native
view-volume representation, desktop visibility, and saving/reloading the square
part. No fixture or user workspace part is edited.

The first attempt stopped at a new test assertion that omitted ScryWrite's
`RIGHT / … [control-id]` label wrapper. Its capture already showed correct
±8/±24 labels. The assertion was corrected to require the exact exported label;
no production geometry, acquisition tolerance or motion profile was changed.
That failed evidence remains in `square-validated-20260928`.

Evidence is native submitted stereo output and simulated controller input through
the physical VR runtime; it does not establish human headset comfort.

## Verified results

- All 44 native tests passed, including production sidebar increment/decrement
  actions for both lattices, zero clamping, and label/layout checks.
- All 27 focused Python tests passed, including one-click 7/8 bp wheel
  corrections in both directions and rejection of unreachable partial steps.
- Square ScryWrite tours passed with steady_fast, steady_deliberate,
  variable_fast and variable_deliberate. Each saved a square part with exactly
  six 48 bp helices at the expected grid addresses and survived reload.
- Both steady profiles reached 48 bp in one wheel drag. Both variable profiles
  overshot to 56 bp, then corrected with one −8 click. These attempts are retained.
- Submitted-eye captures were reviewed for the square painting grid, ±8/±24
  controls, and the committed model after framing with its subsection volume.

Square evidence: `.development-artifacts/vr-extrude/square-controls-validated-20260928/`
(`result.json`, `summary.json`, test logs and per-profile stereo/motion evidence).

The headed honeycomb steady_fast regression also passed with the updated ±7/±21
buttons, the canonical circular six-helix footprint, 42 bp lengths, local volume
rendering and save/reload. Evidence:
`.development-artifacts/vr-extrude/honeycomb-steps-20260928/`.
All test-owned viewers and temporary workspaces were cleaned up. Focused Ruff,
JavaScript syntax checking and `git diff --check` passed.
