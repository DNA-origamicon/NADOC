// @vitest-environment jsdom
/** Hairpin/self-dimer ⚠ in the Overhang Connections panel: dropdown options, the
 *  per-side warning line, and the connection list rows. */
import { describe, it, expect, beforeAll } from 'vitest'

import { initOverhangConnectionsPanel } from './overhang_connections_panel.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds } from '../test-helpers/factory_dom.js'
import { OA, OB, makeDesign, makeReport } from '../test-helpers/hairpin_dimer_fixture.js'

const option = (selectId, value) =>
  [...document.getElementById(selectId).options].find(o => o.value === value)
const warnLines = () => [...document.querySelectorAll('.oconn-hd-warning')]

describe('overhang connections — hairpin/dimer warnings', () => {
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
    store = createMockStore({ currentDesign: makeDesign(), hairpinDimerReport: null })
    initOverhangConnectionsPanel({ store })
    document.getElementById('oconn-heading').dispatchEvent(new Event('click'))
    const a = document.getElementById('oconn-select-a'); a.value = OA; a.dispatchEvent(new Event('change'))
    const b = document.getElementById('oconn-select-b'); b.value = OB; b.dispatchEvent(new Event('change'))
  })

  it('shows nothing until a check has run', () => {
    expect(option('oconn-select-a', OA).textContent.startsWith('⚠')).toBe(false)
    expect(warnLines().every(el => el.hidden)).toBe(true)
    expect(document.querySelector('#oconn-list .hd-warn-icon')).toBeNull()
  })

  it('flags the overhang in both dropdowns and under its sequence row', () => {
    store.setState({ hairpinDimerReport: makeReport() })
    expect(option('oconn-select-a', OA).textContent).toMatch(/^⚠ OH-A/)
    expect(option('oconn-select-b', OA).textContent).toMatch(/^⚠ OH-A/)
    expect(option('oconn-select-a', OB).textContent).not.toContain('⚠')
    expect(option('oconn-select-a', OA).style.color).toBe('rgb(248, 81, 73)')   // > 50 °C → red
    const [lineA, lineB] = warnLines()
    expect(lineA.hidden).toBe(false)
    expect(lineA.style.color).toBe('rgb(248, 81, 73)')
    expect(lineA.textContent).toBe('⚠ hairpin Tm 96.6 °C · self-dimer Tm 67.8 °C')
    expect(lineA.title).toContain('Overhang OH-A (22 nt)')
    expect(lineB.hidden).toBe(true)
  })

  it('marks the connection row when its linker strand is flagged', () => {
    const row = document.querySelector('#oconn-list [data-conn-id="c1"]')
    const icon = row?.querySelector('.hd-warn-icon')
    expect(icon?.title).toContain('Linker strand (50 nt): hairpin Tm 90.2 °C')
    icon.click()
    const figs = [...document.querySelectorAll('.hd-window .hd-window__figure')]
    expect(figs.map(f => f.className.split('--')[1])).toEqual(expect.arrayContaining(['hairpin', 'self-dimer']))
    document.querySelector('.hd-window .modal__close').click()
  })

  it('clicking the warning line opens that overhang\'s structure window', () => {
    warnLines()[0].click()
    expect(document.querySelector('.hd-window .modal__title').textContent).toBe('OH-A — secondary structure')
    expect(document.querySelector('.hd-window .hd-window__subject').textContent).toBe('Overhang OH-A (22 nt)')
    expect(document.querySelector('.hd-window__conditions').textContent).toContain('10 mM Mg²⁺, 0 mM Na⁺, 200 nM oligo')
    document.querySelector('.hd-window .modal__close').click()
  })

  it('clears when the flagged overhang is re-sequenced', () => {
    const d = makeDesign()
    d.overhangs = d.overhangs.map(o => (o.id === OA ? { ...o, sequence: 'T'.repeat(22) } : o))
    store.setState({ currentDesign: d })
    expect(option('oconn-select-a', OA).textContent.startsWith('⚠')).toBe(false)
    expect(warnLines().every(el => el.hidden)).toBe(true)
    expect(document.querySelector('#oconn-list .hd-warn-icon')).toBeNull()
  })
})
