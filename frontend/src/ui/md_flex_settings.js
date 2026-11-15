import { defaultFlexRange, validateFlexRange } from './md_flex_range.js'
export { defaultFlexRange, validateFlexRange, flexRangeQuery } from './md_flex_range.js'

/** Own drafts separately from applied per-job settings. Cancel never starts work. */
export function initMdFlexSettings({ button, getJobId, getCounts, onApply }) {
  const applied = new Map()
  let dialog = null, generation = 0
  const close = () => { generation++; dialog?.remove(); dialog = null }
  async function open() {
    close()
    const epoch = generation, jobId = getJobId()
    if (!jobId) return
    button.disabled = true
    let counts
    try { counts = await getCounts(jobId, { refetch: true }) } catch { counts = null } finally { button.disabled = false }
    if (epoch !== generation || jobId !== getJobId()) return
    const total = counts?.reduce((sum, count) => sum + count, 0) || 0
    const values = applied.get(jobId) || defaultFlexRange(total)
    dialog = document.createElement('dialog')
    dialog.id = 'md-flex-settings-dialog'
    dialog.setAttribute('aria-label', 'Flexibility map settings')
    dialog.style.cssText = 'color:#c9d1d9;background:#161b22;border:1px solid #484f58;border-radius:8px;padding:18px;min-width:270px'
    dialog.innerHTML = `<form><h3 style="margin:0 0 12px">Flexibility map settings</h3>
      <p style="font-size:12px">Frames are numbered from 1; End is included.<br>Available frames: <span data-total></span></p>
      ${['start', 'end', 'interval'].map(key => `<label style="display:flex;justify-content:space-between;gap:20px;margin:8px 0">${key[0].toUpperCase() + key.slice(1)}
        <input name="${key}" aria-label="${key[0].toUpperCase() + key.slice(1)}" type="number" min="1" step="1" required style="width:110px"></label>`).join('')}
      <p data-error role="alert" style="color:#f0883e;font-size:12px"></p>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px"><button type="button" data-cancel>Cancel</button><button type="submit" data-apply>Apply</button></div></form>`
    dialog.querySelector('[data-total]').textContent = total.toLocaleString()
    for (const [key, value] of Object.entries(values)) dialog.querySelector(`[name="${key}"]`).value = value
    for (const key of ['start', 'end']) dialog.querySelector(`[name="${key}"]`).max = total
    dialog.querySelector('[data-apply]').disabled = total < 1
    if (!total) dialog.querySelector('[data-error]').textContent = 'No trajectory frames available.'
    dialog.querySelector('[data-cancel]').onclick = close
    dialog.addEventListener('cancel', event => { event.preventDefault(); close() })
    dialog.querySelector('form').onsubmit = event => {
      event.preventDefault()
      if (jobId !== getJobId()) { close(); return }
      let range
      try { range = validateFlexRange(Object.fromEntries(new FormData(event.currentTarget)), total) }
      catch (error) { dialog.querySelector('[data-error]').textContent = error.message; return }
      applied.set(jobId, range)
      close()
      onApply(range)
    }
    document.body.append(dialog)
    dialog.showModal()
    dialog.querySelector('[name="start"]').focus()
  }
  button?.addEventListener('click', open)
  return { range: jobId => applied.get(jobId) || null, reset: jobId => applied.delete(jobId), open, close,
    dispose() { close(); button?.removeEventListener('click', open) } }
}

/** A rendered preliminary map is already usable for color-scale editing. */
export function showMappedFlexScale(result, scale, viz) {
  if (!Number.isFinite(result?.min) || !Number.isFinite(result?.max)) return
  if (scale?.isVisible?.()) { scale.updateRange?.(result.min, result.max); return }
  scale?.show?.({ title: 'RMSF (nm)', min: result.min, max: result.max, mapType: 'flex',
    onRecolor: (lo, hi, cmap) => viz?.recolorRmsf?.(lo, hi, cmap) })
}
