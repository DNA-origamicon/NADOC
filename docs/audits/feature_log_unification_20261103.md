# Feature-log live-host verification — November 3

The active Vite server on :5173 serves `/home/joshua/NADOC`. The earlier
Repair/filter change existed only in `/home/joshua/NADOC-merge-20261103`.
Applied the UI changes to the served checkout without replacing its existing
uncommitted work, and carried all adapter fixes back into the integration checkout.
The prior backend provenance and routing changes remain in the integration worktree
pending the broader merge; this follow-up changed frontend behavior only.

Both editors use `ui/feature_log_panel.js`. Cadnano's old adapter omitted Repair,
loadout and native history endpoints, and discarded transient store feedback.
The extracted store/API adapters now reuse the same Repair, source-bound routing,
extrusion, pattern and dependency transports as 3D. Metadata acknowledgements use
the shared revision tracker; native edits request complete, revision-bound geometry.
Filter preferences persist per document and synchronize across windows. The popup
anchors within its toolbar so cadnano's narrower sidebar shows every label.
3D main.js LOC delta: 0; cadnano main.js delta: -27.

Validation on the served checkout:

- Focused adapters/Repair/panel: 24 passed.
- Full frontend: 809 files, 9,617 passed, one skipped (353.39s).
- Cross-editor app cases: 2 passed (19.7s). Matching rows and filters, Repair
  inspect, loadout creation propagation, actual native routing edit from cadnano,
  3D synchronization, and independent native history proof.
- Smoke: 23 passed (2.2m).
- Final popup alignment regression after the visual CSS adjustment: 1 passed (12.2s).
- Actual :5173 app: read existing test.nadoc into separate temporary documents;
  verified matching rows, repair/filter controls, disabled annotations and visuals,
  cross-window filtering, and popup bounds. Inspected screenshots of both panels.
  test.nadoc's SHA-256 remained
  `6fd9c082069e4b6338b8570301b8fa3df4a802bfe6f8e8ef1fac5e0757009ed3`.
- Memory lint: zero errors, one pre-existing length warning. Diff whitespace check passed.

Earlier live-review attempts used a test-only hook or failed to exit the welcome
screen; the final review uses the normal same-document startup handoff. Their
failures and cleanup remain in the logs. Visual inspection then found popup
clipping in cadnano, corrected before final live verification and regression run.

Evidence and explicit artifact inventory are in
`.development-artifacts/feature-log-unification/`. `cleanup.json` verifies all
owned temporary roots, backend review documents and session-cache entries absent.
All screenshots were inspected and deleted. No user document was edited or saved.
