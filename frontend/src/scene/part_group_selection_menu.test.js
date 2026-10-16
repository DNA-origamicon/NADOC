import { afterEach, expect, it, vi } from 'vitest'
import { appendPartGroupMembershipMenu, appendPartGroupActions } from './part_group_selection_menu.js'
import { groupDesign } from '../test-helpers/part_groups.js'

afterEach(() => { document.body.innerHTML = '' })
const flush = async () => { await Promise.resolve(); await Promise.resolve() }
function setup(command = vi.fn().mockResolvedValue({ design: {} })) {
  let design = groupDesign()
  const menu = document.createElement('div'); document.body.append(menu)
  const accepted = vi.fn(), options = { getDesign: () => design, command, onAccepted: accepted,
    refs: [{ kind: 'domain', strandId: 's', domainIndex: 1 }] }
  return { menu, options, command, accepted, setDesign: value => { design = value } }
}
it('creates an explicit organization with selected domains and no placement payload', async () => {
  const d = setup(); appendPartGroupMembershipMenu(d.menu, d.options)
  d.menu.querySelector('[data-group-create]').click(); await flush()
  expect(d.command).toHaveBeenCalledExactlyOnceWith('group-create', {
    name: 'Group 4', helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 1 }], color: null, opacity: 1,
  })
  expect(d.accepted).toHaveBeenCalledOnce()
})
it('replaces membership only after an explicit existing-group choice and preserves style', async () => {
  const d = setup(); appendPartGroupMembershipMenu(d.menu, d.options)
  d.menu.querySelector('[data-group-target]').value = 'whole'
  d.menu.querySelector('[data-group-replace]').click(); await flush()
  expect(d.command).toHaveBeenCalledExactlyOnceWith('group-update', { group_id: 'whole', fields: {
    name: 'Whole', color: null, opacity: 1, helix_ids: ['h'], domain_ids: [{ strand_id: 's', domain_index: 1 }],
  } })
})
it.each([null, 'throw'])('keeps the menu and selection available on %s refusal', async result => {
  const command = result === 'throw' ? vi.fn().mockRejectedValue(new Error('Stale group')) : vi.fn().mockResolvedValue(null)
  const d = setup(command); appendPartGroupMembershipMenu(d.menu, d.options)
  d.menu.querySelector('[data-group-create]').click(); await flush()
  expect(d.accepted).not.toHaveBeenCalled()
  expect(d.menu.querySelector('[role=alert]').textContent).toBeTruthy()
  expect(d.menu.querySelector('[data-group-create]').disabled).toBe(false)
})
it('refuses a stale menu before issuing a command to a replacement document', async () => {
  const d = setup(); appendPartGroupMembershipMenu(d.menu, d.options)
  d.setDesign({ ...groupDesign(), id: 'replacement' })
  d.menu.querySelector('[data-group-create]').click(); await flush()
  expect(d.command).not.toHaveBeenCalled()
  expect(d.accepted).not.toHaveBeenCalled()
})
it('renames/dissolves only the organizational namespace and hides with typed IDs', async () => {
  const d = setup(), hide = vi.fn()
  appendPartGroupActions(d.menu, { ...d.options, id: 'same', onHide: hide })
  d.menu.querySelector('[data-group-name]').value = 'Retargeted'
  d.menu.querySelector('[data-group-rename]').click(); await flush()
  expect(d.command).toHaveBeenLastCalledWith('group-update', { group_id: 'same', fields: { name: 'Retargeted' } })
  d.menu.querySelector('[data-group-hide]').click()
  expect(hide).toHaveBeenCalledWith({ partGroupIds: ['same'] })
  d.menu.querySelector('[data-group-dissolve]').click(); await flush()
  expect(d.command).toHaveBeenLastCalledWith('group-dissolve', { group_ids: ['same'] })
})
