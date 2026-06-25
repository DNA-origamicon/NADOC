/**
 * Job archive/unarchive flow — shared by the oxDNA and MD job panels.
 *
 * `initJobArchive({ api, kind })` (kind: 'oxdna' | 'md') → { archive, unarchive }.
 * Each drives the full flow: pick a destination folder (archive) or confirm
 * (unarchive), kick off the background move, and poll the archive-status endpoint
 * reporting byte progress via onProgress(st). The last-used archive root is
 * remembered in localStorage so the next archive defaults to the same drive.
 *
 * The move itself is the backend's job (job_archive.py); this module is the UI
 * orchestration so neither panel duplicates the picker + poll + toast logic.
 */

import { pickSystemFolder } from './folder_picker.js'
import { showToast } from './toast.js'
import { showConfirm } from './primitives/confirm.js'

const _LS_KEY = 'nadoc.archiveRoot'

export function initJobArchive({ api, kind }) {
  // Resolved lazily (not at init) so panels can construct the controller even
  // when the archive endpoints aren't part of a test's api mock.
  const _fns = () => kind === 'md'
    ? { archive: api.archiveMdJob, unarchive: api.unarchiveMdJob, status: api.mdArchiveStatus }
    : { archive: api.archiveOxdnaJob, unarchive: api.unarchiveOxdnaJob, status: api.oxdnaArchiveStatus }

  function _poll(jobId, onProgress) {
    const status = _fns().status
    return new Promise((resolve) => {
      const tick = async () => {
        const st = await status(jobId)
        if (st) {
          if (st.state === 'running') onProgress?.(st)
          if (st.state === 'done' || st.state === 'error') { resolve(st); return }
        }
        setTimeout(tick, 700)
      }
      tick()
    })
  }

  async function archive(job, { onProgress } = {}) {
    const dest = await pickSystemFolder({
      api,
      title: `Archive job ${job.job_id} — choose destination folder`,
      initialPath: localStorage.getItem(_LS_KEY) || null,
    })
    if (!dest) return false
    localStorage.setItem(_LS_KEY, dest)
    const r = await _fns().archive(job.job_id, dest)
    if (!r) { showToast(`Archive failed: ${api.lastErrorMessage?.() ?? 'error'}`, { severity: 'error' }); return false }
    onProgress?.({ state: 'running', moved_bytes: 0, total_bytes: 0 })
    const st = await _poll(job.job_id, onProgress)
    if (st.state === 'error') { showToast(`Archive failed: ${st.error}`, { severity: 'error' }); return false }
    showToast('Job archived', { severity: 'success' })
    return true
  }

  async function unarchive(job, { onProgress } = {}) {
    const ok = await showConfirm({
      title: 'Unarchive job?',
      message: `Move job ${job.job_id} back into the workspace from\n${job.archive_path ?? 'its archive location'}?`,
      confirmLabel: 'Unarchive',
    })
    if (!ok) return false
    const r = await _fns().unarchive(job.job_id)
    if (!r) { showToast(`Unarchive failed: ${api.lastErrorMessage?.() ?? 'error'}`, { severity: 'error' }); return false }
    onProgress?.({ state: 'running', moved_bytes: 0, total_bytes: 0 })
    const st = await _poll(job.job_id, onProgress)
    if (st.state === 'error') { showToast(`Unarchive failed: ${st.error}`, { severity: 'error' }); return false }
    showToast('Job unarchived', { severity: 'success' })
    return true
  }

  return { archive, unarchive }
}
