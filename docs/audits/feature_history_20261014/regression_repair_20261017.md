# Remaining-failure repair — October 17, 2026

Subsequent S06: [native offline revalidation](native_offline_revalidation_20261017.md) built the viewer and passed all 30 targeted cases. The historical prerequisite discussion below is superseded; S04 is now the sole next task in the handoff.

S05 delivered, parent FH-27. The user requested remaining-failure repairs and
questions where dependencies, evidence or geometry intent were uncertain.
Existing dirty changes were preserved (HEAD `96ab701e`). No production/scientific
code, constants, thresholds, source pins or gates changed in this repair.
21/38 milestones complete, 17 remaining (8 core, 9 parked), delta +0/+0; U1–U54 unchanged.

## Isolation correction

`tests/conftest.py` now isolates module-scoped app startup before module-scoped
clients can enter lifespan. `tests/workspace_isolation.py` patches both workspace
owners, the child-process workspace environment and a separate audit logger;
handlers close and globals restore on failure. This addresses the engine WebSocket
fixture that previously preceded function-scoped isolation.

The real mrDNA seed test now uses `tests/mrdna_seed_fixture.py`: resolve existing
fine-stage inputs read-only, copy job/design/display metadata, PSF, companion PDB
and DCD into private scratch after capacity checking, verify SHA256 equality,
then let status reconciliation write only the private job. No source runtime lock
is copied. Hash/size/mtime checks cover each source input and existing lock;
namespace comparison detects added/removed source paths. Cleanup runs on failure.
The numerical reconstruction assertions are unchanged. These are byte-verification
checks of the selected existing inputs, not independent scientific certification.

The initial real test exposed a missing companion PDB in the private input list.
That omission was fixed; the next real reconstruction passed. No missing scientific
input was fabricated. Synthetic fault fixtures exercise cleanup and source-write
detection only, separately from real numerical coverage.

## Checks actually run

| Check | Final result |
|---|---|
| `just test-focused tests/test_engines_ws.py` | 12 passed, 4 warnings, 6.32 s |
| `just test-focused tests/test_workspace_isolation.py` | 3 passed, 2.79 s |
| `just test-focused tests/test_mrdna_md_seed.py -k private_seed_job` | 2 passed, 15 deselected, 2.83 s |
| Real `test_build_namd_seed_from_mrdna_on_real_job` via `just test-focused` | 1 passed, 15 deselected, 2 warnings, 28.29 s |
| `just lint` | Passed |
| `git diff --check` | Passed |

18 distinct focused passes, not a full-suite result. The last guard-only test added
after the real run does not change its valid-input reconstruction path. The first
real attempt failed with missing private PDB (4.29 s), retained in `seed.log`;
`seed_final.log` records the corrected pass. Existing MDAnalysis/deprecation warnings
remain; no suppression or tolerance changes. No browser/native build or broad rerun.
The previous full backend run remains failed; FULL debt and watermark unchanged.

## Questions and blockers

The user answered the CPD questions: this machine should not obtain CPD evidence;
all CPD work is experimental and must be excluded unless specifically requested.
The user completed native installation: dpkg-query verifies all eight packages;
`/usr/bin/pkg-config --modversion glfw3 openxr` returns 3.3.10 and 1.0.

- Evidence: where should this machine obtain
  `tt-cpd-definition-human-review-packet-v7/definition_review_packet.json` and
  `cpd-anti-gpu-longbox-v3/assembly.json`? Are they only on the other machine's
  Archive or is there a verified local/shared copy? Their absence is observed;
  why they are absent is not a development prerequisite. This question is resolved
  by the user’s CPD exclusion, not by copying or synthesizing evidence. Frozen
  campaign scripts/manifests were preserved.
- Geometry: were intentional reviewed changes made to CPD stereochemistry,
  mrDNA reconstruction, junction balance or branch/scaffold generation that the
  assertions have not followed? Which reviewed change/commit is authoritative?
  The user excluded CPD; a separate question about non-CPD geometry remains pending.
  No assumed explanation, updated golden or geometry modification. Existing
  molecular A/B review and explicit authorization still apply before corrections.
- Native: Linux pkg-config, GLM/GLFW/OpenXR development inputs are missing. PATH
  resolves Windows Strawberry pkg-config. `sudo -n true` requires a password.
  Asked the user to install `pkg-config libglm-dev libglfw3-dev libopenxr-dev
  libgl1-mesa-dev libx11-dev zlib1g-dev ninja-build` using apt. No installation
  performed by the agent; user installation is now verified. S06 in the handoff
  is the single ready successor; build and native tests remain unstarted.

The full inventory remains in [the previous validation report](full_software_validation_20261017.md)
and JSON: native representation/sweep, CPD review/collection/stereochemistry,
mrDNA reconstruction, atomistic frame diagnostic, corner clash, surface area,
honeycomb connection, junction arc and scaffold/branch assertions, and NAMD
benchmark timeout. Seven timing cases passed serially previously, not under the
full-run load. Native benchmark termination has a 15 s process-group grace while
the test joins for 10 s; this is an observed mismatch, not a proven explanation
for the original 600 s timeout. No additional sampling or deadline change occurred.

## Artifact and user-state verification

Source metadata mtime remains `2026-10-17 17:04:03.661721176 -0600`; real Alpine
log mtime remains `17:05:28.183783718 -0600` (both pre-repair). Source hash/stat and
namespace guards passed around the real seed run. Existing user jobs/locks/logs
were preserved, not reverted. Private real-input copies were removed by the
context manager. Remaining owned pytest roots 5–7 were removed: 7,367 file bytes,
zero roots remaining. No accessible process cwd/file/mapping referenced them;
protected boot-time system/WSL daemons could not be inspected. No test/native
process remained. Only owned synthetic fixtures and private logs were removed.
Compact logs plus cleanup inventory remain in
`.development-artifacts/regression-repair-20261017/` (9 files, 23,123 bytes). Two additional empty owned pytest roots (0–1) were
removed after policy checks; no accessible references, with protected system/package
installation daemons inaccessible.

ISSUE-144 is fixed for the two demonstrated paths with focused validation; this
is not a proof that every test writer is isolated. S04 desktop browser acceptance
remains unstarted; local storage is available and is not its current blocker.
No milestone, manual acceptance, rollout, commit or push was performed.


## User-directed CPD exclusion

`tests/scientific_validation.py` identifies CPD/photoproduct module and node names
plus seven related QM/campaign module aliases. `pytest_ignore_collect` excludes
those modules before imports in ordinary runs; explicit ordinary CPD targets are
rejected before collection with scientific opt-in guidance. Mixed-module CPD-named
cases use existing scientific deselection. Existing simulation/resource guards
remain intact. No CPD experimental test was run and no missing evidence was supplied.

Ordinary guarded collection completed: 19,087/19,139 tests, 52 deselected, 14.60 s,
no collection errors. This checks import safety, not runtime test acceptance. The
initial policy tests caught a duplicate pytest_configure hook; the guard was merged
into the existing hook, preserving simulation detection, and rerun. The historical
full-run CPD failures remain in the immutable results inventory, but are no longer
ordinary software regression debt under the user’s clarified policy.


Final policy checks: `just test-focused tests/test_scientific_selection.py` passed
11 tests in 2.93 s; lint and diff checks passed. An explicit ordinary target for the
missing-evidence CPD NPT module refused with exit 4 before import, as intended.
Explicit scientific collection of `test_cpd_metrics.py` collected 35 tests in
0.24 s; none executed. Total this session: 29 distinct focused passes. Memory lint:
0 errors, 60 existing size warnings. No full rerun and no native build yet.
