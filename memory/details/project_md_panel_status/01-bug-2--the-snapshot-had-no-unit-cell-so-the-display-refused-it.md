# Bug 2 — the snapshot had no unit cell, so the display refused it — supporting detail

[Topic head](../../project_md_panel_status.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Bug 2 — the snapshot had no unit cell, so the display refused it

A NAMD `.coor` (NAMDBIN) is coordinates only, so the one-frame DCD carried a **zeroed
box**. `ws._try_unwrap` registers MDAnalysis' `unwrap` for anything under
`_UNWRAP_MAX_ATOMS` (200k); it raises *"No box information available"* on the first frame
access, which happens inside `_load_sync` — so the load aborted, `universe` stayed `None`,
and every poll answered *"No trajectory loaded."* This affected **Alpine too**, for every
system under 200k atoms, for as long as the live-frame feature has existed.

Fix: fetch `output/<seg>.restart.xsc` alongside the `.coor` and set `universe.dimensions`
from it (`parse_xsc_dimensions`, pure + tested incl. triclinic). The `.xsc` is rewritten
with the `.coor`, so it is the box AT THAT STEP — which matters under NPT. Measured on
2hb_1xT: 59.18 × 81.31 × 127.50 Å, 90/90/90.

### The troubleshooting tool

`frontend/e2e/helpers/md_display_log.js` — `attachMdDisplayLog(page)` records the status
line (+ spinner), the readiness dot, the ⟳ state, `nadoc:md-display-state` events and the
console on ONE timeline, change-triggered, to `.jsonl` + a readable `.txt`. Attach before
`page.goto` (the event hook is an init script). **`state: 'frame'` is the only definitive
"something reached the scene"** — the status line merely echoes it, and both bugs above
presented as a confident-looking status line above an empty viewport. Logs are gitignored.

Still unmeasured: whether a ~32 MB SFTP every 2 min competes with a much larger run
(2hb_1xT is only 62,677 atoms), and whether `active_segment_name` resolves during the
relax ladder rather than production.

## The readiness dot described the PREVIOUS job (fixed 2026-08-08)

User report: "if I last launched a RunPod, then click on an Alpine job, the MD Display will
have a RunPod related message until it errors out." Three independent causes, all in the
same handful of lines, and each sufficient on its own:

1. **`mdReadinessIndicator` hardcoded `'on the pod'` for EVERY remote target.** The backend
   has always worded its own `not_ready_reason` per target (`md_display_status`: "the pod"
   vs "the cluster") — the dot, which is what you read first, did not. It now takes
   `executionTarget` and reads `on the pod` / `on the cluster` / `not local`. That last
   fallback is deliberate: naming a target we are not sure of is how this bug read.
2. **`_selectJob` cleared `_displayMeta` but never reset the dot.** The state, the tooltip
   AND the label all survived the selection change, so the previous job's answer stayed on
   screen for the whole round trip. New `_resetDisplayIndicator()`. It clears the LABEL as
   well as visibility+tooltip: `_setDisplayIndicator` only writes the label inside
   `if (spec.show)`, so hiding alone leaves the old words in the DOM — invisible, but one
   `display:''` away from being the wrong caption. The live spec caught exactly that as a
   residual leak at t=0 after the first two fixes were in.
3. **Both display fetches `await`ed without re-checking the selection.**
   `_refreshMdPrewarm` captured `job` before its await and `_fetchDisplayMeta` wrote
   `_displayMeta` (and re-rendered the production controls) unconditionally after its own —
   so a slow answer for the job you just left painted over the one you just picked. Both now
   go through `_stillSelected(jobId)`. `_fetchDisplayMeta` still RETURNS the value, so a
   caller that asked about a specific job explicitly gets its answer; only the shared state
   is guarded.

`_setDisplayIndicator` gained a third `jobId` arg (defaulting to the selection) purely so the
wording is resolved from the job the state is ABOUT — the state and the noun can never come
from different runs.

**Verified in-app** (`frontend/e2e/md_display_source_switch.spec.js`, read-only). The live
server could not produce the failing state — every NAMD job on the fixture design is
currently `ready` — so the spec STUBS the two display answers: the RunPod job answers
`remote` instantly, the Alpine one answers after 3.5 s. It asserts `podStateReached` first,
so a green run cannot mean "the leaky state never happened", then samples the dot every
500 ms for 7 s and requires that no sample mentions the pod. Result: pod → `on the pod`,
Alpine → `on the cluster`, 0 leaked samples, 0 console errors.

Not investigated: whether the trailing "until it errors out" is fully explained by cause 3
(the late RunPod answer resolving to `error` over the new selection) or whether the 30 s
`_MD_WARMING_TIMEOUT_MS` also fires on large systems. Measured load for a 1.03 M-atom system
is ~9 s (below), so the timeout is probably not implicated — but it was not measured for the
1.32 M-atom `24hb_0xT` run this was reported against.
