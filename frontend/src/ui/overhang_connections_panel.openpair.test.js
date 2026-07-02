import { describe, it, expect, beforeAll } from 'vitest'

import { initOverhangConnectionsPanel, openConnectionForPair } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

// Fresh module → clean singleton. Drives the link-icon entry point from the
// Overhangs list: openConnectionForPair(a, b) should expand the section, set the
// dropdowns to the pair, and select the pair's APPLIED version.

const A = 'ovhg_h1_5_5p', B = 'ovhg_h2_9_3p'
const OHS = [{ id: A, label: 'OH1' }, { id: B, label: 'OH2' }]
const V = (id, applied) => ({
  id, name: id.toUpperCase(), created_at: id === 'v1' ? 1 : 2,
  overhang_a_id: A, overhang_b_id: B, connection_type: 'root-to-root',
  overhang_a_seq: 'ACGT', overhang_b_seq: 'ACGT', bridge_length: 0, bridge_seq: null, applied,
})
const $ = (id) => document.getElementById(id)

describe('openConnectionForPair (link-icon entry point)', () => {
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
    store = createMockStore({
      currentDesign: {
        overhangs: OHS, strands: [],
        overhang_connections: [], overhang_bindings: [],
        connection_versions: [V('v1', false), V('v2', true)],   // v2 applied
      },
    })
    initOverhangConnectionsPanel({ store })
    // Section starts collapsed; the entry point must expand it itself.
    expect($('oconn-body').style.display).toBe('none')
  })

  it('expands the section, sets both dropdowns, and selects the applied version', () => {
    openConnectionForPair(A, B)
    expect($('oconn-body').style.display).not.toBe('none')   // expanded
    expect($('oconn-select-a').value).toBe(A)
    expect($('oconn-select-b').value).toBe(B)
    // Applied version (v2) drives the Apply button → "Unapply" only when the
    // selected/applied version is materialized.
    expect($('oconn-apply').textContent).toBe('Unapply')
  })

  it('no-ops cleanly for a pair with no connection rows', () => {
    expect(() => openConnectionForPair('nope', 'nada')).not.toThrow()
    expect($('oconn-select-a').value).toBe('')   // unknown id → blank
  })
})
