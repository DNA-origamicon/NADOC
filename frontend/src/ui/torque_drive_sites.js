import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'
import { el } from './primitives/dom.js'
import { createButton } from './primitives/button.js'

/** Driven scopes use the anchor picker, including its display-only focus contract. */
export function initTorqueDriveSites({ mount, getSelection, canEdit, onChange }) {
  const prefix = mount.id
  const ids = Object.fromEntries(['body', 'add', 'clear', 'list', 'glow', 'status']
    .map(key => [key, `${prefix}-${key}`]))
  const add = createButton({ label: 'Add selection to drive', size: 'sm' })
  const clear = createButton({ label: 'Clear', size: 'sm' })
  add.id = ids.add
  clear.id = ids.clear
  const glow = el('input', { attrs: { type: 'checkbox', id: ids.glow } })
  const list = el('div', { attrs: { id: ids.list }, className: 'oxdna-driven-sites-list' })
  mount.append(el('strong', { text: 'Driven sites' }), el('div', { attrs: { id: ids.body }, children: [
    el('div', { className: 'oxdna-driven-sites-actions', children: [add, clear] }), list,
    el('label', { className: 'oxdna-driven-sites-highlight', children: [glow, 'Highlight all driven sites'] }),
    el('div', { attrs: { id: ids.status }, className: 'oxdna-driven-sites-status' }),
  ] }))
  let applying = false
  const picker = initOxdnaAnchorsSetup({ getSelection, ids, engine: 'oxdna-drive',
    collapsible: false, canEdit,
    rowPalette: {
      off: 'background:#1c2733;border:1px solid #30363d;color:#c9d1d9',
      on: 'background:#12343c;border:1px solid #35d9ef;color:#c8f8ff',
    },
    terminology: {
      count: n => `${n} driven site${n === 1 ? '' : 's'}.`,
      empty: 'All unanchored particles',
      focus: 'Click to show only this driven site',
      unfocus: 'Click again to show all driven sites',
    },
    onChange: refs => { if (!applying) onChange(refs) },
  })
  return {
    apply(refs) {
      applying = true
      try { picker.applyConfig(refs) } finally { applying = false }
    },
    refresh() {
      picker.refresh()
      add.disabled = clear.disabled = !canEdit()
      glow.disabled = false
    },
  }
}
