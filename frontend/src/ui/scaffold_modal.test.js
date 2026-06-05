/**
 * Tests for scaffold_modal — the Sequencing → "Assign Scaffold Sequence" dialog.
 * Pure cores (ascWarningText / countScaffoldNt) are tested in scaffold_assign.test.js;
 * here we cover the factory wiring (jsdom). createModal/createButton/toast are stubbed.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { createMockStore } from '../test-helpers/mock_store.js'

const modalOpen = vi.fn()
const modalClose = vi.fn()
vi.mock('./primitives/modal.js', () => ({
  createModal: vi.fn(() => ({ open: modalOpen, close: modalClose })),
}))
// createButton returns an object whose .click() invokes the wired onClick (mirrors
// the real button) so the Apply path and the Enter-to-commit path both work.
vi.mock('./primitives/button.js', () => ({
  createButton: vi.fn(({ onClick }) => ({ __onClick: onClick, click: () => onClick?.() })),
}))
const showToast = vi.fn()
vi.mock('./toast.js', () => ({ showToast: (...a) => showToast(...a) }))

import { initScaffoldModal } from './scaffold_modal.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'

// A scaffold with one 10-nt forward domain.
function designWithScaffold() {
  return {
    helices: [],
    strands: [{ strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 9 }] }],
  }
}

function mountModalDom() {
  const els = mountIds({ 'menu-seq-assign-scaffold': 'button', 'assign-scaffold-modal-body': 'div' })
  els['assign-scaffold-modal-body'].innerHTML = `
    <input type="radio" name="asc-scaffold" value="M13mp18" checked>
    <input type="radio" name="asc-scaffold" value="p8064">
    <div id="asc-length-line"></div>
    <textarea id="asc-custom-seq"></textarea>
    <span id="asc-custom-char-count"></span>
    <span id="asc-custom-error"></span>
    <div id="asc-warning"></div>`
  return els
}

function makeDeps(overrides = {}) {
  return {
    store: createMockStore({ currentDesign: designWithScaffold() }),
    api: {
      assignScaffoldSequence: vi.fn(async () => ({ padded_nt: 0 })),
      syncScaffoldSequenceResponse: vi.fn(async () => {}),
    },
    showProgress: vi.fn(),
    hideProgress: vi.fn(),
    getUndefinedHighlightOn: vi.fn(() => false),
    refreshUndefinedHighlight: vi.fn(),
    ...overrides,
  }
}

// Find the Apply button object that createButton produced.
function applyButton() {
  const call = createButton.mock.calls.find(([opts]) => opts.label === 'Apply')
  return createButton.mock.results[createButton.mock.calls.indexOf(call)].value
}

describe('initScaffoldModal (factory)', () => {
  let els
  beforeEach(() => {
    vi.clearAllMocks()
    els = mountModalDom()
  })
  afterEach(() => clearDom())

  it('returns an openModal API and wires the menu listener', () => {
    const api = initScaffoldModal(makeDeps())
    expect(typeof api.openModal).toBe('function')
    els['menu-seq-assign-scaffold'].dispatchEvent(new Event('click'))
    expect(createModal).toHaveBeenCalledTimes(1)
    expect(modalOpen).toHaveBeenCalledTimes(1)
  })

  it('openModal with no design shows an error toast and builds nothing', () => {
    const deps = makeDeps({ store: createMockStore({ currentDesign: null }) })
    initScaffoldModal(deps).openModal()
    expect(showToast).toHaveBeenCalledWith('No design loaded.', { severity: 'error' })
    expect(createModal).not.toHaveBeenCalled()
  })

  it('openModal sets the scaffold-length line from countScaffoldNt and reveals the body', () => {
    initScaffoldModal(makeDeps()).openModal()
    expect(els['assign-scaffold-modal-body'].hasAttribute('hidden')).toBe(false)
    expect(document.getElementById('asc-length-line').textContent).toBe('Scaffold length: 10 nt')
    expect(modalOpen).toHaveBeenCalledTimes(1)
  })

  it('builds the modal only once across repeated opens', () => {
    const api = initScaffoldModal(makeDeps())
    api.openModal()
    api.openModal()
    expect(createModal).toHaveBeenCalledTimes(1)
    expect(modalOpen).toHaveBeenCalledTimes(2)
  })

  it('Apply posts the chosen reference scaffold + threads the target strand id', async () => {
    const deps = makeDeps()
    const api = initScaffoldModal(deps)
    api.openModal('strand-7')
    await applyButton().__onClick()
    expect(deps.api.assignScaffoldSequence).toHaveBeenCalledWith('M13mp18', {
      customSequence: null,
      strandId: 'strand-7',
    })
    expect(deps.api.syncScaffoldSequenceResponse).toHaveBeenCalled()
    expect(modalClose).toHaveBeenCalled()
  })

  it('Apply sends the custom sequence (uppercased, whitespace-stripped) when present', async () => {
    const deps = makeDeps()
    const api = initScaffoldModal(deps)
    api.openModal()
    document.getElementById('asc-custom-seq').value = ' acgt acgt '
    await applyButton().__onClick()
    expect(deps.api.assignScaffoldSequence).toHaveBeenCalledWith('M13mp18', {
      customSequence: 'ACGTACGT',
      strandId: null,
    })
  })

  it('Apply is blocked when the custom sequence has flagged invalid characters', async () => {
    const deps = makeDeps()
    const api = initScaffoldModal(deps)
    api.openModal()
    const seq = document.getElementById('asc-custom-seq')
    seq.value = 'ACXZ'
    seq.dispatchEvent(new Event('input')) // populates #asc-custom-error
    expect(document.getElementById('asc-custom-error').textContent).toContain('Invalid')
    await applyButton().__onClick()
    expect(deps.api.assignScaffoldSequence).not.toHaveBeenCalled()
  })

  it('refreshes undefined highlight after apply only when it is on', async () => {
    const onDeps = makeDeps({ getUndefinedHighlightOn: vi.fn(() => true) })
    const api = initScaffoldModal(onDeps)
    api.openModal()
    await applyButton().__onClick()
    expect(onDeps.refreshUndefinedHighlight).toHaveBeenCalledTimes(1)

    vi.clearAllMocks()
    els = mountModalDom()
    const offDeps = makeDeps({ getUndefinedHighlightOn: vi.fn(() => false) })
    const api2 = initScaffoldModal(offDeps)
    api2.openModal()
    await applyButton().__onClick()
    expect(offDeps.refreshUndefinedHighlight).not.toHaveBeenCalled()
  })

  it('failed assign surfaces an error toast and skips the sync', async () => {
    const deps = makeDeps({
      api: {
        assignScaffoldSequence: vi.fn(async () => null),
        syncScaffoldSequenceResponse: vi.fn(async () => {}),
      },
      store: createMockStore({ currentDesign: designWithScaffold(), lastError: { message: 'boom' } }),
    })
    const api = initScaffoldModal(deps)
    api.openModal()
    await applyButton().__onClick()
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('boom'), { severity: 'error' })
    expect(deps.api.syncScaffoldSequenceResponse).not.toHaveBeenCalled()
  })

  it('changing the scaffold radio recomputes the over-length warning', () => {
    // 8000-nt scaffold exceeds p8064? no — use a design longer than M13mp18 (7249).
    const big = {
      helices: [],
      strands: [{ strand_type: 'scaffold', domains: [{ helix_id: 0, direction: 'FORWARD', start_bp: 0, end_bp: 7299 }] }],
    }
    initScaffoldModal(makeDeps({ store: createMockStore({ currentDesign: big }) })).openModal()
    const warn = document.getElementById('asc-warning')
    expect(warn.textContent).toContain('exceeds M13mp18') // 7300 > 7249
    // Switch to p8064 (8064 nt) → fits → warning clears.
    document.querySelector('input[value="M13mp18"]').checked = false
    const p8064 = document.querySelector('input[value="p8064"]')
    p8064.checked = true
    p8064.dispatchEvent(new Event('change'))
    expect(warn.style.display).toBe('none')
  })
})
