---
name: Keep development artifacts out of the user workspace
type: feedback
authority: canonical
status: active
---
# Development artifact cleanup

User instruction, 2026-09-15/16: delete disposable development/test artifacts;
retain useful evidence only where it does not clutter the main user workspace.

- `workspace/` is for user designs and application-managed state/jobs. Do not
  create top-level campaign, benchmark, literature-download or diagnostic folders
  there. A filename containing “test” is not evidence that a user design is disposable.
- Use `tempfile.TemporaryDirectory` or pytest `tmp_path` for disposable work, with
  cleanup on success and failure. Remove empty output folders at task completion.
- Retain necessary raw scientific evidence, checkpoints, source assets and large
  diagnostic outputs under repository-local `.development-artifacts/<task>/`.
  On this workstation it is a gitignored symlink to
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
