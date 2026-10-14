import { showConfirm } from './primitives/confirm.js'

/** Collapsed connector sections allocate their rows only on first opening.
 * Authored-input changes replace the section; display-only snapshots retain it.
 */
export function createAssemblyConnectorSection(inst, joints, { api, confirm = showConfirm }) {
  const connectors = inst.interface_points ?? []

  const section = document.createElement('div')
  section.style.cssText = 'padding:0 6px 4px 26px'

  const headerRow = document.createElement('div')
  headerRow.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;padding:2px 0'

  const arrowSpan = document.createElement('span')
  arrowSpan.textContent = '▶'
  arrowSpan.style.cssText = 'font-size:8px;color:#484f58;flex-shrink:0'

  const titleSpan = document.createElement('span')
  titleSpan.style.cssText = 'font-size:var(--text-xs);color:#6e7681'
  titleSpan.textContent = `Connectors (${connectors.length})`

  headerRow.append(arrowSpan, titleSpan)

  const listEl = document.createElement('div')
  listEl.style.display = 'none'
  let _expanded = false
  let built = false

  headerRow.addEventListener('click', () => {
    _expanded = !_expanded
    if (_expanded && !built) {
      buildRows()
      built = true
    }
    listEl.style.display = _expanded ? '' : 'none'
    arrowSpan.textContent = _expanded ? '▼' : '▶'
  })

  function buildRows() {
    for (const ip of connectors) {
      const usedCount = joints.filter(j =>
        (j.instance_b_id === inst.id && j.connector_b_label === ip.label) ||
        (j.instance_a_id === inst.id && j.connector_a_label === ip.label),
      ).length

      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:center;gap:4px;padding:2px 0 2px 8px'

      const lbl = document.createElement('span')
      lbl.textContent = ip.label
      lbl.style.cssText = 'flex:1;font-size:var(--text-xs);color:#8b949e'

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete connector'
      delBtn.style.cssText = [
        'background:none;border:none;cursor:pointer;padding:0 2px',
        'color:#6e7681;font-size:12px;line-height:1',
      ].join(';')
      delBtn.addEventListener('pointerenter', () => { delBtn.style.color = '#f85149' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.color = '#6e7681' })
      delBtn.addEventListener('click', async (e) => {
        e.stopPropagation()
        if (usedCount > 0) {
          const ok = await confirm({
            title: 'Delete connector in use',
            message: `Connector "${ip.label}" is used in ${usedCount} mate(s). Delete anyway?`,
            danger: true,
            confirmLabel: 'Delete',
          })
          if (!ok) return
        }
        await api.deleteInstanceConnector(inst.id, ip.label)
      })

      row.append(lbl, delBtn)
      listEl.appendChild(row)
    }

    if (!connectors.length) {
      const empty = document.createElement('div')
      empty.textContent = 'No connectors defined'
      empty.style.cssText = 'font-size:var(--text-xs);color:#484f58;padding:2px 0 2px 8px'
      listEl.appendChild(empty)
    }
  }

  section.append(headerRow, listEl)
  return section
}
