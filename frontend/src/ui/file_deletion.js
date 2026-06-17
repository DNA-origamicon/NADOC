/**
 * ui/file_deletion.js — shared "delete a workspace file/folder, offering to also
 * remove its MD / oxDNA job folders" flow.
 *
 * Both deletion entry points — the welcome-screen library panel and the
 * file-browser modal — call {@link confirmAndDeleteFile} so they behave
 * identically: confirm the delete, look up the job folders generated from that
 * file (or any file under that folder), and if any exist ask whether to delete
 * them too. If a matching job is still running the job folders are kept (they
 * can't be removed until the job is stopped) and only the file is deleted.
 *
 * The message/decision helpers are pure and unit-tested; the orchestrator wires
 * the confirm dialogs + injected API.
 */

import { showConfirm } from './primitives/confirm.js'
import { showToast } from './toast.js'

/** Pure: total count of associated job folders. */
export function jobCount(jobs) {
  return (jobs?.md?.length || 0) + (jobs?.oxdna?.length || 0)
}

/** Pure: human phrase for the associated job folders, or '' when there are none. */
export function jobCleanupSummary(jobs) {
  const parts = []
  const md = jobs?.md?.length || 0
  const ox = jobs?.oxdna?.length || 0
  if (md) parts.push(`${md} MD job folder${md > 1 ? 's' : ''}`)
  if (ox) parts.push(`${ox} oxDNA job folder${ox > 1 ? 's' : ''}`)
  return parts.join(' and ')
}

/** Pure: ids of associated jobs that are still running. */
export function runningJobIds(jobs) {
  return [...(jobs?.md || []), ...(jobs?.oxdna || [])]
    .filter(j => j.running)
    .map(j => j.job_id)
}

/**
 * Confirm and delete a workspace file/folder, offering job-folder cleanup.
 *
 * @param {object}  opts
 * @param {object}  opts.api      — API client (deleteLibraryItem, getAssociatedJobs)
 * @param {string}  opts.path     — workspace-relative path
 * @param {string}  opts.name     — display name for the confirm dialog
 * @param {boolean} [opts.isDir]  — true for a folder delete
 * @returns {Promise<boolean>} true if the file/folder was deleted
 */
export async function confirmAndDeleteFile({ api, path, name, isDir = false }) {
  const noun = isDir ? 'folder' : 'file'

  const ok = await showConfirm({
    title: isDir ? 'Delete folder' : 'Delete file',
    message: isDir
      ? `Delete folder "${name}" and all its contents?`
      : `Delete "${name}"?`,
    danger: true,
    confirmLabel: 'Delete',
  })
  if (!ok) return false

  // Look up job folders generated from this file/folder. A lookup failure must
  // not block the (already-confirmed) delete — fall back to deleting just the file.
  let jobs = { md: [], oxdna: [] }
  try {
    jobs = await api.getAssociatedJobs(path)
  } catch {
    await api.deleteLibraryItem(path)
    return true
  }

  let deleteJobs = false
  if (jobCount(jobs) > 0) {
    const summary = jobCleanupSummary(jobs)
    const running = runningJobIds(jobs)
    if (running.length) {
      // A running job's folder can't be deleted — offer file-only delete or cancel.
      const proceed = await showConfirm({
        title: 'Job still running',
        message: `This ${noun} has ${summary}, but ${running.length} `
          + `${running.length > 1 ? 'are' : 'is'} still running. Stop `
          + `${running.length > 1 ? 'them' : 'it'} first to remove the job folders.\n\n`
          + `Delete the ${noun} only and keep the job folders?`,
        danger: true,
        confirmLabel: `Delete ${noun}, keep jobs`,
        cancelLabel: 'Cancel',
      })
      if (!proceed) return false
    } else {
      deleteJobs = await showConfirm({
        title: 'Delete job folders?',
        message: `This ${noun} has ${summary}. Also delete `
          + `${jobCount(jobs) > 1 ? 'them' : 'it'}?`,
        danger: true,
        confirmLabel: 'Delete job folders',
        cancelLabel: 'Keep job folders',
      })
    }
  }

  const res = await api.deleteLibraryItem(path, deleteJobs)
  if (deleteJobs && res?.deleted_jobs?.length) {
    const n = res.deleted_jobs.length
    showToast(`Deleted ${n} job folder${n > 1 ? 's' : ''}`)
  }
  return true
}
