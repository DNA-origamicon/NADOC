import { describe, it, expect, beforeAll } from 'vitest'

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

// Phase 2: the per-side preview reads the STORED duplex register (not the
// attach-anchored heuristic). ohA (6 bp) is paired to ohB over a 4 bp window →
// the preview must colour AAAC as paired (green) and the GG tail as toehold (grey).

const IDA = 'ohA', IDB = 'ohB'

function design() {
  return {
    currentDesign: {
      strands: [
        { id: 'sa', domains: [{ helix_id: 'hA', start_bp: 0, end_bp: 5, overhang_id: IDA }] },
        { id: 'sb', domains: [{ helix_id: 'hB', start_bp: 5, end_bp: 0, overhang_id: IDB }] },
      ],
      overhangs: [
        { id: IDA, label: 'OH-A', sequence: 'AAACGG', sub_domains: [{ id: 'sdA', start_bp_offset: 0, length_bp: 6 }] },
        { id: IDB, label: 'OH-B', sequence: 'GTTTCC', sub_domains: [{ id: 'sdB', start_bp_offset: 0, length_bp: 6 }] },
      ],
      overhang_connections: [], overhang_bindings: [], connection_versions: [],
      duplexes: [{
        id: 'd1', name: 'D1',
        left: { overhang_id: IDA, start_bp: 0, end_bp: 3 },
        right: { overhang_id: IDB, start_bp: 5, end_bp: 2 },
        driver: 'left', bound: false, allow_n_wildcard: true,
      }],
    },
  }
}

const prevA = () => document.getElementById('oconn-seq-row-a').nextElementSibling
const spans = (el) => [...el.querySelectorAll('span')]

describe('overhang connections — per-side preview reads the duplex register', () => {
  let store
  beforeAll(() => {
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-list': 'div', 'oconn-details': 'div', 'oconn-popover': 'div',
      'oconn-seq-row-a': 'div', 'oconn-seq-input-a': 'input', 'oconn-seq-gen-a': 'button',
      'oconn-seq-row-b': 'div', 'oconn-seq-input-b': 'input', 'oconn-seq-gen-b': 'button',
      'oconn-pair-warning': 'div',
    })
    store = createMockStore(design())
    initOverhangConnectionsPanel({ store })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))   // expand
    const a = document.getElementById('oconn-select-a'); a.value = IDA; a.dispatchEvent(new Event('change'))
    const b = document.getElementById('oconn-select-b'); b.value = IDB; b.dispatchEvent(new Event('change'))
  })

  it('colours the paired window green and the toehold tail grey', () => {
    const ss = spans(prevA())
    const paired = ss.find(s => s.textContent === 'AAAC')
    const toehold = ss.find(s => s.textContent === 'GG')
    expect(paired?.style.color).toBe('rgb(63, 185, 80)')    // #3fb950 paired
    expect(toehold?.style.color).toBe('rgb(139, 148, 158)') // #8b949e toehold
  })
})
