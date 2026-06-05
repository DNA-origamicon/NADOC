/**
 * Tests for scene/photo_mode.js (extraction #70): the photo-mode pane + the
 * export-only representation upgrade.
 *
 * `planExportRepUpgrade` is the pure decision core (when to swap every instance
 * to the assembly's export representation for the duration of a render).
 * `initPhotoMode` is the stateful factory; tests drive it through jsdom + mock
 * deps, asserting the enter/exit overlay toggles, the save-guard flag, and the
 * export-rep upgrade/restore flow.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { planExportRepUpgrade, initPhotoMode } from './photo_mode.js'

// Mock the photo panel so the factory's lazy init on first enter is observable
// and never touches real DOM/canvas wiring.
let panelCalls = []
vi.mock('../ui/photo_panel.js', () => ({
  initPhotoPanel: (...args) => {
    panelCalls.push(args)
    return { applyActiveProfile: vi.fn(), syncToState: vi.fn() }
  },
}))
// Real shortcut registry would accumulate global state across tests; stub it.
let shortcutCalls = []
vi.mock('../input/shortcuts.js', () => ({
  registerShortcut: (s) => shortcutCalls.push(s),
}))

describe('planExportRepUpgrade (pure)', () => {
  const insts = (reps) => reps.map((r, i) => ({ id: `i${i}`, representation: r }))

  it('not in assembly → no upgrade, inAssembly false', () => {
    const out = planExportRepUpgrade({ assemblyActive: false, currentAssembly: { export_representation: 'full', instances: insts(['working']) } })
    expect(out.inAssembly).toBe(false)
    expect(out.needUpgrade).toBe(false)
  })

  it('assembly active but zero instances → inAssembly false (no upgrade)', () => {
    const out = planExportRepUpgrade({ assemblyActive: true, currentAssembly: { export_representation: 'full', instances: [] } })
    expect(out.inAssembly).toBe(false)
    expect(out.needUpgrade).toBe(false)
    expect(out.patches).toEqual([])
    expect(out.snapshot).toEqual([])
  })

  it('export_representation "working" → never upgrades', () => {
    const out = planExportRepUpgrade({ assemblyActive: true, currentAssembly: { export_representation: 'working', instances: insts(['cylinders', 'full']) } })
    expect(out.inAssembly).toBe(true)
    expect(out.exportRep).toBe('working')
    expect(out.needUpgrade).toBe(false)
  })

  it('all instances already match export rep → no upgrade', () => {
    const out = planExportRepUpgrade({ assemblyActive: true, currentAssembly: { export_representation: 'full', instances: insts(['full', 'full']) } })
    expect(out.needUpgrade).toBe(false)
  })

  it('mismatch → upgrade with patches=all→exportRep and snapshot=originals', () => {
    const out = planExportRepUpgrade({ assemblyActive: true, currentAssembly: { export_representation: 'full', instances: insts(['cylinders', 'full']) } })
    expect(out.needUpgrade).toBe(true)
    expect(out.exportRep).toBe('full')
    expect(out.patches).toEqual([{ id: 'i0', representation: 'full' }, { id: 'i1', representation: 'full' }])
    expect(out.snapshot).toEqual([{ id: 'i0', representation: 'cylinders' }, { id: 'i1', representation: 'full' }])
  })

  it('missing export_representation defaults to "full"', () => {
    const out = planExportRepUpgrade({ assemblyActive: true, currentAssembly: { instances: insts(['cylinders']) } })
    expect(out.exportRep).toBe('full')
    expect(out.needUpgrade).toBe(true)
  })

  it('no currentAssembly → safe defaults', () => {
    const out = planExportRepUpgrade({ assemblyActive: true })
    expect(out.inAssembly).toBe(false)
    expect(out.exportRep).toBe('full')
    expect(out.patches).toEqual([])
  })
})

const DOM = {
  'left-panel': 'div',
  'left-tab-strip': 'div',
  'mode-indicator': 'div',
  'tab-content-photo': 'div',
  'photo-tab-btn': 'button',
}

function makeDeps(initialState = {}) {
  const store = createMockStore(initialState)
  const api = { batchPatchInstances: vi.fn(() => Promise.resolve()), setAssemblyExportRepresentation: vi.fn() }
  const sceneCtx = { scene: { traverse: vi.fn() }, renderer: { domElement: { width: 100, height: 50 } } }
  let active = false
  const photoRenderer = {
    resyncMaterials: vi.fn(), activate: vi.fn(() => { active = true }),
    isActive: vi.fn(() => active), deactivate: vi.fn(() => { active = false }),
    getSettings: vi.fn(() => ({})), getSampleCount: vi.fn(() => 0),
  }
  const assemblyRenderer = { onRebuildComplete: vi.fn(), setPhotoMode: vi.fn(), setSuppressLodDemotion: vi.fn() }
  const designRenderer = { setAxisArrowsVisible: vi.fn() }
  const bluntEnds = { setVisible: vi.fn() }
  const assemblyJointRenderer = { setVisible: vi.fn() }
  const viewCube = { hide: vi.fn(), show: vi.fn() }
  const player = {}
  return { store, api, sceneCtx, photoRenderer, assemblyRenderer, designRenderer, bluntEnds, assemblyJointRenderer, viewCube, player }
}

beforeEach(() => { clearDom(); panelCalls = []; shortcutCalls = [] })

describe('initPhotoMode factory', () => {
  it('returns the expected API surface', () => {
    mountIds(DOM)
    const m = initPhotoMode(makeDeps())
    expect(typeof m.enter).toBe('function')
    expect(typeof m.exit).toBe('function')
    expect(typeof m.getExportRepActive).toBe('function')
    expect(typeof m.withExportRepresentation).toBe('function')
    expect(m.getExportRepActive()).toBe(false)
  })

  it('registers the "p" toggle shortcut', () => {
    mountIds(DOM)
    initPhotoMode(makeDeps())
    expect(shortcutCalls.some(s => s.key === 'p')).toBe(true)
  })

  it('enter() activates the renderer, lazily builds the panel, sets photoActive, suppresses overlays', () => {
    mountIds(DOM)
    const deps = makeDeps()
    const m = initPhotoMode(deps)
    m.enter()
    expect(deps.photoRenderer.activate).toHaveBeenCalled()
    expect(panelCalls.length).toBe(1)            // panel built on first enter
    expect(deps.designRenderer.setAxisArrowsVisible).toHaveBeenCalledWith(false)
    expect(deps.bluntEnds.setVisible).toHaveBeenCalledWith(false)
    expect(deps.assemblyRenderer.setPhotoMode).toHaveBeenCalledWith(true)
    expect(deps.assemblyJointRenderer.setVisible).toHaveBeenCalledWith(false)
    expect(deps.viewCube.hide).toHaveBeenCalled()
    expect(deps.store.getState().photoActive).toBe(true)
    expect(document.getElementById('mode-indicator').style.display).toBe('none')
  })

  it('second enter() reuses the panel (no re-init)', () => {
    mountIds(DOM)
    const m = initPhotoMode(makeDeps())
    m.enter()
    m.exit()
    m.enter()
    expect(panelCalls.length).toBe(1)
  })

  it('exit() is a no-op when not active', () => {
    mountIds(DOM)
    const deps = makeDeps()
    const m = initPhotoMode(deps)
    m.exit()
    expect(deps.photoRenderer.deactivate).not.toHaveBeenCalled()
    expect(deps.designRenderer.setAxisArrowsVisible).not.toHaveBeenCalled()
  })

  it('exit() after enter() restores overlays + photoActive false', () => {
    mountIds(DOM)
    const deps = makeDeps()
    deps.store.setState({ toolFilters: { bluntEnds: true } })
    const m = initPhotoMode(deps)
    m.enter()
    m.exit()
    expect(deps.photoRenderer.deactivate).toHaveBeenCalled()
    expect(deps.designRenderer.setAxisArrowsVisible).toHaveBeenLastCalledWith(true)
    expect(deps.bluntEnds.setVisible).toHaveBeenLastCalledWith(true)
    expect(deps.assemblyRenderer.setPhotoMode).toHaveBeenLastCalledWith(false)
    expect(deps.assemblyJointRenderer.setVisible).toHaveBeenLastCalledWith(true)
    expect(deps.viewCube.show).toHaveBeenCalled()
    expect(deps.store.getState().photoActive).toBe(false)
  })

  it('photo-tab-btn click enters photo mode when inactive', () => {
    mountIds(DOM)
    const deps = makeDeps()
    initPhotoMode(deps)
    document.getElementById('photo-tab-btn').dispatchEvent(new window.MouseEvent('click'))
    expect(deps.photoRenderer.activate).toHaveBeenCalled()
  })

  it('withExportRepresentation: no-upgrade path runs fn + toggles LOD suppression, no patch', async () => {
    mountIds(DOM)
    const deps = makeDeps({ assemblyActive: true, currentAssembly: { export_representation: 'working', instances: [{ id: 'a', representation: 'working' }] } })
    const m = initPhotoMode(deps)
    const fn = vi.fn(() => Promise.resolve())
    await m.withExportRepresentation(fn)
    expect(fn).toHaveBeenCalled()
    expect(deps.api.batchPatchInstances).not.toHaveBeenCalled()
    expect(deps.assemblyRenderer.setSuppressLodDemotion).toHaveBeenCalledWith(true)
    expect(deps.assemblyRenderer.setSuppressLodDemotion).toHaveBeenLastCalledWith(false)
    expect(m.getExportRepActive()).toBe(false)
  })

  it('withExportRepresentation: upgrade path patches, sets the save-guard flag during render, restores', async () => {
    mountIds(DOM)
    const deps = makeDeps({ assemblyActive: true, currentAssembly: { export_representation: 'full', instances: [{ id: 'a', representation: 'cylinders' }] } })
    // Resolve the rebuild barrier synchronously each time it's awaited.
    deps.assemblyRenderer.onRebuildComplete = vi.fn(cb => cb())
    const m = initPhotoMode(deps)
    let flagDuringRender = null
    const fn = vi.fn(() => { flagDuringRender = m.getExportRepActive(); return Promise.resolve() })
    await m.withExportRepresentation(fn)
    expect(flagDuringRender).toBe(true)                       // guarded while rendering
    expect(m.getExportRepActive()).toBe(false)               // cleared after
    // First patch = upgrade to export rep; last = restore originals.
    expect(deps.api.batchPatchInstances.mock.calls[0][0]).toEqual([{ id: 'a', representation: 'full' }])
    expect(deps.api.batchPatchInstances.mock.calls.at(-1)[0]).toEqual([{ id: 'a', representation: 'cylinders' }])
    expect(deps.photoRenderer.resyncMaterials).toHaveBeenCalled()
  })
})
