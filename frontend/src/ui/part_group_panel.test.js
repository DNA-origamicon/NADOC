// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { initClusterPanel } from './cluster_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { showToast } from './toast.js'
import { groupMembersFromSelection, GROUP_ORGANIZATION_CONVERSION_ENABLED } from './part_group_panel.js'

vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
const group = (id, name, extra = {}) => ({ id, name, helix_ids: ['h1'], domain_ids: [],
  color: null, opacity: 1, is_default: false, auto_created: false, ...extra })
const design = () => ({ id: 'part', helices: [{ id: 'h1' }, { id: 'h2' }],
  strands: [{ id: 's', domains: [{ helix_id: 'h1' }, { helix_id: 'h2' }] }],
  cluster_transforms: [group('same', 'First placement', { translation: [7, 0, 0] }), group('p2', 'Second placement')],
  group_organization: { version: 1, groups: [group('same', 'Organization'), group('empty', 'Empty', { helix_ids: [] })] },
})
let store, api, panel, groupClick, placementClick, visibility, preview
const groups = () => [...document.querySelectorAll('[data-part-group-id]')]
const placements = () => [...document.querySelectorAll('[data-placement-id]')]
const button = (row, name) => [...row.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === name)
// The legacy panel retains its own hidden popover; exercise the active group editor.
const styleColor = () => [...document.querySelectorAll('.cluster-style-popover')]
  .find(popover => popover.style.display !== 'none')?.querySelector('input[type=color]')
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
function mount() {
  document.body.innerHTML = '<div id="cluster-panel"><h2 id="cluster-panel-heading"><span>Movable Clusters</span><span id="cluster-panel-arrow"></span></h2><div id="cluster-panel-body"><div id="cluster-list"></div><button id="cluster-repair-btn">Cluster Unassigned Components</button><button id="cluster-new-btn">New Cluster</button></div></div>'
  panel = initClusterPanel(store, { api, onClusterClick: placementClick, onGroupClick: groupClick,
    onGroupVisibilityChange: visibility, onGroupStylePreview: preview })
  store.setState({ currentDesign: store.getState().currentDesign })
}
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks()
  store = createMockStore({ currentDesign: design(), selection: { items: [] }, assemblyActive: false })
  api = { groupOrganizationCommand: vi.fn(async () => null), createCluster: vi.fn(), patchCluster: vi.fn(), deleteCluster: vi.fn() }
  groupClick = vi.fn(); placementClick = vi.fn(); visibility = vi.fn(); preview = vi.fn()
  mount()
})
afterEach(() => { panel?.destroy(); document.body.innerHTML = ''; localStorage.clear(); vi.useRealTimers(); vi.restoreAllMocks() })

it('shows separate organization and ordered explicit placements, even with identical IDs', () => {
  expect(document.querySelector('#cluster-list').textContent).toContain('Groups')
  expect(document.querySelector('#cluster-list').textContent).toContain('Placements')
  expect(groups().map(row => row.dataset.partGroupId)).toEqual(['same', 'empty'])
  expect(placements().map(row => row.dataset.placementId)).toEqual(['same', 'p2'])
  expect(groups()[1].textContent).toContain('0h')
  expect(placements()[0].textContent).toContain('First placement')
  expect(placements()[0].querySelectorAll('input,button')).toHaveLength(0)
  expect(document.querySelector('#cluster-repair-btn').hidden).toBe(true)
})

it('routes group and placement clicks through different callbacks, preserving modifiers', () => {
  groups()[0].dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: true }))
  expect(groupClick).toHaveBeenCalledExactlyOnceWith({ id: 'same', additive: true })
  expect(placementClick).not.toHaveBeenCalled()
  placements()[0].dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }))
  expect(placementClick).toHaveBeenCalledExactlyOnceWith('same', { additive: true })
})

it('highlights only the selected identity namespace', () => {
  store.setState({ selection: { items: [{ kind: 'part_group', id: 'same' }] } })
  expect(groups()[0].getAttribute('aria-selected')).toBe('true')
  expect(placements()[0].getAttribute('aria-selected')).toBe('false')
  store.setState({ selection: { items: [{ kind: 'cluster', id: 'same' }] } })
  expect(groups()[0].getAttribute('aria-selected')).toBe('false')
  expect(placements()[0].getAttribute('aria-selected')).toBe('true')
})

it('derives owned membership values without aliasing source or selection', () => {
  const source = design(), refs = [{ kind: 'domain', strandId: 's', domainIndex: 1 }]
  const before = JSON.stringify({ source, refs }), members = groupMembersFromSelection(source, refs)
  expect(members).toEqual({ helix_ids: ['h2'], domain_ids: [{ strand_id: 's', domain_index: 1 }] })
  members.domain_ids[0].strand_id = 'changed'; members.helix_ids.push('another')
  expect(JSON.stringify({ source, refs })).toBe(before)
})

it('creates exact selected domains, including a whole selected strand, without changing placements', async () => {
  store.setState({ selection: { items: [{ kind: 'strand', id: 's' }, { kind: 'domain', strandId: 's', domainIndex: 1 }] } })
  const before = JSON.stringify(store.getState().currentDesign.cluster_transforms)
  document.querySelector('#cluster-new-btn').click(); await flush()
  expect(api.groupOrganizationCommand).toHaveBeenCalledExactlyOnceWith('group-create', {
    name: 'Group 3', helix_ids: ['h1', 'h2'], domain_ids: [{ strand_id: 's', domain_index: 0 }, { strand_id: 's', domain_index: 1 }],
  })
  expect(api.createCluster).not.toHaveBeenCalled()
  expect(JSON.stringify(store.getState().currentDesign.cluster_transforms)).toBe(before)
  expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/could not/i), expect.anything())
})

it('replaces one group membership from current selection without borrowing the placement ID', async () => {
  store.setState({ selection: { items: [{ kind: 'domain', strandId: 's', domainIndex: 1 }] } })
  button(groups()[0], 'Use selection as group members').click(); await flush()
  expect(api.groupOrganizationCommand).toHaveBeenCalledExactlyOnceWith('group-update', {
    group_id: 'same', fields: { helix_ids: ['h2'], domain_ids: [{ strand_id: 's', domain_index: 1 }] },
  })
  expect(api.patchCluster).not.toHaveBeenCalled()
})

it('does not silently omit a stale selected domain', async () => {
  store.setState({ selection: { items: [{ kind: 'domain', strandId: 's', domainIndex: 9 }] } })
  document.querySelector('#cluster-new-btn').click(); await flush()
  expect(api.groupOrganizationCommand).not.toHaveBeenCalled()
  expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/no longer exists/i), expect.anything())
})

it.each(['null', 'throw'])('preserves the old name and reports a %s rename failure', async failure => {
  if (failure === 'throw') api.groupOrganizationCommand.mockRejectedValue(new Error('Refused'))
  button(groups()[0], 'Rename group').click()
  const input = groups()[0].querySelector('input')
  input.value = 'New name'; input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flush()
  expect(api.groupOrganizationCommand).toHaveBeenCalledWith('group-update', { group_id: 'same', fields: { name: 'New name' } })
  expect(groups()[0].textContent).toContain('Organization')
  expect(groups()[0].textContent).not.toContain('New name')
  expect(showToast).toHaveBeenCalled()
})

it('adopts a server rename and keeps the independent placement name', async () => {
  api.groupOrganizationCommand.mockImplementation(async () => {
    const next = design(); next.group_organization.groups[0].name = 'Accepted'
    store.setState({ currentDesign: next }); return { design: next }
  })
  button(groups()[0], 'Rename group').click(); const input = groups()[0].querySelector('input')
  input.value = 'Accepted'; input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flush()
  expect(groups()[0].textContent).toContain('Accepted')
  expect(placements()[0].textContent).toContain('First placement')
})

it('commits group style through the organization endpoint and restores preview after refusal', async () => {
  vi.useFakeTimers()
  button(groups()[0], 'Edit group style').click()
  const color = styleColor()
  color.value = '#123456'; color.dispatchEvent(new Event('input')); color.dispatchEvent(new Event('change'))
  vi.advanceTimersByTime(300); await flush()
  expect(api.groupOrganizationCommand).toHaveBeenCalledWith('group-update', { group_id: 'same', fields: { color: '#123456' } })
  expect(api.patchCluster).not.toHaveBeenCalled()
  expect(preview).toHaveBeenLastCalledWith('same', { color: null, opacity: 1 }, { color: null, opacity: 1 })
})

it('hides current group members without sharing placement visibility or unhiding on dissolve', async () => {
  button(groups()[0], 'Hide group').click()
  expect(visibility).toHaveBeenCalledExactlyOnceWith('same', true)
  expect(button(groups()[0], 'Show group').title).toContain('current members')
  button(groups()[0], 'Dissolve group').click(); await flush()
  expect(api.groupOrganizationCommand).toHaveBeenCalledWith('group-dissolve', { group_ids: ['same'] })
  expect(button(groups()[0], 'Show group')).toBeDefined()
  api.groupOrganizationCommand.mockImplementation(async () => {
    const next = design(); next.group_organization.groups.shift(); store.setState({ currentDesign: next }); return { design: next }
  })
  button(groups()[0], 'Dissolve group').click(); await flush()
  expect(visibility).toHaveBeenCalledTimes(1)
  expect(placements()[0].dataset.placementId).toBe('same')
})

it('reflects derived group visibility independently of placement hidden IDs', () => {
  panel.syncGroupVisibility(['same'])
  expect(button(groups()[0], 'Show group')).toBeDefined()
  panel.syncVisibility(['same'])
  panel.syncGroupVisibility([])
  expect(button(groups()[0], 'Hide group')).toBeDefined()
  expect(visibility).not.toHaveBeenCalled()
})

it('does not prune a surviving group for a non-null superseded response', async () => {
  button(groups()[0], 'Hide group').click()
  api.groupOrganizationCommand.mockResolvedValue({ design: { ...design(), group_organization: { version: 1, groups: [] } } })
  button(groups()[0], 'Dissolve group').click(); await flush()
  expect(button(groups()[0], 'Show group')).toBeDefined()
  expect(visibility).toHaveBeenCalledTimes(1)
})

it('does not send delayed style work into another document or after teardown', async () => {
  vi.useFakeTimers(); button(groups()[0], 'Edit group style').click()
  const color = styleColor()
  color.value = '#123456'; color.dispatchEvent(new Event('change'))
  store.setState({ currentDesign: { ...design(), id: 'other' } }); panel.destroy(); panel = null
  vi.runAllTimers(); await flush()
  expect(api.groupOrganizationCommand).not.toHaveBeenCalled()
})

it('keeps conversion unavailable by default and retains the legacy list and API', async () => {
  expect(GROUP_ORGANIZATION_CONVERSION_ENABLED).toBe(false)
  const legacy = design(); delete legacy.group_organization; store.setState({ currentDesign: legacy })
  expect(groups()).toHaveLength(0); expect(placements()).toHaveLength(0)
  expect(document.querySelector('[data-action="organize-groups"]')).toBeNull()
  expect(document.querySelector('#cluster-list').textContent).toContain('First placement')
  expect(document.querySelector('#cluster-repair-btn').hidden).toBe(false)
})

it('keeps the assembly view independent of active part groups', () => {
  panel.setAssemblyMode([])
  expect(groups()).toHaveLength(0); expect(placements()).toHaveLength(0)
  expect(document.querySelector('#cluster-new-btn').disabled).toBe(true)
  panel.clearAssemblyMode()
  expect(groups()).toHaveLength(2); expect(placements()).toHaveLength(2)
})
