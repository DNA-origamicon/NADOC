import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'

vi.mock('../api/client.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    patchOverhangBinding: vi.fn(async () => ({})),
    relaxLinker: vi.fn(async () => ({})),
    relaxOverhangBinding: vi.fn(async () => ({})),
  }
})

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { relaxLinker, patchOverhangBinding, relaxOverhangBinding } from '../api/client.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

const IDA = 'ovhg_h1_5_5p', IDB = 'ovhg_h2_9_3p'
const OHS = [
  { id: IDA, label: 'OH1', sub_domains: [{ id: 'sdA', start_bp_offset: 0, length_bp: 4 }] },
  { id: IDB, label: 'OH2', sub_domains: [{ id: 'sdB', start_bp_offset: 0, length_bp: 4 }] },
]
const BINDING = (bound) => ({
  id: 'b1', name: 'B1', bound, overhang_a_id: IDA, overhang_b_id: IDB,
  sub_domain_a_id: 'sdA', sub_domain_b_id: 'sdB',
})
const LINKER = {
  id: 'c1', name: 'L1', linker_type: 'ds', length_value: 12, length_unit: 'bp',
  overhang_a_id: IDA, overhang_a_attach: 'root', overhang_b_id: IDB, overhang_b_attach: 'root',
}
function design({ bindings = [], connections = [] } = {}) {
  return { currentDesign: { overhangs: OHS, strands: [], overhang_connections: connections, overhang_bindings: bindings } }
}
const sec = () => document.getElementById('oconn-secondary')

describe('overhang connections — Bind / Relax secondary button', () => {
  let store
  beforeAll(() => {
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-secondary': 'button',
      'oconn-list': 'div', 'oconn-details': 'div', 'oconn-popover': 'div',
      'oconn-seq-row-a': 'div', 'oconn-seq-input-a': 'input', 'oconn-seq-gen-a': 'button',
      'oconn-seq-row-b': 'div', 'oconn-seq-input-b': 'input', 'oconn-seq-gen-b': 'button',
      'oconn-pair-warning': 'div',
    })
    store = createMockStore(design())
    initOverhangConnectionsPanel({ store })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // expand
  })
  beforeEach(() => { relaxLinker.mockClear(); patchOverhangBinding.mockClear(); relaxOverhangBinding.mockClear() })

  function setup(state, variant) {
    store.setState(design(state))
    const a = document.getElementById('oconn-select-a'); a.value = IDA; a.dispatchEvent(new Event('change'))
    const b = document.getElementById('oconn-select-b'); b.value = IDB; b.dispatchEvent(new Event('change'))
    document.querySelector(`#oconn-popover [data-variant="${variant}"]`).dispatchEvent(new Event('click'))
  }

  it('direct (unbound) → "Relax" moves the clusters then binds', async () => {
    setup({ bindings: [BINDING(false)] }, 'root-to-root')
    expect(sec().textContent).toBe('Relax')
    expect(sec().disabled).toBe(false)
    sec().dispatchEvent(new Event('click'))
    await new Promise(r => setTimeout(r, 0))
    expect(relaxOverhangBinding).toHaveBeenCalledWith('b1')                  // cluster move only
    expect(patchOverhangBinding).toHaveBeenCalledWith('b1', { bound: true }) // relocate
  })

  it('direct + already-bound → "Relax" un-relocates, moves, re-relocates', async () => {
    setup({ bindings: [BINDING(true)] }, 'root-to-root')
    sec().dispatchEvent(new Event('click'))
    await new Promise(r => setTimeout(r, 0))
    expect(patchOverhangBinding).toHaveBeenCalledWith('b1', { bound: false })  // un-relocate first
    expect(relaxOverhangBinding).toHaveBeenCalledWith('b1')
    expect(patchOverhangBinding).toHaveBeenCalledWith('b1', { bound: true })   // re-relocate
  })

  it('end-to-root → "Relax" is inert (behavior removed — clean slate)', async () => {
    setup({ bindings: [BINDING(false)] }, 'end-to-root')
    expect(sec().textContent).toBe('Relax')
    expect(sec().disabled).toBe(true)
    sec().dispatchEvent(new Event('click'))
    await new Promise(r => setTimeout(r, 0))
    expect(relaxOverhangBinding).not.toHaveBeenCalled()
    expect(patchOverhangBinding).not.toHaveBeenCalled()
  })

  it('direct + no binding yet → "Relax" disabled', () => {
    setup({}, 'root-to-root')
    expect(sec().textContent).toBe('Relax')
    expect(sec().disabled).toBe(true)
  })

  it('linker type → "Relax"; click relaxes the pair linker', async () => {
    setup({ connections: [LINKER] }, 'root-to-root-dsdna-linker')
    expect(sec().textContent).toBe('Relax')
    expect(sec().disabled).toBe(false)
    sec().dispatchEvent(new Event('click'))
    await Promise.resolve()
    expect(relaxLinker).toHaveBeenCalledWith('c1')
  })

  it('linker type + no linker for the pair → Relax disabled', () => {
    setup({}, 'root-to-root-dsdna-linker')
    expect(sec().textContent).toBe('Relax')
    expect(sec().disabled).toBe(true)
  })
})
