import { describe, it, expect, beforeAll, vi } from 'vitest'

// Phase 4 (Q4): the driver toggle lets the user pick which overhang's helix hosts
// the duplex. Mock patchDuplex so the click is asserted without a backend.
vi.mock('../api/client.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, patchDuplex: vi.fn(async () => ({})) }
})

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { patchDuplex } from '../api/client.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'

const IDA = 'ohA', IDB = 'ohB'

function design() {
  return {
    currentDesign: {
      strands: [
        { id: 'sa', domains: [{ helix_id: 'hA', start_bp: 0, end_bp: 5, overhang_id: IDA }] },
        { id: 'sb', domains: [{ helix_id: 'hB', start_bp: 5, end_bp: 0, overhang_id: IDB }] },
      ],
      overhangs: [
        { id: IDA, label: 'OH-A', sequence: 'AAACGG' },
        { id: IDB, label: 'OH-B', sequence: 'GTTTCC' },
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

const driverBtns = () => [...document.querySelectorAll('.oconn-driver-box button')]

describe('overhang connections — driver toggle (Q4)', () => {
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
  })

  it('shows two driver buttons with the current driver (A) highlighted', () => {
    const btns = driverBtns()
    expect(btns.map(b => b.textContent)).toEqual(['OH-A', 'OH-B'])
    expect(btns[0].style.color).toBe('rgb(255, 255, 255)')   // active driver = white text on blue
    expect(btns[1].style.color).toBe('rgb(201, 209, 217)')   // inactive
  })

  it('clicking the other overhang patches the duplex driver', async () => {
    driverBtns()[1].dispatchEvent(new Event('click', { bubbles: true }))
    await Promise.resolve()
    expect(patchDuplex).toHaveBeenCalledWith('d1', { driver: 'right' })
  })
})
