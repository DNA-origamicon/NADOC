# Bend/twist release acceptance — S01/S02/S03

**User priority — October 18, 2026:** Complete Bend, Twist, Sweep and Extrude
before moving to other areas. Completion includes their applicable creation and
history-edit controls, isolated preview/Cancel/Apply, dependency and downstream
replay correctness, undo/redo/save/reload, and desktop/latency qualification under
the existing fixed exits. FH-21/FH-22 implementation completion alone does not
establish fully qualified Extrude/Sweep tools; their FH-27 acceptance remains.
Select each bounded successor from the remaining work for these four tools.
Shared infrastructure work must identify a demonstrated blocker to one of these
tool requirements and stay narrowly bounded. Other areas remain deferred;
simulation relevance remains saved-source freshness only. Preserve scientific
authorization and rollout qualification; do not weaken assertions or fixed exits.
S54 Sweep downstream-nick success/refusal desktop workflow is the sole next task, unstarted.

S53 qualifies independent, attached-start and sticky-detached Sweep history editing with later Extrude. Native fixture4 and source-contract40 passed, harness22 passed, focused frontend23 passed; final three-case browser matrix passed with clean consoles. Prefix source inventory, ligation draft controls, fixed-origin orientation, saved source/detach identity, exact Cancel, full native geometry, Apply and persistence are covered. Test synchronization corrections required no production change. S54 Sweep downstream-nick success/refusal desktop workflow is the sole unstarted successor. No milestone advanced. See [S53 evidence](sweep_source_matrix_20261018.md). **21/38 complete, 17 remaining (8 core, 9 parked), delta +0/+0; U1–U60 (60 engineering checkpoints; FH-20 at 5 and FH-28 at 11, both growth flagged).**

**Current storage policy (subsequent October 17 user correction):** Archive belongs
to the other machine. The launcher now uses OS temp by default with explicit local
root/optional mount settings. Live preflight passes here; S09 fixed the share boundary; current task sequencing is in the handoff.
Earlier Archive-blocked results below are historical. See the portability evidence
at the end of this document; fixed feature acceptance/gates are unchanged.

October 17, 2026; source baseline `96ab701e` plus uncommitted S02 registration.
S01 diagnostic, S02 registration and S03 harness source delivered; S02 broad
validation remains incomplete. S09 passes the two existing S03 browser cases; full release acceptance remains incomplete. No rollout, scientific decision or milestone closure. FH-20 retains its full
exit: desktop and latency acceptance, route/editor enabled together, obsolete
mutating preview pruned. FH-27 retains integrated/resource/broad regression exits;
FH-28 retains complete immutable lifecycle qualification.

## Dependency decision

**FH-20 has no demonstrated requirement to finish FH-28 first.** Its existing
private path uses mutable standard parts, not the immutable geometry host. This
is a code-path finding, not a claim that it meets latency acceptance.

1. `frontend/src/app/feature_editor.js`: default-false
   `ISOLATED_DEFORMATION_HISTORY_ENABLED` dispatches deformation rows to
   `history.open`; `ISOLATED_DEFORMATION_CREATION_ENABLED` shares that owner.
2. `frontend/src/app/deformation_history_editor.js` constructs the controller
   with `createDeformationPreviewEndpoints({request: api._request})`; accepted
   Apply alone adopts via `api.syncDesignResponse`.
3. `frontend/src/api/deformation_preview_endpoints.js` sends prepare/create/
   evaluate/apply/cancel/status to `/design/features/deformation-preview`. It
   privately reads design/geometry/revision between status checks for refresh.
4. `backend/api/routes_part_deformation_preview.py` bounds input, checks
   default-false `DEFORMATION_PREVIEW_ENABLED` and compatibility policy, then
   dispatches in a thread to `part_deformation_preview_sessions`.
5. That host's `_prepare` requires `type(source) is Design`, captures under
   `state._lock`, then prepares/evaluates outside it. `evaluate` reuses the
   prefix. `apply` freshly captures, calls `prepare_change` (or creation append),
   then `_publish` preserves document state and calls `publish_replacement`.
   The mutable publisher takes one `_snapshot_copy` for undo. This is not an
   immutable-geometry endpoint or immutable-handle undo transaction.
6. **Production registration delivered in S02:** `backend/api/main.py` now
   imports/includes the existing deformation preview router under `/api`.
   `tests/test_part_deformation_preview_registration.py` proves six unique POST
   endpoints on the actual app, default-disabled refusal and host/document strict
   refusal with a locally enabled flag. It deliberately omits lifespan startup.
   Existing native lifecycle tests retain their separate isolated app/owner.


The [U44 capture diagnostic](ordinary_capture_responsiveness.md) is a shared risk,
not a bend/twist HTTP measurement: 192 helices/25 poses had 19/20 successful
captures, one 64.374 ms refusal overlapping GC, against the unchanged 25 ms budget.
The preview host also captures under lock and copies undo at publication. Measure
this actual path before deciding ownership migration is necessary. If it fails,
identify the phase and missing immutable capability (private prefix display/lease
or preserved-state publication), not “finish FH-28.” U53's immutable Bend/Twist
support alone neither connects this editor nor covers named organization. No
other open milestone has a demonstrated shorter complete exit in this selected
evidence; retain FH-20 without restarting the audit.

## Acceptance matrix

S01 inspected existing coverage. S02 reran only production registration and the
existing HTTP lifecycle module, plus the guarded backend selector reported below.
S10–S15 plus the Bend package provide automated browser evidence as summarized below;
other linked coverage remains historical. Full desktop qualification is not claimed.
Commands are future focused checks, serialized under repository guards. Manual
checks require disposable fixtures, failure-safe cleanup and qualified test
configuration. All production gates remain false. No new timing threshold is
invented; bounded software deadlines are not interactive qualification.

| Requirement | Actual caller/path | Existing evidence | Remaining gap / prerequisite | Exact check or manual gesture |
|---|---|---|---|---|
| Reachability and paired gates | feature_editor flags → endpoints → production deformation router | S02: 24 actual-app boundary passes, 13 native HTTP lifecycle passes; all three flags false | Desktop qualification and coordinated route/history/creation rollout | `just test-focused tests/test_part_deformation_preview_registration.py`; `just test-focused tests/test_part_deformation_preview_routes.py`. No application lifespan or browser acceptance claimed |
| Private preview and controls | editor/controller → prefix evaluator/DTO → deformation_history_preview | validation_deformation_history_editor.json; native display/editor tests; S11 exact preview off/on; Bend angle/radius/direction/reversed planes and S20 Twist units/handedness/reversed planes persist exact final UI inputs | Desktop control and representation parity, canonical isolation | Bend and single-helix Twist: planes, angle/radius/direction, units/handedness, polymer controls, scope and preview off/on; no autosave/export/simulation change. `just test-focused tests/test_deformation_preview_native_display.py` |
| Cancel exactness | nonce/lease cancel → host.cancel; private display disposal | sessions preserve source/stacks; S11 repeated Cancel and S13 pending Cancel/reopen pass on tiny fixtures | App check with redo and repeated opening/disposal | Drag then Esc/Cancel; compare design/revision/cursor/undo/redo/saved bytes; no canonical requests or seek. `just test-focused tests/test_part_deformation_preview_sessions.py` |
| Apply, failure, lost reply | fresh capture/prepare_change → _publish → receipt/status/private refresh | session/receipt/HTTP tests; S12 pending-evaluation Apply, S15 Cancel-after-publication and S22 lost-reply receipt/adoption/persistence pass on tiny fixtures; failed Apply has unit coverage | Actual app adoption and uncertain-publication UX | Apply pending drag once; induce refusal and lost reply; resolve Status without duplicate publication. `just test-focused tests/test_part_deformation_preview_receipts.py` |
| Stale/reset/expiry/disconnect | controller context/epoch; _source_current; nonce/status; disconnect is not rollback | host source/session unit checks; S13 late evaluation and S14 close/load during pending Open pass on tiny fixtures | Real network/middleware and desktop behavior | Reset during Open/evaluate/Apply; open replacement tool before late reply; disconnect before/after commit and resolve status without overwriting newer state. `just validate-safe npm --prefix frontend run test -- src/features/deformation_history_controller.test.js src/api/deformation_preview_endpoints.test.js` |
| Upstream/downstream edits | historical prefix controls; Apply independently proves source and rebuilds suffix | native preview/retarget tests; four-helix Bend→Twist edit/persistence/native proof passes; S48/S49 tiny ordinary Bend/Twist→attached Sweep lifecycle, exact native replay and desktop persistence pass | Routing/Sweep and named/domain complete chain and cold replay in app | Edit earlier extrusion then Bend/Twist with later routing/Sweep; compare independent regeneration and missing-reference refusal, including named/domain targets. `just test-focused tests/test_part_deformation_group_retarget.py`; `just test-focused tests/test_part_deformation_preview.py` |
| Undo/redo/save/reload | publish_replacement snapshot; ordinary persistence | HTTP cold proof/undo test; S10 browser undo/redo/save/reopen passes on tiny fixtures | Complete desktop redo/persistence on representative parts | Apply once, undo/redo, save/reopen and independently verify inputs; Cancel preserves redo. `just test-focused tests/test_part_deformation_preview_routes.py::test_actual_http_preview_apply_status_cold_proof_and_undo` |
| Ordinary creation parity | creation gate → same owner → /create → prepare_creation_append | validation_deformation_creation.json; actual Bend/S20 Twist toolbar selection/Clear and S17/S19 Bend/Twist sidebar/context strand placement/Cancel/Apply/undo/reopen pass | Other targets and plane picking in app | Create Bend/Twist through each entry; Change/Clear selection, refuse incomplete draft, one Apply/undo/reopen; no provisional row. `just validate-safe npm --prefix frontend run test -- src/app/deformation_creation_editor.test.js src/ui/deformation_creation_launcher.test.js` |
| Latency/lock/read tails/retained memory | lock-owned capture; prefix display; preservation/undo copy; private refresh/render | U44 capture diagnostic; current Bend boundary report; neither test durations nor finite RSS samples qualify interaction | Actual complete request/render and larger-part/resource qualification; verified machine-local scratch for captures | Repeat Open/drag/Cancel/Apply on representative small/large parts; record request/render phases, refusals, concurrent light-read tails, undo and retained heap. Preserve budgets; do not infer pass from replay equality |
| Obsolete mutating preview retirement | legacy feature_editor peel/delete/seek; scene/deformation_editor; API add/update/delete | ISSUE-100 characterization; legacy dispatch still live | Qualified replacement and paired enablement first; complete caller inventory | `rg -n 'addDeformation|updateDeformation|deleteDeformation' frontend/src`; trace history/creation/polymerize_panel/VR callers. Prune only obsolete preview branches, preserve unrelated committed operations/deferred VR; run affected tests and gestures |

## Environment and reconciliation

- HEAD is still `96ab701e` (`git log -5 --oneline`). Initial dirty files were
  implementation.md, milestone ledger, project memory, plus untracked handoff
  and fresh_session_prompt.txt. Their existing changes are preserved.
- Both `findmnt -M /media/jojo/Archive` and `findmnt -T /media/jojo/Archive`
  returned no mount; `stat /media/jojo/Archive` reported no such file.
  `ss -ltn '( sport = :8000 or sport = :5173 )'` showed no listening sockets.
  No directory/mount was created and no services started.
- This blocks artifact-producing desktop qualification, not bounded source work.
  Before browser/profile work, restore Archive and verify resolved output/scratch
  filesystem, then start app services with an explicit artifact/cleanup plan.
- Historical “frontend not connected” prose is stale: gated dispatch exists.
  Historical unregistered-router evidence was true at S01 and is resolved by S02. The implementation plan's
  old 18/38 paragraph describes FH-19's checkpoint, not current totals.

## S01 validation and boundary

Inspected source, lifecycle test definitions and historical evidence; checked
Git, mount/path and sockets read-only. Documentation checks and their results are
recorded in the handoff. No backend/frontend tests, native build, browser,
benchmark, app workflow or scientific sampling ran. No bulk artifacts or user
design writes, cleanup deletions, gate changes or commits. Broad regression debt
remains. The first documentation write attempted `python`, unavailable on this
host; it wrote nothing and was rerun with `python3`.

S01 selected S02; S02 is now delivered. Exactly one current successor is specified
in [the handoff](session_handoff.md): **S04, execute/stabilize the S03 history-preview
browser spec**. S03 source delivery is recorded below; S04 was not started. Performance, full desktop coverage,
coordinated enablement and retirement remain open acceptance obligations.

## S02 registration evidence and limits

Acceptance target fixed before editing: register the existing six POST handlers
using production `/api` convention; prove unique matching and disabled/strict
policy boundaries on the actual application. No host or ownership change.
`main.py` changed by two wiring lines. No frontend source change (`main.js` delta 0).

The new test uses `main.app`, including its real strict/document middleware and
route ordering. It creates `TestClient` without entering its context manager:
production lifespan would initialize CUDA, start filesystem/session watchers,
resume jobs and connect RunPod. This harness runs no startup services. The
repository autouse workspace fixture already imports the same app and isolates
workspace paths; boundary tests create no documents. Flags use `monkeypatch`;
host policy restores in `finally`, with an assertion that no session was created.
Six POST route matches are unique and point to the original handlers. Six
malformed-body requests get `preview_disabled` before input/native dispatch;
twelve locally enabled strict requests (host-default/per-document) get
`construction_policy`. Existing native lease tests retain their failure-safe
session teardown and are not duplicated as another owner.

Actual commands/results:

- `just test-focused tests/test_part_deformation_preview_registration.py`:
  **24 passed in 3.35 s**.
- `just test-focused tests/test_part_deformation_preview_routes.py`:
  **13 passed, 6 ORJSONResponse deprecation warnings in 3.53 s**.
- `uv run ruff check backend/api/main.py tests/test_part_deformation_preview_registration.py`:
  passed. Backend `DEFORMATION_PREVIEW_ENABLED` and frontend history/creation
  flags remain literal false. No persistent configuration was enabled.

Reconciliation: HEAD remains `96ab701e`; prior dirty implementation/ledger/issue/
manual/memory and untracked matrix/handoff/reusable prompt were preserved.
`findmnt -M /media/jojo/Archive` found no mount; `stat` found no path;
`ss -ltn '( sport = :8000 or sport = :5173 )'` found no listeners. These are
current observations, not permanent blockers. No browser/app/performance/native
build or scientific campaign ran. Small focused test outputs require no bulk
capture; no user designs or managed jobs were touched by the S02 checks.
ISSUE-100/MV-48/FH-20/FH-27 remain open. Counts remain **21/38, 17 remaining
(8 core, 9 parked), delta +0/+0**. Routine wiring earns no U checkpoint.

### Required selector: incomplete, failed and storage-blocked

[Compact S02 evidence](validation_deformation_registration.json) retains exact
failed node IDs, slow-test diagnoses, counts and cleanup. `just test-smart`
selected **FAST**, four workers, 19,303 collected items; its actual deferral was:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

**This was an interrupted partial run, not a fast-suite pass.** The selector's
standard pytest temporary output was discovered at 320 MiB on the system disk,
contrary to Archive-first bulk storage; Archive was absent. Sent SIGINT only to
the owned pytest process; shutdown reached 355 MiB including directory overhead
and sparse files. No rerun, storage fallback, guard or budget override followed.
A future broad selector must first verify Archive and explicitly place TMPDIR/
pytest scratch there. This prerequisite was missed before this invocation.

Partial result: **16,170 passed, 16 failed, 15 skipped, 2,477 warnings, four
collection errors in 272.00 s; command exit 2**, guard wall time 277 s. Four errors
are repeated worker collection of missing CPD
`.development-artifacts/cpd-anti-gpu-longbox-v3/assembly.json`. Other observed
causes include WSL VR refusal, missing native VR viewer, and a capability test
expecting only cluster_create while extension-upsert v2 is also present. VR Join
and two junction-balance failures are retained as unresolved, not silently
attributed to environment or repaired scientifically. No baseline rerun occurred;
no claim that every failure predates S02. No focused S02 failure was observed.

Applied the [triage-slow-tests skill](../../../.claude/skills/triage-slow-tests/SKILL.md)
to the fresh report and inspected each flagged test: immutable Bend/upstream edit
5.57 s, immutable recovery/edit/persist/recover 5.11 s, immutable placement/upstream
edit 5.06 s. These execute real subprocess workers and native proof; recovery also
performs durable-file cycles. Timing confirmation and registry correction remain
open; no unrelated marker change or budget increase under this bounded router
assignment. The three exact node IDs and causes are in compact evidence. This
is partial triage, not a restored budget or completed regression exit.

Cleanup: verified no active cwd/file-descriptor/mapping references, then removed
only this session's pytest-0/1/2 trees and two new autorefine stub-result files.
The latter match `test_skip_twist_tuning`'s mocked met/stopped outputs and were
born during this run (282 bytes total); no actual simulation ran for them.
Removed **8,609 regular files, 2,392,169,781 logical bytes / 270,286,848 allocated
file bytes**, plus temporary directories/symlinks. Verified all exact paths absent
and no workspace files newer than the S02 test remained. Retained only source,
compact evidence, ordinary test caches and guard debt/timing reports; preserved
existing artifacts, runtimes and user designs. The stub persistence leak remains
an unrelated validation-isolation defect, not fixed in S02.

Final documentation checks: changed tracked local links and new matrix/handoff
links resolve; ledger has 38 unique rows, 21 Done (including qualified status
suffixes), 9 Parked and 8 open core; exactly one successor definition, S03.
Scoped Ruff and `git diff --check` pass. `bash scripts/lint_memory.sh` failed with
**6 errors/60 warnings**, matching S01. All error-bearing files and memory index
are byte-identical to HEAD (oversized CPD/native-VR heads, missing exp-predictor
index entry, three missing MD/VR artifact links). Feature memory is 202 lines,
warning only. These unrelated defects remain open.


## S03 isolated history harness: source delivered, browser blocked

Acceptance target recorded before editing: actual history edit button and popup,
native private display, unchanged canonical design/revision/cursor/undo/redo and
browser/saved persistence throughout Open/edit/Cancel, then one owned Apply.
This is a tiny lifecycle harness, not the complete FH-20 release or FH-27 exit.

Delivered sources:

- `tests/deformation_history_app.py`: new test-only factory copies the production
  route objects, middleware and exception handlers. Its own lifespan enables only
  the process-local preview flag and restores it/clears leases and fixture documents
  in `finally`. Production lifespan is untouched and never entered: no CUDA init,
  session watcher, job supervisor or RunPod startup. Fixture routes precede the
  production static mount and admit only the two `__e2e__history-*` document names.
  Both fixtures use a native 42-bp single-helix bundle and input-defined deformation;
  the backend checkpoint includes complete canonical model, revision, ordered undo/
  redo digests and every isolated workspace file's bytes digest.
- `frontend/e2e/deformation_history.spec.js`: two serial cases; real history edit
  button/popup; private scene matrices change after an edit and disappear on close;
  backend/browser state and persisted-file comparisons on Open/edit/Cancel;
  nonempty redo before editing; single Apply request, one revision and undo addition,
  stable feature identities and canonical browser adoption. Uses existing console
  error helper. No replacement preview owner, synthetic geometry or user input file.
  Ordinary e2e collection skips this spec without its dedicated root.
- `frontend/e2e/deformation_history_vite.js`: explicit test config performs an exact,
  fail-closed transform of the two existing false declarations only for the editor
  module. Ordinary Vite never imports it. Production files remain false on disk;
  no localStorage, query-string or general production runtime gate override.
- `frontend/playwright.deformation-history.config.js`: only this spec, one worker,
  zero retries, dedicated 8004/5177 services with reuse disabled. Production router
  registration is reused; startup is the explicitly test-only app above. Vite uses
  the runner config loader (no checkout `.vite-temp` bundle), task-local cache,
  and no viewer bridge or share plugins. `uv run --no-sync` uses installed dependencies.
- `scripts/run_deformation_history_e2e.py`: mount/resolved-filesystem preflight before
  creating anything; fresh output root; task-local workspace/scratch/caches; finally
  stops process-group and detached descendants carrying the unique root marker,
  refuses deletion if they remain, then removes and verifies the root is absent.
  SIGKILL/power loss cannot execute finally; retain the printed exact root for review.

### Persistent-output inventory and cleanup contract

At launch, `R` is the exact printed fresh directory
`<verified Archive output parent>/__e2e__history-<random>`. No pre-existing files are
reused. Every path below is covered by the outer launcher's finally after service
shutdown, including assertion failure, timeout, startup failure and interruption.
This contract is unit-tested; real browser cleanup is still unverified.

| Writer | Persisted path(s) | Control and cleanup |
|---|---|---|
| Design save/autosave/history | `R/workspace/__e2e__history-bend.nadoc`, `R/workspace/__e2e__history-twist.nadoc`; any generated `__e2e__*` part names and `.nadoc-projects/**` within `R/workspace` | All fixture names use `__e2e__`; explicit save paths and `NADOC_WORKSPACE` share one root; whole fresh workspace removed even if per-test teardown fails |
| Session state / playback / app logs | `R/workspace/.session/**` (disabled), `R/workspace/playback/**`, other workspace-local metadata | Session cache and production startup disabled; all workspace contents inventoried by checkpoint and removed |
| Browser profile, downloads, temporary files | `R/tmp/**` | `TMPDIR` set before child/import; nonpersistent browser context; page closes in finally, launcher stops processes before deleting |
| Playwright output / last-run | `R/playwright/**` | Explicit outputDir; list reporter only; screenshots, video and traces off; entire root removed |
| Playwright transform, Vite, UV/XDG caches | `R/cache/playwright/**`, `R/vite-cache/**`, `R/cache/uv/**`, `R/cache/**` | Explicit PWTEST_CACHE_DIR, cacheDir, UV_CACHE_DIR, XDG_CACHE_HOME; no install/build/browser download; entire root removed |
| Viewer bridge / share | None | Their plugins are omitted from the test config; no credentials to clean |
| Browser localStorage | Nonpersistent browser profile under `R/tmp/**` | Design keys compared before/after preview and Cancel; context/profile removed |

The validation guard's existing lock/debt reports and ordinary small software-test
caches are outside browser payload inventory and remain managed by existing guards.
No browser was invoked, including discovery/list mode, in S03.

### Actual S03 validation

- `just test-focused tests/test_deformation_history_app.py`: **4 passed,
  1 ORJSON deprecation warning in 3.00 s**. Independent native fixture proofs,
  actual production middleware/router prepare/Cancel with unchanged checkpoint,
  unknown fixture-document refusal, production route/lifespan identity and gate
  restoration after normal exit and an induced exception.
- `just test-focused tests/test_deformation_history_launcher.py`: final
  **4 passed in 3.05 s**. Missing mount refuses before allocation/launch; a mount
  alone cannot admit system-disk output; induced startup failure removes only the
  fresh root and preserves an existing sibling; lingering-process refusal retains
  output. These are software tests with mocked launch/storage, not real app evidence.
- `just validate-safe npm --prefix frontend run test -- src/test-helpers/deformation_history_launch.test.js`:
  **3 passed in 546 ms**. Exact-module transform, unchanged disk/default startup,
  drift refusal and explicit-root requirement. This does not start Vite or a browser.
- Scoped `uv run ruff check` on the four new Python files passed. `node --check`
  on spec, Vite config and Playwright config passed. Final diff/document checks
  recorded in the handoff. No new production behavior: no S03 `test-smart` or full
  frontend selector; inherited S02 FAST/deferred FULL failures remain unresolved.
- Early red checks were corrected: fixture routes originally followed the static
  mount (405), test preview ID was not a UUID (422), Vitest initially excluded an
  e2e-folder test, then jsdom's URL caused a Node config import failure. Test moved
  into existing discovery under `src/test-helpers` with Node environment. No
  production or guard changes were made to obtain these passes.

Reconciliation: HEAD remains `96ab701e`; all initial dirty/untracked work is
preserved. Only new test/config/launcher sources were added in S03; S02's two-line
main.py registration remains intact, `main.js` delta 0. Current `findmnt -M`/`stat`
show Archive absent; ports 8000/5173/8004/5177 have no listeners. Additionally,
`readlink -f .development-artifacts` resolves to `/home/joshua/NADOC/.development-artifacts`,
a local directory rather than the policy-described Archive symlink. The launcher
therefore requires an existing explicit Archive parent via
`NADOC_HISTORY_E2E_OUTPUT_PARENT` unless that path is later properly restored.
No relocation/deletion of existing artifacts is authorized or performed here.

**NOT VERIFIED IN APP:** no popup/browser rendering/persistence/cleanup run,
smoke, representative workflow, latency/memory, production startup, broad suite,
native build or scientific campaign. All three production gates stay false.
S03 completes source delivery and available focused validation, not browser
acceptance. S04 is the single successor, defined only in the handoff: execute and
stabilize this spec after storage is available. ISSUE-100/MV-48/FH-20/FH-27 stay
open; **21/38 complete, 17 remaining (8 core, 9 parked), delta +0/+0; U1–U54 unchanged**.

Final S03 closeout: scoped Ruff, three JavaScript syntax checks and `git diff --check`
pass. Ledger checks confirm 38 unique milestones / 21 complete / 9 parked / 8 open
core, one successor S04, and resolving handoff/matrix links. Memory lint reran:
**6 errors/60 warnings**, matching S02; error-bearing files and memory index are
byte-identical to HEAD. Feature memory remains 202 lines (warning); no unrelated
memory cleanup. Removed only three proven S03 pytest scratch trees after checking
active cwd/fd/mapping references: **3 files, 24 logical bytes**, plus directories
and scratch symlinks; verified absent. Earlier empty pytest trees were automatically
rotated by pytest. No browser output or user-design artifacts were created. Retained
only the eight small harness/test/config source files, updated records, and normal
small software-test/guard caches. No cleanup claim for an unexecuted browser run.


User-requested follow-up after S03: memory lint is now **0 errors/60 warnings**;
full prior CPD/VR heads are preserved in archives, active routing/links corrected,
and diff check passes. The earlier six-error result above is historical. See the
[handoff correction](session_handoff.md#user-requested-lint-correction-after-s03-october-17).
Archive remains absent; local output resolves onto system root despite ~662 GiB
free. This is the Archive-first policy/preflight blocker, not evidence of current
disk exhaustion or an observed browser failure. S04 remains unstarted.


## Portable launcher correction — October 17 user request

Scope: remove the workstation-specific storage prerequisite without weakening
feature acceptance, resource guards, test-session rules or cleanup. No hostname
check and no automatic relocation. Scratch resolution is:
`NADOC_TEST_SCRATCH_ROOT` (legacy alias `NADOC_HISTORY_E2E_OUTPUT_PARENT`) or OS temp.
Conflicting explicit settings refuse. An explicit root must already exist, be an
absolute directory, have at least 1 GiB free and pass a real temporary write probe.
`NADOC_TEST_SCRATCH_MOUNT` optionally requires a mounted ancestor on the same resolved
filesystem; absent/misdirected settings fail with no fallback. Mount selection is
only a local configuration on machines needing external storage.

Children inherit TMPDIR/TEMP/TMP plus task-local workspace/Vite/Playwright/UV/XDG
cache paths. `.owner-start` is an additional zero-byte file under the fresh root,
removed with it. Process cleanup uses existing psutil, not `/proc`/killpg APIs:
filter by owner/time and exact unique-root environment marker, let Playwright close
first, then terminate/kill identified survivors; refusal to terminate or lingering
identified processes prevents deletion. Protected processes without provable
ownership are neither signalled nor assumed owned. Catastrophic termination still
requires review of the printed root. No new package dependency was introduced.

Actual checks:

- `just test-focused tests/test_deformation_history_launcher.py`: **18 passed in
  3.34 s**. OS default, both explicit-root settings, invalid/missing/conflicting
  paths, file-vs-directory, mount absence/containment, capacity, write refusal,
  preflight without launch, startup failure, successful/failed exit cleanup and
  exact-owned-process selection. Real child-process test proves an unrelated
  differently marked child survives cleanup; both test children are reaped.
- `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --check-storage`:
  **passed**, `/tmp`, **661 GiB free**. Probe is deleted. No browser/service launch.
- Scoped Ruff and `git diff --check` pass; memory lint **0 errors/60 warnings**.
- Early process-enumeration failures encountered protected same-user processes;
  ownership filtering/permission handling was corrected and final checks pass.
  No guard or test threshold changed. No full backend/frontend suite was needed
  for this launcher/documentation change; prior S02 broad regression debt remains.

Current machine storage is qualified for this launcher's preflight only; no actual
browser acceptance or Windows/macOS end-to-end verification is claimed. Existing
shell guards retain their platform limits. Native scientific campaigns still need
specific authorization and a workload-specific capacity budget; this 1 GiB check
is not a general campaign allocation or continuous quota.

CLAUDE.md, canonical artifact memory, START.md, current plan/ledger/handoff/project
memory and ISSUE-100/MV-48 sequencing now agree: S04 ready/unstarted, storage blocker
removed here, **21/38 milestones, delta +0/+0**. No commit/push or production gate
changes. Legacy scripts do not automatically consume the new configuration;
START.md identifies their existing tool-specific scratch configuration responsibility.

Portable-launcher follow-up cleanup: removed 11 files (58 logical bytes) in three
owned pytest trees after active-reference checks; all exact trees verified absent.
No browser artifacts or user designs were created. Final link/ledger/single-successor
and diff checks pass.


## S04 isolated execution — October 17, 2026

One guarded invocation: **2 failed at browser launch**, before fixture seeding or
any Open/edit/Cancel/Apply assertion. Isolated services started; Playwright sought
the headless shell under disposable XDG cache instead of its installed cache.
The root was removed; post-run checks found no accessible marked processes,
listeners or workspace fixture files. See [exact evidence and limits](deformation_history_browser_20261017.md).
S07 in the handoff is the sole unstarted successor. Historical unstarted/Archive
claims above are superseded. All lifecycle/resource acceptance remains open;
no paired rollout, pruning or milestone credit.


## S07 browser-path repair — October 17, 2026

The launcher resolves the installed Playwright registry before changing XDG,
checks the headless executable and pins its resolved installation directory for
children. Explicit path, relative path and package-local (`0`) rules are retained;
missing browsers refuse before allocation/services, without downloads. Runtime
output inventory and cleanup are unchanged; browser installation is read-only.
23 launcher tests pass. One unchanged browser run launches Chromium, then both
cases time out at 60 s; teardown masks the first wait. See [S07 evidence](browser_path_repair_20261017.md).
No lifecycle row is accepted. S08 in the handoff supersedes historical sequencing.

## S08 timeout diagnosis — October 17, 2026

S08 demonstrates and corrects the harness adoption timeout: bare `?doc=` does not load geometry; the existing read-only handoff now does. Both cases reach the final console assertion, failing on two `/__nadoc_share/links` HTTP 404s each. Two diagnostic invocations only; 9 focused frontend checks pass; cleanup verified. See [S08 evidence](history_timeout_diagnosis_20261017.md). S09 share-link isolation diagnosis is the sole successor, unstarted. **21/38 complete, 17 remaining (8 core, 9 parked), delta +0/+0; U56 added (56 engineering checkpoints).**

Both tiny fixtures pass all lifecycle assertions preceding the final console check;
this is partial browser evidence, not an accepted matrix row or release exit.
No representative scale/latency, full controls, creation, undo/reload or failure
matrix is qualified. The console assertion remains unchanged. Historical next-step
prose above is superseded by S09 in the current handoff.


## S09 share boundary repair — October 17, 2026

S09 restores the real sharing middleware in the isolated harness with autostart disabled, an isolated credential path and explicit host-launch refusal. Background links now use the existing no-host pending protocol. Both unchanged browser cases pass (Bend 9.5 s, Twist 8.9 s); 10 focused tests pass; cleanup verified. See [S09 evidence](share_boundary_repair_20261017.md). S10 tiny-fixture undo/redo/save/reopen acceptance is the sole successor, unstarted. **21/38 complete, 17 remaining (8 core, 9 parked), delta +0/+0; U56 added (56 engineering checkpoints).**

This accepts only the existing tiny-fixture Open/edit/Cancel/Apply assertions,
including exact source/browser/saved-byte preservation during preview and Cancel,
private display changes, disposal and one guarded publication. No entire matrix
row or milestone closes: full controls, creation, failure/stale cases, representative
chains, undo/redo/save/reopen and resource qualification remain. S10 addresses only
the tiny-fixture persistence gap; do not infer visual/scientific validity from
instance-matrix changes or qualify latency from test duration. Historical next-task
prose above is superseded by the current handoff.


## S10–S14 five-task acceptance — October 17, 2026

All five bounded tasks complete; [compact evidence](history_acceptance_five_tasks_20261017.md)
records each objective, changes, executed checks, initial harness failure and cleanup.
The final two cumulative tiny-fixture browser cases pass (Bend 34.2 s, Twist 32.0 s),
as do 124 focused frontend tests. Six browser invocations total; no per-task cap
exceeded. Exact input/identity/native-placement persistence, preview off/on,
repeated Cancel, pending latest-draft Apply, pending Cancel/reopen and ordinary
close/load during pending Open are demonstrated. Production behavior is unchanged.

This does not complete a matrix row at representative scale or close a milestone.
Full controls/creation/chains, failed/lost Apply, publication/Cancel races, other
stale/expiry/disconnect cases, responsiveness/retained memory, broad regression,
paired enablement and legacy pruning remain. S15 publication-aware Cancel is the
sole unstarted successor in the handoff. Historical next-step prose is superseded.
**21/38 complete, 17 remaining; delta +0/+0; U56 added (56 engineering checkpoints).**

## S16 end-menu acceptance — blocked on demonstrated defects

[Current evidence](bend_end_menu_20261017.md) supersedes historical end-menu wiring
claims as desktop qualification. Two real gesture cases delivered; one invocation,
2 failed: sidebar DOM absent, context explicit strand scope replaced by null.
Context placement and preview/Cancel preservation/disposal/empty console pass
before scope failure; publication/undo/reopen remain unexecuted. 104 focused tests
pass but do not cover these defects. Neither end-menu surface is accepted.
ISSUE-145 and MV-48 remain open; S17 in the handoff is the sole unstarted successor.
No fixed release exit or milestone count changed; no repair begun in S16.


## S17 end-menu repair and targeted acceptance

[S17 evidence](bend_end_menu_repair_20261017.md): restored actual sidebar markup
and Properties reveal; canonical explicit selectors preserved through both owned
menu paths, stale explicit selection refused, empty selection retains null scope.
Both S16 real-gesture Bend cases pass placement/Cancel/one Apply/undo/reopen,
strict console/disposal and no legacy mutations. Full frontend 9,277 passed/1
skipped; lint/memory clean. Two browser invocations, with a string-format-only test
correction before the final pass. Required production smoke is outstanding S18.
Neither complete release matrix nor fixed milestone exit is satisfied.


## S18 required smoke — delivered

[Production smoke evidence](production_smoke_20261017.md): 23/23 cases pass in one
isolated invocation using actual production startup/default gates; 25 launcher
and three config tests pass. Independent cleanup and Example digest verification
pass. Clears S17's outstanding smoke gate, not the full release matrix. S19 Twist
end-menu parity is the sole current successor; historical sequencing is superseded.


## S19 Twist end-menu parity — delivered

[S19 evidence](twist_end_menu_20261017.md): four real Bend/Twist end-menu cases
pass (two new Twist cases), one invocation; 52 focused tests pass; cleanup verified.
Accepts only tiny native explicit-strand end-menu creation/persistence, not all
controls/targets/resources. S20 controls/toolbar acceptance is the sole successor.


## S20 Twist controls/toolbar — delivered

[S20 evidence](twist_controls_20261017.md): Twist units/handedness/reversed-plane
history input persistence and toolbar selection Change/Clear/Cancel/Apply/undo/
reopen pass; retained Bend toolbar also passes. Three browser cases in one run,
33 focused tests; strict console and cleanup verified. Other targets/polymer,
failure/recovery, chains and full resource/release exits remain. S21 was selected then; its outcome and current S22 successor are recorded below.

## S21 recovery branch stop

[S21 evidence](lost_apply_reply_20261017.md): retained browser run fails both cases
on excess Status requests after receipt/adoption. Persistence and final console
checks remain unverified. Cap reached; S22 diagnoses the request count and completes
the same cases. This does not qualify failure recovery or any fixed release exit.

## S22 lost-reply recovery — accepted on tiny native fixtures

[S22 evidence](lost_apply_recovery_20261017.md): both Bend/Twist cases pass through
receipt recovery, adoption, persistence and strict console checks. Three Status
reads are required by the existing recovery/guarded-refresh contract, now asserted
in order with identical bindings and receipts. This clears that narrow app branch;
other failures, chains and resource/rollout exits remain. S23 targets the existing
immutable host's missing nonpublishing evaluation seam, not another happy-path
permutation. Larger-part preview still requires projection/HTTP/editor integration.

## S23 private staging — internal integration step

[S23 evidence](immutable_geometry_staging_20261017.md): existing immutable host now
supports nonpublishing sealed candidate evaluation reused by edit/append. 106 focused
tests pass. No desktop/large-part acceptance follows. S24 supplies native display
projection; prefix controls, leases and editor/HTTP integration remain. Gates stay false.

## S24 staged native display — internal integration step

[S24 evidence](immutable_geometry_projection_20261017.md): bounded native component
projection through existing worker transport, source-bound and nonpublishing;
104 focused tests pass. This is final staged-revision display, not feature-prefix
controls. S25 integrates sealed historical Prepare/Evaluate/Cancel with the existing
lease owner; Apply/editor/creation and representative resources remain unqualified.

## S25/U55 sealed historical lease integration

[S25 evidence](immutable_preview_lease_20261017.md): same catalog/worker ownership
now admits sealed historical Prepare/Evaluate/Cancel with true prefix controls and
native display, 151 focused passes. Sealed Apply explicitly refuses; strict HTTP
and editor integration remain absent. S26 integrates Apply/receipt lifecycle before
any public bridge. No desktop/resource acceptance or gate enablement claimed.

## S26/U56 sealed historical Apply and receipt integration

[S26 evidence](immutable_preview_apply_20261017.md): sealed Apply independently proves
source/suffix, publishes through the immutable permit/transaction and retains shared
receipt/Cancel/undo semantics; 170 focused passes. Strict HTTP and editor integration
remain absent. S27 adds gated HTTP admission; no gate, desktop or resource acceptance.

## S27/U57 strict sealed preview HTTP admission

[S27 evidence](immutable_preview_http_20261017.md): five historical preview paths
reuse the existing strict dispatcher, bounded body reader, source-bound host and
worker/receipt owners. Native HTTP Bend/Twist Apply/Status/Cancel/undo and acquisition
refusals pass; request cancellation drains bounded work. 172 unique focused tests
pass after correcting the obsolete blanket strict-route refusal assertion. No app,
latency or broad acceptance. FH-20 growth flagged at three checkpoints; fixed exit
unchanged. S28 is solely the sealed design/geometry read contract needed by existing
post-Apply refresh; not started. No gate or scientific changes.

## S28/U58 bounded sealed design/geometry reads

[S28 evidence](immutable_display_reads_20261017.md): complete native wire responses,
including full feature recovery and straight display geometry, are projected in the
existing bounded worker. Native Apply-to-refresh, ordinary response parity, source
refusals and disconnect cleanup pass. 177 focused tests; no browser or broad run.
S29 is the isolated sealed historical desktop integration, unstarted. FH-20 remains
open/growth flagged at four checkpoints; all fixed exits and production gates remain.

## S29 partial — sealed desktop harness and readiness blocker

[S29 evidence](sealed_history_desktop_20261017.md): explicit sealed fixtures and
strict design routing are wired in the isolated test app; policy/gates restore on
failure. Nine backend/four frontend harness tests pass. Both cases fail in both
browser invocations; final failures occur at readiness handoff completion after
geometry appears, before Open/evaluate/Cancel/Apply. The cap is exhausted.
GET `/api/design/readiness` returns 403; its available report is required to finish
handoff. View volumes, dimensions, VR references, active jobs and collaboration
status also emit 403 polling errors. Do not whitelist or hide these to claim a
pass. S30 addresses only readiness; later desktop acceptance must retain all
remaining errors and lifecycle assertions. 21/38, delta0; U1–U58 unchanged.

## S30/U59 bounded sealed readiness

One closed readiness GET now preserves ordinary part facts and current simulation
evidence through the existing bounded worker. Six focused targets pass; no browser
or broad suite ran. [Evidence and limits](immutable_readiness_20261017.md).
S29 remains partial; other refused polling and lifecycle acceptance remain open.
S31 annotation read pair is the sole unstarted successor in the current handoff.
21/38 complete, delta0; 59 engineering checkpoints, FH-20 checkpoint5 growth flagged.

## S31 partial annotation reads

Strict annotation reads support admitted dimensions and empty view volumes.
Populated view volumes are rejected by existing sealed preservation, so S31
acceptance is partial. [Evidence](immutable_annotation_reads_20261017.md).
S32 is the sole unstarted successor: bounded preservation of that one field,
publication/lifecycle checks and populated-read acceptance. No browser run or
release qualification. 21/38, delta0; 59 engineering checkpoints unchanged.

## S32/U60 geometry-only view-volume preservation

Bounded exact view-volume records now survive sealed geometry publication,
Apply, undo/redo and file recovery; populated annotation HTTP parity completes
S31 acceptance. Batch and other preserved-field admission remain unchanged.
[Evidence and limits](immutable_view_volume_preservation_20261017.md).
21/38 complete, delta0; U60 is FH-28 checkpoint11, growth flagged. Full
immutable/resource and desktop release exits remain open. S33 session-status
read pair is the sole unstarted successor in the current handoff.

## S33 strict service-status read pair

VR-reference and peer-status GETs are admitted with bounded status input/output
and existing service owners. Strict peer observation does not rewrite the registry;
ordinary address repair remains. [Evidence](strict_service_status_reads_20261017.md).
114 focused tests pass; no browser qualification. S34 active-job polling is the
sole unstarted successor. 21/38, delta0; 60 engineering checkpoints unchanged.

## S34 active-job admission stopped at side-effect boundary

Polling reaches NAMD health/metrics/finalization and mrDNA extraction/cache
publication; runtime reconciliation also creates lock files. Isolated tests
intercept these calls. No production source or strict allowlist changed.
[Evidence and remaining acceptance](active_job_observation_boundary_20261017.md).
S35 assessment/finalization separation is the sole unstarted successor.
21/38, delta0; 60 engineering checkpoints unchanged. No browser acceptance.

## S35 bounded activity decision seam

NAMD/mrDNA reconciliation now consumes shared pure decisions with explicit
unknown/finalization-required outcomes. Existing ordinary effects remain.
[68-test evidence and limits](activity_assessment_seam_20261017.md).
At S35 closeout, S36 bounded evidence acquisition was the successor; S34 HTTP and
S29 desktop acceptance remain pending. 21/38, delta0; 60 checkpoints unchanged.

## S36 bounded activity evidence

NAMD/mrDNA observations now reuse native interpretation through finite read hooks,
with one bounded process inventory, explicit unavailable evidence and no lifecycle
effects. Ordinary defaults stay unchanged. [120 focused passes and resource limits](activity_observation_20261017.md).
At S36 closeout, S37 remaining-local-engine observational parity was the successor.
Strict polling, bounded discovery/projection and complete desktop acceptance stay
open. Counts remain 21/38,17 remaining (8 core/9 parked), delta +0/+0, U1–U60.

## S37 remaining local-engine observations

All four remaining engine adapters preserve native ownership/cache/stage predicates
without lifecycle effects. [120 focused passes and limits](activity_local_engines_20261017.md).
At S37 closeout, S38 bounded native catalog/summary projection was the successor.
Strict polling, source/owner completeness and full desktop acceptance stay open.
Counts: 21/38,17 remaining (8 core/9 parked), delta +0/+0, U1–U60 unchanged.

## S38 bounded native catalog and summary

The internal six-family catalog shares native normalization, bounds discovery and
projection, and retains unknown archive/source/ETA/owner evidence explicitly.
[150 focused passes and limits](activity_catalog_20261017.md).
At S38 closeout, S39 closed strict active-job HTTP reads was the successor. Restricted
HTTP admission, remaining metadata/owner completeness and full desktop qualification
stay open. Counts: 21/38,17 remaining (8 core/9 parked), delta +0/+0, U1–U60 unchanged.

## S39 supported strict activity HTTP

The exact GET adapter returns the existing shape only for complete supported
catalogs; unknown evidence refuses, with shared admission and identity/resource
checks. [150 focused passes and limits](strict_activity_reads_20261017.md).
At S39 closeout, S40 sealed Bend/Twist browser rerun was the successor. General
activity and full desktop/latency acceptance remain open; all rollout gates stay
false. Counts: 21/38,17 remaining (8 core/9 parked), delta +0/+0, U1–U60 unchanged.

## S40 sealed browser campaign — lifecycle incomplete

Two invocations produce zero passes/four failures. Readiness progresses; Open
(or initial design adoption) loses the shared slot to overlapping reads. Exact429
body and separate403 inventory are in [S40 evidence](sealed_history_contention_20261017.md).
Both roots/processes/ports cleaned. Only bounded test diagnostics changed, with no
weakened assertions. At S40 closeout, S41 foreground shared-slot admission was the
successor. Full lifecycle/console/latency/rollout exits remain open; counts21/38,
17 remaining (8 core/9 parked), delta+0/+0, U1–U60 unchanged.

## S41 foreground admission behind background reads

The existing shared owner now permits one foreground reservation behind an admitted
annotation/activity read. Polls cannot overtake it; waiting consumes the original
deadline and no worker input is allocated until admission. Existing cleanup retains
worker ownership. [Validation and limits](foreground_work_admission_20261017.md).
At S41 closeout, S42 sealed preview Apply staging admission was the successor;
its immediate-refusal seam was confirmed in source. Startup 403s and full
sealed desktop/console/latency qualification remain open. No frontend behavior,
rollout or scientific change; counts21/38,17 remaining (8 core/9 parked), delta+0/+0,
U1–U60 unchanged. This correction does not close a fixed milestone.

## S42 sealed Apply admission

Historical Apply now reserves the existing shared slot behind background reads;
source/lease checks run before capture, waiting consumes the computation allowance,
and staging cannot outlive lease expiry. Native one-publication/receipt and stale
refusal evidence is in [S42 validation](sealed_apply_admission_20261017.md).
At S42 closeout, S43 was the successor: at most two sealed browser invocations
with unchanged lifecycle/console assertions. Startup403s and full desktop/latency exits
remain open; no gates/pruning/scientific changes or milestone credit. Counts21/38,
17 remaining (8 core/9 parked), delta+0/+0; U1–U60 unchanged.

## S43 sealed browser campaign — late refresh remains unqualified

Two invocations yield zero passes/four failures. Three executions complete Cancel
preservation and receive Apply200 but miss the fixed popup-close deadline; one
is blocked by a toast over the Feature Log tab. Diagnostic Twist's final receipt
check is5.457s after Apply; later revision/history/redo/private-root state shows
progress, not a latency or final proof/console pass. [Evidence](sealed_postapply_campaign_20261017.md).
At S43 closeout, S44 coherent receipt-bound sealed refresh latency was the successor.
No production change/gate/milestone credit;21/38,17 remaining (8 core/9 parked),
delta+0/+0; U1–U60 unchanged. Startup errors and full desktop exits remain open.

## S44 combined sealed refresh — desktop qualification partial

Opt-in combined design/geometry uses one decode/worker/budget; transport retains
ordinary fallback and receipt/revision/local-context checks.34 distinct backend
cases and9287 frontend tests pass (one skipped). Bend adopts in4.636s once, but
four app executions fail later or before reaching Apply. [Evidence](combined_sealed_refresh_20261017.md).
At S44 closeout, S45 passive polling versus foreground history admission was the
successor; exact holder of the Open429 remains unproven. S44 two-family latency,
final HTTP/proof/console and startup acceptance remain open. No gate/milestone
credit;21/38,17 remaining (8 core/9 parked), delta+0/+0; U1–U60 unchanged.

## S45 passive readiness admission — polling coordination partial

Readiness now uses the existing passive lane; native and HTTP history commands
reserve foreground admission and wait for actual cleanup.120 focused backend
checks pass. Both sealed browser fixtures pass lifecycle, final state/geometry/proof
and five-second adoption (Bend3.376s /Twist4.407s), but both fail the strict console
assertion on403/429 responses. [Evidence](passive_readiness_admission_20261018.md).
At S45 closeout, S46 coordination of supported passive consumers through the
existing request owner was the successor. Startup403 capability qualification remains
later work. S44 tiny-fixture two-family timing and later HTTP/proof checks are now
executed successfully; no full desktop/console or broad resource acceptance is
claimed. No gate/milestone credit;21/38,17 remaining (8 core/9 parked),delta+0/+0;
U1–U60 unchanged. Fixed exits remain unchanged; ISSUE-100/MV-48 remain open.

## S46 passive desktop coordination — console acceptance remains open

Supported passive reads now share bounded client admission, foreground priority,
coalescing and stale/cancel retirement; active transports drain before release.
The final full frontend run passes9,296 tests/one skipped across773 files. Final
sealed cases pass lifecycle, final geometry/proof and adoption at3.363s Bend /
3.292s Twist. Both havezero429 console errors but37 unsupported403s each; strict
console acceptance still fails. [Evidence](passive_desktop_coordination_20261018.md).
The final geometry assertion uses the desktop request owner without adopting its
response or filtering errors; independent proof and all original limits remain.
Historical S46 sequencing selected S47; superseded by the S47 scope correction and current handoff.
No gate/milestone credit;21/38,17 remaining (8 core/9 parked),delta+0/+0; U1–U60
unchanged. ISSUE-100/MV-48 and fixed FH-20/FH-28 exits remain open.

## S47 — Startup inventory and scope correction, October 18

Historical result: S47 inventoried37 HTTP403 responses across15 startup routes per
sealed fixture. Lifecycle/geometry/proof passed; strict console acceptance failed.
The user corrected simulation scope and the unvalidated capability runtime draft
was removed. Only bounded failure aggregation remains. See
[S47 evidence](sealed_startup_scope_review_20261018.md).
S48 was selected at that closeout; the current handoff now supersedes that queue.

## S48 — Bend with downstream attached Sweep, October 18

S48 qualifies one tiny ordinary Bend→attached Sweep chain through the existing history owner. Exact Cancel/redo preservation, independent native replay, downstream identity/parameter preservation, changed Sweep geometry and app save/undo/redo/reload pass. Final focused host test:1 passed; harness boundary:10 passed; strengthened browser case:1 passed with clean console. No production behavior changed. Sealed startup and full tool/resource acceptance remain open. S49 Twist→Sweep replay qualification is the sole unstarted successor. No gate or milestone advanced.

See [S48 evidence](bend_sweep_replay_20261018.md). This verifies editing Bend with
a later Sweep, not the complete Sweep editor or sealed-host acceptance. S49's
exact bounded contract is in the current handoff. Fixed exits remain unchanged.

## S49 — Twist with downstream attached Sweep, October 18

S49 qualifies the tiny ordinary Twist→attached Sweep chain and preserves Bend coverage. Independent native replay, exact Cancel/source/history/redo, stable downstream inputs/identities, full geometry and desktop Apply/save/undo/redo/reload pass. Twist changes the inherited radial frame while preserving this straight fixture's attachment origin and axial direction. Focused host2 passed, harness11 passed, browser2 passed with clean consoles. No production behavior changed. S50 attached Sweep history-editor desktop qualification is the sole unstarted successor. No gate or milestone advanced.

See [S49 evidence](twist_sweep_replay_20261018.md). Tiny ordinary chains do not
qualify all controls, sealed-host or resource acceptance. The current handoff
selects S50 for the Sweep editor itself; fixed exits remain unchanged.

## S50 — Attached Sweep editor desktop workflow, October 18

S50 qualifies one tiny ordinary attached Sweep history-editor workflow through a later Extrude. Numeric path edit/add/remove, automatic/explicit orientation, Previous/Next, preview toggles, exact Cancel, Apply and undo/redo/save/reopen pass with native geometry/proof and clean console. Native oracle1 passed, harness12 passed, focused frontend23 passed, final browser1 passed. Test-only paired gates restore; production behavior is unchanged. S51 Bundle Extrude history editing through Bend→Sweep is the sole unstarted successor. No gate or milestone advanced.

See [S50 evidence](sweep_editor_desktop_20261018.md). MV-51 remains open for
other source/control variants, canvas gestures, failures and resource acceptance.
S51 targets the earlier Bundle Extrude row; the handoff owns its exact bound.

## S51 — Bundle history through Bend/Sweep, October 18

S51 qualifies earlier Bundle Extrude history editing through Bend→attached Sweep. Draft controls and exact Cancel, source-bound length/name Save, independent native replay, downstream identity/input preservation and desktop undo/redo/save/reopen pass with clean console. Real-worker oracle1 passed, harness13 passed, focused frontend42 passed, browser1 passed. No production behavior or additional gate changed. S52 remaining six Extrude-family desktop workflows is the sole unstarted successor. No milestone advanced.

See [S51 evidence](bundle_editor_desktop_20261018.md). Bundle's other draft
options were cancelled; only length/name publication is qualified here. MV-50
stays open. S52's fixed six-family matrix is defined in the current handoff.

## S52 — Six-family Extrude desktop matrix, October 18

S52 qualifies the initial six-family Extrude desktop matrix: Segment, Continuation, Deformed Continuation, Frame, Circle and Overhang. Real-worker native replay6 passed, harness19 passed, focused frontend42 passed; final browser7 passed including Bundle regression, with clean consoles. An initial Overhang timeout exposed excessive per-field assertion overhead; aggregate presence checking preserves all exact geometry values and the unchanged deadline. No production behavior changed. S53 Sweep source-variant desktop matrix is the sole unstarted successor. No milestone advanced.

See [S52 evidence](extrude_family_matrix_20261018.md) for the exact committed
control inventory. Initial family lifecycles qualify; alternate modes, failures,
races and resources remain open. S53 is defined in the current handoff.

## S53 — Sweep source-mode desktop matrix, October 18

S53 qualifies independent, attached-start and sticky-detached Sweep history editing with later Extrude. Native fixture4 and source-contract40 passed, harness22 passed, focused frontend23 passed; final three-case browser matrix passed with clean consoles. Prefix source inventory, ligation draft controls, fixed-origin orientation, saved source/detach identity, exact Cancel, full native geometry, Apply and persistence are covered. Test synchronization corrections required no production change. S54 Sweep downstream-nick success/refusal desktop workflow is the sole unstarted successor. No milestone advanced.

See [S53 evidence](sweep_source_matrix_20261018.md). Source inventory/plane state and ligation toggles are exercised; source switching, alternate planes/strands and canvas picking are not claimed. MV-51 and fixed FH-27 remain open. S54 is defined only in the current handoff and is unstarted.

## S54 — mid-log refusal (October 18, 2026)
- Current status and sole successor: [session handoff](session_handoff.md); operating contract supersedes historical rules above.
- Replaced provisional Sweep expansion with the nearer Bend/Twist C7 app gap; no production changes.
- Both existing Bend/Twist→Sweep fixtures seek to cursor 1 through the real client, then exercise history Edit and toolbar creation.
- Edit refuses with a visible reason; creation refuses with its own reason and retains the selection picker with disabled Apply; Cancel closes it.
- Exact design/history/redo/revision and adopted geometry are preserved; no mutation requests; returning to tip permits Edit/Cancel.
- `NADOC_HISTORY_E2E_GREP='mid-log creation' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`: final **2 passed (34.1 s)**, clean consoles.
- First two runs: 2 failures each from incorrectly expecting the refused creation picker to close; corrected to its documented existing refusal behavior, retaining strict state/request checks.
- `node --check frontend/e2e/bend_release.spec.js` passed; independent cleanup: all three owned roots absent, no accessible marked processes, ports 8004/5177 bind, no workspace fixtures; 32 protected environments unreadable.
- No interaction latency measurements, representative-design claim, scientific changes, gate flip, milestone close or broad-suite run. C7 evidence is bounded-fixture only.

## S55 — downstream nick replay (October 18, 2026)
- Current status and sole successor: [session handoff](session_handoff.md).
- Added Bend/Twist→native nick fixture variants, using the existing routing-group representation and nick convention; invalidated recovery snapshots.
- Existing fixture proof route now exposes independent root/command replay authoring and geometry for these variants; no production changes or new endpoints.
- Two browser cases assert exact Cancel including redo, one Apply, complete authoring/helix/strand/ordered-domain identity, full native geometry equality and exact adopted placement fields.
- One-step undo/redo and save/reopen retain identity and geometry; root replay is checked initially, after Apply, after redo and after reopen; clean tool consoles.
- `just test-focused tests/test_deformation_history_app.py -k nick`: final **4 passed, 22 deselected (2.80 s)**, including serialized fixture round-trip.
- `NADOC_HISTORY_E2E_GREP='downstream nick cold replay' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`: final **2 passed (30.1 s)**.
- Initial browser run: 2 failures at reopened proof because fixture used a bare minor row; corrected to native routing group without relaxing assertions. Earlier selector invocation selected no tests before edits ran (`python` unavailable; used `python3`).
- `node --check frontend/e2e/bend_release.spec.js` passed. Both exact scratch roots absent; no accessible marked processes or workspace fixtures; 32 process environments unreadable.
- No listeners on 8004/5177; both bind with SO_REUSEADDR (initial plain bind encountered TIME_WAIT). Launcher stopped owned processes before deleting scratch.
- No interaction latencies measured; bounded-fixture C3/C6 evidence only, no representative-design or full-suite claim. No gate or milestone changed.

## S56 — upstream deletion decision blocker (October 18, 2026)
- Added two C5 cases using Bend/Twist→nick fixtures: dependent IDs/labels/reasons, pre-decision preservation, Cancel, cascade and undo/proof.
- `node --check frontend/e2e/bend_release.spec.js`: passed.
- `NADOC_HISTORY_E2E_GREP='upstream deletion dependents' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`: **2 failed**, repeated **2 failed** after moving preservation checks before visibility.
- Both final cases verify correct `edited-feature`/`nick-child` identities, labels/reasons and exact canonical/browser preservation, then fail at missing dialog (5 s assertion timeout).
- Cause: `frontend/src/ui/primitives/dependents_dialog.js:65–71` creates but never opens the modal; `modal.js:120–127` requires explicit `open()` to append it.
- Shared dependency UI prerequisite: stopped under contract §5/S56 exclusions; no production repair. Cancel/cascade/undo and final strict-console assertions remain unexecuted; C5 not passed.
- No interaction latency measurement; no full suites run. No gate or milestone change. Current state and user-decision successor: [handoff](session_handoff.md).
- Both exact roots `/tmp/__e2e__history-dqojntjl` and `/tmp/__e2e__history-4816mo4i` independently verified absent; no accessible marked processes or workspace fixtures; ports 8004/5177 bind with SO_REUSEADDR.

## S57 — authorized dependents-dialog repair (October 18, 2026)
- User authorized the shared-dialog repair and resumption at counter 3. Open the existing modal; forward sub-index/options through the app deletion wrapper so cascade reaches the existing API.
- Two Bend/Twist→nick C5 cases now pass: correct visible dependent IDs/labels, exact pre-decision/Cancel preservation, one confirmed deletion, one-step undo and independent proof.
- Undo adoption matches all 17 shared native placement fields exactly; a subsequent full read also matches the entire original geometry payload exactly. No topology/geometry production changes.
- Harness stubs only default-animation startup POST; console checks remain strict. No lifecycle or endpoint added.
- `just test-frontend`: **773 files passed; 9297 tests passed, 1 skipped (337.58 s)** after modal fix, before wrapper repair. Final wrapper exercised by browser run; no second full-suite run.
- `NADOC_HISTORY_E2E_GREP='upstream deletion dependents' just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`: final **2 passed (25.0 s)**, clean consoles.
- Five earlier runs: 2 failures each; missing cascade forwarding, compact/full comparison mismatch, and unsuccessful baseline round-trip setup (animation/empty undo stack). Final test checks actual adopted placements before full-read equality; no assertions removed.
- `node --check` on both production files and browser spec, plus `git diff --check`: passed. No interaction latencies measured; bounded-fixture evidence only.
- Six exact `/tmp/__e2e__history-` roots (ocry3tf8, x6g50wev, rhal3pef, 0zflnp4m, cbtgicvz, z_6eg5ws) absent; no accessible marked processes or workspace fixtures; 31 environments unreadable; ports 8004/5177 bind with SO_REUSEADDR.
- No gate/milestone change; ledger/memory untouched. Current state and single successor: [handoff](session_handoff.md).

## S58 — production gates on, real-size parts, legacy fallback, C4 (October 18, 2026; Claude session, user-authorized option A)
- Gates ON: `DEFORMATION_PREVIEW_ENABLED`, `ISOLATED_DEFORMATION_HISTORY_ENABLED`, `ISOLATED_DEFORMATION_CREATION_ENABLED`. Harness plugin now verifies (not flips) them.
- Blockers removed: toy allowances (16 helices / 1024 slots / 128 commands / 1 s; 30k-node 25 ms capture; 16-helix display contract) raised to part scale (512 helices, 2M slots, 120 s, 2 s capture); prefix replay admits `ORDINARY_UNESTIMATED` routing/scaffold/staple/sequence kinds; imports, NP, protein, photoproduct, relax and autorefine kinds stay refused. Output budget kept; C `json.dumps` replaces pure-Python iterencode; node walk only when size could exceed it. Strict service reads keep 2 MB/200k.
- Legacy fallback: prepare refusals `missing_recipe_root|missing_proof_contract|unsupported_preview_scope|preview_limit|recipe_not_reproducible` continue the same gesture in the legacy editor (history Edit, toolbar/sidebar launcher, blunt-end menus). All 8 workspace files with bends/twists lack recipe roots → legacy. `historical_cursor` still refuses (C7).
- C4: Apply refusal names the earliest failing downstream feature ("F3 Bend cannot regenerate after this edit: …"); nothing publishes; Cancel exact.
- C8 (in-process host, scaffolded+stapled honeycomb, before→after vs legacy PATCH+geometry refetch): 6hb×126 prepare 0.34 s, evaluate 0.10 s, apply 0.05 s (legacy ~0.1 s); 18hb×252 2.1–2.3 s / 0.67–0.84 s / 1.1 s (legacy ~0.95 s); 18hb×504 5.8 s / 1.55 s / 3.5 s (legacy ~1.9 s). Budget miss: 18hb×252 <2×; 18hb×504 ~3× → perf task S59. Browser render/transfer not separately timed.
- Tests: focused frontend 194 passed; `just test-frontend` 773 files, 9306 passed, 1 skipped (344 s); history browser suite **38 passed (10.0 m)** incl. 17-helix open, legacy-fallback and C4 cases, cleanup verified; new `tests/test_deformation_preview_real_scale.py` 3 passed; bounding-mechanism tests pinned to test scale via `tests/preview_test_limits.py`.
- `just test-smart`: FAST, 15 failed / 18955 passed / 19 skipped, DEFERRED full suite, FAST SUITE TOO SLOW (371 s). 4 failures were this change and are fixed (rerun pass); 13 pre-existing and untouched by it: 10 strict registration (Codex's untracked sealed strict-preview admission returns 415), `test_part_immutable_evaluation` strict GET 409, 2 `test_junction_balance` tolerance (clean modules).
- Open: C8 large-part preview (S59). October 19 update: desktop fallback for unverified parts has been removed; unsupported history refuses without canonical mutation. Other legacy creation consumers are not claimed removed. C4 now adds transient failure/blocked history rows through the shared editor; a downstream fixed-endpoint Bend failure and Cancel pass in the isolated browser. Full frontend9354 passed,1 skipped. Not verified on the user's live dev server; verified in the isolated real-frontend harness.

## S60 — R1 incremental rebuild (October 18, 2026)
- `part_replay_cache.ReplayChain`: full-key hits and, for `DEFORMATION_INDEPENDENT` kinds after a geometry-only edit, topology hits (cached output + current deformations). Wired into preview prefix replay, Apply source proof and `regenerate`.
- Invariants and cold-replay equality: `tests/test_part_replay_cache.py` 8 passed (HC/SQ, bend/twist, 7 routing kinds).
- 18hb×504: Apply after routed bend 3.5 s → 0.25 s; bend before autostaple, repeat Apply 0.16 s (first after load ~3.2 s). Open/evaluate now display-bound (S61).
- Browser history suite 38 passed; `test-smart` FAST 14 failed/18964 passed (1 mine, fixed; 13 pre-existing).

## S62 — R2 legacy conversion (October 18, 2026)
- Option B with frozen deformation-independent routing rows; exact `reproduced_import` proof gate; new-file save, original untouched (browser case asserts bytes).
- Survey: 78/89 convert exactly; 34 keep editable features; 3/8 legacy bends/twists editable. Limits: 1 MB import root (manifest-hashed), unseeded extrusions, stale legacy rows.
- Fixed workspace-save identity stamp breaking every native proof (Apply 409 after first save).
- Browser history suite 39 passed; test-frontend 9310 passed; test-smart FAST 13 pre-existing failures only.

## S61 — C8 large-part preview latency (October 19, 2026; Claude session)
- Browser bug fixed: the frontend DNA display validator still had toy caps (16 helices, 128 strands, 1,024 nt, 16 axes), so the isolated editor refused any real part ("display allowance exceeded"). Caps now equal the backend contract (`DNA_DISPLAY_LIMITS`).
- Server evaluate (18hb×504, in-process): 1.3–1.7 s → 0.63–0.70 s. Display reads the owned prefix (no deep copy; non-mutation pinned), orjson size check with explicit NaN/∞ refusal (projection-validated panes not re-walked), bulk coordinate finiteness, numpy bounds (native values kept), GC paused per evaluate (re-entrant), gzip skipped for loopback preview responses.
- Client: hidden cylinder-LOD tubes not built in static preview layers; copying decode replaces structuredClone (~5×); layer builder reuses the controller's validation of the same object.
- Browser (new `e2e/bend_preview_latency.spec.js`, fixture `bend-large`; render loop paused because this desktop's headless WebGL is SwiftShader at ~2 s/frame, so GPU raster is excluded): update median 1.75 s → 1.46 s, p95 1.98 s → 1.67 s. Split: server+headers ~0.95 s, body 0.08 s, client ~0.6 s. Open (prepare) 4.5 s server / ~6.3 s browser. 18hb×252 server evaluate 0.35 s.
- Not kept: memoizing arm frames in `deformed_helix_axes` (0.31 → 0.10 s, byte-identical output; browser median 1.27 s / p95 1.42 s) because `deformation.py` is pinned by the CPD and duplex-relax engine manifests — needs a user-reviewed manifest transition.
- C8 status: small/medium parts within the 2× allowance; the full-size 18hb×504 part is ~2.9× → performance task remains (contract §3), or the user revises the large-design budget.
- Checks: `tests/test_preview_display_performance.py` 6, preview DTO/session/real-scale 84 (one unreproduced failure in 4 runs), frontend codec/limit tests, `just test-frontend` 776 files / 9331 passed, manifest tests 185 passed after reverting the frame cache; `test-smart` and history browser suite results are in the handoff.

## S63 — compact preview transport, frame cache shipped (October 19, 2026; Claude session)
- User approved changing CPD/duplex-relax engine pins: `deformed_helix_axes` arm-frame memoization re-applied (byte-identical axes on 42 designs); reviewed transition `preview-axis-frame-cache-v1` recorded (16 edges retargeted, 2 added; prior policy and before-capture in this folder); manifest tests 187 passed.
- Preview DNA component v3: coordinates as one base64 little-endian float64 block (28 doubles/record), other columns as JSON rows; Python and JS decoders accept v2 rows and v3 blocks; decoded records equal the native rows exactly. Payload 13.7 → 8.5 MB.
- Client: unrolled compact decoder (103 → ~15 ms); layer takes the validator's decoded records once.
- Browser `bend-large` (GPU raster excluded): median 1.46 → 1.17 s, p95 1.67 → 1.23 s; server+headers ~0.73 s, client after body ~0.41 s. In-process server evaluate ~0.67 s, spread over geometry 0.14, record validation 0.14 (incl. guard slab recompute), axes 0.09, prefix deep copy 0.05, four whole-model admissions 0.06, packing 0.035.
- Checks: `just test-frontend` 776 files / 9335 passed; `test-smart` FAST 13 failed (known) / 19022 passed; preview/comparison backend 127 passed.

## S64 — Session-local rows and occupancy, October 19

Opt-in evaluation reuses prepare-time scalar rows and equal topology inventory; finite/slab/axes guards remain per update. Backend focused146 passed. Browser median1113 ms, p95 1208.8 ms, ~6.3 MB response; the explicit1000 ms assertion still fails. User chose Sweep/Extrude and history/dependency completion first, retaining this gap. No gate or completion credit.

## C8 qualification — October 20, 2026

- `bend_preview_latency.spec.js` now covers Bend/Twist on native 6×84 and 18×504 recipes, records file sizes, and enforces preview1000ms / Apply6000–20000ms / Cancel400ms without a loose default.
- Each of12 samples requires one successful unique evaluation and a complete candidate; Apply adoption, exact Cancel, no canonical Cancel reads/writes and fixture cleanup are checked. Software rendering pauses before fixture setup; GPU raster remains excluded.
- Focused browser command: `NADOC_HISTORY_E2E_GREP='(bend|twist)-(small|large) preview Apply and Cancel latency' NADOC_C8_SPLIT=1 scripts/validation_guard.sh uv run --no-sync python scripts/run_deformation_history_e2e.py`.
- Result:2passed/2failed, only large preview ceilings failed. Small Bend/Twist p95=118/112ms, Apply950/425ms, Cancel72/67ms. Large p95=1315/1136ms, Apply4664/4417ms, Cancel162/157ms.
- Saved fixture sizes: Bend small61783/large750241bytes; Twist small61791/large750209bytes. Generated native recipes, not a new existing-workspace or hardware-GPU qualification.
- Server profile (three unprofiled samples): evaluate57–60ms, display568–586ms, JSON4–5ms. Native geometry, record validation and helix axes dominate; browser diagnostic server701/673ms, after-body layer369/392ms.
- Final assertion aggregation uses soft failures so all budgets and fixture console checks run even on a latency miss. That reporting-only edit passed syntax checks; its queued browser repeat was cancelled behind another full suite.
- Focused Ruff and both JS syntax checks passed. No production behavior changed; broad suites were not rerun for this harness-only task. No molecular sources, manifests, goldens or gates changed.
- Own browser scratch `/tmp/__e2e__history-w9btjio7` and profiler scratch `_66eaqqe` independently absent; interrupted/cancelled queued checks created no roots. Compact logs/scripts remain under `.development-artifacts/feature-history-focus/`.
- C8 remains open; current counts and the single next task are in the [handoff](session_handoff.md).

## Native preview buffer reuse — October20,2026
- Reuse one detached candidate buffer with exact topology/scalar inventory checks; retain native bead/slab/connector poses. Private guides use sampled polylines with shared native bp clipping and no domain-gap joins; canonical axes keep their defaults.
- Compact scalar validation and finite-block checking avoid per-update record/coordinate-array allocation. Failed candidate updates preserve the last valid visible scene; resized guide buffers release their former GPU owner.
- Focused preview23pass and native wire/render14pass verify molecular matrix parity and exact guide samples; resized-buffer ownership also passes in the full frontend run.
- Fixed12-sample four-case C8 now4pass. Small Bend/Twist preview101/108ms, Apply936/422ms, Cancel59/80ms; large preview866/942ms, Apply4377/5196ms, Cancel151/193ms.
- Same1000ms/6000–20000ms/400ms limits; GPU raster excluded. C8 passes; paired Bend/Twist tools and FH-20 are complete.
- Evidence: axis-lines-focused.log, axis-lines-native.log and axis-lines-c8.log in .development-artifacts/feature-history-focus/. Browser root /tmp/__e2e__history-tfn8qjbl independently absent.
- Final frontend780files/9395pass/1skip; backend FAST19099pass/83known failures/19skip, exact baseline failure set and no new errors; FULL deferred, aggregate timing debt retained. No native molecular placement, scientific constants, manifests or goldens changed.
