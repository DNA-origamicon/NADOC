// @vitest-environment jsdom
/** Hairpin/self-dimer ⚠ in the strand spreadsheet's ID column (3D editor). */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds } from '../test-helpers/factory_dom.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { LINKER, OA, makeDesign, makeReport } from '../test-helpers/hairpin_dimer_fixture.js'

vi.mock('../api/client.js', () => new Proxy({}, { get: () => vi.fn(async () => ({})) }))
vi.mock('./toast.js', () => ({ showToast: vi.fn() }))
vi.mock('../state/store.js', () => ({ pushGroupUndo: vi.fn() }))

import { initSpreadsheet } from './spreadsheet.js'

const idCell = id => document.querySelector(`tr[data-strand-id="${id}"] td[data-col="id"]`)

let store
beforeEach(() => {
  localStorage.clear()
  mountIds({
    'spreadsheet-panel': 'div', 'spreadsheet-body': 'div',
    'spreadsheet-thead-row': 'tr', 'spreadsheet-tbody': 'tbody',
    'spreadsheet-col-toggles': 'div', 'sheet-edge': 'div', 'sheet-toggle': 'button',
  })
  store = createMockStore({ currentDesign: null, hairpinDimerReport: null })
  initSpreadsheet(store, { goToStrand: vi.fn() }).toggle()
  store.setState({ currentDesign: makeDesign() })
})

describe('spreadsheet hairpin/dimer warnings', () => {
  it('shows no icon before a check has run', () => {
    expect(document.querySelector('.hd-warn-icon')).toBeNull()
  })

  it('marks exactly the flagged strands once a report arrives', () => {
    store.setState({ hairpinDimerReport: makeReport() })
    expect(idCell('s_a').querySelector('.hd-warn-icon').title).toContain('Overhang OH-A (22 nt): hairpin Tm 96.6 °C')
    expect(idCell(LINKER).querySelector('.hd-warn-icon')).toBeTruthy()
    expect(idCell('s_b').querySelector('.hd-warn-icon')).toBeNull()
    expect(idCell('s_a').querySelector('.hd-warn-icon--critical')).toBeTruthy()   // 96.6 °C
  })

  it('clicking the ⚠ opens the structure window without selecting the row', () => {
    store.setState({ hairpinDimerReport: makeReport() })
    idCell('s_a').querySelector('.hd-warn-icon').click()
    const win = document.querySelector('.hd-window')
    expect(win.querySelector('.modal__title').textContent).toMatch(/secondary structure/)
    expect(win.querySelector('.hd-structure--hairpin .hd-pair--GC')).toBeTruthy()
    expect(win.querySelector('.hd-structure--dimer')).toBeTruthy()
    document.querySelector('.hd-window .modal__close').click()
    expect(document.querySelector('.hd-window')).toBeNull()
  })

  it('drops the icon when the overhang sequence is edited (stale check)', () => {
    store.setState({ hairpinDimerReport: makeReport() })
    const d = makeDesign()
    d.overhangs = d.overhangs.map(o => (o.id === OA ? { ...o, sequence: 'T'.repeat(22) } : o))
    store.setState({ currentDesign: d })
    expect(idCell('s_a').querySelector('.hd-warn-icon')).toBeNull()
  })
})
