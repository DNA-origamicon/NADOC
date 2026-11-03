# Box and solvent

In Simulations → NAMD, expand **Box and solvent** above the surface card. Choose
Recommended (current bounding box + 6 nm per face), custom bounding-box padding,
Allow any orientation (rotation envelope), or explicit X/Y/Z dimensions in nm.
Selecting Recommended resets padding to 6 nm. Editing initial solvent padding commits
on blur or Enter and switches Recommended to custom padding. The committed value is
saved to the selected draft job (or document defaults when configuring a new job)
and refreshes the box/solvent preview, open wizard,
and Alpine/RunPod size and resource estimates. Explicit dimensions work on a blank
part without first estimating DNA geometry. Fit modes recalculate when geometry,
selected padding or surface settings change. Actual six-face water clearances are
shown separately from selected envelope padding. Preparation does not automatically
trim padding or switch sizing modes to fit hardware; see [box sizing](namd_box_sizing.md).

Select **Custom** ionic conditions to enter NaCl and MgCl₂ concentrations in mM.
Origami screening uses 0 mM NaCl and 12.5 mM MgCl₂. Surface-control temperature is
editable; ordinary DNA relaxation displays its protocol-controlled 300 K target.
Production retains the prepared source job's box, solvent and protocol behavior.

**View details** adds a display-only overlay:

- Cell outline with X/Y/Z dimension labels.
- Cyan water-margin slabs around a structure, or a solvent-volume highlight for
  an empty system; paired surfaces also show the separate liquid compartment.
- Salt, approximate bulk ion counts and temperature callout. Counts use liquid
  volume and salt stoichiometry; excluded molecular volume and neutralizing
  counterions are resolved during preparation.
- Faint blue periodic faces. For the two-electrode setup, amber normal faces
  identify the slab-corrected periodic direction with vacuum padding. They do
  not represent open/nonperiodic boundaries.

**View periodic images**, on its own row below View details, shows six faint,
non-interactive backbone copies at ± one box length on each axis. It works
independently of View details in every representation and follows design-backbone
positions/colors. Switching representation preserves the toggle and copies. These
are setup-box neighbors, not a live trajectory-cell contact analysis. See [periodic-image preview](namd_box_sizing.md#display-controls).

The two-electrode card owns its gap and lateral dimensions; Box and solvent shows
its derived simulation cell with 3× normal padding. Salt counts exclude this
vacuum. Two-electrode jobs now select the experimental Electrode relaxation protocol;
see `namd_electrode_protocol.md`. Native qualification remains pending, and this
overlay does not imply completed validation.

The live relaxation wizard summarizes these settings and uses the same values
when creating the job, rather than providing competing preparation controls.
Selecting a draft restores its saved preparation settings; deselecting it turns off
View details and periodic images. Prepared and started job snapshots remain immutable. Actual molecular fitting is still checked
at preparation time: an explicit box preview is not proof that a structure fits.
Plain blank electrolyte native preparation is not qualified by these UI checks.

Local memory admission uses the selected box and salt recipe, including partially
explicit dimensions. It displays a conservative atom upper budget before preparation
and uses the PSF count afterward. Preparation has its own RAM budget. Large neighbor
or margin settings may also require automatic CUDA patch subdivision, even when total
VRAM fits; subdivision preserves the physical box and force settings. Unsupported
explicit patch controls block launch rather than retrying on a larger-memory GPU.
See [memory policy](namd_setup.md#solvent-and-memory-policy) for the limits and scope.

New-job defaults are saved as `metadata.namd_box_solvent` in the document.
Selected draft edits are saved to that job’s `prep_params`; they do not overwrite
the defaults for a different job. Named
presets include this card but remain global files under `workspace/namd_setup_presets`,
independent of any `.nadoc` document. Both display toggles start off when a new
document is opened.

## Validation (2026-09-13)

- `just test-frontend`: 6,399 passed (428 files).
- Focused browser checks: all five box/charged-wall/preset/surface tests passed;
  the final annotation revision passed its separate visual rerun. Ordinary and
  slab screenshots were inspected and removed after review.
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

The user-provided `2electrode_solvent_only.nadoc` workflow was checked in Playwright
at 300 mM NaCl and 300 K. Persistent prepared job `8395d215579b` and its qualification
record are described in `.development-artifacts/2electrode_solvent_only_validation/README.md`.
Native dynamics remain pending a user-opened test session.
