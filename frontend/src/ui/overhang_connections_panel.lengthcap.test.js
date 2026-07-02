import { describe, it, expect, beforeAll, vi } from 'vitest'

// Regression: connecting two DIFFERENT-length overhangs must NOT grow the shorter
// one. The complementary-sequence write is capped to the target overhang's own
// backing-domain length, so `patchOverhang` never resizes it.
vi.mock('../api/client.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    patchOverhang: vi.fn(async () => ({})),
    generateOverhangRandomSequence: vi.fn(async () => ({})),
  }
})

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { patchOverhang } from '../api/client.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

const IDA = 'ohA', IDB = 'ohB'   // A = 24 bp (sequenced), B = 10 bp (empty)

function design() {
  return {
    currentDesign: {
      strands: [
        { id: 'sa', domains: [{ helix_id: 'hA', start_bp: 0, end_bp: 23, overhang_id: IDA }] },  // 24 bp
        { id: 'sb', domains: [{ helix_id: 'hB', start_bp: 0, end_bp: 9, overhang_id: IDB }] },    // 10 bp
      ],
      overhangs: [
        { id: IDA, label: 'OH-A', sequence: 'ACGTACGTACGTACGTACGTACGT', sub_domains: [{ id: 'sdA', start_bp_offset: 0, length_bp: 24 }] },
        { id: IDB, label: 'OH-B', sequence: null, sub_domains: [{ id: 'sdB', start_bp_offset: 0, length_bp: 10 }] },
      ],
      overhang_connections: [], overhang_bindings: [], connection_versions: [], duplexes: [],
    },
  }
}

describe('overhang connections — connecting different-length overhangs preserves length', () => {
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
    const store = createMockStore(design())
    initOverhangConnectionsPanel({ store })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))
    const a = document.getElementById('oconn-select-a'); a.value = IDA; a.dispatchEvent(new Event('change'))
    const b = document.getElementById('oconn-select-b'); b.value = IDB; b.dispatchEvent(new Event('change'))
    // Pick a direct type so Gen fills the complement.
    document.querySelector('#oconn-popover [data-variant="root-to-root"]').dispatchEvent(new Event('click'))
  })

  it('Gen on the 10 bp side fills a 10-base RC of the 24 bp partner (not 24)', async () => {
    document.getElementById('oconn-seq-gen-b').dispatchEvent(new Event('click'))
    await Promise.resolve(); await Promise.resolve()
    expect(patchOverhang).toHaveBeenCalled()
    const [id, patch] = patchOverhang.mock.calls[patchOverhang.mock.calls.length - 1]
    expect(id).toBe(IDB)
    expect(patch.sequence).toHaveLength(10)   // capped to B's length — no resize
  })
})
