import { describe, it, expect, beforeAll } from 'vitest'

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

// Per-side sequence PREVIEW lines (`.oconn-seq-preview`): N-padding to the
// CURRENT backing-domain length + complementary coloring for a direct pair.
// OH-A's backing domain is 6 bp but its sequence is only 4 nt (AAAC) → the
// preview must reveal the 2 undefined tail bases as 'N' (excess), not hide them.

const IDA = 'ovhg_h1_5_5p', IDB = 'ovhg_h2_9_3p'
const PAIR_EXCESS = '#8b949e'
const PAIR_PAIRED = '#3fb950'

function design() {
  return {
    currentDesign: {
      overhangs: [
        { id: IDA, label: 'OH-A', sequence: 'AAAC', sub_domains: [{ id: 'sdA', start_bp_offset: 0, length_bp: 4 }] },
        { id: IDB, label: 'OH-B', sequence: 'GTTT', sub_domains: [{ id: 'sdB', start_bp_offset: 0, length_bp: 4 }] },
      ],
      // OH-A's backing domain was dragged out to 6 bp (start..end inclusive).
      strands: [{ id: 'st1', domains: [{ overhang_id: IDA, start_bp: 0, end_bp: 5 }] }],
      overhang_connections: [], overhang_bindings: [],
    },
  }
}

const prevA = () => document.getElementById('oconn-seq-row-a').nextElementSibling
const spans = (el) => [...el.querySelectorAll('span')]

describe('overhang connections — per-side sequence preview (N + pairing colors)', () => {
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
    // Select both overhangs + a direct (root-to-root) variant.
    const a = document.getElementById('oconn-select-a'); a.value = IDA; a.dispatchEvent(new Event('change'))
    const b = document.getElementById('oconn-select-b'); b.value = IDB; b.dispatchEvent(new Event('change'))
    document.querySelector('#oconn-popover [data-variant="root-to-root"]').dispatchEvent(new Event('click'))
  })

  it('reveals the dragged-longer tail as N in the preview', () => {
    expect(prevA().classList.contains('oconn-seq-preview')).toBe(true)
    expect(prevA().textContent).toContain('AAACNN')   // 4 defined + 2 undefined
  })

  it('colors the complementary bases paired (green) and the excess tail grey', () => {
    const ss = spans(prevA())
    const paired = ss.find(s => s.textContent === 'AAAC')
    const excess = ss.find(s => s.textContent === 'NN')
    expect(paired?.style.color).toBe('rgb(63, 185, 80)')   // #3fb950
    expect(excess?.style.color).toBe('rgb(139, 148, 158)') // #8b949e
    // sanity: the constants the panel uses
    expect(PAIR_PAIRED).toBe('#3fb950')
    expect(PAIR_EXCESS).toBe('#8b949e')
  })
})
