# Pre-existing failure triage — October 17, 2026

User-requested bounded follow-up to S03/storage portability. Baseline `96ab701e`;
prior dirty work preserved. This is not S04, a new U checkpoint, or qualification.

## Delivered

- Fixed all five Ruff F401 findings: four unused Path imports in CPD tests;
  explicit `parse_event as parse_event` re-export in `vr_prompts.py` preserves
  its route/test consumers. An initial removal broke imports during development;
  corrected before final validation (group tests rerun, parser tests passed).
- Updated the exact capability assertion to include the existing extension-upsert
  v2 override while retaining global proof v1 and cluster-create v2 expectations.
- Mocked only host-platform detection in two capture parameter cases and the
  join-publication unit test. Actual Windows/macOS/WSL refusal stays intact.
- Autorefine route stubs now use private pytest storage and registries, signal
  cancellation and join worker threads before fixture teardown. No real sampling.
- Applied the repository triage-slow-tests skill: three real spawned-worker
  lifecycle tests exceeded the prior FAST 5 s limit (5.57/5.11/5.06 s). Registered
  only those tests as slow/headless in conftest. Existing source selector rules for
  part_immutable_geometry and part_geometry_inputs already select headless.
  Smaller sibling tests stay fast; no budget, guard or assertion relaxed.

## Actual final validation

All commands used `just test-focused` serially; paths below are under `tests/`.

| Target / filter | Result |
|---|---|
| test_group_creation_v2.py | 24 passed, 2.96 s |
| test_vr_join.py | 13 passed, 3.10 s |
| test_vr_capture_launch.py | 37 passed, 3.27 s |
| test_skip_twist_tuning.py -k route | 5 passed, 18 deselected, 4 deprecation warnings, 3.26 s |
| test_vr_routes.py -k platform | 4 passed, 58 deselected, 2.97 s |
| test_vr_prompts.py | 2 passed, 3.07 s |
| test_part_immutable_deformation.py -m slow | 1 passed, 22 deselected, 7.25 s (call 4.25 s) |
| test_part_immutable_geometry_recovery.py -m slow | 1 passed, 15 deselected, 7.44 s (call 3.96 s) |
| test_part_immutable_transform.py -m slow | 1 passed, 12 deselected, 7.15 s (call 4.08 s) |

88 focused passes. Slow-filter execution confirms retained integration coverage;
isolated timings below 5 s do not invalidate the prior concurrent-suite evidence.
`just lint` passes; `just lint-memory`: 0 errors / 60 existing size warnings;
`git diff --check` passes. No new production behavior, frontend changes, broad
selector, browser, native build or scientific campaign. No new FAST wall-time claim.
One attempted compound `-k`/`--tb` command was rejected by the focused wrapper;
the supported `-k full_rep` command below was then used.

## Remaining failures and limits

| Evidence | Why it persists / required work |
|---|---|
| `test_junction_balance.py -k full_rep`: 2 failed, 10 deselected, 3.20 s | Square maximum arc difference 0.001015730377341928 nm; honeycomb 0.0013676456009520388 nm; both exceed unchanged 0.001 nm limit. Requires scientific diagnosis and concrete A/B authorization before any molecular geometry change. No tolerance/golden regeneration. |
| `test_vr_representation_loading.py -k full_only`: 1 failed, 14 deselected, 2.98 s | Missing `native/vr_viewer/build/nadoc-vr-viewer`. Other nine failures in S02 belong to the same native validation family but were not individually rerun. Native build/toolchain qualification is outside this small repair. Host WSL additionally prevents actual native VR launch, though that is distinct from offline viewer validation. |
| `test_cpd_gpu_npt_context_v4.py --collect-only -q`: 1 collection error, 1.37 s | Import of gpu_longbox_validation_v3 calls dimensions(), which reads missing `.development-artifacts/cpd-anti-gpu-longbox-v3/assembly.json`. S02's four collection errors repeated this across workers. Needs campaign data with provenance or a separately validated decoupling of campaign I/O from software-test imports; no fabricated data or success-producing skip. |
| Incomplete S02 FAST / pending FULL | Four assertion failures fixed and three timing offenders classified; no broad rerun or clearance. Historical evidence JSON remains unchanged. Aggregate timing debt remains unmeasured. |
| Browser acceptance | Portable storage preflight already passed in preceding follow-up. S04 has not started; neither missing native viewer nor CPD dataset is established as a blocker for the isolated desktop spec. |

Existing `workspace/autorefine` contains 1,344 historical JSON files, latest mtime
October 16 18:33:06 local; this turn added none. Leave historical data intact.
Only pytest-managed private scratch and ordinary guard caches were produced.
Final cleanup removed the three remaining owned pytest roots (11–13), 3 files /
16,221 bytes, after checking process cwd/open-file/mapping references; exact roots
verified absent. Earlier roots had rotated out under pytest retention.
No rollout gates, scientific rules, fixed exits, user designs, commits or pushes changed.

## Sequencing

21/38 milestones complete; 17 remain (8 core, 9 parked); delta +0/+0; U1–U54
unchanged. Sole successor remains **S04**, ready and unstarted. Its objective,
parent FH-20/FH-27, deliverables, relevant files, acceptance checks, exclusions and
stop condition are defined in [the handoff](session_handoff.md#next-bounded-task).
Do not treat the remaining failures as additional ready tasks or begin S04 here.
