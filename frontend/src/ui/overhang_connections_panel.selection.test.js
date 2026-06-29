import { describe, it, expect, beforeAll } from 'vitest'
import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

// Auto-populate-from-scene-selection behaviour (2-slot LRU). Separate file →
// fresh module instance (vitest isolates per file), so the singleton slot state
// starts clean. Tests run in order and share the singleton, so each step's
// expected slots are computed from the prior step.

const OH1 = { id: 'ovhg_h1_5_5p', label: 'OH1' }
const OH2 = { id: 'ovhg_h2_9_3p', label: 'OH2' }
const OH3 = { id: 'ovhg_h3_3_5p', label: 'OH3' }
const OH4 = { id: 'ovhg_h4_7_3p', label: 'OH4' }
// strand whose domain 0 is OH1's overhang domain — exercises the domain filter.
const STRAND = { id: 's1', domains: [{ overhang_id: 'ovhg_h1_5_5p' }] }

const A = () => document.getElementById('oconn-select-a').value
const B = () => document.getElementById('oconn-select-b').value

describe('overhang connections — auto-populate dropdowns (2-slot LRU)', () => {
  let store
  beforeAll(() => {
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-list': 'div', 'oconn-popover': 'div',
    })
    store = createMockStore({
      currentDesign: {
        overhangs: [OH1, OH2, OH3, OH4], strands: [STRAND],
        overhang_connections: [], overhang_bindings: [],
      },
    })
    initOverhangConnectionsPanel({ store })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))  // expand
  })

  // simulate a single overhang-filter click (replaces the selection with one id)
  const pick = (id) => store.setState({ multiSelectedOverhangIds: [id] })

  it('the spec example: OH1, OH2, OH3, OH4 sequential', () => {
    pick('ovhg_h1_5_5p')                       // empty,empty → A
    expect([A(), B()]).toEqual(['ovhg_h1_5_5p', ''])
    pick('ovhg_h2_9_3p')                       // A full, B empty → B
    expect([A(), B()]).toEqual(['ovhg_h1_5_5p', 'ovhg_h2_9_3p'])
    pick('ovhg_h3_3_5p')                       // both full → evict older (A)
    expect([A(), B()]).toEqual(['ovhg_h3_3_5p', 'ovhg_h2_9_3p'])   // A=OH3, B=OH2
    pick('ovhg_h4_7_3p')                       // both full → evict older (B)
    expect([A(), B()]).toEqual(['ovhg_h3_3_5p', 'ovhg_h4_7_3p'])   // A=OH3, B=OH4
  })

  it('ctrl/shift add evicts the older-shown slot', () => {
    // establish a clean A=OH1, B=OH2 first
    store.setState({ multiSelectedOverhangIds: ['ovhg_h1_5_5p', 'ovhg_h2_9_3p'] })
    expect([A(), B()]).toEqual(['ovhg_h1_5_5p', 'ovhg_h2_9_3p'])
    // ctrl-add OH3 (one new id) → evicts the older slot (A)
    store.setState({ multiSelectedOverhangIds: ['ovhg_h1_5_5p', 'ovhg_h2_9_3p', 'ovhg_h3_3_5p'] })
    expect([A(), B()]).toEqual(['ovhg_h3_3_5p', 'ovhg_h2_9_3p'])
  })

  it('re-picking an already-shown overhang is a no-op', () => {
    // current: A=OH3, B=OH2. Re-select OH2 alone → stays put.
    pick('ovhg_h2_9_3p')
    expect([A(), B()]).toEqual(['ovhg_h3_3_5p', 'ovhg_h2_9_3p'])
  })

  it('domain-filter selection (multiSelectedDomainIds → overhang_id) feeds a slot', () => {
    // current: A=OH3, B=OH2. Select OH1 via a domain ref → evicts the older slot.
    store.setState({
      multiSelectedOverhangIds: [],
      multiSelectedDomainIds: [{ strandId: 's1', domainIndex: 0 }],
      selectedObject: null,
    })
    expect([A(), B()]).toContain('ovhg_h1_5_5p')
  })

  it('does NOT touch the dropdowns while collapsed, then snaps on open', () => {
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // collapse
    expect(document.getElementById('oconn-body').style.display).toBe('none')
    document.getElementById('oconn-select-a').value = ''
    document.getElementById('oconn-select-b').value = ''
    store.setState({
      multiSelectedOverhangIds: ['ovhg_h2_9_3p', 'ovhg_h4_7_3p'],
      multiSelectedDomainIds: [], selectedObject: null,
    })
    expect([A(), B()]).toEqual(['', ''])                 // unchanged while collapsed
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // expand
    expect(A()).not.toBe('')                             // snapped to current selection
    expect(B()).not.toBe('')
  })
})
