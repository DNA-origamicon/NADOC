import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createDesignReadinessActions, readinessActions } from './design_readiness_actions.js'

const menuIds = ['menu-routing-scaffold-ends', 'menu-routing-full-autostaple', 'menu-seq-assign-scaffold', 'menu-seq-assign-staples']
const actions = ['scaffold_routing', 'staple_routing', 'scaffold_sequence', 'staple_sequences']
const partReport = () => ({ context: 'part', design_id: 'part', steps: actions.map(action => ({ action, complete: false })) })
let controller

beforeEach(() => {
  document.body.innerHTML = menuIds.map(id => `<button id="${id}">Command</button>`).join('')
})
afterEach(() => { controller?.dispose(); controller = null; document.body.innerHTML = '' })

function setup(options = {}) {
  const store = options.store ?? createMockStore({ currentDesign: { id: 'part' } })
  controller = createDesignReadinessActions({ store, ...options })
  controller.decorate(partReport())
  return controller
}

describe('readiness action availability', () => {
  it('shows the established shortcuts without mutating the report', () => {
    const original = partReport()
    const decorated = readinessActions(original, { document })
    expect(decorated.steps.map(step => step.hotkey)).toEqual(['1', '2', '5', '6'])
    expect(original.steps[0]).not.toHaveProperty('hotkey')
    document.getElementById(menuIds[0]).disabled = true
    const blocked = readinessActions(original, { document }).steps[0]
    expect(blocked).toMatchObject({ blocked: true, hotkey: null })
    expect(blocked.blocked_reason).toContain('disabled')
  })

  it('dispatches each existing command and rechecks disabled state at click time', async () => {
    const handlers = menuIds.map(id => {
      const handler = vi.fn()
      document.getElementById(id).addEventListener('click', handler)
      return handler
    })
    setup()
    for (const action of actions) await controller.run(action)
    handlers.forEach(handler => expect(handler).toHaveBeenCalledTimes(1))
    document.getElementById(menuIds[0]).disabled = true
    await expect(controller.run(actions[0])).rejects.toThrow('disabled')
    expect(handlers[0]).toHaveBeenCalledTimes(1)
  })

  it('rejects a stale report after switching documents', async () => {
    const store = createMockStore({ currentDesign: { id: 'part' } })
    setup({ store })
    store.setState({ currentDesign: { id: 'other' } })
    await expect(controller.run('staple_sequences')).rejects.toThrow('document changed')
  })

  it('rejects a stale report after editing the same document id', async () => {
    const store = createMockStore({ currentDesign: { id: 'part', strands: [] } })
    setup({ store })
    store.setState({ currentDesign: { id: 'part', strands: [{ id: 'new-strand' }] } })
    await expect(controller.run('staple_sequences')).rejects.toThrow('document changed')
  })
})

describe('details and assembly ownership', () => {
  it('shows exact issue text safely and removes its modal on disposal', async () => {
    setup()
    await controller.run('validation', { action: 'validation', label: 'Topology', issues: ['Missing helix H7', '<img src=x onerror=alert(1)>'] })
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('Missing helix H7')
    expect(dialog.textContent).toContain('Correct each issue')
    expect(dialog.querySelector('img')).toBeNull()
    controller.dispose()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('opens the owning part in an isolated document without invoking an underlying part command', async () => {
    const click = vi.fn()
    document.getElementById(menuIds[0]).addEventListener('click', click)
    document.getElementById(menuIds[0]).disabled = true
    const open = vi.fn(() => ({ focus: vi.fn() }))
    const store = createMockStore({ assemblyActive: true, currentAssembly: { id: 'asm', instances: [{ id: 'a' }] }, currentDesign: { id: 'old' } })
    setup({ store, getDocId: () => 'assembly-doc', window: { open } })
    const report = controller.decorate({ context: 'assembly', document_id: 'asm', design_id: 'flat_asm', steps: [{ action: 'scaffold_routing', targets: [{ instance_id: 'a', name: 'Arm' }] }] })
    expect(report.steps[0]).toMatchObject({ blocked: false, hotkey: null })
    await controller.run('scaffold_routing', report.steps[0])
    expect(click).not.toHaveBeenCalled()
    const url = new URL(open.mock.calls[0][0], 'http://localhost')
    expect(Object.fromEntries(url.searchParams)).toEqual({ 'part-instance': 'a', doc: 'pe-assembly-doc-a', 'assembly-doc': 'assembly-doc', readiness: 'scaffold_routing' })
    expect(open.mock.calls[0][1]).toBe('nadoc-part-a')
  })

  it('accepts the legacy flattened assembly id without treating its stale underlying part as current', async () => {
    const openPartEditor = vi.fn()
    const store = createMockStore({ assemblyActive: true, currentAssembly: { id: 'asm', instances: [{ id: 'a' }] }, currentDesign: { id: 'stale-part' } })
    setup({ store, openPartEditor })
    controller.decorate({ context: 'assembly', design_id: 'flat_asm', steps: [] })
    await controller.run('staple_routing', { action: 'staple_routing', targets: [{ instance_id: 'a' }] })
    expect(openPartEditor).toHaveBeenCalledWith('a', 'staple_routing')
  })

  it('offers multiple owning parts and explains assembly-level issues without choosing a stale part', async () => {
    const openPartEditor = vi.fn()
    const store = createMockStore({ assemblyActive: true, currentAssembly: { id: 'asm', instances: [{ id: 'a' }, { id: 'b' }] } })
    setup({ store, openPartEditor })
    controller.decorate({ context: 'assembly', design_id: 'asm', steps: [] })
    await controller.run('staple_routing', { action: 'staple_routing', targets: [{ instance_id: 'a', name: 'Arm A' }, { instance_id: 'b', name: 'Arm B' }] })
    expect(openPartEditor).not.toHaveBeenCalled()
    const button = [...document.querySelectorAll('[role="dialog"] button')].find(node => node.textContent === 'Open Arm B')
    button.click()
    await Promise.resolve()
    expect(openPartEditor).toHaveBeenCalledWith('b', 'staple_routing')
    await controller.run('validation', { action: 'validation', targets: [], issues: ['Invalid linker'] })
    expect(document.querySelector('[role="dialog"]').textContent).toContain('combined assembly')
  })

  it('keeps a part chooser bound to its original source after a newer readiness report arrives', async () => {
    const openPartEditor = vi.fn()
    const store = createMockStore({ assemblyActive: true, currentAssembly: { id: 'asm', instances: [{ id: 'a' }, { id: 'b' }] } })
    setup({ store, openPartEditor })
    const report = { context: 'assembly', document_id: 'asm', design_id: 'flat_asm', steps: [] }
    controller.decorate(report)
    await controller.run('staple_routing', { action: 'staple_routing', targets: [{ instance_id: 'a', name: 'Arm A' }, { instance_id: 'b', name: 'Arm B' }] })
    store.setState({ currentAssembly: { id: 'asm', instances: [{ id: 'a', source: { type: 'file', path: 'replacement.nadoc' } }, { id: 'b' }] } })
    controller.decorate(report)
    const button = [...document.querySelectorAll('[role="dialog"] button')].find(node => node.textContent === 'Open Arm A')
    button.click()
    await Promise.resolve()
    expect(openPartEditor).not.toHaveBeenCalled()
    expect(document.querySelector('[role="dialog"] [role="alert"]').textContent).toContain('document changed')
  })
})

describe('simulation navigation', () => {
  it('opens 3D simulation controls without launching a job', async () => {
    const onSimulate = vi.fn()
    setup({ onSimulate })
    await controller.run('simulation')
    expect(onSimulate).toHaveBeenCalledTimes(1)
  })

  it('focuses and signals only a matching same-origin 3D opener', async () => {
    const opener = { location: { href: 'http://localhost/?doc=matching' }, focus: vi.fn() }
    const window = { location: { href: 'http://localhost/cadnano-editor.html?doc=matching' }, opener, open: vi.fn() }
    const broadcast = { emit: vi.fn() }
    setup({ mode: 'cadnano', window, getDocId: () => 'matching', broadcast })
    await controller.run('simulation')
    expect(opener.focus).toHaveBeenCalledTimes(1)
    expect(broadcast.emit).toHaveBeenCalledWith('readiness-action', { action: 'simulation', docId: 'matching' })
    expect(window.open).not.toHaveBeenCalled()
  })

  it('uses the canonical null broadcast scope for a default-document 3D opener', async () => {
    const opener = { location: { href: 'http://localhost/?doc=__default__' }, focus: vi.fn() }
    const window = { location: { href: 'http://localhost/cadnano-editor.html' }, opener, open: vi.fn() }
    const broadcast = { emit: vi.fn() }
    setup({ mode: 'cadnano', window, getDocId: () => null, broadcast })
    await controller.run('simulation')
    expect(opener.focus).toHaveBeenCalledTimes(1)
    expect(broadcast.emit).toHaveBeenCalledWith('readiness-action', { action: 'simulation', docId: null })
    expect(window.open).not.toHaveBeenCalled()
  })

  it.each(['http://localhost/?doc=other', 'http://elsewhere/?doc=matching'])('does not change an unrelated opener %s', async href => {
    const opener = { location: { href }, focus: vi.fn() }
    const open = vi.fn(() => ({ focus: vi.fn() }))
    const window = { location: { href: 'http://localhost/cadnano-editor.html?doc=matching' }, opener, open }
    const broadcast = { emit: vi.fn() }
    setup({ mode: 'cadnano', window, getDocId: () => 'matching', broadcast })
    await controller.run('simulation')
    expect(opener.focus).not.toHaveBeenCalled()
    expect(broadcast.emit).not.toHaveBeenCalled()
    expect(open).toHaveBeenCalledWith('/?doc=matching&readiness=simulation', 'nadoc-readiness-3d-matching')
  })

  it('pins the default backend document when standalone cadnano has no doc query', async () => {
    const open = vi.fn(() => ({ focus: vi.fn() }))
    setup({ mode: 'cadnano', window: { location: { href: 'http://localhost/cadnano-editor.html' }, open }, getDocId: () => null })
    await controller.run('simulation')
    expect(open).toHaveBeenCalledWith('/?doc=__default__&readiness=simulation', 'nadoc-readiness-3d-__default__')
  })
})
