# S30/U59 — Bounded sealed readiness

Delivered October 17, 2026 against HEAD `96ab701e`; unrelated dirty changes preserved.
S30 implements exactly the readiness GET selected by the current handoff. S29's
strict 403 was an implementation gap; the closed dispatcher now admits that GET.
This is HTTP acceptance, not a rerun or completion of S29 desktop acceptance.

## Implementation and boundaries

`part_immutable_display_reads.py` uses its existing captured sealed source,
transport, single work slot, supervisor and child worker for `/api/design/readiness`.
It returns ordinary `standard_readiness`/`finish_readiness` facts, part context and
document identity. Parent code holds sealed handles; it neither decodes the model
nor invokes compatibility handlers or obtains mutation permits. Unsupported query
modes (including assembly and request-selected workspace) refuse before work.
Source, session identity, revision, policy generation, gate and cancellation remain
bound before/after child work and response encoding. Existing native display scope,
2 MiB response bound and five-second deadline remain unchanged.

New `part_readiness_evidence.py` supplies a read-only reader to the existing
`readiness_jobs.completed_simulation` implementation. It preserves live/archive,
production-parent and stored-project-revision provenance rather than inventing
completion from job status alone. Strict reads bypass ordinary evidence caches so
job completion can change without a design revision. Optional reader injection in
`readiness_jobs.py` and `ProjectRevisionStore.load_design` leaves ordinary defaults
and revision format/checksum/decompression checks intact. Workspace is selected by
the host. No simulations, archive cache writes or canonical mutations occur.

Evidence file reads share the existing metadata allowance of 8 MiB per request;
entry visits share a 30,000 allowance, including directory/archive traversal.
Existing project snapshot decode bounds still apply. Budget exhaustion escapes
ordinary unreadable-record handling and returns `readiness_evidence_limit` (413),
rather than presenting an incomplete scan as a valid completion assessment.
Large stores can therefore refuse; this task does not widen limits or qualify
near-limit latency. No scientific/topology/sequence constants or goldens changed.

## Validation actually run

All commands used repository guards, sequentially:

- `just test-focused tests/test_part_immutable_readiness.py -x`: initial 29 cases
  passed in 21.19 s. The final test file adds an HTTP oversized-evidence case and
  strengthens stale/unknown assertions.
- Final serial loop, each `just test-focused TARGET`, stopped on any error:
  `tests/test_part_immutable_readiness.py` (30 cases),
  `tests/test_part_immutable_display_reads.py`,
  `tests/test_design_readiness.py`, `tests/test_design_readiness_api.py`,
  `tests/test_project_revisions.py`, `tests/test_part_strict_http.py`.
  All six targets passed; loop exit 0. Observed final summaries include 25 API,
  22 project-revision and 61 strict-HTTP passes. No aggregate count inferred from
  truncated streamed output. ORJSONResponse deprecation warnings remain.
- Readiness coverage: native Bend/Twist ordinary-report equality for absent,
  current, stale, unknown, archived, parent-inherited and stored-revision evidence;
  completion refresh without revision change; unsupported queries/gate refusal;
  source/session/revision/policy/cancel races; worker/shared-memory cleanup;
  cumulative byte/entry exhaustion and actual oversized-file HTTP refusal.
  Canonical history/redo and fixture file bytes remain unchanged.
- Changed-file Ruff: pass for the display/evidence adapters, readiness jobs,
  project revisions and new readiness tests. `git diff --check`: pass.
- `just lint-memory`: pass, 0 errors/0 warnings. Current document links, unique
  38 milestone rows/21 Done, 59 engineering rows and sole S31 successor checked.
- `just test-smart --dry-run`: accumulated changes select FULL due to `main.py`,
  then FAST fallback without a dedicated session. This was a dry run: **zero
  broad tests ran**, and neither FAST nor FULL is claimed passed. Nineteen
  historical timing candidates remain recorded; no new scientific/broad sweep.

Required selector debt wording (the “ran” phrase is tool boilerplate, not execution):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

No browser, full frontend or broad backend run. S29's two failed browser runs and
unreached Open/Cancel/Apply remain pending. View volumes, dimensions, VR references,
active jobs and collaboration polls remain observed refused contracts. Scientific
qualification, full resource/latency acceptance and historical broad failures are
not cleared by these focused passes. All production rollout gates remain false.

## Artifact closeout and sequencing

Own remaining pytest roots 5/6/7 were removed after cwd/open-file/memory-map checks:
no accessible process reference; 32 inaccessible-or-exited process records limit
that inspection. Roots contained respectively 9 files/18,507 bytes, 110 files/
66,022 bytes and no files. Pytest retention already removed older S30 roots;
all selected roots are absent, unrelated `pytest-0` preserved. No app servers were
started in S30. The temporary documentation script was removed after use.

**21/38 milestones Done; 17 remaining (8 core,9 parked); delta +0/+0.** U59 is
engineering checkpoint 59 and FH-20 checkpoint 5, task growth flagged. Fixed
FH-20/FH-27/FH-28 exits, ISSUE-100 and MV-48 remain open. No commit or push.
S31 is the sole unstarted successor: the sealed view-volume/dimension GET pair,
with ordinary persisted-annotation and document-selection parity. Its objective,
files, acceptance, exclusions and stop condition are in the
[current handoff](session_handoff.md#next-bounded-task). No S31 implementation began.
