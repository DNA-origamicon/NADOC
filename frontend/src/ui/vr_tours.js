import { createModal } from './primitives/modal.js'
import { el } from './primitives/dom.js'
import './vr_tours.css'

/** Organized entry points into the maintained VR workflows, with owned-run status. */
export function initVrTours({ headers = () => ({}), request = fetch } = {}) {
  const entry = document.getElementById('menu-debug-vr-tours')
  if (!entry) return null
  let catalog = null, category = 'overview', run = null, timer = null, busy = false, errorMessage = null
  const tabs = el('div', { className: 'vr-tours__tabs', attrs: { role: 'tablist', 'aria-label': 'VR tour categories' } })
  const cards = el('div', { id: 'vr-tour-cards', attrs: { role: 'tabpanel' } })
  const message = el('p', { attrs: { role: 'status' } })
  const logs = el('pre', { className: 'vr-tours__log', attrs: { 'aria-label': 'Tour output', tabindex: '0' } })
  const mode = el('select', { attrs: { 'aria-label': 'Tour mode' }, children: [
    el('option', { text: 'Demo · steady controller', attrs: { value: 'demo' } }),
    el('option', { text: 'Validate · all four controller profiles', attrs: { value: 'validate' } }),
  ], on: { change: () => renderCards() } })
  const stop = el('button', { className: 'btn', text: 'Stop tour', on: { click: () => action('/stop/'+run.id) } })
  const body = el('div', { className: 'vr-tours', children: [
    el('p', { text: 'Run an isolated VR demo or validation. Close any active viewer first. Demo menus stay open for review until you stop the tour; validation exits when finished.' }),
    el('div', { className: 'vr-tours__toolbar', children: [mode, stop] }),
    tabs, cards, message, logs,
  ] })
  const modal = createModal({ title: 'VR Tours & Tests', size: 'lg', body,
    onClose: () => { clearInterval(timer); timer = null; entry.focus() } })
  modal.root.setAttribute('aria-label', 'VR Tours & Tests')
  async function api(path = '', data) {
    const response = await request('/api/vr/tours'+path, {
      method: data === undefined ? 'GET' : 'POST',
      headers: { ...headers(), 'Content-Type': 'application/json' },
      ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    })
    const json = await response.json()
    if (!response.ok) throw new Error(json.detail || 'Could not access VR tours')
    return json
  }
  const active = () => run && ['running', 'stopping'].includes(run.status)
  function renderStatus() {
    stop.disabled = busy || !active() || run.status === 'stopping'
    mode.disabled = busy || !!active()
    cards.querySelectorAll('[data-start]').forEach(button => { button.disabled = busy || !!active() })
    if (errorMessage) { message.textContent = errorMessage; return }
    if (run) {
      const title = catalog?.tours.find(t => t.id === run.tour)?.title ?? run.tour
      message.textContent = `${title}: ${run.status}${run.exit_code == null ? '' : ` (exit ${run.exit_code})`} · Evidence: ${run.output}`
      logs.textContent = run.log || 'Waiting for tour output…'
      logs.hidden = false
    } else { message.textContent = 'Ready. Evidence is retained under .development-artifacts/vr-debug-tours/.'; logs.hidden = true }
  }
  async function action(path, payload = {}) {
    if (busy) return
    errorMessage = null; busy = true; renderStatus()
    try { run = (await api(path, payload)).run }
    catch (error) { errorMessage = error.message; message.textContent = errorMessage; busy = false; return }
    finally { busy = false; stop.disabled = !active() || run?.status === 'stopping'; mode.disabled = !!active(); cards.querySelectorAll('[data-start]').forEach(b => { b.disabled = !!active() }) }
    renderStatus()
  }
  async function refresh() {
    if (busy || !modal.isOpen()) return
    try { run = (await api('/status')).run; renderStatus() }
    catch (error) { message.textContent = error.message }
  }
  function renderCards() {
    if (!catalog) return
    cards.setAttribute('aria-labelledby', 'vr-tour-tab-'+category)
    cards.replaceChildren(el('p', { text: catalog.groups.find(g => g.id === category)?.description }))
    for (const tour of catalog.tours.filter(t => t.group === category)) {
      const command = mode.value === 'validate' ? tour.validation_command : tour.command
      const copy = el('button', { className: 'btn btn--sm', text: 'Copy command', on: { click: async () => {
        try { await navigator.clipboard.writeText(command); copy.textContent = 'Copied' }
        catch { message.textContent = 'Clipboard unavailable. Select and copy the command below.' }
      } } })
      const actions = [copy]
      if (tour.runnable) actions.unshift(el('button', { className: 'btn btn--primary btn--sm', text: mode.value === 'validate' ? 'Run validation' : 'Run demo',
        dataset: { start: tour.id }, on: { click: () => action('/start', { tour: tour.id, mode: mode.value }) } }))
      cards.append(el('article', { className: 'vr-tours__card', children: [
        el('h3', { text: tour.title }), el('p', { text: tour.description }),
        el('div', { className: 'vr-tours__toolbar', children: actions }),
        el('code', { text: command }),
      ] }))
    }
    renderStatus()
  }
  function select(id, focus = false) {
    category = id
    for (const button of tabs.children) {
      const selected = button.dataset.category === category
      button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1
      if (selected && focus) button.focus()
    }
    renderCards()
  }
  async function open() {
    modal.open(); errorMessage = null; message.textContent = 'Loading tours…'
    try {
      const result = await api(); if (!modal.isOpen()) return; catalog = result; run = result.run
      tabs.replaceChildren(...catalog.groups.map(group => el('button', {
        id: 'vr-tour-tab-'+group.id, text: group.label, dataset: { category: group.id },
        attrs: { role: 'tab', 'aria-controls': cards.id }, on: { click: () => select(group.id) },
      })))
      select(category, true)
      clearInterval(timer); timer = setInterval(refresh, 1000)
    } catch (error) { message.textContent = error.message }
  }
  tabs.addEventListener('keydown', event => {
    const index = catalog.groups.findIndex(g => g.id === category), count = catalog.groups.length
    const next = { ArrowRight: (index+1)%count, ArrowLeft: (index+count-1)%count, Home: 0, End: count-1 }[event.key]
    if (next !== undefined) { event.preventDefault(); select(catalog.groups[next].id, true) }
  })
  entry.addEventListener('click', open)
  return { open, close: modal.close, dispose() { modal.close(); clearInterval(timer); entry.removeEventListener('click', open) } }
}
