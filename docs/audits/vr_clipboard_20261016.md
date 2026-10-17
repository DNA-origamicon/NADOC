# VR clipboard validation — 2026-10-16

Copy and Paste are wired into the six-sector right touchpad wheel. Copy snapshots
its acknowledged selection, leaves the source intact, and draws a bounded mint
wire preview attached to the right hand. Paste applies the displayed rigid pose
through the existing undoable element-paste history path. The configured normal
VR launcher now points to the tested Archive build; the prior configuration is
retained for rollback. See [usage and supported scope](../vr_clipboard.md).

The initial cluster-only evidence below is historical; the follow-up section
records the final all-element/minimum-domain implementation and validation.

## Evidence

`.development-artifacts/vr-clipboard-20261016/app-isolated-settled/result.json`
records passing steady_fast, steady_deliberate, variable_fast, and
variable_deliberate runs. Each uses a real browser-owned private document and
physical OpenXR runtime with ScryWrite controller input. Two of three clusters
are selected. Checks cover Copy without a document mutation, stereo preview
pixels, hand translation and rotation, Paste, every pasted nucleotide's expected
transformed position, preservation of original helices, and Undo.

The observation setup uses ordinary bimanual grip to shrink scene presentation
by 0.2, so the complete ghost fits near the hand. A half-second capture settle
occurs outside timed gestures. Neither production targets, noise presets nor
input-delivery thresholds were relaxed. Inspected stereo images show both mint
copies beside the right controller, then solid geometry at the pasted pose.
Physical hand comfort and through-lens visibility remain manual coverage.

Native clipboard and wheel checks: **2 passed**. Focused clipboard, rigid-element
copy, event parsing, and wheel/catalog checks: **28 passed**. Frontend regression:
**672 files, 7,961 tests passed, 1 skipped**. Desktop smoke: **23 passed**,
with zero prefixed artifacts after teardown and the private workspace removed. Rigid-element placement has backend
coverage; its headset workflow remains unverified. Individual strand/domain/base
copying is not implemented.

## Preserved failures and regression limits

- `app-initial`: probe began before OpenXR focus; fixed by the existing readiness wait.
- `app-focused`: an unregistered history operation name rejected Paste; fixed by
  using the registered element-paste operation. This fixture also exposed that
  repeated createBundle calls replace the design; the final fixture appends.
- `app-final`: all four motion presets passed before runtime cleanup isolation.
- `app-isolated`: variable-fast thumb playback missed its 150 ms timing limit by
  reporting 289 ms lateness after diagnostic capture. The failed trial is retained.
  `app-isolated-settled` passed all four with capture settling outside measurement.
- `just test-smart`: **FAST**, 10,898 passed, 92 skipped, 2 failed, 4 setup errors.
  Both Alpine-worker failures and its 5.02 s slow-test flag came from an overlong
  Archive Unix-socket path. All 12 worker tests passed with shorter scratch;
  the flagged test took 1.19 s. No slow marker or timing threshold changed.
  The four CPD-preview setup errors report `Incorrect preview stereochemistry:
  cis-anti-I`; this work does not modify that scientific workflow.
- `just lint`: five unused imports in untouched files. Targeted lint of this
  change passes, and `git diff --check` passes.

The backend selector's deferral is retained verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.

## Storage and cleanup

Builds, screenshots, traces, raw stereo data, and logs are retained on mounted
Archive storage under the task directory. Final tour runtime/workspace roots
were removed; the new tour owns its capture configuration, sidecars, sockets,
and temporary files even on failure. Playwright teardown removed prefixed
fixtures and their project revisions. Earlier attempts inherited shared capture
storage and left empty runtime directories and tiny prompt sidecars; the
inventory records this residue rather than deleting historical directories by
mtime. The existing compositor and user documents were preserved.

`deployment.json` records the tested binary hash and previous build location;
`vr-capture-config-before.json` is the local launcher rollback snapshot.
`artifact-inventory.txt`, `backend-smart.log`, `worker-triage.log`, and `lint.log`
retain the detailed validation boundaries.

## Follow-up: all selection kinds and minimum owning domains

The user's final scope instruction supersedes the initial whole-cluster limit and
an intermediate whole-strand proposal. Base/end picks resolve to their owning
domain; bonds/crossovers resolve their endpoint domains; extensions retain their
terminal domain and extension. Explicit strands/clusters retain their selected
scope. Overlaps copy once, while gaps produce separate fragments. Real linker
bridge picks retain the bridge domain without its neighboring complement domains.
Rigid elements carry their owned DNA. Pose tests include rotations, loop copies,
skips, extensions, external protein anchors, and same-bp sites on different helices.

Copy validates an immutable browser snapshot against the complete canonical native
selection. The backend returns bounded source-space preview strokes for that exact
resolved scope. Native code applies the copy-time scene frame and follows the
right hand until Paste succeeds. This removes the old dependence on which selected
primitives happen to exist in the current representation. Mixed selections and
rigid-owned strand refs now survive native startup/default selection transport.

Rendered review exposed omitted rigid objects in normal native scene exports.
The fix adds selectable protein traces and nanoparticle cores, so pasted rigid
objects remain visible after the mint preview clears. The final probe additionally
checks added gold-core pixels at the placement region in both eyes, alongside
persisted placement matrices, original-object preservation and Undo.

Expanded evidence is under `.development-artifacts/vr-clipboard-all-20261016/`.
The authoritative final campaign is `app-visible/`: clusters, overlapping
base/bond/extension picks, and proteins plus nanoparticles each passed
`steady_fast`, `steady_deliberate`, `variable_fast`, and `variable_deliberate`
(12 browser/physical-runtime cases). Captures use the normal 0.2 bimanual scene
zoom for observation; preset noise, hit areas and timing limits are unchanged.
Eye images establish rendered visibility, not physical through-lens comfort.

The first expanded campaign (`app-initial/`) passed cluster/domain cases but
failed rigid startup: its trace records HTTP 422 for a nanoparticle selection kind
missing from the launch enum. That protocol is fixed and regression-covered.
The intermediate `app-final/` campaign was superseded after visual inspection
found absent committed rigid geometry. Its last rigid case also failed while
source edits were occurring during the campaign (native status `failed`, paste
wait timeout); it is retained, not counted as final verification. The final
`app-visible/` campaign ran with fixed application source and passed all cases.

The final private VR runtime `/media/jojo/Archive/cb-1a3nssrw` was removed and its
absence verified. Earlier expanded runtime roots `cb-nrbyftlm` and `cb-qjquj9oj`
were also verified absent. Test documents use `__e2e__` names inside private
Archive workspaces; global teardown removed project/revision artifacts. Existing
shared capture history, user documents and SteamVR compositor were preserved.

### Final regression checks and review

The final frontend sweep passed 672 files: 7,964 tests passed, one skipped
(`frontend-final.log`). The focused backend regression passed 107 tests after
making rigid export tolerate minimal test adapters with absent optional
collections (`focused-regression.log`). Native clipboard, selection-wheel and
interaction checks passed 3/3 (`native-final.log`); clipboard/wheel assertions
remain enabled in Release, and interaction uses its explicit require helper.

The final guarded `just test-smart` run (`backend-smart-verified.log`) finished
with 10,916 passed, 92 skipped and four pre-existing CPD preview fixture errors:
`Incorrect preview stereochemistry: cis-anti-I`. No feature failures remain.
This is not a clean full-suite pass. The runner reported:

```text
decision: FAST  (fast suite only)
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

The mandatory slow-test triage retained the six-engine/1,008-nt assembly input
preparation as one slow test in the assembly/CanDo area (5.90 s in sweep,
5.34 s focused). It passed focused; siblings stay fast. Transient revision/save
I/O stalls passed focused at 0.48/0.23 s and were not reclassified. The final run
used two workers to reduce Archive I/O contention: 174 s wall time, zero per-test
budget violations, slowest 2.70 s. The aggregate backstop still warned; the
11,009-item report showed distributed work across unrelated modules, with no
shared accidental slow fixture identified. No budgets were raised or further
fast tests relegated to suppress the aggregate warning.

Intermediate backend failures are retained: missing optional rigid collections
were fixed and regression-tested; long AF_UNIX scratch paths were shortened;
a global pytest basetemp override was removed because nested pytest workers
reject ancestor working directories. Five placement-journal incidents from
those failures were individually reviewed against their preserved reports and
focused reruns. No coordinate discrepancy or geometry-kernel change was involved.
Review evidence is in `placement-reviews/`; the original journal is preserved.

The marked assembly test was confirmed present with `-m 'slow and cando'
collection (one selected, six fast siblings deselected). Final targeted Ruff and
`git diff --check` passed. `python -m tools.native_placement_audit check` returned
`Native Full placement review gate: clear` after all checks.

The smoke gate passed **23 tests** in 1.3 minutes (`smoke-final.log`). It ran the
normal simulation guard followed by the guarded smoke and assembly-exit specs,
with only the artifact output path redirected to Archive. Its private workspace
was removed; default frontend report directories are absent (`smoke-cleanup.json`).
Final task scratch cleanup is recorded in `cleanup-final.json`; tested binaries,
stereo evidence, failed attempts and original placement reports remain available.

The normal local VR configuration now uses the final `native-build` directory.
Only `viewer_build_directory` changed. `vr-capture-before-final.json` preserves
the previous configuration, and `deployment.json` records the candidate binary
SHA-256. No active viewer was replaced and the SteamVR compositor was preserved.
Physical headset comfort remains a manual validation item.
