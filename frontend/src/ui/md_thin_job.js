import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { showConfirm } from './primitives/confirm.js'
import { el } from './primitives/dom.js'
import { formatBytes } from './format_bytes.js'

export const THIN_JOB_TOOLTIP = 'Reduce trajectory storage by keeping every selected frame interval. Retained frame coordinates stay unchanged; discarded frames are permanently deleted after confirmation.'
export const THIN_JOB_CONFIRMATION = 'Are you sure? This will permanently delete frames from the job to reduce storage space.'

export function openThinJob({ jobId, api, onApplying = () => {}, onApplied = async () => {} }) {
  let preview = null
  let busy = false
  let closed = false
  const status = el('p', { text: 'Assessing frame spacing, storage, and RMSD…', attrs: { role: 'status' } })
  const select = el('select', { className: 'select', attrs: { 'aria-label': 'Keep every frame interval', disabled: true, style: 'width:auto;min-width:120px;margin:0 6px' } })
  const label = el('label', { children: ['Keep every ', select, ' frame.'] })
  const table = el('table', { attrs: { 'aria-label': 'Thinning options', style: 'width:100%;margin-top:16px;text-align:left;border-collapse:collapse' } })
  const note = el('p', { attrs: { style: 'font-size:var(--text-sm);color:var(--color-text-muted);margin-top:12px' } })
  const boundary = el('p')
  const body = el('div', { children: [label, status, table, note, boundary] })
  const cancel = createButton({ label: 'Cancel', onClick: () => modal.close() })
  const apply = createButton({ label: 'Apply', variant: 'primary', onClick: async () => {
    if (busy || !preview || Number(select.value) <= 1) return
    busy = true; update()
    const yes = await showConfirm({ title: 'Confirm thinning', message: THIN_JOB_CONFIRMATION,
      danger: true, confirmLabel: 'Yes', cancelLabel: 'No' })
    if (!yes) { busy = false; update(); return }
    status.textContent = 'Thinning trajectory and verifying retained frames…'
    try {
      await onApplying()
      const result = await api.applyThinMdJob(jobId, {
        stride: Number(select.value), fingerprint: preview.fingerprint, confirmed: true,
      })
      if (!result?.ok) throw new Error(api.lastErrorMessage?.() || 'Thinning failed. Close and reopen this dialog to refresh the assessment.')
      busy = false
      modal.close()
      await onApplied(result)
    } catch (error) {
      busy = false
      status.textContent = error.message || 'Thinning failed.'
      // A stale preview must never silently become an authorization for new files.
      preview = null
      update()
    }
  } })
  function update() {
    apply.disabled = busy || !preview || Number(select.value) <= 1
    cancel.disabled = busy
    select.disabled = busy || !preview
    for (const row of table.querySelectorAll('tbody tr')) {
      const selected = row.dataset.stride === select.value
      row.style.background = selected ? 'rgba(74,158,255,.15)' : ''
      row.setAttribute('aria-selected', String(selected))
    }
  }
  select.addEventListener('change', update)
  const modal = createModal({ title: 'Thin job', body, size: 'lg', actions: [cancel, apply],
    onClose: () => { if (busy) return false; closed = true } })
  update(); modal.open()
  const ready = (async () => {
    try {
      const result = await api.previewThinMdJob(jobId)
      if (closed) return
      if (!result?.options?.length) throw new Error(api.lastErrorMessage?.() || 'No trajectory available for thinning.')
      preview = result
      for (const option of preview.options) select.appendChild(el('option', {
        attrs: { value: option.stride }, text: `${option.stride}${option.stride === 1 ? ' (unchanged)' : ''}`,
      }))
      select.value = preview.options.some(o => o.stride === 2) ? '2' : '1'
      const head = el('tr', { children: ['Keep every', 'Frame spacing', 'Storage saved', 'Median RMSD (estimate)'].map(text => el('th', { text, attrs: { scope: 'col', style: 'padding:8px 6px' } })) })
      const tbody = el('tbody')
      for (const option of preview.options) {
        const ps = value => Number(value.toPrecision(6))
        const spacing = option.spacing_ps.length === 1 ? `${ps(option.spacing_ps[0])} ps`
          : `${ps(Math.min(...option.spacing_ps))}–${ps(Math.max(...option.spacing_ps))} ps`
        const rmsd = option.median_rmsd_A == null ? 'Unavailable' : `${option.median_rmsd_A.toFixed(2)} Å`
        tbody.appendChild(el('tr', { dataset: { stride: option.stride }, children: [
          `${option.stride} frame${option.stride === 1 ? '' : 's'}`, spacing,
          `${formatBytes(option.saved_bytes)} (${option.saved_percent.toFixed(1)}%)`, rmsd,
        ].map(text => el('td', { text, attrs: { style: 'padding:8px 6px;border-top:1px solid var(--color-border-default)' } })) }))
      }
      table.replaceChildren(el('thead', { children: [head] }), tbody)
      status.textContent = `${preview.source_frames.toLocaleString()} frames in ${preview.file_count} trajectory file${preview.file_count === 1 ? '' : 's'}.`
      note.textContent = preview.rmsd_note
      boundary.textContent = `${preview.boundary_note} Storage savings refer to trajectory files.`
      update()
    } catch (error) {
      if (!closed) status.textContent = error.message || 'Assessment failed.'
    }
  })()
  return { ...modal, ready }
}
