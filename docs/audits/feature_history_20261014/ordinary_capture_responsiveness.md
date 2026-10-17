# Ordinary geometry capture: measured ownership gap

U44, October 17, 2026. FH-27 diagnostic checkpoint; no milestone closed and
no production behavior or rollout gate changed. This is not app qualification.

## Reproducible evidence

Run `just validate-safe uv run python -m scripts.benchmark_part_capture`.
The script builds native bundle/pose recipes entirely in memory, then performs
20 captures per case with the production 25 ms / 30,000-node / 2 MB limits.
It observes GC and top-level deepcopy duration, without collection requests,
disabled GC, retries, forced scheduling or raised limits. Returned capture
destruction is outside the timer. No session, file cache, worker or browser is
created. Source construction is outside measurements. These synthetic designs
do not represent the complete standard-tool matrix.

[All 80 samples](benchmark_part_capture.json), Python 3.12.3 on this workstation:

| Helices / pose features | Successful captures | Median ms | Maximum ms | Median copy ms |
|---|---:|---:|---:|---:|
| 1 / 0 | 20/20 | 1.084 | 1.965 | 0.146 |
| 24 / 25 | 20/20 | 4.081 | 5.573 | 1.790 |
| 96 / 25 | 20/20 | 11.316 | 11.670 | 6.276 |
| 192 / 25 | 19/20 | 20.641 | 64.374 | 12.472 |

The refused sample overlapped a generation-2 collection lasting 46.276 ms.
Copy time includes any overlapping GC; do not add the two. Instrumentation adds
overhead, and this sample cannot separate all scheduler delay from CPU time.
No claim about HTTP latency, lock contention, native proof throughput, tail
percentiles or interactive performance follows from these small samples.
The earlier U41 HTTP GC refusal is independently consistent with this finding.

## Architecture finding and next implementation boundary

`part_ordinary_recipe_recording._run` retains the mutable `Design` and copies
authoring under `state._lock`; revision checks alone cannot make unlocked copying
safe against an in-place writer. The immutable worker already accepts sealed
bytes and projects them in the child, but `part_immutable_evaluation.check_request`
admits only strict batch/verify. It is not a drop-in ordinary-tool transport.
Sealing the mutable model on every edit under the lock would merely replace
the copy with full-document serialization. A cache keyed only by identity or
revision is insufficient until all writers obey immutable ownership.

The next implementation boundary is to admit an ordinary geometry operation
against an already sealed source through the existing host, with feature/input
selection in the worker and source/session/revision/policy-bound publication.
Start with one existing core editor and prove parity, stale/cancel refusal and
undo, then extend the shared path. Keep mutable documents on their current
bounded path until durable creation/recovery and all relevant writers qualify;
do not silently convert user documents or open immutable rollout gates.
This belongs to the existing FH-28/FH-29 exits, not new scope. Research any
unresolved ownership/interaction decisions before committing their design.

Smaller copying optimizations can reduce typical work but cannot guarantee
avoidance of a process-wide collection pause. Keep the current fail-closed
deadline, source isolation, node/byte accounting and independent native proof.
No molecular algorithm change is needed for this ownership investigation.

## Validation and limits

37 existing capture/admission/accounting regressions passed in 4.03 s; two
serializer warnings come from the intentionally unsupported legacy-kind fixture.
Changed-script Ruff and diff whitespace checks pass. No backend runtime code
changed, so no broad backend/frontend run was made. The benchmark produced only
this small tracked report; no bulk artifacts or user designs were written.
The responsiveness defect remains open; this checkpoint establishes a reusable
measurement and narrows the implementation decision, rather than fixing it.
