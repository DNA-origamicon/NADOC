---
name: job-archive
description: Archive/unarchive MD & oxDNA job folders off-workspace; job_dir() archive-awareness invariant
metadata: 
  node_type: memory
  type: project
  originSessionId: 1f766f1d-28a3-4726-8d47-59748bd2677c
---

oxDNA and MD jobs can be **archived**: their heavy folder is moved off the
workspace to anywhere on the host (external drive), keeping the list entry +
chaining. Added 2026-06-24 alongside per-job size-on-disk and the welcome-screen
"Data on disk" column / Help ▸ About-this-file panel ([[job-disk-usage]]).

**Core invariant (do not break):** `MdJob.job_dir()` / `OxdnaJob.job_dir()` return
`Path(archive_path)` when `archived`, else `workspace/{kind}/job_id`. Almost all
job-file reads (incl. chaining a child off a parent — `parent.job_dir()` /
`stage_dir()`) flow through this, so archived jobs stay readable and chainable
with no call-site changes. **Any new code that reads job files MUST go through
`job_dir()`, never recompute `workspace/{md,oxdna}_jobs/<id>` by hand.** The only
sanctioned hardcoded paths are inside `load()` / `list_jobs()` (which consult the
index) and `job_archive.py` itself.

**Mechanism:**
- `backend/core/job_archive.py` — index helpers (`resolve_job_json`,
  `archived_job_ids`, `purge_index_entry`), background copy-then-delete move with
  byte progress, in-process task registry (`start_archive`/`start_unarchive`/
  `task_status`). Index file: `workspace/{kind}/.archive_index.json` = `{job_id:
  archive_folder}`.
- `archived` + `archive_path` fields on both job dataclasses; `load()`/`list_jobs()`
  are archive-aware (list = scan workspace dirs ∪ index).
- Routes: `POST /api/{md,oxdna}/jobs/{id}/archive` (body `{dest_root}`),
  `/unarchive`, `GET /archive-status`. Job-list routes add `size_bytes`. Delete
  paths (job delete + library delete-with-jobs) call `purge_index_entry`.
- `backend/api/routes_fs.py` — `GET /api/fs/listdir`, `POST /api/fs/mkdir` back the
  system folder picker.

**Tests:** `tests/test_job_archive.py` (unit/route round-trips, index, fs browse, symlink
guard). Full-pipeline validation: `tests/test_headless_oxdna_build.py::test_archive_unarchive_round_trip_preserves_job_and_chaining`
— builds a real relaxed oxDNA job (mock binary), archives to an "external_drive" tmp dir,
**chains a field child off the archived parent** (the headline property), then unarchives;
proven can-go-red by breaking `job_dir()` archive-awareness.

**Frontend:** `ui/folder_picker.js` (system folder navigator), `ui/job_archive_action.js`
(shared archive/unarchive flow + poll + progress; lazy api-method resolution so test
mocks don't need the endpoints), wired into `oxdna_jobs_panel.js` + `md_jobs_panel.js`
(per-row size + 📦 marker, Archive/Unarchive button next to Delete, progress line).
Last-used archive root remembered in `localStorage['nadoc.archiveRoot']`.
**Gotcha:** both panels skip re-rendering the job list unless the change-signature
differs — `archived` + `size_bytes` are now part of `_listSignature` / `mdListSignature`;
adding new per-row fields needs the same.

Move is copy-then-delete (interrupt-safe: source survives, partial dest cleaned on
failure). Background thread, not persisted across server restart — a restart mid-move
leaves the job un-archived (source intact).

**Field incident 2026-06-24 (18hb e29d1e5d5ace), fixed:** the user had manually
symlinked a job folder onto an external drive (`workspace/md_jobs/<id>` → `/media/.../NADOC/md_jobs/<id>`).
Archiving it made `os.walk` follow the symlink and COPY 40 GB to a second spot on the
SAME drive; then `shutil.rmtree` silently no-op'd on the symlink source → a 40 GB
duplicate + a stale workspace symlink that would also break unarchive. Concurrently a
heavy MDAnalysis trajectory load on the same 42 GB run pegged the server, so the
archive only *looked* hung (the copy had actually finished). Fixes:
- `start_archive` now **refuses a symlinked job dir** (`src.is_symlink()` → ValueError).
- post-copy cleanup unlinks a symlink source instead of rmtree-ing it.
- **`dir_size_bytes_cached` (60 s TTL) in design_disk_usage.py** — the per-job
  `size_bytes` (added to `/api/{md,oxdna}/jobs`, polled every few seconds) was
  re-walking multi-GB external folders each poll; now memoised. Use the cached variant
  on any polling hot path; bare `dir_size_bytes` only for one-shot calls.
- Recovery if it recurs: confirm the new copy is complete (compare path+size manifest;
  only `job.json` should differ — it carries the archived flag), then `unlink` the
  workspace symlink + `rm -rf` the redundant copy; index already points at the keeper.
  A wedged `--reload` worker does NOT auto-respawn on SIGKILL — `touch backend/api/main.py`
  to make the reloader start a fresh worker.

**Open follow-up 2026-10-03 — transfer progress during one large file:** User observed
1.2 GiB / 1% apparently frozen while moving `small_plate` production `a5e2cf157a76`
to Archive2 (`/mnt/f/NADOC/a5e2cf157a76`). Read-only checks confirm the DCD keeps
growing (23,384,252,416 bytes at latest check), with `state=running`, `error=null`.
`_copy_tree_with_progress` updates bytes only AFTER each `shutil.copy2` returns;
UI faithfully shows completed-file bytes and omits the in-flight file. Logged in
`issues_ledger.md` under “Archive transfer progress appears stalled during a large file”.
**User explicitly requests no interruption: defer the code fix until this transfer
finishes.** Backend auto-reload would kill the background transfer. Future fix must
report within-file progress with a regression test, while preserving move safety
and throughput. Only Markdown notes were changed while the transfer was running.

**Resolved 2026-10-03:** User authorized the progress fix after the first transfer
completed. `_copy_tree_with_progress` now copies in bounded 8 MiB chunks, updates
progress within each file, fsyncs completed output, and preserves metadata with
`copystat`. Regression first reproduced the old failure; archive tests pass.
Frontend treats an idle task after restart as an interrupted transfer and tells
the user to check both locations instead of polling forever. The later interrupted
`cube_pore` Alpine production job `a4cb52583c26` is being recovered separately,
using rsync append verification plus full per-file SHA-256 comparisons before
changing the archive index and deleting the original. Recovery status/report:
`/tmp/nadoc-cube-pore-recovery/` (temporary; final result will be recorded here).

**Recovery completed 2026-10-03:** All 37 cube_pore files (48,829,771,544 bytes)
matched source/destination SHA-256, including the 47,859,659,852-byte trajectory.
Then job metadata + archive index were updated to `/mnt/f/NADOC/a4cb52583c26`,
and only then was the WSL source directory removed. Verified archived job loads
and reports storage available. Audit manifests and hashes retained under
`.development-artifacts/archive-recovery-cube-pore-20261003/`. WSL usage afterward:
about 300 GiB. Progress fix validation: 22 backend archive tests, interrupted-task
UI regression test, frontend production build. New tasks are registered before
worker scheduling so an immediate poll cannot falsely report interruption.
