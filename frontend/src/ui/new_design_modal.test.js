/**
 * Tests for new_design_modal — the File → "New Part" dialog + create flow.
 * Pure core sanitizeWorkspaceStem + factory wiring (jsdom). createModal/
 * createButton are stubbed; the lifecycle spine + spawn guard are injected.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const modalOpen = vi.fn()
const modalClose = vi.fn()
vi.mock('./primitives/modal.js', () => ({
  createModal: vi.fn(() => ({ open: modalOpen, close: modalClose })),
}))
vi.mock('./primitives/button.js', () => ({
  createButton: vi.fn(({ onClick }) => ({ __onClick: onClick, click: () => onClick?.() })),
}))

import { sanitizeWorkspaceStem, initNewDesignModal } from './new_design_modal.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'

function mountModalDom() {
  const els = mountIds({ 'menu-file-new': 'button', 'new-design-modal-body': 'div' })
  els['new-design-modal-body'].innerHTML = `
    <div id="new-design-unsaved-warn" style="display:none"></div>
    <input id="new-design-name" type="text">
    <div id="new-design-name-error" style="display:none"></div>
    <input type="radio" name="new-lattice-type" value="HONEYCOMB" checked>
    <input type="radio" name="new-lattice-type" value="SQUARE">`
  return els
}

function makeDeps(overrides = {}) {
  const libraryPanel = { refresh: vi.fn() }
  return {
    store: createMockStore({ currentDesign: { name: 'x' } }),
    api: {
      createDesign: vi.fn(async () => ({})),
      uploadLibraryFile: vi.fn(async () => ({ path: 'workspace/foo.nadoc' })),
    },
    workspace: { show: vi.fn() },
    resetForNewDesign: vi.fn(),
    setFileName: vi.fn(),
    hideWelcome: vi.fn(),
    setWorkspacePath: vi.fn(),
    setFileHandle: vi.fn(),
    getLibraryPanel: vi.fn(() => libraryPanel),
    spawnDocTabIfBusy: vi.fn(async () => false),
    _libraryPanel: libraryPanel,
    ...overrides,
  }
}

// Find the Create button object createButton produced.
function createButtonObj() {
  const idx = createButton.mock.calls.findIndex(([opts]) => opts.label === 'Create')
  return createButton.mock.results[idx].value
}

describe('sanitizeWorkspaceStem (pure)', () => {
  it('keeps alphanumerics, spaces, hyphens and underscores', () => {
    expect(sanitizeWorkspaceStem('My Part-01_v2')).toBe('My Part-01_v2')
  })
  it('replaces other characters with underscore', () => {
    expect(sanitizeWorkspaceStem('a/b:c*d')).toBe('a_b_c_d')
  })
  it('trims surrounding whitespace after substitution', () => {
    expect(sanitizeWorkspaceStem('  hello  ')).toBe('hello')
  })
  it('falls back to "untitled" only for an empty / whitespace-only name', () => {
    expect(sanitizeWorkspaceStem('')).toBe('untitled')
    expect(sanitizeWorkspaceStem('   ')).toBe('untitled')
    // Invalid chars substitute to underscores (non-empty) → no fallback.
    expect(sanitizeWorkspaceStem('***')).toBe('___')
  })
})

describe('initNewDesignModal (factory)', () => {
  let els
  beforeEach(() => {
    vi.clearAllMocks()
    els = mountModalDom()
  })
  afterEach(() => clearDom())

  it('returns an openModal API and wires the menu-file-new listener', async () => {
    const api = initNewDesignModal(makeDeps())
    expect(typeof api.openModal).toBe('function')
    els['menu-file-new'].dispatchEvent(new Event('click'))
    await Promise.resolve()
    expect(createModal).toHaveBeenCalledTimes(1)
    expect(modalOpen).toHaveBeenCalledTimes(1)
  })

  it('menu-file-new defers to a new tab when the space is busy (no modal)', async () => {
    const deps = makeDeps({ spawnDocTabIfBusy: vi.fn(async () => true) })
    initNewDesignModal(deps)
    els['menu-file-new'].dispatchEvent(new Event('click'))
    await Promise.resolve(); await Promise.resolve()
    expect(deps.spawnDocTabIfBusy).toHaveBeenCalledWith('new=part')
    expect(modalOpen).not.toHaveBeenCalled()
  })

  it('openModal builds the modal once across repeated opens', () => {
    const api = initNewDesignModal(makeDeps())
    api.openModal()
    api.openModal()
    expect(createModal).toHaveBeenCalledTimes(1)
    expect(modalOpen).toHaveBeenCalledTimes(2)
  })

  it('openModal shows the unsaved warning only when a design with helices is loaded', () => {
    const api = initNewDesignModal(makeDeps({ store: createMockStore({ currentDesign: { helices: [{}] } }) }))
    api.openModal()
    expect(document.getElementById('new-design-unsaved-warn').style.display).toBe('block')
  })

  it('openModal clears the name field + error on open', () => {
    const api = initNewDesignModal(makeDeps())
    const name = document.getElementById('new-design-name')
    name.value = 'leftover'
    document.getElementById('new-design-name-error').style.display = 'block'
    api.openModal()
    expect(name.value).toBe('')
    expect(document.getElementById('new-design-name-error').style.display).toBe('none')
  })

  it('openModal falls back to a fast Untitled create when the modal body is absent', () => {
    document.getElementById('new-design-modal-body').remove()
    const deps = makeDeps()
    initNewDesignModal(deps).openModal()
    expect(deps.resetForNewDesign).toHaveBeenCalled()
    expect(deps.setFileHandle).toHaveBeenCalledWith(null)
    expect(deps.workspace.show).toHaveBeenCalledWith()
    expect(deps.api.createDesign).toHaveBeenCalledWith('Untitled')
    expect(createModal).not.toHaveBeenCalled()
  })

  it('Create with an empty name shows the error and does not create', async () => {
    const deps = makeDeps()
    const api = initNewDesignModal(deps)
    api.openModal()
    document.getElementById('new-design-name').value = '   '
    await createButtonObj().__onClick()
    expect(document.getElementById('new-design-name-error').style.display).toBe('block')
    expect(deps.api.createDesign).not.toHaveBeenCalled()
  })

  it('Create runs the full new-design flow with the chosen lattice + workspace save', async () => {
    const deps = makeDeps()
    const api = initNewDesignModal(deps)
    api.openModal()
    document.getElementById('new-design-name').value = 'My Part!'
    document.querySelector('input[value="HONEYCOMB"]').checked = false
    document.querySelector('input[value="SQUARE"]').checked = true
    await createButtonObj().__onClick()

    expect(modalClose).toHaveBeenCalled()
    expect(deps.resetForNewDesign).toHaveBeenCalled()
    expect(deps.setFileHandle).toHaveBeenCalledWith(null)
    expect(deps.setFileName).toHaveBeenCalledWith('My Part!')
    expect(deps.hideWelcome).toHaveBeenCalled()
    expect(deps.workspace.show).toHaveBeenCalledWith('SQUARE')
    expect(deps.api.createDesign).toHaveBeenCalledWith('My Part!', 'SQUARE')
    // sanitized stem ("My Part!" → "My Part_") drives the workspace filename
    expect(deps.api.uploadLibraryFile).toHaveBeenCalledWith(expect.any(String), 'My Part_.nadoc')
    expect(deps.setWorkspacePath).toHaveBeenCalledWith('workspace/foo.nadoc')
    expect(deps._libraryPanel.refresh).toHaveBeenCalled()
  })

  it('Create defaults the lattice to HONEYCOMB when no radio is checked', async () => {
    const deps = makeDeps()
    const api = initNewDesignModal(deps)
    api.openModal()
    document.getElementById('new-design-name').value = 'P'
    document.querySelector('input[value="HONEYCOMB"]').checked = false
    await createButtonObj().__onClick()
    expect(deps.api.createDesign).toHaveBeenCalledWith('P', 'HONEYCOMB')
  })

  it('Create skips the workspace-path write when the upload returns no path', async () => {
    const deps = makeDeps({ api: {
      createDesign: vi.fn(async () => ({})),
      uploadLibraryFile: vi.fn(async () => null),
    } })
    const api = initNewDesignModal(deps)
    api.openModal()
    document.getElementById('new-design-name').value = 'P'
    await createButtonObj().__onClick()
    expect(deps.setWorkspacePath).not.toHaveBeenCalled()
    expect(deps._libraryPanel.refresh).not.toHaveBeenCalled()
  })
})
