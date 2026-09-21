# CPD progress view

Open **Help → CPD progress…** to compare all **eight ordered DNA TT-CPD isomers**
and inspect the current CPD evidence snapshot. The gallery shows every isomer
at the same scale and in the same ordered cyclobutane frame. Select a card for
the larger, rotatable view; camera orientation is retained when switching isomers.

Both endpoints include deoxyribose and phosphate. Blue identifies endpoint 1;
purple identifies endpoint 2. Dashed arrows mark the local 5′ exit at P and 3′
exit at O3′. Outlined O5′ atoms identify the same backbone-bead landmark used by
NADOC's Full representation. The two pale crosslinks follow each registered
graph: C5–C5/C6–C6 for syn, C5–C6/C6–C5 for anti. Endpoint numbers are retained
chemical identities, not an assumption that the two residues share a strand.

**Show sugar–phosphate context** toggles the attachment geometry. Each **sugar
rotation** slider explores the corresponding N1–C1′ torsion while keeping the
CPD core, attachment bond length, and internal sugar geometry fixed. C1′ and
O5′ separations and the angle between local P→O3′ vectors update alongside the
view. These describe one conformer; they do not establish strand compatibility.
**Reset view** restores the camera and both initial sugar orientations.

The cis-syn-I preview uses the current preliminary coordinate template. The
other seven use existing ETKDG/UFF starting cores checked against all four
registered stereocenters. Their D-sugar/phosphate attachments are transferred by
proper rotations from the preliminary template; a coarse heavy-atom clearance
search adjusts only the two glycosidic torsions. These are explicitly labeled
**In development · estimate**. They are not force-field minima, fitted duplexes,
or guarantees of clash-free placement in a design. No authoring or simulation
qualification is enabled by these previews. Original source hashes accompany
the portable starting cores in `backend/data/cpd_preview_cores.json`.

The **Evidence studies · model fragments** selector group retains the corrected
cis-syn core, two corrected sugar fragments, three original comparison structures,
and two deferred cis-anti starting structures. These remain independently
inspectable studies; their check colors are separate from the endpoint colors
used in the isomer gallery.

Drag to rotate, scroll to zoom, and hover over an atom or bond for its recorded
checks. Tab also selects elements; click or Enter pins the details for inspection.
Each detail includes measured values, acceptance criteria, available evidence
paths and SHA-256 hashes, and shared model checks and remaining work.

Colors summarize recorded local checks:

- Red: multiple failures involving the element.
- Orange: one failure.
- Yellow: validation incomplete.
- Gray: no local evidence recorded; this is not a pass.
- Green: all available local checks pass, visible only in **Available local checks** mode.

The default **Overall readiness** mode keeps otherwise passing elements yellow
because DNA validation is incomplete. Shared energy checks are displayed separately
from localized geometry checks. An angle check applies to its participating atoms
and bonds; a red bond can therefore indicate angular failures as well as its length.
Passing fitted geometry is training evidence, not independent validation.

## Updating the evidence

The UI reads `frontend/public/cpd-progress.json`. It does not monitor running jobs.
Refresh just the isomer illustrations using tracked repository data, with no
archive access, RDKit installation, GUI, or simulation required:

```sh
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/export_cpd_isomer_previews.py
```

This preserves the original evidence date, studies, and checks. It can update an
alternate snapshot with `--snapshot PATH`. The full evidence exporter also
regenerates the isomer catalog, so routine evidence refreshes retain it.

After new assessments are saved, regenerate the snapshot from the repository root:

```sh
OPENBLAS_NUM_THREADS=1 .venv/bin/python experiments/cpd_published_comparator/export_progress.py
```

The exporter requires the retained evidence under `.development-artifacts` and the
workstation's `/media/jojo/Archive/NADOC_archive/photoproduct_evidence` archive.
The generated JSON is portable and requires no archive access in the browser.
The exporter defaults to the checked `cpd-cis-syn-joint-v6` candidate.
Use `--boundary-root .development-artifacts/<candidate>` to inspect a different
completed assessment. Candidate native/core checks without a saved result remain
pending. The original boundary failures remain available for comparison. Corrected
models display all fragment bond/angle errors, including outliers away from the
fitted attachment, with before/after values and a no-new-failures regression check.
All 142 bonds and 270 angles in the current three-model candidate pass the recorded
geometry targets; those are training checks. Independent glycosidic profiles and
solution validation remain pending. The corrected core has its own current
energy, force and minimum checks, separate from the original model's evidence.
The snapshot also includes the completed `cpd-dna-replicas-v2` short DNA pilot:
three CPD and three matched control runs, each with 100 ps equilibration and
100 ps production. Shared checks show the six individual results and the
aggregate 6/6 pass. These checks apply to the current corrected cis-syn models;
they do not change local atom/bond colors or mark overall readiness complete.
Longer sampling and convergence remain unvalidated. Use `--dna-root` to select
another campaign assessment; missing results stay pending.

The ongoing `cpd-dna-extended-v1` continuation targets 5 additional ns per
replica in 30 total one-nanosecond blocks. Its monitor refreshes the saved
snapshot at block boundaries. The view reports assessed blocks and execution
state, while the longer-sampling check remains pending until convergence has
been reviewed. A failed block is shown as a failure.

**Reload evidence** fetches the saved JSON again; it does not rerun assessments.
Add newly assessed model compounds and their checks to the exporter as work expands.

## Verification

`frontend/src/ui/cpd_progress.test.js` covers status semantics, projection,
snapshot validation, all eight structures, torsion invariants, details, and
asynchronous modal lifecycle. `tests/test_cpd_preview.py` checks all stereocenters,
correct crosslinks, bond lengths, preserved core/sugar geometry and handedness,
the O5′ landmark, portable regeneration, and unchanged evidence/release gates.
`frontend/e2e/cpd_progress.spec.js` exercises the real menu, evidence, structure
switching, all eight context views, sugar rotation/reset, context visibility,
failed glycosidic-bond details, rotation, and closing in headless Chromium.

## Drift localization evidence

The shared checks now flag periodic-image isolation separately from local CPD
geometry: the completed DNA campaign reaches 5.61 Å between a control duplex and
its periodic copy, with a brief 11.81 Å approach in CPD replica 2. The localization
note records end-region motion and the initially open A8–B13 pair. These are
campaign/starting-state concerns, not newly assigned atom-specific fitting errors.
Source diagnostics are retained under `cpd-drift-localization-v2`.

The revised `cpd-dna-largebox-v1` pilot now appears separately: deposited 1T4I
coordinates, 90 Å cubic box and per-replica image-clearance checks. The prior
campaign's image-isolation failure remains labeled as historical evidence.
Its event-driven monitor refreshes the saved snapshot at completed replicas.

The eight-hour `cpd-overnight-8h-v1` array reports assessed nanoseconds in 0.5 ns
blocks. Its shared check stays pending until final review; per-block failures
show as failures. The event-driven monitor updates this snapshot at block boundaries.

The completed overnight review marks the finite native/stability benchmark passed
(68 blocks, 34 ns). A separate pending check records the persistent A6–B15 opening
in CPD replica 3. It is not localized as a fitted bond/angle failure, and no
production-readiness flag is enabled. The linked evidence distinguishes the
observed state change from an established parameter defect.
