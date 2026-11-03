# Full software validation — October 17, 2026

Subsequent S06: [native offline revalidation](native_offline_revalidation_20261017.md)
passes all 11 representation failures and 19 sweep setup errors after dependency
installation/build. This supersedes their missing-prerequisite status below, not
the historical full-run result/JSON inventory. No broad rerun or watermark advance.


User explicitly opened a four-hour test session and requested a long run, easy
repairs, and an explanation of remaining errors/warnings. No scientific campaign
was requested. Baseline `96ab701e`; all previous uncommitted work preserved.

## Full backend result

`NADOC_TEST_CONFIRM=1 just validate-safe just test` completed under the existing
resource/session guards: **19,852 passed, 38 failed, 31 skipped, 28 errors,
3,372 warnings in 2,334.68 s (38m54s)**. Four xdist workers; scientific cases remain
centrally excluded. No budget, timeout, guard, geometry tolerance or golden changed.
This is a completed **failed** software run, not full regression clearance.
The watermark was not advanced and FULL debt remains. The stock command did not
print individual skip reasons or a durations table; no per-skip qualification or
slowest-test ranking is inferred. Logs are retained under
`.development-artifacts/software-regression-20261017/`.

[Machine-readable inventory](full_software_validation_20261017.json) contains all
66 failure/error entries, including repeated collection errors. It supersedes the
older incomplete S02 run as the latest broad evidence, without changing that record.

## Frontend result

`just test-frontend`: **770 files passed; 9,271 tests passed, 1 skipped in
362.08 s**. No unhandled-error report. Output includes 663 jsdom canvas-context
not-implemented diagnostics and mocked server-failure logs. These limit rendering
coverage; installing canvas or pretending it renders is not browser acceptance.
No frontend production change or actual browser execution occurred.

## Small repairs

- `tests/test_vr_startup.py`: mock host-platform detection for the already mocked
  launch-order test. Keep actual platform-refusal coverage and production guard.
- `tests/test_polymerize.py`: use `LatticeType.SQUARE` instead of bypassing model
  validation with a string; retain the mismatched-source assertions.
- `tests/test_remote_live_frame.py`: test binary-coordinate/DCD round trips with
  an empty in-memory topology. Remove unnecessary placeholder PDB creation and
  its missing-field/unknown-mass warnings; retain coordinate and cell assertions.
- `tests/test_atomistic_validation.py` and `tests/test_fem_solver.py`: assert the
  precise numerical warning categories produced by deliberately non-finite and
  singular inputs, alongside the existing refusal assertions. No global warning
  suppression or production numerical changes.

These are test-only changes. Full-suite numbers above precede these repairs;
focused validation is recorded separately below.

## Focused validation after repairs

All 13 commands used `just test-focused` serially under the resource guard.

| Target / filter (under tests/) | Result |
|---|---|
| test_vr_startup.py | 5 passed, 3.08 s |
| test_vr_routes.py -k platform | 4 passed, 2.85 s |
| test_polymerize.py | 32 passed, 18 ORJSON warnings, 3.02 s |
| test_remote_live_frame.py | 37 passed, 3 warnings, 3.76 s; final rerun 37 passed, 2 upstream DCD warnings, 3.36 s |
| test_atomistic_validation.py -k non_finite_atom_flagged | 1 passed, 1 ORJSON warning, 3.84 s |
| test_fem_solver.py -k singular_system | 1 passed, 2.96 s |
| test_connection_owner_selection.py -k creator_dependency | 1 passed, 4.14 s |
| test_native_protein_free_import.py -k broken_prefix | 1 passed, 2.84 s |
| test_part_routing_worker.py -k real_spawned_prefix | 1 passed, 5.61 s |
| test_part_immutable_deformation.py -k real_worker | 1 passed, 6.88 s |
| test_native_streptavidin_proof.py -k registered_lifecycle | 2 passed, 18.94 s |
| test_part_strict_geometry_http.py -k real_http_workers | 1 passed, 5.59 s |
| test_part_immutable_transform.py -k nucleotide-transform-delete | 1 passed, 3.02 s |

**88 distinct focused cases passed.** All seven full-run budget failures pass
serially without changes to their assertions/limits. This supports load sensitivity,
not resolution of concurrent-suite/resource acceptance. The VR startup failure is
fixed. Geometry/evidence/native failures and the benchmark cancellation defect
were not erased or retested into a new full-suite verdict. `just lint` and
`git diff --check` pass; memory lint: 0 errors / 60 existing size warnings.


## Remaining causes

| Category | Full-run entries | Evidence and why not repaired here |
|---|---:|---|
| Native VR prerequisites | 11 failures + 19 setup errors | Representation tests require absent `native/vr_viewer/build/nadoc-vr-viewer`; sweep calibration compilation cannot find `glm/glm.hpp`. Linux pkg-config, GLFW/OpenXR headers are absent; PATH pkg-config resolves to an unusable Windows Strawberry Perl tool. Requires explicit native dependency/build setup. No success-producing skip added. |
| Scientific evidence unavailable | 7 failures + 4 collection errors | Photoproduct review requires Archive's `tt-cpd-definition-human-review-packet-v7/definition_review_packet.json`; CPD NPT import reads missing local `cpd-anti-gpu-longbox-v3/assembly.json`. The four collection errors repeat one module across workers. These are provenance-bearing inputs, not scratch-space shortages. Restore verified evidence or separately decouple software fixtures from campaign data; do not fabricate it or rewrite frozen manifests. |
| CPD preview stereochemistry | 4 setup errors | `Incorrect preview stereochemistry: cis-anti-I`. Needs a concrete molecular A/B review; no scientific correction or approval inferred. |
| Worker/capture time budgets | 7 failures | Connection verification wait(5), protein capture, routing worker, Bend worker, streptavidin capture, strict HTTP worker, transform-delete capture. Full-suite contention is a hypothesis; serial reruns below test it. Limits remain intact and isolated passes do not qualify concurrent resource acceptance. |
| NAMD benchmark | 1 failure + 1 teardown error | Still running at the 600 s test deadline, with minimization log at step 1999; cancellation thread did not join within 10 s. Needs bounded benchmark/cancellation diagnosis, not increased timeouts. No second benchmark or new scientific sampling launched. |
| mrDNA round trip | 1 failure | Mean position error 0.691175 nm exceeds 0.10 nm. Molecular mapping diagnosis required. |
| Atomistic trajectory audit | 1 failure | NativePlacementError: native Full coordinates disagree with transported site. Needs ownership/geometry diagnosis; not a warning to suppress. |
| Corner optimization | 1 failure | 13 clashes versus reference maximum 11. Keep objective/threshold intact. |
| Surface regression | 1 failure | VoltronCore area 19045.6537 versus baseline 18077.7, 5.3544% outside 5% limit. Requires representative visual investigation; no baseline regeneration. |
| Platform attachment | 1 failure | Honeycomb three-connection platform: fitted duplex intersects existing DNA/protein. Requires scientific collision review. |
| Junction balance | 2 failures | Square 0.0010157304 nm and honeycomb 0.0013676456 nm exceed 0.001 nm. Same failures as preceding triage; no tolerance relaxation. |
| Scaffold accounting | 1 failure | Screened-I physical scaffold 7230 versus 7249 expected. Requires topology/recipe diagnosis. |
| Joined branches | 3 failures | 4np auto/7249 overhang-extrude differs from native helices/strands; 8064 nick differs in strands. Requires definition/replay diagnosis, not weakening native proof. |
| Mocked host platform | 1 failure | VR startup unit test fixed above; no actual headset qualification. |

## Warnings

- FastAPI ORJSONResponse deprecations dominate the printed warning inventory.
  Replacing the shared response policy requires serialization/HTTP compatibility
  validation, especially NumPy payloads and direct route callers. Not a safe global
  substitution or suppression in this test-only repair.
- MDAnalysis DCDReader copying semantics are deprecated upstream; XTC fixtures
  lack timestep metadata; other synthetic PDB fixtures lack optional fields;
  topology-only PSF loading has no coordinate reader. Remote-live-frame's avoidable
  placeholder warnings are repaired (its intentionally absent box warning is now
  asserted locally), but no package upgrade or fabricated physical
  timing is introduced.
- MDAnalysis also emitted an unraisable DCDReader destructor error (`_file` absent)
  after failed initialization. Requires reader-lifecycle/upstream investigation.
- Pydantic mrDNA `copy` fields shadow BaseModel.copy; renaming requires preserving
  schema/wire compatibility. Malformed/legacy feature-log fixtures also generate
  serialization warnings. Polymerization's unintended enum mismatch is fixed;
  fault-injection payloads are not silently normalized.
- Deliberate non-finite atom and singular-FEM warnings are now locally asserted.
- Existing memory-size warnings remain documentation-maintenance debt.

## Artifact isolation finding

After the run, the real workspace had modified `mrdna_jobs/102c5d2a99dc/job.json`
and `.runtime.lock`; metadata still describes the existing completed VoltronCore
job. `test_build_namd_seed_from_mrdna_on_real_job` directly calls the reconciling
seed builder with `_WS` pointing to the real workspace. No pre-run byte snapshot
exists, so byte-for-byte preservation cannot be claimed. Do not restore or delete
that job blindly. The audit log also gained two `logger_ready` events from worker
71857. Existing `workspace/logs/alpine_operations.jsonl` is retained intact.
This is a genuine isolation defect, distinct from disposable pytest output.
No active NAMD/oxDNA/ARBD/full-pytest process remained after the guarded full run.

## Cleanup and retained evidence

Removed only the remaining owned pytest roots 12–14: 42 files / 159,672 bytes;
earlier roots rotated out through pytest retention. Verified exact roots absent.
Checked accessible process cwd/open files/mappings and confirmed no validation
workers remained. Two protected, pre-existing systemd/sd-pam processes were not
inspectable and were left untouched; this limitation is recorded in cleanup.json.
Removed two duplicate generated summaries. Retained four raw logs (797,844 bytes)
and a small cleanup manifest under `.development-artifacts/software-regression-20261017/`,
plus the tracked concise Markdown/JSON report. Preserved existing user job metadata,
lock and audit log; their observed modification is ISSUE-144, not disposable output.

## Sequencing

No milestone closes: **21/38 complete; 17 remaining (8 core, 9 parked); delta
+0/+0; U1–U54 unchanged**. The sole next bounded task is **S05: isolate real-job
software tests from mutable user state**, under FH-27. S04 browser acceptance
remains unstarted and retained, but follows this isolation repair. No rollout gates,
scientific approval rules, fixed milestone exits, commit or push changed.
