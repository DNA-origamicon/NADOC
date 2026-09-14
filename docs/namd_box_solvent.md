# Box and solvent

In Simulations → NAMD, expand **Box and solvent** above the surface card. Choose
rotation-safe fit, bounding-box fit, or explicit X/Y/Z dimensions in nm. Explicit
dimensions work on a blank part without first estimating DNA geometry. Fit modes
recalculate when geometry, water margin or surface settings change.

Select **Custom** ionic conditions to enter NaCl and MgCl₂ concentrations in mM.
Origami screening uses 0 mM NaCl and 12.5 mM MgCl₂. Surface-control temperature is
editable; ordinary DNA relaxation displays its protocol-controlled 300 K target.
Production retains the prepared source job's box, solvent and protocol behavior.

**View details** adds a display-only overlay:

- Cell outline with X/Y/Z dimension labels.
- Cyan water-margin slabs around a structure, or a solvent-volume highlight for
  an empty system.
- Salt, approximate bulk ion counts and temperature callout. Counts use liquid
  volume and salt stoichiometry; excluded molecular volume and neutralizing
  counterions are resolved during preparation.
- Faint blue periodic faces.

The live relaxation wizard summarizes these settings and uses the same values
when creating the job, rather than providing competing preparation controls.
Existing job snapshots remain immutable. Actual molecular fitting is still checked
at preparation time: an explicit box preview is not proof that a structure fits.
Plain blank electrolyte native preparation is not qualified by these UI checks.

Current choices are saved as `metadata.namd_box_solvent` in the document. Named
presets include this card but remain global files under `workspace/namd_setup_presets`,
independent of any `.nadoc` document. The visibility overlay starts off when a new
document is opened.

## Validation (2026-09-13)

- `just test-frontend`: 6,399 passed (428 files).
- Focused browser checks: all five box/charged-wall/preset/surface tests passed;
  the final annotation revision passed its separate visual rerun. Ordinary-box screenshots were inspected and removed after review.
- `just smoke`: 23 passed.
- `just test-smart`: FAST; 8,321 passed, 110 skipped, nine pre-existing failures
  involving absent BigO/smallO workspace fixtures. Slow/full work remains deferred
  by the expired user test-session marker.
- `just lint`: two existing findings (`routes_oxdna.py` unused `seq`,
  `test_oxdna_peg.py` unused `Path`); no new findings. `git diff --check` passed.
- No native simulations launched. Main composition-root cost for this feature:
  one import and one factory initialization (+2 lines).

The preparation overlay uses compact green dimension labels (70% of the original
scale) on offset dimension lines with extension lines to the measured cell edges. A smaller green-bordered conditions callout connects
to the liquid compartment with horizontal/vertical and 45-degree screen-space
leader segments that update when the camera orbits. Labels describe the padded cell;
the green liquid outline distinguishes the solvent volume.
