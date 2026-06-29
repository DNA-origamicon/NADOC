import { describe, it, expect, beforeAll, vi } from 'vitest'

// Mock the mutating endpoints so blur / Gen / Bound-toggle don't hit the network.
vi.mock('../api/client.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    patchOverhangConnection: vi.fn(async () => ({})),
    patchOverhangBinding: vi.fn(async () => ({})),
    generateRandomSequence: vi.fn(async () => 'ACGTACGT'),
  }
})

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { patchOverhangConnection, patchOverhangBinding, generateRandomSequence } from '../api/client.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

const OH1 = { id: 'ovhg_h1_5_5p', label: 'OH1', sequence: 'ACGT', sub_domains: [{ id: 'sdA', start_bp_offset: 0, length_bp: 4 }] }
const OH2 = { id: 'ovhg_h2_9_3p', label: 'OH2', sequence: 'TTTT', sub_domains: [{ id: 'sdB', start_bp_offset: 0, length_bp: 4 }] }
const CONN = {
  id: 'c1', name: 'L1', linker_type: 'ss', length_value: 4, length_unit: 'bp',
  overhang_a_id: 'ovhg_h1_5_5p', overhang_a_attach: 'free_end',
  overhang_b_id: 'ovhg_h2_9_3p', overhang_b_attach: 'root',
  bridge_sequence: 'GGGG',
}
const LNK_STRAND = {
  id: '__lnk__c1__s',
  domains: [
    { helix_id: 'h1', start_bp: 0, end_bp: 3 },        // complement A
    { helix_id: '__lnk__c1', start_bp: 0, end_bp: 3 }, // bridge
    { helix_id: 'h2', start_bp: 0, end_bp: 3 },        // complement B
  ],
}
const BINDING = {
  id: 'b1', name: 'B1', bound: false,
  sub_domain_a_id: 'sdA', sub_domain_b_id: 'sdB',
  overhang_a_id: 'ovhg_h1_5_5p', overhang_b_id: 'ovhg_h2_9_3p',
}

const rows = () => [...document.getElementById('oconn-list').querySelectorAll('.oconn-row')]
const details = () => document.getElementById('oconn-details')

describe('overhang connections — selected-row sequence + backend wiring', () => {
  let store
  beforeAll(() => {
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-list': 'div', 'oconn-details': 'div', 'oconn-popover': 'div',
    })
    store = createMockStore({
      currentDesign: {
        overhangs: [OH1, OH2], strands: [LNK_STRAND],
        overhang_connections: [CONN], overhang_bindings: [BINDING],
      },
    })
    initOverhangConnectionsPanel({ store })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // expand
  })

  it('selecting a linker row shows its sequence + bridge editor', () => {
    rows().find(r => r.textContent.includes('L1')).dispatchEvent(new Event('click', { bubbles: true }))
    expect(details().hidden).toBe(false)
    // RC(ACGT)=ACGT (A, cyan) + GGGG (bridge) + RC(TTTT)=AAAA (B, magenta)
    expect(details().textContent).toContain('GGGG')
    expect(details().textContent).toContain('AAAA')
    const input = document.getElementById('oconn-bridge-input')
    expect(input).not.toBeNull()
    expect(input.value).toBe('GGGG')
  })

  it('editing the bridge input commits via patchOverhangConnection', async () => {
    const input = document.getElementById('oconn-bridge-input')
    input.dispatchEvent(new Event('focus'))
    input.value = 'acgt'
    input.dispatchEvent(new Event('blur'))
    await Promise.resolve(); await Promise.resolve()
    expect(patchOverhangConnection).toHaveBeenCalledWith('c1', { bridge_sequence: 'ACGT' })
  })

  it('Gen generates a random bridge of the linker length and patches it', async () => {
    document.querySelector('#oconn-details button').dispatchEvent(new Event('click'))
    await Promise.resolve(); await Promise.resolve()
    expect(generateRandomSequence).toHaveBeenCalledWith(4)
    expect(patchOverhangConnection).toHaveBeenCalledWith('c1', { bridge_sequence: 'ACGTACGT' })
  })

  it('selecting a binding row shows sub-domain seqs + a Bound toggle', () => {
    rows().find(r => r.textContent.includes('B1')).dispatchEvent(new Event('click', { bubbles: true }))
    expect(details().textContent).toContain('ACGT')   // sub_domain A = OH1 sliced
    expect(details().textContent).toContain('TTTT')   // sub_domain B = OH2 sliced
    const cb = details().querySelector('input[type="checkbox"]')
    expect(cb).not.toBeNull()
    expect(cb.checked).toBe(false)
  })

  it('toggling Bound commits via patchOverhangBinding', async () => {
    const cb = details().querySelector('input[type="checkbox"]')
    cb.checked = true
    cb.dispatchEvent(new Event('change'))
    await Promise.resolve(); await Promise.resolve()
    expect(patchOverhangBinding).toHaveBeenCalledWith('b1', { bound: true })
  })
})
