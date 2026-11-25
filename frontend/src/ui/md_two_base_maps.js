import { store } from '../state/store.js'
import { getMdTwoBaseMaps, getMdTwoBaseProgress } from '../api/client.js'
import { selectedBaseDisplayRows } from './design_display_labels.js'
import { openTwoBaseMaps, DEFAULT_TWO_BASE_MAPS } from './two_base_maps_popup.js'

import { exportTwoBaseMaps } from './two_base_maps_export.js'

export function singleSelectedBase(state) {
  const items = state.selection?.items || []
  return items.length === 1 && items[0].kind === 'base' ? items[0].key : null
}

export function initMdTwoBaseMaps({ getSelectedJob, stateStore = store, root = document,
  generate = (...args) => getMdTwoBaseMaps(...args), show = openTwoBaseMaps, exportResult = exportTwoBaseMaps,
  getProgress = (...args) => getMdTwoBaseProgress(...args) } = {}) {
  const el = key => root.getElementById(`md-two-base-${key}`)
  const picks = [el('1'), el('2')], gen = el('generate'), display = el('show'), status = el('status'), save = el('export')
  const bar = el('progress'), fill = el('fill'), percent = el('percent')
  const maps = [...DEFAULT_TWO_BASE_MAPS]
  let poll = null, completedPercent = 0
  function stopPolling() { clearInterval(poll); poll = null }
  function paintProgress(value) {
    const n = Math.max(completedPercent,Math.min(100,Number(value)||0))
    completedPercent = n
    if (bar) { bar.hidden = false; bar.setAttribute('aria-valuenow',String(n)) }
    if (fill) fill.style.width = `${n}%`
    if (percent) percent.textContent = `${Math.floor(n)}%`
  }
  let keys = [null, null], armed = null, result = null, busy = false, revision = 0, controller = null
  let jobId = null, designId = null
  const listeners = []
  function listen(node, fn) { node?.addEventListener('click', fn); listeners.push(() => node?.removeEventListener('click', fn)) }
  function invalidate() { completedPercent = 0; stopPolling(); if (bar) bar.hidden = true; revision++; controller?.abort(); controller = null; result = null; busy = false }
  function sync() {
    const state = stateStore.getState(), job = getSelectedJob?.()
    if (jobId !== job?.job_id || designId !== state.currentDesign?.id) {
      invalidate(); keys = [null, null]; armed = null
      jobId = job?.job_id; designId = state.currentDesign?.id
      if (status) status.textContent = ''
    }
    picks.forEach((button, i) => {
      if (!button) return
      const label = keys[i] ? selectedBaseDisplayRows([keys[i]], state.currentDesign, state.currentGeometry)[0]?.label || keys[i] : 'Select'
      button.textContent = `base ${i + 1}: ${armed === i ? 'Select a base…' : label}`
      button.setAttribute('aria-pressed', String(armed === i))
      button.disabled = !jobId
    })
    if (gen) gen.disabled = busy || !jobId || !keys.every(Boolean) || keys[0] === keys[1]
    if (display) display.disabled = busy || !result
    if (save) save.disabled = busy || !result
    for (const button of [...picks,gen,display,save]) if (button) {
      button.style.opacity = button.disabled ? '0.45' : '1'
      button.style.cursor = button.disabled ? 'default' : 'pointer'
    }
  }
  function capture(i, key) { invalidate(); keys[i] = key; armed = null; if (status) status.textContent = keys[0] === keys[1] ? 'Choose two different bases.' : ''; sync() }
  picks.forEach((button, i) => listen(button, () => {
    const key = singleSelectedBase(stateStore.getState())
    if (key) capture(i, key)
    else { armed = armed === i ? null : i; sync() }
  }))
  const unsubscribe = stateStore.subscribe((state, previous) => {
    sync()
    if (armed != null && state.selection !== previous.selection) {
      const key = singleSelectedBase(state)
      if (key) capture(armed, key)
    }
  })
  listen(gen, async () => {
    if (gen.disabled) return
    const token = ++revision
    controller = new AbortController(); busy = true; sync()
    if (status) status.textContent = 'Generating…'
    completedPercent = 0; paintProgress(0)
    const requestId = crypto.randomUUID(), requestJob = jobId
    let polling = false
    poll = setInterval(async () => {
      if (polling) return
      polling = true
      try { const p = await getProgress(requestJob,requestId); if (token === revision && busy) paintProgress(p.percent) }
      catch { /* The generation request reports errors. */ }
      finally { polling = false }
    },500)
    try {
      const data = await generate(jobId, keys, { signal: controller.signal, designId, requestId })
      if (token !== revision) return
      result = data
      paintProgress(100)
      if (status) status.textContent = `${data.frames} frames`
    } catch (error) { if (token === revision) { if (bar) bar.hidden = true; if (status) status.textContent = error.message || 'Generation failed.' } }
    finally { if (token === revision) { stopPolling(); busy = false; controller = null; sync() } }
  })
  listen(display, () => { if (result && !display.disabled) show(result, { maps }) })
  listen(save, async () => {
    if (!result || save.disabled) return
    const token = revision
    try { await exportResult(result,jobId,[...maps]) }
    catch (error) { if (token === revision && status) status.textContent = error.message || 'Export failed.' }
  })
  sync()
  return { sync, dispose() { invalidate(); unsubscribe(); listeners.forEach(f => f()) } }
}
