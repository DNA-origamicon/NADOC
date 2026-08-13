/**
 * Strand groups panel ("Staple Groups") — collapsible sidebar list of named,
 * colored strand groups. Each row: name (inline-editable), color picker, strand
 * count, delete. A "New" button creates a group from the current multi-selection;
 * a "From colors" button auto-buckets every staple by its effective color.
 * Clicking a row multi-selects that group's (still-live) strands.
 *
 * Stateful: owns DOM + a store subscription, and mutates store.strandGroups
 * (with pushGroupUndo before each change). So it's a factory — pass dependencies
 * in. The pure cores (effectiveStrandColors / groupStrandsByColor /
 * trimGroupsRemovingStrands / selectableGroupStrandIds) are exported +
 * unit-tested in strand_groups_panel.test.js; the DOM build stays here.
 *
 * Extracted verbatim from main.js's `_initGroupsPanel` IIFE.
 *
 * @param {object} deps
 * @param {object} deps.store            — Zustand-style store (getState/setState/subscribe)
 * @param {object} deps.selectionManager — needs setMultiHighlight(ids)
 * @returns {{ rebuild: Function }}
 */
import { showToast } from './toast.js'
import { pushGroupUndo } from '../state/store.js'
import { buildStapleColorMap } from '../scene/helix_renderer.js'
import { hexFromInt } from '../scene/color_util.js'
import { selectedStrandIds } from '../scene/selection_model.js'

/**
 * Pure: base per-strand colors merged with group color overrides.
 *
 * Each group's `color` (a `#rrggbb` string) is parsed to an int and applied to
 * every strand id in that group, overriding any base color.
 *
 * @param {Object<string,number>} strandColors — base strandId → int color
 * @param {object[]} strandGroups               — [{ color, strandIds }]
 * @returns {Object<string,number>}
 */
export function effectiveStrandColors(strandColors, strandGroups) {
  const effective = { ...(strandColors ?? {}) }
  for (const group of strandGroups ?? []) {
    if (!group.color) continue
    const hex = parseInt(group.color.replace('#', ''), 16)
    for (const sid of group.strandIds ?? []) effective[sid] = hex
  }
  return effective
}

/**
 * Pure: bucket non-scaffold strands by resolved color into `[{ color, strandIds }]`.
 *
 * Color resolution per strand: effectiveColors override → strand.color →
 * palette fallback. Strands with no resolvable color are skipped. The returned
 * `color` is the lowercase hex string key. Caller assigns ids/names.
 *
 * @param {object[]} strands         — design strands
 * @param {Object<string,number>} effectiveColors
 * @param {Map<string,number>} palette — staple color map fallback
 * @returns {{color: string, strandIds: string[]}[]}
 */
export function groupStrandsByColor(strands, effectiveColors, palette) {
  const byColor = new Map()
  for (const strand of strands ?? []) {
    if (strand.strand_type === 'scaffold') continue
    let color = effectiveColors[strand.id]
    if (color == null && strand.color) color = parseInt(strand.color.replace('#', ''), 16)
    if (color == null) color = palette?.get(strand.id)
    if (color == null) continue
    const key = hexFromInt(color).toLowerCase()
    if (!byColor.has(key)) byColor.set(key, [])
    byColor.get(key).push(strand.id)
  }
  return [...byColor.entries()].map(([color, strandIds]) => ({ color, strandIds }))
}

/**
 * Pure: remove the given strand ids from every group's `strandIds`.
 *
 * Returns the input array unchanged when there is nothing to remove (so a no-op
 * "New empty group" doesn't churn the groups array identity).
 *
 * @param {object[]} strandGroups
 * @param {string[]} idsToRemove
 * @returns {object[]}
 */
export function trimGroupsRemovingStrands(strandGroups, idsToRemove) {
  if (!idsToRemove?.length) return strandGroups
  return strandGroups.map(g => ({ ...g, strandIds: g.strandIds.filter(s => !idsToRemove.includes(s)) }))
}

/**
 * Pure: of a group's strands, those that still exist in the design.
 *
 * @param {object} group  — { strandIds }
 * @param {object} design — Design with .strands
 * @returns {string[]}
 */
export function selectableGroupStrandIds(group, design) {
  const designStrandIds = new Set((design?.strands ?? []).map(s => s.id))
  return (group?.strandIds ?? []).filter(id => designStrandIds.has(id))
}

export function initStrandGroupsPanel({ store, selectionManager }) {
  const panel     = document.getElementById('groups-panel')
  const list      = document.getElementById('groups-list')
  const heading   = document.getElementById('groups-panel-heading')
  const arrow     = document.getElementById('groups-panel-arrow')
  const newBtn    = document.getElementById('groups-new-btn')
  const colorsBtn = document.getElementById('groups-colors-btn')
  if (!panel || !list) return { rebuild: () => {} }

  let _collapsed = false

  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    list.style.display   = _collapsed ? 'none' : ''
    newBtn.style.display = _collapsed ? 'none' : ''
    if (colorsBtn) colorsBtn.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
  })

  const _iStyle  = 'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
                   'color:#c9d1d9;padding:2px 5px;font-family:var(--font-ui);font-size:11px;'
  const _editStyle = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _saveStyle = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _delStyle  = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'

  function _rebuildPanel(groups) {
    list.innerHTML = ''
    for (const group of groups) {
      const row = document.createElement('div')
      row.style.cssText = 'display:grid;grid-template-columns:1fr auto auto auto auto;gap:4px;margin-bottom:6px;align-items:center;cursor:pointer'
      row.title = 'Select strands in this group'
      row.addEventListener('click', e => {
        if (e.target.closest('button,input')) return
        const ids = selectableGroupStrandIds(group, store.getState().currentDesign)
        if (!ids.length) {
          showToast('This group has no strands to select')
          return
        }
        selectionManager.setMultiHighlight(ids)
      })

      // Name label
      const nameSpan = document.createElement('span')
      nameSpan.textContent = group.name
      nameSpan.style.cssText = 'font-size:11px;color:#c9d1d9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'

      // Edit / Save button — use only onclick so exactly one handler is active.
      const editBtn = document.createElement('button')
      editBtn.textContent = '✎'
      editBtn.title = 'Rename group'
      editBtn.style.cssText = _editStyle
      editBtn.addEventListener('pointerenter', () => {
        editBtn.style.background = editBtn.textContent === '✓' ? '#1f3d2a' : '#2d333b'
        editBtn.style.color      = editBtn.textContent === '✓' ? '#57d05a' : '#c9d1d9'
      })
      editBtn.addEventListener('pointerleave', () => {
        editBtn.style.cssText = editBtn.textContent === '✓' ? _saveStyle : _editStyle
      })

      function _enterGroupEdit() {
        const nameInput = document.createElement('input')
        nameInput.type = 'text'
        nameInput.value = group.name
        nameInput.style.cssText = _iStyle + 'width:100%;box-sizing:border-box'
        nameSpan.replaceWith(nameInput)
        nameInput.focus(); nameInput.select()
        editBtn.textContent = '✓'
        editBtn.title = 'Save name'
        editBtn.style.cssText = _saveStyle

        function _save() {
          const newName = nameInput.value.trim() || group.name
          nameInput.replaceWith(nameSpan)
          nameSpan.textContent = newName
          editBtn.textContent = '✎'
          editBtn.title = 'Rename group'
          editBtn.style.cssText = _editStyle
          editBtn.onclick = _enterGroupEdit
          pushGroupUndo()
          const gs = store.getState().strandGroups
          store.setState({ strandGroups: gs.map(g => g.id === group.id ? { ...g, name: newName } : g) })
        }
        nameInput.addEventListener('keydown', e => {
          if (e.key === 'Enter')  { e.preventDefault(); _save() }
          if (e.key === 'Escape') {
            nameInput.replaceWith(nameSpan)
            editBtn.textContent = '✎'
            editBtn.title = 'Rename group'
            editBtn.style.cssText = _editStyle
            editBtn.onclick = _enterGroupEdit
          }
        })
        editBtn.onclick = _save
      }
      editBtn.onclick = _enterGroupEdit

      // Color picker
      const colorInput = document.createElement('input')
      colorInput.type  = 'color'
      colorInput.value = group.color ?? '#74b9ff'
      colorInput.title = 'Group color'
      colorInput.style.cssText = 'width:28px;height:22px;border:none;background:none;cursor:pointer;padding:0'
      colorInput.addEventListener('change', () => {
        pushGroupUndo()
        const gs = store.getState().strandGroups
        store.setState({ strandGroups: gs.map(g => g.id === group.id ? { ...g, color: colorInput.value } : g) })
      })

      // Strand count badge
      const countEl = document.createElement('span')
      countEl.textContent = `${group.strandIds.length}`
      countEl.title       = `${group.strandIds.length} strand(s)`
      countEl.style.cssText = 'color:#8b949e;font-size:var(--text-xs);min-width:1.5em;text-align:center'

      // Delete button
      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Remove group'
      delBtn.style.cssText = _delStyle
      delBtn.addEventListener('pointerenter', () => { delBtn.style.background = '#3d1c1c'; delBtn.style.color = '#ff6b6b' })
      delBtn.addEventListener('pointerleave', () => { delBtn.style.cssText = _delStyle })
      delBtn.addEventListener('click', () => {
        pushGroupUndo()
        const gs = store.getState().strandGroups
        store.setState({ strandGroups: gs.filter(g => g.id !== group.id) })
      })

      row.appendChild(nameSpan)
      row.appendChild(editBtn)
      row.appendChild(colorInput)
      row.appendChild(countEl)
      row.appendChild(delBtn)
      list.appendChild(row)
    }
  }

  colorsBtn?.addEventListener('click', () => {
    const { currentDesign, currentGeometry, strandColors, strandGroups } = store.getState()
    const strands = currentDesign?.strands ?? []
    if (!strands.length) return

    const effective = effectiveStrandColors(strandColors, strandGroups)
    const palette = currentGeometry ? buildStapleColorMap(currentGeometry, currentDesign) : new Map()

    const groups = groupStrandsByColor(strands, effective, palette).map((g, i) => ({
      id: `grp_color_${Date.now()}_${i}`,
      name: `Group ${i + 1}`,
      color: g.color,
      strandIds: g.strandIds,
    }))
    pushGroupUndo()
    store.setState({ strandGroups: groups })
    showToast(`Created ${groups.length} staple group${groups.length === 1 ? '' : 's'} from colors`)
  })

  newBtn.addEventListener('click', () => {
    pushGroupUndo()
    const state = store.getState()
    const { strandGroups } = state
    const n = strandGroups.length + 1
    const colors = ['#74b9ff', '#6bcb77', '#ff6b6b', '#ffd93d', '#a29bfe', '#55efc4']
    const color = colors[(n - 1) % colors.length]
    const initialIds = selectedStrandIds(state)
    // Remove selected strands from any existing group before adding to the new one.
    const trimmed = trimGroupsRemovingStrands(strandGroups, initialIds)
    store.setState({
      strandGroups: [...trimmed, { id: `grp_${Date.now()}`, name: `Group ${n}`, color, strandIds: initialIds }],
    })
  })

  store.subscribe((newState, prevState) => {
    if (newState.strandGroups === prevState.strandGroups) return
    if (!_collapsed) _rebuildPanel(newState.strandGroups)
  })

  return { rebuild: _rebuildPanel }
}
