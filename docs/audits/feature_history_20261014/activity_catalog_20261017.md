# S38 — Bounded native job catalog and internal summary

October 17, 2026; HEAD `96ab701e` unchanged, unrelated accumulated changes preserved.
S38 delivers bounded six-family discovery, native metadata normalization and an
internal activity-summary projection. No strict HTTP route was admitted.

`activity_catalog.py` discovers the six native job folders with one shared evidence
allowance and process inventory. Five archive-aware families also read their local
archive index; LAMMPS retains its native non-archive discovery contract. Index
identity takes precedence over a local directory and is deduplicated. External
archive paths are never accessed: cached local metadata is represented with an
explicit archive-live-unverified result, including cached terminal records. Missing
cache/index/metadata evidence cannot silently become a complete empty catalog.
Symlink discovery/metadata refuses; host-selected local paths remain a prerequisite.
This is not a race-proof filesystem sandbox or arbitrary mount-timeout guarantee.

Each native job class now exposes its existing metadata normalization as
`from_metadata`, called by ordinary `load` as well as the catalog. Default enums,
nested stage/segment/health records, historical defaults and NAMD retired-field
filtering remain shared. Ordinary archive resolution/cache refresh and NAMD
restart/transfer overlays remain in ordinary load, in their original order. The
catalog normalizes only its private bounded parsed dictionary and never invokes
those effects/sidecar readers. Those overlays do not supply activity-summary fields;
remote lifecycle verification remains explicitly outside this result.

Records preserve existing engine/job/source/design/status/time/resource fields
and NAMD scheduler metadata where proven. `active` is true, false or unknown;
`action` retains the underlying observer decision. Raw finalization-required and
unavailable evidence stay visible. Queued/terminal jobs follow the ordinary
activity collector's initial nonbusy filter. Source fallback, running NAMD/oxDNA
ETA, remote accelerator/ownership, preparation and archive liveness remain explicit
issues; no whole Design, workspace source scan, remote request, output extraction,
status repair, job save or new lock occurs. `complete` is false if discovery or any
required record evidence is incomplete. This is an internal result, not a changed
public response schema or an independent persisted catalog/status owner.

Bounds: 128 total candidate records, at most 128 IDs per family before sorting,
4096 directory entries per scan, existing 16 KiB text/64-level JSON limits and
8 MiB evidence allowance, aggregate 30,000 input graph nodes and 2 MB graph bytes
before native normalization, and 128 nested stage/segment/health records. Summary
strings/scalars are validated before projection. Output is graph-checked before
finite JSON encoding, capped at 30,000 nodes/2 MB and checked against the shared
cooperative work/deadline envelope. Exhaustion returns explicit incomplete evidence;
it cannot return a successful empty list. The existing five-second deadline is
cooperative between calls, not a filesystem syscall/import timeout. No limit was
widened; larger or unavailable native jobs remain unqualified rather than truncated.

## Validation actually run

Sequential guarded `just test-focused TARGET`: **150 distinct passes**.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_activity_catalog.py` | 27 passed | 3.18 |
| `tests/test_activity_local_engines.py` | 49 passed | 3.17 |
| `tests/test_activity_observation.py` | 41 passed | 3.00 |
| `tests/test_lammps_job.py` | 5 passed | 3.02 |
| `tests/test_job_archive.py` | 22 passed | 3.41 |
| `tests/test_md_vram.py::test_mdjob_failure_kind_and_prep_params_roundtrip` | 1 passed | 2.84 |
| `tests/test_md_vram.py::test_mdjob_load_defaults_missing_fix_fields` | 1 passed | 2.77 |
| `tests/test_mrdna_jobs.py::test_mrdna_job_save_load_roundtrip` | 1 passed | 2.95 |
| `tests/test_cando_job.py::test_job_persistence_roundtrip` | 1 passed | 2.65 |
| `tests/test_snupi_job.py::test_job_persistence_roundtrip` | 1 passed | 2.90 |
| `tests/test_oxdna_relaxation.py::test_job_roundtrip` | 1 passed | 3.08 |

Initial catalog run: 24 passed/1 failed; the inventory counter included the test's
own before/after/lock snapshot scans. Scoped instrumentation to the catalog call;
25 passed, then final 27 passed after raw-completion and ordinary-overlay coverage.
No production counter fix or weakened assertion was needed. Final tests compare
native normalization/load results for all six families, check unchanged fixture
files, unknown archive/malformed/budget/permission/source/owner records, complete
empty discovery, mixed-family completion, CPU resource identity, deduplication,
shared inventory and ordinary overlay order. S36/S37 and ordinary archive/model
regressions remain green. Seven existing FastAPI ORJSONResponse deprecation warnings
occurred in archive API tests. No simulation, solver or user job operation ran;
archive tests copy/move only isolated fixture files (including a 26 MiB copy test).

Changed-source/test Ruff and `git diff --check` pass. Main.js S38 delta is zero.
No browser, frontend suite or broad backend suite ran. `just test-smart --dry-run`
still selects FULL for accumulated main.py changes, then FAST fallback; **zero
broad tests executed**. Nineteen historical timing candidates remain; no new
focused test exceeded five seconds. Required selector text:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

“Ran” is selector boilerplate, not a FAST execution claim. Broad debt stays open.

## Sequencing

S39 is the sole unstarted successor: closed strict active-job HTTP reads using the
bounded catalog, with explicit refusal for incomplete evidence and no legacy
collector fallback. The [handoff](session_handoff.md#next-bounded-task) owns its full
contract. Unqualified source/ETA/archive/preparation/remote cases remain obligations;
a supported-scope endpoint does not complete general activity or desktop acceptance.
S29 browser lifecycle and ISSUE-100/MV-48 stay open. No external blocker for S39.
Counts: 21/38 Done,17 remaining (8 core/9 parked), delta +0/+0, U1–U60 unchanged.
This internal catalog earns no U checkpoint or milestone credit. No gate enablement,
scientific/golden change, commit or push.

## Final records and cleanup

`just lint-memory`: 0 errors/0 warnings. Local current plan/report/memory links
resolve; ledger check finds 38 unique FH rows, 21 Done and 60 U rows. Handoff has
exactly one task ID, S39; current issue/manual records agree. All four production
gates remain false. Final changed-source lint and diff checks pass.

`/tmp` had 662 GiB free before the larger archive fixture run. Pytest pruned earlier
owned runs, including the archive copy fixture; remaining owned roots `pytest-11`,
`pytest-12`, `pytest-13` and four S38 logs were checked for active cwd/open-file/
mapping references: none accessible, 31 processes inaccessible/exited. Removed
3,536 logical bytes / 12,288 allocated bytes from those roots and 18,030 log bytes
after summarizing evidence. All paths independently absent; dangling current link
removed, unrelated `pytest-0` retained. No active validation handle or test-created
user-workspace artifact remains.
