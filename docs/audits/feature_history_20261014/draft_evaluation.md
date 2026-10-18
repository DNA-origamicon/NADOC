# Saved repair draft evaluation

A saved proposal now enters the existing part evaluation lifecycle through
`POST /api/design/features/repair-draft/evaluate`. Its strict request is:

```json
{
  "draft_version": 1,
  "expected_design_id": "part-id",
  "expected_revision": 12,
  "expected_draft_id": "proposal-id",
  "expected_generation": 3
}
```

The document header selects the runtime host. The request carries no candidate,
replacement actions, source bytes, output geometry or implementation-pin bypass.
The response is the existing 202 evaluation-start response plus a compact
`repair_draft: {draft_id, generation}` binding. Polling, cancellation, expiry and
commit use `/api/design/features/evaluation/jobs/{job_id}` and its existing
DELETE / `/commit` operations. No second worker, queue or candidate catalog is
introduced.

## Admission and publication

1. Under the existing state lock, compare part/revision/draft guards, require an
   editable branch, capture bounded definitions and the saved proposal, and
   retain the actual source object and server-owned session-incarnation UUID.
   Capture includes only published source references for the base check. It
   does not execute proposal actions, inspect geometry or decode recovery.
2. Outside the lock, compute the durable published base fingerprint. The saved
   base part ID, root/ordered command identities and published source evidence
   must still match. A mismatch requires explicit rebase. Neither old values nor
   implementation pins are rewritten automatically.
3. Compile the stored actions into the existing `RepairRequest`. The ordinary
   repair worker owns action planning, numerical upgrades, prefix regeneration,
   downstream errors and candidate validation; host admission duplicates none
   of those algorithms. The existing job capture rechecks the trusted source
   object and session identity before copying geometry. A close/reopen ABA or
   intervening edit during fingerprinting therefore refuses before that copy.
4. Commit publishes the exact privately evaluated candidate once. Existing
   source/revision/session/cancellation/expiry guards apply, with one geometry
   undo entry. The current saved proposal is retained. Its base becomes stale
   after a changed recipe is applied; another evaluation requires explicit
   rebase. An unchanged old expectation may then need a deliberate edit. Apply
   never silently discards a proposal; discard remains a separate metadata
   operation.

Matching a base fingerprint is a concurrency/precondition check, not evidence
that the design regenerates. No ready state is persisted, and saved geometry
cannot supply missing dependencies. Metadata edits and source staging bump the
same session revision and invalidate previously evaluated candidates.

## Source integration

`POST /api/design/features/repair-draft/source/inspect` accepts a strict named
selection and returns an exact prior-byte receipt. It is an explicit read; POST
keeps the structured selection out of URL query limits. The caller sends that
result as ASCII JSON in `X-NADOC-Repair-Source` with original octet-stream bytes
to `POST /api/design/features/repair-draft/source`.

The separate [source staging contract](repair_source_staging.md) distinguishes
proposed staging from published restoration, preserves family/cumulative
budgets, limits acquisition to one nonqueued upload, and checks cancellation
before its metadata-only publication. A published-source restoration changes
the saved base and requires explicit rebase. Staged bytes used only by proposed
inputs do not change the published fingerprint. Protected branches permit
inspection but refuse staging, restoration and evaluation.

## Validation gates

- Pure compilation: strict guards; exact action ownership; changed root/input/
  feature identity/order/source evidence requires rebase; proposed-only bytes,
  presentation, recovery and current geometry do not enter the base.
- Host: fingerprint outside lock; no action replanning; stale draft before
  capture; source/revision/session ABA between fingerprint and job admission
  rejects before molecular capture; protected branch refusal.
- Actual registered HTTP lifecycle: save a broken native-reference proposal,
  evaluate in the existing spawned worker, poll without exposing its candidate,
  commit once, verify in a second fresh process with poisoned recovery, and
  undo with the proposal retained. Subsequent evaluate rejects the old base.
- Existing cancellation, expiry, changed proposal and reopened-session guards
  prevent commit. No parser, model field, numerical pin or scientific formula
  changes are required by this slice. Root runs all checks serially.

## Precedent and policy

[Onshape's repair documentation](https://cad.onshape.com/help/Content/Document/repairing.htm)
describes editing failed features and resolving references from earlier errors
forward through the feature list. Its [import-update workflow](https://cad.onshape.com/help/Content/Document/working_with_imported_cad.htm)
explicitly updates source data and reapplies downstream operations, exposing
rebuild failures. NADOC's explicit durable-base/rebase and session compare-and-
swap rules are local concurrency policies supporting that repair workflow,
rather than claims that either vendor implements this particular draft schema.
