/** Context actions share the source-bound organization endpoint with the sidebar. */
import { hasOrganization, partGroupById } from './part_group_display.js'
import { groupSelectionMembers } from './part_group_selection.js'

function section(menu, options) {
  const source = options.getDesign()
  if (!hasOrganization(source)) return null
  const box = document.createElement('div'); box.className = 'part-group-menu'
  const label = document.createElement('div'); label.textContent = 'Groups'; label.className = 'ctx-label'
  const error = document.createElement('div'); error.setAttribute('role', 'alert')
  box.append(label, error); menu.append(box)
  let busy = false
  const run = async action => {
    if (busy) return
    busy = true; error.textContent = ''
    const controls = [...box.querySelectorAll('button,input,select')]
    controls.forEach(c => { c.disabled = true })
    try {
      if (options.getDesign() !== source) throw new Error('The document changed. Reopen the group menu.')
      const response = await action(source)
      if (!response) throw new Error('The document changed or the group edit was not accepted.')
      options.onAccepted?.(response)
    } catch (e) { error.textContent = e?.message || 'Group edit failed' }
    finally { busy = false; controls.forEach(c => { c.disabled = false }) }
  }
  const button = (key, text, action) => {
    const b = document.createElement('button'); b.type = 'button'; b.dataset[key] = ''; b.textContent = text
    b.addEventListener('click', () => run(action)); box.append(b); return b
  }
  return { source, box, button, error }
}

export function appendPartGroupMembershipMenu(menu, options) {
  const s = section(menu, options)
  if (!s) return
  const { source, box, button } = s
  const groups = source.group_organization.groups
  button('groupCreate', 'New group from selection', () => options.command('group-create', {
    name: `Group ${groups.length + 1}`, ...groupSelectionMembers(source, options.refs), color: null, opacity: 1,
  }))
  if (!groups.length) return
  const target = document.createElement('select'); target.dataset.groupTarget = ''; target.setAttribute('aria-label', 'Group to replace members')
  for (const group of groups) { const o = document.createElement('option'); o.value = group.id; o.textContent = group.name; target.append(o) }
  box.append(target)
  button('groupReplace', 'Replace members with selection', () => {
    const group = partGroupById(source, target.value)
    if (!group) throw new Error('Selected group no longer exists')
    return options.command('group-update', { group_id: group.id, fields: {
      name: group.name, color: group.color ?? null, opacity: group.opacity ?? 1,
      ...groupSelectionMembers(source, options.refs),
    } })
  })
}

export function appendPartGroupActions(menu, options) {
  const s = section(menu, options)
  if (!s) return
  const group = partGroupById(s.source, options.id)
  if (!group) { s.error.textContent = 'Selected group no longer exists'; return }
  const name = document.createElement('input'); name.dataset.groupName = ''; name.value = group.name
  name.maxLength = 512; name.setAttribute('aria-label', 'Group name'); s.box.append(name)
  s.button('groupRename', 'Rename group', () => options.command('group-update', { group_id: group.id, fields: { name: name.value.trim() } }))
  if (options.onHide) {
    const hide = document.createElement('button'); hide.type = 'button'; hide.dataset.groupHide = ''; hide.textContent = 'Hide group'
    hide.addEventListener('click', () => options.onHide({ partGroupIds: [group.id] })); s.box.append(hide)
  }
  s.button('groupDissolve', 'Dissolve group', () => options.command('group-dissolve', { group_ids: [group.id] }))
}
