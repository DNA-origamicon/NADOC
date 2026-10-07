# Native Full placement failure review

A failure in a native Full bead/slab positioning regression is an incident, including
preview, partial-response, reload, desktop/VR parity, and representation changes.
It must produce inspectable evidence and a complete positioning review. A later green
rerun does **not** clear the incident. Tests keep running so fixes can be verified, but
placement test runs and the explicit release gate remain unsuccessful until review.

The ledger defaults to `.native-placement-review/`, separate from
authored `.nadoc` documents. Set `NADOC_PLACEMENT_REPORT_DIR` for isolated tests, CI, or
another persistent destination. Self-tests always use temporary directories. Failures
to write or read the evidence fail closed; do not delete the ledger to make a run pass.

## What is recorded

Each failure immediately creates a unique immutable incident directory containing:

- `report.json`: test/operation identity, UTC timestamp, exception and traceback,
  reproducible command, SHA-256 identities of positioning source files and the test,
  and all supplied per-site expected/actual coordinates and displacements.
- `report.html` and `report.txt`: a simple review-required explanation followed by
  the complete evidence. HTML escapes exception/data content.
- `REVIEW_REQUIRED.json` at the ledger root: unresolved incident identities. Passing
  tests never rewrite this latch. Missing incident evidence and malformed reports
  cannot yield a successful gate.

Use `@pytest.mark.native_placement` (or a module `pytestmark`) for backend regressions.
`test_measured_positioning.py`, `test_display_placement.py`,
`test_native_full_placement.py`, `test_native_slab_placement.py`, and files containing
`native_placement` are automatically marked, excluding the isolated gate self-test.
The `native_placement_evidence` fixture accepts keyword evidence before an assertion.
For complete displacement records use
`tools.native_placement_audit.evidence.coordinate_deltas(expected, actual, identities=...)`.
An exception's `details` field is also recorded. Both assertion and setup/teardown
failures are covered; the xdist controller owns writing worker reports.

Frontend regressions use `*.native_placement.test.js` or `[native-placement]` in their
full test name. Existing `helix_renderer.slab_coordinates.test.js` and
`native_placement.failure_ui.test.js` are also guarded; the retired
`new_positioning.test.js` filename remains guarded against accidental resurrection. The Vitest reporter records failed test
and module errors, expected/actual values and assertion diffs, through the same journal.
Place rich diagnostic values in assertion expected/actual objects when relevant.

The registered native `nadoc-vr-placement-integrity` CTest uses
`python3 -m tools.native_placement_audit.command`. A failure preserves its exact
command, stdout, stderr, source hashes and exit status in the same journal.
A passing native rerun cannot clear the incident. Runtime failures also latch
the desktop and matching native VR session: rendering and molecular exports stop,
and native edit actions stop. Recovery requires completing the recorded review
and reloading or relaunching. Source document saving remains available for evidence.

An unreadable or malformed journal fails closed. A configured path that is a
regular file, an inaccessible incident directory, or an interrupted report write
cannot be treated as a clean journal. A genuinely absent, never-created ledger is
valid and is created only when evidence must be recorded.

Runtime integrity handlers can call `record_failure` with `test_id="runtime:<operation>"`
and identity/field/expected/actual evidence. Recording an incident never repairs,
falls back, changes geometry, saves a document, or transmits a message.

## Complete the review

Review the actual shared-frame geometry and per-site differences, identify the
root cause and scope, and inspect every affected full/compact/partial/preview,
desktop/VR, and fresh-load path. Preserve the canonical native landmarks. Explain
why the defect could escape the prior gates and add the missing regression. Include
positive and negative examples and retained visual/numeric evidence; do not replace
an oracle or regenerate geometry goldens merely to obtain a pass.

Create a review JSON with these nonempty fields:

```json
{
  "root_cause": "Exact faulty path and why the invariant broke",
  "affected_paths": ["Every affected producer, consumer, and transient path"],
  "validation": "Commands/results and the limits of physical or visual checks",
  "regression_tests": ["Exact regression test identities"],
  "evidence": ["Paths to inspectable before/after geometry and per-site reports"]
}
```

The explicit acknowledgement is separate from testing:

```bash
python3 -m tools.native_placement_audit acknowledge INCIDENT_ID \
  --reviewer 'Reviewer name' --review /path/to/completed-review.json
python3 -m tools.native_placement_audit check
```

The acknowledgement stores the reviewer's name, time, complete review and hash of
the original report. It cannot overwrite a previous review. Each incident must be
reviewed separately; acknowledging one does not clear others. This acknowledgement
does not authorize a new molecular placement or replace the molecular-geometry
authorization requirements in `CLAUDE.md`.

## CI and release

CI runs the explicit `python3 -m tools.native_placement_audit check` gate and retains
incident reports as artifacts even after failing tests. Backend and frontend jobs
restore/save separate per-branch review ledgers so a passing rerun does not silently
clear a prior failure. Cache retention is controlled by GitHub; the downloaded
incident bundle is the durable review record and must be retained until acknowledged.
To acknowledge a CI incident, download its bundle, set `NADOC_PLACEMENT_REPORT_DIR`
to that ledger, and use the explicit acknowledgement command above with
`--export-review tools/native_placement_audit/reviews/INCIDENT_ID.json`. Review this
record with the fix. CI's `apply-reviews` step accepts the committed acknowledgement
only when its incident ID and report SHA-256 match the restored immutable report.
This is a recorded reviewer attestation, not a cryptographic identity signature.

There is no repository-managed deployment or Git pre-push hook. Existing pytest and
Vitest test commands are gated as described above; run the explicit `check` command
before pushing or deploying. This change does not install hooks or claim to prevent
a user from bypassing local test commands. An incident must not be dismissed by
deleting caches, changing the report directory, unmarking a test, or updating a golden.
