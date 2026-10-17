# Registered batch publication qualification

October 15, 2026. Proposal and harness; the public batch gate remains disabled.
This does not change existing manual edits, compatibility imports or assemblies.

## What the existing bounds cover

The new job path has one source proof and one candidate publication, with ordinary
25 ms/30,000-node/2 MB capture, shared 2 MB worker input, 16 MB result and 8 MB
regenerated recovery budgets. Those bounds constrain isolated recipe evaluation.
They do **not** yet bound the complete source retained by undo.

`core.part_verification_capture.capture` excludes physical, presentation and
repair-draft fields and omits saved recovery bodies. `part_recipe_publication`
carries the current physical/presentation/draft state into the published model.
`part_replacement_transaction.publish_replacement` invokes `state._snapshot_copy`
under the global state lock; that copies/validates the complete source, including
all excluded fields and old history payloads. Documents with lattice frames take
the generic deep-copy branch. Existing undo/redo entries are also retained, up to
50 entries, without a cumulative memory budget.

Consequently, a tiny captured recipe can coexist with large atomistic references,
loadouts, arbitrary annotation-ref JSON, a bounded but nontrivial repair draft, or
oversized old recovery strings. Independent proof correctly ignores these values;
that fact cannot authorize an unbounded full-source publication. Saved recovery
may be poisoned and still ignored during replay, while its bytes remain alive in
the new undo snapshot. No validity label or candidate digest solves this cost.

Pinned-source staging is not a reusable solution: its transaction publishes only
metadata and creates no geometry undo snapshot. Its 256-source/~66.7 MB encoded
table envelope is unsuitable as a latency bound for copying a whole part. Batch
capture currently applies its much smaller ordinary source budget.

## Harness and interpretation

`scripts/benchmark_registered_batch_jobs.py` runs a temporary in-memory FastAPI
application and isolated document, without the production lifespan or workspace
writes. Root runs it serially. It temporarily opens the gate only in the harness
process and restores it; no workload budget is changed.

For each case it collects at least 30 actual HTTP captures with submission
intercepted, plus 30 independent commits of a separately evaluated candidate.
Lock holds/waits, full-source undo snapshot time, actual concurrent revision HTTP
requests and correct complete publication are reported. Captures that refuse
remain failures in the output; a successful prepared commit is not described as
an admitted end-to-end job. Separate real spawned cases cover complete evaluation,
cancel/reap, stale source, empty-root worker overhead and cold replay.

Cases cover 32 gold commands, 32 mixed DNA/group/pose/gold commands, 32 commands
with 49,984 authored strand residues and helix base pairs, and real native history
grown until the next single command cannot fit unchanged recovery/entry budgets.
The last admitted history must also support an independent ordinary parameter
edit. The long-history case may exceed ordinary capture; the output must report
that rather than widening the profile.

The intermediate qualification mode, `--intermediate-history-only`, constructs
exactly 64, 128 and 256 source rows through ordinary native gold commands. Each
case appends 32 commands and independently edits the resulting complete candidate.
It measures the same 30 HTTP capture/publication samples, real spawned jobs, cold
replay and cancel/stale cleanup while omitting the maximum-history search and
excluded-storage probes. Fixture growth timings are separate from HTTP timings.
The default full run includes these intermediate cases too. No new production
row limit is implied by adding a benchmark boundary.

Additional, explicitly unqualified storage probes attach 10,000 synthetic physical
atom records, 100,000 arbitrary presentation values, a repair draft, or oversized
old recovery to an otherwise identical source. These are storage-cost fixtures,
not molecular calculations. They demonstrate why captured authoring alone cannot
qualify publication. Rootless sources must fail; explicit imported roots remain
`reproduced_import`, which is a construction basis and not public import permission.

Exit zero means harness integrity and cleanup passed. Enabling the gate still
requires reviewing refusal rates, p95 capture/publication/HTTP latency, cold replay
and the exact proposed source scope. A cooperative 25 ms allowance is not a hard
wall-time ceiling. Rejected boundaries must remain in the evidence record.

## Initial evidence

`registered_batch_jobs_benchmark_initial_p6.json` retains the first complete run.
All 240 independent prepared publications were correct and cleanup succeeded.
The 32-row gold source had capture/publication lock p95 of 9.60/0.98 ms; the mixed
native source had 4.52/0.63 ms. Real 32-command jobs completed and passed cold
replay in roughly 1.19–1.23 seconds, including worker startup.

These results do not qualify the entire tested envelope. The 49,984-residue case
had one capture refusal in 30 samples (65 ms maximum capture lock hold), despite
3.60 ms p95. A native 1,685-row final history remained independently editable and
the next single command failed atomically at the unchanged recovery budget. Its
1,684-row source refused all 30 live captures; independent prepared publication
had 80.01 ms lock p95. Retaining 10,000 physical atom records raised publication
lock p95 to 56.15 ms. The intermediate report subsequently measured 64/128/256 source rows.
64+32 and 128+32 each refused one of 30 captures (capture p95 12.65/24.76 ms);
256+32 refused all 30. Prepared publication p95 was 0.90/1.31/2.63 ms.
The public gate stays disabled. These reports predate final permit enforcement.

## Proposed first public scope

Before enabling, add a server-owned preflight that checks the **live full source**
under the same lock and before capture. Recheck its trusted scope at publication,
using the same session incarnation, source identity and revision guard. Do not
accept caller-selected limits, retries, saved approvals or arbitrary actor labels.

A small initial slice can be explicit-empty-root parts with the reviewed seven
batch command families, no imported source table, no lattice frames, no physical
payloads and no nondefault presentation collections or pending repair draft.
`annotations_enabled` may vary because it is a scalar. This keeps existing
manual workflows unchanged and makes unsupported batch scope actionable. It is
preferable to claiming all existing native parts are qualified based on empty-root
fixtures. Existing pure imported-root support remains useful for independent
replay and future explicit import policy, but is not automatically enabled here.

Derive a maximum source/history envelope from the measured passing boundary, not
from the largest abstract registry limit. Count all incoming saved recovery/diff
strings against a fixed aggregate allowance before snapshotting; do not assume
the source previously passed the regenerated 8 MB budget. Bound command/header
count and nested JSON work before traversing them. Keep the ordinary capture
limits unchanged. Repeated batches may hit a publication-scope bound before the
generic 2,000-entry limit; report that distinction clearly.

Pending drafts and ordinary presentation can be added through a separately
measured bounded full-source traversal once worthwhile. Physical state needs a
qualified snapshot/storage design; merely permitting its collection length is
insufficient because nested records and arbitrary payloads can be large. A
bounded number of undo steps is not a whole-process heap guarantee: any stronger
memory claim needs cumulative retention accounting or immutable storage, tested
independently. Avoid using a generic recursive deep copy as admission itself.

## Session incarnation seam

Source-object identity plus revision can repeat after a document session is
dropped/recreated with the same object. The host now assigns `_DesignSession.identity`,
outside Design, undo and saved requests. `capture_design_for_evaluation` retains
its default triple and optionally returns the same-lock session identity as a
fourth value. Internal callers can also require `expected_source` and
`expected_session_identity` before copying. Evaluation jobs carry the captured
token through supervisor checks, polling and final `set_design`; missing context
cannot authorize publication. Already-committed handles remain idempotent only
within their original session. Benchmark synthetic jobs explicitly capture the
host identity. No client request or worker response supplies this authority.

## First bounded scope measurement

The host preflight now limits source plus proposed command/group rows to 64,
retained recovery to the existing aggregate 8 MB, and excludes nondefault
physical/presentation collections, source tables and repair drafts. It shares the
ordinary capture deadline, rather than starting a fresh allowance after preflight.
Read-only verification continues to ignore old recovery bytes. Final batch
publication must repeat scope checks on the live source and exact candidate.

`registered_batch_jobs_benchmark_public_scope_p6.json` measured four real native
histories at this boundary, before private-permit integration. It records 120/120
correct prepared publications and verified cleanup. Capture p95 was 7.72 ms for
32 gold rows plus 32 commands, 4.43 ms for 37 mixed rows plus 27 commands, and
6.00 ms for 50,000 authored residues ending at 64 rows; these had no refusals.
The 63-row retained history plus one command refused once in 30 samples:
capture p95 17.36 ms, maximum 59.51 ms, concurrent lightweight HTTP maximum
60.64 ms. Prepared snapshot p95 across the four cases stayed below 0.82 ms.
All real spawned completion cases independently cold-replayed; cancel/stale
cases refused commit and reaped. These measurements still do not establish
a hard latency ceiling or qualify a gate change.

The next measurement must exercise the private admission/permit boundary and
retain refusals. Copy allocation and collection pauses require diagnosis; narrowing
a row bound or raising a deadline alone does not explain occasional outliers.
