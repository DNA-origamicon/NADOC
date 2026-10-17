// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'

vi.mock('../api/overhang_endpoints.js', () => ({
  generateOverhangRandomSequence: vi.fn(), checkHairpinDimer: vi.fn(),
}))
import { generateOverhangRandomSequence, checkHairpinDimer } from '../api/overhang_endpoints.js'

import {
  openHairpinDimerWindow,
  openStrandHairpinDimerWindow,
  prependStrandWarningIcon,
} from './hairpin_dimer_window.js'
import { buildHairpinDimerIndex } from './hairpin_dimer_report.js'
import { makeDesign, makeReport, makeWarningReport } from '../test-helpers/hairpin_dimer_fixture.js'

afterEach(() => { document.body.innerHTML = '' })
beforeEach(() => vi.clearAllMocks())

const win = () => document.querySelector('.hd-window')

describe('hairpin/dimer structure window', () => {
  it.each(['direct', 'strand', 'badge'])('offers generation from the %s entry point and refreshes drawings', async (entry) => {
    const design = makeDesign(), report = makeReport()
    const check = report.checks[0]
    generateOverhangRandomSequence.mockResolvedValue({})
    checkHairpinDimer.mockResolvedValue({ ...report, checks: [{ ...check, hairpin: null, dimer: null, flagged: false }] })
    if (entry === 'direct') openHairpinDimerWindow({ checks: [check] })
    else if (entry === 'strand') openStrandHairpinDimerWindow(report, design, 's_a')
    else {
      const td = document.createElement('td')
      prependStrandWarningIcon(td, buildHairpinDimerIndex(report, design), 's_a', design, report)
      td.firstChild.click()
    }
    const button = win().querySelector('.hd-window__generate')
    expect(button.textContent).toBe('Generate new sequence')
    button.click()
    expect(button.disabled).toBe(true)
    await vi.waitFor(() => expect(button.disabled).toBe(false))
    expect(generateOverhangRandomSequence).toHaveBeenCalledExactlyOnceWith(check.overhang_ids[0])
    expect(win().querySelector('.hd-window__figure')).toBeNull()
    expect(win().textContent).toContain('No secondary structure above the screening threshold')
  })

  it('lets a linker user choose which overhang to regenerate', async () => {
    const design = makeDesign(), report = makeReport()
    generateOverhangRandomSequence.mockResolvedValue({})
    checkHairpinDimer.mockResolvedValue(report)
    openStrandHairpinDimerWindow(report, design, '__lnk__c1__s')
    const target = win().querySelector('.hd-window__generate-target')
    expect(target.options.length).toBe(2)
    expect([...target.options].map(o => o.textContent)).toEqual(['OH-A', 'OH-B'])
    target.value = report.checks[1].overhang_ids[0]
    win().querySelector('.hd-window__generate').click()
    await vi.waitFor(() => expect(checkHairpinDimer).toHaveBeenCalled())
    expect(generateOverhangRandomSequence).toHaveBeenCalledExactlyOnceWith(target.value)
  })

  it('does not reopen a dismissed window after generation completes', async () => {
    let resolve
    generateOverhangRandomSequence.mockReturnValue(new Promise(r => { resolve = r }))
    const modal = openHairpinDimerWindow({ checks: [makeReport().checks[0]] })
    win().querySelector('.hd-window__generate').click()
    modal.close()
    resolve({})
    await Promise.resolve()
    expect(win()).toBeNull()
    expect(checkHairpinDimer).not.toHaveBeenCalled()
  })

  it('shows each flagged structure with ΔG / Tm and the buffer', () => {
    const report = makeReport()
    openStrandHairpinDimerWindow(report, makeDesign(), 's_a', { title: 'S7 OH22' })
    expect(win().querySelector('.modal__title').textContent).toBe('S7 OH22 — secondary structure')
    expect(win().querySelector('.hd-window__subject').textContent).toBe('Overhang OH-A (22 nt)')
    const figs = win().querySelectorAll('.hd-window__figure')
    expect([...figs].map(f => f.className)).toEqual([
      'hd-window__figure hd-window__figure--hairpin', 'hd-window__figure hd-window__figure--self-dimer',
    ])
    expect(figs[0].querySelector('.hd-caption').textContent).toBe('ΔG = -12.51 kcal/mol · Tm = 96.6 °C')
    expect(win().querySelector('.hd-window__conditions').textContent)
      .toBe('Tm > 30 °C amber, > 50 °C red · 10 mM Mg²⁺, 0 mM Na⁺, 200 nM oligo · ΔG at 37 °C · primer3')
    // Both structures of OH-A are above 50 °C → red captions.
    expect([...win().querySelectorAll('.hd-window__caption')].map(c => c.textContent))
      .toEqual(['⚠ Hairpin — Tm > 50 °C', '⚠ Self-dimer — Tm > 50 °C'])
    expect(win().querySelector('.hd-window__caption--critical').style.color).toBe('rgb(248, 81, 73)')
  })

  it('an amber-tier structure gets an amber caption and badge', () => {
    const report = makeWarningReport(), design = makeDesign()
    openStrandHairpinDimerWindow(report, design, 's_a')
    const cap = win().querySelector('.hd-window__caption')
    expect(cap.textContent).toBe('⚠ Hairpin')
    expect(cap.classList.contains('hd-window__caption--warning')).toBe(true)
    const td = document.createElement('td')
    prependStrandWarningIcon(td, buildHairpinDimerIndex(report, design), 's_a', design, report)
    expect(td.querySelector('.hd-warn-icon--warning')).toBeTruthy()
  })

  it('keeps one window at a time and closes on Escape', () => {
    const report = makeReport()
    openStrandHairpinDimerWindow(report, makeDesign(), 's_a')
    openStrandHairpinDimerWindow(report, makeDesign(), '__lnk__c1__s')
    expect(document.querySelectorAll('.hd-window')).toHaveLength(1)
    expect(win().querySelector('.hd-window__subject').textContent).toBe('Linker strand (50 nt)')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(win()).toBeNull()
  })

  it('does nothing for an unflagged strand', () => {
    expect(openStrandHairpinDimerWindow(makeReport(), makeDesign(), 's_b')).toBeNull()
    expect(win()).toBeNull()
  })

  it('falls back to numbers when a hit carries no structure', () => {
    const check = { ...makeReport().checks[0], dimer: null, hairpin: { tm: 50, dg: -1, structure: [] } }
    openHairpinDimerWindow({ checks: [check] })
    expect(win().querySelector('.hd-window__figure').textContent).toContain('Tm 50 °C')
  })

  it('spreadsheet badge: clickable ⚠ that widens the ID cell', () => {
    const design = makeDesign(), report = makeReport()
    const idx = buildHairpinDimerIndex(report, design)
    const td = document.createElement('td'); td.textContent = 'S3'
    expect(prependStrandWarningIcon(td, idx, 's_a', design, report, { title: 'S3' })).toBe(true)
    expect(td.textContent).toBe('⚠S3')
    expect(td.style.maxWidth).toBe('none')
    expect(td.firstChild.title).toContain('hairpin Tm 96.6 °C')
    expect(td.firstChild.classList.contains('hd-warn-icon--critical')).toBe(true)
    td.firstChild.click()
    expect(win().querySelector('.modal__title').textContent).toBe('S3 — secondary structure')
    const plain = document.createElement('td')
    expect(prependStrandWarningIcon(plain, idx, 's_b', design, report)).toBe(false)
  })
})
