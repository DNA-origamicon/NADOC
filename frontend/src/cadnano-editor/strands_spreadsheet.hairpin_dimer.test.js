// @vitest-environment jsdom
/** Hairpin/self-dimer ⚠ in the cadnano editor's strand spreadsheet ID column. */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mountIds } from '../test-helpers/factory_dom.js'
import { makeDesign, makeReport } from '../test-helpers/hairpin_dimer_fixture.js'
import { junctionFixture } from '../test-helpers/strand_junction_fixture.js'

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
  it('updates sections within the same strand and clears them for whole-strand selection', () => {
    Element.prototype.scrollIntoView = vi.fn()
    sheet.update(junctionFixture().design)
    sheet.setSelectedStrands(['s'], [{ kind: 'domain', strandId: 's', domainIndex: 1 }])
    const marked = () => [...document.querySelectorAll('.sheet-seq-selected-base')].map(el => el.textContent).join('')
    expect(marked()).toBe('GCA')
    sheet.setSelectedStrands(['s'], [{ kind: 'crossover', id: 'xo' }])
    expect(marked()).toBe('GATTTTTG')
    sheet.setSelectedStrands(['s'])
    expect(marked()).toBe('')
  })

  it('shares continuous extra-base sequence and arc decoration with the 3D sheet', () => {
    sheet.update(junctionFixture(true).design)
    const cell = document.querySelector('td[data-col="sequence"]')
    expect(cell.dataset.searchSequence).toBe('ACGATTTTTGCA')
    expect(cell.querySelector('.sheet-seq').textContent).toBe('ACGATTTTTGCA')
    expect(cell.querySelector('.sheet-seq-extra').textContent).toBe('ATTTTT')
  })

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


it('bounds junction indexing per table operation and highlights existing rows by identity', () => {
  Element.prototype.scrollIntoView = vi.fn()
  const { design, strand } = junctionFixture()
  design.strands = Array.from({ length: 40 }, (_, i) => ({ ...strand, id: 's' + i }))
  const crossovers = design.crossovers
  let reads = 0
  Object.defineProperty(design, 'crossovers', { get() { reads++; return crossovers } })
  sheet.update(design)
  expect(reads).toBeLessThan(10)
  reads = 0
  const row = document.querySelector('tr[data-strand-id="s20"]')
  sheet.setSelectedStrands(['s20'])
  expect(reads).toBe(0)
  expect(row.classList.contains('sheet-selected')).toBe(true)
  reads = 0
  sheet.setSelectedStrands(['s20'], [{ kind: 'domain', strandId: 's20', domainIndex: 1 }])
  expect(reads).toBeLessThan(10)
  expect(document.querySelectorAll('.sheet-seq-selected-base')).toHaveLength(3)
  // A new table operation must observe in-place junction edits, not stale global caches.
  crossovers[0].extra_bases = 'CC'
  sheet.update(design)
  expect(document.querySelector('tr[data-strand-id="s20"] .sheet-seq-extra').textContent).toBe('CC')
})


it('updates only changed sequence rows and retains unrelated edits and row order', () => {
  Element.prototype.scrollIntoView = vi.fn()
  const { design, strand } = junctionFixture()
  design.strands.push({ ...strand, id: 'other' })
  sheet.update(design)
  const row = id => document.querySelector(`tr[data-strand-id="${id}"]`)
  const before = row('s'), other = row('other'), originalOrder = [...other.parentNode.children].map(r => r.dataset.strandId)
  const ref = [{ kind: 'domain', strandId: 's', domainIndex: 1 }]
  sheet.setSelectedStrands(['s'], ref)
  expect(row('other')).toBe(other)
  expect(row('s')).toBe(before)
  expect(row('s').querySelectorAll('mark')).toHaveLength(3)
  const selected = row('s')
  sheet.setSelectedStrands(['s'], ref)
  expect(row('s')).toBe(selected)
  sheet.setSelectedStrands(['other'])
  expect(row('other')).toBe(other)
  expect(row('s').querySelector('mark')).toBeNull()
  expect([...other.parentNode.children].map(r => r.dataset.strandId)).toEqual(originalOrder)
})

it('initializes safely when the spreadsheet was already open in the previous session', () => {
  localStorage.setItem('editor_spreadsheet_open', 'true')
  expect(() => initStrandsSpreadsheet()).not.toThrow()
})
