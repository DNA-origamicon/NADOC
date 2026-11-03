# Five bounded history-acceptance tasks — October 17, 2026

The user explicitly requested the next five tasks, superseding the handoff's
one-task-per-session default. S10 is the initial task; successors are defined
from evidence before implementation. These are acceptance slices of FH-20,
supporting FH-27, not five milestones. HEAD remains `96ab701e`; existing dirty
work is preserved. No production behavior/geometry, constants, scientific
thresholds, rollout gates, test guards or historical evidence changed.

## Common validation and artifact contract

Every browser command is `just validate-safe uv run --no-sync python
scripts/run_deformation_history_e2e.py`. One worker, no retries, 60-second case
budget, strict empty-console assertion and prior lifecycle assertions remain.
Storage preflight passed on /tmp (661 GiB free). Node syntax checks run before
changed specs. No full suite, scientific campaign, downloads or external sharing.
The real S09 no-host middleware remains; no fabricated sharing responses.

All output remains inside each fresh launcher root: workspace/project/log/playback
files, browser profiles/downloads, caches, Playwright results, potential isolated
sharing credentials. Saved fixtures, including the new edited file, use __e2e__
names. No screenshots/video/traces. Launcher finally stops owned processes before
removing the root; each run is independently checked for absent root, no accessible
owned process, no listeners/reusable 8004/5177 and no workspace fixtures. Protected
process environments are counted as unreadable, not claimed inspected. Byte totals
are not metered; only compact evidence retained. Routing fault tests, if selected,
must release held real responses and remove routes in finally; no fabricated success.

## S10 — Tiny-fixture undo/redo/save/reopen (complete)

Objective/parent: the handoff's persistence slice, FH-20 supporting FH-27.
Deliverable: extend the existing Bend/Twist cases using ordinary client undo,
redo, saveDesign and loadDesign. Compare original/edited deformation inputs and
feature logs, stack lengths and adopted native placements; undo before loading
the edited saved file so a no-op load cannot pass. No backend fixture changes.

Invocation 1: both cases failed at raw geometry equality after undo; all preceding
lifecycle, native input/log and undo/redo stack assertions passed. GET geometry
and compact mutation geometry have different ordering and optional metadata.
`geometry_codec.js` explicitly groups compact results by helix/direction. The
harness now keys by helix/direction/bp/copy, asserts unique identities and compares
all 17 shared identity/topology/placement fields exactly, including all six native
position/orientation fields. SHA256 only bounds diagnostics; no numeric tolerance,
coordinate changes or reduced preview/Cancel preservation assertion.

Invocation 2: **2 passed (47.4 s), Bend 22.1 s, Twist 20.4 s**. All persistence
checks and strict console check passed. Node syntax passed. Exactly two invocations;
no further S10 diagnostic run. First root `/tmp/__e2e__history-mmma1big`, second
`/tmp/__e2e__history-ax1nz6nk`; both absent, ports reusable, no accessible owned
processes or workspace fixtures (32 protected environments). Warnings were existing
ORJSON, NO_COLOR/FORCE_COLOR and WebGL diagnostics. Raw geometry assertion dumps
were not retained as repository artifacts. Full controls/creation/resource and
representative-chain acceptance remain. No milestone/U credit.

Successor selected before implementation: S11, preview off/on and repeated Cancel
with the same tiny fixtures. This exercises the existing private-preview matrix
without expanding into full controls or molecular validation.

## S11 — Preview off/on and repeated Cancel (complete)

Target recorded before editing in the handoff. Existing tiny fixtures now verify
include_geometry false/true, feasibility in both responses, prefix-only versus
candidate display, exact restoration of candidate matrices, source/browser/files
unchanged and repeated Open/Cancel leaving zero private roots. Prior persistence
and lifecycle assertions remain. Only the spec/current records changed.

One guarded invocation: **2 passed (50.9 s), Bend 23.8 s, Twist 22.0 s**. Syntax
passed. Root `/tmp/__e2e__history-4lfucm8h` absent; no accessible owned process or
workspace fixture; both ports reusable (32 protected environments). Inventory
unchanged from S10. No complete controls/representation/resource qualification.
Successor S12: apply while evaluation is pending, requiring the latest draft and
exactly one publication; defined before implementation. No milestone/U credit.

## S12 — Apply with pending evaluation (complete)

Target recorded before editing. The browser route executes one real evaluate
request, holds its response, queues a newer value (35 → 40), clicks Apply and
asserts disabled Apply with unchanged source/browser and zero Apply requests.
After forwarding the unchanged response, it verifies the next evaluation differs
from the held draft and its params exactly equal the single Apply body. Existing
revision/history increment, disposal and S10 persistence assertions still pass.
The helper releases responses/removes routes in finally; no sleeps or fake success.

One guarded invocation: **2 passed (53.8 s), Bend 24.9 s, Twist 23.8 s**. Syntax
passed; root `/tmp/__e2e__history-hkt6rfd6` absent, no accessible owned process or
workspace fixture, ports reusable (32 protected environments). No production code
changed. Successor S13 is Cancel during held evaluation and replacement-preview
protection, defined before implementation. No milestone/U credit.

## S13 — Cancel pending evaluation and protect reopened preview (complete)

Target recorded before editing. Hold a real evaluate response after changing to
45, cancel through the popup, await real cancel acknowledgement, verify zero
private roots and exact source/browser/file preservation, then reopen before
releasing the old response. After delivery/abort processing and two animation
frames, the replacement matrices and canonical state are unchanged. No Apply or
canonical preview writes; the new preview also cancels cleanly. Normal abort is
allowed to propagate; no console errors are filtered. Existing S10–S12 checks remain.

One guarded invocation: **2 passed (58.1 s), Bend 27.2 s, Twist 25.8 s**. Syntax
passed; root `/tmp/__e2e__history-s7hpck0p` absent, no accessible owned process or
workspace fixture, ports reusable (32 protected environments). Inventory unchanged.
This qualifies the browser abort/late-delivery boundary, not arbitrary transport
failure or every source-reset race. S14 is the fifth task: ordinary document
close/load while Open is pending. No milestone/U credit.

## S14 — Document reset during pending Open (complete)

Target recorded before editing. Hold the actual prepare response, call ordinary
client closeSession (real reset event and DELETE) then loadDesign on the owned
edited file. Verify original saved design ID/feature log/edited inputs and exact
adopted native placements, zero private roots, then open a fresh nonce before
releasing the old response. After completion/abort processing and two frames,
reloaded backend/browser/files and the new preview are unchanged; no extra Apply.
The fresh preview cancels and disposes cleanly. No synthetic reset or fabricated
prepare response. Revision/session changes are not mistaken for persisted identity.

One guarded invocation: **2 passed (reported total 1.2 m), Bend 34.2 s, Twist
32.0 s**, within the unchanged 60-second per-case budget. All accumulated S10–S13
assertions and strict console check passed. Syntax passed. Root
`/tmp/__e2e__history-cx544ewk` absent, no accessible owned process or workspace
fixture, ports reusable (32 protected environments). Inventory unchanged.

Final focused regression:
`just validate-safe npm --prefix frontend run test -- src/features/deformation_history_controller.test.js src/app/deformation_history_editor.test.js src/api/deformation_preview_endpoints.test.js src/test-helpers/deformation_history_launch.test.js src/ui/design_readiness_boot.test.js src/viewer/geometry_codec.test.js`
— **124 passed across 6 files in 2.89 s**. These are existing relevant unit tests,
not 124 new browser cases. The focused middleware temp directory was also removed.

## Result, remaining boundaries and successor

Five tasks complete: S10 persistence; S11 preview off/on/repeated Cancel; S12
pending-evaluation Apply; S13 pending-evaluation Cancel/reopen; S14 close/load
while Open is pending. Six browser invocations total: S10's initial two failures
were a wire-comparison harness mistake, followed by a passing correction; each
later task passed on its first invocation. The final spec still has two cumulative
tiny native cases, not ten independent representative cases. No new production
defect was demonstrated; no production source was changed in these five tasks.

No full matrix row, FH-20/FH-27 exit, broad regression debt or scientific acceptance
is closed. Remaining: complete controls and creation entry points, representative
upstream/downstream chains, actual failed/lost Apply and publication/Cancel races,
expiry/disconnect cases, latency/lock/read/retained-memory qualification and paired
rollout/obsolete-preview pruning. Historical failed full-software evidence remains.
No performance claim follows from test duration or finite display-root counts.

**21/38 complete, 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged.**
The sole successor is **S15 — Cancel after publication while Apply reply is held**,
fully specified in the [handoff](session_handoff.md). It is unstarted; the five-task
authorization is exhausted. No commit/push or unqualified gate enablement.

Final closeout: memory lint reports 0 errors/0 warnings; git diff --check and
scoped untracked whitespace checks pass. All 49 checked local links resolve;
38 unique milestone rows/21 Done, five completed S10–S14 report sections and one
fully specified S15 successor are verified. Current plan/ledger/memory/issue/manual
sequencing agrees. Final independent cleanup recheck finds all six roots absent,
no accessible owned processes, no listeners and reusable ports, no workspace
fixtures (31 protected process environments unreadable at this final recheck).
The focused middleware temp roots are absent. Temporary records/cleanup scripts
were removed. HEAD remains 96ab701e; unrelated dirty changes are preserved.
