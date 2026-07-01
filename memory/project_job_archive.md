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
