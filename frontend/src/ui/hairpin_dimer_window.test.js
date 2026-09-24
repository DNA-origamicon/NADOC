// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'

import {
  openHairpinDimerWindow,
  openStrandHairpinDimerWindow,
  prependStrandWarningIcon,
} from './hairpin_dimer_window.js'
import { buildHairpinDimerIndex } from './hairpin_dimer_report.js'
import { makeDesign, makeReport, makeWarningReport } from '../test-helpers/hairpin_dimer_fixture.js'

afterEach(() => { document.body.innerHTML = '' })

const win = () => document.querySelector('.hd-window')

describe('hairpin/dimer structure window', () => {
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
