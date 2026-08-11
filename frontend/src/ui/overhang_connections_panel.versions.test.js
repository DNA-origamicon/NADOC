import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'

vi.mock('./primitives/confirm.js', () => ({ showConfirm: vi.fn(async () => true) }))

vi.mock('../api/client.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    createConnectionVersion: vi.fn(async () => ({})),
    createAndApplyConnectionVersion: vi.fn(async () => ({})),
    patchConnectionVersion: vi.fn(async () => ({})),
    deleteConnectionVersion: vi.fn(async () => ({})),
    applyConnectionVersion: vi.fn(async () => ({})),
    createOverhangConnection: vi.fn(async () => ({})),
    createOverhangBinding: vi.fn(async () => ({})),
    deleteOverhangConnection: vi.fn(async () => ({})),
    deleteOverhangBinding: vi.fn(async () => ({})),
    patchOverhang: vi.fn(async () => ({})),
  }
})

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import {
  createConnectionVersion, createAndApplyConnectionVersion,
  patchConnectionVersion, deleteConnectionVersion,
  applyConnectionVersion, createOverhangConnection, deleteOverhangConnection,
  createOverhangBinding,
} from '../api/client.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

const A = 'ovhg_h1_5_5p', B = 'ovhg_h2_9_3p', C = 'ovhg_h3_3_5p'
const OHS = [
  { id: A, label: 'OH1', sub_domains: [{ id: 'sdA', length_bp: 4 }] },
  { id: B, label: 'OH2', sub_domains: [{ id: 'sdB', length_bp: 4 }] },
  { id: C, label: 'OH3', sub_domains: [{ id: 'sdC', length_bp: 4 }] },
]
const V = (id, applied, extra = {}) => ({
  id, name: id.toUpperCase(), created_at: id === 'v1' ? 1 : 2,
  overhang_a_id: A, overhang_b_id: B, connection_type: 'root-to-root-ssdna-linker',
  overhang_a_seq: 'ACGT', overhang_b_seq: null, bridge_length: 5, bridge_seq: null, applied, ...extra,
})
function design(versions = []) {
  return { currentDesign: { overhangs: OHS, strands: [], overhang_connections: [], overhang_bindings: [], connection_versions: versions } }
}
const $ = (id) => document.getElementById(id)
const rows = () => [...$('oconn-list').querySelectorAll('.oconn-version-row')]

describe('overhang connections — versions (Connect / Add version / Apply)', () => {
  let store
  beforeAll(() => {
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-apply': 'button', 'oconn-secondary': 'button',
      'oconn-list': 'div', 'oconn-details': 'div', 'oconn-popover': 'div',
      'oconn-seq-row-a': 'div', 'oconn-seq-input-a': 'input', 'oconn-seq-gen-a': 'button',
      'oconn-seq-row-b': 'div', 'oconn-seq-input-b': 'input', 'oconn-seq-gen-b': 'button',
      'oconn-pair-warning': 'div',
    })
    store = createMockStore(design())
    initOverhangConnectionsPanel({ store })
    $('oconn-heading').dispatchEvent(new Event('click'))   // expand
  })
  beforeEach(() => {
    for (const m of [createConnectionVersion, createAndApplyConnectionVersion, patchConnectionVersion, deleteConnectionVersion, applyConnectionVersion, createOverhangConnection, deleteOverhangConnection, createOverhangBinding]) m.mockClear()
  })

  function pickVariant(id) {
    document.querySelector(`#oconn-popover [data-variant="${id}"]`).dispatchEvent(new Event('click'))
  }

  function selectPair(a, b) {
    $('oconn-select-a').value = a; $('oconn-select-a').dispatchEvent(new Event('change'))
    $('oconn-select-b').value = b; $('oconn-select-b').dispatchEvent(new Event('change'))
  }

  it('button is "Connect" for a never-paired pair, "Add version" once a version exists', () => {
    store.setState(design([]))
    selectPair(A, C)                       // no version for A/C
    expect($('oconn-generate').textContent).toBe('Connect')
    store.setState(design([V('v1', true)]))
    selectPair(A, B)                       // A/B has a version
    expect($('oconn-generate').textContent).toBe('Add version')
  })

  it('renders a header + indented version rows with an applied badge', () => {
    store.setState(design([V('v1', true), V('v2', false)]))
    const header = $('oconn-list').querySelector('.oconn-group-header')
    expect(header.textContent).toContain('OH1')
    expect(header.textContent).toContain('OH2')
    expect(rows()).toHaveLength(2)
    const applied = rows().find(r => r.classList.contains('is-applied'))
    expect(applied.textContent).toContain('V1')
  })

  it('button is "Apply" for a draft, "Unapply" for the applied version', () => {
    store.setState(design([V('v1', true), V('v2', false)]))
    rows().find(r => r.textContent.includes('V2')).dispatchEvent(new Event('click', { bubbles: true }))
    expect($('oconn-apply').textContent).toBe('Apply')
    expect($('oconn-apply').disabled).toBe(false)
    rows().find(r => r.textContent.includes('V1')).dispatchEvent(new Event('click', { bubbles: true }))
    expect($('oconn-apply').textContent).toBe('Unapply')   // applied → can unapply
    expect($('oconn-apply').disabled).toBe(false)
  })

  it('Unapply tears down the materialization + clears the applied flag', async () => {
    store.setState({ currentDesign: {
      overhangs: OHS, strands: [],
      overhang_connections: [{
        id: 'conn_ab', overhang_a_id: A, overhang_b_id: B, linker_type: 'ss',
        length_value: 5, length_unit: 'bp', overhang_a_attach: 'free_end', overhang_b_attach: 'free_end',
      }],
      overhang_bindings: [],
      connection_versions: [V('v1', true)],   // applied A↔B (conn_ab)
    } })
    rows().find(r => r.textContent.includes('V1')).dispatchEvent(new Event('click', { bubbles: true }))
    $('oconn-apply').dispatchEvent(new Event('click'))   // "Unapply"
    await new Promise(r => setTimeout(r, 0))
    expect(deleteOverhangConnection).toHaveBeenCalledWith('conn_ab')        // torn down
    expect(patchConnectionVersion).toHaveBeenCalledWith('v1', { applied: false })
  })

  it('Apply calls the atomic backend apply endpoint for the selected version', async () => {
    store.setState(design([V('v1', true), V('v2', false)]))
    rows().find(r => r.textContent.includes('V2')).dispatchEvent(new Event('click', { bubbles: true }))
    $('oconn-apply').dispatchEvent(new Event('click'))
    await new Promise(r => setTimeout(r, 0))
    expect(applyConnectionVersion).toHaveBeenCalledWith('v2')
  })

  it('Add version creates a version then auto-applies it', async () => {
    store.setState(design([V('v1', true)]))
    selectPair(A, B)
    // mock create to add the new version so _captureVersion can find + apply it
    createConnectionVersion.mockImplementationOnce(async () => {
      store.setState(design([V('v1', true), { ...V('v2', false), id: 'vNew' }]))
    })
    $('oconn-generate').dispatchEvent(new Event('click'))   // "Add version"
    await new Promise(r => setTimeout(r, 0))
    expect(createConnectionVersion).toHaveBeenCalled()
    expect(applyConnectionVersion).toHaveBeenCalledWith('vNew')   // newest auto-applied
  })

  it('Connect delegates conflicting teardown to the atomic Apply endpoint', async () => {
    store.setState({ currentDesign: {
      overhangs: OHS, strands: [],
      overhang_connections: [{
        id: 'conn_ab', overhang_a_id: A, overhang_b_id: B, linker_type: 'ss',
        length_value: 5, length_unit: 'bp', overhang_a_attach: 'free_end', overhang_b_attach: 'free_end',
      }],
      overhang_bindings: [],
      connection_versions: [V('vab', true)],   // applied A↔B
    } })
    selectPair(B, C)                            // never-paired → "Connect"
    expect($('oconn-generate').textContent).toBe('Connect')
    $('oconn-generate').dispatchEvent(new Event('click'))
    await new Promise(r => setTimeout(r, 0))
    expect(createAndApplyConnectionVersion).toHaveBeenCalled()
    // Apply performs both operations server-side before computing final geometry.
    expect(patchConnectionVersion).not.toHaveBeenCalled()
    expect(deleteOverhangConnection).not.toHaveBeenCalled()
  })

  it('Connect for end-to-root creates a version then APPLIES it (binder splice) — not the old OverhangBinding', async () => {
    // Both 5p → end-to-root is a valid polarity (forbidden iff polarities differ).
    // A pre-sequenced so the sequence step only patches B (no random-gen network call).
    const aId = 'ovhg_h1_5_5p', bId = 'ovhg_h2_9_5p'
    const ohs = [
      { id: aId, label: 'OH1', sequence: 'AAACCCGG', sub_domains: [{ id: 'sdA', length_bp: 8 }] },
      { id: bId, label: 'OH2', sub_domains: [{ id: 'sdB', length_bp: 8 }] },
    ]
    const st = (versions) => ({ currentDesign: {
      overhangs: ohs, strands: [], overhang_connections: [], overhang_bindings: [], connection_versions: versions } })
    const vE2R = { id: 'vE2R', name: 'V1', created_at: 1, overhang_a_id: aId, overhang_b_id: bId,
      connection_type: 'end-to-root', overhang_a_seq: 'AAACCCGG', overhang_b_seq: null,
      bridge_length: 0, bridge_seq: null, applied: false }
    store.setState(st([]))
    selectPair(aId, bId)
    pickVariant('end-to-root')
    expect($('oconn-generate').textContent).toBe('Connect')      // never-paired pair
    expect($('oconn-generate').disabled).toBe(false)             // valid polarity → enabled
    $('oconn-generate').dispatchEvent(new Event('click'))        // "Connect"
    await new Promise(r => setTimeout(r, 0))
    expect(createAndApplyConnectionVersion).toHaveBeenCalled()
    expect(createAndApplyConnectionVersion.mock.calls[0][0].connection_type).toBe('end-to-root')
    expect(createOverhangBinding).not.toHaveBeenCalled()         // ← NOT the old direct-binding method
  })

  it('Connect for root-to-root creates a version then APPLIES it (same path as end-to-root) — not the old OverhangBinding', async () => {
    // root-to-root is valid iff polarities DIFFER (5p ↔ 3p). A pre-sequenced so the
    // sequence step only patches B (no random-gen network call).
    const aId = 'ovhg_h1_5_5p', bId = 'ovhg_h2_9_3p'
    const ohs = [
      { id: aId, label: 'OH1', sequence: 'AAACCCGG', sub_domains: [{ id: 'sdA', length_bp: 8 }] },
      { id: bId, label: 'OH2', sub_domains: [{ id: 'sdB', length_bp: 8 }] },
    ]
    const st = (versions) => ({ currentDesign: {
      overhangs: ohs, strands: [], overhang_connections: [], overhang_bindings: [], connection_versions: versions } })
    const vR2R = { id: 'vR2R', name: 'V1', created_at: 1, overhang_a_id: aId, overhang_b_id: bId,
      connection_type: 'root-to-root', overhang_a_seq: 'AAACCCGG', overhang_b_seq: null,
      bridge_length: 0, bridge_seq: null, applied: false }
    store.setState(st([]))
    selectPair(aId, bId)
    pickVariant('root-to-root')
    expect($('oconn-generate').textContent).toBe('Connect')      // never-paired pair
    expect($('oconn-generate').disabled).toBe(false)             // valid polarity → enabled
    $('oconn-generate').dispatchEvent(new Event('click'))        // "Connect"
    await new Promise(r => setTimeout(r, 0))
    expect(createAndApplyConnectionVersion).toHaveBeenCalled()
    expect(createAndApplyConnectionVersion.mock.calls[0][0].connection_type).toBe('root-to-root')
    expect(createOverhangBinding).not.toHaveBeenCalled()         // ← NOT the old direct-binding path
  })

  it('deleting a version row calls deleteConnectionVersion', async () => {
    store.setState(design([V('v1', true), V('v2', false)]))
    const delBtn = rows().find(r => r.textContent.includes('V2')).querySelector('.oconn-row-del')
    delBtn.dispatchEvent(new Event('click', { bubbles: true }))
    // showConfirm resolves async; flush a few microtasks
    await new Promise(r => setTimeout(r, 0))
    expect(deleteConnectionVersion).toHaveBeenCalledWith('v2')
  })
})
