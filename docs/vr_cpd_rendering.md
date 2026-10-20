# CPD rendering in native VR

Full exports the same two gold schematic bars as the desktop. Their attachment
sites come from the shared CPD slab projection and the registered chemical graph:
syn products use C5–C5/C6–C6; anti products use C5–C6/C6–C5. Saved coordinates,
stereochemistry, slab placement authorities and simulation parameters are unchanged.
Live Full slab frames transport both ends independently, including rotation.
Beads hides these slab-specific bars, matching the desktop.

Crossover-insert CPD beads and slabs now consume the saved O5′/ring-centroid/frame
landmarks and saved residue transforms used by the desktop, instead of rebuilding
an unconverted insert pose. Regression checks require their displayed C5/C6 sites
to coincide with the shared atomistic model, including rotated/translated designs.

Stick and Ball & Stick use the existing atomistic CPD bonds. VDW displays the
atomic envelope without bond cylinders. Coarse representations do not claim to
resolve cyclobutane chemistry.

Debug → VR Tours & Tests → Visualization → **CPD isomers · native rendering**
runs `python -m tools.vr_workflows.cpd_representation_check`. It reads the four
saved designs in `workspace/CPD_1xT_isomers` without modifying them. An alternate
directory is accepted with `--design-dir`. Captures and logs go to a fresh
Archive-backed `.development-artifacts/cpd-vr/` directory.

The workflow exports all representations through the production exporter,
renders diagnostic stereo views through the production native GL renderer,
and compares Full, Stick and Ball & Stick against the same scene with only the
two CPD crosslinks removed. Beads and VDW must be unchanged by that removal.
It also checks slab-frame transport. Backend tests compare exported Full bars
with the actual desktop Three.js bar builder and verify atomic bond identities.
Whole-model context images are retained alongside explicitly labelled isolated
residue images; isolation changes visibility only and exposes occluded crosslinks.

These diagnostic cameras are not OpenXR-submitted eyes or physical headset
scanout. The maintained physical `representation_tour --cycle --snapshot ...`
workflow complements this check when SteamVR and the headset are available.
No controller motion behavior is changed by the CPD rendering fix.

Verification on 2026-10-20 covered 48 native representation cases and 20
submitted stereo cases through the physical OpenXR runtime: all four isomers
in Full, Stick, Ball & Stick, VDW and Beads. All four saved designs had zero
serialized Full-to-atomic C5/C6 site error. A closer repeat failed the existing
recorder-readiness check before launching a viewer; the first captures remain
valid, and the runtime returned to its initial stopped state.
See the [verification record](audits/cpd_vr_rendering_20261020.json) for test
results, retained attempts and the broader suite's outstanding failures.
