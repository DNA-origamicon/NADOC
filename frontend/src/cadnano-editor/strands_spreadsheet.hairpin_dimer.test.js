// @vitest-environment jsdom
/** Hairpin/self-dimer ⚠ in the cadnano editor's strand spreadsheet ID column. */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds } from '../test-helpers/factory_dom.js'
import { makeDesign, makeReport } from '../test-helpers/hairpin_dimer_fixture.js'

vi.mock('./api.js', () => ({
  patchStrand: vi.fn(), patchOverhang: vi.fn(), generateOverhangRandomSequence: vi.fn(),
}))
vi.mock('../ui/toast.js', () => ({ showToast: vi.fn() }))

import { initStrandsSpreadsheet } from './strands_spreadsheet.js'

const idCell = id => [...document.querySelectorAll('#spreadsheet-tbody tr')]
  .map(tr => tr.querySelector('td[data-col="id"]'))
  .find(td => td?.title === id)

let report
let sheet
beforeEach(() => {
  localStorage.clear()
  mountIds({
    'spreadsheet-panel': 'div', 'spreadsheet-body': 'div',
    'spreadsheet-thead-row': 'tr', 'spreadsheet-tbody': 'tbody',
    'spreadsheet-col-toggles': 'div', 'sheet-edge': 'div', 'sheet-toggle': 'button',
  })
  report = null
  sheet = initStrandsSpreadsheet({ getHairpinDimerReport: () => report })
  sheet.toggle()
  sheet.update(makeDesign())
})

describe('cadnano spreadsheet hairpin/dimer warnings', () => {
  it('marks flagged strands on the next update after a report arrives', () => {
    expect(document.querySelector('.hd-warn-icon')).toBeNull()
    report = makeReport()
    sheet.update(makeDesign())
    expect(idCell('s_a').querySelector('.hd-warn-icon')?.title).toContain('hairpin Tm 96.6 °C')
    expect(idCell('s_b').querySelector('.hd-warn-icon')).toBeNull()
    idCell('s_a').querySelector('.hd-warn-icon').click()
    expect(document.querySelector('.hd-window .hd-structure--hairpin')).toBeTruthy()
    document.querySelector('.hd-window .modal__close').click()
  })
})
