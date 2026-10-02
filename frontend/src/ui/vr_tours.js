import { el } from './primitives/dom.js'
import './vr_tours.css'

/** Direct-launch flyouts use the same menu behavior as the other Debug entries. */
export function initVrTours({ headers = () => ({}), request = fetch, store = {}, showToast = () => {}, entryId = 'menu-debug-vr-tours', title = 'VR Tours & Tests', groupFilter = null, modes = ['demo', 'validate'] } = {}) {
  const entry = document.getElementById(entryId)
  if (!entry) return null
  let run = null, busy = false, loaded = false, timer = null, disposed = false
  const menu = el('div', { className: 'submenu vr-tours-menu', attrs: { role: 'menu' } })
  const status = el('span', { className: 'vr-tours-status', attrs: { role: 'status' } })
  const stop = el('button', { className: 'dropdown-item', text: 'Stop tour', on: { click: () => action('/stop/'+run.id) } })
  entry.className = 'submenu-item'
  entry.replaceChildren(document.createTextNode(title), el('span', { text: '›', attrs: { 'aria-hidden': 'true' } }), menu)
  entry.tabIndex = 0
  entry.setAttribute('aria-haspopup', 'menu')
  menu.append(status)
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
  function render() {
    stop.disabled = busy || !active() || run.status === 'stopping'
    menu.querySelectorAll('[data-start]').forEach(b => { b.disabled = busy || !!active() || b.dataset.runnable !== 'true' })
    status.textContent = run ? `Tour ${run.status}` : 'Ready'
    status.title = run ? `${run.output}\n${run.log || ''}` : 'Evidence is retained under .development-artifacts/vr-debug-tours/'
  }
  function poll() {
      clearInterval(timer)
      timer = setInterval(async () => {
        if (busy || disposed) return
        try { run = (await api('/status')).run; render(); if (!active()) clearInterval(timer) } catch { clearInterval(timer) }
      }, 1000)
  }
  async function action(path, payload = {}) {
    if (busy) return
    busy = true; render()
    try {
      run = (await api(path, payload)).run
      showToast(`VR tour ${run.status}`)
      poll()
    } catch (error) {
      showToast(error.message, { severity: 'error' })
      busy = false; render(); status.textContent = error.message; return
    } finally { busy = false }
    render()
  }
  async function open() {
    if (loaded || busy) return
    busy = true; status.textContent = 'Loading tours…'
    try {
      const catalog = await api()
      if (disposed) return
      run = catalog.run
      for (const group of catalog.groups.filter(g => !groupFilter || g.id === groupFilter)) {
        const children = el('div', { className: 'submenu vr-tours-menu vr-tours-leaves', attrs: { role: 'menu' } })
        for (const tour of catalog.tours.filter(t => t.group === group.id)) {
          for (const mode of modes) {
            children.append(el('button', {
              className: 'dropdown-item', text: `${tour.title} ${mode === 'desktop' ? 'desktop demo' : mode === 'demo' ? (groupFilter ? 'VR demo' : 'demo') : 'validation'}`,
              dataset: { start: tour.id, mode, runnable: String(tour.runnable) },
              attrs: { title: tour.description },
              on: { click: () => action('/start', { tour: tour.id, mode,
                ...(tour.id === 'representations' ? { assembly_active: !!store.assemblyActive } : {}) }) },
            }))
          }
        }
        menu.insertBefore(el('div', { className: 'submenu-item', text: group.label,
          dataset: { category: group.id }, attrs: { role: 'menuitem', tabindex: '0', 'aria-haspopup': 'menu', title: group.description },
          children: [el('span', { text: '›', attrs: { 'aria-hidden': 'true' } }), children] }), status)
      }
      menu.append(stop); loaded = true; if (active()) poll()
    } catch (error) { status.textContent = error.message }
    finally { busy = false; if (loaded) render() }
  }
  function keyboard(event) {
    const branch = event.target.closest('.submenu-item')
    if (!branch || !entry.contains(branch) || event.target !== branch) return
    if (['Enter', ' ', 'ArrowRight', 'ArrowDown'].includes(event.key)) {
      event.preventDefault(); event.stopPropagation()
      branch.classList.add('a11y-open')
      open().then(() => branch.querySelector(':scope > .submenu > .submenu-item, :scope > .submenu > button:not(:disabled)')?.focus())
    } else if (event.key === 'ArrowLeft' && branch !== entry) {
      event.preventDefault(); event.stopPropagation(); branch.classList.remove('a11y-open'); entry.focus()
    }
  }
  function position(event) {
    const branch = event.target.closest('[data-category]')
    if (!branch) return
    const children = branch.querySelector(':scope > .submenu')
    const top = branch.getBoundingClientRect().top
    children.style.top = `${Math.max(8 - top, Math.min(0, window.innerHeight - top - children.getBoundingClientRect().height - 8))}px`
  }
  entry.addEventListener('keydown', keyboard)
  entry.addEventListener('pointerover', position)
  entry.addEventListener('focusin', position)
  entry.addEventListener('pointerenter', open)
  entry.addEventListener('focusin', open)
  entry.addEventListener('click', open)
  return { open, dispose() { disposed = true; clearInterval(timer); entry.removeEventListener('keydown', keyboard); entry.removeEventListener('pointerover', position); entry.removeEventListener('focusin', position); entry.removeEventListener('pointerenter', open); entry.removeEventListener('focusin', open); entry.removeEventListener('click', open) } }
}
