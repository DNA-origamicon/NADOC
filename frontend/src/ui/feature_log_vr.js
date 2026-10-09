const clean = value => String(value ?? '').replace(/\s+/g, ' ').trim()

/** A view of the actual desktop log. Never reconstruct operation semantics here. */
export function featureRowPosition(key) {
  if (!/^\d+(?:\.\d+)?$/.test(key)) throw new Error('Invalid feature state')
  const [row, sub] = key.split('.').map(Number)
  return { position: row === 0 ? -2 : row - 1, subPosition: sub ?? null }
}
export function createFeatureLogVR({ list, target, prepare, context, seek, seekConfig }) {
  function snapshot() {
    prepare()
    const state = { ...context() }
    if (list.ownerDocument.querySelector('.modal__overlay')) { state.busy = true;state.status = 'Finish the dialog in the VR desktop panel' }
    const elements = [...list.querySelectorAll('[data-fl-row]')]
    const rows = elements.map((element, index) => {
      const key = element.dataset.flRow
      const clone = element.cloneNode(true)
      clone.querySelectorAll('button,[title*="Fine Routing"]').forEach(el => el.remove())
      const buttons = [...element.querySelectorAll('button')]
      const find = pattern => buttons.find(el => pattern.test(el.title))
      const actions = { edit: find(/^Edit|^Rename/i), revert: find(/^Revert/i), delete: find(/^Delete/i),
        expand: [...element.querySelectorAll('[title]')].find(el => /^(Expand|Collapse) Fine Routing/.test(el.title)) }
      const { position, subPosition } = featureRowPosition(key)
      const active = state.configurations ? index === (state.cursor<0?elements.length-1:state.cursor) : state.cursor === -1 ? index === elements.length - 1
        : position === state.cursor && subPosition === state.subCursor
      return { id: `r:${index}`, key, label: clean(clone.textContent).replace(/^[^\w]*?(?=F\d)/, ''),
        active, enabled: !state.busy, ...Object.fromEntries(Object.entries(actions).map(([name, el]) => [name, !!el && !el.disabled && !state.busy])),
        actions, element }
    })
    if (rows.length && !rows.some(row => row.active)) {
      const fallback = rows.find(row => { const key = featureRowPosition(row.key);return key.position === state.cursor && key.subPosition == null }) ?? rows.at(-1)
      fallback.active = true
    }
    const targets = target.hidden ? [] : [...target.options].map((option, i) => ({ id: `t:${i}`, label: clean(option.textContent), enabled: !state.busy && !target.disabled && !option.disabled, active: option.selected, value: option.value }))
    return { ...state, rows, targets }
  }
  async function activate(id, state = snapshot()) {
    if (id.startsWith('t:')) {
      const option = state.targets.find(t => t.id === id)
      if (!option?.enabled) return
      target.value = option.value;target.dispatchEvent(new Event('change', { bubbles: true }));return
    }
    const match = /^([a-z]+):(\d+)(?::(edit|revert|delete|expand))?$/.exec(id)
    if (!match) return
    const row = state.rows[Number(match[2])]
    if (!row?.enabled) return
    if (match[1] === 'r') {
      if (state.configurations) await seekConfig(Number(match[2]))
      else { const key = featureRowPosition(row.key);await seek(key.position, key.subPosition) }
    } else if (match[1] === 'a' && row[match[3]]) row.actions[match[3]].click()
  }
  return { snapshot, activate }
}
