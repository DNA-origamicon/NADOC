---
name: Keep development artifacts out of the user workspace
type: feedback
authority: canonical
status: active
---
# Development artifact cleanup

## Legacy GROMACS campaigns deleted — 2026-10-23

User explicitly requested deletion: “Delete the gromacs campaigns. We have no
need for them anymore.” Deleted all three campaigns in checkout `runs/`:
`10hb_bundle_params` (303 files), `3NN_opt2_bundle_params` (485 files), and
`crossover_parameterization` (384 files). These were standalone legacy campaigns
without NADOC `job.json` records; no references were found in the 95 workspace
part files inspected. No active process cwd/open-file references were found
before deletion. Verified `runs/` is empty afterward. Removed 1,172 files,
24,440,135,868 logical bytes; measured free-space increase 24,443,875,328 bytes
(22.76 GiB). No archive copy was made and no part files or managed jobs changed.
Historical references to these campaign outputs now refer to deleted data.

User instruction, 2026-09-15/16: delete disposable development/test artifacts;
retain useful evidence only where it does not clutter the main user workspace.

## Portable storage across machines — 2026-10-17

User clarification: Archive belongs to another machine whose system drive was
space-constrained. This machine has ample local storage. The October 11 Archive
restriction below applies to that workstation, not every checkout or test.
This clarification supersedes globally applying its absolute mount path.

- Tests depend on isolated writable scratch with sufficient capacity, not a named
  disk or hostname. Use the OS temporary directory by default for ordinary tests.
- Explicit local configuration selects external scratch where needed. The history
  harness accepts `NADOC_TEST_SCRATCH_ROOT`; the older
  `NADOC_HISTORY_E2E_OUTPUT_PARENT` remains a compatibility alias. Conflicting
  settings, missing/unwritable paths and insufficient capacity fail without fallback.
- On a machine requiring an external filesystem, also configure
  `NADOC_TEST_SCRATCH_MOUNT`. Require a mounted directory and resolve scratch onto
  that filesystem. Never create the missing mount directory to satisfy preflight.
- These variables are local shell/CI settings, not committed machine identities.
  For other tools, configure their supported scratch settings (`TMPDIR`, `TEMP`,
  `TMP`, pytest placement, native-engine scratch) before imports/child launches.
  Do not assume legacy tools automatically read the new harness variables.
- Large campaigns must estimate their own storage and check available capacity.
  The small capture-free history spec's 1 GiB free-space preflight is operational
  headroom, not a general campaign budget or a continuous disk quota.
- Keep every run in a fresh owned directory and clean up after success/failure.
  Retain compact summaries; no user-workspace output or implicit migration of
  existing data. Scientific authorization and resource/test guards are unchanged.
- Instructions saying Archive is universally required, including older handoffs,
  are historical. Apply this machine-local policy to future validation decisions.

See [setup and commands](../START.md#test-scratch-on-different-machines).

## Feature-validation cleanup — 2026-10-13

User clarification: “make sure we are cleaning up all data after validation” and
“We don't want to be saving large capture files after testing each new feature.”

- Treat feature-validation captures as temporary. After reviewing and summarizing
  the results, delete recordings, extracted frames, depth/object-ID buffers,
  browser traces, copied fixture designs and detailed frame/pose dumps, including
  failed attempts. Keep compact pass/fail, timing, failure-reason and cleanup
  summaries; a failed test does not justify indefinite bulk retention.
- Complete any necessary pixel/identity analysis before deletion. Retain large
  evidence beyond the validation task only when the user explicitly requests it.
- Check active file/mapping references and configured runtime dependencies first.
  Preserve deployed binaries, active runtimes, authored designs and managed jobs.
  Verify deletion and report bytes removed; mark prior raw-evidence links as pruned.
- This instruction authorizes cleanup of completed Join feature-validation data
  and governs future feature checks. It does not authorize deleting scientific
  production results or unrelated historical storage-review candidates.

## Archive-first storage and review — 2026-10-11

On the Archive workstation, the user reported its system disk was nearly full and explicitly requires review
before moving or deleting the existing development artifacts in this inventory.
The October 11 request takes precedence over the earlier general cleanup rule:
inventory and propose exact paths/actions first; do not execute this cleanup until
the user approves a selection. Workspace user designs and their managed jobs are
excluded. Flag development copies derived from user designs separately rather
than assuming they fall within that exclusion-free scope.

On that space-constrained workstation, large development files must be created on the mounted Archive drive
from the first byte, including simulation outputs, native integral scratch,
temporary simulation packages, frame/profile captures, browser traces, downloads,
and new large development caches/tool environments. Use
`.development-artifacts/<task>/` (resolved archive path), and put temporary work
under that task's `tmp/` or `scratch/`; set `TMPDIR` and engine-specific scratch
variables before imports/child launches, or pass an explicit archive `dir=` to
temporary-directory APIs. Do not stage large output in `/tmp`, the checkout,
`runs/`, or a home-directory cache before archiving it.

On that workstation, verify `/media/jojo/Archive` is actually mounted and the resolved output/scratch
paths are on its filesystem before a bulk writer starts. Stop if the mount is
unavailable; never silently create bulk output on the system filesystem at an
unmounted archive path. Existing live runtimes, source pins, and managed-job paths
must stay intact until an approved, verified relocation. Do not redirect a running
calculation or rewrite frozen historical manifests.

Read-only review inventory:
`.development-artifacts/storage-review-20261011/candidates.csv` and
`inventory.json`. No files were moved, deleted, truncated, or compressed during
the inventory. Current CPD output and scratch already use Archive; old Psi4
scratch in `~/.cache/nadoc-qm/` is separately listed for review.

## General retention rules

- `workspace/` is for user designs and application-managed state/jobs. Do not
  create top-level campaign, benchmark, literature-download or diagnostic folders
  there. A filename containing “test” is not evidence that a user design is disposable.
- Use `tempfile.TemporaryDirectory` or pytest `tmp_path` for disposable work, with
  cleanup on success and failure. For large output, select and verify scratch
  according to the machine-local policy above. Remove empty output folders at task completion.
- Retain necessary raw scientific evidence, checkpoints, source assets and large
  diagnostic outputs under repository-local `.development-artifacts/<task>/`.
  On the original Archive workstation this was a gitignored symlink to
  `/media/jojo/Archive/NADOC_archive/runtime/development-artifacts`, outside the
  main user workspace. On another machine create/configure an equivalent local
  directory; never fall back silently to the user workspace.
- Keep reusable code, concise reports and small regression fixtures in the
  appropriate tracked `experiments/`, `docs/` or `tests/` directories. These are
  maintained development assets, not disposable test output.
- Before moving/removing artifacts, identify active processes, managed-job
  dependencies, runtime assets and useful evidence. Preserve user files, source
  edits and managed jobs. Update live paths and symlinks when relocating retained
  data. Keep historical hashed logs/manifests unchanged and provide a relocation
  index rather than rewriting their recorded provenance.
- At completion, verify cleanup, retained-file counts/sizes, asset hashes where
  applicable, and relevant readers. State what was deleted versus retained.
- Browser tests that must create workspace designs use the existing `__e2e__`
  naming and failure-safe teardown rules in CLAUDE.md. Verify no leftovers.

Cleanup inventory: `docs/audits/development_artifact_relocation_20260915.json`.

Mobile-gold validation evidence is retained in `experiments/mobile_gold/ws/` to
investigate pairing loss. Compact results live in `docs/validation/`; the cleanup
manifest in the isolated workspace records moved and deleted paths.

## Explicit VR workspace exception — 2026-09-22

User requested persistent, user-editable test parts in `workspace/VR Testing/`.
Retesting deletes old .nadoc parts there even if edited; parts are not validation
fixtures. This authorization is limited to that marked folder. Preserve other
workspace files. See [campaign policy](../docs/vr_authoring_workflows.md).
