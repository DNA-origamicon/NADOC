# Native Full simulation menu — 2026-10-12

Implementation record and measured limits. Evidence root:
`.development-artifacts/vr-simulations-live-20261012` (Archive filesystem).

## Scope

Accepted raised scrubber, compact split, curved engine tabs and horizontal mapper.
Desktop handlers own simulation visualization semantics. Full is selected before
result activation. Atomistic is outside this iteration; topology is unchanged.
Metadata-only trajectory selection precedes explicit Load. Exact raw-frame ranges
and intervals are applied before coordinate extraction; coordinate and NAMD
ion/cell pages are bounded. Native file parsing and bounds calculation are worker
work; geometry uploads stage into spare buffers and playback reuses texture atlases.

## Retained diagnostics

- Attempts 1–3 exposed private-fixture listing and observation-placement issues.
  The test-only listing route exposes its private `__e2e__` fixture. Controller
  rays are parked away from the menu during model grip setup; translation and
  enlargement are checked against actual transforms.
- Attempt 4 completed native 24HB load/playback but its generic pixel checker
  wrongly demanded text inside the raised scrubber. The checker now requires a
  visible colored handle across the full track. The retained stereo image passes
  that correction; off-screen controls still fail.
- Attempt 5 passed the real 24HB native trajectory tour. Its ten-second quiet
  playback interval had zero compositor drops, GPU p95 5.49 ms, maximum 6.77 ms,
  at 90 Hz. Initial-load and diagnostic-input intervals still contained drops.
  Resource traces showed guarded-scope memory-high events and gigabytes of fixture
  copy page cache. Subsequent setup releases only cache for newly written private
  copies; source files and global cache settings are untouched.

These are submitted-eye captures and compositor measurements, not through-lens
inspection. Physical legibility, comfort and controller haptics remain MV-43.
No new production simulation was launched. Original jobs/designs remain intact.

## Software checks

Final frontend: 666 files, **7,873 passed, one skipped** (138.88 seconds).
Focused busy-state/trajectory/solvent checks previously had 67 passes; the final
full run also covers deferred companion drawing and completed-status indicators. Native viewer
build and panel/trajectory models pass. Existing-data extraction checks include
cross-segment interval selection against unsampled NAMD and oxDNA oracles.

`just test-smart` chose **FAST**. The first run: 10,711 passed, 92 skipped, 13
failures and eight errors. Most were environment failures: automatic psfgen lookup
selected a source directory; the long Archive scratch path exceeded AF_UNIX limits.
The required [slow-test triage](../../.claude/skills/triage-slow-tests/SKILL.md)
identified the 5.02-second worker test as a socket-startup timeout, not heavy work.
A short Archive TMPDIR fixes it: all eight worker tests pass in 3.40 seconds.
No timing budgets or test classifications changed.

A second FAST attempt selected the installed psfgen executable explicitly: 10,723
passed, 92 skipped, five failures and four errors. An inherited fixed `--basetemp`
interfered with five tests that spawn pytest; subsequent checks use a short TMPDIR
instead. Four CPD-preview errors report `Incorrect preview stereochemistry:
cis-anti-I`; chemistry files are unrelated and untouched. Aggregate fast-suite
time was 103 seconds with no individual over-budget test (10,824 collected
outcomes). This is broad-suite timing debt, not grounds to reclassify random tests.

The selector's broad-suite debt is retained verbatim:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

Repository lint reports five unrelated unused imports in `vr_prompts.py` and four
CPD test files. No unrelated edits were made to silence those reports.

The fixed-basetemp attempt also created five persistent placement-review incidents
from the gate's subprocess self-tests. They blocked app startup as intended.
`placement-incidents-inventory.json` preserves their identities. Each was reviewed
individually: its child pytest rejected arguments before geometry execution; all
recorded positioning producer/consumer hashes remained unchanged (only main.js's
Full-selection wiring differed). The correct-TMPDIR rerun has 22 passed/one skip.
The explicit reviews preserve original reports and their hashes; no journal deletion,
gate bypass, geometry change or golden regeneration occurred. The resulting ledger
is clear. Review artifacts: `20261012T164451-*-review.json` and
`placement-review-completed.json` under the task evidence root.


## Four-profile 24HB campaign

`benchmark-final-four/result.json` retains all four unchanged motion profiles:

| Profile | Result | Limitation / evidence |
| --- | --- | --- |
| steady_fast | Failed | Input transport late by 178 ms while selecting Off after Display MD. |
| steady_deliberate | Passed | Real Load, ions, cell, Play/Pause, stereo and desktop delivery. |
| variable_fast | Passed | Same complete path. |
| variable_deliberate | Failed | Could not hold hover on the compact Overlays tab for the required reaction interval in three attempts. |

No input timing, motion variability, target size or acquisition threshold was relaxed.
The compact tab's pointer tolerance needs physical review (MV-43). A 90 Hz display
rate alone is **not** evidence of uninterrupted 90 FPS. The deliberate run's quiet
10.04-second playback interval had zero compositor drops, GPU p95 **5.63 ms**;
variable-fast's 10.25-second interval had **23 dropped frames**, GPU p95 **5.83 ms**.
Loading/buffering and diagnostic capture intervals contain additional drops.
Native timing attributes some long input frames to existing menu/manipulation and
ligation processing; screenshot encoding also blocks the render thread. These are
remaining performance limits, not a fulfilled all-operations 90 FPS guarantee.

The submitted eye image in `benchmark-final-four/end/steady_deliberate/…/14-capture/after/left.png`
was visually inspected: raised scrubber and selected job, Full DNA, ion cloud and
cell are all present. The subsequent status fix removes the false indefinite
loading bar caused by matching “read” inside “ready”. Through-lens viewing and
physical controller haptics remain unverified.

## Ion/cell extraction equivalence and optimization

The 24HB 0xT fixture has **4,084,448 topology atoms, 6,720 nucleotides and 4,195 ions**.
Frames 0, 17 and 34 from the existing composite trajectory were extracted both
through the original whole-solvent context and the cached lightweight context.
The complete binary outputs have identical SHA-256 hashes; maximum coordinate
difference is **0 nm**. Species, ion count and cell corners agree. The original
shared affine and periodic imaging functions remain the sole coordinate producers.

First comparison: 13.23 s original, 3.16 s including new metadata setup. Final
repeat (`companions-oracle.json`): **12.70 s original, 0.52 s disk-cached, 0.05 s
warm in-process**. These are extraction timings for three saved frames, not XR
frame rates. The VR run's first ion preparation fell from 43.47 s to 5.23 s;
cell visibility then reused the same payload in 0.06 s. Page transitions still
buffer and expose actual progress. No new physical simulation was launched.

Native panel/trajectory binaries were built and exercised. Task-specific
`main.js` line delta is **0** (7,375 before and after); unrelated shared-worktree
changes are excluded from that claim.


Final `just test-smart` again chose **FAST**: **10,728 passed, 92 skipped, four
errors**, 110.92 seconds. All four errors are the unchanged CPD-preview chemistry
failures listed above. Two autosave/revision tests exceeded the five-second
per-test guard (5.94 s and 5.39 s). Required triage found tiny revision fixtures
performing durable file writes, without a solver or large scientific input;
serialized focused reruns passed with call times **1.57 s** and **0.88 s**.
Archive filesystem contention during the four-worker suite is consistent with
this difference; it is not grounds to classify these regressions as scientific
slow tests or increase limits. The aggregate 113-second guard and broad FULL debt
remain recorded. Evidence: `backend-smart-3.log`, `backend-smart-3-slow-candidates.json`,
`slow-triage-revision.log`, `slow-triage-identity.log`.

The official smoke gate and its exact 23-test selection passed in an isolated
workspace (1.3 minutes), including real-design console and session teardown gates.
`smoke-private-inventory.json` and `smoke-cleanup.json` record ownership and zero
remaining prefixed fixtures; the private workspace was removed on exit.


## Cross-engine app coverage

`engines-final` passed (3.3 minutes): real CanDo and SNUPI predicted shapes,
mrDNA relaxed shape, oxDNA Display/trajectory and NAMD Display/trajectory.
The 2HB oxDNA playback reached source frame 159; NAMD reached frame 209 of 210
using interval 2 (105 selected frames). The final submitted NAMD eye was inspected,
including the absence of the false completed-status loading bar. All five result
engines were exercised, not every suboption combination. The available SNUPI
fixture has no thermal trajectory; SNUPI indexed frame/metadata behavior has
software coverage, but no real thermal trajectory app proof in this campaign.
LAMMPS paging has extraction/controller checks; no completed LAMMPS fixture was
available for the native tour.

The initial 24HB 1xT production choice (`06fe9c9bff7a`, archived 50 ns run) contains
cached static results but **no DCD files**. Display succeeded; trajectory metadata
correctly reported zero available frames, failing the test's fixture assumption.
`benchmark-1xt-production` retains that result. The follow-up uses archived 5 ns
job `f14e00b8cacf`, whose existing DCD is present; neither archive was altered.


## Final production and buffering check

The 5 ns 24HB 1xT job has 1,384,821 topology atoms and 1,250 saved frames.
The native tour selected every seventh frame (179 selected), loaded real data,
enabled ions/cell, played and paused. Both `benchmark-1xt-5ns` and the subsequent
`benchmark-buffering-fix` passed in 2.5 minutes each. Synthetic-residue mappings
retain the original complete extraction context, so this fixture still has long
page preparation: final first load 20.33 s; first ion page 13.05 s; cell visibility
0.04 s. Progress stayed visible throughout.

The final eye capture exposed and then verified a display-state correction:
buffering preserves **FRAME 50 / 1247** and the raised handle's position while
keeping Pause available during active playback. Previously that same state
incorrectly said “LOAD TO ENABLE” and reset the handle. Native regression checks
cover this distinction; the real capture asserts the displayed source frame.
`review-24hb-vr.png` is the final inspected submitted-eye image.

The final ten-second quiet rendering interval had zero compositor drops and GPU
p95 **6.13 ms**, but it includes a held frame while the next page buffers. It does
**not** establish continuous trajectory updates at 90 FPS. Initial loading had
56 dropped frames; the wider input/playback interval had 62. All-operations 90 FPS
remains unachieved. Original geometry/radii/chemistry were not changed to improve
these numbers. Native build, panel/trajectory regressions and scoped lint pass
(`build-final.log`, `final-static-checks.json`). The four-profile campaign above
preceded the buffering-readout correction; the final production rerun used
unchanged `steady_fast` input.


Loading/input interval totals include the tour's diagnostic capture and inspector
costs; they do not isolate file extraction alone. Quiet rendering is reported
separately. No claim of a physical headset's through-lens experience is made.

## Cleanup

All private workspaces, scratch exports, test caches and owned viewers were
removed after checking process dependencies. `cleanup-inventory.json` records
paths and sizes; `cleanup-result.json` confirms no remaining task scratch.
Useful captures, traces, failures, equivalence results and the native build remain
on Archive. The task-started SteamVR runtime was closed; the original Steam client
and user development servers on 8000/5173 remain running. Original 24HB design
hashes still match the benchmark-open records (`final-verification.json`). No
original job/archive was edited, moved or deleted. No commit or push was made.
