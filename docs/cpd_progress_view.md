# CPD progress view

Open **Help → CPD progress…** to inspect the current CPD evidence snapshot.
The selector opens the corrected cis-syn core and includes two corrected sugar
fragments, three original comparison structures, and two deferred cis-anti starting
structures. These are model compounds and
starting structures, not a validated full DNA strand.

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
snapshot validation, details, and asynchronous modal lifecycle.
`frontend/e2e/cpd_progress.spec.js` exercises the real menu, evidence, structure
switching, failed glycosidic-bond details, rotation, and closing in Chromium.

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
