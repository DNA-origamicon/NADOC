# S06 — Native offline revalidation, October 17, 2026

Delivered under FH-27, with no milestone closure: **21/38 complete, 17 remaining
(8 core, 9 parked); delta +0/+0; U1–U54 unchanged.** All 30 targeted full-run
native dependency entries now pass unchanged. S04 browser evidence is the sole
successor in [the handoff](session_handoff.md), not started here.

## Reconciliation and acceptance

HEAD remains `96ab701e`. The initial dirty/untracked S02/S03/S05, CPD-policy,
memory-maintenance and other changes were preserved. The handoff correctly
reported installed packages and an unstarted build; current inspection found no
`native/vr_viewer/build` directory. Unlike the earlier failed environment,
`pkg-config` now resolves `/usr/bin/pkg-config`. dpkg-query confirmed all eight
requested packages installed; GLFW/OpenXR versions are 3.3.10/1.0. Local scratch
has about 662 GiB free, with no explicit scratch override. No package installation
or deployed/runtime binary replacement was needed.

Acceptance was fixed before execution: build the existing viewer, then rerun only
the 11 representation failures and 19 sweep setup errors listed in
`full_software_validation_20261017.json`. Preserve geometry, assertions, scientific
policy, guards, resource limits and rollout gates. Stop on pass or concrete blocker.

## Commands and actual results

Configuration succeeded with the README's Release/Ninja/Linux-compiler recipe,
explicitly selecting Linux pkg-config, under the serialization guard:

```bash
just validate-safe env -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS \
  CC=/usr/bin/gcc CXX=/usr/bin/g++ \
  cmake -S native/vr_viewer -B native/vr_viewer/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DPKG_CONFIG_EXECUTABLE=/usr/bin/pkg-config
just validate-safe cmake --build native/vr_viewer/build --target nadoc-vr-viewer
```

Only the required viewer target was built (two compile/link steps); no unrelated
CTest targets or runtime launches. Build log contains no warnings. Observed user
systemd scope limits: MemoryHigh 6 GiB, MemoryMax 8 GiB, swap 512 MiB; native
parallelism stayed at the wrapper default of one.

The following `just test-focused` selections ran sequentially inside
`scripts/validation_guard.sh`, with TMPDIR/TMP/TEMP set before child imports to a
fresh owned temporary directory. The sweep module fixture compiles the existing
standalone adapter using `/usr/bin/g++ -std=c++17 -O2` and the existing native
headers; its successful tests demonstrate that compilation succeeded.

| Target and `-k` selection | Actual pytest result |
|---|---|
| `tests/test_vr_representation_loading.py`, `full_only_does_not_construct_atoms_or_extra_representations or selective_export_matches_same_blocks_in_complete_snapshot` | **11 passed, 4 deselected, 28.31 s** |
| `tests/test_vr_sweep_calibration.py`, `unstable_profiles_remove_wandering_and_preserve_curve or physical_smoothing_is_consistent_across_zoom` | **19 passed, 2 deselected, 5.08 s** |

No failures, errors, skips or warnings in these final runs. The selected cases
match all 30 native-dependency entries in the historical JSON inventory. Viewer
checks invoke `--validate`, not OpenXR. Sweep checks retain their original spatial
and zoom-consistency thresholds. No source edits or success-producing skips.

An initial nested `just validate-safe just test-focused` invocation lost filter
quoting and both commands exited 2 at argument parsing, before collection. The
corrected direct validation-wrapper invocation retains both resource and focused
test guards. Those initial logs and cleanup results remain separate from the
successful run; they are not counted as test failures or passes.

## Artifact policy and limits

New intended build directory retained: approximately 11 MiB, including the viewer
SHA256 `1f7be04f60f523202df833f881dfefaf66339bc64a01c6ca0b828b22a3f000ed`.
It was absent before S06; no existing deployed/runtime binaries were touched.
Snapshots, isolated workspaces, placement reports, adapter source and adapter
binary used private scratch. After children exited, accessible process cwd/exe,
open files and mappings had zero references to scratch. Protected processes that
could not be inspected are enumerated in the cleanup JSON, not claimed inspected.
TemporaryDirectory cleanup verified both roots absent: initial invocation root
(one empty file), final root **14 files / 11,507,732 logical bytes removed**.
No captures, scientific outputs or user designs were created by this task.

Compact configure/build/test logs, exact selected-node inventory, commands,
process-scan limitations and cleanup JSON are retained under
`.development-artifacts/s06-native-offline-20261017/`. Historical full-run JSON
remains unchanged; these focused results do not revise its aggregate verdict.

No task blocker remains. No browser/headset/production-app verification, broad
backend/frontend suite, scientific campaign, source-pin/golden change, rollout,
commit or push occurred. Non-CPD geometry questions, broad concurrency/regression
debt and all fixed FH-20/FH-27/FH-28 exits remain. CPD experiments remain excluded
from general tests. S04 is limited to the existing browser spec and documented
cleanup; it is not full release qualification.

Closeout checks passed: `git diff --check`; `just lint-memory` (0 errors,
60 existing size warnings); handoff/evidence local links; 38 unique milestone
rows with 21 Done; exactly one next-task ID (S04); matching plan/memory summaries;
30 distinct inventory nodes (11 + 19); both scratch roots absent. SHA256 comparison
against the pre-document snapshot confirms all other existing dirty/untracked
files, including the historical JSON inventory and source/test files, unchanged.
No source lint or broader tests were needed for these documentation-only edits.
Retained task evidence is approximately 29 KiB (13 small files); the intended build
occupies about 11 MiB on disk (9,801,752 logical bytes including directory entries).
