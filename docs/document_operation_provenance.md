# Semantic document provenance

`Design.document_history` records meaningful document operations independently of
`feature_log`. There is no Save/autosave operation and no new visible feature row.
The first materialization of Main records one `loadout-initialize`; repeated saves
only maintain the existing revision store and bounded current head/base receipts.

Version 1 records loadout initialization, creation, rename, selection and deletion,
and document name, description, author and tag changes. Repeated unchanged metadata
and loadout renames do not append records. Selecting the already-active, unchanged
branch with unchanged last-editable state is also a no-op. Assembly per-instance
part-loadout routes use the same journal; these are part document operations, not
assembly molecular construction commands.

Each entry binds its source branch and exact native construction inputs (root,
input sources, ordered command parameters and a digest of the reconstructed state).
It does not carry a molecular output snapshot as a replacement root. Selection and
active-loadout deletion also bind the actual restored target inputs and metadata
operations. This distinguishes branch selection that discards unsaved changes.

The semantic reducer validates branch identities, names, active/last-editable state
and metadata operations. Native authoring proof applies the recorded metadata
commands after construction replay. Regenerating geometry preserves the journal
and current recorded metadata; source constructions and physical fields remain
subject to their original proof rules.

Agent publication additionally re-executes every operation's source/target inputs,
audits every saved branch (including inactive branches), checks the active embedded
snapshot against the current part, and validates revision identity/content bindings.
Current head/base revision records travel with each loadout, so their verification
does not require the author's local revision store. These storage receipts are not
user-facing history. Replay has explicit operation and command budgets.

Undo restores the existing document snapshot including its journal. Branch switches
retain the document journal rather than reverting to the selected branch's older
copy. Failed operations do not publish new records. A concurrent first autosave
initializes the actual current document without replacing newer metadata edits.
Branch switching marks changed inactive snapshots dirty while retaining their
expected revision head; autosave persists those branches with the existing
compare-and-swap checks before issuing new portable receipts.

## Boundaries

Existing loadouts without recorded creation are not retroactively assigned an
initialization event. They remain readable, but the agent cannot certify their
missing document history. No existing user files are migrated by this change.
Protected simulation loadouts still require a separate provenance contract and
remain refused by agent publication. This is not a blanket publication exception
for any snapshot, imported root, diagnostic feature, or physical override.

The feature-log **filter** popup now offers Fine routing (initially on) and
Document ops (initially off). Document ops displays the recorded journal in order
below the construction timeline; these rows do not seek geometry. Fine-routing
visibility preserves original feature numbers and replay inputs. Preferences persist per document and synchronize between the 3D and cadnano
windows. Annotations and visuals is disabled: those operations and
animation uses remain deferred. Autosaves never appear as document operations.

## Validation

Regression coverage: `tests/test_document_operations.py`,
`tests/test_agent_structure_guard.py`, existing loadout/revision/save-race tests,
and the document-provenance round trip in `frontend/e2e/extrude_history.spec.js`.
The tests include repeated persistence, no-op operations, independent branch names,
discard/select, active deletion, assembly part routes, regeneration, concurrent
first save, tampered source recipes, revision pointers and inactive geometry.


November 3 validation in the integration worktree:

- Final focused backend run: **137 passed** (document operations, publication,
  loadouts, revision storage, save races, workspace identity and archival capture).
- Browser: the new semantic-operation/workspace-autosave/reopen check passed;
  the existing early-Extrude edit/Save/reopen check also passed. The first attempt
  at the new check used the legacy direct-file save API and was corrected to
  exercise the workspace autosave API. Both browser roots were cleaned on exit.
- Ruff and diff checks pass; memory lint has zero errors and the same three
  pre-existing size warnings. Native-placement review gate is clear.
- `main.js` LOC delta: **0**. No production frontend behavior was changed.

`just test-smart` selected **FAST**, with 20,402 passed, 53 failed and 100 skipped
in 462.84 seconds (474 seconds including wrapper overhead). It was started before
refactoring finished, so 13 document/publication cases hit mixed old/new module
imports; the clean-process focused run above clears those cases. This broad run
is not evidence of a clean final suite. The other 40 failures comprise the known
23 backend failures, ten missing-native-viewer checks, the previously selected
experimental CPD contract case, and six additional residue-axis/history projection
failures in the merged code. The axis implementation and tests were not changed
in this document-provenance task. Keep these as merge-readiness debt.

The slow-test triage procedure was applied. The broad wrapper reported **zero
per-test budget violations** and an aggregate overrun on the roughly 20,000-test
suite. The final focused report has no violators (its slowest test is first-use
initialization at about 2.5 seconds). No time budget or classification was weakened.
The broad timing report was replaced by the later focused run; the broad wrapper
verdict remains in the retained log. No unsupported claim of a full timing fix is made.

The broad-suite deferral remains verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

Compact logs are retained under `.development-artifacts/merge-readiness/document-*`.
The code remains uncommitted in the integration worktree; the original shared
working tree and user designs were not edited.
