import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initAssemblyPanel } from './assembly_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { showConfirm } from './primitives/confirm.js'

vi.mock('./file_browser.js', () => ({ openFileBrowser: vi.fn() }))
vi.mock('./primitives/confirm.js', () => ({ showConfirm: vi.fn() }))

function sourceVersion(instance, version = 'f:/part.nadoc:1:') {
  Object.defineProperty(instance, 'geometrySourceKey', { value: version, configurable: true })
  return instance
}
function assembly() {
  return {
    id: 'assembly', metadata: { name: 'Assembly' },
    instances: ['a', 'b'].map(id => sourceVersion({ id, name: `Part ${id}`, visible: true,
      representation: 'cylinders', source: { type: 'file', path: 'part.nadoc' },
      transform: { translation: [0, 0, 0] }, interface_points: [{ label: 'tip' }] })),
    groups: [{ id: 'group', name: 'Group', instance_ids: ['a'], subgroup_ids: [], expanded: true }],
    joints: [{ id: 'joint', name: 'Mate', joint_type: 'rigid', instance_a_id: 'a', instance_b_id: 'b',
      connector_a_label: 'tip', connector_b_label: 'tip' }],
  }
}
function copy(assembly) {
  const next = JSON.parse(JSON.stringify(assembly))
  next.instances.forEach((instance, index) => sourceVersion(instance, assembly.instances[index].geometrySourceKey))
  return next
}
const row = id => document.querySelector(`[data-instance-id="${id}"]`)
const representation = id => row(id).nextElementSibling.querySelector('select')
const mates = () => document.getElementById('_assembly-mates-section')

describe('assembly panel representation updates', () => {
  let panel, store, api, onPartContextChange
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    document.body.innerHTML = `<section id="assembly-panel"><div id="assembly-panel-name"></div>
      <div id="assembly-instance-list"></div></section>`
    vi.stubGlobal('requestAnimationFrame', fn => { fn(); return 0 })
    HTMLElement.prototype.scrollIntoView = vi.fn()
    store = createMockStore({ currentAssembly: assembly(), assemblyActive: true,
      activeInstanceId: 'a', multiSelectedInstanceIds: [], activeGroupId: null })
    store.subscribeSlice = (_slice, listener) => store.subscribe(listener)
    api = {
      getInstanceDesign: vi.fn(async () => ({ design: { id: 'part', helices: [] } })),
      patchInstance: vi.fn(async () => ({})),
      getJointConnectorFrames: vi.fn(async () => ({ frames: [] })),
      getJointDebugFrames: vi.fn(async () => ({})),
    }
    onPartContextChange = vi.fn()
    panel = initAssemblyPanel(store, { api, onInstanceSelect: vi.fn(), onPartContextChange })
    panel.rebuild(store.getState())
  })
  afterEach(() => {
    panel.dispose()
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
    delete HTMLElement.prototype.scrollIntoView
  })

  it('retains rows, connector expansion, mate drafts/status and source context through display snapshots', async () => {
    await Promise.resolve()
    const originalRow = row('a'), originalSelect = representation('a')
    const connectors = originalRow.nextElementSibling.nextElementSibling
    connectors.firstElementChild.click()
    panel.applySolveStatus({ joint: { satisfied: true } })
    mates().querySelector('[title="Mate"]').click()
    await Promise.resolve()
    mates().querySelector('[title="Edit mate"]').click()
    const draft = mates().querySelector('input[type="text"]')
    draft.value = 'Unsaved mate name'
    const status = mates().querySelector('[title="Satisfied before resolve"]')
    const oldContextCalls = onPartContextChange.mock.calls.length

    const optimistic = { ...store.getState().currentAssembly,
      instances: store.getState().currentAssembly.instances.map(instance =>
        sourceVersion({ ...instance, representation: 'full' }, instance.geometrySourceKey)) }
    store.setState({ currentAssembly: optimistic })
    const acknowledged = copy(optimistic)
    acknowledged.instances[0].representation = 'beads'
    store.setState({ currentAssembly: acknowledged })

    expect(row('a')).toBe(originalRow)
    expect(representation('a')).toBe(originalSelect)
    expect(originalSelect.value).toBe('beads')
    expect(representation('b').value).toBe('full')
    expect(connectors.lastElementChild.style.display).toBe('')
    expect(mates().querySelector('input[type="text"]')).toBe(draft)
    expect(draft.value).toBe('Unsaved mate name')
    expect(mates().querySelector('[title="Satisfied before resolve"]')).toBe(status)
    expect(api.getJointConnectorFrames).toHaveBeenCalledOnce()
    expect(api.getInstanceDesign).toHaveBeenCalledOnce()
    expect(onPartContextChange).toHaveBeenCalledTimes(oldContextCalls)
  })

  it('repaints active/group/multiple selection and refreshes a newly selected part on a reused snapshot', () => {
    const originalRow = row('a'), next = copy(store.getState().currentAssembly)
    next.instances[0].representation = 'full'
    store.setState({ currentAssembly: next, activeInstanceId: 'b',
      multiSelectedInstanceIds: ['a'], activeGroupId: 'group' })
    expect(row('a')).toBe(originalRow)
    expect(row('a').style.background).toBe('rgb(25, 44, 69)')
    expect(row('b').style.background).toBe('rgb(30, 58, 95)')
    expect(document.querySelector('[data-group-id]').style.borderLeftColor).toBe('rgb(139, 92, 246)')
    expect(api.getInstanceDesign).toHaveBeenLastCalledWith('b')
  })

  it('restores the latest displayed representation when a retained heavy-mode confirmation is canceled', async () => {
    let cancel
    showConfirm.mockImplementationOnce(() => new Promise(resolve => { cancel = resolve }))
    const select = representation('a')
    select.value = 'vdw'
    select.dispatchEvent(new Event('change', { bubbles: true }))
    const next = copy(store.getState().currentAssembly)
    next.instances[0].representation = 'hull-prism'
    store.setState({ currentAssembly: next })
    cancel(false)
    await Promise.resolve()
    expect(representation('a')).toBe(select)
    expect(select.value).toBe('hull-prism')
    expect(api.patchInstance).not.toHaveBeenCalled()
  })

  it.each([
    ['part name', next => { next.instances[0].name = 'New name' }],
    ['visibility', next => { next.instances[0].visible = false }],
    ['pose', next => { next.instances[0].transform.translation[0] = 5 }],
    ['source path', next => { next.instances[0].source.path = 'other.nadoc' }],
    ['source version', next => { sourceVersion(next.instances[0], 'f:/part.nadoc:2:') }],
    ['connectors', next => { next.instances[0].interface_points[0].label = 'other' }],
    ['joint state', next => { next.joints[0].name = 'New mate' }],
    ['group state', next => { next.groups[0].expanded = false }],
    ['metadata', next => { next.metadata.name = 'New assembly' }],
    ['instance order', next => { next.instances.reverse() }],
    ['new fields', next => { next.display_annotation = { enabled: true } }],
  ])('rebuilds and refreshes context when %s changes with representation', (_label, change) => {
    const previous = row('b'), next = copy(store.getState().currentAssembly)
    next.instances[0].representation = 'full'
    change(next)
    store.setState({ currentAssembly: next })
    expect(row('b')).not.toBe(previous)
    expect(api.getInstanceDesign).toHaveBeenCalledTimes(2)
  })

  it('does not reuse unversioned file sources or nested inline edits', () => {
    const unversioned = copy(store.getState().currentAssembly)
    delete unversioned.instances[0].geometrySourceKey
    store.setState({ currentAssembly: unversioned })
    const first = row('a')
    store.setState({ currentAssembly: { ...unversioned } })
    expect(row('a')).not.toBe(first)

    const inline = copy(store.getState().currentAssembly)
    inline.instances[0].source = { type: 'inline', design: { id: 'inline', helices: [{ length_bp: 10 }] } }
    store.setState({ currentAssembly: inline })
    const beforeEdit = row('a')
    inline.instances[0].source.design.helices[0].length_bp = 20
    store.setState({ currentAssembly: { ...inline } })
    expect(row('a')).not.toBe(beforeEdit)
  })

  it('detects same-object representation, pose, and inline source mutations without stale controls', () => {
    const same = store.getState().currentAssembly
    const previous = row('a')
    same.instances[0].representation = 'beads'
    panel.rebuild(store.getState())
    expect(row('a')).toBe(previous)
    expect(representation('a').value).toBe('beads')
    expect(api.getInstanceDesign).toHaveBeenCalledOnce()

    same.instances[0].transform.translation[0] = 10
    panel.rebuild(store.getState())
    expect(row('a')).not.toBe(previous)
    same.instances[0].source = { type: 'inline', design: { id: 'inline', helices: [{ length_bp: 10 }] } }
    panel.rebuild(store.getState())
    const beforeSourceEdit = row('a')
    same.instances[0].source.design.helices[0].length_bp = 20
    panel.rebuild(store.getState())
    expect(row('a')).not.toBe(beforeSourceEdit)
    expect(api.getInstanceDesign).toHaveBeenCalledTimes(4)
  })

  it('invalidates same-ID document replacement and removes its subscription/listener on disposal', () => {
    const previous = row('a')
    window.dispatchEvent(new Event('nadoc:document-reset'))
    store.setState({ currentAssembly: copy(store.getState().currentAssembly) })
    expect(row('a')).not.toBe(previous)
    const finalRow = row('a'), remove = vi.spyOn(window, 'removeEventListener')
    panel.dispose()
    expect(remove).toHaveBeenCalledWith('nadoc:document-reset', expect.any(Function))
    const next = copy(store.getState().currentAssembly)
    next.instances[0].name = 'After disposal'
    store.setState({ currentAssembly: next })
    expect(row('a')).toBe(finalRow)
    remove.mockRestore()
  })
})
