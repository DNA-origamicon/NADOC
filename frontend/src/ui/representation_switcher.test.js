/**
 * Tests for representation_switcher (frontier #2 switcher CORE).
 * Drives the factory through real jsdom menu clicks + the registered F-key
 * handlers; oracles derived from pre-extraction main.js behaviour + the
 * scene/coloring_modes.js support matrix.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initRepresentationSwitcher } from './representation_switcher.js'
import { getShortcuts, clearShortcuts, dispatchKeyEvent } from '../input/shortcuts.js'

// Plain fake keydown for the registry matcher (a real off-document KeyboardEvent
// has target:null and throws — see keyboard_shortcuts.test.js / log #39).
function fkey(key) {
  return { key, ctrlKey: false, shiftKey: false, altKey: false, repeat: false,
           target: { tagName: 'BODY' }, preventDefault: vi.fn() }
}

// Menu ids the factory reads: the eight repr radios, the mixed-state dot, and
// the six Coloring submenu items (whose `.disabled` the availability matrix sets).
const REPR_IDS = [
  'menu-view-hull-prism', 'menu-view-detail-cylinders', 'menu-view-detail-beads',
  'menu-view-detail-full', 'menu-view-surface', 'menu-view-atomistic-vdw',
  'menu-view-atomistic-ballstick',
  'menu-view-atomistic-stick',
  'menu-view-mrdna-coarse', 'menu-view-mrdna-fine',
]
const COLORING_IDS = [
  'menu-view-coloring-strand', 'menu-view-coloring-base', 'menu-view-coloring-cluster',
  'menu-view-coloring-overhang-only', 'menu-view-coloring-cpk', 'menu-view-coloring-source',
]
const DOM = {}
for (const id of REPR_IDS)     DOM[id] = 'button'
for (const id of COLORING_IDS) DOM[id] = 'button'
DOM['menu-view-repr-mixed-dot'] = 'div'

function makeDeps(initialState = {}) {
  const store = createMockStore({ coloringMode: 'strand', ...initialState })
  const api = {
    batchPatchInstances: vi.fn().mockResolvedValue({}),
    clearRepresentationOverrides: vi.fn().mockResolvedValue({}),
  }
  const atomisticRenderer = { getMode: vi.fn(() => 'off'), setMode: vi.fn() }
  const designRenderer = { setDetailLevel: vi.fn() }
  const flexibleArcs = { setRepresentation: vi.fn() }
  const overhangLinkArcs = { setRepresentation: vi.fn() }
  const unfoldView = { refreshArcVisibility: vi.fn() }
  const jointRenderer = { setHullRepr: vi.fn(), setHullScanTick: vi.fn() }
  let lastDetailLevel = 0
  const deps = {
    store, api, atomisticRenderer, designRenderer, flexibleArcs, overhangLinkArcs, unfoldView,
    getJointRenderer: () => jointRenderer,
    getSurfaceMode: vi.fn(() => 'off'),
    applySurfaceMode: vi.fn().mockResolvedValue(undefined),
    applyAtomisticMode: vi.fn().mockResolvedValue(undefined),
    setCGVisible: vi.fn(),
    setColoringMode: vi.fn(),
    reprOptionSliders: vi.fn(),
    getLastDetailLevel: () => lastDetailLevel,
    setLastDetailLevel: vi.fn((v) => { lastDetailLevel = v }),
    setLodMode: vi.fn(),
    setCurrentRepr: vi.fn(),
    jointRenderer,
  }
  return deps
}

beforeEach(() => { clearDom(); clearShortcuts() })

describe('initRepresentationSwitcher — construction', () => {
  it('returns the three-fn API and no-ops gracefully with no DOM', () => {
    const api = initRepresentationSwitcher(makeDeps())
    expect(typeof api.setRepresentation).toBe('function')
    expect(typeof api.updateReprRadio).toBe('function')
    expect(typeof api.syncAssemblyReprMenu).toBe('function')
  })

  it('registers F1…F8 shortcuts in least→most-intensive order', () => {
    mountIds(DOM)
    initRepresentationSwitcher(makeDeps())
    const keys = getShortcuts().filter(s => /^F[1-8]$/.test(s.key)).map(s => s.key).sort()
    expect(keys).toEqual(['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8'])
    const f1 = getShortcuts().find(s => s.key === 'F1')
    expect(f1.description).toContain('Hull Prism')
    const f7 = getShortcuts().find(s => s.key === 'F7')
    expect(f7.description).toContain('Ball & Stick')
    const f8 = getShortcuts().find(s => s.key === 'F8')
    expect(f8.description).toContain('Stick')
  })

  it('seeds initial Coloring-menu availability for default repr "full" (cpk + source disabled)', () => {
    mountIds(DOM)
    initRepresentationSwitcher(makeDeps())
    // full supports strand/base/cluster/overhang-only → cpk + source disabled
    expect(document.getElementById('menu-view-coloring-strand').disabled).toBe(false)
    expect(document.getElementById('menu-view-coloring-base').disabled).toBe(false)
    expect(document.getElementById('menu-view-coloring-cpk').disabled).toBe(true)
    expect(document.getElementById('menu-view-coloring-source').disabled).toBe(true)
  })
})

describe('updateReprRadio', () => {
  it('checks only the active repr and drives Coloring availability', () => {
    mountIds(DOM)
    const api = initRepresentationSwitcher(makeDeps())
    api.updateReprRadio('cylinders')
    expect(document.getElementById('menu-view-detail-cylinders').classList.contains('is-checked')).toBe(true)
    expect(document.getElementById('menu-view-detail-full').classList.contains('is-checked')).toBe(false)
    // cylinders supports strand/cluster/overhang-only → base disabled
    expect(document.getElementById('menu-view-coloring-base').disabled).toBe(true)
  })
})

describe('syncAssemblyReprMenu', () => {
  it('hides the dot and leaves radios when there are no instances', () => {
    mountIds(DOM)
    const api = initRepresentationSwitcher(makeDeps())
    api.syncAssemblyReprMenu({ instances: [] })
    expect(document.getElementById('menu-view-repr-mixed-dot').style.display).toBe('none')
  })

  it('single agreed repr → checks it, hides dot', () => {
    mountIds(DOM)
    const api = initRepresentationSwitcher(makeDeps())
    api.syncAssemblyReprMenu({ instances: [{ representation: 'beads' }, { representation: 'beads' }] })
    expect(document.getElementById('menu-view-detail-beads').classList.contains('is-checked')).toBe(true)
    expect(document.getElementById('menu-view-repr-mixed-dot').style.display).toBe('none')
  })

  it('mixed reprs → clears all checks, shows dot', () => {
    mountIds(DOM)
    const api = initRepresentationSwitcher(makeDeps())
    document.getElementById('menu-view-detail-full').classList.add('is-checked')
    api.syncAssemblyReprMenu({ instances: [{ representation: 'beads' }, { representation: 'full' }] })
    expect(document.getElementById('menu-view-detail-full').classList.contains('is-checked')).toBe(false)
    expect(document.getElementById('menu-view-repr-mixed-dot').style.display).toBe('')
  })
})

describe('setRepresentation — design-mode activation', () => {
  it('full → setCGVisible(true), LOD 0, arcs/lod-mode/repr set, sliders updated', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    deps.getLastDetailLevel = () => 2  // currently cylinders → switching to full changes level
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('full')
    expect(deps.setCurrentRepr).toHaveBeenCalledWith('full')
    expect(deps.flexibleArcs.setRepresentation).toHaveBeenCalledWith('full')
    expect(deps.setCGVisible).toHaveBeenCalledWith(true)
    expect(deps.overhangLinkArcs.setRepresentation).toHaveBeenCalledWith('full')
    expect(deps.setLastDetailLevel).toHaveBeenCalledWith(0)
    expect(deps.setLodMode).toHaveBeenCalledWith('full')
    expect(deps.designRenderer.setDetailLevel).toHaveBeenCalledWith(0)
    expect(deps.reprOptionSliders).toHaveBeenCalledWith('full')
    expect(document.getElementById('menu-view-detail-full').classList.contains('is-checked')).toBe(true)
  })

  it('cylinders when already at that LOD → no setDetailLevel (level unchanged)', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    deps.getLastDetailLevel = () => 2  // cylinders = level 2 already
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('cylinders')
    expect(deps.setCGVisible).toHaveBeenCalledWith(true)
    expect(deps.designRenderer.setDetailLevel).not.toHaveBeenCalled()
    expect(deps.setLodMode).not.toHaveBeenCalled()
  })

  it('vdw → applyAtomisticMode + atomisticMode store patch', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('vdw')
    expect(deps.applyAtomisticMode).toHaveBeenCalledWith('vdw')
    expect(deps.store.getState().atomisticMode).toBe('vdw')
  })

  it('surface → applySurfaceMode("on") + surfaceMode store patch', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('surface')
    expect(deps.applySurfaceMode).toHaveBeenCalledWith('on')
    expect(deps.store.getState().surfaceMode).toBe('on')
  })

  it('mrDNA representations delegate to the external result renderer', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    deps.beforeRepresentationChange = vi.fn()
    deps.applyExternalRepresentation = vi.fn().mockResolvedValue(true)
    const api = initRepresentationSwitcher(deps)
    expect(await api.setRepresentation('mrdna-coarse')).not.toBe(false)
    expect(deps.beforeRepresentationChange).toHaveBeenCalledWith('mrdna-coarse')
    expect(deps.applyExternalRepresentation).toHaveBeenCalledWith('mrdna-coarse')
    expect(document.getElementById('menu-view-mrdna-coarse').classList.contains('is-checked')).toBe(true)
  })

  it('leaves the prior radio selected when mrDNA geometry is unavailable', async () => {
    mountIds(DOM)
    document.getElementById('menu-view-detail-full').classList.add('is-checked')
    const deps = makeDeps()
    deps.applyExternalRepresentation = vi.fn().mockResolvedValue(false)
    const api = initRepresentationSwitcher(deps)
    expect(await api.setRepresentation('mrdna-fine')).toBe(false)
    expect(document.getElementById('menu-view-detail-full').classList.contains('is-checked')).toBe(true)
    expect(deps.setCurrentRepr).not.toHaveBeenCalled()
  })

  it('hull-prism honeycomb → CG off, scan tick 8, hull repr on', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { lattice_type: 'HONEYCOMB' } })
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('hull-prism')
    expect(deps.setCGVisible).toHaveBeenCalledWith(false)
    expect(deps.jointRenderer.setHullScanTick).toHaveBeenCalledWith(8)
    expect(deps.jointRenderer.setHullRepr).toHaveBeenCalledWith(true)
  })

  it('hull-prism square → scan tick 7', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { lattice_type: 'SQUARE' } })
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('hull-prism')
    expect(deps.jointRenderer.setHullScanTick).toHaveBeenCalledWith(7)
  })

  it('switching away from atomistic deactivates the atomistic renderer', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    deps.atomisticRenderer.getMode = vi.fn(() => 'vdw')  // currently atomistic
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('full')
    expect(deps.atomisticRenderer.setMode).toHaveBeenCalledWith('off')
    expect(deps.store.getState().atomisticMode).toBe('off')
  })

  it('switching away from surface deactivates surface mode', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    deps.getSurfaceMode = vi.fn(() => 'on')  // currently surface
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('beads')
    expect(deps.applySurfaceMode).toHaveBeenCalledWith('off')
    expect(deps.store.getState().surfaceMode).toBe('off')
  })

  it('switching away from hull-prism turns hull repr off', async () => {
    mountIds(DOM)
    const deps = makeDeps()
    const api = initRepresentationSwitcher(deps)
    await api.setRepresentation('full')
    expect(deps.jointRenderer.setHullRepr).toHaveBeenCalledWith(false)
  })
})

describe('menu click — design mode', () => {
  it('toasts + bails when no design is loaded', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: null, assemblyActive: false })
    initRepresentationSwitcher(deps)
    document.getElementById('menu-view-detail-beads').click()
    await Promise.resolve()
    expect(deps.designRenderer.setDetailLevel).not.toHaveBeenCalled()
  })

  it('clears representation_overrides before applying the new global repr', async () => {
    mountIds(DOM)
    const deps = makeDeps({
      currentDesign: { representation_overrides: [{ strand_id: 1 }] },
      assemblyActive: false,
    })
    initRepresentationSwitcher(deps)
    document.getElementById('menu-view-detail-beads').click()
    await new Promise(r => setTimeout(r, 0))
    expect(deps.api.clearRepresentationOverrides).toHaveBeenCalled()
    expect(deps.setCurrentRepr).toHaveBeenCalledWith('beads')
  })

  // Dispatching 'nadoc:representation-change' is not free: six listeners fan out of it
  // and several do real network work (oxDNA/NAMD heavy-frame reconstruction, the solvent
  // refetch, the NAMD trajectory prebuild). Re-picking what is already on screen must not
  // pay any of that.
  describe('no-op re-pick', () => {
    it('re-clicking the active repr does not re-apply or re-dispatch', async () => {
      mountIds(DOM)
      const deps = makeDeps({ currentDesign: { id: 'd1' }, assemblyActive: false })
      initRepresentationSwitcher(deps)
      document.getElementById('menu-view-detail-beads').click()
      await new Promise(r => setTimeout(r, 0))

      const seen = vi.fn()
      window.addEventListener('nadoc:representation-change', seen)
      deps.setCurrentRepr.mockClear()
      deps.reprOptionSliders.mockClear()
      document.getElementById('menu-view-detail-beads').click()
      await new Promise(r => setTimeout(r, 0))
      window.removeEventListener('nadoc:representation-change', seen)

      expect(seen).not.toHaveBeenCalled()
      expect(deps.setCurrentRepr).not.toHaveBeenCalled()
      expect(deps.reprOptionSliders).not.toHaveBeenCalled()
    })

    it('a DIFFERENT repr still applies normally', async () => {
      mountIds(DOM)
      const deps = makeDeps({ currentDesign: { id: 'd1' }, assemblyActive: false })
      initRepresentationSwitcher(deps)
      document.getElementById('menu-view-detail-beads').click()
      await new Promise(r => setTimeout(r, 0))
      deps.setCurrentRepr.mockClear()
      document.getElementById('menu-view-detail-cylinders').click()
      await new Promise(r => setTimeout(r, 0))
      expect(deps.setCurrentRepr).toHaveBeenCalledWith('cylinders')
    })

    // The master reset: the structure on screen genuinely diverges from the nominal
    // global rep while per-region overrides are live, so the same name is real work.
    it('re-clicking the active repr DOES re-apply when it clears overrides', async () => {
      mountIds(DOM)
      const deps = makeDeps({
        currentDesign: { id: 'd1', representation_overrides: [{ strand_id: 1 }] },
        assemblyActive: false,
      })
      initRepresentationSwitcher(deps)
      document.getElementById('menu-view-detail-beads').click()
      await new Promise(r => setTimeout(r, 0))
      deps.setCurrentRepr.mockClear()
      document.getElementById('menu-view-detail-beads').click()
      await new Promise(r => setTimeout(r, 0))
      expect(deps.api.clearRepresentationOverrides).toHaveBeenCalledTimes(2)
      expect(deps.setCurrentRepr).toHaveBeenCalledWith('beads')
    })

    // The first click after boot always goes through: nothing has been applied yet, so
    // the menu's is-checked class is a claim about the HTML default, not about state.
    it('the first click is never skipped', async () => {
      mountIds(DOM)
      const deps = makeDeps({ currentDesign: { id: 'd1' }, assemblyActive: false })
      initRepresentationSwitcher(deps)
      document.getElementById('menu-view-detail-full').click()
      await new Promise(r => setTimeout(r, 0))
      expect(deps.setCurrentRepr).toHaveBeenCalledWith('full')
    })
  })
})

describe('menu click — assembly mode', () => {
  it('no instances → bails without a PATCH', async () => {
    mountIds(DOM)
    const deps = makeDeps({ assemblyActive: true, currentAssembly: { instances: [] } })
    initRepresentationSwitcher(deps)
    document.getElementById('menu-view-detail-cylinders').click()
    await new Promise(r => setTimeout(r, 0))
    expect(deps.api.batchPatchInstances).not.toHaveBeenCalled()
  })

  // Every instance already agrees on this repr → the PATCH would rewrite each one to the
  // value it already holds and the renderer would rebuild for nothing.
  it('already-uniform repr → no PATCH', async () => {
    mountIds(DOM)
    const deps = makeDeps({
      assemblyActive: true,
      currentAssembly: {
        instances: [{ id: 'a', representation: 'cylinders' },
                    { id: 'b', representation: 'cylinders' }],
      },
    })
    initRepresentationSwitcher(deps)
    document.getElementById('menu-view-detail-cylinders').click()
    await new Promise(r => setTimeout(r, 0))
    expect(deps.api.batchPatchInstances).not.toHaveBeenCalled()
    // …but the menu still reads as checked.
    expect(document.getElementById('menu-view-detail-cylinders').classList.contains('is-checked')).toBe(true)
  })

  // Mixed state still goes through: there the click means "make them all agree".
  it('mixed reprs → PATCHes even when one instance already matches', async () => {
    mountIds(DOM)
    const deps = makeDeps({
      assemblyActive: true,
      currentAssembly: {
        instances: [{ id: 'a', representation: 'cylinders' },
                    { id: 'b', representation: 'full' }],
      },
    })
    initRepresentationSwitcher(deps)
    document.getElementById('menu-view-detail-cylinders').click()
    await new Promise(r => setTimeout(r, 0))
    expect(deps.api.batchPatchInstances).toHaveBeenCalledWith([
      { id: 'a', representation: 'cylinders' },
      { id: 'b', representation: 'cylinders' },
    ])
  })

  it('cheap repr → batch-PATCHes every instance to that repr (no confirm)', async () => {
    mountIds(DOM)
    const deps = makeDeps({
      assemblyActive: true,
      currentAssembly: { instances: [{ id: 'a' }, { id: 'b' }] },
    })
    initRepresentationSwitcher(deps)
    document.getElementById('menu-view-detail-cylinders').click()
    await new Promise(r => setTimeout(r, 0))
    expect(deps.api.batchPatchInstances).toHaveBeenCalledWith([
      { id: 'a', representation: 'cylinders' },
      { id: 'b', representation: 'cylinders' },
    ])
  })
})

describe('F-key handler', () => {
  it('inactive repr → clicks the menu button (delegates to switch)', async () => {
    mountIds(DOM)
    const deps = makeDeps({ currentDesign: { lattice_type: 'SQUARE' }, assemblyActive: false })
    initRepresentationSwitcher(deps)
    const clickSpy = vi.spyOn(document.getElementById('menu-view-hull-prism'), 'click')
    await dispatchKeyEvent(fkey('F1'))
    expect(clickSpy).toHaveBeenCalled()
  })

  it('already-checked repr (no overrides) → cycles coloring instead of clicking', async () => {
    mountIds(DOM)
    const deps = makeDeps({ assemblyActive: false, currentDesign: {}, coloringMode: 'strand' })
    initRepresentationSwitcher(deps)
    const fullBtn = document.getElementById('menu-view-detail-full')
    fullBtn.classList.add('is-checked')
    const clickSpy = vi.spyOn(fullBtn, 'click')
    await dispatchKeyEvent(fkey('F4'))
    expect(clickSpy).not.toHaveBeenCalled()
    // full's cycle from 'strand' → next supported mode 'base'
    expect(deps.setColoringMode).toHaveBeenCalledWith('base')
  })

  it('checked repr WITH overrides → clicks (reset) rather than cycling', async () => {
    mountIds(DOM)
    const deps = makeDeps({
      assemblyActive: false,
      currentDesign: { representation_overrides: [{ strand_id: 1 }] },
    })
    initRepresentationSwitcher(deps)
    const fullBtn = document.getElementById('menu-view-detail-full')
    fullBtn.classList.add('is-checked')
    const clickSpy = vi.spyOn(fullBtn, 'click')
    await dispatchKeyEvent(fkey('F4'))
    expect(clickSpy).toHaveBeenCalled()
    expect(deps.setColoringMode).not.toHaveBeenCalled()
  })

  it('disabled button → handler no-ops (no click, no cycle)', async () => {
    mountIds(DOM)
    const deps = makeDeps({ assemblyActive: false })
    initRepresentationSwitcher(deps)
    const vdwBtn = document.getElementById('menu-view-atomistic-vdw')
    vdwBtn.disabled = true
    const clickSpy = vi.spyOn(vdwBtn, 'click')
    await dispatchKeyEvent(fkey('F6'))
    expect(clickSpy).not.toHaveBeenCalled()
  })
})
