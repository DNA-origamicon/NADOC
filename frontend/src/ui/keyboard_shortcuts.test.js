/**
 * Tests for initKeyboardShortcuts (Group 1: view/tool toggles + number hotkeys).
 *
 * Drives the REAL registry: initKeyboardShortcuts registers via the shared
 * input/shortcuts.js, and we dispatch synthetic keydowns through the real
 * dispatchKeyEvent matcher, asserting the injected deps fire. clearShortcuts()
 * resets the module-level registry between cases (it's a singleton).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { initKeyboardShortcuts } from './keyboard_shortcuts.js'
import { dispatchKeyEvent, clearShortcuts } from '../input/shortcuts.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// Build a fake keydown event (dispatchKeyEvent reads plain fields + target.tagName).
function press(key, { ctrl = false, shift = false, alt = false, repeat = false, tag = 'BODY' } = {}) {
  const e = {
    key,
    ctrlKey: ctrl, metaKey: false, shiftKey: shift, altKey: alt, repeat,
    target: { tagName: tag },
    preventDefault: vi.fn(),
  }
  return dispatchKeyEvent(e).then(() => e)
}

function makeDeps(overrides = {}) {
  const store = createMockStore({
    currentDesign: { helices: [{}], camera_poses: [] },
    unfoldActive: false,
    assemblyActive: false,
    toolFilters: { bluntEnds: false, crossoverLocations: false, overhangLocations: false },
    selectedObject: null,
    multiSelectedStrandIds: [],
    multiSelectedOverhangIds: [],
    multiSelectedDomainIds: [],
  })
  return {
    store,
    api: {
      getDeformDebug: vi.fn(), createCameraPose: vi.fn(),
      undo: vi.fn(async () => ({})), redo: vi.fn(async () => ({})),
      undoAssembly: vi.fn(async () => ({})), redoAssembly: vi.fn(async () => ({})),
      saveAssemblyAs: vi.fn(async () => ({})), saveAssemblyToWorkspace: vi.fn(async () => ({})),
      deleteStrand: vi.fn(async () => ({})), deleteStrandsBatch: vi.fn(async () => ({})),
      deleteOverhangs: vi.fn(async () => ({})), addNick: vi.fn(async () => ({})),
      addNickBatch: vi.fn(async () => ({})),
      deleteForcedLigation: vi.fn(async () => ({})), batchDeleteForcedLigations: vi.fn(async () => ({})),
    },
    slicePlane: { isVisible: vi.fn(() => false), hide: vi.fn() },
    expandedSpacing: { toggle: vi.fn() },
    debugOverlay: { toggle: vi.fn(), isActive: vi.fn(() => true) },
    measurementTool: { isActive: vi.fn(() => false), clear: vi.fn(), show: vi.fn() },
    selectionManager: {
      getDrillLock: vi.fn(() => null),
      setDrillLock: vi.fn(),
      getCtrlBeads: vi.fn(() => []),
      getCtrlBeadPos: vi.fn(() => [0, 0, 0]),
      clearCtrlBeads: vi.fn(),
      clearMultiOverhangSelection: vi.fn(),
      getMultiCrossoverArcs: vi.fn(() => []),
      clearMultiCrossoverArcs: vi.fn(),
    },
    workspace: { show: vi.fn() },
    deformView: { isActive: vi.fn(() => false), activate: vi.fn(async () => {}) },
    crossSectionMinimap: { clearSlice: vi.fn(), hide: vi.fn() },
    sliceHighlighter: { clear: vi.fn() },
    isUnfoldActive: vi.fn(() => false),
    isDeformActive: vi.fn(() => false),
    isManualSelect: vi.fn(() => false),
    captureCurrentCamera: vi.fn(() => ({ pos: [1, 2, 3] })),
    frameSelectionOrAll: vi.fn(),
    setMenuToggle: vi.fn(),
    reflectLockOnButtons: vi.fn(),
    resetToAutoBaseline: vi.fn(),
    toggleUnfold: vi.fn(),
    toggleCadnano: vi.fn(),
    savePartToAssembly: vi.fn(),
    saveAssemblyAsGuarded: vi.fn(),
    setAssemblyWorkspacePath: vi.fn(),
    showWelcome: vi.fn(),
    ooClose: vi.fn(),
    cancelTranslateRotateTool: vi.fn(),
    watchDeformState: vi.fn(),
    deformEscape: vi.fn(),
    popGroupUndo: vi.fn(() => false),
    isTranslateRotateActive: vi.fn(() => false),
    getPartEditContext: vi.fn(() => null),
    getAssemblyWorkspacePath: vi.fn(() => null),
    getOoActiveIds: vi.fn(() => []),
    ...overrides,
  }
}

describe('initKeyboardShortcuts — Group 1 toggles', () => {
  beforeEach(() => {
    clearShortcuts()
    clearDom()
    // Number-hotkey targets + mode indicator.
    mountIds({
      'menu-routing-scaffold-ends': 'button',
      'menu-routing-auto-crossover': 'button',
      'menu-routing-autobreak': 'button',
      'menu-seq-update-routing': 'button',
      'menu-seq-assign-scaffold': 'button',
      'menu-seq-assign-staples': 'button',
      'mode-indicator': 'div',
    })
  })

  it("'u' toggles unfold; 'k' toggles cadnano", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('u')
    await press('k')
    expect(d.toggleUnfold).toHaveBeenCalledTimes(1)
    expect(d.toggleCadnano).toHaveBeenCalledTimes(1)
  })

  it("'u' is blocked while focus is in an INPUT (blockedInInput)", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('u', { tag: 'INPUT' })
    expect(d.toggleUnfold).not.toHaveBeenCalled()
  })

  it("Tab cycles the drill lock null→cluster and toasts; blocked when translate/rotate active", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    const e = await press('Tab')
    expect(e.preventDefault).toHaveBeenCalled()
    expect(d.resetToAutoBaseline).toHaveBeenCalled()
    expect(d.selectionManager.setDrillLock).toHaveBeenCalledWith('cluster')
    expect(d.reflectLockOnButtons).toHaveBeenCalledWith('cluster')

    // Now block it.
    d.selectionManager.setDrillLock.mockClear()
    d.isTranslateRotateActive.mockReturnValue(true)
    await press('Tab')
    expect(d.selectionManager.setDrillLock).not.toHaveBeenCalled()
  })

  it("Tab wraps from the last lock (xover) back to null/auto-drill", async () => {
    const d = makeDeps()
    d.selectionManager.getDrillLock.mockReturnValue('xover')
    initKeyboardShortcuts(d)
    await press('Tab')
    expect(d.selectionManager.setDrillLock).toHaveBeenCalledWith(null)
  })

  it("'q' toggles expanded spacing only when a design is loaded and unfold/slice are off", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('q')
    expect(d.expandedSpacing.toggle).toHaveBeenCalledTimes(1)

    // Blocked while unfold active.
    d.expandedSpacing.toggle.mockClear()
    d.isUnfoldActive.mockReturnValue(true)
    await press('q')
    expect(d.expandedSpacing.toggle).not.toHaveBeenCalled()

    // No design → no-op (no throw).
    d.isUnfoldActive.mockReturnValue(false)
    d.store.setState({ currentDesign: { helices: [] } })
    await press('q')
    expect(d.expandedSpacing.toggle).not.toHaveBeenCalled()
  })

  it("'v' captures a camera pose named by count", async () => {
    const d = makeDeps()
    d.store.setState({ currentDesign: { helices: [{}], camera_poses: [{}, {}] } })
    initKeyboardShortcuts(d)
    await press('v')
    expect(d.captureCurrentCamera).toHaveBeenCalled()
    expect(d.api.createCameraPose).toHaveBeenCalledWith('Pose 3', { pos: [1, 2, 3] })
  })

  it('Shift+D dumps deform debug from the api', async () => {
    const d = makeDeps()
    d.api.getDeformDebug.mockResolvedValue(null) // null → early toast, no crash
    initKeyboardShortcuts(d)
    await press('d', { shift: true })
    expect(d.api.getDeformDebug).toHaveBeenCalled()
  })

  it('number hotkeys click their (enabled) menu target; disabled targets are ignored', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    const btn = document.getElementById('menu-routing-autobreak')
    const click = vi.fn()
    btn.click = click
    await press('3')
    expect(click).toHaveBeenCalledTimes(1)

    // Disabled → no click.
    const btn2 = document.getElementById('menu-seq-assign-staples')
    const click2 = vi.fn()
    btn2.click = click2
    btn2.disabled = true
    await press('6')
    expect(click2).not.toHaveBeenCalled()
  })

  it('backtick toggles the debug overlay and reflects menu + store state', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('`')
    expect(d.debugOverlay.toggle).toHaveBeenCalled()
    expect(d.setMenuToggle).toHaveBeenCalledWith('menu-view-debug', true)
    expect(d.store.getState().debugOverlayActive).toBe(true)
  })

  it("'f' frames the selection", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('f')
    expect(d.frameSelectionOrAll).toHaveBeenCalledTimes(1)
  })

  it("'m' shows measurement when exactly 2 ctrl-beads are picked; clears when already active", async () => {
    const d = makeDeps()
    d.selectionManager.getCtrlBeads.mockReturnValue([{}, {}])
    initKeyboardShortcuts(d)
    await press('m')
    expect(d.measurementTool.show).toHaveBeenCalled()

    // Already active → clears instead.
    d.measurementTool.isActive.mockReturnValue(true)
    d.measurementTool.show.mockClear()
    await press('m')
    expect(d.measurementTool.clear).toHaveBeenCalled()
    expect(d.measurementTool.show).not.toHaveBeenCalled()
  })

  it("'m' is suppressed in unfold view (shows mode-indicator message)", async () => {
    const d = makeDeps()
    d.store.setState({ unfoldActive: true })
    d.selectionManager.getCtrlBeads.mockReturnValue([{}, {}])
    initKeyboardShortcuts(d)
    await press('m')
    expect(d.measurementTool.show).not.toHaveBeenCalled()
    expect(document.getElementById('mode-indicator').textContent).toMatch(/not available/i)
  })

  it("'b'/'c'/'o' flip their toolFilters flags; key-repeat is ignored (noRepeat)", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('b')
    expect(d.store.getState().toolFilters.bluntEnds).toBe(true)
    await press('c')
    expect(d.store.getState().toolFilters.crossoverLocations).toBe(true)
    await press('o')
    expect(d.store.getState().toolFilters.overhangLocations).toBe(true)

    // Held key (repeat) does not re-toggle.
    await press('b', { repeat: true })
    expect(d.store.getState().toolFilters.bluntEnds).toBe(true)
  })
})

describe('initKeyboardShortcuts — Group 2 file/edit + Delete/Escape', () => {
  beforeEach(() => {
    clearShortcuts()
    clearDom()
    mountIds({
      'menu-file-open': 'button',
      'menu-file-save': 'button',
      'menu-file-save-as': 'button',
      'mode-indicator': 'div',
    })
  })

  it('Ctrl+O clicks the File>Open menu item', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    const click = vi.fn()
    document.getElementById('menu-file-open').click = click
    await press('o', { ctrl: true })
    expect(click).toHaveBeenCalledTimes(1)
  })

  it("Ctrl+S routes by mode: part-edit→savePartToAssembly, assembly→saveAssemblyToWorkspace, else menu Save", async () => {
    // part-edit context
    let d = makeDeps({ getPartEditContext: vi.fn(() => ({ instanceId: 'x' })) })
    initKeyboardShortcuts(d)
    await press('s', { ctrl: true })
    expect(d.savePartToAssembly).toHaveBeenCalled()

    // assembly mode, no workspace path → saveAssemblyToWorkspace
    clearShortcuts()
    d = makeDeps()
    d.store.setState({ assemblyActive: true })
    initKeyboardShortcuts(d)
    await press('s', { ctrl: true })
    expect(d.api.saveAssemblyToWorkspace).toHaveBeenCalled()
    expect(d.api.saveAssemblyAs).not.toHaveBeenCalled()

    // plain design → clicks menu Save
    clearShortcuts()
    d = makeDeps()
    initKeyboardShortcuts(d)
    const click = vi.fn()
    document.getElementById('menu-file-save').click = click
    await press('s', { ctrl: true })
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('Ctrl+S in assembly mode WITH a workspace path uses saveAssemblyAs(path)', async () => {
    const d = makeDeps({ getAssemblyWorkspacePath: vi.fn(() => 'workspace/foo.nass') })
    d.store.setState({ assemblyActive: true })
    initKeyboardShortcuts(d)
    await press('s', { ctrl: true })
    expect(d.api.saveAssemblyAs).toHaveBeenCalledWith('workspace/foo.nass')
  })

  it('Ctrl+Shift+S → saveAssemblyAsGuarded in assembly mode, else clicks Save As', async () => {
    let d = makeDeps()
    d.store.setState({ assemblyActive: true })
    initKeyboardShortcuts(d)
    await press('s', { ctrl: true, shift: true })
    expect(d.saveAssemblyAsGuarded).toHaveBeenCalled()

    clearShortcuts()
    d = makeDeps()
    initKeyboardShortcuts(d)
    const click = vi.fn()
    document.getElementById('menu-file-save-as').click = click
    await press('s', { ctrl: true, shift: true })
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('Ctrl+Z undoes (design), is blocked during deform, short-circuits on group-undo, and undoes assembly in assembly mode', async () => {
    // normal design undo
    let d = makeDeps()
    initKeyboardShortcuts(d)
    await press('z', { ctrl: true })
    expect(d.api.undo).toHaveBeenCalled()

    // blocked while deform active (blockedWhen)
    clearShortcuts()
    d = makeDeps({ isDeformActive: vi.fn(() => true) })
    initKeyboardShortcuts(d)
    await press('z', { ctrl: true })
    expect(d.api.undo).not.toHaveBeenCalled()

    // group-undo short-circuits the api call
    clearShortcuts()
    d = makeDeps({ popGroupUndo: vi.fn(() => true) })
    initKeyboardShortcuts(d)
    await press('z', { ctrl: true })
    expect(d.popGroupUndo).toHaveBeenCalled()
    expect(d.api.undo).not.toHaveBeenCalled()

    // assembly mode → undoAssembly
    clearShortcuts()
    d = makeDeps()
    d.store.setState({ assemblyActive: true })
    initKeyboardShortcuts(d)
    await press('z', { ctrl: true })
    expect(d.api.undoAssembly).toHaveBeenCalled()
    expect(d.api.undo).not.toHaveBeenCalled()
  })

  it('Ctrl+Y / Ctrl+Shift+Z redo (design + assembly)', async () => {
    let d = makeDeps()
    initKeyboardShortcuts(d)
    await press('y', { ctrl: true })
    expect(d.api.redo).toHaveBeenCalledTimes(1)
    await press('z', { ctrl: true, shift: true })
    expect(d.api.redo).toHaveBeenCalledTimes(2)

    clearShortcuts()
    d = makeDeps()
    d.store.setState({ assemblyActive: true })
    initKeyboardShortcuts(d)
    await press('y', { ctrl: true })
    expect(d.api.redoAssembly).toHaveBeenCalled()
  })

  it('Delete: multi-overhang → deleteOverhangs + ooClose; single selected strand → deleteStrand', async () => {
    let d = makeDeps()
    d.store.setState({ multiSelectedOverhangIds: ['oh1', 'oh2'] })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.selectionManager.clearMultiOverhangSelection).toHaveBeenCalled()
    expect(d.ooClose).toHaveBeenCalled()
    expect(d.api.deleteOverhangs).toHaveBeenCalledWith(['oh1', 'oh2'])

    clearShortcuts()
    d = makeDeps()
    d.store.setState({ selectedObject: { type: 'strand', data: { strand_id: 's7' } } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteStrand).toHaveBeenCalledWith('s7')
  })

  it('Delete with no selection is a no-op (no api calls)', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteStrand).not.toHaveBeenCalled()
    expect(d.api.deleteOverhangs).not.toHaveBeenCalled()
    expect(d.api.addNick).not.toHaveBeenCalled()
  })

  it('Escape cancels in priority order: oo edit → ctrl-beads → translate/rotate → deform → slice → drill-lock', async () => {
    // oo edit set active
    let d = makeDeps({ getOoActiveIds: vi.fn(() => ['oh']) })
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.ooClose).toHaveBeenCalled()

    // ctrl-beads present → clearCtrlBeads (after measurement clear)
    clearShortcuts()
    d = makeDeps()
    d.selectionManager.getCtrlBeads.mockReturnValue([{}])
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.selectionManager.clearCtrlBeads).toHaveBeenCalled()

    // translate/rotate active → cancel tool
    clearShortcuts()
    d = makeDeps({ isTranslateRotateActive: vi.fn(() => true) })
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.cancelTranslateRotateTool).toHaveBeenCalled()

    // deform active → deformEscape + watch
    clearShortcuts()
    d = makeDeps({ isDeformActive: vi.fn(() => true) })
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.deformEscape).toHaveBeenCalled()
    expect(d.watchDeformState).toHaveBeenCalled()

    // slice visible → hide slice + minimap
    clearShortcuts()
    d = makeDeps()
    d.slicePlane.isVisible.mockReturnValue(true)
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.slicePlane.hide).toHaveBeenCalled()
    expect(d.crossSectionMinimap.hide).toHaveBeenCalled()
    expect(d.setMenuToggle).toHaveBeenCalledWith('menu-view-slice', false)

    // drill lock set → back to auto-drill
    clearShortcuts()
    d = makeDeps()
    d.selectionManager.getDrillLock.mockReturnValue('cluster')
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.selectionManager.setDrillLock).toHaveBeenCalledWith(null)
    expect(d.reflectLockOnButtons).toHaveBeenCalledWith(null)
  })
})
