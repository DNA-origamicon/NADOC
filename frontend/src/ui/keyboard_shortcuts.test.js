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
    toolFilters: { bluntEnds: false, overhangLocations: false },
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
      deleteOverhangs: vi.fn(async () => ({})), deleteStrandExtensionsBatch: vi.fn(async () => ({})),
      addNick: vi.fn(async () => ({})),
      addNickBatch: vi.fn(async () => ({})),
      deleteForcedLigation: vi.fn(async () => ({})), batchDeleteForcedLigations: vi.fn(async () => ({})),
      deleteCrossover: vi.fn(async () => ({})), batchDeleteCrossovers: vi.fn(async () => ({})),
      forcedLigation: vi.fn(async () => ({})),
    },
    slicePlane: { isVisible: vi.fn(() => false), hide: vi.fn() },
    expandedSpacing: { toggle: vi.fn() },
    debugOverlay: { toggle: vi.fn(), isActive: vi.fn(() => true) },
    measurementTool: { isActive: vi.fn(() => false), clear: vi.fn(), show: vi.fn() },
    clusterClipboard: {
      copy: vi.fn(), paste: vi.fn(), cancel: vi.fn(), isActive: vi.fn(() => false),
    },
    selectionManager: {
      getSelectionLevel: vi.fn(() => 'default'),
      setSelectionLevel: vi.fn(),
      getCtrlBeads: vi.fn(() => []),
      getSelectedEndBeads: vi.fn(() => []),
      getCtrlBeadPos: vi.fn(() => [0, 0, 0]),
      clearCtrlBeads: vi.fn(),
      clearEndSelection: vi.fn(),
      clearMultiOverhangSelection: vi.fn(),
      clearMultiExtensionSelection: vi.fn(),
      getMultiCrossoverArcs: vi.fn(() => []),
      clearMultiCrossoverArcs: vi.fn(),
      getSelectedCrossoverArc: vi.fn(() => null),
      clearSelection: vi.fn(),
    },
    extrudePanel: { hide: vi.fn() },
    deformView: { isActive: vi.fn(() => false), activate: vi.fn(async () => {}) },
    crossSectionMinimap: { clearSlice: vi.fn(), hide: vi.fn() },
    sliceHighlighter: { clear: vi.fn() },
    isUnfoldActive: vi.fn(() => false),
    isDeformActive: vi.fn(() => false),
    captureCurrentCamera: vi.fn(() => ({ pos: [1, 2, 3] })),
    frameSelectionOrAll: vi.fn(),
    setMenuToggle: vi.fn(),
    toggleUnfold: vi.fn(),
    toggleCadnano: vi.fn(),
    toggleHelicalAxisLines: vi.fn(),
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
    isProteinMoveActive: vi.fn(() => false),
    getPartEditContext: vi.fn(() => null),
    getAssemblyWorkspacePath: vi.fn(() => null),
    getOoActiveIds: vi.fn(() => []),
    ...overrides,
  }
}

describe('initKeyboardShortcuts — helical axis lines', () => {
  beforeEach(() => { clearShortcuts(); clearDom() })

  it('/ toggles helical axis lines and is ignored in text inputs', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)

    await press('/')
    expect(d.toggleHelicalAxisLines).toHaveBeenCalledOnce()

    await press('/', { tag: 'INPUT' })
    expect(d.toggleHelicalAxisLines).toHaveBeenCalledOnce()
  })

  it('L toggles helix labels and is ignored in text inputs', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)

    await press('l')
    expect(d.store.getState().showHelixLabels).toBe(true)
    await press('l', { tag: 'INPUT' })
    expect(d.store.getState().showHelixLabels).toBe(true)
    await press('l')
    expect(d.store.getState().showHelixLabels).toBe(false)
  })
})

describe('initKeyboardShortcuts — Group 1 toggles', () => {
  beforeEach(() => {
    clearShortcuts()
    clearDom()
    // Number-hotkey targets + mode indicator.
    mountIds({
      'menu-routing-scaffold-ends': 'button',
      'menu-routing-full-autostaple': 'button',
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

  it("Tab is blocked when translate/rotate is active", async () => {
    const d = makeDeps()
    d.isTranslateRotateActive.mockReturnValue(true)
    initKeyboardShortcuts(d)
    await press('Tab', { tag: 'CANVAS' })
    expect(d.selectionManager.setSelectionLevel).not.toHaveBeenCalled()
  })

  it('Tab is reserved for the gizmo when a protein move session is active', async () => {
    const d = makeDeps()
    d.isProteinMoveActive.mockReturnValue(true)
    initKeyboardShortcuts(d)
    await press('Tab', { tag: 'CANVAS' })
    expect(d.selectionManager.setSelectionLevel).not.toHaveBeenCalled()
  })

  it('Tab keeps native focus navigation when a button has focus', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    const e = await press('Tab', { tag: 'BUTTON' })
    expect(d.selectionManager.setSelectionLevel).not.toHaveBeenCalled()
    expect(e.preventDefault).not.toHaveBeenCalled()
  })

  it("'q' cycles the selectable level backward", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('q', { tag: 'CANVAS' })
    expect(d.selectionManager.setSelectionLevel).toHaveBeenCalledWith('base')
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
    // '2' = Full Autostaple (Auto Crossover [old 2] + Autobreak [old 3] are retired).
    const btn = document.getElementById('menu-routing-full-autostaple')
    const click = vi.fn()
    btn.click = click
    await press('2')
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
    await press('m', { shift: true })
    expect(d.measurementTool.show).toHaveBeenCalled()

    // Already active → clears instead.
    d.measurementTool.isActive.mockReturnValue(true)
    d.measurementTool.show.mockClear()
    await press('m', { shift: true })
    expect(d.measurementTool.clear).toHaveBeenCalled()
    expect(d.measurementTool.show).not.toHaveBeenCalled()
  })

  it("'m' is suppressed in unfold view (shows mode-indicator message)", async () => {
    const d = makeDeps()
    d.store.setState({ unfoldActive: true })
    d.selectionManager.getCtrlBeads.mockReturnValue([{}, {}])
    initKeyboardShortcuts(d)
    await press('m', { shift: true })
    expect(d.measurementTool.show).not.toHaveBeenCalled()
    expect(document.getElementById('mode-indicator').textContent).toMatch(/not available/i)
  })

  it("'x' activates quick expand", async () => {
    const d = makeDeps()
    const button = document.createElement('button')
    button.className = 'vt-btn'; button.dataset.vt = 'expanded'
    const clicked = vi.fn(); button.addEventListener('click', clicked); document.body.append(button)
    initKeyboardShortcuts(d)
    await press('x')
    expect(clicked).toHaveBeenCalledTimes(1)
    expect(d.api.forcedLigation).not.toHaveBeenCalled()
  })

  it("'x' rejects an invalid pair (same polarity / same strand) without calling the api", async () => {
    const d = makeDeps()
    // Two 5′ ends → not a 3′/5′ pair.
    d.selectionManager.getSelectedEndBeads.mockReturnValue([
      { nuc: { strand_id: 'A', is_five_prime: true } },
      { nuc: { strand_id: 'B', is_five_prime: true } },
    ])
    initKeyboardShortcuts(d)
    await press('x')
    expect(d.api.forcedLigation).not.toHaveBeenCalled()
    expect(d.selectionManager.clearEndSelection).not.toHaveBeenCalled()
  })

  it("'x' is a no-op unless exactly 2 ends are selected, and never in assembly mode", async () => {
    const d = makeDeps()
    d.selectionManager.getSelectedEndBeads.mockReturnValue([{ nuc: { strand_id: 'A', is_five_prime: true } }])
    initKeyboardShortcuts(d)
    await press('x')
    expect(d.api.forcedLigation).not.toHaveBeenCalled()

    // Even a valid pair is ignored while an assembly is active.
    d.store.setState({ assemblyActive: true })
    d.selectionManager.getSelectedEndBeads.mockReturnValue([
      { nuc: { strand_id: 'A', is_five_prime: true } },
      { nuc: { strand_id: 'B', is_three_prime: true } },
    ])
    await press('x')
    expect(d.api.forcedLigation).not.toHaveBeenCalled()
  })

  it("'b'/'o' flip their toolFilters flags; key-repeat is ignored (noRepeat)", async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('b')
    expect(d.store.getState().toolFilters.bluntEnds).toBe(true)
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

  it('does not run file/edit shortcuts while an editable control has focus', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    const open = vi.fn()
    document.getElementById('menu-file-open').click = open
    for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) {
      await press('o', { ctrl: true, tag })
      await press('s', { ctrl: true, tag })
      await press('z', { ctrl: true, tag })
      await press('y', { ctrl: true, tag })
    }
    expect(open).not.toHaveBeenCalled()
    expect(d.api.undo).not.toHaveBeenCalled()
    expect(d.api.redo).not.toHaveBeenCalled()
  })

  it('Ctrl+C copies when a cluster is selected', async () => {
    const d = makeDeps()
    d.store.setState({ selection: { items: [{ kind: 'cluster', id: 'cA' }] } })
    initKeyboardShortcuts(d)
    const e = await press('c', { ctrl: true })
    expect(d.clusterClipboard.copy).toHaveBeenCalledTimes(1)
    expect(e.preventDefault).toHaveBeenCalled()
  })

  it('Ctrl+C copies from the cluster multi-select pool', async () => {
    const d = makeDeps()
    d.store.setState({ selection: { items: [
      { kind: 'cluster', id: 'cA' }, { kind: 'cluster', id: 'cB' },
    ] } })
    initKeyboardShortcuts(d)
    await press('c', { ctrl: true })
    expect(d.clusterClipboard.copy).toHaveBeenCalledTimes(1)
  })

  it('Ctrl+C yields to the browser text copy when no cluster is selected', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    const e = await press('c', { ctrl: true })
    expect(d.clusterClipboard.copy).not.toHaveBeenCalled()
    expect(e.preventDefault).not.toHaveBeenCalled()
  })

  it('Ctrl+C and Ctrl+V are blocked in assembly mode', async () => {
    const d = makeDeps()
    d.store.setState({ assemblyActive: true, selection: { items: [{ kind: 'cluster', id: 'cA' }] } })
    initKeyboardShortcuts(d)
    await press('c', { ctrl: true })
    await press('v', { ctrl: true })
    expect(d.clusterClipboard.copy).not.toHaveBeenCalled()
    expect(d.clusterClipboard.paste).not.toHaveBeenCalled()
  })

  it('Ctrl+V arms the paste ghost', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('v', { ctrl: true })
    expect(d.clusterClipboard.paste).toHaveBeenCalledTimes(1)
  })

  it('Ctrl+V does not fire the plain-v camera-pose capture', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('v', { ctrl: true })
    expect(d.captureCurrentCamera).not.toHaveBeenCalled()
  })

  it('Escape cancels an armed paste ghost before anything else', async () => {
    const d = makeDeps()
    d.clusterClipboard.isActive.mockReturnValue(true)
    d.getOoActiveIds = vi.fn(() => ['oh1'])   // would otherwise win
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.clusterClipboard.cancel).toHaveBeenCalledTimes(1)
    expect(d.ooClose).not.toHaveBeenCalled()
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
    d.store.setState({ selection: { items: [
      { kind: 'overhang', id: 'oh1' },
      { kind: 'overhang', id: 'oh2' },
    ] } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.selectionManager.clearMultiOverhangSelection).toHaveBeenCalled()
    expect(d.ooClose).toHaveBeenCalled()
    expect(d.api.deleteOverhangs).toHaveBeenCalledWith(['oh1', 'oh2'])

    clearShortcuts()
    d = makeDeps()
    d.store.setState({ selection: { items: [{ kind: 'strand', id: 's7' }] } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteStrand).toHaveBeenCalledWith('s7')
  })

  it('Delete: canonical extension refs delete the extensions as one batch', async () => {
    const d = makeDeps()
    d.store.setState({ selection: { items: [
      { kind: 'extension', id: 'e1' },
      { kind: 'extension', id: 'e2' },
    ] } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.selectionManager.clearMultiExtensionSelection).toHaveBeenCalled()
    expect(d.api.deleteStrandExtensionsBatch).toHaveBeenCalledWith(['e1', 'e2'])
  })

  it('Delete: canonical backbone bond nicks at its from-base identity', async () => {
    const d = makeDeps()
    d.store.setState({ selection: { items: [{
      kind: 'bond', fromKey: 'h2:14:FORWARD', toKey: 'h2:15:FORWARD', strandId: 's1',
    }] } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.addNick).toHaveBeenCalledWith({ helixId: 'h2', bpIndex: 14, direction: 'FORWARD' })
    expect(d.selectionManager.clearSelection).toHaveBeenCalled()
  })

  it('Delete: single selected forced ligation → deleteForcedLigation(id) + clears selection', async () => {
    const d = makeDeps()
    d.store.setState({ selection: {
      context: 'design', level: 'xover',
      items: [{ kind: 'crossover', id: 'fl9', subtype: 'forced_ligation' }],
      primary: { kind: 'crossover', id: 'fl9', subtype: 'forced_ligation' },
    } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteForcedLigation).toHaveBeenCalledWith('fl9')
    expect(d.selectionManager.clearSelection).toHaveBeenCalled()
    expect(d.api.deleteStrand).not.toHaveBeenCalled()
  })

  it('Delete: record-backed crossover → deleteCrossover(id) (removes record, not just a nick)', async () => {
    const d = makeDeps()
    d.store.setState({ selection: {
      context: 'design', level: 'xover',
      items: [{ kind: 'crossover', id: 'xo3', subtype: 'crossover' }],
      primary: { kind: 'crossover', id: 'xo3', subtype: 'crossover' },
    } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteCrossover).toHaveBeenCalledWith('xo3')
    expect(d.api.addNick).not.toHaveBeenCalled()
    expect(d.selectionManager.clearSelection).toHaveBeenCalled()
  })

  it('Delete: forced-ligation ref → deleteForcedLigation(id)', async () => {
    const d = makeDeps()
    d.store.setState({ selection: {
      context: 'design', level: 'xover',
      items: [{ kind: 'crossover', id: 'fl1', subtype: 'forced_ligation' }],
      primary: { kind: 'crossover', id: 'fl1', subtype: 'forced_ligation' },
    } })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteForcedLigation).toHaveBeenCalledWith('fl1')
    expect(d.api.deleteCrossover).not.toHaveBeenCalled()
  })

  it('Delete: canonical crossover refs split into forced-ligation and crossover batches', async () => {
    const d = makeDeps()
    d.store.setState({
      selection: {
        context: 'design', level: 'xover',
        items: [
          { kind: 'crossover', id: 'fl1', subtype: 'forced_ligation' },
          { kind: 'crossover', id: 'xoA', subtype: 'crossover' },
          { kind: 'crossover', id: 'xoB', subtype: 'crossover' },
        ],
        primary: { kind: 'crossover', id: 'xoB', subtype: 'crossover' },
      },
    })
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteForcedLigation).toHaveBeenCalledWith('fl1')
    expect(d.api.batchDeleteCrossovers).toHaveBeenCalledWith(['xoA', 'xoB'])
    expect(d.api.addNick).not.toHaveBeenCalled()
    expect(d.selectionManager.clearSelection).toHaveBeenCalled()
  })

  it('Delete with no selection is a no-op (no api calls)', async () => {
    const d = makeDeps()
    initKeyboardShortcuts(d)
    await press('Delete')
    expect(d.api.deleteStrand).not.toHaveBeenCalled()
    expect(d.api.deleteOverhangs).not.toHaveBeenCalled()
    expect(d.api.addNick).not.toHaveBeenCalled()
  })

  it('Escape cancels in priority order: oo edit → ctrl-beads → translate/rotate → deform → slice', async () => {
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
  })
})

describe('initKeyboardShortcuts — drill v2 (selectionLevel) E/Q/Escape', () => {
  beforeEach(() => { clearShortcuts(); clearDom(); mountIds({ 'mode-indicator': 'div' }) })

  const makeV2Deps = (level = 'default') => {
    const d = makeDeps()
    d.selectionManager.getSelectionLevel = vi.fn(() => level)
    d.selectionManager.setSelectionLevel = vi.fn()
    return d
  }

  it('E cycles the unified selectionLevel default→strand→domain→… (cluster excluded)', async () => {
    const d = makeV2Deps('default')
    initKeyboardShortcuts(d)
    await press('e', { tag: 'CANVAS' })
    expect(d.selectionManager.setSelectionLevel).toHaveBeenCalledWith('strand')
  })

  it('E from cluster restarts at strand (cluster is button-only, not in the cycle)', async () => {
    const d = makeV2Deps('cluster')
    initKeyboardShortcuts(d)
    await press('e', { tag: 'CANVAS' })
    expect(d.selectionManager.setSelectionLevel).toHaveBeenCalledWith('strand')
  })

  it('E steps xover→base (base is the finest grain, last stop before the wrap)', async () => {
    const d = makeV2Deps('xover')
    initKeyboardShortcuts(d)
    await press('e', { tag: 'CANVAS' })
    expect(d.selectionManager.setSelectionLevel).toHaveBeenCalledWith('base')
  })

  it('E wraps base→none(default)', async () => {
    const d = makeV2Deps('base')
    initKeyboardShortcuts(d)
    await press('e', { tag: 'CANVAS' })
    expect(d.selectionManager.setSelectionLevel).toHaveBeenCalledWith('default')
  })

  it('Escape returns the selectionLevel to default when engaged', async () => {
    const d = makeV2Deps('domain')
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.selectionManager.setSelectionLevel).toHaveBeenCalledWith('default')
  })

  it('Escape at default level does NOT set the level (falls through the chain)', async () => {
    const d = makeV2Deps('default')
    initKeyboardShortcuts(d)
    await press('Escape')
    expect(d.selectionManager.setSelectionLevel).not.toHaveBeenCalled()
  })
})
