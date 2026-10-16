/** Part-only organization controls. Placement records remain explicit and ordered. */
import { canonicalSelection } from '../scene/selection_model.js'
import { groupSelectionMembers as groupMembersFromSelection } from '../scene/part_group_selection.js'
import { hasOrganization } from '../scene/part_group_display.js'
import { STAPLE_PALETTE } from '../scene/helix_renderer/palette.js'
import { initClusterStylePopover } from './cluster_style_popover.js'
import { showToast } from './toast.js'
import { el } from './primitives/dom.js'

// Deployment decision, deliberately not a preference, URL, environment or UI switch.
export const GROUP_ORGANIZATION_CONVERSION_ENABLED = false

// Keep the panel's public helper name while sharing exact membership semantics
// with context-menu grouping, including refusal of unsupported mixed selectors.
export { groupMembersFromSelection }

const palette = index => '#' + STAPLE_PALETTE[index % STAPLE_PALETTE.length].toString(16).padStart(6, '0')
const count = record => record.domain_ids?.length ? `${record.domain_ids.length}d` : `${record.helix_ids?.length ?? 0}h`
const button = (label, text, click, title = label) => el('button', { text,
  className: 'btn btn--sm', attrs: { 'aria-label': label, title },
  on: { click: event => { event.stopPropagation(); click(event) } } })

export function createPartGroupPanel({ store, container, api, onGroupClick, onClusterClick,
  onGroupVisibilityChange, onGroupStylePreview }) {
  let enabled = false, disposed = false, designId = null, epoch = 0, busy = 0
  let popover = null, styleContext = null, styleRequest = 0
  const hidden = new Set()
  const context = () => ({ id: store.getState().currentDesign?.id, epoch })
  const current = token => !disposed && enabled && token.epoch === epoch
    && token.id === store.getState().currentDesign?.id && !store.getState().assemblyActive
    && hasOrganization(store.getState().currentDesign)
  const closeStyle = () => {
    styleContext = null
    const old = popover; popover = null
    old?.destroy() // Invalidating context first prevents close from submitting stale work.
  }
  const reset = () => { epoch++; closeStyle(); hidden.clear() }
  window.addEventListener('nadoc:document-reset', reset)

  async function command(kind, inputs, token = context()) {
    if (!current(token)) return null
    busy++
    try {
      const result = await api.groupOrganizationCommand(kind, inputs)
      if (!current(token)) return null
      if (!result) throw new Error(store.getState().lastError?.message ?? 'The operation was cancelled, superseded or refused.')
      return result
    } catch (error) {
      if (current(token)) showToast(`Could not edit group: ${error.message}`, { severity: 'error' })
      return null
    } finally { busy--; if (current(token)) render() }
  }

  function members() {
    return groupMembersFromSelection(store.getState().currentDesign, canonicalSelection(store.getState()).items)
  }
  function canCreate() {
    return enabled && !busy && canonicalSelection(store.getState()).items.some(ref => ['strand', 'domain'].includes(ref.kind))
  }
  async function createFromSelection() {
    if (!enabled || busy) return
    try {
      const groups = store.getState().currentDesign.group_organization.groups
      await command('group-create', { name: `Group ${groups.length + 1}`, ...members() })
    } catch (error) { showToast(error.message, { severity: 'error' }) }
  }

  function style(group, index, anchor) {
    // A deliberate switch flushes the old control while it still owns its context.
    popover?.close(); closeStyle()
    const token = context(), owner = { ...token, groupId: group.id }
    styleContext = owner
    const valid = () => styleContext === owner && current(token)
      && store.getState().currentDesign.group_organization.groups.some(item => item.id === group.id)
    popover = initClusterStylePopover({
      onPreview: (id, patch, values) => { if (valid()) onGroupStylePreview?.(id, patch, values) },
      onCommit: async (id, patch) => {
        if (!valid()) return
        const request = ++styleRequest
        const fields = { ...patch, ...(patch.color === '' ? { color: null } : {}) }
        const result = await command('group-update', { group_id: id, fields }, token)
        if (!result && valid() && request === styleRequest) {
          const actual = store.getState().currentDesign.group_organization.groups.find(item => item.id === id)
          const values = { color: actual.color, opacity: actual.opacity }
          onGroupStylePreview?.(id, values, values)
          closeStyle()
        }
      },
    })
    popover.openFor(group.id, anchor, { color: group.color ?? palette(index), opacity: group.opacity })
  }

  function rename(row, label, group) {
    const token = context()
    const input = el('input', { attrs: { 'aria-label': 'Group name', maxlength: 512 }, on: {
      keydown: event => {
        event.stopPropagation()
        if (event.key === 'Escape') { event.preventDefault(); render() }
        if (event.key === 'Enter') { event.preventDefault(); void save() }
      },
      click: event => event.stopPropagation(),
    } })
    input.value = group.name
    const save = async () => {
      if (input.disabled || !current(token)) return
      input.disabled = true
      await command('group-update', { group_id: group.id, fields: { name: input.value } }, token)
    }
    label.replaceWith(input)
    row.append(button('Save group name', 'Save', save))
    input.focus(); input.select()
  }

  function groupRow(group, index, selected) {
    const row = el('div', { className: 'part-group-row', dataset: { partGroupId: group.id },
      attrs: { 'aria-selected': String(selected.has(group.id)), tabindex: 0 },
      on: { click: event => onGroupClick?.({ id: group.id, additive: event.ctrlKey || event.metaKey || event.shiftKey }),
        keydown: event => { if (event.target === row && event.key === 'Enter') { event.preventDefault(); onGroupClick?.({ id: group.id, additive: event.ctrlKey || event.metaKey || event.shiftKey }) } } } })
    row.style.cssText = `display:flex;align-items:center;gap:5px;flex-wrap:wrap;padding:5px 3px;border-radius:4px;${selected.has(group.id) ? 'background:#1c3a2a' : ''}`
    const label = el('span', { text: group.name || '(unnamed group)' })
    label.style.cssText = 'flex:1;min-width:70px;overflow-wrap:anywhere'
    const badge = el('span', { text: `${group.is_default ? '◆ ' : ''}${count(group)}` })
    const swatch = button('Edit group style', '●', () => style(group, index, swatch), 'Colour and opacity')
    swatch.style.color = group.color ?? palette(index)
    swatch.style.opacity = String(Math.max(.25, group.opacity ?? 1))
    const show = hidden.has(group.id)
    const visibility = button(show ? 'Show group' : 'Hide group', show ? 'Show' : 'Hide', () => {
      const hide = !hidden.has(group.id)
      if (hide) hidden.add(group.id); else hidden.delete(group.id)
      onGroupVisibilityChange?.(group.id, hide)
      render()
    }, show ? 'Show group and its current members' : 'Hide group, including future members')
    const edit = button('Rename group', 'Rename', () => rename(row, label, group))
    const membership = button('Use selection as group members', 'Use selection', async () => {
      try { await command('group-update', { group_id: group.id, fields: members() }) }
      catch (error) { showToast(error.message, { severity: 'error' }) }
    }, 'Replace group membership with the selected strands and domains')
    membership.disabled = !canCreate()
    const dissolve = button('Dissolve group', 'Dissolve', async () => {
      const token = context(), result = await command('group-dissolve', { group_ids: [group.id] }, token)
      if (result && current(token) && !store.getState().currentDesign.group_organization.groups.some(item => item.id === group.id)) {
        // The missing group's hide rule is dormant until undo restores its ID;
        // other base and placement visibility rules retain their own meaning.
        hidden.delete(group.id); render()
      }
    }, 'Dissolve group — keep members and all placement records')
    for (const item of [swatch, edit, dissolve]) item.disabled = busy > 0
    row.append(label, badge, swatch, visibility, edit, membership, dissolve)
    return row
  }

  function render() {
    if (disposed || !enabled) return
    const state = store.getState(), design = state.currentDesign
    if (!hasOrganization(design) || state.assemblyActive) return
    if (design.id !== designId) { reset(); designId = design.id }
    const groups = design.group_organization.groups
    if (styleContext && !groups.some(group => group.id === styleContext.groupId)) closeStyle()
    const selected = new Set(canonicalSelection(state).items.filter(ref => ref.kind === 'part_group').map(ref => ref.id))
    const groupSection = el('section', { attrs: { 'aria-label': 'Groups' }, children: [el('h3', { text: 'Groups' })] })
    if (!groups.length) groupSection.append(el('p', { text: 'No groups. Select strands or domains to create one.' }))
    groups.forEach((group, index) => groupSection.append(groupRow(group, index, selected)))
    const placementSection = el('section', { attrs: { 'aria-label': 'Placements' }, children: [el('h3', { text: 'Placements' }),
      el('p', { text: 'Select an existing placement to Move/Rotate. Grouping does not create or change a placement.' })] })
    const selectedPlacements = new Set(canonicalSelection(state).items.filter(ref => ref.kind === 'cluster').map(ref => ref.id))
    for (const placement of design.cluster_transforms ?? []) {
      const row = el('div', { dataset: { placementId: placement.id }, attrs: { tabindex: 0,
        'aria-selected': String(selectedPlacements.has(placement.id) || state.activeClusterId === placement.id),
        title: `Placement ${placement.id}` }, children: [el('span', { text: placement.name || placement.id }),
        el('span', { text: count(placement) }), ...(placement.overhang_duplex_driver_id
          ? [el('span', { text: 'Duplex', attrs: { title: 'Rotation-point controls are in Move/Rotate' } })] : [])],
      on: { click: event => onClusterClick?.(placement.id, { additive: event.ctrlKey || event.metaKey || event.shiftKey }),
        keydown: event => { if (event.target === row && event.key === 'Enter') { event.preventDefault(); onClusterClick?.(placement.id, { additive: event.ctrlKey || event.metaKey || event.shiftKey }) } } } })
      row.style.cssText = 'display:flex;gap:6px;padding:5px 3px;cursor:pointer;overflow-wrap:anywhere'
      placementSection.append(row)
    }
    container.replaceChildren(groupSection, placementSection)
  }

  return {
    render, canCreate, createFromSelection,
    setActive(value) {
      if (enabled && !value) { reset(); designId = null }
      enabled = value
      if (enabled) render()
    },
    syncVisibility(ids) { hidden.clear(); for (const id of ids ?? []) hidden.add(id); render() },
    resetVisibility() { hidden.clear(); render() },
    destroy() { disposed = true; reset(); window.removeEventListener('nadoc:document-reset', reset) },
  }
}
