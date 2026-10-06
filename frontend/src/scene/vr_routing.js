import { docHeaders } from '../shared/doc_id.js'

export const ROUTING_ACTIONS = [
  ['menu-routing-scaffold-ends', 'Autoscaffold'],
  ['menu-routing-full-autostaple', 'Full Autostaple'],
  ['menu-routing-polymerization', 'Route for Polymerization'],
  ['menu-seq-update-routing', 'Add Loops/Skips'],
  ['menu-seq-clear-all-loop-skips', 'Clear All Loop/Skips'],
  ['menu-seq-assign-scaffold', 'Assign Scaffold Sequence'],
  ['menu-seq-assign-staples', 'Assign Staple Sequences'],
  ['menu-seq-generate-overhangs', 'Generate Overhangs'],
  ['menu-seq-hairpin-dimer', 'Hairpin/Dimer Checker'],
  ['menu-edit-undo', 'Undo'], ['menu-edit-redo', 'Redo'],
]
const clean = text => String(text ?? '').replace(/\s+/g, ' ').trim()

/** Desktop handlers own validation, design changes and history. Native receives only allowlisted controls. */
export function createVRRouting({ doc = document, request = fetch, onError = console.error } = {}) {
  let version = Math.floor(Math.random() * 1e9), acknowledged = 0, published, sending = false, epoch = 0
  let opened = false, editing = false, message = '', operation = '', invoking = false
  const pending = new Set()
  const win = doc.defaultView
  const diagnostic = ({ detail: d }) => {
    if (d.phase === 'start' && opened && (invoking || /^\/(?:design|assembly)\/(?:auto-scaffold|full-autostaple|route-for-polymerization|assign-|generate-overhang-sequences|loop-skip|overhangs?\/|hairpin|undo$|redo$)/.test(d.path)) && d.method !== 'GET') pending.add(d.id)
    if (['complete', 'error'].includes(d.phase) && pending.delete(d.id)) {
      if (d.phase === 'error' || d.status >= 400) message = d.message || 'Operation failed.'
    }
  }
  win?.addEventListener('nadoc:api-request', diagnostic)
  const observer = new win.MutationObserver(records => {
    if (!opened) return
    for (const record of records) for (const node of record.addedNodes) {
      const toast = node.nodeType === 1 && (node.matches('.toast-message') ? node : node.querySelector('.toast-message'))
      if (toast && !/^Selection:/.test(clean(toast.textContent))) message = clean(toast.textContent)
    }
  })
  observer.observe(doc.body, { childList: true, subtree: true })
  const busy = () => pending.size > 0 || !!doc.querySelector('#op-progress.visible')
  const enabled = el => !!el && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !el.classList.contains('disabled')
  function snapshot() {
    const waiting = busy()
    const roots = ROUTING_ACTIONS.map(([id, label]) => { const element = doc.getElementById(id); return { id, label, enabled: enabled(element) && !waiting, active: element?.getAttribute('aria-checked') === 'true' || !!element?.classList.contains('is-on') || !!element?.classList.contains('is-checked'), element } })
    const auto = doc.querySelector('#autoscaffold-modal.visible')
    const modal = [...doc.querySelectorAll('.modal__overlay')].find(el => /^(Assign Scaffold Sequence|Clear loops & skips)$/.test(clean(el.querySelector('.modal__title')?.textContent)))
    const root = auto || modal
    let title = '', detail = '', controls = []
    const add = (id, label, run, active = false, allowed = true) => controls.push({ id, label, active, enabled: allowed && !waiting, run })
    if (root) {
      title = auto ? 'Autoscaffold' : clean(root.querySelector('.modal__title')?.textContent)
      const textarea = root.querySelector('#asc-custom-seq')
      if (editing && textarea) {
        title = 'Custom scaffold sequence'
        detail = `${textarea.value.length} bases: ${textarea.value.slice(-60) || '(empty)'}`
        const edit = fn => { textarea.value = fn(textarea.value); textarea.dispatchEvent(new win.Event('input', { bubbles: true })) }
        add('key-done', 'Done', () => { editing = false })
        for (const base of ['A', 'C', 'G', 'T', 'N']) add(`key-${base.toLowerCase()}`, `Add ${base}`, () => edit(value => value + base))
        add('key-delete', 'Backspace', () => edit(value => value.slice(0, -1)))
        add('key-clear', 'Clear sequence', () => edit(() => ''))
      } else {
        detail = clean(auto ? root.querySelector('input:checked')?.closest('label')?.querySelector('.as-desc')?.textContent || 'Choose seamed or seamless routing' : root.querySelector('.modal__body')?.textContent)
        for (const [i, el] of [...root.querySelectorAll('button,input[type=radio]')].entries()) {
          if (el.classList.contains('modal__close')) continue
          const label = clean(el.type === 'radio' ? el.closest('label')?.querySelector('.as-label')?.textContent || el.closest('label')?.textContent || el.value : el.getAttribute('aria-label') || el.textContent)
          add(`dialog-${i}`, label, () => { el.click(); if (/^(Cancel|Close)$/i.test(label)) { opened = false; editing = false } }, !!el.checked, enabled(el))
        }
        if (textarea) add('custom-sequence', `Custom sequence (${textarea.value.length} bases)`, () => { editing = true })
      }
    } else if (opened) {
      title = waiting ? `${operation}: working...` : operation
      detail = message || (waiting ? 'Please wait for the operation to finish.' : 'Operation finished.')
      add('dismiss', 'Back to Tools', () => { opened = false; message = ''; editing = false })
      for (const row of roots.slice(-2)) add(row.id, row.label, () => row.element.click(), false, row.enabled)
    }
    // Keep full messages readable by scrolling rather than truncating to one label.
    const info = (detail.match(/.{1,65}(?:\s|$)|.{1,65}/g) || []).map((label, i) => ({ id: `info-${i}`, label: clean(label), enabled: false, active: false }))
    return { title, roots, controls: [...controls, ...info] }
  }
  const wire = state => JSON.parse(JSON.stringify(state, (key, value) => ['element', 'run'].includes(key) ? undefined : value))
  async function publish() {
    if (sending) return
    const state = snapshot(), data = wire(state), signature = JSON.stringify(data)
    if (published?.signature === signature && published.acknowledged === acknowledged) return
    const current = ++version, generation = epoch, ack = acknowledged
    sending = true
    try {
      const response = await request('/api/vr/routing', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ ...data, version: current, acknowledged: ack }) })
      if (!response.ok) throw new Error('Could not update VR routing controls')
      if (generation === epoch) published = { version: current, signature, acknowledged: ack }
    } finally { sending = false }
  }
  async function activate(event) {
    if (!Number.isSafeInteger(event.sequence) || event.sequence <= acknowledged) return
    acknowledged = event.sequence
    const state = snapshot()
    if (!published || event.version !== published.version || JSON.stringify(wire(state)) !== published.signature) { await publish(); return }
    const row = (state.title ? state.controls : state.roots).find(row => row.id === event.id)
    if (row?.enabled) {
      invoking = true
      try {
        if (row.run) { if (row.id.startsWith('menu-edit-')) { message = ''; operation = row.label } row.run() }
        else { opened = true; editing = false; message = ''; operation = row.label; row.element.click() }
      } finally { invoking = false }
    }
    await publish()
  }
  return { snapshot, publish: () => publish().catch(() => {}), activate: event => activate(event).catch(error => onError(error.message)),
    reset() { epoch++; published = null; acknowledged = 0; opened = false; editing = false; pending.clear() },
    dispose() { observer.disconnect(); win?.removeEventListener('nadoc:api-request', diagnostic) },
  }
}
